"""brain floor lock and unlock (wi-brain-unadopted-floor, review round 6): the locked floor held by the operating
system. A guard that parses the shell cannot stop a session that runs as the same user, since the session can rewrite
what the guard reads; so the files the floor rests on are given to the administrators, out of the session's reach:

- the personal brain's checkout that holds config.json (config.json and its .git; config.json alone when it is in no
  checkout), the pointer <BRAIN_HOME>/personal.json, the guard's interpreter (<BRAIN_HOME>/venv, and its base
  installation when a session can write it), the guard's own code when it is not in that venv (an install from a
  checkout), and the plugin folder that carries guard.sh (Claude Code's installed_plugins.json, else
  $CLAUDE_PLUGIN_ROOT);
- each is owned by Administrators (root on POSIX), the users may read and run it only, its inheritance cut (Windows:
  ``icacls``; POSIX: ``chown -R 0:0``, ``chmod -R u=rwX,go=rX``);
- then the machine's lock file (brain.floor.LOCK_FILE in brain.floor.lock_dir(): <ProgramData>/Brain, /etc/brain) is
  written and locked the same way: the floor config.json gives, the config.json it holds, the paths the guard checks
  on each call and the plugin folders. git's system configuration gains the checkout as a safe.directory, so that the
  session's git still reads it.

The plan (``brain floor lock``) prints each path, whether it is held already, the commands, and the elevated command
the owner runs; the apply (``--apply``) refuses to run without elevation (a session never elevates). ``--refresh``
fetches the checkout and fast-forwards it to origin/main before it locks again (a change merged on the personal
brain). ``brain floor unlock`` gives everything back to the user and removes the lock file, elevated too.
brain.floor.unlocked is what the guard checks on each call.
"""

from __future__ import annotations

import getpass
import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import config, floor, paths

ADMINS, SYSTEM, USERS = "*S-1-5-32-544", "*S-1-5-18", "*S-1-5-32-545"   # Administrators, SYSTEM, Users (SIDs)
TREE_GRANTS = (f"{ADMINS}:(OI)(CI)F", f"{SYSTEM}:(OI)(CI)F", f"{USERS}:(OI)(CI)RX")
FILE_GRANTS = (f"{ADMINS}:F", f"{SYSTEM}:F", f"{USERS}:RX")
ELEVATED_HINT = {"nt": "an elevated PowerShell (Run as administrator)", "posix": "sudo"}


class LockError(Exception):
    """Why the lock cannot be planned or applied (brain floor prints it, exit 2)."""


@dataclass
class Root:
    """A path the lock gives to the administrators: a folder whole (``tree``) or one file, and the paths under it the
    guard checks on each call (the root first)."""
    path: Path
    kind: str          # "tree" or "file"
    what: str          # what it is, for the plan
    checks: list[Path] = field(default_factory=list)


def elevated() -> bool:
    """Whether this process runs elevated (an administrator's full token; root on POSIX)."""
    if os.name == "nt":
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (OSError, AttributeError):
            return False
    return os.geteuid() == 0


def _checkout(folder: Path) -> Path | None:
    """The git checkout that holds ``folder`` (the first parent with a .git), else None."""
    for p in (folder, *folder.parents):
        if (p / ".git").exists():
            return p
    return None


def plugin_roots(cfg) -> list[Path]:
    """The folders of the core plugin Claude Code runs the guard from: installed_plugins.json's installPath of
    ``<plugin>@<marketplace>`` (each scope's), else $CLAUDE_PLUGIN_ROOT."""
    names = config.claude(cfg)
    key = f"{names['plugin']}@{names['marketplace']}"
    out: list[Path] = []
    try:
        data = json.loads((Path.home() / ".claude" / "plugins" / "installed_plugins.json").read_text(encoding="utf-8"))
        for entry in (data.get("plugins") or {}).get(key) or []:
            if isinstance(entry, dict) and isinstance(entry.get("installPath"), str):
                out.append(Path(entry["installPath"]))
    except (OSError, ValueError, AttributeError):
        pass
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if not out and env:
        out.append(Path(env))
    return [p for p in dict.fromkeys(out) if p.is_dir()]


def _base_interpreter(venv: Path) -> Path | None:
    """The base installation a venv redirects to (pyvenv.cfg's home: its folder, or the folder above bin or
    Scripts)."""
    try:
        text = (venv / "pyvenv.cfg").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        key, eq, value = line.partition("=")
        if eq and key.strip().lower() == "home" and value.strip():
            base = Path(value.strip())
            return base.parent if base.name.lower() in ("bin", "scripts") else base
    return None


