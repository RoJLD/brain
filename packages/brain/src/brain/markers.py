"""Conflict markers (wi-brain-guard-conflict-markers): the lines git writes into a file it could not merge.

A marker is a line that starts with ``<<<<<<< ``, ``||||||| `` (diff3) or ``>>>>>>> ``, or a bare ``=======``. Two
places look for them: the commit guard (brain.guards, check markers) in the added lines of what a commit records, and
``brain check`` in a store's files, its journals, its decision logs and its records, which every brain command loads
(a YAML file with a marker breaks them all, and the generated views of a stale merge pass the graph check). Two shapes
pass: a Markdown or reStructuredText setext heading (``=======`` under a line of text, in a file with no other
marker) and a file under a test fixtures folder (``fixtures``, ``fixture``, ``testdata``), where a marker is the data a test reads.
"""

from __future__ import annotations

import re
from pathlib import Path

MARKER = re.compile(r"^(?:<{7}|\|{7}|>{7}) |^={7}\r?$")
SIDE = re.compile(r"^(?:<{7}|\|{7}|>{7}) ")   # the markers no text shares: a file with one has no ======= heading
SETEXT = (".md", ".markdown", ".mdx", ".rst")   # a ======= under a line of text is a heading there
FIXTURES = {"fixtures", "fixture", "testdata"}   # a folder whose files are a test's data
MAX_FILE = 5_000_000


def exempt(path: str) -> bool:
    """Whether ``path`` (a repo path, / or \\) is under a test fixtures folder."""
    return bool(FIXTURES & {p.lower() for p in re.split(r"[\\/]", path)[:-1]})


def heading(line: str, previous: str | None, path: str) -> bool:
    """Whether the bare ``=======`` ``line`` is a setext heading's underline: in a Markdown or reStructuredText file,
    under a line of text (``previous``; None at the file's top) that is no marker."""
    return path.lower().endswith(SETEXT) and previous is not None and bool(previous.strip()) \
        and not MARKER.match(previous)


def _kept(found: list[tuple[str, int, bool]], sided: set[str]) -> list[str]:
    """``path:line`` of the markers ``found`` (path, line, a heading's shape): a heading's shape counts only in a file
    that holds a <<<<<<<, ||||||| or >>>>>>> marker too (``sided``)."""
    return [f"{p}:{n}" for p, n, shape in found if not shape or p in sided]


def scan_text(path: str, text: str) -> list[str]:
    """``path:line`` for each marker of a file's ``text``."""
    if exempt(path):
        return []
    found, sided, previous = [], set(), None
    for i, line in enumerate(text.splitlines(), 1):
        if MARKER.match(line):
            found.append((path, i, line.startswith("=") and heading(line, previous, path)))
            sided |= {path} if SIDE.match(line) else set()
        previous = line
    return _kept(found, sided)


def scan_diff(diff: str) -> list[str]:
    """``path:line`` for each marker an added line of a unified diff brings (one line of context or more, so the line
    above a ``=======`` is known; a binary file shows no lines)."""
    found, sided, path, line, previous = [], set(), "", 0, None
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            path = raw[4:].strip('"')
            path = path[2:] if path.startswith("b/") else path
        elif raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            line, previous = (int(m.group(1)) if m else 0), None
        elif raw.startswith(("+", " ")) and not raw.startswith("+++"):
            text = raw[1:]
            if raw[0] == "+" and MARKER.match(text) and not exempt(path):
                found.append((path, line, text.startswith("=") and heading(text, previous, path)))
                sided |= {path} if SIDE.match(text) else set()
            previous, line = text, line + 1
    return _kept(found, sided)


def scan_files(files) -> list[str]:
    """``path:line`` for each marker of ``files`` (paths; a folder is read whole, a binary or missing file skipped)."""
    hits: list[str] = []
    for f in files:
        f = Path(f)
        for p in sorted(f.rglob("*")) if f.is_dir() else [f]:
            try:
                if not p.is_file() or p.stat().st_size > MAX_FILE:
                    continue
                data = p.read_bytes()
            except OSError:
                continue
            if b"\0" in data[:8000]:
                continue
            hits += scan_text(p.as_posix(), data.decode("utf-8", "replace"))
    return hits
