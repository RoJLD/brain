"""The overlap check (wi-brain-rule-overlap): a rule, a procedure step or a memory note restated in another place
drifts and is injected twice, so ``brain check`` warns when one text of the personal brain overlaps another. Zero
token.

The method is agency-agents' originality check (``scripts/check-agent-originality.sh``, msitarzewski/agency-agents,
MIT), rewritten in Python: each text is cut into **shingles of 8 words** after its **entities are neutralized**, so a
copy that only swaps an id, a date, a number or a project's name still scores as a copy; two texts are compared by
the share of shingles they have in common.

**The texts** are the Markdown files under the roots (config.json ``overlap.roots``, globs relative to the brain's
root; by default the neutral source's rules and procedures, ``<source>/rules/**/*.md`` and
``<source>/procedures/**/*.md``, and the notes under ``<memory>/**/*.md``), less ``overlap.exclude`` (by default
``**/MEMORY.md``, the memory's index of one-line pointers). A file is cut at its ``## `` headings: each section is one
unit (a rule of a rules file, a step of a procedure), the text before the first heading another; a file without a
heading is one unit. Front matter, the heading's own line, HTML comments (a rule's ``<!-- id: ... -->``) and URLs
are not text.

**Neutral words.** Words are runs of letters, digits, ``-`` and ``_``, lowercased; a word that holds a digit (a date,
a PR number, a version), an id of three parts or more (``wi-brain-x``, ``adr-2026-...``) or one of the brain's entity
names of one word (the owner, the projects of its registry, the terms of ``public.deny`` and what brain.denylist
derives; a name of several words would drop common words) is dropped; a compound word is then split at its ``-`` and ``_``, so ``zero-token`` reads as ``zero token``.

**The score** of a pair is its **containment**: the shared shingles over the smaller unit's, so a note restated
inside a longer rule scores high although the rule says more (agency-agents scores Jaccard, the shared shingles over
the union, which a long text dilutes; :func:`pairs` gives both). A unit of fewer than ``overlap.min_shingles``
shingles (default 10, about 17 words) is not scored: a heading's one-liner shares a phrase by chance. A pair at or
above ``overlap.warn`` (a percentage, default 20, agency-agents' level, set on Jaccard there; calibrated in
docs/overlap.md) is a warning of ``brain check``; this slice never makes it an error.
The review packet's procedure lens names the pairs a PR's touched files take part in (brain.review).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import config

WINDOW = 8
WARN = 20.0          # percent of the smaller unit's shingles (overlap.warn)
MIN_SHINGLES = 10    # a smaller unit is not scored (overlap.min_shingles)
EXCLUDE = ("**/MEMORY.md",)
KEY = "overlap"

_FRONT = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n", re.S)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+", re.I)
_HEADING = re.compile(r"^## ", re.M)
_WORD = re.compile(r"[\w-]+")
_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+){2,}$")
_DIGIT = re.compile(r"\d")


@dataclass(frozen=True)
class Unit:
    path: str            # relative to the brain's root, posix
    line: int            # the line its section starts on (1-based)
    title: str           # its heading, "" for a file's text before its first heading
    shingles: frozenset

    @property
    def name(self) -> str:
        return f"{self.path}:{self.line}" + (f" ({self.title})" if self.title else "")


@dataclass(frozen=True)
class Pair:
    a: Unit
    b: Unit
    shared: int

    @property
    def containment(self) -> float:
        return 100.0 * self.shared / min(len(self.a.shingles), len(self.b.shingles))

    @property
    def jaccard(self) -> float:
        return 100.0 * self.shared / len(self.a.shingles | self.b.shingles)


def settings(cfg: config.Config) -> dict:
    """config.json ``overlap`` resolved: roots, exclude, warn, min_shingles (a key of the wrong type: its default)."""
    raw = cfg.data.get(KEY)
    raw = raw if isinstance(raw, dict) else {}
    source = cfg.get("source") or "source"
    memory = cfg.get("memory") or "memory"
    roots = [f"{source}/rules/**/*.md", f"{source}/procedures/**/*.md", f"{memory}/**/*.md"]
    out = {"roots": roots, "exclude": list(EXCLUDE), "warn": WARN, "min_shingles": MIN_SHINGLES}
    for key in ("roots", "exclude"):
        if isinstance(raw.get(key), list) and all(isinstance(g, str) for g in raw[key]):
            out[key] = list(raw[key])
    if isinstance(raw.get("warn"), (int, float)) and not isinstance(raw.get("warn"), bool):
        out["warn"] = float(raw["warn"])
    if isinstance(raw.get("min_shingles"), int) and not isinstance(raw.get("min_shingles"), bool):
        out["min_shingles"] = raw["min_shingles"]
    return out


def entities(cfg: config.Config) -> set[str]:
    """The brain's entity names that are one word, lowercased: the owner, the registry's projects, public.deny and its
    derived terms. A name of several words (a path, ``owner/repo``, the placeholder « the owner ») is left out: its
    pieces are common words. What cannot be read adds nothing."""
    names: set[str] = set()
    try:
        names.add(config.owner(cfg))
        names.update(t for _, t in config.deny_terms(cfg))
    except Exception:   # noqa: BLE001 - a registry that cannot be read leaves the ids and numbers neutral
        pass
    try:
        from . import projects
        names.update(projects.load(cfg.root))
    except Exception:   # noqa: BLE001
        pass
    out = set()
    for n in names:
        ws = _WORD.findall(n.lower()) if isinstance(n, str) else []
        if len(ws) == 1 and ws[0].strip("-_"):
            out.add(ws[0].strip("-_"))
    return out


def words(text: str, neutral: set[str] = frozenset()) -> list[str]:
    """The neutral words of ``text`` (front matter, comments and URLs left out)."""
    text = _URL.sub(" ", _COMMENT.sub(" ", _FRONT.sub("", text.replace("\r\n", "\n"), count=1)))
    out = []
    for w in _WORD.findall(text.lower()):
        w = w.strip("-_")
        if not w or _DIGIT.search(w) or _ID.match(w) or w in neutral:
            continue
        out += [p for p in re.split(r"[-_]+", w) if p and p not in neutral]
    return out


def shingles(ws: list[str], k: int = WINDOW) -> frozenset:
    return frozenset(" ".join(ws[i:i + k]) for i in range(len(ws) - k + 1))


def units(rel: str, text: str, neutral: set[str] = frozenset()) -> list[Unit]:
    """``text``'s units: one per ``## `` section, and the text before the first heading."""
    body = _FRONT.sub(lambda m: "\n" * m.group(0).count("\n"), text.replace("\r\n", "\n"), count=1)
    starts = [0] + [m.start() for m in _HEADING.finditer(body)]
    out = []
    for i, s in enumerate(starts):
        chunk = body[s:starts[i + 1] if i + 1 < len(starts) else len(body)]
        title = chunk.split("\n", 1)[0][3:].strip() if chunk.startswith("## ") else ""
        sh = shingles(words(chunk.partition("\n")[2] if chunk.startswith("## ") else chunk, neutral))   # no heading
        if sh:
            out.append(Unit(rel, body.count("\n", 0, s) + 1, title, sh))
    return out


