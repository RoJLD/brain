"""brain merge-ready <pr> (wi-brain-merge-gate): exit 0 or the list of what blocks: open, fresh against the base on
the files the PR touches, merge-check, CI green on the head, the review's stamp, the public check's stamp, nothing
private in the body."""

import json
from pathlib import Path

import pytest
from brain import cli, config, mergeready, review
from conftest import git_init, run_git

GREEN = [{"__typename": "CheckRun", "name": "tests", "status": "COMPLETED", "conclusion": "SUCCESS"},
         {"__typename": "CheckRun", "name": "release-tag", "status": "COMPLETED", "conclusion": "SKIPPED"}]
CFG = config.Config(None, Path("."), {"public": {"deny": {"people": ["Zebulon"]}}})


@pytest.fixture
def pr(make_repo, tmp_path):
    """A clone of an origin whose PR branch feat changes a.txt; ``pr.view`` is gh pr view's answer for it."""
    origin = git_init(tmp_path / "origin.git", bare=True)
    work = make_repo("work", {"a.txt": "a\n", "b.txt": "b\n"})
    run_git(work, "remote", "add", "origin", str(origin))
    run_git(work, "push", "-q", "origin", "main")
    run_git(work, "switch", "-q", "-c", "feat")
    head = make_repo.commit(work, {"a.txt": "a, changed\n"})
    run_git(work, "push", "-q", "origin", "feat")
    run_git(work, "fetch", "-q", "origin")

    class P:
        repo = work
        data = {"number": 7, "state": "OPEN", "isDraft": False, "mergeable": "MERGEABLE", "headRefName": "feat",
                "headRefOid": head, "baseRefName": "main", "body": "Adds a line.", "statusCheckRollup": GREEN}

        @staticmethod
        def view(number, slug, cwd=None):
            return dict(P.data)

        @staticmethod
        def on_main(files):
            """A commit pushed to origin's main from another clone."""
            other = make_repo("other-" + "-".join(sorted(files)).replace(".", "_"), {})
            run_git(other, "fetch", "-q", str(origin), "main")
            run_git(other, "reset", "-q", "--hard", "FETCH_HEAD")
            make_repo.commit(other, files)
            run_git(other, "push", "-q", str(origin), "HEAD:main")

    return P


def _gate(p, **kw):
    return mergeready.gate(p.repo, "7", "owner/lab", view=p.view, cfg=CFG, **kw)


def _blocks(g):
    return {c["check"] for c in g.blocks}


def test_a_reviewed_green_fresh_pr_is_ready_and_stamped(pr):
    review.stamp(pr.data["headRefOid"], 2, 2)
    g = _gate(pr)
    assert g.ready, g.checks
    assert [c["check"] for c in g.checks] == ["open", "fresh", "merge-check", "ci", "review", "public", "body", "pins"]
    f = mergeready.stamp(g)
    assert json.loads(f.read_text(encoding="utf-8"))["head"] == pr.data["headRefOid"]


def test_main_moved_under_a_file_the_pr_touches_blocks_and_elsewhere_does_not(pr):
    review.stamp(pr.data["headRefOid"], 0, 0)
    pr.on_main({"b.txt": "b, on main\n"})
    g = _gate(pr)
    assert g.ready, g.checks
    assert "other files only" in g.checks[1]["detail"]
    pr.on_main({"a.txt": "a, on main\n"})
    g = _gate(pr)
    assert _blocks(g) == {"fresh"} and "a.txt" in g.checks[1]["detail"]


def test_ci_running_or_failed_blocks(pr):
    review.stamp(pr.data["headRefOid"], 0, 0)
    pr.data["statusCheckRollup"] = [*GREEN, {"__typename": "CheckRun", "name": "brain (3.12)", "status": "IN_PROGRESS",
                                             "conclusion": ""}]
    g = _gate(pr)
    assert _blocks(g) == {"ci"} and "running: brain (3.12)" in g.checks[3]["detail"]
    pr.data["statusCheckRollup"] = [*GREEN, {"__typename": "StatusContext", "context": "lint", "state": "FAILURE"}]
    assert _blocks(_gate(pr)) == {"ci"}
    pr.data["statusCheckRollup"] = []
    assert _blocks(_gate(pr)) == {"ci"}


def test_no_review_stamp_or_findings_left_open_block(pr):
    assert _blocks(_gate(pr)) == {"review"}
    review.stamp(pr.data["headRefOid"], 3, 1, 1)
    g = _gate(pr)
    assert _blocks(g) == {"review"} and "1 finding(s) left open" in g.checks[4]["detail"]


def test_a_draft_a_conflict_or_a_private_name_blocks(pr):
    review.stamp(pr.data["headRefOid"], 0, 0)
    pr.data.update(isDraft=True)
    g = _gate(pr)
    assert _blocks(g) == {"open"} and "a draft" in g.checks[0]["detail"]
    pr.data.update(isDraft=False, mergeable="CONFLICTING")
    g = _gate(pr)
    assert _blocks(g) == {"open"} and "a conflict" in g.checks[0]["detail"]
    pr.data.update(mergeable="MERGEABLE", body="Asked by Zebulon on his laptop.")
    g = _gate(pr)
    assert _blocks(g) == {"body"} and "body line 1: people term" in g.checks[6]["detail"]
    pr.data.update(body="Fine.", title="For Zebulon")
    assert "title: people term" in _gate(pr).checks[6]["detail"]


