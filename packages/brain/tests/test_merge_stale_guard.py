"""wi-brain-merge-stale-main-2: brain merge-check shipped, then the lesson les-brain-merge-stale-main regressed because
nothing ran it. The push guard merges:stale runs it on each branch a git push sends that carries a merge of the base,
against the base as merged and against a fresh one (fetched again), and refuses a resolution made against a main that
has moved since on a watched file the branch changes too. Real repos: a bare origin and two clones."""

from __future__ import annotations

import pytest
from conftest import run_git

from brain import guards, mergecheck
from test_guards import bash

LOG = "CHANGELOG.md"


@pytest.fixture
def two(tmp_path, make_repo):
    """origin (bare), ours (a clone on branch feat) and theirs (another clone that lands PRs on main)."""
    seed = make_repo("seed", {LOG: "# Changes\n\n- one\n", "src/a.py": "x = 1\n"})
    origin = tmp_path / "origin.git"
    run_git(tmp_path, "clone", "-q", "--bare", str(seed), str(origin))
    ours, theirs = tmp_path / "ours", tmp_path / "theirs"
    for c in (ours, theirs):
        run_git(tmp_path, "clone", "-q", str(origin), str(c))
    run_git(ours, "checkout", "-q", "-b", "feat")
    return origin, ours, theirs, make_repo


def _land(theirs, make_repo, files):
    """A PR merged on origin's main from the other clone."""
    run_git(theirs, "pull", "-q", "--ff-only")
    make_repo.commit(theirs, files)
    run_git(theirs, "push", "-q", "origin", "HEAD:main")


def _push(repo):
    return guards.check_merge_stale(guards.calls("git push origin feat", str(repo), False))


def test_a_branch_with_no_merge_of_main_passes(two):
    _, ours, theirs, make_repo = two
    make_repo.commit(ours, {LOG: "# Changes\n\n- one\n- ours\n"})
    _land(theirs, make_repo, {LOG: "# Changes\n\n- one\n- theirs\n"})
    assert _push(ours) is None


def test_a_merge_of_a_fresh_main_that_keeps_everything_passes(two):
    _, ours, theirs, make_repo = two
    make_repo.commit(ours, {LOG: "# Changes\n\n- one\n- ours\n"})
    _land(theirs, make_repo, {LOG: "# Changes\n\n- one\n- theirs\n"})
    run_git(ours, "fetch", "-q")
    run_git(ours, "merge", "-q", "origin/main", "-X", "ours", "-m", "merge")   # conflict resolved: drops theirs
    assert "lost 1 line(s) or node(s) of the origin/main it merged" in _push(ours)
    make_repo.commit(ours, {LOG: "# Changes\n\n- one\n- ours\n- theirs\n"})   # put back
    assert _push(ours) is None


def test_a_resolution_against_a_main_that_moved_since_is_refused(two):
    """The regression: ours merged main, then a PR landed on main in the same file; the fresh fetch sees it."""
    _, ours, theirs, make_repo = two
    make_repo.commit(ours, {LOG: "# Changes\n\n- one\n- ours\n"})
    _land(theirs, make_repo, {LOG: "# Changes\n\n- one\n- theirs\n"})
    run_git(ours, "fetch", "-q")
    run_git(ours, "merge", "-q", "origin/main", "-X", "ours", "-m", "merge")
    make_repo.commit(ours, {LOG: "# Changes\n\n- one\n- ours\n- theirs\n"})
    _land(theirs, make_repo, {LOG: "# Changes\n\n- one\n- theirs\n- later\n"})   # ours has not fetched it
    reason = _push(ours)
    assert "has moved since on CHANGELOG.md, which the branch changes too" in reason
    assert reason.startswith("git push refused: feat (")
    run_git(ours, "merge", "-q", "origin/main", "-X", "ours", "-m", "merge again")   # the guard fetched it
    make_repo.commit(ours, {LOG: "# Changes\n\n- one\n- ours\n- theirs\n- later\n"})
    assert _push(ours) is None


def test_main_moving_on_a_file_the_branch_leaves_alone_passes(two):
    _, ours, theirs, make_repo = two
    make_repo.commit(ours, {"src/a.py": "x = 2\n"})
    _land(theirs, make_repo, {LOG: "# Changes\n\n- one\n- theirs\n"})
    run_git(ours, "fetch", "-q")
    run_git(ours, "merge", "-q", "origin/main", "-m", "merge")
    _land(theirs, make_repo, {LOG: "# Changes\n\n- one\n- theirs\n- later\n"})
    assert _push(ours) is None


def test_a_tag_and_a_deletion_pass_and_the_hook_names_the_guard(two):
    _, ours, theirs, make_repo = two
    make_repo.commit(ours, {LOG: "# Changes\n\n- one\n- ours\n"})
    _land(theirs, make_repo, {LOG: "# Changes\n\n- one\n- theirs\n"})
    run_git(ours, "fetch", "-q")
    run_git(ours, "merge", "-q", "origin/main", "-X", "ours", "-m", "merge")
    run_git(ours, "tag", "v1")
    assert guards.check_merge_stale(guards.calls("git push origin refs/tags/v1", str(ours), False)) is None
    assert guards.check_merge_stale(guards.calls("git push origin --delete feat", str(ours), False)) is None
    assert "lost 1 line(s)" in bash(ours, "git push origin feat")


def test_a_failed_fetch_reads_the_base_as_last_fetched(two, monkeypatch):
    _, ours, theirs, make_repo = two
    make_repo.commit(ours, {LOG: "# Changes\n\n- one\n- ours\n"})
    _land(theirs, make_repo, {LOG: "# Changes\n\n- one\n- theirs\n"})
    run_git(ours, "fetch", "-q")
    run_git(ours, "merge", "-q", "origin/main", "-X", "ours", "-m", "merge")
    monkeypatch.setattr(mergecheck, "_fetch", lambda repo, base: "timed out")
    assert "(git fetch failed: timed out; origin/main as last fetched)" in _push(ours)