def _glob(root: Path, pattern: str) -> set[Path]:
    """What ``pattern`` names: relative to ``root``, or from its own anchor when absolute (config.json ``memory`` or
    ``source`` may be an absolute path); a pattern pathlib refuses names nothing."""
    p = Path(pattern)
    base, pat = (Path(p.anchor), p.relative_to(p.anchor).as_posix()) if p.is_absolute() else (root, pattern)
    pat = pat + "/*" if pat == "**" or pat.endswith("/**") else pat   # a folder's '**': every file under it
    try:
        return {f.resolve() for f in base.glob(pat)}
    except (ValueError, OSError):
        return set()


def rel_name(f: Path, root: Path) -> str:
    """``f`` relative to ``root`` in posix form, or its absolute posix path when outside it."""
    try:
        return f.relative_to(root.resolve()).as_posix()
    except ValueError:
        return f.as_posix()


def files(root: Path, opts: dict) -> list[Path]:
    """The Markdown files under ``opts``' roots, less its exclusions (both globs read alike: ``**`` is zero or more
    folders, ``*`` stays within one), each once, sorted."""
    found: set[Path] = set()
    for g in opts["roots"]:
        found |= {f for f in _glob(root, g) if f.is_file() and f.suffix.lower() == ".md"}
    for g in opts["exclude"]:
        found -= _glob(root, g)
    return sorted(found)


