"""``brain adr``: the project's decision log (notes/decisions.md), append-only."""

from __future__ import annotations

import sys
from pathlib import Path

from .. import graph, notes
from ._common import _project, _store, _text

ORDER = 80   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 80   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain adr new TITLE --context C --decision D --why W --revisit R [--why-not-script S] [--decides ID]...
  brain adr new --reverses ADR --trigger T --decision D --why W --migration M ...   REVERSAL: <title>, supersedes
"""


def cmd_adr(args, root: Path) -> int:
    path = Path(args.file).resolve() if args.file else _project(args, root).decisions
    fields = {k: _text(getattr(args, k)) for k in ("context", "decision", "why", "revisit", "why_not_script",
                                                    "trigger", "migration")}
    store = _store(args, root)
    try:
        etypes = graph.load_schema(store).get("edge_types") or []  # before writing: every edge must be possible
        for etype, wanted in (("supersedes", args.reverses), ("decided_by", args.decides)):
            if wanted and etype not in etypes:
                raise graph.GraphError(f"{etype}: not an edge type of {store / 'schema.yaml'}")
        for target in args.decides or []:
            if target not in graph.node_index(store):
                raise graph.GraphError(f"{target}: unknown node (--decides)")
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
    print(f"adr: {out['id']} appended to {path.name}" + (f"; {len(edges)} edge(s)" if edges else "")
          + "; then brain sync and brain check")
    if out["todo"]:
        print(f"brain: warning: fields left TODO: {', '.join(out['todo'])} (fill them before the commit)")
    return 0


def register(sub, ctx) -> None:
    ad = sub.add_parser("adr", help="the project's decision log (notes/decisions.md), append-only").add_subparsers(
        dest="adr_cmd", required=True)
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


run = cmd_adr
