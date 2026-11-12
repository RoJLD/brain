"""Secret patterns. A line of text that matches one is dropped before it reaches a ledger or a record.

The list errs on the side of dropping: losing a line of a commit subject is cheap, a key in git history is not.
Only string values are scanned; keys and numbers are kept. Passwords have no shape of their own, so they are found by
the word before them (password, passwd, passphrase, pwd, mdp, mot de passe): a quoted value right after it, an
unquoted one after ``:``, ``=`` or ``|`` that holds a digit or a symbol, and, in ``clean_text`` and ``scan_lines``,
the rows of a Markdown table under a password column.

Hardened before the first machine snapshot (wi-brain-secretscan-hardening, spec-brain-one-brain §10):

- **a whole PEM block**: every line from a ``-----BEGIN ... PRIVATE KEY-----`` line to its ``-----END ...`` line (to
  the text's end when it has none) matches ``private-key``, so :func:`clean_text` drops the key's body, not only its
  first line;
- **the fleet's token formats**: ntfy (``tk_``), Tailscale (``tskey-``), GitLab (``glpat-``), PyPI (``pypi-``) and npm
  (``npm_``);
- **a whole unit** (:func:`unit_hits`, :func:`clean_unit`): a note, a rule file or a snapshot's unit is refused whole
  on a match, never sent with its matching lines dropped;
- **no waiver where the owner's own text lives**: ``gitleaks:allow`` is ignored under ``machines/`` and ``memory/``
  (:data:`STRICT`), the folders committed in clear under the git-private waiver: a line there that matches is refused
  whatever it carries.
"""

from __future__ import annotations

import re

DROPPED = "[dropped: matches a secret pattern]"

