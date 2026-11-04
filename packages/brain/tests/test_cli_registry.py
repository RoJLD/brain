"""wi-brain-cli-registry: each top-level command is a module of brain.commands; brain.cli builds the parser from them
and dispatches; brain audit flags a command outside the registry (check cmd.registry)."""

import argparse
import types
from pathlib import Path

import pytest

import help_dump
from brain import audit, cli, commands, inventory
from brain.commands import _registry
from brain.commands import audit as audit_cmd
from brain.commands import (bundle, capture, check, code_map, collisions, decision, down, health, impact, index, init,
                            memory, merge_check, merge_driver, milestone, perf, refresh, resume, retro, schedule,
                            sessions, spec, timed, up, update)
from test_audit import README, _measure

MODULES = _registry.load()


def test_every_command_module_keeps_the_contract():
    assert {m.__name__.rsplit(".", 1)[1] for m in MODULES} == set(commands._names())
    assert len(MODULES) >= 55 and not any(n.startswith("_") for n in commands._names())
    owners = _registry.register_all(argparse.ArgumentParser().add_subparsers(), _registry.Context("Ada", "ada"))
    for m in MODULES:
        assert isinstance(m.ORDER, int) and callable(m.register), m.__name__
        assert callable(getattr(m, "run", None)) or callable(getattr(m, "early", None)), m.__name__
        assert any(o is m for o in owners.values()), f"{m.__name__} registers no command"
    orders = [m.ORDER for m in MODULES]
    usage_orders = [m.USAGE_ORDER for m in MODULES if getattr(m, "USAGE", "")]
    assert len(set(orders)) == len(orders) and len(set(usage_orders)) == len(usage_orders)   # one place each
    assert owners["doctor"] is owners["profile"] and owners["lessons"] is owners["lesson"]   # an alias, its module
    assert _registry.no_project() == {"capture", "announce", "memory", "sessions"}


def test_the_help_of_every_parser_formats_and_a_second_build_is_the_same(monkeypatch):
    """help_dump.py is the move's proof (its output before and after, diffed); here every parser formats its help,
    and a second build_parser in the same process gives the same text: no module's import replaced a registry
    function (brain.commands.usage, the command, once shadowed the usage lines' function of the same name)."""
    monkeypatch.setenv("COLUMNS", "120")
    first = help_dump.dump(cli.build_parser())
    assert help_dump.dump(cli.build_parser()) == first
    paths = [" ".join(p) for p, _ in help_dump.walk(cli.build_parser())]
    assert len(paths) >= 149 and {"brain record sr", "brain vault recipient add", "brain doctor list"} <= set(paths)
    assert "{owner}" not in first and "Ada's decision queue" in first
    epilog = cli.build_parser().epilog
    assert epilog.startswith("  brain record sr ") and "\n\nThe repo acted on is --root" in epilog
    assert epilog.index("  brain features list") < epilog.index("  brain modules [--write]")   # USAGE_ORDER, not ORDER


# Before the registry, cli._dispatch ran these before any root was resolved (a hook, a machine-wide command, a repo
# that may hold no graph store): their module defines early, and no run; decision, resume and check define both (early
# for announce, --hook and --public only); every other command needs the project's root (run only)
EARLY = {capture, memory, timed, perf, init, merge_driver, merge_check, sessions, schedule, update, audit_cmd, impact,
         index, up, down, health, bundle}
BOTH = {decision, resume, check}
ROOTED = {code_map, collisions, milestone, refresh, retro, spec}   # a sample of the rest: they need the graph store


def test_the_commands_that_run_before_a_root_is_resolved_keep_their_phase():
    def phase(m):
        return "both" if hasattr(m, "early") and hasattr(m, "run") else "early" if hasattr(m, "early") else "run"
    assert {m.__name__ for m in MODULES if phase(m) == "early"} == {m.__name__ for m in EARLY}
    assert {m.__name__ for m in MODULES if phase(m) == "both"} == {m.__name__ for m in BOTH}
    assert all(phase(m) == "run" for m in ROOTED)
    for m in EARLY | BOTH | ROOTED:   # each registers the command of its file name
        sub = argparse.ArgumentParser().add_subparsers()
        m.register(sub, _registry.Context("Ada", "ada"))
        assert list(sub.choices) == [m.__name__.rsplit(".", 1)[1].replace("_", "-")], m.__name__


