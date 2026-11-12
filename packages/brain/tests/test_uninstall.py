"""wi-brain-uninstall-purge: brain uninstall [--purge] [--confirm-recovery ...] [--apply]: every trace the store
registry knows, a plan first; the stores nothing else keeps held until their recovery copy is confirmed."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from brain import classes, cli, config, keystore, paths, schedule, uninstall


class FakePath:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeSystem:
    label = "fake"

    def __init__(self):
        self.deleted = []

    def where(self, name):
        return f"\\Brain\\{name}"

    def delete(self, name):
        self.deleted.append(name)
        return ""


def _claude(listed=True, fail=None):
    """A fake claude CLI: (runner, calls). ``listed``: the plugin and marketplace are installed."""
    calls = []

    def run(argv):
        calls.append(argv[1:])
        if argv[-1] == "--json":
            rows = [{"id": "brain-core@brain", "name": "brain"}] if listed else []
            return subprocess.CompletedProcess(argv, 0, json.dumps(rows), "")
        bad = fail and fail in argv
        return subprocess.CompletedProcess(argv, 1 if bad else 0, "", "boom: not removed\n" if bad else "")
    return run, calls


def _home(*names, files=()):
    """BRAIN_HOME (the conftest's temporary one) with these folders and files."""
    home = paths.brain_home()
    home.mkdir(parents=True, exist_ok=True)
    for n in names:
        (home / n).mkdir(parents=True, exist_ok=True)
        (home / n / "x.txt").write_text("x", encoding="utf-8")
    for n in files:
        (home / n).parent.mkdir(parents=True, exist_ok=True)
        (home / n).write_text("{}", encoding="utf-8")
    return home


def _plan(purge=False, confirmed=(), **kw):
    kw.setdefault("claude", "")
    kw.setdefault("user_path", FakePath(""))
    kw.setdefault("keystore_backend", keystore.Memory())
    return uninstall.plan(config.load(), purge, set(confirmed), **kw)


def _by(steps):
    return {(s.kind, s.name): s.action for s in steps}


def test_without_purge_the_install_goes_and_the_data_stays():
    home = _home("venv", "bin", "engine", "venvs", "ledger", "cache", "vault", files=("tui.json",))
    steps = _plan()
    by = _by(steps)
    assert by[("store", "venv")] == by[("store", "bin")] == by[("store", "engine-clones")] == "remove"
    assert ("store", "ledger") not in by and ("store", "cache") not in by   # the data: only with --purge
    assert by[("home", str(home))] == "keep" and by[("transcripts", str(paths.projects_dir()))] == "keep"
    uninstall.apply(steps)
    assert sorted(p.name for p in home.iterdir()) == ["cache", "ledger", "tui.json", "vault"]


def test_purge_removes_the_derived_and_holds_what_nothing_else_keeps():
    home = _home("ledger", "vault", "cache", "resume", "ipc", "mystery", files=("tui.json", "tui.json.bak"))
    by = _by(_plan(purge=True))
    assert by[("store", "cache")] == by[("store", "resume")] == "remove"   # derived: rebuilt from the rest
    for held in ("ledger", "vault", "ipc", "cockpit", "mystery"):   # truth-local, log, secret, and an unknown name
        assert by[("store", held)] == "held", held
    steps = _plan(purge=True)
    out = dict((s.name, o) for s, o in uninstall.apply(steps) if s.kind == "store")
    assert out == {"cache": "done", "resume": "done", "ledger": "", "vault": "", "ipc": "", "cockpit": "",
                   "mystery": ""}
    assert sorted(p.name for p in home.iterdir()) == ["ipc", "ledger", "mystery", "tui.json", "tui.json.bak",
                                                      "vault"]
    assert home.is_dir()   # not empty: BRAIN_HOME stays


def test_a_confirmed_recovery_releases_its_store_and_all_empties_brain_home():
    home = _home("ledger", "vault", "mystery", files=("tui.json",))
    by = _by(_plan(purge=True, confirmed={"ledger", "mystery"}))
    assert by[("store", "ledger")] == by[("store", "mystery")] == "remove" and by[("store", "vault")] == "held"
    ks = keystore.Memory()
    ks.set("device", "AGE-SECRET-KEY-TEST")
    steps = _plan(purge=True, confirmed={"all"}, keystore_backend=ks)
    assert _by(steps)[("keystore", "keystore")] == "remove"
    assert all(o in ("", "done") for _, o in uninstall.apply(steps))
    assert not home.exists() and ks.get("device") is None


def test_the_device_key_is_held_until_confirmed():
    ks = keystore.Memory()
    ks.set("device", "AGE-SECRET-KEY-TEST")
    steps = _plan(purge=True, keystore_backend=ks)
    step = next(s for s in steps if s.kind == "keystore")
    assert step.action == "held" and "--confirm-recovery keystore" in step.line and "AGE-SECRET" not in step.line
    uninstall.apply(steps)
    assert ks.get("device") == "AGE-SECRET-KEY-TEST"
    ks.delete("device")   # the memory keystore is the process's: leave it as found
    assert not [s for s in _plan(purge=True, keystore_backend=ks) if s.kind == "keystore"]


def test_the_plugin_goes_through_the_claude_cli_and_only_when_installed():
    run, calls = _claude()
    steps = [s for s in _plan(claude="claude.exe", run=run) if s.kind == "plugin"]
    assert [s.name for s in steps] == ["brain-core@brain", "brain"]   # the tests' brain has no adapters.claude
    assert all(o == "done" for _, o in uninstall.apply(steps))
    assert ["plugin", "uninstall", "brain-core@brain", "--scope", "user"] in calls
    assert ["plugin", "marketplace", "remove", "brain"] in calls
    run, _ = _claude(listed=False)
    assert not [s for s in _plan(claude="claude.exe", run=run) if s.kind == "plugin"]
    run, _ = _claude(fail="uninstall")
    out = [o for s, o in uninstall.apply(_plan(claude="claude.exe", run=run)) if s.kind == "plugin"]
    assert out == ["failed: boom: not removed", "done"]
    left = [s for s in _plan(claude="") if s.kind == "plugin"]   # no CLI: the commands to run by hand
    assert [s.action for s in left] == ["left", "left"] and "claude plugin uninstall brain-core@brain" in left[0].line


def test_the_launchers_folder_leaves_the_user_path_and_nothing_else_does():
    home = paths.brain_home()
    other = r"C:\Tools;%USERPROFILE%\bin"
    up = FakePath(f"{other};{home / 'bin'};{str(home / 'bin').upper()}\\")
    steps = uninstall.path_steps(home, up, windows=True)
    assert [s.action for s in steps] == ["remove"]
    uninstall.apply(steps)
    assert up.value == other
    assert uninstall.path_steps(home, up, windows=True) == []
    assert uninstall.path_steps(home, None, windows=True) == []   # under pytest: never the real registry


@pytest.mark.skipif(os.name == "nt", reason="the launcher's link is the POSIX install")
def test_the_launchers_link_goes_when_it_points_into_brain_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "h"))
    home = _home("venv")
    link = tmp_path / "h" / ".local" / "bin" / "brain"
    link.parent.mkdir(parents=True)
    link.symlink_to(home / "venv" / "x.txt")
    steps = uninstall.path_steps(home, windows=False)
    assert [s.action for s in steps] == ["remove"]
    uninstall.apply(steps)
    assert not link.is_symlink()
    link.symlink_to(tmp_path / "elsewhere")
    assert uninstall.path_steps(home, windows=False) == []


