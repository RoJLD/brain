"""brain release tag vX.Y.Z (wi-brain-release-tag-command; docs/release.md, « 3. The tag »): the signed release tag in
one owner gesture, on a throwaway engine repo and its bare remote, signed with a test key made in the test (never an
owner's). Each step stops the rest when it fails and says which; the command refuses an agent's session."""

import json
import re
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
    elsewhere = tmp_path / "elsewhere"   # $BRAIN_CONFIG names another brain, with no releaser: --planning wins
    elsewhere.mkdir()
    (elsewhere / "config.json").write_text(json.dumps({"v": 1}), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(elsewhere / "config.json"))
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


def ran(out: str, step: str) -> bool:
    """Whether the step's outcome was said (its plan line aside)."""
    return any(ln.startswith(f"{step:<9}{o}") for ln in out.splitlines() for o in ("done", "same", "failed"))


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
    assert all(c.startswith(f"check --public --repo {engine.repo} --remote origin") for c in checks)
    pushed = git(engine.remote, "rev-parse", "refs/tags/v1.2.0")   # the tag object verified, not a lightweight ref
    assert git(engine.remote, "cat-file", "-t", pushed) == "tag" and pushed == git(engine.repo, "rev-parse", "v1.2.0")
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
    assert "switch   failed tracked files have changes" in out and not ran(out, "pull")
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
    assert "merge    failed HEAD" in out and "does not name release-1.2.0" in out
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
    assert not ran(out, "sign") and "stopped  at private" in out
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


@needs_ssh
def test_a_later_pr_that_names_the_release_is_not_the_version_merge(engine, capsys):
    git(engine.repo, "switch", "--quiet", "main")
    git(engine.repo, "switch", "--quiet", "-c", "fix/release-1.2.0-docs")
    write(engine.repo, "late.txt", "a fix merged after the version PR\n")
    git(engine.repo, "add", "late.txt")
    git(engine.repo, "commit", "--quiet", "-m", "docs")
    git(engine.repo, "switch", "--quiet", "main")
    git(engine.repo, "merge", "--quiet", "--no-ff", "fix/release-1.2.0-docs", "-m",
        "Merge pull request #11 from ada/fix/release-1.2.0-docs")
    git(engine.repo, "push", "--quiet", "origin", "main")
    code, out = run(engine, capsys)
    assert code == 1 and "is after the version PR's merge: its first parent is at 1.2.0 already" in out
    assert not git(engine.repo, "tag", "--list")


@needs_ssh
@pytest.mark.parametrize("breaks, said", [
    (lambda r: write(r, releasetag.RG_INIT, '__version__ = "1.1.0"\n'), "__version__ is 1.1.0, not 1.2.0"),
    (lambda r: write(r, releasetag.CHANGELOG, "# Changelog\n\n## 1.1.0 — 2026-11-01 — Before\n"),
     "has no heading « ## 1.2.0 — date — theme »"),
])
def test_the_version_merge_must_carry_both_versions_and_the_heading(engine, capsys, breaks, said):
    git(engine.repo, "switch", "--quiet", "chore/release-1.2.0")
    breaks(engine.repo)
    git(engine.repo, "commit", "--quiet", "-am", "Release 1.2.0, amended")
    git(engine.repo, "switch", "--quiet", "main")
    git(engine.repo, "reset", "--quiet", "--hard", "HEAD~1")
    git(engine.repo, "merge", "--quiet", "--no-ff", "chore/release-1.2.0", "-m",
        f"Merge pull request #9 from ada/chore/release-1.2.0\n\nRelease 1.2.0: {THEME}")
    git(engine.repo, "push", "--quiet", "--force", "origin", "main")   # the test's own throwaway remote
    code, out = run(engine, capsys)
    assert code == 1 and "merge    failed" in out and said in out and not git(engine.repo, "tag", "--list")


@needs_ssh
def test_a_main_that_diverged_stops_at_the_pull(engine, capsys):
    git(engine.repo, "switch", "--quiet", "main")
    write(engine.repo, "local.txt", "a commit of its own\n")
    git(engine.repo, "add", "local.txt")
    git(engine.repo, "commit", "--quiet", "-m", "local")
    other = engine.repo.parent / "other"
    git(engine.repo.parent, "clone", "--quiet", str(engine.remote), str(other))
    write(other, "remote.txt", "x\n")
    git(other, "add", "remote.txt")
    git(other, "commit", "--quiet", "-m", "remote")
    git(other, "push", "--quiet", "origin", "main")
    code, out = run(engine, capsys)
    assert code == 1 and "pull     failed git pull --ff-only origin main" in out and not ran(out, "free")


