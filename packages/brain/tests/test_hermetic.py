"""wi-brain-hermetic-tests: the suite's environment is an allow list (conftest.py). Every variable the engine reads is
either cleared for the tests (its family: BRAIN_*, CLAUDE*, GIT_*, RESEARCH_GRAPH_*, or a token or the editor),
pinned by the conftest, or examined here and passed through with its reason; git reads an empty global
configuration; no test calls monkeypatch.undo()."""

import ast
import os
import re
import subprocess
from pathlib import Path

import conftest
import pytest

TESTS = Path(__file__).resolve().parent
ENGINE = TESTS.parent / "src"                       # packages/brain/src: the brain package and its hooks
GRAPH = TESTS.parents[2] / "src" / "research_graph"   # research-graph, which the brain command runs in process
NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
SHELL_VAR = re.compile(r"\$\{?([A-Z][A-Z0-9_]*)")

# The variables the engine reads that the hermetic environment leaves as the machine has them, each examined: a new
# one the engine starts reading fails test_every_variable_the_engine_reads_is_cleared_pinned_or_examined until it is
# cleared (a family, conftest.CLEARED), pinned (conftest's brain_home) or added here with its reason.
PASSTHROUGH = {
    "PATH": "where git, bash and python are found: the tests need them",
    "PATHEXT": "Windows' executable suffixes, for shutil.which",
    "HOME": "the user's home: every path the engine derives from it is pinned (BRAIN_HOME, CLAUDE_CONFIG_DIR, ...)",
    "USERPROFILE": "the same on Windows",
    "APPDATA": "Windows' roaming folder: the keystore's and the cockpit's defaults, overridden where a test reads them",
    "LOCALAPPDATA": "pinned by brain_home to a temporary folder (the desktop app's sessions)",
    "XDG_CONFIG_HOME": "the POSIX config folder, read as HOME is",
    "USER": "the account's name, for a default display name: never a path to the owner's data",
    "USERNAME": "the same on Windows",
    "LOGNAME": "the same on POSIX",
    "USERDOMAIN": "the Windows domain, part of the machine's facts (brain doctor)",
    "COMPUTERNAME": "the machine's name (brain.machine): the tests pass their own where they compare it",
    "HOSTNAME": "the same in bash (the hooks)",
    "CI": "the read mode's default: BRAIN_STRICT, pinned, wins over it; the tests about it set it themselves",
    "COLUMNS": "the terminal's width for argparse's help: brain.readme sets it while it renders",
    "PYTHONPATH": "passed to the venv a test builds (brain.detail): the checkout under test",
    "PYTEST_CURRENT_TEST": "pytest's own: the engine refuses the real ~/.brain and keystore under it",
    "EPOCHREALTIME": "bash's own clock (the hooks' timings)",
    "BASH_SOURCE": "bash's own",
    "BASH_REMATCH": "bash's own",
    "BASH_CMDS": "bash's own",
}


def _envish(node) -> bool:
    """A node that reads like an environment mapping: os.environ, an ``env`` parameter, ``environ``."""
    return "env" in ast.unparse(node).lower()


def _call(node):
    """os.getenv("X"), <env>.get / pop / setdefault("X")."""
    if not (node.args and isinstance(node.args[0], ast.Constant)):
        return None
    func = node.func
    by_env = isinstance(func, ast.Attribute) and func.attr in ("get", "pop", "setdefault") and _envish(func.value)
    return node.args[0].value if by_env or ast.unparse(func).endswith("getenv") else None


def _subscript(node):
    """<env>["X"]."""
    return node.slice.value if isinstance(node.slice, ast.Constant) and _envish(node.value) else None


def _compare(node):
    """"X" in <env>."""
    hit = isinstance(node.left, ast.Constant) and isinstance(node.ops[0], (ast.In, ast.NotIn)) \
        and _envish(node.comparators[0])
    return node.left.value if hit else None


def _constant(node):
    """A string of a family anywhere (ALLOW_ENV = "BRAIN_GUARD_ALLOW", read through the name)."""
    return node.value if isinstance(node.value, str) and conftest.hermetic(node.value) else None


READERS = {ast.Call: _call, ast.Subscript: _subscript, ast.Compare: _compare, ast.Constant: _constant}


def _python_reads(tree) -> set[str]:
    """The constant names read from an environment, by the forms of :data:`READERS`."""
    names = (READERS[type(n)](n) for n in ast.walk(tree) if type(n) in READERS)
    return {n for n in names if isinstance(n, str) and NAME.match(n)}


def engine_reads() -> dict[str, list[str]]:
    """{variable: [files]} of what the engine's Python modules and shell hooks read from the environment."""
    reads: dict[str, list[str]] = {}
    for root in (ENGINE, GRAPH):
        for f in sorted(root.rglob("*.py")):
            for name in _python_reads(ast.parse(f.read_text(encoding="utf-8"), str(f))):
                reads.setdefault(name, []).append(f.name)
        for f in sorted(root.rglob("*.sh")):
            for name in set(SHELL_VAR.findall(f.read_text(encoding="utf-8"))):
                reads.setdefault(name, []).append(f.name)
    return reads


