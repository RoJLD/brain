"""The registry's functions (brain.commands): the command modules loaded in ORDER, their parsers added, the module of
a command, the usage lines and the NO_PROJECT names, for build_parser and the dispatch (brain.cli)."""

from __future__ import annotations

import argparse
import functools
import importlib
from dataclasses import dataclass
from types import ModuleType

from . import _names

LAST = 10 ** 6   # the ORDER or USAGE_ORDER of a module that gives none: after the others


@dataclass(frozen=True)
class Context:
    """What a command's parser may name: the owner, as config.json identity gives them (brain config)."""
    who: str   # the display name (identity.display_name), in the help
    by: str    # the id (identity.owner), --by's default: a record never changes for display


_OWNERS: dict[str, ModuleType] = {}   # each command and alias -> its module, as register_all found them


@functools.lru_cache(maxsize=None)
def load() -> tuple[ModuleType, ...]:
    """Every command module of brain.commands, in ORDER (then by name)."""
    mods = [importlib.import_module(f"{__package__}.{name}") for name in _names()]
    return tuple(sorted(mods, key=lambda m: (getattr(m, "ORDER", LAST), m.__name__)))


def register_all(sub: argparse._SubParsersAction, ctx: Context) -> dict[str, ModuleType]:
    """Each command module's parser added to ``sub``, in ORDER: {command or alias: its module}."""
    owners: dict[str, ModuleType] = {}
    for mod in load():
        before = set(sub.choices)
        mod.register(sub, ctx)
        owners.update({name: mod for name in sub.choices if name not in before})
    _OWNERS.update(owners)
    return owners


def owner(name: str) -> ModuleType:
    """The module of a command or alias (``args.cmd``)."""
    if name not in _OWNERS:
        register_all(argparse.ArgumentParser().add_subparsers(), Context("", ""))
    return _OWNERS[name]


def usage() -> list[str]:
    """brain --help's usage lines: each command module's USAGE, in USAGE_ORDER (then by name)."""
    mods = sorted((m for m in load() if getattr(m, "USAGE", "")),
                  key=lambda m: (getattr(m, "USAGE_ORDER", LAST), m.__name__))
    return [line for m in mods for line in m.USAGE.removesuffix("\n").split("\n")]


def no_project() -> set[str]:
    """The parsers no --project is added after (brain.cli): every command module's NO_PROJECT."""
    return {name for m in load() for name in getattr(m, "NO_PROJECT", ())}
