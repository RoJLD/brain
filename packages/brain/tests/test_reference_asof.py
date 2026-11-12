"""wi-brain-reference-asof: the technical reference as of a wave, a milestone, a date or a git ref, read from git,
with « Changes since » the wave before and a pending milestone's target view, written under BRAIN_HOME/views, never
into the repo (brain.asof)."""

import shutil
from pathlib import Path

import pytest

from brain import asof, cli
from conftest import git_init, run_git

FIXTURE = Path(__file__).parent / "fixtures" / "reference"
WAVES = ("- {id: wave-0.1.0, type: Milestone, status: reached, title: Wave 0.1.0, props: {kind: wave, release: 0.1.0, "
         "reached: \"2026-10-02: closed\"}}\n"
         "- {id: wave-0.2.0, type: Milestone, status: pending, title: Wave 0.2.0, props: {kind: wave, release: 0.2.0, "
         "trigger: two kettles}}\n")


def _commit(root, day, message, monkeypatch):
    monkeypatch.setenv("GIT_AUTHOR_DATE", f"{day}T12:00:00+00:00")
    monkeypatch.setenv("GIT_COMMITTER_DATE", f"{day}T12:00:00+00:00")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-q", "-m", message)


@pytest.fixture
def lab(tmp_path, monkeypatch):
    """The reference fixture in a git repo: a first commit the day wave 0.1.0 was reached, a second three days later
    (wi-pour done, a module and a feature changed), wave 0.2.0 still pending."""
    root = git_init(tmp_path / "lab")
    shutil.copytree(FIXTURE, root, dirs_exist_ok=True)
    store = root / "notes" / "graph"
    (store / "nodes" / "waves.yaml").write_text(WAVES, encoding="utf-8")
    (store / "edges" / "waves.yaml").write_text("- {from: wi-weigh, to: wave-0.2.0, type: part_of}\n"
                                                "- {from: wi-pour, to: wave-0.2.0, type: part_of}\n", encoding="utf-8")
    (root / "projects.yaml").write_text("lab: {root: .}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(root / "projects.yaml"))
    monkeypatch.chdir(root)
    _commit(root, "2026-10-02", "first", monkeypatch)
    work = store / "nodes" / "work.yaml"
    work.write_text(work.read_text(encoding="utf-8").replace("id: wi-pour, type: WorkItem, status: todo",
                                                             "id: wi-pour, type: WorkItem, status: done"),
                    encoding="utf-8")
    (store / "modules.yaml").write_text((store / "modules.yaml").read_text(encoding="utf-8")
                                        + "- {id: K3, name: kettle-lid, brick: K, phase: V1, status: proposed}\n",
                                        encoding="utf-8")
    feats = store / "nodes" / "features.yaml"
    text = feats.read_text(encoding="utf-8")
    assert "status: planned" in text
    feats.write_text(text.replace("status: planned", "status: have", 1), encoding="utf-8")
    _commit(root, "2026-10-05", "second", monkeypatch)
    return root, store


def test_a_reached_wave_is_read_at_the_day_it_was_reached(lab):
    root, store = lab
    point, files = asof.render(store, "0.1.0")   # by its release too
    first = run_git(root, "rev-list", "-1", "HEAD~1").strip()
    assert (point.label, point.sha, point.day, point.pending) == ("wave-0.1.0", first, "2026-10-02", False)
    text = files["README.md"]
    assert text.split("\n")[4] == f"As of `wave-0.1.0`: commit `{first[:12]}`, 2026-10-02 (brain reference --asof; " \
                                  "not the repo's copy)."
    assert "## Changes since" not in text and "modules/K3.md" not in files   # nothing before; K3 came later
    assert "- [ ] `wi-pour`" in files["modules/K1.md"]


def test_a_date_after_the_wave_says_what_changed_since(lab):
    root, store = lab
    point, files = asof.render(store, "2026-10-06")
    assert point.sha == run_git(root, "rev-parse", "HEAD").strip() and point.day == "2026-10-06"
    changes = files["README.md"].split("## Changes since wave-0.1.0\n", 1)[1]
    assert "### Items done: 1\n\n- `wi-pour` Pour for Ada" in changes
    assert "### Modules added: 1\n\n- `K3`" in changes
    assert "### Features whose status changed: 1" in changes and "planned → have" in changes
    assert "modules/K3.md" in files


def test_a_pending_wave_is_read_as_of_now_with_its_target_view(lab):
    root, store = lab
    point, files = asof.render(store, "wave-0.2.0")
    assert point.pending and point.sha == run_git(root, "rev-parse", "HEAD").strip()
    target = files["README.md"].split("## Target: at the end of wave-0.2.0\n", 1)[1]
    assert "Reached when: two kettles" in target
    assert "### Items: 1 done, 1 left" in target and "- [x] `wi-pour`" in target and "- [ ] `wi-weigh`" in target


def test_a_git_ref_and_what_names_nothing(lab):
    root, store = lab
    point, _ = asof.render(store, "HEAD~1")
    assert point.day == "2026-10-02"
    for bad in ("nope", "--upload-pack=x", "2025-01-01"):
        with pytest.raises(asof.AsofError):
            asof.render(store, bad)


def test_cli_writes_under_brain_home_never_into_the_repo(lab, capsys):
    root, store = lab
    assert cli.main(["reference", "--asof", "wave-0.1.0"]) == 0
    out = asof.out_dir("lab", asof.Point("wave-0.1.0", "x"))
    assert (out / "README.md").is_file() and (out / "modules" / "K1.md").is_file()
    assert "reference as of wave-0.1.0" in capsys.readouterr().out
    assert run_git(root, "status", "--porcelain").strip() == "" and not (root / "docs" / "reference").exists()
    assert cli.main(["reference", "--asof", "wave-0.1.0", "--write"]) == 1
    assert cli.main(["reference", "--asof", "nope"]) == 1 and "brain reference --asof:" in capsys.readouterr().err


def test_the_modules_registry_kept_in_another_store_is_read_at_that_commit(lab, monkeypatch):
    """config.json modules.store: the registry of another store of the repo, read as of the commit too."""
    root, store = lab
    other = root / "atlas" / "graph"
    other.mkdir(parents=True)
    shutil.copy(store / "schema.yaml", other / "schema.yaml")
    (other / "nodes").mkdir()
    (store / "modules.yaml").rename(other / "modules.yaml")
    (root / "config.json").write_text('{"v": 1, "modules": {"store": "atlas"}}\n', encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(root / "config.json"))   # this repo's brain, not the tests' default one
    (root / "projects.yaml").write_text("lab: {root: .}\natlas: {root: ., stores: [atlas/graph], journal: "
                                        "atlas/journal.md, decisions: atlas/decisions.md}\n", encoding="utf-8")
    (root / "atlas" / "journal.md").write_text("# Journal\n", encoding="utf-8")
    (root / "atlas" / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    _commit(root, "2026-10-07", "registry moved", monkeypatch)
    text = (other / "modules.yaml").read_text(encoding="utf-8")
    (other / "modules.yaml").write_text(text + "- {id: K4, name: kettle-spout, brick: K, phase: V1}\n",
                                        encoding="utf-8")
    _commit(root, "2026-10-08", "K4", monkeypatch)
    _, files = asof.render(store, "2026-10-07")
    assert "modules/K3.md" in files and "modules/K4.md" not in files   # the registry as it was that day
