"""The floor's ACL step (config.json floor.acl, wi-brain-floor-acl-lock; brain.floorlock runs it, docs/guards.md « The
ACL step »): on a floor-only machine (Windows), brain floor lock --apply denies the account the sessions run as every
way to change what Claude Code runs or reads beside the guard, whatever writes it (a script, a program, inline code the
guard does not read): its user settings, its hooks, skills, commands, agents and plugins, and the settings and
customization of the brain's projects. brain floor unlock --apply gives them back.

- The rights are named one by one, never icacls' W or M (they carry SYNCHRONIZE and READ_CONTROL, and Claude Code must
  still read the files), and they hold every right the per-call check reads (brain.floor.WRITE_RIGHTS).
- The owner of each path becomes Administrators: an owner keeps WRITE_DAC unless an OWNER RIGHTS entry says otherwise.
- The elevated step follows no link: a path that is a link or a junction, or holds one, refuses the step (a session
  could aim an administrator's write at a folder of the system's), and each path is opened by itself, a link refused.
- The step writes each path's ACL raw on its own handle (deny_exact, undeny), propagating nothing, each before any deny
  of the account lands on it, with the token's backup and restore privileges asked: it often runs as the account.
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
SCRIPTS = {".sh", ".bash", ".ps1", ".psm1", ".cmd", ".bat", ".py", ".js", ".mjs", ".cjs", ".ts", ".exe", ".vbs"}
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


def plan(cfg, sid: str, nt: bool | None = None, kind=None, owner=None) -> dict:
    """The paths the step denies ``sid``: ``home`` (~/.claude itself, its other children kept), ``files`` (its
    settings, and each project's that exist), ``trees`` (its hooks, skills, commands, agents and plugins, and each
    project's that exist), ``folders`` (each project's .claude), ``create`` (what is missing and is made first, an empty
    settings file or folder, so that none can be made later; a folder's ends with a separator); the projects are the
    brain's own folder and its registry's that exist on this machine, with the repos they span. LockError for an
    account that is not a person's (``kind``: floor.sid_kind), a profile the registry does not name, a registry that
    does not load, a path another account owns (``owner``: floor.owner), or off Windows (``nt``)."""
    home = _profile(sid, nt, kind) / ".claude"
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
    out["files"] += _scripts(home)
    for root in project_roots(cfg):
        _project(out, root / ".claude", home)
    foreign = owned_by_others(out, (owner or floor.owner))
    if foreign:
        raise _error(f"the ACL step holds only the account's own paths (or a lock's): {'; '.join(foreign[:6])}; take "
                     "it out of the registry, or give it to the account, then plan again")
    return out


def _profile(sid: str, nt: bool | None, kind) -> Path:
    """The profile folder of ``sid``, a person's account on Windows (:func:`plan`'s LockErrors)."""
    if not (os.name == "nt" if nt is None else nt):
        raise _error("floor.acl is a Windows deny entry for the session's account: turn it off on this machine")
    if not ACCOUNT.fullmatch(sid or "") or (kind or floor.sid_kind)(sid) != SID_TYPE_USER:
        raise _error(f"{sid or 'no account'} is not a person's account SID (S-1-5-21-..., S-1-12-1-..., a user's): "
                     "print the plan in a normal terminal of the account the sessions run as")
    prof = floor.profile(sid, fallback=False)
    if prof is None:
        raise _error(f"no profile folder for {sid} in HKLM's ProfileList: the account has not signed in here")
    return prof


def owned_by_others(a: dict, owner) -> list[str]:
    """Each existing path of a plan owned by another than the account or the administrators (a previous lock's): a
    registry entry or a worktree a session wrote could otherwise aim the step at another account's folder."""
    allowed = {a["account"], ADMINS[1:]}
    return [f"{p} (owned by {who or 'an owner that cannot be read'})"
            for p in sorted(paths_of(a)) if os.path.lexists(p) and (who := owner(p)) not in allowed]


def _scripts(folder: Path) -> list[str]:
    """The scripts directly in ``folder`` (a settings' statusLine or helper runs one, ~/.claude/statusline-command.sh)."""
    try:
        return sorted(str(p) for p in folder.iterdir() if p.is_file() and p.suffix.lower() in SCRIPTS)
    except OSError:
        return []


def _project(out: dict, folder: Path, home: Path) -> None:
    if os.path.normcase(str(folder)) == os.path.normcase(str(home)) or str(folder) in out["folders"]:
        return
    out["folders"].append(str(folder))
    for sub in ("", "worktrees"):   # worktrees: where Claude Code makes a session's; nothing new is added after
        if not (folder / sub).exists():
            out["create"].append(str(folder / sub).rstrip("\\/") + os.sep)
    out["files"] += [str(folder / n) for n in SETTINGS_FILES if (folder / n).is_file()] + _scripts(folder)
    out["trees"] += [str(folder / n) for n in CUSTOMIZATION if (folder / n).is_dir()]


def project_roots(cfg) -> list[Path]:
    """The brain's own folder, the roots of its registry's projects that exist here (projects.load), the repos they
    span (projects.repos_of) and the worktrees of each (git worktree list: a session opened in one reads its own
    .claude), once each. LockError when the registry or a project's repos do not load: the plan would leave their
    settings out unsaid."""
    from . import projects
    roots = [Path(cfg.file).parent]
    try:
        for p in projects.load(Path(cfg.file).parent).values():
            roots.append(p.root)
            roots += [Path(r.path) for r in projects.repos_of(p)]
    except Exception as exc:   # any failure: the plan stops, said
        raise _error(f"the registry beside config.json does not load ({type(exc).__name__}: {exc}): fix it (brain "
                     "check), then plan again") from None
    out: list[Path] = []
    for r in [*roots, *(w for root in roots for w in _worktrees(root))]:
        r = Path(os.path.realpath(r))
        if r.is_dir() and r not in out:
            out.append(r)
    return out


def _worktrees(root: Path) -> list[Path]:
    """The linked worktrees of the checkout at ``root``, read from its .git/worktrees/*/gitdir (no process: the elevated
    step runs no git a session may have put first on PATH); none when it is no main checkout. LockError when one
    cannot be read."""
    admin = root / ".git" / "worktrees"
    if not admin.is_dir():
        return []
    out = []
    try:
        for entry in sorted(admin.iterdir()):
            gitdir = entry / "gitdir"
            if gitdir.is_file():
                out.append(Path(gitdir.read_text(encoding="utf-8").strip()).parent)
    except OSError as exc:
        raise _error(f"the worktrees of {root} cannot be read ({exc}): the plan would leave their settings out") from None
    return out


def _deny(path: str, sid: str, rights: str) -> list[str]:
    """The step's command for one path: its owner made Administrators and its deny entry added, on one handle."""
    return [DENY, path, "/deny", f"*{sid}:{rights}", "/setowner", ADMINS, "/L"]


def commands(a: dict) -> list[list[str]]:
    """The commands that deny the account its paths (:func:`plan`), each on the path itself (:func:`deny_exact`: one
    handle, never a link's target; no wildcard, nothing recursive): its owner made Administrators (an owner keeps
    WRITE_DAC) and its deny entry added; ~/.claude first, so nothing under it is renamed meanwhile. A tree's root ends
    it: :func:`lock_trees` then walks what it holds."""
    sid = a["account"]
    out = [_deny(a["home"], sid, HOME)]
    out += [_deny(d, sid, FOLDER) for d in a["folders"]]   # a project's .claude before what it holds
    out += [_deny(f, sid, FILE) for f in a["files"]]
    out += [_deny(d, sid, TREE) for d in a["trees"]]
    return out


def lock_trees(a: dict, run) -> list[str]:
    """Walk each tree from its root (already denied: nothing is added to it or removed through it any more), top down:
    each entry's owner made Administrators and a deny entry of its own for the account (never a reset, which would
    weaken a folder swapped in for it), one entry at a time, before its own entries are listed; a link or a junction
    met is refused, never followed. Each entry is written before any deny of the account lands on it (deny_exact
    propagates nothing): the elevated step often runs as the account itself. What failed."""
    sid = a["account"]
    failed: list[str] = []
    stack = list(reversed(a["trees"]))
    while stack:
        d = stack.pop()
        try:
            entries = sorted(os.scandir(d), key=lambda e: e.name)
        except OSError as exc:
            failed.append(f"{d}: {exc}")
            continue
        for e in entries:
            if e.is_symlink() or _junction(e.path) or floor._real(e.path) != os.path.normcase(os.path.abspath(e.path)):
                failed.append(f"{e.path}: a link or a junction")
                continue
            w = run_acl(_deny(e.path, sid, TREE), run)
            if w:
                failed.append(w)
            elif e.is_dir(follow_symlinks=False):
                stack.append(e.path)
    return failed


def undo(a: dict, owner=None) -> tuple[list[list[str]], list[str]]:
    """(the commands that lift the account's deny entries, trees first, each of their entries, and ~/.claude last, on
    the path itself (:func:`undeny`); what is left alone and why): only a path still there, no link nor holding one,
    owned by Administrators (``owner``: floor.owner). The ownership stays the administrators': an elevated step never
    gives a path's owner away (a folder a session swapped in for one of them would be handed to the account); the
    account keeps the rights it inherits, and takes the ownership back itself if it wants (takeown /f <path> /r)."""
    sid = f"*{a['account']}"
    owner = owner or floor.owner
    out, left = [], []
    for p, tree in [*((x, True) for x in a.get("trees", [])),
                    *((x, False) for x in (*a.get("files", []), *a.get("folders", []), a.get("home")) if x)]:
        why = _unsafe(p, tree, owner)
        if why:
            left.append(f"{p}: {why}")
            continue
        out.append([UNDENY, p, "/remove:d", sid, "/L"])
        if tree:   # an entry's copies of its tree's deny go too (one an administrator's new entry inherited)
            for root, dirs, files in os.walk(p):
                out += [[UNDENY, os.path.join(root, n), "/remove:d", sid, "/L", "/inherited"]
                        for n in sorted((*dirs, *files))]
    return out, left


def paths_of(a: dict | None) -> set[str]:
    """Every path a step's plan holds."""
    if not isinstance(a, dict):
        return set()
    return {x for x in (a.get("home"), *a.get("files", []), *a.get("trees", []), *a.get("folders", [])) if x}


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
    """What is not held after the step: a path missing, a link or a junction, owned outside floor.TRUSTED_OWNERS, or
    whose deny entries for the account lack a right its kind needs; a tree: itself and everything under it, where an
    entry of a child's own that lets anyone else write would come before the deny it inherits (the paths the step
    denies explicitly keep their deny first). ``denied``: :func:`denied`, ``writers``: :func:`explicit_writers`."""
    denied, writers = denied or globals()["denied"], writers or explicit_writers
    sid, out = a["account"], []
    for kind, rights in (("home", HOME), ("files", FILE), ("folders", FOLDER), ("trees", FOLDER)):
        mask = mask_of(rights)
        for p in [a["home"]] if kind == "home" else a[kind]:
            out += _wrong(p, sid, mask, False, denied, writers)
            if kind == "trees" and os.path.isdir(p) and not out[-1:] == [f"{p}: a link or a junction"]:
                for root, dirs, files in os.walk(p):
                    for n in (*dirs, *files):
                        out += _wrong(os.path.join(root, n), sid, mask, not explicit_deny(os.path.join(root, n), sid),
                                      denied, writers)
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
    got = denied(p, sid)
    lack = mask & ~got
    if lack:
        out.append(f"{p}: {sid} not denied {', '.join(k for k, v in RIGHTS.items() if v & lack)}")
    if got & READ_RIGHTS:   # Claude Code could no longer read it (CreateFile asks SYNCHRONIZE and READ_CONTROL too)
        out.append(f"{p}: {sid} denied a right reading needs (0x{got & READ_RIGHTS:x})")
    out += [f"{p}: an entry of its own lets {w} write" for w in (writers(p) if own_entries else [])]
    return out


# What opening a file or a folder to read asks (FILE_GENERIC_READ, FILE_TRAVERSE): never denied.
READ_RIGHTS = 0x1 | 0x8 | 0x20 | 0x80 | 0x20000 | 0x100000
DENY = "brain-deny"       # a command's first word: deny_exact, not icacls (which adds rights reading needs to a deny)
UNDENY = "brain-undeny"   # undeny, not icacls' /remove:d (which an entry's own deny refuses, and /C reports as done)
ACCESS_DENIED_ACE = 1
# The step's own token: the elevated step often runs as the account it denies (its own deny then holds it too), and an
# OWNER RIGHTS entry (S-1-3-4, which Python's mkdir(mode=0o700) writes) takes the owner's implicit WRITE_DAC away; the
# backup and restore privileges (an administrator's, off until asked) open a path for its ACL and owner whatever it
# denies.
PRIVILEGES = ("SeRestorePrivilege", "SeBackupPrivilege", "SeTakeOwnershipPrivilege")


def run_acl(cmd: list[str], run) -> str:
    """Run one command of the step: a DENY one by :func:`deny_exact`, an UNDENY one by :func:`undeny`, when ``run``
    is the real subprocess.run (a test's fake runner gets them as it gets the others), any other through
    brain.floorlock._run; '' when it succeeded."""
    import subprocess

    from .floorlock import _run
    if cmd[0] in (DENY, UNDENY) and run is subprocess.run:
        sid, _, rights = cmd[3].lstrip("*").partition(":")
        if cmd[0] == UNDENY:
            return undeny(cmd[1], sid, inherited="/inherited" in cmd)
        owner = cmd[cmd.index("/setowner") + 1].lstrip("*") if "/setowner" in cmd else None
        return deny_exact(cmd[1], sid, mask_of(rights), inherit="(OI)(CI)" in rights, owner=owner)
    return _run(cmd, run)


def run_all(cmds: list[list[str]], run) -> list[str]:
    """:func:`run_acl` of each command; what failed."""
    return [w for w in (run_acl(c, run) for c in cmds) if w]


def deny_exact(path: str, sid: str, mask: int, inherit: bool = False, owner: str | None = None) -> str:
    """Add an access-denied entry for ``sid`` with exactly ``mask`` (and, ``inherit``, inherited by what is made in it
    later) first in the DACL of ``path`` itself, and make ``owner`` its owner, on one handle (never a link's target),
    the backup and restore privileges asked (:data:`PRIVILEGES`). icacls' /deny adds SYNCHRONIZE to it, which a read
    of the file asks (Claude Code could no longer read its settings); SetNamedSecurityInfo also writes the entry into
    every child, which then denies the next write of its own ACL. Nothing changes when the entry is there already
    (a relock). '' when done, else why."""
    if mask & READ_RIGHTS:
        return f"{path}: a deny mask holding a right reading needs (0x{mask:x})"
    try:
        who = sid_bytes(sid)
        new_owner = sid_bytes(owner) if owner else None
    except ValueError as exc:
        return f"{path}: {exc}"
    return _rewrite(path, lambda acl: with_deny(acl, who, mask, 0x3 if inherit else 0), new_owner, "the deny entry")


def undeny(path: str, sid: str, inherited: bool = False) -> str:
    """Remove every access-denied entry for ``sid`` of the DACL of ``path`` itself (``inherited``: the ones it
    inherited too: a tree's entry), on one handle (never a link's target), the backup and restore privileges asked;
    the owner stays. '' when done or none was there, else why."""
    try:
        who = sid_bytes(sid)
    except ValueError as exc:
        return f"{path}: {exc}"
    return _rewrite(path, lambda acl: without_deny(acl, who, inherited), None, "the deny entries' removal")


def sid_bytes(sid: str) -> bytes:
    """The binary SID of 'S-1-5-21-...' (revision, count, authority big-endian, sub-authorities little-endian)."""
    import struct
    parts = (sid or "").split("-")
    if len(parts) < 3 or parts[0] != "S" or parts[1] != "1" or not all(p.isdigit() for p in parts[2:]) \
            or len(parts) - 3 > 15:
        raise ValueError(f"{sid or 'no account'} is no SID")
    subs = [int(p) for p in parts[3:]]
    if int(parts[2]) >= 1 << 48 or any(s >= 1 << 32 for s in subs):
        raise ValueError(f"{sid} is no SID")
    return bytes([1, len(subs)]) + int(parts[2]).to_bytes(6, "big") + b"".join(struct.pack("<I", s) for s in subs)


def acl_entries(acl: bytes) -> tuple[int, list[bytes]]:
    """(revision, each entry's bytes) of a binary ACL."""
    import struct
    if len(acl) < 8:
        raise ValueError("a malformed ACL")
    rev, _, size, count, _ = struct.unpack_from("<BBHHH", acl)
    size = min(size, len(acl))
    out, at = [], 8
    for _ in range(count):
        n = struct.unpack_from("<H", acl, at + 2)[0] if at + 4 <= size else 0
        if n < 8 or at + n > size:
            raise ValueError("a malformed ACL")
        out.append(bytes(acl[at:at + n]))
        at += n
    return rev, out


def build_acl(rev: int, entries: list[bytes]) -> bytes:
    import struct
    body = b"".join(entries)
    return struct.pack("<BBHHH", rev, 0, 8 + len(body), len(entries), 0) + body


def _deny_of(entry: bytes, who: bytes) -> tuple[int, int] | None:
    """(flags, mask) of an access-denied entry for ``who``; None for any other entry."""
    import struct
    if entry[0] != ACCESS_DENIED_ACE or entry[8:] != who:
        return None
    return entry[1], struct.unpack_from("<I", entry, 4)[0]


def with_deny(acl: bytes, who: bytes, mask: int, flags: int) -> bytes | None:
    """``acl`` with an explicit deny entry for ``who`` first (the canonical order: explicit denies before any allow);
    None when one of its own already denies ``mask`` with the same inheritance."""
    import struct
    rev, entries = acl_entries(acl)
    for e in entries:
        d = _deny_of(e, who)
        if d and not d[0] & (INHERITED | INHERIT_ONLY) and d[0] & 0x3 == flags & 0x3 and d[1] & mask == mask:
            return None
    ace = struct.pack("<BBHI", ACCESS_DENIED_ACE, flags, 8 + len(who), mask) + who
    return build_acl(max(rev, 2), [ace, *entries])


def without_deny(acl: bytes, who: bytes, inherited: bool) -> bytes | None:
    """``acl`` without the deny entries for ``who`` (its own; ``inherited``: the inherited ones too); None when it
    holds none."""
    rev, entries = acl_entries(acl)
    keep = [e for e in entries if not ((d := _deny_of(e, who)) and (inherited or not d[0] & INHERITED))]
    return None if len(keep) == len(entries) else build_acl(rev, keep)


def _not_itself(path: str, h, k32) -> str:
    """Why the handle ``h`` is not ``path`` itself: a link or a junction (a name surrogate: a compressed, deduplicated
    or cloud file passes), or a path that resolves elsewhere (a folder above it renamed and replaced by a junction
    once checked: with the privileges asked, an administrator's write would land on a system file); '' when it is."""
    import ctypes
    import struct
    tag = ctypes.create_string_buffer(8)   # FILE_ATTRIBUTE_TAG_INFO: FileAttributes, ReparseTag
    if not k32.GetFileInformationByHandleEx(h, 9, tag, 8):   # FileAttributeTagInfo
        return f"{path}: its attributes cannot be read (error {ctypes.get_last_error()})"
    attrs, reparse = struct.unpack("<II", tag.raw)
    if attrs & 0x400 and reparse & 0x20000000:   # FILE_ATTRIBUTE_REPARSE_POINT, a name surrogate
        return f"{path}: a link or a junction"
    buf = ctypes.create_unicode_buffer(32768)
    n = k32.GetFinalPathNameByHandleW(h, buf, len(buf), 0)   # FILE_NAME_NORMALIZED, VOLUME_NAME_DOS
    if not n or n >= len(buf):
        return f"{path}: its final path cannot be read (error {ctypes.get_last_error()})"
    final = buf.value
    for prefix, repl in (("\\\\?\\UNC\\", "\\\\"), ("\\\\?\\", "")):
        if final.startswith(prefix):
            final = repl + final[len(prefix):]
            break
    if os.path.normcase(final) != os.path.normcase(os.path.abspath(path)):
        return f"{path}: resolves to {final} (a folder on its way is a link or a junction)"
    return ""


def _rewrite(path: str, edit, owner: bytes | None, what: str) -> str:
    """Open ``path`` itself (FILE_FLAG_OPEN_REPARSE_POINT: never a link's target; a link or a junction, or a path
    resolving elsewhere, refused: :func:`_not_itself`) for its ACL (and ``owner``: its owner), the privileges asked,
    then write ``edit`` of its DACL (None: unchanged) and the owner as they are, with no inheritance computed nor
    propagated (SetKernelObjectSecurity), its control bits kept. '' when done, else why."""
    import ctypes
    import struct
    if os.name != "nt":
        return f"{path}: an ACL is a Windows one"
    try:
        adv, k32 = _api()
    except (OSError, AttributeError) as exc:
        return f"{path}: {exc}"
    restore = _privileged(adv, k32)
    try:
        access = 0x20000 | 0x40000 | (0x80000 if owner else 0)   # READ_CONTROL, WRITE_DAC, WRITE_OWNER
        h = k32.CreateFileW(path, access, 0x7, None, 3, 0x02000000 | 0x00200000, None)   # OPEN_EXISTING;
        if h in (None, ctypes.c_void_p(-1).value):          # BACKUP_SEMANTICS (a folder, the privileges), REPARSE_POINT
            return f"{path}: cannot be opened for its ACL (error {ctypes.get_last_error()})"
        try:
            why = _not_itself(path, h, k32)
            if why:
                return why
            acl, now, control = _security_of(path, h, adv)
            new_acl, new_owner = edit(acl), owner if owner and owner != now else None
            if new_acl is None and new_owner is None:
                return ""
            err = _set_security(h, adv, new_acl or acl, new_owner, control)
            return f"{path}: {what} cannot be written (error {err})" if err else ""
        finally:
            k32.CloseHandle(h)
    except (OSError, ValueError, struct.error) as exc:
        return f"{path}: {exc}"
    finally:
        restore()


def _security_of(path: str, h, adv) -> tuple[bytes, bytes, int]:
    """(the DACL, the owner SID, the control bits) of the open handle ``h``; OSError when they cannot be read or the
    path has no DACL (anyone may do anything: a deny would make one of only itself)."""
    import ctypes
    import struct
    from ctypes import wintypes as w
    need = w.DWORD(0)
    adv.GetKernelObjectSecurity(h, 0x1 | 0x4, None, 0, ctypes.byref(need))   # OWNER, DACL
    sd = ctypes.create_string_buffer(need.value or 1)
    present, defaulted = w.BOOL(), w.BOOL()
    pdacl, powner, control, rev = ctypes.c_void_p(), ctypes.c_void_p(), w.WORD(), w.DWORD()
    if not (need.value and adv.GetKernelObjectSecurity(h, 0x1 | 0x4, sd, need, ctypes.byref(need))
            and adv.GetSecurityDescriptorDacl(sd, ctypes.byref(present), ctypes.byref(pdacl), ctypes.byref(defaulted))
            and adv.GetSecurityDescriptorOwner(sd, ctypes.byref(powner), ctypes.byref(defaulted))
            and adv.GetSecurityDescriptorControl(sd, ctypes.byref(control), ctypes.byref(rev))):
        raise OSError(f"its ACL cannot be read (error {ctypes.get_last_error()})")
    if not present or not pdacl.value:
        raise OSError("no DACL (anyone may do anything): give it one first")
    size = struct.unpack_from("<H", ctypes.string_at(pdacl.value, 4), 2)[0]
    now = ctypes.string_at(powner.value, adv.GetLengthSid(powner)) if powner.value else b""
    return ctypes.string_at(pdacl.value, size), now, control.value


def _set_security(h, adv, acl: bytes, owner: bytes | None, control: int) -> int:
    """Write ``acl`` (and ``owner``) on the open handle ``h`` as they are: SetKernelObjectSecurity computes and
    propagates nothing; SE_DACL_PROTECTED and SE_DACL_AUTO_INHERITED kept (the latter asked back with
    SE_DACL_AUTO_INHERIT_REQ, else the kernel drops it). 0 when done, else the Win32 error."""
    import ctypes
    dacl = ctypes.create_string_buffer(acl)
    sid = ctypes.create_string_buffer(owner or b"\0")
    new = ctypes.create_string_buffer(64)   # an absolute SECURITY_DESCRIPTOR (40 bytes on x64)
    kept = control & 0x1400                 # SE_DACL_AUTO_INHERITED, SE_DACL_PROTECTED
    kept |= 0x100 if kept & 0x400 else 0
    if not (adv.InitializeSecurityDescriptor(new, 1) and adv.SetSecurityDescriptorDacl(new, True, dacl, False)
            and adv.SetSecurityDescriptorControl(new, 0x1500, kept)
            and (owner is None or adv.SetSecurityDescriptorOwner(new, sid, False))
            and adv.SetKernelObjectSecurity(h, 0x4 | (0x1 if owner else 0), new)):
        return ctypes.get_last_error() or -1
    return 0


def _api():
    """advapi32 and kernel32 with the signatures the step calls (their own instances: nothing shared is changed)."""
    import ctypes
    from ctypes import wintypes as w
    adv, k32 = ctypes.WinDLL("advapi32", use_last_error=True), ctypes.WinDLL("kernel32", use_last_error=True)
    p, pp = ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)
    k32.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, p, w.DWORD, w.DWORD, w.HANDLE]
    k32.CreateFileW.restype = w.HANDLE
    k32.CloseHandle.argtypes = [w.HANDLE]
    k32.GetFileInformationByHandleEx.argtypes = [w.HANDLE, ctypes.c_int, p, w.DWORD]
    k32.GetFinalPathNameByHandleW.argtypes = [w.HANDLE, w.LPWSTR, w.DWORD, w.DWORD]
    k32.GetFinalPathNameByHandleW.restype = w.DWORD
    k32.GetCurrentProcess.restype = w.HANDLE
    adv.GetKernelObjectSecurity.argtypes = [w.HANDLE, w.DWORD, p, w.DWORD, ctypes.POINTER(w.DWORD)]
    adv.SetKernelObjectSecurity.argtypes = [w.HANDLE, w.DWORD, p]
    adv.GetSecurityDescriptorDacl.argtypes = [p, ctypes.POINTER(w.BOOL), pp, ctypes.POINTER(w.BOOL)]
    adv.GetSecurityDescriptorOwner.argtypes = [p, pp, ctypes.POINTER(w.BOOL)]
    adv.GetSecurityDescriptorControl.argtypes = [p, ctypes.POINTER(w.WORD), ctypes.POINTER(w.DWORD)]
    adv.SetSecurityDescriptorControl.argtypes = [p, w.WORD, w.WORD]
    adv.InitializeSecurityDescriptor.argtypes = [p, w.DWORD]
    adv.SetSecurityDescriptorDacl.argtypes = [p, w.BOOL, p, w.BOOL]
    adv.SetSecurityDescriptorOwner.argtypes = [p, p, w.BOOL]
    adv.GetLengthSid.argtypes = [p]
    adv.GetLengthSid.restype = w.DWORD
    adv.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    adv.LookupPrivilegeValueW.argtypes = [w.LPCWSTR, w.LPCWSTR, p]
    adv.AdjustTokenPrivileges.argtypes = [w.HANDLE, w.BOOL, p, w.DWORD, p, ctypes.POINTER(w.DWORD)]
    return adv, k32


