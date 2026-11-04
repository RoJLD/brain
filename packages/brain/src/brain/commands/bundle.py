"""``brain bundle``: the Compose bundles the engine ships (sovereign: OpenTelemetry collector, Prometheus, Loki,
Grafana, Qdrant): the plan, then the apply (brain.bundles).
"""

from __future__ import annotations

from .. import bundles
from ._common import root_of

ORDER = 350   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 450   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain bundle plan [BUNDLE]... [--json]   a Compose bundle the engine ships (sovereign: OpenTelemetry collector,
                                  Prometheus, Loki, Grafana, Qdrant): checks (ports on 127.0.0.1 only, images pinned
                                  by digest, docker compose config), the files, folders and images, and what the apply
                                  does with each component; writes and starts nothing (exit 1 on a problem)
  brain bundle apply [BUNDLE]... [--no-start]   render it into <BRAIN_HOME>/stacks/<bundle> (data where each
                                  component's placement says), pull the missing images, brain up its components; a
                                  component whose secret file is missing waits; a second apply changes nothing
"""


def register(sub, ctx) -> None:
    bu = sub.add_parser("bundle", help="the Compose bundles the engine ships (sovereign: OpenTelemetry collector, "
                                       "Prometheus, Loki, Grafana, Qdrant): the plan, then the apply (brain.bundles)"
                        ).add_subparsers(dest="bundle_cmd", required=True)
    for name, text in (("plan", "checks (ports on 127.0.0.1, images pinned, docker compose config), the files, "
                                "folders and images, and what the apply would do with each component; writes and "
                                "starts nothing"),
                       ("apply", "render into <BRAIN_HOME>/stacks/<bundle>, pull the missing images, start the "
                                 "components (brain up); a second apply changes nothing")):
        sp = bu.add_parser(name, help=text)
        sp.add_argument("bundles", nargs="*", metavar="BUNDLE", help="default: every bundle the engine ships")
        if name == "plan":
            sp.add_argument("--json", action="store_true", help="the plan as JSON")
        else:
            sp.add_argument("--no-start", dest="start", action="store_false",
                            help="write the files and folders only; brain up <bundle> starts it later")


def early(args) -> int:
    """Bundles and stack names are global, like brain up."""
    return bundles.main(args.bundle_cmd, args.bundles, root_of(args), start=getattr(args, "start", True),
                        as_json=getattr(args, "json", False))
