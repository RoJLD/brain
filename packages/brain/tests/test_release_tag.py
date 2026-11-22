"""brain release tag vX.Y.Z (wi-brain-release-tag-command; docs/release.md, « 3. The tag »): the signed release tag in
one owner gesture, on a throwaway engine repo and its bare remote, signed with a test key made in the test (never an
owner's). Each step stops the rest when it fails and says which; the command refuses an agent's session."""

import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_tagsig import KEYGEN, allowed, make_key

from brain import cli, gestures, releasetag

needs_ssh = pytest.mark.skipif(not KEYGEN or not shutil.which("git"), reason="ssh-keygen (OpenSSH 8.2+) or git missing")
THEME = "Small things, done once"
FAKE_BRAIN = '''import os, sys
with open(os.environ["FAKE_BRAIN_LOG"], "a", encoding="utf-8") as fh:
    fh.write(" ".join(sys.argv[1:]) + "\\n")
fail = os.environ.get("FAKE_BRAIN_FAIL", "")
if fail and fail in sys.argv:
    print("public check: 1 finding", flush=True)
    sys.exit(1)
print("public check: clean")
'''


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def write(repo: Path, rel: str, text: str) -> None:
    f = repo / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")


def versions(repo: Path, v: str, theme: str | None = None) -> None:
    write(repo, releasetag.INIT, f'__version__ = "{v}"\n')
    write(repo, releasetag.RG_INIT, f'__version__ = "{v}"\n')
    head = f"## {v} — 2026-11-22 — {theme}\n\n### Added\n\n- x\n\n" if theme else ""
    write(repo, releasetag.CHANGELOG, f"# Changelog\n\n{head}## 1.1.0 — 2026-11-01 — Before\n")


@pytest.fixture
def engine(tmp_path, monkeypatch):
    """A bare remote and its engine clone whose main ends at the merge of the version PR of 1.2.0, the clone on a
    feature branch, git set to sign with the test's releaser key; the planning brain's allowed_signers; a fake
    brain for the public checks: SimpleNamespace(repo, remote, planning, log, brain, key, other)."""
    empty = tmp_path / "gitconfig"
    empty.write_text("[user]\n\tname = Ada\n\temail = ada@example.com\n[commit]\n\tgpgsign = false\n"
                     "[init]\n\tdefaultBranch = main\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for var in (*gestures.MARKER_NAMES, "CLAUDE_BRAIN_DIR", "BRAIN_PERSONAL"):
        monkeypatch.delenv(var, raising=False)
    keys = tmp_path / "keys"
    keys.mkdir()
    key, pub = make_key(keys, "releaser")
    other, _ = make_key(keys, "other")
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--quiet", "--bare", str(remote))
    repo = tmp_path / "engine"
    git(tmp_path, "clone", "--quiet", str(remote), str(repo))
    git(repo, "config", "gpg.format", "ssh")
    git(repo, "config", "user.signingkey", key.as_posix())
    git(repo, "config", "gpg.ssh.program", Path(KEYGEN).as_posix())
    versions(repo, "1.1.0")
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "1.1.0")
    git(repo, "switch", "--quiet", "-c", "chore/release-1.2.0")
    versions(repo, "1.2.0", THEME)
    git(repo, "commit", "--quiet", "-am", "Release 1.2.0")
    git(repo, "switch", "--quiet", "main")
    git(repo, "merge", "--quiet", "--no-ff", "chore/release-1.2.0", "-m",
        f"Merge pull request #9 from ada/chore/release-1.2.0\n\nRelease 1.2.0: {THEME}")
    git(repo, "push", "--quiet", "origin", "main")
    git(repo, "switch", "--quiet", "-c", "feat/next")
    planning = tmp_path / "planning"
    planning.mkdir()
    (planning / "config.json").write_text(json.dumps({"v": 1, "identity": {"owner": "Ada"}}), encoding="utf-8")
    (planning / "allowed_signers").write_text(allowed(pub), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(planning / "config.json"))
    fake = tmp_path / "fake_brain.py"
    fake.write_text(FAKE_BRAIN, encoding="utf-8")
    log = tmp_path / "brain.log"
    monkeypatch.setenv("FAKE_BRAIN_LOG", str(log))
    monkeypatch.delenv("FAKE_BRAIN_FAIL", raising=False)
    return SimpleNamespace(repo=repo, remote=remote, planning=planning, log=log, brain=[sys.executable, str(fake)],
                           key=key, other=other)


