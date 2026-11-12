"""``brain catalogue``: the module catalogue's contract, catalogue/v1 (brain.catalogue; docs/catalogue.md). ``validate``
checks documents any program emitted against it and needs no brain; ``emit`` prints the brain's own catalogue (its
registry's modules, else the engine's capabilities) as a catalogue/v1 document.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .. import __version__, catalogue

ORDER = 254   # its place in brain --help's list of commands (brain.commands): after mod, spool and session-archive
USAGE_ORDER = 252   # its usage lines' place in brain --help's epilog, after brain mod's
USAGE = """\
  brain catalogue validate FILE... [--json] | emit [--out FILE]   the module catalogue's contract, catalogue/v1
                 (docs/catalogue.md): validate reads each document (any producer's) against the schema and the rules
                 a schema cannot say (ids unique, every module, brick, distribution and base preset named resolved, no
                 cycle of hard dependencies, no planned module in a preset), notes what a reader keeps (a soft
                 dependency on another catalogue's module, what a preset pulls) and exits 1 when one is invalid or
                 written for a later version; emit prints the brain's catalogue (brain mod's modules, their
                 dependencies, requirements, costs, fallbacks and licence, the engine and its extras, the presets
                 Lite, Default and Recommended) as a catalogue/v1 document (--out: a file)
"""


def _check(name: str) -> dict:
    """One file's result: file, ok, errors, notes, summary (None for a file not read or a later version)."""
    try:
        doc = catalogue.load(Path(name))
    except catalogue.CatalogueError as exc:
        return {"file": name, "ok": False, "errors": [str(exc)], "notes": [], "summary": None}
    errors, notes = catalogue.validate(doc, where=name)
    return {"file": name, "ok": not errors, "errors": errors, "notes": notes,
            "summary": None if errors and catalogue.newer(doc) else catalogue.summary(doc)}


def _print(r: dict) -> None:
    s = r["summary"] or {}
    counts = (f": {s.get('modules', 0)} module(s), {s.get('distributions', 0)} distribution(s), presets "
              f"{', '.join(s.get('presets') or []) or 'none'}") if s else ""
    print(f"{r['file']}: {'OK' if r['ok'] else 'INVALID'}{counts}")
    for e in r["errors"]:
        print(f"  error: {e}")
    for n in r["notes"]:
        print(f"  note: {n}")


def _validate(files: list[str], as_json: bool) -> int:
    out = [_check(name) for name in files]
    if as_json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        for r in out:
            _print(r)
    return 1 if any(not r["ok"] for r in out) else 0


def early(args):
    """validate runs without a root (another program's documents)."""
    if args.catalogue_cmd == "validate":
        return _validate(args.files, args.json)
    return None


def run(args, root: Path) -> int:
    """emit: the brain's catalogue as a catalogue/v1 document."""
    doc = catalogue.emit(root, f"brain {__version__}")
    errors, _ = catalogue.validate(doc, where="emit")
    for e in errors:   # the engine's own document holds to the contract: a failure here is the engine's bug
        print(f"error: {e}", file=sys.stderr)
    text = json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8", newline="\n")
        print(f"{args.out}: {len(doc['modules'])} module(s), {len(doc['distributions'])} distribution(s), "
              f"presets {', '.join(p['id'] for p in doc['presets'])}")
    else:
        sys.stdout.write(text)
    return 1 if errors else 0


def register(sub, ctx) -> None:
    cg = sub.add_parser("catalogue", help="the module catalogue's contract, catalogue/v1: validate documents, emit the "
                                          "brain's own (brain.catalogue)")
    cs = cg.add_subparsers(dest="catalogue_cmd", required=True)
    cv = cs.add_parser("validate", help="exit 1 when a document does not hold to catalogue/v1 or is written for a "
                                        "later version")
    cv.add_argument("files", nargs="+", metavar="FILE", help="a catalogue/v1 JSON document")
    cv.add_argument("--json", action="store_true", help="stable keys: file, ok, errors, notes, summary")
    ce = cs.add_parser("emit", help="the brain's catalogue (its modules, distributions and presets) as a catalogue/v1 "
                                    "document")
    ce.add_argument("--out", default="", help="write it to this file instead of printing it")
