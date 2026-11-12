"""The table of moves (wi-brain-moved-paths): config.json ``moved``, ``{old prefix: {to: new prefix, date: YYYY-MM-DD,
note: ...}}``. A path, a folder or a repo that moved is written there once, the day it moves; the checks read it at
zero token instead of a sweep by hand (the post-extraction sweep found about 20 stale lines with four subagents):

- ``brain audit``'s ``doc.dead-ref`` flags a doc line that names an old prefix, with its new one;
- ``brain check`` in a brain's own root flags the same in its instructions, memory notes, skills and scripts
  (:func:`brain_files`), a warning each;
- the memory lint (wi-brain-memory-lint) reads it through :func:`scan_text`.

A prefix matches at the start of a path: not after another path segment (``engine/`` is not in ``tools/engine/x``;
``./engine/`` is), not inside a longer name (``old-notes`` is not in ``old-notes-help`` or ``old-notes.md``), and a
prefix ending in ``/`` only as a folder (``kit/engine/`` is not in ``kit/engine.py``); ``/`` and ``\\`` alike, case
ignored (Windows paths). A bare name (a repo's) matches in prose too, by design, but never in a CodeRef id
(``code:<repo>:...``: brain audit's coderef.dangling owns those). A line that names the new prefix outside the old one
too is history (« moved from X to Y ») and passes.
"""

from __future__ import annotations

import fnmatch
import functools
import re
from dataclasses import dataclass
from pathlib import Path

from . import config

KEY = "moved"
# what brain check reads in a brain's own root (paths lowercased; fnmatch: a * crosses folders): its instructions,
# rules, agents and commands, memory notes, skills, hooks and settings, and scripts
BRAIN_FILES = ("claude.md", "*/claude.md", "agents.md", "*/agents.md", "*/rules/*.md", ".claude/*.md", "*/skills/*",
               "skills/*", "memory/*.md", "*hooks.json", "*settings.json", "*/hooks/*", "*.ps1", "*.sh", "*.cmd", "*.bat")
MAX_FILE = 2_000_000


@dataclass(frozen=True)
class Move:
    old: str
    new: str
    date: str
    note: str = ""

    def says(self) -> str:
        return f"{self.old} moved to {self.new} on {self.date}" + (f" ({self.note})" if self.note else "")


def _norm(text: str) -> str:
    return text.replace("\\", "/").lower()


@functools.lru_cache(maxsize=512)
def _pattern(old: str) -> re.Pattern:
    """Where ``old`` starts a path: not after a word, '.' or '-', nor after a segment and its slash ('./' is fine),
    nor in a CodeRef id; and ends one: a folder prefix (ending in '/') before a slash, else not before a word, '-'
    or '.<word>'."""
    norm = _norm(old)
    body = re.escape(norm.rstrip("/"))
    end = r"(?=/)" if norm.endswith("/") else r"(?![\w-]|\.\w)"
    return re.compile(rf"(?<![\w.-])(?<![\w-]/)(?<!code:){body}{end}")


def table(cfg: config.Config | None = None) -> list[Move]:
    """The moves config.json declares, longest old prefix first; [] without the key (the schema checks its shape:
    a malformed entry is left out here)."""
    cfg = cfg if cfg is not None else config.load()
    raw = cfg.data.get(KEY) if isinstance(cfg.data, dict) else None
    out = []
    for old, v in (raw.items() if isinstance(raw, dict) else []):
        if isinstance(old, str) and old.strip() and isinstance(v, dict) and isinstance(v.get("to"), str):
            out.append(Move(old, v["to"], str(v.get("date", "")), str(v.get("note", ""))))
    return sorted(out, key=lambda m: -len(m.old))


def find_in_line(line: str, moves: list[Move]) -> list[Move]:
    """The moves whose old prefix ``line`` names (a line that names the new one too is history: none)."""
    if not moves:
        return []
    low = _norm(line)
    hits, taken = [], []
    for m in moves:
        if _norm(m.old).rstrip("/") not in low:
            continue   # the cheap test first: most lines name no move
        spans = [h.span() for h in _pattern(m.old).finditer(low)]
        fresh = [sp for sp in spans if not any(a <= sp[0] < b for a, b in taken)]   # not inside a longer prefix
        if not fresh:
            continue
        taken += fresh   # found, or history: a shorter prefix inside it is no finding either
        if any(not any(a <= n.start() < b for a, b in spans) for n in _pattern(m.new).finditer(low)):
            continue   # the new prefix named outside the old one: history
        hits.append(m)
    return hits


def scan_text(path: str, text: str, moves: list[Move]) -> list[tuple[str, int, Move]]:
    """(path, line number, move) of each line of ``text`` that names an old prefix."""
    return [(path, i, m) for i, line in enumerate(text.splitlines(), 1) for m in find_in_line(line, moves)]


def brain_files(root: Path, tracked: list[str]) -> list[str]:
    """The tracked files of a brain's root that brain check reads for old prefixes (:data:`BRAIN_FILES`)."""
    return [t for t in tracked if any(fnmatch.fnmatchcase(t.lower(), g) for g in BRAIN_FILES)]


def scan_root(root: Path, tracked: list[str], moves: list[Move]) -> list[str]:
    """``path:line names OLD: moved to NEW on DATE`` for each line of the brain's files that names an old prefix."""
    out = []
    for rel in brain_files(root, tracked):
        f = root / rel
        try:
            if f.stat().st_size > MAX_FILE:
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        out += [f"{p}:{n} names {m.old}: {m.says()}; write {m.new}" for p, n, m in scan_text(rel, text, moves)]
    return out
