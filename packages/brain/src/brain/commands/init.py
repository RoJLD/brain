"""``brain init``: a new personal brain from the templates: config.json, projects.yaml, the graph store, journal, ADR
log, starter rules (a plan; --apply writes it).
"""

from __future__ import annotations

from .. import init

ORDER = 200   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 230   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain init [DIR] [--owner NAME] [--template NAME|DIR] [--kind person|team] [--tenant ID] [--tier lite|default]
                 [--name NAME] [--stage prototype|mvp|v1|scale] [--apply]
                 a new personal brain from a template (generic by default; cli, local-client, service, data-pipeline
                 and research add a project profile's standards, CI, test harness, issue and ADR templates and
                 graph layers), in DIR
                 (default: here): config.json (its public.deny: the owner, this machine's user and host), projects.yaml,
                 boundary.yaml (readiness_max 0: brain check refuses anything private in src/, tests/, fixtures/), the
                 graph store, journal, ADR log, starter rules, CLAUDE.md, README.md, the local Claude marketplace,
                 memory and records, and this machine's pointer <BRAIN_HOME>/personal.json when it has none; --owner
                 defaults to DIR's config.json identity.owner; a plan, --apply writes it; never overwrites
"""


def register(sub, ctx) -> None:
    ini = sub.add_parser("init", help="a new personal brain from the templates: config.json, projects.yaml, the graph "
                                      "store, journal, ADR log, starter rules (a plan; --apply writes it)")
    ini.add_argument("dir", nargs="?", help="the folder that becomes the brain's private repo (default: here)")
    ini.add_argument("--owner", help="the person or team who decides for it (config.json identity.owner; default: "
                                     "the owner of DIR's config.json, when it has one)")
    ini.add_argument("--template", default=init.DEFAULT_TEMPLATE,
                     help="the engine's template by name (default generic; a project profile: cli, local-client, "
                          "service, data-pipeline, research) or a folder holding a template.yaml")
    ini.add_argument("--kind", choices=init.KINDS, default="person", help="a person (default) or a team")
    ini.add_argument("--tenant", help="the tenant id, for a brain hosted for a team")
    ini.add_argument("--tier", choices=init.TIERS, default="lite",
                     help="the profile its machines start from (config.json tier.base; default lite)")
    ini.add_argument("--name", default="brain", help="its name in projects.yaml (default brain)")
    ini.add_argument("--stage", choices=init.STAGES, default=init.DEFAULT_STAGE,
                     help="the project's stage, for a profile's template: the standards it selects are those "
                          "required at it (projects.yaml standards.stage; default prototype)")
    ini.add_argument("--apply", action="store_true", help="write it (default: the plan)")


def early(args) -> int:
    """A new brain has no graph store yet."""
    return init.main(args)
