"""The locked floor held by the operating system (brain floor lock, brain.floorlock, brain.floorhook; review rounds 6-8
of wi-brain-unadopted-floor): the lock file's floor is the authority and config.json is only compared to it, a
floor-only machine without its lock refuses every call, the override does not lift a locked floor, the guard runs as a
system component (its copy, its manifest, its managed hooks), and the plan, the apply (elevated only) and the unlock.
Owner Ada; the lock, guard and managed folders are the tests' own (conftest)."""

import json
import os
from pathlib import Path

import pytest
from brain import floor, floorhook, floorlock, guards
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


def _lock(cfg_file, floor_section=None, checks=(), brain_home=""):
    """A lock file in the tests' lock folder holding ``cfg_file``, with a guard copy whose manifest it hashed."""
    guard = floor.guard_dir()
    guard.mkdir(parents=True, exist_ok=True)
    (guard / floor.MANIFEST).write_text("{}\n", encoding="utf-8")
    d = floor.lock_dir()
    d.mkdir(parents=True, exist_ok=True)
    data = {"format": floor.LOCK_FORMAT, "floor": floor_section or {"refuse": True, "only": True},
            "config": str(cfg_file), "brain_home": brain_home, "guard": str(guard),
            "interpreter": str(guard / "python" / "python.exe"),
            "manifest": floor.file_hash(guard / floor.MANIFEST), "checks": [str(c) for c in checks]}
    (d / floor.LOCK_FILE).write_text(json.dumps(data), encoding="utf-8")
    return d / floor.LOCK_FILE


# --- the lock file: the floor's authority ------------------------------------------------------------------------

def test_the_lock_file_raises_the_floor_and_an_unreadable_one_reads_only(tmp_path, monkeypatch):
    f = config(tmp_path, monkeypatch)
    cfg = guards.config.load()
    assert floor.effective(cfg, None) == {"refuse": False, "only": False}
    assert floor.effective(cfg, {"floor": {"only": True}}) == {"refuse": False, "only": True}
    assert floor.effective(cfg, {"error": "x"}) == floor.ONLY
    _lock(f, {"refuse": True})
    assert guards.floor_settings(cfg) == {"refuse": True, "only": False}   # config.json says off: the lock holds
    (floor.lock_dir() / floor.LOCK_FILE).write_text("{oops", encoding="utf-8")
    assert floor.read_lock()["error"] and guards.floor_settings(cfg) == floor.ONLY
    (floor.lock_dir() / floor.LOCK_FILE).write_text(json.dumps({"format": "brain.floor-lock/v1"}), encoding="utf-8")
    assert "not a brain.floor-lock/v2" in floor.read_lock()["error"]   # round 6's lock is no lock: lock again


def test_unlocked_says_why_the_floor_is_not_held(tmp_path, monkeypatch, unheld):
    f = config(tmp_path, monkeypatch, only=True)
    cfg = guards.config.load()
    only = {"refuse": False, "only": True}
    assert unheld(cfg, {"refuse": True, "only": False}, None, never) == ""      # refuse alone, no lock: the parser's
    assert "has no lock" in unheld(cfg, only, None, never)
    assert "cannot be read" in unheld(cfg, only, {"error": "x"}, never)
    _lock(f, {"only": True}, checks=[floor.guard_dir()])
    lock = floor.read_lock()
    assert unheld(cfg, only, lock, never) == ""
    assert "is writable" in unheld(cfg, only, lock, lambda p: str(p) == str(floor.lock_dir()))   # the lock folder itself
    assert "is writable" in unheld(cfg, only, lock, lambda p: str(p) == str(floor.guard_dir()))
    (floor.guard_dir() / floor.MANIFEST).write_text('{"guard.py": "x"}', encoding="utf-8")
    assert "manifest" in unheld(cfg, only, lock, never)                          # the guard's files changed
    _lock(f, {"refuse": True}, checks=[tmp_path / "gone"])
    assert "is missing" in unheld(cfg, only, floor.read_lock(), never)
    _lock(f, {"refuse": True})                                                   # config.json says only: not the lock's
    assert "is not the locked one" in unheld(cfg, only, floor.read_lock(), never)
    other = tmp_path / "other" / "config.json"
    other.parent.mkdir()
    other.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(other))   # the guard pointed at another config.json
    assert "the lock holds" in unheld(guards.config.load(), only, floor.read_lock(), never)


