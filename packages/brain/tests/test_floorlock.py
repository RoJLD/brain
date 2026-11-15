"""The locked floor held by the operating system (brain floor lock, brain.floorlock; review round 6 of
wi-brain-unadopted-floor): the lock file raises the floor, a floor-only machine without its lock refuses every call,
the guard checks the session token's access to what the lock holds, and the plan, the apply (elevated only) and the
unlock. Owner Ada; the lock folder is the tests' own (conftest's floor.LOCK_DIR)."""

import json

import pytest
from brain import floor, guards
from conftest import run_git
from test_floor import _guard_sh, config, edit
from test_guards import bash, pwsh


@pytest.fixture
def repo(git_repo):
    run_git(git_repo, "remote", "add", "origin", "https://code.example/ada/lab.git")
    return git_repo


def never(path) -> bool:
    """An administrator's file: out of this session's reach."""
    return False


@pytest.fixture
def unheld():
    """brain.floor.unlocked as it is."""
    return floor.unlocked


# --- review round 6: the floor held by the operating system (brain floor lock) ------------------------------------

def _lock(tmp_path, cfg_file, floor_section=None, checks=(), plugins=()):
    """A lock file in the tests' lock folder (conftest's floor.LOCK_DIR), holding ``cfg_file``."""
    d = floor.lock_dir()
    d.mkdir(parents=True, exist_ok=True)
    data = {"format": floor.LOCK_FORMAT, "floor": floor_section or {"refuse": True, "only": True},
            "config": str(cfg_file), "roots": [], "checks": [str(c) for c in checks],
            "plugins": [str(p) for p in plugins]}
    (d / floor.LOCK_FILE).write_text(json.dumps(data), encoding="utf-8")
    return d / floor.LOCK_FILE


def test_the_lock_file_raises_the_floor_and_an_unreadable_one_reads_only(tmp_path, monkeypatch):
    f = config(tmp_path, monkeypatch)
    cfg = guards.config.load()
    assert floor.effective(cfg, None) == {"refuse": False, "only": False}
    assert floor.effective(cfg, {"floor": {"only": True}}) == {"refuse": False, "only": True}
    assert floor.effective(cfg, {"error": "x"}) == floor.ONLY
    _lock(tmp_path, f, {"refuse": True})
    assert guards.floor_settings(cfg) == {"refuse": True, "only": False}   # config.json says off: the lock holds
    (floor.lock_dir() / floor.LOCK_FILE).write_text("{oops", encoding="utf-8")
    assert floor.read_lock()["error"] and guards.floor_settings(cfg) == floor.ONLY


def test_unlocked_says_why_the_floor_is_within_reach(tmp_path, monkeypatch, unheld):
    f = config(tmp_path, monkeypatch, only=True)
    cfg = guards.config.load()
    only = {"refuse": False, "only": True}
    assert unheld(cfg, {"refuse": True, "only": False}, None, never) == ""      # refuse alone, no lock: the parser's
    assert "has no lock" in unheld(cfg, only, None, never)
    assert "cannot be read" in unheld(cfg, only, {"error": "x"}, never)
    _lock(tmp_path, f, checks=[f])
    lock = floor.read_lock()
    assert unheld(cfg, only, lock, never) == ""
    assert unheld(cfg, {"refuse": False, "only": False}, lock, lambda p: str(p) == str(f)).endswith("by this session")
    assert "is writable" in unheld(cfg, only, lock, lambda p: p == floor.lock_dir())   # the lock folder itself
    other = tmp_path / "other" / "config.json"
    other.parent.mkdir()
    other.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(other))   # the guard pointed at another config.json
    assert "the lock holds" in unheld(guards.config.load(), only, lock, never)
    _lock(tmp_path, f, checks=[tmp_path / "gone"])
    assert "is missing" in unheld(cfg, only, floor.read_lock(), never)
    _lock(tmp_path, f, plugins=[tmp_path / "plugin"])
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path / "elsewhere"))
    assert "does not hold" in unheld(cfg, only, floor.read_lock(), never)
    (tmp_path / "plugin" / "hooks").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path / "plugin" / "hooks" / ".."))
    assert unheld(cfg, only, floor.read_lock(), never) == ""


