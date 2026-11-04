"""brain tidy on temporary repos: an origin, its clone as the main checkout, worktrees, the desktop app's state."""

import json
import os
import shutil
import sys
import time

import pytest
from conftest import GIT_ENV, git_init, run_git

from brain import cli, projects, tidy


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A main checkout on main with an origin (origin/HEAD set), registered as project demo; no desktop app."""
    if not shutil.which("git"):
        pytest.skip("git not available")
    for k, v in GIT_ENV.items():
        monkeypatch.setenv(k, v)
    origin = tmp_path / "origin.git"
    git_init(origin, bare=True)
    main = tmp_path / "main"
    main.mkdir()
    git_init(main)
    run_git(main, "config", "commit.gpgsign", "false")
    (main / "a.txt").write_text("a\n", encoding="utf-8")
    run_git(main, "add", "-A")
    run_git(main, "commit", "-q", "-m", "init")
    run_git(main, "remote", "add", "origin", str(origin))
    run_git(main, "push", "-q", "-u", "origin", "main")
    run_git(main, "remote", "set-head", "origin", "main")
    reg = tmp_path / "projects.yaml"
    reg.write_text(f"demo: {{root: {main.as_posix()}}}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.setattr(tidy, "_open_pr_heads", lambda repo: (set(), ""))
    return main


def commit(repo, name, text="x"):
    (repo / name).write_text(text + "\n", encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", name)


def merged(main, name, push=False):
    """A branch with a commit, merged into main (and main pushed)."""
    run_git(main, "checkout", "-q", "-b", name)
    commit(main, name.replace("/", "-") + ".txt")
    if push:
        run_git(main, "push", "-q", "origin", name)
    run_git(main, "checkout", "-q", "main")
    run_git(main, "merge", "-q", "--no-ff", "-m", f"merge {name}", name)
    run_git(main, "push", "-q", "origin", "main")


def unmerged(main, name, push=False):
    run_git(main, "checkout", "-q", "-b", name)
    commit(main, name.replace("/", "-") + ".txt")
    if push:
        run_git(main, "push", "-q", "origin", name)
    run_git(main, "checkout", "-q", "main")


def branches(main):
    return set(run_git(main, "for-each-ref", "--format=%(refname:short)", "refs/heads").split())


def app(tmp_path, leases=None, sessions=None):
    """The desktop app's state: {worktree path: session id} leases, {session id: (cwd, archived)} session files."""
    base = tmp_path / "appdata" / "Claude-Data" / "claude_x"
    (base / "claude-code-sessions" / "acct" / "org").mkdir(parents=True, exist_ok=True)
    (base / "git-worktrees.json").write_text(json.dumps({"worktrees": {
        os.path.basename(p): {"name": os.path.basename(p), "path": str(p), "leasedBy": sid}
        for p, sid in (leases or {}).items()}}), encoding="utf-8")
    for sid, (cwd, archived) in (sessions or {}).items():
        (base / "claude-code-sessions" / "acct" / "org" / f"{sid}.json").write_text(
            json.dumps({"sessionId": sid, "cwd": str(cwd), "isArchived": archived}), encoding="utf-8")


def demo():
    return projects.get("demo")


def one(**kw):
    (rp,) = tidy.plan([demo()], **kw)
    return rp


# --- branches ----------------------------------------------------------------------------------------------------

def test_merged_branches_are_listed_then_deleted_with_d_only(repo, capsys):
    merged(repo, "feat/a")
    unmerged(repo, "feat/b")
    merged(repo, "master")   # a default branch's name is never deleted
    rp = one()
    assert rp.default == "main"
    assert [s.target for s in rp.of("branch", True)] == ["feat/a"]
    assert tidy.main([demo()]) == 0
    out = capsys.readouterr().out
    assert "delete feat/a" in out and "tidy: dry run, nothing removed" in out
    assert branches(repo) == {"main", "master", "feat/a", "feat/b"}   # the dry run removes nothing
    assert tidy.main([demo()], apply=True) == 0
    assert "deleted branch feat/a" in capsys.readouterr().out
    assert branches(repo) == {"main", "master", "feat/b"}


def test_a_branch_merged_into_origin_only_counts(repo):
    """origin/main holds it while the local main is behind: still merged (git branch -d then checks its upstream)."""
    merged(repo, "feat/a", push=True)
    run_git(repo, "branch", "-u", "origin/feat/a", "feat/a")
    run_git(repo, "reset", "-q", "--hard", "HEAD~1")
    assert [s.target for s in one().of("branch", True)] == ["feat/a"]


# --- worktrees ---------------------------------------------------------------------------------------------------

def add_worktree(main, tmp_path, name, branch=None, base="main"):
    wt = tmp_path / "wts" / name
    args = ["worktree", "add", "-q"] + (["-b", branch] if branch else ["--detach"]) + [str(wt), base]
    run_git(main, *args)
    return wt