@needs_ssh
@pytest.mark.parametrize("fails, said", [
    ("ls-remote", "free     failed git ls-remote origin could not read its tags"),
    ("timeout", "free     failed git ls-remote origin could not read its tags: git could not run (TimeoutExpired"),
])
def test_a_remote_that_cannot_be_read_stops_before_the_tag(engine, capsys, fails, said):
    def runner(argv, *a, **kw):
        if "ls-remote" in argv:
            if fails == "timeout":
                raise subprocess.TimeoutExpired(argv, 1)
            return subprocess.CompletedProcess(argv, 128, "", "fatal: could not read from remote repository")
        return subprocess.run(argv, *a, **kw)
    code = releasetag.main(args(engine), brain=engine.brain, refused="", runner=runner)
    out = capsys.readouterr().out
    assert code == 1 and said in out and not git(engine.repo, "tag", "--list")


@needs_ssh
def test_a_warning_on_stderr_is_not_a_tag_on_the_remote(engine, capsys):
    def runner(argv, *a, **kw):
        if "ls-remote" in argv:
            return subprocess.CompletedProcess(argv, 0, "", "Warning: Permanently added 'host' to the known hosts.")
        return subprocess.run(argv, *a, **kw)
    code = releasetag.main(args(engine), brain=engine.brain, refused="", runner=runner)
    assert code == 0, capsys.readouterr().out
    assert on_remote(engine) == "v1.2.0"


@needs_ssh
def test_a_tag_moved_after_its_verification_is_not_pushed(engine, capsys, monkeypatch):
    real = releasetag._push

    def push(p, ctx):   # another hand moves the local tag between verify and push
        git(engine.repo, "tag", "-f", "-a", "v1.2.0", "-m", "moved", "main~1")
        return real(p, ctx)
    monkeypatch.setitem(releasetag.RUN, "push", push)
    code = releasetag.main(args(engine), brain=engine.brain, refused="")
    out = capsys.readouterr().out
    assert code == 1 and "push     failed v1.2.0 moved after it was verified" in out and not on_remote(engine)


@needs_ssh
def test_the_planning_brain_named_is_read_not_brain_config(engine, capsys, monkeypatch):
    monkeypatch.setenv("BRAIN_CONFIG", str(engine.planning / "config.json"))   # the releaser's brain
    elsewhere = engine.planning.parent / "elsewhere"
    code, out = run(engine, capsys, planning=str(elsewhere))   # names a brain without a releaser
    assert code == 1 and "verify   failed no releaser key to verify with" in out and not on_remote(engine)


@needs_ssh
def test_no_terminal_and_no_yes_runs_nothing_and_fails(engine, capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", open(__file__, encoding="utf-8"))   # not a tty
    code = releasetag.main(args(engine, yes=False), brain=engine.brain, refused="")
    sys.stdin.close()
    out = capsys.readouterr().out
    assert code == 1 and "no terminal to answer y; --yes runs it (nothing tagged)" in out
    assert git(engine.repo, "branch", "--show-current") == "feat/next"


@needs_ssh
def test_the_json_plan_in_an_agent_session_is_refused_too(engine, capsys):
    code = releasetag.main(args(engine, json=True), brain=engine.brain, refused="not here")
    assert code == 1 and json.loads(capsys.readouterr().out)["tag"] == "v1.2.0"


def test_the_commands_it_runs_and_its_docs_pass_the_real_parser(tmp_path):
    parser = cli.build_parser()
    p = releasetag.TagPlan(repo=tmp_path, tag="v1.2.0", version="1.2.0", remote="upstream")
    for flag in ("--history", "--private-text"):
        ns = parser.parse_args(releasetag.check_argv(p, flag))
        assert ns.public and ns.remote == "upstream" and ns.repo == str(tmp_path)
    doc = (Path(__file__).resolve().parents[3] / "docs" / "release.md").read_text(encoding="utf-8")
    lines = {ln.split("#")[0].strip().strip("`") for ln in doc.splitlines() if "brain release tag v" in ln}
    lines |= {"brain release tag vX.Y.Z --branch release/X.Y", "brain release tag v1.2.0 --json"}
    for line in lines:
        for found in re.findall(r"brain release tag vX\.Y\.Z[^`;,)]*|brain release tag v[\d.]+[^`;,)]*", line):
            ns = parser.parse_args(found.split()[1:])
            assert ns.release_cmd == "tag", found


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
    ("Merge pull request #11 from ada/fix/release-status-1.2.0", "1.2.0", False),
    ("Release notes for 1.2.0", "1.2.0", False),
])
def test_names_release(text, version, named):
    assert releasetag.names_release(text, version) is named


def test_the_heading_gives_the_theme():
    text = "# C\n\n## 1.2.0 — 2026-11-22 — Small things\n\n## 1.1.0 - 2026-11-01 - Before\n"
    assert releasetag.heading(text, "1.2.0") == "Small things"
    assert releasetag.heading(text, "1.1.0") == "Before"
    assert releasetag.heading(text, "1.3.0") == ""
