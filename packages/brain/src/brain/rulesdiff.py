"""``brain rules diff``: the owner's rules compared across the places they are written, read only, at zero token.

The sources, each one overridable by a flag (the command's tests do):

- **machine**: this machine's ``~/.claude/CLAUDE.md`` (``$CLAUDE_CONFIG_DIR/CLAUDE.md`` when it is set);
- **global**: the brain's global rules, config.json ``rules`` (relative to the brain's root), else the core plugin's
  copy that ``brain lint rules`` reads (:func:`brain.lint.global_rules`);
- **project**: the current project's ``CLAUDE.md`` files (``CLAUDE.md``, ``.claude/CLAUDE.md``, ``CLAUDE.local.md``)
  at ``--project``'s root, else at the repo of the current folder;
- **notes**: the machine's feedback memory notes, the Claude Code notes whose front matter says ``type: feedback``
  (or ``metadata: {type: feedback}``), under ``<projects>/<key>/memory/``, the restricted folders left out.

A unit is a rule of a Markdown file as ``brain lint rules`` cuts it (a bullet with its wrapped continuation lines and
sub-bullets, a numbered list with its lead, a paragraph: :func:`brain.lint.units`), or one whole feedback note. Each
unit is put in classes:

- **identical**: a unit of another file has the same words (normalised text), however short;
- **near**: a unit of another file is close by content words (``brain lint rules``' measure, :func:`brain.lint.
  similarity`: a Jaccard index of 0.5, or a containment of 0.75);
- **one side**: no unit of another file is identical or near to it;
- **contradictory**: two units say a value of the same subject, in the same scope, and the values differ;
- **to check**: a unit touches a subject (its topic patterns) and no value of it could be read (none matched, or
  several did).

**The subject list** is the owner's, a YAML file this engine does not ship: config.json ``rules_diff.subjects``
(relative to the brain's root) or ``--subjects FILE``. Without one, nothing is classified and no contradiction is
computed; the report says so. Its format (``docs`` and the tests hold an invented example)::

    v: 1
    scopes:                        # optional: where a sentence applies; a sentence that names none is "any"
      this-brain: {en: ['in this brain'], fr: ['dans ce brain']}
    subjects:
      - id: git-authority
        kind: guardrail            # guardrail or preference
        title: who commits and merges
        topic: {en: ['\\bcommit', '\\bmerge'], fr: ['\\bcommit', '\\bmerge']}
        values:                    # a closed set; each value's patterns, by language
          ask: {en: [['\\bnever\\b', '\\bcommit']], fr: [['\\bjamais\\b', '\\bcommit']]}
          automerge:
            en: [['\\bmerge\\b', 'yourself']]
            fr: [['\\bmerge', 'toi-meme']]
            not: ['\\b(?:never|not|jamais|ne)\\b']   # a negation: « never merge your PRs yourself » is no claim

A pattern is a regular expression searched in a sentence (lower case, accents dropped from both, so ``toi-même`` and
``toi-meme`` match alike), or a list of them that must all match; a value's ``not`` patterns cancel it in a sentence
they match. A unit is cut into sentences (not after « e.g. », « i.e. » and the like); each sentence that matches
exactly one value of a subject is a claim ``(subject, value, scope)``, deterministic, no model. Its scope is the one
the sentence names, else the one named before it in the unit, else its heading's, else ``any``.

**Restricted notes.** A project whose notes must never be copied (config.json ``rules_diff.restricted``: memory folder
keys, or project folders turned into their key the way Claude Code names the folder; and each ``--restricted-notes``
folder, added to them) is read by one function only, :func:`restricted_feedback_subjects`: it returns each feedback
note's name and the ids of the subjects it touches, nothing of its text; it catches every exception and logs only the
exception's class and the note's name to ``ledger/errors.log``; and it refuses to run in an agent session
(``CLAUDECODE``, ``CLAUDE_CODE_ENTRYPOINT`` or ``BRAIN_AGENT_SESSION`` set: :func:`brain.vault.agent_session`). A
memory folder whose key is a restricted key, or starts with one and a '-' (the project's worktrees), is never read as
ordinary notes, even when ``--notes`` names it; an entry that matches no folder is reported, never dropped silently.

The command writes nothing of its own but that error log line; like every brain command, it also leaves the engine's
own timing event of the run (brain.selftime: the command, its duration and exit code, never a note's text).
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import config, graph, lint, paths

SOURCES = ("machine", "global", "project", "notes")
KINDS = ("guardrail", "preference")
CLASSES = ("identical", "near", "contradictory", "one_side", "to_check")
ANY = "any"
CONFIG_KEY = "rules_diff"
NOT = "not"  # a value's patterns that cancel it (a negation)
_SENTENCE = re.compile(r"(?<=[.;!?])\s+")
# a piece that ends with one of these is not a sentence's end: « never commit, e.g. in this repo »
_ABBREV = re.compile(r"(?:^|[\s(])(?:e\.g|i\.e|cf|vs|n\.b|p|p\. ?ex|ex|resp|approx)\.$")
_MARKUP = re.compile(r"[`*_]+")


class RulesDiffError(Exception):
    """An explicit input that cannot be read (a file named by a flag or config.json, a malformed subject list)."""


class Refused(Exception):
    """The restricted reader asked to run in an agent session: the variable that marks it."""


# --- the subject list ---

@dataclass
class Subject:
    id: str
    kind: str
    title: str
    topic: list
    values: dict  # value -> ([pattern], [not pattern]): a compiled regex, or a tuple of them that must all match


@dataclass
class Subjects:
    file: str
    subjects: list[Subject]
    scopes: dict  # scope -> [pattern]


def _plain(text: str) -> str:
    """A text without its accents (é as e)."""
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def fold(text: str) -> str:
    """A text as the patterns see it: lower case, accents dropped, Markdown emphasis and code marks dropped, spaces
    collapsed."""
    return " ".join(_MARKUP.sub("", _plain(text)).lower().split())


def _regex(p: str):
    """A pattern compiled as the texts are folded: accents dropped, case ignored."""
    return re.compile(_plain(p), re.I)


def _items(raw, where: str) -> list:
    """A value's, a topic's or a scope's patterns as one list: a list, a string, or a mapping of language -> list (a
    value's ``not`` key aside: :func:`_value`)."""
    if isinstance(raw, dict):
        return [p for lang, ps in raw.items() if lang != NOT for p in (ps if isinstance(ps, list) else [ps])]
    if isinstance(raw, (list, str)):
        return raw if isinstance(raw, list) else [raw]
    raise RulesDiffError(f"{where}: patterns are a list or a mapping of language -> list")