def test_a_public_repo_needs_the_public_checks_stamp(pr, monkeypatch):
    review.stamp(pr.data["headRefOid"], 0, 0)
    cfg = config.Config(None, Path("."), {"public": {"repos": ["owner/lab"]}})
    g = mergeready.gate(pr.repo, "7", "owner/lab", view=pr.view, cfg=cfg)
    assert _blocks(g) == {"public"} and "brain check --public --history" in g.checks[5]["detail"]
    monkeypatch.setattr(mergeready.public, "stamp_refusal", lambda slug, sha, c: "")   # a valid stamp
    assert mergeready.gate(pr.repo, "7", "owner/lab", view=pr.view, cfg=cfg).ready


def test_merge_check_runs_on_the_prs_head_once_it_merged_the_base(pr, make_repo):
    pr.on_main({"CHANGELOG.md": "# Changes\n\n- main's line\n"})
    run_git(pr.repo, "fetch", "-q", "origin")
    run_git(pr.repo, "merge", "-q", "--no-edit", "origin/main")
    make_repo.commit(pr.repo, {"CHANGELOG.md": "# Changes\n"}, msg="drop main's line")   # a bad resolution
    run_git(pr.repo, "push", "-q", "origin", "feat")
    pr.data["headRefOid"] = run_git(pr.repo, "rev-parse", "HEAD").strip()
    review.stamp(pr.data["headRefOid"], 0, 0)
    run_git(pr.repo, "switch", "-q", "main")   # the gate reads the PR's head, not this checkout's HEAD
    g = _gate(pr)
    assert _blocks(g) == {"merge-check"}, g.checks
    # main moves on another file: the head merged an older main, and what it lost of it still blocks
    pr.on_main({"b.txt": "b, on main\n"})
    g = _gate(pr)
    assert _blocks(g) == {"merge-check"} and "other files only" in g.checks[1]["detail"]


def test_a_rename_by_the_pr_of_a_file_main_changed_is_not_fresh(pr, make_repo):
    run_git(pr.repo, "mv", "b.txt", "c.txt")
    make_repo.commit(pr.repo, {}, msg="rename b")
    run_git(pr.repo, "push", "-q", "origin", "feat")
    pr.data["headRefOid"] = run_git(pr.repo, "rev-parse", "HEAD").strip()
    review.stamp(pr.data["headRefOid"], 0, 0)
    pr.on_main({"b.txt": "b, on main\n"})
    g = _gate(pr)
    assert _blocks(g) == {"fresh"} and "b.txt" in g.checks[1]["detail"]


def test_a_pending_status_blocks_as_running():
    ok, why = mergeready.ci([*GREEN, {"__typename": "StatusContext", "context": "deploy", "state": "PENDING"}])
    assert not ok and why == "running: deploy"


def test_gh_or_a_missing_head_exits_2_and_the_slug_comes_from_the_url(pr, monkeypatch, capsys):
    def broken(*a):
        raise mergeready.GateError("gh pr view 7: no such PR")
    monkeypatch.setattr(mergeready, "gh_view", broken)
    assert cli.main(["merge-ready", "7", "--repo-dir", str(pr.repo), "--slug", "owner/lab"]) == 2
    assert "no such PR" in capsys.readouterr().err
    gone = {**pr.data, "headRefOid": "0" * 40, "url": "https://github.com/owner/lab/pull/7"}
    monkeypatch.setattr(mergeready, "gh_view", lambda *a: dict(gone))
    run_git(pr.repo, "remote", "set-url", "origin", str(pr.repo.parent / "origin.git"))   # no GitHub URL: the PR's
    assert cli.main(["merge-ready", "7", "--repo-dir", str(pr.repo), "--no-fetch"]) == 2
    assert "is not in" in capsys.readouterr().err
    assert mergeready.slug_of_url(gone["url"]) == "owner/lab"


def test_brain_merge_ready_exits_1_with_the_blocks_and_0_when_ready(pr, monkeypatch, capsys):
    monkeypatch.setattr(mergeready, "gh_view", pr.view)
    args = ["merge-ready", "7", "--repo-dir", str(pr.repo), "--slug", "owner/lab"]
    assert cli.main(args) == 1
    assert "BLOCK review" in capsys.readouterr().out
    review.stamp(pr.data["headRefOid"], 0, 0)
    assert cli.main(args) == 0
    assert f"READY: gh pr merge 7 --match-head-commit {pr.data['headRefOid']}" in capsys.readouterr().out
    assert cli.main([*args, "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ready"] and out["stamp"].endswith(f"{pr.data['headRefOid']}.json")
