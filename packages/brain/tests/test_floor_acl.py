"""The floor's ACL step (wi-brain-floor-acl-lock; brain.flooracl, run by brain.floorlock; docs/guards.md « The ACL
step »): under config.json floor.only with floor.acl (off by default), brain floor lock --apply denies the account the
sessions run as every change of its Claude Code settings, hooks, skills, commands, agents and plugins and of its
projects' settings, and brain floor unlock --apply gives them back. No test changes a real ACL: the commands go to a
fake runner, the profile is the tests' own (conftest's floor.PROFILE_DIR); one test runs icacls on a scratch folder,
elevated only."""

import json
import os
from pathlib import Path

import pytest
from brain import floor, flooracl, floorlock, guards
from test_floorlock import _Done, _install, _lock, _setup

SID = "S-1-5-21-1111111111-2222222222-3333333333-1001"
nt = pytest.mark.skipif(os.name != "nt", reason="floor.acl is a Windows deny entry")
REAL_ACCOUNT, REAL_KIND, REAL_OWNER = floor.account, floor.sid_kind, floor.owner


def USER(sid):
    return flooracl.SID_TYPE_USER   # the tests' account is a user's


@pytest.fixture(autouse=True)
def a_user(monkeypatch):
    """The tests' SID looks up as a user's, and the guard's own account is it."""
    monkeypatch.setattr(floor, "sid_kind", USER)
    monkeypatch.setattr(floor, "account", lambda: SID)
    monkeypatch.setattr(floor, "owner", lambda p: SID)   # the account's own files, before any lock
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)


