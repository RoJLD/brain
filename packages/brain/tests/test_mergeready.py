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
PUBLIC = config.Config(None, Path("."), {"public": {"repos": ["owner/lab"], "deny": {"people": ["Zebulon"]}}})


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


def test_a_draft_a_conflict_or_a_private_name_in_a_public_repos_pr_blocks(pr, monkeypatch):
    review.stamp(pr.data["headRefOid"], 0, 0)
    pr.data.update(isDraft=True)
    g = _gate(pr)
    assert _blocks(g) == {"open"} and "a draft" in g.checks[0]["detail"]
    pr.data.update(isDraft=False, mergeable="CONFLICTING")
    g = _gate(pr)
    assert _blocks(g) == {"open"} and "a conflict" in g.checks[0]["detail"]
    pr.data.update(mergeable="MERGEABLE", body="Asked by Zebulon on his laptop.")
    monkeypatch.setattr(mergeready.public, "stamp_refusal", lambda slug, sha, c: "")   # the head stamped
    g = mergeready.gate(pr.repo, "7", "owner/lab", view=pr.view, cfg=PUBLIC)
    assert _blocks(g) == {"body"} and "body line 1: people term" in g.checks[6]["detail"]
    pr.data.update(body="Fine.", title="For Zebulon")
    assert "title: people term" in mergeready.gate(pr.repo, "7", "owner/lab", view=pr.view, cfg=PUBLIC).checks[6][
        "detail"]


def test_a_private_repos_pr_body_may_name_its_owner_but_never_holds_a_secret(pr):
    """wi-brain-gate-body-terms-public-only: the public terms are checked in a public repo's PR body only; a secret
    blocks in any repo's."""
    review.stamp(pr.data["headRefOid"], 0, 0)
    pr.data.update(title="For Zebulon", body="Asked by Zebulon on his laptop.")
    g = _gate(pr)   # owner/lab is not in public.repos
    assert g.ready, g.checks
    assert g.checks[6]["detail"] == "no secret (a private repo: names allowed)"
    pr.data.update(body="token ghp_" + "a1B2c3D4e5" * 4)
    g = _gate(pr)
    assert _blocks(g) == {"body"} and "looks like a secret" in g.checks[6]["detail"]


def test_a_repo_that_declares_no_ci_blocks_as_local_and_one_that_does_not_stays_blocked(pr):
    """wi-brain-gate-local-checks-no-ci: no check on the head of a repo whose config says it has no CI is a block the
    merger's local checks answer (marked local); a repo that has a CI, or says nothing, still needs a reported check,
    and a no-CI repo's head that reports checks is judged by them."""
    review.stamp(pr.data["headRefOid"], 0, 0)
    pr.data["statusCheckRollup"] = []
    g = _gate(pr)
    assert _blocks(g) == {"ci"} and g.checks[3]["detail"] == "no check reported on the head"
    assert not g.checks[3].get(mergeready.LOCAL)
    cfg = config.Config(None, Path("."), {"merge": {"repos": {"Owner/Lab": {"ci": False}}}})
    g = mergeready.gate(pr.repo, "7", "owner/lab", view=pr.view, cfg=cfg)
    assert _blocks(g) == {"ci"} and g.checks[3][mergeready.LOCAL] is True
    assert "merge.repos.owner/lab.ci is false" in g.checks[3]["detail"] and not g.ready   # merge-ready alone: blocked
    pr.data["statusCheckRollup"] = [{"__typename": "CheckRun", "name": "lint", "status": "COMPLETED",
                                     "conclusion": "FAILURE"}]
    g = mergeready.gate(pr.repo, "7", "owner/lab", view=pr.view, cfg=cfg)
    assert _blocks(g) == {"ci"} and "lint (failure)" in g.checks[3]["detail"] and not g.checks[3].get("local")
    cfg = config.Config(None, Path("."), {"merge": {"repos": {"owner/lab": {"ci": True}}}})
    pr.data["statusCheckRollup"] = []
    assert not mergeready.gate(pr.repo, "7", "owner/lab", view=pr.view, cfg=cfg).checks[3].get("local")


