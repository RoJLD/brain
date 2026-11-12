"""``brain digest``: the digest: what happened in a window (milestones, closed items, ADRs, DDRs, merged PRs, session
records, journal), newest first, at zero token.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import digest, resume
from ._common import _scope

ORDER = 310   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 350   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain digest [--project P | --all | --scope REF] [--since WHEN] [--until WHEN] [--budget N] [--write] [--offline]
                 [--json] the digest: what happened in a window, newest first, from the graph (milestones reached, items
                 closed), the ADRs, the DDRs, the SRs, gh (merged PRs; --offline skips them) and the journal; WHEN is
                 YYYY-MM-DD, today, yesterday, last-week, last-month or a reached milestone's id (default: last-week
                 to today); --budget lowers the sections from full text to one line each to counts, the journal
                 first (default 4000 tokens, 0: no limit); --write keeps it in
                 <BRAIN_HOME>/digest/<project>/<since>_<until>.md, which the resume pack names; --json: the records
"""


def cmd_digest(args, root: Path) -> int:
    """The digest of the project (or of every registered project with --all) over a window; printed (the records
    with --json), and kept in <BRAIN_HOME>/digest/<project>/ with --write. A window that does not resolve (a
    milestone not reached, unknown in that project) fails that project only."""
    many = args.all or bool(args.scope)   # --scope REF: the projects of a node's subtree (brain.scopes)
    scope = _scope(args, root) if many else [getattr(args, "project_obj", None) or resume.project_for(root)]
    texts, data, rc = [], [], 0
    for p in scope:
        if not p.root.is_dir():
            print(f"== {p.name}: {p.root} not found, skipped", file=sys.stderr)
            continue
        try:
            d = digest.gather(p, args.since, args.until, offline=args.offline)
        except digest.DigestError as exc:
            print(f"brain digest: {p.name}: {exc}", file=sys.stderr)
            rc = 1
            continue
        text = digest.render(p, d, budget=args.budget)
        if args.write:
            out = digest.write(p.name, d, text)
            print(f"digest: {p.name} -> {out} (~{resume.tokens(text)} tokens)", file=sys.stderr)
        texts.append(text)
        data.append(d)
    if args.json:
        print(json.dumps(data if many else (data[0] if data else None), ensure_ascii=False, indent=1))
    else:
        print("\n".join(texts), end="")
    return rc


def register(sub, ctx) -> None:
    dg = sub.add_parser("digest", help="the digest: what happened in a window (milestones, closed items, ADRs, DDRs, "
                                       "merged PRs, session records, journal), newest first, at zero token")
    dg.add_argument("--project", default=argparse.SUPPRESS, help="a registered project (same as brain --project)")
    dg.add_argument("--all", action="store_true", help="every project of the registry, one digest each")
    dg.add_argument("--scope", help="the projects of a node's subtree in the scope tree (brain scopes): an id, a path "
                    "of ids, global (= --all), . or ..; one digest each")
    dg.add_argument("--since", default="last-week", help=f"first day included: {digest.WHEN} (the day it was "
                                                         "reached); default last-week, seven days before today")
    dg.add_argument("--until", default="today", help="last day included, same forms (default today)")
    dg.add_argument("--budget", type=int, default=digest.BUDGET,
                    help=f"tokens (~{resume.CHARS_PER_TOKEN} characters each): sections lowered from full text to "
                         f"one line each to counts, the journal first, then lines cut from the end; 0: no limit "
                         f"(default {digest.BUDGET})")
    dg.add_argument("--write", action="store_true", help="also keep it in <BRAIN_HOME>/digest/<project>/"
                                                         "<since>_<until>.md (the resume pack names the latest)")
    dg.add_argument("--offline", action="store_true", help="do not ask gh for the merged PRs")
    dg.add_argument("--json", action="store_true", help="print the records gathered (before any condensing) as JSON")


run = cmd_digest
