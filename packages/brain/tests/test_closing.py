"""brain close (brain.closing): an item's definition of done from its merged PR in one command: the plan, then --write
closes the item with the PR and its merge's date, adds the journal's line, sets the features the PR names, checks its
changelog fragment, lists the milestones left with no open item and removes the PR's merged branch through tidy's plan.
Fixtures only: the PR is a dict as gh gives it, the repo built here."""

import json
import os
import shutil
import subprocess

import pytest
import yaml
from conftest import GIT_ENV, git_init, run_git

from brain import cli, closing

SCHEMA = ("node_types: [WorkItem, Milestone, Feature]\nedge_types: [part_of, depends_on]\n"
          "statuses: [todo, doing, blocked, done, dropped, pending, reached, have, partial, planned, no]\n")
NODES = """\
- {id: ms-close, type: Milestone, status: pending, title: "Closing", props: {trigger: "every closing step automated"}}
- {id: ms-big, type: Milestone, status: pending, title: "Bigger", props: {trigger: "all of it"}}
- {id: ms-old, type: Milestone, status: reached, title: "Old"}
- {id: wi-close, type: WorkItem, status: doing, title: "Close in one command", props: {pr: "engine #3"}}
- {id: wi-other, type: WorkItem, status: todo, title: "Another"}
- {id: wi-done, type: WorkItem, status: done, title: "Done", props: {pr: "engine #1", done: "2030-01-01 done"}}
"""
FEATURES = """\
- {id: feat-close, type: Feature, status: planned, title: "Close", props: {domain: workflow, repo: engine}}
- {id: feat-private-name, type: Feature, status: planned, title: "Aliased", props: {domain: workflow, repo: engine,
   public_id: feat-neutral}}
- {id: feat-applied, type: Feature, status: have, title: "Applied", props: {domain: workflow, repo: engine,
   status_merged: "2030-02-01T00:00:00Z"}}
"""
EDGES = """\
- {from: wi-close, to: ms-close, type: part_of}
- {from: wi-done, to: ms-close, type: part_of}
- {from: wi-close, to: ms-big, type: part_of}
- {from: wi-other, to: ms-big, type: part_of}
- {from: wi-close, to: ms-old, type: part_of}
"""
JOURNAL = "# Journal\n\n## 2030-01-01 — Start\n\n- began\n"
BODY = "Closes the item.\n\nfeat-close: have\nfeat-neutral: partial\nfeat-applied: have\nfeat-nowhere: have\n"


def _pr(**over) -> dict:
    pr = {"number": 7, "title": "One command closes an item", "body": BODY, "state": "MERGED",
          "mergedAt": "2030-01-05T12:00:00Z", "headRefName": "feat/close",
          "files": [{"path": "src/a.py"}, {"path": "changes/wi-close.md"}, {"path": "changes/wi-x-upgrade.md"}]}
    pr.update(over)
    return pr


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "brain"
    store = r / "notes" / "graph"
    (store / "nodes").mkdir(parents=True)
    (store / "edges").mkdir()
    (store / "schema.yaml").write_text(SCHEMA, encoding="utf-8")
    (store / "edges.yaml").write_text("", encoding="utf-8")
    (store / "nodes" / "work.yaml").write_text(NODES, encoding="utf-8", newline="\n")
    (store / "nodes" / "features.yaml").write_text(FEATURES, encoding="utf-8", newline="\n")
    (store / "edges" / "work.yaml").write_text(EDGES, encoding="utf-8", newline="\n")
    (r / "notes" / "journal.md").write_text(JOURNAL, encoding="utf-8", newline="\n")
    return r


@pytest.fixture
def gh(monkeypatch):
    """closing.fetch_pr answered from ``seen['pr']``; the calls recorded."""
    seen = {"pr": _pr(), "calls": []}

    def fake(repo_dir, number):
        seen["calls"].append((str(repo_dir), number))
        return dict(seen["pr"])
    monkeypatch.setattr(closing, "fetch_pr", fake)
    return seen


