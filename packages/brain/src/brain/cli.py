"""``brain``: one command for {owner}'s records and backlogs, at zero token (Q3, 2026-10-30).

The repo acted on is --root, else the registered project --project NAME (projects.yaml of the Brain repo), else
$BRAIN_ROOT, else the nearest folder above with notes/graph/schema.yaml (a worktree of a registered project keeps its
name). --project with --root: that project's layout at that root (a worktree). --project goes before or after the
subcommand. Every view takes --project NAME or --all (every registered project), not both: status, projects, resume,
digest, queue, decision pending, batch and view, milestone suggest, spec activate, notify status, alerts, lint rules,
audit, sync, check, refresh, tui, usage, forecast (cost takes --project);
health, index, up and down take --project to narrow them to that project's stacks and repos (their names are global);
perf reads every project unless --project; timed and memory are machine-wide. A text value written @FILE is read from
FILE; a journal line '-' reads stdin.
The local ledger the hooks write is $BRAIN_HOME (default ~/.brain). The stacks are declared under each project's
stacks: in projects.yaml (brain.stacks); up, down and health print one line per stack, exit 1 on a failure. The repos
GitNexus indexes are declared under each project's code_index:, the stack that indexes them under its index:
(brain.codeindex). The notification channels and each project's routes per level are declared under notify:
(brain.notify); a secret is named by its environment variable only, and $BRAIN_NOTIFY=off sends nothing. Where
each project's alerts come from (scheduler folders, tasks and their cadences, stacks, alert files, event folders,
levels) is declared under alerts: (brain.alerts).
{owner}: config.json's identity.owner (brain config), filled in by build_parser.
"""

from __future__ import annotations

import argparse
import codecs
import os
import sys

from . import __version__, config, nowindow, paths, projects, selftime
from .commands import _registry as registry
from .commands._common import root_of

# brain.cli stays the facade of the commands (brain.commands): the names its callers and tests reach through it
from . import features, graph, links  # noqa: F401
from .commands._stores import (_bundle_problems, _bundles_check, _check_session_ids, _check_store,  # noqa: F401
                               _merge_marks, _sync_store, check_registry)


def build_parser() -> argparse.ArgumentParser:
    # the help names the owner by their display name (identity.display_name) and --by defaults to their id
    # (identity.owner): a record never changes for display
    ctx = registry.Context(who=config.name_of(), by=config.owner_of())
    # the docstring holds the first line and the closing paragraph; each command module's USAGE goes between them
    doc = __doc__.split("\n")
    usage_ = "\n".join(doc[:2] + registry.usage() + [""] + doc[2:]).replace("{owner}", ctx.who).split("\n")
    p = argparse.ArgumentParser(prog="brain", description=usage_[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog="\n".join(usage_[2:-2]))
    p.add_argument("--version", action="version", version=f"brain {__version__}")
    p.add_argument("--root", help="repo to act on (default: $BRAIN_ROOT, else the nearest notes/graph above)")
    p.add_argument("--project", help="a project of the registry (projects.yaml): brain, demo...")
    p.add_argument("--store", help="graph store (default: the project's first store, <root>/notes/graph)")
    sub = p.add_subparsers(dest="cmd", required=True)
    registry.register_all(sub, ctx)   # every command, in ORDER: a new command is a new module of brain.commands
    _project_after(p, registry.no_project())
    return p


def _project_after(parser: argparse.ArgumentParser, skip: set[str]) -> None:
    """--project after the subcommand too (brain status --project quant), on every leaf subcommand but those of
    ``skip`` (the commands' NO_PROJECT: the hooks', memory and sessions, machine-wide)."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sp in action.choices.items():
                if name in skip:
                    continue
                if any(isinstance(a, argparse._SubParsersAction) for a in sp._actions):
                    _project_after(sp, skip)
                elif "--project" not in sp._option_string_actions:
                    sp.add_argument("--project", default=argparse.SUPPRESS,
                                    help="a registered project (same as brain --project)")


def _utf8(stream) -> None:
    """Records and logs are UTF-8; a pipe or a file on Windows defaults to cp1252, and so does NUL, which reports
    isatty() true (wi-brain-nul-stdout-encoding): any stream that is not a tty, or whose encoding is not UTF-8, writes
    UTF-8 with errors=replace. A real console (UTF-8 since Python 3.6) is left alone."""
    if not hasattr(stream, "reconfigure"):
        return
    try:
        utf8 = codecs.lookup(stream.encoding or "ascii").name == "utf-8"
    except LookupError:
        utf8 = False
    if not utf8 or not stream.isatty():
        stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    nowindow.install()  # under pythonw.exe, a scheduled task's: each git or gh would otherwise open a window
    if sys.stdout is None:  # pythonw.exe has no console: argparse's help writes to a stream, so give it one
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    for stream in (sys.stdout, sys.stderr):
        _utf8(stream)
    args = build_parser().parse_args(argv)
    with selftime.run(selftime.command_task(args)):  # the engine's exec event, and an error event if it raises
        return _dispatch(args)


def _dispatch(args) -> int:
    """The command's module runs it: its early handler first, before any root is resolved (a hook, a machine-wide
    command, a repo that may hold no graph store), then its run with the project's root."""
    command = registry.owner(args.cmd)
    early = getattr(command, "early", None)
    if early is not None:
        code = early(args)
        if code is not None or not hasattr(command, "run"):
            return code
    root = root_of(args)
    if args.project:
        args.project_obj = projects.get(args.project, root)
        root = args.project_obj.root
        if not args.root:  # run from a worktree of the project's repo: that worktree is the root (wi-brain-root-from-cwd)
            wt = projects.cwd_worktree(args.project_obj)
            if wt is not None:
                args.project_obj = projects.get(args.project, wt)
                root = wt
    root = root or paths.find_root()
    return command.run(args, root)


if __name__ == "__main__":
    sys.exit(main())
