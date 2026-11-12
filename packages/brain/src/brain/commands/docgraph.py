"""``brain docgraph``: the documentation graph's contract, docgraph/v1 (brain.docgraph; docs/docgraph.md). ``validate``
checks documents any program emitted against it; ``checks`` lists the named checks and what each means. Neither needs
a brain: they run anywhere the engine is installed.
"""

from __future__ import annotations

import json
from pathlib import Path

from .. import docgraph

ORDER = 47   # its place in brain --help's list of commands (brain.commands), after brain docs
USAGE_ORDER = 34   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain docgraph validate FILE... [--json] | checks [--json]   the documentation graph's neutral contract,
                 docgraph/v1 (docs/docgraph.md): validate reads each document (any producer's) against the schema and
                 the rules a schema cannot say (ids unique and prefixed by their type, a source naming a file or a
                 tracker object, checks run and not run apart), notes what a reader keeps without judging (an edge to
                 an id the document does not hold, a producer's own check) and exits 1 when one is invalid or written
                 for a later version; checks lists the named checks, their subject, severity and meaning
"""


def _validate(files: list[str], as_json: bool) -> int:
    out, bad = [], 0
    for name in files:
        try:
            doc = docgraph.load(Path(name))
        except docgraph.DocgraphError as exc:
            out.append({"file": name, "ok": False, "errors": [str(exc)], "notes": [], "summary": None})
            bad += 1
            continue
        errors, notes = docgraph.validate(doc, where=name)
        bad += bool(errors)
        out.append({"file": name, "ok": not errors, "errors": errors, "notes": notes,
                    "summary": None if errors and docgraph.newer(doc) else docgraph.summary(doc)})
    if as_json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 1 if bad else 0
    for r in out:
        s = r["summary"] or {}
        counts = (f": {sum(s.get('nodes', {}).values())} node(s), {sum(s.get('edges', {}).values())} edge(s), "
                  f"{sum(s.get('findings', {}).values())} finding(s) "
                  f"({s.get('findings', {}).get('error', 0)} error)") if s else ""
        print(f"{r['file']}: {'OK' if r['ok'] else 'INVALID'}{counts}")
        for e in r["errors"]:
            print(f"  error: {e}")
        for n in r["notes"]:
            print(f"  note: {n}")
    return 1 if bad else 0


def _checks(as_json: bool) -> int:
    if as_json:
        print(json.dumps([{"id": c.id, "subject": c.subject, "severity": c.severity, "means": c.means,
                           "needs": c.needs} for c in docgraph.CHECKS], indent=2))
        return 0
    width = max(len(c.id) for c in docgraph.CHECKS)
    for c in docgraph.CHECKS:
        print(f"{c.id:<{width}}  {c.severity:<7}  {c.means} (needs {c.needs})")
    return 0


def early(args):
    """Both subcommands run without a root (another program's documents, the contract's catalogue)."""
    if args.docgraph_cmd == "validate":
        return _validate(args.files, args.json)
    if args.docgraph_cmd == "checks":
        return _checks(args.json)
    return None


def register(sub, ctx) -> None:
    dg = sub.add_parser("docgraph", help="the documentation graph's contract, docgraph/v1: validate documents, list "
                                         "the named checks (brain.docgraph)")
    ds = dg.add_subparsers(dest="docgraph_cmd", required=True)
    dv = ds.add_parser("validate", help="exit 1 when a document does not hold to docgraph/v1 or is written for a later "
                                        "version")
    dv.add_argument("files", nargs="+", metavar="FILE", help="a docgraph/v1 JSON document")
    dv.add_argument("--json", action="store_true", help="stable keys: file, ok, errors, notes, summary")
    dc = ds.add_parser("checks", help="the named checks: id, subject, severity, meaning, what a producer needs to run "
                                      "it")
    dc.add_argument("--json", action="store_true", help="stable keys")