def test_the_schedules_this_machine_installed_are_removed(monkeypatch):
    fake = FakeSystem()
    monkeypatch.setattr(schedule, "system", lambda run=None, platform=None: fake)
    monkeypatch.setattr(schedule, "installed", lambda: {"alerts": {"where": "\\Brain\\alerts"}, "canary": {}})
    steps = [s for s in _plan(run=lambda argv: None) if s.kind == "schedule"]
    assert [(s.name, s.action) for s in steps] == [("alerts", "remove"), ("canary", "remove")]
    uninstall.apply(steps)
    assert fake.deleted == ["alerts", "canary"]
    # under pytest, the default runner never reaches the real scheduler
    assert [s.action for s in uninstall.schedule_steps()] == ["left", "left"]


def test_the_install_store_this_command_runs_from_is_left_with_its_command(monkeypatch):
    home = _home("venv")
    monkeypatch.setattr(sys, "prefix", str(home / "venv"))
    step = next(s for s in _plan() if s.name == "venv")
    assert step.action == "left" and "this command runs from it" in step.line and str(home / "venv") in step.line
    uninstall.apply([step])
    assert (home / "venv").is_dir()


def test_a_link_out_of_brain_home_has_only_its_link_removed(tmp_path):
    home = _home()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("k", encoding="utf-8")
    link = home / "cache"
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(outside), str(link))   # a junction needs no privilege
        else:
            link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("no link or junction here")
    uninstall.apply(_plan(purge=True))
    assert not (link.exists() or link.is_symlink()) and (outside / "keep.txt").is_file()
    assert uninstall.remove(outside, home).endswith("not removed")   # a folder outside BRAIN_HOME is refused


def test_every_install_store_of_the_registry_is_known_to_the_purge():
    """The purge's decision follows the registry's format classes: a store added there is planned, never skipped."""
    for name, k in classes.ENGINE_STORES.items():
        if k.path.startswith("$BRAIN_HOME/") and "/" not in k.path[len("$BRAIN_HOME/"):]:
            assert uninstall._store_of(k.path.split("/", 1)[1])[0] == name


def test_the_command_plans_refuses_an_unknown_name_and_applies_only_outside_a_session(monkeypatch, capsys):
    home = _home("cache", "ledger")
    assert cli.main(["uninstall", "--purge"]) == 0
    out = capsys.readouterr().out
    assert "remove   " in out and "held     " in out and "(plan only" in out and (home / "cache").is_dir()
    assert cli.main(["uninstall", "--purge", "--confirm-recovery", "nosuchstore"]) == 2
    assert "names no store here: nosuchstore" in capsys.readouterr().err
    monkeypatch.setenv("CLAUDECODE", "1")
    assert cli.main(["uninstall", "--purge", "--apply"]) == 2
    assert "--apply refused" in capsys.readouterr().err and (home / "cache").is_dir()
    monkeypatch.delenv("CLAUDECODE")
    assert cli.main(["uninstall", "--purge", "--apply", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["applied"] and {s["name"]: s["outcome"] for s in doc["steps"] if s["kind"] == "store"} == \
        {"cache": "done", "ledger": ""}
    assert not (home / "cache").exists() and (home / "ledger").is_dir()
