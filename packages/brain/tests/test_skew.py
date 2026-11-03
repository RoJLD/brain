"""The running engine against config.json engine.pin (brain.skew, wi-brain-engine-version-skew): brain check warns,
brain sync, refresh and render --write refuse unless --force; an engine ahead of the pin, behind it, and equal."""

import json

import pytest

from brain import cli, skew

PIN = "v0.2.3"
RELEASE = [skew.Engine("brain", "0.2.3", PIN, "2c9cc77aaaa"), skew.Engine("research-graph", "0.2.3", PIN, "2c9cc77")]
AHEAD = [skew.Engine("brain", "0.2.4", "v0.2.4", "abc1234"), skew.Engine("research-graph", "0.2.4", "v0.2.4", "abc")]
BEHIND = [skew.Engine("brain", "0.2.1", "v0.2.1", "def5678"), RELEASE[1]]


def test_ahead_behind_and_equal():
    assert skew.problems(PIN, RELEASE) == []
    assert skew.problems(PIN, AHEAD) == ["brain 0.2.4 is ahead of the pin v0.2.3",
                                         "research-graph 0.2.4 is ahead of the pin v0.2.3"]
    assert skew.problems(PIN, BEHIND) == ["brain 0.2.1 is behind the pin v0.2.3"]


def test_the_pins_version_from_other_code_is_a_dev_engine():
    branch = [skew.Engine("brain", "0.2.3", "main", "9f8e7d6c5")]
    assert skew.problems(PIN, branch) == ["brain 0.2.3 runs from git main@9f8e7d6, not the v0.2.3 release"]
    folder = [skew.Engine("brain", "0.2.3", folder="/src/brain")]
    assert skew.problems(PIN, folder, tag_check=lambda f, t: False) == [
        "brain 0.2.3 runs from folder /src/brain, a dev engine not at v0.2.3"]
    assert skew.problems(PIN, folder, tag_check=lambda f, t: (f, t) == ("/src/brain", PIN)) == []
    assert skew.problems(PIN, [skew.Engine("brain", "0.2.3")]) == []   # a wheel: its version alone
    assert skew.problems(PIN, [skew.Engine("brain", "0.3.0.dev1")]) == [
        "brain 0.3.0.dev1 is not a release version (the pin is v0.2.3)"]
    assert skew.how(None, PIN, folder) == "run the v0.2.3 engine (brain update, or its venv), or --force"


def test_no_pin_or_a_pin_that_is_not_a_tag_is_not_compared():
    assert skew.problems(None, AHEAD) == [] and skew.problems("main", AHEAD) == []


def test_where_an_engine_was_installed_from(monkeypatch):
    import brain
    here = __import__("pathlib").Path(brain.__file__).resolve()
    monkeypatch.setattr(skew, "_installed_file", lambda dist, module: here)
    monkeypatch.setattr(skew, "_direct_url", lambda dist: {
        "url": "https://github.com/someone/brain.git", "subdirectory": "packages/brain",
        "vcs_info": {"vcs": "git", "requested_revision": PIN, "commit_id": "2c9cc7737eb1"}})
    assert skew.engine_of("brain", "brain") == skew.Engine("brain", brain.__version__, PIN, "2c9cc7737eb1")
    monkeypatch.setattr(skew, "_direct_url", lambda dist: {"url": "file:///E:/work/brain", "dir_info": {}})
    assert skew.engine_of("brain", "brain").folder.replace("\\", "/").endswith("work/brain")
    monkeypatch.setattr(skew, "_direct_url", lambda dist: {"url": "file:///E:/work/brain",
                                                           "dir_info": {"editable": True}})
    assert skew.engine_of("brain", "brain").folder == str(here.parent)
    monkeypatch.setattr(skew, "_installed_file", lambda dist, module: None)   # imported from a source tree
    monkeypatch.setattr(skew, "_direct_url", lambda dist: {})
    assert skew.engine_of("brain", "brain").folder == str(here.parent)
    assert {e.name for e in skew.running()} == {"brain", "research-graph"}


def test_at_tag_reads_the_checkout(git_repo):
    from conftest import run_git
    run_git(git_repo, "tag", PIN)
    assert skew.at_tag(str(git_repo), PIN) is True
    (git_repo / "notes" / "extra.md").write_text("dirty\n", encoding="utf-8")
    assert skew.at_tag(str(git_repo), PIN) is False
    assert skew.at_tag(str(git_repo), "v9.9.9") is False


@pytest.fixture
def pinned(store, tmp_path, monkeypatch):
    """A brain whose config.json pins v0.2.3, with a store to sync."""
    cfg = tmp_path / "pinned-config.json"
    cfg.write_text(json.dumps({"v": 1, "identity": {"owner": "Ada", "kind": "person"},
                               "engine": {"repo": "someone/brain", "pin": PIN}}), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(cfg))
    return store.parent.parent


@pytest.mark.parametrize("engines,refused", [(AHEAD, True), (BEHIND, True), (RELEASE, False)])
def test_sync_refuses_another_engine_unless_forced(pinned, monkeypatch, capsys, engines, refused):
    monkeypatch.setattr(skew, "running", lambda: engines)
    kanban = pinned / "notes" / "kanban_graph.md"
    rc = cli.main(["--root", str(pinned), "sync", "--offline"])
    err = capsys.readouterr().err
    if not refused:
        assert rc == 0 and kanban.is_file() and "engine.pin" not in err
        return
    assert rc == 1 and not kanban.exists()
    assert "brain sync: the running engine is not config.json engine.pin v0.2.3: brain 0.2" in err
    assert "--force" in err
    if engines is AHEAD:   # after brain update: the pin to move, in one line
        assert (f"brain sync: to keep this engine, set engine.pin to v0.2.4 in {pinned.parent / 'pinned-config.json'} "
                "and commit it") in err
    else:
        assert "to keep this engine, set engine.pin to v0.2.1" in err
    assert cli.main(["--root", str(pinned), "refresh", "--offline"]) == 1
    assert cli.main(["--root", str(pinned), "sync", "--offline", "--force"]) == 0 and kanban.is_file()
    assert "(--force: written anyway)" in capsys.readouterr().err


def test_check_warns_and_render_write_refuses(pinned, monkeypatch, capsys):
    monkeypatch.setattr(skew, "running", lambda: AHEAD)
    cli.main(["--root", str(pinned), "check"])
    out = capsys.readouterr().out
    assert "warning: the running engine is not config.json engine.pin v0.2.3: brain 0.2.4 is ahead" in out
    assert cli.main(["--root", str(pinned), "render", "--write"]) == 1
    assert "brain render: the running engine is not config.json engine.pin" in capsys.readouterr().err
    monkeypatch.setattr(skew, "running", lambda: RELEASE)
    cli.main(["--root", str(pinned), "check"])
    assert "engine.pin" not in capsys.readouterr().out