def test_a_worktree_whose_session_is_archived_is_removed_then_its_branch(repo, tmp_path, capsys):
    merged(repo, "claude/done")
    run_git(repo, "branch", "-q", "claude/live", "main")
    done = add_worktree(repo, tmp_path, "done", base="claude/done")
    run_git(done, "checkout", "-q", "claude/done")
    live = add_worktree(repo, tmp_path, "live", base="claude/live")
    run_git(live, "checkout", "-q", "claude/live")
    app(tmp_path, leases={done: "local_a", live: "local_b"},
        sessions={"local_a": (done, True), "local_b": (live, False)})
    rp = one()
    steps = {os.path.basename(s.target): s for s in rp.of("worktree")}
    assert steps["done"].remove and "session local_a archived" in steps["done"].why
    assert not steps["live"].remove and "session local_b is open" in steps["live"].why
    br = {s.target: s for s in rp.of("branch")}
    assert br["claude/done"].remove and br["claude/done"].why == "after its worktree"
    assert not br["claude/live"].remove and "checked out in" in br["claude/live"].why
    assert tidy.main([demo()], apply=True) == 0
    out = capsys.readouterr().out
    assert f"removed worktree {done}" in out and "deleted branch claude/done" in out
    assert not done.exists() and live.is_dir()
    assert "claude/done" not in branches(repo) and "claude/live" in branches(repo)


def test_a_lease_to_a_session_without_a_file_is_gone(repo, tmp_path):
    wt = add_worktree(repo, tmp_path, "w")
    app(tmp_path, leases={wt: "local_zz"})
    (s,) = one().of("worktree")
    assert s.remove and "session local_zz gone" in s.why and "detached" in s.why


def test_a_dirty_worktree_an_unmerged_one_a_locked_one_and_the_current_folder_stay(repo, tmp_path, monkeypatch):
    dirty = add_worktree(repo, tmp_path, "dirty")
    (dirty / "new.txt").write_text("work\n", encoding="utf-8")   # untracked counts
    unmerged(repo, "feat/wip")
    wip = add_worktree(repo, tmp_path, "wip", base="feat/wip")
    run_git(wip, "checkout", "-q", "feat/wip")
    locked = add_worktree(repo, tmp_path, "locked")
    run_git(repo, "worktree", "lock", str(locked))
    here = add_worktree(repo, tmp_path, "here")
    orphan = add_worktree(repo, tmp_path, "orphan")
    commit(orphan, "only-here.txt")   # detached on a commit no branch holds
    app(tmp_path, sessions={f"local_{n}": (tmp_path / "wts" / n, True)
                            for n in ("dirty", "wip", "locked", "here", "orphan")})
    monkeypatch.chdir(here)
    whys = {os.path.basename(s.target): (s.remove, s.why) for s in one().of("worktree")}
    assert whys == {"dirty": (False, "1 change(s) not committed"), "wip": (False, "feat/wip is not merged"),
                    "locked": (False, "locked"), "here": (False, "the current folder"),
                    "orphan": (False, "detached on a commit no branch holds")}


def test_without_the_app_a_recent_worktree_is_live_an_idle_one_stale(repo, tmp_path):
    wt = add_worktree(repo, tmp_path, "w")
    (rp,) = tidy.plan([demo()])
    assert not rp.of("worktree")[0].remove and "active" in rp.of("worktree")[0].why
    later = time.time() + (tidy.RECENT_HOURS + 2) * 3600
    rp = tidy.plan_repo("demo", "main", repo, False, now=later)
    (s,) = rp.of("worktree")
    assert s.remove and "no session known, idle" in s.why and s.target == str(wt)


def _link(target, link):
    """A junction on Windows, a symbolic link elsewhere; False when the system refuses."""
    try:
        if sys.platform == "win32":
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
        else:
            os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, AttributeError):
        return False


def test_junctions_into_production_are_unlinked_before_the_worktree_goes(repo, tmp_path, monkeypatch, capsys):
    prod = tmp_path / "prod"
    (prod / ".git").mkdir(parents=True)
    (prod / "data").mkdir()
    (prod / "data" / "keep.csv").write_text("1\n", encoding="utf-8")
    reg = tmp_path / "projects.yaml"
    reg.write_text(f"demo: {{root: {repo.as_posix()}}}\nlive: {{root: {prod.as_posix()}, production: [.]}}\n",
                   encoding="utf-8")
    wt = add_worktree(repo, tmp_path, "w")
    (repo / ".git" / "info" / "exclude").write_text("data\n", encoding="utf-8")   # ignored: the worktree stays clean
    if not _link(prod / "data", wt / "data"):
        pytest.skip("no junction or symbolic link here")
    app(tmp_path, sessions={"local_a": (wt, True)})
    (s,) = one().of("worktree")
    assert s.remove and s.links == [str(wt / "data")] and s.into_production == [str(wt / "data")]
    assert "a junction into production" in "\n".join(tidy.render(one()))
    assert tidy.main([demo()], apply=True) == 0
    out = capsys.readouterr().out
    assert f"unlinked {wt / 'data'} (into production)" in out and f"removed worktree {wt}" in out
    assert (prod / "data" / "keep.csv").read_text(encoding="utf-8") == "1\n"   # never followed