def _pattern(p, where: str):
    """One pattern: a regular expression, or a tuple of them that must all match."""
    try:
        if isinstance(p, str) and p:
            return _regex(p)
        if isinstance(p, list) and p and all(isinstance(x, str) and x for x in p):
            return tuple(_regex(x) for x in p)
    except (re.error, OverflowError, RecursionError) as exc:   # a repeat count past the engine's limit, say
        raise RulesDiffError(f"{where}: pattern {p!r}: {exc.__class__.__name__}: {exc}") from None
    raise RulesDiffError(f"{where}: a pattern is a regular expression or a list of them, got {p!r}")


def _compile(raw, where: str) -> list:
    return [_pattern(p, where) for p in _items(raw, where)]


def _value(raw, where: str) -> tuple[list, list]:
    """A value's patterns and its ``not`` patterns: a sentence that matches one of these is not that value (« never
    merge your PRs yourself » is no claim of merging them yourself)."""
    nots = raw.get(NOT) if isinstance(raw, dict) else None
    return _compile(raw, where), (_compile(nots, f"{where}.{NOT}") if nots else [])


def _subject(s, where: str, seen: set) -> Subject:
    if not isinstance(s, dict) or not isinstance(s.get("id"), str) or not s["id"]:
        raise RulesDiffError(f"{where}: a mapping with an id")
    if s["id"] in seen:
        raise RulesDiffError(f"{where}: id {s['id']!r} twice")
    seen.add(s["id"])
    kind = s.get("kind", "guardrail")
    if kind not in KINDS:
        raise RulesDiffError(f"{where}: kind is {' or '.join(KINDS)}, not {kind!r}")
    values = s.get("values")
    if not isinstance(values, dict) or not values:
        raise RulesDiffError(f"{where}: values is a mapping of value -> patterns")
    return Subject(s["id"], kind, str(s.get("title") or ""),
                   _compile(s["topic"], f"{where}.topic") if s.get("topic") else [],
                   {str(v): _value(p, f"{where}.values.{v}") for v, p in values.items()})


