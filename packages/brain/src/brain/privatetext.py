"""The private-text check (wi-brain-secretscan-hardening, spec-brain-one-brain §10): ``brain check --public
--private-text``, before each tag, compares a public repo's tracked files with the personal brain's own text, its
rules (config.json ``rules``) and its notes (the Markdown files under config.json ``memory``), by windows of 8 words:
a sentence copied from a rule or a note into the engine is refused even when it names no denied term. Zero token.

Words are runs of letters and digits, lowercased, so case, punctuation and line breaks do not hide a copy. A finding
names the file and line where a copied run starts, and the source it comes from (a path relative to the personal
brain); a run of overlapping windows is one finding. A file under ``public.allow`` is not read; neither is a file
over 1 MB or not UTF-8 (the tree scan's limits).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from . import config, paths

WINDOW = 8
WORD = re.compile(r"\w+")


def sources(cfg: config.Config) -> list[Path]:
    """The personal brain's own text: its rules files, then the Markdown notes under its memory folder."""
    out = [f for f in config.rules_files(cfg) if f.is_file()]
    mem = cfg.path("memory")
    out += sorted(mem.rglob("*.md")) if mem.is_dir() else []
    return out


def _words(text: str) -> list[tuple[str, int]]:
    """(word, its line number) for every word of ``text``, lowercased."""
    out, line, pos = [], 1, 0
    for m in WORD.finditer(text):
        line += text.count("\n", pos, m.start())
        pos = m.start()
        out.append((m.group(0).lower(), line))
    return out


def index(cfg: config.Config) -> dict[tuple, str]:
    """{8 words: the source they come from}, over :func:`sources`."""
    idx: dict[tuple, str] = {}
    for f in sources(cfg):
        try:
            words = [w for w, _ in _words(f.read_text(encoding="utf-8"))]
        except (OSError, UnicodeDecodeError):
            continue
        rel = f.relative_to(cfg.root).as_posix() if f.is_relative_to(cfg.root) else f.name
        for i in range(len(words) - WINDOW + 1):
            idx.setdefault(tuple(words[i:i + WINDOW]), rel)
    return idx


def scan(text: str, idx: dict) -> list[tuple[int, str]]:
    """(line, source) where a run of windows of ``text`` copied from ``idx`` starts, one per run. ``idx`` is
    :func:`index`'s (keyed by the words) or :func:`hashed_index`'s (keyed by :func:`window_key`)."""
    words = _words(text)
    hashed = isinstance(next(iter(idx), None), str)
    out, last = [], -2
    for i in range(len(words) - WINDOW + 1):
        window = tuple(w for w, _ in words[i:i + WINDOW])
        src = idx.get(window_key(window) if hashed else window)
        if src is not None:
            if i != last + 1:
                out.append((words[i][1], src))
            last = i
    return out


def window_key(window: tuple) -> str:
    """A window's key in the hashed index: 16 hex digits of the SHA-1 of its words, never the words themselves."""
    return hashlib.sha1(" ".join(window).encode("utf-8")).hexdigest()[:16]


def hashed_index(cfg: config.Config) -> dict[str, str]:
    """:func:`index` keyed by :func:`window_key`, kept in ``<BRAIN_HOME>/cache/private-text.json`` while each source
    keeps its path, mtime and size (the push guard's advice reads it on each push to a public repo: built once, not
    per push). The cache holds hashes and source paths, never a window's words; a cache that cannot be read or
    written is rebuilt or skipped."""
    files = sources(cfg)
    key = []
    for f in files:
        try:
            st = f.stat()
            key.append([str(f), st.st_mtime_ns, st.st_size])
        except OSError:
            key.append([str(f), None, None])
    cache = paths.brain_home() / "cache" / "private-text.json"
    try:
        kept = json.loads(cache.read_text(encoding="utf-8"))
        if kept.get("v") == 1 and kept.get("key") == key and isinstance(kept.get("windows"), dict):
            return kept["windows"]
    except (OSError, ValueError, AttributeError):
        pass
    idx = {window_key(w): src for w, src in index(cfg).items()}
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_name(f".{cache.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"v": 1, "key": key, "windows": idx}), encoding="utf-8")
        os.replace(tmp, cache)
    except OSError:
        pass
    return idx