def _acl_brain(tmp_path, monkeypatch, acl=True, only=True, project=True):
    """A floor-only brain with floor.acl, a registry naming one project with its own .claude settings and hooks; the
    profile's ~/.claude holds settings.json, hooks and plugins (the rest is missing)."""
    section = {"only": True} if only else {"refuse": True}
    cfg = _setup(tmp_path, monkeypatch, **section, acl=acl)
    home = floor.profile(SID) / ".claude"
    for d in ("hooks", "plugins"):
        (home / d).mkdir(parents=True, exist_ok=True)
    (home / "hooks" / "h.sh").write_text("exit 0", encoding="utf-8")
    (home / "settings.json").write_text("{}", encoding="utf-8")
    if project:
        lab = tmp_path / "lab"
        (lab / ".claude" / "hooks").mkdir(parents=True)
        (lab / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
        (cfg.parent / "projects.yaml").write_text("lab: {root: ../lab}\n", encoding="utf-8")
    return cfg


def test_the_acl_step_is_off_by_default_and_asked_under_floor_only(tmp_path, monkeypatch):
    _acl_brain(tmp_path, monkeypatch, acl=False)
    assert floorlock.plan(guards.config.load())["acl"] is None
    assert not [ln for ln in floorlock.status(guards.config.load()) if ln.startswith("acl:")]   # not asked: unsaid
    again = tmp_path / "again"
    again.mkdir()
    cfg = _acl_brain(again, monkeypatch, only=False)                    # floor.refuse alone: not asked
    assert not flooracl.wanted(guards.config.load()) and floorlock.plan(guards.config.load())["acl"] is None
    data = json.loads(cfg.read_text(encoding="utf-8"))
    data["floor"] = {"only": True, "acl": "yes"}                        # a bool or nothing
    cfg.write_text(json.dumps(data), encoding="utf-8")
    assert not flooracl.wanted(guards.config.load())


def test_the_plan_names_the_account_s_files_and_its_projects(tmp_path, monkeypatch):
    _acl_brain(tmp_path, monkeypatch)
    a = flooracl.plan(guards.config.load(), SID, nt=True)
    home = floor.profile(SID) / ".claude"
    lab = Path(os.path.realpath(tmp_path / "lab"))
    personal = Path(os.path.realpath(tmp_path / "personal"))
    assert a["account"] == SID and a["home"] == str(home)
    assert a["files"] == [str(home / "settings.json"), str(home / "settings.local.json"),
                          str(lab / ".claude" / "settings.json")]
    assert a["trees"] == [*(str(home / n) for n in ("hooks", "skills", "commands", "agents", "plugins")),
                          str(lab / ".claude" / "hooks")]          # a project's customization too (review #4)
    assert a["folders"] == [str(personal / ".claude"), str(lab / ".claude")]
    assert a["create"] == [str(home / "settings.local.json"), *(str(home / n) + os.sep for n in
                                                                ("skills", "commands", "agents")),
                           str(personal / ".claude") + os.sep, str(personal / ".claude" / "worktrees") + os.sep,
                           str(lab / ".claude" / "worktrees") + os.sep]   # made first: none can be made later


@pytest.mark.parametrize("sid", ["", "S-1-5-32-544", "S-1-5-18", "S-1-1-0", "ada", "S-1-5-21-1 /grant x:F",
                                 SID + "\n", SID + " "])
def test_the_plan_refuses_an_account_that_is_not_a_person_s(tmp_path, monkeypatch, sid):
    _acl_brain(tmp_path, monkeypatch)
    with pytest.raises(floorlock.LockError, match="not a person's account"):
        flooracl.plan(guards.config.load(), sid, nt=True)


def test_the_plan_refuses_a_group_an_unknown_profile_and_a_registry_that_does_not_load(tmp_path, monkeypatch):
    cfg = _acl_brain(tmp_path, monkeypatch)
    with pytest.raises(floorlock.LockError, match="not a person's account"):   # Domain Users is a group (review #10)
        flooracl.plan(guards.config.load(), SID, nt=True, kind=lambda s: 2)
    with monkeypatch.context() as m:
        m.setattr(floor, "profile", lambda sid, fallback=True: None)
        with pytest.raises(floorlock.LockError, match="no profile folder"):
            flooracl.plan(guards.config.load(), SID, nt=True)
    (cfg.parent / "projects.yaml").write_text("lab: [not, a, mapping\n", encoding="utf-8")
    with pytest.raises(floorlock.LockError, match="registry beside config.json does not load"):   # review #7
        flooracl.plan(guards.config.load(), SID, nt=True)


def test_the_acl_step_is_windows_only(tmp_path, monkeypatch):
    _acl_brain(tmp_path, monkeypatch)
    with pytest.raises(floorlock.LockError, match="Windows deny entry"):
        flooracl.plan(guards.config.load(), SID, nt=False)


def _plan(home="H", files=("H/settings.json",), trees=("H/hooks",), folders=("P/.claude",)):
    return {"account": SID, "home": home, "files": list(files), "trees": list(trees), "folders": list(folders),
            "create": []}


def test_the_commands_act_on_the_path_itself_and_deny_the_account():
    """Each path's owner made Administrators and its deny added by one command on one handle (deny_exact): ~/.claude
    first, a project's .claude before what it holds, a tree's root before its walk."""
    sid, own = f"*{SID}", ["/setowner", "*S-1-5-32-544", "/L"]
    full = flooracl.commands(_plan())
    assert {c[0] for c in full} == {flooracl.DENY}   # no icacls: its /setowner and /deny under /C hid a failure
    cmds = [c[1:] for c in full]
    assert cmds == [["H", "/deny", f"{sid}:(DC,WDAC,WO)", *own],
                    ["P/.claude", "/deny", f"{sid}:(WD,AD,WEA,WA,D,DC,WDAC,WO)", *own],
                    ["H/settings.json", "/deny", f"{sid}:(WD,AD,WEA,WA,DC,D,WDAC,WO)", *own],
                    ["H/hooks", "/deny", f"{sid}:(OI)(CI)(WD,AD,WEA,WA,D,DC,WDAC,WO)", *own]]
    assert not [c for c in cmds if "/T" in c or any("*" in w and not w.startswith("*S-") for w in c)]   # round 2
    for c in cmds:   # never icacls' W, M or F: they carry SYNCHRONIZE and READ_CONTROL, and the files must still read
        assert not any(":" in w and ("(W)" in w or "(M)" in w or "F)" in w) for w in c), c


def test_undo_gives_back_only_what_is_still_the_lock_s(tmp_path):
    h = tmp_path / "h"
    (h / "hooks").mkdir(parents=True)
    (h / "settings.json").write_text("{}", encoding="utf-8")
    (h / "hooks" / "x.sh").write_text("x", encoding="utf-8")
    a = _plan(str(h), [str(h / "settings.json"), str(h / "gone.json")], [str(h / "hooks")], [])
    cmds, left = flooracl.undo(a, owner=lambda p: "S-1-5-32-544")
    sid = f"*{SID}"
    assert {c[0] for c in cmds} == {flooracl.UNDENY}   # never icacls' /remove:d: its own deny refused it, /C hid that
    assert [c[1:] for c in cmds] == [[str(h / "hooks"), "/remove:d", sid, "/L"],          # trees first, entry by entry
                                     [str(h / "hooks" / "x.sh"), "/remove:d", sid, "/L", "/inherited"],
                                     [str(h / "settings.json"), "/remove:d", sid, "/L"],
                                     [str(h), "/remove:d", sid, "/L"]]                     # ~/.claude last
    assert not [c for c in cmds if "/setowner" in c or "/T" in c]   # round 3: an elevated step gives no owner away
    assert left == [f"{h / 'gone.json'}: gone"]                     # a recorded path gone: skipped (review #6)
    cmds, left = flooracl.undo(a, owner=lambda p: SID)     # a folder a session made again: never handed over
    assert cmds == [] and all("not owned by Administrators" in x or "gone" in x for x in left)


def test_the_rights_masks_hold_what_the_per_call_check_reads():
    """Review #1: a file's deny must hold every right of WRITE_RIGHTS, DELETE_CHILD included (a file's inherited
    FullControl grants it, and AccessCheck then says writable)."""
    for rights in (flooracl.FILE, flooracl.TREE, flooracl.FOLDER):
        assert floor.WRITE_RIGHTS & ~flooracl.mask_of(rights) == 0, rights
        assert not flooracl.mask_of(rights) & (0x100000 | 0x20000)   # never SYNCHRONIZE nor READ_CONTROL
    assert flooracl.mask_of(flooracl.HOME) == 0x40 | 0x40000 | 0x80000


def test_links_are_found_before_any_command(tmp_path):
    """Review #2: an elevated icacls follows a link; the apply refuses any among its paths, or under its trees, and
    undo leaves them alone."""
    h = tmp_path / "h"
    (h / "hooks").mkdir(parents=True)
    target = tmp_path / "system"
    target.mkdir()
    try:
        import _winapi
        _winapi.CreateJunction(str(target), str(h / "agents"))
        _winapi.CreateJunction(str(target), str(h / "hooks" / "inner"))
    except (ImportError, OSError):
        pytest.skip("no junction")
    a = _plan(str(h), [], [str(h / "hooks"), str(h / "agents")], [])
    assert set(flooracl.all_links(a)) == {str(h / "agents"), str(h / "hooks" / "inner")}
    cmds, left = flooracl.undo(a, owner=lambda p: "S-1-5-32-544")
    assert not [c for c in cmds if str(h / "agents") in c or str(h / "hooks") in c]
    assert any("a link or a junction" in x for x in left)


def test_verify_finds_what_is_not_held(tmp_path, monkeypatch):
    h = tmp_path / "h"
    (h / "hooks" / "x").mkdir(parents=True)
    (h / "settings.json").write_text("{}", encoding="utf-8")
    a = _plan(str(h), [str(h / "settings.json"), str(h / "gone.json")], [str(h / "hooks")], [])
    monkeypatch.setattr(floor, "owner", lambda p: "S-1-5-32-544")

    def full(p, sid):
        return flooracl.mask_of(flooracl.TREE)

    def none(p):
        return []
    assert flooracl.verify(a, denied=full, writers=none) == [f"{h / 'gone.json'}: missing"]

    def partial(p, sid):
        return flooracl.mask_of(flooracl.FILE) & ~0x40 if "hooks" in str(p) else flooracl.mask_of(flooracl.TREE)
    wrong = flooracl.verify({**a, "files": [str(h / "settings.json")]}, denied=partial, writers=none)
    assert wrong == [f"{h / 'hooks'}: {SID} not denied DC", f"{h / 'hooks' / 'x'}: {SID} not denied DC"]

    def allowed(p):   # an allow of its own, ahead of the inherited deny (review #9)
        return [SID] if p.endswith("x") else []
    assert flooracl.verify({**a, "files": []}, denied=full, writers=allowed) == \
        [f"{h / 'hooks' / 'x'}: an entry of its own lets {SID} write"]
    monkeypatch.setattr(floor, "owner", lambda p: SID)
    assert all("owned by" in w for w in flooracl.verify({**a, "files": [], "trees": []}, denied=full, writers=none))


def test_minus_keeps_what_the_previous_lock_held():
    a = _plan(files=("H/settings.json", "Q/.claude/settings.json"), folders=("P/.claude", "Q/.claude"))
    rest = flooracl.minus(a, _plan())
    assert rest["home"] is None and rest["files"] == ["Q/.claude/settings.json"] and rest["trees"] == []
    assert rest["folders"] == ["Q/.claude"]
    assert flooracl.minus(a, {**_plan(), "account": "S-1-5-21-9-9-9-9"}) == a   # another account's: all is new


def _applier(ran: list, account=SID, acl_check=lambda a: []):
    def run(cmd, **kw):
        ran.append((cmd, floor.managed_file().exists(), (floor.lock_dir() / floor.LOCK_FILE).exists()))
        return _Done()

    def apply(check=lambda p: [], **kw):
        return floorlock.apply(guards.config.load(), run=run, is_elevated=lambda: True, install=_install,
                               tools=lambda check: {}, check=check, account=account, acl_check=acl_check, **kw)
    return apply


@pytest.fixture
def admins_own(monkeypatch):
    monkeypatch.setattr(floor, "owner", lambda p: "S-1-5-32-544")


@nt
def test_the_apply_denies_the_account_its_files_before_the_hooks_and_the_lock(tmp_path, monkeypatch, admins_own):
    _acl_brain(tmp_path, monkeypatch)
    with pytest.raises(floorlock.LockError, match="--account"):
        floorlock.apply(guards.config.load(), is_elevated=lambda: True)
    ran = []
    out = _applier(ran)()
    lock = floor.read_lock()
    a = lock["acl"]
    assert a["account"] == SID and lock["floor"] == {"refuse": False, "only": True}
    assert not (set(a["files"]) | set(a["trees"]) | set(a["folders"])) & set(lock["checks"])   # _acl_held reads them
    home = Path(a["home"])
    assert json.loads((home / "settings.local.json").read_text(encoding="utf-8")) == {} and (home / "agents").is_dir()
    _the_acl_commands_ran_in_order(ran, a, home)
    assert any("paths denied to" in line for line in out)


def _the_acl_commands_ran_in_order(ran, a, home):
    denies = [(cmd, managed, locked) for cmd, managed, locked in ran if "/deny" in cmd and SID in cmd[3]]
    denied_paths = [cmd[1] for cmd, *_ in denies]
    assert str(home / "hooks" / "h.sh") in denied_paths                   # a tree's entry, one at a time
    assert set(a["files"]) | set(a["trees"]) | set(a["folders"]) | {a["home"]} <= set(denied_paths)
    assert not [c for c, *_ in ran if c[1].startswith(str(home)) and ("/T" in c or "/reset" in c)]
    assert not any(managed or locked for _, managed, locked in denies)   # before the managed hooks and the lock file


@nt
def test_the_apply_refuses_a_link_among_its_paths(tmp_path, monkeypatch, admins_own):
    _acl_brain(tmp_path, monkeypatch)
    home = floor.profile(SID) / ".claude"
    try:
        import _winapi
        _winapi.CreateJunction(str(tmp_path), str(home / "agents"))
    except (ImportError, OSError):
        pytest.skip("no junction")
    ran = []
    with pytest.raises(floorlock.LockError, match="link or a junction"):
        _applier(ran)()
    assert not ran and floor.read_lock() is None   # nothing run, not even the guard's copy


@nt
def test_a_failed_acl_step_is_undone_and_leaves_no_lock(tmp_path, monkeypatch, admins_own):
    _acl_brain(tmp_path, monkeypatch)
    ran = []
    with pytest.raises(floorlock.LockError, match="the ACL step: .* not denied WD"):
        _applier(ran, acl_check=lambda a: [f"{a['files'][0]}: {SID} not denied WD"])()
    assert floor.read_lock() is None and not floor.managed_file().exists()
    removed = [cmd for cmd, *_ in ran if "/remove:d" in cmd]
    assert removed and all(cmd[3] == f"*{SID}" for cmd in removed)   # given back


@nt
def test_a_failed_relock_gives_back_only_what_it_added(tmp_path, monkeypatch, admins_own):
    """Review #5: the previous lock, restored, keeps its entries; only what the failed relock added goes back."""
    cfg = _acl_brain(tmp_path, monkeypatch)
    _applier([])()
    held = (floor.lock_dir() / floor.LOCK_FILE).read_bytes()
    lab2 = tmp_path / "lab2"
    (lab2 / ".claude").mkdir(parents=True)
    (cfg.parent / "projects.yaml").write_text("lab: {root: ../lab}\nlab2: {root: ../lab2}\n", encoding="utf-8")
    ran = []
    with pytest.raises(floorlock.LockError):
        _applier(ran)(check=lambda p: ["x: owned by S-1-5-21-x"] if p == floor.lock_dir() else [])
    assert (floor.lock_dir() / floor.LOCK_FILE).read_bytes() == held                  # the previous lock, whole
    removed = [cmd[1] for cmd, *_ in ran if "/remove:d" in cmd]
    assert removed == [str(Path(os.path.realpath(lab2)) / ".claude")]                 # and its entries with it


@nt
def test_a_relock_without_acl_gives_the_previous_entries_back(tmp_path, monkeypatch, admins_own):
    cfg = _acl_brain(tmp_path, monkeypatch)
    _applier([])()
    data = json.loads(cfg.read_text(encoding="utf-8"))
    data["floor"] = {"only": True}
    cfg.write_text(json.dumps(data), encoding="utf-8")
    ran = []
    out = _applier(ran, account=None)()
    assert "acl" not in floor.read_lock()
    assert [cmd for cmd, *_ in ran if "/remove:d" in cmd] and any("given back" in line for line in out)


@nt
def test_unlock_gives_the_files_back_first_and_stops_whole_when_it_cannot(tmp_path, monkeypatch, admins_own):
    _acl_brain(tmp_path, monkeypatch)
    _applier([])()

    def failing(cmd, **kw):
        return type("R", (), {"returncode": 5, "stdout": "", "stderr": "denied"})()
    with pytest.raises(floorlock.LockError, match="the managed hooks stay; these deny entries are still there"):
        floorlock.unlock(is_elevated=lambda: True, run=failing)
    assert floor.read_lock() is not None and floor.managed_file().exists()
    ran = []
    out = floorlock.unlock(is_elevated=lambda: True, run=lambda cmd, **kw: (ran.append(cmd), _Done())[1])
    assert floor.read_lock() is None and "unlocked" in out[0]
    assert ran and all("/remove:d" in c or "/setowner" in c for c in ran)


@nt
def test_unlock_of_an_unreadable_lock_needs_the_account(tmp_path, monkeypatch, admins_own):
    """Review #6: a lock file that cannot be read says nothing of its ACL step: the unlock stops until --account
    names the account, whose paths it rebuilds from config.json."""
    _acl_brain(tmp_path, monkeypatch)
    _applier([])()
    (floor.lock_dir() / floor.LOCK_FILE).write_text("{oops", encoding="utf-8")
    with pytest.raises(floorlock.LockError, match="--account SID"):
        floorlock.unlock(is_elevated=lambda: True, run=lambda cmd, **kw: _Done())
    ran = []
    floorlock.unlock(is_elevated=lambda: True, run=lambda cmd, **kw: (ran.append(cmd), _Done())[1],
                     cfg=guards.config.load(), account=SID)
    assert floor.read_lock() is None and [c for c in ran if "/remove:d" in c]


@nt
def test_the_plan_prints_the_acl_step_and_the_command_carries_the_account(tmp_path, monkeypatch):
    _acl_brain(tmp_path, monkeypatch)
    p = floorlock.plan(guards.config.load(), SID)
    text = "\n".join(floorlock.render_plan(p))
    assert "The ACL step (config.json floor.acl)" in text and SID in text and "makes first" in text
    assert "brain floor unlock" in text and "always allow" in text
    assert floorlock.run_command(p).split()[-3:] == ["--account", SID, "--wait"]
    assert "--account" not in floorlock.run_command(p, "unlock")


def _acl_lock(tmp_path, monkeypatch, paths, account=SID):
    cfg = _setup(tmp_path, monkeypatch, only=True, acl=True)
    lock = _lock(cfg, {"refuse": False, "only": True}, checks=paths)
    data = json.loads(lock.read_text(encoding="utf-8"))
    data["acl"] = {"account": account, "home": str(tmp_path / "profile" / ".claude"), "files": [str(p) for p in paths], "trees": [],
                   "folders": []}
    lock.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profile"))
    monkeypatch.setenv("HOME", str(tmp_path / "profile"))
    c = guards.config.load()
    return c, floor.effective(c, floor.read_lock())


@nt   # floor.acl counts on Windows only: elsewhere a lock with an ACL step is not the locked config's (_held_config)
def test_the_guard_refuses_every_call_while_an_acl_path_is_not_held(tmp_path, monkeypatch):
    """The per-call check (brain.floor.unlocked): each path present, out of reach and owned by the administrators
    (review #3: a folder made again with a read-only DACL of its own is not), the account the session's (#8),
    no CLAUDE_CONFIG_DIR, config.json's floor.acl the locked one (#7)."""
    settings = tmp_path / "profile" / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{}", encoding="utf-8")
    c, fl = _acl_lock(tmp_path, monkeypatch, [settings])

    def held(p):   # an administrator's file
        return False
    monkeypatch.setattr(floor, "owner", lambda p: "S-1-5-32-544")
    assert floor.unlocked(c, fl, floor.read_lock(), writable=held) == ""
    assert "writable by this session" in floor.unlocked(c, fl, floor.read_lock(),
                                                        writable=lambda p: str(p) == str(settings))
    if os.name == "nt":
        monkeypatch.setattr(floor, "owner", lambda p: SID)
        assert "not owned by the administrators" in floor.unlocked(c, fl, floor.read_lock(), writable=held)
        monkeypatch.setattr(floor, "owner", lambda p: "S-1-5-32-544")
    monkeypatch.setattr(floor, "account", lambda: "S-1-5-21-9-9-9-1002")
    assert "not this session's account" in floor.unlocked(c, fl, floor.read_lock(), writable=held)
    monkeypatch.setattr(floor, "account", lambda: "")                       # unread: refused (round 2)
    assert "not this session's account" in floor.unlocked(c, fl, floor.read_lock(), writable=held)
    monkeypatch.setattr(floor, "account", lambda: SID)
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "elsewhere"))          # Claude Code's home moved (round 2)
    assert "USERPROFILE moves" in floor.unlocked(c, fl, floor.read_lock(), writable=held)
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profile"))
    for home in ("/u/a", "H:\\", str(tmp_path / "elsewhere")):           # HOME is not node's home (round 3)
        monkeypatch.setenv("HOME", home)
        assert floor.unlocked(c, fl, floor.read_lock(), writable=held) == ""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "elsewhere"))
    assert "CLAUDE_CONFIG_DIR" in floor.unlocked(c, fl, floor.read_lock(), writable=held)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR")
    cfg = Path(os.environ["BRAIN_CONFIG"])
    cfg.write_text(json.dumps({"v": 1, "floor": {"only": True}}), encoding="utf-8")   # floor.acl off: not the locked
    assert "floor.acl" in floor.unlocked(guards.config.load(), fl, floor.read_lock(), writable=held)
    cfg.write_text(json.dumps({"v": 1, "floor": {"only": True, "acl": True}}), encoding="utf-8")
    settings.unlink()                        # removed through ~/.claude, or ~/.claude renamed through the profile
    assert "is missing" in floor.unlocked(guards.config.load(), fl, floor.read_lock(), writable=held)


