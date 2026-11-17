"""``brain project new``: the new-project wizard (brain.project_new, wi-brain-project-wizard): what the project
produces and its stage, then its brain by ``brain init``, a plan then --apply. ``brain project add``: a project
registered in this brain's projects.yaml (brain.project_add, wi-brain-project-add): read only, an existing instance,
or a new one from a template, placed in the scope tree, a plan then --apply."""

from __future__ import annotations

from .. import init, langs, project_add, project_new, projects

ORDER = 201   # its place in brain --help's list of commands (brain.commands), after brain init
USAGE_ORDER = 231   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain project new DIR --kind K [--kind K]... [--stage prototype|mvp|v1|scale] [--template NAME|DIR]
                 [--lang py|ts [--tool SLOT=TOOL]...] [--floor CLASS | --residency] [--personal-data]
                 [--name NAME] [--owner NAME] [--apply]   the new-project wizard: what it produces (ids of the
                 typology catalog, brain typologies: code products and research first, STD-5), its stage, its
                 language and each check's tool (lint, typecheck, test, coverage, format: the language's usual one
                 unless --tool names another, none for none), its data (the class floor, a residency clause,
                 personal data: the privacy standards included; a floor its own stores are under, which brain
                 check refuses, is refused with them), then a plan (the layers its kinds are proposed, the tools and
                 their reports, those the template's CI does not write, the standards rows it follows and those its
                 tools run, the template, brain init's plan) and --apply: its brain written by brain init from the
                 first kind's profile template, its registry entry recording lifecycle: {typologies, stage}, its
                 repo's lang and tools, classes: {floor} and standards include; in a folder that holds its brain
                 already, the plan shows what the answers change there (written by a PR of that brain, never here)
  brain project add NAME (--read | --existing DIR [--store PATH] | --template T --dir DIR) [--parent NODE]
                 [--floor CLASS] [--title TEXT] [--profile P] [--kind K]... [--stage S] [--team] [--interactive]
                 [--no-notes] [--apply]   a project registered in this brain's projects.yaml
                 (--root, else $BRAIN_PROJECTS, else the nearest above): read only (title, access: read), an existing
                 instance (its root, relative to the registry's checkout) or a new one written by brain init from a
                 template; --parent places it in the scope tree, --floor marks its class floor (public.deny_from_tree
                 then denies its names); the plan shows the entry and what the deny list gains; --apply checks the
                 registry as it would be (brain check's errors it would add refuse it), appends the entry, comments
                 kept, and logs the step in <BRAIN_HOME>/ledger/setup-<month>.jsonl; with a notes home, its map
                 maps/NAME.md there too (scope: NAME), never over a file (--no-notes: none). The qualification's
                 five questions (purpose --profile, what it produces --kind, stage --stage, criticity --floor, a
                 team --team with --template), each unanswered one named in the plan, --interactive asks them: the
                 answers go to the entry's lifecycle: {profile, typologies, stage, since}
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
    new.add_argument("--lang", choices=langs.LANGS, help="the language of its own repo (repos[].lang): its tools "
                                                         "are asked next")
    new.add_argument("--tool", dest="tools", action="append", metavar="SLOT=TOOL",
                     help="a check's tool (slots: lint, typecheck, test, coverage, format; TOOL none for none; "
                          "repeatable); a slot not named takes the language's usual tool")
    new.add_argument("--floor", help="the class floor of its data (classes: {floor: CLASS}; brain classes): "
                                     "refused when its own stores are under it (brain check refuses them)")
    new.add_argument("--residency", action="store_true", help="its data are under a residency clause: the floor "
                                                              "resident, refused as --floor is")
    new.add_argument("--personal-data", action="store_true", help="it handles personal data: the privacy standards "
                                                                  "join its selection's include")
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
    add.add_argument("--no-notes", action="store_true", help="no map in the notes home (default: maps/NAME.md "
                                                             "there, when the brain has one)")
    add.add_argument("--profile", choices=projects.LIFECYCLE_PROFILES,
                     help="qualification 1, its purpose and audience: lifecycle.profile")
    add.add_argument("--kind", dest="kinds", action="append", metavar="K",
                     help="qualification 2, what it produces: an id of the typology catalog (repeatable; brain "
                          "typologies): lifecycle.typologies")
    add.add_argument("--stage", help="qualification 3, its stage: a lifecycle stage (explore, build...) or a "
                                     "standards stage read as one (mvp: build): lifecycle.stage")
    add.add_argument("--team", action="store_true",
                     help="qualification 5, with --template: the new brain is a team's (brain init --kind team)")
    add.add_argument("--interactive", "-i", action="store_true",
                     help="the qualification's questions the options leave unanswered, asked in the terminal")
    add.add_argument("--apply", action="store_true", help="write it (default: the plan)")


def early(args) -> int:
    """A new project has no graph store yet; a registry may sit in a brain whose store is elsewhere."""
    return project_add.main(args) if args.project_cmd == "add" else project_new.main(args)