def test_a_floor_only_machine_without_its_lock_refuses_every_call(repo, tmp_path, monkeypatch, unheld):
    f = config(tmp_path, monkeypatch, only=True)
    for reason in (bash(repo, "git status"), edit(repo, repo / "x.md", "x"), pwsh(repo, "Get-ChildItem")):
        assert reason and "the floor is not locked" in reason and "brain floor lock" in reason
    _lock(f, {"only": True})
    monkeypatch.setattr(floor, "writable", never)   # brain floor lock applied: out of reach
    assert bash(repo, "git status") is None
    assert "floor" in (bash(repo, "git push origin main") or "")   # the parser's refusals still run
    monkeypatch.setattr(floor, "writable", lambda p: str(p) == str(floor.lock_dir() / floor.LOCK_FILE))
    assert "is writable by this session" in (bash(repo, "git status") or "")


def test_config_json_differing_from_the_lock_refuses_every_call(repo, tmp_path, monkeypatch, unheld):
    """Round 7: the lock's floor is the authority; a config.json rewritten floor-off does not lower it, it stops
    every call until the owner locks again (and renaming or replacing the checkout changes nothing else)."""
    f = config(tmp_path, monkeypatch)
    _lock(f, {"refuse": True, "only": False})
    monkeypatch.setattr(floor, "writable", never)
    reason = bash(repo, "git status") or ""
    assert "is not the locked one" in reason and "the owner locks it again" in reason


def test_the_override_does_not_lift_a_locked_floor(repo, tmp_path, monkeypatch, unheld):
    """Round 7 #2: BRAIN_GUARD_ALLOW=floor (or all, or floor:lock) comes from the session's environment."""
    f = config(tmp_path, monkeypatch, refuse=True)
    monkeypatch.setenv(guards.ALLOW_ENV, "floor")
    assert "floor" in guards.allowed()                                   # no lock: the owner's override
    _lock(f, {"refuse": True})
    monkeypatch.setattr(floor, "writable", never)
    for allow in ("floor", "all", "floor:lock,floor:push"):
        monkeypatch.setenv(guards.ALLOW_ENV, allow)
        assert not any(n == "floor" or n.startswith("floor:") for n in guards.allowed())
        assert "breaks the locked floor" in (bash(repo, "git push origin feat/x:main") or "")
    monkeypatch.setattr(floor, "writable", lambda p: True)
    assert "the floor is not locked" in (bash(repo, "git status") or "")   # the lock refusal is not lifted either


def test_the_locked_hook_takes_its_selectors_from_the_lock(tmp_path, monkeypatch):
    f = config(tmp_path, monkeypatch, refuse=True)
    _lock(f, {"refuse": True}, brain_home=str(tmp_path / "home"))
    env = {"BRAIN_CONFIG": "evil.json", "BRAIN_PYTHON": "x", "CLAUDE_PLUGIN_ROOT": "y", "BRAIN_PERSONAL": "z",
           "CLAUDE_BRAIN_DIR": "w", "BRAIN_HOME": "v", "PATH": "p"}
    floorhook.pin(env)
    assert env == {"BRAIN_CONFIG": str(f), "BRAIN_HOME": str(tmp_path / "home"), "PATH": "p",
                   "NoDefaultCurrentDirectoryInExePath": "1"}   # round 8 #8: no program from the working directory
    (floor.lock_dir() / floor.LOCK_FILE).unlink()
    env = {"BRAIN_CONFIG": "evil.json"}
    floorhook.pin(env)
    assert env == {"NoDefaultCurrentDirectoryInExePath": "1"}   # no lock: no config.json chosen by the session (the guard refuses every call)