def roots(cfg, home: Path | None = None, writable=None) -> list[Root]:
    """What the lock holds on this machine (module docstring), the lock folder left out (apply writes it last).
    LockError when config.json cannot be held (none found, or a worktree's)."""
    writable = writable or floor.writable
    home = home or paths.brain_home()
    if cfg.file is None or not Path(cfg.file).is_file():
        raise LockError("no config.json found: the lock holds the one the guard reads (brain config shows it)")
    cfg_file = Path(cfg.file).resolve()
    out: list[Root] = []
    checkout = _checkout(cfg_file.parent)
    if checkout is not None and (checkout / ".git").is_file():
        raise LockError(f"{cfg_file} is in a worktree ({checkout}): point <BRAIN_HOME>/personal.json at the personal "
                        "brain's main checkout, then lock")
    if checkout is not None:
        out.append(Root(checkout, "tree", "the personal brain's checkout (config.json and its .git)",
                        [checkout, checkout / ".git", cfg_file]))
    else:
        out.append(Root(cfg_file, "file", "config.json (in no git checkout)", [cfg_file]))
    pointer = home / paths.PERSONAL
    if pointer.is_file():
        out.append(Root(pointer, "file", "the pointer to the personal brain", [pointer]))
    venv = home / "venv"
    if venv.is_dir():
        py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        out.append(Root(venv, "tree", "the guard's interpreter", [venv, *(p for p in (py, venv / "pyvenv.cfg")
                                                                          if p.exists())]))
        base = _base_interpreter(venv)
        if base is not None and base.is_dir() and writable(base):
            out.append(Root(base, "tree", "the base Python the venv runs (a session can write it)", [base]))
    code = Path(floor.__file__).resolve().parent.parent   # the folder on sys.path that holds the brain package
    if not any(_inside(code, r.path) for r in out):
        out.append(Root(code, "tree", "the guard's own code (an install from a checkout)", [code]))
    for plugin in plugin_roots(cfg):
        hooks = plugin / "hooks"
        out.append(Root(plugin, "tree", "the plugin that carries guard.sh",
                        [plugin, *(p for p in (hooks / "guard.sh", hooks / "hooks.json") if p.exists())]))
    return out


def _inside(path: Path, folder: Path) -> bool:
    return floor._within(path, folder)


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


def lock_commands(root: Root, nt: bool | None = None) -> list[list[str]]:
    """The commands that give ``root`` to the administrators, read-only for the users, inheritance cut. Windows: the
    owner set (whole tree), every ACL reset to inherited, then the root's own: its inheritance cut, Administrators and
    SYSTEM full, Users read and run (the children inherit it). POSIX: owner root, u=rwX,go=rX."""
    nt = os.name == "nt" if nt is None else nt
    p = str(root.path)
    tree = root.kind == "tree"
    if nt:
        icacls, t = _system_tool("icacls") if os.name == "nt" else "icacls", (["/T"] if tree else [])
        return [[icacls, p, "/setowner", ADMINS, *t, "/C", "/Q"], [icacls, p, "/reset", *t, "/C", "/Q"],
                [icacls, p, "/inheritance:r", "/grant:r", *(TREE_GRANTS if tree else FILE_GRANTS), "/C", "/Q"]]
    return ([["chown", "-R", "0:0", p], ["chmod", "-R", "u=rwX,go=rX", p]] if tree else
            [["chown", "0:0", p], ["chmod", "0644", p]])


def unlock_commands(root: Root, owner: str, nt: bool | None = None) -> list[list[str]]:
    """The commands that give ``root`` back to ``owner`` (a Windows account; uid:gid on POSIX): every ACL back to
    what the folder above gives, the owner set back."""
    nt = os.name == "nt" if nt is None else nt
    p = str(root.path)
    tree = root.kind == "tree"
    if nt:
        icacls, t = _system_tool("icacls") if os.name == "nt" else "icacls", (["/T"] if tree else [])
        return [[icacls, p, "/reset", *t, "/C", "/Q"], [icacls, p, "/setowner", owner, *t, "/C", "/Q"]]
    return [["chown", *(["-R"] if tree else []), owner, p]]


