"""brain lot check SESSION (wi-brain-lot-close-check, brain.lotcheck): a finished lot read from the desktop app's file
of its session: its worktrees clean, its branches merged (by PR or by the default branch) or kept, and pushed;
« ready to archive » and what to remove, else what is left. Read only. Fixtures only: a repo and an app folder here."""

import json
import os
import shutil

import pytest
from brain import cli, lotcheck
from conftest import git_init, run_git

SID = "local_0000aaaa-1111-2222-3333-444455556666"
URL = "https://github.com/owner/demo.git"


@pytest.fixture
def lot(make_repo, tmp_path, monkeypatch):
    """A repo whose origin is owner/demo (a bare repo here, by insteadOf); branches: done (merged into main), open
    (pushed, its PR open), kept (pushed, unmerged), local (never pushed); a worktree on each but done's; the app's file
    of the session."""
    origin = git_init(tmp_path / "origin.git", bare=True)
    repo = make_repo("repo", {"a.txt": "a\n"})
    run_git(repo, "config", f"url.{origin.as_posix()}.insteadOf", URL)
    run_git(repo, "remote", "add", "origin", URL)
    run_git(repo, "push", "-q", "-u", "origin", "main")
    for b in ("done", "open", "kept", "local"):
        run_git(repo, "switch", "-q", "-c", b, "main")
        make_repo.commit(repo, {f"{b}.txt": b + "\n"}, msg=b)
        if b != "local":
            run_git(repo, "push", "-q", "-u", "origin", b)
    run_git(repo, "switch", "-q", "main")
    run_git(repo, "merge", "-q", "--no-ff", "-m", "merge done", "done")
    run_git(repo, "push", "-q", "origin", "main")
    run_git(repo, "fetch", "-q", "origin")
    trees = {}
    for b in ("open", "kept", "local"):
        trees[b] = tmp_path / f"wt-{b}"
        run_git(repo, "worktree", "add", "-q", str(trees[b]), b)
    app = tmp_path / "appdata"
    folder = app / "Claude-Data" / "claude_x" / "claude-code-sessions" / "a" / "b"
    folder.mkdir(parents=True)
    record = {"sessionId": SID, "title": "Lot demo", "originCwd": str(repo), "cwd": str(trees["open"]),
              "worktreePath": str(trees["open"]), "branch": "open", "isArchived": False,
              "spawnedFrom": {"sessionId": "local_parent", "name": "w1-demo"},
              "writtenBranches": [f"{trees['open']}\u0000open", f"{trees['kept']}\u0000kept"],
              "prs": [{"prNumber": 3, "repo": "owner/demo", "branch": "done", "state": "MERGED"},
                      {"prNumber": 4, "repo": "owner/demo", "branch": "open", "state": "OPEN"}]}
    (folder / f"{SID}.json").write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(app))
    scratch = tmp_path / "venvs" / "demo"
    scratch.mkdir(parents=True)

    class L:
        def save(self):
            (folder / f"{SID}.json").write_text(json.dumps(self.record), encoding="utf-8")
    L.repo, L.trees, L.scratch, L.folder, L.record, L.make = repo, trees, scratch, folder, record, make_repo
    return L()


def _by(rep):
    return {b.branch: b for b in rep.branches}


def _ready(lot):
    """The lot finished: open's PR merged by squash, local pushed and merged, kept kept."""
    lot.record["prs"][1]["state"] = "MERGED"
    lot.save()
    run_git(lot.repo, "push", "-q", "origin", "local")
    run_git(lot.repo, "merge", "-q", "--no-ff", "-m", "merge local", "local")
    run_git(lot.repo, "push", "-q", "origin", "main")
    run_git(lot.repo, "fetch", "-q", "origin")


def test_what_is_left_open_unpushed_unmerged_and_a_dirty_worktree(lot):
    (lot.trees["kept"] / "draft.txt").write_text("x\n", encoding="utf-8")
    rep = lotcheck.check(SID, branches=["local"], offline=True)
    assert rep.lot == "w1-demo" and len(rep.repos) == 1
    b = _by(rep)
    assert b["done"].merged and b["done"].in_default and b["done"].states == {"MERGED"}
    assert b["open"].pushed and not b["open"].merged and b["open"].left == "its PR owner/demo#4 is open"
    assert b["kept"].left == "not merged (--keep it if on purpose)"
    assert b["local"].left == "a commit neither pushed nor in the default branch"
    assert not rep.ready and rep.removals() == []
    left = "\n".join(rep.left)
    assert "draft.txt" in left and "owner/demo#4 is open" in left and "branch local" in left
    assert sorted(w.branch for w in rep.worktrees) == ["kept", "local", "open"]


def test_ready_once_merged_kept_and_clean_with_what_to_remove(lot):
    _ready(lot)
    rep = lotcheck.check(SID, branches=["local"], keep=["kept"], scratch=[str(lot.scratch.parent / "{lot}")],
                         lot="demo", offline=True)
    assert rep.ready, rep.left
    removals = "\n".join(rep.removals())
    assert f'worktree remove "{lot.trees["open"]}"' in removals
    assert "wt-kept" not in removals and 'branch -d "kept"' not in removals   # kept on purpose: it stays
    assert 'branch -d "done"' in removals and 'branch -d "local"' in removals
    assert 'branch -d "open"   (merged by squash' in removals
    assert f"remove the folder {lot.scratch}" in removals
    assert run_git(lot.repo, "worktree", "list").count("wt-") == 3   # read only: nothing removed


