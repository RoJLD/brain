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
  brain schedule list [--json]   every declared schedule, whether it runs here and is installed, and the alerts
                 pass's dead-man: SILENT when its last pass is older than two cadences (the SessionStart health hook
                 and brain status's alerts row say so)
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


def early(args) -> int:
    """The machine's scheduler: schedule names are global, any project's registry."""
    root = root_of(args)
    from .. import schedule
    return schedule.main(args.schedule_cmd, getattr(args, "apply", False), root, args.json)
