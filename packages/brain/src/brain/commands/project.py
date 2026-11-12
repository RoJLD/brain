"""``brain project new``: the new-project wizard (brain.project_new, wi-brain-project-wizard): what the project
produces and its stage, then its brain by ``brain init``, a plan then --apply."""

from __future__ import annotations

from .. import init, project_new

ORDER = 201   # its place in brain --help's list of commands (brain.commands), after brain init
USAGE_ORDER = 231   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain project new DIR --kind K [--kind K]... [--stage prototype|mvp|v1|scale] [--template NAME|DIR]
                 [--name NAME] [--owner NAME] [--apply]   the new-project wizard: what it produces (ids of the
                 typology catalog, brain typologies: code products and research first, STD-5), its stage, then a
                 plan (the layers its kinds are proposed, the template, brain init's plan) and --apply: its brain
                 written by brain init from the first kind's profile template, its registry entry recording
                 lifecycle: {typologies, stage}; in a folder that holds its brain already, the plan shows what the
                 answers change there (written by a PR of that brain, never here)
"""


def register(sub, ctx) -> None:
    pr = sub.add_parser("project", help="the new-project wizard: brain project new (brain.project_new)")
    psub = pr.add_subparsers(dest="project_cmd", required=True)
    new = psub.add_parser("new", help="a new project's brain from what it produces and its stage: a plan, then "
                                      "--apply (brain init)")
    new.add_argument("dir", help="the folder of the project's brain")
    new.add_argument("--kind", dest="kinds", action="append", metavar="K",
                     help="what it produces: an id of the typology catalog (repeatable; brain typologies)")
    new.add_argument("--stage", choices=init.STAGES, default=init.DEFAULT_STAGE,
                     help="its stage (default prototype): the standards required at it, the lifecycle stage it "
                          "reads as")
    new.add_argument("--template", help="the profile template (default: the first kind's)")
    new.add_argument("--name", default="brain", help="its name in its projects.yaml (default brain)")
    new.add_argument("--owner", help="the person or team who decides for it (brain init --owner)")
    new.add_argument("--apply", action="store_true", help="write it (default: the plan)")


def early(args) -> int:
    """A new project has no graph store yet."""
    return project_new.main(args)
