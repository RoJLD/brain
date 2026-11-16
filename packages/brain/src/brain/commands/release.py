"""``brain release``: the version PR's mechanical part in one command (brain.release), a plan then --write."""

from __future__ import annotations

ORDER = 905   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 905   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain release prepare X.Y.Z --theme T [--repo DIR] [--planning ROOT] [--store DIR] [--repo-name NAME]
                 [--no-freeze] [--write]   the engine checkout's version PR, its mechanical part, as a plan (the
                 checkout found from here, else --repo): both __version__, the research-graph pin, brain_version,
                 the install lines and the stranger test's --ref; freeze_store.py vP (the store the previous release
                 wrote; skipped once frozen); changelog.py compile; FEATURES.md and docs/reference/ rendered from the
                 planning brain (--planning, else the personal brain; the public render of --repo-name, default
                 brain); release_check.py (--store: the planning brain's notes/graph by default), then its --preview;
                 --write runs them in that order and stops at the first that fails; the Upgrade steps' prose, the
                 pilot page's line and the review stay a model's (docs/release.md, « The version PR »)
"""
NO_PROJECT = {"release"}   # its parsers that take no --project after them


def register(sub, ctx) -> None:
    rel = sub.add_parser("release", help="the version PR's mechanical part: a plan, then --write (brain.release)"
                         ).add_subparsers(dest="release_cmd", required=True)
    pr = rel.add_parser("prepare", help="versions, the previous store frozen, the changelog compiled, FEATURES.md "
                                        "and the reference rendered, release_check: a plan, then --write")
    pr.add_argument("version", help="the new version, X.Y.Z")
    pr.add_argument("--theme", required=True, help="the release's theme (the CHANGELOG heading, the tag message)")
    pr.add_argument("--repo", help="the engine checkout (default: the one holding the current folder)")
    pr.add_argument("--planning", help="the brain that plans the releases (default: --root, else the personal brain)")
    pr.add_argument("--store", help="the graph store release_check reads the wave from (default: the planning "
                                    "brain's notes/graph)")
    pr.add_argument("--repo-name", default="brain", help="the engine's repo name in the planning brain (default "
                                                         "brain)")
    pr.add_argument("--no-freeze", dest="freeze", action="store_false",
                    help="skip freeze_store.py (release_check then refuses the version PR)")
    pr.add_argument("--write", action="store_true", help="run the steps, in order, stopping at the first that fails")


def early(args) -> int:
    """No project's root: the engine checkout is the one here (or --repo), the planning brain --planning or --root."""
    from .. import release
    return release.main_prepare(args)
