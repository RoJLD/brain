"""The engine's one unified-diff reader (wi-brain-diff-parser; the lesson les-brain-unescaped-format).

Every reader of git's patches goes through :func:`parse`: brain impact's hunks, the commit guards (the secrets, the
conflict markers, the public commit check), the public history scan and the changed-items reader of brain.actions.
Three parsers had the same defect before (brain #35 finding 3, #37 findings 9 and 14): a content line starting with
``-- `` or ``++ `` read as a ``--- ``/``+++ `` header, and a path with a space kept git's trailing TAB.

What the parser holds to:

- **Headers only from the diff's structure.** A hunk's body is read by the counts of its ``@@`` line: while lines of
  the hunk remain, a line is content whatever it starts with (``--- x`` is the deleted line ``-- x``). A file's
  headers (``---``, ``+++``, ``rename from``, ``new file mode``, ``Binary files``...) are read only outside a hunk.
- **Paths as git writes them.** A C-quoted path (``"a/caf\\303\\251"``) is unquoted; an unquoted one ends at its
  first TAB (git's TAB after a path with a space, GNU diff's TAB before a timestamp); the ``a/`` and ``b/`` prefixes
  are stripped; ``/dev/null`` is the empty path.
- **The user's git config neutralised.** :func:`argv` builds a ``git diff|show|log`` call that forces the a/ and b/
  prefixes (``diff.noprefix``, ``diff.mnemonicPrefix``), whole-repo paths (``diff.relative``), no colour, no external
  diff, no textconv and a context line written as a space (``diff.suppressBlankEmpty``; an empty line inside a hunk is
  read as context anyway).
- **Combined diffs** (``diff --cc``, a merge commit's ``git show``): ``@@@`` hunks with one column per parent; a line
  is in the result unless a column says ``-``, added when a column says ``+``.

Line ends: the text is split on ``\\n`` only (``str.splitlines`` would cut a content line at a form feed or a
``\\x1c``); one trailing ``\\r`` is dropped from every line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# git -c ...: before the subcommand. --src/--dst-prefix win over diff.noprefix and diff.mnemonicPrefix.
CONFIG = ("-c", "core.quotepath=off", "-c", "diff.relative=false", "-c", "diff.suppressBlankEmpty=false",
          "-c", "color.diff=false", "-c", "color.ui=false")
OPTIONS = ("--no-color", "--no-ext-diff", "--no-textconv", "--src-prefix=a/", "--dst-prefix=b/")
PREFIXES = ("a/", "b/")

_HUNK = re.compile(r"^(@{2,}) (.*?) \1(?: |$)")
_RANGE = re.compile(r"([-+])(\d+)(?:,(\d+))?")
_ESCAPES = {"a": "\a", "b": "\b", "t": "\t", "n": "\n", "v": "\v", "f": "\f", "r": "\r", '"': '"', "\\": "\\"}
_FILE_STARTS = ("diff --git ", "diff --cc ", "diff --combined ")


def argv(sub: str, *rest: str) -> list[str]:
    """git's arguments (after ``git`` and its ``-C``) for ``sub`` (diff, show, log) with the user's config that
    changes a patch's shape neutralised; ``rest`` follows the forced options (a range, ``-U0``, ``--``, paths)."""
    return [*CONFIG, sub, *OPTIONS, *rest]


@dataclass
class Line:
    kind: str                # '+' added, '-' removed, ' ' context
    old: int | None          # its line number on the (first) old side, None for an added line
    new: int | None          # its line number on the new side, None for a removed line
    text: str


@dataclass
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[Line] = field(default_factory=list)

    def new_span(self) -> tuple[int, int] | None:
        """(first, last) new-side lines it covers; an insertion-free deletion (count 0) touches the line it follows
        (None at the top of the file)."""
        return _span(self.new_start, self.new_count)

    def old_span(self) -> tuple[int, int] | None:
        return _span(self.old_start, self.old_count)


@dataclass
class FileDiff:
    old: str = ""            # '' when added (/dev/null)
    new: str = ""            # '' when deleted
    status: str = "M"        # A, D, M, R (renamed), C (copied)
    binary: bool = False
    combined: bool = False
    mode: str = ""           # the new file mode git names, when it names one
    hunks: list[Hunk] = field(default_factory=list)

    @property
    def path(self) -> str:
        """The new path, the old one for a deletion."""
        return self.new or self.old

    def added(self) -> list[tuple[int, str]]:
        """(new line number, text) of each added line, in order."""
        return [(ln.new or 0, ln.text) for h in self.hunks for ln in h.lines if ln.kind == "+"]


def _span(start: int, count: int) -> tuple[int, int] | None:
    if count:
        return start, start + count - 1
    return (start, start) if start else None


