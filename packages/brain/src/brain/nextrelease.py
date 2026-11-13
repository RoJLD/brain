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

Advisory: it never changes an exit code. It runs the script with this interpreter, bounded by :data:`TIMEOUT`; a
script that fails, hangs or prints garbage is said in one line (``forecast unknown: ...``).
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

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


def forecast(repos: list[Path], ref: str = "", timeout: float = TIMEOUT) -> dict | None:
    """The preview of the project's engine checkout as data (release_check.py's ``--json`` keys, plus ``repo``), or
    {"error": why} when it cannot tell; None when no repo of the project holds the script."""
    repo = checkout(repos)
    if repo is None:
        return None
    ref = ref or default_ref(repo)
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
        return {"error": why.removeprefix("release-preview: "), "repo": str(repo), "ref": ref}
    try:
        data = json.loads(done.stdout)
    except ValueError:
        data = None
    if not isinstance(data, dict) or data.get("kind") not in ("patch", "minor") or not data.get("patch"):
        return {"error": "the release preview printed no forecast (an engine checkout older than this command?)",
                "repo": str(repo), "ref": ref}
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
    at = f"release_check --preview of {fc['ref']} at {fc.get('sha') or '?'}"
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
        out.append(f"  first tipped by {tipped['sha']}{pr}: {tipped['subject']}")
    for r in fc.get("reasons") or []:
        what = r["path"] if r["kind"] == "schema" else f"{r['path']}: {r.get('step', '')}"
        label = "a registered schema moved" if r["kind"] == "schema" else "an Upgrade step beyond the standard ones"
        out.append(f"  {label}: {what}")
    return out