_PW = r"(?<![A-Za-z])(?:pass(?:word|wd|phrase)|mot[ _-]?de[ _-]?passe|mdp|pwd)"
_SEP = r"(?:[\s*_]*[:=]|[\s*_]+\|)"  # a table cell's | needs a space or ** before it: pwd|private is a regex
_NOT_A_VALUE = r"(?![<$%{\[(*/.~\\]|[A-Za-z]:[\\/])"  # a placeholder, a variable, a path
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (name, re.compile(rx))
    for name, rx in [
        ("anthropic-key", r"sk-ant-[A-Za-z0-9_\-]{16,}"),
        ("openai-key", r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{20,}"),
        ("github-token", r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})"),
        ("aws-access-key", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
        ("google-api-key", r"\bAIza[0-9A-Za-z_\-]{35}\b"),
        ("slack-token", r"\bxox[abposr]-[A-Za-z0-9\-]{10,}"),
        ("huggingface-token", r"\bhf_[A-Za-z0-9]{30,}\b"),
        ("stripe-key", r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{16,}"),
        ("private-key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        ("age-secret-key", r"\bAGE-SECRET-KEY-1[0-9A-Z]{58}\b"),   # an age identity (brain.vault)
        ("ntfy-token", r"\btk_[A-Za-z0-9]{29}\b"),
        ("tailscale-key", r"\btskey-[a-z]+-[A-Za-z0-9]{4,}-[A-Za-z0-9]{8,}"),
        ("gitlab-token", r"\bglpat-[A-Za-z0-9_\-]{20,}"),
        ("pypi-token", r"\bpypi-AgEIcHlwaS5vcmc[A-Za-z0-9_\-]{40,}"),
        ("npm-token", r"\bnpm_[A-Za-z0-9]{36}\b"),
        ("jwt", r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
        ("bearer", r"(?i)\bbearer\s+[A-Za-z0-9._~+/\-]{20,}"),
        ("url-credentials", r"[a-z][a-z0-9+.\-]*://[^/\s:@]+:[^/\s@]+@"),
        ("telegram-bot-token", r"\b\d{8,10}:[A-Za-z0-9_\-]{35}\b"),
        (
            "assignment",
            r"(?i)\b[\w.\-]*(?:api[_\-]?key|secret|token|passw(?:or)?d|pwd|private[_\-]?key|access[_\-]?key)[\w.\-]*"
            r"\s*[:=]\s*['\"]?[A-Za-z0-9_\-+/=.]{16,}",
        ),
        ("password-quoted", rf"(?i){_PW}\w*(?:{_SEP}|\s+is|\s+est)?[\s*_]*([`'\"]){_NOT_A_VALUE}[^\s`'\"]{{6,}}\1"),
        ("password-field", rf"(?i){_PW}\w*{_SEP}[\s*_`'\"]*{_NOT_A_VALUE}(?=[^\s|`'\"]*[0-9!@#$%^&*+=?~])"
                           r"[^\s|`'\"]{6,}"),
    ]
]
_PW_HEADER = re.compile(rf"(?i){_PW}(?![A-Za-z])")
_PEM_BEGIN = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
_PEM_END = re.compile(r"-----END [A-Z0-9 ]*PRIVATE KEY-----")
STRICT = ("machines/", "memory/")   # the folders where gitleaks:allow waives nothing
DROPPED_UNIT = "[dropped: the unit matches a secret pattern]"
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$")
_EMPTY_CELL = re.compile(r"(?i)^(?:|-+|—|n/?a|none|\(none\)|\*+|<[^>]*>|\$\{?\w+\}?|\.\.\.|…)$")


# What a commit or a public repo refuses (brain.guards, brain.public): an assignment counts only when its value is
# quoted or ends the line, so ``token_env: BRAIN_TOKEN,`` (a variable's name) passes.
_WORD = r"[\w.\-]*(?:api[_\-]?key|secret|token|passw(?:or)?d|pwd|private[_\-]?key|access[_\-]?key)[\w.\-]*"
_VALUE = r"[A-Za-z0-9_\-+/=.]{16,}"
ASSIGNMENT = re.compile(rf"(?i)\b{_WORD}['\"]?\s*[:=]\s*(?:(['\"]){_VALUE}\1|{_VALUE}\s*$)")
ALLOW_MARK = "gitleaks:allow"


def find(text: str) -> list[str]:
    """Names of the patterns that match ``text``."""
    return [name for name, rx in PATTERNS if rx.search(text)]


def strict(path: str) -> bool:
    """Whether ``path`` (relative to its repo) is under a folder of :data:`STRICT`, where ``gitleaks:allow`` waives
    nothing."""
    p = (path or "").replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.startswith(STRICT)


def find_in_line(line: str, path: str = "") -> list[str]:
    """Names of the patterns a line of a file matches, :data:`ASSIGNMENT` instead of the looser assignment pattern;
    none when the line carries ``gitleaks:allow``, unless ``path`` is under a :data:`STRICT` folder."""
    if ALLOW_MARK in line and not strict(path):
        return []
    names = [n for n in find(line) if n != "assignment"]
    return names + (["assignment"] if ASSIGNMENT.search(line) else [])


def _cells(line: str) -> list[str] | None:
    s = line.strip()
    return [c.strip() for c in s.strip("|").split("|")] if s.startswith("|") else None


def _pem_body(lines: list[str], hits: list[list[str]]) -> None:
    """``private-key`` on each line of a PEM block after its BEGIN line, its END line included (to the end of
    ``lines`` when it has none)."""
    inside = False
    for i, line in enumerate(lines):
        begin = _PEM_BEGIN.search(line)
        if begin:
            inside = not _PEM_END.search(line[begin.end():])
        elif inside:
            if "private-key" not in hits[i]:
                hits[i].append("private-key")
            inside = not _PEM_END.search(line)


def _hits(lines: list[str]) -> list[list[str]]:
    """The pattern names of each line, the body of a PEM block included, plus ``password-table`` for a Markdown table
    row whose cell under a password column holds a value."""
    hits = [find(line) for line in lines]
    _pem_body(lines, hits)
    columns: list[int] = []
    for i, line in enumerate(lines):
        cells = _cells(line)
        if cells is None:
            columns = []
        elif _TABLE_RULE.match(line):
            continue
        elif i + 1 < len(lines) and _TABLE_RULE.match(lines[i + 1]):  # a header row
            columns = [j for j, c in enumerate(cells) if _PW_HEADER.search(c)]
        elif any(j < len(cells) and not _EMPTY_CELL.match(cells[j].strip("`'\"* ")) for j in columns):
            hits[i].append("password-table")
    return hits


def clean_text(text: str) -> tuple[str, int]:
    """``text`` with every matching line replaced by DROPPED, and the number of lines dropped."""
    if not find(text) and not _PW_HEADER.search(text):   # a PEM block starts with a line find() matches
        return text, 0
    out, dropped = [], 0
    lines = text.split("\n")
    for line, names in zip(lines, _hits(lines)):
        if names:
            out.append(DROPPED)
            dropped += 1
        else:
            out.append(line)
    return "\n".join(out), dropped


def clean(obj):
    """A copy of ``obj`` (dicts, lists, strings) with matching lines dropped from every string, and the count."""
    if isinstance(obj, str):
        return clean_text(obj)
    if isinstance(obj, dict):
        out, n = {}, 0
        for k, v in obj.items():
            out[k], d = clean(v)
            n += d
        return out, n
    if isinstance(obj, list):
        out, n = [], 0
        for v in obj:
            c, d = clean(v)
            out.append(c)
            n += d
        return out, n
    return obj, 0


def unit_hits(text: str) -> list[tuple[int, str]]:
    """(line number, pattern name) of every match in a unit (a note, a rule file, a snapshot's unit), the PEM blocks
    whole; a unit is refused whole on any (``gitleaks:allow`` waives nothing in it)."""
    return scan_lines(text)


def clean_unit(text: str) -> tuple[str, int]:
    """``text`` unchanged when no line matches, else :data:`DROPPED_UNIT` alone, and the number of matching lines: a
    unit never leaves with only its matching lines dropped (the lines around a key can name what it opens)."""
    hits = unit_hits(text)
    return (DROPPED_UNIT if hits else text), len({line for line, _ in hits})


def scan_lines(text: str) -> list[tuple[int, str]]:
    """(line number, pattern name) for every matching line of ``text``."""
    hits = []
    for i, names in enumerate(_hits(text.splitlines()), 1):
        for name in names:
            hits.append((i, name))
    return hits


# The patterns with a shape of their own (a key's prefix, a token's form): what a scan of machine files looks for
# (brain.spool, before a store is sealed to leave the machine). The password and assignment heuristics read a word
# before a value, and a key of the engine's own JSON files can look like one: a false refusal. The engine's text lines
# were cleaned with the whole list when they were written (:func:`clean`).
LOOSE = ("assignment", "password-quoted", "password-field")
SHAPED = [(name, rx) for name, rx in PATTERNS if name not in LOOSE]
BINARY_PROBE = 8192   # a NUL byte in a file's first 8 KB: a binary file (sqlite, an archive), not scanned


def scan_file(path, patterns: list[tuple[str, re.Pattern[str]]] | None = None) -> list[tuple[int, str]]:
    """(line number, pattern name) of each match of ``patterns`` (:data:`SHAPED` by default) in a text file, in
    order; [] for a binary one. OSError when it cannot be read."""
    with open(path, "rb") as fh:
        blob = fh.read()
    if b"\0" in blob[:BINARY_PROBE]:
        return []
    text = blob.decode("utf-8", "replace")
    hits = [(text.count("\n", 0, m.start()) + 1, name) for name, rx in (patterns or SHAPED) for m in rx.finditer(text)]
    return sorted(hits)


def strip_url_credentials(url: str) -> str:
    """The URL without its user-info part (the user and password before the @)."""
    return re.sub(r"^([a-z][a-z0-9+.\-]*://)[^/@\s]+@", r"\1", url.strip())
