"""``brain gate``: the pre-push checks of a branch in one call, each step's log in a file, a three-line verdict
(brain.gate)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ORDER = 504   # its place in brain --help's list of commands (brain.commands), after ship
USAGE_ORDER = 163
PHASE = "early"   # its handlers: early only, before any root is resolved (brain.commands)
USAGE = """\
  brain gate [--base REF] [--repo-dir D] [--skip STEP]... [--strict] [--fail-fast] [--python PY] [-n N]
             [--logs DIR] [--store DIR] [--json]
                        the pre-push checks in one call, on the checkout here (or --repo-dir): clean (nothing left
                        out of HEAD, untracked files included), merge-check (a fresh base merged in, nothing of it
                        lost), review (HEAD's review stamp, no finding open), views (a graph store's
                        views regenerated and checked: brain refresh --offline), audit (brain audit --diff: 0 NEW, 0
                        LEFT; --store: a worktree's code store), public (a public repo's HEAD stamped by brain check
                        --public --history), tests (brain test --changed; --strict runs the whole suite when the
                        selection widens). Each step's log in <temp>/brain-gate/<run>/ (or --logs), then three lines:
                        what passed, what failed and why, the next command. Exit 0 only when every step that applies
                        passes (a --skip says INCOMPLETE, exit 1); 2 when it cannot start (not a git checkout, a
                        --base found neither here nor on its remote). --python: the tests' interpreter (the brain
                        steps run with this engine); a remote --base (origin/main) is fetched again
"""


def early(args) -> int:
    """Any checkout of a git repo: no project root needed (the steps find theirs)."""
    from .. import gate
    from ..inventory import AuditError, git
    try:
        top = Path(git(Path(args.repo_dir or getattr(args, "root", None) or ".").resolve(),
                       "rev-parse", "--show-toplevel").strip()).resolve()
        g = gate.Gate(top, args.base or "", skip=tuple(args.skip or ()), strict=args.strict,
                      fail_fast=args.fail_fast, python=args.python or "", workers=args.workers or "",
                      logs=Path(args.logs).resolve() if args.logs else None, store=args.store or "",
                      say=None if args.json else (lambda line: print(line, file=sys.stderr, flush=True)))
    except (AuditError, gate.GateError, OSError) as exc:
        print(f"brain gate: {exc}", file=sys.stderr)
        return 2
    report = g.run()
    if args.json:
        print(json.dumps(report.to_json(), ensure_ascii=False, indent=1))
    else:
        print("\n".join(report.lines()))
    return 0 if report.ok else 1


def register(sub, ctx) -> None:
    from ..gate import STEPS
    g = sub.add_parser("gate", help="the pre-push checks in one call (clean, merge-check, review, views, audit, "
                                    "public, tests): each step's log in a file, a three-line verdict; exit 0 only "
                                    "when all pass")
    g.add_argument("--base", metavar="REF", help="the base (default: origin's default branch); a remote one "
                                                 "(origin/main) fetched again first")
    g.add_argument("--repo-dir", metavar="D", help="the checkout (default: the current folder)")
    g.add_argument("--skip", action="append", choices=STEPS, metavar="STEP",
                   help=f"skip a step on purpose (repeatable): the verdict says INCOMPLETE, exit 1: "
                        f"{', '.join(STEPS)}")
    g.add_argument("--strict", action="store_true", help="tests: the whole suite when the selection widens")
    g.add_argument("--fail-fast", action="store_true", help="stop at the first step that fails")
    g.add_argument("--python", default="", help="the Python that runs the tests (default: this one; the brain "
                                                "steps always run with the engine running the gate)")
    g.add_argument("-n", dest="workers", default="", metavar="N", help="tests: pytest-xdist workers (auto, 8...)")
    g.add_argument("--logs", metavar="DIR", help="the folder of this run's logs (default: <temp>/brain-gate/<run>)")
    g.add_argument("--store", metavar="DIR", help="audit: a code store in a worktree (a change across two repos)")
    g.add_argument("--json", action="store_true", help="the report as JSON (the steps, their logs, the verdict)")