def safe_directory(checkout: Path) -> list[str]:
    """git's system configuration gains the locked checkout as a safe.directory: git refuses a repo another account
    owns, and the session's git must still read it."""
    return ["git", "config", "--system", "--add", "safe.directory", checkout.as_posix()]


def _owner() -> str:
    """Who unlock gives the paths back to: the account that runs it (Windows), the owner of <BRAIN_HOME> as uid:gid
    (POSIX, under sudo)."""
    if os.name == "nt":
        return getpass.getuser()
    st = paths.brain_home().stat()
    return f"{st.st_uid}:{st.st_gid}"


def plan(cfg, writable=None) -> dict:
    """What brain floor lock would do: {"roots": [(Root, held)], "lock": the lock folder, "commands": [...],
    "floor": config.json's floor}."""
    writable = writable or floor.writable
    rs = roots(cfg, writable=writable)
    lockdir = floor.lock_dir()
    lock_root = Root(lockdir, "tree", "the machine's lock file", [lockdir, lockdir / floor.LOCK_FILE])
    rows = [(r, not any(writable(c) for c in r.checks)) for r in rs]
    cmds = [c for r, _ in rows for c in lock_commands(r)]
    checkout = next((r.path for r in rs if r.kind == "tree" and (r.path / ".git").exists()), None)
    if checkout is not None:
        cmds.append(safe_directory(checkout))
    cmds += lock_commands(lock_root)
    return {"roots": rows, "lock": lock_root, "commands": cmds, "floor": floor.settings(cfg.data),
            "config": str(Path(cfg.file).resolve())}


