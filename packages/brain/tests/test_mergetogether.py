"""brain merge-ready PR --with PR... (wi-brain-merge-ready-together, brain.mergetogether): PRs green alone checked
merged together on the base: the repo's merge driver by git merge-tree (nothing checked out), the order said, the PR
GitHub will see conflicting once those before it merge, a head that conflicts left out, the tests impact chooses run
in a scratch worktree, a stamp per head naming the set."""

import json
import sys
from pathlib import Path

import pytest
from brain import cli, config, mergeready, mergetogether, review
from conftest import git_init, run_git

GREEN = [{"__typename": "CheckRun", "name": "tests", "status": "COMPLETED", "conclusion": "SUCCESS"}]
CFG = config.Config(None, Path("."), {})
CHANGELOG = "# Changelog\n\n## Unreleased\n\n### Added\n\n- base\n"


@pytest.fixture
def prs(make_repo, tmp_path):
    """A clone of an origin with four PR branches: 1 and 2 each add a CHANGELOG bullet (the driver unions them, text
    conflicts), 3 and 4 change one line of a.txt each way (a conflict either way)."""
    origin = git_init(tmp_path / "origin.git", bare=True)
    work = make_repo("work", {"a.txt": "a\n", "CHANGELOG.md": CHANGELOG,
                              ".gitattributes": "CHANGELOG.md merge=brain\n"})
    run_git(work, "config", "merge.brain.driver",
            f'"{Path(sys.executable).as_posix()}" -m brain merge-driver run %O %A %B %P %L')
    run_git(work, "remote", "add", "origin", str(origin))
    run_git(work, "push", "-q", "origin", "main")
    heads = {}
    changes = {1: {"CHANGELOG.md": CHANGELOG + "- one\n", "tests/test_one.py": "def test_one():\n    assert True\n"},
               2: {"CHANGELOG.md": CHANGELOG + "- two\n"}, 3: {"a.txt": "a, three\n"}, 4: {"a.txt": "a, four\n"}}
    for n, files in changes.items():
        run_git(work, "switch", "-q", "-c", f"pr{n}", "main")
        heads[n] = make_repo.commit(work, files, msg=f"PR {n}")
        run_git(work, "push", "-q", "origin", f"pr{n}")
    run_git(work, "switch", "-q", "main")
    run_git(work, "fetch", "-q", "origin")

    def view(number, slug, cwd=None):
        n = int(number)
        return {"number": n, "state": "OPEN", "isDraft": False, "mergeable": "MERGEABLE", "headRefName": f"pr{n}",
                "headRefOid": heads[n], "baseRefName": "main", "title": f"PR {n}", "body": "A change.",
                "statusCheckRollup": GREEN}

    for h in heads.values():
        review.stamp(h, 0, 0)

    class P:
        pass
    P.repo, P.heads, P.view = work, heads, staticmethod(view)
    return P


def _check(p, numbers, **kw):
    return mergetogether.check(p.repo, [str(n) for n in numbers], "owner/lab", view=p.view, cfg=CFG, fetch=False,
                               **kw)


def test_two_prs_the_driver_merges_are_ready_together_and_the_second_must_merge_the_base(prs):
    t = _check(prs, [1, 2])
    assert t.ready, mergetogether.lines(t)
    assert t.order == [1, 2] and [s.merged for s in t.steps] == [True, True]
    assert t.steps[0].as_text == [] and t.steps[1].as_text == ["CHANGELOG.md"]   # GitHub merges as text
    text = "\n".join(mergetogether.lines(t))
    assert "then  #2: once #1 merged, GitHub sees a conflict on CHANGELOG.md" in text
    merged = run_git(prs.repo, "show", f"{t.result}:CHANGELOG.md")
    assert "- one" in merged and "- two" in merged and "<<<<<<<" not in merged
    assert run_git(prs.repo, "rev-parse", "HEAD").strip() == run_git(prs.repo, "rev-parse", "main").strip()
    assert not (prs.repo / ".git" / "brain-refresh").exists()   # a check marks no view
    files = mergetogether.stamps(t)
    rec = json.loads(files[1].read_text(encoding="utf-8"))
    assert rec["head"] == prs.heads[2] and rec["together"]["with"] == [1] and rec["together"]["order"] == [1, 2]


def test_a_head_that_conflicts_with_one_before_it_is_left_out(prs):
    t = _check(prs, [3, 4, 1])
    assert not t.ready and t.order == [3, 1]
    assert [(s.pr, s.conflicts) for s in t.left] == [(4, ["a.txt"])]
    assert "BLOCK #4 conflicts after #3: a.txt" in "\n".join(mergetogether.lines(t))
    assert t.tests == [] and t.tests_rc is None   # no test chosen for a set that does not merge


def test_a_pr_not_ready_alone_is_not_ready_together(prs):
    review.stamp(prs.heads[2], 1, 0)   # a finding left open on the second head
    t = _check(prs, [1, 2])
    assert not t.ready and t.order == [1, 2]
    assert {c["check"] for g in t.gates for c in g.blocks} == {"review"}


def test_the_chosen_tests_run_in_a_scratch_worktree_of_the_integrated_commit(prs, monkeypatch):
    monkeypatch.setattr(mergetogether, "chosen_tests", lambda *a: (["tests/test_one.py"], "chosen here"))
    before = run_git(prs.repo, "worktree", "list")
    t = _check(prs, [1, 2], test=True)
    assert t.tests_rc == 0 and t.ready, t.tests_note
    assert "pytest exit 0" in t.tests_note
    assert run_git(prs.repo, "worktree", "list") == before   # the scratch worktree is removed
    rc, tail = mergetogether.run_tests(prs.repo, prs.heads[2], ["tests/test_one.py"])   # not in PR 2 alone
    assert rc != 0


def test_prs_onto_different_bases_are_refused(prs):
    run_git(prs.repo, "push", "-q", "origin", "main:release")
    run_git(prs.repo, "fetch", "-q", "origin")
    other = prs.view

    def view(number, slug, cwd=None):
        d = other(number, slug, cwd)
        return {**d, "baseRefName": "release"} if int(number) == 2 else d
    prs.view = staticmethod(view)
    t = _check(prs, [1, 2])
    assert not t.ready and "different bases: main, release" in t.error


def test_brain_merge_ready_with_exits_0_when_ready_and_1_when_not(prs, monkeypatch, capsys):
    monkeypatch.setattr(mergeready, "gh_view", prs.view)
    monkeypatch.setattr(mergetogether, "chosen_tests", lambda *a: ([], "none here"))
    base = ["merge-ready", "1", "--repo-dir", str(prs.repo), "--slug", "owner/lab", "--no-fetch"]
    assert cli.main([*base, "--with", "2", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ready"] and out["order"] == [1, 2] and len(out["stamps"]) == 2
    assert cli.main([*base, "--with", "3,4"]) == 1
    text = capsys.readouterr().out
    assert "not ready; merge order: #1, #3" in text and "BLOCK #4" in text
