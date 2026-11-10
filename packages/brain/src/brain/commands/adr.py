"""``brain adr``: the project's decision log (notes/decisions.md), append-only, and its ADRs read back."""

from __future__ import annotations

import sys
from pathlib import Path

from .. import graph, notes, reads
from ._common import _print_json, _project, _read_stores, _store, _text

ORDER = 80   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 80   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain adr show REF [--titles] [--json]   instead of reading the decision log by hand: the ADR REF names (its id,
                 its title, or the start of its id), else the ADRs that decide the node REF (a rule, an item, a spec),
                 each with its text and whether a later ADR supersedes it; --titles: their headings only
  brain adr new TITLE --context C --decision D --why W --revisit R [--why-not-script S] [--decides ID]...
  brain adr new --reverses ADR --trigger T --decision D --why W --migration M ...   REVERSAL: <title>, supersedes
"""


def cmd_show(args, root: Path) -> int:
    """``brain adr show``: an ADR's text, or the ADRs that decide a node (brain.reads)."""
    try:
        out = reads.adr_show(_project(args, root), root, _read_stores(args, root), args.ref)
    except reads.ReadError as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 1
    if args.json:
        _print_json(out)
    else:
        print("\n".join(reads.render_adrs(out, titles=args.titles)))
    return 0


def cmd_adr(args, root: Path) -> int:
    path = Path(args.file).resolve() if args.file else _project(args, root).decisions
    fields = {k: _text(getattr(args, k)) for k in ("context", "decision", "why", "revisit", "why_not_script",
                                                    "trigger", "migration")}
    store = _store(args, root)
    try:
        if not (store / "schema.yaml").is_file():   # checked before anything is written, as every edge is
            raise graph.GraphError(f"{store}: no graph store here (no schema.yaml): brain init, or --store")
        etypes = graph.load_schema(store).get("edge_types") or []  # before writing: every edge must be possible
        for etype, wanted in (("supersedes", args.reverses), ("decided_by", args.decides)):
            if wanted and etype not in etypes:
                raise graph.GraphError(f"{etype}: not an edge type of {store / 'schema.yaml'}")
        for target in args.decides or []:
            if target not in graph.node_index(store):
                raise graph.GraphError(f"{target}: unknown node (--decides)")
        if args.decides or args.reverses:   # the edges' file, checked before the log is written
            graph.layer_file(store, args.edges_file)
        out = notes.adr_new(path, args.title or "", fields, day=args.date, reverses=args.reverses or "")
        edges = []
        if out["supersedes"]:
            edges.append(graph.link(store, out["id"], "supersedes", out["supersedes"], args.edges_file,
                                    pending={out["id"], out["supersedes"]}, via="brain adr new"))
        for target in args.decides or []:
            edges.append(graph.link(store, target, "decided_by", out["id"], args.edges_file, pending={out["id"]},
                                    via="brain adr new"))
    except (notes.NotesError, graph.GraphError) as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:   # a log or layer file that cannot be written: said, never a traceback
        print(f"brain: {exc.filename or path}: {exc.strerror or exc}", file=sys.stderr)
        return 1
    print(f"adr: {out['id']} appended to {path.name}" + (f"; {len(edges)} edge(s)" if edges else "")
          + "; then brain sync and brain check")
    if out["todo"]:
        print(f"brain: warning: fields left TODO: {', '.join(out['todo'])} (fill them before the commit)")
    return 0


def register(sub, ctx) -> None:
    ad = sub.add_parser("adr", help="the project's decision log (notes/decisions.md), append-only: show, "
                                    "new").add_subparsers(
        dest="adr_cmd", required=True)
    sh = ad.add_parser("show", help="an ADR's text (by id, title or the start of its id), else the ADRs that decide "
                                    "a node (a rule, an item, a spec)")
    sh.add_argument("ref", help="an ADR id or title, or a node id (rule-x, wi-x, spec-x)")
    sh.add_argument("--titles", action="store_true", help="the ADRs' headings only, not their text")
    sh.add_argument("--json", action="store_true", help="{ref, node, adrs: [{id, day, title, file, line, text}], "
                                                        "inherited}")
    an = ad.add_parser("new", help="append a dated ADR (Context, Decision, Why, Revisit if; a reversal with "
                                   "--reverses); a missing field is written TODO")
    an.add_argument("title", nargs="?", help="the heading's title (a reversal's default: REVERSAL: <original>)")
    an.add_argument("--context")
    an.add_argument("--decision", help="the decision (a reversal: the new decision)")
    an.add_argument("--why")
    an.add_argument("--revisit", help="Revisit if")
    an.add_argument("--why-not-script", help="for a new or extended rule: why a script cannot do it")
    an.add_argument("--reverses", help="the ADR reversed, by id or title: adds Supersedes and a supersedes edge")
    an.add_argument("--trigger", help="a reversal: what made the old decision wrong")
    an.add_argument("--migration", help="a reversal: what changes, in order")
    an.add_argument("--decides", action="append", help="node decided by this ADR: a decided_by edge (repeatable)")
    an.add_argument("--date", help="YYYY-MM-DD (default: today)")
    an.add_argument("--file", help="the log (default: the project's, notes/decisions.md)")
    an.add_argument("--edges-file", default="edges/work.yaml")


def run(args, root: Path) -> int:
    return (cmd_show if args.adr_cmd == "show" else cmd_adr)(args, root)
