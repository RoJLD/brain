"""The personal brain found from anywhere: $BRAIN_PERSONAL, then the installer's pointer <BRAIN_HOME>/personal.json
(brain.paths.personal_root, bases, find_root; brain.config, brain.projects, brain.permissions)."""

import json
from pathlib import Path

import pytest

from brain import cli, config, paths, permissions, projects, render


def _brain(root: Path, owner: str = "Ada") -> Path:
    """A personal brain: config.json, projects.yaml and a graph store."""
    (root / "notes" / "graph").mkdir(parents=True)
    (root / "notes" / "graph" / "schema.yaml").write_text(f"owner: {owner}\nnode_types: [WorkItem]\n",
                                                          encoding="utf-8")
    (root / config.FILE).write_text(json.dumps({"v": 1, "identity": {"owner": owner}}), encoding="utf-8")
    (root / projects.REGISTRY).write_text("me: {root: .}\n", encoding="utf-8")
    return root


@pytest.fixture
def mine(tmp_path, monkeypatch, brain_home):
    """Ada's brain somewhere, the tests' config and registry overrides off, a working folder outside every brain."""
    monkeypatch.delenv("BRAIN_CONFIG", raising=False)
    monkeypatch.delenv("BRAIN_PROJECTS", raising=False)
    monkeypatch.delenv("BRAIN_PERMISSIONS", raising=False)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    brain_home.mkdir(parents=True, exist_ok=True)
    return _brain(tmp_path / "ada-brain")


def _point(brain_home: Path, root) -> None:
    (brain_home / paths.PERSONAL).write_text(json.dumps({"root": str(root)}), encoding="utf-8")


def test_no_pointer_no_personal_brain(mine):
    assert paths.personal_root() is None and paths.pointer_root() is None
    assert config.config_file() is None and projects.registry_file() is None
    with pytest.raises(SystemExit, match="brain init"):
        paths.find_root()


def test_the_pointer_then_the_variable(mine, brain_home, monkeypatch):
    _point(brain_home, mine)
    assert paths.personal_root() == mine and paths.find_root() == mine.resolve()
    assert config.config_file() == mine / config.FILE and config.owner_of() == "Ada"
    assert projects.registry_file() == mine / projects.REGISTRY
    other = _brain(mine.parent / "team-brain", "Team")
    monkeypatch.setenv("BRAIN_PERSONAL", str(other))   # the variable wins over the pointer
    assert paths.personal_root() == other and config.owner_of() == "Team"


def test_a_relative_or_broken_pointer(mine, brain_home):
    (brain_home / paths.PERSONAL).write_text(json.dumps({"root": "sub"}), encoding="utf-8")
    assert paths.pointer_root() == brain_home / "sub"   # relative: read from BRAIN_HOME
    for text in ("not json", "[]", '{"root": ""}', '{"root": 3}'):
        (brain_home / paths.PERSONAL).write_text(text, encoding="utf-8")
        assert paths.pointer_root() is None, text


def test_the_repo_acted_on_comes_before_the_pointer(mine, brain_home, tmp_path):
    """A worktree of the personal brain reads its own config.json and registry; $CLAUDE_BRAIN_DIR and $BRAIN_PERSONAL
    still come first."""
    _point(brain_home, mine)
    worktree = _brain(tmp_path / "worktree", "Ada")
    order = paths.bases(worktree)
    assert order.index(worktree) < order.index(mine)
    assert config.config_file(worktree) == worktree / config.FILE
    assert projects.registry_file(worktree) == worktree / projects.REGISTRY
    assert config.config_file(tmp_path / "elsewhere") == mine / config.FILE   # a project without one: the pointer's


def test_permissions_next_to_the_personal_brain_and_the_engines_allow_rules(mine, brain_home):
    _point(brain_home, mine)
    (mine / permissions.FILE).write_text("v: 1\n", encoding="utf-8")
    assert permissions.permissions_file() == mine / permissions.FILE
    engine = permissions.engine_file(mine / permissions.FILE)
    assert engine == Path(permissions.__file__).resolve().parent / "adapters" / "claude" / permissions.ENGINE_FILE


def test_a_registry_named_outright_is_the_root_of_a_registry_wide_command(mine, monkeypatch):
    monkeypatch.setenv("BRAIN_PROJECTS", str(mine / projects.REGISTRY))
    (mine / "notes" / "graph" / "schema.yaml").unlink()
    assert paths.find_root() == mine.resolve()


def test_brain_config_shows_the_pointer(mine, brain_home, capsys):
    assert cli.main(["--root", str(mine), "config"]) == 0
    assert "no pointer" in capsys.readouterr().out
    _point(brain_home, mine)
    assert cli.main(["config", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["config"]["personal"] == str(mine)


def test_the_claude_hooks_ship_with_the_package():
    hooks = render.claude_hooks()
    assert hooks == Path(render.__file__).resolve().parent / "adapters" / "claude" / "hooks"
    assert (hooks / "hooks.json").is_file() and (hooks / "guard.sh").is_file()


@pytest.mark.parametrize("hook", ["announce.sh", "budget.sh", "capture.sh", "guard.sh", "midsession.sh",
                                  "health.sh", "memory.sh", "resume.sh", "readhint.sh"])
def test_every_hook_tries_the_brain_commands_venv(hook):
    """A plugin folder without the package runs the installed engine: each launcher tries the brain command's venv
    (<BRAIN_HOME>/venv) before the PATH's python3 and python."""
    text = (render.claude_hooks() / hook).read_text(encoding="utf-8")
    loop = next(line for line in text.splitlines() if line.startswith("brain_python "))  # hooks/common.sh
    assert '"$home/venv/Scripts/python.exe" "$home/venv/bin/python"' in loop and '"${BRAIN_PYTHON:-}"' in loop
    assert loop.index("venv") < loop.index("python3")
    assert 'home="${BRAIN_HOME:-${USERPROFILE:-$HOME}/.brain}"' in text   # Python's home (wi-brain-hook-contracts)
