"""brain floor lock and unlock (wi-brain-unadopted-floor, review rounds 6-8): the locked floor held by the operating
system. A guard that parses the shell cannot stop a session that runs as the same user: the session can rewrite what
the guard reads or runs from, and any folder in the user's profile can be renamed through its parent. So the lock
moves the floor's authority and the guard itself into folders whose parents only an administrator writes:

- the machine's lock file (brain.floor.LOCK_FILE in brain.floor.lock_dir(): <ProgramData>/Brain, /etc/brain) holds
  the floor's copy, which is the authority (config.json is only compared to it), the config.json and <BRAIN_HOME> the
  guard reads, the paths it checks on each call, the hash of the guard's manifest, and the git (and bash) it runs;
- the guard as a system component: a copy per lock under brain.floor.guard_dir() (<Program Files>/Brain/guard,
  /opt/brain/guard), holding a copy of the interpreter (Windows; on POSIX the system's own, root's) compiled in place,
  the guard's code and its dependencies, the plugin's hook scripts, two launchers (hook.py for the hooks, floor.py for
  the owner's elevated step) and a manifest of their hashes (bytecode included);
- Claude Code's managed settings (brain.floor.managed_file(): managed-settings.d in C:\\Program Files\\ClaudeCode,
  /etc/claude-code, /Library/Application Support/ClaudeCode): ``allowManagedHooksOnly`` (round 8: a user's, project's
  or plugin's hook would otherwise run beside the guard and rewrite the call it judged), and the plugin's hooks
  declared again from the copy in exec form (an absolute program and its arguments, no shell): the PreToolUse ones
  run the copy's interpreter with ``-I`` (brain.floorhook.HOOKS), the judging ones with ``onFailure: block`` (Claude
  Code v2.1.295 or later) and a deadline inside; the others run the copy's scripts with the administrators' bash.

Each folder is owned by Administrators (root), the users read and run only, its inheritance cut (Windows: ``icacls``;
POSIX: ``chown -R 0:0``, ``chmod -R u=rwX,go=rX``), and the apply checks every file under it before it keeps the lock
file. A new lock installs a new copy beside the one in use and removes the old ones last, never the one its own
interpreter runs from; a step that fails restores the managed file and the lock file as they were. The plan (``brain
floor lock``) prints the floor it would lock, what it installs and the command line the owner runs elevated from
Win+R (no interactive shell, which would load a profile and modules a session can write); the apply (``--apply``)
refuses to run without elevation (a session never elevates), with the floor off, or lowering a locked floor without
``--lower``. ``brain floor unlock --apply`` removes the lock file and the managed file together, then the copies.
Under config.json ``floor.acl`` on a floor-only machine (Windows), the apply also denies the account the sessions run
as every change of its own Claude Code files and its projects' settings (the ACL step, :func:`acl_plan`), and the
unlock gives them back first.
brain.floor.unlocked is what the guard checks on each call; ``brain floor status`` checks every file.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import floor, floorhook

ADMINS, SYSTEM, USERS = "*S-1-5-32-544", "*S-1-5-18", "*S-1-5-32-545"   # Administrators, SYSTEM, Users (SIDs)
TREE_GRANTS = (f"{ADMINS}:(OI)(CI)F", f"{SYSTEM}:(OI)(CI)F", f"{USERS}:(OI)(CI)RX")
FILE_GRANTS = (f"{ADMINS}:F", f"{SYSTEM}:F", f"{USERS}:RX")
# Who may own or write a locked path: Administrators, SYSTEM, TrustedInstaller (root on POSIX).
TRUSTED = {"S-1-5-32-544", "S-1-5-18", "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"}
DEPENDENCIES = ("pyyaml", "research-graph", "tomli")   # what the guard imports besides the standard library
# What the interpreter's copy leaves out: its packages (the copy brings its own), tests, docs, Tk, headers.
RUNTIME_SKIP = {"site-packages", "test", "idlelib", "tkinter", "turtledemo", "ensurepip", "Doc", "Tools", "include",
                "libs", "tcl"}
BLOCKING = {"guard", "governor"}   # the managed hooks that judge: onFailure block, a deadline inside
DEADLINE = 0.6                     # of the hook's timeout, past which the judging hook refuses (brain.floorhook)
MIN_CLAUDE_CODE = "2.1.295"        # onFailure (Claude Code's hooks reference, "Block the action when a hook fails")
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

def plan(cfg, account: str | None = None) -> dict:
    """What brain floor lock would do: the floor it locks and the one held now, the paths it writes, the command the
    owner runs, and under config.json floor.acl the paths the ACL step denies ``account`` (the plan's own account when
    None: a normal terminal's is the sessions'). LockError when there is no config.json to lock, or its floor is
    off."""
    if cfg.file is None or cfg.error or not Path(cfg.file).is_file():
        raise LockError("no readable config.json: the lock copies the floor of the one the guard reads "
                        "(brain config shows it)")
    fl = floor.settings(cfg.data)
    if not (fl["refuse"] or fl["only"]):
        raise LockError("config.json's floor is off: set floor.only (or floor.refuse) in it first; a lock of no floor "
                        "holds nothing")
    lock = floor.read_lock()
    held = floor.settings({"floor": lock.get("floor")}) if lock and not lock.get("error") else None
    return {"floor": fl, "held": held, "lowers": bool(held) and _rank(fl) < _rank(held),
            "config": str(Path(cfg.file).resolve()), "brain_home": str(_brain_home()), "guard": floor.guard_dir(),
            "lock": floor.lock_dir(), "managed": floor.managed_file(),
            "installed": lock if _installed(lock) else None,
            "acl": acl_plan(cfg, account or floor.account()) if acl_wanted(cfg) else None}


def _rank(fl: dict) -> int:
    return 2 if fl["only"] else 1 if fl["refuse"] else 0


def _brain_home() -> Path:
    from . import paths
    return paths.brain_home().resolve()


def _installed(lock: dict | None) -> bool:
    """Whether the guard's copy the lock names is installed as the manifest the lock hashed (the owner then runs it,
    not the user's venv)."""
    return bool(lock) and not lock.get("error") and isinstance(lock.get("interpreter"), str) \
        and not floor._manifest_changed(lock)


