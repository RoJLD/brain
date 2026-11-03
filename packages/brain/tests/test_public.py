"""brain check --public and the public guard (wi-brain-public-boundary-check, brain.public, brain.guards)."""

import io
import json
import os
import subprocess
from pathlib import Path

import pytest

from brain import boundary, cli, config, guards, public

from conftest import run_git

PUBLIC = {"v": 1, "identity": {"owner": "Ada"},
          "public": {"repos": ["acme/engine"],
                     "deny": {"people": ["Ada"], "hosts": ["box1"], "repos": ["ada-private"], "paths": ["D:/work"]},
                     "allow": {"LICENSE": "the licence keeps its author's name"},
                     "patterns": {"venue": "(?i)venue_[a-z]+_price"},
                     "refuse": {"research/**": "the research IP stays in the private split"}}}


@pytest.fixture
def pub(tmp_path, monkeypatch, make_repo):
    """A clean engine checkout whose origin is the public repo acme/engine, and Ada's config.json beside it."""
    cfg = tmp_path / "ada-brain" / config.FILE
    cfg.parent.mkdir()
    cfg.write_text(json.dumps(PUBLIC), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(cfg))
    repo = make_repo("engine", {"README.md": "# engine\n\nA graph engine, by its maintainers.\n",
                                "LICENSE": "MIT License\n\nCopyright (c) 2026 Ada\n",
                                "src/engine/core.py": "def run():\n    return 1\n"})
    run_git(repo, "remote", "add", "origin", "https://github.com/acme/engine.git")
    return repo


def _push(repo, command="git push origin main"):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(repo)}
    return [(g, reason) for g, _, reason, _ in guards.refusals(payload) if g == "public"]


def test_repo_slug():
    for url in ("https://github.com/acme/engine.git", "https://github.com/acme/engine", "git@github.com:acme/engine.git",
                "ssh://git@github.com/acme/engine", "https://x@github.com/acme/engine.git/"):
        assert public.repo_slug(url) == "acme/engine", url
    assert public.repo_slug("https://gitlab.com/acme/engine.git") == "" and public.repo_slug("") == ""


def test_a_clean_repo_is_green_and_stamped_with_its_history(pub, capsys):
    assert cli.main(["check", "--public", "--repo", str(pub)]) == 0
    out = capsys.readouterr().out
    assert "acme/engine" in out and "denied 0, secret 0, pattern 0, file 0, domain 0" in out
    assert "green: the tree only; --history checks the commits" in out
    head = run_git(pub, "rev-parse", "HEAD").strip()
    assert not public.stamped("acme/engine", head)
    assert cli.main(["check", "--public", "--repo", str(pub), "--history"]) == 0
    out = capsys.readouterr().out
    assert "1 commit(s) not on origin" in out and "green: stamped" in out
    assert public.stamped("acme/engine", head) and public.stamped("ACME/Engine", head)
    stamp = json.loads(public.stamp_path("acme/engine", head).read_text(encoding="utf-8"))
    assert stamp["commits"] == 1 and stamp["remote"] == "origin"