def test_a_floor_only_machine_without_its_lock_refuses_every_call(repo, tmp_path, monkeypatch, unheld):
    f = config(tmp_path, monkeypatch, only=True)
    for reason in (bash(repo, "git status"), edit(repo, repo / "x.md", "x"), pwsh(repo, "Get-ChildItem")):
        assert reason and "the floor is not locked" in reason and "brain floor lock" in reason
        assert f"{guards.ALLOW_ENV}=floor (or floor:lock)" in reason
    _lock(tmp_path, f, checks=[f])
    monkeypatch.setattr(floor, "writable", lambda p: False)   # brain floor lock applied: out of reach
    assert bash(repo, "git status") is None
    assert "floor" in (bash(repo, "git push origin main") or "")   # the parser's refusals still run
    monkeypatch.setattr(floor, "writable", lambda p: str(p) == str(f))   # the lock no longer holds config.json
    assert "is writable by this session" in (bash(repo, "git status") or "")


def test_a_lock_holds_the_floor_whatever_config_json_says(repo, tmp_path, monkeypatch, unheld):
    f = config(tmp_path, monkeypatch)   # config.json rewritten floor-off
    _lock(tmp_path, f, {"refuse": True, "only": False}, checks=[f])
    monkeypatch.setattr(floor, "writable", lambda p: False)
    assert "breaks the locked floor" in (bash(repo, "git push origin main") or "")


def test_writable_reads_the_token_access_not_the_read_only_attribute(tmp_path):
    import os
    import sys
    mine = tmp_path / "mine.txt"
    mine.write_text("x", encoding="utf-8")
    assert floor.writable(mine) and floor.writable(tmp_path)
    assert floor.writable(tmp_path / "missing")   # what cannot be told reads as reachable
    from brain import floorlock
    if floorlock.elevated():
        pytest.skip("an elevated token reaches everything")
    system = os.environ.get("SystemRoot", "C:\\Windows") if sys.platform == "win32" else "/"
    assert not floor.writable(system)


def _lock_setup(tmp_path, monkeypatch):
    """A personal brain checkout with config.json, a BRAIN_HOME with its pointer and venv, an installed plugin."""
    import os
    from brain import floorlock
    brain = tmp_path / "personal"
    brain.mkdir()
    run_git(brain, "init", "-q")
    cfg = brain / "config.json"
    cfg.write_text(json.dumps({"v": 1, "floor": {"only": True}}), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(cfg))
    home = floorlock.paths.brain_home()
    (home / "venv").mkdir(parents=True)
    (home / "personal.json").write_text(json.dumps({"root": str(brain)}), encoding="utf-8")
    plugin = tmp_path / "plugin"
    (plugin / "hooks").mkdir(parents=True)
    (plugin / "hooks" / "guard.sh").write_text("", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin))
    monkeypatch.setattr(floorlock.Path, "home", classmethod(lambda c: tmp_path / "userhome"))
    monkeypatch.setattr(floor, "__file__", os.path.join(str(home), "venv", "Lib", "brain", "floor.py"))
    return brain, cfg, home, plugin


def test_the_lock_plan_names_what_it_gives_to_the_administrators(tmp_path, monkeypatch):
    from brain import floorlock
    brain, cfg, home, plugin = _lock_setup(tmp_path, monkeypatch)
    p = floorlock.plan(guards.config.load(), writable=lambda x: True)
    kinds = {str(r.path): r.kind for r, held in p["roots"]}
    assert kinds == {str(brain): "tree", str(home / "personal.json"): "file", str(home / "venv"): "tree",
                     str(plugin): "tree"}
    assert p["floor"] == {"refuse": False, "only": True} and p["lock"].path == floor.lock_dir()
    text = "\n".join(floorlock.render_plan(p))
    assert "to lock" in text and "brain floor lock --apply" in text and "a session never elevates" in text
    assert ["git", "config", "--system", "--add", "safe.directory", brain.as_posix()] in p["commands"]
    tree = floorlock.Root(brain, "tree", "")
    assert [c[1:] for c in floorlock.lock_commands(tree, nt=True)] == [
        [str(brain), "/setowner", "*S-1-5-32-544", "/T", "/C", "/Q"], [str(brain), "/reset", "/T", "/C", "/Q"],
        [str(brain), "/inheritance:r", "/grant:r", "*S-1-5-32-544:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F",
         "*S-1-5-32-545:(OI)(CI)RX", "/C", "/Q"]]
    assert floorlock.lock_commands(tree, nt=False) == [["chown", "-R", "0:0", str(brain)],
                                                         ["chmod", "-R", "u=rwX,go=rX", str(brain)]]
    assert floorlock.unlock_commands(tree, "ada", nt=False) == [["chown", "-R", "ada", str(brain)]]
    held = floorlock.plan(guards.config.load(), writable=lambda x: False)
    assert all(h for _, h in held["roots"]) and "held" in "\n".join(floorlock.render_plan(held))


