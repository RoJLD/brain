"""The memory sync's keys (brain.memory): which project folder a note belongs to, which keys may be exported, which
notes a SessionEnd watches. Standard library only on the hook's path: the registry is read only by
:func:`registered_keys`, in the sync.

A key is Claude Code's folder name for a project (:func:`path_key`). ``BRAIN_MEMORY_MAP`` renames a local key to the
repo's (``local-key=repo-key;...``) or leaves a folder out (``local-key=``).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from . import paths

CONFLICT_RX = re.compile(r"\.conflict-[A-Za-z0-9_-]+\.md$")


def key_map() -> dict[str, str]:
    """BRAIN_MEMORY_MAP, 'local-key=repo-key;...': local project folder -> repo key ('' leaves the folder out)."""
    out = {}
    for part in re.split(r"[;\n]", os.environ.get("BRAIN_MEMORY_MAP", "")):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def local_notes() -> dict[str, Path]:
    """'key/name.md' -> local file, for every note of every project's memory folder (MEMORY.md included, conflict
    copies left out)."""
    root = paths.projects_dir()
    if not root.is_dir():
        return {}
    aliases = key_map()
    out = {}
    for mem in sorted(root.glob("*/memory")):
        key = aliases.get(mem.parent.name, mem.parent.name)
        if not key:
            continue
        for f in sorted(mem.glob("*.md")):
            if f.is_file() and not CONFLICT_RX.search(f.name):
                out[f"{key}/{f.name}"] = f
    return out


def local_dir(key: str) -> Path | None:
    """This machine's memory folder for the repo key ``key``, when its project folder exists (import never creates
    a project folder: on a machine with another layout it would be noise)."""
    aliases = key_map()
    local_key = next((k for k, v in aliases.items() if v == key), key)
    if aliases.get(local_key, local_key) != key:
        return None
    proj = paths.projects_dir() / local_key
    return proj / "memory" if proj.is_dir() else None


def path_key(path: str | Path) -> str:
    """Claude Code's folder name for a project at ``path``: every character but a letter or a digit becomes '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def registered_keys() -> set[str]:
    """The keys of the folders of the projects the personal brain registers (each one's root and repos), lower case;
    none when there is no personal brain or its registry does not load."""
    root = paths.personal_root()
    if not root:
        return set()
    try:
        import yaml

        from . import projects
    except ImportError:   # no PyYAML: only main's keys and the map are recognized
        return set()
    out = set()
    try:
        loaded = projects.load(root)
    except (OSError, ValueError, yaml.YAMLError):   # the registry unreadable: only main's keys and the map
        return set()
    for p in loaded.values():
        out.add(path_key(p.root).lower())
        try:
            out.update(path_key(r.path).lower() for r in projects.repos_of(p))
        except ValueError:   # a bad repos: entry (RepoError): the root alone
            pass
    return out


def recognized_keys(keys: set[str], on_main: set[str], registered: set[str] | None = None) -> set[str]:
    """The keys among ``keys`` the sync may export: a key already on ``main`` (reviewed before), one of
    ``BRAIN_MEMORY_MAP``'s repo keys, or the folder of a registered project or a folder inside it (a worktree of it).
    Another key is not exported: before adoption a machine would export every folder it ever opened."""
    registered = registered_keys() if registered is None else registered
    mapped = {v for v in key_map().values() if v}
    out = set()
    for k in keys:
        low = k.lower()
        if k in on_main or k in mapped or any(low == r or low.startswith(r + "-") for r in registered):
            out.add(k)
    return out


def snapshot(notes: dict[str, Path]) -> dict[str, list[int]]:
    out = {}
    for k, f in notes.items():
        try:
            st = f.stat()
        except OSError:
            continue
        out[k] = [st.st_mtime_ns, st.st_size]
    return out


def watched(notes: dict[str, Path], state: dict) -> dict[str, Path]:
    """The notes whose change starts a run: those of the keys the last run recognized (``state['keys']``); every note
    before a first run. A key left out (a read-only project's, a folder no project claims) starts none."""
    keys = state.get("keys")
    if not isinstance(keys, list):
        return notes
    keep = set(keys)
    return {k: f for k, f in notes.items() if k.split("/", 1)[0] in keep}