def args(e, tag="v1.2.0", **kw):
    base = dict(tag=tag, repo=str(e.repo), planning=str(e.planning), root=None, branch="main", remote="origin",
                yes=True, json=False)
    return SimpleNamespace(**{**base, **kw})


def run(e, capsys, refused="", **kw):
    code = releasetag.main(args(e, **kw), brain=e.brain, refused=refused)
    return code, capsys.readouterr().out


def on_remote(e, tag="v1.2.0") -> str:
    return git(e.remote, "tag", "--list", tag)


@needs_ssh
def test_the_tag_is_signed_verified_and_pushed(engine, capsys):
    code, out = run(engine, capsys)
    assert code == 0, out
    assert git(engine.repo, "branch", "--show-current") == "main"
    assert on_remote(engine) == "v1.2.0"
    assert git(engine.remote, "rev-parse", "v1.2.0^{commit}") == git(engine.repo, "rev-parse", "main")
    assert git(engine.remote, "cat-file", "tag", "v1.2.0").rstrip().splitlines()[5] == \
        f"brain 1.2.0 and research-graph 1.2.0 — {THEME}"
    for step in releasetag.STEPS:
        assert f"\n{step:<9}" in out, step
    assert "verify   done   signed by ada" in out
    checks = engine.log.read_text(encoding="utf-8").splitlines()
    assert [c.split()[-1] for c in checks] == ["--history", "--private-text"]
    assert all(c.startswith(f"check --public --repo {engine.repo}") for c in checks)
    assert "next     brain release status 1.2.0" in out


