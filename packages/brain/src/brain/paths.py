"""Where things live: the local ledger (outside any repo), the transcripts, the brain repo and its graph store."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def brain_home() -> Path:
    """Machine-local brain data: $BRAIN_HOME, default ~/.brain (kept when a plugin is uninstalled)."""
    env = os.environ.get("BRAIN_HOME")
    return Path(env).expanduser() if env else Path.home() / ".brain"


def ledger_dir() -> Path:
    return brain_home() / "ledger"


def sessions_dir() -> Path:
    return brain_home() / "sessions"


def projects_dir() -> Path:
    """Claude Code's transcripts: $CLAUDE_CONFIG_DIR/projects, default ~/.claude/projects (read only)."""
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(env).expanduser() if env else Path.home() / ".claude") / "projects"


def find_transcript(session_id: str) -> Path | None:
    """The main transcript of a session, ``<projects>/<project>/<session_id>.jsonl``, or None."""
    root = projects_dir()
    if not root.is_dir():
        return None
    hits = sorted(root.glob(f"*/{session_id}.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return hits[0] if hits else None


def relative_transcript(path: str | Path) -> str:
    """A transcript path relative to the projects dir when it is inside it (no home path in records)."""
    p = Path(path)
    try:
        return p.resolve().relative_to(projects_dir().resolve()).as_posix()
    except (ValueError, OSError):
        return p.name


PERSONAL = "personal.json"   # <BRAIN_HOME>/personal.json: {"root": <the personal brain's main checkout>}


def personal_file() -> Path:
    """The machine's pointer to its personal brain, written by the installer (install.ps1 -Personal)."""
    return brain_home() / PERSONAL


def pointer_root() -> Path | None:
    """The root <BRAIN_HOME>/personal.json names (a relative one read from BRAIN_HOME), or None: no file, not JSON,
    no root."""
    try:
        data = json.loads(personal_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    root = data.get("root") if isinstance(data, dict) else None
    if not isinstance(root, str) or not root:
        return None
    p = Path(root).expanduser()
    return p if p.is_absolute() else brain_home() / p


def personal_root() -> Path | None:
    """The personal brain this machine runs: ``$BRAIN_PERSONAL``, else the pointer <BRAIN_HOME>/personal.json, else
    None."""
    env = os.environ.get("BRAIN_PERSONAL")
    return Path(env).expanduser() if env else pointer_root()


def bases(root: str | Path | None = None) -> list[Path]:
    """Where the personal brain's files (config.json, projects.yaml, permissions.yaml) are looked for, in order:
    ``$CLAUDE_BRAIN_DIR``, ``$BRAIN_PERSONAL``, the repo acted on (``root``: a worktree of the personal brain reads its
    own files), the pointer <BRAIN_HOME>/personal.json, then, for an install from a checkout of a personal brain that
    still holds the engine, the checkout that holds this package and the clone installed editable."""
    out: list[Path] = []
    for base in (os.environ.get("CLAUDE_BRAIN_DIR"), os.environ.get("BRAIN_PERSONAL"), root, pointer_root(),
                 package_repo(), installed_checkout()):
        if base and Path(base) not in out:
            out.append(Path(base))
    return out


def package_repo() -> Path | None:
    """The git checkout that holds this package as a plugin's folder (plugins/<core plugin>/brain -> repo root), when
    there is one: a personal brain that still holds the engine. None for an installed package."""
    root = Path(__file__).resolve().parents[3]
    return root if (root / ".git").exists() and (root / "notes" / "graph").is_dir() else None


def installed_checkout() -> Path | None:
    """The clone the brain command is installed from when it is installed editable (in <BRAIN_HOME>/venv), read from
    its direct_url.json: how a hook run from the plugin's cached copy found the Brain's projects.yaml before the
    installer wrote personal.json."""
    from urllib.parse import urlparse  # here, not at the top: urllib.request costs a hook ~50 ms to import
    from urllib.request import url2pathname

    venv = brain_home() / "venv"
    for f in (*venv.glob("Lib/site-packages/brain-*.dist-info/direct_url.json"),
              *venv.glob("lib/python3*/site-packages/brain-*.dist-info/direct_url.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        url = data.get("url") or ""
        if (data.get("dir_info") or {}).get("editable") and url.startswith("file:"):
            return Path(url2pathname(urlparse(url).path))
    return None


def main_checkout(d: str | Path) -> Path | None:
    """The main checkout of the git repo ``d`` is in (itself when it is not a worktree), or None."""
    try:
        common = subprocess.run(["git", "-C", str(d), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return Path(common).parent if common else None


def find_root(start: str | Path | None = None) -> Path:
    """The repo to act on: $BRAIN_ROOT, else the nearest ancestor of ``start`` (cwd) with notes/graph/schema.yaml,
    else the personal brain ($BRAIN_PERSONAL, then <BRAIN_HOME>/personal.json), else the checkout that holds this
    package."""
    env = os.environ.get("BRAIN_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    here = Path(start or os.getcwd()).resolve()
    for d in (here, *here.parents):
        if (d / "notes" / "graph" / "schema.yaml").is_file():
            return d
    for pkg in (personal_root(), package_repo()):
        if pkg and (pkg / "notes" / "graph" / "schema.yaml").is_file():
            return pkg.resolve()
    reg = os.environ.get("BRAIN_PROJECTS")
    if reg and Path(reg).expanduser().is_file():
        return Path(reg).expanduser().resolve().parent  # a registry named outright: its brain's folder (--all)
    raise SystemExit("brain: no notes/graph/schema.yaml above the current folder and no personal brain "
                     "($BRAIN_PERSONAL, <BRAIN_HOME>/personal.json); pass --root, set BRAIN_ROOT, or run brain init")
