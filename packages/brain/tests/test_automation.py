"""``brain automation list`` (brain.commands.automation, wi-brain-automation-catalogue): the automation catalogue
(brain.gestures.CATALOGUE) printed as text and as JSON, read only, with no root, config or project needed. The
catalogue's own invariants (ids, ceilings, the floor) are tests/test_gestures.py's."""

import json

import pytest

from brain import cli, gestures
from brain.commands import automation


def test_list_json_is_the_catalogue(capsys):
    assert cli.main(["automation", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == json.loads(json.dumps(gestures.catalogue()))


def test_list_text_has_one_block_per_gesture(capsys):
    assert cli.main(["automation", "list"]) == 0
    out = capsys.readouterr().out
    locked = sum(1 for a in gestures.CATALOGUE if a.floor)
    assert out.startswith(f"automation catalogue v1: {len(gestures.CATALOGUE)} gestures, levels manual < ask < auto; "
                          f"{locked} locked by the floor")
    heads = [line.split()[0] for line in out.splitlines()[1:-1] if not line.startswith(" ")]
    assert heads == [a.id for a in gestures.CATALOGUE]
    assert "if: fast-forward only" in out and "locked: keys" in out and "commands: brain release tag" in out
    assert out.rstrip().endswith("harness, Claude Code's own confirmation (the app)")


def test_a_floor_gesture_shows_locked_at_manual():
    lines = automation._text(gestures.catalogue())
    vault = next(line for line in lines if line.startswith("vault-open "))
    assert "manual (default)" in vault and "ceiling manual" in vault and vault.endswith("locked: keys")
    clone = next(line for line in lines if line.startswith("engine-clone-pull "))
    assert "auto   (default)" in clone and "locked" not in clone


def test_it_needs_no_project_or_config(tmp_path, monkeypatch, capsys):
    """Machine-wide and read only: it runs outside any brain, with no config.json and no projects.yaml."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BRAIN_CONFIG", str(tmp_path / "missing.json"))
    monkeypatch.setenv("BRAIN_PROJECTS", str(tmp_path / "missing.yaml"))
    monkeypatch.delenv("BRAIN_ROOT", raising=False)
    assert cli.main(["automation", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["v"] == gestures.CATALOGUE_V
    assert list(tmp_path.iterdir()) == []   # it wrote nothing


def test_a_subcommand_is_required():
    with pytest.raises(SystemExit):
        cli.main(["automation"])
