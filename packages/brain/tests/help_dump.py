"""Every ``brain <command> [<subcommand>]... --help`` and its arguments, in one text (wi-brain-cli-registry).

The proof that a change of the parser's code changes no command: run it before and after, the diff must be empty.

  python tests/help_dump.py > before.txt   (change the code)   python tests/help_dump.py > after.txt
  git diff --no-index before.txt after.txt

For each parser, depth first in registration order (an alias is listed under its own name too): its help as
``--help`` prints it, at a fixed width of 120 columns, then one line per argument (option strings, dest, default,
type, choices, nargs, required, const, metavar, help) and its set_defaults, which the help does not show. The owner's
name in the help comes from config.json identity, so both runs read the same BRAIN_HOME. tests/test_cli_registry.py
runs it on every commit: every parser formats its help.
"""

from __future__ import annotations

import argparse
import os
import sys


def _name(value) -> str:
    """A stable text for an argument's type, default or const: a function by its qualified name, else repr."""
    if callable(value) and hasattr(value, "__qualname__"):
        return value.__qualname__
    return repr(value)


def _actions(parser: argparse.ArgumentParser) -> list[str]:
    out = []
    for a in parser._actions:
        if isinstance(a, argparse._SubParsersAction):
            out.append(f"  <subcommands> dest={a.dest!r} required={a.required!r} choices={list(a.choices)!r}")
            continue
        out.append(f"  {'/'.join(a.option_strings) or '<positional>'} {type(a).__name__} dest={a.dest!r} "
                   f"default={_name(a.default)} type={_name(a.type)} choices={a.choices!r} nargs={a.nargs!r} "
                   f"required={a.required!r} const={_name(a.const)} metavar={a.metavar!r} help={a.help!r}")
    groups = [[x.dest for x in g._group_actions] for g in parser._mutually_exclusive_groups]
    if groups:
        out.append(f"  <mutually exclusive> {groups!r}")
    if parser._defaults:
        out.append(f"  <defaults> {sorted((k, _name(v)) for k, v in parser._defaults.items())!r}")
    return out


def walk(parser: argparse.ArgumentParser, path: tuple[str, ...] = ("brain",)):
    """(path, parser) for the parser and every subparser under it, depth first, in registration order."""
    yield path, parser
    for a in parser._actions:
        if isinstance(a, argparse._SubParsersAction):
            for name, sub in a.choices.items():
                yield from walk(sub, path + (name,))


def dump(parser: argparse.ArgumentParser) -> str:
    out = []
    for path, p in walk(parser):
        out += [f"===== {' '.join(path)} --help", p.format_help().rstrip("\n"), "----- arguments", *_actions(p), ""]
    return "\n".join(out) + "\n"


def main() -> int:
    os.environ["COLUMNS"] = "120"   # argparse wraps the help at the terminal's width
    from brain import cli
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stdout.write(dump(cli.build_parser()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
