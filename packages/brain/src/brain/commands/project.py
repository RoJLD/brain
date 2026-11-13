"""``brain project new``: the new-project wizard (brain.project_new, wi-brain-project-wizard): what the project
produces and its stage, then its brain by ``brain init``, a plan then --apply. ``brain project add``: a project
registered in this brain's projects.yaml (brain.project_add, wi-brain-project-add): read only, an existing instance,
or a new one from a template, placed in the scope tree, a plan then --apply."""

from __future__ import annotations

from .. import init, project_add, project_new

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
  brain project add NAME (--read | --existing DIR [--store PATH] | --template T --dir DIR) [--parent NODE]
                 [--floor CLASS] [--title TEXT] [--apply]   a project registered in this brain's projects.yaml
                 (--root, else $BRAIN_PROJECTS, else the nearest above): read only (title, access: read), an existing
                 instance (its root, relative to the registry's checkout) or a new one written by brain init from a
                 template; --parent places it in the scope tree, --floor marks its class floor (public.deny_from_tree
                 then denies its names); the plan shows the entry and what the deny list gains; --apply checks the
                 registry as it would be (brain check's errors it would add refuse it), appends the entry, comments
                 kept, and logs the step in <BRAIN_HOME>/ledger/setup-<month>.jsonl
"""


def register(sub, ctx) -> None:
    pr = sub.add_parser("project", help="the new-project wizard (brain project new) and a project registered here "
                                        "(brain project add)")
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
    add = psub.add_parser("add", help="a project registered in this brain's projects.yaml: read only, an existing "
                                      "instance or a new one from a template; a plan, then --apply")
    add.add_argument("name", help="its id in projects.yaml and the scope tree (kebab-case)")
    how = add.add_mutually_exclusive_group(required=True)
    how.add_argument("--read", action="store_true", help="a project the brain reads and never writes (access: read)")
    how.add_argument("--existing", metavar="DIR", help="an existing instance: the folder that holds its graph store")
    how.add_argument("--template", metavar="T", help="a new project's brain written by brain init DIR --template T")
    add.add_argument("--dir", help="with --template: the new project's folder")
    add.add_argument("--store", help="with --existing: its graph store, relative to DIR (default notes/graph)")
    add.add_argument("--parent", help="its place in the scope tree: a container of scopes.yaml or a project")
    add.add_argument("--floor", help="its class floor (classes: {floor: CLASS}): private or stricter marks it private")
    add.add_argument("--title", help="its one line for the views")
    add.add_argument("--apply", action="store_true", help="write it (default: the plan)")


def early(args) -> int:
    """A new project has no graph store yet; a registry may sit in a brain whose store is elsewhere."""
    return project_add.main(args) if args.project_cmd == "add" else project_new.main(args)
