"""wi-brain-merge-stale-main: brain merge-check, after a merge of main into a branch, finds what the resolution lost
(brain.mergecheck), the three sides compared: main, the branch before the merge and their merge base."""

import json

import pytest

from brain import cli, mergecheck, projects

from conftest import run_git

A = '- {id: wi-a, type: WorkItem, status: todo, title: "A"}\n'
D = '- {id: wi-d, type: WorkItem, status: todo, title: "D"}\n'
C = '- {id: wi-c, type: WorkItem, status: todo, title: "C"}\n'
B = '- {id: wi-b, type: WorkItem, status: todo, title: "B"}\n'
A_CLOSED = '- {id: wi-a, type: WorkItem, status: done, title: "A", props: {pr: "brain #2"}}\n'
A_MAIN = '- {id: wi-a, type: WorkItem, status: todo, title: "A", props: {priority: P1}}\n'
A_BOTH = '- {id: wi-a, type: WorkItem, status: done, title: "A", props: {pr: "brain #2", priority: P1}}\n'
EDGES = "# 2026-11-01: wi-a (brain item add)\n- {from: wi-a, to: wi-d, type: depends_on}\n"
JOURNAL = "# Journal\n\n## 2026-11-01 — Start\n\n- one\n"
NODES, EDGE_F, JOURN, LOG = ("notes/graph/nodes/work.yaml", "notes/graph/edges/work.yaml", "notes/journal.md",
                             "CHANGELOG.md")


@pytest.fixture
def repo(make_repo):
    """main: wi-a and wi-d; the branch closes wi-a, removes wi-d and its edge, adds wi-b and a journal line; main then
    adds wi-c, a priority on wi-a, a journal line, a CHANGELOG entry and a new edge file."""
    r = make_repo("brain", {"notes/graph/schema.yaml": "node_types: [WorkItem]\n", NODES: A + D, EDGE_F: EDGES,
                            JOURN: JOURNAL, "notes/graph/nodes/_generated_x.yaml": "[]\n", LOG: "# Changelog\n"})
    run_git(r, "checkout", "-q", "-b", "feat")
    make_repo.commit(r, {NODES: A_CLOSED + B, EDGE_F: "", JOURN: JOURNAL + "- two (the branch)\n"}, msg="branch work")
    run_git(r, "checkout", "-q", "main")
    make_repo.commit(r, {NODES: A_MAIN + D + C, JOURN: JOURNAL + "- three (main)\n", LOG: "# Changelog\n\n- main's\n",
                         "notes/graph/edges/new.yaml": "- {from: wi-c, to: wi-a, type: depends_on}\n"}, msg="main")
    run_git(r, "checkout", "-q", "feat")
    return r


def _project(r):
    return projects.Project(name="demo", root=r, stores=[r / "notes" / "graph"], journals=[r / JOURN])


def _check(r, **kw):
    return mergecheck.check(r, _project(r), "main", fetch=False, **kw)


def _resolve(repo, make_repo, files, msg="resolution"):
    """A merge of main with exactly ``files`` as its result (the rest as the branch has it)."""
    run_git(repo, "merge", "-q", "--no-commit", "-s", "ours", "main")
    make_repo.commit(repo, files, msg=msg)


GOOD = {NODES: A_BOTH + C + B, JOURN: JOURNAL + "- three (main)\n- two (the branch)\n", LOG: "# Changelog\n\n- main's\n",
        "notes/graph/edges/new.yaml": "- {from: wi-c, to: wi-a, type: depends_on}\n"}


def test_watched_files_skip_the_generated_views_and_read_the_base(repo):
    files = mergecheck.watched(repo, _project(repo), revs=("main",))
    assert files == {NODES: "nodes", EDGE_F: "append", "notes/graph/edges/new.yaml": "append", JOURN: "append",
                     LOG: "append"}


def test_a_branch_without_the_base_is_behind(repo):
    r = _check(repo)
    assert r["behind"] and mergecheck.failed(r)
    assert "behind: main is not merged" in "\n".join(mergecheck.render(r))


def test_a_resolution_that_drops_main_s_work_is_caught(repo):
    run_git(repo, "merge", "-q", "-s", "ours", "-m", "bad resolution", "main")   # keeps the branch's side whole
    r = _check(repo)
    assert not r["behind"] and mergecheck.failed(r)
    assert r["lost_ids"] == [{"path": NODES, "id": "wi-c"}]          # wi-d: the branch removed it on purpose
    lost = {(x["path"], x["text"]) for x in r["lost"]}
    assert lost == {(JOURN, "- three (main)"), (LOG, ""), (LOG, "- main's"), (NODES, "wi-a props.priority: P1"),
                    ("notes/graph/edges/new.yaml", "- {from: wi-c, to: wi-a, type: depends_on}")}
    text = "\n".join(mergecheck.render(r))
    assert "lost id  notes/graph/nodes/work.yaml: wi-c" in text and "lost     CHANGELOG.md:3: - main's" in text


def test_a_good_resolution_passes_whatever_the_order(repo, make_repo):
    _resolve(repo, make_repo, {**GOOD, JOURN: JOURNAL + "- two (the branch)\n- three (main)\n",  # the driver's order
                               LOG: "# Changelog\n\n- main's\n"})
    r = _check(repo)
    assert not mergecheck.failed(r), r
    assert mergecheck.render(r)[-1] == "ok: nothing main brought since the merge base is lost"


def test_main_s_change_to_an_existing_node_dropped_is_lost(repo, make_repo):
    _resolve(repo, make_repo, {**GOOD, NODES: A_CLOSED + C + B})     # wi-a without main's priority
    assert [x["text"] for x in _check(repo)["lost"]] == ["wi-a props.priority: P1"]


def test_an_uncommitted_resolution_is_read_with_worktree(repo):
    run_git(repo, "merge", "-q", "--no-commit", "-s", "ours", "main")
    for path, text in GOOD.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text, encoding="utf-8")
    r = _check(repo, worktree=True)
    assert not r["behind"] and not mergecheck.failed(r), r            # main is in MERGE_HEAD
    (repo / JOURN).write_text(JOURNAL + "- two (the branch)\n", encoding="utf-8")
    assert [x["text"] for x in _check(repo, worktree=True)["lost"]] == ["- three (main)"]


def test_a_later_commit_after_the_merge_still_checks_that_merge(repo, make_repo):
    run_git(repo, "merge", "-q", "-s", "ours", "-m", "bad", "main")
    make_repo.commit(repo, {"notes/other.md": "x\n"}, msg="after the merge")
    assert _check(repo)["lost_ids"] == [{"path": NODES, "id": "wi-c"}]


def test_cli_exit_codes(repo, capsys, monkeypatch):
    monkeypatch.chdir(repo)
    assert cli.main(["merge-check", "--base", "main", "--no-fetch"]) == 1
    assert "behind" in capsys.readouterr().out
    run_git(repo, "merge", "-q", "-s", "ours", "-m", "bad", "main")
    assert cli.main(["merge-check", "--base", "main", "--json", "--path", LOG]) == 1   # a local base: not fetched
    assert json.loads(capsys.readouterr().out)["lost"]
    assert cli.main(["merge-check", "--base", "nope", "--no-fetch"]) == 2