@needs_ssh
def test_an_agent_session_is_refused_after_the_plan(engine, capsys, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    code = cli.main(["release", "tag", "v1.2.0", "--repo", str(engine.repo), "--planning", str(engine.planning),
                     "--yes"])
    out = capsys.readouterr().out
    assert code == 1
    assert "sign     git tag -s v1.2.0" in out and "not from a Claude Code session's shell (CLAUDECODE is set)" in out
    assert git(engine.repo, "branch", "--show-current") == "feat/next"   # nothing ran: not even the switch
    assert not git(engine.repo, "tag", "--list") and not on_remote(engine)
    assert not engine.log.exists()


@needs_ssh
def test_a_tracked_change_stops_it_before_the_switch(engine, capsys):
    write(engine.repo, releasetag.CHANGELOG, "edited\n")
    code, out = run(engine, capsys)
    assert code == 1
    assert "switch   failed tracked files have changes" in out and "pull     not run" not in out
    assert "stopped  at switch" in out
    assert git(engine.repo, "branch", "--show-current") == "feat/next"
    assert (engine.repo / releasetag.CHANGELOG).read_text(encoding="utf-8") == "edited\n"   # nothing stashed


@needs_ssh
def test_a_head_past_the_version_merge_is_refused(engine, capsys):
    git(engine.repo, "switch", "--quiet", "main")
    write(engine.repo, "late.txt", "a PR merged after the version PR\n")
    git(engine.repo, "add", "late.txt")
    git(engine.repo, "commit", "--quiet", "-m", "Merge pull request #10 from ada/feat/late")
    git(engine.repo, "push", "--quiet", "origin", "main")
    code, out = run(engine, capsys)
    assert code == 1
    assert "merge    failed HEAD" in out and "does not name « release » and 1.2.0" in out
    assert not git(engine.repo, "tag", "--list") and not engine.log.exists()


@needs_ssh
def test_a_version_that_is_not_the_checkouts_is_refused(engine, capsys):
    code, out = run(engine, capsys, tag="v1.3.0")
    assert code == 1 and "merge    failed" in out and "1.3.0" in out


@needs_ssh
def test_a_tag_on_the_remote_is_never_moved(engine, capsys):
    git(engine.repo, "tag", "v1.2.0", "main~1")
    git(engine.repo, "push", "--quiet", "origin", "v1.2.0")
    git(engine.repo, "tag", "-d", "v1.2.0")
    code, out = run(engine, capsys)
    assert code == 1
    assert "free     failed v1.2.0 is on origin already: a pushed tag is never moved" in out


@needs_ssh
def test_a_public_check_that_fails_stops_it_before_the_tag(engine, capsys, monkeypatch):
    monkeypatch.setenv("FAKE_BRAIN_FAIL", "--private-text")
    code, out = run(engine, capsys)
    assert code == 1
    assert "public   done" in out and "private  failed brain check --public --private-text (exit 1)" in out
    assert "sign     not run" not in out and "stopped  at private" in out
    assert not git(engine.repo, "tag", "--list") and not on_remote(engine)


@needs_ssh
def test_a_key_outside_the_allowed_signers_is_not_pushed(engine, capsys):
    git(engine.repo, "config", "user.signingkey", engine.other.as_posix())
    code, out = run(engine, capsys)
    assert code == 1
    assert "verify   failed v1.2.0: not verified" in out and "git tag -d v1.2.0" in out
    assert git(engine.repo, "tag", "--list") == "v1.2.0" and not on_remote(engine)   # local only, said


@needs_ssh
def test_no_allowed_signers_is_refused_before_the_push(engine, capsys):
    (engine.planning / "allowed_signers").unlink()
    code, out = run(engine, capsys)
    assert code == 1 and "verify   failed no releaser key to verify with" in out and not on_remote(engine)


@needs_ssh
def test_a_failed_push_resumes_on_the_next_run(engine, capsys):
    def no_push(argv, *a, **kw):
        if "push" in argv:
            return subprocess.CompletedProcess(argv, 128, "", "could not reach the remote")
        return subprocess.run(argv, *a, **kw)
    code = releasetag.main(args(engine), brain=engine.brain, refused="", runner=no_push)
    out = capsys.readouterr().out
    assert code == 1 and "push     failed git push origin v1.2.0 failed (exit 128)" in out and not on_remote(engine)
    code, out = run(engine, capsys)
    assert code == 0, out
    assert "sign     same   v1.2.0 is here already, at HEAD" in out and on_remote(engine) == "v1.2.0"


@needs_ssh
def test_a_local_tag_elsewhere_is_said_not_moved(engine, capsys):
    git(engine.repo, "tag", "v1.2.0", "main~1")
    code, out = run(engine, capsys)
    assert code == 1 and "sign     failed a local v1.2.0 names" in out and "git tag -d v1.2.0" in out


@needs_ssh
def test_the_plan_runs_nothing_without_a_yes(engine, capsys):
    code = releasetag.main(args(engine, yes=False), brain=engine.brain, refused="", ask=lambda q: "n")
    out = capsys.readouterr().out
    assert code == 0 and "nothing tagged" in out and "switch   git switch main (on feat/next now)" in out
    code = releasetag.main(args(engine, json=True), brain=engine.brain, refused="")
    plan = json.loads(capsys.readouterr().out)
    assert plan["tag"] == "v1.2.0" and plan["version"] == "1.2.0" and len(plan["lines"]) == len(releasetag.STEPS)
    assert git(engine.repo, "branch", "--show-current") == "feat/next" and not engine.log.exists()


def test_a_tag_that_is_not_a_release_is_refused(tmp_path, capsys):
    ns = SimpleNamespace(tag="1.2.0", repo=str(tmp_path), planning=str(tmp_path), root=None, branch="main",
                         remote="origin", yes=True, json=False)
    assert releasetag.main(ns, refused="") == 2
    assert "a release tag vX.Y.Z" in capsys.readouterr().err


@pytest.mark.parametrize("text, version, named", [
    ("Merge pull request #9 from ada/chore/release-1.2.0\nRelease 1.2.0: x", "1.2.0", True),
    ("Release v1.2.0 (#9)", "1.2.0", True),
    ("Merge pull request #9 from ada/chore/release-1.2.0", "1.2.0", True),
    ("Release 1.2.10", "1.2.1", False),
    ("Bump 1.2.0 deps", "1.2.0", False),
])
def test_names_release(text, version, named):
    assert releasetag.names_release(text, version) is named


def test_the_heading_gives_the_theme():
    text = "# C\n\n## 1.2.0 — 2026-11-22 — Small things\n\n## 1.1.0 - 2026-11-01 - Before\n"
    assert releasetag.heading(text, "1.2.0") == "Small things"
    assert releasetag.heading(text, "1.1.0") == "Before"
    assert releasetag.heading(text, "1.3.0") == ""
