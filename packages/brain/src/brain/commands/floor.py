"""``brain floor``: the locked floor held by the operating system (wi-brain-unadopted-floor, review rounds 6-7;
brain.floorlock): ``lock`` prints the plan and the command the owner runs elevated, ``lock --apply`` installs the
guard as a system component and writes the lock file (elevated only), ``unlock`` removes them, ``status`` says what
the guard holds. Machine-wide: no root."""

from __future__ import annotations

import sys

from .. import config, floorlock

ORDER = 487   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 367   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain floor lock [--apply] [--lower] | unlock [--apply] | status
                 the locked floor held by the operating system: lock prints the floor it locks, what it installs (the
                 guard's copy in Program Files, its hooks in Claude Code's managed settings, the lock file in
                 ProgramData) and the elevated command; --apply does it, in an elevated terminal only (--lower to lock
                 a lower floor than the locked one); unlock --apply removes them; status checks every file
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
        return 2
    print("\n".join(lines))
    return 0


def _unlock_plan() -> list[str]:
    from .. import floor
    lock = floor.read_lock()
    if lock is None:
        return ["no lock on this machine: nothing to unlock"]
    guard = lock.get("guard") or floor.guard_dir()
    managed = lock.get("managed") or floor.managed_file()
    return ["brain floor unlock --apply removes, in an elevated terminal (powershell -NoProfile; sudo):",
            f"  {managed}  the guard's managed hooks", f"  {guard}  the guard's copy",
            f"  {floor.lock_dir() / floor.LOCK_FILE}  the lock file",
            "The plugin's guard then judges again, from the user's profile."]


def register(sub, ctx) -> None:
    f = sub.add_parser("floor", help="the locked floor held by the operating system: lock (plan, --apply elevated), "
                                     "unlock, status")
    fs = f.add_subparsers(dest="floor_cmd", required=True)
    lock = fs.add_parser("lock", help="print the plan and the elevated command; --apply locks (elevated only)")
    lock.add_argument("--apply", action="store_true", help="install the guard's copy and its managed hooks, write "
                                                           "the lock file (an elevated terminal only)")
    lock.add_argument("--lower", action="store_true", help="allow a lower floor than the locked one")
    unlock = fs.add_parser("unlock", help="print what unlock removes; --apply does it (elevated only)")
    unlock.add_argument("--apply", action="store_true", help="remove the managed hooks, the guard's copy and the "
                                                           "lock file")
    fs.add_parser("status", help="the floor, the lock file, and whether a session can change what they hold")
