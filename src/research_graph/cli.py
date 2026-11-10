from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from . import history, priorities, query, report
from .code_layer import FAILING, check_code_refs, orphan_code_refs, repo_heads, structure_errors
from .export_gitnexus import build_payload, push
from .init import init_store
from .kanban import FILE as KANBAN_FILE
from .kanban import kanban_stale, render_kanban, view_path, write_kanban
from .loader import ValidationError, apply_overlay, load_store, read_foreign
from .model import LayeredGraph
from .roadmap import FILE as ROADMAP_FILE
from .roadmap import render_roadmap, roadmap_stale, write_roadmap
from .sync import derive, regenerate_edges_file_text, render_edges, render_stubs
from .validate import _posix, check_consistency, check_coverage, check_wiring, decision_logs, unchecked_anchors

DEFAULT_STORE = "notes/graph"
OPEN = ["doing", "todo", "blocked"]


def _add_filters(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--status", action="append", help="todo, doing, blocked, done, dropped (repeatable; default: "
                                                      "the open ones).")
    sp.add_argument("--all", action="store_true", help="Every status.")
    sp.add_argument("--priority", action="append", help="P0-P3, P1? (a proposal), none (repeatable).")
    sp.add_argument("--repo", help="props.repo / repos, or the repo of props.pr; else the store's own repo.")
    sp.add_argument("--prop", action="append", metavar="KEY[=TEXT]", help="Items with this prop (whose value "
                                                                            "contains TEXT); repeatable.")
    sp.add_argument("--text", help="Every word in the id, title, anchor or props.")
    sp.add_argument("--json", action="store_true")


def _name_path(value: str) -> tuple[str, Path]:
    name, sep, path = value.partition("=")
    if not sep or not name or not path:
        raise argparse.ArgumentTypeError(f"{value!r}: NAME=PATH")
    return name, Path(path)


def _inside(value: str, repo_root: str, option: str) -> str:
    """``value`` relative to the repo root, posix; an absolute path inside the root is made relative. ValueError when
    it is not inside the root (an anchor names a path relative to it)."""
    path = Path(value)
    if path.is_absolute():
        try:
            value = path.resolve().relative_to(Path(repo_root).resolve()).as_posix()
        except ValueError:
            raise ValueError(f"{option} {value}: not inside --repo-root {repo_root}") from None
    rel = _posix(value)
    if rel == ".." or rel.startswith("../"):
        raise ValueError(f"{option} {value}: not inside --repo-root {repo_root}")
    return rel


def _layout(args) -> list[str]:
    """The store's layout options, resolved in place (``args.decisions``: None for the defaults, [] with
    --no-decisions), and as arguments again for the commands init runs after it."""
    if args.no_decisions:
        args.decisions = []
    elif args.decisions is not None:
        args.decisions = [_inside(d, args.repo_root, "--decisions") for d in args.decisions]
    if args.views is not None:   # anywhere: no anchor names it
        try:
            args.views = _inside(args.views, args.repo_root, "--views")
        except ValueError:
            args.views = _posix(args.views)
    out = ["--no-decisions"] if args.no_decisions else [a for d in args.decisions or [] for a in ("--decisions", d)]
    return out + (["--views", args.views] if args.views is not None else [])


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to cp1252 and choke on β/— in titles; force utf-8 output.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    p = argparse.ArgumentParser(prog="research_graph")
    p.add_argument("--store", default=DEFAULT_STORE)
    p.add_argument("--repo-root", default=".")
    p.add_argument("--overlay", action="append", default=[],
                   help="Sibling graph store to add read-only, e.g. ../ops-repo/ops/graph (repeatable).")
    p.add_argument("--foreign-store", action="append", default=[], metavar="LABEL=PATH", type=_name_path,
                   help="Another store whose ids an edge of this store may name (repeatable): such an edge loads, "
                        "its other end shown by its id and LABEL in the views, never listed as this store's own; "
                        "without it an edge to an id the store does not hold is refused. An edge needs one end in "
                        "this store.")
    logs = p.add_mutually_exclusive_group()
    logs.add_argument("--decisions", action="append", metavar="PATH",
                      help="A decision log the store covers, relative to --repo-root (repeatable): check wants an "
                           "SDR/ADR node per dated heading, sync writes the missing ones, anchored at this path; a "
                           "file named scientific_decisions.md holds SDRs, any other ADRs (default: "
                           "notes/scientific_decisions.md and notes/decisions.md). init writes its ADR log at the "
                           "first ADR log given.")
    logs.add_argument("--no-decisions", action="store_true",
                      help="The store covers no decision log (another store of the same repo covers them).")
    p.add_argument("--views", metavar="DIR", help="The folder of the generated board and roadmap, relative to "
                                                  "--repo-root (default notes): kanban --write and roadmap --write "
                                                  "write there, check flags them stale there.")
    sub = p.add_subparsers(dest="cmd", required=True)
    ini = sub.add_parser("init", help="Start a store from the templates: schema, empty work layer, ADR log; then "
                                      "sync --write and kanban --write. Never overwrites.")
    ini.add_argument("--owner", help="Who decides for the store, a person or a team (owner in schema.yaml).")
    ini.add_argument("--examples", action="store_true",
                     help="Example spec, milestone, work items and ADR to read and replace.")
    sub.add_parser("build")
    sub.add_parser("frontier")
    sub.add_parser("gated")
    ck = sub.add_parser("check")
    ck.add_argument("--repo-path", action="append", default=[], metavar="NAME=PATH", type=_name_path,
                    help="The checkout of a repo a node's repo names, whose files its anchor is in (repeatable; "
                         "without one, those anchors are not checked: an advisory).")
    syncp = sub.add_parser("sync")
    syncp.add_argument("--write", action="store_true")
    prov = sub.add_parser("provenance")
    prov.add_argument("node")
    sub.add_parser("work-frontier")
    sub.add_parser("blocked")
    ms = sub.add_parser("milestone")
    ms.add_argument("node")
    imp = sub.add_parser("impact")
    imp.add_argument("node")
    dec = sub.add_parser("decisions")
    dec.add_argument("node")
    lay = sub.add_parser("layer")
    lay.add_argument("name")
    code = sub.add_parser("code", help="Code behind a node: its CodeRefs and those of what it relies on.")
    code.add_argument("node")
    cc = sub.add_parser("code-check", help="Dev-local: CodeRefs whose file or symbol is gone in the sibling repos.")
    cc.add_argument("--platform-root", help="Parent dir of the platform repos (default: parent of --repo-root).")
    cc.add_argument("--json", metavar="PATH", help="Also write the findings (resolved file, kind, line) as JSON.")
    kb = sub.add_parser("kanban", help="Render the work layer as a generated markdown board.")
    kb.add_argument("--write", action="store_true", help=f"Write it to --out (default <repo-root>/<views>/{KANBAN_FILE}"
                                                         f", views being --views or notes), and the roadmap to "
                                                         f"<repo-root>/<views>/{ROADMAP_FILE} unless --out.")
    kb.add_argument("--out", help="Output file; a file without the GENERATED marker is never overwritten.")
    # --- read the backlog, the roadmap and the decisions (query.py, history.py)
    it = sub.add_parser("items", help="Work items with filters (default: the open ones).")
    _add_filters(it)
    it.add_argument("--since", metavar="YYYY-MM-DD", help="Only items changed on or after this day (git).")
    one = sub.add_parser("item", help="One node: props, links both ways, ids its props name, history from git.")
    one.add_argument("node")
    one.add_argument("--no-git", action="store_true", help="Skip the history.")
    one.add_argument("--json", action="store_true")
    cl = sub.add_parser("closed", help="Done and dropped items by date (props.done, else the git transition).")
    cl.add_argument("--since", metavar="YYYY-MM-DD")
    cl.add_argument("--no-git", action="store_true", help="props.done dates only.")
    cl.add_argument("--json", action="store_true")
    ev = sub.add_parser("events", help="Changes to the work layer from git: created, status, title, props.")
    ev.add_argument("--since", metavar="YYYY-MM-DD")
    ev.add_argument("--id", action="append", help="Only these nodes (repeatable).")
    ev.add_argument("--all-types", action="store_true", help="Every node type, not only the work layer.")
    ev.add_argument("--rev", default="HEAD", help="Revision whose first-parent history is read (default HEAD).")
    ev.add_argument("--json", action="store_true")
    ao = sub.add_parser("asof", help="The backlog on a day, read from the store's files in git (no overlay).")
    ao.add_argument("day", metavar="YYYY-MM-DD")
    _add_filters(ao)
    ao.add_argument("--rev", default="HEAD")
    rm = sub.add_parser("roadmap", help="Milestones: status, trigger, reached, the items that move each.")
    rm.add_argument("--write", action="store_true", help=f"Write the markdown view to --out (default "
                                                         f"<repo-root>/<views>/{ROADMAP_FILE}, views being --views "
                                                         "or notes).")
    rm.add_argument("--out", help="Output file; a file without the GENERATED marker is never overwritten.")
    rm.add_argument("--markdown", action="store_true", help="Print the markdown view instead of the summary.")
    rm.add_argument("--json", action="store_true")
    pd = sub.add_parser("pending", help="Decisions waiting for the store's owner (owner in schema.yaml): props.open, "
                                        "unanswered spec questions, items blocked on the owner, proposed specs.")
    pd.add_argument("--json", action="store_true")
    pr = sub.add_parser("priorities", help="Priority proposals (props.priority_proposed) and applying them.")
    prs = pr.add_subparsers(dest="pcmd", required=True)
    pp = prs.add_parser("proposal", help="Open items with a proposal, by proposed priority (markdown tables).")
    pp.add_argument("--json", action="store_true")
    pa = prs.add_parser("apply", help="Validated proposals -> props.priority (dry run unless --write).")
    pa.add_argument("--only", help="Comma-separated ids: validate only these.")
    pa.add_argument("--skip", help="Comma-separated ids: leave these proposals as they are.")
    pa.add_argument("--set", action="append", default=[], metavar="ID=P1",
                    help="Validate with the owner's value instead of the proposal (repeatable).")
    pa.add_argument("--write", action="store_true", help="Edit the node files (then kanban --write and check).")
    exp = sub.add_parser("export-gitnexus")
    exp.add_argument("--out", default="results/graph/gitnexus_payload.json")
    exp.add_argument("--layers", nargs="*", help="Only these layers (default: all).")
    exp.add_argument("--push", metavar="URL", help="Sidecar base URL, e.g. http://localhost:4174.")
    exp.add_argument("--name", help="Graph name in the sidecar (default: the repo root's folder name, lower case).")
    exp.add_argument("--mode", choices=["single", "typed"], default="single",
                     help="single: one Node table (works with the current sidecar); typed: a table per type.")
    args = p.parse_args(argv)
    try:
        args.layout = _layout(args)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    if args.cmd == "init":
        return _init(args)
    if args.cmd == "sync":
        res = derive(args.store, args.repo_root, args.decisions)
        exp_txt = render_stubs(res["experiments"])
        dec_txt = render_stubs(res["decisions"])
        hyp_txt = render_stubs(res["hypotheses"])
        edge_txt = render_edges(res["edges"])
        if args.write:
            nodes_dir = Path(args.store) / "nodes"
            if exp_txt:
                (nodes_dir / "_generated_experiments.yaml").write_text(
                    "# Auto-generated Experiment stubs (research_graph sync). Curate freely.\n"
                    + exp_txt
                    + "\n",
                    encoding="utf-8",
                )
            decisions_file = nodes_dir / "_generated_decisions.yaml"
            if dec_txt or decisions_file.exists():  # derived from the logs (in git): none left is authoritative
                decisions_file.write_text(
                    "# Auto-generated SDR/ADR coverage stubs (research_graph sync). Curate freely.\n"
                    + (dec_txt or "[]")
                    + "\n",
                    encoding="utf-8",
                )
            if hyp_txt:
                (nodes_dir / "_generated_hypotheses.yaml").write_text(
                    "# Auto-generated L2 Hypothesis stubs (research_graph sync). Curate freely.\n"
                    + hyp_txt
                    + "\n",
                    encoding="utf-8",
                )
            # rewrite edges.yaml = hand-curated prefix + freshly regenerated auto-derived block
            # (GC: stale/dangling auto-edges from prior syncs are dropped, not accumulated)
            (Path(args.store) / "edges.yaml").write_text(
                regenerate_edges_file_text(args.store, edge_txt), encoding="utf-8"
            )
            print(
                f"wrote {len(res['experiments'])} experiment + {len(res['decisions'])} decision "
                f"stub(s) + {len(res['hypotheses'])} hypothesis stub(s) + {len(res['edges'])} lineage edge(s)"
            )
        else:
            print("\n".join(t for t in (exp_txt, dec_txt, hyp_txt, edge_txt) if t))
        return 0

    try:
        graph = load_store(args.store, foreign=_foreign(args))
        for overlay in args.overlay:
            apply_overlay(graph, overlay, args.repo_root)
    except ValidationError as exc:
        print(exc, file=sys.stderr)
        return 1

    rg = LayeredGraph(graph)

    if args.cmd in VIEWS:
        return VIEWS[args.cmd](graph, args)
    if args.cmd == "build":
        print(f"loaded {graph.number_of_nodes()} nodes, " f"{graph.number_of_edges()} edges")
        return 0
    if args.cmd == "frontier":
        for n in rg.frontier():
            print(n)
        return 0
    if args.cmd == "gated":
        for n in rg.gated():
            print(n)
        return 0
    if args.cmd == "provenance":
        try:
            nodes = rg.provenance(args.node)
        except KeyError:
            print(f"unknown node: {args.node}", file=sys.stderr)
            return 1
        for n in nodes:
            print(n)
        return 0
    if args.cmd == "work-frontier":
        for n in rg.work_frontier():
            print(f"{n}  {graph.nodes[n].get('title', '')}")
        return 0
    if args.cmd == "blocked":
        for n, why in rg.blocked().items():
            print(f"{n}  <- {', '.join(why)}")
        return 0
    if args.cmd in {"milestone", "impact", "decisions", "code"} and args.node not in graph:
        print(f"unknown node: {args.node}", file=sys.stderr)
        return 1
    if args.cmd == "milestone":
        m = rg.milestone(args.node)
        print(f"{m['milestone']} [{m['status']}] trigger: {m['trigger'] or '-'}")
        print(f"items: {m['items']}  " + "  ".join(f"{k}={v}" for k, v in m["by_status"].items()))
        if m["cycle"]:
            print("critical path: dependency CYCLE among open items")
        else:
            print("critical path: " + (" -> ".join(m["critical_path"]) or "(none open)"))
        return 0
    if args.cmd == "impact":
        for layer, nodes in rg.impact(args.node).items():
            print(f"[{layer}] {len(nodes)}")
            for n in nodes:
                print(f"  {n}")
        return 0
    if args.cmd == "decisions":
        d = rg.decisions(args.node)

        def show(e: dict) -> str:
            line = f"  {report.name(e)} [{e['type']} {e['status']}] {e['title']}"
            if e.get("superseded_by"):
                line += f"  -> superseded by {e['superseded_by']}"
            if e.get("via"):
                line += f"  (via {e['via']})"
            return line

        print(f"decisions behind {d['node']}")
        print(f"direct: {len(d['direct'])}")
        for e in d["direct"]:
            print(show(e))
        print(f"inherited: {len(d['inherited'])}")
        for e in d["inherited"]:
            print(show(e))
        print(f"specs (pre-registrations): {len(d['specs'])}")
        for s_ in d["specs"]:
            print(f"  {report.name(s_)} [{s_['status']}] {s_['anchor'] or ''}")
        return 0
    if args.cmd == "code":
        c = rg.code(args.node)
        print(f"code behind {c['node']}")
        print(f"direct: {len(c['direct'])}")
        for cid in c["direct"]:
            print(f"  {cid}")
        print(f"inherited: {len(c['inherited'])}")
        for e in c["inherited"]:
            print(f"  {e['id']}  (via {e['via']})")
        return 0
    if args.cmd == "code-check":
        return _code_check(graph, args)
    if args.cmd == "kanban":
        if not args.write:
            print(render_kanban(graph), end="")
            return 0
        try:
            out = write_kanban(graph, args.out or Path(args.repo_root) / view_path(KANBAN_FILE, args.views))
            # the roadmap is regenerated with the board, at its default place only (--out names the board)
            road = None if args.out else write_roadmap(graph, Path(args.repo_root) / view_path(ROADMAP_FILE,
                                                                                               args.views))
        except FileExistsError as exc:
            print(exc, file=sys.stderr)
            return 1
        print(f"wrote {out}" + (f" and {road}" if road else ""))
        return 0
    if args.cmd == "layer":
        for n in rg.layer(args.name):
            print(f"{n}  [{graph.nodes[n].get('status')}]  {graph.nodes[n].get('title', '')}")
        return 0
    if args.cmd == "export-gitnexus":
        payload = build_payload(graph, set(args.layers) if args.layers else None, mode=args.mode)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {out}: {len(payload['nodes'])} nodes, {len(payload['edges'])} edges, "
              f"{len(payload['ddl'])} DDL statements")
        if args.push:
            print(push(payload, args.push, args.name or _repo_name(args).lower()))
        return 0
    if args.cmd == "check":
        repos = dict(args.repo_path)
        problems = check_coverage(graph, args.repo_root, repos, args.decisions)
        problems += check_wiring(graph, args.repo_root)
        problems += structure_errors(graph)
        advisories = check_consistency(graph) + orphan_code_refs(graph) + unchecked_anchors(graph, repos)
        views = kanban_stale(graph, args.repo_root, args.views) + roadmap_stale(graph, args.repo_root, args.views)
        for adv in advisories + views:
            print(f"advisory: {adv}")
        for adv in graph.graph.get("collapsed_edges", []):
            print(f"advisory: collapsed edge {adv}")
        if problems:
            print("\n".join(problems), file=sys.stderr)
            return 1
        print("graph-check OK")
        return 0
    return 0


