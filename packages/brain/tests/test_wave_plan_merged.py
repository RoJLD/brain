"""wi-brain-wave-plan-merged: brain wave plan and brain next count an item whose PR merged (not closed yet) as done,
with brain wave close-merged's mapping (brain.closemerged.overlay: the PRs merged since the last tag, by the changelog
fragment they add or an item id in their title, git only): out of the lots, the rounds and the quick-win slot, a
satisfied prerequisite, listed apart in the plan's head; --include-merged keeps them in the lots, --no-merged reads
no PR. A repo that cannot be read (not a repo, git missing, git hanging) maps nothing: its items stay open, said.
Fixtures only: a repo built here, the tests' Ada."""

import json
import os
import shutil
import subprocess
from types import SimpleNamespace

import pytest
from conftest import GIT_ENV, git_init, run_git
from test_wave_plan import EDGES, NODES, SCHEMA

from brain import cli, closemerged, governor, lots, quota
from brain.commands import next as next_cmd
from brain.commands import wave as wave_cmd

pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="git not available")


@pytest.fixture
def root(tmp_path, monkeypatch):
    store = tmp_path / "root" / "notes" / "graph"
    (store / "nodes").mkdir(parents=True)
    (store / "edges").mkdir()
    (store / "schema.yaml").write_text(SCHEMA, encoding="utf-8")
    (store / "edges.yaml").write_text("", encoding="utf-8")
    (store / "nodes" / "work.yaml").write_text(NODES, encoding="utf-8", newline="\n")
    (store / "edges" / "work.yaml").write_text(EDGES, encoding="utf-8", newline="\n")
    monkeypatch.setattr(governor, "memory_info", lambda: {"committed": 40.0, "available_gb": 30.0})
    monkeypatch.setattr(quota, "load_status", lambda: {})
    return tmp_path / "root"


def _commit(repo, files: dict, message: str, day: str) -> None:
    for path, text in files.items():
        f = repo / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    run_git(repo, "add", "-A")
    env = dict(os.environ, **GIT_ENV, GIT_AUTHOR_DATE=f"{day}T10:00:00", GIT_COMMITTER_DATE=f"{day}T10:00:00")
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", message], check=True, env=env)


def _pr(repo, n: int, title: str, files: dict, day: str) -> None:
    """A PR merged as GitHub merges one: a merge commit whose body's first line is the PR's title."""
    run_git(repo, "checkout", "-q", "-b", f"pr{n}", "main")
    _commit(repo, files, title, day)
    run_git(repo, "checkout", "-q", "main")
    env = dict(os.environ, **GIT_ENV, GIT_AUTHOR_DATE=f"{day}T12:00:00", GIT_COMMITTER_DATE=f"{day}T12:00:00")
    subprocess.run(["git", "-C", str(repo), "merge", "-q", "--no-ff", "-m",
                    f"Merge pull request #{n} from demo/pr{n}\n\n{title}", f"pr{n}"], check=True, env=env)


@pytest.fixture
def engine(tmp_path, monkeypatch):
    for k, v in GIT_ENV.items():
        monkeypatch.setenv(k, v)
    repo = git_init(tmp_path / "engine")
    _commit(repo, {"README.md": "engine\n", "changes/wi-lots.md": "section: Added\n\n- before the tag\n"}, "base",
            "2030-01-01")
    run_git(repo, "tag", "v1.0.0")
    _pr(repo, 1, "The views", {"changes/wi-views.md": "section: Added\n\n- views\n"}, "2030-01-03")
    _pr(repo, 2, "Fix wi-outside", {"src/other.py": "x = 1\n"}, "2030-01-04")
    _pr(repo, 3, "The lots' fragment reworded", {"changes/wi-lots.md": "section: Added\n\n- reworded\n"},
        "2030-01-05")   # a fragment modified, not added: it maps nothing
    return repo


def _plan(root, repos, **kw):
    return lots.plan(root / "notes" / "graph", root, wave="1.1.0", repos=repos, **kw)


def test_a_merged_item_leaves_the_lots_and_satisfies_what_waits_on_it(root, engine):
    wp = _plan(root, [("engine", engine)])
    assert "wi-views" not in wp.units and "wi-lots" in wp.units   # wi-lots' fragment came before the tag
    assert wp.units["wi-views-more"].after == []   # its prerequisite merged: satisfied
    assert wp.units["wi-blank"].outside == []      # wi-outside, merged outside the wave: satisfied too
    assert wp.merged["items"] == {"wi-views": ["engine #1"]}
    assert wp.merged["outside"] == {"wi-outside": ["engine #2"]}
    assert wp.merged["counted"] == "done" and wp.merged["ranges"]["engine"].startswith("v1.0.0 (2030-01-01)..")
    assert all("wi-views" not in lot.items for lot in wp.lots)
    text = "\n".join(lots.render(wp))
    assert ("Merged, to close (1): wi-views (engine #1); out of the lots, counted done; "
            "brain wave close-merged 1.1.0 --write") in text
    assert "merged outside the wave, satisfied as prerequisites (1): wi-outside" in text
    assert wp.as_dict()["merged"]["items"] == {"wi-views": ["engine #1"]}
    assert ", 1 merged to close apart; round 1:" in lots.summary(wp)[0]