def test_every_check_finds_its_case(pub, make_repo):
    make_repo.commit(pub, {
        "src/engine/a.py": "# written on box1 for Ada\nPATH = 'D:\\work\\engine'\n",
        "src/engine/b.py": "KEY = 'sk-ant-" + "a" * 30 + "'\nTOKEN = 'sk-ant-" + "b" * 30 + "'  # gitleaks:allow\n"
                           "token_env: ENGINE_TELEGRAM_TOKEN_NAME, chat_id_env: ENGINE_CHAT\n",
        "docs/c.md": "Mail ada.lovelace@gmail.com, not noreply@github.com nor t@example.invalid.\n"  # public-check:allow
                     "Home: /home/ada and C:\\Users\\ada\\x, not /home/runner nor C:\\Users\\<you>.\n"  # public-check:allow
                     "Allowed here: /Users/someone_else  <!-- public-check:allow -->\n",
        "src/engine/cols.py": "COLUMNS = ['venue_yes_price']\n",
        "data/ticks.csv": "a,b\n1,2\n", "tests/fixtures/table.csv": "a,b\n", "x/heirs.yaml": "heirs: []\n",
        "keys/deploy.pem": "x\n", "research/alpha.md": "notes\n", "store/cache.parquet": "PAR1",
        "library/paper.pdf": "%PDF-1.7", "library/book.epub": "PK",
        "notes/ada-private.md": "see ada-private\n"})
    data = public.check(pub)
    got = {(f["check"], f["path"], f["line"]) for f in data["findings"]}
    assert ("denied", "src/engine/a.py", 1) in got and ("denied", "src/engine/a.py", 2) in got  # Ada, box1, D:/work
    assert ("denied", "notes/ada-private.md", 1) in got  # a private repo's name
    assert ("denied", "LICENSE", 3) not in got  # public.allow
    assert ("secret", "src/engine/b.py", 1) in got and ("secret", "src/engine/b.py", 2) not in got
    assert ("secret", "src/engine/b.py", 3) not in got  # a variable's name, not a key
    patterns = [f["what"] for f in data["findings"] if f["check"] == "pattern"]
    assert any("ada.lovelace@gmail.com" in w for w in patterns)  # public-check:allow
    assert not any("noreply" in w for w in patterns)
    assert any("/home/ada" in w for w in patterns) and any("Users\\ada" in w for w in patterns)  # public-check:allow
    assert not any("runner" in w or "someone_else" in w or "example.invalid" in w for w in patterns)
    files = {f["path"]: f["what"] for f in data["findings"] if f["check"] == "file"}
    assert set(files) == {"data/ticks.csv", "x/heirs.yaml", "keys/deploy.pem", "store/cache.parquet",
                          "library/paper.pdf", "library/book.epub"}
    assert ("domain", "src/engine/cols.py", 1) in got and ("domain", "research/alpha.md", 0) in got
    assert data["counts"]["denied"] >= 4 and all(data["counts"][c] for c in public.CHECKS)


def test_history_finds_what_a_later_commit_took_out(pub, make_repo, capsys):
    make_repo.commit(pub, {"src/engine/core.py": "def run():\n    return 1  # box1\n"})
    make_repo.commit(pub, {"src/engine/core.py": "def run():\n    return 1\n"})
    assert public.check(pub)["findings"] == []
    data = public.check(pub, history=True)
    assert data["commits"] == 3 and [(f["check"], f["path"]) for f in data["findings"]] == [
        ("denied", "src/engine/core.py")]
    assert data["findings"][0]["commit"] and data["findings"][0]["line"] == 2
    assert cli.main(["check", "--public", "--repo", str(pub), "--history"]) == 1
    out = capsys.readouterr().out
    assert "src/engine/core.py:2: denied: hosts term 'box1'" in out and "nothing is stamped" in out


def test_history_stops_at_what_the_remote_has(pub, make_repo):
    head = run_git(pub, "rev-parse", "HEAD").strip()
    make_repo.commit(pub, {"src/engine/core.py": "def run():\n    return 2\n"})
    run_git(pub, "update-ref", "refs/remotes/origin/main", head)  # the remote has the first commit
    assert public.check(pub, history=True)["commits"] == 1


def test_history_reads_the_messages_and_the_authors_addresses(pub, make_repo):
    """A commit message is published with its commit: a denied term there fails; so does an author's own e-mail
    address, while a no-reply one passes and a name is the owner's to sign with."""
    (pub / "NOTES.md").write_text("notes\n", encoding="utf-8")
    env = dict(os.environ, GIT_AUTHOR_NAME="Ada", GIT_AUTHOR_EMAIL="ada@mail.acme.org",  # public-check:allow
               GIT_COMMITTER_NAME="Ada",
               GIT_COMMITTER_EMAIL="1+ada@users.noreply.github.com")
    for args in (["add", "-A"], ["commit", "-q", "-m", "notes: written on box1\n\nNothing else."]):
        subprocess.run(["git", "-C", str(pub), *args], check=True, capture_output=True, env=env)
    found = [(f["check"], f["path"], f["line"]) for f in public.check(pub, history=True)["findings"]]
    assert found == [("denied", "<message>", 1), ("pattern", "<author>", 0)]
    assert public.check(pub)["findings"] == []  # the tree alone holds nothing


