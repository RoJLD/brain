"""The running engine against the brain's pin (wi-brain-engine-version-skew): ``config.json`` ``engine.pin`` names
one release of the engine (one tag series for brain and research-graph). A sync or a render run by another engine
rewrites the rendered hooks and the generated links with code the brain does not pin: a dev engine's sync once
re-rendered the plugin's hooks, and a branch still pinned at an older tag had them rewritten by the newer installed
engine; nothing warned.

:func:`running` reads each distribution's version as it runs and where it was installed from (its
``direct_url.json``): a git revision (a release tag or anything else), a local folder (editable or not), or nothing
known (a wheel: the version alone counts). :func:`problems` compares them with the pin: ahead, behind, or the pin's
version from other code (another git revision, or a folder whose checkout is not at the tag, or dirty). ``brain
check`` warns; ``brain sync``, ``brain refresh`` and ``brain render --write`` refuse unless ``--force``
(:func:`refuse`). A brain with no pin, or a pin that is not a release tag (``main``), is not compared.
"""

from __future__ import annotations

import importlib
import importlib.metadata as md
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import paths, update

DISTS = (("brain", "brain"), ("research-graph", "research_graph"))   # (distribution, module)


@dataclass(frozen=True)
class Engine:
    name: str             # the distribution: brain or research-graph
    version: str          # its __version__ as it runs
    revision: str = ""    # the git revision it was installed from (a tag, a branch, a commit), '' when not from git
    commit: str = ""      # the commit that revision was
    folder: str = ""      # the local folder it runs or was installed from, '' when not from one

    def source(self) -> str:
        if self.revision or self.commit:
            return f"git {self.revision or '?'}@{self.commit[:7]}"
        return f"folder {self.folder}" if self.folder else "an unknown source"


def _direct_url(dist: str) -> dict:
    try:
        raw = md.distribution(dist).read_text("direct_url.json")
    except md.PackageNotFoundError:
        return {}
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _installed_file(dist: str, module: str) -> Path | None:
    try:
        return Path(md.distribution(dist).locate_file(f"{module}/__init__.py")).resolve()
    except (md.PackageNotFoundError, OSError, TypeError):
        return None


def engine_of(dist: str, module: str) -> Engine:
    """One distribution as it runs: imported from its installed files, or from a source folder."""
    mod = importlib.import_module(module)
    version = str(getattr(mod, "__version__", ""))
    here = Path(mod.__file__).resolve()
    data = _direct_url(dist)
    vcs, url = data.get("vcs_info") or {}, str(data.get("url") or "")
    if _installed_file(dist, module) != here or (data.get("dir_info") or {}).get("editable"):
        return Engine(dist, version, folder=str(here.parent))   # a source tree: editable, or on the path
    if vcs:
        return Engine(dist, version, str(vcs.get("requested_revision") or ""), str(vcs.get("commit_id") or ""))
    if url.startswith("file:"):
        return Engine(dist, version, folder=str(paths.file_url_path(url)))
    return Engine(dist, version)


def running() -> list[Engine]:
    """brain and research-graph as this process runs them."""
    out = []
    for dist, module in DISTS:
        try:
            out.append(engine_of(dist, module))
        except ImportError:
            continue
    return out


def at_tag(folder: str, tag: str) -> bool:
    """Whether the git checkout holding ``folder`` is at ``tag``, with nothing changed under the folder."""
    def run(*args: str) -> str:
        try:
            p = subprocess.run(["git", "-C", folder, *args], capture_output=True, text=True, timeout=10,
                               stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            return "?"
        return p.stdout.strip() if p.returncode == 0 else "?"

    head, want = run("rev-parse", "HEAD"), run("rev-parse", "--verify", "-q", f"{tag}^{{commit}}")
    return "?" not in (head, want) and head == want and run("status", "--porcelain", "--", ".") == ""


def problems(pin: str | None, engines: list[Engine], tag_check=at_tag) -> list[str]:
    """What differs between the running engines and the pin, one line each ([] when they agree, or when the pin is
    absent or not a release tag)."""
    want = update.version_of(pin) if pin else None
    if want is None:
        return []
    out = []
    for e in engines:
        v = update.version_of(e.version)
        if v is None:
            out.append(f"{e.name} {e.version or '?'} is not a release version (the pin is {pin})")
        elif v != want:
            out.append(f"{e.name} {e.version} is {'ahead of' if v > want else 'behind'} the pin {pin}")
        elif e.revision and e.revision != pin:
            out.append(f"{e.name} {e.version} runs from {e.source()}, not the {pin} release")
        elif e.folder and not tag_check(e.folder, pin):
            out.append(f"{e.name} {e.version} runs from {e.source()}, a dev engine not at {pin}")
    return out


def of(root: Path | None) -> tuple[str | None, list[str]]:
    """(the pin, what differs) for the brain acted on from ``root``."""
    pin = update.engine(root)[1]
    return pin, problems(pin, running()) if pin else []


def check_lines(root: Path | None) -> list[str]:
    """brain check's warning ([] when the engine is the pinned one)."""
    pin, diff = of(root)
    return [f"warning: the running engine is not config.json engine.pin {pin}: {'; '.join(diff)} (brain sync and "
            "brain render refuse to write until it is: run the pinned engine, or move the pin by a reviewed PR)"
            ] if diff else []


def refuse(root: Path | None, what: str, force: bool) -> int:
    """1 (after saying why) when ``what`` (sync, refresh, render) would write with an engine other than the pin;
    0 when it is the pin, or with ``force`` (said too)."""
    pin, diff = of(root)
    if not diff:
        return 0
    head = f"brain {what}: the running engine is not config.json engine.pin {pin}: {'; '.join(diff)}"
    if force:
        print(f"warning: {head} (--force: written anyway)", file=sys.stderr)
        return 0
    print(f"{head}. It would rewrite the rendered hooks and the generated links with another engine: run the "
          "pinned engine (brain update, or its venv), move the pin by a reviewed PR, or --force", file=sys.stderr)
    return 1
