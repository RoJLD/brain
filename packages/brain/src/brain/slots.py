"""Blue-green engine slots (wi-brain-update-blue-green, the owner's pillar 4.3; the layout of
ddr-2026-11-12-blue-green-engine-slots, « venvs and a link »).

``brain update`` no longer installs a new version over the running one. It installs it **beside** the old, in a venv
of its own, ``<BRAIN_HOME>/venvs/vX.Y.Z`` (:data:`SLOTS`), runs the **health gate** there (:func:`smoke`: the
version, ``brain doctor --quick``, the guards' import and a harmless command they must let pass), and only then
**switches**: ``<BRAIN_HOME>/venv``, the path every reader already follows (the hooks, the installer, the
transitional shim), becomes a link to the new slot (a directory junction on Windows, a symlink elsewhere). The
launcher on the PATH is left as it is: the installer's runs ``<BRAIN_HOME>/venv``'s Python, so it follows the link (a
slot's own launcher would tie ``sys.executable``, and what records it, such as the schedules, to a slot a prune
removes later). After the switch the **watchdog** (:func:`watch`) runs the version through ``<BRAIN_HOME>/venv`` and
through the launcher; if either fails, the link goes back to the previous slot. The previous slots are kept
(:data:`KEEP` in all, the active one included), so switching back later is the same rename (:func:`switch`); a slot
a running process still holds a file of is never pruned (it cannot be renamed aside first).

- **The switch** is a rename of a link, never of a venv's files: a Python running through the old link (a hook, the
  cockpit, ``brain update`` itself) keeps running. On Windows a junction cannot replace another in one call, so the
  old link is renamed aside, the new one renamed in, and the old removed (a link removed with ``os.rmdir``: never its
  target's files); between the two renames, for a few microseconds, ``venv`` is missing and a hook falls back to the
  Python on the PATH, as it does for a machine without the command. On Linux and macOS ``os.replace`` swaps the
  symlink atomically.
- **The first update** of a machine finds ``venv`` a real folder (the installer's). It is renamed, whole, into
  ``venvs/v<its version>`` (a rename of the folder works while a Python runs from it on Windows, measured; not while
  a process holds a file open inside it: then the switch is refused, nothing changed, and the plan says to close the
  cockpit and try again), then the link takes its place: that slot is the one the watchdog switches back to.
- The **installer** keeps working unchanged: it reads and installs into ``<BRAIN_HOME>/venv``, which a link makes the
  active slot; a reinstall there is an install in place, without this gate.
- Nothing here runs without the owner's gesture: :func:`brain.update.apply` calls it, from ``brain update --yes`` or
  the owner's ``y``.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

from . import paths

SLOTS = "venvs"            # <BRAIN_HOME>/venvs/vX.Y.Z: one venv per engine version
ACTIVE = "venv"            # <BRAIN_HOME>/venv: the active slot, a link once a blue-green update ran
KEEP = 3                   # slots kept, the active one included
TIMEOUT_S = 120.0          # each smoke and watchdog step
SLOT_RE = re.compile(r"^v\d+\.\d+\.\d+$")
WINDOWS = os.name == "nt"


def home() -> Path:
    return paths.brain_home()


def slots_dir() -> Path:
    return home() / SLOTS


def active_path() -> Path:
    return home() / ACTIVE


def slot(tag: str) -> Path:
    return slots_dir() / tag


def python_of(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if WINDOWS else "bin/python")


def launcher_of(venv: Path) -> Path:
    return venv / ("Scripts/brain.exe" if WINDOWS else "bin/brain")


# --- the link ---

def is_link(p: Path) -> bool:
    """A symlink, or a directory junction on Windows (Python 3.10 and 3.11 have no Path.is_junction)."""
    if p.is_symlink():
        return True
    try:
        st = os.lstat(p)
    except OSError:
        return False
    return getattr(st, "st_reparse_tag", 0) == getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", -1)


def target(p: Path) -> Path | None:
    """The folder a link points to; None for a real folder or nothing."""
    if not is_link(p):
        return None
    try:
        raw = os.readlink(p)
    except OSError:
        return None
    raw = raw[4:] if raw.startswith("\\\\?\\") else raw
    t = Path(raw)
    return t if t.is_absolute() else (p.parent / t)


def make_link(to: Path, link: Path) -> None:
    """``link`` -> ``to``: a junction on Windows (no privilege needed, unlike a symlink), a symlink elsewhere."""
    if WINDOWS:
        import _winapi

        _winapi.CreateJunction(str(to), str(link))
    else:
        os.symlink(to, link, target_is_directory=True)


def remove_link(link: Path) -> None:
    """The link alone, never its target's files (os.rmdir removes a junction; a symlink is unlinked)."""
    if WINDOWS and not link.is_symlink():
        os.rmdir(link)
    else:
        os.unlink(link)


def active() -> Path | None:
    """The active slot (what ``<BRAIN_HOME>/venv`` links to); None when it is a real folder or missing."""
    return target(active_path())


