"""``brain docgraph``: the documentation graph's contract, docgraph/v1 (brain.docgraph; docs/docgraph.md). ``validate``
checks documents any program emitted against it; ``checks`` lists the named checks and what each means: neither
needs a brain. ``emit`` writes the project's own documentation graph (brain.docsgraph) as a docgraph/v1 document;
``pin`` copies a read project's document from a clone at a commit, ``join`` reads them all as one graph and runs the
named checks across it (brain.docjoin).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .. import __version__, docgraph, docjoin, docsgraph, targets

ORDER = 47   # its place in brain --help's list of commands (brain.commands), after brain docs
USAGE_ORDER = 34   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain docgraph validate FILE... [--json] | checks [--json] | emit [--out FILE]   the documentation graph's contract,
                 docgraph/v1 (docs/docgraph.md): validate reads each document (any producer's) against the schema and
                 the rules a schema cannot say (ids unique and prefixed by their type, a source naming a file or a
                 tracker object, checks run and not run apart), notes what a reader keeps without judging (an edge to
                 an id the document does not hold, a producer's own check) and exits 1 when one is invalid or written
                 for a later version; checks lists the named checks, their subject, severity and meaning; emit
                 prints the project's documentation graph (brain.docsgraph: its doc sections, the nodes they cite,
                 the declared links, doc.stale and cycle run) as a docgraph/v1 document (--out: a file)
  brain docgraph pin PROJECT --from CLONE --ref REF --file PATH | join [--json] [--out FILE] [--no-own]
                 the documents of other projects, read only (docs/docgraph.md): pin reads an access: read project's
                 document from a local clone with git show at REF (never a checkout), validates it and writes its
                 pinned copy docgraph/PROJECT.json under the root (one key added: pinned, the commit read); join
                 reads the project's own graph and every docgraph/*.json (the pinned copies, the brain's own
                 documents), namespaces their ids by project (<type>:<project>/<id>), runs the named checks again
                 across the joined graph and prints each document and the findings (--json, --out: the joined
                 docgraph/v1 document); exit 1 when a document is left out or the join finds an error
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


def _emitted(args, root: Path) -> tuple[str, dict] | None:
    """(the project's name, its documentation graph as a docgraph/v1 document); None when its store has none."""
    from ._common import _project, _store
    from ._stores import _docs_catalogue
    store = _store(args, root)
    if not docsgraph.applies(store):
        return None
    project = _project(args, root)
    cat = _docs_catalogue(project, root, store)
    ref = docsgraph._git(root, "rev-parse", "HEAD").strip()
    doc = docsgraph.to_docgraph(cat, f"brain {__version__}", repo=cat.repo, ref=ref)
    return project.name, targets.add_to(doc, store, root, project.decision_logs or [project.decisions])


def _pin(args, root: Path) -> int:
    out, errors, notes = docjoin.pin(root, args.project_name, Path(args.source).resolve(), args.ref, args.file)
    for n in notes:
        print(f"note: {n}")
    for e in errors:
        print(f"error: {e}", file=sys.stderr)
    if out is None:
        return 1
    doc = docgraph.load(out)
    sm = docgraph.summary(doc)
    print(f"{out.relative_to(root.resolve()) if out.is_relative_to(root.resolve()) else out}: pinned at "
          f"{doc[docjoin.PINNED]['ref'][:12]}, {sum(sm['nodes'].values())} node(s), {sum(sm['edges'].values())} "
          "edge(s); commit it by PR")
    return 0


def _join(args, root: Path) -> int:
    own = None if args.no_own else _emitted(args, root)
    srcs = docjoin.sources(root, own)
    doc = docjoin.join(srcs, f"brain {__version__}")
    if args.out:
        Path(args.out).write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8",
                                  newline="\n")
    if args.json:
        print(json.dumps({"sources": [{"name": s.name, "path": s.path, "ok": s.ok, "ref": s.ref,
                                       "read_only": s.read_only, "errors": s.errors, "notes": s.notes}
                                      for s in srcs],
                          "checks": doc["checks"], "checks_run": doc["checks_run"],
                          "checks_not_run": doc["checks_not_run"]}, indent=2, ensure_ascii=False))
    else:
        print("\n".join(docjoin.summary_lines(srcs, doc)))
        if not srcs:
            print(f"no document: brain docgraph pin <project> ... writes {docjoin.DIR}/<project>.json")
    left_out = any(not s.ok for s in srcs)
    return 1 if left_out or any(f.get("severity") == "error" for f in doc["checks"]) else 0


def run(args, root: Path) -> int:
    """emit: the project's documentation graph as a docgraph/v1 document; pin, join: brain.docjoin."""
    if args.docgraph_cmd == "pin":
        return _pin(args, root)
    if args.docgraph_cmd == "join":
        return _join(args, root)
    from ._common import _store
    emitted = _emitted(args, root)
    if emitted is None:
        print(f"brain docgraph emit: {_store(args, root)} has no links graph (a schema with the Doc type, then brain "
              "sync)")
        return 1
    doc = emitted[1]
    errors, _ = docgraph.validate(doc, where="emit")
    for e in errors:   # the engine's own document holds to the contract: a failure here is the engine's bug
        print(f"error: {e}", file=sys.stderr)
    text = json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8", newline="\n")
        print(f"{args.out}: {len(doc['nodes'])} node(s), {len(doc['edges'])} edge(s), "
              f"{len(doc['checks'])} finding(s)")
    else:
        sys.stdout.write(text)
    return 1 if errors or any(f["severity"] == "error" for f in doc["checks"]) else 0


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
    de = ds.add_parser("emit", help="the project's documentation graph as a docgraph/v1 document; exit 1 on an error "
                                    "finding (a cycle of declared links)")
    de.add_argument("--out", default="", help="write it to this file instead of printing it")
    dp = ds.add_parser("pin", help="copy an access: read project's document from a local clone at a commit, "
                                   "validated, to docgraph/<project>.json (brain.docjoin)")
    dp.add_argument("project_name", metavar="PROJECT", help="an access: read project of the registry")
    dp.add_argument("--from", dest="source", required=True, help="a local clone of it (read with git show only)")
    dp.add_argument("--ref", required=True, help="the commit or tag to read the document at")
    dp.add_argument("--file", required=True, help="the document's path in that repository")
    dj = ds.add_parser("join", help="the project's graph and every docgraph/*.json as one graph, ids namespaced by "
                                    "project, the named checks run again across it; exit 1 when a document is left "
                                    "out or an error is found")
    dj.add_argument("--json", action="store_true", help="stable keys: sources, checks, checks_run, checks_not_run")
    dj.add_argument("--out", default="", help="write the joined docgraph/v1 document to this file")
    dj.add_argument("--no-own", action="store_true", help="leave the project's own graph out (the documents only)")