def test_a_records_or_docs_pr_needs_no_review_stamp_and_a_code_pr_still_does(pr, make_repo):
    """wi-brain-gate-review-scope: every file under merge.repos.<repo>.review_exempt: no stamp asked; one file
    outside: a code PR, the stamp asked (fail closed); no glob: every PR."""
    cfg = config.Config(None, Path("."), {"merge": {"repos": {"owner/lab": {"review_exempt": ["*.txt", "notes/**"]}}}})
    g = mergeready.gate(pr.repo, "7", "owner/lab", view=pr.view, cfg=cfg)   # the PR changes a.txt alone
    assert g.ready, g.checks
    assert g.checks[4]["detail"].startswith("n/a: 1 file(s), each under merge.repos.owner/lab.review_exempt")
    assert _blocks(_gate(pr)) == {"review"}   # the same PR, no exemption configured
    head = make_repo.commit(pr.repo, {"notes/graph/nodes/work.yaml": "x: 1\n", "src/tool.py": "x = 1\n"})
    run_git(pr.repo, "push", "-q", "origin", "feat")
    pr.data["headRefOid"] = head
    g = mergeready.gate(pr.repo, "7", "owner/lab", view=pr.view, cfg=cfg)
    assert _blocks(g) == {"review"} and "no review stamp" in g.checks[4]["detail"]


def test_review_exempt_and_has_ci_read_the_config_fail_closed():
    cfg = config.Config(None, Path("."), {"merge": {"repos": {"a/b": {"review_exempt": ["docs/**", "", 3],
                                                                       "ci": "no"}}}})
    assert mergeready.review_exempt("A/B", cfg, {"docs/x.md", "docs/y/z.md"}).startswith("n/a: 2 file(s)")
    assert mergeready.review_exempt("a/b", cfg, ["docs/x.md", "README.md"]) == ""
    assert mergeready.review_exempt("a/b", cfg, []) == ""   # no file: nothing proves it is no code
    assert mergeready.review_exempt("c/d", cfg, ["docs/x.md"]) == ""
    assert mergeready.has_ci("a/b", cfg) and mergeready.has_ci("c/d", CFG)   # only false says no CI
    bad = config.Config(None, Path("."), {"merge": {"repos": ["a/b"]}})
    assert mergeready.repo_settings("a/b", bad) == {} and mergeready.has_ci("a/b", bad)


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


def _merge_main(pr, hand: dict | None = None) -> str:
    """origin/main merged into feat in the work clone (``hand``: files changed before the merge is committed),
    pushed; the PR's head is the merge."""
    run_git(pr.repo, "fetch", "-q", "origin")
    run_git(pr.repo, "merge", "-q", "--no-ff", "--no-commit", "origin/main")
    for rel, text in (hand or {}).items():
        (pr.repo / rel).write_text(text, encoding="utf-8")
    run_git(pr.repo, "add", "-A")
    run_git(pr.repo, "commit", "-q", "--no-edit", "-m", "Merge origin/main into feat")
    pr.data["headRefOid"] = run_git(pr.repo, "rev-parse", "HEAD").strip()   # the gate reads it in this clone
    return pr.data["headRefOid"]


def test_a_head_that_only_merges_main_into_the_reviewed_head_carries_its_review(pr):
    stamped = pr.data["headRefOid"]
    review.stamp(stamped, 2, 2)
    pr.on_main({"b.txt": "b, on main\n"})
    head = _merge_main(pr)
    g = _gate(pr)
    assert g.ready, g.checks
    assert f"carried from {stamped[:8]}" in g.checks[4]["detail"] and review.check(head) is None


def test_a_merge_with_a_change_by_hand_or_a_commit_after_it_needs_its_own_review(pr, make_repo):
    review.stamp(pr.data["headRefOid"], 0, 0)
    pr.on_main({"b.txt": "b, on main\n"})
    _merge_main(pr, hand={"a.txt": "a, changed by hand in the merge\n"})
    assert _blocks(_gate(pr)) == {"review"}
    run_git(pr.repo, "reset", "-q", "--hard", "HEAD^1")
    head = _merge_main(pr)
    assert "review" not in _blocks(_gate(pr))
    after = make_repo.commit(pr.repo, {"a.txt": "a, after the merge\n"})
    pr.data["headRefOid"] = after
    assert "review" in _blocks(_gate(pr)) and after != head


def test_a_merge_of_a_branch_that_is_not_the_base_carries_nothing(pr, make_repo):
    stamped = pr.data["headRefOid"]
    review.stamp(stamped, 0, 0)
    run_git(pr.repo, "switch", "-q", "-c", "side", "main")
    make_repo.commit(pr.repo, {"c.txt": "c\n"})
    run_git(pr.repo, "switch", "-q", "feat")
    run_git(pr.repo, "merge", "-q", "--no-ff", "--no-edit", "side")
    head = run_git(pr.repo, "rev-parse", "HEAD").strip()
    pr.data["headRefOid"] = head
    assert mergeready.carried_review(pr.repo, head, run_git(pr.repo, "rev-parse", "origin/main").strip()) == (None, "")
    assert "review" in _blocks(_gate(pr))