def _privileged(adv, k32):
    """Turn :data:`PRIVILEGES` on in this process's token where it holds them (an elevated administrator's); the
    function that turns them back as they were. A token that holds none (a normal one) changes nothing."""
    import ctypes
    from ctypes import wintypes as w

    class LUID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Low", w.DWORD), ("High", w.LONG), ("Attributes", w.DWORD)]

    class TOKEN_PRIVILEGES(ctypes.Structure):
        _fields_ = [("Count", w.DWORD), ("Privileges", LUID_AND_ATTRIBUTES * len(PRIVILEGES))]

    tok = w.HANDLE()
    if not adv.OpenProcessToken(k32.GetCurrentProcess(), 0x20 | 0x8, ctypes.byref(tok)):   # ADJUST_PRIVILEGES, QUERY
        return lambda: None
    want, n = TOKEN_PRIVILEGES(), 0
    for name in PRIVILEGES:
        luid = (w.DWORD * 2)()
        if adv.LookupPrivilegeValueW(None, name, luid):
            want.Privileges[n] = LUID_AND_ATTRIBUTES(luid[0], luid[1], 0x2)   # SE_PRIVILEGE_ENABLED
            n += 1
    want.Count = n
    prev, size = TOKEN_PRIVILEGES(), w.DWORD(0)
    changed = n and adv.AdjustTokenPrivileges(tok, False, ctypes.byref(want), ctypes.sizeof(prev), ctypes.byref(prev),
                                              ctypes.byref(size))

    def restore():
        try:
            if changed and prev.Count:
                adv.AdjustTokenPrivileges(tok, False, ctypes.byref(prev), 0, None, None)
        finally:
            k32.CloseHandle(tok)
    return restore


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


