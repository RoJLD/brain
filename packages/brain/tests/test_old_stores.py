"""The old-store fixture (wi-brain-old-store-fixture; spec-brain-waves-retro 4): every store-reading command of this
checkout runs on a brain a released engine wrote, never only on stores its own code wrote. brain #33's blocking
finding was the case: brain lesson add refused every store made before the PR, and its tests only used stores the PR
wrote.

tests/fixtures/stores/<tag>/brain/ is the brain as that tag's engine wrote it through its own commands (brain init,
items, a milestone, a decision, a journal line, a lesson where it had one, an AR, an SR, the views), frozen by
installer/freeze_store.py and never edited; freeze.json says what it ran. Each test copies one, commits it, moves
the pin and runs brain sync as brain update does, then runs this checkout strict (BRAIN_STRICT=1, as CI): a command either works or refuses
cleanly, with its reason and no traceback, and nothing it did not mean to write changes."""

import json
import re
import shutil
from pathlib import Path

import pytest
from brain import __version__, cli, config, graph, skew
from conftest import git_init, run_git

STORES = Path(__file__).parent / "fixtures" / "stores"
TAGS = sorted((d.name for d in STORES.glob("v*") if (d / "brain" / "config.json").is_file()),
              key=lambda t: tuple(int(x) for x in t[1:].split(".")))


def ran(tag: str) -> dict[str, bool]:
    """The freeze's steps for ``tag``: {step: ok}."""
    data = json.loads((STORES / tag / "freeze.json").read_text(encoding="utf-8"))
    return {s["step"]: s["ok"] for s in data["steps"]}


def frozen_copy(tmp_path: Path, tag: str, monkeypatch) -> Path:
    """A copy of the frozen brain of ``tag``, committed on main, its pin moved to this engine (brain update's first
    write), and this dev engine standing for that release (brain.skew), as test_init does."""
    root = tmp_path / f"old-brain-{tag}"     # the tag in its name: tag_of
    shutil.copytree(STORES / tag / "brain", root)
    git_init(root)
    cfg = root / "config.json"
    data = json.loads(cfg.read_text(encoding="utf-8"))
    data.setdefault("engine", {})["pin"] = f"v{__version__}"
    cfg.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    commit(root, f"the brain {tag} wrote, its pin moved")
    monkeypatch.delenv("BRAIN_CONFIG", raising=False)
    monkeypatch.delenv("BRAIN_PROJECTS", raising=False)
    monkeypatch.setattr(skew, "running", lambda: [skew.Engine(d, __version__, f"v{__version__}", "0" * 40)
                                                  for d, _ in skew.DISTS])
    return root


def commit(root: Path, message: str) -> None:
    run_git(root, "add", "-A")
    run_git(root, "commit", "-q", "--allow-empty", "-m", message)


@pytest.fixture(params=TAGS)
def raw(request, tmp_path, monkeypatch, brain_home):
    """The frozen brain as the upgrade finds it: the pin moved, nothing rendered again yet."""
    return frozen_copy(tmp_path, request.param, monkeypatch)


@pytest.fixture(params=TAGS)
def old(request, tmp_path, monkeypatch, brain_home, capsys):
    """The frozen brain after brain update: the pin moved, brain sync run and committed (docs/install.md)."""
    root = frozen_copy(tmp_path, request.param, monkeypatch)
    assert brain(root, "sync") == 0, capsys.readouterr().out
    commit(root, "brain sync after the upgrade")
    capsys.readouterr()
    return root


def tag_of(root: Path) -> str:
    return root.name.removeprefix("old-brain-")


def brain(root: Path, *args: str) -> int:
    return cli.main(["--root", str(root), *args])


def clean(out: str) -> bool:
    return "Traceback" not in out and "usage: brain" not in out


def test_there_is_a_frozen_store_of_a_released_engine():
    """The fixture exists and is what a tag wrote: the version PR adds the last tag's (docs/release.md; release_check
    refuses a version PR without it)."""
    assert TAGS, f"no frozen store under {STORES}"
    for tag in TAGS:
        info = json.loads((STORES / tag / "freeze.json").read_text(encoding="utf-8"))
        assert info["tag"] == tag and info["engine"] == tag[1:] and info["source"] == "tag"
        steps = ran(tag)
        assert all(steps[s] for s in ("init apply", "first commit", "item", "decision", "check")), steps
    assert any(not ran(t).get("lesson") for t in TAGS), "no store from before the Lesson type"


