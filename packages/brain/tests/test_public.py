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


# --- the stamp's key (wi-brain-public-stamp-binding) ---

def _stamp_head(pub, monkeypatch, gitleaks=False):
    monkeypatch.setattr(public, "gitleaks_exe", lambda: "gitleaks" if gitleaks else None)
    monkeypatch.setattr(public, "gitleaks_history", lambda repo, rev: [] if gitleaks else None)
    assert cli.main(["check", "--public", "--repo", str(pub), "--history"]) == 0
    return run_git(pub, "rev-parse", "HEAD").strip()


def test_a_fresh_stamp_carries_its_key_and_passes(pub, monkeypatch):
    head = _stamp_head(pub, monkeypatch)
    data = json.loads(public.stamp_path("acme/engine", head).read_text(encoding="utf-8"))
    assert data["v"] == public.STAMP_V == 2
    assert data["key"] == public.stamp_key(config.load(), False)
    assert set(data["key"]) == {"engine", "rules", "gitleaks"} and len(data["key"]["rules"]) == 64
    assert public.stamp_refusal("acme/engine", head, config.load()) == ""
    assert not _push(pub)


def test_a_stamp_from_another_engine_version_is_refused(pub, monkeypatch):
    import brain
    _stamp_head(pub, monkeypatch)
    monkeypatch.setattr(brain, "__version__", "9.9.9")
    (reason,) = [r for _, r in _push(pub)]
    assert "was stamped by brain " in reason and "not this brain 9.9.9" in reason
    assert "rerun brain check --public --history" in reason


def test_a_stamp_under_other_deny_rules_is_refused(pub, monkeypatch):
    _stamp_head(pub, monkeypatch)
    cfg_file = Path(os.environ["BRAIN_CONFIG"])
    changed = json.loads(json.dumps(PUBLIC))
    changed["public"]["deny"]["hosts"].append("box2")
    cfg_file.write_text(json.dumps(changed), encoding="utf-8")
    (reason,) = [r for _, r in _push(pub)]
    assert "stamped under other rules" in reason and "rerun brain check --public --history" in reason
    # the same rules written another way are the same rules
    cfg_file.write_text(json.dumps(PUBLIC, indent=2, sort_keys=True), encoding="utf-8")
    assert not _push(pub)
    # a change to allow, patterns or refuse counts too
    for key, value in (("allow", {"NOTICE": "x"}), ("patterns", {"p": "x"}), ("refuse", {"x/**": "x"})):
        other = json.loads(json.dumps(PUBLIC))
        other["public"][key] = {**other["public"][key], **value}
        cfg_file.write_text(json.dumps(other), encoding="utf-8")
        assert _push(pub), key


def test_a_stamp_with_or_without_gitleaks_is_refused_when_that_changed(pub, monkeypatch):
    _stamp_head(pub, monkeypatch, gitleaks=False)
    monkeypatch.setattr(public, "gitleaks_exe", lambda: "gitleaks")
    (reason,) = [r for _, r in _push(pub)]
    assert "stamped without gitleaks, which is now on the PATH" in reason
    _stamp_head(pub, monkeypatch, gitleaks=True)
    assert not _push(pub)
    monkeypatch.setattr(public, "gitleaks_exe", lambda: None)
    (reason,) = [r for _, r in _push(pub)]
    assert "stamped with gitleaks, which is no longer on the PATH" in reason


def test_no_commit_to_read_keys_gitleaks_by_its_presence(pub, monkeypatch):
    head = run_git(pub, "rev-parse", "HEAD").strip()
    run_git(pub, "update-ref", "refs/remotes/origin/main", head)  # nothing left to push but HEAD itself
    for there in (False, True):
        monkeypatch.setattr(public, "gitleaks_exe", lambda there=there: "gitleaks" if there else None)
        data = public.check(pub, history=True)
        assert data["commits"] == 0 and data["gitleaks"] is there
        public.stamp(data, config.load())
        assert public.stamp_refusal("acme/engine", head, config.load()) == ""


