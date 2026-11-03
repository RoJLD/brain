"""brain init: a new personal brain from the templates, a plan then an apply that never overwrites (brain.init)."""

import json
import re

import pytest

from brain import __version__, cli, config, init, paths, projects


@pytest.fixture
def fresh(tmp_path, monkeypatch, brain_home):
    """An empty folder to become Ada's brain; the tests' own config and registry overrides off."""
    monkeypatch.delenv("BRAIN_CONFIG", raising=False)
    monkeypatch.delenv("BRAIN_PROJECTS", raising=False)
    root = tmp_path / "ada-brain"
    root.mkdir()
    return root


def test_the_plan_writes_nothing(fresh, brain_home, capsys):
    assert cli.main(["init", str(fresh), "--owner", "Ada"]) == 0
    out = capsys.readouterr().out
    assert "create   config.json" in out and "create   notes/graph (research_graph init --owner Ada)" in out
    assert f"point    {paths.personal_file()}" in out and "(plan only: brain init --apply writes it)" in out
    assert list(fresh.iterdir()) == [] and not paths.personal_file().exists()


def test_apply_writes_a_brain_that_checks_and_points_to_it(fresh, monkeypatch, capsys):
    assert cli.main(["init", str(fresh), "--owner", "Ada", "--apply"]) == 0
    out = capsys.readouterr().out
    assert "next: git init" in out
    data = json.loads((fresh / "config.json").read_text(encoding="utf-8"))
    assert data == {"v": 1, "identity": {"owner": "Ada", "kind": "person"}, "registry": "projects.yaml",
                    "rules": ["rules/global.md"], "memory": "memory", "records": "records",
                    "engine": {"repo": init.ENGINE_REPO, "pin": f"v{__version__}"}, "tier": {"base": "lite"}}
    assert config.check(fresh) == [] and config.owner_of(fresh) == "Ada"
    assert "owner: \"Ada\"" in (fresh / "notes" / "graph" / "schema.yaml").read_text(encoding="utf-8")
    assert (fresh / "notes" / "decisions.md").is_file() and (fresh / "notes" / "kanban_graph.md").is_file()
    rules = (fresh / "rules" / "global.md").read_text(encoding="utf-8")
    assert rules.startswith("# Ada's rules for every project") and "{owner}" not in rules
    reg = projects.load(fresh)
    assert list(reg) == ["brain"] and reg["brain"].root == fresh.resolve()
    assert paths.pointer_root() == fresh.resolve()
    assert cli.main(["--root", str(fresh), "check"]) == 0
    assert "graph-check OK" in capsys.readouterr().out


def test_the_first_items_go_into_the_empty_layers(fresh, capsys):
    """research_graph init writes an empty layer as a flow list (``[]``): the first item and its first edge go after
    its comments, and the store still checks."""
    assert cli.main(["init", str(fresh), "--owner", "Ada", "--apply"]) == 0
    assert cli.main(["--root", str(fresh), "item", "add", "wi-first", "--title", "First: the pilot", "--priority",
                     "P1", "--reason", "the pilot"]) == 0
    assert cli.main(["--root", str(fresh), "item", "add", "wi-second", "--title", "Second", "--after",
                     "wi-first"]) == 0
    work = (fresh / "notes" / "graph" / "nodes" / "work.yaml").read_text(encoding="utf-8")
    assert "[]" not in work and work.startswith("# Work layer") and "- {id: wi-first," in work
    assert "{from: wi-second, to: wi-first, type: depends_on}" in \
        (fresh / "notes" / "graph" / "edges" / "work.yaml").read_text(encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["--root", str(fresh), "sync"]) == 0 and cli.main(["--root", str(fresh), "check"]) == 0
    assert "graph-check OK" in capsys.readouterr().out


def test_a_second_apply_changes_nothing_and_a_file_is_never_overwritten(fresh, capsys):
    (fresh / "rules").mkdir()
    (fresh / "rules" / "global.md").write_text("my own rules\n", encoding="utf-8")
    assert cli.main(["init", str(fresh), "--owner", "Ada", "--apply"]) == 0
    assert "keep     rules/global.md (exists)" in capsys.readouterr().out
    assert (fresh / "rules" / "global.md").read_text(encoding="utf-8") == "my own rules\n"
    before = {p: p.read_bytes() for p in fresh.rglob("*") if p.is_file()}
    assert cli.main(["init", str(fresh), "--owner", "Ada", "--apply"]) == 0
    out = capsys.readouterr().out
    assert "create" not in out and "point" not in out and "keep     notes/graph (a graph store already)" in out
    assert {p: p.read_bytes() for p in fresh.rglob("*") if p.is_file()} == before


def test_a_team_a_tenant_and_another_pointer(fresh, brain_home, tmp_path, capsys):
    brain_home.mkdir(parents=True, exist_ok=True)
    (brain_home / paths.PERSONAL).write_text(json.dumps({"root": str(tmp_path / "other")}), encoding="utf-8")
    assert cli.main(["init", str(fresh), "--owner", "Team  Z", "--kind", "team", "--tenant", "team-z", "--tier",
                     "default", "--name", "team-z", "--apply"]) == 0
    out = capsys.readouterr().out
    assert "keep     " in out and "install.ps1 -Personal moves it" in out
    data = json.loads((fresh / "config.json").read_text(encoding="utf-8"))
    assert data["identity"] == {"owner": "Team Z", "kind": "team", "tenant": "team-z"}
    assert data["tier"] == {"base": "default"}
    assert "team-z:\n  root: .\n" in (fresh / "projects.yaml").read_text(encoding="utf-8")
    assert paths.pointer_root() == tmp_path / "other"   # never moved by brain init


@pytest.mark.parametrize("args, why", [([], "--owner NAME"), (["--owner", " "], "--owner NAME"),
                                       (["--owner", "Ada", "--name", "Bad Name"], "--name 'Bad Name'")])
def test_bad_arguments_plan_nothing(fresh, capsys, args, why):
    assert cli.main(["init", str(fresh), *args]) == 2
    assert why in capsys.readouterr().out and list(fresh.iterdir()) == []


def test_the_templates_name_no_one():
    """The starter files carry the owner's name only where brain init puts it: placeholders, no name."""
    for name in ("rules.md", "journal.md", "projects.yaml", "CLAUDE.md", "gitignore"):
        text = init.template(name)
        assert set(re.findall(r"\{(\w+)\}", text)) <= {"owner", "name", "title"} and "Ada" not in text, name