def _foreign(args) -> dict | None:
    """The ids of the --foreign-store stores (None without one: the loader refuses an edge to an id it lacks)."""
    return read_foreign(args.foreign_store) if args.foreign_store else None


def _init(args) -> int:
    adr_logs = [rel for rel, kind in decision_logs(args.decisions) if kind == "ADR"]
    try:
        written = init_store(args.store, args.repo_root, owner=args.owner, examples=args.examples,
                             log=adr_logs[0] if adr_logs else None)
    except FileExistsError as exc:
        print(exc, file=sys.stderr)
        return 1
    for path in written:
        print(f"created {path}")
    base = ["--store", str(args.store), "--repo-root", str(args.repo_root), *args.layout]
    code = main(base + ["sync", "--write"]) or main(base + ["kanban", "--write"])
    if not code:
        print("next: research_graph check, then edit nodes/work.yaml and edges/work.yaml (research_graph --help)")
    return code


def _print_json(data) -> None:
    print(json.dumps(data, indent=1, ensure_ascii=False, default=str))


def _repo_name(args) -> str:
    return Path(args.repo_root).resolve().name


def _filters(args) -> dict:
    props = {}
    for p in args.prop or []:
        key, sep, value = p.partition("=")
        props[key] = value if sep else None
    return {"statuses": None if args.all else (args.status or OPEN), "priorities": args.priority,
            "repo": args.repo, "props": props or None, "text": args.text, "default_repo": _repo_name(args)}


