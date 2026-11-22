"""The owner's engine clone kept current (wi-brain-clone-autopull; the owner's answer of 2026-11-18: a fast-forward
only): brain refresh fast-forwards it when it is on main, clean and in no operation, and otherwise says why and
leaves it exactly as it was (never a switch, a commit, a reset or a stash). On a throwaway remote and clones."""

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from brain import engineclone
from brain.commands import refresh

needs_git = pytest.mark.skipif(not shutil.which("git"), reason="git missing")


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                          timeout=60)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def commit(repo: Path, name: str, text: str = "x\n") -> str:
    (repo / name).write_text(text, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "--quiet", "-m", f"add {name}")
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def clones(tmp_path, monkeypatch):
    """A bare remote of the engine, the owner's clone at its first commit, a second clone that merged one more
    commit into the remote's main: SimpleNamespace(remote, clone, other, first, last)."""
    cfg = tmp_path / "gitconfig"
    cfg.write_text("[user]\n\tname = Ada\n\temail = ada@example.com\n[commit]\n\tgpgsign = false\n"
                   "[init]\n\tdefaultBranch = main\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(cfg))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    remote = tmp_path / "engine.git"
    git(tmp_path, "init", "--quiet", "--bare", str(remote))
    other = tmp_path / "other"
    git(tmp_path, "clone", "--quiet", str(remote), str(other))
    first = commit(other, "a.txt")
    git(other, "push", "--quiet", "origin", "main")
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "--quiet", str(remote), str(clone))
    last = commit(other, "b.txt")
    git(other, "push", "--quiet", "origin", "main")
    return SimpleNamespace(remote=remote, clone=clone, other=other, first=first, last=last)


def state(repo: Path) -> tuple:
    """What the rule never changes on its own: the branch, HEAD, the working tree's status, the stash."""
    stash = subprocess.run(["git", "-C", str(repo), "stash", "list"], capture_output=True, text=True).stdout
    return (git(repo, "branch", "--show-current"), git(repo, "rev-parse", "HEAD"),
            git(repo, "status", "--porcelain"), stash)


@needs_git
def test_a_clean_main_is_fast_forwarded(clones):
    res = engineclone.pull(clones.clone)
    assert res.state == engineclone.PULLED, res.line
    assert git(clones.clone, "rev-parse", "HEAD") == clones.last
    assert res.said() == f"engine clone {clones.clone}: main fast-forwarded {clones.first[:12]} -> {clones.last[:12]}"
    again = engineclone.pull(clones.clone)
    assert again.state == engineclone.SAME and "up to date" in again.line


@needs_git
@pytest.mark.parametrize("make, said", [
    (lambda c: git(c, "switch", "--quiet", "-c", "feat/x"), "on feat/x, not main: left as it is (never switched)"),
    (lambda c: (c / "a.txt").write_text("edited\n", encoding="utf-8"),
     "1 tracked file(s) changed: left as it is (never stashed, reset or committed)"),
    (lambda c: (c / "a.txt").write_text("edited\n", encoding="utf-8") or git(c, "add", "a.txt"),
     "1 tracked file(s) changed"),
    (lambda c: git(c, "switch", "--quiet", "--detach"), "on a detached HEAD, not main"),
    (lambda c: (Path(git(c, "rev-parse", "--absolute-git-dir")) / "MERGE_HEAD").write_text("0" * 40 + "\n"),
     "a merge is in progress: left as it is"),
])
def test_any_other_state_is_said_and_left(clones, make, said):
    make(clones.clone)
    before = state(clones.clone)
    res = engineclone.pull(clones.clone)
    assert res.state == engineclone.SKIPPED and said in res.line
    assert state(clones.clone) == before


@needs_git
def test_an_untracked_file_does_not_stop_it(clones):
    (clones.clone / "notes.txt").write_text("mine\n", encoding="utf-8")
    assert engineclone.pull(clones.clone).state == engineclone.PULLED
    assert (clones.clone / "notes.txt").read_text(encoding="utf-8") == "mine\n"


@needs_git
def test_a_main_with_commits_of_its_own_is_not_moved(clones):
    mine = commit(clones.clone, "local.txt")
    before = state(clones.clone)
    res = engineclone.pull(clones.clone)
    assert res.state == engineclone.FAILED and "did not move it" in res.line and "commits of its own" in res.line
    assert state(clones.clone) == before and git(clones.clone, "rev-parse", "HEAD") == mine


@needs_git
def test_an_unreachable_remote_is_said(clones):
    git(clones.clone, "remote", "set-url", "origin", str(clones.remote.parent / "gone.git"))
    res = engineclone.pull(clones.clone)
    assert res.state == engineclone.FAILED and git(clones.clone, "rev-parse", "HEAD") == clones.first


def test_a_folder_that_is_no_checkout_is_said(tmp_path):
    res = engineclone.pull(tmp_path)
    assert res.state == engineclone.SKIPPED and "not a git checkout" in res.line


def brain_with(tmp_path, monkeypatch, engine: dict, projects: str = "") -> Path:
    root = tmp_path / "brain"
    root.mkdir(exist_ok=True)
    (root / "config.json").write_text(json.dumps({"v": 1, "engine": engine}), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(root / "config.json"))
    reg = root / "projects.yaml"
    reg.write_text(projects or "{}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    return root


@needs_git
def test_the_clone_is_config_s_engine_clone_else_the_registry_s(clones, tmp_path, monkeypatch):
    root = brain_with(tmp_path, monkeypatch, {"repo": "ada/engine", "pin": "v1.0.0", "clone": "../clone"})
    assert engineclone.find(root) == clones.clone.resolve()
    # no engine.clone: the registry's checkout whose origin is engine.repo
    git(clones.clone, "remote", "set-url", "origin", "https://github.com/ada/engine.git")
    lab = f"lab:\n  root: .\n  repos: ['.', {{path: '{clones.clone.as_posix()}'}}]\n"
    root = brain_with(tmp_path, monkeypatch, {"repo": "Ada/Engine", "pin": "v1.0.0"}, lab)
    assert engineclone.find(root) == clones.clone.resolve()
    root = brain_with(tmp_path, monkeypatch, {"repo": "ada/other", "pin": "v1.0.0"}, lab)
    assert engineclone.find(root) is None
    root = brain_with(tmp_path, monkeypatch, {"repo": "ada/engine", "pin": "v1.0.0", "clone": "../missing"})
    assert engineclone.find(root) is None and engineclone.refresh(root).said() == ""


@needs_git
def test_refresh_pulls_it_unless_offline_or_no_clone(clones, tmp_path, monkeypatch, capsys):
    root = brain_with(tmp_path, monkeypatch, {"repo": "ada/engine", "pin": "v1.0.0", "clone": str(clones.clone)})
    for flags in ({"offline": True, "no_clone": False}, {"offline": False, "no_clone": True}):
        refresh._clone(SimpleNamespace(**flags), root)
        assert capsys.readouterr().out == "" and git(clones.clone, "rev-parse", "HEAD") == clones.first
    refresh._clone(SimpleNamespace(offline=False, no_clone=False), root)
    assert "main fast-forwarded" in capsys.readouterr().out
    assert git(clones.clone, "rev-parse", "HEAD") == clones.last