def test_the_lock_plan_refuses_a_worktree_or_no_config(tmp_path, monkeypatch):
    from brain import floorlock
    monkeypatch.setenv("BRAIN_CONFIG", str(tmp_path / "none.json"))
    with pytest.raises(floorlock.LockError, match="no config.json"):
        floorlock.plan(guards.config.load())
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text("gitdir: elsewhere", encoding="utf-8")
    (wt / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(wt / "config.json"))
    with pytest.raises(floorlock.LockError, match="worktree"):
        floorlock.plan(guards.config.load())


def test_the_apply_refuses_without_elevation_and_writes_the_lock_last(tmp_path, monkeypatch):
    from brain import floorlock
    brain, cfg, home, plugin = _lock_setup(tmp_path, monkeypatch)
    with pytest.raises(floorlock.LockError, match="elevated"):
        floorlock.apply(guards.config.load(), is_elevated=lambda: False)
    assert floor.read_lock() is None
    ran = []

    class Done:
        returncode, stdout, stderr = 0, "", ""

    def run(cmd, **kw):
        ran.append(cmd)
        r = Done()
        if cmd[-1] == "safe.directory":   # --get-all: already listed
            r.stdout = brain.as_posix() + "\n"
        return r
    floorlock.apply(guards.config.load(), run=run, is_elevated=lambda: True)
    lock = floor.read_lock()
    assert lock["format"] == floor.LOCK_FORMAT and lock["floor"] == {"refuse": False, "only": True}
    assert lock["config"] == str(cfg.resolve()) and str(cfg.resolve()) in lock["checks"]
    assert lock["plugins"] == [str(plugin)]
    assert not any(c[:4] == ["git", "config", "--system", "--add"] for c in ran)   # listed already: not added twice
    assert str(floor.lock_dir()) in ran[-1]                                          # the lock folder locked last
    ran.clear()
    floorlock.apply(guards.config.load(), refresh=True, run=run, is_elevated=lambda: True)
    assert ran[0][-2:] == ["fetch", "origin"] and ran[1][-3:] == ["merge", "--ff-only", "origin/main"]
    out = floorlock.unlock(run=run, is_elevated=lambda: True, owner="ada")
    assert floor.read_lock() is None and "unlocked" in out[0]


def test_brain_floor_status_and_the_plan_from_the_command_line(tmp_path, monkeypatch, capsys, unheld):
    from brain import cli
    _lock_setup(tmp_path, monkeypatch)
    assert cli.main(["floor", "status"]) == 0
    out = capsys.readouterr().out
    assert "only=True" in out and "lock: none" in out and "held: no: this machine has no lock" in out
    assert cli.main(["floor", "lock"]) == 0 and "brain floor lock --apply" in capsys.readouterr().out
    monkeypatch.setattr("brain.floorlock.elevated", lambda: False)
    assert cli.main(["floor", "lock", "--apply"]) == 2 and "never elevates" in capsys.readouterr().err


def test_guard_sh_fails_closed_on_a_locked_machine(tmp_path):
    pd = tmp_path / "programdata"
    (pd / "Brain").mkdir(parents=True)
    (pd / "Brain" / floor.LOCK_FILE).write_text("{}", encoding="utf-8")
    out = _guard_sh(tmp_path, "cp a ~/.claude/settings.json", {}, False, PROGRAMDATA=pd.as_posix())
    assert "the locked floor is on" in out


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows' ACLs")
def test_a_real_lock_of_a_scratch_folder(tmp_path):
    """The apply's icacls commands on a scratch folder, for real: only in an elevated terminal (the owner's)."""
    import subprocess
    from brain import floorlock
    if not floorlock.elevated():
        pytest.skip("needs an elevated terminal: a session never elevates")
    scratch = tmp_path / "scratch"
    (scratch / "sub").mkdir(parents=True)
    (scratch / "sub" / "f.txt").write_text("x", encoding="utf-8")
    root = floorlock.Root(scratch, "tree", "")
    for cmd in floorlock.lock_commands(root):
        assert subprocess.run(cmd, capture_output=True, timeout=300).returncode == 0, cmd
    try:
        acl = subprocess.run(["icacls", str(scratch / "sub" / "f.txt")], capture_output=True, text=True, timeout=60).stdout
        owner = subprocess.run(["powershell", "-NoProfile", "-Command", f"(Get-Acl '{scratch}').Owner"],
                               capture_output=True, text=True, timeout=60).stdout
        assert "BUILTIN\\Users:(I)(RX)" in acl and "Administrators" in owner
    finally:
        for cmd in floorlock.unlock_commands(root, floorlock._owner()):
            subprocess.run(cmd, capture_output=True, timeout=300)
