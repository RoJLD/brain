"""``brain floor``: the locked floor held by the operating system (wi-brain-unadopted-floor, review round 6;
brain.floorlock): ``lock`` prints the plan, ``lock --apply`` applies it (elevated only), ``lock --refresh`` fast-forwards
the locked checkout first, ``unlock`` gives everything back, ``status`` says what the guard holds. Machine-wide: no
root."""

from __future__ import annotations

import sys

from .. import config, floorlock

ORDER = 487   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 367   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain floor lock [--apply] [--refresh] | unlock [--apply] | status
                 the locked floor held by the operating system: lock prints what it gives to the administrators
                 (config.json's checkout, the pointer, the guard's venv and code, the plugin that carries guard.sh, the
                 machine's lock file) and the commands; --apply runs them, in an elevated terminal only; --refresh
                 fast-forwards the checkout to origin/main first; status says whether a session can change them
"""


def early(args) -> int:
    try:
        cfg = config.load()
        if args.floor_cmd == "status":
            lines = floorlock.status(cfg)
        elif args.floor_cmd == "unlock":
            lines = floorlock.unlock() if args.apply else _unlock_plan()
        elif args.apply or args.refresh:
            if args.refresh and not args.apply:
                print("brain floor lock --refresh: the plan below; --apply --refresh runs it", file=sys.stderr)
                lines = floorlock.render_plan(floorlock.plan(cfg), refresh=True)
            else:
                lines = floorlock.apply(cfg, refresh=args.refresh)
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
    if lock.get("error"):
        return [f"the lock file cannot be read ({lock['error']})"]
    rows = [f"  {r.get('kind', 'tree'):4}  {r.get('path')}" for r in lock.get("roots") or [] if isinstance(r, dict)]
    return ["brain floor unlock gives these back to the user and removes the lock file:", *rows,
            f"  tree  {floor.lock_dir()}", "Run it elevated: brain floor unlock --apply"]


def register(sub, ctx) -> None:
    f = sub.add_parser("floor", help="the locked floor held by the operating system: lock (plan, --apply elevated), "
                                     "unlock, status")
    fs = f.add_subparsers(dest="floor_cmd", required=True)
    lock = fs.add_parser("lock", help="print the plan; --apply locks (elevated only)")
    lock.add_argument("--apply", action="store_true", help="give the paths to the administrators and write the lock "
                                                           "file (an elevated terminal only)")
    lock.add_argument("--refresh", action="store_true", help="fetch the checkout and fast-forward it to origin/main "
                                                             "before locking (a change merged on the personal brain)")
    unlock = fs.add_parser("unlock", help="print what unlock gives back; --apply does it (elevated only)")
    unlock.add_argument("--apply", action="store_true", help="give the paths back and remove the lock file")
    fs.add_parser("status", help="the floor, the lock file, and whether a session can change what they hold")
