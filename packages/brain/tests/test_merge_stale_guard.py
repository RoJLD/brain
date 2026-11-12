"""wi-brain-merge-stale-main-2: brain merge-check shipped, then the lesson les-brain-merge-stale-main regressed because
nothing ran it. The push guard merges:stale checks each pushed branch whose merge of the base is not on the remote
branch yet: against the commit of the base it merged and against a fresh one (fetched again), and it refuses a watched
file the merge itself resolved when the base has moved on it since. Real repos: a bare origin and two clones."""

from __future__ import annotations

import subprocess

import pytest
from conftest import run_git

from brain import guards, mergecheck
from test_guards import bash

LOG = "CHANGELOG.md"


def _log(*lines):
    return "# Changes\n\n- one\n" + "".join(f"- {x}\n" for x in lines)


@pytest.fixture
def two(tmp_path, make_repo):
    """origin (bare), ours (a clone on branch feat) and theirs (another clone that lands PRs on main)."""
    seed = make_repo("seed", {LOG: _log(), "src/a.py": "x = 1\n"})
    origin = tmp_path / "origin.git"
    run_git(tmp_path, "clone", "-q", "--bare", str(seed), str(origin))
    ours, theirs = tmp_path / "ours", tmp_path / "theirs"
    for c in (ours, theirs):
        run_git(tmp_path, "clone", "-q", str(origin), str(c))
    run_git(ours, "checkout", "-q", "-b", "feat")
    return ours, theirs, make_repo


def _land(theirs, make_repo, files):
    """A PR merged on origin's main from the other clone."""
    run_git(theirs, "pull", "-q", "--ff-only")
    make_repo.commit(theirs, files)
    run_git(theirs, "push", "-q", "origin", "HEAD:main")


def _merge(repo, make_repo, ref, resolved=None):
    """git merge ``ref``; the changelog resolved by hand to ``resolved`` (a union: the file then differs from both
    parents) and the merge committed, unless git merged it clean."""
    subprocess.run(["git", "-C", str(repo), "merge", "-q", "--no-edit", ref], capture_output=True)
    if resolved is not None:
        make_repo.write(repo, {LOG: resolved})
        subprocess.run(["git", "-C", str(repo), "commit", "-qam", f"merge {ref}"], capture_output=True)   # clean: none


def _push(repo, command="git push origin feat"):
    return guards.check_merge_stale(guards.calls(command, str(repo), False))


def test_a_branch_with_no_merge_of_main_passes(two):
    ours, theirs, make_repo = two
    make_repo.commit(ours, {LOG: _log("ours")})
    _land(theirs, make_repo, {LOG: _log("theirs")})
    assert _push(ours) is None


def test_a_resolution_that_loses_a_line_of_what_it_merged_is_refused(two):
    ours, theirs, make_repo = two
    make_repo.commit(ours, {LOG: _log("ours")})
    _land(theirs, make_repo, {LOG: _log("theirs")})
    run_git(ours, "fetch", "-q")
    run_git(ours, "merge", "-q", "origin/main", "-X", "ours", "-m", "merge")   # the conflict resolved: theirs gone
    reason = _push(ours)
    assert "lost 1 line(s) or node(s) of the commit of origin/main it merged" in reason and "- theirs" in reason
    assert "lost 1 line(s)" in _push(ours, "git push origin HEAD:feat")   # an explicit refspec
    make_repo.commit(ours, {LOG: _log("ours", "theirs")})   # put back
    assert _push(ours) is None