def test_status_says_whether_the_acl_paths_are_held(tmp_path, monkeypatch):
    f = tmp_path / "s.json"
    f.write_text("{}", encoding="utf-8")
    _acl_lock(tmp_path, monkeypatch, [f, tmp_path / "gone"])
    monkeypatch.setattr(floor, "writable", lambda p: False)
    monkeypatch.setattr(floor, "owner", lambda p: "S-1-5-32-544")
    text = "\n".join(floorlock.status(guards.config.load()))
    assert f"acl: {SID} denied 2 paths; NOT held: {tmp_path / 'gone'} missing" in text
    monkeypatch.setattr(floor, "writable", lambda p: True)
    assert f"{f} writable" in "\n".join(floorlock.status(guards.config.load()))


def test_the_command_line_takes_the_account(tmp_path, monkeypatch, capsys):
    from brain import cli
    _acl_brain(tmp_path, monkeypatch)
    monkeypatch.setattr("brain.floorlock.elevated", lambda: False)
    assert cli.main(["floor", "lock", "--apply", "--account", SID]) == 2 and "never elevates" in capsys.readouterr().err
    assert cli.main(["floor", "unlock", "--apply", "--account", SID]) == 2


def test_the_account_its_kind_and_its_profile():
    if os.name == "nt":
        me = REAL_ACCOUNT()
        assert flooracl.ACCOUNT.fullmatch(me) and REAL_KIND(me) == flooracl.SID_TYPE_USER   # this process's own
        assert REAL_KIND("S-1-5-32-544") == 4                                               # an alias: a group
    else:
        assert REAL_ACCOUNT() == "" and REAL_KIND(SID) == 0
    assert floor.profile(SID) == floor.PROFILE_DIR   # the tests' own (conftest)


