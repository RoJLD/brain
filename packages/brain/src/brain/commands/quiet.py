"""``brain quiet``: no interruption for a while; the notifications below critical are held, then summed up
(wi-brain-quiet-mode). Machine-wide: no root, no task paused."""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from .. import notify, projects, quiet

ORDER = 485   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 365   # its usage lines' place in brain --help's epilog
NO_PROJECT = ("quiet",)
USAGE = """\
  brain quiet [--for 2h | --off] [--dry-run]   silence the notifications below critical for a while (at most 7d), or
                 end it; what was held is summed up in one message per project when it ends; no task is paused, a
                 collector runs on; with no option: the state. Declared hours: notify: quiet_hours: "22:00-07:00"
"""


def early(args) -> int:
    try:
        now = datetime.now(timezone.utc)
        if args.off:
            ended = quiet.stop()
            print("quiet ended" if ended else "no manual quiet was running")
            _release(args.dry_run, now)
        elif args.for_:
            until = quiet.start(quiet.duration(args.for_), now)
            print(f"quiet until {until.astimezone():%Y-%m-%d %H:%M}: notifications below critical are held; every "
                  "task, collection included, keeps running; brain quiet --off ends it")
        else:
            _release(args.dry_run, now)
            print(quiet.line(quiet.summary(now=now)) or "not quiet: no manual quiet, no quiet_hours declared")
        return 0
    except (quiet.QuietError, notify.NotifyError) as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 2


def _release(dry_run: bool, now: datetime) -> None:
    try:
        reg = projects.load()
    except Exception:   # noqa: BLE001 (no registry: nothing to send the sum-up through)
        return
    for line in quiet.release(reg, now=now, dry_run=dry_run):
        print(line)


def register(sub, ctx) -> None:
    q = sub.add_parser("quiet", help="silence notifications below critical for a while; held, then summed up; no "
                                     "task paused")
    q.add_argument("--for", dest="for_", metavar="DURATION", help="90m, 2h, 1d (at most 7d)")
    q.add_argument("--off", action="store_true", help="end the quiet now and send the sum-up")
    q.add_argument("--dry-run", action="store_true", help="the sum-up is printed, not sent")