def corpus(root: Path, cfg: config.Config | None = None, opts: dict | None = None) -> list[Unit]:
    """Every unit of the brain at ``root`` (a file that cannot be read as UTF-8 is skipped)."""
    cfg = cfg or config.load(root)
    opts = opts or settings(cfg)
    neutral = entities(cfg)
    out: list[Unit] = []
    for f in files(root, opts):
        try:
            text = f.read_text(encoding="utf-8-sig")   # a BOM is no text
        except (OSError, UnicodeDecodeError):
            continue
        out += units(rel_name(f, root), text, neutral)
    return out


def pairs(us: list[Unit], min_shingles: int = MIN_SHINGLES) -> list[Pair]:
    """Every pair of units of at least ``min_shingles`` shingles that shares one, by containment then names."""
    big = [u for u in us if len(u.shingles) >= min_shingles]
    by: dict[str, list[int]] = {}
    for i, u in enumerate(big):
        for s in u.shingles:
            by.setdefault(s, []).append(i)
    shared: dict[tuple[int, int], int] = {}
    for ids in by.values():
        for x in range(len(ids)):
            for y in range(x + 1, len(ids)):
                shared[(ids[x], ids[y])] = shared.get((ids[x], ids[y]), 0) + 1
    out = [Pair(big[i], big[j], n) for (i, j), n in shared.items()]
    return sorted(out, key=lambda p: (-p.containment, p.a.name, p.b.name))


def findings(root: Path, cfg: config.Config | None = None, touched: list[str] | None = None) -> list[Pair]:
    """The pairs at or above overlap.warn; with ``touched`` (paths relative to ``root``), those a touched file
    takes part in."""
    cfg = cfg or config.load(root)
    opts = settings(cfg)
    out = [p for p in pairs(corpus(root, cfg, opts), opts["min_shingles"]) if p.containment >= opts["warn"]]
    if touched is not None:
        keep = {Path(t).as_posix() for t in touched}
        out = [p for p in out if p.a.path in keep or p.b.path in keep]
    return out


def line(p: Pair) -> str:
    return (f"overlap: {p.a.name} and {p.b.name} share {p.containment:.0f} % of the smaller one's 8-word shingles "
            f"(Jaccard {p.jaccard:.0f} %): one text says it, the other points to it")


def review_notes(repo: Path, touched: list[str]) -> list[str]:
    """The review packet's notes for the procedure lens: the pairs a touched file takes part in, read from the
    checkout at ``repo`` (none outside a brain; a review is never stopped by it)."""
    try:
        return [f"{line(p)} (procedure lens)" for p in findings(repo, touched=touched)]
    except Exception as exc:   # noqa: BLE001
        return [f"overlap: not checked ({type(exc).__name__}: {exc})"]


def check_lines(root: Path) -> list[str]:
    """brain check's warnings: one line per pair at or above overlap.warn (never an error in this slice)."""
    try:
        return [line(p) for p in findings(root)]
    except Exception as exc:   # noqa: BLE001 - a warning check never stops brain check
        return [f"overlap: not checked ({type(exc).__name__}: {exc})"]