def _valid_day(text: str | None) -> bool:
    try:
        return text is None or bool(date.fromisoformat(text))
    except ValueError:
        print(f"not a day (YYYY-MM-DD): {text!r}", file=sys.stderr)
        return False


def _items(graph, args) -> int:
    if not _valid_day(args.since):
        return 2
    ids = None
    if args.since:
        try:
            ids = query.changed_since(history.timeline(args.store), args.since)
        except history.GitError as exc:
            print(f"--since reads the store's git history: {exc}", file=sys.stderr)
            return 1
    rows = query.list_items(graph, ids=ids, **_filters(args))
    if args.json:
        _print_json(rows)
    else:
        print("\n".join(report.rows(rows)))
    return 0


def _item(graph, args) -> int:
    try:
        detail = query.show_item(graph, args.node, default_repo=_repo_name(args))
    except KeyError:
        print(f"unknown node: {args.node}", file=sys.stderr)
        return 1
    events, error = None, None
    if not args.no_git:
        node = graph.nodes[args.node]
        try:  # an overlay node's history is its own repository's
            events = [e for e in history.timeline(node.get("overlay") or args.store, types={node.get("type")})
                      if e.id == args.node]
        except history.GitError as exc:
            error = str(exc)
    if args.json:
        _print_json({**detail, "history": None if events is None else [e.to_json() for e in events],
                     "history_error": error})
    else:
        print("\n".join(report.item(detail, events, error)))
    return 0


