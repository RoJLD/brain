"""The passes over a project's stores that sync, check and refresh share: each store synced or checked, the
registry's check, the marks the merge driver leaves (brain.commands)."""

from __future__ import annotations

import sys
from pathlib import Path

from .. import (alerts, bundles, classes, codeindex, config, decisions, defaults, features, graph, links, lint, markers,
                milestones, modules, neutral, permissions, projects, public, records, render, skew, specs, stacks, tidy,
                tiers, vault)
from ..inventory import AuditError
from ._common import _now, _on_main, _project, _queue_changed, _repos, _scope, _store_label
from .features import _features_view
from .record import cmd_record_check


def _module_warnings(root: Path, store: Path) -> list[str]:
    """brain check's lines on the module map: its view stale, an open item it does not place."""
    if not modules.applies(store):
        return []
    stale = [f"{modules.VIEW} is stale: brain sync (or brain modules --write)"]         if modules.stale(root, store, _store_label(root, store)) else []
    return stale + [f"module map: {line}" for line in modules.problems(store)]


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


def _sync_store(args, root: Path, store: Path) -> int:
    if _activate_specs(args, root, store):
        return 1
    featured = features.has_type(graph.load_schema(store))
    if featured and not getattr(args, "offline", False):   # before the graph sync: it reads the statuses
        features.sync_prs(store, [(c.name, c.path) for c in _repos(args, root) if c.path.is_dir()])
    rc = graph.research_graph(root, store, "sync", "--write")
    if rc:
        return rc
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
    if featured and _features_view(args, root, store, write=True):   # after the links: FEATURES.md shows them
        return 1
    if modules.applies(store) and modules.write(root, store, _store_label(root, store)):
        print(f"view: {modules.VIEW} written")
    if (root / records.RECORDS_DIR / "ddr").is_dir():
        for ddr_id in defaults.finalize(root, _now()):   # 24 h without an answer: the low-stakes default is final
            print(f"{ddr_id}: taken by default (brain decision defaulted)")
        _queue_changed(root, args)
    if neutral.applies(root) and render.main(root, "claude", do_write=True):   # the marketplace from the source
        return 1
    for line in render.keep_current(root, _project(args, root).name, fix=True):   # AGENTS.md and the like, here
        print(line)
    return graph.research_graph(root, store, "kanban", "--write")


def _check_markers(project: projects.Project, root: Path, store: Path) -> int:
    """1 when the store, a journal, a decision log or a record holds a conflict marker (brain.markers;
    wi-brain-guard-conflict-markers): every brain command loads them, and a stale merge's generated views pass the
    graph check."""
    files = [store, *(project.journals or [project.journal]), *(project.decision_logs or [project.decisions]),
             root / records.RECORDS_DIR]
    hits = markers.scan_files([f for f in files if f])
    for hit in hits:
        print(f"error: {hit} holds a conflict marker: finish the merge in that file, then brain refresh")
    return 1 if hits else 0


def _check_store(args, root: Path, store: Path) -> int:
    if _check_markers(_project(args, root), root, store):   # every later step would read a half-merged file
        return 1
    rc = cmd_record_check(args, root) if (root / records.RECORDS_DIR).is_dir() else 0
    if decisions.view_stale(root, _project(args, root).name):
        print(f"warning: {decisions.VIEW} is stale: brain sync (or brain decision view --write)")
    roots: dict[str, Path] = {}   # the other repos' checkouts, where research_graph reads their nodes' anchors
    if links.applies(store):
        name, cfg, cfgs = _links_repo(args, root)
        roots = links.anchor_roots(cfgs, name)
        try:
            for f in links.stale(root, store, name, cfg, cfgs):
                print(f"warning: {f} is stale: brain sync")
        except AuditError as exc:
            print(f"warning: the links graph could not be checked: {exc}")
    for line in milestones.orphan_lines(store, root):
        print(line)
    for line in _module_warnings(root, store):   # every open item has its module (wi-brain-module-map)
        print(f"warning: {line}")
    for line in skew.check_lines(root):   # the running engine against config.json engine.pin
        print(line)
    rc = _check_session_ids(root) or rc   # a DDR's local_ id that matches no session (scale study gap 19)
    for r in specs.readiness(root, store):
        if r.ready:
            print(f"warning: spec {r.id} is ready to turn active (closed by {r.closed_by()}): brain refresh, or "
                  "brain spec activate --write")
    hard = lint.hard_rules(store)
    if hard and hard["edge_type"]:  # the hard-rule ratio; a soft rule is a warning, never an error
        print("\n".join(lint.render_hard(hard)))
    if neutral.applies(root):   # the marketplace is the source's render: a hand edit fails here
        rc = render.main(root, "claude", check=True) or rc
    gate_rc, lines = public.gate(root)   # boundary.yaml: every file has a side, the engine side holds nothing private
    for line in lines:
        print(line)
    rc = gate_rc or rc
    for line in render.keep_current(root, _project(args, root).name, fix=False):   # a stale AGENTS.md: brain sync
        print(f"warning: {line}")
    line = tidy.hygiene(_project(args, root))   # stale worktrees and merged branches: brain tidy
    if line:
        print(line)
    given = [a for n, p in sorted(roots.items()) for a in ("--repo-path", f"{n}={p}")]
    return graph.research_graph(root, store, "check", *given) or rc


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


def _merge_marks(root: Path, then: str, clear: bool = False) -> None:
    """The views the merge driver kept from one side in this worktree (brain.mergedriver): said, or cleared once
    brain refresh regenerated them."""
    from .. import mergedriver
    views = mergedriver.clear(root) if clear else mergedriver.marked(root)
    if views:
        print(f"merge driver: {len(views)} view(s) kept from one side at the last merge ({', '.join(views)}); {then}")


def check_registry(root: Path | None, projs: list[projects.Project]) -> int:
    """The registry (its keys and shapes, repos, stacks, code_index), its alerts and config.json (brain.config),
    then the ids: unique across every store of every project, unless waived under a project's shared_ids. Exit
    code 1 on an error."""
    errors = projects.check(root) + config.check(root) + permissions.check(root)
    data_classes = classes.check(root)
    for w in data_classes.waived:
        print(f"waived: classes: {w}")
    errors += [f"classes: {e}" for e in data_classes.errors] + [f"vault: {e}" for e in vault.check(root)]
    errors += [f"tiers: {e}" for e in tiers.check(root)]
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
    for line in render.registry_warnings(neutral.brain_root(root), projs) + _uncloned(root):
        print(f"warning: {line}")
    for e in errors:
        print(f"error: {e}")
    print(f"registry: {len(projs)} project(s), {ids['stores']} store(s), "
          + (f"{len(errors)} error(s)" if errors else "ids unique"))
    return 1 if errors else 0


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


def _each_store(args, root: Path, *, sync: bool, check: bool) -> int:
    """sync and/or check each store of each project in scope (refresh, sync --all, check --all); a main checkout on
    main or master is not written unless --on-main; --all with check ends with check_registry."""
    failed = []
    scope = _scope(args, root)
    for p in scope:
        args.project_obj = p
        if not p.root.is_dir():
            print(f"== {p.name}: {p.root} not found, skipped")
            continue
        branch = "" if getattr(args, "on_main", False) or not sync else _on_main(p.root)
        for store in p.stores or [p.root / "notes" / "graph"]:
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
        if check_registry(root, _registry_scope(root)):
            failed.append("registry")
    print(f"{args.cmd}: {len(failed)} project(s) failed" + (f": {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0