def test_the_scan_sees_what_the_engine_reads():
    """The scan itself: the variables of the incidents behind the allow list, read through each form it knows."""
    reads = engine_reads()
    for name in ("BRAIN_HOME", "CLAUDE_CODE_HOST_SESSION_ID", "CLAUDE_CONFIG_DIR", "BRAIN_GUARD_ALLOW",
                 "CLAUDE_PLUGIN_ROOT", "BRAIN_PERSONAL", "LOCALAPPDATA", "CI", "COLUMNS"):
        assert name in reads, name
    assert _python_reads(ast.parse('import os\nos.environ.get("A_1"); os.getenv("B"); env["C"]; "D" in os.environ\n'
                                   'env.pop("E", None); x = {"F": 1}.get("F")')) == {"A_1", "B", "C", "D", "E"}


def test_every_variable_the_engine_reads_is_cleared_pinned_or_examined():
    reads = engine_reads()
    unexamined = {n: files for n, files in reads.items()
                  if not conftest.hermetic(n) and n not in conftest.PINNED and n not in PASSTHROUGH}
    assert not unexamined, ("the engine reads these and the hermetic environment leaves them as the machine has them: "
                            "clear them (conftest.CLEARED), pin them (conftest's brain_home) or add them to "
                            f"PASSTHROUGH with the reason: {unexamined}")
    stale = sorted(set(PASSTHROUGH) - set(reads))
    assert not stale, f"PASSTHROUGH names variables the engine no longer reads: {stale}"


def test_the_conftest_leaves_no_variable_of_a_family_set_but_its_pins():
    """Inside a test, whatever the shell the suite runs from (a desktop-app session, CI, a terminal with BRAIN_*)."""
    left = sorted(k for k in os.environ if conftest.hermetic(k) and k.upper() not in conftest.PINNED
                  and k.upper() not in conftest.SESSION_PINS)
    assert left == []
    assert os.environ["BRAIN_STRICT"] == "1" and os.environ["GIT_CONFIG_NOSYSTEM"] == "1"


def test_the_environment_is_cleared_by_families_not_by_names():
    """A variable of a family nobody has named yet is cleared too: the deny list missed each new one."""
    env = {"CLAUDECODE": "1", "CLAUDE_CODE_HOST_SESSION_ID": "local_x", "CLAUDE_SOMETHING_NEW": "1",
           "BRAIN_NEXT_KNOB": "1", "GIT_DIR": "/elsewhere", "Git_Work_Tree": "/x", "GH_TOKEN": "t",
           "BRAIN_TEST_ROOT": "C:/t", "BRAIN_TEST_WORKERS": "4", "PATH": "/bin", "LANG": "C"}
    cleared = conftest.hermetic_environment(env, "/tmp/empty.gitconfig")
    assert cleared == sorted(["BRAIN_NEXT_KNOB", "CLAUDECODE", "CLAUDE_CODE_HOST_SESSION_ID", "CLAUDE_SOMETHING_NEW",
                              "GH_TOKEN", "GIT_DIR", "Git_Work_Tree"])
    assert env == {"BRAIN_TEST_ROOT": "C:/t", "BRAIN_TEST_WORKERS": "4", "PATH": "/bin", "LANG": "C",
                   "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/tmp/empty.gitconfig"}


def test_a_variable_set_without_monkeypatch_does_not_reach_the_next_test(monkeypatch):
    os.environ["BRAIN_LEAKED_BY_A_TEST"] = "1"   # what a careless test does; the next test's brain_home clears it
    monkeypatch.setenv("BRAIN_LEAKED_BY_A_TEST", "1")   # and this one's teardown restores it as it found it


def test_the_leak_of_the_previous_test_is_gone():
    assert "BRAIN_LEAKED_BY_A_TEST" not in os.environ


def test_git_reads_an_empty_global_configuration(tmp_path):
    """A user's diff.noprefix, alias or hook path never reaches a test: git sees no global and no system file."""
    gitconfig = Path(os.environ["GIT_CONFIG_GLOBAL"])
    assert gitconfig.is_file() and gitconfig.read_text(encoding="utf-8") == ""
    res = subprocess.run(["git", "config", "--list", "--show-scope"], cwd=tmp_path, capture_output=True, text=True,
                         timeout=60)
    scopes = {line.split("\t", 1)[0] for line in res.stdout.splitlines() if line.strip()}
    assert not scopes & {"global", "system"}, res.stdout


def _undo_calls(tree) -> list[int]:
    """The lines of a ``<monkeypatch>.undo()`` call (comments and strings that mention it do not count)."""
    return [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "undo" and "monkeypatch" in ast.unparse(n.func.value) and not n.args]


def test_no_test_calls_monkeypatch_undo():
    """2026-11-03: a test's monkeypatch.undo() dropped the conftest's BRAIN_HOME and the memory keystore, and the rest
    of it rotated the owner's real device key. monkeypatch.context() undoes only what it set."""
    assert _undo_calls(ast.parse("monkeypatch.undo()\n# monkeypatch.undo()\nx = 'monkeypatch.undo()'\n")) == [1]
    found = {f.name: lines for f in sorted(TESTS.glob("*.py"))
             if (lines := _undo_calls(ast.parse(f.read_text(encoding="utf-8"), str(f))))}
    assert not found, f"monkeypatch.undo() drops the conftest's whole environment: use monkeypatch.context() {found}"


@pytest.mark.parametrize("name", sorted(conftest.PINNED))
def test_each_pin_is_set_before_a_test(name):
    assert os.environ.get(name), name
