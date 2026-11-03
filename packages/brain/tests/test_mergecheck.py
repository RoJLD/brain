"""wi-brain-merge-stale-main: brain merge-check, after a merge of main into a branch, finds what the resolution lost
(brain.mergecheck)."""

import json

import pytest

from brain import cli, mergecheck, projects

from conftest import run_git

WORK = """- {id: wi-a, type: WorkItem, status: todo,
   title: "A"}
"""
EDGES = "# 2026-11-01: wi-a (brain item add)\n- {from: wi-a, to: wi-x, type: depends_on}\n"
JOURNAL = "# Journal\n\n## 2026-11-01 — Start\n\n- one\n"


@pytest.fixture
def repo(make_repo):
    r = make_repo("brain", {"notes/graph/schema.yaml": "node_types: [WorkItem]\n", "notes/graph/nodes/work.yaml": WORK,
                            "notes/graph/edges/work.yaml": EDGES, "notes/journal.md": JOURNAL,
                            "notes/graph/nodes/_generated_x.yaml": "[]\n", "CHANGELOG.md": "# Changelog\n"})
    run_git(r, "checkout", "-q", "-b", "feat")
    make_repo.commit(r, {"notes/graph/nodes/work.yaml": WORK.replace('"A"}', '"A", props: {pr: "brain #2"}}')
                         + '- {id: wi-b, type: WorkItem, status: todo, title: "B"}\n',
                         "notes/graph/edges/work.yaml": "",          # brain item unlink: on purpose
                         "notes/journal.md": JOURNAL + "- two (the branch)\n"}, msg="branch work")
    run_git(r, "checkout", "-q", "main")
    make_repo.commit(r, {"notes/graph/nodes/work.yaml": WORK + '- {id: wi-c, type: WorkItem, status: todo, title: "C"}\n',
                         "notes/journal.md": JOURNAL + "- three (main)\n",
                         "CHANGELOG.md": "# Changelog\n\n- main's entry\n"}, msg="main moves")
    run_git(r, "checkout", "-q", "feat")
    return r


def _project(r):
    g = r / "notes" / "graph"
    return projects.Project(name="demo", root=r, stores=[g], journals=[r / "notes" / "journal.md"])


def test_watched_files_skip_the_generated_views(repo):
    files = mergecheck.watched(repo, _project(repo))
    assert files == {"notes/graph/nodes/work.yaml": "nodes", "notes/graph/edges/work.yaml": "append",
                     "notes/journal.md": "append", "CHANGELOG.md": "append"}


def test_a_branch_without_the_base_is_behind(repo):
    r = mergecheck.check(repo, _project(repo), "main", fetch=False)
    assert r["behind"] and mergecheck.failed(r)
    assert "behind: main is not merged" in "\n".join(mergecheck.render(r))


def test_a_resolution_that_drops_main_s_lines_is_caught(repo):
    run_git(repo, "merge", "-q", "-s", "ours", "-m", "bad resolution", "main")   # keeps the branch's side whole
    r = mergecheck.check(repo, _project(repo), "main", fetch=False)
    assert not r["behind"] and mergecheck.failed(r)
    assert r["lost_ids"] == [{"path": "notes/graph/nodes/work.yaml", "id": "wi-c"}]
    assert {(x["path"], x["text"]) for x in r["lost"]} == {("notes/journal.md", "- three (main)"),
                                                           ("CHANGELOG.md", ""), ("CHANGELOG.md", "- main's entry")}
    assert r["removed"] == 2   # the unlinked edge and its note: the branch's own commit removed them
    text = "\n".join(mergecheck.render(r))
    assert "lost id  notes/graph/nodes/work.yaml: wi-c" in text and "put each lost line back" in text


def test_a_good_resolution_passes(repo, make_repo):
    run_git(repo, "merge", "-q", "--no-commit", "-s", "ours", "main")
    make_repo.commit(repo, {"notes/graph/nodes/work.yaml": WORK.replace('"A"}', '"A", props: {pr: "brain #2"}}')
                            + '- {id: wi-c, type: WorkItem, status: todo, title: "C"}\n'
                            + '- {id: wi-b, type: WorkItem, status: todo, title: "B"}\n',
                            "notes/journal.md": JOURNAL + "- three (main)\n- two (the branch)\n",
                            "CHANGELOG.md": "# Changelog\n\n- main's entry\n"}, msg="good resolution")
    r = mergecheck.check(repo, _project(repo), "main", fetch=False)
    assert not mergecheck.failed(r) and r["changed"] == 1 and r["removed"] == 2
    assert mergecheck.render(r)[-1] == "ok: nothing of the base is lost"


def test_an_uncommitted_resolution_is_read_with_worktree(repo):
    run_git(repo, "merge", "-q", "--no-commit", "-s", "ours", "main")
    (repo / "notes" / "journal.md").write_text(JOURNAL + "- two (the branch)\n", encoding="utf-8")
    r = mergecheck.check(repo, _project(repo), "main", fetch=False, worktree=True)
    assert ("notes/journal.md", "- three (main)") in {(x["path"], x["text"]) for x in r["lost"]}


def test_cli_exit_codes(repo, capsys, monkeypatch):
    monkeypatch.chdir(repo)
    assert cli.main(["merge-check", "--base", "main", "--no-fetch"]) == 1
    assert "behind" in capsys.readouterr().out
    run_git(repo, "merge", "-q", "-s", "ours", "-m", "bad", "main")
    assert cli.main(["merge-check", "--base", "main", "--no-fetch", "--json", "--path", "CHANGELOG.md"]) == 1
    assert json.loads(capsys.readouterr().out)["lost"]
    assert cli.main(["merge-check", "--base", "nope", "--no-fetch"]) == 2
