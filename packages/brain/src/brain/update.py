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

Before an install, the plan verifies the tag (brain.tagsig, wi-brain-release-signing): ``git verify-tag`` against the
brain's ``allowed_signers`` (members.yaml's releaser role). pip installs the tag (brain.skew reads a release by its
tag), then the commits it recorded for brain and research-graph are compared with the verified one: a tag moved
between the check and the install is said. The plan says the verification either way; under config.json
``engine.verify_tags: true`` (the owner's opt-in, off by default) a tag not verified is refused.

After the install, when config.json lists public repos, the new engine runs ``brain check --public --refresh``
(brain.public.refresh, wi-brain-public-stamp-refresh): each local checkout of a public repo is checked with its
history and stamped again, since the push guard refuses a stamp of another engine; one with uncommitted work is
skipped and named. Its findings are said, never an install failure.

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

from . import __version__, config, net, paths, tagsig

ENGINE_REPO = "RoJLD/brain"   # where this package is published (brain.init.ENGINE_REPO): the default engine.repo
CACHE = "update.json"         # <BRAIN_HOME>/update.json: the last tags read, and when
TTL_S = 24 * 3600.0           # UPD-1: one read a day at most
TIMEOUT_S = 15.0              # git ls-remote, and the CHANGELOG's read
STAMPS_TIMEOUT_S = 1800.0     # brain check --public --refresh: every public checkout's history, after an install
SERVICE = "git-remote:github.com"   # the tags' breaker (brain.net); brain update's refresh closes it first
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
    try:   # under GitHub's breaker (brain.net): a timeout skips the next reads for a window
        proc = net.call(SERVICE, lambda: runner(
            ["git", "-c", "credential.helper=", "ls-remote", "--tags", "--refs", f"https://github.com/{repo}.git"],
            capture_output=True, text=True, timeout=TIMEOUT_S, stdin=subprocess.DEVNULL, env=env), retries=0)
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
        if refresh:   # asked for (brain update): tried even when a background check timed out a minute ago
            net.ok(SERVICE)
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
    """The pip spec of the engine at a tag (or at the commit a verified tag names), as install.ps1 writes it
    (research-graph comes at the tag the engine's pyproject pins)."""
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


def plan(info: dict, root: Path | None = None, *, read_changelog=None, verify=None) -> dict:
    """What brain update would do for ``info`` (:func:`check`): {installed, latest, tag, repo, changelog, python,
    spec, launcher, pin, signature, verify_tags, blocked}. ``blocked`` says why there is nothing to apply ('' when
    there is). ``signature`` is the tag's verification (brain.tagsig.verdict) when there is something to install:
    after the install the commits pip recorded are checked against it; one not verified is refused only under config.json
    engine.verify_tags. ``verify`` (tests) stands for brain.tagsig.verify."""
    installed, latest, repo = info["installed"], info.get("latest"), info["repo"]
    py = venv_python()
    out = {"installed": installed, "latest": latest, "tag": f"v{latest}" if latest else None, "repo": repo,
           "checked": info.get("checked"), "source": info.get("source"), "changelog": None, "python": str(py),
           "spec": None, "launcher": None, "pin": None, "signature": None, "verify_tags": False, "blocked": "",
           "stamps": None}
    target = f"v{latest}" if info.get("newer") else f"v{installed}"
    pin = info.get("pin")
    editable = paths.installed_checkout()
    if pin and pin != target:
        cfg = config.load(root)
        out["pin"] = {"file": str(cfg.file) if cfg.file else config.FILE, "from": pin, "to": target,
                      "move": _pin_move(cfg, pin, target, latest, editable, py, bool(info.get("newer")))}
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
    sig = _verified(root, repo, out["tag"], verify)
    out["signature"], out["verify_tags"] = sig, tagsig.required(root)
    if sig["status"] != tagsig.VERIFIED and out["verify_tags"]:
        out["blocked"] = f"refused: {tagsig.line(sig, True)}"
        out["pin"] = None   # never moved to a tag refused
        return out
    out["spec"] = spec(repo, out["tag"], extras(py))
    pair = launcher(py)
    out["launcher"] = [str(pair[0]), str(pair[1])] if pair else None
    out["stamps"] = _stamps_root(root)
    return out


def _stamps_root(root: Path | None) -> str | None:
    """The brain's root when its config.json lists public repos (wi-brain-public-stamp-refresh): after the install,
    the new engine re-checks their local checkouts (brain check --public --refresh), so that no stamp of the old engine
    is left for the push guard to refuse; None otherwise."""
    from . import public

    cfg = config.load(root)   # never raises: an unreadable config.json is a Config with an error and no data
    return str(cfg.root) if cfg.root and public.public_repos(cfg) else None


def _verified(root: Path | None, repo: str, tag: str, verify) -> dict:
    """The tag's verification; never raises (a failure is a verdict that says why)."""
    try:
        return (verify or tagsig.verify)(root, repo, tag)
    except Exception as exc:   # by design: the cockpit's plan never raises; the verdict says unverifiable and why
        return tagsig.verdict(tagsig.UNVERIFIABLE, tag, why=f"{type(exc).__name__}: {exc}")


def _pin_move(cfg, pin: str, target: str, latest: str | None, editable, py: Path, newer: bool) -> str:
    """How the plan moves the pin (COMPAT-5): "write" (written, committed, then brain sync) for a brain that declares
    no installer, forwards to the latest release tag, installed into the brain's venv; "pr" (shown: a reviewed PR,
    or by hand) otherwise."""
    if cfg.file is None or cfg.error or declared_installer(cfg.root) or config.unexpected(cfg):
        return "pr"
    have, want = version_of(pin), version_of(target)
    if not have or not want or want <= have or target != f"v{latest}" or editable or not py.is_file():
        return "pr"
    if not newer and venv_version(py) != latest:
        return "pr"   # the pin alone: only to the engine the brain's venv runs, whatever engine runs this command
    return "write"


def venv_version(py: Path) -> str | None:
    """The version of brain installed in that venv (its brain-X.Y.Z.dist-info), None when there is none or several."""
    found = {d.name[len("brain-"):-len(".dist-info")] for sp in _site_packages(py) if sp.is_dir()
             for d in sp.glob("brain-*.dist-info")}
    return found.pop() if len(found) == 1 else None


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
    if p.get("signature") and p.get("spec"):
        steps.append(f"verify   {tagsig.line(p['signature'], bool(p.get('verify_tags')))}")
    if p.get("spec"):
        steps.append(f"install  brain {p['tag']} into {Path(p['python']).parent.parent} "
                     f"(pip install \"{p['spec']}\")")
        if p.get("launcher"):
            steps.append(f"launcher {p['launcher'][0]} -> {p['launcher'][1]} (swapped in even while a brain runs)")
        if p.get("stamps"):
            steps.append(f"stamps   brain check --public --refresh by brain {p['tag']}: each local checkout of a "
                         "public repo re-checked and stamped for the push guard (one with uncommitted work skipped, "
                         "named)")
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
    cmd = ["git", "-C", str(root), *args]
    try:
        return runner(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env)
    except (OSError, subprocess.SubprocessError) as exc:   # git missing: said as a failure, never a traceback
        return subprocess.CompletedProcess(cmd, 127, "", str(exc))


def write_pin(file: Path, frm: str, to: str) -> None:
    """engine.pin ``frm`` -> ``to`` in config.json, its other keys, their order, its indent, its line endings and its
    BOM kept, written atomically (brain.stateio.write_atomic; git holds the previous version, so no .bak beside it).
    Raises ValueError when the file no longer pins ``frm`` (moved since the plan) or is not JSON."""
    from . import stateio

    raw = file.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    data = json.loads(text)
    eng = data.get("engine") if isinstance(data, dict) else None
    if not isinstance(eng, dict) or eng.get("pin") != frm:
        raise ValueError(f"{file.name} engine.pin is no longer {frm}: nothing written (brain update again)")
    eng["pin"] = to
    m = re.search(r"\n([ \t]+)\S", text)
    indent = m.group(1) if m else None
    out = json.dumps(data, indent=indent, ensure_ascii=False) + "\n"
    if "\r\n" in text:
        out = out.replace("\n", "\r\n")
    stateio.write_atomic(file, ("﻿" if bom else "") + out)


def move_pin(p: dict, runner=subprocess.run) -> tuple[int, list[str]]:
    """The pin step of a brain without an installer of its own (COMPAT-5): config.json written and committed alone
    in the brain's repo (not pushed), then brain sync run with the venv's engine. Refused, nothing written, when the
    brain's root is not a git repo, config.json is not tracked there or it has changes not committed."""
    pin = p["pin"]
    file = Path(pin["file"])
    root = file.parent
    hand = f"move {file.name} engine.pin {pin['from']} -> {pin['to']} and commit it, then brain sync"
    branch, why = _pin_branch(root, file.name, runner)
    if why:
        return 1, [f"pin      {why}: nothing written; {hand}"]
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
    out = [f"pin      {file.name} engine.pin {pin['from']} -> {pin['to']}, committed on {branch} in {root} "
           f"({msg!r}; not pushed)"]
    code, said = _sync(p["python"], root, runner)
    return code, [*out, *said]


def _pin_branch(root: Path, name: str, runner) -> tuple[str, str]:
    """(the brain's branch, '') when the pin may be written and committed there; else ('', why not)."""
    if _git(root, "rev-parse", "--show-toplevel", runner=runner).returncode != 0:
        return "", f"{root} is not a git repo (or git cannot run)"
    branch = (_git(root, "rev-parse", "--abbrev-ref", "HEAD", runner=runner).stdout or "").strip()
    if not branch or branch == "HEAD":
        return "", f"{root} is on no branch (a detached HEAD)"
    if _git(root, "ls-files", "--error-unmatch", "--", name, runner=runner).returncode != 0:
        return "", f"{name} is not tracked in {root}"
    dirty = _git(root, "status", "--porcelain", "--", name, runner=runner)
    if dirty.returncode != 0 or (dirty.stdout or "").strip():
        return "", f"{name} has changes not committed (commit them, then brain update again)"
    return branch, ""


def _sync(python: str, root: Path, runner) -> tuple[int, list[str]]:
    """brain sync in the brain, run by the venv's engine (the one the pin now names)."""
    try:
        sync = runner([python, "-m", "brain", "--root", str(root), "sync"], capture_output=True, text=True,
                      stdin=subprocess.DEVNULL, cwd=str(root))
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, [f"sync     brain sync failed: {exc}; run it in {root}"]
    said = ((sync.stdout or "") + (sync.stderr or "")).strip().splitlines()
    if sync.returncode != 0:
        return 1, [f"sync     brain sync failed with exit code {sync.returncode}: run it in {root}", *said[-20:]]
    return 0, [f"synced   brain sync in {root}"]


def _refresh_stamps(p: dict, runner) -> list[str]:
    """The plan's stamps step: brain check --public --refresh run by the venv's engine, the one just installed (a
    stamp is valid only under the engine that made it), in the brain's root: its lines; [] when the plan has no such
    step; a failure is said, never an install failure (the push guard names the fix)."""
    if not p.get("stamps"):
        return []
    python, root = p["python"], Path(p["stamps"])
    hand = f"run brain check --public --history in each public checkout (brain check --public --refresh, in {root})"
    try:
        done = runner([python, "-m", "brain", "--root", str(root), "check", "--public", "--refresh"],
                      capture_output=True, text=True, stdin=subprocess.DEVNULL, cwd=str(root),
                      timeout=STAMPS_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        return [f"stamps   not refreshed ({exc}): {hand}"]
    said = [ln for ln in ((done.stdout or "") + (done.stderr or "")).splitlines() if ln.strip()]
    if done.returncode == 2 and not any(ln.startswith(("stamps", "same", "stamped", "skip", "refused", "failed"))
                                        for ln in said):
        return [f"stamps   the installed brain has no check --public --refresh: {hand}"]
    return said or [f"stamps   brain check --public --refresh said nothing (exit {done.returncode})"]


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
    out = [f"installed brain {p['tag']} into {Path(p['python']).parent.parent}", *_moved_since_verified(p)]
    if out[-1].startswith("refused"):
        return 1, out
    if p.get("launcher"):
        src, dst = Path(p["launcher"][0]), Path(p["launcher"][1])
        try:
            out.append(f"{set_launcher(src, dst)} {dst}" if src.is_file() else f"launcher {src} missing: rerun the "
                       "installer")
        except OSError as exc:
            return 1, [*out, f"launcher {dst}: {exc} (rerun installer/install.ps1 -Apply)"]
    out += _refresh_stamps(p, runner)
    code = 0
    if pin_writes(p):
        code, moved = move_pin(p, runner)
        out += moved
    elif p.get("pin"):
        pin = p["pin"]
        out.append(f"to do    move {Path(pin['file']).name} engine.pin {pin['from']} -> {pin['to']} by a reviewed PR")
    out.append(f"restart  brain tui and the sessions, to run {p['tag']}")
    return code, out


def _moved_since_verified(p: dict) -> list[str]:
    """When the tag was verified: a commit pip recorded for brain or research-graph (both by the tag, from the
    engine's repo) other than the verified one means the tag moved between the check and the install: said (a
    warning, then a refusal line under engine.verify_tags), [] otherwise."""
    sig = p.get("signature") or {}
    if sig.get("status") != tagsig.VERIFIED:
        return []
    sites = _site_packages(Path(p["python"]))
    moved = [(d, got) for d in ("brain", "research_graph")
             for got in [tagsig.installed_commit(sites, d, p["repo"])] if got and got != sig["commit"]]
    if not moved:
        return []
    said = [f"warning  {d} was installed from commit {got[:12]}, not {sig['commit'][:12]} which the signed "
            f"{p['tag']} names: the tag moved during the install" for d, got in moved]
    said.append("repair   the venv holds code the signature does not cover: check the repo's tags (git ls-remote), "
                f"then {p['python']} -m pip install --force-reinstall \"{p['spec']}\"")
    if p.get("verify_tags"):
        said.append("refused  the launcher and the pin are left as they were")
    return said


def main(root: Path | None, *, check_only: bool, yes: bool, as_json: bool, refused: str = "",
         ask=None, out=print) -> int:
    """brain update: the plan (always), then on the owner's yes (--yes, or y in a terminal) its install."""
    p = plan(check(root, refresh=True), root)
    if as_json:
        out(json.dumps(p, ensure_ascii=False, indent=1, sort_keys=True))
    else:
        out("\n".join(lines(p)))
    if check_only:
        return 0
    if not runs(p):
        return 1 if p.get("blocked", "").startswith("refused:") else 0   # a tag refused is a failure, not "nothing"
    if refused:
        out(f"brain update: {refused}; run it yourself in a terminal")
        return 1
    if not yes and not _owner_says_yes(p, ask, out):
        return 0
    code, done = apply(p)
    out("\n".join(done))
    return code


def _owner_says_yes(p: dict, ask, out) -> bool:
    """The owner's y at the prompt (a terminal), naming what runs: the install, the pin's move, or both."""
    moving = f"move engine.pin to {p['pin']['to']}, commit it and run brain sync" if pin_writes(p) else ""
    if p.get("spec"):
        question = f"Install brain {p['tag']}" + (f", {moving}" if moving else "")
        does = "installs it" + (" and moves the pin" if moving else "")
    else:
        question, does = moving[0].upper() + moving[1:], "moves the pin"
    if ask is None and not sys.stdin.isatty():
        out(f"brain update --yes {does}")
        return False
    if (ask or input)(f"{question} now? [y/N] ").strip().lower() in ("y", "yes", "o", "oui"):
        return True
    out("nothing installed" if p.get("spec") else "nothing moved")
    return False
