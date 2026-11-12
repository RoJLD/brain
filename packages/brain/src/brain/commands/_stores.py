"""The passes over a project's stores that sync, check and refresh share: each store synced or checked, the
registry's check, the marks the merge driver leaves (brain.commands).

A project that shares its root with the one registered there first (brain.projects) gets its stores' passes only:
research_graph with its layout (its views beside its store, its own decision logs), its specs, its features' statuses,
its module map. The root's own passes are its owner's: the records and their view, the decision queue and the
defaults, the rendered marketplace and AGENTS.md, the links graph and FEATURES.md, the public gate, the engine's skew,
the session ids and the hygiene line."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from .. import (alerts, bundles, classes, codeindex, config, crossstore, decisions, defaults, docsgraph, features,
                gates, graph, links, lint, markers, milestones, modulemap, modules, neutral, permissions, projects,
                public, readme, records, reference, render, scopes, sizing, skew, specs, stacks, tidy, tiers, vault,
                views, waves)
from ..inventory import AuditError
from ._common import _now, _on_main, _project, _queue_changed, _repos, _scope, _store_label
from .features import _features_view
from .record import cmd_record_check


def _module_view(project: projects.Project, root: Path, store: Path) -> str:
    """The module map's view of ``store``, relative to ``root``: beside the store's other views (brain.projects)."""
    folder = projects.views_dir(project, store)
    return _store_label(root, folder / modules.FILE)


def _module_warnings(project: projects.Project, root: Path, store: Path, stale: views.Stale) -> list[str]:
    """brain check's lines on the module map: an open item it does not place, a feature or a done item with no module
    (wi-brain-module-backfill), an imported entry's fields (wi-brain-module-registry-import); its view, when stale,
    joins ``stale``. A store without a registry of its own reads the one config.json modules.store names; a key that
    names none is a warning here."""
    if not modules.applies(store, root):
        wanted = modules.named(root, store)
        return [f"module map: config.json modules.store {wanted!r} names no store of the registry that keeps "
                f"{modules.REGISTRY}"] if wanted else []
    view = _module_view(project, root, store)
    if modules.stale(root, store, _store_label(root, store), view):
        stale.add(view, "brain sync (or brain modules --write)")
    found = modules.registry_problems(store, root) + modulemap.problems(store, root) + modules.problems(store, root)
    return [f"module map: {line}" for line in found + modules.warnings(store, root) + modulemap.warnings(store, root)]


def _write_module_view(project: projects.Project, root: Path, store: Path) -> None:
    view = _module_view(project, root, store)
    if modules.applies(store, root) and modules.write(root, store, _store_label(root, store), view):
        print(f"view: {view} written")


def _reference_applies(project: projects.Project, root: Path, store: Path) -> bool:
    """Whether brain sync and check keep docs/reference/ current for ``store``: the project's first store, and a
    folder that holds the project's own render (the owner's opt-in, brain reference --write; never a public one)."""
    return projects.uses_defaults(project, store) and reference.private_render(root / reference.DIR)


def _reference_prose_check(project: projects.Project, root: Path, store: Path) -> int:
    """brain check: the reference's prose (docs/reference.yaml) holds its required fields, once the reference is kept
    (1 on an error, as the README's YAML)."""
    if not _reference_applies(project, root, store):
        return 0
    errors = reference.load_prose(root)[1]
    for e in errors:
        print(f"error: {e} (schemas/reference.schema.json; then brain reference --write)")
    return 1 if errors else 0


def _write_reference(project: projects.Project, root: Path, store: Path) -> None:
    """docs/reference/ written again (brain.reference) once the owner opted in: a brain without it gets none."""
    if _reference_applies(project, root, store):
        if reference.load_prose(root)[1]:   # never over the last good render: brain check says why
            print(f"warning: {reference.YAML} breaks its schema: {reference.DIR} not written (brain check)")
            return
        changed, kept = reference.write(root / reference.DIR, reference.render(root, store, _store_label(root, store)))
        if changed:
            print(f"view: {reference.DIR} written ({len(changed)} file(s))")
        for p in kept:
            print(f"warning: {reference.DIR}/{p} is not generated: kept, not overwritten")


def _plan_view(project: projects.Project, root: Path, store: Path) -> str:
    """The plan's view of ``store`` (eras, milestones, waves), relative to ``root``: beside the store's other views."""
    return _store_label(root, projects.views_dir(project, store) / waves.FILE)


def _write_plan_view(project: projects.Project, root: Path, store: Path) -> None:
    """brain sync, its one writer: the plan view of a store that holds a wave or an era (brain.waves)."""
    view = _plan_view(project, root, store)
    if waves.applies(store) and waves.write(root, store, view):
        print(f"view: {view} written")


def _plan_checks(project: projects.Project, root: Path, store: Path, stale: views.Stale) -> int:
    """brain check's lines on the waves and eras: errors (1) and warnings; the view, when stale, joins ``stale``."""
    if not waves.applies(store):
        return 0
    plan = waves.load(store, root)
    errors = waves.problems(plan)
    for line in errors:
        print(f"error: plan: {line}")
    for line in waves.warnings(plan):
        print(f"warning: plan: {line}")
    view = _plan_view(project, root, store)
    if waves.stale(root, store, view):
        stale.add(view)
    return 1 if errors else 0


def _view_clash(args, project: projects.Project, root: Path, store: Path) -> str:
    """What to say when an earlier store at this root writes its views in this store's folder, else '' (computed once
    per command)."""
    clashes = getattr(args, "_view_clashes", None)
    if clashes is None:
        clashes = args._view_clashes = projects.view_clashes(projects.holders(root))
    return clashes.get((project.name, _store_label(project.root, store)), "")


def _docs_view(project: projects.Project, root: Path, store: Path) -> str:
    """The documentation graph's view of ``store``, relative to ``root``: beside the store's other views."""
    return _store_label(root, projects.views_dir(project, store) / docsgraph.FILE)


def _docs_catalogue(project: projects.Project, root: Path, store: Path) -> docsgraph.Catalogue:
    """The documentation graph of ``store`` (brain.docsgraph): the root's repo, the project's other checkouts here."""
    try:
        cfgs = projects.repos_of(project)
    except projects.RepoError:
        cfgs = []
    own = next((c.name for c in cfgs if c.path.resolve() == root.resolve()), projects._repo_folder(root).lower())
    return docsgraph.catalogue(root, store, own, links.anchor_roots(cfgs, own))


def _write_docs_view(project: projects.Project, root: Path, store: Path) -> None:
    """brain sync, its one writer: the documentation graph of a store whose links graph is written."""
    if docsgraph.applies(store):
        view = _docs_view(project, root, store)
        if docsgraph.write(root, view, docsgraph.render(_docs_catalogue(project, root, store))):
            print(f"view: {view} written")


def _docs_checks(project: projects.Project, root: Path, store: Path, stale: views.Stale) -> list[str]:
    """brain check's warnings on the documentation graph: a declared link without its reason or not between two
    docs, the docs to re-read (doc.stale, one line per doc); its view, when stale, joins ``stale``."""
    if not docsgraph.applies(store):
        return []
    cat = _docs_catalogue(project, root, store)
    view = _docs_view(project, root, store)
    if docsgraph.is_stale_view(root, view, docsgraph.render(cat)):
        stale.add(view)
    by_doc: dict[str, int] = {}
    for d in cat.docs.values():
        if d.stale:
            by_doc[d.path if d.repo == cat.repo else f"{d.repo}: {d.path}"] = len(d.stale)
    return cat.warnings + [f"doc.stale: {name}: {n} section(s) to re-read (a cited node or a declared parent changed "
                           f"after its last commit; {view})" for name, n in sorted(by_doc.items())]


def _store_checks(project: projects.Project, root: Path, store: Path, stale: views.Stale) -> int:
    """The checks of the store itself, whichever project at the root it belongs to: milestones, the waves and eras
    (1 on an error), the module map, the specs ready to turn active, the hard-rule ratio; its stale views join
    ``stale``."""
    for line in milestones.orphan_lines(store, root):
        print(line)
    for line in sizing.check_lines(store):   # every item written since the rule has a size (wi-brain-item-size)
        print(line)
    for line in gates.check_lines(store, project.registry_dir):   # gates as data (wi-brain-forecast-gates)
        print(line)
    rc = _plan_checks(project, root, store, stale)
    for line in _module_warnings(project, root, store, stale):   # every open item has its module (wi-brain-module-map)
        print(f"warning: {line}")
    for line in _docs_checks(project, root, store, stale):   # the docs to re-read (wi-brain-docs-graph)
        print(f"warning: {line}")
    for r in specs.readiness(root, store):
        if r.ready:
            print(f"warning: spec {r.id} is ready to turn active (closed by {r.closed_by()}): brain refresh, or "
                  "brain spec activate --write")
    hard = lint.hard_rules(store)
    if hard and hard["edge_type"]:  # the hard-rule ratio; a soft rule is a warning, never an error
        print("\n".join(lint.render_hard(hard)))
    return rc


def _shared_line(project: projects.Project) -> str:
    return (f"{project.name} shares its root with {project.shares_root_with}: the root's records, decision queue, "
            f"rendered files, links and FEATURES.md are {project.shares_root_with}'s")


def _records_view(root: Path, store: Path) -> bool:
    """The records' graph view applies to a project with records/ and DDR nodes in its schema."""
    return (root / records.RECORDS_DIR).is_dir() and "DDR" in (graph.load_schema(store).get("node_types") or [])


def _links_repo(args, root: Path) -> tuple[str, projects.Repo | None, list[projects.Repo]]:
    """(name, registry entry) of the repo at ``root``, whose store takes the Doc, Test and Workflow links, and the
    project's repos (the others a CodeRef of the store names are derived into it too)."""
    try:
        cfgs = projects.repos_of(_project(args, root))
    except projects.RepoError:
        cfgs = []
    for c in cfgs:
        if c.path.resolve() == root.resolve():
            return c.name, c, cfgs
    return projects._repo_folder(root).lower(), None, cfgs


def _activate_specs(args, root: Path, store: Path) -> int:
    """The proposed specs whose decisions are all taken and applied, with no thinking phase left, turned active
    (brain.specs; before the graph sync: the kanban and the queue view read the statuses)."""
    try:
        for node in specs.activate(store, specs.readiness(root, store), via=f"brain {args.cmd}"):
            print(f"spec {node['id']}: turned active (closed by {node['props']['activated_by']})")
    except graph.GraphError as exc:
        print(f"brain: specs not activated: {exc}", file=sys.stderr)
        return 1
    return 0


def _take_defaults(root: Path) -> bool:
    """The low-stakes defaults due now, taken (24 h without an answer: brain.defaults), before any view is written:
    the records' graph and the kanban then show those DDRs answered. False when the project has no DDR."""
    if not (root / records.RECORDS_DIR / "ddr").is_dir():
        return False
    for ddr_id in defaults.finalize(root, _now()):
        print(f"{ddr_id}: taken by default (brain decision defaulted)")
    return True


def _sync_store(args, root: Path, store: Path) -> int:
    project = _project(args, root)
    owner = not project.shares_root_with   # the root's own passes are its owner's
    layout = projects.layout(project, store)   # its views beside its store, its own decision logs
    clash = _view_clash(args, project, root, store)
    if clash:   # its board would be written over another store's: nothing written
        print(f"error: {clash}: not synced")
        return 1
    if _activate_specs(args, root, store):
        return 1
    if not owner:   # a project that shares the root: its store's passes only, never the root's defaults or views
        rc = _sync_graph(args, project, root, store, layout, owner=False)
        if rc:
            return rc
        print(_shared_line(project))
        _write_module_view(project, root, store)
        _write_plan_view(project, root, store)
        return graph.research_graph(root, store, *layout, "kanban", "--write")
    ddrs = _take_defaults(root)
    queued = []
    try:
        return _sync_views(args, project, root, store, layout, ddrs, queued)
    finally:
        if ddrs and not queued:   # a view step failed after the defaults were taken: the queue view still shows them
            _queue_changed(root, args)


def _sync_graph(args, project: projects.Project, root: Path, store: Path, layout: list[str], *, owner: bool) -> int:
    """The features' statuses (before the graph sync: it reads them), then the graph sync with the store's layout; 0,
    else the failing code. An edge of a store listed after its project's first may name a decision stub that first
    store derives: research_graph resolves it there (brain.crossstore, wi-brain-shared-root-stub-rule-drop)."""
    if features.has_type(graph.load_schema(store)) and not getattr(args, "offline", False):
        repos = [(c.name, c.path) for c in _repos(args, root) if c.path.is_dir()]
        if not repos and not owner:   # a project that spans no repo: its features are named by the root's PRs
            repos = [(projects._repo_folder(root).lower(), root)]
        features.sync_prs(store, repos)
    return graph.research_graph(root, store, *layout, "sync", "--write")


def _graph_views(args, root: Path, store: Path) -> int:
    """The records' graph and the links graph, after the graph sync; 1 when the links graph cannot be written."""
    if _records_view(root, store):
        n, e, left = records.write_graph(root, store)
        print(f"records graph: {n} node(s), {e} edge(s)" + (f", {left} link(s) to nodes not in the store"
                                                             if left else ""))
    if links.applies(store):
        try:
            n, e, missing = links.write(root, store, *_links_repo(args, root))
            print(f"links graph: {n} node(s), {e} edge(s)" + (f"; not on this machine, left out: {', '.join(missing)}"
                                                             if missing else ""))
        except AuditError as exc:
            print(f"brain: links graph not written: {exc}", file=sys.stderr)
            return 1
    return 0


def _sync_views(args, project: projects.Project, root: Path, store: Path, layout: list[str], ddrs: bool,
                queued: list) -> int:
    """The views the root's owner writes after the defaults are taken; ``queued`` is set once the queue view is."""
    rc = _sync_graph(args, project, root, store, layout, owner=True)
    if rc:
        return rc
    if _graph_views(args, root, store):
        return 1
    if features.has_type(graph.load_schema(store)) and _features_view(args, root, store, write=True):
        return 1   # after the links: FEATURES.md shows them
    _write_module_view(project, root, store)
    _write_plan_view(project, root, store)
    _write_docs_view(project, root, store)   # after the links graph: its Doc nodes and documented_in edges
    _write_reference(project, root, store)
    if scopes.view_applies(root) and scopes.write_view(root):   # a brain's own root, once a tree is declared
        print(f"view: {scopes.VIEW} written")
    if ddrs:
        _queue_changed(root, args)
        queued.append(True)
    if neutral.applies(root) and render.main(root, "claude", do_write=True):   # the marketplace from the source
        return 1
    for line in render.keep_current(root, project.name, fix=True):   # AGENTS.md and the like, here
        print(line)
    return graph.research_graph(root, store, *layout, "kanban", "--write")


def _check_markers(project: projects.Project, root: Path, store: Path) -> int:
    """1 when the store, a journal, a decision log or a record holds a conflict marker (brain.markers;
    wi-brain-guard-conflict-markers): every brain command loads them, and a stale merge's generated views pass the
    graph check. The records are the root's: its owner's to scan."""
    files = [store, *(project.journals or [project.journal]), *(project.decision_logs or [project.decisions]),
             *([] if project.shares_root_with else [root / records.RECORDS_DIR])]
    hits = markers.scan_files([f for f in files if f])
    for hit in hits:
        print(f"error: {hit} holds a conflict marker: finish the merge in that file, then brain refresh")
    return 1 if hits else 0


def _readme_checks(args, project: projects.Project, root: Path, store: Path) -> tuple[list[str], list[str]]:
    """The generated READMEs of the project's opted-in repos (a checkout with readme.yaml, brain.readme), once per
    project (from its first store): (errors, stale ones). The errors are printed here (readme.yaml invalid, a quoted
    command gone); a stale README is a stale view, the default branch's to hold fresh. ([], []) for a project with no
    readme.yaml anywhere: nothing is read."""
    if not projects.uses_defaults(project, store):
        return [], []
    from . import docs  # here: brain.commands.docs imports this module's package
    every = argparse.Namespace(**{**vars(args), "repo": "", "dir": ""})   # brain check's --repo is --public's
    try:
        if not [t for t in docs.targets(every, root) if readme.applies(t[1])]:
            return [], []
        errors, stale = docs.problems(every, root, config.load(root))
    except (SystemExit, readme.ReadmeError, graph.GraphError, OSError, ValueError) as exc:
        errors, stale = [f"the generated READMEs could not be checked: {exc}"], []
    for line in errors:
        print(f"error: {line}: brain docs check")
    return errors, stale


def _check_store(args, root: Path, store: Path) -> int:
    project = _project(args, root)
    if _check_markers(project, root, store):   # every later step would read a half-merged file
        return 1
    layout = projects.layout(project, store)
    clash = _view_clash(args, project, root, store)
    if clash:
        print(f"error: {clash}")
    rc = 1 if clash else 0
    where, stale, legacy = views.place(root), views.Stale(), {}
    strict = views.strict(root)   # config.json views.strict: a stale view fails the default branch's check
    if getattr(args, "views_as_default", False):   # brain views --write: its check is the default branch's, strict
        where, strict = views.as_default(where), True
    if project.shares_root_with:   # its store's checks only: the root's are its owner's
        print(_shared_line(project))
        rc = _store_checks(project, root, store, stale) or rc
        rc = _views_verdict(project, root, store, where, stale, legacy, strict) or rc
        return graph.research_graph(root, store, *layout, "check") or rc
    rc = (cmd_record_check(args, root) if (root / records.RECORDS_DIR).is_dir() else 0) or rc
    if decisions.view_stale(root, _project(args, root).name):
        stale.add(decisions.VIEW, "brain sync (or brain decision view --write)")
    roots: dict[str, Path] = {}   # the other repos' checkouts, where research_graph reads their nodes' anchors
    if links.applies(store):
        name, cfg, cfgs = _links_repo(args, root)
        roots = links.anchor_roots(cfgs, name)
        try:
            for f in links.stale(root, store, name, cfg, cfgs):
                path = _store_label(root, store / f)
                legacy[path] = f   # an earlier engine's warning named it from the store
                stale.add(path)
        except AuditError as exc:
            print(f"warning: the links graph could not be checked: {exc}")
    rc = _store_checks(project, root, store, stale) or rc
    readmes = _readme_checks(args, project, root, store)   # opt-in: a repo with readme.yaml (wi-brain-readme-sync)
    rc = (1 if readmes[0] else 0) or rc
    rc = _reference_prose_check(project, root, store) or rc   # docs/reference.yaml (wi-brain-reference-arc42)
    if where.where == "default":   # the views only the default branch must hold fresh (brain.views)
        if _records_view(root, store):
            for f in records.graph_stale(root, store):
                stale.add(_store_label(root, store / f))
        if features.has_type(graph.load_schema(store)) and _features_stale(args, root, store):
            stale.add(features.VIEW, "brain features render --write")
        if _reference_applies(project, root, store):   # opt-in: brain reference --write
            for f in reference.stale(root / reference.DIR, reference.render(root, store, _store_label(root, store))):
                stale.add(f"{reference.DIR}/{f}", "brain sync (or brain reference --write)")
        for line in readmes[1]:
            stale.add(line.split(":", 1)[0] + ":" + readme.VIEW, "brain docs render --write")
    rc = _views_verdict(project, root, store, where, stale, legacy, strict) or rc
    for line in skew.check_lines(root):   # the running engine against config.json engine.pin
        print(line)
    rc = _check_session_ids(root) or rc   # a DDR's local_ id that matches no session (scale study gap 19)
    rc = _check_identity(root, project.name) or rc   # members.yaml and the owner's signed answers (brain.identity)
    if neutral.applies(root):   # the marketplace is the source's render: a hand edit fails here
        rc = render.main(root, "claude", check=True) or rc
    gate_rc, lines = public.gate(root)   # boundary.yaml: every file has a side, the engine side holds nothing private
    for line in lines:
        print(line)
    rc = gate_rc or rc
    for line in render.keep_current(root, project.name, fix=False):   # a stale AGENTS.md: brain sync
        print(f"warning: {line}")
    line = tidy.hygiene(project)   # stale worktrees and merged branches: brain tidy
    if line:
        print(line)
    given = [a for n, p in sorted(roots.items()) for a in ("--repo-path", f"{n}={p}")]
    return graph.research_graph(root, store, *layout, "check", *given) or rc


def _features_stale(args, root: Path, store: Path) -> bool:
    """Whether the root's FEATURES.md exists and is not the render of the store's Feature nodes."""
    from ._common import _root_repo
    target = root / features.VIEW
    if not target.is_file():
        return False
    repo = _root_repo(args, root).lower()
    want = features.render(features.load_store(store, _root_repo(args, root)), repo, _store_label(root, store))
    return bool(features.check_view(target.read_text(encoding="utf-8"), want))


def _views_verdict(project: projects.Project, root: Path, store: Path, where: views.Place, stale: views.Stale,
                   legacy: dict[str, str], strict: bool = False) -> int:
    """The stale views of a store's check said by where the checkout stands (brain.views): on the default branch
    (with the board and the roadmap, measured there only) an error under ``strict`` (config.json views.strict, or the
    one writer's own check), else a warning naming the writer; a ``views:`` line on another branch, the warnings
    outside git; 1 on the default branch when one is stale under ``strict``."""
    if where.where == "default":
        folder = _store_label(root, projects.views_dir(project, store))
        for path in graph.board_stale(root, store, folder):
            stale.add(path, "brain sync (research_graph kanban --write)")
    rc, lines = views.verdict(stale, where, legacy, strict)
    for line in lines:
        print(line)
    return rc


def _check_session_ids(root: Path) -> int:
    """1 when a DDR stamped on this machine names an app id (local_) that matches no session (brain.sessions)."""
    if not (root / records.RECORDS_DIR / "ddr").is_dir():
        return 0
    from .. import sessions
    refused, warned = sessions.unknown_ids(decisions.load(root))
    for line in refused:
        print(f"error: {line}")
    for line in warned:
        print(f"warning: {line}")
    return 1 if refused else 0


def _check_identity(root: Path, project: str) -> int:
    """1 when members.yaml or an owner-decides answer's signature fails under config.json identity.require_signed;
    the same findings are warnings without it, and nothing is said without members.yaml (brain.identity)."""
    from .. import identity
    errors, warnings = identity.check(root, project)
    for line in errors:
        print(f"error: identity: {line}")
    for line in warnings:
        print(f"warning: identity: {line}")
    return 1 if errors else 0


def _merge_marks(root: Path, then: str, clear: bool = False) -> None:
    """The views the merge driver kept from one side in this worktree (brain.mergedriver): said, or cleared once
    brain refresh regenerated them."""
    from .. import mergedriver
    views = mergedriver.clear(root) if clear else mergedriver.marked(root)
    if views:
        print(f"merge driver: {len(views)} view(s) kept from one side at the last merge ({', '.join(views)}); {then}")


def check_registry(root: Path | None, projs: list[projects.Project], every: bool = False) -> int:
    """The registry (its keys and shapes, repos, stacks, code_index), its alerts and config.json (brain.config),
    then the ids: unique across every store of every project, unless waived under a project's shared_ids; then the
    edges between stores (brain.crossstore): one whose end is in no store is an error with ``every`` (check --all,
    which checks every store: that store's own check refuses it too), else a warning. The projects the brain reads
    and never writes are counted. Exit code 1 on an error."""
    errors = projects.check(root) + config.check(root) + permissions.check(root)
    from .. import plugins
    from . import _registry
    errors += plugins.check(root, _registry.register_all(argparse.ArgumentParser().add_subparsers(),
                                                         _registry.Context("", "")))
    data_classes = classes.check(root)
    for n in data_classes.home_notes:   # an engine store undeclared takes its default class: noted, never failed
        print(f"note: classes: {n}")
    for w in data_classes.waived:
        print(f"waived: classes: {w}")
    errors += [f"classes: {e}" for e in data_classes.errors] + [f"vault: {e}" for e in vault.check(root)]
    errors += [f"tiers: {e}" for e in tiers.check(root)]
    errors += _scopes_check(root)
    errors += [f"alerts: {e}" for e in alerts.check(projects.load(root))]
    from .. import schedule
    errors += [f"schedules: {e}" for e in schedule.check(projects.load(root))]
    for what, load, error in (("stacks", stacks.load, stacks.StackError),
                              ("code_index", codeindex.load, codeindex.CodeIndexError)):
        try:
            load(root)
        except error as exc:
            errors.append(f"{what}: {exc}")
    errors += _bundles_check(root)
    ids = projects.collisions([p for p in projs if p.root.is_dir()])
    for c in ids["collisions"]:
        line = f"id {c['id']} is in {', '.join(c['where'])}"
        if c["waived"]:
            print(f"waived: {line} (shared_ids of {c['waived']})")
        else:
            errors.append(f"{line} (rename one, or waive it under shared_ids: with its reason)")
    for s in ids["stale"]:
        print(f"warning: shared_ids of {s}: no longer in two stores (remove it)")
    errors += _cross_store(projs, every)
    errors += _unregistered_code_refs(root, projs, every)
    for line in _moved_names(root):
        print(f"warning: moved: {line}")
    for line in render.registry_warnings(neutral.brain_root(root), projs) + _uncloned(root):
        print(f"warning: {line}")
    for e in errors:
        print(f"error: {e}")
    read_only = len(projects.readonly(root))
    print(f"registry: {len(projs)} project(s), {ids['stores']} store(s), "
          + (f"{len(errors)} error(s)" if errors else "ids unique") + (f"; {read_only} read only" if read_only else ""))
    return 1 if errors else 0


def _scopes_check(root: Path | None) -> list[str]:
    """The scope tree's errors (brain.scopes), its warnings printed; its generated view stale is a warning (brain
    sync writes it). Nothing for a brain without a tree."""
    errors, warnings = scopes.check(root)
    if root is not None and not errors and scopes.view_applies(root) and scopes.view_stale(root):
        warnings.append(f"{scopes.VIEW} is stale (brain sync writes it)")
    for w in warnings:
        print(f"warning: scopes: {w}")
    return [f"scopes: {e}" for e in errors]


def _cross_store(projs: list[projects.Project], every: bool) -> list[str]:
    """The edges between the registry's stores, said; the dangling ones returned as errors with ``every``, else
    warned (brain.crossstore)."""
    rep = crossstore.check([p for p in projs if p.root.is_dir()])
    if rep.cross:
        print(f"cross-store edges: {len(rep.cross)} (an edge's end held by another store of the registry)")
    for line in rep.dangling if not every else []:
        print(f"warning: edge {line} (its store's check refuses it)")
    return [f"edge {line}" for line in rep.dangling] if every else []


def _moved_names(root: Path | None) -> list[str]:
    """The brain's instructions, memory notes, skills and scripts that name a prefix config.json's table of moves says
    moved (brain.moves, wi-brain-moved-paths): warnings, with the new prefix."""
    from .. import moves
    cfg = config.load(root)
    table = moves.table(cfg)
    top = Path(root) if root is not None else cfg.root   # the brain checked, as the rest of its registry check
    if not table:
        return []
    try:
        out = subprocess.run(["git", "-C", str(top), "ls-files", "-z"], capture_output=True, timeout=60,
                             stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        out = None
    if out is None or out.returncode:
        return [f"not checked: {top} is not a git checkout (its tracked files are what is read)"]
    return moves.scan_root(Path(top), [t for t in out.stdout.decode("utf-8", "replace").split("\0") if t], table)


def _unregistered_code_refs(root: Path | None, projs: list[projects.Project], every: bool) -> list[str]:
    """The active CodeRefs of the registry's stores whose repo no project registers
    (wi-brain-audit-unregistered-coderef): errors with ``every`` (check --all), else warned. brain audit reports
    them as coderef.dangling (P0); nothing would measure them otherwise."""
    from ..inventory import parse_code_ref
    known = projects.repo_tokens(root)
    found, read = [], set()
    for p in projs:
        for store in p.stores:
            key = projects._norm(store)
            if key in read or not (store / "nodes").is_dir():
                continue
            read.add(key)
            for cid, status in projects.code_refs(store):
                try:
                    repo = parse_code_ref(cid)[0]
                except ValueError:
                    continue   # malformed: the store's own check refuses it
                if status == "active" and repo.lower() not in known:
                    found.append(f"CodeRef {cid} ({p.name}): its repo {repo} is in no project's repos: (register "
                                 "it, point the CodeRef at a registered repo, or retire it)")
    for line in found if not every else []:
        print(f"warning: {line}")
    return found if every else []


def _uncloned(root: Path | None) -> list[str]:
    """The registered projects whose stacks this machine cannot read (their root is elsewhere): said, not failed."""
    return [f"stacks of project {n}: its root is not on this machine, not checked here" for n in stacks.uncloned(root)]


def _bundles_check(root: Path | None) -> list[str]:
    """Each bundle the engine ships, rendered with the components the registry declares: what would block its apply
    (a registry that does not load is said by the stacks' own check)."""
    try:
        reg = stacks.load(root)
    except stacks.StackError:
        return []
    shipped = bundles.names()
    unknown = [f"stack {s.name} ({s.project}): bundle {s.bundle!r} is not one the engine ships (shipped: "
               f"{', '.join(shipped) or 'none'})" for s in reg.values() if s.bundle and s.bundle not in shipped]
    return unknown + [f"bundle {b}: {e}" for b in shipped for e in _bundle_problems(reg, b)]


def _bundle_problems(reg: dict, bundle: str) -> list[str]:
    """What blocks ``brain bundle apply`` of ``bundle`` with this registry's components (none declared: nothing)."""
    comps = bundles.components(reg, bundle)
    if not comps:
        return []
    doc, _ = bundles.render(bundle, comps)
    tiers_off = [f"component {s.name} is of tier class {s.tier['class']!r}: a bundle's component is a service "
                 "(class: service, with its fallback)" for s in comps if s.tier.get("class", "service") != "service"]
    return bundles.problems(bundle, doc, comps)[1] + tiers_off


def _registry_too(args, root: Path | None) -> bool:
    """--all, or a brain's own root (its neutral source): the registry, config.json, the classes, the permissions, the
    stacks and bundles, the ids are checked too (brain refresh in a brain checks its own data, wi-brain-test-split)."""
    return bool(getattr(args, "all", False) or (root is not None and neutral.applies(root)))


def _registry_scope(root: Path | None) -> list[projects.Project]:
    """The projects whose stores the registry check reads the ids of: every registered one, with --all or without
    (a shared_ids waiver names an id another project holds), those not on this machine skipped by the check."""
    return list(projects.load(root).values())


def _each_store(args, root: Path, *, sync: bool, check: bool, written_on_main: bool = False,
                scope: list[projects.Project] | None = None) -> int:
    """sync and/or check each store of each project in scope (refresh, sync --all, check --all, and sync or check at a
    root several projects share); a main checkout on main or master is not written unless --on-main (or
    ``written_on_main``: a plain sync writes there, as for one project); --all with check ends with check_registry."""
    failed = []
    scope = scope if scope is not None else _scope(args, root, root_shared=True)
    for p in scope:
        args.project_obj = p
        if not p.root.is_dir():
            print(f"== {p.name}: {p.root} not found, skipped")
            continue
        on_main = getattr(args, "on_main", False) or written_on_main
        branch = "" if on_main or not sync else _on_main(p.root)
        for store in projects.stores_of(p):
            if not (store / "schema.yaml").is_file():
                print(f"== {p.name}: no store at {store}, skipped")
                continue
            if branch and not check:
                print(f"== {p.name}: {store} (main checkout on {branch}: not written, skipped)")
                continue
            print(f"== {p.name}: {store}" + (f" (main checkout on {branch}: check only)" if branch else ""))
            rc = 0 if branch or not sync else _sync_store(args, p.root, store)
            rc = rc or (_check_store(args, p.root, store) if check else 0)
            if rc:
                failed.append(p.name)
    if check and _registry_too(args, root):
        print("== registry")
        if check_registry(root, _registry_scope(root), every=bool(getattr(args, "all", False))):
            failed.append("registry")
    print(f"{args.cmd}: {len(failed)} project(s) failed" + (f": {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0
