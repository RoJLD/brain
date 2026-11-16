"""``brain ship <pr>``: a local merge queue. The session queues its PR and stops; ``brain ship --run``, the merger,
catches each PR up with main, checks it and merges it under one lock (brain.ship, brain.filelock).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ORDER = 503   # its place in brain --help's list of commands (brain.commands), after merge-ready
USAGE_ORDER = 162
USAGE = """\
  brain ship PR [--repo-dir D] [--slug OWNER/NAME] [--remote R] [--json]   the local merge queue: the PR queued
                        once under <BRAIN_HOME>/ship/queue.json (its repo's main checkout, its title and branch as gh
                        reads them; gh down, it is queued all the same), its place said, exit 0; the session stops
  brain ship --list [--json]   the queue as a Markdown table (or JSON), and the merger's lock when it is held
  brain ship --run [--batch N] [--dry-run] [--json]   the merger: the lock <BRAIN_HOME>/locks/ship.lock (exit 1 and
                        its holder when another merger holds it; a stale one broken), then each queued PR in order:
                        the merge gate (brain merge-ready's checks, its fresh check answered by the catch-up), main
                        merged in, the views regenerated once and brain check, merge-check, the targeted tests, the
                        catch-up pushed, gh pr merge --match-head-commit; a PR that fails is marked and the next
                        goes on; every N merged per repo (5), the full suite once, a bisection naming the culprit
                        when it fails, and the run stops. --dry-run: the plan, nothing run. Exit 1 when a PR failed
"""


def _out(args, data: dict, lines: list[str]) -> None:
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=1))
    else:
        print("\n".join(lines))


def _list(args) -> int:
    from .. import filelock, ship
    rows = ship.entries()
    held = ship.lock_holder()
    lines = ship.table(rows) if rows else [f"brain ship: the queue is empty ({ship.queue_path()})"]
    if held:
        lines.append(f"the merger runs: {filelock.describe(held)}")
    _out(args, {"queue": str(ship.queue_path()), "entries": rows, "lock": held or None}, lines)
    return 0


def _run(args) -> int:
    from .. import filelock, ship
    if args.dry_run:
        lines = ship.plan(args.batch)
        _out(args, {"dry_run": True, "plan": lines}, lines)
        return 0
    say = (lambda line: print(line, file=sys.stderr)) if args.json else print
    try:
        rep = ship.merge_queue(args.batch, say=say)
    except filelock.Held as exc:
        print(f"brain ship: another merger runs: {filelock.describe(exc.holder)}", file=sys.stderr)
        return 1
    except (filelock.LockError, ship.stateio.StateError) as exc:
        print(f"brain ship: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(rep.to_json(), ensure_ascii=False, indent=1))
    elif not rep.done:
        print("brain ship: nothing queued")
    if rep.stopped:
        print(f"brain ship: {rep.stopped}", file=sys.stderr)
    return 0 if rep.ok else 1


def _queue(args) -> int:
    from .. import filelock, ship
    try:
        e, added, (at, total), warnings = ship.queue_pr(args.pr, Path(args.repo_dir or ".").resolve(),
                                                        args.slug or "", args.remote or "origin")
    except (ship.ShipError, filelock.Held, filelock.LockError, ship.stateio.StateError) as exc:
        print(f"brain ship: {exc}", file=sys.stderr)
        return 1
    for w in warnings:
        print(f"brain ship: warning: {w}", file=sys.stderr)
    status = e.get("status")
    if status == "merged":
        line = f"{e['repo']}#{e['pr']} is already merged by the queue"
    else:
        line = (f"{'queued' if added else 'already queued'}: {e['repo']}#{e['pr']} {ship.cell(e.get('title'))}"
                f" (place {at} of {total} for {e['repo']}); the merger takes it at its next run (brain ship --run)")
    _out(args, {**e, "added": added, "place": at, "of": total}, [line])
    return 0


def early(args) -> int:
    """A machine-wide queue: no project root needed."""
    modes = [bool(args.pr), args.list, args.run]
    if sum(modes) != 1:
        print("brain ship: give one of PR, --list or --run", file=sys.stderr)
        return 2
    if (args.batch is not None or args.dry_run) and not args.run:
        print("brain ship: --batch and --dry-run go with --run", file=sys.stderr)
        return 2
    if args.batch is not None and args.batch < 1:
        print("brain ship: --batch is 1 or more", file=sys.stderr)
        return 2
    if args.batch is None:
        from ..ship import BATCH
        args.batch = BATCH
    if args.list:
        return _list(args)
    return _run(args) if args.run else _queue(args)


def register(sub, ctx) -> None:
    s = sub.add_parser("ship", help="the local merge queue: queue a PR and stop; --run, the merger, catches each PR "
                                    "up with main, checks it and merges it under one lock",
                       description="The local merge queue. brain ship PR queues the PR once "
                                   "(BRAIN_HOME/ship/queue.json) and says its place; brain ship --run, the merger, "
                                   "takes BRAIN_HOME/locks/ship.lock and ships each queued PR in order: the merge gate "
                                   "(its fresh check answered by the catch-up), main merged in with the merge driver, "
                                   "the views and brain check, merge-check, the targeted tests, the catch-up pushed, "
                                   "gh pr merge --match-head-commit. A PR that fails is marked and the next goes on; "
                                   "every N PRs merged per repo the full suite runs once, and a bisection names the "
                                   "culprit. Starting the merger as a service is the owner's decision.")
    s.add_argument("pr", nargs="?", default="", help="the PR to queue: its number or URL")
    s.add_argument("--repo-dir", metavar="D", help="a checkout (or worktree) of the PR's repo (default: here)")
    s.add_argument("--slug", metavar="OWNER/NAME", help="the GitHub repo (default: the remote's)")
    s.add_argument("--remote", help="the remote the merger fetches and pushes (default: origin)")
    s.add_argument("--list", action="store_true", help="the queue, and the merger's lock when held")
    s.add_argument("--run", action="store_true", help="the merger: take the lock and ship the queued PRs in order")
    s.add_argument("--batch", type=int, metavar="N", help="--run: the full suite once every N PRs merged per repo "
                                                          "(default 5)")
    s.add_argument("--dry-run", action="store_true", help="--run: say what it would do, run nothing")
    s.add_argument("--json", action="store_true")
