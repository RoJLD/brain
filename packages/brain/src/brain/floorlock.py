"""brain floor lock and unlock (wi-brain-unadopted-floor, review rounds 6-7): the locked floor held by the operating
system. A guard that parses the shell cannot stop a session that runs as the same user: the session can rewrite what
the guard reads or runs from, and any folder in the user's profile can be renamed through its parent. So the lock
moves the floor's authority and the guard itself into folders whose parents only an administrator writes:

- the machine's lock file (brain.floor.LOCK_FILE in brain.floor.lock_dir(): <ProgramData>/Brain, /etc/brain) holds
  the floor's copy, which is the authority (config.json is only compared to it), the config.json and <BRAIN_HOME> the
  guard reads, the paths it checks on each call and the hash of the guard's manifest;
- the guard as a system component (brain.floor.guard_dir(): <Program Files>/Brain/guard, /opt/brain/guard): a copy of
  the interpreter (Windows; on POSIX the system's own, root's), of the guard's code and its dependencies, two
  launchers (guard.py for the hooks, floor.py for the owner's elevated step) and a manifest of their hashes;
- the guard's hooks declared in Claude Code's managed settings (brain.floor.managed_file(): managed-settings.d in
  C:\\Program Files\\ClaudeCode, /etc/claude-code, /Library/Application Support/ClaudeCode), which a user's or a
  project's disableAllHooks cannot turn off; each hook runs the copy by absolute path, with ``-I``.

Each folder is owned by Administrators (root), the users read and run only, its inheritance cut (Windows: ``icacls``;
POSIX: ``chown -R 0:0``, ``chmod -R u=rwX,go=rX``), and the apply checks every file under it before it keeps the lock
file. The plan (``brain floor lock``) prints the floor it would lock, what it installs and the command the owner runs,
elevated, with no profile; the apply (``--apply``) refuses to run without elevation (a session never elevates), with
the floor off, or lowering a locked floor without ``--lower``. ``brain floor unlock --apply`` removes all three.
brain.floor.unlocked is what the guard checks on each call; ``brain floor status`` checks every file.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import floor

ADMINS, SYSTEM, USERS = "*S-1-5-32-544", "*S-1-5-18", "*S-1-5-32-545"   # Administrators, SYSTEM, Users (SIDs)
TREE_GRANTS = (f"{ADMINS}:(OI)(CI)F", f"{SYSTEM}:(OI)(CI)F", f"{USERS}:(OI)(CI)RX")
FILE_GRANTS = (f"{ADMINS}:F", f"{SYSTEM}:F", f"{USERS}:RX")
# Who may own or write a locked path: Administrators, SYSTEM, TrustedInstaller (root on POSIX).
TRUSTED = {"S-1-5-32-544", "S-1-5-18", "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"}
ELEVATED_HINT = {"nt": "an elevated PowerShell (Run as administrator)", "posix": "an elevated shell (sudo)"}
DEPENDENCIES = ("pyyaml", "research-graph", "tomli")   # what the guard imports besides the standard library
# What the interpreter's copy leaves out: its packages (the copy brings its own), tests, docs, Tk, headers.
RUNTIME_SKIP = {"site-packages", "test", "idlelib", "tkinter", "turtledemo", "ensurepip", "__pycache__", "Doc",
                "Tools", "include", "libs", "tcl"}
LAUNCHER = '''"""The locked guard's launcher (brain floor lock): its own folders first, nothing from the environment."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE / "site")]
from brain import floorhook  # noqa: E402