@pytest.mark.skipif(os.name != "nt", reason="Windows' ACLs")
def test_a_real_acl_step_on_a_scratch_profile(tmp_path, monkeypatch):
    """The step for real, on a scratch profile and this process's own account: only in an elevated terminal (CI's
    Windows runner). The elevated step runs as the account it denies, under pytest's folders whose OWNER RIGHTS entry
    takes the owner's implicit WRITE_DAC away: CI round 4 (each child's deny, propagated from its tree's root, refused
    the child's own next ACL write, error 5). verify() then finds every right denied, a write refused and a read
    still served; a relock changes nothing; undo lifts every deny (the owner stays the administrators'). The real
    owner read (the autouse fixture fakes it for the planning tests)."""
    if not floorlock.elevated():
        pytest.skip("needs an elevated terminal: a session never elevates")
    monkeypatch.setattr(floor, "owner", REAL_OWNER)
    import subprocess
    sid = REAL_ACCOUNT()
    home = tmp_path / "profile" / ".claude"
    (home / "hooks" / "sub").mkdir(parents=True)
    (home / "hooks" / "sub" / "h.sh").write_text("x", encoding="utf-8")
    (home / "settings.json").write_text("{}", encoding="utf-8")
    a = {"account": sid, "home": str(home), "files": [str(home / "settings.json")], "trees": [str(home / "hooks")],
         "folders": [], "create": []}
    try:
        for _ in range(2):   # the lock, then a relock over it: the entries there already, nothing changes
            assert flooracl.run_all(flooracl.commands(a), subprocess.run) == []
            assert flooracl.lock_trees(a, subprocess.run) == []
            assert flooracl.verify(a) == []
        for p in (home / "hooks" / "sub", home / "hooks" / "sub" / "h.sh"):
            assert flooracl.explicit_deny(p, sid)   # an entry of its own on each entry, none merely inherited
            assert flooracl.denied(p, sid) & flooracl.mask_of(flooracl.FOLDER) == flooracl.mask_of(flooracl.FOLDER)
        assert json.loads((home / "settings.json").read_text(encoding="utf-8")) == {}   # still readable
        with pytest.raises(PermissionError):
            (home / "settings.json").write_text("{\"x\": 1}", encoding="utf-8")   # the account's own write refused
    finally:
        undone = flooracl.run_all(flooracl.undo(a)[0], subprocess.run)
    assert undone == []
    for p in (home, home / "settings.json", home / "hooks", home / "hooks" / "sub", home / "hooks" / "sub" / "h.sh"):
        assert flooracl.denied(p, sid) == 0, p
    (home / "hooks" / "sub" / "h.sh").write_text("y", encoding="utf-8")   # lifted: the account writes again
    assert floor.owner(home / "settings.json") == "S-1-5-32-544"   # an elevated step gives no owner away (round 3)