def test_brain_cli_adds_no_parser_itself():
    assert audit._parsers_added(Path(cli.__file__).read_text(encoding="utf-8")) == []


def _fake(**handlers):
    return types.SimpleNamespace(__name__="brain.commands.fake", **handlers)


def test_the_dispatch_runs_early_first_then_run_with_the_root(monkeypatch, tmp_path):
    seen = []
    with monkeypatch.context() as m:
        m.setitem(_registry._OWNERS, "fake", _fake(early=lambda a: seen.append("early"),
                                                   run=lambda a, root: seen.append(root) or 7))
        args = argparse.Namespace(cmd="fake", root=str(tmp_path), project=None)
        assert cli._dispatch(args) == 7 and seen == ["early", tmp_path.resolve()]   # early's None: on to run
        m.setitem(_registry._OWNERS, "fake", _fake(early=lambda a: 3, run=lambda a, root: 1 / 0))
        assert cli._dispatch(args) == 3                                              # early's code: run never runs
        m.setitem(_registry._OWNERS, "fake", _fake(early=lambda a: None))
        assert cli._dispatch(args) is None                                           # no run: early's, even None
    assert "fake" not in _registry._OWNERS


REGISTRY = {
    "README.md": README,
    "src/a/__init__.py": "",
    "src/a/cli.py": "from a.commands import _registry\n\ndef main():\n    _registry.load()\n",
    "src/a/commands/__init__.py": "import pkgutil\n\n\ndef _names():\n    return [m.name for m in "
                                  "pkgutil.iter_modules(__path__)]\n",
    "src/a/commands/hello.py": "def register(sub, ctx):\n    sub.add_parser('hello')\n\n\ndef run(args, root):\n"
                               "    return 0\n",
    "src/a/commands/_common.py": "def helper():\n    pass\n",
}


def _registry_found(files: dict) -> dict:
    res = _measure({"a": files})
    return {f["unit"]: f for f in res["repos"][0]["findings"] if f["check"] == "cmd.registry"}


def test_audit_flags_a_parser_added_outside_the_registry_and_a_module_without_register():
    assert _registry_found(REGISTRY) == {}
    bad = dict(REGISTRY, **{
        "src/a/cli.py": "def main(sub):\n    sub.add_parser('stray').add_subparsers().add_parser('leaf')\n",
        "src/a/commands/half.py": "def run(args, root):\n    return 0\n"})
    found = _registry_found(bad)
    assert set(found) == {"src/a/cli.py", "src/a/commands/half.py"}
    assert "adds 2 parser(s) itself, outside the command registry: stray, leaf" in found["src/a/cli.py"]["why"]
    assert found["src/a/commands/half.py"]["fix"].startswith("define register(sub, ctx)")
    assert audit.CHECKS["cmd.registry"].scout == "new+left" and audit.RULESET >= 5
    plain = dict(bad, **{"src/a/commands/__init__.py": ""})   # a commands/ package that lists nothing: no registry
    assert _registry_found(plain) == {}


def test_audit_takes_a_register_a_command_module_imports():
    """The review of wi-brain-cli-registry: inventory.has_symbol reads definitions only, so a module whose register
    comes from an import was flagged although the registry finds it."""
    run = "\n\n\ndef run(args, root):\n    return 0\n"
    found = _registry_found(dict(REGISTRY, **{
        "src/a/commands/_impl.py": "def register(sub, ctx):\n    sub.add_parser('via')\n\n\ndef reg(sub, ctx):\n"
                                   "    sub.add_parser('alias')\n",
        "src/a/commands/via.py": "from ._impl import register" + run,
        "src/a/commands/alias.py": "from ._impl import reg as register" + run,
        "src/a/commands/other.py": "from ._impl import reg" + run}))
    assert set(found) == {"src/a/commands/other.py"}   # reg is not register


def test_the_engines_own_registry_passes_its_audit_check():
    root = Path(__file__).resolve().parents[3]
    if not (root / ".git").exists():
        pytest.skip("not a git checkout")
    rf = inventory.collect(inventory.work_tree(root), "brain")
    assert [f["unit"] for f in audit.registry_findings("brain", rf)] == []
    assert inventory.facts(rf.tree, "packages/brain/src/brain/commands/__init__.py").discovers
