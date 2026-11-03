"""Append-only edits of a project's markdown logs: ``brain journal add`` (notes/journal.md) and ``brain adr new``
(notes/decisions.md), and the text I/O that keeps a file's line endings, used by every brain edit.

A file keeps its line endings (a CRLF checkout stays CRLF) and only grows: each write checks that the old text, less
its trailing blank lines, is a prefix of the new one. A line that matches a secret pattern is refused.
"""

from __future__ import annotations

import re
import textwrap
from datetime import date
from pathlib import Path

from . import actions, secretscan

WIDTH = 118
_DAY_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2})\b")
_HEADING_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})\s*[—:\-]*\s*(.*?)\s*$")  # research_graph.sync's ADR heading
_LIST_RE = re.compile(r"^(\s*)([-*]|\d+\.)\s+(.*)$")
ADR_SUFFIX_RE = re.compile(r"\s*\((?:ADR|SDR)\)\s*$")


class NotesError(Exception):
    pass


def read(path: Path) -> tuple[str, str]:
    """(the text with LF line ends, the file's newline: CRLF when it has any, else LF)."""
    raw = path.read_bytes().decode("utf-8")
    return raw.replace("\r\n", "\n"), ("\r\n" if "\r\n" in raw else "\n")


def write(path: Path, text: str, nl: str = "\n") -> None:
    path.write_bytes(text.replace("\n", nl).encode("utf-8"))


def _append(path: Path, old: str, new: str, nl: str) -> None:
    if not new.startswith(old.rstrip()):
        raise NotesError(f"{path}: the edit would change existing lines; nothing written")
    hits = secretscan.scan_lines(new[len(old.rstrip()):])
    if hits:
        raise NotesError(f"{path}: line(s) matching a secret pattern ({', '.join(n for _, n in hits)}); nothing "
                         "written")
    write(path, new, nl)


def _group(text: str) -> list[tuple[str | None, str]]:
    """The blocks of a text, as (lead, body): a list line (``- x``, ``1. x``, indented or not) starts a block led by
    its marker; an unmarked line continues the block before it (a hard-wrapped paragraph or bullet), else starts a
    paragraph (lead ''); a blank line ends a block; code, table, quote and heading lines are kept (lead None)."""
    blocks: list[list] = []
    cur: list | None = None
    code = False
    for line in text.split("\n"):
        s = line.rstrip()
        if s.lstrip().startswith("```"):
            code = not code
        if code or s.lstrip().startswith("```") or s.startswith(("|", ">", "#")):
            blocks.append([None, s])
            cur = None
        elif not s.strip():
            cur = None
        elif _LIST_RE.match(s):
            m = _LIST_RE.match(s)
            cur = [f"{m.group(1)}{m.group(2)} ", m.group(3)]
            blocks.append(cur)
        elif cur is not None:
            cur[1] += " " + s.strip()
        else:
            cur = ["", s.strip()]
            blocks.append(cur)
    return [(b[0], b[1]) for b in blocks]


def _fill(body: str, lead: str, width: int) -> list[str]:
    return textwrap.wrap(body, width, initial_indent=lead, subsequent_indent=" " * len(lead),
                         break_long_words=False, break_on_hyphens=False) or [lead.rstrip()]


def wrap(lines: list[str], width: int = WIDTH) -> list[str]:
    """Markdown list lines, one or more per item of ``lines``: a paragraph becomes a bullet, bullets and numbered lines
    stay so; each is re-wrapped at ``width`` with its continuation indented under its text."""
    out: list[str] = []
    for text in lines:
        for lead, body in _group(str(text)):
            out += [body] if lead is None else _fill(body, lead or "- ", width)
    return out


# --- journal ---

def last_day(text: str) -> str | None:
    """The date of the last dated entry (``## YYYY-MM-DD — ...``) of a journal."""
    days = [m.group(1) for m in map(_DAY_RE.match, text.splitlines()) if m]
    return days[-1] if days else None


def journal_add(path: Path, lines: list[str], title: str = "", day: str | None = None,
                width: int = WIDTH) -> str:
    """Append to a journal. With a title: a new entry ``## <day> — <title>`` and its lines. Without: the lines go at
    the end of the day's entry, which must be the journal's last. Returns what was done ('entry' or 'lines')."""
    day = day or date.today().isoformat()
    if not path.is_file():
        raise NotesError(f"{path}: no journal here")
    old, nl = read(path)
    body = wrap(lines, width)
    base = old.rstrip() + "\n"
    if title:
        new = base + f"\n## {day} — {' '.join(title.split())}\n" + ("\n" + "\n".join(body) + "\n" if body else "")
        what = "entry"
    else:
        if not body:
            raise NotesError("journal add: nothing to add (give lines, or --title for a new entry)")
        last = last_day(old)
        if last != day:
            raise NotesError(f"{path.name}: the last entry is {last or 'none'}, not {day}: give --title to start "
                             f"the {day} entry")
        new = base + "\n".join(body) + "\n"
        what = "lines"
    _append(path, old, new, nl)
    return what