def run_command(p: dict, verb: str = "lock") -> str:
    """The command line the owner runs elevated (Windows: from Win+R, Ctrl+Shift+Enter, no shell): the installed
    copy's interpreter and floor.py, else the engine this command runs from (its first lock trusts it); absolute
    paths, ``-I``."""
    lock = p.get("installed")
    if lock:
        py, args = Path(lock["interpreter"]), [str(Path(lock["guard"]) / "floor.py"), verb, "--apply"]
    else:
        py, args = Path(sys.executable), ["-m", "brain", "floor", verb, "--apply"]
    if p.get("lowers"):
        args.append("--lower")
    if p.get("acl") and verb == "lock":
        args += ["--account", p["acl"]["account"]]
    if os.name != "nt":
        return " ".join(["/usr/bin/sudo", str(py), "-I", *args])
    return " ".join(f'"{a}"' if " " in a else a for a in [str(py), "-I", *args, "--wait"])


def runbook(command: str) -> list[str]:
    """How the owner runs ``command`` elevated without a shell a session can write (round 8 #3)."""
    if os.name != "nt":
        return ["Run it from a root-owned login (sudo with an absolute path; a session never elevates):",
                f"  {command}"]
    return ["Press Win+R, paste this line, then Ctrl+Shift+Enter (it runs as administrator with no shell; a session "
            "never elevates):", f"  {command}",
            "  Not from an elevated PowerShell window: the window loads your profile and modules (PSReadLine), which a "
            "session can write. The window stays open on its result until Enter."]


def render_plan(p: dict) -> list[str]:
    fl, held = p["floor"], p["held"]
    out = [f"brain floor lock: locks refuse={fl['refuse']}, only={fl['only']} (config.json {p['config']}); "
           + (f"held now: refuse={held['refuse']}, only={held['only']}" if held else "no lock now")]
    if p["lowers"]:
        out.append("  this LOWERS the locked floor: the apply needs --lower (check config.json's floor first: a "
                   "session may have changed it)")
    out += ["What the apply writes (owner Administrators or root, the users read and run only):",
            f"  {p['guard']}  a new copy of the guard (an interpreter compiled in place, its code, the plugin's hook "
            "scripts, two launchers, a manifest of hashes); older copies removed last",
            f"  {p['managed']}  Claude Code's managed settings: allowManagedHooksOnly (no user, project or plugin "
            "hook runs) and the plugin's hooks declared from the copy",
            f"  {p['lock'] / floor.LOCK_FILE}  the lock file: the floor's copy (written last, after every file is "
            "checked)",
            *_render_acl(p.get("acl")),
            f"Needs Claude Code v{MIN_CLAUDE_CODE} or later (onFailure: block on the judging hooks).",
            "Before the apply: close every Claude Code session (a process keeps what it opened before the lock).",
            *runbook(run_command(p))]
    if not p["installed"]:
        out.append(f"  (this first lock runs the engine in {Path(sys.executable).parent.parent}, which a session can "
                   "write: update it from your own terminal first. Later locks run the guard's copy.)")
    out.append("Then, in a normal terminal, brain floor status checks every file.")
    return out


def _render_acl(a: dict | None) -> list[str]:
    if not a:
        return []
    made = [f"    makes first: {c}" for c in a["create"]]
    return [f"The ACL step (config.json floor.acl): the account {a['account']} denied write, delete and any change of "
            "ACL or owner, Administrators made their owner:",
            *(f"  {x}" for x in (*a["files"], *a["trees"], *a["folders"])),
            f"  {a['home']}  itself: no file removed or renamed through it", *made,
            "  While locked, Claude Code's own writes there fail (an \"always allow\" saved to settings.local.json, a "
            "skill installed); change them after brain floor unlock."]


# --- the guard's copy ------------------------------------------------------------------------------------------------