def _closed(graph, args) -> int:
    if not _valid_day(args.since):
        return 2
    events = None
    if not args.no_git:
        try:
            events = history.timeline(args.store, types={"WorkItem"})
        except history.GitError as exc:
            print(f"warning: no git history ({exc}): props.done dates only", file=sys.stderr)
    rows = query.closed_items(graph, since=args.since, events=events, default_repo=_repo_name(args))
    if args.json:
        _print_json(rows)
    else:
        print("\n".join(report.closed(rows)))
    return 0


def _events(graph, args) -> int:
    if not _valid_day(args.since):
        return 2
    try:
        evts = history.timeline(args.store, rev=args.rev, types=None if args.all_types else history.WORK_TYPES)
    except history.GitError as exc:
        print(exc, file=sys.stderr)
        return 1
    evts = [e for e in evts if (not args.since or e.day >= args.since) and (not args.id or e.id in args.id)]
    if args.json:
        _print_json([e.to_json() for e in evts])
    else:
        print("\n".join(report.events(evts)))
    return 0


def _asof(graph, args) -> int:
    if not _valid_day(args.day):
        return 2
    try:
        commit = history.commit_on(args.store, date.fromisoformat(args.day), rev=args.rev)
        if commit is None:
            print(f"no commit on or before {args.day}", file=sys.stderr)
            return 1
        old = history.load_store_at(args.store, commit.sha, _foreign(args))
    except (history.GitError, ValidationError) as exc:
        print(exc, file=sys.stderr)
        return 1
    rows = query.list_items(old, **_filters(args))
    if args.json:
        _print_json({"day": args.day, "commit": commit.to_json(), "items": rows})
    else:
        print(f"backlog as of {args.day}: the store at {commit.sha[:7]} ({commit.day}, {commit.ref})")
        print("\n".join(report.rows(rows)))
    return 0


