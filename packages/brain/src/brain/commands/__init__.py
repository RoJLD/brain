"""The command registry of ``brain`` (wi-brain-cli-registry): each top-level command is a module of this package.

A new command is a new module here, and no shared file changes: build_parser (brain.cli) finds the modules by
listing this package (brain.commands._registry), and ``brain audit``'s check cmd.registry flags a parser added outside
them. A command module exposes:

- ``ORDER``: its place among brain's commands (brain --help lists them in ORDER, ties by module name);
- ``register(sub, ctx)``: adds its parser, with its subcommands and an alias if it has one, to brain's subparsers
  ``sub``; ``ctx.who`` is the owner's display name for the help, ``ctx.by`` their id, --by's default;
- ``run(args, root)``: the handler, given the project's root (--root, else --project's, else the nearest folder
  above with a graph store);
- ``early(args)``, optional: called first, before any root is resolved (a hook, a machine-wide command, a repo that
  may hold no graph store): its exit code, or None to go on to ``run``; a module without ``run`` returns early's;
- ``USAGE`` and ``USAGE_ORDER``, optional: its lines of brain --help's epilog, printed in USAGE_ORDER ({owner}: the
  owner's display name);
- ``NO_PROJECT``, optional: the names of its parsers that take no --project after their subcommand (a hook's, a
  machine-wide command's).

A module whose name starts with ``_`` is not a command: it holds what the commands share (_common, _stores) or the
registry itself (_registry). This package's own names start with ``_`` too: importing a command module sets an
attribute of its name on the package, which would replace a function of the same name. brain's inventory
(brain.inventory) reads the listing below as an import of every module of the package, so the audit's production
closure and the tests' reach go through the registry as through a plain import.
"""

import pkgutil as _pkgutil


def _names() -> list[str]:
    """The command modules of this package, by name (the ``_`` modules left out)."""
    return [m.name for m in _pkgutil.iter_modules(__path__) if not m.name.startswith("_")]