def test_a_commit_after_a_squash_merge_left_unpushed_is_left(lot):
    _ready(lot)
    lot.make.commit(lot.trees["open"], {"late.txt": "late\n"}, msg="late")
    rep = lotcheck.check(SID, branches=["local"], keep=["kept"], offline=True)
    assert _by(rep)["open"].left == "a commit neither pushed nor in the default branch" and not rep.ready


def test_a_pr_of_another_repo_and_a_branch_reused_with_an_open_pr(lot):
    _ready(lot)
    lot.record["prs"].append({"prNumber": 9, "repo": "owner/other", "branch": "kept", "state": "MERGED"})
    lot.record["prs"].append({"prNumber": 5, "repo": "owner/demo", "branch": "done", "state": "OPEN"})
    lot.save()
    rep = lotcheck.check(SID, branches=["local"], offline=True)
    b = _by(rep)
    assert [p["pr"] for p in b["kept"].prs] == [] and not b["kept"].merged   # owner/other's PR is not this repo's
    assert b["done"].left == "its PR owner/demo#5 is open"   # an open PR of the branch, whatever the other


def test_the_default_branch_and_the_main_checkout_s_never_count(lot):
    lot.record["writtenBranches"].append(f"{lot.repo}\u0000main")
    lot.save()
    _ready(lot)
    rep = lotcheck.check(SID, branches=["local", "master"], keep=["kept"], offline=True)
    assert "main" not in _by(rep) and rep.ready
    assert 'branch -d "main"' not in "\n".join(rep.removals())
    assert all(not os.path.samefile(w.path, lot.repo) for w in rep.worktrees)


def test_a_closed_pr_unmerged_is_left_and_a_gone_worktree_is_pruned_first(lot):
    _ready(lot)
    lot.record["prs"].append({"prNumber": 6, "repo": "owner/demo", "branch": "kept", "state": "CLOSED"})
    lot.save()
    rep = lotcheck.check(SID, branches=["local"], offline=True)
    assert _by(rep)["kept"].left.startswith("its PR closed unmerged")
    shutil.rmtree(lot.trees["kept"])
    rep = lotcheck.check(SID, branches=["local"], keep=["kept"], offline=True)
    assert rep.prunable == [rep.repos[0]] and rep.removals()[0].endswith("worktree prune")


def test_a_detached_head_with_commits_no_remote_holds_is_left(lot):
    _ready(lot)
    run_git(lot.trees["open"], "switch", "-q", "--detach")
    lot.make.commit(lot.trees["open"], {"lost.txt": "x\n"}, msg="on a detached HEAD")
    rep = lotcheck.check(SID, branches=["local"], keep=["kept"], offline=True)
    assert any("detached HEAD" in x for x in rep.left)


def test_scratch_with_no_lot_name_is_refused_and_the_newest_session_file_wins(lot, tmp_path):
    lot.record.pop("spawnedFrom")
    lot.save()
    with pytest.raises(lotcheck.LotError, match="no name"):
        lotcheck.check(SID, scratch=[str(tmp_path / "venvs" / "{lot}")], offline=True)
    older = lot.folder.parent.parent.parent.parent / "claude_old" / "claude-code-sessions" / "x" / "y"
    older.mkdir(parents=True)
    (older / f"{SID}.json").write_text(json.dumps({**lot.record, "title": "older"}), encoding="utf-8")
    os.utime(older / f"{SID}.json", (1, 1))
    assert lotcheck.check(SID, offline=True).title == "Lot demo"
    with pytest.raises(lotcheck.LotError, match="no session file"):
        lotcheck.check("*", offline=True)   # an id is not a pattern


def test_brain_lot_check_exits_by_the_answer(lot, capsys, monkeypatch):
    assert cli.main(["lot", "check", SID, "--offline"]) == 1
    out = capsys.readouterr().out
    assert "not ready" in out and "branch   done: merged, PR owner/demo#3 merged (app)" in out
    assert cli.main(["lot", "check", SID, "--offline", "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["ready"] is False and data["session"] == SID and data["removals"] == []
    assert cli.main(["lot", "check", "local_missing", "--offline"]) == 2
    assert "no session file" in capsys.readouterr().err
    assert cli.main(["lot", "check", "--offline"]) == 2   # no session given, none in the environment
    assert "which session" in capsys.readouterr().err
    monkeypatch.setenv("CLAUDE_CODE_HOST_SESSION_ID", SID)   # the session that runs it
    assert cli.main(["lot", "check", "--offline"]) == 1 and "Lot demo" in capsys.readouterr().out


def test_gh_s_state_wins_over_the_app_s_and_says_so(lot, monkeypatch):
    monkeypatch.setattr(lotcheck, "gh_state", lambda slug, n: "MERGED" if n == 4 else "")
    rep = lotcheck.check(SID)
    o = _by(rep)["open"]
    assert o.prs == [{"pr": "owner/demo#4", "state": "MERGED", "source": "gh"}] and o.merged and not o.in_default
    assert _by(rep)["done"].prs[0]["source"] == "app"   # gh did not answer for #3
