"""brain lot check SESSION (wi-brain-lot-close-check, brain.lotcheck): a finished lot read from the desktop app's file
of its session: its worktrees clean, its branches merged (by PR or by the default branch) or kept, and pushed;
« ready to archive » and what to remove, else what is left. Read only. Fixtures only: a repo and an app folder here."""

import json

import pytest
from brain import cli, lotcheck
from conftest import git_init, run_git

SID = "local_0000aaaa-1111-2222-3333-444455556666"


@pytest.fixture
def lot(make_repo, tmp_path, monkeypatch):
    """A repo with an origin; branches: done (merged into main), open (pushed, its PR open), kept (pushed, unmerged),
    local (never pushed); a worktree on each but done's; the app's file of the session."""
    origin = git_init(tmp_path / "origin.git", bare=True)
    repo = make_repo("repo", {"a.txt": "a\n"})
    run_git(repo, "remote", "add", "origin", str(origin))
    run_git(repo, "push", "-q", "-u", "origin", "main")
    for b in ("done", "open", "kept", "local"):
        run_git(repo, "switch", "-q", "-c", b, "main")
        make_repo.commit(repo, {f"{b}.txt": b + "\n"}, msg=b)
        if b != "local":
            run_git(repo, "push", "-q", "-u", "origin", b)
    run_git(repo, "switch", "-q", "main")
    run_git(repo, "merge", "-q", "--no-ff", "-m", "merge done", "done")
    run_git(repo, "push", "-q", "origin", "main")
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
        pass
    L.repo, L.trees, L.scratch, L.folder, L.record = repo, trees, scratch, folder, record
    return L


def _by(rep):
    return {b.branch: b for b in rep.branches}


def test_what_is_left_open_unpushed_unmerged_and_a_dirty_worktree(lot):
    (lot.trees["kept"] / "draft.txt").write_text("x\n", encoding="utf-8")
    rep = lotcheck.check(SID, branches=["local"], offline=True)
    assert rep.lot == "w1-demo" and rep.repos == [str(lot.repo)]
    b = _by(rep)
    assert b["done"].merged and b["done"].in_default and b["done"].pr_state == "MERGED"
    assert b["open"].pushed and not b["open"].merged and b["open"].left == "its PR owner/demo#4 is open"
    assert b["kept"].left == "not merged (--keep it if on purpose)" and b["local"].left == "not pushed"
    assert not rep.ready
    left = "\n".join(rep.left)
    assert "draft.txt" in left and "owner/demo#4 is open" in left and "branch local" in left
    assert sorted(w.branch for w in rep.worktrees) == ["kept", "local", "open"]


def test_ready_once_merged_kept_and_clean_with_what_to_remove(lot):
    lot.record["prs"][1]["state"] = "MERGED"   # open's PR merged by squash: main does not hold its tip
    (lot.folder / f"{SID}.json").write_text(json.dumps(lot.record), encoding="utf-8")
    run_git(lot.repo, "push", "-q", "origin", "local")
    run_git(lot.repo, "merge", "-q", "--no-ff", "-m", "merge local", "local")
    run_git(lot.repo, "push", "-q", "origin", "main")
    rep = lotcheck.check(SID, branches=["local"], keep=["kept"], scratch=[str(lot.scratch.parent / "{lot}")],
                         lot="demo", offline=True)
    assert rep.ready, rep.left
    removals = "\n".join(rep.removals())
    assert f'worktree remove "{lot.trees["open"]}"' in removals
    assert "wt-kept" not in removals and "branch -d kept" not in removals   # kept on purpose: it stays
    assert "branch -d done" in removals and "branch -d local" in removals
    assert "branch -d open   (merged by squash" in removals
    assert f"remove the folder {lot.scratch}" in removals
    assert run_git(lot.repo, "worktree", "list").count("wt-") == 3   # read only: nothing removed


def test_brain_lot_check_exits_by_the_answer(lot, capsys):
    assert cli.main(["lot", "check", SID, "--offline"]) == 1
    out = capsys.readouterr().out
    assert "not ready" in out and "branch   done: merged, PR owner/demo#3 merged" in out
    assert cli.main(["lot", "check", SID, "--offline", "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["ready"] is False and data["session"] == SID
    assert cli.main(["lot", "check", "local_missing", "--offline"]) == 2
    assert "no session file" in capsys.readouterr().err
    assert cli.main(["lot", "check", "--offline"]) == 2   # no session given, none in the environment
    assert "which session" in capsys.readouterr().err


def test_gh_s_state_wins_over_the_app_s(lot, monkeypatch):
    monkeypatch.setattr(lotcheck, "gh_state", lambda slug, n: "MERGED" if n == 4 else "")
    rep = lotcheck.check(SID)
    assert _by(rep)["open"].pr_state == "MERGED" and _by(rep)["open"].merged and not _by(rep)["open"].in_default