def install_guard(gdir: Path, base: Path | None = None, packages: list[Path] | None = None,
                  nt: bool | None = None, compile: bool = True, run=subprocess.run, rendered: Path | None = None) -> Path:
    """Write a new copy of the guard into ``gdir`` (which must not exist): the interpreter (``base``: this one's
    installation; POSIX: the system's own, which root must own), the packages, the plugin's hook scripts, the
    launchers, the bytecode (``compile``: compileall by the copy's own interpreter, round 8 #5: under Program Files
    the hooks cannot write it), the manifest. ``rendered``: the plugin brain sync rendered, whose rules and hook
    contract the copy's inject-rules.sh reads (round 9 #5). Windows: the copy's own site folder on its interpreter's
    path (a .pth) and named in plugin/hooks/locked-python, so that every hook of the copy runs the copy's engine. The
    interpreter's path."""
    nt = os.name == "nt" if nt is None else nt
    if gdir.exists():
        raise LockError(f"{gdir} exists: a copy is installed into a new folder")
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
    no_cache = shutil.ignore_patterns("__pycache__")
    for pkg in packages if packages is not None else guard_packages():
        (shutil.copytree(pkg, site / pkg.name, ignore=no_cache) if pkg.is_dir() else shutil.copy2(pkg, site / pkg.name))
    shutil.copytree(Path(floor.__file__).parent / "adapters" / "claude" / "hooks", gdir / "plugin" / "hooks",
                    ignore=no_cache)
    for rel in ("rules", "hooks/contract.txt") if rendered else ():
        src, dst = rendered / rel, gdir / "plugin" / rel
        (shutil.copytree(src, dst, ignore=no_cache) if src.is_dir() else shutil.copy2(src, dst) if src.is_file() else None)
    if nt:   # every run of the copy's interpreter imports the copy's engine; the copy's scripts run that interpreter
        packages_dir = gdir / "python" / "Lib" / "site-packages"
        packages_dir.mkdir(parents=True, exist_ok=True)
        (packages_dir / "brain-guard.pth").write_text(str(site) + "\n", encoding="utf-8")
        (gdir / "plugin" / "hooks" / "locked-python").write_text(interp.as_posix() + "\n", encoding="utf-8")
    for name, entry in (("hook.py", "hook"), ("floor.py", "cli")):
        (gdir / name).write_text(LAUNCHER.format(entry=entry), encoding="utf-8")
    if compile:
        why = _run([str(interp), "-I", "-m", "compileall", "-q", "-j", "0", str(gdir)], run)
        if why:
            raise LockError(f"the guard's copy does not compile: {why}")
    (gdir / floor.MANIFEST).write_text(json.dumps(manifest(gdir), indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return interp


def _skip_runtime(folder, names):
    return [n for n in names if n in RUNTIME_SKIP]


def guard_packages() -> list[Path]:
    """The brain package and its dependencies' top-level modules and metadata (.dist-info: a copy installs the next
    copy from its own, round 8 #4), where this interpreter imports them from."""
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
            if path.exists() and not top.endswith(".pth") and top != "__pycache__":
                out.append(path)
    return out


def manifest(gdir: Path) -> dict:
    """{path relative to ``gdir``: sha256} of every file of the guard's copy but the manifest (bytecode included)."""
    out = {}
    for root, _, files in os.walk(gdir):
        for name in files:
            p = Path(root) / name
            rel = p.relative_to(gdir).as_posix()
            if rel != floor.MANIFEST:
                out[rel] = floor.file_hash(p)
    return out


def hooks_settings(interp: Path, gdir: Path, bash: str | None = None, data: dict | None = None,
                   marketplaces: list | None = None) -> dict:
    """The managed settings: allowManagedHooksOnly, and every hook of the plugin's hooks.json (the opt-in ones only
    when ``data``, config.json, turns them on) declared from the copy in exec form (:func:`_managed_hook`); a hook of
    another event is left out when there is no administrators' ``bash``. ``marketplaces``: the strictKnownMarketplaces
    sources (round 11 #4: "Allowlist the marketplace sources users can add and install from", enforced "on
    marketplace add and on plugin install, update, refresh, and auto-update"), the brain's own only."""
    from .render import OPTIONAL_HOOKS, _opted_in
    plugin = json.loads((Path(floor.__file__).parent / "adapters" / "claude" / "hooks" / "hooks.json")
                        .read_text(encoding="utf-8"))
    off = {script for script, keys in OPTIONAL_HOOKS.items() if not _opted_in(data or {}, keys)}
    out: dict = {}
    for event, groups in (plugin.get("hooks") or {}).items():
        for group in groups:
            hooks = []
            for h in group.get("hooks") or []:
                m = re.search(r"/hooks/([\w-]+\.sh)\"?\s*(.*)$", str(h.get("command") or ""))
                if m and m.group(1) not in off:
                    hooks += [x for x in [_managed_hook(h, event, m.group(1), m.group(2).split(), interp, gdir, bash)]
                              if x]
            if hooks:
                out.setdefault(event, []).append({**{k: v for k, v in group.items() if k != "hooks"}, "hooks": hooks})
    # strictPluginOnlyCustomization: skills', commands' and agents' frontmatter hooks (round 9 #2), and the MCP servers
    # of ~/.claude.json and .mcp.json (round 10 #4: their stdio commands start with no tool call); managed and plugin
    # servers keep loading, among them the brain's own (the rendered plugin's .mcp.json).
    return {"allowManagedHooksOnly": True, "strictPluginOnlyCustomization": ["hooks", "mcp"],
            **({"strictKnownMarketplaces": marketplaces} if marketplaces is not None else {}), "hooks": out}


def known_marketplaces(cfg) -> list:
    """The brain's own marketplace as a strictKnownMarketplaces source (config.json adapters.claude.source: owner/repo
    on GitHub, or an absolute folder; else the brain's folder when it holds .claude-plugin/marketplace.json); [] when
    none is known (then no marketplace may be added or installed from)."""
    from . import config
    src = config.claude(cfg)["source"]
    if re.fullmatch(r"[\w.-]+/[\w.-]+", src or ""):
        return [{"source": "github", "repo": src}]
    root = Path(src) if src and os.path.isabs(src) else Path(cfg.file).parent
    return [{"source": "directory", "path": str(root)}] if (root / ".claude-plugin" / "marketplace.json").is_file() \
        else []


def _managed_hook(h: dict, event: str, script: str, rest: list[str], interp: Path, gdir: Path,
                  bash: str | None) -> dict | None:
    """One plugin hook in exec form: a PreToolUse hook runs the copy's interpreter on hook.py (its name, a deadline
    and onFailure block when it judges); another event's runs the copy's script with ``bash``."""
    out = {k: v for k, v in h.items() if k not in ("command", "args", "shell")}
    name = script[:-3]
    if event == "PreToolUse":
        if name not in floorhook.HOOKS:
            return None
        args = ["-X", "utf8", "-I", str(gdir / "hook.py")]
        if name in BLOCKING:
            args.append(f"--deadline={round(float(h.get('timeout') or 30) * DEADLINE, 1):g}")
            out["onFailure"] = "block"
        return {**out, "command": str(interp), "args": [*args, name, *rest]}
    if not bash:
        return None
    return {**out, "command": bash, "args": [(gdir / "plugin" / "hooks" / script).as_posix(), *rest]}


def system_tools(check=None) -> dict:
    """The administrators' bash and git the managed hooks and the guard run (Windows: Git for Windows under Program
    Files; POSIX: /bin/bash, /usr/bin/git), each kept only when ``check`` (verify) finds nothing wrong with it."""
    check = check or verify
    if os.name == "nt":
        git_root = Path(floor._hklm_folder("ProgramFilesDir")) / "Git"
        found = {"bash": git_root / "bin" / "bash.exe", "git": git_root / "cmd" / "git.exe"}
    else:
        found = {"bash": Path("/bin/bash"), "git": Path("/usr/bin/git")}
    return {k: str(p) for k, p in found.items() if p.is_file() and not check(p)}


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


# --- the account's own Claude Code files (config.json floor.acl, wi-brain-floor-acl-lock) ----------------------------
# Under floor.only with config.json floor.acl (off by default), the apply also denies the session's account (a SID the
# plan reads unelevated) every way to change what Claude Code runs or reads beside the guard: its user settings, its
# hooks, skills, commands and agents, and the project settings of the brain's projects, whatever writes them (a script,
# a program, inline code the guard does not read). Rights, never icacls' W or M: those carry SYNCHRONIZE and
# READ_CONTROL, and Claude Code must still read the files. The owner of each path becomes Administrators (an owner
# keeps WRITE_DAC whatever its ACL says); the owner's elevated unlock gives them back.
ACL_FILE = "(WD,AD,WEA,WA,D,WDAC,WO)"              # a file: no write, append, attribute, delete, ACL or owner change
ACL_TREE = "(OI)(CI)(WD,AD,WEA,WA,D,DC,WDAC,WO)"   # hooks, skills, commands, agents: the folder and all it holds
ACL_FOLDER = "(WD,AD,WEA,WA,D,DC,WDAC,WO)"         # a project's .claude: nothing added to it or removed through it
ACL_HOME = "(DC,WDAC,WO)"                          # ~/.claude: no child removed or renamed through it
RIGHTS = {"WD": 0x2, "AD": 0x4, "WEA": 0x10, "DC": 0x40, "WA": 0x100, "D": 0x10000, "WDAC": 0x40000, "WO": 0x80000}
SETTINGS_FILES = ("settings.json", "settings.local.json")
CUSTOMIZATION = ("hooks", "skills", "commands", "agents")
# A person's account: local or Microsoft (S-1-5-21-...), Entra ID (S-1-12-1-...); never a group nor a well-known SID.
ACCOUNT = re.compile(r"^S-1-(?:5-21|12-1)(?:-\d+){2,7}$")


def acl_wanted(cfg) -> bool:
    """Whether config.json asks the lock for the ACL step: ``floor.acl: true`` under ``floor.only``."""
    section = cfg.data.get("floor") if isinstance(cfg.data, dict) else None
    return isinstance(section, dict) and section.get("acl") is True and floor.settings(cfg.data)["only"]


def acl_plan(cfg, sid: str, nt: bool | None = None) -> dict:
    """The paths the ACL step denies ``sid``: ``home`` (~/.claude itself, its other children kept), ``files`` (its
    settings, and each project's that exist), ``trees`` (its hooks, skills, commands, agents), ``folders`` (each
    project's .claude), ``create`` (what is missing and is made first, an empty settings file or folder, so that none
    can be made later; a folder's ends with a separator); the projects are the brain's own folder and the registry's
    that exist on this machine. LockError for an account that is not a person's, or off Windows (``nt``)."""
    if not (os.name == "nt" if nt is None else nt):
        raise LockError("floor.acl is a Windows deny entry for the session's account: turn it off on this machine")
    if not ACCOUNT.match(sid or ""):
        raise LockError(f"{sid or 'no account'} is not a person's account SID (S-1-5-21-..., S-1-12-1-...): print the "
                        "plan in a normal terminal of the account the sessions run as")
    home = floor.profile(sid) / ".claude"
    out: dict = {"account": sid, "home": str(home), "files": [], "trees": [], "folders": [], "create": []}
    if not home.is_dir():
        out["create"].append(str(home) + os.sep)
    for name in SETTINGS_FILES:
        out["files"].append(str(home / name))
        if not (home / name).exists():
            out["create"].append(str(home / name))
    for name in CUSTOMIZATION:
        out["trees"].append(str(home / name))
        if not (home / name).exists():
            out["create"].append(str(home / name) + os.sep)
    for root in _project_roots(cfg):
        folder = root / ".claude"
        if os.path.normcase(str(folder)) == os.path.normcase(str(home)):
            continue
        out["folders"].append(str(folder))
        if not folder.exists():
            out["create"].append(str(folder) + os.sep)
        if not (folder / "worktrees").exists():   # where Claude Code makes a session's worktree: nothing new after
            out["create"].append(str(folder / "worktrees") + os.sep)
        out["files"] += [str(folder / n) for n in SETTINGS_FILES if (folder / n).is_file()]
    return out


def _project_roots(cfg) -> list[Path]:
    """The brain's own folder and the roots of its registry's projects that exist here (projects.load), once each."""
    from . import projects
    roots = [Path(cfg.file).parent]
    try:
        roots += [p.root for p in projects.load(Path(cfg.file).parent).values()]
    except Exception:   # noqa: BLE001 - a registry that does not load: the brain's own folder alone
        pass
    out: list[Path] = []
    for r in roots:
        r = Path(os.path.realpath(r))
        if r.is_dir() and r not in out:
            out.append(r)
    return out


def _icacls(nt: bool | None) -> str:
    return _system_tool("icacls") if os.name == "nt" and nt is not False else "icacls"


def acl_commands(a: dict, nt: bool | None = None) -> list[list[str]]:
    """The icacls commands that deny the account its paths (:func:`acl_plan`): each one's owner made Administrators,
    then its deny entry; a tree's children reset to what they inherit (an entry made before the lock goes), their
    owner Administrators."""
    icacls, sid, q = _icacls(nt), f"*{a['account']}", ("/C", "/Q")
    out = [[icacls, a["home"], "/setowner", ADMINS, *q], [icacls, a["home"], "/deny", f"{sid}:{ACL_HOME}", *q]]
    for f in a["files"]:
        out += [[icacls, f, "/setowner", ADMINS, *q], [icacls, f, "/deny", f"{sid}:{ACL_FILE}", *q]]
    for d in a["folders"]:
        out += [[icacls, d, "/setowner", ADMINS, *q], [icacls, d, "/deny", f"{sid}:{ACL_FOLDER}", *q]]
    for d in a["trees"]:
        out += [[icacls, d, "/deny", f"{sid}:{ACL_TREE}", *q], [icacls, os.path.join(d, "*"), "/reset", "/T", *q],
                [icacls, d, "/setowner", ADMINS, "/T", *q]]
    return out


def acl_undo(a: dict, nt: bool | None = None) -> list[list[str]]:
    """The commands that give the paths back to the account: its deny entries removed first, then its ownership."""
    icacls, sid, q = _icacls(nt), f"*{a['account']}", ("/C", "/Q")
    out = []
    for p in [x for x in (a.get("home"), *a.get("files", []), *a.get("folders", [])) if x]:
        out += [[icacls, p, "/remove:d", sid, *q], [icacls, p, "/setowner", sid, *q]]
    for d in a.get("trees", []):
        out += [[icacls, d, "/remove:d", sid, "/T", *q], [icacls, d, "/setowner", sid, "/T", *q]]
    return out


def acl_create(a: dict) -> None:
    """Make what the plan found missing: an empty folder, an empty settings file ({})."""
    for p in a["create"]:
        if p.endswith(os.sep):
            Path(p).mkdir(parents=True, exist_ok=True)
        elif not Path(p).exists():
            Path(p).parent.mkdir(parents=True, exist_ok=True)
            Path(p).write_text("{}\n", encoding="utf-8")


def acl_verify(a: dict, denied=None) -> list[str]:
    """What is not held after the ACL step: a path missing, a link or a junction, owned outside TRUSTED, or whose deny
    entries for the account lack a right its kind needs (a tree: itself and everything under it). ``denied``:
    :func:`denied`."""
    denied = denied or globals()["denied"]
    sid, out = a["account"], []
    for kind, rights in (("home", ACL_HOME), ("files", ACL_FILE), ("folders", ACL_FOLDER), ("trees", ACL_FOLDER)):
        mask = _mask(rights)
        paths = [a["home"]] if kind == "home" else list(a[kind])
        for p in list(paths) if kind == "trees" else ():
            if os.path.isdir(p) and not os.path.islink(p):
                for root, dirs, files in os.walk(p):
                    paths += [os.path.join(root, n) for n in (*dirs, *files)]
        for p in paths:
            if not os.path.lexists(p):
                out.append(f"{p}: missing")
                continue
            if floor._real(p) != os.path.normcase(os.path.abspath(p)):
                out.append(f"{p}: a link or a junction")
                continue
            who = floor.owner(p)
            if who not in TRUSTED:
                out.append(f"{p}: owned by {who or 'an owner that cannot be read'}")
            lack = mask & ~denied(p, sid)
            if lack:
                out.append(f"{p}: {sid} not denied {', '.join(k for k, v in RIGHTS.items() if v & lack)}")
    return out


def _mask(rights: str) -> int:
    """The access mask of an icacls rights list, its inheritance flags aside: '(WD,D)' -> 0x10002."""
    return sum(RIGHTS[r] for r in re.findall(r"[A-Z]+", rights.rsplit("(", 1)[-1]) if r in RIGHTS)


def denied(path, sid: str) -> int:
    """The rights the DACL of ``path`` denies ``sid`` (its access-denied entries, its own and inherited; an entry
    that only its children inherit aside); 0 when it cannot be read or off Windows."""
    if os.name != "nt":
        return 0
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
        return 0
    count = ctypes.cast(acl.value + 4, ctypes.POINTER(ctypes.c_ushort))[0]   # ACL: revision, sbz1, size, AceCount
    out = 0
    for i in range(count):
        ace = ctypes.c_void_p()
        if not adv.GetAce(acl, i, ctypes.byref(ace)):
            return 0
        kind, flags = ctypes.cast(ace, ctypes.POINTER(ctypes.c_ubyte * 2))[0]
        if kind != 1 or flags & 0x08:   # ACCESS_DENIED_ACE_TYPE, not INHERIT_ONLY
            continue
        text = wintypes.LPWSTR()
        if adv.ConvertSidToStringSidW(ctypes.c_void_p(ace.value + 8), ctypes.byref(text)) and text.value == sid:
            out |= ctypes.cast(ace.value + 4, ctypes.POINTER(wintypes.DWORD))[0]
    return out


# --- apply, unlock, status -------------------------------------------------------------------------------------------

def _need_elevation(what: str, is_elevated=None) -> None:
    """LockError unless this process runs elevated: a session never elevates."""
    if not (is_elevated or elevated)():
        raise LockError(f"{what} writes where only an administrator may; a session never elevates (brain floor "
                        f"{what.split()[2]} prints the command line to run elevated)")


def _no_link(*folders: Path) -> None:
    for d in folders:
        if d.exists() and floor._real(d) != os.path.normcase(os.path.abspath(d)):
            raise LockError(f"{d} is a link or a junction: remove it, then lock")


def _saved(*files: Path) -> dict:
    return {f: f.read_bytes() if f.is_file() else None for f in files}


def _restore(saved: dict) -> None:
    """Put the files back as they were (None: absent), together."""
    for f, data in saved.items():
        try:
            if data is None:
                f.unlink(missing_ok=True)
            else:
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(data)
        except OSError:
            pass


def _running_from(folder: Path) -> bool:
    here = os.path.normcase(os.path.realpath(sys.executable))
    return here.startswith(os.path.normcase(os.path.realpath(folder)) + os.sep)


def _prune(root: Path, keep: Path | None) -> list[str]:
    """Remove the copies under ``root`` but ``keep`` and the one this interpreter runs from; what stays."""
    left = []
    for child in sorted(root.iterdir()) if root.is_dir() else []:
        if keep is not None and child == keep:
            continue
        if _running_from(child):
            left.append(str(child))
            continue
        try:
            shutil.rmtree(child) if child.is_dir() else child.unlink()
        except OSError:
            left.append(str(child))
    return left


def apply(cfg, lower: bool = False, run=subprocess.run, is_elevated=None, install=install_guard,
          check=verify, tools=None, account: str | None = None, acl_check=acl_verify) -> list[str]:
    """Lock this machine (module docstring); the lines to print. LockError without elevation, with the floor off,
    lowering a locked floor without ``lower``, when a command fails or a file is not held: the managed file and the
    lock file are then restored as they were (no lock before: none, and a floor-only machine refuses every call) and
    the new copy removed; the copy in use is never touched until the new one holds. Under config.json floor.acl, the
    ACL step denies ``account`` (the plan's --account: the elevated step may run as another administrator) its
    Claude Code files once the copy holds, checked by ``acl_check``; undone if a later step fails, unless the previous
    lock held them already."""
    _need_elevation("brain floor lock --apply", is_elevated)
    if acl_wanted(cfg) and not account:
        raise LockError("floor.acl needs --account SID, the account the sessions run as: brain floor lock, printed in "
                        "a normal terminal of that account, gives the command line with it")
    p = plan(cfg, account)
    prev_acl = (floor.read_lock() or {}).get("acl")
    if p["lowers"] and not lower:
        raise LockError("this lowers the locked floor: check config.json's floor, then run the apply with --lower")
    root, lockdir, managed = p["guard"], p["lock"], p["managed"]
    _no_link(root, lockdir, managed.parent)
    lock_file = lockdir / floor.LOCK_FILE
    saved = _saved(managed, lock_file)
    stamp = datetime.now(timezone.utc).strftime("g%Y%m%d-%H%M%S")
    new, n = root / stamp, 1
    while new.exists():   # never the copy in use, even locked twice in a second
        new, n = root / f"{stamp}-{n}", n + 1
    found = (tools or system_tools)(check)
    a, acl_started = p["acl"], False
    try:
        root.mkdir(parents=True, exist_ok=True)
        interp = install(new, rendered=_rendered(cfg))
        failed = _run_all(lock_commands(root), run)
        wrong = [] if failed else check(root)
        if failed or wrong:
            raise LockError("; ".join([*failed, *wrong][:12]))
        if a:   # the account's own Claude Code files, before the managed hooks and the lock file that check them
            acl_create(a)
            acl_started = True
            failed = _run_all(acl_commands(a), run)
            wrong = [] if failed else acl_check(a)
            if failed or wrong:
                raise LockError("the ACL step: " + "; ".join([*failed, *wrong][:12]))
        managed.parent.mkdir(parents=True, exist_ok=True)
        managed.write_text(json.dumps(hooks_settings(interp, new, found.get("bash"), cfg.data, known_marketplaces(cfg)),
                                      indent=2) + "\n", encoding="utf-8")
        lockdir.mkdir(parents=True, exist_ok=True)
        cut = lock_commands(lockdir)
        before, after = (cut[:3], cut[2:]) if os.name == "nt" else ([], cut)   # Windows: cut before the file is written
        failed = _run_all([*lock_commands(managed, tree=False), *before], run)
        _empty(lockdir)   # what was in it before the cut (a session may create a folder in ProgramData)
        lock_file.write_text(json.dumps(lock_data(p, interp, new, found), indent=2) + "\n", encoding="utf-8")
        failed += _run_all(after, run)   # the owner again, the file's ACL from the cut root
        wrong = [w for d in (managed, lockdir) for w in check(d)]
        if failed or wrong:
            raise LockError("; ".join([*failed, *wrong][:12]))
    except BaseException as exc:
        _restore(saved)
        _remove(new)
        undone = _run_all(acl_undo(a), run) if acl_started and not _same_acl(prev_acl, a) else []
        if isinstance(exc, LockError):
            raise LockError("the lock is not complete, the managed settings and the lock file are back as they were "
                            f"({'the previous lock' if saved[lock_file] else 'no lock'}): {exc}"
                            + (f"; the ACL step not undone: {'; '.join(undone[:6])}" if undone else "")) from None
        raise
    left = _prune(root, keep=new)
    lost = [] if found.get("bash") else ["no administrators' bash: the hooks of other events than PreToolUse "
                                         "(rules, announce, health, capture, budget, memory) are not declared"]
    gone = _acl_released(prev_acl, a, run)
    return [f"locked: the floor refuse={p['floor']['refuse']}, only={p['floor']['only']} in {lock_file}; the guard in "
            f"{new}, its hooks in {managed}. Start Claude Code again (v{MIN_CLAUDE_CODE} or later), then in a normal "
            "terminal brain floor status checks every file", *lost,
            *([f"the ACL step: {len(a['files']) + len(a['trees']) + len(a['folders'])} paths denied to "
               f"{a['account']} (and {a['home']} itself)"] if a else []), *gone,
            *([f"older copies still there (in use): {', '.join(left)}; the next lock removes them"] if left else [])]


def _same_acl(prev: dict | None, a: dict | None) -> bool:
    """Whether the previous lock denied the same account the same paths (a failed relock then leaves them held)."""
    keys = ("account", "home", "files", "trees", "folders")
    return bool(prev and a) and all(prev.get(k) == a.get(k) for k in keys)


def _acl_released(prev: dict | None, a: dict | None, run) -> list[str]:
    """Once a new lock holds: the previous lock's ACL entries that this one no longer holds given back (another
    account, or floor.acl turned off); what failed, said."""
    if not isinstance(prev, dict) or not prev.get("account") or _same_acl(prev, a):
        return []
    if a and a["account"] == prev["account"]:   # the same account: give back only the paths no longer held
        kept = {*a["files"], *a["trees"], *a["folders"], a["home"]}
        prev = {**prev, "files": [p for p in prev.get("files", []) if p not in kept],
                "trees": [p for p in prev.get("trees", []) if p not in kept],
                "folders": [p for p in prev.get("folders", []) if p not in kept], "home": None}
    failed = _run_all(acl_undo(prev), run)
    return [f"the previous ACL entries given back to {prev['account']}" +
            (f", but: {'; '.join(failed[:6])}" if failed else "")]


def _rendered(cfg) -> Path | None:
    """The plugin brain sync rendered for this brain (<brain>/plugins/<plugin>), when it holds rules or a contract."""
    from . import config
    p = Path(cfg.file).parent / "plugins" / config.claude(cfg)["plugin"]
    return p if (p / "rules").is_dir() or (p / "hooks" / "contract.txt").is_file() else None


def _remove(folder: Path) -> None:
    if folder.exists() and not _running_from(folder):
        shutil.rmtree(folder, ignore_errors=True)


def _empty(folder: Path) -> None:
    for child in list(folder.iterdir()):
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def lock_data(p: dict, interp: Path, gdir: Path, tools: dict | None = None) -> dict:
    """The lock file's content."""
    tools, a = tools or {}, p.get("acl")
    acl = [*a["files"], *a["trees"], *a["folders"]] if a else []   # checked on each call: missing or writable refuses
    return {"format": floor.LOCK_FORMAT, "floor": p["floor"], "config": p["config"], "brain_home": p["brain_home"],
            "guard": str(gdir), "interpreter": str(interp), "managed": str(p["managed"]),
            "manifest": floor.file_hash(gdir / floor.MANIFEST), **tools,
            "checks": [str(x) for x in (p["guard"], gdir, gdir / floor.MANIFEST, gdir / "hook.py", gdir / "floor.py",
                                        interp, p["managed"], *tools.values(), *acl)],
            **({"acl": {k: a[k] for k in ("account", "home", "files", "trees", "folders", "create")}} if a else {}),
            "locked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "lock_dir": str(p["lock"])}


def unlock(is_elevated=None, run=subprocess.run) -> list[str]:
    """Give the account its Claude Code files back when the lock denied them (LockError if a command fails: the lock
    stays, whole), then remove the lock file and the managed hooks together (both restored if either fails), then the
    guard's copies but the one this interpreter runs from (elevated); the lines to print."""
    _need_elevation("brain floor unlock --apply", is_elevated)
    lock = floor.read_lock()
    managed = floor.managed_file()
    if lock and not lock.get("error"):
        managed = Path(lock.get("managed") or managed)
        a = lock.get("acl")
        failed = _run_all(acl_undo(a), run) if isinstance(a, dict) and a.get("account") else []
        if failed:
            raise LockError("unlock stopped, the lock is whole: the ACL step was not undone: "
                            + "; ".join(failed[:6]))
    lock_file = floor.lock_dir() / floor.LOCK_FILE
    saved = _saved(lock_file, managed)
    try:
        lock_file.unlink(missing_ok=True)
        managed.unlink(missing_ok=True)
    except OSError as exc:
        _restore(saved)
        raise LockError(f"unlock failed, the lock and the managed settings are back as they were: {exc}") from None
    root = floor.guard_dir()
    left = _prune(root, keep=None)
    for d in (root, floor.lock_dir()):
        try:
            d.rmdir()
        except OSError:
            pass
    return [f"unlocked: the lock file and {managed} removed; the plugin's guard judges again (start Claude Code "
            "again)", *([f"still there (this window runs from it): {', '.join(left)}; remove it once the window is "
                         "closed, or the next lock does"] if left else [])]


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
        out.append(_in_force(lock))
        out += _acl_status(lock.get("acl"))
    if not (fl["only"] or lock is not None):
        return out
    why = floor.unlocked(cfg, fl, lock) or (_whole(lock) if lock and not lock.get("error") else "")
    out.append(f"held: {'no: ' + why if why else 'yes: this terminal cannot change the floor or the guard'}")
    if why and elevated():
        out.append("(this terminal is elevated: run brain floor status in a normal one to see what a session sees)")
    return out


def _acl_status(a) -> list[str]:
    """The ACL step's paths: held (present and out of this terminal's reach) or which are not."""
    if not isinstance(a, dict) or not a.get("account"):
        return ["acl: none (config.json floor.acl off when locked)"]
    paths = [*a.get("files", []), *a.get("trees", []), *a.get("folders", [])]
    loose = [f"{p} {'missing' if not os.path.lexists(p) else 'writable'}" for p in paths
             if not os.path.lexists(p) or floor.writable(p)]
    return [f"acl: {a['account']} denied {len(paths)} paths" + (f"; NOT held: {', '.join(loose[:6])}" if loose else
                                                                ", all held")]


def _in_force(lock: dict) -> str:
    """Whether Claude Code reads the managed file (round 8 #9): its managed sources are first-wins, server-managed
    settings, then the HKLM policy (Windows), then the files; one of the first two holding a policy skips the files."""
    if os.name != "nt":
        return "hooks: in force when no server-managed settings apply to this account (Claude Code reads those first)"
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Policies\ClaudeCode"):
            return ("hooks: NOT in force: an HKLM policy (SOFTWARE\\Policies\\ClaudeCode) comes before the managed "
                    "files; put the lock's settings there or remove it")
    except OSError:
        pass
    return "hooks: in force unless server-managed settings apply to this account (Claude Code reads those first)"


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