def _roadmap(graph, args) -> int:
    if args.write:
        try:
            out = write_roadmap(graph, args.out or Path(args.repo_root) / view_path(ROADMAP_FILE, args.views))
        except FileExistsError as exc:
            print(exc, file=sys.stderr)
            return 1
        print(f"wrote {out}")
    elif args.json:
        _print_json(query.roadmap(graph, default_repo=_repo_name(args)))
    elif args.markdown:
        print(render_roadmap(graph), end="")
    else:
        print("\n".join(report.roadmap(query.roadmap(graph, default_repo=_repo_name(args)))))
    return 0


def _pending(graph, args) -> int:
    data = query.pending_decisions(graph, args.repo_root)
    if args.json:
        _print_json(data)
    else:
        print("\n".join(report.pending(data)))
    return 0


def _ids(text: str | None) -> list[str] | None:
    return [t.strip() for t in text.split(",") if t.strip()] if text else None


def _priorities(graph, args) -> int:
    if args.pcmd == "proposal":
        if args.json:
            _print_json(priorities.proposal_rows(graph))
        else:
            print(priorities.render_proposal(graph), end="")
        return 0
    overrides = {}
    for s in args.set:
        nid, sep, value = s.partition("=")
        if not sep:
            print(f"--set {s!r}: expected ID=P0..P3", file=sys.stderr)
            return 2
        overrides[nid.strip()] = value.strip()
    try:
        changes = priorities.apply_priorities(args.store, only=_ids(args.only), skip=_ids(args.skip) or (),
                                              overrides=overrides, write=args.write)
    except priorities.EditError as exc:
        print(exc, file=sys.stderr)
        return 1
    for c in changes:
        print(c.line())
    if args.write:
        print(f"{len(changes)} priority(ies) written"
              + ("; now: research_graph kanban --write, then check" if changes else ""))
    else:
        print(f"{len(changes)} priority(ies) to write (dry run: add --write to apply them)")
    return 0


