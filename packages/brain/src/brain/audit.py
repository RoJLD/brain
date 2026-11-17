"""``brain audit``: per repo and module, what misses the standard, measured at zero token (spec 2026-10-30 section
3.18, Q16 A: measure first; the answers Q1-Q4 of 2026-11-02 in the ADR "brain audit : mesurer la dette de
conformité à zéro token").

A full audit reads each repo of a project (``repos:`` in projects.yaml) at the tip of its default branch, or at HEAD
in a linked worktree, through git plumbing: committed state only, the same code path as the trend. The checks are
CHECKS (RULESET; a change of check or severity needs an ADR and a ruleset bump): P0 when the repo states something
false, P1 for a gap on a production path (a unit the static closure from the declared entries reaches, class entry
or prod), P2 elsewhere, info never counted. The checks a generator will own are PENDING: listed per repo as not
measured, never counted, never in an exit code, but they keep the milestone ms-brain-conformance from being met. A
generator turns its checks on by giving them a ``run`` (and a CHECKS entry): doc.links and test.links (brain.links)
are measured where the repo's own store has the Doc and Test types, features.md and feature.links (brain.features)
in a project whose store has the Feature type; else they are still listed as not measured, and still keep the
milestone from being met when they would carry P0 or P1. feature.coverage (brain.feature_coverage) lists, as info and
in a section of its own per repo, the commands and modules of a command registry that no feature names.

Outputs: text (every P0 and P1, a count and three examples per P2 check; -v for all), --json (stable keys, no
timestamp), --trend [N] (the last N completed ISO weeks re-measured at their end commit with today's rules),
--write (the view notes/audit.md, from a worktree), --items (one debt item per repo, priority proposed, never closed,
reopened or linked automatically). Exit codes: 0 the report was produced (debt alone never fails it); 1 --fail-on
and a finding at that severity or above, or a refused write; 2 a registry or usage error, or a git failure.
``brain audit --diff`` is the scout (brain.scout).

By concern: the checks and their ruleset (brain.audit_checks), the measure of a project's repos (brain.audit_measure),
the trend and the milestone (brain.audit_trend), the outputs (brain.audit_render); this module holds the backlog sync
and the command, and keeps every public name the others had here (brain.audit.measure, CHECKS, RULESET, ...:
__all__); a private helper is its module's (brain.audit_measure._moved), and so is a patch of a name a moved
function reads (brain.audit_measure.measure for the trend's weeks, brain.audit_checks.PENDING).
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from . import config, graph, paths, projects
from .audit_checks import (
    CALIBRATED,
    CHECKS,
    COVERAGE_FLOOR,
    NO_FEATURES,
    NO_README,
    NO_TOOLS,
    PENDING,
    REFERENCE_PAGE,
    RULESET,
    SEVERITIES,
    Check,
    Pending,
    doc_links,
    feature_cover,
    feature_links,
    feature_tests,
    features_md,
    finding,
    generated_doc,
    help_quoted,
    lang_report,
    readme_yaml,
    severity,
    standards_gap,
    test_coverage,
    test_links,
)
from .audit_measure import (
    BACKTICK,
    DOC_PATH,
    EXTERNAL,
    FILE_EXTS,
    HEADING,
    README_LINES,
    SECTIONS,
    TICK_DOTTED,
    WAIVABLE,
    measure,
    registry_findings,
    stale_waivers,
    trees_now,
    waived_findings,
)
from .audit_render import VIEW, _public, render_json, render_text, render_view, write_view
from .audit_trend import (
    MILESTONE,
    STREAK,
    _total,
    falling,
    merge_trends,
    milestone,
    trend,
    trend_line,
    week_ends,
)
from .inventory import AuditError
from .mergedriver import HEAD_LINES

# brain.audit's names: its own, and those of the concern modules it is the front of (kept for its callers)
__all__ = ["BACKTICK", "CALIBRATED", "CHECKS", "COVERAGE_FLOOR", "DOC_PATH", "EXTERNAL", "FILE_EXTS", "HEADING",
           "HEAD_LINES", "MILESTONE", "NO_FEATURES", "NO_README", "NO_TOOLS", "PENDING", "README_LINES",
           "REFERENCE_PAGE", "RULESET", "SECTIONS", "SEVERITIES", "STREAK", "TICK_DOTTED", "VIEW", "WAIVABLE",
           "AuditError", "Check", "Pending", "doc_links", "falling", "feature_cover", "feature_links",
           "feature_tests", "features_md", "finding", "generated_doc", "help_quoted", "item_id", "lang_report",
           "main", "measure", "merge_trends", "milestone", "readme_yaml", "registry_findings", "render_json",
           "render_text", "render_view", "run", "scope", "severity", "stale_waivers", "standards_gap", "sync_items",
           "test_coverage", "test_links", "trees_now", "trend", "trend_line", "waived_findings", "week_ends",
           "write_view"]

# --- backlog sync ---

def item_id(c: projects.Repo) -> str:
    return c.item or f"wi-debt-{c.name}"


def sync_items(p: projects.Project, cfgs: list[projects.Repo], result: dict, store: Path, out=None) -> int:
    """One item per repo with measured debt: created with its priority proposed; afterwards a missing audit_repo or
    report is filled in and priority_proposed changes when the measure moves; a validated priority is never touched.
    Never closed, reopened or linked."""
    out = out or sys.stdout
    if "WorkItem" not in (graph.load_schema(store).get("node_types") or []):
        print(f"warning: {store} has no WorkItem type: the audit stays report-only for {p.name}", file=out)
        return 0
    spec = (p.audit or {}).get("spec", "")
    by = {c.name: c for c in cfgs}
    for r in result["repos"]:
        if r.get("error"):
            continue
        c, counts = by[r["name"]], r["counts"]
        nid = item_id(c)
        debt = counts["P0"] + counts["P1"] + counts["P2"]
        want = "P1" if counts["P0"] or counts["P1"] else "P2"
        index = graph.node_index(store)
        node = index[nid][1] if nid in index else None
        if node is None:
            if not debt:
                continue
            props = {"priority_proposed": want, "theme": "3.18", "audit_repo": c.name,
                     "report": f"{VIEW}#{c.name}"}
            graph.add_item(store, nid, f"{c.name} up to the standard (brain audit debt): by batches, production "
                           "first", props=props, spec=spec if spec in index else "")
            print(f"item: {nid} added (priority_proposed {want}); proposal, never automatic: link it to a "
                  f"milestone and to what depends on it (brain item link {nid} part_of <milestone>)", file=out)
            continue
        props = node.get("props") or {}
        if node.get("status") in ("done", "dropped"):
            if debt:
                print(f"warning: {nid} is {node['status']} and {c.name} has debt again (P0 {counts['P0']}, P1 "
                      f"{counts['P1']}, P2 {counts['P2']}): reopen it or add an item (not automatic)", file=out)
            continue
        if not debt:
            print(f"{nid}: no debt left in {c.name}: close it (close-item)", file=out)
            continue
        sets = [f"{k}={v}" for k, v in (("audit_repo", c.name), ("report", f"{VIEW}#{c.name}"))
                if k not in props]
        if props.get("priority_proposed") != want:
            sets.append(f"priority_proposed={want}")
        if sets:
            graph.set_item(store, nid, sets)
            print(f"item: {nid} set {', '.join(sets)}", file=out)
        if props.get("priority") and props["priority"] != want:
            print(f"note: {nid} has the validated priority {props['priority']}; the measure suggests {want} "
                  f"(left to {config.owner_of()})", file=out)
    return 0


# --- the command ---

def _registered(root: Path | None) -> dict[str, projects.Project]:
    reg = projects.load(root)
    if not reg:
        raise AuditError(f"the project registry is needed ({projects.REGISTRY}; $BRAIN_PROJECTS or "
                         "$CLAUDE_BRAIN_DIR)")
    return reg


def _not_registered(name: str, root: Path | None, reg) -> str:
    """Why --project ``name`` is not one to audit: what --project says (read only, a mount, not loaded), else
    unknown."""
    return projects.unloaded(name, root) or f"unknown project {name!r} (known: {', '.join(reg)})"


def scope(args, root: Path | None) -> list[projects.Project]:
    """--all: every registered project; --project; else the project whose root (or one of whose repos) is the main
    checkout of --root or the current folder; else the project of the nearest graph store."""
    if getattr(args, "scope", None):   # a node of the scope tree: the projects of its subtree (brain.scopes)
        return _tree_scope(args, root)
    if args.all:
        return _every(args, root)
    if args.project:
        reg = _registered(root)
        if args.project not in reg:
            raise AuditError(_not_registered(args.project, root, reg))
        return [projects.get(args.project, root)]
    here = root or Path.cwd()
    main = paths.main_checkout(here)
    reg = projects.load(root)
    if main:
        for p in reg.values():
            if p.root.resolve() == main.resolve():
                return [projects.get(p.name, root) if root else p]
        if root is None:
            for p in reg.values():
                if any(r.path.resolve() == main.resolve() for r in projects.repos_of(p)):
                    return [p]
    return [projects.for_root(root or paths.find_root())]


def _every(args, root: Path | None) -> list[projects.Project]:
    """--all: every registered project, refused with --project."""
    if args.project:
        raise AuditError("--project or --all, not both")
    return list(_registered(root).values())


def _tree_scope(args, root: Path | None) -> list[projects.Project]:
    from . import scopes
    if args.all or args.project:
        raise AuditError("--scope, --project or --all: one of them")
    try:
        node, names = scopes.select(args.scope, root, _here(root))
    except scopes.ScopeError as exc:
        raise AuditError(str(exc)) from None
    if not names:
        raise AuditError(f"--scope {args.scope}: no registered project the brain loads under {node}")
    if node == scopes.GLOBAL:   # global is --all: the milestone line too
        args.all = True
    reg = _registered(root)
    return [reg[n] for n in names if n in reg]


def _here(root: Path | None) -> str:
    found = projects.at_root(root) if root is not None else []
    return found[0].name if found else ""


def run(args, root: Path | None, today: date | None = None) -> dict:
    """The data of a full run: {audit, ruleset, projects: [...], trend, milestone}."""
    today = today or date.today()
    projs = scope(args, root)
    if (args.write or args.items) and (len(projs) > 1 or args.all or getattr(args, "scope", None)):
        raise SystemExit("brain: --write and --items take one project (not --all or --scope)")
    if args.write and args.repo:
        raise SystemExit("brain: --write writes the whole project's view (not --repo)")
    if args.write and projs and projs[0].shares_root_with:
        owner = projs[0].shares_root_with
        raise SystemExit(f"brain: {projs[0].name} shares its root with {owner}: {VIEW} is {owner}'s (brain --project "
                         f"{owner} audit --write)")
    data = {"audit": 1, "ruleset": RULESET, "projects": []}
    trends = {}
    n = args.trend if args.trend else (5 if args.write else 0)
    if args.repo:
        names = {c.name for p in projs for c in projects.repos_of(p, audit=True)}
        unknown = sorted(set(args.repo) - names)
        if unknown:
            raise AuditError(f"unknown repo(s) {', '.join(unknown)} (repos: {', '.join(sorted(names))})")
    for p in projs:
        cfgs = projects.repos_of(p, audit=True)
        only = None
        if args.repo:   # every repo is still read: the closure and cross-repo references span them all
            only = set(args.repo)
            if not only & {c.name for c in cfgs}:
                continue
        trees, refs, errors = trees_now(cfgs)
        res = measure(p, cfgs, trees, only)
        res["repos"] += [{"name": k, "path": str(next(c.path for c in cfgs if c.name == k)), "error": v}
                         for k, v in errors.items() if only is None or k in only]
        res["cfgs"], res["project"] = cfgs, p
        if not cfgs and not p.shares_root_with and not projects.software(p):
            kinds = ", ".join(map(str, p.lifecycle.get("typologies") or []))
            res["not_software"] = (f"no code repo audited: its kinds ({kinds}) meet no software pack (repos: or "
                                   "production: in its registry entry audits one anyway)")
        if n:
            res["trend"] = trend(p, cfgs, refs, n, today, only, res["layered"], res["linked"], res["featured"],
                                 res["coverage"])
            res["trend"]["falling"] = falling([_total(w) for w in res["trend"]["weeks"]])
            trends[p.name] = res["trend"]
        data["projects"].append(res)
    if trends:
        data["trend"] = merge_trends(trends)
    if args.all:
        data["milestone"] = milestone(data["projects"], data.get("trend")) if not args.repo else             {"id": MILESTONE, "met": False, "reasons": ["not evaluated: --repo narrows the scope"], "pending": []}
    return data


def _worst(data: dict) -> int:
    sevs = [f["severity"] for p in data["projects"] for r in p["repos"] for f in r.get("findings", [])
            if f["severity"] in SEVERITIES]
    return min((SEVERITIES.index(s) for s in sevs), default=len(SEVERITIES))


def main(args, root: Path | None) -> int:
    try:
        if args.diff is not None:
            from . import scout
            return scout.main(args, root)
        data = run(args, root)
        projs = data["projects"]
        if args.write or args.items:
            p = projs[0]
            proj = p["project"]
            from .commands._common import _on_main
            branch = _on_main(proj.root)
            if branch:
                raise SystemExit(f"brain: {proj.root} is a main checkout on {branch}: write from a worktree "
                                 f"(brain --project {proj.name} --root <worktree> audit --write)")
            if args.write:
                f, changed = write_view(proj.root, render_view(_public(p)))
                print(f"view: {f.relative_to(proj.root).as_posix()} {'written' if changed else 'unchanged'}")
            if args.items:
                store = proj.stores[0] if proj.stores else proj.root / "notes" / "graph"
                try:
                    sync_items(proj, p["cfgs"], p, store)
                except graph.GraphError as exc:
                    print(f"brain: {exc}", file=sys.stderr)
                    return 1
        public = {**data, "projects": [_public(p) for p in projs]}
        if args.json:
            print(render_json(public))
        else:
            print("\n".join(render_text(public, args.verbose)))
        if args.fail_on and _worst(data) <= SEVERITIES.index(args.fail_on):
            return 1
        return 0
    except (AuditError, projects.RepoError) as exc:
        print(f"brain audit: {exc}", file=sys.stderr)
        return 2
