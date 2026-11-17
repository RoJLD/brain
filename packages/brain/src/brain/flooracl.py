"""The floor's ACL step (config.json floor.acl, wi-brain-floor-acl-lock; brain.floorlock runs it, docs/guards.md « The
ACL step »): on a floor-only machine (Windows), brain floor lock --apply denies the account the sessions run as every
way to change what Claude Code runs or reads beside the guard, whatever writes it (a script, a program, inline code the
guard does not read): its user settings, its hooks, skills, commands, agents and plugins, and the settings and
customization of the brain's projects. brain floor unlock --apply gives them back.

- The rights are named one by one, never icacls' W or M (they carry SYNCHRONIZE and READ_CONTROL, and Claude Code must
  still read the files), and they hold every right the per-call check reads (brain.floor.WRITE_RIGHTS).
- The owner of each path becomes Administrators: an owner keeps WRITE_DAC whatever its ACL says.
- The elevated step follows no link: a path that is a link or a junction, or holds one, refuses the step (a session
  could aim an administrator's icacls at a folder of the system's), and every command takes /L.
- What the per-call check holds (brain.floor.unlocked): each path present, out of the session's reach, owned by
  Administrators, SYSTEM or TrustedInstaller; the account the lock denies is the session's; CLAUDE_CONFIG_DIR unset.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from . import floor

ADMINS = "*S-1-5-32-544"
FILE = "(WD,AD,WEA,WA,DC,D,WDAC,WO)"                # a file: no write, append, attribute, delete, ACL or owner change
TREE = "(OI)(CI)(WD,AD,WEA,WA,D,DC,WDAC,WO)"         # a folder and everything it holds, inherited
FOLDER = "(WD,AD,WEA,WA,D,DC,WDAC,WO)"               # a project's .claude: nothing added to it or removed through it
HOME = "(DC,WDAC,WO)"                                # ~/.claude: no locked child removed or renamed through it
RIGHTS = {"WD": 0x2, "AD": 0x4, "WEA": 0x10, "DC": 0x40, "WA": 0x100, "D": 0x10000, "WDAC": 0x40000, "WO": 0x80000}
SETTINGS_FILES = ("settings.json", "settings.local.json")
CUSTOMIZATION = ("hooks", "skills", "commands", "agents")   # ~/.claude's are made when missing; a project's if present
HOME_TREES = (*CUSTOMIZATION, "plugins")   # plugins: their MCP servers and bin/ run with no tool call
# A person's account: local or Microsoft (S-1-5-21-...), Entra ID (S-1-12-1-...), read whole; the lookup
# (floor.sid_kind) then says it is a user's, never a group's.
ACCOUNT = re.compile(r"S-1-(?:5-21|12-1)(?:-\d+){2,7}")
SID_TYPE_USER = 1
INHERITED, INHERIT_ONLY = 0x10, 0x08


def _error(msg: str):
    from .floorlock import LockError
    return LockError(msg)


def wanted(cfg) -> bool:
    """Whether config.json asks the lock for the ACL step: ``floor.acl: true`` under ``floor.only``."""
    return floor.acl_wanted(cfg.data)


def plan(cfg, sid: str, nt: bool | None = None, kind=None) -> dict:
    """The paths the step denies ``sid``: ``home`` (~/.claude itself, its other children kept), ``files`` (its
    settings, and each project's that exist), ``trees`` (its hooks, skills, commands, agents and plugins, and each
    project's that exist), ``folders`` (each project's .claude), ``create`` (what is missing and is made first, an empty
    settings file or folder, so that none can be made later; a folder's ends with a separator); the projects are the
    brain's own folder and its registry's that exist on this machine, with the repos they span. LockError for an
    account that is not a person's (``kind``: floor.sid_kind), a profile the registry does not name, a registry that
    does not load, or off Windows (``nt``)."""
    if not (os.name == "nt" if nt is None else nt):
        raise _error("floor.acl is a Windows deny entry for the session's account: turn it off on this machine")
    if not ACCOUNT.fullmatch(sid or "") or (kind or floor.sid_kind)(sid) != SID_TYPE_USER:
        raise _error(f"{sid or 'no account'} is not a person's account SID (S-1-5-21-..., S-1-12-1-..., a user's): "
                     "print the plan in a normal terminal of the account the sessions run as")
    prof = floor.profile(sid, fallback=False)
    if prof is None:
        raise _error(f"no profile folder for {sid} in HKLM's ProfileList: the account has not signed in here")
    home = prof / ".claude"
    out: dict = {"account": sid, "home": str(home), "files": [], "trees": [], "folders": [], "create": []}
    if not home.is_dir():
        out["create"].append(str(home) + os.sep)
    for name in SETTINGS_FILES:
        out["files"].append(str(home / name))
        if not (home / name).exists():
            out["create"].append(str(home / name))
    for name in HOME_TREES:
        out["trees"].append(str(home / name))
        if not (home / name).exists():
            out["create"].append(str(home / name) + os.sep)
    for root in project_roots(cfg):
        _project(out, root / ".claude", home)
    return out


def _project(out: dict, folder: Path, home: Path) -> None:
    if os.path.normcase(str(folder)) == os.path.normcase(str(home)) or str(folder) in out["folders"]:
        return
    out["folders"].append(str(folder))
    for sub in ("", "worktrees"):   # worktrees: where Claude Code makes a session's; nothing new is added after
        if not (folder / sub).exists():
            out["create"].append(str(folder / sub).rstrip("\\/") + os.sep)
    out["files"] += [str(folder / n) for n in SETTINGS_FILES if (folder / n).is_file()]
    out["trees"] += [str(folder / n) for n in CUSTOMIZATION if (folder / n).is_dir()]


def project_roots(cfg) -> list[Path]:
    """The brain's own folder, the roots of its registry's projects that exist here (projects.load) and the repos they
    span (projects.repos_of), once each. LockError when the registry or a project's repos do not load: the plan
    would leave their settings out unsaid."""
    from . import projects
    roots = [Path(cfg.file).parent]
    try:
        for p in projects.load(Path(cfg.file).parent).values():
            roots.append(p.root)
            roots += [Path(r.path) for r in projects.repos_of(p)]
    except Exception as exc:   # noqa: BLE001 - any failure: the plan stops, said
        raise _error(f"the registry beside config.json does not load ({type(exc).__name__}: {exc}): fix it (brain "
                     "check), then plan again") from None
    out: list[Path] = []
    for r in roots:
        r = Path(os.path.realpath(r))
        if r.is_dir() and r not in out:
            out.append(r)
    return out


def _icacls(nt: bool | None) -> str:
    from .floorlock import _system_tool
    return _system_tool("icacls") if os.name == "nt" and nt is not False else "icacls"


def commands(a: dict, nt: bool | None = None) -> list[list[str]]:
    """The icacls commands that deny the account its paths (:func:`plan`), each on the path itself (/L, never a
    link's target): its owner made Administrators, then its deny entry; a tree's children reset to what they inherit
    (an entry made before the lock goes, the account's own allows among them), their owner Administrators."""
    icacls, sid, q = _icacls(nt), f"*{a['account']}", ("/L", "/C", "/Q")
    out = [[icacls, a["home"], "/setowner", ADMINS, *q], [icacls, a["home"], "/deny", f"{sid}:{HOME}", *q]]
    for f in a["files"]:
        out += [[icacls, f, "/setowner", ADMINS, *q], [icacls, f, "/deny", f"{sid}:{FILE}", *q]]
    for d in a["folders"]:
        out += [[icacls, d, "/setowner", ADMINS, *q], [icacls, d, "/deny", f"{sid}:{FOLDER}", *q]]
    for d in a["trees"]:
        out += [[icacls, d, "/deny", f"{sid}:{TREE}", *q], [icacls, os.path.join(d, "*"), "/reset", "/T", *q],
                [icacls, d, "/setowner", ADMINS, "/T", *q]]
    return out


def undo(a: dict, nt: bool | None = None, owner=None) -> tuple[list[list[str]], list[str]]:
    """(the commands that give the account its paths back: their deny entries removed first, then their ownership,
    on the path itself; what is left alone and why): only a path still there, no link nor holding one, owned by
    Administrators (``owner``: floor.owner), so an elevated unlock never hands the account a folder a session swapped
    in for one of them."""
    icacls, sid, q = _icacls(nt), f"*{a['account']}", ("/L", "/C", "/Q")
    owner = owner or floor.owner
    out, left = [], []
    for p, tree in [*((x, False) for x in (a.get("home"), *a.get("files", []), *a.get("folders", [])) if x),
                    *((x, True) for x in a.get("trees", []))]:
        why = _unsafe(p, tree, owner)
        if why:
            left.append(f"{p}: {why}")
            continue
        t = ("/T",) if tree else ()
        out += [[icacls, p, "/remove:d", sid, *t, *q], [icacls, p, "/setowner", sid, *t, *q]]
    return out, left


def _unsafe(p: str, tree: bool, owner) -> str:
    if not os.path.lexists(p):
        return "gone"
    linked = links([p], [p] if tree else [])
    if linked:
        return f"a link or a junction ({linked[0]})"
    if owner(p) != ADMINS[1:]:
        return "not owned by Administrators (not the lock's)"
    return ""


def links(paths: list[str], trees: list[str] = ()) -> list[str]:
    """Each of ``paths``, or anything under ``trees``, that is a link or a junction or sits under one (its real path
    is not the path as written); an administrator's icacls must never follow one."""
    out = [p for p in paths if os.path.lexists(p) and floor._real(p) != os.path.normcase(os.path.abspath(p))]
    for t in trees:
        if not os.path.isdir(t) or t in out:
            continue
        for root, dirs, files in os.walk(t):   # never into a link (os.walk follows none by default)
            for n in (*dirs, *files):
                p = os.path.join(root, n)
                if os.path.islink(p) or _junction(p):
                    out.append(p)
    return out


def _junction(p: str) -> bool:
    isj = getattr(os.path, "isjunction", None)   # Python 3.12; else a folder whose real path is elsewhere
    if isj is not None:
        return isj(p)
    return os.path.isdir(p) and floor._real(p) != os.path.normcase(os.path.abspath(p))


def all_links(a: dict) -> list[str]:
    """:func:`links` of every path the step names (the home, its parents included, through _real)."""
    return links([a["home"], *a["files"], *a["trees"], *a["folders"]], a["trees"])


def create(a: dict) -> None:
    """Make what the plan found missing: an empty folder, an empty settings file ({})."""
    for p in a["create"]:
        if p.endswith(os.sep):
            Path(p).mkdir(parents=True, exist_ok=True)
        elif not Path(p).exists():
            Path(p).parent.mkdir(parents=True, exist_ok=True)
            Path(p).write_text("{}\n", encoding="utf-8")


def verify(a: dict, denied=None, writers=None) -> list[str]:
    """What is not held after the step: a path missing, a link or a junction, owned outside floor.TRUSTED_OWNERS,
    whose deny entries for the account lack a right its kind needs, or with an entry of its own that lets anyone else
    write (an allow ahead of the inherited deny); a tree: itself and everything under it. ``denied``: :func:`denied`,
    ``writers``: :func:`explicit_writers`."""
    denied, writers = denied or globals()["denied"], writers or explicit_writers
    sid, out = a["account"], []
    for kind, rights in (("home", HOME), ("files", FILE), ("folders", FOLDER), ("trees", FOLDER)):
        mask = mask_of(rights)
        paths = [a["home"]] if kind == "home" else list(a[kind])
        for p in list(paths) if kind == "trees" else ():
            if os.path.isdir(p) and not os.path.islink(p):
                for root, dirs, files in os.walk(p):
                    paths += [os.path.join(root, n) for n in (*dirs, *files)]
        for p in paths:
            out += _wrong(p, sid, mask, kind != "home", denied, writers)
    return out


def _wrong(p: str, sid: str, mask: int, own_entries: bool, denied, writers) -> list[str]:
    if not os.path.lexists(p):
        return [f"{p}: missing"]
    if floor._real(p) != os.path.normcase(os.path.abspath(p)):
        return [f"{p}: a link or a junction"]
    out = []
    who = floor.owner(p)
    if who not in floor.TRUSTED_OWNERS:
        out.append(f"{p}: owned by {who or 'an owner that cannot be read'}")
    lack = mask & ~denied(p, sid)
    if lack:
        out.append(f"{p}: {sid} not denied {', '.join(k for k, v in RIGHTS.items() if v & lack)}")
    out += [f"{p}: an entry of its own lets {w} write" for w in (writers(p) if own_entries else [])]
    return out


def mask_of(rights: str) -> int:
    """The access mask of an icacls rights list, its inheritance flags aside: '(WD,D)' -> 0x10002."""
    return sum(RIGHTS[r] for r in re.findall(r"[A-Z]+", rights.rsplit("(", 1)[-1]) if r in RIGHTS)


def _aces(path) -> list[tuple[int, int, int, str]] | None:
    """(type, flags, mask, SID) of each entry of the DACL of ``path``; None when it cannot be read or off Windows."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    adv.GetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                     ctypes.POINTER(wintypes.DWORD)]
    adv.GetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL),
                                              ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
    adv.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    need = wintypes.DWORD(0)
    adv.GetFileSecurityW(str(path), 0x4, None, 0, ctypes.byref(need))   # DACL_SECURITY_INFORMATION
    sd = ctypes.create_string_buffer(need.value or 1)
    present, acl, defaulted = wintypes.BOOL(), ctypes.c_void_p(), wintypes.BOOL()
    if not (need.value and adv.GetFileSecurityW(str(path), 0x4, sd, need, ctypes.byref(need))
            and adv.GetSecurityDescriptorDacl(sd, ctypes.byref(present), ctypes.byref(acl), ctypes.byref(defaulted))
            and present and acl.value):
        return None
    count = ctypes.cast(acl.value + 4, ctypes.POINTER(ctypes.c_ushort))[0]   # ACL: revision, sbz1, size, AceCount
    out = []
    for i in range(count):
        ace = ctypes.c_void_p()
        if not adv.GetAce(acl, i, ctypes.byref(ace)):
            return None
        kind, flags = ctypes.cast(ace, ctypes.POINTER(ctypes.c_ubyte * 2))[0]
        mask = ctypes.cast(ace.value + 4, ctypes.POINTER(wintypes.DWORD))[0]
        text, sid = wintypes.LPWSTR(), "?"
        if kind in (0, 1) and adv.ConvertSidToStringSidW(ctypes.c_void_p(ace.value + 8), ctypes.byref(text)):
            sid = text.value or "?"
        out.append((kind, flags, mask, sid))
    return out


def denied(path, sid: str) -> int:
    """The rights the DACL of ``path`` denies ``sid`` (its access-denied entries, its own and inherited; one that only
    its children inherit aside); 0 when it cannot be read."""
    return sum_rights(e[2] for e in (_aces(path) or []) if e[0] == 1 and not e[1] & INHERIT_ONLY and e[3] == sid)


def sum_rights(masks) -> int:
    out = 0
    for m in masks:
        out |= m
    return out


def explicit_writers(path) -> list[str]:
    """Who an entry of the path's own (not inherited) allows a write right, outside floor.TRUSTED_OWNERS: an allow
    that comes before the inherited deny; ['?'] when the DACL cannot be read."""
    entries = _aces(path)
    if entries is None:
        return [] if os.name != "nt" else ["its DACL cannot be read"]
    grant = floor.WRITE_RIGHTS | 0x40000000 | 0x10000000   # and GENERIC_WRITE, GENERIC_ALL
    return [sid for kind, flags, mask, sid in entries
            if kind == 0 and not flags & (INHERITED | INHERIT_ONLY) and mask & grant
            and sid not in floor.TRUSTED_OWNERS]


def minus(a: dict, prev: dict | None) -> dict:
    """``a`` without what ``prev`` held for the same account (a failed relock gives back only what it added)."""
    if not isinstance(prev, dict) or prev.get("account") != a["account"]:
        return a
    held = {prev.get("home"), *prev.get("files", []), *prev.get("trees", []), *prev.get("folders", [])}
    return {**a, "home": None if a["home"] in held else a["home"],
            **{k: [p for p in a[k] if p not in held] for k in ("files", "trees", "folders")}}


def released(prev: dict | None, a: dict | None, run) -> list[str]:
    """Once a new lock holds: the previous lock's entries this one no longer holds given back (another account,
    other paths, or floor.acl turned off); what failed or was left, said."""
    from .floorlock import _run_all
    if not isinstance(prev, dict) or not prev.get("account"):
        return []
    rest = minus(prev, a) if a and a["account"] == prev["account"] else prev
    if not (rest.get("home") or rest.get("files") or rest.get("trees") or rest.get("folders")):
        return []
    cmds, left = undo(rest)
    failed = _run_all(cmds, run)
    return [f"the previous ACL entries given back to {prev['account']}" +
            (f", but: {'; '.join([*failed, *left][:6])}" if failed or left else "")]


def render(a: dict | None) -> list[str]:
    """The plan's lines for the step."""
    if not a:
        return []
    made = [f"    makes first: {c}" for c in a["create"]]
    return [f"The ACL step (config.json floor.acl): the account {a['account']} denied write, delete and any change of "
            "ACL or owner, Administrators made their owner:",
            *(f"  {x}" for x in (*a["files"], *a["trees"], *a["folders"])),
            f"  {a['home']}  itself: none of those removed or renamed through it", *made,
            "  While locked, Claude Code's own writes there fail (an \"always allow\" saved to settings.local.json, a "
            "skill or plugin installed or updated); change them after brain floor unlock."]


def status(a, wanted_now: bool) -> list[str]:
    """The step's paths: held (present, out of this terminal's reach, owned by the administrators) or which not."""
    if not isinstance(a, dict) or not a.get("account"):
        return ["acl: none, though config.json asks floor.acl: lock again"] if wanted_now else []
    paths = [*a.get("files", []), *a.get("trees", []), *a.get("folders", [])]
    loose = [f"{p} {why}" for p in paths if (why := floor.acl_loose(p))]
    return [f"acl: {a['account']} denied {len(paths)} paths" + (f"; NOT held: {', '.join(loose[:6])}" if loose else
                                                                ", all held")]