def explicit_deny(path, sid: str) -> bool:
    """Whether the DACL of ``path`` holds an access-denied entry of its own (not inherited) for ``sid``: it comes
    before any allow, explicit or inherited."""
    return any(e[0] == 1 and not e[1] & (INHERITED | INHERIT_ONLY) and e[3] == sid for e in (_aces(path) or []))


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


def undo_beside(a: dict, other: dict | None) -> tuple[list[list[str]], list[str]]:
    """:func:`undo` of ``a`` while another step ``other`` holds now: for the same account, only the paths ``other``
    does not hold; for another account, every path (its deny entries alone: the owner stays the administrators)."""
    if isinstance(other, dict) and other.get("account") == a["account"]:
        return undo(minus(a, other))
    return undo(a)


def released(prev: dict | None, a: dict | None, run) -> list[str]:
    """Once a new lock holds: the previous lock's entries this one no longer holds given back (another account,
    other paths, or floor.acl turned off); what failed or was left, said."""
    if not isinstance(prev, dict) or not prev.get("account"):
        return []
    cmds, left = undo_beside(prev, a)
    if not cmds and not left:
        return []
    failed = run_all(cmds, run)
    return [f"the previous ACL entries given back to {prev['account']}" +
            (f", but: {'; '.join([*failed, *left][:6])}" if failed or left else "")]


