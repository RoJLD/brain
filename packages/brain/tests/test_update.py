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


def test_a_pinned_brain_shows_the_pin_to_move(venv, installer_brain):
    """A brain that declares its own installer (an install.ps1) keeps the reviewed pin PR (COMPAT-5)."""
    pinned = installer_brain
    info = update.check(fetch=_fetch(), now=NOW, installed="0.2.2")
    p = update.plan(info, read_changelog=lambda *a: None)
    assert info["repo"] == "ada/engine" and "ada/engine.git@v0.2.3" in p["spec"]
    assert p["pin"] == {"file": str(pinned / "config.json"), "from": "v0.2.2", "to": "v0.2.3", "move": "pr"}
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


# --- wi-brain-tui-apply-reload (INST-1): the installed engine against the brain's pin, and its declared installer ---

@pytest.fixture
def installer_brain(pinned):
    """Ada's pinned brain (v0.2.2) declaring its own installer, config.json engine.installer."""
    cfg = json.loads((pinned / "config.json").read_text(encoding="utf-8"))
    cfg["engine"]["installer"] = "install.ps1"
    (pinned / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    (pinned / "install.ps1").write_text("'the plan'\n", encoding="utf-8")
    return pinned


def test_lag_behind_equal_and_ahead_of_the_pin():
    assert update.lag("0.2.1", "v0.2.3") == "behind"  # a pin PR merged, -Apply not run yet
    assert update.lag("0.2.3", "v0.2.3") == "equal"
    assert update.lag("0.2.4", "v0.2.3") == "ahead"  # brain update past the pin, or a branch's engine
    assert update.lag("0.2.10", "v0.2.9") == "ahead"  # compared as versions, not as text
    assert update.lag("0.2.3", None) is None and update.lag("0.2.3+dev", "v0.2.3") is None


def test_pinned_reads_the_installer_the_brain_declares(installer_brain):
    info = update.pinned(installed="0.2.1")
    assert info == {"pin": "v0.2.2", "lag": "behind", "installer": "install.ps1", "root": str(installer_brain)}
    assert update.installer() == installer_brain / "install.ps1"
    (installer_brain / "install.ps1").unlink()  # declared but missing: none (brain config --check says so)
    assert update.pinned(installed="0.2.1")["installer"] is None


def test_the_title_says_the_pin_to_apply(installer_brain):
    behind = update.check(fetch=_fetch(TAGS[:-1]), now=NOW, installed="0.2.1")  # latest v0.2.2, the pin
    assert update.applies(behind) and behind["installer"] == "install.ps1"
    assert update.title(behind, "0.2.1") == "brain 0.2.1 · pin v0.2.2: -Apply"  # the pin's tag is not « available »
    past = update.check(fetch=_fetch(), now=NOW, installed="0.2.1", refresh=True)  # v0.2.3 is out, past the pin
    assert update.title(past, "0.2.1") == "brain 0.2.1 · pin v0.2.2: -Apply · 0.2.3 available"
    equal = update.check(fetch=_fetch(), now=NOW, installed="0.2.2")
    assert not update.applies(equal) and update.title(equal, "0.2.2") == "brain 0.2.2 · 0.2.3 available"
    ahead = update.check(fetch=_fetch(), now=NOW, installed="0.2.3")
    assert ahead["lag"] == "ahead" and update.title(ahead, "0.2.3") == "brain 0.2.3"
    offline = update.check(fetch=_offline, now=NOW + 2 * update.TTL_S, installed="0.2.1")
    assert update.title(offline, "0.2.1").startswith("brain 0.2.1 · pin v0.2.2: -Apply")  # no network needed


def test_a_brain_without_an_installer_keeps_brain_update(pinned):
    """The tester's brain (from brain init): pinned, no installer of its own, so brain update stays the path."""
    info = update.check(fetch=_fetch(), now=NOW, installed="0.2.1")
    assert info["lag"] == "behind" and info["installer"] is None and not update.applies(info)
    assert update.title(info, "0.2.1") == "brain 0.2.1 · 0.2.3 available"


def test_config_check_reports_a_missing_installer(installer_brain):
    from brain import config
    assert config.check() == []
    (installer_brain / "install.ps1").unlink()
    assert config.check() == ["config.json: engine.installer 'install.ps1' does not exist"]


# --- wi-brain-update-moves-pin (COMPAT-5): a brain without an installer of its own has its pin moved by brain update ---

@pytest.fixture
def pin_repo(pinned, monkeypatch):
    """Ada's pinned brain (v0.2.2, no installer of its own) as a git repo, config.json committed and indented."""
    from conftest import GIT_ENV, git_init, run_git
    if not shutil.which("git"):
        pytest.skip("git not available")
    for k, v in GIT_ENV.items():
        monkeypatch.setenv(k, v)
    cfg = {"v": 1, "identity": {"owner": "Ada", "kind": "person"}, "engine": {"repo": "ada/engine", "pin": "v0.2.2"}}
    (pinned / "config.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    git_init(pinned)
    run_git(pinned, "add", "config.json")
    run_git(pinned, "commit", "-q", "-m", "init")
    return pinned


def _runner(ran, sync_code=0):
    """git runs for real; pip and brain sync are recorded (brain sync exits ``sync_code``)."""
    def run(cmd, **kw):
        if cmd[0] == "git":
            return subprocess.run(cmd, **kw)
        ran.append(cmd)
        return subprocess.CompletedProcess(cmd, sync_code if cmd[1:4] == ["-m", "brain", "--root"] else 0, "", "")
    return run


def _pin(root):
    return json.loads((root / "config.json").read_text(encoding="utf-8"))["engine"]["pin"]


def _venv_has(version):
    """The brain venv holds brain at ``version`` (its dist-info), as pip leaves it."""
    py = update.venv_python()
    if py.is_file():
        for d in update._site_packages(py):
            if d.is_dir():
                for old in d.glob("brain-*.dist-info"):
                    old.rmdir()
                (d / f"brain-{version}.dist-info").mkdir()


def _plan(installed, tags=TAGS, venv_has=None):
    _venv_has(venv_has or installed)
    return update.plan(update.check(fetch=_fetch(tags), now=NOW, installed=installed, refresh=True),
                       read_changelog=lambda *a: [])


def test_without_an_installer_the_plan_writes_the_pin(venv, pin_repo):
    from conftest import run_git
    p = _plan("0.2.2")
    assert p["pin"] == {"file": str(pin_repo / "config.json"), "from": "v0.2.2", "to": "v0.2.3", "move": "write"}
    text = "\n".join(update.lines(p))
    assert "pin      config.json engine.pin v0.2.2 -> v0.2.3: written and committed in" in text
    assert "sync     brain sync in" in text and "reviewed PR" not in text
    ran = []
    code, done = update.apply(p, runner=_runner(ran))
    assert code == 0, done
    assert ran[0][1:4] == ["-m", "pip", "install"]  # the install first, then the pin
    assert ran[1] == [p["python"], "-m", "brain", "--root", str(pin_repo), "sync"]  # with the new engine
    assert _pin(pin_repo) == "v0.2.3"
    assert run_git(pin_repo, "log", "-1", "--format=%s").strip() == "brain update: engine.pin v0.2.2 -> v0.2.3"
    assert run_git(pin_repo, "status", "--porcelain") == ""  # committed, nothing left behind (no .bak in the repo)
    text = (pin_repo / "config.json").read_text(encoding="utf-8")
    assert text.startswith('{\n  "v": 1,\n  "identity"') and text.endswith("}\n")  # its order and indent kept
    assert any(line.startswith("synced   brain sync in") for line in done)


def test_the_pin_moves_alone_when_the_engine_is_already_the_latest(venv, pin_repo):
    """An update made before this one installed v0.2.3 and left the pin behind: no install, the pin moves."""
    p = _plan("0.2.3")
    assert p["spec"] is None and update.pin_writes(p) and update.runs(p)
    assert "The plan (brain update --yes" in "\n".join(update.lines(p))
    ran = []
    code, done = update.apply(p, runner=_runner(ran))
    assert code == 0 and _pin(pin_repo) == "v0.2.3" and [c[1:3] for c in ran] == [["-m", "brain"]]  # no pip


def test_the_pin_is_never_moved_backwards_nor_off_a_tag(venv, pin_repo):
    behind = _plan("0.2.1", TAGS[:2])  # the latest tag, v0.2.1, is below the pin v0.2.2
    assert behind["pin"]["move"] == "pr" and not update.runs(behind)
    cfg = json.loads((pin_repo / "config.json").read_text(encoding="utf-8"))
    cfg["engine"]["pin"] = "main"
    (pin_repo / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    assert _plan("0.2.2")["pin"]["move"] == "pr"


def test_an_editable_install_never_moves_the_pin(venv, pin_repo, monkeypatch, tmp_path):
    monkeypatch.setattr(update.paths, "installed_checkout", lambda: tmp_path / "engine-checkout")
    for installed in ("0.2.2", "0.2.3"):
        p = _plan(installed)
        assert p["pin"]["move"] == "pr" and not update.runs(p)


def test_a_declared_installer_keeps_the_pr_even_when_its_file_is_missing(venv, installer_brain):
    (installer_brain / "install.ps1").unlink()
    p = _plan("0.2.2")
    assert p["pin"]["move"] == "pr" and not update.pin_writes(p)


def test_a_config_with_changes_not_committed_is_left_alone(venv, pin_repo):
    p = _plan("0.2.2")
    f = pin_repo / "config.json"
    f.write_text(f.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    before = f.read_bytes()
    ran = []
    code, done = update.apply(p, runner=_runner(ran))
    assert code == 1 and f.read_bytes() == before
    assert any("has changes not committed (commit them, then brain update again): nothing written" in line for line in done)
    assert len(ran) == 1  # installed, but no brain sync


def test_a_brain_that_is_not_a_git_repo_is_left_alone(venv, pinned, monkeypatch):
    if not shutil.which("git"):
        pytest.skip("git not available")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(pinned.parent))  # no repo above the brain's folder
    p = _plan("0.2.3")
    code, done = update.apply(p, runner=_runner([]))
    assert code == 1 and "is not a git repo (or git cannot run): nothing written" in done[0] and _pin(pinned) == "v0.2.2"


def test_a_failed_sync_is_reported(venv, pin_repo):
    code, done = update.apply(_plan("0.2.3"), runner=_runner([], sync_code=1))
    assert code == 1 and _pin(pin_repo) == "v0.2.3" and "brain sync failed with exit code 1" in done[-1]


def test_a_pin_moved_since_the_plan_is_not_overwritten(pin_repo):
    with pytest.raises(ValueError, match="no longer v0.2.1"):
        update.write_pin(pin_repo / "config.json", "v0.2.1", "v0.2.3")
    assert _pin(pin_repo) == "v0.2.2"


def _fixed_check(installed):
    return lambda root=None, refresh=False, **kw: _real_check(root, refresh=refresh, installed=installed,
                                                               fetch=_fetch())


def test_the_pin_moves_on_the_owners_yes_only_never_from_a_session(venv, pin_repo, monkeypatch, capsys):
    monkeypatch.setattr(update, "check", _fixed_check("0.2.3"))
    _venv_has("0.2.3")
    moved = []
    monkeypatch.setattr(update, "apply", lambda p, runner=None: moved.append(p) or (0, ["moved"]))
    asked = []
    assert update.main(None, check_only=False, yes=False, as_json=False,
                       ask=lambda q: asked.append(q) or "n", out=lambda s: None) == 0
    assert moved == [] and asked == ["Move engine.pin to v0.2.3, commit it and run brain sync now? [y/N] "]
    monkeypatch.setenv("CLAUDECODE", "1")
    assert cli.main(["update", "--yes"]) == 1 and moved == []  # a Claude Code session never moves it
    assert "run it yourself in a terminal" in capsys.readouterr().out and _pin(pin_repo) == "v0.2.2"
    monkeypatch.delenv("CLAUDECODE")
    assert cli.main(["update", "--yes"]) == 0 and len(moved) == 1  # the owner's --yes


def test_the_question_names_the_pin_with_the_install(venv, pin_repo, monkeypatch):
    monkeypatch.setattr(update, "check", _fixed_check("0.2.2"))
    asked = []
    update.main(None, check_only=False, yes=False, as_json=False, ask=lambda q: asked.append(q) or "n",
                out=lambda s: None)
    assert asked == ["Install brain v0.2.3, move engine.pin to v0.2.3, commit it and run brain sync now? [y/N] "]


def test_write_pin_keeps_the_line_endings_and_the_bom(tmp_path):
    """A config.json Windows PowerShell 5.1 wrote: a BOM, CRLF, four spaces; only the pin changes."""
    f = tmp_path / "config.json"
    body = '{\r\n    "engine": {\r\n        "pin": "v0.2.2",\r\n        "repo": "ada/engine"\r\n    },\r\n    "v": 1\r\n}\r\n'
    f.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
    update.write_pin(f, "v0.2.2", "v0.2.3")
    assert f.read_bytes() == b"\xef\xbb\xbf" + body.replace("v0.2.2", "v0.2.3").encode("utf-8")


def test_an_untracked_config_is_left_alone(venv, pin_repo):
    from conftest import run_git
    run_git(pin_repo, "rm", "-q", "--cached", "config.json")
    run_git(pin_repo, "commit", "-q", "-m", "untrack")
    (pin_repo / ".git" / "info" / "exclude").write_text("config.json\n", encoding="utf-8")  # ignored: status is clean
    code, done = update.apply(_plan("0.2.3"), runner=_runner([]))
    assert code == 1 and "is not tracked in" in done[0] and _pin(pin_repo) == "v0.2.2"


def test_the_pin_alone_follows_the_venvs_engine_not_the_running_one(venv, pin_repo):
    """A brain run from another interpreter (a checkout's venv) at the latest tag, the brain's venv still at the pin:
    the pin stays, since brain sync would run the venv's older engine against it."""
    p = _plan("0.2.3", venv_has="0.2.2")
    assert p["pin"]["move"] == "pr" and not update.runs(p)
    assert _plan("0.2.3")["pin"]["move"] == "write"


def test_a_detached_head_is_left_alone(venv, pin_repo):
    from conftest import run_git
    run_git(pin_repo, "checkout", "-q", "--detach")
    code, done = update.apply(_plan("0.2.3"), runner=_runner([]))
    assert code == 1 and "a detached HEAD" in done[0] and _pin(pin_repo) == "v0.2.2"


def test_git_missing_is_said_not_raised(venv, pin_repo):
    def run(cmd, **kw):
        if cmd[0] == "git":
            raise FileNotFoundError("git")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    code, done = update.apply(_plan("0.2.2"), runner=run)
    assert code == 1 and done[0].startswith("installed brain v0.2.3")
    assert any("git cannot run" in line for line in done) and _pin(pin_repo) == "v0.2.2"


# --- wi-brain-release-signing (STD-3): the tag verified before it is installed, refused only under verify_tags ---

COMMIT = "c0ffee" * 6 + "abcd"


def _verdict(status, signer="ada"):
    from brain import tagsig

    def verify(root, repo, tag):
        return tagsig.verdict(status, tag, signer=signer if status == tagsig.VERIFIED else "", commit=COMMIT,
                              why="" if status == tagsig.VERIFIED else f"{tag} carries no signature",
                              source="allowed_signers")
    return verify


def _verify_tags(root, on=True):
    f = root / "config.json"
    data = json.loads(f.read_text(encoding="utf-8"))
    data["engine"]["verify_tags"] = on
    f.write_text(json.dumps(data), encoding="utf-8")


def _signed_plan(status, **kw):
    info = update.check(fetch=_fetch(), now=NOW, installed="0.2.2")
    return update.plan(info, read_changelog=lambda *a: [], verify=_verdict(status), **kw)


def test_a_verified_tag_is_installed_by_its_commit(venv, pinned):
    p = _signed_plan("verified")
    assert p["signature"]["status"] == "verified" and not p["blocked"]
    assert p["spec"] == f"brain[tui] @ git+https://github.com/ada/engine.git@{COMMIT}#subdirectory=packages/brain"
    text = "\n".join(update.lines(p))
    assert f"verify   v0.2.3: signed by ada (allowed_signers), commit {COMMIT[:12]}" in text


def test_an_unsigned_tag_is_said_and_installed_while_verify_tags_is_off(venv, pinned):
    p = _signed_plan("unsigned")
    assert p["verify_tags"] is False and not p["blocked"] and p["spec"].endswith("@v0.2.3#subdirectory=packages/brain")
    assert "verify   v0.2.3: not verified, v0.2.3 carries no signature (not refused: config.json engine.verify_tags " \
           "is off)" in "\n".join(update.lines(p))


def test_verify_tags_refuses_an_unsigned_tag_before_any_install(venv, pinned):
    _verify_tags(pinned)
    for status in ("unsigned", "unknown-key", "unverifiable", "no-signers"):
        p = _signed_plan(status)
        assert p["spec"] is None and p["blocked"].startswith("refused: v0.2.3: not verified"), status
        assert "Not applicable here: refused" in "\n".join(update.lines(p))
        assert p["pin"] is None   # never moved to a refused tag
        assert update.apply(p, runner=lambda *a, **kw: pytest.fail("no pip"))[0] == 1
    assert _signed_plan("verified")["spec"].endswith(f"@{COMMIT}#subdirectory=packages/brain")


def test_without_signers_the_plan_reads_no_network(venv, pinned):
    """The default verification: no allowed_signers and no releaser in members.yaml, so nothing is fetched."""
    from brain import tagsig
    info = update.check(fetch=_fetch(), now=NOW, installed="0.2.2")
    p = update.plan(info, read_changelog=lambda *a: [])
    assert p["signature"]["status"] == tagsig.NO_SIGNERS and p["spec"].endswith("@v0.2.3#subdirectory=packages/brain")


def test_a_verification_that_raises_is_a_verdict(venv, pinned):
    def boom(*a):
        raise RuntimeError("broken")
    p = update.plan(update.check(fetch=_fetch(), now=NOW, installed="0.2.2"), read_changelog=lambda *a: [],
                    verify=boom)
    assert p["signature"]["status"] == "unverifiable" and "RuntimeError" in p["signature"]["why"]


def _research_graph_from(commit):
    site = update._site_packages(update.venv_python())[0 if update.WINDOWS else 1]
    d = site / "research_graph-0.2.3.dist-info"
    d.mkdir(parents=True, exist_ok=True)
    (d / "direct_url.json").write_text(json.dumps({"url": "https://github.com/ada/engine.git",
                                                   "vcs_info": {"vcs": "git", "commit_id": commit}}),
                                        encoding="utf-8")


def test_a_tag_moved_during_the_install_is_said_and_refused_under_verify_tags(brain_home, venv, installer_brain):
    def ok(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, "", "")
    _research_graph_from(COMMIT)
    code, done = update.apply(_signed_plan("verified"), runner=ok)
    assert code == 0 and not any(line.startswith("warning") for line in done), done
    _research_graph_from("bad" * 13 + "b")
    code, done = update.apply(_signed_plan("verified"), runner=ok)
    assert code == 0 and any(line.startswith("warning  research-graph was installed from commit badbad") for line in done)
    _verify_tags(installer_brain)
    if update.WINDOWS:
        (brain_home / "bin" / "brain.exe").unlink(missing_ok=True)
    code, done = update.apply(_signed_plan("verified"), runner=ok)
    assert code == 1 and done[-1].startswith("refused  the launcher and the pin are left as they were")
    assert not (brain_home / "bin" / "brain.exe").exists()
