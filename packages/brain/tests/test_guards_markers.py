"""Conflict markers (brain.markers; wi-brain-guard-conflict-markers): the commit guard refuses a commit that adds one
(check markers), brain check fails on a store, journal, decision log or record that holds one; a Markdown setext
heading and a test fixture pass. The markers are assembled at run time, so this file never holds one at a line's
start."""

import pytest
from conftest import run_git
from test_guards import bash, pwsh

from brain import cli, graph, guards, markers

OURS, THEIRS, MID, BASE = "<" * 7 + " HEAD", ">" * 7 + " claude/other", "=" * 7, "|" * 7 + " base"
CONFLICT = f"- {{id: wi-a, status: todo}}\n{OURS}\n- {{id: wi-b, status: doing}}\n{MID}\n" \
           f"- {{id: wi-b, status: done}}\n{THEIRS}\n"


# --- brain.markers --------------------------------------------------------------------------------------------------

def test_scan_text_finds_each_marker_with_its_line():
    assert markers.scan_text("notes/graph/nodes/work.yaml", CONFLICT) == [
        "notes/graph/nodes/work.yaml:2", "notes/graph/nodes/work.yaml:4", "notes/graph/nodes/work.yaml:6"]
    assert markers.scan_text("a.py", f"x = 1\n{BASE}\n") == ["a.py:2"]
    assert markers.scan_text("a.py", f"{MID}=\n{'<' * 7}x\n  {MID}\nx = '{OURS}'\n") == []   # not a marker's shape


@pytest.mark.parametrize("path,text,hits", [
    ("README.md", f"Title\n{MID}\n\nText.\n", []),                        # a setext heading
    ("docs/guide.rst", f"Usage\n{MID}\n", []),
    ("README.md", f"Text.\n\n{MID}\n", ["README.md:3"]),                   # under a blank line: no heading
    ("README.md", f"{MID}\nTitle\n", ["README.md:1"]),                     # at the top
    ("notes/journal.md", f"- a\n{OURS}\n- b\n{MID}\n- c\n{THEIRS}\n",      # a conflict in Markdown: the ======= is
     ["notes/journal.md:2", "notes/journal.md:4", "notes/journal.md:6"]),  # under a marker, not text
    ("config.yaml", f"Title\n{MID}\n", ["config.yaml:2"]),                 # no heading outside Markdown
    ("tests/fixtures/merge/work.yaml", CONFLICT, []),                      # a test's data
    ("tests/testdata/conflict.txt", CONFLICT, []),
])
def test_setext_headings_and_fixtures_pass(path, text, hits):
    assert markers.scan_text(path, text) == hits


def test_scan_diff_reads_added_lines_with_the_line_above():
    diff = (f"diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -3,1 +3,3 @@\n Intro\n"
            f"+Usage\n+{MID}\n"
            f"diff --git a/w.yaml b/w.yaml\n--- a/w.yaml\n+++ b/w.yaml\n@@ -1,1 +1,3 @@\n-{OURS}\n x: 1\n"
            f"+{THEIRS}\n+{MID}\n")
    assert markers.scan_diff(diff) == ["w.yaml:2", "w.yaml:3"]   # a removed marker is no hit


# --- the commit guard -----------------------------------------------------------------------------------------------

@pytest.fixture
def repo(git_repo, monkeypatch):
    monkeypatch.delenv(guards.ALLOW_ENV, raising=False)
    monkeypatch.setattr(guards, "gitleaks", lambda repo: None)
    monkeypatch.setenv("BRAIN_PROJECTS", str(git_repo / "no-registry.yaml"))
    return git_repo


def test_a_staged_marker_is_refused_with_file_and_line(repo):
    (repo / "work.yaml").write_text(CONFLICT, encoding="utf-8")
    run_git(repo, "add", "work.yaml")
    reason = bash(repo, 'git commit -m "merge"')
    assert "git commit refused: work.yaml:2 and 2 more adds a conflict marker" in reason
    assert "BRAIN_GUARD_ALLOW=markers" in reason
    assert "work.yaml:2" in pwsh(repo, 'git commit -m "merge"')


def test_a_marker_staged_by_the_same_command_or_commit_all_is_refused(repo):
    (repo / "notes" / "decisions.md").write_text(f"# Decisions\n{OURS}\nA\n{MID}\nB\n{THEIRS}\n", encoding="utf-8")
    assert "notes/decisions.md:2" in bash(repo, 'git commit -am "decisions"')
    assert "notes/decisions.md:2" in bash(repo, 'git add notes && git commit -m "decisions"')
    (repo / "new.yaml").write_text(f"{THEIRS}\n", encoding="utf-8")
    assert "new.yaml:1" in bash(repo, 'git add new.yaml && git commit -m "new"')


def test_a_merge_continue_is_read_too(repo):
    (repo / "work.yaml").write_text(CONFLICT, encoding="utf-8")
    run_git(repo, "add", "work.yaml")
    for sub in ("merge", "rebase", "cherry-pick"):
        assert f"git {sub} --continue refused: work.yaml:2" in bash(repo, f"git {sub} --continue")


@pytest.mark.parametrize("name,text", [
    ("README.md", f"# Demo\n\nUsage\n{MID}\n\nRun it.\n"),
    ("tests/fixtures/merge/work.yaml", CONFLICT),
    ("code.py", f"SEP = '{MID}'\nMARK = '{OURS}'\n"),
])
def test_headings_fixtures_and_quoted_markers_commit(repo, name, text):
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(text, encoding="utf-8")
    run_git(repo, "add", name)
    assert bash(repo, 'git commit -m "x"') is None


def test_removing_a_marker_commits(repo):
    (repo / "work.yaml").write_text(CONFLICT, encoding="utf-8")
    run_git(repo, "add", "work.yaml")
    run_git(repo, "commit", "-m", "broken")
    (repo / "work.yaml").write_text("- {id: wi-a, status: todo}\n- {id: wi-b, status: done}\n", encoding="utf-8")
    assert bash(repo, 'git commit -am "fix"') is None


# --- brain check ----------------------------------------------------------------------------------------------------

@pytest.fixture
def checked(store, monkeypatch, tmp_path):
    """The store fixture's brain, with research_graph check faked green (the graph check passed #189's stale files)."""
    monkeypatch.setattr(graph, "research_graph", lambda *a: 0)
    monkeypatch.setenv("BRAIN_PROJECTS", str(tmp_path / "no-registry.yaml"))
    return store.parents[1]


def _check(root):
    return cli.main(["--root", str(root), "check"])


@pytest.mark.parametrize("rel", ["notes/graph/nodes/work.yaml", "notes/graph/nodes/_generated_decisions.yaml",
                                 "notes/journal.md", "notes/decisions.md", "records/sessions/2026-11.jsonl"])
def test_brain_check_fails_on_a_marker(checked, rel, capsys):
    f = checked / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text((f.read_text(encoding="utf-8") if f.is_file() else "") + f"{OURS}\nx\n{THEIRS}\n", encoding="utf-8")
    assert _check(checked) == 1
    out = capsys.readouterr().out
    assert f"{f.as_posix()}:" in out and "holds a conflict marker: finish the merge in that file" in out


def test_brain_check_passes_a_setext_heading_in_the_journal(checked, capsys):
    (checked / "notes" / "journal.md").write_text(f"Journal\n{MID}\n\n## 2026-11-03\n- a\n", encoding="utf-8")
    assert _check(checked) == 0
    assert "conflict marker" not in capsys.readouterr().out