# The settings keys whose value Claude Code runs with no tool call: a script they name is held only when it is a path
# of the step (the plan says so otherwise).
COMMAND_KEYS = ("statusLine", "apiKeyHelper", "otelHeadersHelper", "awsAuthRefresh", "awsCredentialExport",
                "gcpAuthRefresh", "fileSuggestion")


ENV_SCRIPT_KEYS = ("BASH_ENV", "ENV", "CLAUDE_ENV_FILE", "CLAUDE_CODE_SHELL_PREFIX", "NODE_OPTIONS")


def unheld_commands(a: dict) -> list[str]:
    """Each file a held settings file's command keys (or an `env` value Claude Code's shell or node reads) name that
    the step does not hold: '<path> (<key> in <file>)'. A word with no folder runs from wherever a session is: said
    too."""
    import json
    held, trees = {os.path.normcase(p) for p in a["files"]}, [os.path.normcase(t) for t in a["trees"]]
    home = str(Path(a["home"]).parent)
    out = []
    for f in a["files"]:
        try:
            data = json.loads(Path(f).read_text(encoding="utf-8")) if f.endswith(".json") else {}
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        env = data.get("env") if isinstance(data.get("env"), dict) else {}
        named = [(k, data.get(k)) for k in COMMAND_KEYS] + [(f"env.{k}", env.get(k)) for k in ENV_SCRIPT_KEYS]
        for key, value in named:
            text = value.get("command") if isinstance(value, dict) else value
            for word in (text.split() if isinstance(text, str) else [])[:64]:
                out += _unheld(word.strip("'\""), key, f, home, held, trees)
    return out