# --- the session token's reach ------------------------------------------------------------------------------------

def test_owner_reads_the_owner_s_id(tmp_path):
    mine = tmp_path / "mine.txt"
    mine.write_text("x", encoding="utf-8")
    who = floor.owner(mine)
    assert who and (who.startswith("S-1-") if os.name == "nt" else who == str(os.getuid()))
    assert floor.owner(tmp_path / "missing") == ""


def test_writable_reads_the_token_access_not_the_read_only_attribute(tmp_path):
    import sys
    mine = tmp_path / "mine.txt"
    mine.write_text("x", encoding="utf-8")
    assert floor.writable(mine) and floor.writable(tmp_path)
    assert floor.writable(tmp_path / "missing")   # what cannot be told reads as reachable
    if floorlock.elevated():
        pytest.skip("an elevated token reaches everything")
    system = os.environ.get("SystemRoot", "C:\\Windows") if sys.platform == "win32" else "/"
    assert not floor.writable(system)


def test_verify_names_a_user_s_folder_and_its_writers(tmp_path):
    """The apply's check reads owners and DACL entries, not the token (it runs elevated)."""
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "f.txt").write_text("x", encoding="utf-8")
    wrong = floorlock.verify(tmp_path)
    assert any("sub" in w and "f.txt" in w for w in wrong)
    if not floorlock.elevated():   # an elevated administrator's files are owned by Administrators (CI's runner)
        assert any("owned by" in w for w in wrong)
    if os.name == "nt":
        assert any("writable by S-1-" in w for w in wrong)   # the user's own entry (or OWNER RIGHTS)
        system = os.environ.get("SystemRoot", "C:\\Windows")
        assert floorlock.foreign_writers(os.path.join(system, "System32", "kernel32.dll")) == []


# --- plan, install, apply, unlock ---------------------------------------------------------------------------------

def _setup(tmp_path, monkeypatch, **section):
    cfg = tmp_path / "personal" / "config.json"
    cfg.parent.mkdir()
    cfg.write_text(json.dumps({"v": 1, "floor": section or {"only": True}}), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(cfg))
    return cfg