def _nodes(root, name="work.yaml"):
    return {n["id"]: n for n in yaml.safe_load((root / "notes" / "graph" / "nodes" / name).read_text("utf-8"))}


def _base(root, tmp_path, *more):
    return ["--root", str(root), "close", "wi-close", "--pr", "engine #7", "--repo-dir", str(tmp_path),
            "--no-tidy", *more]


def test_the_plan_says_each_step_and_writes_nothing(root, gh, tmp_path, capsys):
    assert cli.main(_base(root, tmp_path)) == 0
    out = capsys.readouterr().out
    assert gh["calls"] == [(str(tmp_path.resolve()), 7)]
    assert 'to close: wi-close --pr "engine #3, engine #7" --outcome "One command closes an item" (2030-01-05)' in out
    assert "journal: - wi-close done (engine #3, engine #7): One command closes an item" in out
    assert "feature: feat-close planned -> have" in out
    assert "feature: feat-private-name planned -> partial" in out   # named by its public_id
    assert "feature already applied: feat-applied" in out and "feature named, unknown: feat-nowhere" in out
    assert "fragment: changes/wi-close.md" in out
    assert "milestone ms-close: no open item left; its trigger: « every closing step automated »" in out
    assert "milestone ms-big: 1 open left (wi-other)" in out and "ms-old" not in out   # a reached one is not checked
    assert "not written: --write" in out
    assert _nodes(root)["wi-close"]["status"] == "doing"
    assert (root / "notes" / "journal.md").read_text("utf-8") == JOURNAL


def test_write_closes_journals_and_sets_the_features(root, gh, tmp_path, capsys):
    assert cli.main(_base(root, tmp_path, "--write", "--journal-title", "Closing day")) == 0
    out = capsys.readouterr().out
    assert 'closed: wi-close --pr "engine #3, engine #7" (2030-01-05)' in out and "written; then brain sync" in out
    item = _nodes(root)["wi-close"]
    assert item["status"] == "done" and item["props"]["pr"] == "engine #3, engine #7"
    assert item["props"]["done"] == "2030-01-05 One command closes an item"
    feats = _nodes(root, "features.yaml")
    assert feats["feat-close"]["status"] == "have"
    assert feats["feat-close"]["props"]["status_pr"] == "engine #7"
    assert feats["feat-close"]["props"]["status_merged"] == "2030-01-05T12:00:00Z"
    assert feats["feat-private-name"]["status"] == "partial"
    assert feats["feat-applied"]["props"]["status_merged"] == "2030-02-01T00:00:00Z"   # a later merge stands
    journal = (root / "notes" / "journal.md").read_text("utf-8")
    assert "— Closing day\n\n- wi-close done (engine #3, engine #7): One command closes an item\n" in journal
    assert journal.startswith(JOURNAL)
    # once closed, a second run closes nothing and journals nothing
    assert cli.main(_base(root, tmp_path, "--write")) == 0
    assert "closed:" not in capsys.readouterr().out
    assert (root / "notes" / "journal.md").read_text("utf-8") == journal


def test_the_line_goes_under_today_when_today_has_an_entry(root, gh, tmp_path, monkeypatch):
    today = closing.date.today().isoformat()
    (root / "notes" / "journal.md").write_text(JOURNAL + f"\n## {today} — Today\n\n- a line\n", encoding="utf-8")
    assert cli.main(_base(root, tmp_path, "--write", "--outcome", "done by hand")) == 0
    text = (root / "notes" / "journal.md").read_text("utf-8")
    assert text.endswith("- a line\n- wi-close done (engine #3, engine #7): done by hand\n")
    assert text.count(f"## {today}") == 1


