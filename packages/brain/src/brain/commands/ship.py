"""``brain ship <pr>``: a local merge queue. The session queues its PR and stops; ``brain ship --run``, the merger,
catches each PR up with main, checks it and merges it under one lock (brain.ship, brain.filelock).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ORDER = 503   # its place in brain --help's list of commands (brain.commands), after merge-ready
PHASE = "early"   # its handlers: early only, before any root is resolved (brain.commands)
USAGE_ORDER = 162
USAGE = """\
  brain ship PR [--repo-dir D] [--slug OWNER/NAME] [--remote R] [--json]   the local merge queue: the PR queued
                        once under <BRAIN_HOME>/ship/queue.json (its repo's main checkout, its title and branch as gh
                        reads them; gh down, it is queued all the same; a PR of another repo than the checkout's
                        remote refused), its place said, exit 0; the session stops. No --project nor --root: the
                        checkout is --repo-dir or here
  brain ship --list [--json]   the queue as a Markdown table (or JSON), the red bases, the merger's lock when held
  brain ship --run [--batch N] [--force] [--dry-run] [--json]   the merger: the lock <BRAIN_HOME>/locks/ship.lock
                        (exit 1 and its holder when another merger holds it; a stale one broken), then each queued PR
                        in order: the merge gate (its fresh check answered by the catch-up, a no-CI repo's ci by the
                        local checks below; a fork PR or a branch that is the base refused), main merged in, the
                        views regenerated once and brain check, merge-check, the targeted tests (--strict); a
                        caught-up head gets the public check before its push, its CI awaited (none for a no-CI repo)
                        and the gate again with nothing waived; gh pr merge --match-head-commit, the PR read back. A
                        PR that fails is marked and the next goes on; every N merged per repo and base (5), the full
                        suite once, a confirmed bisection naming the culprit when it fails, the base marked red (its
                        PRs wait; --force ships them) and the run stops.
                        --dry-run: the plan, nothing run. Exit 1 when a PR failed or waits
"""


def _out(args, data: dict, lines: list[str]) -> None:
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=1))
    else:
        print("\n".join(lines))


def _fail(args, msg: str, rc: int = 1) -> int:
    """A refusal: on stderr, and as ``{"ok": false, "error"}`` on stdout under --json."""
    print(f"brain ship: {msg}", file=sys.stderr)
    if getattr(args, "json", False):
        print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    return rc


def _errors():
    from .. import filelock, ship
    return ship.ShipError, filelock.Held, filelock.LockError, ship.stateio.StateError, OSError


def _list(args) -> int:
    from .. import filelock, ship
    rows = ship.entries()
    held = ship.lock_holder()
    reds = ship.red()
    lines = ship.table(rows) if rows else [f"brain ship: the queue is empty ({ship.queue_path()})"]
    lines += [f"red: {k}: {ship.cell(v.get('detail'))} (its PRs wait; brain ship --run --force ships them)"
              for k, v in reds.items()]
    if held:
        lines.append(f"the merger runs: {filelock.describe(held)}")
    _out(args, {"queue": str(ship.queue_path()), "entries": rows, "red": reds, "lock": held or None}, lines)
    return 0


def _run(args) -> int:
    from .. import filelock, ship
    if args.dry_run:
        lines = ship.plan(args.batch)
        _out(args, {"dry_run": True, "plan": lines}, lines)
        return 0
    say = (lambda line: print(line, file=sys.stderr)) if args.json else print
    try:
        rep = ship.merge_queue(args.batch, say=say, force=args.force)
    except filelock.Held as exc:
        return _fail(args, f"another merger runs: {filelock.describe(exc.holder)}")
    except _errors() as exc:
        return _fail(args, str(exc))
    if args.json:
        print(json.dumps(rep.to_json(), ensure_ascii=False, indent=1))
    elif not rep.done and not rep.waiting:
        print("brain ship: nothing queued")
    if rep.stopped:
        print(f"brain ship: {rep.stopped}", file=sys.stderr)
    return 0 if rep.ok else 1


def _queue(args) -> int:
    from .. import ship
    try:
        e, added, (at, total), warnings = ship.queue_pr(args.pr, Path(args.repo_dir or ".").resolve(),
                                                        args.slug or "", args.remote or "origin")
    except _errors() as exc:
        return _fail(args, str(exc))
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
    if getattr(args, "project", None) or getattr(args, "root", None):
        return _fail(args, "--project and --root do not name a PR's repo here: run it from a checkout of the PR's "
                           "repo, or give --repo-dir D", 2)
    modes = [bool(args.pr), args.list, args.run]
    if sum(modes) != 1:
        return _fail(args, "give one of PR, --list or --run", 2)
    if (args.batch is not None or args.dry_run or args.force) and not args.run:
        return _fail(args, "--batch, --force and --dry-run go with --run", 2)
    if args.batch is not None and args.batch < 1:
        return _fail(args, "--batch is 1 or more", 2)
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
                                   "the views and brain check, merge-check, the targeted tests; a caught-up head is "
                                   "stamped by the public check, pushed, its CI awaited and gated again; then gh pr "
                                   "merge --match-head-commit. A PR that fails is marked and the next goes on; every "
                                   "N PRs merged per repo and base the full suite runs once, and a confirmed "
                                   "bisection names the culprit. Starting the merger as a service is the owner's "
                                   "decision.")
    s.add_argument("pr", nargs="?", default="", help="the PR to queue: its number or URL")
    s.add_argument("--repo-dir", metavar="D", help="a checkout (or worktree) of the PR's repo (default: here)")
    s.add_argument("--slug", metavar="OWNER/NAME", help="the GitHub repo (default: the remote's; another is refused)")
    s.add_argument("--remote", help="the remote the merger fetches and pushes (default: origin)")
    s.add_argument("--list", action="store_true", help="the queue, the red bases, and the merger's lock when held")
    s.add_argument("--run", action="store_true", help="the merger: take the lock and ship the queued PRs in order")
    s.add_argument("--batch", type=int, metavar="N", help="--run: the full suite once every N PRs merged per repo "
                                                          "and base (default 5)")
    s.add_argument("--force", action="store_true", help="--run: ship the PRs of a base whose last full suite was red")
    s.add_argument("--dry-run", action="store_true", help="--run: say what it would do, run nothing")
    s.add_argument("--json", action="store_true")