# --- ADR log ---

def headings(text: str) -> list[tuple[str, str]]:
    """(date, title) of every dated ``##`` heading, as research_graph sync reads them."""
    return [(m.group(1), m.group(2)) for m in map(_HEADING_RE.match, text.splitlines()) if m]


def adr_id(day: str, title: str, existing: list[tuple[str, str]], kind: str = "adr") -> str:
    """The node id research_graph sync gives a heading: ``adr-<date>-<slug>``, ``-1``, ``-2``... on a repeat."""
    base = f"{kind}-{day}-{actions.slug(title) if title else 'entry'}"
    n = sum(1 for d, t in existing if f"{kind}-{d}-{actions.slug(t) if t else 'entry'}" == base)
    return f"{base}-{n}" if n else base


def find_adr(text: str, ref: str, kind: str = "adr") -> tuple[str, str, str]:
    """(date, title, id) of the ADR named by its id or its exact title (the last one when titles repeat)."""
    found: list[tuple[str, str, str]] = []
    seen: list[tuple[str, str]] = []
    for day, title in headings(text):
        nid = adr_id(day, title, seen, kind)
        seen.append((day, title))
        if ref in (nid, title, ADR_SUFFIX_RE.sub("", title)):
            found.append((day, title, nid))
    if not found:
        raise NotesError(f"{ref}: no ADR with this id or title")
    return found[-1]


FIELDS = [("context", "Context"), ("decision", "Decision"), ("why", "Why"), ("revisit", "Revisit if"),
          ("why_not_script", "Why not a script")]
REVERSAL_FIELDS = [("supersedes", "Supersedes"), ("trigger", "Trigger"), ("context", "Context"),
                   ("decision", "New decision"), ("why", "Why"), ("migration", "Migration"),
                   ("revisit", "Revisit if")]
TODO = "TODO"


def _label(old: str, label: str) -> str:
    """French "Décision" when the log mostly writes it so."""
    if label == "Decision" and old.count("**Décision.**") > old.count("**Decision.**"):
        return "Décision"
    return label


def _field(label: str, value: str, width: int) -> list[str]:
    """``**Label.** text``: the value's first paragraph on the label's line, then its lists and paragraphs."""
    blocks = _group(value.strip())
    out = [f"**{label}.**"]
    if blocks and blocks[0][0] == "":
        out = _fill(f"**{label}.** {blocks[0][1]}", "", width)
        blocks = blocks[1:]
    for lead, body in blocks:
        out += [body] if lead is None else ([""] if lead == "" else []) + _fill(body, lead, width)
    return out


def adr_new(path: Path, title: str, fields: dict, day: str | None = None, reverses: str = "",
            kind: str = "adr", width: int = WIDTH) -> dict:
    """Append a dated ADR to a decision log: ``## <day> — <title>`` and its fields (a missing one is written TODO).
    ``reverses`` (an ADR id or title) makes it ``REVERSAL: <original title>`` with its Supersedes, Trigger, New
    decision and Migration fields. Returns {"id", "title", "supersedes", "todo"}."""
    day = day or date.today().isoformat()
    if not path.is_file():
        raise NotesError(f"{path}: no decision log here")
    old, nl = read(path)
    existing = headings(old)
    supersedes = ""
    spec = FIELDS
    fields = {k: v for k, v in fields.items() if v}
    if reverses:
        o_day, o_title, supersedes = find_adr(old, reverses, kind)
        title = title or f"REVERSAL: {ADR_SUFFIX_RE.sub('', o_title)}"
        fields.setdefault("supersedes", f"{o_day} — {o_title} (`{supersedes}`)")
        spec = REVERSAL_FIELDS
        if fields.get("why_not_script"):
            spec = spec + [FIELDS[-1]]
    if not title.strip():
        raise NotesError("adr new: a title is needed")
    title = " ".join(title.split())
    todo = [k for k, _ in spec if k not in fields and k != "why_not_script"]
    parts = []
    for key, label in spec:
        if key == "why_not_script" and key not in fields:
            continue
        parts.append("\n".join(_field(_label(old, label), fields.get(key, TODO), width)))
    new = old.rstrip() + "\n" + f"\n## {day} — {title}\n\n" + "\n\n".join(parts) + "\n"
    _append(path, old, new, nl)
    return {"id": adr_id(day, title, existing, kind), "title": title, "supersedes": supersedes, "todo": todo}