def test_an_old_format_or_unreadable_stamp_is_refused_with_the_fix(pub, monkeypatch):
    head = run_git(pub, "rev-parse", "HEAD").strip()
    f = public.stamp_path("acme/engine", head)
    f.parent.mkdir(parents=True)
    # what brain 0.2.5 wrote: no v, no key
    f.write_text(json.dumps({"at": "2026-11-01T10:00:00Z", "commits": 1, "files": 3, "gitleaks": False,
                             "remote": "origin", "repo": str(pub)}) + "\n", encoding="utf-8")
    assert public.stamped("acme/engine", head)
    (reason,) = [r for _, r in _push(pub)]
    assert "a stamp of an older format (no ruleset key)" in reason
    assert "rerun brain check --public --history" in reason
    for text in ("{not json", "[1, 2]", '{"v": 2, "key": "x"}', '{"v": 3, "key": {}}', "\xff"):
        f.write_bytes(text.encode("latin-1"))
        (reason,) = [r for _, r in _push(pub)]
        assert "rerun brain check --public --history" in reason, text
    _stamp_head(pub, monkeypatch)
    assert not _push(pub)


def test_gitleaks_on_the_path_but_failing_stamps_nothing(pub, monkeypatch, capsys):
    """A stamp made without gitleaks while it is on the PATH would be refused at every push: the check says so."""
    monkeypatch.setattr(public, "gitleaks_exe", lambda: "gitleaks")
    monkeypatch.setattr(public, "gitleaks_history", lambda repo, rev: None)  # it ran and failed
    assert cli.main(["check", "--public", "--repo", str(pub), "--history"]) == 1
    out = capsys.readouterr().out
    assert "gitleaks is on the PATH but failed" in out and "refused: gitleaks failed, nothing is stamped" in out
    head = run_git(pub, "rev-parse", "HEAD").strip()
    assert not public.stamped("acme/engine", head)


def test_a_newer_or_pathological_stamp_is_refused_never_raised(pub):
    head = run_git(pub, "rev-parse", "HEAD").strip()
    f = public.stamp_path("acme/engine", head)
    f.parent.mkdir(parents=True)
    f.write_text(json.dumps({"v": 3, "key": {}}), encoding="utf-8")
    assert "written by a newer brain (v 3" in public.stamp_refusal("acme/engine", head, config.load())
    f.write_text("[" * 200000 + "]" * 200000, encoding="utf-8")  # json.loads raises RecursionError
    assert "unreadable stamp" in public.stamp_refusal("acme/engine", head, config.load())
    (reason,) = [r for _, r in _push(pub)]
    assert "rerun brain check --public --history" in reason


# --- the stamps refreshed after an engine change (wi-brain-public-stamp-refresh) ---