def test_a_worktree_whose_folder_is_gone_is_pruned_except_in_production(repo, tmp_path, capsys):
    wt = add_worktree(repo, tmp_path, "gone")
    shutil.rmtree(wt)
    (s,) = one().of("prune")
    assert s.remove and s.why == "its folder is gone"
    rp = tidy.plan_repo("demo", "main", repo, True)
    (s,) = rp.of("prune")
    assert not s.remove and "production" in s.why
    assert tidy.apply_repo(rp) == []   # production: git worktree remove and git branch -d only
    assert "gone" in run_git(repo, "worktree", "list")
    assert tidy.main([demo()], apply=True) == 0
    assert "pruned" in capsys.readouterr().out and "gone" not in run_git(repo, "worktree", "list")


# --- the desktop app's state -------------------------------------------------------------------------------------

def test_session_state_reads_leases_and_session_cwds(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    w1, w2, w3 = (tmp_path / n for n in ("w1", "w2", "w3"))
    app(tmp_path, leases={w1: "local_1"}, sessions={"local_1": (w1, False), "local_2": (w2 / "sub", True),
                                                     "local_3": (w2, False)})
    st = tidy.app_state()
    assert st.seen and tidy.session_state(str(w1), st) == ("live", "local_1")
    assert tidy.session_state(str(w2), st) == ("live", "local_3")   # one open session keeps it
    assert tidy.session_state(str(w3), st) == ("unknown", "")
    monkeypatch.delenv("LOCALAPPDATA")
    assert not tidy.app_state().seen


# --- remote branches ---------------------------------------------------------------------------------------------

def remote_heads(repo):
    return {ln.split("refs/heads/")[1] for ln in run_git(repo, "ls-remote", "--heads", "origin").splitlines()}


def test_remote_merged_branches_are_the_owners_to_delete(repo, tmp_path, monkeypatch, capsys):
    merged(repo, "feat/a", push=True)
    merged(repo, "feat/pr", push=True)
    merged(repo, "claude/live", push=True)
    unmerged(repo, "feat/b", push=True)
    live = add_worktree(repo, tmp_path, "live", base="claude/live")
    run_git(live, "checkout", "-q", "claude/live")
    app(tmp_path, sessions={"local_l": (live, False)})
    monkeypatch.setattr(tidy, "_open_pr_heads", lambda r: ({"feat/pr"}, ""))
    rp = one(remote=True)
    assert rp.remote == ["feat/a"]
    assert "kept, checked out in a worktree that stays: claude/live" in rp.remote_note
    assert "kept, the head of an open PR: feat/pr" in rp.remote_note
    monkeypatch.setenv("CLAUDECODE", "1")   # a session's shell: the exact command goes to the owner's queue
    assert tidy.main([demo()], remote=True, apply=True) == 0
    out = capsys.readouterr().out
    assert "brain queue add --kind action" in out and "--command 'brain tidy --project demo --remote --apply'" in out
    assert "feat/a" in remote_heads(repo)
    monkeypatch.delenv("CLAUDECODE")   # the owner's terminal
    assert tidy.main([demo()], remote=True, apply=True) == 0
    assert "deleted 1 remote branch(es) of origin" in capsys.readouterr().out
    assert remote_heads(repo) == {"main", "feat/pr", "claude/live", "feat/b"}


def test_without_remote_nothing_is_read_from_origin(repo, monkeypatch):
    monkeypatch.setattr(tidy, "remote_merged", lambda *a: pytest.fail("origin read without --remote"))
    assert one().remote is None


# --- the hygiene line, the command -------------------------------------------------------------------------------

def test_the_hygiene_line(repo, tmp_path):
    assert tidy.hygiene(demo()) is None
    merged(repo, "feat/a")
    assert tidy.hygiene(demo()) == ("warning: tidy: 1 merged branch(es) to remove: brain tidy (the list), then "
                                    "--apply")
    assert tidy.hygiene(projects.Project("x", tmp_path / "nowhere")) is None


def test_the_command_plans_as_json_and_takes_all(repo, capsys):
    merged(repo, "feat/a")
    assert cli.main(["--project", "demo", "tidy", "--json"]) == 0
    (rp,) = json.loads(capsys.readouterr().out)
    assert rp["default"] == "main" and [s["target"] for s in rp["steps"] if s["remove"]] == ["feat/a"]
    assert cli.main(["tidy", "--all"]) == 0
    assert "== demo: main" in capsys.readouterr().out
    assert branches(repo) == {"main", "feat/a"}


def test_a_repo_without_a_default_branch_is_reported(tmp_path, monkeypatch):
    if not shutil.which("git"):
        pytest.skip("git not available")
    bare = tmp_path / "r"
    bare.mkdir()
    git_init(bare, "trunk")
    rp = tidy.plan_repo("x", "r", bare, False)
    assert rp.error.startswith("no default branch") and tidy.render(rp)[0].endswith(rp.error)