def _ran(ran):
    def run(c, **k):
        ran.append(c[1:])
        return _Done()
    return run


def test_lock_trees_walks_top_down_one_entry_at_a_time_and_refuses_a_link(tmp_path):
    """Round 2 (both skeptics): no wildcard nor /T, whose middle components icacls follows; each entry owned by the
    administrators then given a deny of its own (round 3: never a reset, which would weaken a folder swapped in for
    it), before its own entries are listed; a junction met is refused, never followed."""
    h = tmp_path / "h"
    (h / "hooks" / "sub").mkdir(parents=True)
    (h / "hooks" / "sub" / "x.sh").write_text("x", encoding="utf-8")
    (h / "hooks" / "a.sh").write_text("x", encoding="utf-8")
    ran = []
    failed = flooracl.lock_trees(_plan(str(h), [], [str(h / "hooks")], []), _ran(ran))
    deny = ["/deny", f"*{SID}:{flooracl.TREE}", "/setowner", "*S-1-5-32-544", "/L"]
    assert failed == [] and ran == [[str(h / "hooks" / "a.sh"), *deny],
                                    [str(h / "hooks" / "sub"), *deny],
                                    [str(h / "hooks" / "sub" / "x.sh"), *deny]]
    try:
        import _winapi
        _winapi.CreateJunction(str(tmp_path), str(h / "hooks" / "sub" / "j"))
    except (ImportError, OSError):
        return
    ran.clear()
    failed = flooracl.lock_trees(_plan(str(h), [], [str(h / "hooks")], []), _ran(ran))
    assert failed == [f"{h / 'hooks' / 'sub' / 'j'}: a link or a junction"]
    assert not [c for c in ran if Path(c[0]).name == "j"]


