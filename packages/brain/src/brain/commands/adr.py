"""``brain adr``: the project's decision log (notes/decisions.md), append-only, and its ADRs read back."""

from __future__ import annotations

import sys
from pathlib import Path

from .. import graph, notes, reads, targets
from ._common import _print_json, _project, _read_stores, _store, _text

ORDER = 80   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 80   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain adr show REF [--titles] [--json]   instead of reading the decision log by hand: the ADR REF names (its id,
                 its title, or the start of its id), else the ADRs that decide the node REF (a rule, an item, a spec),
                 each with its text and whether a later ADR supersedes it; --titles: their headings only
  brain adr new TITLE --context C --decision D --why W --revisit R [--why-not-script S] [--decides ID]...
  brain adr new --reverses ADR --trigger T --decision D --why W --migration M ...   REVERSAL: <title>, supersedes
  brain adr new ... --scope S --target ID=COMPAT[:note]... [--leaves-open T]   a one-way door (a persisted format, a
                 public contract or CLI key, a licence, a security invariant, an identity or key, the graph's schema):
                 its Scope (what it covers, up to which wave or era) and its Target compatibility (each future need it
                 touches, COMPAT compatible, extension-point or to-review, and what it leaves open); one without the
                 other is written TODO (docs/adr-target.md)
  brain adr target [--needs] [--json]   the advisory target check of the one-way-door ADRs (decision.target-compat-
                 missing, decision.review-trigger-missing, decision.target-unreferenced: an open need of a module the
                 ADR decides that its target compatibility does not cite); --needs: the register of future needs it
                 reads (the planned features, the pending milestones with a trigger, the open items of later waves and
                 of the pending eras), computed from the graph; exit 0 (advisory)
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
                                                    "trigger", "migration", "scope")}
    try:
        fields["target"] = targets.target_text(args.target or [], _text(args.leaves_open) or "")
    except ValueError as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 1
    if fields["scope"] or fields["target"]:   # a one-way door states both: the one left out is written TODO
        fields = {**fields, "scope": fields["scope"] or notes.TODO, "target": fields["target"] or notes.TODO}
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


def cmd_target(args, root: Path) -> int:
    """``brain adr target``: the advisory check of the one-way-door ADRs against the register (brain.targets)."""
    project, store = _project(args, root), _store(args, root)
    needs = targets.register(store, root)
    if args.needs:
        if args.json:
            _print_json(needs)
        else:
            print("\n".join(f"{n['kind']:<9} {n['id']} ({n['native_status']}, {n['phase']}"
                            f"{', ' + n['module'] if n['module'] else ''}): {n['title'][:90]}" for n in needs)
                  or "no future need in the graph")
        return 0
    logs = [p for p in (project.decision_logs or [project.decisions]) if p]
    decs = targets.decisions(store, logs, root)
    found = targets.check(decs, needs)
    if args.json:
        _print_json({"decisions": len(decs), "needs": len(needs), "findings": found})
        return 0
    print(f"target check: {len(decs)} one-way-door ADR(s), {len(needs)} future need(s), {len(found)} finding(s) "
          "(advisory)")
    print("\n".join(f"  warning: {f['id']} {f['subjects'][0].partition(':')[2]}: {f['message']}" for f in found))
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
    an.add_argument("--scope", help="a one-way door: what it covers, up to which wave or era")
    an.add_argument("--target", action="append", metavar="ID=COMPAT[:note]",
                    help="a one-way door: a future need it touches (a planned feature, a later item, a milestone) and "
                         "how it leaves it: compatible, extension-point or to-review (repeatable)")
    an.add_argument("--leaves-open", help="a one-way door: what it leaves open (never a later phase's design)")
    an.add_argument("--date", help="YYYY-MM-DD (default: today)")
    an.add_argument("--file", help="the log (default: the project's, notes/decisions.md)")
    an.add_argument("--edges-file", default="edges/work.yaml")
    at = ad.add_parser("target", help="the advisory target check of the one-way-door ADRs against the register of "
                                      "future needs (brain.targets); exit 0")
    at.add_argument("--needs", action="store_true", help="the register of future needs instead")
    at.add_argument("--json", action="store_true", help="stable keys: decisions, needs, findings (--needs: the "
                                                        "needs)")


def run(args, root: Path) -> int:
    return {"show": cmd_show, "target": cmd_target}.get(args.adr_cmd, cmd_adr)(args, root)
