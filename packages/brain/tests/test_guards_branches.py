"""The branches guard: the names a session gives a branch in the registry's repos, against the allowed list."""

import io
import json
import shutil
from pathlib import Path

import pytest
from conftest import GIT_ENV, git_init, run_git

from brain import guards


@pytest.fixture(scope="module")
def repos(tmp_path_factory):
    """The two repos, made once per module and copied by each test (git's calls were most of this module's time)."""
    if not shutil.which("git"):
        pytest.skip("git not available")
    where = tmp_path_factory.mktemp("branches")
    for name in ("demo", "other"):
        r = git_init(where / name)
        (r / "a.txt").write_text("a\n", encoding="utf-8")
        run_git(r, "add", "-A")
        run_git(r, "commit", "-q", "-m", "init")
        run_git(r, "remote", "add", "origin", f"https://github.com/ada/{name}.git")
    run_git(where / "demo", "checkout", "-q", "-b", "claude/start")
    return where


@pytest.fixture
def reg(repos, tmp_path, monkeypatch):
    """A registered repo (origin github.com/ada/demo) on branch claude/start, and an unregistered one."""
    for k, v in GIT_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv(guards.ALLOW_ENV, raising=False)
    monkeypatch.setattr(guards, "gitleaks", lambda repo: None)
    out = {name: Path(shutil.copytree(repos / name, tmp_path / name)) for name in ("demo", "other")}
    (tmp_path / "projects.yaml").write_text(f"demo: {{root: {out['demo'].as_posix()}}}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(tmp_path / "projects.yaml"))
    return out


def decide(tool, cwd, command):
    p = {"session_id": "s-1", "cwd": str(cwd), "hook_event_name": "PreToolUse", "tool_name": tool,
         "tool_input": {"command": command}, "tool_use_id": "toolu_01"}
    out = io.StringIO()
    assert guards.main(stdin=io.StringIO(json.dumps(p)), stdout=out) == 0
    return json.loads(out.getvalue())["hookSpecificOutput"]["permissionDecisionReason"] if out.getvalue() else None


def bash(cwd, command):
    return decide("Bash", cwd, command)


@pytest.mark.parametrize("command", [
    "git checkout -b fix-thing", "git checkout -q -B Fix/Thing main", "git checkout --orphan scratch",
    "git switch -c wip", "git switch --create=wip", "git switch -C feature/x",
    "git worktree add -b wip ../wt main", "git worktree add ../wip", "git worktree add --lock --reason r ../wip",
    "git branch tmp", "git branch --track tmp origin/main", "git branch -m tmp", "git branch -c claude/start tmp",
    "git -C . checkout -btmp", "gh pr create --head tmp --title t --body b", "gh pr create -H ada:tmp",
    "git checkout -b memory/2026-11-03", "git checkout -b claude/Upper",
])
def test_a_name_outside_the_list_is_refused(reg, command):
    reason = bash(reg["demo"], command)
    assert reason and "fits none of the allowed names (config.json branches.allowed): claude/<slug>, " \
                      "memory/<host>/<date>, feat/, fix/" in reason
    assert "BRAIN_GUARD_ALLOW=branches (or branches:name)" in reason


@pytest.mark.parametrize("command", [
    "git checkout -b claude/fix-thing", "git switch -c feat/x", "git worktree add -b docs/x ../wt main",
    "git worktree add --detach ../wt", "git worktree add ../wt claude/start", "git branch fix/x",
    "git branch -d tmp", "git branch -D tmp", "git branch --list 'tmp*'", "git branch -a", "git branch -vv",
    "git branch -u origin/main", "git branch -m claude/renamed", "git checkout main", "git checkout -- a.txt",
    "git switch -c main", "git checkout -b memory/host1/2026-11-03", "gh pr create -H ada:claude/ok",
    "gh pr create --title t --body b", "git checkout -b x --help", "gh pr create --help",
    "for b in tmp1 tmp2; do gh pr create --head $b; done",
])
def test_a_name_in_the_list_and_what_names_no_branch_pass(reg, command):
    assert bash(reg["demo"], command) is None   # gh pr create alone: the head is claude/start


def test_the_implicit_worktree_branch_is_judged_only_when_new(reg):
    run_git(reg["demo"], "branch", "wt-old")
    assert bash(reg["demo"], "git worktree add ../wt-old") is None   # it checks out the branch that exists
    assert bash(reg["demo"], "git worktree add ../wt-new")


def test_gh_pr_create_judges_the_current_branch(reg):
    run_git(reg["demo"], "checkout", "-q", "-b", "oddname")
    reason = bash(reg["demo"], "gh pr create --title t --body b")
    assert reason.startswith("brain-core guard: gh pr create refused: the branch name oddname fits none")
    assert "rename the branch first (git branch -m NEW), then push it (such as claude/oddname)" in reason
    run_git(reg["demo"], "checkout", "-q", "--detach")
    assert bash(reg["demo"], "gh pr create --title t --body b") is None   # detached: gh refuses by itself


def test_only_the_registrys_repos_are_judged(reg, tmp_path):
    assert bash(reg["other"], "git checkout -b anything") is None
    assert bash(tmp_path, "gh pr create --repo ada/other --head anything") is None
    assert bash(tmp_path, "gh pr create --repo ada/demo --head anything")   # registered by its origin
    assert bash(tmp_path, "gh pr create -R github.com/ADA/Demo --head anything")
    wt = tmp_path / "wt"
    run_git(reg["demo"], "worktree", "add", "-q", "--detach", str(wt))
    assert bash(wt, "git switch -c anything")   # a worktree of a registered repo is judged


def test_config_json_replaces_the_list(reg, tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"v": 1, "identity": {"owner": "Ada"},
                               "branches": {"allowed": ["topic/", "rel-<date>", "u/<host>/<slug>"]}}),
                   encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(cfg))
    assert bash(reg["demo"], "git checkout -b topic/x") is None
    assert bash(reg["demo"], "git checkout -b rel-2026-11-03") is None
    assert bash(reg["demo"], "git checkout -b u/host1/x") is None
    reason = bash(reg["demo"], "git checkout -b claude/x")
    assert "branches.allowed): topic/, rel-<date>, u/<host>/<slug>;" in reason and "(such as topic/claude-x)" in reason


def test_powershell_and_the_override(reg, brain_home, monkeypatch):
    (brain_home / "ledger").mkdir(parents=True)
    assert decide("PowerShell", reg["demo"], "Set-Location .; git checkout -b tmp")
    monkeypatch.setenv(guards.ALLOW_ENV, "branches")
    assert decide("PowerShell", reg["demo"], "git checkout -b tmp") is None
    rows = [json.loads(line) for f in sorted((brain_home / "ledger").glob("guards-*.jsonl"))
            for line in f.read_text(encoding="utf-8").splitlines()]
    assert [(r["guard"], r["check"], r["decision"]) for r in rows] == [("branches", "name", "denied"),
                                                                        ("branches", "name", "overridden")]


def test_branch_rules_compile_the_shapes():
    entries, rx = guards.branch_rules()
    assert entries == list(guards.BRANCHES)
    assert rx.fullmatch("memory/host1/2026-11-03") and not rx.fullmatch("memory/host1/2026-11")
    assert rx.fullmatch("claude/a.b_c-1") and not rx.fullmatch("claude/a/b") and not rx.fullmatch("claude/-a")
    assert rx.fullmatch("release/v0.6.0") and not rx.fullmatch("feat/")
