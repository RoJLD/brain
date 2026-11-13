"""The release a wave will be (wi-brain-wave-version-forecast): ``brain wave check`` and ``brain next`` say whether the
next release is a patch or a minor one, and why, from the release preview of the project's engine checkout
(``packages/brain/installer/release_check.py --preview --ref REF --json``), as soon as the first PR that tips it is
merged, so the version and the wave's name are decided before the version PR.

- **Which checkout**: the first repo of the project that holds :data:`SCRIPT`; a project without one has no forecast
  (nothing said).
- **Which commit**: the remote's default branch as git last fetched it (``origin/HEAD``, else ``origin/main``, else
  HEAD), read with git: the checkout's working tree and branch are left as they are, and nothing is fetched (the
  forecast says the commit it read; ``git fetch`` makes it current). The preview that runs is that commit's own
  (its two scripts read with ``git show`` into a temporary folder), never the working tree's copy.
- **Which wave**: the wave whose release is the next patch or the next minor of the last tag; a later wave gets no
  forecast.

A commit already previewed is read from the cache store (``<BRAIN_HOME>/cache/release-forecast.json``, one entry per
checkout, keyed by the commit's sha): ``brain next`` runs the preview once per fetch, not on every call.

Advisory: it never changes an exit code. It runs the script with this interpreter, bounded by :data:`TIMEOUT`; a
script that fails, hangs or prints garbage is said in one line (``forecast unknown: ...``).
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from . import paths

SCRIPT = "packages/brain/installer/release_check.py"
SCRIPTS = ("release_check.py", "changelog.py")   # the preview's files, beside each other (it imports changelog)
TIMEOUT = 60.0
REFS = ("origin/HEAD", "origin/main", "HEAD")


def _git(repo: Path, *args: str, timeout: float = 10.0) -> str:
    try:
        done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def checkout(repos: list[Path]) -> Path | None:
    """The first of ``repos`` that holds the release preview's script."""
    return next((Path(r) for r in repos if (Path(r) / SCRIPT).is_file()), None)