def test_a_resolution_against_a_stale_local_main_is_refused(two):
    """The lesson: the branch merged the local main ref; a PR had landed since on the file the merge resolved."""
    ours, theirs, make_repo = two
    make_repo.commit(ours, {LOG: _log("ours")})
    _land(theirs, make_repo, {LOG: _log("theirs")})
    run_git(ours, "fetch", "-q")
    run_git(ours, "branch", "-q", "-f", "main", "origin/main")   # the local main, as last fetched
    _land(theirs, make_repo, {LOG: _log("theirs", "later")})   # ours has not fetched it
    _merge(ours, make_repo, "main", _log("ours", "theirs"))
    first = _push(ours, "git push origin main feat")   # main has no merge: feat still gets the fetch (review, A)
    assert first and "has moved since" in first
    reason = _push(ours)
    assert "resolved CHANGELOG.md against a commit of origin/main" in reason and "has moved since" in reason
    _merge(ours, make_repo, "origin/main", _log("ours", "theirs", "later"))   # the guard fetched it
    assert _push(ours) is None


def test_a_clean_merge_then_the_branchs_own_work_passes_when_main_moves(two):
    """Review of the guard, finding 1: the merge resolved nothing; the branch's later change to the changelog is its
    own, and GitHub's merge keeps both sides."""
    ours, theirs, make_repo = two
    make_repo.commit(ours, {"src/a.py": "x = 2\n"})
    _land(theirs, make_repo, {LOG: _log("theirs")})
    run_git(ours, "fetch", "-q")
    _merge(ours, make_repo, "origin/main")
    make_repo.commit(ours, {LOG: _log("theirs", "ours")})
    _land(theirs, make_repo, {LOG: _log("theirs", "later")})
    assert _push(ours) is None


def test_a_merge_already_on_the_remote_branch_is_not_checked_again(two):
    ours, theirs, make_repo = two
    make_repo.commit(ours, {LOG: _log("ours")})
    _land(theirs, make_repo, {LOG: _log("theirs")})
    run_git(ours, "fetch", "-q")
    _merge(ours, make_repo, "origin/main", _log("ours", "theirs"))
    run_git(ours, "push", "-q", "-u", "origin", "feat:feat-remote")   # checked when it went, under another name
    run_git(ours, "config", "push.default", "upstream")
    _land(theirs, make_repo, {LOG: _log("theirs", "later")})
    make_repo.commit(ours, {"src/a.py": "x = 3\n"})
    assert _push(ours, "git push") is None   # its upstream, read by git (review, B)
    assert _push(ours, "git push origin feat:feat-remote") is None   # merge-ready reads main moving under the PR


def test_tags_and_a_deletion_pass_and_the_hook_names_the_guard(two):
    ours, theirs, make_repo = two
    make_repo.commit(ours, {LOG: _log("ours")})
    _land(theirs, make_repo, {LOG: _log("theirs")})
    run_git(ours, "fetch", "-q")
    run_git(ours, "merge", "-q", "origin/main", "-X", "ours", "-m", "merge")
    run_git(ours, "tag", "v1")
    for command in ("git push origin refs/tags/v1", "git push origin v1", "git push origin --delete feat"):
        assert _push(ours, command) is None, command
    assert "lost 1 line(s)" in bash(ours, "git push origin feat")


def test_a_failed_fetch_reads_the_base_as_last_fetched(two, monkeypatch):
    ours, theirs, make_repo = two
    make_repo.commit(ours, {LOG: _log("ours")})
    _land(theirs, make_repo, {LOG: _log("theirs")})
    run_git(ours, "fetch", "-q")
    run_git(ours, "merge", "-q", "origin/main", "-X", "ours", "-m", "merge")
    monkeypatch.setattr(mergecheck, "_fetch", lambda repo, base: "timed out")
    assert "(git fetch failed: timed out; origin/main as last fetched)" in _push(ours)


def test_a_field_only_main_changed_is_refused_one_both_changed_is_not():
    """Review, C: a node field main changed that the resolution reverts is lost; one the branch changed too stays
    brain merge-check's « check it by eye »."""
    lost = {"path": "graph/nodes/work.yaml", "line": 0, "text": "wi-a status: done"}
    assert mergecheck._lost({"lost_ids": [], "lost": [{**lost, "both": False}]}) == [
        "graph/nodes/work.yaml: wi-a status: done"]
    assert mergecheck._lost({"lost_ids": [], "lost": [{**lost, "both": True}]}) == []
