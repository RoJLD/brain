"""``brain schedule``: the brain commands a machine's scheduler runs (projects.yaml schedules:): the plan, installed
with --apply.
"""

from __future__ import annotations

from ._common import root_of

ORDER = 470   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 380   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain schedule install [--apply] [--json]   the brain commands the registry's schedules: declare for this machine
                 (the alerts pass every 15 minutes and at logon, a daily canary), as a plan, then installed with
                 --apply: the Task Scheduler (its Brain folder, the user's session, no console window) on Windows, a
                 systemd user timer on Linux (else the user's crontab); what this machine installed and no longer
                 declares is removed; the installer's schedule step runs it (creating a task is {owner}'s apply)
  brain schedule list [--json]   every scheduled task of every project, one view: the declared schedules (whether
                 each runs here and is installed) and the tasks found in a project's scheduler folders (alerts:
                 scheduler:), each with its cadence, window (hidden or visible), enabled, its project's quiet hours
                 (notifications held, the task runs), a collector's floor, its last run, where its value lives and how
                 it changes; then the alerts pass's dead-man: SILENT when its last pass is older than two cadences
                 (the SessionStart health hook and brain status's alerts row say so)
  brain schedule set NAME [--every D|none] [--at HH:MM|none] [--days mon,fri|none] [--visible|--hidden]
                 [--enable|--disable] [--apply] [--json]   a declared schedule's change, as a plan (its line before
                 and after) in the file that declares it (the registry or the project's schedules file), written by
                 --apply, its comments and other lines kept; a collector's floor refuses a slower every and a
                 --disable; nothing is installed: brain schedule install --apply then (the owner's)
"""


def register(sub, ctx) -> None:
    sc = sub.add_parser("schedule", help="the brain commands a machine's scheduler runs (projects.yaml schedules:): "
                                         "the plan, installed with --apply").        add_subparsers(dest="schedule_cmd", required=True)
    sci = sc.add_parser("install", help="the schedules declared for this machine, as a plan; --apply creates, updates "
                                        "and removes them (the Task Scheduler, systemd --user or crontab)")
    sci.add_argument("--apply", action="store_true", help="change the scheduler (idempotent)")
    sci.add_argument("--json", action="store_true")
    scl = sc.add_parser("list", help="every declared schedule, here or not, installed or not; the alerts pass's "
                                     "dead-man")
    scl.add_argument("--json", action="store_true")
    scs = sc.add_parser("set", help="a declared schedule's change in the file that declares it: the plan, written "
                                    "with --apply (nothing installed)")
    scs.add_argument("name", help="the schedule's name (brain schedule list)")
    scs.add_argument("--every", metavar="D", help="its cadence (1m to 1d: 15m, 1h), or none")
    scs.add_argument("--at", metavar="HH:MM", help="its daily time, or none")
    scs.add_argument("--days", metavar="DAYS", help="the days --at runs on (mon,fri), or none for every day")
    vis = scs.add_mutually_exclusive_group()
    vis.add_argument("--visible", dest="visible", action="store_const", const=True,
                     help="a console window when it runs")
    vis.add_argument("--hidden", dest="visible", action="store_const", const=False,
                     help="no console window (the default)")
    on = scs.add_mutually_exclusive_group()
    on.add_argument("--enable", dest="enabled", action="store_const", const=True)
    on.add_argument("--disable", dest="enabled", action="store_const", const=False,
                    help="removed from its machines at the next install (a collector's floor refuses it)")
    scs.add_argument("--apply", action="store_true", help="write the file (the scheduler is not changed)")
    scs.add_argument("--json", action="store_true")


def early(args) -> int:
    """The machine's scheduler: schedule names are global, any project's registry."""
    root = root_of(args)
    from .. import schedule
    return schedule.main(args.schedule_cmd, getattr(args, "apply", False), root, args.json, args)