def lock_data(p: dict) -> dict:
    """The lock file's content for a plan."""
    lock_root = p["lock"]
    return {"format": floor.LOCK_FORMAT, "floor": p["floor"], "config": p["config"],
            "roots": [{"path": str(r.path), "kind": r.kind} for r, _ in p["roots"]],
            "checks": [str(c) for r, _ in p["roots"] for c in r.checks],
            "plugins": [str(r.path) for r, _ in p["roots"] if r.what.startswith("the plugin")],
            "locked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "lock_dir": str(lock_root.path)}


def render_plan(p: dict, refresh: bool = False) -> list[str]:
    fl = p["floor"]
    out = [f"brain floor lock: the floor config.json gives is refuse={fl['refuse']}, only={fl['only']} "
           f"({p['config']})", "Paths the lock gives to the administrators (the users read and run only):"]
    for r, held in p["roots"]:
        out.append(f"  {'held   ' if held else 'to lock'}  {r.kind:4}  {r.path}  ({r.what})")
    out.append(f"  then     tree  {p['lock'].path}  (the machine's lock file, written last)")
    if refresh:
        out.append("Before locking: the checkout fetched and fast-forwarded to origin/main.")
    out.append("Commands the apply runs:")
    out += ["  " + " ".join(_quote(a) for a in c) for c in p["commands"]]
    how = ELEVATED_HINT["nt" if os.name == "nt" else "posix"]
    out.append(f"Run it in {how}: brain floor lock --apply{' --refresh' if refresh else ''} (a session never "
               "elevates). Then, in a normal terminal, brain floor status says whether the session is out of reach.")
    return out


def _quote(a: str) -> str:
    return f'"{a}"' if any(c in a for c in " ()") else a


def _run(cmd: list[str], run) -> str:
    """Run one command; '' when it succeeded, else what failed."""
    try:
        r = run(cmd, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"{cmd[0]}: {exc}"
    if r.returncode:
        return f"{' '.join(cmd[:3])}: exit {r.returncode}: {(r.stderr or r.stdout or '').strip()[:200]}"
    return ""


def apply(cfg, refresh: bool = False, run=subprocess.run, is_elevated=None) -> list[str]:
    """Lock this machine (module docstring); the lines to print. LockError without elevation, or when a command
    fails (what ran is kept: a second apply finishes it)."""
    if not (is_elevated or elevated)():
        how = ELEVATED_HINT["nt" if os.name == "nt" else "posix"]
        raise LockError(f"brain floor lock --apply changes who owns the floor's files: run it in {how}; a session "
                        "never elevates (brain floor lock prints the plan)")
    if refresh:
        checkout = _checkout(Path(cfg.file).resolve().parent) if cfg.file else None
        if checkout is None:
            raise LockError("--refresh needs config.json in a git checkout")
        for cmd in (["git", "-C", str(checkout), "fetch", "origin"],
                    ["git", "-C", str(checkout), "merge", "--ff-only", "origin/main"]):
            why = _run(cmd, run)
            if why:
                raise LockError(f"refresh failed: {why}")
        cfg = config.load()   # the fast-forwarded config.json's floor goes into the lock file
    p = plan(cfg)
    lockdir = p["lock"].path
    if lockdir.exists() and floor._real(lockdir) != os.path.normcase(os.path.abspath(lockdir)):
        raise LockError(f"{lockdir} is a link or a junction: remove it, then lock")
    failed = []
    for cmd in p["commands"][:-len(lock_commands(p["lock"]))]:
        if cmd[:4] == ["git", "config", "--system", "--add"] and _has_safe(cmd[-1], run):
            continue   # idempotent: the checkout is a safe.directory already
        why = _run(cmd, run)
        if why:
            failed.append(why)
    lockdir.mkdir(parents=True, exist_ok=True)
    (lockdir / floor.LOCK_FILE).write_text(json.dumps(lock_data(p), indent=2) + "\n", encoding="utf-8")
    failed += [why for cmd in lock_commands(p["lock"]) if (why := _run(cmd, run))]
    if failed:
        raise LockError("the lock is not complete (run the apply again): " + "; ".join(failed))
    return [f"locked: {len(p['roots'])} paths and {lockdir / floor.LOCK_FILE}; in a normal terminal, brain floor "
            "status checks that a session cannot change them"]


def _has_safe(value: str, run) -> bool:
    """Whether git's system configuration already lists ``value`` as a safe.directory (the add is then skipped)."""
    try:
        r = run(["git", "config", "--system", "--get-all", "safe.directory"], capture_output=True, text=True,
                timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return value in (r.stdout or "").splitlines()


def unlock(run=subprocess.run, is_elevated=None, owner: str | None = None) -> list[str]:
    """Give the paths the lock file names back to the user and remove the lock file (elevated); the lines to print."""
    if not (is_elevated or elevated)():
        how = ELEVATED_HINT["nt" if os.name == "nt" else "posix"]
        raise LockError(f"brain floor unlock changes who owns the floor's files: run it in {how}")
    lock = floor.read_lock()
    if lock is None:
        return ["no lock on this machine: nothing to unlock"]
    if lock.get("error"):
        raise LockError(f"the lock file cannot be read ({lock['error']}): remove {floor.lock_dir()} by hand")
    owner = owner or _owner()
    rs = [Root(Path(r["path"]), r.get("kind", "tree"), "") for r in lock.get("roots") or []
          if isinstance(r, dict) and isinstance(r.get("path"), str)]
    lockdir = floor.lock_dir()
    failed = [why for r in [*rs, Root(lockdir, "tree", "")] for cmd in unlock_commands(r, owner)
              if Path(r.path).exists() and (why := _run(cmd, run))]
    if failed:
        raise LockError("the unlock is not complete (run it again): " + "; ".join(failed))
    (lockdir / floor.LOCK_FILE).unlink(missing_ok=True)
    try:
        lockdir.rmdir()
    except OSError:
        pass
    return [f"unlocked: {len(rs)} paths given back to {owner}; the lock file removed (git's safe.directory entry is "
            "left: it only lets git read the checkout)"]


def status(cfg) -> list[str]:
    """What the guard holds now: the floor, the lock file, and whether this session's token is out of reach."""
    lock = floor.read_lock()
    fl = floor.effective(cfg, lock)
    out = [f"floor: refuse={fl['refuse']}, only={fl['only']} (config.json {cfg.file or 'none'}"
           f"{', and the lock file' if lock else ''})"]
    if lock is None:
        out.append(f"lock: none ({floor.lock_dir() / floor.LOCK_FILE})")
    elif lock.get("error"):
        out.append(f"lock: unreadable ({lock['error']})")
    else:
        out.append(f"lock: {floor.lock_dir() / floor.LOCK_FILE}, locked at {lock.get('locked_at', '?')}, "
                   f"{len(lock.get('checks') or [])} paths checked")
    why = floor.unlocked(cfg, fl, lock) if (fl["only"] or lock is not None) else ""
    if fl["only"] or lock is not None:
        out.append(f"held: {'no: ' + why if why else 'yes: this terminal cannot change the floor or what runs it'}")
        if why and elevated():
            out.append("(this terminal is elevated: run brain floor status in a normal one to see what a session sees)")
    return out
