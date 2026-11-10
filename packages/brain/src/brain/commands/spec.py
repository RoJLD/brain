"""``brain spec``: specs: one read back, a section at a time (brain.reads); the proposed ones turn active by
themselves once their decisions are taken (brain.specs)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .. import graph, reads, specs
from ._common import _print_json, _read_stores, _scope

ORDER = 60   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 60   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain spec show REF [--section N | --toc] [--json]   a spec by its Spec node id, a Doc id (doc:<repo>:<path>::<key>,
                 that section) or its path: the whole text, the section N names (its number 2.1, its key or the start
                 of its title, down to the next heading of its level), or --toc its headings with their keys
  brain spec activate [--write] [--all] [--json]   each proposed spec, ready or what keeps it proposed: a spec turns
                 active once a decision is recorded (a DDR names it in links.specs, or props.validated or decided),
                 every DDR naming it is answered and acked, it has no props.open, its document no unanswered question
                 and no line <!-- thinking: open[: note] --> outside code; props.keep_proposed opts out; --write
                 flips the ready ones (status, props.activated, props.activated_by), as brain sync does by itself
"""


def cmd_show(args, root: Path) -> int:
    """``brain spec show``: a spec, one of its sections or its headings (brain.reads)."""
    try:
        out = reads.spec_show(root, _read_stores(args, root), args.ref, args.section or "", toc=args.toc)
    except reads.ReadError as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 1
    if args.json:
        _print_json(out)
    elif args.toc:
        print(f"{out['file']}: {len(out['toc'])} heading(s); brain spec show {args.ref} --section KEY")
        print("\n".join(f"{'  ' * (h['level'] - 1)}{h['key']:<12} {h['title']}" for h in out["toc"]))
    else:
        print(f"<!-- {out['file']}" + (f" § {out['section']}" if out["section"] else "") + " -->")
        print(out["text"])
    return 0


def cmd_spec(args, root: Path) -> int:
    """``brain spec activate``: each proposed spec, ready or what keeps it proposed (brain.specs); --write turns the
    ready ones active, as brain sync and brain refresh do."""
    if args.all and args.write:
        raise SystemExit("brain: spec activate --write takes one project")
    out, rc = [], 0
    for p in _scope(args, root):
        stores = [s for s in (p.stores or [p.root / "notes" / "graph"]) if (s / "schema.yaml").is_file()] \
            if p.root.is_dir() else []
        for store in stores:
            rows = specs.readiness(p.root, store, full=True)
            if args.json:
                out.append({"project": p.name, "store": str(store), "specs": [r.as_dict() for r in rows]})
                continue
            if args.all:
                print(f"== {p.name}: {store}")
            written = []
            if args.write:
                try:
                    written = specs.activate(store, rows, via="brain spec activate")
                except graph.GraphError as exc:
                    print(f"brain: {exc}", file=sys.stderr)
                    rc = 1
            print("\n".join(specs.render(rows, written=bool(written))))
            if written:
                print("then brain sync and brain check")
    if args.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
    return rc


def register(sub, ctx) -> None:
    sc = sub.add_parser("spec", help="specs: the proposed ones turn active by themselves once their decisions are "
                                     "taken (brain.specs); show reads one").add_subparsers(dest="spec_cmd",
                                                                                           required=True)
    sw = sc.add_parser("show", help="a spec, one of its sections (--section) or its headings (--toc), instead of "
                                    "reading the file by hand")
    sw.add_argument("ref", help="a Spec node id, a Doc id (doc:<repo>:<path>::<key>) or the spec's path")
    how = sw.add_mutually_exclusive_group()
    how.add_argument("--section", help="its number (2.1), its key or the start of its title: down to the next "
                                       "heading of its level")
    how.add_argument("--toc", action="store_true", help="its headings, with the key --section takes")
    sw.add_argument("--json", action="store_true", help="{file, section, title, text, toc}")
    sa = sc.add_parser("activate", help="each proposed spec, ready (every DDR naming it answered and acked, no "
                                        "props.open, no unanswered question, no <!-- thinking: open --> marker in "
                                        "its document) or what keeps it proposed; --write turns the ready ones active")
    sa.add_argument("--write", action="store_true", help="turn the ready specs active (status, props.activated and "
                                                         "props.activated_by), as brain sync does")
    sa.add_argument("--all", action="store_true", help="every registered project's proposed specs (not --write)")
    sa.add_argument("--json", action="store_true", help="each store's proposed specs, ready or what they wait on")


def run(args, root: Path) -> int:
    return (cmd_show if args.spec_cmd == "show" else cmd_spec)(args, root)
