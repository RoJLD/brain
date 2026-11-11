"""A project's command plugin (wi-brain-command-plugins, Q3 of 2026-10-30: one command, ``brain``): ``brain <project>
<subcommand> ...`` runs the subcommands the project's plugin brings, declared under its ``plugin`` key in
projects.yaml. A registry without the key behaves as before: no plugin is required, and none is imported unless its
project is named on the command line.

The value names the plugin: an entry point of the group ``brain.plugins`` (an installed package declares it under
``[project.entry-points."brain.plugins"]``), or ``module:attr`` directly (``module:`` names the module itself). The object it loads is one of:

- a **command module**, the contract of brain.commands: ``register(sub, ctx)`` adds its subcommands to ``sub`` (an
  argparse subparsers action, dest ``cmd``) and ``run(args, root) -> int`` runs them, ``args.project`` and
  ``args.project_obj`` set to the project and ``root`` to its root (a worktree of it when run from one, as for
  ``--project``);
- a **main**, a callable ``main(argv) -> int | None`` given the words after the project's name: a project's own CLI
  plugs in unchanged, so its console script stays a shortcut of ``brain <project>`` (``demo x`` = ``brain demo x``).

A plugged project's name must not be one of brain's commands: the command wins and ``brain check --all`` reports the
clash (:func:`check`). ``brain --help`` lists the plugged projects without importing them (:func:`help_lines`); a
plugin that cannot be loaded fails its own run only (exit 2), never another command. Each run is timed into the
engine's exec ledger as ``brain <project> <subcommand>``.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from importlib import metadata
from pathlib import Path

from . import projects

GROUP = "brain.plugins"
OPTIONS = ("--root", "--project", "--store")   # brain's options that take a value, before the command


class PluginError(Exception):
    """A plugin that cannot be named, found or loaded."""


def declared(root: Path | None = None) -> dict[str, str]:
    """{project: its plugin as declared}, for the loaded projects whose ``plugin`` is a non-empty string."""
    return {name: p.plugin.strip() for name, p in projects.load(root).items()
            if isinstance(p.plugin, str) and p.plugin.strip()}


def resolve(ref: str):
    """The object ``ref`` names: ``module:attr`` (dotted attributes allowed; ``module:`` the module itself), else the
    entry point of that name in :data:`GROUP`. Raises PluginError."""
    if ":" in ref:
        module, _, attr = ref.partition(":")
        try:
            obj = importlib.import_module(module.strip())
            for part in filter(None, attr.strip().split(".")):   # module: is the module itself
                obj = getattr(obj, part)
            return obj
        except (ImportError, AttributeError, ValueError) as exc:
            raise PluginError(f"plugin {ref!r} cannot be loaded: {exc}") from exc
    found = [ep for ep in metadata.entry_points(group=GROUP) if ep.name == ref]
    if not found:
        raise PluginError(f"plugin {ref!r}: no entry point of that name in the group {GROUP} (is its package "
                          f"installed in this environment?)")
    try:
        return found[0].load()
    except Exception as exc:  # noqa: BLE001 - a plugin's import error is its own
        raise PluginError(f"plugin {ref!r} cannot be loaded: {exc}") from exc


def shape(obj) -> str:
    """``module`` (register and run), ``main`` (a callable) or '' (neither)."""
    if callable(getattr(obj, "register", None)) and callable(getattr(obj, "run", None)):
        return "module"
    return "main" if callable(obj) else ""


def split(argv: list[str]) -> tuple[list[str], str, list[str]] | None:
    """(the options before the command, the command word, the words after it); None when there is no command word
    (``brain --help``, ``brain --version``)."""
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in OPTIONS:
            i += 2
        elif a.startswith("-"):
            i += 1
        else:
            return argv[:i], a, argv[i + 1:]
    return None


def target(argv: list[str], commands) -> tuple[list[str], str, str, list[str]] | None:
    """(the options before it, the project, its plugin, the words after it) when ``argv``'s command word is not one
    of ``commands`` but a project that declares a plugin; else None (the registry is read only then)."""
    parts = split(argv)
    if parts is None or parts[1] in commands:
        return None
    before, word, after = parts
    pre = _prefix(before)
    try:
        plugged = declared(Path(pre.root) if pre.root else None)
    except Exception:  # noqa: BLE001 - a registry that cannot be read leaves argparse's own error
        return None
    return (before, word, plugged[word], after) if word in plugged else None


def _prefix(before: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(add_help=False)
    for opt in OPTIONS:
        p.add_argument(opt)
    return p.parse_known_args(before)[0]


def run(before: list[str], name: str, ref: str, after: list[str], ctx, resolve_root) -> int:
    """``brain [options] <name> <after...>``: the plugin loaded and run, timed as ``brain <name> <subcommand>``.
    ``resolve_root(args) -> root`` is brain.cli's (the project's root, or the worktree of it run from)."""
    from . import selftime
    pre = _prefix(before)
    if pre.project and pre.project != name:
        print(f"brain: brain {name} runs project {name}'s plugin; --project {pre.project} names another",
              file=sys.stderr)
        return 2
    try:
        obj = resolve(ref)
    except PluginError as exc:
        print(f"brain {name}: {exc}", file=sys.stderr)
        return 2
    kind = shape(obj)
    if kind == "main":
        sub = next((w for w in after if not w.startswith("-")), "")
        with selftime.run(" ".join(["brain", name, *([sub] if sub else [])])):
            code = obj(list(after))
        return code if isinstance(code, int) else 0
    if kind != "module":
        print(f"brain {name}: plugin {ref!r} is neither a command module (register and run) nor a callable main",
              file=sys.stderr)
        return 2
    title = getattr(projects.load(Path(pre.root) if pre.root else None).get(name), "title", "") or None
    parser = argparse.ArgumentParser(prog=f"brain {name}", description=title)
    sub = parser.add_subparsers(dest="cmd", required=True)
    obj.register(sub, ctx)
    args = parser.parse_args(after)
    args.root, args.store, args.project = pre.root, pre.store, name
    with selftime.run(" ".join(["brain", name, str(args.cmd)])):
        return obj.run(args, resolve_root(args))


def help_lines(root: Path | None = None) -> list[str]:
    """brain --help's paragraph on the plugged projects, from the registry alone (no plugin imported)."""
    try:
        plugged = declared(root)
    except Exception:  # noqa: BLE001 - a broken registry never breaks the help
        return []
    if not plugged:
        return []
    reg = projects.load(root)
    width = max(map(len, plugged))
    lines = ["Plugged projects (brain <project> <subcommand> ...; brain <project> --help lists its subcommands):"]
    for name, ref in plugged.items():
        title = reg[name].title if name in reg else ""
        lines.append(f"  {name.ljust(width)}  {title + ' ' if title else ''}(plugin {ref})")
    return lines


def check(root: Path | None, commands) -> list[str]:
    """What is wrong with the plugins declared: a value that is not a non-empty string, a project whose name is one
    of brain's ``commands`` (the command wins, so the plugin would never run). A plugin that is not installed is not
    an error here: a machine may lack a project's package; its run says so."""
    errors = []
    for name, entry in projects.raw(root).items():
        if not isinstance(entry, dict) or "plugin" not in entry:
            continue
        value = entry["plugin"]
        if not (isinstance(value, str) and value.strip()):
            errors.append(f"project {name}: plugin is an entry point name of the group {GROUP} or module:attr")
        elif name in commands:
            errors.append(f"project {name}: its plugin never runs, brain {name} is one of brain's commands "
                          f"(rename the project or drop the key)")
    return errors