def unquote(text: str) -> str:
    """A C-quoted name's text without its quotes, its escapes read (octal bytes decoded as UTF-8)."""
    out, i = bytearray(), 0
    while i < len(text):
        c = text[i]
        if c == "\\" and re.match(r"[0-7]{3}", text[i + 1:i + 4]):
            out.append(int(text[i + 1:i + 4], 8) & 0xFF)
            i += 4
        elif c == "\\" and i + 1 < len(text):
            out += _ESCAPES.get(text[i + 1], text[i + 1]).encode()
            i += 2
        else:
            out += c.encode()
            i += 1
    return out.decode("utf-8", "replace")


def _quoted(text: str) -> tuple[str, str] | None:
    """(the unquoted name, the rest after it) when ``text`` starts with a C-quoted name, else None."""
    if not text.startswith('"'):
        return None
    i = 1
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == '"':
            return unquote(text[1:i]), text[i + 1:]
        i += 1
    return None


def header_path(value: str, prefixes: tuple[str, ...] = PREFIXES) -> str:
    """The path of a ``---``/``+++`` header's value: unquoted, cut at its first TAB, its prefix stripped; '' for
    /dev/null."""
    q = _quoted(value)
    name = q[0] if q else value.split("\t", 1)[0]
    if name == "/dev/null":
        return ""
    for p in prefixes:
        if p and name.startswith(p):
            return name[len(p):]
    return name


def _plain_name(value: str) -> str:
    """A ``rename from``/``copy to`` value: no prefix, maybe quoted."""
    q = _quoted(value)
    return q[0] if q else value


def _git_line_paths(rest: str, prefixes: tuple[str, ...]) -> tuple[str, str]:
    """(old, new) from ``diff --git``'s two names, the fallback of a file with no ---/+++ (binary, mode only):
    quoted names read as such; unquoted ones split where both halves name the same path."""
    src, dst = (tuple(prefixes) + ("", ""))[:2]
    q = _quoted(rest)
    if q:
        first, tail = q[0], q[1].lstrip(" ")
        q2 = _quoted(tail)
        second = q2[0] if q2 else tail
    else:
        n = (len(rest) - 1) // 2
        mid = rest.rfind(" " + dst) if dst else -1
        if len(rest) % 2 == 1 and rest[n] == " " and rest[:n].removeprefix(src) == rest[n + 1:].removeprefix(dst):
            first, second = rest[:n], rest[n + 1:]
        elif mid > 0:
            first, second = rest[:mid], rest[mid + 1:]
        else:
            return "", ""
    return first.removeprefix(src), second.removeprefix(dst)


def _git_file(raw: str, prefixes: tuple[str, ...]) -> FileDiff:
    """The file a ``diff --git`` (its two names) or ``diff --cc`` (one name) line opens."""
    if raw.startswith("diff --git "):
        f = FileDiff()
        f.old, f.new = _git_line_paths(raw[len("diff --git "):], prefixes)
        return f
    name = _plain_name(raw.split(" ", 2)[2])
    return FileDiff(old=name, new=name, combined=True)