def test_without_repos_the_plan_is_as_before(root, engine):
    wp = _plan(root, None)
    assert "wi-views" in wp.units and wp.units["wi-views-more"].after == ["wi-views"] and wp.merged == {}
    assert not any(line.startswith("Merged, to close") for line in lots.render(wp))


def test_include_merged_keeps_them_in_the_lots_said_merged(root, engine):
    wp = _plan(root, [("engine", engine)], include_merged=True)
    assert wp.units["wi-views"].merged == ["engine #1"] and wp.units["wi-views-more"].after == ["wi-views"]
    assert wp.units["wi-blank"].outside == ["wi-outside"]
    text = "\n".join(lots.render(wp))
    assert "wi-views [P2, merged: engine #1] -> wi-views-more [P3, after wi-views]" in text
    assert "still in the lots (--include-merged)" in text and "merged outside the wave, counted open (1)" in text
    assert "merged to close apart" not in lots.summary(wp)[0]


@pytest.mark.parametrize("fault", ["not a repo", "git missing", "git hangs"])
def test_a_repo_that_cannot_be_read_leaves_its_items_open_and_says_so(root, engine, tmp_path, monkeypatch, fault):
    repo = engine
    if fault == "not a repo":
        repo = tmp_path / "plain"
        repo.mkdir()
    else:
        exc = FileNotFoundError("git") if fault == "git missing" else subprocess.TimeoutExpired("git", 120)

        def boom(*a, **kw):
            raise exc
        monkeypatch.setattr(closemerged.subprocess, "run", boom)
    wp = _plan(root, [("engine", repo)])
    assert "wi-views" in wp.units and wp.merged["items"] == {} and "engine" in wp.merged["skipped"]
    assert any(line.startswith("  merged PRs not read in engine: ") and line.endswith("(its items stay open)")
               for line in lots.render(wp))


def test_no_tag_before_the_release_reads_nothing(root, engine):
    run_git(engine, "tag", "-d", "v1.0.0")
    wp = _plan(root, [("engine", engine)])
    assert "wi-views" in wp.units and "no release tag before 1.1.0" in wp.merged["skipped"]["engine"]


@pytest.fixture
def registry(engine, monkeypatch):
    """The project's repos, as brain.projects names them: the engine built here."""
    repos = [SimpleNamespace(name="engine", path=engine)]
    monkeypatch.setattr(wave_cmd, "_project_repos", lambda args, root: repos)
    monkeypatch.setattr(next_cmd, "_repos", lambda args, root: repos)
    return repos


def test_the_command_reads_the_project_repos_and_its_flags(root, registry, capsys):
    base = ["--root", str(root), "wave", "plan", "1.1.0"]
    assert cli.main(base) == 0
    out = capsys.readouterr().out
    assert out.startswith("Wave 1.1.0 (wave-1.1.0): 7 open item(s) in ")   # 8 open, one merged
    assert "Merged, to close (1): wi-views (engine #1)" in out
    assert cli.main(base + ["--include-merged"]) == 0
    assert "wi-views [P2, merged: engine #1]" in capsys.readouterr().out
    assert cli.main(base + ["--no-merged"]) == 0
    out = capsys.readouterr().out
    assert "Merged, to close" not in out and "8 open item(s)" in out
    assert cli.main(base + ["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["merged"]["items"] == {"wi-views": ["engine #1"]}
    with pytest.raises(SystemExit):
        cli.main(base + ["--include-merged", "--no-merged"])


def test_next_counts_the_merged_items_done(root, registry, capsys):
    assert cli.main(["--root", str(root), "next"]) == 0
    out = capsys.readouterr().out
    assert ("  merged, to close (1), counted done: wi-views (brain wave close-merged 1.1.0 --write)") in out
    assert "wi-views [" not in out   # neither startable nor open any more
    assert "1 merged to close apart" in out
    assert cli.main(["--root", str(root), "next", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["merged"]["items"] == {"wi-views": ["engine #1"]} and data["lots"]["merged"]["counted"] == "done"