def test_the_plan_refuses_no_config_or_no_floor(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_CONFIG", str(tmp_path / "none.json"))
    with pytest.raises(floorlock.LockError, match="no readable config.json"):
        floorlock.plan(guards.config.load())
    _setup(tmp_path, monkeypatch, refuse=False)
    with pytest.raises(floorlock.LockError, match="floor is off"):
        floorlock.plan(guards.config.load())


def test_the_plan_prints_what_it_writes_and_an_absolute_command_with_no_profile(tmp_path, monkeypatch):
    cfg = _setup(tmp_path, monkeypatch, only=True)
    p = floorlock.plan(guards.config.load())
    assert p["floor"] == {"refuse": False, "only": True} and p["held"] is None and not p["installed"]
    text = "\n".join(floorlock.render_plan(p))
    for part in (str(floor.guard_dir()), str(floor.managed_file()), floor.LOCK_FILE, "close every Claude Code session",
                 "a session never elevates", " -I ", "floor lock --apply", "allowManagedHooksOnly",
                 f"v{floorlock.MIN_CLAUDE_CODE}"):
        assert part in text, part
    if os.name == "nt":   # round 8 #3: Win+R, no interactive shell, the window waits
        assert "Win+R" in text and "Ctrl+Shift+Enter" in text and "powershell" not in floorlock.run_command(p)
        assert floorlock.run_command(p).endswith("--wait")
    _lock(cfg, {"refuse": True, "only": True})
    cfg.write_text(json.dumps({"v": 1, "floor": {"refuse": True}}), encoding="utf-8")
    p = floorlock.plan(guards.config.load())
    assert p["lowers"] and p["installed"] and "--lower" in floorlock.run_command(p)   # only stays, refuse goes
    assert str(floor.guard_dir() / "floor.py") in floorlock.run_command(p)            # the guard's copy runs it


def test_lock_commands_cut_before_the_owner_and_reset_the_children():
    root = floor.guard_dir()
    cmds = [c[1:] for c in floorlock.lock_commands(root, nt=True)]
    assert cmds == [[str(root), "/reset", "/C", "/Q"],
                    [str(root), "/inheritance:r", "/grant:r", "*S-1-5-32-544:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F",
                     "*S-1-5-32-545:(OI)(CI)RX", "/C", "/Q"],
                    [str(root), "/setowner", "*S-1-5-32-544", "/T", "/C", "/Q"],
                    [os.path.join(str(root), "*"), "/reset", "/T", "/C", "/Q"]]
    assert floorlock.lock_commands(root, nt=False) == [["chown", "-R", "0:0", str(root)],
                                                         ["chmod", "-R", "u=rwX,go=rX", str(root)]]


def test_install_guard_copies_the_interpreter_the_code_and_hashes_them(tmp_path):
    base = tmp_path / "base"
    for rel in ("python.exe", "Lib/os.py", "Lib/__pycache__/os.cpython-312.pyc", "Lib/site-packages/evil.pth",
                "Lib/test/t.py", "DLLs/x.pyd"):
        (base / rel).parent.mkdir(parents=True, exist_ok=True)
        (base / rel).write_text("x", encoding="utf-8")
    pkg = tmp_path / "src" / "brain"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    gdir = floor.guard_dir() / "g1"
    ran = []

    class Done:
        returncode, stdout, stderr = 0, "", ""

    def run(cmd, **kw):   # the copy's own interpreter compiles it (round 8 #5)
        ran.append(cmd)
        (gdir / "site" / "brain" / "__pycache__").mkdir()
        (gdir / "site" / "brain" / "__pycache__" / "__init__.cpython-312.pyc").write_text("pyc", encoding="utf-8")
        return Done()

    rendered = tmp_path / "plugins" / "core"   # what brain sync rendered: the rules and the hook contract (round 9 #5)
    (rendered / "rules").mkdir(parents=True)
    (rendered / "rules" / "global.md").write_text("rules", encoding="utf-8")
    (rendered / "hooks").mkdir()
    (rendered / "hooks" / "contract.txt").write_text("contract", encoding="utf-8")
    interp = floorlock.install_guard(gdir, base=base, packages=[pkg], nt=True, run=run, rendered=rendered)
    assert interp == gdir / "python" / "python.exe"
    assert ran == [[str(interp), "-I", "-m", "compileall", "-q", "-j", "0", str(gdir)]]
    assert (gdir / "python" / "Lib" / "os.py").exists() and (gdir / "python" / "DLLs" / "x.pyd").exists()
    assert (gdir / "python" / "Lib" / "__pycache__").exists()   # the standard library's bytecode kept
    packages_dir = gdir / "python" / "Lib" / "site-packages"   # none of the base's packages: the copy's site alone
    assert [p.name for p in packages_dir.iterdir()] == ["brain-guard.pth"] and not (gdir / "python" / "Lib" / "test").exists()
    assert (packages_dir / "brain-guard.pth").read_text(encoding="utf-8").strip() == str(gdir / "site")
    hooks_dir = gdir / "plugin" / "hooks"   # the copy's scripts run the copy's interpreter (common.sh's brain_python)
    assert (hooks_dir / "locked-python").read_text(encoding="utf-8").strip() == interp.as_posix()
    assert (gdir / "plugin" / "rules" / "global.md").exists() and (hooks_dir / "contract.txt").exists()
    assert (gdir / "site" / "brain" / "__init__.py").exists() and (hooks_dir / "budget.sh").exists()
    assert "floorhook.hook(" in (gdir / "hook.py").read_text(encoding="utf-8")
    assert "floorhook.cli(" in (gdir / "floor.py").read_text(encoding="utf-8")
    listed = json.loads((gdir / floor.MANIFEST).read_text(encoding="utf-8"))
    assert listed == floorlock.manifest(gdir) and "hook.py" in listed and "python/python.exe" in listed
    assert "site/brain/__pycache__/__init__.cpython-312.pyc" in listed   # bytecode in the manifest
    with pytest.raises(floorlock.LockError, match="exists"):   # a copy goes into a new folder, never over one
        floorlock.install_guard(gdir, base=base, packages=[pkg], nt=True, compile=False)


def test_the_managed_settings_block_other_hooks_and_declare_the_plugin_s_in_exec_form(tmp_path):
    """Round 8 #1, #2: allowManagedHooksOnly; every plugin hook declared from the copy, exec form (no shell, no PATH);
    the judging ones with onFailure block and a deadline under their timeout; the others with the administrators'
    bash, or left out without one; the opt-in read hint only when config.json turns it on."""
    gdir, interp = tmp_path / "g1", tmp_path / "g1" / "python" / "python.exe"
    s = floorlock.hooks_settings(interp, gdir)
    assert s["allowManagedHooksOnly"] is True and set(s["hooks"]) == {"PreToolUse"}   # no bash: other events left out
    assert s["strictPluginOnlyCustomization"] == ["hooks"]   # round 9 #2: skills', commands', agents' hooks stop
    hooks = [h for g in s["hooks"]["PreToolUse"] for h in g["hooks"]]
    assert {h["command"] for h in hooks} == {str(interp)} and not [h for h in hooks if "shell" in h]
    assert {tuple(h["args"][:4]) for h in hooks} == {("-X", "utf8", "-I", str(gdir / "hook.py"))}
    judged = {" ".join(h["args"][4:]): h.get("onFailure") for h in hooks}   # what runs: whether its failure blocks
    assert judged["--deadline=18 guard shell"] == judged["--deadline=6 guard edit"] == "block"
    assert judged["--deadline=6 governor"] == "block"
    assert judged["waithint"] is None                                       # a hint never judges
    assert not [k for k in judged if "readhint" in k]                       # opt-in, off


def test_the_managed_settings_run_other_events_with_the_administrators_bash(tmp_path):
    """Round 8 #1: the rules, announcements, capture... run the copy's scripts with an absolute bash, exec form."""
    gdir, interp = tmp_path / "g1", tmp_path / "g1" / "python" / "python.exe"
    s = floorlock.hooks_settings(interp, gdir, bash="C:/Program Files/Git/bin/bash.exe", data={"hints": {"read": True}})
    assert any("readhint" in h["args"] for g in s["hooks"]["PreToolUse"] for h in g["hooks"])
    start = [h for g in s["hooks"]["SessionStart"] for h in g["hooks"]]
    assert start[0] == {"type": "command", "timeout": 10, "command": "C:/Program Files/Git/bin/bash.exe",
                        "args": [(gdir / "plugin" / "hooks" / "inject-rules.sh").as_posix(), "SessionStart"]}
    assert {"Stop", "SessionEnd", "PostToolUse", "UserPromptSubmit", "SubagentStart"} <= set(s["hooks"])


def test_the_locked_hook_refuses_past_its_deadline_and_an_unknown_name(capsys, monkeypatch):
    """Round 8 #2: a guard that has not decided within its deadline refuses (exit 2, Claude Code blocks the call)."""
    import threading
    exited = threading.Event()
    codes = []
    timer = floorhook.refuse_after(0.05, "guard", exit=lambda code: (codes.append(code), exited.set()))
    assert exited.wait(5) and codes == [2]
    timer.cancel()
    assert "did not decide within 0.05 s" in capsys.readouterr().err
    monkeypatch.setattr(floorhook, "pin", lambda: None)
    assert floorhook.hook(["--deadline=5", "nothing"]) == 2 and "unknown" in capsys.readouterr().err


def test_the_locked_launcher_runs_the_copy_s_guard(tmp_path, monkeypatch):
    """hook.py of the copy, run as the managed hook runs it: -I, its own site folder, a refusal on stdout."""
    import shutil
    import subprocess
    import sys
    f = config(tmp_path, monkeypatch, refuse=True)
    gdir = floor.guard_dir()
    (gdir / "site").mkdir(parents=True)
    (gdir / "hook.py").write_text(floorlock.LAUNCHER.format(entry="hook"), encoding="utf-8")
    shutil.copytree(os.path.dirname(floor.__file__), gdir / "site" / "brain",
                    ignore=shutil.ignore_patterns("__pycache__"))
    _lock(f, {"refuse": True})
    shim = tmp_path / "shim.py"   # the tests' lock folder for the child (floor.LOCK_DIR), then the launcher
    shim.write_text("import sys, runpy\nsys.argv = sys.argv[1:]\n"
                    "sys.path[:0] = [sys.argv[0].rsplit('/', 1)[0] + '/site']\n"
                    "from brain import floor\nfrom pathlib import Path\n"
                    f"floor.LOCK_DIR = Path({str(floor.lock_dir())!r})\n"
                    "runpy.run_path(sys.argv[0], run_name='__main__')\n", encoding="utf-8")
    hook = {"tool_name": "Bash", "tool_input": {"command": "git push origin feat/x:main"}, "cwd": str(tmp_path)}
    env = {**os.environ, "BRAIN_GUARD_ALLOW": "floor", "BRAIN_CONFIG": "elsewhere.json"}
    r = subprocess.run([sys.executable, "-X", "utf8", "-I", str(shim), (gdir / "hook.py").as_posix(), "--deadline=20",
                        "guard", "shell"], input=json.dumps(hook).encode(), capture_output=True, timeout=120, env=env)
    out = r.stdout.decode("utf-8")
    # the scratch lock does not hold (a user's folders): refused, and the environment's override lifted nothing
    assert "deny" in out and "the floor is not locked" in out, (out, r.stderr.decode("utf-8", "replace")[-800:])


class _Done:
    returncode, stdout, stderr = 0, "", ""


def _install(gdir, **kw):
    gdir.mkdir(parents=True)
    (gdir / floor.MANIFEST).write_text("{}", encoding="utf-8")
    return gdir / "python" / "python.exe"


def _applier(ran: list):
    def run(cmd, **kw):
        ran.append((cmd, (floor.lock_dir() / floor.LOCK_FILE).exists()))
        return _Done()

    def apply(**kw):
        return floorlock.apply(guards.config.load(), run=run, is_elevated=lambda: True, install=_install,
                               tools=lambda check: {"git": "C:/Program Files/Git/cmd/git.exe"}, **kw)
    return apply


def test_the_apply_needs_elevation_checks_every_file_and_writes_the_lock_last(tmp_path, monkeypatch):
    cfg = _setup(tmp_path, monkeypatch, only=True)
    with pytest.raises(floorlock.LockError, match="elevated"):
        floorlock.apply(guards.config.load(), is_elevated=lambda: False)
    assert floor.read_lock() is None
    ran = []
    apply = _applier(ran)
    floor.lock_dir().mkdir(parents=True)
    (floor.lock_dir() / "planted.txt").write_text("x", encoding="utf-8")   # a session's file before the lock
    out = apply(check=lambda p: [])
    lock = floor.read_lock()
    copy = Path(lock["guard"])
    assert copy.parent == floor.guard_dir() and lock["format"] == floor.LOCK_FORMAT
    assert lock["floor"] == {"refuse": False, "only": True} and lock["git"] == "C:/Program Files/Git/cmd/git.exe"
    assert lock["config"] == str(cfg.resolve()) and lock["manifest"] == floor.file_hash(copy / "manifest.json")
    assert str(floor.managed_file()) in lock["checks"] and str(floor.guard_dir()) in lock["checks"]
    assert "locked" in out[0] and not (floor.lock_dir() / "planted.txt").exists()
    managed = json.loads(floor.managed_file().read_text(encoding="utf-8"))
    assert managed["allowManagedHooksOnly"] is True and managed["hooks"]["PreToolUse"]
    cuts = [written for cmd, written in ran if str(floor.lock_dir()) == cmd[1] and "/inheritance:r" in cmd]
    if os.name == "nt":
        assert cuts == [False]   # the lock folder cut before the lock file is written


def test_a_failed_apply_restores_the_previous_lock_then_lower_and_unlock(tmp_path, monkeypatch):
    """Round 8 #4: a step that fails leaves the previous state whole; a new lock replaces the copy; unlock removes all."""
    cfg = _setup(tmp_path, monkeypatch, only=True)
    apply = _applier([])
    apply(check=lambda p: [])
    copy = Path(floor.read_lock()["guard"])
    held_lock, held_managed = (floor.lock_dir() / floor.LOCK_FILE).read_bytes(), floor.managed_file().read_bytes()
    with pytest.raises(floorlock.LockError, match="back as they were"):   # round 8 #4: the previous state whole
        apply(check=lambda p: [f"{p}: writable by S-1-5-21-x"] if p == floor.lock_dir() else [])
    assert (floor.lock_dir() / floor.LOCK_FILE).read_bytes() == held_lock
    assert floor.managed_file().read_bytes() == held_managed and [p for p in floor.guard_dir().iterdir()] == [copy]
    cfg.write_text(json.dumps({"v": 1, "floor": {"refuse": True}}), encoding="utf-8")
    with pytest.raises(floorlock.LockError, match="--lower"):
        apply(check=lambda p: [])
    apply(lower=True, check=lambda p: [])
    assert floor.read_lock()["floor"] == {"refuse": True, "only": False}
    assert [p.name for p in floor.guard_dir().iterdir()] == [Path(floor.read_lock()["guard"]).name] != [copy.name]
    out = floorlock.unlock(is_elevated=lambda: True)
    assert floor.read_lock() is None and not floor.guard_dir().exists() and not floor.managed_file().exists()
    assert "unlocked" in out[0]


def test_a_failed_first_apply_leaves_no_lock_and_the_running_copy_is_never_removed(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, only=True)
    with pytest.raises(floorlock.LockError, match="no lock"):
        floorlock.apply(guards.config.load(), run=lambda c, **k: _Done(), is_elevated=lambda: True, install=_install,
                        tools=lambda check: {}, check=lambda p: ["x: owned by S-1-5-21-x"])
    assert floor.read_lock() is None and not floor.managed_file().exists()
    assert not any(floor.guard_dir().iterdir())   # the new copy removed
    running = floor.guard_dir() / "g-old"
    (running / "python").mkdir(parents=True)
    monkeypatch.setattr(floorlock.sys, "executable", str(running / "python" / "python.exe"))
    assert floorlock._prune(floor.guard_dir(), keep=None) == [str(running)] and running.exists()


def test_the_guard_runs_the_git_the_lock_names(tmp_path, monkeypatch):
    """Round 8 #8: never a git.exe in the hook's working directory."""
    monkeypatch.setenv("NoDefaultCurrentDirectoryInExePath", "")
    f = config(tmp_path, monkeypatch, refuse=True)
    _lock(f, {"refuse": True})
    lock = json.loads((floor.lock_dir() / floor.LOCK_FILE).read_text(encoding="utf-8"))
    lock["git"] = str(tmp_path / "Git" / "cmd" / "git.exe")
    (floor.lock_dir() / floor.LOCK_FILE).write_text(json.dumps(lock), encoding="utf-8")
    assert floor.git() == lock["git"]
    (floor.lock_dir() / floor.LOCK_FILE).unlink()
    (tmp_path / "git.exe").write_text("planted", encoding="utf-8")   # a git in the working directory
    (tmp_path / "git").write_text("planted", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    found = floor.git()
    assert found != lock["git"] and os.path.dirname(os.path.abspath(found)) != str(tmp_path)
    assert os.environ["NoDefaultCurrentDirectoryInExePath"] == ""   # the lookup's setting does not stay


def test_brain_floor_status_and_the_plan_from_the_command_line(tmp_path, monkeypatch, capsys, unheld):
    from brain import cli
    _setup(tmp_path, monkeypatch, only=True)
    assert cli.main(["floor", "status"]) == 0
    out = capsys.readouterr().out
    assert "only=True" in out and "lock: none" in out and "held: no: this machine has no lock" in out
    assert cli.main(["floor", "lock"]) == 0 and "floor lock --apply" in capsys.readouterr().out
    monkeypatch.setattr("brain.floorlock.elevated", lambda: False)
    assert cli.main(["floor", "lock", "--apply"]) == 2 and "never elevates" in capsys.readouterr().err
    assert cli.main(["floor", "unlock"]) == 0 and "nothing to unlock" in capsys.readouterr().out


def test_guard_sh_fails_closed_on_a_locked_machine(tmp_path):
    pd = tmp_path / "programdata"
    (pd / "Brain").mkdir(parents=True)
    (pd / "Brain" / floor.LOCK_FILE).write_text("{}", encoding="utf-8")
    out = _guard_sh(tmp_path, "cp a ~/.claude/settings.json", {}, False, PROGRAMDATA=pd.as_posix())
    assert "the locked floor is on" in out


@pytest.mark.skipif(os.name != "nt", reason="Windows' ACLs")
def test_a_real_lock_of_a_scratch_folder(tmp_path):
    """The apply's icacls commands on a scratch folder, for real: only in an elevated terminal (CI's Windows runner,
    the owner's). An entry the user adds to a child before the lock goes, and verify() then finds nothing."""
    import getpass
    import subprocess
    if not floorlock.elevated():
        pytest.skip("needs an elevated terminal: a session never elevates")
    scratch = tmp_path / "scratch"
    (scratch / "sub").mkdir(parents=True)
    child = scratch / "sub" / "f.txt"
    child.write_text("x", encoding="utf-8")
    me = getpass.getuser()
    assert subprocess.run(["icacls", str(child), "/grant", f"{me}:F"], capture_output=True, timeout=60).returncode == 0
    for cmd in floorlock.lock_commands(scratch):
        assert subprocess.run(cmd, capture_output=True, timeout=300).returncode == 0, cmd
    try:
        saved = tmp_path / "acl.txt"   # the DACLs as SDDL, whatever the system's language
        assert subprocess.run(["icacls", str(scratch), "/save", str(saved), "/T", "/C", "/Q"], capture_output=True,
                              timeout=60).returncode == 0
        sddl = saved.read_bytes().decode("utf-16-le").lstrip("\ufeff").splitlines()
        lines = dict(zip(sddl[0::2], sddl[1::2], strict=False))   # a name relative to the folder above, then its DACL
        root_acl, child_acl = lines["scratch"], lines["scratch\\sub\\f.txt"]
        assert "D:PAI" in root_acl and "(A;OICI;0x1200a9;;;BU)" in root_acl     # inheritance cut, Users read and run
        assert "(A;OICI;FA;;;BA)" in root_acl and "(A;OICI;FA;;;SY)" in root_acl
        assert "(A;ID;0x1200a9;;;BU)" in child_acl and "S-1-5-21" not in child_acl   # the user's own entries gone
        assert floor.owner(scratch) == floor.owner(child) == "S-1-5-32-544"   # Administrators
        assert floorlock.verify(scratch) == []
    finally:
        for cmd in (["icacls", str(scratch), "/reset", "/T", "/C", "/Q"],
                    ["icacls", str(scratch), "/setowner", me, "/T", "/C", "/Q"]):
            subprocess.run(cmd, capture_output=True, timeout=300)
