"""Conflict markers (wi-brain-guard-conflict-markers): the lines git writes into a file it could not merge.

A marker is a line that starts with ``<<<<<<< ``, ``||||||| `` (diff3) or ``>>>>>>> ``, or a bare ``=======``. Two
places look for them: the commit guard (brain.guards, check markers) in the added lines of what a commit records, and
``brain check`` in a store's files, its journals, its decision logs and its records, which every brain command loads
(a YAML file with a marker breaks them all, and the generated views of a stale merge pass the graph check). Two shapes
pass: a Markdown or reStructuredText setext heading (``=======`` under a line of text, in a file with no other
marker; .md, .markdown, .mdx, .qmd, .Rmd, .rst, and .txt when the text is no longer than the underline, reST's rule)
and a file under a test fixtures folder (``fixtures``, ``fixture``, ``testdata``), where a marker is the data a test reads.
In a Markdown file, a fenced block whose info string holds the tag ``conflict-example`` (a fence opened with
three backticks then ``text conflict-example``) is an example and its markers pass; every other fence is read like the
rest of the file. A diff hunk that starts inside a fence whose opening line it does not show is read as unfenced (fail
closed).
"""

from __future__ import annotations

import re
from pathlib import Path

from . import diffs

MARKER = re.compile(r"^(?:<{7}|\|{7}|>{7}) |^={7}\r?$")
SIDE = re.compile(r"^(?:<{7}|\|{7}|>{7}) ")   # the markers no text shares: a file with one has no ======= heading
# A ======= under a line of text is a heading there: Markdown (Quarto's and R Markdown's too) and reStructuredText,
# whose sources are often .txt (Sphinx, CHANGES.txt).
SETEXT = (".md", ".markdown", ".mdx", ".qmd", ".rmd", ".rst", ".txt")
FIXTURES = {"fixtures", "fixture", "testdata"}   # a folder whose files are a test's data
FENCED = (".md", ".markdown", ".mdx", ".qmd", ".rmd")   # Markdown: fenced code blocks
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
EXAMPLE = "conflict-example"   # the tag of a fence whose conflict markers are an example (the owner, 2026-11-10)
MAX_FILE = 5_000_000


def exempt(path: str) -> bool:
    """Whether ``path`` (a repo path, / or \\) is under a test fixtures folder."""
    return bool(FIXTURES & {p.lower() for p in re.split(r"[\\/]", path)[:-1]})


def heading(line: str, previous: str | None, path: str) -> bool:
    """Whether the bare ``=======`` ``line`` is a setext heading's underline: in a Markdown or reStructuredText file,
    under a line of text (``previous``; None at the file's top) that is no marker. In a .txt file, where data files
    live too (requirements.txt, constraints.txt), only reStructuredText's shape counts: a title no longer than its
    underline, so a bare ======= left under ``numpy==1.26`` is still a marker."""
    if not (path.lower().endswith(SETEXT) and previous is not None and previous.strip()
            and not MARKER.match(previous)):
        return False
    return not path.lower().endswith(".txt") or len(previous.strip()) <= len(line.strip())


def fence_step(line: str, state: tuple | None, path: str) -> tuple[tuple | None, bool]:
    """(the fence state after ``line``, whether ``line`` is inside a fence tagged as an example). ``state`` is None
    outside a fence, else (its character, its length, tagged); only Markdown files have fences here."""
    if not path.lower().endswith(FENCED):
        return None, False
    m = FENCE.match(line)
    if state is None:
        return ((m.group(1)[0], len(m.group(1)), EXAMPLE in m.group(2).split()) if m else None), False
    if m and m.group(1)[0] == state[0] and len(m.group(1)) >= state[1] and not m.group(2).strip():
        return None, False   # the closing fence
    return state, state[2]


def _kept(found: list[tuple[str, int, bool]], sided: set[str]) -> list[str]:
    """``path:line`` of the markers ``found`` (path, line, a heading's shape): a heading's shape counts only in a file
    that holds a <<<<<<<, ||||||| or >>>>>>> marker too (``sided``)."""
    return [f"{p}:{n}" for p, n, shape in found if not shape or p in sided]


def scan_text(path: str, text: str) -> list[str]:
    """``path:line`` for each marker of a file's ``text``."""
    return scan_lines(path, text.splitlines())


def scan_lines(path: str, lines) -> list[str]:
    """``path:line`` for each marker of a file's ``lines`` (any iterable, so a big file is read as it goes)."""
    if exempt(path):
        return []
    found, sided, previous, fence = [], set(), None, None
    for i, line in enumerate(lines, 1):
        line = line.rstrip("\n")
        fence, example = fence_step(line, fence, path)
        if MARKER.match(line) and not example:
            found.append((path, i, line.startswith("=") and heading(line, previous, path)))
            sided |= {path} if SIDE.match(line) else set()
        previous = line
    return _kept(found, sided)


def scan_diff(diff: str) -> list[str]:
    """``path:line`` for each marker an added line of a unified diff brings (one line of context or more, so the line
    above a ``=======`` is known; a binary file shows no lines). The diff is read by brain.diffs, the engine's one
    reader: a hunk's lines by its counts, never a header guessed from a content line."""
    found, sided = [], set()
    for f in diffs.parse(diff):
        path = f.new
        if not path:
            continue
        for h in f.hunks:
            previous, fence = None, None   # a fence opened above the hunk: unknown
            for ln in h.lines:
                if ln.kind == "-":
                    continue
                fence, example = fence_step(ln.text, fence, path)
                if ln.kind == "+" and MARKER.match(ln.text) and not exempt(path) and not example:
                    found.append((path, ln.new, ln.text.startswith("=") and heading(ln.text, previous, path)))
                    sided |= {path} if SIDE.match(ln.text) else set()
                previous = ln.text
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
