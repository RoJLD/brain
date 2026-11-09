"""Conflict markers (wi-brain-guard-conflict-markers): the lines git writes into a file it could not merge.

A marker is a line that starts with ``<<<<<<< ``, ``||||||| `` (diff3) or ``>>>>>>> ``, or a bare ``=======``. Two
places look for them: the commit guard (brain.guards, check markers) in the added lines of what a commit records, and
``brain check`` in a store's files, its journals, its decision logs and its records, which every brain command loads
(a YAML file with a marker breaks them all, and the generated views of a stale merge pass the graph check). Two shapes
pass: a Markdown or reStructuredText setext heading (``=======`` under a line of text, in a file with no other
marker; .md, .markdown, .mdx, .qmd, .Rmd, .rst, and .txt when the text is no longer than the underline, reST's rule)
and a file under a test fixtures folder (``fixtures``, ``fixture``, ``testdata``), where a marker is the data a test reads.
"""

from __future__ import annotations

import re
from pathlib import Path

MARKER = re.compile(r"^(?:<{7}|\|{7}|>{7}) |^={7}\r?$")
SIDE = re.compile(r"^(?:<{7}|\|{7}|>{7}) ")   # the markers no text shares: a file with one has no ======= heading
# A ======= under a line of text is a heading there: Markdown (Quarto's and R Markdown's too) and reStructuredText,
# whose sources are often .txt (Sphinx, CHANGES.txt).
SETEXT = (".md", ".markdown", ".mdx", ".qmd", ".rmd", ".rst", ".txt")
FIXTURES = {"fixtures", "fixture", "testdata"}   # a folder whose files are a test's data
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
    found, sided, previous = [], set(), None
    for i, line in enumerate(lines, 1):
        line = line.rstrip("\n")
        if MARKER.match(line):
            found.append((path, i, line.startswith("=") and heading(line, previous, path)))
            sided |= {path} if SIDE.match(line) else set()
        previous = line
    return _kept(found, sided)


ESCAPES = {"t": "\t", "n": "\n", "r": "\r", "a": "\a", "b": "\b", "f": "\f", "v": "\v"}


def _unquote(text: str) -> str:
    """A path git C-quoted (core.quotePath: "caf\\303\\251 notes.md", its \\" and \\\\), without its escapes."""
    out, i = bytearray(), 0
    while i < len(text):
        if text[i] == "\\" and re.match(r"[0-7]{3}", text[i + 1:i + 4]):
            out.append(int(text[i + 1:i + 4], 8) & 0xFF)
            i += 4
        elif text[i] == "\\" and i + 1 < len(text):
            out += ESCAPES.get(text[i + 1], text[i + 1]).encode()
            i += 2
        else:
            out += text[i].encode()
            i += 1
    return out.decode("utf-8", "replace")


def diff_path(header: str) -> str:
    """The path of a unified diff's ``+++ `` line: without the TAB git adds after a path with a space (for GNU
    patch), unquoted when git C-quoted it, without its b/ prefix."""
    path = header[4:].rstrip("\r\n").rstrip("\t")
    if len(path) > 1 and path.startswith('"') and path.endswith('"'):
        path = _unquote(path[1:-1])
    return path[2:] if path.startswith("b/") else path


def scan_diff(diff: str) -> list[str]:
    """``path:line`` for each marker an added line of a unified diff brings (one line of context or more, so the line
    above a ``=======`` is known; a binary file shows no lines)."""
    found, sided, path, line, previous = [], set(), "", 0, None
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            path = diff_path(raw)
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