@pytest.fixture
def registry(pub, tmp_path, monkeypatch, make_repo):
    """Ada's registry: her brain spans the public engine's checkout, a second checkout of it with uncommitted work, a
    third with a finding, and a private repo; gitleaks off."""
    dirty = make_repo("engine-dirty", {"README.md": "# engine\n"})
    run_git(dirty, "remote", "add", "origin", "git@github.com:acme/engine.git")
    (dirty / "README.md").write_text("# engine, changed\n", encoding="utf-8")
    leak = make_repo("engine-leak", {"src/a.py": "# written on box1\n"})
    run_git(leak, "remote", "add", "origin", "https://github.com/acme/engine")
    private = make_repo("ada-private", {"notes.md": "Ada's notes\n"})
    run_git(private, "remote", "add", "origin", "https://github.com/ada/ada-private.git")
    reg = tmp_path / "ada-brain" / "projects.yaml"
    reg.write_text("ada:\n  root: .\n  repos: [., ../engine, ../engine-dirty, ../engine-leak, ../ada-private,"
                   " ../missing]\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    monkeypatch.setattr(public, "gitleaks_exe", lambda: None)
    return {"clean": pub, "dirty": dirty, "leak": leak, "private": private}


def test_the_public_checkouts_are_the_registrys_repos_with_a_public_remote(registry):
    found, notes = public.checkouts(config.load())
    assert [(p.name, slug) for p, slug in found] == [("engine", "acme/engine"), ("engine-dirty", "acme/engine"),
                                                    ("engine-leak", "acme/engine")]
    assert not notes


def test_refresh_stamps_the_clean_checkouts_and_names_the_others(registry, capsys):
    head = run_git(registry["clean"], "rev-parse", "HEAD").strip()
    assert cli.main(["check", "--public", "--refresh"]) == 1   # the leaking checkout is refused
    out = capsys.readouterr().out
    assert f"stamped  acme/engine {registry['clean']}: HEAD {head[:8]}" in out
    assert public.stamp_refusal("acme/engine", head, config.load()) == ""
    assert f"skip     acme/engine {registry['dirty']}: 1 tracked file(s) not committed" in out
    assert f"refused  acme/engine {registry['leak']}: 1 finding(s)" in out
    assert "ada-private" not in out
    leak_head = run_git(registry["leak"], "rev-parse", "HEAD").strip()
    dirty_head = run_git(registry["dirty"], "rev-parse", "HEAD").strip()
    assert not public.stamped("acme/engine", leak_head) and not public.stamped("acme/engine", dirty_head)


def test_refresh_leaves_a_valid_stamp_and_redoes_one_of_another_engine(registry, monkeypatch, capsys):
    """The case it exists for: after an engine change the push guard refuses the old engine's stamps; the refresh run
    by the new engine stamps HEAD again, and a second run has nothing to do."""
    import brain

    run_git(registry["leak"], "remote", "set-url", "origin", "https://github.com/ada/scratch.git")   # not public now
    assert cli.main(["check", "--public", "--refresh"]) == 0
    capsys.readouterr()
    assert cli.main(["check", "--public", "--refresh"]) == 0
    assert capsys.readouterr().out.count("same     acme/engine") == 1
    monkeypatch.setattr(brain, "__version__", "9.9.9")   # the new engine
    head = run_git(registry["clean"], "rev-parse", "HEAD").strip()
    assert "not this brain 9.9.9" in public.stamp_refusal("acme/engine", head, config.load())
    assert _push(registry["clean"])
    assert cli.main(["check", "--public", "--refresh"]) == 0
    assert capsys.readouterr().out.count("stamped  acme/engine") == 1
    assert public.stamp_refusal("acme/engine", head, config.load()) == "" and not _push(registry["clean"])


def test_refresh_without_public_repos_or_checkouts_says_so(pub, tmp_path, monkeypatch):
    reg = tmp_path / "ada-brain" / "projects.yaml"
    reg.write_text("ada:\n  root: .\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    code, lines = public.refresh()
    assert code == 0 and lines == ["stamps   no local checkout of acme/engine in the registry"]
    cfg = tmp_path / "ada-brain" / config.FILE
    cfg.write_text(json.dumps({**PUBLIC, "public": {"deny": PUBLIC["public"]["deny"]}}), encoding="utf-8")
    assert public.refresh() == (0, ["stamps   config.json public.repos lists no public repo: nothing to refresh"])


def test_a_bad_repos_entry_is_noted_never_raised(pub, tmp_path, monkeypatch):
    reg = tmp_path / "ada-brain" / "projects.yaml"
    reg.write_text("ada:\n  root: .\n  repos: [{name: x}]\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    code, lines = public.refresh()
    assert code == 0 and lines[0].startswith("stamps   note: project ada:") and "not refreshed" in lines[0]


def test_one_checkout_git_cannot_read_never_stops_the_others(registry, monkeypatch):
    """A timeout (or a broken index) in one checkout is that checkout's failed line; the others are still refreshed;
    a checkout with no commit is skipped; a malformed public.repos reads as none (brain update's plan never raises)."""
    real = public.dirty

    def dirty(repo):
        if repo.name == "engine-dirty":
            raise subprocess.TimeoutExpired(["git", "status"], 60)
        return real(repo)

    monkeypatch.setattr(public, "dirty", dirty)
    code, lines = public.refresh()
    assert code == 1
    assert any(ln.startswith("failed   acme/engine") and "TimeoutExpired" in ln for ln in lines)
    assert any(ln.startswith("stamped  acme/engine") for ln in lines)
    (registry["clean"] / ".git" / "refs" / "heads" / "main").unlink()   # no commit on its branch any more
    assert any(ln.startswith("skip") and "no commit yet" in ln for ln in public.refresh()[1])
    assert public.public_repos(config.Config(None, Path("."), {"public": {"repos": True}})) == []


INSTALLER = Path(__file__).resolve().parents[1] / "installer" / "install.ps1"


def test_the_installer_refreshes_the_stamps_after_the_command_and_never_fails_on_them():
    text = INSTALLER.read_text(encoding="utf-8-sig")
    step = text[text.index("function Update-Stamps {"):text.index("# --- end of the stamps step ---")]
    assert "Invoke-Brain check --public --refresh" in step and "throw" not in step
    assert "$script:brain_code -eq 2" in step   # an older command only says so
    assert "if ($repo -and -not $SkipCommand) { Update-Stamps }" in text
    assert text.index("if ($repo) { Set-Schedules }") < text.index("Update-Stamps }")
