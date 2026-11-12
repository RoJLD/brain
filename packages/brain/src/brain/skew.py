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

from . import config, paths, update

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


def of(root: Path | None) -> tuple[str | None, list[str], list[Engine]]:
    """(the pin, what differs, the running engines) for the brain acted on from ``root``."""
    pin = update.engine(root)[1]
    engines = running() if pin else []
    return pin, problems(pin, engines) if pin else [], engines


def how(root: Path | None, pin: str, engines: list[Engine]) -> str:
    """The way out, in one line: an engine at another release (after brain update, say) moves the pin, a dev engine
    gives way to the pinned one."""
    brain = next((e for e in engines if e.name == "brain"), None)
    v = update.version_of(brain.version) if brain else None
    cfg = config.load(root).file or config.FILE
    if v and v != update.version_of(pin) and not brain.folder:
        return (f"to keep this engine, set engine.pin to v{brain.version} in {cfg} and commit it (by a reviewed PR "
                f"where the brain's main is protected); to keep {pin}, run that engine (its venv); or --force")
    return f"run the {pin} engine (brain update, or its venv), or --force"


def check_lines(root: Path | None) -> list[str]:
    """brain check's warnings ([] when the engine is the pinned one and not below engine.min)."""
    low = below_min(root)
    pin, diff, engines = of(root)
    return ([f"warning: {low}"] if low else []) + [f"warning: the running engine is not config.json engine.pin {pin}: {'; '.join(diff)} (brain sync and "
            f"brain render refuse to write until it is: {how(root, pin, engines)})"] if diff else []


def below_min(root: Path | None = None) -> str:
    """Why this engine is below config.json ``engine.min`` ('' when it is not, or no minimum is set): under it the
    machine reads but never writes the shared formats (the memory sync, the DDRs; spec one-brain 4.10)."""
    try:
        eng = config.load(root).data.get("engine")
    except Exception:  # noqa: BLE001 - an unreadable config.json is brain check's to report
        return ""
    want = update.version_of(eng.get("min")) if isinstance(eng, dict) and eng.get("min") else None
    if want is None:
        return ""
    from . import __version__

    have = update.version_of(__version__)
    if have is None or have >= want:
        return ""
    return (f"this engine is {__version__}, below config.json engine.min {eng['min']}: it reads, it writes no shared "
            "format (brain update, then the installer)")


WRITES = "the rendered hooks and the generated links"


def refuse(root: Path | None, what: str, force: bool, writes: str = WRITES) -> int:
    """1 (after saying why and the way out) when ``what`` (sync, refresh, render, views --write, or a command that
    writes one committed view, through :func:`refuse_view`: ``writes`` names it) would write with an engine other
    than the pin; 0 when it is the pin, or with ``force`` (said too). Committed views are written by the pinned engine
    only (COMPAT-1, N10)."""
    pin, diff, engines = of(root)
    if not diff:
        return 0
    head = f"brain {what}: the running engine is not config.json engine.pin {pin}: {'; '.join(diff)}"
    if force:
        print(f"warning: {head} (--force: written anyway)", file=sys.stderr)
        return 0
    print(f"{head}. It would rewrite {writes} with another engine.\n"
          f"brain {what}: {how(root, pin, engines)}", file=sys.stderr)
    return 1


def refuse_view(root: Path | None, what: str, force: bool, writes: str) -> int:
    """:func:`refuse` for a command that writes one committed view (brain audit --write, coverage --write, features
    render --write, decision view --write, modules --write), under ``config.json`` ``views.strict`` only (the owner's
    opt-in, brain.views.strict); 0 otherwise: those commands write with any engine, as before."""
    from . import views
    return refuse(root, what, force, writes) if views.strict(root) else 0
