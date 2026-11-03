"""wi-brain-tui-update-check (ADR UPD-1 to UPD-3): the engine's version check, cached 24 h and silent offline, and
brain update's plan, run on the owner's gesture only."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from brain import cli, update

NOW = 1_793_700_000.0  # 2026-11-03, a fixed clock
TAGS = ["v0.1.0", "v0.2.1", "v0.2.2", "v0.2.3"]
REMOTE_TAGS, CHANGELOG = update.remote_tags, update.changelog  # the real ones: conftest keeps the tests offline


def _fetch(tags=TAGS, calls=None):
    def fetch(repo):
        if calls is not None:
            calls.append(repo)
        return list(tags)
    return fetch


def _offline(repo):
    raise OSError("offline")


@pytest.fixture
def venv(brain_home):
    """A brain venv as install.ps1 lays it out: its interpreter and its launcher, Textual installed (the tui extra)."""
    scripts = brain_home / "venv" / ("Scripts" if update.WINDOWS else "bin")
    scripts.mkdir(parents=True)
    (scripts / ("python.exe" if update.WINDOWS else "python")).write_bytes(b"python")
    (scripts / "brain.exe").write_bytes(b"launcher v2")
    site = brain_home / "venv" / ("Lib/site-packages" if update.WINDOWS else "lib/python3.12/site-packages")
    (site / "textual-1.0.0.dist-info").mkdir(parents=True)
    return scripts


@pytest.fixture
def pinned(tmp_path, monkeypatch):
    """A personal brain whose config.json pins the engine at v0.2.2."""
    brain = tmp_path / "ada-brain"
    brain.mkdir()
    cfg = {"v": 1, "identity": {"owner": "Ada", "kind": "person"}, "engine": {"repo": "ada/engine", "pin": "v0.2.2"}}
    (brain / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(brain / "config.json"))
    return brain


def test_version_of_reads_release_tags_only():
    assert update.version_of("v0.2.10") == (0, 2, 10) and update.version_of("0.2.3") == (0, 2, 3)
    assert update.version_of("v0.3.0-rc1") is None and update.version_of("latest") is None
    assert update.version_of("v0.2.10") > update.version_of("v0.2.9")


def test_remote_tags_asks_no_credential(monkeypatch):
    seen = {}

    def runner(cmd, **kw):
        seen["cmd"], seen["env"], seen["stdin"] = cmd, kw["env"], kw["stdin"]
        out = "a\trefs/tags/v0.2.10\nb\trefs/tags/v0.2.9\nc\trefs/tags/v0.3.0-rc1\nd\trefs/tags/v0.1.0\n"
        return subprocess.CompletedProcess(cmd, 0, out, "")

    assert REMOTE_TAGS("ada/engine", runner) == ["v0.1.0", "v0.2.9", "v0.2.10"]
    assert seen["cmd"][:3] == ["git", "-c", "credential.helper="] and "https://github.com/ada/engine.git" in seen["cmd"]
    assert seen["env"]["GIT_TERMINAL_PROMPT"] == "0" and seen["stdin"] == subprocess.DEVNULL
    with pytest.raises(OSError):
        REMOTE_TAGS("ada/gone", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 128, "", "not found"))


def test_offline_is_silent(brain_home):
    info = update.check(fetch=_offline, now=NOW, installed="0.2.2")
    assert info["latest"] is None and not info["newer"] and info["source"] == "offline"
    assert update.title(info, "0.2.2") == "brain 0.2.2"
    assert not (brain_home / update.CACHE).exists()
    assert update.lines(update.plan(info))[0].endswith("could not be read (offline?); nothing to update")


def test_offline_keeps_the_last_answer(brain_home):
    update.check(fetch=_fetch(), now=NOW, installed="0.2.2")
    info = update.check(fetch=_offline, now=NOW + update.TTL_S + 1, installed="0.2.2")
    assert info["source"] == "offline" and info["latest"] == "0.2.3" and info["newer"]


def test_a_cache_hit_reads_nothing(brain_home):
    calls = []
    first = update.check(fetch=_fetch(calls=calls), now=NOW, installed="0.2.2")
    assert first["source"] == "remote" and calls == ["RoJLD/brain"]
    cached = json.loads((brain_home / update.CACHE).read_text(encoding="utf-8"))
    assert cached["repo"] == "RoJLD/brain" and cached["tags"] == TAGS
    again = update.check(fetch=_fetch(calls=calls), now=NOW + update.TTL_S - 60, installed="0.2.2")
    assert again["source"] == "cache" and again["latest"] == "0.2.3" and calls == ["RoJLD/brain"]
    later = update.check(fetch=_fetch(calls=calls), now=NOW + update.TTL_S + 1, installed="0.2.2")
    assert later["source"] == "remote" and len(calls) == 2  # a day later: read again
    update.check(fetch=_fetch(calls=calls), now=NOW + update.TTL_S + 2, installed="0.2.2", refresh=True)
    assert len(calls) == 3  # brain update --check reads now


def test_another_repo_is_not_a_cache_hit(brain_home, pinned):
    (brain_home).mkdir(parents=True, exist_ok=True)
    (brain_home / update.CACHE).write_text(json.dumps({"repo": "RoJLD/brain", "checked": "2026-11-03T08:00:00Z",
                                                       "tags": ["v9.9.9"]}), encoding="utf-8")
    calls = []
    info = update.check(fetch=_fetch(calls=calls), now=NOW, installed="0.2.2")
    assert calls == ["ada/engine"] and info["latest"] == "0.2.3"


def test_a_newer_tag(brain_home, venv):
    info = update.check(fetch=_fetch(), now=NOW, installed="0.2.2")
    assert info["newer"] and info["latest"] == "0.2.3"
    assert update.title(info, "0.2.2") == "brain 0.2.2 · 0.2.3 available"
    p = update.plan(info, read_changelog=lambda repo, tag, since: ["## 0.2.3 — 2026-11-05", "", "- A fix."])
    assert p["tag"] == "v0.2.3" and not p["blocked"]
    assert p["spec"] == "brain[tui] @ git+https://github.com/RoJLD/brain.git@v0.2.3#subdirectory=packages/brain"
    text = "\n".join(update.lines(p))
    assert "brain 0.2.2 installed; v0.2.3 is the latest tag of RoJLD/brain" in text
    assert "  ## 0.2.3 — 2026-11-05" in text and "install  brain v0.2.3 into" in text
    assert "restart  brain tui" in text and "pin " not in text
    if update.WINDOWS:
        assert p["launcher"] == [str(venv / "brain.exe"), str(brain_home / "bin" / "brain.exe")]


def test_up_to_date_has_no_plan(venv):
    info = update.check(fetch=_fetch(TAGS[:-1]), now=NOW, installed="0.2.2")
    p = update.plan(info, read_changelog=lambda *a: pytest.fail("no CHANGELOG read when up to date"))
    assert not info["newer"] and p["spec"] is None and p["blocked"]
    assert update.lines(p)[0].startswith("brain 0.2.2 is up to date (the latest tag of RoJLD/brain is v0.2.2")


def test_a_pinned_brain_shows_the_pin_to_move(venv, pinned):
    info = update.check(fetch=_fetch(), now=NOW, installed="0.2.2")
    p = update.plan(info, read_changelog=lambda *a: None)
    assert info["repo"] == "ada/engine" and "ada/engine.git@v0.2.3" in p["spec"]
    assert p["pin"] == {"file": str(pinned / "config.json"), "from": "v0.2.2", "to": "v0.2.3"}
    text = "\n".join(update.lines(p))
    assert "pin      config.json engine.pin v0.2.2 -> v0.2.3: move it by a reviewed PR" in text
    assert "the CHANGELOG at v0.2.3 could not be read" in text
    before = (pinned / "config.json").read_bytes()
    code, done = update.apply(p, runner=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "", ""))
    assert code == 0 and (pinned / "config.json").read_bytes() == before  # shown, never moved
    assert any(line.startswith("to do    move config.json engine.pin v0.2.2 -> v0.2.3") for line in done)


def test_an_editable_install_is_not_updated_by_pip(venv, monkeypatch, tmp_path):
    monkeypatch.setattr(update.paths, "installed_checkout", lambda: tmp_path / "engine-checkout")
    p = update.plan(update.check(fetch=_fetch(), now=NOW, installed="0.2.2"), read_changelog=lambda *a: [])
    assert p["spec"] is None and "installed editable from" in p["blocked"]
    assert update.apply(p, runner=lambda *a, **kw: pytest.fail("no pip"))[0] == 1


def test_apply_installs_then_swaps_the_launcher(brain_home, venv):
    p = update.plan(update.check(fetch=_fetch(), now=NOW, installed="0.2.2"), read_changelog=lambda *a: [])
    ran = []
    code, done = update.apply(p, runner=lambda cmd, **kw: ran.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", ""))
    assert code == 0 and ran == [[p["python"], "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                                  p["spec"]]]
    if update.WINDOWS:
        assert (brain_home / "bin" / "brain.exe").read_bytes() == b"launcher v2" and "copied" in done[1]
    failed = update.apply(p, runner=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "no network"))
    assert failed[0] == 1 and "failed with exit code 1" in failed[1][0]


def test_no_install_without_the_gesture(venv, monkeypatch, capsys):
    monkeypatch.setattr(update, "remote_tags", _fetch())
    monkeypatch.setattr(update, "changelog", lambda *a: ["## 0.2.3 — 2026-11-05"])
    monkeypatch.setattr(update, "check", lambda root=None, refresh=False, **kw: _check(root, refresh))
    applied = []
    monkeypatch.setattr(update, "apply", lambda p, runner=None: applied.append(p) or (0, ["installed"]))
    monkeypatch.delenv("CLAUDECODE", raising=False)
    assert cli.main(["update", "--check"]) == 0
    assert "The plan (brain update --yes" in capsys.readouterr().out and applied == []
    assert update.main(None, check_only=False, yes=False, as_json=False, ask=lambda q: "n", out=lambda s: None) == 0
    assert applied == []  # the owner said no
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert cli.main(["update"]) == 0 and applied == []  # no terminal to ask in: it says how, installs nothing
    assert "brain update --yes installs it" in capsys.readouterr().out
    monkeypatch.setenv("CLAUDECODE", "1")
    assert cli.main(["update", "--yes"]) == 1 and applied == []  # a Claude Code session never installs
    monkeypatch.delenv("CLAUDECODE")
    assert update.main(None, check_only=False, yes=False, as_json=False, ask=lambda q: "y", out=lambda s: None) == 0
    assert cli.main(["update", "--yes"]) == 0 and len(applied) == 2  # the owner's yes, the owner's --yes


_real_check = update.check


def _check(root, refresh):
    return _real_check(root, refresh=refresh, installed="0.2.2")


def test_update_check_json(venv, monkeypatch, capsys):
    monkeypatch.setattr(update, "remote_tags", _fetch())
    monkeypatch.setattr(update, "changelog", lambda *a: [])
    monkeypatch.setattr(update, "check", lambda root=None, refresh=False, **kw: _check(root, refresh))
    assert cli.main(["update", "--check", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["latest"] == "0.2.3" and data["tag"] == "v0.2.3" and data["pin"] is None


def test_changelog_reads_the_tags_file(monkeypatch):
    class Resp:
        def __init__(self, url):
            self.url = url

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return "## 0.2.3 — c\n\n- three\n\n## 0.2.2 — b\n".encode()
    seen = []
    got = CHANGELOG("ada/engine", "v0.2.3", "0.2.2", opener=lambda url, timeout: seen.append(url) or Resp(url))
    assert got == ["## 0.2.3 — c", "", "- three"]
    assert seen == ["https://raw.githubusercontent.com/ada/engine/v0.2.3/packages/brain/CHANGELOG.md"]
    assert CHANGELOG("ada/engine", "v0.2.3", "0.2.2", opener=lambda url, timeout: _offline(url)) is None


def test_sections_since_the_installed_version():
    text = ("# Changelog\n\n## Unreleased\n\n- next\n\n## 0.2.4 — d\n\n- four\n\n## 0.2.3 — c\n\n- three\n\n"
            "## 0.2.2 — b\n\n- two\n")
    assert update.sections(text, "0.2.2", "0.2.4") == ["## 0.2.4 — d", "", "- four", "", "## 0.2.3 — c", "",
                                                       "- three"]
    assert update.sections(text, "0.2.3", "0.2.3") == []


def test_set_launcher_same_then_copied(tmp_path):
    src, dst = tmp_path / "venv-brain.exe", tmp_path / "bin" / "brain.exe"
    src.write_bytes(b"launcher v2")
    assert update.set_launcher(src, dst) == "copied" and dst.read_bytes() == b"launcher v2"
    assert update.set_launcher(src, dst) == "same"
    assert not (dst.parent / "brain.exe.new").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="a running image is locked on Windows only")
def test_set_launcher_swaps_a_running_image(tmp_path):
    src, dst = tmp_path / "venv-brain.exe", tmp_path / "brain.exe"
    src.write_bytes(b"launcher v2")
    shutil.copy(Path(r"C:\Windows\System32\PING.EXE"), dst)  # a real image, locked while it runs
    running = subprocess.Popen([str(dst), "-n", "30", "127.0.0.1"], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    try:
        assert update.set_launcher(src, dst) == "swapped"
        assert dst.read_bytes() == b"launcher v2" and len(list(tmp_path.glob("brain.exe.old-*"))) == 1
    finally:
        running.kill()
        running.wait()
    assert update.set_launcher(src, dst) == "same" and not list(tmp_path.glob("brain.exe.old-*"))
