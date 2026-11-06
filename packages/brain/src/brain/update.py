"""Is a newer engine out, and the owner's update to it (wi-brain-tui-update-check, ADR UPD-1 to UPD-3).

:func:`check` reads the engine's release tags (``vX.Y.Z``) from its public repo, ``config.json`` ``engine.repo``
(else the repo this package is published from), with ``git ls-remote --tags``: no token, no credential helper, no
prompt. The answer is kept 24 h in ``<BRAIN_HOME>/update.json``; offline, or when git fails, it says nothing new
(the last answer kept, else none). The cockpit runs it in a worker after its first paint, so the screen never waits
on it, and shows the answer in its title bar: ``brain 0.2.2 · 0.2.3 available``.

:func:`pinned` reads, with no network, how the installed engine stands to the brain's ``config.json`` ``engine.pin``
(behind once a pin PR merged and before the installer's ``-Apply``, equal, ahead) and the installer the brain declares
(``engine.installer``; the engine names none, and a brain from ``brain init`` has none, so ``brain update`` stays its
path). When the installed engine lags the pin and the brain declares its installer (:func:`applies`, ADR INST-1), the
title bar says so, ``brain 0.2.1 · pin v0.2.3: -Apply``, and the cockpit's ``u`` opens that installer's plan, then
``-Apply`` on the owner's yes, through a window that installs once the cockpit has exited (brain.handover, INST-2).

:func:`plan` is what ``brain update`` does: the version and the CHANGELOG sections since the installed one (read
from the tag), installing the tag into the brain's venv (``<BRAIN_HOME>/venv``, pip, the extras installed kept), the
launcher swapped in (``<BRAIN_HOME>/bin/brain.exe``, even while a brain runs: install.ps1's Set-Launcher), and for a
pinned brain (``config.json`` ``engine.pin``) the pin to move. Which way the pin moves depends on the brain
(COMPAT-5, spec-brain-data-compat):

- a brain that declares its own installer (``engine.installer``, say install.ps1) moves it by a reviewed PR:
  shown, never done here (``pin.move`` ``"pr"``);
- a brain that declares none (one from ``brain init``, the pilot's) has no review step: the plan writes the new tag
  into ``engine.pin``, commits ``config.json`` alone in the brain's repo, then runs ``brain sync`` with the new engine
  (``pin.move`` ``"write"``). The pin also moves alone, with no install, when the installed engine is already the
  latest tag and past the pin (an update made before this one). It never moves backwards, nor to or from a pin that
  is not a release tag, nor for an editable install; a ``config.json`` with changes not committed is left as it is.

:func:`apply` runs it: only from ``brain update --yes``, the terminal's yes or the cockpit's confirmation (which runs
``brain update --yes`` in a window), the owner's gesture; never from a Claude Code session's shell, never on its own.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, config, paths

ENGINE_REPO = "RoJLD/brain"   # where this package is published (brain.init.ENGINE_REPO): the default engine.repo
CACHE = "update.json"         # <BRAIN_HOME>/update.json: the last tags read, and when
TTL_S = 24 * 3600.0           # UPD-1: one read a day at most
TIMEOUT_S = 15.0              # git ls-remote, and the CHANGELOG's read
TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
CHANGELOG = "https://raw.githubusercontent.com/{repo}/{tag}/packages/brain/CHANGELOG.md"
SECTION_RE = re.compile(r"^## (\d+\.\d+\.\d+)\b")
WINDOWS = os.name == "nt"


def version_of(tag: str) -> tuple[int, int, int] | None:
    """(X, Y, Z) of a release tag vX.Y.Z (or of X.Y.Z); None for anything else (a pre-release, a branch's tag)."""
    m = TAG_RE.match(tag if tag.startswith("v") else f"v{tag}")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def engine(root: Path | None = None) -> tuple[str, str | None]:
    """(repo, pin) of the brain's config.json engine: its repo (default :data:`ENGINE_REPO`) and its tag, or None
    when the brain pins none."""
    data = config.load(root).data.get("engine")
    data = data if isinstance(data, dict) else {}
    repo = data.get("repo") if isinstance(data.get("repo"), str) and data.get("repo") else ENGINE_REPO
    pin = data.get("pin") if isinstance(data.get("pin"), str) and data.get("pin") else None
    return repo, pin


def installer(root: Path | None = None) -> Path | None:
    """The brain's own installer, config.json ``engine.installer`` (a path from the brain's root): None when the brain
    declares none (a brain from brain init: brain update is its path) or the file is missing (brain config --check
    says so). The engine never names one itself (INST-1)."""
    cfg = config.load(root)
    data = cfg.data.get("engine")
    name = data.get("installer") if isinstance(data, dict) else None
    if not isinstance(name, str) or not name:
        return None
    f = cfg.root / name
    return f if f.is_file() else None


def declared_installer(root: Path | None = None) -> str | None:
    """The installer config.json ``engine.installer`` names, whether or not the file exists: a brain that declares
    one keeps the reviewed pin PR even while the file is missing (brain config --check says so)."""
    data = config.load(root).data.get("engine")
    name = data.get("installer") if isinstance(data, dict) else None
    return name if isinstance(name, str) and name else None


def lag(installed: str, pin: str | None) -> str | None:
    """How the installed engine stands to the brain's pin: behind (a pin PR merged, the installer's -Apply not run
    yet), equal or ahead (a branch's engine, or brain update past the pin); None without a pin or a version."""
    mine, want = version_of(installed), version_of(pin or "")
    if not mine or not want:
        return None
    return "behind" if mine < want else "equal" if mine == want else "ahead"


def pinned(root: Path | None = None, installed: str = __version__) -> dict:
    """{pin, lag, installer, root}: the brain's pin, how the installed engine stands to it, its installer as
    config.json declares it (from the brain's root, None when it declares none or the file is missing) and that
    root. Local files only, no network; never raises."""
    try:
        _, pin = engine(root)
        inst, home = installer(root), config.load(root).root
    except Exception:  # a config that cannot be read never stops the cockpit
        pin, inst, home = None, None, None
    return {"pin": pin, "lag": lag(installed, pin), "installer": inst.relative_to(home).as_posix() if inst else None,
            "root": str(home) if home else None}


def remote_tags(repo: str, runner=subprocess.run) -> list[str]:
    """The release tags of github.com/<repo>, read with git ls-remote without a token: no credential helper, no
    prompt (a missing repo fails instead of asking). Raises OSError when git cannot read them."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
    try:
        proc = runner(["git", "-c", "credential.helper=", "ls-remote", "--tags", "--refs",
                       f"https://github.com/{repo}.git"], capture_output=True, text=True, timeout=TIMEOUT_S,
                      stdin=subprocess.DEVNULL, env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        raise OSError(f"git ls-remote {repo}: {exc}") from exc
    if proc.returncode != 0:
        raise OSError(f"git ls-remote {repo}: exit {proc.returncode}")
    tags = [line.rsplit("refs/tags/", 1)[-1].strip() for line in (proc.stdout or "").splitlines() if "refs/tags/" in line]
    return sorted((t for t in tags if version_of(t)), key=version_of)


def cache_file() -> Path:
    return paths.brain_home() / CACHE


def _read_cache() -> dict:
    try:
        data = json.loads(cache_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_cache(data: dict) -> None:
    try:
        f = cache_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, f)
    except OSError:
        pass  # a cache that cannot be written only means the next opening reads the tags again


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch(iso: str | None) -> float | None:
    try:
        return datetime.strptime(str(iso), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def check(root: Path | None = None, *, refresh: bool = False, now: float | None = None, fetch=None,
          installed: str = __version__) -> dict:
    """Whether a newer engine is out: {installed, latest, newer, repo, pin, lag, installer, checked, source} (``lag``
    and ``installer``: :func:`pinned`). ``source`` says where
    ``latest`` comes from: cache (read less than 24 h ago), remote (read now), offline (the tags could not be read:
    the last answer kept, or none). Never raises: a failure is silent (UPD-1). ``refresh`` reads the tags even when
    the cache is fresh; ``fetch`` (tests) stands for :func:`remote_tags`."""
    now = time.time() if now is None else now
    try:
        repo, pin = engine(root)
    except Exception:  # a config that cannot be read never stops the check
        repo, pin = ENGINE_REPO, None
    cached = _read_cache()
    if cached.get("repo") != repo:
        cached = {}  # another engine's tags
    tags, checked, source = cached.get("tags"), cached.get("checked"), "cache"
    at = _epoch(checked)
    if refresh or at is None or not 0 <= now - at < TTL_S:
        try:
            tags = (fetch or remote_tags)(repo)
            source, checked = "remote", _iso(now)
            _write_cache({"repo": repo, "checked": checked, "tags": list(tags)})
        except Exception:  # offline, git missing, the repo gone: silent
            source = "offline"
    versions = sorted((t for t in (tags or []) if isinstance(t, str) and version_of(t)), key=version_of)
    latest = versions[-1][1:] if versions else None
    mine = version_of(installed)
    newer = bool(latest and mine and version_of(latest) > mine)
    return {"installed": installed, "latest": latest, "newer": newer, "repo": repo, "checked": checked,
            "source": source, **pinned(root, installed), "pin": pin}


def applies(info: dict | None) -> bool:
    """Whether the brain's installer is the way to the engine it wants: the installed one lags the pin and the brain
    declares an installer (INST-1). Else brain update is, when a newer tag is out."""
    return bool(info and info.get("lag") == "behind" and info.get("installer"))


def title(info: dict | None, installed: str = __version__) -> str:
    """The cockpit's title: the installed version; the pin when the installed engine lags it and the brain's
    installer applies it (« brain 0.2.1 · pin v0.2.3: -Apply »); the newer tag when there is one past the pin."""
    parts = [f"brain {(info or {}).get('installed') or installed}"]
    if applies(info):
        parts.append(f"pin {info['pin']}: -Apply")
    if info and info.get("newer") and not (applies(info) and version_of(info["latest"]) <= version_of(info["pin"])):
        parts.append(f"{info['latest']} available")
    return " · ".join(parts)


# --- the plan ---

def venv_python() -> Path:
    """The interpreter of the brain's venv, <BRAIN_HOME>/venv (install.ps1's), else $BRAIN_PYTHON."""
    venv = paths.brain_home() / "venv"
    py = venv / ("Scripts/python.exe" if WINDOWS else "bin/python")
    if not py.is_file() and os.environ.get("BRAIN_PYTHON"):
        return Path(os.environ["BRAIN_PYTHON"]).expanduser()
    return py


def _site_packages(py: Path) -> list[Path]:
    venv = py.parent.parent
    return [venv / "Lib" / "site-packages", *sorted(venv.glob("lib/python3*/site-packages"))]


def extras(py: Path) -> list[str]:
    """The extras installed in that venv, kept by the update: tui when Textual is there."""
    return ["tui"] if any(any(d.glob("textual-*.dist-info")) for d in _site_packages(py) if d.is_dir()) else []


def spec(repo: str, tag: str, extra: list[str]) -> str:
    """The pip spec of the engine at a tag, as install.ps1 writes it (research-graph comes at the same tag)."""
    name = f"brain[{','.join(extra)}]" if extra else "brain"
    return f"{name} @ git+https://github.com/{repo}.git@{tag}#subdirectory=packages/brain"


def launcher(py: Path) -> tuple[Path, Path] | None:
    """(the venv's launcher, the copy on the PATH) on Windows, where the installer copies it into <BRAIN_HOME>/bin;
    None elsewhere (~/.local/bin/brain is a link to the venv's, which pip replaces in place)."""
    if not WINDOWS:
        return None
    return py.parent / "brain.exe", paths.brain_home() / "bin" / "brain.exe"


def changelog(repo: str, tag: str, since: str, opener=None) -> list[str] | None:
    """The CHANGELOG sections after ``since`` up to the tag's version, read from the tag on GitHub; None when it
    cannot be read."""
    from urllib.request import urlopen  # here: urllib.request costs ~50 ms to import

    try:
        with (opener or urlopen)(CHANGELOG.format(repo=repo, tag=tag), timeout=TIMEOUT_S) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None
    return sections(text, since, tag[1:])


def sections(text: str, since: str, upto: str) -> list[str]:
    """The lines of the CHANGELOG's sections whose version is after ``since`` and at most ``upto``."""
    low, high = version_of(since), version_of(upto)
    out, keep = [], False
    for line in text.splitlines():
        m = SECTION_RE.match(line)
        if m:
            v = version_of(m.group(1))
            keep = bool(v and low and high and low < v <= high)
        elif line.startswith("## "):
            keep = False  # Unreleased, or another heading: not part of a release
        if keep:
            out.append(line)
    while out and not out[-1].strip():
        out.pop()
    return out


def plan(info: dict, root: Path | None = None, *, read_changelog=None) -> dict:
    """What brain update would do for ``info`` (:func:`check`): {installed, latest, tag, repo, changelog, python,
    spec, launcher, pin, blocked}. ``blocked`` says why there is nothing to apply ('' when there is)."""
    installed, latest, repo = info["installed"], info.get("latest"), info["repo"]
    py = venv_python()
    out = {"installed": installed, "latest": latest, "tag": f"v{latest}" if latest else None, "repo": repo,
           "checked": info.get("checked"), "source": info.get("source"), "changelog": None, "python": str(py),
           "spec": None, "launcher": None, "pin": None, "blocked": ""}
    target = f"v{latest}" if info.get("newer") else f"v{installed}"
    pin = info.get("pin")
    editable = paths.installed_checkout()
    if pin and pin != target:
        cfg = config.load(root)
        out["pin"] = {"file": str(cfg.file) if cfg.file else config.FILE, "from": pin, "to": target,
                      "move": _pin_move(cfg, pin, target, latest, editable, py)}
    if not latest:
        out["blocked"] = f"the tags of {repo} could not be read (offline?)"
        return out
    if not info.get("newer"):
        out["blocked"] = f"brain {installed} is the latest"
        return out
    out["changelog"] = (read_changelog or changelog)(repo, out["tag"], installed)
    if editable:
        out["blocked"] = f"brain is installed editable from {editable}: update that checkout (git pull) instead"
        return out
    if not py.is_file():
        out["blocked"] = (f"no brain venv at {py.parent.parent}: install the engine first (installer/install.ps1, "
                          "docs/install.md)")
        return out
    out["spec"] = spec(repo, out["tag"], extras(py))
    pair = launcher(py)
    out["launcher"] = [str(pair[0]), str(pair[1])] if pair else None
    return out


def _pin_move(cfg, pin: str, target: str, latest: str | None, editable, py: Path) -> str:
    """How the plan moves the pin (COMPAT-5): "write" (written, committed, then brain sync) for a brain that declares
    no installer, forwards to the latest release tag, installed into the brain's venv; "pr" (shown: a reviewed PR,
    or by hand) otherwise."""
    if cfg.file is None or cfg.error or declared_installer(cfg.root) or config.unexpected(cfg):
        return "pr"
    have, want = version_of(pin), version_of(target)
    if not have or not want or want <= have or target != f"v{latest}" or editable or not py.is_file():
        return "pr"
    return "write"


def pin_writes(p: dict) -> bool:
    """Whether the plan writes and commits the pin itself (a brain without an installer of its own)."""
    return bool(p.get("pin") and p["pin"].get("move") == "write")


def runs(p: dict) -> bool:
    """Whether the plan has anything to run on the owner's yes: an install, or the pin alone."""
    return bool(p.get("spec") or pin_writes(p))


def lines(p: dict) -> list[str]:
    """The plan in text: what brain update --check prints and the cockpit's confirmation shows."""
    when = f", checked {p['checked'].replace('T', ' ').rstrip('Z')} UTC" if p.get("checked") else ""
    off = " (offline: the last answer)" if p.get("source") == "offline" and p.get("latest") else ""
    newer = bool(p.get("latest") and version_of(p["latest"]) > (version_of(p["installed"]) or (0, 0, 0)))
    if not p.get("latest"):
        out = [f"brain {p['installed']}: the tags of {p['repo']} could not be read (offline?); nothing to update"]
    elif not newer:
        out = [f"brain {p['installed']} is up to date (the latest tag of {p['repo']} is v{p['latest']}{when}{off})"]
    else:
        out = [f"brain {p['installed']} installed; {p['tag']} is the latest tag of {p['repo']}{when}{off}"]
        if p.get("changelog") is not None:
            out += ["", f"What changes (CHANGELOG since {p['installed']}):"]
            out += [f"  {line}" if line else "" for line in p["changelog"]] or ["  (no section for these versions)"]
        else:
            out += ["", f"What changes: the CHANGELOG at {p['tag']} could not be read"]
    steps = []
    if p.get("spec"):
        steps.append(f"install  brain {p['tag']} into {Path(p['python']).parent.parent} "
                     f"(pip install \"{p['spec']}\")")
        if p.get("launcher"):
            steps.append(f"launcher {p['launcher'][0]} -> {p['launcher'][1]} (swapped in even while a brain runs)")
    if pin_writes(p):
        pin = p["pin"]
        where = Path(pin["file"]).parent
        steps.append(f"pin      {Path(pin['file']).name} engine.pin {pin['from']} -> {pin['to']}: written and committed "
                     f"in {where} (this brain declares no installer of its own: no pin PR to review)")
        steps.append(f"sync     brain sync in {where}, with {pin['to']} (the plugin's hooks and views)")
    elif p.get("pin"):
        pin = p["pin"]
        steps.append(f"pin      {Path(pin['file']).name} engine.pin {pin['from']} -> {pin['to']}: move it by a reviewed "
                     f"PR in {Path(pin['file']).parent} (shown, not done here; until it merges, the installer's next "
                     f"-Apply installs {pin['from']} back)")
    if p.get("spec"):
        steps.append(f"restart  brain tui and the sessions, to run {p['tag']}")
    if steps:
        out += ["", "The plan (brain update --yes, or the cockpit's u, runs it on the owner's yes):"
                if runs(p) else "To do by hand:", *(f"  {s}" for s in steps)]
    if p.get("blocked") and newer:
        out += ["", f"Not applicable here: {p['blocked']}"]
    return out


# --- applying it: the owner's gesture only ---

def set_launcher(src: Path, dst: Path) -> str:
    """install.ps1's Set-Launcher in Python (wi-brain-install-running-exe): an identical launcher is left alone, a new
    one is copied beside it and swapped in with a short retry, and one still locked (Windows refuses to overwrite a
    running image, which a brain update run from it is) is renamed aside and removed on the next run. Returns same,
    copied or swapped."""
    import hashlib
    import shutil

    for old in dst.parent.glob(f"{dst.name}.old-*"):
        try:
            old.unlink()
        except OSError:
            pass
    if dst.is_file() and hashlib.sha256(dst.read_bytes()).digest() == hashlib.sha256(src.read_bytes()).digest():
        return "same"
    dst.parent.mkdir(parents=True, exist_ok=True)
    new = dst.with_name(f"{dst.name}.new")
    shutil.copyfile(src, new)
    for wait in (0.2, 0.4, 0.8, 1.6):
        try:
            os.replace(new, dst)
            return "copied"
        except OSError:
            time.sleep(wait)
    dst.rename(dst.with_name(f"{dst.name}.old-{datetime.now().strftime('%Y%m%d%H%M%S')}"))
    os.replace(new, dst)
    return "swapped"


def _git(root: Path, *args: str, runner=subprocess.run):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    return runner(["git", "-C", str(root), *args], capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env)


def write_pin(file: Path, frm: str, to: str) -> None:
    """engine.pin ``frm`` -> ``to`` in config.json, its other keys, their order and its indent kept, written
    atomically (brain.stateio.write_atomic; git holds the previous version, so no .bak beside it). Raises ValueError
    when the file no longer pins ``frm`` (moved since the plan) or is not JSON."""
    from . import stateio

    text = file.read_text(encoding="utf-8-sig")
    data = json.loads(text)
    eng = data.get("engine") if isinstance(data, dict) else None
    if not isinstance(eng, dict) or eng.get("pin") != frm:
        raise ValueError(f"{file.name} engine.pin is no longer {frm}: nothing written (brain update again)")
    eng["pin"] = to
    m = re.search(r"\n([ \t]+)\S", text)
    indent = m.group(1) if m else None
    stateio.write_atomic(file, json.dumps(data, indent=indent, ensure_ascii=False) + "\n")


def move_pin(p: dict, runner=subprocess.run) -> tuple[int, list[str]]:
    """The pin step of a brain without an installer of its own (COMPAT-5): config.json written and committed alone
    in the brain's repo, then brain sync run with the venv's engine. Refused, nothing written, when the brain's root
    is not a git repo or config.json has changes not committed."""
    pin = p["pin"]
    file = Path(pin["file"])
    root = file.parent
    hand = f"move {file.name} engine.pin {pin['from']} -> {pin['to']} and commit it, then brain sync"
    top = _git(root, "rev-parse", "--show-toplevel", runner=runner)
    if top.returncode != 0:
        return 1, [f"pin      {root} is not a git repo: nothing written; {hand}"]
    dirty = _git(root, "status", "--porcelain", "--", file.name, runner=runner)
    if dirty.returncode != 0 or (dirty.stdout or "").strip():
        return 1, [f"pin      {file.name} has changes not committed: nothing written; commit them, then brain update "
                   f"again (or {hand})"]
    try:
        write_pin(file, pin["from"], pin["to"])
    except (OSError, ValueError) as exc:
        return 1, [f"pin      {exc}"]
    msg = f"brain update: engine.pin {pin['from']} -> {pin['to']}"
    done = _git(root, "commit", "--quiet", "-m", msg, "--", file.name, runner=runner)
    if done.returncode != 0:
        said = ((done.stdout or "") + (done.stderr or "")).strip().splitlines()[-10:]
        return 1, [f"pin      {file.name} engine.pin written ({pin['to']}), but git commit failed (exit "
                   f"{done.returncode}): commit it yourself, then brain sync", *said]
    out = [f"pin      {file.name} engine.pin {pin['from']} -> {pin['to']}, committed in {root} ({msg!r})"]
    try:
        sync = runner([p["python"], "-m", "brain", "--root", str(root), "sync"], capture_output=True, text=True,
                      stdin=subprocess.DEVNULL, cwd=str(root))
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, [*out, f"sync     brain sync failed: {exc}; run it in {root}"]
    said = ((sync.stdout or "") + (sync.stderr or "")).strip().splitlines()
    if sync.returncode != 0:
        return 1, [*out, f"sync     brain sync failed with exit code {sync.returncode}: run it in {root}", *said[-20:]]
    return 0, [*out, f"synced   brain sync in {root}"]


def apply(p: dict, runner=subprocess.run) -> tuple[int, list[str]]:
    """Run a plan's install and launcher steps, then its pin step: moved, committed and synced for a brain without
    an installer of its own (:func:`move_pin`), shown only for one with (a reviewed PR): (exit code, what was done).
    A plan with no install but a pin to write moves the pin alone."""
    if not p.get("spec"):
        if pin_writes(p):
            return move_pin(p, runner)
        return 1, [p.get("blocked") or "nothing to apply"]
    if p.get("blocked"):
        return 1, [p["blocked"]]
    cmd = [p["python"], "-m", "pip", "install", "--quiet", "--disable-pip-version-check", p["spec"]]
    try:
        proc = runner(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, [f"pip install failed: {exc}"]
    said = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if proc.returncode != 0:
        return 1, [f"pip install \"{p['spec']}\" failed with exit code {proc.returncode}", *said.splitlines()[-20:]]
    out = [f"installed brain {p['tag']} into {Path(p['python']).parent.parent}"]
    if p.get("launcher"):
        src, dst = Path(p["launcher"][0]), Path(p["launcher"][1])
        try:
            out.append(f"{set_launcher(src, dst)} {dst}" if src.is_file() else f"launcher {src} missing: rerun the "
                       "installer")
        except OSError as exc:
            return 1, [*out, f"launcher {dst}: {exc} (rerun installer/install.ps1 -Apply)"]
    code = 0
    if pin_writes(p):
        code, moved = move_pin(p, runner)
        out += moved
    elif p.get("pin"):
        pin = p["pin"]
        out.append(f"to do    move {Path(pin['file']).name} engine.pin {pin['from']} -> {pin['to']} by a reviewed PR")
    out.append(f"restart  brain tui and the sessions, to run {p['tag']}")
    return code, out


def main(root: Path | None, *, check_only: bool, yes: bool, as_json: bool, refused: str = "",
         ask=None, out=print) -> int:
    """brain update: the plan (always), then on the owner's yes (--yes, or y in a terminal) its install."""
    p = plan(check(root, refresh=True), root)
    if as_json:
        out(json.dumps(p, ensure_ascii=False, indent=1, sort_keys=True))
    else:
        out("\n".join(lines(p)))
    if check_only or not runs(p):
        return 0
    if refused:
        out(f"brain update: {refused}; run it yourself in a terminal")
        return 1
    if not yes:
        moving = f"move engine.pin to {p['pin']['to']}, commit it and run brain sync" if pin_writes(p) else ""
        if ask is None and not sys.stdin.isatty():
            out("brain update --yes " + ("installs it" + (" and moves the pin" if moving else "") if p.get("spec")
                                         else "moves the pin"))
            return 0
        question = f"Install brain {p['tag']}" + (f", {moving}" if moving else "") if p.get("spec") else \
            moving[0].upper() + moving[1:]
        reply = (ask or input)(f"{question} now? [y/N] ")
        if reply.strip().lower() not in ("y", "yes", "o", "oui"):
            out("nothing installed" if p.get("spec") else "nothing moved")
            return 0
    code, done = apply(p)
    out("\n".join(done))
    return code