sys.exit(floorhook.{entry}(sys.argv[1:]))
'''


class LockError(Exception):
    """Why the lock cannot be planned or applied (brain floor prints it, exit 2)."""


def elevated() -> bool:
    """Whether this process runs elevated (an administrator's full token; root on POSIX)."""
    if os.name == "nt":
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (OSError, AttributeError):
            return False
    return os.geteuid() == 0


# --- the plan --------------------------------------------------------------------------------------------------------

def plan(cfg) -> dict:
    """What brain floor lock would do: the floor it locks and the one held now, the paths it writes, the command the
    owner runs. LockError when there is no config.json to lock, or its floor is off."""
    if cfg.file is None or cfg.error or not Path(cfg.file).is_file():
        raise LockError("no readable config.json: the lock copies the floor of the one the guard reads "
                        "(brain config shows it)")
    fl = floor.settings(cfg.data)
    if not (fl["refuse"] or fl["only"]):
        raise LockError("config.json's floor is off: set floor.only (or floor.refuse) in it first; a lock of no floor "
                        "holds nothing")
    lock = floor.read_lock()
    held = floor.settings({"floor": lock.get("floor")}) if lock and not lock.get("error") else None
    gdir = floor.guard_dir()
    return {"floor": fl, "held": held, "lowers": bool(held) and _rank(fl) < _rank(held),
            "config": str(Path(cfg.file).resolve()), "brain_home": str(_brain_home()), "guard": gdir,
            "lock": floor.lock_dir(), "managed": floor.managed_file(), "installed": _installed(lock)}


def _rank(fl: dict) -> int:
    return 2 if fl["only"] else 1 if fl["refuse"] else 0


def _brain_home() -> Path:
    from . import paths
    return paths.brain_home().resolve()


def _installed(lock: dict | None) -> bool:
    """Whether the guard's copy is installed and the manifest the lock hashed (the owner then runs it, not the
    user's venv)."""
    return bool(lock) and not lock.get("error") and not floor._manifest_changed(lock)


def run_command(p: dict) -> str:
    """The command the owner runs, elevated: the guard's copy once installed, else the engine this command runs from
    (its first lock trusts it); with no profile, by absolute paths."""
    if p["installed"]:
        py, args = _interpreter(p["guard"]), [str(p["guard"] / "floor.py"), "lock", "--apply"]
    else:
        py, args = Path(sys.executable), ["-m", "brain", "floor", "lock", "--apply"]
    if p["lowers"]:
        args.append("--lower")
    if os.name != "nt":
        return " ".join(["sudo", str(py), "-I", *args])
    return "powershell -NoProfile -Command \"& '" + str(py) + "' -I " + " ".join(f"'{a}'" if " " in a else a
                                                                             for a in args) + '"'


def render_plan(p: dict) -> list[str]:
    fl, held = p["floor"], p["held"]
    out = [f"brain floor lock: locks refuse={fl['refuse']}, only={fl['only']} (config.json {p['config']}); "
           + (f"held now: refuse={held['refuse']}, only={held['only']}" if held else "no lock now")]
    if p["lowers"]:
        out.append("  this LOWERS the locked floor: the apply needs --lower (check config.json's floor first: a "
                   "session may have changed it)")
    out += ["What the apply writes (owner Administrators or root, the users read and run only):",
            f"  {p['guard']}  the guard: an interpreter, its code, two launchers, a manifest of hashes",
            f"  {p['managed']}  the guard's hooks in Claude Code's managed settings",
            f"  {p['lock'] / floor.LOCK_FILE}  the lock file: the floor's copy (written last, after every file is "
            "checked)",
            "Before the apply: close every Claude Code session (a process keeps what it opened before the lock).",
            "Run it in " + ELEVATED_HINT["nt" if os.name == "nt" else "posix"] + " (a session never elevates):",
            "  " + run_command(p)]
    if not p["installed"]:
        out.append(f"  (this first lock runs the engine in {Path(sys.executable).parent.parent}, which a session can "
                   "write: update it from your own terminal first. Later locks run the guard's copy.)")
    out.append("Then, in a normal terminal, brain floor status checks every file.")
    return out


def _interpreter(gdir: Path) -> Path:
    """The interpreter the guard's copy runs (the lock file names it; Windows: its own copy)."""
    lock = floor.read_lock() or {}
    if isinstance(lock.get("interpreter"), str):
        return Path(lock["interpreter"])
    return gdir / "python" / "python.exe" if os.name == "nt" else Path("/usr/bin/python3")


# --- the guard's copy ------------------------------------------------------------------------------------------------

def install_guard(gdir: Path, base: Path | None = None, packages: list[Path] | None = None,
                  nt: bool | None = None) -> Path:
    """Write the guard's copy into ``gdir`` (its old copy removed): the interpreter (``base``: this one's
    installation; POSIX: the system's own, which root must own), the packages, the launchers, the manifest. The
    interpreter's path."""
    nt = os.name == "nt" if nt is None else nt
    if gdir.exists():
        shutil.rmtree(gdir)
    gdir.mkdir(parents=True)
    if nt:
        shutil.copytree(base or Path(sys.base_prefix), gdir / "python", ignore=_skip_runtime)
        interp = gdir / "python" / "python.exe"
    else:
        interp = Path(os.path.realpath(base or getattr(sys, "_base_executable", sys.executable)))
        if floor.owner(interp) != "0":
            raise LockError(f"{interp} is not root's: install Python from the system's packages, then lock")
    site = gdir / "site"
    site.mkdir()
    for pkg in packages if packages is not None else guard_packages():
        (shutil.copytree(pkg, site / pkg.name, ignore=shutil.ignore_patterns("__pycache__")) if pkg.is_dir()
         else shutil.copy2(pkg, site / pkg.name))
    for name, entry in (("guard.py", "hook"), ("floor.py", "cli")):
        (gdir / name).write_text(LAUNCHER.format(entry=entry), encoding="utf-8")
    (gdir / floor.MANIFEST).write_text(json.dumps(manifest(gdir), indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return interp


def _skip_runtime(folder, names):
    return [n for n in names if n in RUNTIME_SKIP]


def guard_packages() -> list[Path]:
    """The brain package and its dependencies' top-level modules, where this interpreter imports them from."""
    from importlib import metadata
    out = [Path(floor.__file__).resolve().parent]
    for name in DEPENDENCIES:
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        tops = {Path(str(f)).parts[0] for f in dist.files or [] if not str(f).startswith("..")}
        for top in sorted(tops):
            path = Path(str(dist.locate_file(top)))
            if path.exists() and not top.endswith((".dist-info", ".pth")) and top != "__pycache__":
                out.append(path)
    return out


def manifest(gdir: Path) -> dict:
    """{path relative to ``gdir``: sha256} of every file of the guard's copy but the manifest."""
    out = {}
    for root, _, files in os.walk(gdir):
        for name in files:
            p = Path(root) / name
            rel = p.relative_to(gdir).as_posix()
            if rel != floor.MANIFEST:
                out[rel] = floor.file_hash(p)
    return out


def hooks_settings(interp: Path, gdir: Path) -> dict:
    """The managed settings that run the guard's copy: the plugin's guard.sh hooks (hooks.json's matchers), each
    command the copy's interpreter on guard.py by absolute path, with ``-I``."""
    plugin = json.loads((Path(floor.__file__).parent / "adapters" / "claude" / "hooks" / "hooks.json")
                        .read_text(encoding="utf-8"))
    out: dict = {}
    for event, groups in (plugin.get("hooks") or {}).items():
        for group in groups:
            hooks = [_locked_hook(h, interp, gdir) for h in group.get("hooks") or []
                     if "/hooks/guard.sh" in str(h.get("command"))]
            if hooks:
                out.setdefault(event, []).append({**{k: v for k, v in group.items() if k != "hooks"}, "hooks": hooks})
    return {"hooks": out}


def _locked_hook(h: dict, interp: Path, gdir: Path) -> dict:
    kind = str(h["command"]).rsplit(" ", 1)[-1]
    return {"type": "command", "timeout": h.get("timeout", 30),
            "command": f'"{interp.as_posix()}" -X utf8 -I "{(gdir / "guard.py").as_posix()}" {kind}'}


# --- the operating system's lock --------------------------------------------------------------------------------------

def _system_tool(name: str) -> str:
    """The system's own icacls (System32 as Windows names it), not one a session put first on PATH."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.kernel32.GetSystemDirectoryW(buf, 260):
            return str(Path(buf.value) / f"{name}.exe")
    except (OSError, AttributeError):
        pass
    return name


def lock_commands(path: Path, tree: bool = True, nt: bool | None = None) -> list[list[str]]:
    """The commands that give ``path`` to the administrators, the users read and run only. Windows, a folder: its own
    ACL reset, then its inheritance cut with the grants (from here no child can gain the user's rights), then the
    owner set on the whole tree, then every child's ACL reset to what it inherits (an entry added before the cut
    goes). A file: its owner, then its ACL. POSIX: owner root, u=rwX,go=rX."""
    nt = os.name == "nt" if nt is None else nt
    p = str(path)
    if nt:
        icacls = _system_tool("icacls") if os.name == "nt" else "icacls"
        if not tree:
            return [[icacls, p, "/setowner", ADMINS, "/C", "/Q"],
                    [icacls, p, "/inheritance:r", "/grant:r", *FILE_GRANTS, "/C", "/Q"]]
        return [[icacls, p, "/reset", "/C", "/Q"], [icacls, p, "/inheritance:r", "/grant:r", *TREE_GRANTS, "/C", "/Q"],
                [icacls, p, "/setowner", ADMINS, "/T", "/C", "/Q"],
                [icacls, os.path.join(p, "*"), "/reset", "/T", "/C", "/Q"]]
    return ([["chown", "-R", "0:0", p], ["chmod", "-R", "u=rwX,go=rX", p]] if tree else
            [["chown", "0:0", p], ["chmod", "0644", p]])


def _run(cmd: list[str], run) -> str:
    """Run one command; '' when it succeeded, else what failed."""
    try:
        r = run(cmd, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"{cmd[0]}: {exc}"
    if r.returncode:
        return f"{' '.join(cmd[:3])}: exit {r.returncode}: {(r.stderr or r.stdout or '').strip()[:200]}"
    return ""


def _run_all(cmds: list[list[str]], run) -> list[str]:
    return [why for why in (_run(c, run) for c in cmds) if why]


def foreign_writers(path) -> list[str]:
    """Who else than TRUSTED may change ``path`` (its DACL's allow entries that grant a write right, by SID; a missing
    DACL or an entry this cannot read counts); POSIX: group or others with write. Read as the descriptor says, not
    through this process's token (the apply runs elevated)."""
    if os.name != "nt":
        mode = os.lstat(path).st_mode
        return ["group or others"] if mode & 0o022 else []
    return _dacl_writers(str(path))


def _dacl_writers(path: str) -> list[str]:
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
    adv.GetFileSecurityW(path, 0x4, None, 0, ctypes.byref(need))   # DACL_SECURITY_INFORMATION
    sd = ctypes.create_string_buffer(need.value or 1)
    present, acl, defaulted = wintypes.BOOL(), ctypes.c_void_p(), wintypes.BOOL()
    if not (need.value and adv.GetFileSecurityW(path, 0x4, sd, need, ctypes.byref(need))
            and adv.GetSecurityDescriptorDacl(sd, ctypes.byref(present), ctypes.byref(acl), ctypes.byref(defaulted))):
        return ["its security descriptor cannot be read"]
    if not present or not acl.value:
        return ["no DACL (everyone may write)"]
    count = ctypes.cast(acl.value + 4, ctypes.POINTER(ctypes.c_ushort))[0]   # ACL: revision, sbz1, size, AceCount
    out = []
    for i in range(count):
        ace = ctypes.c_void_p()
        if not adv.GetAce(acl, i, ctypes.byref(ace)):
            return ["an entry cannot be read"]
        kind, flags = ctypes.cast(ace, ctypes.POINTER(ctypes.c_ubyte * 2))[0]
        if kind == 1 or flags & 0x08:   # a deny entry, or one that only its children inherit
            continue
        mask = ctypes.cast(ace.value + 4, ctypes.POINTER(wintypes.DWORD))[0]
        if kind != 0:
            out.append(f"an allow entry of type {kind}")
        elif mask & (floor.WRITE_RIGHTS | 0x40000000 | 0x10000000):   # GENERIC_WRITE, GENERIC_ALL
            text = wintypes.LPWSTR()
            sid = adv.ConvertSidToStringSidW(ctypes.c_void_p(ace.value + 8), ctypes.byref(text)) and text.value or "?"
            if sid not in TRUSTED:
                out.append(sid)
    return out


def verify(path: Path) -> list[str]:
    """What is wrong under ``path`` (itself and every descendant): an owner outside TRUSTED (root), a writer outside
    them, a link or a junction."""
    out = []
    items = [path]
    if path.is_dir() and not os.path.islink(path):
        for root, dirs, files in os.walk(path):
            items += [Path(root) / n for n in (*dirs, *files)]
    for p in items:
        if floor._real(p) != os.path.normcase(os.path.abspath(p)):
            out.append(f"{p}: a link or a junction")
            continue
        who = floor.owner(p)
        if who not in (TRUSTED if os.name == "nt" else {"0"}):
            out.append(f"{p}: owned by {who or 'an owner that cannot be read'}")
        out += [f"{p}: writable by {w}" for w in foreign_writers(p)]
    return out


# --- apply, unlock, status -------------------------------------------------------------------------------------------

def _need_elevation(what: str, is_elevated=None) -> None:
    """LockError unless this process runs elevated: a session never elevates."""
    if not (is_elevated or elevated)():
        how = ELEVATED_HINT["nt" if os.name == "nt" else "posix"]
        raise LockError(f"{what} writes where only an administrator may: run it in {how}; a session never elevates "
                        "(brain floor lock prints the plan and the command)")


def _no_link(*folders: Path) -> None:
    for d in folders:
        if d.exists() and floor._real(d) != os.path.normcase(os.path.abspath(d)):
            raise LockError(f"{d} is a link or a junction: remove it, then lock")


def apply(cfg, lower: bool = False, run=subprocess.run, is_elevated=None, install=install_guard,
          check=verify) -> list[str]:
    """Lock this machine (module docstring); the lines to print. LockError without elevation, with the floor off,
    lowering a locked floor without ``lower``, when a command fails or a file is not held (the lock file is then
    removed: the guard refuses every call until an apply completes)."""
    _need_elevation("brain floor lock --apply", is_elevated)
    p = plan(cfg)
    if p["lowers"] and not lower:
        raise LockError("this lowers the locked floor: check config.json's floor, then run the apply with --lower")
    gdir, lockdir, managed = p["guard"], p["lock"], p["managed"]
    _no_link(gdir, lockdir, managed.parent)
    interp = install(gdir)
    managed.parent.mkdir(parents=True, exist_ok=True)
    managed.write_text(json.dumps(hooks_settings(interp, gdir), indent=2) + "\n", encoding="utf-8")
    lockdir.mkdir(parents=True, exist_ok=True)
    cut = lock_commands(lockdir)
    before, after = (cut[:3], cut[2:]) if os.name == "nt" else ([], cut)   # Windows: cut before the file is written
    failed = _run_all([*lock_commands(gdir), *lock_commands(managed, tree=False), *before], run)
    _empty(lockdir)   # what was in it before the cut (a session may create a folder in ProgramData)
    lock_file = lockdir / floor.LOCK_FILE
    lock_file.write_text(json.dumps(lock_data(p, interp), indent=2) + "\n", encoding="utf-8")
    failed += _run_all(after, run)   # the owner again, the file's ACL from the cut root
    wrong = [w for d in (gdir, managed, lockdir) for w in check(d)]
    if failed or wrong:
        lock_file.unlink(missing_ok=True)
        raise LockError("the lock is not complete, every call stays refused until an apply completes: "
                        + "; ".join([*failed, *wrong][:12]))
    return [f"locked: the floor refuse={p['floor']['refuse']}, only={p['floor']['only']} in {lock_file}; the guard in "
            f"{gdir}, its hooks in {managed}. Start Claude Code again, then in a normal terminal brain floor status "
            "checks every file"]


def _empty(folder: Path) -> None:
    for child in list(folder.iterdir()):
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def lock_data(p: dict, interp: Path) -> dict:
    """The lock file's content."""
    gdir = p["guard"]
    return {"format": floor.LOCK_FORMAT, "floor": p["floor"], "config": p["config"], "brain_home": p["brain_home"],
            "guard": str(gdir), "interpreter": str(interp), "managed": str(p["managed"]),
            "manifest": floor.file_hash(gdir / floor.MANIFEST),
            "checks": [str(x) for x in (gdir, gdir / floor.MANIFEST, gdir / "guard.py", gdir / "floor.py", interp,
                                        p["managed"])],
            "locked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "lock_dir": str(p["lock"])}


def unlock(is_elevated=None) -> list[str]:
    """Remove the managed hooks, the guard's copy and the lock file (elevated); the lines to print."""
    _need_elevation("brain floor unlock --apply", is_elevated)
    lock = floor.read_lock()
    gdir, managed = floor.guard_dir(), floor.managed_file()
    if lock and not lock.get("error"):
        gdir, managed = Path(lock.get("guard") or gdir), Path(lock.get("managed") or managed)
    managed.unlink(missing_ok=True)
    if gdir.exists():
        shutil.rmtree(gdir)
    (floor.lock_dir() / floor.LOCK_FILE).unlink(missing_ok=True)
    try:
        floor.lock_dir().rmdir()
    except OSError:
        pass
    return [f"unlocked: {managed}, {gdir} and the lock file removed; the plugin's guard judges again (start Claude "
            "Code again)"]


def status(cfg) -> list[str]:
    """What the guard holds now: the floor, the lock file, whether this session's token is out of reach of every file
    of the lock, and the guard's files against its manifest."""
    lock = floor.read_lock()
    fl = floor.effective(cfg, lock)
    out = [f"floor: refuse={fl['refuse']}, only={fl['only']} (config.json {cfg.file or 'none'}"
           f"{', and the lock file' if lock else ''})"]
    if lock is None:
        out.append(f"lock: none ({floor.lock_dir() / floor.LOCK_FILE})")
    elif lock.get("error"):
        out.append(f"lock: unreadable ({lock['error']})")
    else:
        out.append(f"lock: {floor.lock_dir() / floor.LOCK_FILE}, locked at {lock.get('locked_at', '?')}; the guard in "
                   f"{lock.get('guard')}, its hooks in {lock.get('managed')}")
    if not (fl["only"] or lock is not None):
        return out
    why = floor.unlocked(cfg, fl, lock) or (_whole(lock) if lock and not lock.get("error") else "")
    out.append(f"held: {'no: ' + why if why else 'yes: this terminal cannot change the floor or the guard'}")
    if why and elevated():
        out.append("(this terminal is elevated: run brain floor status in a normal one to see what a session sees)")
    return out


def _whole(lock: dict) -> str:
    """Every file of the lock (not only those the guard checks on each call): out of reach, and the guard's files as
    the manifest hashed them; '' when all are."""
    gdir = Path(str(lock.get("guard")))
    for root in (floor.lock_dir(), gdir):
        for folder, _, files in os.walk(root):
            for p in (Path(folder), *(Path(folder) / n for n in files)):
                if floor.writable(p):
                    return f"{p} is writable by this session"
    try:
        listed = json.loads((gdir / floor.MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return f"{gdir / floor.MANIFEST} cannot be read"
    now = manifest(gdir)
    changed = sorted(set(listed) ^ set(now) | {k for k in listed if now.get(k) != listed[k]})
    return f"the guard's files differ from its manifest: {', '.join(changed[:5])}" if changed else ""