VIEWS = {"items": _items, "item": _item, "closed": _closed, "events": _events, "asof": _asof,
         "roadmap": _roadmap, "pending": _pending, "priorities": _priorities}


def _code_check(graph, args) -> int:
    """Dev-local, like scripts/check_platform_pins.py: reads the sibling checkouts as they are, skips absent repos.
    Exit 1 on a malformed id, a missing file or symbol, or an unparsable file."""
    problems = structure_errors(graph)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    root = Path(args.platform_root) if args.platform_root else Path(args.repo_root).resolve().parent
    findings = check_code_refs(graph, root)
    heads = repo_heads(graph, root)
    print(f"code-check @ {root}")
    for repo, head in heads.items():
        print(f"  {repo}: {head}")
    print()
    for f in findings:
        where = f"{f.file}:{f.line}" if f.line else (f.file or "")
        line = f"  {f.verdict:<14} {f.id}"
        if f.verdict == "OK":
            line += f"  [{f.kind}] {where}"
        else:
            line += f"  <- {f.detail}"
        print(line)
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.verdict] = counts.get(f.verdict, 0) + 1
    print("\n" + (", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "no active CodeRef"))
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"platform_root": str(root), "heads": heads,
                                   "findings": [vars(f) for f in findings]}, indent=1), encoding="utf-8")
    return 1 if any(f.verdict in FAILING for f in findings) else 0