def _unheld(word: str, key: str, f: str, home: str, held: set, trees: list) -> list[str]:
    if not re.search(r"\.(?:" + "|".join(x[1:] for x in sorted(SCRIPTS)) + r")$", word, re.I) and "/" not in word \
            and "\\" not in word:
        return []
    if not re.search(r"[\\/]", word):
        return [f"{word} ({key} in {f}: a script named without a folder runs from wherever a session is)"]
    word = re.sub(r"^(?:~|\$HOME|\$\{HOME\}|%USERPROFILE%|\$env:USERPROFILE)(?=[\\/])", home.replace("\\", "/"),
                  word, flags=re.I)
    p = os.path.normcase(os.path.abspath(word))
    if p in held or any(p.startswith(t + os.sep) for t in trees):
        return []
    return [f"{word} ({key} in {f})"]


def render(a: dict | None) -> list[str]:
    """The plan's lines for the step."""
    if not a:
        return []
    made = [f"    makes first: {c}" for c in a["create"]]
    loose = [f"  NOT held, a command a held setting runs: {x}; move it under a held folder" for x in unheld_commands(a)]
    return [f"The ACL step (config.json floor.acl): the account {a['account']} denied write, delete and any change of "
            "ACL or owner, Administrators made their owner:",
            *(f"  {x}" for x in (*a["files"], *a["trees"], *a["folders"])),
            f"  {a['home']}  itself: none of those removed through it (renamed with it: detected, every call refused)",
            *made, *loose,
            "  While locked, Claude Code's own writes there fail (an \"always allow\" saved to settings.local.json, a "
            "skill or plugin installed or updated); change them after brain floor unlock.",
            "  Before the apply, sign out and in again (or restart): a process that opened one of them before the "
            "lock keeps the rights it opened it with."]


def status(a, wanted_now: bool) -> list[str]:
    """The step's paths: held (present, out of this terminal's reach, owned by the administrators) or which not."""
    if not isinstance(a, dict) or not a.get("account"):
        return ["acl: none, though config.json asks floor.acl: lock again"] if wanted_now else []
    paths = [*a.get("files", []), *a.get("trees", []), *a.get("folders", [])]
    loose = [f"{p} {why}" for p in paths if (why := floor.acl_loose(p))]
    return [f"acl: {a['account']} denied {len(paths)} paths" + (f"; NOT held: {', '.join(loose[:6])}" if loose else
                                                                ", all held")]
