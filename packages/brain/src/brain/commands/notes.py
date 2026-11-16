"""``brain notes``: the owner's notes home (brain.knowledge): init by plan, check, find."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .. import knowledge

ORDER = 435   # its place in brain --help's list of commands (brain.commands), after brain memory
USAGE_ORDER = 435   # its usage lines' place in brain --help's epilog, after brain memory's
RUNS_VIA = {   # brain perf --usage: how a subcommand that may never run from the CLI is reached (brain.adoption)
    "notes init": "on demand: the owner lays out a notes home once, by plan",
    "notes check": "on demand: before a pull request to the notes repo",
    "notes find": "on demand: the owner or an agent searches the notes, zero token",
}
USAGE = """\
  brain notes init DIR [--from VAULT] [--apply]   the notes home's layout, templates, .gitignore, README and agents'
                                  rules, as a plan; --apply writes it, never over a file that is there; --from copies
                                  an existing vault's notes into inbox/ and its other files into attachments/
  brain notes check [--dir DIR] [--json]   the notes' front matter against notes.schema.json, duplicate ids, Brain ids
                                  the graph does not hold, secrets, contact data outside people/, the folders git must
                                  not hold; exit 1 on an error
  brain notes find WORDS... [--confidential] [--scope ID] [--limit N] [--dir DIR] [--json]   the notes holding every
                                  word (SQLite FTS5, zero token): private folders only unless --confidential
"""
NO_PROJECT = {"notes"}   # its parsers that take no --project after them


def register(sub, ctx) -> None:
    no = sub.add_parser("notes", help="the owner's notes home: init by plan, check, find (zero token)").add_subparsers(
        dest="notes_cmd", required=True)
    ni = no.add_parser("init", help="lay out a notes home: a plan, then --apply (never overwrites)")
    ni.add_argument("dir", help="the notes home's folder (the private notes repo's checkout)")
    ni.add_argument("--from", dest="source", default="", help="an existing vault whose files are copied in (a copy, "
                                                               "never a move)")
    ni.add_argument("--apply", action="store_true", help="write the plan (without it: print it, write nothing)")
    ni.add_argument("--json", action="store_true", help="the plan or what was done, as JSON")
    nc = no.add_parser("check", help="check the notes: schema, ids, links, secrets, contact data, layout")
    nc.add_argument("--dir", default="", help="the notes home (default: config.json knowledge.path, else the "
                                              "registry's kind: knowledge entry)")
    nc.add_argument("--json", action="store_true", help="the findings as JSON")
    nf = no.add_parser("find", help="search the notes (SQLite FTS5, zero token)")
    nf.add_argument("words", nargs="+", help="every word must be in the note")
    nf.add_argument("--confidential", action="store_true", help="search daily/ and people/ too (never sealed/)")
    nf.add_argument("--scope", default="", help="only the notes of this scope id")
    nf.add_argument("--limit", type=int, default=20, help="at most this many notes (default 20)")
    nf.add_argument("--dir", default="", help="the notes home (default: as brain notes check)")
    nf.add_argument("--json", action="store_true", help="the notes found as JSON")


def _home(args) -> Path | None:
    if getattr(args, "dir", ""):
        return Path(args.dir).expanduser().resolve()
    return knowledge.home()


def _init(args) -> int:
    target = Path(args.dir).expanduser().resolve()
    source = Path(args.source).expanduser().resolve() if args.source else None
    why = knowledge.refuse_init(target, source)
    if why:
        print(f"brain notes init: {why}", file=sys.stderr)
        return 2
    steps = knowledge.plan(target, source)
    if not args.apply:
        if args.json:
            print(json.dumps([{"action": s.action, "path": s.path, "what": s.what} for s in steps], indent=2))
        else:
            print(f"brain notes init {target}: the plan (--apply writes it; nothing is ever overwritten)")
            print("\n".join("  " + s.line() for s in steps))
        return 0
    target.mkdir(parents=True, exist_ok=True)
    done = knowledge.apply(target, steps)
    if args.json:
        print(json.dumps(done, indent=2))
    else:
        print("\n".join(done))
        print(f"done: {target}. Commit it to the private notes repo; register it in projects.yaml (kind: knowledge) "
              "or config.json knowledge.path for brain notes check and find.")
    return 0


def early(args) -> int:
    """Machine-wide: the notes home is no project and holds no graph store."""
    if args.notes_cmd == "init":
        return _init(args)
    root = _home(args)
    if root is None or not root.is_dir():
        print("brain notes: no notes home: give --dir, set config.json knowledge.path, or register one in "
              "projects.yaml with kind: knowledge" + (f" ({root} is no folder)" if root else ""), file=sys.stderr)
        return 2
    if args.notes_cmd == "check":
        found = knowledge.check(root, knowledge.brain_ids())
        errors = [f for f in found if f.level == "error"]
        if args.json:
            print(json.dumps([vars(f) for f in found], indent=2))
        else:
            print("\n".join(f.line() for f in found) or f"{root}: no finding")
            if found:
                print(f"{len(errors)} error(s), {len(found) - len(errors)} warning(s)")
        return 1 if errors else 0
    hits = knowledge.find(root, " ".join(args.words), confidential=args.confidential, scope=args.scope,
                          limit=max(args.limit, 1))
    if args.json:
        print(json.dumps(hits, indent=2))
    else:
        for h in hits:
            print(f"{h['path']}  {h['title']}" + (f"  [{h['class']}]" if h["class"] != "private" else ""))
            if h["snippet"]:
                print(f"    {h['snippet']}")
        if not hits:
            print("no note holds every word")
    return 0