def test_a_relock_for_another_account_keeps_the_shared_paths_owned_by_the_administrators(monkeypatch):
    """Round 2: the previous account's deny entries go, the ownership (the administrators') stays."""
    monkeypatch.setattr(flooracl, "_unsafe", lambda p, tree, owner: "")
    old = {**_plan(), "account": "S-1-5-21-9-9-9-1002"}
    cmds, _ = flooracl.undo_beside(old, _plan())
    assert cmds and all(c[2] == "/remove:d" and c[3] == "*S-1-5-21-9-9-9-1002" for c in cmds)
    assert flooracl.undo_beside(_plan(), _plan())[0] == []                      # the same account, the same paths


def test_the_plan_refuses_a_path_another_account_owns(tmp_path, monkeypatch):
    """Round 3: a registry entry or a worktree a session wrote could aim the step at another account's folder."""
    _acl_brain(tmp_path, monkeypatch)
    lab = Path(os.path.realpath(tmp_path / "lab"))
    with pytest.raises(floorlock.LockError, match="holds only the account's own paths"):
        flooracl.plan(guards.config.load(), SID, nt=True,
                      owner=lambda p: "S-1-5-21-9-9-9-500" if str(p).startswith(str(lab)) else SID)
    assert flooracl.plan(guards.config.load(), SID, nt=True, owner=lambda p: "S-1-5-32-544")   # a previous lock's


def test_the_worktrees_are_read_without_running_git(tmp_path):
    root = tmp_path / "repo"
    (root / ".git" / "worktrees" / "w1").mkdir(parents=True)
    (root / ".git" / "worktrees" / "w1" / "gitdir").write_text(str(tmp_path / "w1" / ".git") + "\n", encoding="utf-8")
    assert flooracl._worktrees(root) == [tmp_path / "w1"] and flooracl._worktrees(tmp_path / "w1") == []


