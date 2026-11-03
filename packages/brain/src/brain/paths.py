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


def package_repo() -> Path | None:
    """The git checkout that holds this package (plugins/<core plugin>/brain -> repo root), when there is one."""
    root = Path(__file__).resolve().parents[3]
    return root if (root / ".git").exists() and (root / "notes" / "graph").is_dir() else None


def installed_checkout() -> Path | None:
    """The clone the brain command is installed from (editable, in <BRAIN_HOME>/venv by install.ps1), read from its
    direct_url.json: how a hook run from the plugin's cached copy finds the Brain's projects.yaml."""
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
    else the checkout that holds this package."""
    env = os.environ.get("BRAIN_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    here = Path(start or os.getcwd()).resolve()
    for d in (here, *here.parents):
        if (d / "notes" / "graph" / "schema.yaml").is_file():
            return d
    pkg = package_repo()
    if pkg:
        return pkg
    raise SystemExit("brain: no notes/graph/schema.yaml above the current folder; pass --root or set BRAIN_ROOT")