def test_check_before_sync_finds_only_the_plugin_to_render(raw, capsys):
    """Before brain sync, the one failure is the plugin the old engine rendered (its hooks carry its version): the
    graph, the records and the boundary read clean, strict."""
    rc = brain(raw, "check")
    out = capsys.readouterr().out
    assert clean(out) and "graph-check OK" in out and "public scan green" in out
    if rc:
        assert re.search(r"^brain render: \d+ file\(s\) not current", out, re.M), out
        # the one failure: the plugin rendered again, and nothing else, check passes
        assert brain(raw, "render", "--target", "claude", "--write") == 0
        commit(raw, "the plugin rendered again")
        capsys.readouterr()
        assert brain(raw, "check") == 0, capsys.readouterr().out
    assert brain(raw, "record", "check") == 0
    assert "0 error(s), 0 warning(s)" in capsys.readouterr().out
    assert config.check(raw) == []


def test_sync_then_check_strict(raw, capsys):
    """brain sync, the documented step after an upgrade (brain update runs it): then brain check passes, strict."""
    assert brain(raw, "sync") == 0
    commit(raw, "brain sync after the upgrade")
    assert brain(raw, "check") == 0
    out = capsys.readouterr().out
    assert "graph-check OK" in out and clean(out)


def test_items_are_read_and_written(old, capsys):
    store = old / "notes" / "graph"
    nodes = graph.node_index(store)
    assert {"wi-first", "wi-second", "ms-first-release"} <= set(nodes)
    assert nodes["wi-first"][1]["status"] == "done"
    assert brain(old, "item", "show", "wi-second") == 0
    out = capsys.readouterr().out
    assert "wi-first" in out and clean(out)                      # its depends_on edge, read back
    assert brain(old, "item", "add", "wi-third", "--title", "A third item", "--after", "wi-second") == 0
    assert brain(old, "item", "set", "wi-second", "status=doing") == 0
    assert brain(old, "item", "close", "wi-second", "--pr", "ada/brain #2") == 0
    assert graph.node_index(store)["wi-second"][1]["status"] == "done"
    assert brain(old, "items") == 0 and clean(capsys.readouterr().out)
    assert brain(old, "check") == 0


def test_lessons_are_listed_and_added_or_refused_with_the_way(old, capsys):
    """A store with the Lesson type takes a new lesson; one made before it lists nothing and refuses an add with
    the way to add the type (brain #33: it refused every store made before the PR, unread)."""
    assert brain(old, "lesson") == 0
    listed = capsys.readouterr().out
    assert clean(listed)
    has = "Lesson" in (old / "notes" / "graph" / "schema.yaml").read_text(encoding="utf-8")
    if ran(tag_of(old)).get("lesson"):
        assert "les-ada-first-page" in listed
    rc = brain(old, "lesson", "add", "les-ada-second", "--title", "Commit before the review", "--trigger",
               "a review", "--anti-pattern", "reviewed an uncommitted tree", "--check", "`git status` is clean",
               "--from", "wi-second", "--new")
    out = capsys.readouterr()
    assert clean(out.out + out.err)
    if has:
        assert rc == 0 and "les-ada-second" in graph.node_index(old / "notes" / "graph")
        assert brain(old, "check") == 0
    else:
        assert rc != 0 and "docs/lessons.md" in out.out + out.err   # the way to add the type, never a crash


def test_retro_reads_an_item(old, capsys):
    """brain retro on an item the old engine closed: its friction signals and five questions, nothing recorded."""
    before = (old / "notes" / "graph" / "nodes" / "work.yaml").read_bytes()
    assert brain(old, "retro", "wi-first", "--no-scan") == 0
    out = capsys.readouterr().out
    assert "wi-first" in out and clean(out)
    assert (old / "notes" / "graph" / "nodes" / "work.yaml").read_bytes() == before


def test_nothing_unmeant_changes(old):
    """The reads write nothing: after check, item show, lesson list and retro, git sees no change."""
    for args in (["check"], ["item", "show", "wi-first"], ["lesson"], ["retro", "wi-first", "--no-scan"],
                 ["record", "check"]):
        assert brain(old, *args) == 0, args
    assert run_git(old, "status", "--porcelain") == ""