def parse_subjects(data, file: str = "") -> Subjects:
    """A subject list read from YAML data (:data:`KINDS`, a closed set of values, each with its patterns)."""
    if not isinstance(data, dict) or not isinstance(data.get("subjects"), list):
        raise RulesDiffError(f"{file or 'subjects'}: a mapping with a list under 'subjects'")
    scopes = data.get("scopes") or {}
    if not isinstance(scopes, dict):
        raise RulesDiffError(f"{file}: scopes is a mapping of scope -> patterns")
    seen: set = set()
    out = [_subject(s, f"{file}: subjects[{i}]", seen) for i, s in enumerate(data["subjects"])]
    return Subjects(file, out, {str(k): _compile(v, f"{file}: scopes.{k}") for k, v in scopes.items()})


def load_subjects(path: Path) -> Subjects:
    try:
        data = graph.load_yaml(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RulesDiffError(f"subjects {path}: not readable ({exc.__class__.__name__})") from None
    except (ValueError, yaml.YAMLError) as exc:  # a YAML error: its class, the file's place
        raise RulesDiffError(f"subjects {path}: not valid YAML ({exc.__class__.__name__})") from None
    return parse_subjects(data, path.as_posix())


def _hit(pattern, text: str) -> bool:
    return all(p.search(text) for p in pattern) if isinstance(pattern, tuple) else bool(pattern.search(text))


def _any(patterns: list, text: str) -> bool:
    return any(_hit(p, text) for p in patterns)


def sentences(text: str) -> list[str]:
    """A unit's sentences, its lines joined first (a wrapped line is not a sentence), bullets and numbers dropped."""
    joined = " ".join(re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", ln) for ln in text.splitlines())
    out: list[str] = []
    for piece in _SENTENCE.split(fold(joined)):
        if out and _ABBREV.search(out[-1]):   # « e.g. », « i.e. »: the sentence goes on
            out[-1] = f"{out[-1]} {piece}"
        elif piece:
            out.append(piece)
    return out


def scope_of(text: str, subjects: Subjects) -> str:
    """The first scope of the list that a text names ('' for none)."""
    folded = fold(text)
    return next((k for k, pats in subjects.scopes.items() if _any(pats, folded)), "")


def classify(text: str, subjects: Subjects, heading: str = "") -> tuple[list[dict], dict[str, str]]:
    """The claims of a text, [{subject, value, scope}] (one per sentence and subject that match exactly one value, a
    value's ``not`` patterns aside), and the subjects it touches with no value read: {subject: why}. A sentence that
    names no scope keeps the scope named before it in the unit, else its heading's, else ``any``."""
    claims: list[dict] = []
    touched: dict[str, str] = {}
    scope = scope_of(heading, subjects) or ANY
    for sent in sentences(text):
        scope = scope_of(sent, subjects) or scope
        for s in subjects.subjects:
            hits = [v for v, (pats, nots) in s.values.items() if _any(pats, sent) and not _any(nots, sent)]
            if len(hits) == 1:
                claim = {"subject": s.id, "value": hits[0], "scope": scope}
                if claim not in claims:
                    claims.append(claim)
            elif hits:
                touched.setdefault(s.id, "several values: " + ", ".join(hits))
            elif _any(s.topic, sent):
                touched.setdefault(s.id, "no value")
    claimed = {c["subject"] for c in claims}
    return claims, {k: v for k, v in touched.items() if k not in claimed}


# --- the units ---

@dataclass
class Unit:
    source: str  # machine, global, project, notes
    file: str  # as shown: ~/.claude/CLAUDE.md, the brain-relative rules file, CLAUDE.md, <key>/<note>.md
    line: int
    text: str
    words: frozenset = field(default_factory=frozenset)
    claims: list = field(default_factory=list)
    touched: dict = field(default_factory=dict)
    section: str = ""  # its nearest heading: a scope it names applies to the unit

    @property
    def side(self) -> tuple[str, str]:
        return self.source, self.file

    @property
    def ref(self) -> str:
        return f"{self.source}:{self.file}:{self.line}"

    def excerpt(self, n: int = 90) -> str:
        text = " ".join(" ".join(re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", ln) for ln in self.text.splitlines())
                        .split())
        return text if len(text) <= n else text[: n - 1] + "…"

    def as_dict(self, cls: str = "") -> dict:
        first = self.claims[0] if self.claims else {}
        out = {"source": self.source, "file": self.file, "line": self.line, "subject": first.get("subject"),
               "value": first.get("value"), "scope": first.get("scope"), "claims": self.claims,
               "excerpt": self.excerpt(200)}
        return {"class": cls, **out} if cls else out


def _read(path: Path) -> str:
    """A text file, a UTF-8 BOM dropped (Windows PowerShell 5.1 writes one), its line ends as LF."""
    return path.read_text(encoding="utf-8-sig", errors="replace").replace("\r", "")


def _without_front_matter(text: str) -> str:
    """A rules file's YAML front matter blanked, its lines kept (the units' line numbers stay the file's)."""
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---", 3)
    if end < 0:
        return text
    close = text.find("\n", end + 4)
    head = text if close < 0 else text[:close]
    return "\n" * head.count("\n") + text[len(head):]


def markdown_units(text: str, source: str, file: str) -> list[Unit]:
    """The rule units of a Markdown text (:func:`brain.lint.units`), headings and a YAML front matter left out."""
    return [Unit(source, file, u.line, u.text, u.words, section=u.section)
            for u in lint.units(_without_front_matter(text), source, file)]


def front_matter(text: str) -> tuple[dict, str, int]:
    """(front matter, body, the body's first line) of a note; ({}, text, 1) without one. A malformed front matter
    raises (the restricted reader catches it; a plain note is skipped)."""
    if not text.startswith("---"):
        return {}, text, 1
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text, 1
    data = graph.load_yaml(text[3:end]) or {}
    rest = text[end + 4:]
    rest = rest[rest.find("\n") + 1:] if "\n" in rest else ""
    body = rest.lstrip("\n")   # the body's first line: after the closing ---, past the blank lines
    line = text[: end + 4].count("\n") + 2 + rest[: len(rest) - len(body)].count("\n")
    return (data if isinstance(data, dict) else {}), body, line


def is_feedback(meta: dict) -> bool:
    meta_meta = meta.get("metadata")
    kind = meta.get("type") or (meta_meta.get("type") if isinstance(meta_meta, dict) else None)
    return str(kind or "").strip().lower() == "feedback"


def note_unit(path: Path, key: str) -> Unit | None:
    """One feedback note as one unit (its body; its description when the body is empty), None for another note."""
    try:
        meta, body, line = front_matter(_read(path))
    except (OSError, ValueError, yaml.YAMLError):  # unreadable, or a malformed front matter: not a note to class
        return None
    if not is_feedback(meta):
        return None
    text = body.strip() or str(meta.get("description") or "").strip()
    if not text:
        return None
    return Unit("notes", f"{key}/{path.name}", line, text, lint.words(text))


def memory_key(entry: str) -> str:
    """A restricted entry as a memory folder key: a key as is, a path turned into one the way Claude Code names the
    folder (every character but letters and digits as '-')."""
    if "/" in entry or "\\" in entry or entry.startswith("~"):
        return re.sub(r"[^A-Za-z0-9]", "-", str(Path(entry).expanduser().resolve()))
    return entry


def folder_key(folder: Path) -> str:
    """A memory folder's key: the name of the project folder that holds it (``<key>/memory``), else its own name."""
    return folder.parent.name if folder.name == "memory" else folder.name


def is_restricted(folder: Path, keys: set[str], locked: list[Path]) -> bool:
    """A memory folder of a restricted project: one of ``locked``, or its key is a restricted key, or starts with one
    and a '-' (the project's worktrees: Claude Code names their folder after the worktree's path, the main checkout's
    first). Case is ignored. It fails closed: another project whose key starts so is left out too."""
    if _same(folder) in {_same(p) for p in locked}:
        return True
    key = folder_key(folder).casefold()
    return any(key == k or key.startswith(k + "-") for k in keys)


def memory_folders(keys: set[str], locked: list[Path]) -> list[Path]:
    """Every project's memory folder on this machine, ``<projects>/*/memory``, the restricted ones left out."""
    return [m for m in _all_memory_folders() if not is_restricted(m, keys, locked)]


def _same(p: Path) -> str:
    try:
        return os.path.normcase(str(p.resolve()))
    except OSError:
        return os.path.normcase(str(p))


def notes_units(folders: list[Path]) -> list[Unit]:
    out = []
    for folder in folders:
        key = folder_key(folder)
        for f in sorted(folder.glob("*.md")):
            if f.name == "MEMORY.md" or not f.is_file():
                continue
            u = note_unit(f, key)
            if u:
                out.append(u)
    return out


# --- the restricted reader ---

def _log_restricted(exc: BaseException, name: str) -> None:
    """The exception's class and the note's name in ledger/errors.log, never its message (it may quote the note)."""
    from .capture import _log_line  # it swallows its own OSError: a failure to log never shows the note

    _log_line("rules-diff", f"restricted note {name}: {type(exc).__name__}")


def restricted_feedback_subjects(folders: list[Path], subjects: Subjects | None) -> list[dict]:
    """[{name, subjects}] of the feedback notes of restricted memory folders: each note's file name and the ids of the
    subjects it touches (claimed or not), nothing else of it. Every exception is caught and logged by its class and
    the note's name. Refused (:class:`Refused`) in an agent session."""
    from .vault import agent_session

    var = agent_session()
    if var:
        raise Refused(var)
    out: list[dict] = []
    for folder in folders:
        try:
            files = sorted(f for f in folder.glob("*.md") if f.name != "MEMORY.md" and f.is_file())
        except Exception as exc:
            _log_restricted(exc, "(folder)")
            continue
        for f in files:
            name = f.stem
            try:
                meta, body, _ = front_matter(_read(f))
                if not is_feedback(meta):
                    continue
                ids: set[str] = set()
                if subjects is not None:
                    claims, touched = classify(body.strip() or str(meta.get("description") or ""), subjects)
                    ids = {c["subject"] for c in claims} | set(touched)
                out.append({"name": name, "subjects": sorted(ids)})
            except Exception as exc:
                _log_restricted(exc, name)
    return out


# --- the sources ---

@dataclass
class Source:
    source: str
    file: str  # as shown
    path: Path
    explicit: bool  # named by a flag or config.json: unreadable is an error, not a skip


def _brain_roots(cfg: config.Config) -> list[Path]:
    roots = [cfg.root] if cfg.file else []
    roots += [r for r in (paths.personal_root(), paths.package_repo()) if r]
    return roots or [cfg.root]


def _shown(path: Path, root: Path) -> str:
    """A path relative to ``root``, or whole when it is outside it (an absolute config.json rules entry)."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def global_sources(cfg: config.Config) -> list[Source]:
    """config.json rules (each one, relative to the brain's root), else the core plugin's copy brain lint rules
    reads, at the first of the brain's roots that holds it."""
    named = config.rules_files(cfg)
    if named:
        return [Source("global", _shown(p, cfg.root), p, True) for p in named]
    rel = lint.global_rules(cfg)
    for root in _brain_roots(cfg):
        if (root / rel).is_file():
            return [Source("global", rel, root / rel, False)]
    return []


def project_root(project, cwd: Path) -> Path:
    """--project's root, else the repo of the current folder (the nearest folder above with .git), else it."""
    if project is not None:
        return project.root
    here = cwd.resolve()
    return next((d for d in (here, *here.parents) if (d / ".git").exists()), here)


def subjects_path(cfg: config.Config) -> Path | None:
    """config.json rules_diff.subjects, relative to the brain's root."""
    block = cfg.data.get(CONFIG_KEY) if cfg.file else None
    rel = block.get("subjects") if isinstance(block, dict) else None
    return cfg.root / rel if isinstance(rel, str) and rel else None


@dataclass
class Restriction:
    keys: set[str]  # restricted memory keys, case folded
    folders: list[Path]  # the restricted memory folders found (each key's, its worktrees', each --restricted-notes)
    unmatched: list[str]  # config.json entries no memory folder of this machine matches (reported, never dropped)


def restriction(cfg: config.Config, extra: list[Path]) -> Restriction:
    """config.json rules_diff.restricted and every --restricted-notes folder, together: their keys, the memory folders
    of this machine they match (:func:`is_restricted`: a key's worktrees too), and the entries none matches."""
    entries = _restricted_entries(cfg)
    keys = {memory_key(e).casefold() for e in entries} | {folder_key(d).casefold() for d in extra}
    found = [m for m in _all_memory_folders() if is_restricted(m, keys, [])]
    unmatched = [e for e in entries if not any(is_restricted(m, {memory_key(e).casefold()}, []) for m in found)]
    given = {_same(d) for d in extra}
    return Restriction(keys, list(extra) + [m for m in found if _same(m) not in given], unmatched)


def _restricted_entries(cfg: config.Config) -> list[str]:
    block = cfg.data.get(CONFIG_KEY) if cfg.file else None
    entries = block.get("restricted") if isinstance(block, dict) else None
    return [e for e in entries if isinstance(e, str) and e] if isinstance(entries, list) else []


def _all_memory_folders() -> list[Path]:
    root = paths.projects_dir()
    return [m for m in sorted(root.glob("*/memory")) if m.is_dir()] if root.is_dir() else []


def _explicit(path: Path, what: str) -> Path:
    if not path.is_file():
        raise RulesDiffError(f"{what} {path}: not found")
    return path


def _explicit_dir(path: Path, what: str) -> Path:
    if not path.is_dir():
        raise RulesDiffError(f"{what} {path}: not a folder")
    return path


def _sources(cfg: config.Config, project_dir: Path, machine: Path | None, global_rules: list[Path] | None,
             project_rules: list[Path] | None) -> list[Source]:
    """The rule files: each flag's (checked here), else the default places."""
    srcs = [Source("machine", machine.as_posix(), _explicit(machine, "--machine-rules"), True) if machine is not None
            else Source("machine", "~/.claude/CLAUDE.md", lint.claude_dir() / "CLAUDE.md", False)]
    srcs += ([Source("global", p.as_posix(), _explicit(p, "--global"), True) for p in global_rules] if global_rules
             else global_sources(cfg))
    srcs += ([Source("project", p.as_posix(), _explicit(p, "--project-rules"), True) for p in project_rules]
             if project_rules else [Source("project", rel, project_dir / rel, False) for rel in lint.CLAUDE_FILES])
    return srcs


def _subjects_file(cfg: config.Config, subjects: Path | None) -> Path | None:
    """--subjects, else config.json rules_diff.subjects (named, so it must exist), else None."""
    if subjects is not None:
        return _explicit(subjects, "--subjects")
    found = subjects_path(cfg)
    if found is not None and not found.is_file():
        raise RulesDiffError(f"config.json {CONFIG_KEY}.subjects {found}: not found")
    return found


def _read_sources(srcs: list[Source]) -> tuple[list[Unit], list[dict], list[dict]]:
    """(units, the files read with their unit counts, the default files missing), each file once."""
    units: list[Unit] = []
    shown, skipped, seen = [], [], set()
    for s in srcs:
        if _same(s.path) in seen:
            continue
        seen.add(_same(s.path))
        if not s.path.is_file():
            if s.explicit:
                raise RulesDiffError(f"{s.source} rules {s.file}: not found")
            if s.source != "project" or s.file == "CLAUDE.md":   # the optional CLAUDE.md files go unsaid
                skipped.append({"source": s.source, "file": s.file})
            continue
        try:
            got = markdown_units(_read(s.path), s.source, s.file)
        except OSError as exc:
            raise RulesDiffError(f"{s.source} rules {s.file}: not readable ({exc.__class__.__name__})") from None
        units += got
        shown.append({"source": s.source, "file": s.file, "units": len(got)})
    return units, shown, skipped


def _note_folders(notes: list[Path] | None, lock: Restriction) -> tuple[list[Path], list[Path]]:
    """(the memory folders read as ordinary notes, the --notes folders held back as restricted): a restricted folder
    is never read as ordinary notes, named by --notes or not, in an agent session or not."""
    if not notes:
        return memory_folders(lock.keys, lock.folders), []
    named = [_explicit_dir(d, "--notes") for d in notes]
    return ([d for d in named if not is_restricted(d, lock.keys, lock.folders)],
            [d for d in named if is_restricted(d, lock.keys, lock.folders)])


def build(cfg: config.Config, project_dir: Path, *, machine: Path | None = None, global_rules: list[Path] | None = None,
          project_rules: list[Path] | None = None, notes: list[Path] | None = None, subjects: Path | None = None,
          restricted: list[Path] | None = None) -> dict:
    """The report: each source read (a flag's file or folder, else the default place), the units classed. A file or
    folder named by a flag, or a subject list config.json names, that cannot be read raises RulesDiffError; a default
    place that holds nothing is listed as skipped."""
    srcs = _sources(cfg, project_dir, machine, global_rules, project_rules)
    sub_file = _subjects_file(cfg, subjects)
    subs = load_subjects(sub_file) if sub_file is not None else None
    lock = restriction(cfg, [_explicit_dir(d, "--restricted-notes") for d in restricted or []])
    folders, held = _note_folders(notes, lock)
    units, shown, skipped = _read_sources(srcs)
    skipped += [{"source": "notes", "file": d.as_posix(), "why": "restricted"} for d in held]
    got = notes_units(folders)
    units += got
    shown.append({"source": "notes", "file": f"{len(folders)} memory folder(s), feedback notes", "units": len(got)})
    refused, found = "", []
    try:
        found = restricted_feedback_subjects(lock.folders, subs) if lock.folders else []
    except Refused as exc:
        refused = str(exc)
    return {"sources": shown, "skipped": skipped,
            "subjects": {"file": sub_file.as_posix(), "count": len(subs.subjects)} if subs else None,
            "contradictions": "computed" if subs else (f"not computed: no subject list (config.json {CONFIG_KEY}"
                                                       ".subjects or --subjects FILE)"),
            "classes": diff(units, subs),
            "restricted": {"folders": len(lock.folders), "refused": refused, "notes": found,
                           "unmatched": lock.unmatched}}


# --- the diff ---

def _contradictions(a: Unit, b: Unit, kinds: dict[str, str]) -> list[dict]:
    """The claims of two units that give one subject, in one scope, two values."""
    return [{"subject": ca["subject"], "kind": kinds.get(ca["subject"], ""), "scope": ca["scope"], "a": a,
             "a_value": ca["value"], "b": b, "b_value": cb["value"]}
            for ca in a.claims for cb in b.claims
            if ca["subject"] == cb["subject"] and ca["scope"] == cb["scope"] and ca["value"] != cb["value"]]


def diff(units: list[Unit], subjects: Subjects | None) -> dict:
    """The classes of the units: pairs (identical, near, contradictory) and units alone (one side, to check)."""
    if subjects is not None:
        for u in units:
            u.claims, u.touched = classify(u.text, subjects, u.section)
    kinds = {s.id: s.kind for s in subjects.subjects} if subjects else {}
    identical, near, contra = [], [], []
    matched: set[int] = set()
    for i, a in enumerate(units):
        for j in range(i + 1, len(units)):
            b = units[j]
            if a.side != b.side:   # identical: the same normalised text, however short (« Use bash. » twice)
                found = lint.similarity(a.text, a.words, b.text, b.words, min_exact=1)
                if found:
                    kind, jac, cont = found
                    pair = {"a": a, "b": b, "jaccard": round(jac, 2), "containment": round(cont, 2)}
                    (identical if kind == "exact" else near).append(pair)
                    matched |= {i, j}
            contra += _contradictions(a, b, kinds)
    one_side = [u for k, u in enumerate(units) if k not in matched]
    to_check = [(u, s, why) for u in units for s, why in u.touched.items()]
    return {"identical": identical, "near": sorted(near, key=lambda p: -max(p["jaccard"], p["containment"])),
            "contradictory": contra, "one_side": one_side, "to_check": to_check}


def to_json(report: dict) -> dict:
    """The report as JSON: each unit by source, file, line, class, subject and value (and a short excerpt)."""
    def pair(cls: str, p: dict) -> dict:
        out = {"class": cls, "a": p["a"].as_dict(), "b": p["b"].as_dict()}
        if cls == "contradictory":
            out.update(subject=p["subject"], kind=p["kind"], scope=p["scope"])
            out["a"].update(subject=p["subject"], value=p["a_value"], scope=p["scope"])
            out["b"].update(subject=p["subject"], value=p["b_value"], scope=p["scope"])
        else:
            out.update(jaccard=p["jaccard"], containment=p["containment"])
        return out

    classes = report["classes"]
    return {"sources": report["sources"], "skipped": report["skipped"], "subjects": report["subjects"],
            "contradictions": report["contradictions"],
            "counts": counts(report),
            "identical": [pair("identical", p) for p in classes["identical"]],
            "near": [pair("near", p) for p in classes["near"]],
            "contradictory": [pair("contradictory", p) for p in classes["contradictory"]],
            "one_side": [u.as_dict("one_side") for u in classes["one_side"]],
            "to_check": [{**u.as_dict("to_check"), "subject": s, "value": None, "why": why}
                         for u, s, why in classes["to_check"]],
            "restricted": report["restricted"]}


def counts(report: dict) -> dict:
    return {c: len(report["classes"][c]) for c in CLASSES}


def render(report: dict) -> list[str]:
    """The text report: the sources, then each class with its count, each unit by source and a short excerpt."""
    c = report["classes"]
    n = counts(report)
    units_n = sum(s["units"] for s in report["sources"])
    lines = [f"rules diff: {units_n} unit(s) in {len(report['sources'])} source file(s) (read only)"]
    for s in report["sources"]:
        lines.append(f"  {s['source']:<8} {s['file']}  {s['units']} unit(s)")
    for s in report["skipped"]:
        why = "restricted, not read as notes" if s.get("why") == "restricted" else "not found"
        lines.append(f"  {s['source']:<8} {s['file']}  {why}, skipped")
    lines.append(f"subjects: {report['subjects']['file']} ({report['subjects']['count']} subject(s))"
                 if report["subjects"] else f"subjects: {report['contradictions']}")
    lines.append("")
    lines.append(f"identical ({n['identical']})")
    lines += [f"  {p['a'].ref}  =  {p['b'].ref}  {p['a'].excerpt(70)}" for p in c["identical"]]
    lines.append(f"near ({n['near']})")
    for p in c["near"]:
        lines.append(f"  J {p['jaccard']:.2f} C {p['containment']:.2f}  {p['a'].ref}  ~  {p['b'].ref}")
        lines.append(f"      {p['a'].excerpt(70)}")
        lines.append(f"      {p['b'].excerpt(70)}")
    lines.append(f"contradictory ({n['contradictory']})" if report["subjects"] else "contradictory: not computed")
    for p in c["contradictory"]:
        lines.append(f"  {p['subject']} ({p['kind']}), scope {p['scope']}: {p['a_value']} vs {p['b_value']}")
        lines.append(f"      {p['a_value']}: {p['a'].ref}  {p['a'].excerpt(60)}")
        lines.append(f"      {p['b_value']}: {p['b'].ref}  {p['b'].excerpt(60)}")
    lines.append(f"one side ({n['one_side']})")
    lines += [f"  {u.ref}  {u.excerpt(70)}" for u in c["one_side"]]
    lines.append(f"to check ({n['to_check']})")
    lines += [f"  {s} ({why}): {u.ref}  {u.excerpt(60)}" for u, s, why in c["to_check"]]
    return lines + _render_restricted(report["restricted"])


def _render_restricted(r: dict) -> list[str]:
    """The restricted notes by name and subjects, or why they were not read, and the entries no folder matches."""
    lines = []
    if r["refused"]:
        lines.append(f"restricted notes: not read in an agent session ({r['refused']} is set)")
    elif r["folders"]:
        lines.append(f"restricted notes ({len(r['notes'])}): names and subjects only")
        lines += [f"  {x['name']}: {', '.join(x['subjects']) or '(no subject)'}" for x in r["notes"]]
    return lines + [f"restricted entry {e}: no memory folder of this machine matches it (a key, or a project folder)"
                    for e in r["unmatched"]]
