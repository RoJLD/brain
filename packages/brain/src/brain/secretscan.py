"""Secret patterns. A line of text that matches one is dropped before it reaches a ledger or a record.

The list errs on the side of dropping: losing a line of a commit subject is cheap, a key in git history is not.
Only string values are scanned; keys and numbers are kept. Passwords have no shape of their own, so they are found by
the word before them (password, passwd, passphrase, pwd, mdp, mot de passe): a quoted value right after it, an
unquoted one after ``:``, ``=`` or ``|`` that holds a digit or a symbol, and, in ``clean_text`` and ``scan_lines``,
the rows of a Markdown table under a password column.
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


def find_in_line(line: str) -> list[str]:
    """Names of the patterns a line of a file matches, :data:`ASSIGNMENT` instead of the looser assignment pattern;
    none when the line carries ``gitleaks:allow``."""
    if ALLOW_MARK in line:
        return []
    names = [n for n in find(line) if n != "assignment"]
    return names + (["assignment"] if ASSIGNMENT.search(line) else [])


def _cells(line: str) -> list[str] | None:
    s = line.strip()
    return [c.strip() for c in s.strip("|").split("|")] if s.startswith("|") else None


def _hits(lines: list[str]) -> list[list[str]]:
    """The pattern names of each line, plus ``password-table`` for a Markdown table row whose cell under a password
    column holds a value."""
    hits = [find(line) for line in lines]
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
    if not find(text) and not _PW_HEADER.search(text):
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


def scan_lines(text: str) -> list[tuple[int, str]]:
    """(line number, pattern name) for every matching line of ``text``."""
    hits = []
    for i, names in enumerate(_hits(text.splitlines()), 1):
        for name in names:
            hits.append((i, name))
    return hits


def strip_url_credentials(url: str) -> str:
    """The URL without its user-info part (the user and password before the @)."""
    return re.sub(r"^([a-z][a-z0-9+.\-]*://)[^/@\s]+@", r"\1", url.strip())