class _Reader:
    def __init__(self, prefixes: tuple[str, ...]):
        self.prefixes = prefixes
        self.files: list[FileDiff] = []
        self.cur: FileDiff | None = None
        self.headers = False          # inside a file's header block (before its first hunk)
        self.left_old: list[int] = []  # lines left on each old side of the open hunk
        self.left_new = 0
        self.old_no = self.new_no = 0
        self.saw_minus = self.saw_plus = False

    def in_hunk(self) -> bool:
        return self.left_new > 0 or any(n > 0 for n in self.left_old)

    def start(self, f: FileDiff) -> None:
        self.files.append(f)
        self.cur, self.headers = f, True
        self.saw_minus = self.saw_plus = False

    def feed(self, raw: str) -> None:
        if self.in_hunk() and self.body(raw):
            return
        if raw.startswith(_FILE_STARTS):
            self.start(_git_file(raw, self.prefixes))
        elif raw.startswith("@") and self.cur is not None and (m := _HUNK.match(raw)):
            self.hunk(m)
        elif self.opens_plain(raw):
            self.start(FileDiff())   # a plain unified diff (no diff --git line, maybe no ---): its header opens a file
            self.header(raw)
        elif self.cur is not None and self.headers:
            self.header(raw)
        # anything else (a commit's header in git log -p, '\ No newline at end of file') is not the patch's

    def opens_plain(self, raw: str) -> bool:
        """A ---/+++ line outside a hunk that is not the next header of the file being read."""
        if raw.startswith("--- "):
            return not (self.headers and not self.saw_minus and not self.saw_plus)
        return raw.startswith("+++ ") and not (self.headers and not self.saw_plus)

    def header(self, raw: str) -> None:
        f = self.cur
        assert f is not None
        if raw.startswith("--- "):
            f.old, self.saw_minus = header_path(raw[4:], self.prefixes[:1]), True
        elif raw.startswith("+++ "):
            f.new, self.saw_plus = header_path(raw[4:], self.prefixes[1:2]), True
        elif raw.startswith(("rename from ", "copy from ")):
            f.old = _plain_name(raw.split(" ", 2)[2])
            f.status = "R" if raw.startswith("rename") else "C"
        elif raw.startswith(("rename to ", "copy to ")):
            f.new = _plain_name(raw.split(" ", 2)[2])
            f.status = "R" if raw.startswith("rename") else "C"
        elif raw.startswith("new file mode "):
            f.status, f.old, f.mode = "A", "", raw.rsplit(" ", 1)[1]
        elif raw.startswith("deleted file mode "):
            f.status, f.new = "D", ""
        elif raw.startswith("new mode "):
            f.mode = raw.rsplit(" ", 1)[1]
        elif raw.startswith(("Binary files ", "GIT binary patch")):
            f.binary = True

    def hunk(self, m: re.Match) -> None:
        f = self.cur
        assert f is not None
        cols = len(m.group(1)) - 1
        ranges = [(s, int(a), int(b) if b else 1) for s, a, b in _RANGE.findall(m.group(2))]
        olds = [(a, b) for s, a, b in ranges if s == "-"]
        news = [(a, b) for s, a, b in ranges if s == "+"]
        if len(olds) != cols or len(news) != 1:
            return   # not a hunk header this reader knows: left out rather than guessed
        h = Hunk(olds[0][0], olds[0][1], news[0][0], news[0][1])
        f.hunks.append(h)
        self.headers = False
        self.left_old = [b for _, b in olds]
        self.left_new = news[0][1]
        self.old_no, self.new_no = olds[0][0], news[0][0]

    def body(self, raw: str) -> bool:
        """Read one line of the open hunk; False when it cannot be one (a truncated hunk: the line is read as a
        header instead)."""
        cols = len(self.left_old)
        if raw.startswith("\\"):
            return True   # '\ No newline at end of file'
        marks = raw[:cols] if raw else " " * cols   # an empty line: a context line whose space was dropped
        if len(marks) < cols:
            marks = marks.ljust(cols)
        if any(c not in " +-" for c in marks):
            self.left_old, self.left_new = [], 0
            return False
        text = raw[cols:]
        assert self.cur is not None   # a hunk is open, so a file is
        h = self.cur.hunks[-1]
        if "-" in marks:
            h.lines.append(Line("-", self.old_no if marks[0] == "-" else None, None, text))
            if marks[0] == "-":
                self.old_no += 1
        else:
            kind = "+" if "+" in marks else " "
            old = None if marks[0] == "+" else self.old_no
            h.lines.append(Line(kind, old, self.new_no, text))
            self.new_no += 1
            self.left_new -= 1
            if marks[0] != "+":
                self.old_no += 1
        gone = "-" in marks   # a removed line is on the parents whose column says '-'; a kept one on those with ' '
        for i, c in enumerate(marks):
            if c == ("-" if gone else " "):
                self.left_old[i] -= 1
        return True

    def done(self) -> list[FileDiff]:
        for f in self.files:
            if f.status in ("M",) and not f.combined:
                f.status = "A" if not f.old and f.new else "D" if f.old and not f.new else \
                    "R" if f.old != f.new else "M"
        return self.files


def parse(text: str, prefixes: tuple[str, ...] = PREFIXES) -> list[FileDiff]:
    """The files of a unified diff (git's, a combined one, or a plain ``diff -u``), in order. ``prefixes``: the
    old and new sides' path prefixes git was asked for (:data:`OPTIONS` forces a/ and b/); ``("", "")`` for a
    patch made without them."""
    r = _Reader(prefixes)
    for raw in text.split("\n"):
        r.feed(raw[:-1] if raw.endswith("\r") else raw)
    return r.done()


def lines(files: list[FileDiff], kinds: str = "+-") -> list[str]:
    """Each line of ``files``' hunks whose kind is in ``kinds``, written back with its mark (``+text``, ``-text``):
    for a reader that matches a pattern on the patch's lines."""
    return [ln.kind + ln.text for f in files for h in f.hunks for ln in h.lines if ln.kind in kinds]


def log_records(text: str, prefixes: tuple[str, ...] = PREFIXES) -> list[tuple[str, list[FileDiff]]]:
    """(the head line, its files) of each commit of a ``git log -p --format=%x00<fields>``: a NUL opens each record,
    so a commit's own fields are never read as the patch."""
    out = []
    for record in text.split("\0")[1:]:
        head, _, patch = record.partition("\n")
        out.append((head.strip(), parse(patch, prefixes)))
    return out


def added_lines(text: str, prefixes: tuple[str, ...] = PREFIXES) -> dict[str, list[tuple[int, str]]]:
    """path -> (new line number, text) of each added line of a diff, deleted files left out."""
    out: dict[str, list[tuple[int, str]]] = {}
    for f in parse(text, prefixes):
        if f.new and (rows := f.added()):
            out.setdefault(f.new, []).extend(rows)
    return out