def test_the_plan_names_a_command_a_held_setting_runs_from_an_unheld_path(tmp_path, monkeypatch):
    _acl_brain(tmp_path, monkeypatch, project=False)
    home = floor.profile(SID) / ".claude"
    loose = tmp_path / "tools" / "status.sh"
    loose.parent.mkdir()
    loose.write_text("echo", encoding="utf-8")
    (home / "statusline.sh").write_text("echo", encoding="utf-8")
    settings = {"statusLine": {"type": "command", "command": f"bash {loose.as_posix()}"},
                "apiKeyHelper": "bash ~/.claude/statusline.sh"}
    (home / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    a = flooracl.plan(guards.config.load(), SID, nt=True)
    assert str(home / "statusline.sh") in a["files"]                          # a script in ~/.claude: held
    text = " | ".join(flooracl.render(a))
    assert f"NOT held, a command a held setting runs: {loose.as_posix()} (statusLine" in text
    assert "statusline.sh (apiKeyHelper" not in text and "sign out" in text


def test_acl_wanted_is_windows_only_and_the_per_call_check_refuses_a_link(tmp_path):
    data = {"floor": {"only": True, "acl": True}}
    assert floor.acl_wanted(data, nt=True) and not floor.acl_wanted(data, nt=False)
    target = tmp_path / "t"
    target.mkdir()
    try:
        import _winapi
        _winapi.CreateJunction(str(target), str(tmp_path / "j"))
    except (ImportError, OSError):
        pytest.skip("no junction")
    assert floor.acl_loose(tmp_path / "j", writable=lambda p: False) == "a link or a junction"


def test_no_deny_holds_a_right_reading_needs(monkeypatch):
    """CI's elevated runner (1165d26f): icacls' /deny made settings.json unreadable (a read asks SYNCHRONIZE and
    READ_CONTROL): the deny entries are written with their exact mask (deny_exact), none holds a right reading needs,
    and verify says so if one does."""
    for rights in (flooracl.FILE, flooracl.TREE, flooracl.FOLDER, flooracl.HOME):
        assert not flooracl.mask_of(rights) & flooracl.READ_RIGHTS, rights
    assert "reading needs" in flooracl.deny_exact("x", SID, 0x100000)
    assert all(c[0] == flooracl.DENY for c in flooracl.commands(_plan()) if "/deny" in c)
    ran = []
    assert flooracl.run_acl([flooracl.DENY, "x", "/deny", f"*{SID}:{flooracl.FILE}"], lambda c, **k: (ran.append(c), _Done())[1]) == ""
    assert ran   # a fake runner gets it: no real ACL is written in a test
    monkeypatch.setattr(floor, "owner", lambda p: "S-1-5-32-544")
    assert flooracl._wrong(__file__, SID, 0, False, lambda p, s: 0x100000, lambda p: []) == \
        [f"{__file__}: {SID} denied a right reading needs (0x100000)"]


# CI round 4 (90e8f219, the elevated runner): each tree entry's deny failed with error 5. SetNamedSecurityInfo had
# written the tree root's inheritable deny into every child, and the elevated step runs as the account it denies: the
# child's own next ACL write was refused (pytest's 0o700 folders carry an OWNER RIGHTS entry, which takes the owner's
# implicit WRITE_DAC away). The entries are now written raw on one handle (no propagation), top down, each before any
# deny of the account lands on it, the backup and restore privileges asked for a relock and the unlock.

ADMINS_BIN = bytes([1, 2, 0, 0, 0, 0, 0, 5]) + (32).to_bytes(4, "little") + (544).to_bytes(4, "little")


def _acl(*entries):
    return flooracl.build_acl(2, list(entries))


def _ace(kind, flags, mask, who):
    import struct
    return struct.pack("<BBHI", kind, flags, 8 + len(who), mask) + who


def test_a_sid_s_bytes_and_a_malformed_one():
    assert flooracl.sid_bytes("S-1-5-32-544") == ADMINS_BIN
    me = flooracl.sid_bytes(SID)
    assert me[:8] == bytes([1, 5, 0, 0, 0, 0, 0, 5]) and len(me) == 8 + 4 * 5
    assert int.from_bytes(me[-4:], "little") == 1001
    for bad in ("", "S-1", "S-2-5-21", "S-1-5-x", "1-5-21-1", f"S-1-5-{1 << 32}-1", "S-1-5" + "-1" * 16):
        with pytest.raises(ValueError):
            flooracl.sid_bytes(bad)
    assert "is no SID" in flooracl.deny_exact("x", "S-1-x", 0x2)


def test_the_deny_entry_goes_first_with_its_exact_mask_once():
    """Explicit denies before any allow (the canonical order); a relock adds nothing; another inheritance is new."""
    me, mask = flooracl.sid_bytes(SID), flooracl.mask_of(flooracl.TREE)
    allow = _ace(0, 0x13, 0x1F01FF, ADMINS_BIN)   # an inherited FullControl
    acl = _acl(allow)
    out = flooracl.with_deny(acl, me, mask, 0x3)
    rev, entries = flooracl.acl_entries(out)
    assert rev == 2 and entries == [_ace(1, 0x3, mask, me), allow]
    assert not mask & flooracl.READ_RIGHTS
    assert flooracl.with_deny(out, me, mask, 0x3) is None                 # there already: unchanged
    assert flooracl.with_deny(out, me, 0x2, 0x3) is None                  # a narrower one is held by it
    assert flooracl.with_deny(out, me, mask, 0) is not None               # another inheritance: added
    inherited_only = _acl(_ace(1, 0x13, mask, me), allow)                 # a copy its parent gave it is not its own
    assert flooracl.acl_entries(flooracl.with_deny(inherited_only, me, mask, 0x3))[1][0] == _ace(1, 0x3, mask, me)


def test_undeny_removes_the_account_s_own_entries_and_its_tree_s_copies_only_when_asked():
    me, other = flooracl.sid_bytes(SID), flooracl.sid_bytes("S-1-5-21-9-9-9-1002")
    own, copy, theirs = _ace(1, 0x3, 0x2, me), _ace(1, 0x13, 0x2, me), _ace(1, 0x3, 0x2, other)
    allow = _ace(0, 0x3, 0x1F01FF, me)
    acl = _acl(own, theirs, allow, copy)
    assert flooracl.acl_entries(flooracl.without_deny(acl, me, False))[1] == [theirs, allow, copy]
    assert flooracl.acl_entries(flooracl.without_deny(acl, me, True))[1] == [theirs, allow]
    assert flooracl.without_deny(_acl(theirs, allow), me, True) is None   # none there: nothing written
    with pytest.raises(ValueError):
        flooracl.acl_entries(_acl(own)[:-4])                              # a truncated ACL is refused


def test_run_acl_hands_each_command_to_its_writer(monkeypatch):
    """The real runner: a DENY command to deny_exact (its owner, mask and inheritance), an UNDENY one to undeny (a
    tree entry's copies too); never icacls."""
    import subprocess
    calls = []
    monkeypatch.setattr(flooracl, "deny_exact", lambda *a, **k: (calls.append(("deny", a, k)), "")[1])
    monkeypatch.setattr(flooracl, "undeny", lambda *a, **k: (calls.append(("undeny", a, k)), "")[1])
    a = _plan(trees=())
    assert flooracl.run_all([*flooracl.commands(a), [flooracl.UNDENY, "H/x", "/remove:d", f"*{SID}", "/L", "/inherited"],
                             [flooracl.UNDENY, "H", "/remove:d", f"*{SID}", "/L"]], subprocess.run) == []
    assert calls[0] == ("deny", ("H", SID, flooracl.mask_of(flooracl.HOME)), {"inherit": False, "owner": "S-1-5-32-544"})
    tree = flooracl.run_acl(flooracl._deny("T", SID, flooracl.TREE), subprocess.run)
    assert tree == "" and calls[-1][2]["inherit"] is True
    assert ("undeny", ("H/x", SID), {"inherited": True}) in calls and ("undeny", ("H", SID), {"inherited": False}) in calls


@pytest.mark.skipif(os.name != "nt", reason="Windows' ACLs")
def test_a_real_deny_reaches_no_existing_child_and_is_lifted(tmp_path):
    """No elevation needed (a SID no token holds, no owner change): the deny lands first in the path's own DACL with
    its exact mask, reaches none of the entries already there (SetNamedSecurityInfo wrote it into each, which then
    refused the elevated step's next write of their ACL), is written once, and undeny lifts it; a junction is refused
    on its handle."""
    other = "S-1-5-21-1111111111-2222222222-3333333333-1001"
    tree = tmp_path / "hooks"
    (tree / "sub").mkdir(parents=True)
    (tree / "sub" / "h.sh").write_text("x", encoding="utf-8")
    mask = flooracl.mask_of(flooracl.TREE)
    try:
        assert flooracl.deny_exact(str(tree), other, mask, inherit=True) == ""
        first = flooracl._aces(tree)[0]
        assert first == (1, 0x3, mask, other)
        assert flooracl.denied(tree / "sub", other) == 0 == flooracl.denied(tree / "sub" / "h.sh", other)
        size = len(flooracl._aces(tree))
        assert flooracl.deny_exact(str(tree), other, mask, inherit=True) == "" and len(flooracl._aces(tree)) == size
        assert flooracl.deny_exact(str(tree / "sub" / "h.sh"), other, mask, inherit=True) == ""
        assert flooracl.explicit_deny(tree / "sub" / "h.sh", other)
        assert (tree / "sub" / "h.sh").read_text(encoding="utf-8") == "x"
    finally:
        lifted = [flooracl.undeny(str(p), other, inherited=True) for p in (tree, tree / "sub" / "h.sh")]
    assert lifted == ["", ""] and flooracl.denied(tree, other) == 0 == flooracl.denied(tree / "sub" / "h.sh", other)
    try:
        import _winapi
        _winapi.CreateJunction(str(tree), str(tmp_path / "j"))
    except (ImportError, OSError):
        return
    assert flooracl.deny_exact(str(tmp_path / "j"), other, 0x2) == f"{tmp_path / 'j'}: a link or a junction"
    assert flooracl.denied(tree, other) == 0   # its target untouched

    via = tmp_path / "j" / "sub" / "h.sh"   # a folder on its way is a junction (renamed and replaced once checked)
    why = flooracl.deny_exact(str(via), other, 0x2)
    assert why.startswith(f"{via}: resolves to ") and flooracl.denied(tree / "sub" / "h.sh", other) == 0


def _control(path):
    import ctypes
    from ctypes import wintypes as w
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    adv.GetFileSecurityW.argtypes = [w.LPCWSTR, w.DWORD, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
    adv.GetSecurityDescriptorControl.argtypes = [ctypes.c_void_p, ctypes.POINTER(w.WORD), ctypes.POINTER(w.DWORD)]
    need = w.DWORD(0)
    adv.GetFileSecurityW(str(path), 0x4, None, 0, ctypes.byref(need))
    sd = ctypes.create_string_buffer(need.value)
    control, rev = w.WORD(), w.DWORD()
    assert adv.GetFileSecurityW(str(path), 0x4, sd, need, ctypes.byref(need))
    assert adv.GetSecurityDescriptorControl(sd, ctypes.byref(control), ctypes.byref(rev))
    return control.value & 0x1400   # SE_DACL_AUTO_INHERITED, SE_DACL_PROTECTED


@pytest.mark.skipif(os.name != "nt", reason="Windows' ACLs")
def test_a_deny_and_its_removal_keep_the_dacl_s_control_bits(tmp_path):
    """Review (CI round 4 fix): a raw write drops SE_DACL_AUTO_INHERITED unless it asks it back
    (SE_DACL_AUTO_INHERIT_REQ); a protected DACL stays protected. A SID no token holds: no elevation needed."""
    import subprocess
    other = "S-1-5-21-1111111111-2222222222-3333333333-1001"
    plain, cut = tmp_path / "plain", tmp_path / "cut"
    plain.mkdir()
    cut.mkdir()
    for p, how in ((plain, "/reset"), (cut, "/inheritance:d")):   # inherited, auto-inherited; protected
        assert subprocess.run(["icacls", str(p), how], capture_output=True, timeout=60).returncode == 0
    for p in (plain, cut):
        before = _control(p)
        assert flooracl.deny_exact(str(p), other, 0x2) == "" and _control(p) == before, p
        assert flooracl.undeny(str(p), other) == "" and _control(p) == before, p
    assert _control(plain) & 0x400 and _control(cut) & 0x1000