def switch(to: Path, *, aside_for: str = "") -> Path | None:
    """Make ``<BRAIN_HOME>/venv`` the link to the slot ``to``; returns what it was before (a slot, or the slot the real
    folder was moved into: ``venvs/<aside_for>``), None when there was nothing. Raises OSError, with everything as it
    was, when a rename is refused."""
    venv = active_path()
    _clear_stale_links()
    tmp = venv.with_name(f"{ACTIVE}.switch-{os.getpid()}.tmp")
    make_link(to, tmp)
    try:
        if is_link(venv):
            before = target(venv)
            if WINDOWS:
                aside = venv.with_name(f"{ACTIVE}.prev-{os.getpid()}.tmp")
                os.rename(venv, aside)
                try:
                    os.rename(tmp, venv)
                except OSError:
                    os.rename(aside, venv)
                    raise
                try:   # the switch is done: a link left aside is cleared by the next switch, never an error now
                    remove_link(aside)
                except OSError:
                    pass
            else:
                os.replace(tmp, venv)
            return before
        if venv.exists():   # the installer's real folder: moved, whole, into its own slot
            dest = slots_dir() / (aside_for or f"v0.0.0-{time.strftime('%Y%m%d%H%M%S')}")
            if dest.exists() or is_link(dest):
                dest = dest.with_name(f"{dest.name}-{time.strftime('%Y%m%d%H%M%S')}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.rename(venv, dest)
            try:
                os.rename(tmp, venv)
            except OSError:
                os.rename(dest, venv)
                raise
            return dest
        os.rename(tmp, venv)
        return None
    finally:
        if is_link(tmp):
            remove_link(tmp)


def _clear_stale_links() -> None:
    """The links an interrupted switch left beside venv (``venv.switch-*.tmp``, ``venv.prev-*.tmp``): links only,
    never a folder."""
    for p in home().glob(f"{ACTIVE}.*-*.tmp"):
        if is_link(p) and (p.name.startswith(f"{ACTIVE}.switch-") or p.name.startswith(f"{ACTIVE}.prev-")):
            try:
                remove_link(p)
            except OSError:
                pass


# --- the base interpreter, a slot's creation ---

def base_python(venv: Path) -> Path | None:
    """The interpreter a venv was made from (its pyvenv.cfg ``executable``, else ``home``'s python): the one a new
    slot is made from, so that every slot runs the same Python. None when it cannot be found."""
    cfg = venv / "pyvenv.cfg"
    try:
        text = cfg.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    keys = {}
    for line in text.splitlines():
        k, sep, v = line.partition("=")
        if sep:
            keys[k.strip().lower()] = v.strip()
    exe = Path(keys["executable"]) if keys.get("executable") else None
    if exe and exe.is_file():
        return exe
    home_dir = Path(keys["home"]) if keys.get("home") else None
    minor = ".".join((keys.get("version") or keys.get("version_info") or "").split(".")[:2])
    names = ("python.exe",) if WINDOWS else (*((f"python{minor}",) if minor else ()), "python3", "python")
    for name in names:   # the same minor version first: /usr/bin/python3 may be another one
        if home_dir and (home_dir / name).is_file():
            return home_dir / name
    return None


def _run(cmd: list[str], runner, **kw) -> subprocess.CompletedProcess:
    try:
        return runner(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                      stdin=subprocess.DEVNULL, timeout=kw.pop("timeout", TIMEOUT_S), **kw)
    except (OSError, subprocess.SubprocessError) as exc:   # said as a failure, never raised
        return subprocess.CompletedProcess(cmd, 127, "", f"{type(exc).__name__}: {exc}")


def _said(proc) -> str:
    lines = [ln.strip() for ln in f"{proc.stdout or ''}\n{proc.stderr or ''}".splitlines() if ln.strip()]
    return " / ".join(lines[-3:]) or f"exit {proc.returncode}"


def create(dest: Path, base: Path, spec: str, runner=subprocess.run) -> list[str]:
    """A new slot: ``base -m venv dest`` (made again when an earlier try left it half made: no pip in it), then pip
    installs ``spec`` into it. [] when done, else the lines that say what failed. Never the active slot."""
    py = python_of(dest)
    live = active()
    if live and os.path.normcase(os.path.realpath(live)) == os.path.normcase(os.path.realpath(dest)):
        return [f"slot     {dest} is the active one: nothing installed over it"]
    if dest.exists() and not (py.is_file() and _has_pip(dest)):
        _remove_tree(dest)   # a half-made slot (venv or ensurepip interrupted): made anew
    if not py.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        made = _run([str(base), "-m", "venv", str(dest)], runner, timeout=600)
        if made.returncode != 0 or not py.is_file():
            _remove_tree(dest)
            return [f"slot     {base} -m venv {dest} failed (exit {made.returncode}): {_said(made)}"]
    got = _run([str(py), "-m", "pip", "install", "--quiet", "--disable-pip-version-check", spec], runner, timeout=1800)
    if got.returncode != 0:
        return [f"pip install \"{spec}\" into {dest} failed with exit code {got.returncode}",
                *((got.stdout or "") + (got.stderr or "")).strip().splitlines()[-20:]]
    return []


# --- the health gate and the watchdog ---

SMOKE_GUARD = ("import json, sys; import research_graph; from brain import guards; "
               "r = list(guards.refusals({'tool_name': 'Bash', 'tool_input': {'command': 'git status'}, "
               "'cwd': sys.argv[1]})); print(json.dumps([x[0] for x in r])); sys.exit(1 if r else 0)")


def smoke(py: Path, version: str, root: Path | None, runner=subprocess.run) -> list[str]:
    """The health gate, run by the slot's own Python before any switch: [] when it passes, else what failed.

    1. ``brain --version`` names ``version``;
    2. ``brain --root <the brain> doctor --quick --json`` exits 0 (the machine's facts and the brain's profile, read
       by the new engine); skipped without a brain's root (it needs one);
    3. the guards import, with research-graph, and let ``git status`` pass in the brain's root (a guard that cannot
       run refuses every commit and push: the worst way for an update to fail).
    """
    failed = []
    v = _run([str(py), "-I", "-m", "brain", "--version"], runner)
    if v.returncode != 0 or version not in (v.stdout or ""):
        failed.append(f"smoke    brain --version: not {version} ({_said(v)})")
        return failed   # nothing else can be trusted
    if root:
        d = _run([str(py), "-I", "-m", "brain", "--root", str(root), "doctor", "--quick", "--json"], runner)
        if d.returncode != 0:
            failed.append(f"smoke    brain doctor --quick: exit {d.returncode} ({_said(d)})")
    g = _run([str(py), "-I", "-c", SMOKE_GUARD, str(root or home())], runner)
    if g.returncode != 0:
        failed.append(f"smoke    the guards on git status: exit {g.returncode} ({_said(g)})")
    return failed


def watch(version: str, launcher: Path | None, runner=subprocess.run) -> list[str]:
    """The watchdog, after the switch: ``brain --version`` through ``<BRAIN_HOME>/venv`` (what the hooks run) and
    through the launcher on the PATH (what the owner and the schedules run); [] when both name ``version``."""
    failed = []
    for what, cmd in (("venv", [str(python_of(active_path())), "-I", "-m", "brain", "--version"]),
                      ("launcher", [str(launcher), "--version"] if launcher else None)):
        if cmd is None:
            continue
        r = _run(cmd, runner)
        if r.returncode != 0 or version not in (r.stdout or ""):
            failed.append(f"watch    {what}: brain --version is not {version} ({_said(r)})")
    return failed


# --- the slots kept ---

def _version(name: str) -> tuple[int, ...]:
    return tuple(int(x) for x in name[1:].split(".")) if SLOT_RE.match(name) else (0,)


def prune(keep_also: list[Path | None], keep: int = KEEP) -> list[str]:
    """Remove the oldest slots beyond ``keep`` (by version), never the active one nor those of ``keep_also``; only
    folders named vX.Y.Z under venvs/, never a link. The lines of what was removed (or could not be: a file in use)."""
    d = slots_dir()
    if not d.is_dir():
        return []
    spare = {os.path.normcase(os.path.realpath(p)) for p in [active(), *keep_also] if p}
    found = sorted((p for p in d.iterdir() if SLOT_RE.match(p.name) and p.is_dir() and not is_link(p)),
                   key=lambda p: _version(p.name), reverse=True)
    out = []
    kept = 0
    for p in found:
        if os.path.normcase(os.path.realpath(p)) in spare or kept < keep:
            kept += 1
            continue
        # renamed aside first: a slot a running process still holds a file of cannot be renamed, so it is kept whole
        # rather than half deleted under that process
        trash = p.with_name(f".{p.name}.pruned-{os.getpid()}")
        try:
            os.rename(p, trash)
        except OSError as exc:
            out.append(f"kept     {p}: in use ({exc}); brain update tries again next time")
            continue
        _remove_tree(trash)
        out.append(f"pruned   {p} (an older slot; {keep} kept)")
    for left in d.glob(".v*.pruned-*"):   # what an earlier prune could not finish (a file that was still loaded)
        if left.is_dir() and not is_link(left):
            _remove_tree(left)
    return out


def _has_pip(venv: Path) -> bool:
    return any(any(sp.glob("pip/__init__.py")) for sp in (venv / "Lib" / "site-packages",
                                                          *venv.glob("lib/python3*/site-packages")) if sp.is_dir())


def _remove_tree(p: Path) -> None:
    """A folder of this module's own (a slot that is not active, a half-made one, one pruned); never a link (its
    target is never touched): what cannot be removed now is left."""
    if is_link(p) or not p.exists():
        return
    shutil.rmtree(p, ignore_errors=False, **({"onexc": _ignore_writable} if sys.version_info >= (3, 12)
                                             else {"onerror": _ignore_writable}))


def _ignore_writable(func, path, *_):
    try:
        _writable(func, path)
    except OSError:
        pass   # a file still loaded (a .pyd): left, cleared by a later prune


def _writable(func, path, *_):
    os.chmod(path, stat.S_IWRITE)
    func(path)