def test_a_pr_not_merged_is_refused_and_nothing_written(root, gh, tmp_path, capsys):
    gh["pr"] = _pr(state="OPEN", mergedAt=None)
    assert cli.main(_base(root, tmp_path)) == 1
    assert "refused: engine #7 is not merged (open): close it after the merge" in capsys.readouterr().out
    assert cli.main(_base(root, tmp_path, "--write")) == 2
    assert "nothing written" in capsys.readouterr().out
    assert _nodes(root)["wi-close"]["status"] == "doing"
    assert _nodes(root, "features.yaml")["feat-close"]["status"] == "planned"


def test_an_unknown_item_is_refused(root, gh, tmp_path, capsys):
    args = ["--root", str(root), "close", "wi-nowhere", "--pr", "engine #7", "--repo-dir", str(tmp_path), "--no-tidy",
            "--json"]
    assert cli.main(args) == 1
    assert json.loads(capsys.readouterr().out)["problems"] == ["wi-nowhere: unknown node"]


def test_an_item_already_closed_keeps_its_close_and_gets_its_features(root, gh, tmp_path, capsys):
    gh["pr"] = _pr(files=[])
    args = ["--root", str(root), "close", "wi-done", "--pr", "engine #7", "--repo-dir", str(tmp_path), "--no-tidy",
            "--write"]
    assert cli.main(args) == 0
    out = capsys.readouterr().out
    assert "fragment: none of the PR's names wi-done" in out
    assert _nodes(root)["wi-done"]["props"] == {"pr": "engine #1", "done": "2030-01-01 done"}
    assert _nodes(root, "features.yaml")["feat-close"]["status"] == "have"
    assert (root / "notes" / "journal.md").read_text("utf-8") == JOURNAL


def test_parse_ref_reads_the_forms_of_a_pr():
    assert closing.parse_ref("engine #12") == ("engine", 12)
    assert closing.parse_ref("#12", "engine") == ("engine", 12)
    assert closing.parse_ref(" 12 ", "") == ("", 12)
    with pytest.raises(closing.CloseError):
        closing.parse_ref("engine twelve")


def test_a_repo_the_project_does_not_have_is_refused(root, gh, capsys):
    assert cli.main(["--root", str(root), "close", "wi-close", "--pr", "nowhere #7"]) == 2
    assert "nowhere: no repo of that name in the project" in capsys.readouterr().err
    assert gh["calls"] == []


def test_fetch_pr_says_why_gh_failed(monkeypatch, tmp_path):
    def run(*a, **k):
        return subprocess.CompletedProcess(a, 1, "", "no pull requests found")
    monkeypatch.setattr(closing.subprocess, "run", run)
    with pytest.raises(closing.CloseError, match="no pull requests found"):
        closing.fetch_pr(tmp_path, 7)
    monkeypatch.setattr(closing.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "[]", ""))
    with pytest.raises(closing.CloseError, match="not a PR"):
        closing.fetch_pr(tmp_path, 7)


@pytest.mark.skipif(not shutil.which("git"), reason="git not available")
def test_tidy_removes_the_prs_merged_branch_and_no_other(root, gh, tmp_path, monkeypatch, capsys):
    for k, v in GIT_ENV.items():
        monkeypatch.setenv(k, v)
    repo = git_init(tmp_path / "engine")
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "base")
    for branch in ("feat/close", "feat/other"):
        run_git(repo, "branch", branch)
    monkeypatch.setattr(closing.tidy, "_open_pr_heads", lambda r: (set(), ""), raising=False)
    monkeypatch.chdir(tmp_path)
    args = ["--root", str(root), "close", "wi-close", "--pr", "engine #7", "--repo-dir", str(repo)]
    assert cli.main(args) == 0
    out = capsys.readouterr().out
    assert "tidy: remove branch feat/close (merged)" in out and "feat/other" not in out
    assert cli.main(args + ["--write"]) == 0
    assert "tidy: deleted branch feat/close" in capsys.readouterr().out
    branches = subprocess.run(["git", "-C", str(repo), "branch", "--format=%(refname:short)"], capture_output=True,
                              text=True, check=True, env=dict(os.environ, **GIT_ENV)).stdout.split()
    assert sorted(branches) == ["feat/other", "main"]