def test_a_repo_outside_public_repos_is_checked_not_stamped(pub, capsys):
    run_git(pub, "remote", "set-url", "origin", "https://github.com/acme/other.git")
    assert cli.main(["check", "--public", "--repo", str(pub), "--history"]) == 0
    out = capsys.readouterr().out
    assert "is not in config.json public.repos" in out and "stamped" not in out.split("note:")[0]
    assert not list((Path(os.environ["BRAIN_HOME"]) / public.STAMPS).rglob("*"))


def test_json_and_not_a_checkout(pub, tmp_path, capsys):
    assert cli.main(["check", "--public", "--repo", str(pub), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["slug"] == "acme/engine" and data["counts"]["denied"] == 0 and data["stamp"] is None
    (tmp_path / "plain").mkdir()
    assert cli.main(["check", "--public", "--repo", str(tmp_path / "plain")]) == 2


def test_the_engine_side_dry_run(git_repo, monkeypatch):
    (git_repo / boundary.FILE).write_text(
        'v: 1\nrules:\n  - {glob: "src/**", side: engine, target: "packages/brain/src/"}\n'
        '  - {glob: "**", side: personal}\n', encoding="utf-8")
    (git_repo / "src").mkdir()
    (git_repo / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (git_repo / "src" / "b.py").write_text("# Ada's\n", encoding="utf-8")
    (git_repo / config.FILE).write_text(json.dumps(PUBLIC), encoding="utf-8")
    run_git(git_repo, "add", "-A")
    run_git(git_repo, "commit", "-q", "-m", "x")
    monkeypatch.setenv("BRAIN_CONFIG", str(git_repo / config.FILE))
    data = public.check(git_repo, engine=True, history=True)
    assert data["files"] == 2 and data["commits"] == 0  # the engine's files only, never its history
    assert [(f["check"], f["path"]) for f in data["findings"]] == [("denied", "src/b.py")]
    assert public.stamp(data) is None


# --- the guard on git push ---

def test_the_guard_refuses_a_push_until_the_check_stamps_head(pub):
    (reason,) = [r for _, r in _push(pub)]
    assert "acme/engine is a public repo" in reason and "brain check --public --history" in reason
    assert _push(pub, "git push") and _push(pub, f'git -C "{pub}" push -u origin HEAD:main')
    assert _push(pub, "git push https://github.com/acme/engine.git main")
    assert not _push(pub, "git push https://github.com/acme/other.git main")  # not a public repo
    assert not _push(pub, "git push origin --delete old")  # a deletion sends nothing
    assert not _push(pub, "git status && git log")
    assert cli.main(["check", "--public", "--repo", str(pub), "--history"]) == 0
    assert not _push(pub) and not _push(pub, "git push")


def test_the_guard_checks_every_commit_a_push_sends(pub, make_repo):
    assert cli.main(["check", "--public", "--repo", str(pub), "--history"]) == 0
    run_git(pub, "branch", "side")
    make_repo.commit(pub, {"src/engine/core.py": "def run():\n    return 3\n"})
    run_git(pub, "tag", "v1")
    assert _push(pub, "git push origin main")  # HEAD moved: no stamp yet
    assert not _push(pub, "git push origin side")  # side is the stamped commit
    assert _push(pub, "git push origin --tags") and _push(pub, "git push --all origin")


def test_the_guard_message_and_override(pub, monkeypatch, capsys):
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git push origin main"}, "cwd": str(pub)})
    out = io.StringIO()
    guards.main(io.StringIO(payload), out)
    reason = json.loads(out.getvalue())["hookSpecificOutput"]["permissionDecisionReason"]
    assert reason.startswith("brain-core guard: git push refused")
    assert "Override (Ada only): BRAIN_GUARD_ALLOW=public" in reason
    monkeypatch.setenv(guards.ALLOW_ENV, "public")
    out = io.StringIO()
    guards.main(io.StringIO(payload), out)
    assert out.getvalue() == ""


def test_no_public_repo_no_push_check(git_repo):
    run_git(git_repo, "remote", "add", "origin", "https://github.com/acme/engine.git")
    assert not _push(git_repo)  # the tests' brain (Ada's fixture) names no public repo
