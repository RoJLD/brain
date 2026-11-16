"""``brain floor``: the locked floor held by the operating system (wi-brain-unadopted-floor, review rounds 6-8;
brain.floorlock): ``lock`` prints the plan and the command line the owner runs elevated (Win+R, no shell), ``lock
--apply`` installs the guard as a system component and writes the lock file (elevated only), ``unlock`` removes them,
``status`` says what the guard holds. Machine-wide: no root."""

from __future__ import annotations

import sys

from .. import config, floorlock

ORDER = 487   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 367   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain floor lock [--apply] [--lower] [--wait] | unlock [--apply] [--wait] | status
                 the locked floor held by the operating system: lock prints the floor it locks, what it installs (the
                 guard's copy in Program Files, its hooks in Claude Code's managed settings, the lock file in
                 ProgramData) and the command line to run elevated from Win+R; --apply does it, elevated only (--lower
                 to lock a lower floor than the locked one; --wait keeps the window open on the result); unlock
                 --apply removes them; status checks every file and says whether the managed hooks are in force
"""


def early(args) -> int:
    try:
        cfg = config.load()
        if args.floor_cmd == "status":
            lines = floorlock.status(cfg)
        elif args.floor_cmd == "unlock":
            lines = floorlock.unlock() if args.apply else _unlock_plan()
        elif args.apply:
            lines = floorlock.apply(cfg, lower=args.lower)
        else:
            lines = floorlock.render_plan(floorlock.plan(cfg))
    except floorlock.LockError as exc:
        print(f"brain floor: {exc}", file=sys.stderr)
        return _wait(args, 2)
    print("\n".join(lines))
    return _wait(args, 0)


def _wait(args, code: int) -> int:
    """--wait: the window Win+R opened stays on the result until Enter."""
    if getattr(args, "wait", False):
        try:
            input("Press Enter to close this window. ")
        except (EOFError, OSError):
            pass
    return code


def _unlock_plan() -> list[str]:
    from .. import floor
    lock = floor.read_lock()
    if lock is None and not floor.guard_dir().exists():
        return ["no lock on this machine: nothing to unlock"]
    p = {"installed": lock if floorlock._installed(lock) else None}
    return ["brain floor unlock --apply removes, elevated: the lock file "
            f"({floor.lock_dir() / floor.LOCK_FILE}) and the managed hooks ({floor.managed_file()}) together, then the "
            f"guard's copies ({floor.guard_dir()}). The plugin's guard then judges again, from the user's profile.",
            *floorlock.runbook(floorlock.run_command(p, "unlock"))]


def register(sub, ctx) -> None:
    f = sub.add_parser("floor", help="the locked floor held by the operating system: lock (plan, --apply elevated), "
                                     "unlock, status")
    fs = f.add_subparsers(dest="floor_cmd", required=True)
    lock = fs.add_parser("lock", help="print the plan and the elevated command line; --apply locks (elevated only)")
    lock.add_argument("--apply", action="store_true", help="install the guard's copy and its managed hooks, write "
                                                           "the lock file (elevated only)")
    lock.add_argument("--lower", action="store_true", help="allow a lower floor than the locked one")
    lock.add_argument("--wait", action="store_true", help="wait for Enter before closing (the Win+R window)")
    unlock = fs.add_parser("unlock", help="print what unlock removes and its command line; --apply does it (elevated "
                                          "only)")
    unlock.add_argument("--apply", action="store_true", help="remove the lock file and the managed hooks, then the "
                                                             "guard's copies")
    unlock.add_argument("--wait", action="store_true", help="wait for Enter before closing (the Win+R window)")
    fs.add_parser("status", help="the floor, the lock file, whether the managed hooks are in force, and whether a "
                                 "session can change what they hold")