def default_ref(repo: Path) -> str:
    """The remote's default branch as last fetched (``origin/HEAD``'s target), else ``origin/main``, else HEAD."""
    target = _git(repo, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if target:
        return target
    return next((r for r in REFS[1:] if _git(repo, "rev-parse", "--verify", "--quiet", f"{r}^{{commit}}")), "HEAD")


def well_formed(data) -> bool:
    """Whether a preview's JSON holds what :func:`lines` reads (a later engine's copy may rename a key)."""
    if not isinstance(data, dict) or data.get("kind") not in ("patch", "minor"):
        return False
    if not all(isinstance(data.get(k), str) and data.get(k) for k in ("patch", "minor")):
        return False
    reasons, tipped = data.get("reasons"), data.get("tipped_by")
    if not isinstance(reasons, list) or not all(isinstance(r, dict) and isinstance(r.get("path"), str)
                                                and r.get("kind") in ("schema", "upgrade") for r in reasons):
        return False
    return tipped is None or (isinstance(tipped, dict)
                              and all(isinstance(tipped.get(k), str) for k in ("sha", "subject")))


def _cached(repo: Path, key: str) -> dict | None:
    try:
        got = json.loads(CACHE().read_text(encoding="utf-8")).get(str(repo))
    except (OSError, ValueError, AttributeError):
        return None
    return got["data"] if isinstance(got, dict) and got.get("key") == key and well_formed(got.get("data")) else None


def _keep(repo: Path, key: str, data: dict) -> None:
    """The forecast kept for that commit (the cache store's ``release-forecast.json``, one entry per checkout): the
    same commit gives the same forecast, so brain next runs the preview once per fetch."""
    f = CACHE()
    try:
        held = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
        held = held if isinstance(held, dict) else {}
        held[str(repo)] = {"key": key, "data": data}
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(held, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(f)
    except (OSError, ValueError):
        pass   # a cache: the next call runs the preview again


def CACHE() -> Path:   # noqa: N802 - a path read at call time (BRAIN_HOME may move in a test)
    return paths.brain_home() / "cache" / "release-forecast.json"


def forecast(repos: list[Path], ref: str = "", timeout: float = TIMEOUT) -> dict | None:
    """The preview of the project's engine checkout as data (release_check.py's ``--json`` keys, plus ``repo``), or
    {"error": why} when it cannot tell; None when no repo of the project holds the script. A commit already
    previewed is read from the cache (:func:`_keep`)."""
    repo = checkout(repos)
    if repo is None:
        return None
    ref = ref or default_ref(repo)
    if ref.startswith("-"):
        return {"error": f"{ref!r} is no commit", "repo": str(repo), "ref": ref}
    sha = _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    if sha:
        hit = _cached(repo, sha)
        if hit is not None:
            return hit | {"repo": str(repo), "ref": ref}
    with tempfile.TemporaryDirectory(prefix="brain-forecast-") as tmp:
        for name in SCRIPTS:   # the commit's own scripts: the checkout's branch and working tree play no part
            text = _git(repo, "show", f"{ref}:{Path(SCRIPT).parent.as_posix()}/{name}")
            if not text:
                return {"error": f"{ref} has no {name}: not an engine checkout, or a ref git cannot read",
                        "repo": str(repo), "ref": ref}
            (Path(tmp) / name).write_text(text + "\n", encoding="utf-8")
        cmd = [sys.executable, "-I", str(Path(tmp) / Path(SCRIPT).name), "--repo", str(repo), "--preview",
               "--ref", ref, "--json"]
        try:
            done = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            return {"error": f"the release preview took more than {timeout:g} s", "repo": str(repo), "ref": ref}
        except OSError as exc:
            return {"error": f"the release preview cannot run: {exc}", "repo": str(repo), "ref": ref}
    if done.returncode:
        why = (done.stderr.strip().splitlines() or [f"exit {done.returncode}"])[-1]
        if "unrecognized arguments" in why:   # a commit before this command: its preview reads only the working tree
            why = f"the release preview at {ref} predates the forecast (no --ref, --json): it comes with that engine"
        return {"error": why.removeprefix("release-preview: "), "repo": str(repo), "ref": ref}
    try:
        data = json.loads(done.stdout)
    except ValueError:
        data = None
    if not well_formed(data):
        return {"error": "the release preview printed no forecast this engine reads (another engine's shape?)",
                "repo": str(repo), "ref": ref}
    if sha:
        _keep(repo, sha, data)
    return data | {"repo": str(repo), "ref": ref}


def concerns(fc: dict | None, release: str) -> bool:
    """Whether the forecast speaks of the wave planned as ``release``: the next patch or the next minor of its tag
    (an unknown forecast speaks of every wave: it says so once)."""
    if not fc:
        return False
    return "error" in fc or release in (fc.get("patch"), fc.get("minor"))


def lines(fc: dict | None, release: str) -> list[str]:
    """What brain wave check and brain next print about the wave planned as ``release``; [] when the forecast does not
    concern it."""
    if not concerns(fc, release):
        return []
    if "error" in fc:
        return [f"release forecast unknown: {fc['error']}"]
    at = f"release_check --preview of {fc.get('ref') or '?'} at {fc.get('sha') or '?'}"
    if fc["kind"] == "patch":
        if release == fc["patch"]:
            return [f"release forecast: wave {release} ships as the patch {fc['patch']}, as planned ({at})"]
        return [f"release forecast: nothing pending makes a minor yet, the next release is the patch {fc['patch']}; "
                f"wave {release} is planned as the minor ({at})"]
    out = [f"release forecast: wave {release} ships as a minor, {fc['minor']}"
           + (f", not the patch {fc['patch']} it is named for: rename it before the version PR"
              if release == fc["patch"] else ", as planned") + f" ({at})"]
    tipped = fc.get("tipped_by")
    if tipped:
        pr = f" (PR #{tipped['pr']})" if tipped.get("pr") else ""
        out.append(f"  first tipped by {tipped.get('sha', '?')}{pr}: {tipped.get('subject', '')}")
    for r in fc.get("reasons") or []:
        schema = r.get("kind") == "schema"
        what = r.get("path", "?") if schema else f"{r.get('path', '?')}: {r.get('step', '')}"
        label = "a registered schema moved" if schema else "an Upgrade step beyond the standard ones"
        out.append(f"  {label}: {what}")
    return out
