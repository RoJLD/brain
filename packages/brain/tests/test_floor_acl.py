"""The floor's ACL step (wi-brain-floor-acl-lock; brain.floorlock's acl_*, docs/guards.md « The lock »): under
config.json floor.only with floor.acl (off by default), brain floor lock --apply denies the account the sessions run
as every change of its Claude Code settings, hooks, skills, commands and agents and of its projects' settings, and
brain floor unlock --apply gives them back. No test changes a real ACL: the commands go to a fake runner, the profile
is the tests' own (conftest's floor.PROFILE_DIR); one test runs icacls on a scratch folder, elevated only."""

import json
import os
from pathlib import Path

import pytest
from brain import floor, floorlock, guards
from test_floorlock import _Done, _install, _lock, _setup

SID = "S-1-5-21-1111111111-2222222222-3333333333-1001"
nt = pytest.mark.skipif(os.name != "nt", reason="floor.acl is a Windows deny entry")


def _acl_brain(tmp_path, monkeypatch, acl=True, only=True, project=True):
    """A floor-only brain with floor.acl, a registry naming one project with its own .claude settings; the profile's
    ~/.claude holds settings.json and hooks only (the rest is missing)."""
    cfg = _setup(tmp_path, monkeypatch, only=only, acl=acl) if only else _setup(tmp_path, monkeypatch, refuse=True,
                                                                                    acl=acl)
    home = floor.profile(SID) / ".claude"
    (home / "hooks").mkdir(parents=True, exist_ok=True)
    (home / "settings.json").write_text("{}", encoding="utf-8")
    if project:
        lab = tmp_path / "lab"
        (lab / ".claude").mkdir(parents=True)
        (lab / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
        (cfg.parent / "projects.yaml").write_text("lab: {root: ../lab}\n", encoding="utf-8")
    return cfg


def test_the_acl_step_is_off_by_default_and_asked_under_floor_only(tmp_path, monkeypatch):
    _acl_brain(tmp_path, monkeypatch, acl=False)
    assert floorlock.plan(guards.config.load())["acl"] is None
    _setup_again = tmp_path / "again"
    _setup_again.mkdir()
    cfg = _acl_brain(_setup_again, monkeypatch, only=False)        # floor.refuse alone: not asked
    assert not floorlock.acl_wanted(guards.config.load()) and floorlock.plan(guards.config.load())["acl"] is None
    data = json.loads(cfg.read_text(encoding="utf-8"))
    data["floor"] = {"only": True, "acl": "yes"}                     # a bool or nothing
    cfg.write_text(json.dumps(data), encoding="utf-8")
    assert not floorlock.acl_wanted(guards.config.load())


def test_the_plan_names_the_account_s_files_and_its_projects_settings(tmp_path, monkeypatch):
    _acl_brain(tmp_path, monkeypatch)
    a = floorlock.acl_plan(guards.config.load(), SID, nt=True)
    home = floor.profile(SID) / ".claude"
    lab = Path(os.path.realpath(tmp_path / "lab"))
    personal = Path(os.path.realpath(tmp_path / "personal"))
    assert a["account"] == SID and a["home"] == str(home)
    assert a["files"] == [str(home / "settings.json"), str(home / "settings.local.json"),
                          str(lab / ".claude" / "settings.json")]
    assert a["trees"] == [str(home / n) for n in ("hooks", "skills", "commands", "agents")]
    assert a["folders"] == [str(personal / ".claude"), str(lab / ".claude")]
    assert a["create"] == [str(home / "settings.local.json"), *(str(home / n) + os.sep for n in
                                                                ("skills", "commands", "agents")),
                           str(personal / ".claude") + os.sep, str(personal / ".claude" / "worktrees") + os.sep,
                           str(lab / ".claude" / "worktrees") + os.sep]   # made first: none can be made later


@pytest.mark.parametrize("sid", ["", "S-1-5-32-544", "S-1-5-18", "S-1-1-0", "ada", "S-1-5-21-1 /grant x:F"])
def test_the_plan_refuses_an_account_that_is_not_a_person_s(tmp_path, monkeypatch, sid):
    _acl_brain(tmp_path, monkeypatch)
    with pytest.raises(floorlock.LockError, match="not a person's account"):
        floorlock.acl_plan(guards.config.load(), sid, nt=True)


def test_the_acl_step_is_windows_only(tmp_path, monkeypatch):
    _acl_brain(tmp_path, monkeypatch)
    with pytest.raises(floorlock.LockError, match="Windows deny entry"):
        floorlock.acl_plan(guards.config.load(), SID, nt=False)


def _plan(home="H", files=("H/settings.json",), trees=("H/hooks",), folders=("P/.claude",)):
    return {"account": SID, "home": home, "files": list(files), "trees": list(trees), "folders": list(folders),
            "create": []}


def test_the_commands_give_each_path_to_the_administrators_then_deny_the_account():
    sid, q = f"*{SID}", ["/C", "/Q"]
    cmds = [c[1:] for c in floorlock.acl_commands(_plan(), nt=True)]
    assert cmds == [["H", "/setowner", "*S-1-5-32-544", *q], ["H", "/deny", f"{sid}:(DC,WDAC,WO)", *q],
                    ["H/settings.json", "/setowner", "*S-1-5-32-544", *q],
                    ["H/settings.json", "/deny", f"{sid}:(WD,AD,WEA,WA,D,WDAC,WO)", *q],
                    ["P/.claude", "/setowner", "*S-1-5-32-544", *q],
                    ["P/.claude", "/deny", f"{sid}:(WD,AD,WEA,WA,D,DC,WDAC,WO)", *q],
                    ["H/hooks", "/deny", f"{sid}:(OI)(CI)(WD,AD,WEA,WA,D,DC,WDAC,WO)", *q],
                    [os.path.join("H/hooks", "*"), "/reset", "/T", *q],
                    ["H/hooks", "/setowner", "*S-1-5-32-544", "/T", *q]]
    for c in cmds:   # never icacls' W, M or F: they carry SYNCHRONIZE and READ_CONTROL, and the files must still read
        assert not any(":" in w and ("(W)" in w or "(M)" in w or "F)" in w) for w in c), c
    undo = [c[1:] for c in floorlock.acl_undo(_plan(), nt=True)]
    assert undo[:2] == [["H", "/remove:d", sid, *q], ["H", "/setowner", sid, *q]]   # the deny entry goes first
    assert undo[-2:] == [["H/hooks", "/remove:d", sid, "/T", *q], ["H/hooks", "/setowner", sid, "/T", *q]]


def test_the_rights_masks():
    assert floorlock._mask(floorlock.ACL_FILE) == 0x2 | 0x4 | 0x10 | 0x100 | 0x10000 | 0x40000 | 0x80000
    assert floorlock._mask(floorlock.ACL_TREE) == floorlock._mask(floorlock.ACL_FOLDER) == \
        floorlock._mask(floorlock.ACL_FILE) | 0x40
    assert floorlock._mask(floorlock.ACL_HOME) == 0x40 | 0x40000 | 0x80000
    assert not floorlock._mask(floorlock.ACL_FILE) & (0x100000 | 0x20000)   # never SYNCHRONIZE nor READ_CONTROL
    assert floor.WRITE_RIGHTS & ~floorlock._mask(floorlock.ACL_FOLDER) == 0   # what the per-call check asks: all


def test_verify_finds_a_missing_path_an_owner_and_a_right_not_denied(tmp_path, monkeypatch):
    h = tmp_path / "h"
    (h / "hooks" / "x").mkdir(parents=True)
    (h / "settings.json").write_text("{}", encoding="utf-8")
    a = _plan(str(h), [str(h / "settings.json"), str(h / "gone.json")], [str(h / "hooks")], [])
    monkeypatch.setattr(floor, "owner", lambda p: "S-1-5-32-544")
    full = lambda p, sid: 0xFFFFF   # noqa: E731 - every right denied
    assert floorlock.acl_verify(a, denied=full) == [f"{h / 'gone.json'}: missing"]
    partial = lambda p, sid: floorlock._mask(floorlock.ACL_FILE) if "hooks" in str(p) else 0xFFFFF   # noqa: E731
    wrong = floorlock.acl_verify({**a, "files": [str(h / "settings.json")]}, denied=partial)
    assert wrong == [f"{h / 'hooks'}: {SID} not denied DC", f"{h / 'hooks' / 'x'}: {SID} not denied DC"]
    monkeypatch.setattr(floor, "owner", lambda p: SID)
    assert all("owned by" in w for w in floorlock.acl_verify({**a, "files": [], "trees": []}, denied=full))


def _applier(ran: list, account=SID, acl_check=lambda a: []):
    def run(cmd, **kw):
        ran.append((cmd, floor.managed_file().exists(), (floor.lock_dir() / floor.LOCK_FILE).exists()))
        return _Done()

    def apply(check=lambda p: [], **kw):
        return floorlock.apply(guards.config.load(), run=run, is_elevated=lambda: True, install=_install,
                               tools=lambda check: {}, check=check, account=account, acl_check=acl_check, **kw)
    return apply, run


@nt
def test_the_apply_denies_the_account_its_files_before_the_hooks_and_the_lock(tmp_path, monkeypatch):
    _acl_brain(tmp_path, monkeypatch)
    with pytest.raises(floorlock.LockError, match="--account"):
        floorlock.apply(guards.config.load(), is_elevated=lambda: True)
    ran = []
    apply, _ = _applier(ran)
    out = apply()
    lock = floor.read_lock()
    a = lock["acl"]
    assert a["account"] == SID and lock["floor"] == {"refuse": False, "only": True}
    assert set(a["files"]) | set(a["trees"]) | set(a["folders"]) <= set(lock["checks"])   # checked on each call
    assert a["home"] not in lock["checks"]                    # ~/.claude itself takes Claude Code's own new files
    home = Path(a["home"])
    assert json.loads((home / "settings.local.json").read_text(encoding="utf-8")) == {} and (home / "agents").is_dir()
    denies = [(cmd, managed, locked) for cmd, managed, locked in ran if "/deny" in cmd and SID in cmd[3]]
    assert len(denies) == len(a["files"]) + len(a["trees"]) + len(a["folders"]) + 1
    assert not any(managed or locked for _, managed, locked in denies)   # before the managed hooks and the lock file
    assert any("paths denied to" in line for line in out)


@nt
def test_a_failed_acl_step_is_undone_and_leaves_no_lock(tmp_path, monkeypatch):
    _acl_brain(tmp_path, monkeypatch)
    ran = []
    apply, _ = _applier(ran, acl_check=lambda a: [f"{a['files'][0]}: {SID} not denied WD"])
    with pytest.raises(floorlock.LockError, match="the ACL step: .* not denied WD"):
        apply()
    assert floor.read_lock() is None and not floor.managed_file().exists()
    removed = [cmd for cmd, *_ in ran if "/remove:d" in cmd]
    assert removed and all(cmd[3] == f"*{SID}" for cmd in removed)   # given back


@nt
def test_a_failed_relock_keeps_the_entries_the_previous_lock_held(tmp_path, monkeypatch):
    _acl_brain(tmp_path, monkeypatch)
    apply, _ = _applier([])
    apply()
    held = (floor.lock_dir() / floor.LOCK_FILE).read_bytes()
    ran = []
    again, _ = _applier(ran)
    with pytest.raises(floorlock.LockError):
        again(check=lambda p: ["x: owned by S-1-5-21-x"] if p == floor.lock_dir() else [])
    assert (floor.lock_dir() / floor.LOCK_FILE).read_bytes() == held                  # the previous lock, whole
    assert not [cmd for cmd, *_ in ran if "/remove:d" in cmd]                         # and its ACL with it


@nt
def test_a_relock_without_acl_gives_the_previous_entries_back(tmp_path, monkeypatch):
    cfg = _acl_brain(tmp_path, monkeypatch)
    apply, _ = _applier([])
    apply()
    data = json.loads(cfg.read_text(encoding="utf-8"))
    data["floor"] = {"only": True}
    cfg.write_text(json.dumps(data), encoding="utf-8")
    ran = []
    again, _ = _applier(ran, account=None)
    out = again()
    assert "acl" not in floor.read_lock()
    assert [cmd for cmd, *_ in ran if "/remove:d" in cmd] and any("given back" in line for line in out)


@nt
def test_unlock_gives_the_files_back_first_and_stops_whole_when_it_cannot(tmp_path, monkeypatch):
    _acl_brain(tmp_path, monkeypatch)
    apply, _ = _applier([])
    apply()
    failing = lambda cmd, **kw: type("R", (), {"returncode": 5, "stdout": "", "stderr": "denied"})()   # noqa: E731
    with pytest.raises(floorlock.LockError, match="the lock is whole"):
        floorlock.unlock(is_elevated=lambda: True, run=failing)
    assert floor.read_lock() is not None and floor.managed_file().exists()
    ran = []
    out = floorlock.unlock(is_elevated=lambda: True, run=lambda cmd, **kw: (ran.append(cmd), _Done())[1])
    assert floor.read_lock() is None and "unlocked" in out[0]
    assert ran and all("/remove:d" in c or "/setowner" in c for c in ran)


@nt
def test_the_plan_prints_the_acl_step_and_the_command_carries_the_account(tmp_path, monkeypatch):
    _acl_brain(tmp_path, monkeypatch)
    p = floorlock.plan(guards.config.load(), SID)
    text = "\n".join(floorlock.render_plan(p))
    assert "The ACL step (config.json floor.acl)" in text and SID in text and "makes first" in text
    assert "brain floor unlock" in text and "always allow" in text
    assert floorlock.run_command(p).split()[-3:] == ["--account", SID, "--wait"]
    assert "--account" not in floorlock.run_command(p, "unlock")


def test_the_guard_refuses_every_call_while_an_acl_path_is_reachable_or_gone(tmp_path, monkeypatch):
    """The per-call check (brain.floor.unlocked) reads the lock's checks, the ACL step's paths among them."""
    cfg = _setup(tmp_path, monkeypatch, only=True)
    settings = tmp_path / "profile" / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{}", encoding="utf-8")
    _lock(cfg, {"refuse": False, "only": True}, checks=[settings])
    c = guards.config.load()
    fl = floor.effective(c, floor.read_lock())
    held = lambda p: False   # noqa: E731 - an administrator's file
    assert floor.unlocked(c, fl, floor.read_lock(), writable=held) == ""
    assert "writable by this session" in floor.unlocked(c, fl, floor.read_lock(),
                                                        writable=lambda p: str(p) == str(settings))
    settings.unlink()                        # removed through ~/.claude, or ~/.claude renamed through the profile
    assert "is missing" in floor.unlocked(c, fl, floor.read_lock(), writable=held)


def test_status_says_whether_the_acl_paths_are_held(tmp_path, monkeypatch):
    cfg = _setup(tmp_path, monkeypatch, only=True)
    f = tmp_path / "s.json"
    f.write_text("{}", encoding="utf-8")
    lock = _lock(cfg, {"refuse": False, "only": True})
    data = json.loads(lock.read_text(encoding="utf-8"))
    data["acl"] = {"account": SID, "home": str(tmp_path), "files": [str(f), str(tmp_path / "gone")], "trees": [],
                   "folders": []}
    lock.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(floor, "writable", lambda p: False)
    text = "\n".join(floorlock.status(guards.config.load()))
    assert f"acl: {SID} denied 2 paths; NOT held: {tmp_path / 'gone'} missing" in text
    monkeypatch.setattr(floor, "writable", lambda p: True)
    assert f"{f} writable" in "\n".join(floorlock.status(guards.config.load()))


def test_the_command_line_takes_the_account(tmp_path, monkeypatch, capsys):
    from brain import cli
    _acl_brain(tmp_path, monkeypatch)
    monkeypatch.setattr("brain.floorlock.elevated", lambda: False)
    assert cli.main(["floor", "lock", "--apply", "--account", SID]) == 2 and "never elevates" in capsys.readouterr().err


def test_the_account_and_its_profile():
    if os.name == "nt":
        assert floorlock.ACCOUNT.match(floor.account())   # this process's own: a person's account
    else:
        assert floor.account() == ""
    assert floor.profile(SID) == floor.PROFILE_DIR   # the tests' own (conftest)


@pytest.mark.skipif(os.name != "nt", reason="Windows' ACLs")
def test_a_real_acl_step_on_a_scratch_profile(tmp_path, monkeypatch):
    """The ACL step's icacls commands for real, on a scratch profile and this process's own account: only in an
    elevated terminal (CI's Windows runner); verify() then finds every right denied, and undo gives it all back."""
    if not floorlock.elevated():
        pytest.skip("needs an elevated terminal: a session never elevates")
    import subprocess
    sid = floor.account()
    home = tmp_path / "profile" / ".claude"
    (home / "hooks" / "sub").mkdir(parents=True)
    (home / "hooks" / "sub" / "h.sh").write_text("x", encoding="utf-8")
    (home / "settings.json").write_text("{}", encoding="utf-8")
    a = {"account": sid, "home": str(home), "files": [str(home / "settings.json")], "trees": [str(home / "hooks")],
         "folders": [], "create": []}
    try:
        for cmd in floorlock.acl_commands(a):
            assert subprocess.run(cmd, capture_output=True, timeout=300).returncode == 0, cmd
        assert floorlock.acl_verify(a) == []
        assert floorlock.denied(home / "hooks" / "sub" / "h.sh", sid) & floorlock._mask(floorlock.ACL_FOLDER) == \
            floorlock._mask(floorlock.ACL_FOLDER)
        assert json.loads((home / "settings.json").read_text(encoding="utf-8")) == {}   # still readable
    finally:
        for cmd in floorlock.acl_undo(a):
            subprocess.run(cmd, capture_output=True, timeout=300)
    assert floorlock.denied(home / "settings.json", sid) == 0 and floor.owner(home / "settings.json") == sid
