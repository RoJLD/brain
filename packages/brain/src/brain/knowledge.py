"""The owner's notes home, ``brain notes`` (wi-brain-notes-home; spec-brain-second-brain 3.2, 3.4, 3.7): Markdown with
wikilinks in a private repo of its own, beside the work brain. Obsidian edits it when the owner wants; nothing here
needs it.

Where it is: ``config.json`` ``knowledge.path`` (relative to the config file's folder), else the first ``kind:
knowledge`` entry of the registry (brain.projects.knowledge), else ``--dir``.

**The layout** (:data:`LAYOUT`): the folders say the lifecycle and the class, never the subject. A note's ``scope``
(ids of the scope tree), ``type`` and ``tags`` are properties of its front matter (``notes.schema.json``):

- ``inbox/`` (private): captures and ideas; an agent only ever proposes here, by PR;
- ``notes/``, ``sources/``, ``maps/``, ``templates/``, ``attachments/`` (private): committed in clear to the private
  remote;
- ``daily/``, ``people/`` (confidential): kept on the owner's devices, ignored by git until encrypted git is adopted;
  a person's contact data belongs in ``people/`` alone;
- ``sealed/`` (sealed): never in git, never indexed; ``_brain/`` and ``_maps/``: generated, never committed.

**Commands**, zero token:

- ``brain notes init DIR [--from VAULT] [--apply]``: a plan, then (``--apply``) the layout, the templates, the
  ``.gitignore``, a README and the agents' CLAUDE.md, never overwriting a file; ``--from`` copies an existing vault's
  notes into ``inbox/`` and its other files into ``attachments/`` (a copy, never a move).
- ``brain notes check``: each note's front matter against the schema, duplicate ids, Brain ids the graph does not
  hold, secret patterns, a third party's contact data outside ``people/``, a class under its folder's, and the
  folders git must not track.
- ``brain notes find WORDS``: SQLite FTS5 over the notes (the index under ``$BRAIN_HOME/notes-index``, derived),
  private folders only unless ``--confidential``; ``sealed/`` is never indexed.

The owner's own edits are committed directly (the Obsidian Git plugin, or git); a scheduled commit would be a new
scheduled task, the owner's decision.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import config, paths, schema, secretscan

# folder -> (class, in git, what it holds)
LAYOUT = {
    "inbox": ("private", True, "captures and ideas; agents propose here only, by PR"),
    "notes": ("private", True, "atomic notes, linked"),
    "sources": ("private", True, "one note per source: its reference, a summary of one's own, short quotes"),
    "maps": ("private", True, "maps of content written by hand"),
    "templates": ("private", True, "one template per note type"),
    "attachments": ("private", True, "the files notes cite (PDF, images); a large one stays out of git"),
    "daily": ("confidential", False, "the daily and weekly notes, meetings: on the owner's devices, not in git"),
    "people": ("confidential", False, "one note per person: name, role, link to the owner; nothing more"),
    "sealed": ("sealed", False, "never in git, never indexed"),
    "_brain": ("private", False, "generated: the work graph projected for the editor"),
    "_maps": ("private", False, "generated: the maps per scope and tag"),
}
RANK = {"private": 0, "confidential": 1, "sealed": 2}
TYPES = {   # type -> its folder
    "fleeting": "inbox", "idea": "inbox", "note": "notes", "source": "sources", "daily": "daily",
    "weekly": "daily", "meeting": "daily", "person": "people", "map": "maps",
}
FRONT_FREE = {"inbox"}   # a capture may have no front matter yet
BRAIN_ID = re.compile(r"^(?:wi|adr|spec|feat|ms|ddr|sr|lesson|wave|era)-[a-z0-9][a-z0-9.-]*$")
WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
# a run of digits with spaces, dots or dashes, not inside a word, an id (n-20261116-0930) or a path; a phone number
# once it holds 9 digits or more (contact()), so a date (8) or a year is never one
PHONE = re.compile(r"(?<![\w.:/-])\+?\d[\d .-]{7,}\d(?![\w.-])")


def contact(text: str) -> bool:
    """True when ``text`` holds an e-mail address or a phone number (a third party's contact data)."""
    return bool(EMAIL.search(text)) or any(sum(c.isdigit() for c in m.group()) >= 9 for m in PHONE.finditer(text))
SKIP_IMPORT = {".obsidian", ".git", ".trash"}
GENERATED = ("_brain", "_maps")

_BODIES = {"fleeting": "", "idea": "\n## What\n\n## Why\n\n## For which project\n", "note": "\n",
           "source": "\n## Summary\n\n## Quotes\n", "daily": "\n", "weekly": "\n",
           "meeting": "\n## Who\n\n## Decided\n\n## To do\n", "person": "\n## Role\n\n## Link\n", "map": "\n"}


def template(type_: str) -> str:
    """The template of a note type: its front matter with the placeholders an editor fills, then a body outline."""
    head = ("---\nid: n-{{date:YYYYMMDD}}-{{time:HHmm}}\n" f"type: {type_}\n" 'title: "{{title}}"\n'
            "scope: []\ntags: []\nstatus: seed\nlinks: []\nshare: []\nsummary: \"\"\n"
            "aliases: [n-{{date:YYYYMMDD}}-{{time:HHmm}}]\ncreated: \"{{date:YYYY-MM-DD}}\"\n")
    if type_ == "source":
        head += "kind: \"\"\nurl: \"\"\nretrieved: \"{{date:YYYY-MM-DD}}\"\n"
    return head + "---\n" + _BODIES[type_]


def ignore_lines(classes: dict[str, str] | None = None) -> list[str]:
    """The lines the home's .gitignore must hold: each folder git must never hold, then the editor's own files."""
    return [f"/{name}/" for name in untracked(classes)] + [".obsidian/workspace*.json", ".trash/"]


def gitignore(classes: dict[str, str] | None = None) -> str:
    return "\n".join(["# brain notes init: the folders git must never hold (brain.knowledge.LAYOUT)",
                      *ignore_lines(classes), ""])


README = """# Notes

The owner's notes: Markdown with wikilinks, one idea per note, linked. The folders say the lifecycle and the class;
a note's scope, type and tags are in its front matter (the engine's `notes.schema.json`).

| Folder | Class | In git | What |
|---|---|---|---|
{rows}

`brain notes check` checks the notes, `brain notes find WORDS` searches them (zero token). Any editor works; Obsidian
opens this folder as a vault.
"""

AGENTS = """# Rules for agents in this repo

- Propose only: a new note goes to `inbox/`, by a pull request. Never edit another folder, never commit to main.
- Never read `daily/`, `people/` or `sealed/`: they are the owner's, confidential or sealed.
- Never write a secret, nor a person's contact data outside `people/`.
- `brain notes check` before the pull request.
"""


def _knowledge(cfg: config.Config) -> dict:
    k = cfg.data.get("knowledge")
    return k if isinstance(k, dict) else {}


def home(cfg: config.Config | None = None) -> Path | None:
    """The notes home: config.json knowledge.path, else the registry's first kind: knowledge entry; None when there is
    neither."""
    cfg = cfg or config.load()
    path = _knowledge(cfg).get("path")
    if isinstance(path, str) and path:
        p = Path(os.path.expanduser(path))
        return p if p.is_absolute() else (cfg.file.parent if cfg.file else cfg.root) / p
    from . import projects

    return next(iter(projects.knowledge(cfg.root).values()), None)


def folder_classes(cfg: config.Config | None = None) -> dict[str, str]:
    """{folder: class}: the layout's, raised by config.json knowledge.folders (never lowered); a folder of the owner's
    own named there joins with its class."""
    out = {name: cls for name, (cls, _, _) in LAYOUT.items()}
    folders = _knowledge(cfg or config.load()).get("folders")
    for name, cls in (folders.items() if isinstance(folders, dict) else ()):
        if isinstance(cls, str) and cls in RANK and RANK[cls] > RANK.get(out.get(name, "private"), 0):
            out[str(name)] = cls
    return out


def untracked(classes: dict[str, str] | None = None) -> list[str]:
    """The folders git must never hold: the layout's (confidential, sealed, generated) and any folder whose class
    config.json raised above private."""
    classes = classes if classes is not None else folder_classes()
    return [n for n, c in classes.items() if c != "private" or (n in LAYOUT and not LAYOUT[n][1])]


def strings(value) -> list[str]:
    """A front matter list's strings; [] for anything else (a number, a mapping, a lone string)."""
    return [str(x) for x in value if isinstance(x, (str, int, float)) and not isinstance(x, bool)] \
        if isinstance(value, list) else []


def note_class(folder_cls: str, front: dict | None) -> str:
    """A note's class: its folder's, raised (never lowered) by its own ``class``."""
    raised = (front or {}).get("class")
    return raised if isinstance(raised, str) and RANK.get(raised, -1) > RANK.get(folder_cls, 0) else folder_cls


# --- init ---

@dataclass
class Step:
    action: str   # mkdir, write, copy, append (lines added after the file as it is), keep
    path: str     # relative to the notes home
    what: str = ""
    data: bytes | None = None
    source: Path | None = None

    def line(self) -> str:
        return f"{self.action:<6} {self.path}" + (f"  ({self.what})" if self.what else "")


def plan(target: Path, source: Path | None = None) -> list[Step]:
    """What ``brain notes init`` writes into ``target``: every folder, template and file it is missing; a file that is
    there is kept as it is."""
    steps: list[Step] = []

    def file(rel: str, data: str | bytes, what: str) -> None:
        if (target / rel).exists():
            steps.append(Step("keep", rel, "there already: kept as it is"))
        else:
            steps.append(Step("write", rel, what, data.encode("utf-8") if isinstance(data, str) else data))

    for name, (cls, tracked, what) in LAYOUT.items():
        if not (target / name).is_dir():
            steps.append(Step("mkdir", name + "/", f"{cls}{'' if tracked else ', not in git'}: {what}"))
        if tracked and name != "templates":
            file(f"{name}/.gitkeep", b"", "keeps the empty folder in git")
    for t in TYPES:
        file(f"templates/{t}.md", template(t), f"the template of a {t}")
    ignore = target / ".gitignore"
    if ignore.is_file():   # the owner's lines kept; only the missing ones added, else git would hold daily/
        have = {line.strip() for line in ignore.read_text(encoding="utf-8", errors="replace").splitlines()}
        missing = [line for line in ignore_lines() if line not in have]
        steps.append(Step("append", ".gitignore", "adds " + ", ".join(missing), "\n".join(missing).encode("utf-8"))
                     if missing else Step("keep", ".gitignore", "there already: holds every line"))
    else:
        file(".gitignore", gitignore(), "the folders git must never hold")
    rows = "\n".join(f"| `{n}/` | {c} | {'yes' if t else 'no'} | {w} |" for n, (c, t, w) in LAYOUT.items())
    file("README.md", README.format(rows=rows), "what this repo is")
    file("CLAUDE.md", AGENTS, "the agents' rules: propose in inbox/ only")
    return steps + (_imports(target, source) if source is not None else [])


def refuse_init(target: Path, source: Path | None = None) -> str:
    """Why ``brain notes init`` refuses ``target`` (and ``--from source``); "" when it may plan. A file in the
    target's place, a source that is no folder, and a source and a target inside one another are refused: a copy
    into itself would never end."""
    if target.exists() and not target.is_dir():
        return f"{target} is a file, not a folder"
    files = [n for n in LAYOUT if (target / n).exists() and not (target / n).is_dir()]
    if files:
        return f"{', '.join(files)} in {target}: a file where the layout puts a folder; move it first"
    if (target / ".gitignore").is_dir():
        return f"{target / '.gitignore'} is a folder"
    if source is None:
        return ""
    if not source.is_dir():
        return f"--from {source}: no such folder"
    s, t = source.resolve(), target.resolve()
    if s == t or s in t.parents or t in s.parents:
        return f"--from {source} and {target} are inside one another: give a vault outside the notes home"
    return ""


def project_map(home: Path, name: str, title: str = "", today: str = "") -> Step:
    """What ``brain project add`` plans in the notes home for a new project (wi-brain-project-add-notes): its map,
    ``maps/<name>.md`` (type map, ``scope: [name]``), kept as it is when there. Never a folder of its own: the folders
    say the lifecycle and the class, never the subject (SB-4); a note joins the project by its ``scope``, wherever it
    lives, and the generated map of the scope goes to ``_maps/``."""
    import datetime as _dt

    import yaml

    rel = f"maps/{name}.md"
    if (home / rel).exists():
        return Step("keep", rel, "there already: kept as it is")
    nid = f"n-map-{name}"
    shown = " ".join(str(title).split()) or name   # one line, never empty: a heading and a YAML scalar alike
    front = {"id": nid, "type": "map", "title": shown, "scope": [name], "tags": [], "status": "seed", "links": [],
             "share": [], "summary": "", "aliases": [nid], "created": today or _dt.date.today().isoformat()}
    text = ("---\n" + yaml.safe_dump(front, sort_keys=False, allow_unicode=True, width=1000) + "---\n"
            f"# {shown}\n\nThe notes of `{name}`: a note joins it by `scope: [{name}]` in its front matter, wherever it "
            f"lives. The generated map of the scope is `_maps/{name}.md`.\n\n## Notes\n\n## Sources\n")
    return Step("write", rel, f"the map of {name}: scope {name}", text.encode("utf-8"))


def _imports(target: Path, source: Path) -> list[Step]:
    """A vault's notes into inbox/, its other files into attachments/, their sub-folders kept; a vault's top folder
    that the layout names (daily/, people/, sealed/, notes/...) keeps its place and so its class, never under inbox/
    where git would hold it; its generated folders are left out; never a file that is there."""
    out = []
    for f in sorted(source.rglob("*")):
        rel = f.relative_to(source)
        top = rel.parts[0]
        if not f.is_file() or f.is_symlink() or top in SKIP_IMPORT or top in GENERATED:
            continue
        if len(rel.parts) > 1 and top in folder_classes():
            dest = rel
        else:
            dest = Path("inbox" if f.suffix.lower() == ".md" else "attachments") / rel
        if (target / dest).exists():
            out.append(Step("keep", dest.as_posix(), "there already: kept as it is"))
        else:
            out.append(Step("copy", dest.as_posix(), f"from {rel.as_posix()}", source=f))
    return out


def apply(target: Path, steps: list[Step]) -> list[str]:
    """The plan written, each file through a temporary name then a rename, never over a file that appeared since the
    plan; the lines of what was done."""
    done = []
    for s in steps:
        dest = target / s.path
        if s.action == "mkdir":
            dest.mkdir(parents=True, exist_ok=True)
        elif s.action == "append":   # the file as it is, the missing lines after it, through a temporary name
            old = dest.read_bytes() if dest.is_file() else b""
            sep = b"" if not old or old.endswith(b"\n") else b"\n"
            tmp = dest.with_name(dest.name + ".brain-tmp")
            tmp.write_bytes(old + sep + (s.data or b"") + b"\n")
            os.replace(tmp, dest)
        elif s.action in ("write", "copy"):
            if dest.exists():
                done.append(f"kept   {s.path}: written meanwhile")
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".brain-tmp")
            if s.action == "copy":
                shutil.copy2(s.source, tmp)
            else:
                tmp.write_bytes(s.data or b"")
            os.replace(tmp, dest)
        else:
            continue
        done.append(f"{s.action:<6} {s.path}")
    return done


# --- reading notes ---

def front_matter(text: str) -> tuple[dict | None, str]:
    """(the front matter, the body); None when the note has none, {} when it does not parse to a mapping. A byte
    order mark (Windows Notepad writes one) is skipped; a date an editor writes unquoted (``created: 2026-11-02``)
    reads as its ISO text, as the schema has it."""
    import datetime as _dt

    text = text.removeprefix("﻿")
    if not text.startswith("---"):
        return None, text
    end = re.search(r"^---\s*$", text[3:], re.M)
    if not end:
        return {}, text
    import yaml

    from . import graph

    try:
        data = graph.load_yaml(text[3:3 + end.start()])   # the engine's one YAML reader (wi-brain-yaml-fast-load)
    except (yaml.YAMLError, ValueError):
        return {}, text[3 + end.end():]
    if not isinstance(data, dict):
        return {}, text[3 + end.end():]
    return ({str(k): v.isoformat() if isinstance(v, _dt.date) else v for k, v in data.items()},
            text[3 + end.end():])


def note_files(root: Path, classes: set[str] | None = None) -> list[Path]:
    """The notes (*.md) of the home's folders whose class is in ``classes`` (private and confidential by default);
    sealed/, the templates and the generated folders are left out."""
    allowed = classes or {"private", "confidential"}
    out = []
    for name, cls in folder_classes().items():
        d = root / name
        if name.startswith("_") or name == "templates" or cls not in allowed or not d.is_dir():
            continue
        out += [f for f in sorted(d.rglob("*.md")) if f.is_file() and not f.is_symlink()]
    return out


# --- check ---

@dataclass
class Finding:
    level: str    # error, warn
    path: str
    message: str

    def line(self) -> str:
        return f"{self.level:<6} {self.path}: {self.message}"


def brain_ids(cfg: config.Config | None = None) -> set[str] | None:
    """Every node id of the registered projects' graph stores; None when no registry loads (links unchecked)."""
    from . import projects

    try:
        reg = projects.load((cfg or config.load()).root)
    except (OSError, ValueError):
        return None
    out: set[str] = set()
    for p in reg.values():
        for store in projects.stores_of(p):
            try:
                out |= set(projects.node_ids(store))
            except (OSError, ValueError):
                continue
    return out or None


def _git_tracked(root: Path, folder: str) -> list[str]:
    try:
        p = subprocess.run(["git", "-C", str(root), "ls-files", "--", folder], capture_output=True, text=True,
                           timeout=30, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return []
    return [line for line in p.stdout.splitlines() if line.strip()] if p.returncode == 0 else []


def _unknown_line(u: str) -> str:
    """An unknown field's warning; its name is left out when it looks like a secret (a key that is a token)."""
    u = u.removeprefix("notes: ")
    return "an unknown field whose name looks like a secret (not printed)" if secretscan.scan_lines(u) else u


def _front_findings(rel: str, folder: str, front: dict | None) -> list[Finding]:
    if front is None:
        return [] if folder in FRONT_FREE else [Finding("error", rel, "no front matter (templates/ holds one per type)")]
    if not front:
        return [Finding("error", rel, "its front matter does not parse to a mapping")]
    errors, unknown = schema.validate("notes", front, schema.READ)
    return ([Finding("error", rel, e.removeprefix("notes: ").removeprefix("notes.")) for e in errors]
            + [Finding("warn", rel, _unknown_line(u)) for u in unknown])


def _note_findings(rel: str, folder: str, cls: str, text: str, known: set[str] | None) -> tuple[list[Finding], dict]:
    front, body = front_matter(text)
    out = _front_findings(rel, folder, front)
    front = front or {}
    raised = front.get("class")
    if isinstance(raised, str) and raised in RANK and RANK[raised] < RANK[cls]:
        out.append(Finding("error", rel, f"class {raised} is under its folder's ({cls}): class only raises it"))
    out += [Finding("error", f"{rel}:{line}", f"a secret pattern ({pattern}): never in a note")
            for line, pattern in secretscan.scan_lines(text)]
    if folder != "people" and contact(text):
        out.append(Finding("warn", rel, "an e-mail address or a phone number outside people/ (a third party's data "
                                        "goes in people/, at the minimum)"))
    if known is not None:
        cited = strings(front.get("links")) + [m.strip() for m in WIKILINK.findall(body)]
        out += [Finding("warn", rel, f"{c}: no such Brain id in the graph") for c in dict.fromkeys(cited)
                if BRAIN_ID.match(c) and c not in known]
    own = note_class(cls, front)
    if front.get("share") and own != "private":
        out.append(Finding("error", rel, f"share on a {own} note: only a private note is shared"))
    return out, front


def _layout_findings(root: Path, classes: dict[str, str]) -> list[Finding]:
    f = root / ".gitignore"
    ignore = {line.strip() for line in f.read_text(encoding="utf-8", errors="replace").splitlines()} \
        if f.is_file() else set()
    out = []
    for name in untracked(classes):
        if f"/{name}/" not in ignore:
            out.append(Finding("error", ".gitignore", f"/{name}/ is missing: git would hold {name}/ (brain notes init "
                                                      "adds it)"))
        out += [Finding("error", t, f"tracked by git, in {name}/ (never in git): git rm --cached it")
                for t in _git_tracked(root, name)]
    return out


def check(root: Path, known: set[str] | None = None) -> list[Finding]:
    """Every finding of the notes home at ``root`` (``known``: the Brain's ids, None to leave links unchecked)."""
    fc = folder_classes()
    out = _layout_findings(root, fc)
    ids: dict[str, str] = {}
    tags: dict[str, set[str]] = {}
    for f in note_files(root):
        rel = f.relative_to(root).as_posix()
        folder = rel.split("/", 1)[0]
        found, front = _note_findings(rel, folder, fc.get(folder, "private"),
                                      f.read_text(encoding="utf-8", errors="replace"), known)
        out += found
        nid = front.get("id")
        if isinstance(nid, str) and nid in ids:
            out.append(Finding("error", rel, f"id {nid} is {ids[nid]}'s too: an id is never reused"))
        if isinstance(nid, str):
            ids.setdefault(nid, rel)
        for t in strings(front.get("tags")):
            tags.setdefault(t.lower(), set()).add(t)
    return out + [Finding("warn", "tags", f"{' and '.join(sorted(v))} differ only by case") for v in tags.values()
                  if len(v) > 1]


# --- find ---

INDEX_V = 2   # the index's own shape: a change of it rebuilds every index


def index_path(root: Path) -> Path:
    """The home's index: ``$BRAIN_HOME/notes-index/<a hash of its path>.sqlite`` (derived, rebuilt at will)."""
    key = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:16]
    return paths.brain_home() / "notes-index" / f"{key}.sqlite"


def _table(con: sqlite3.Connection) -> bool:
    """The notes table: FTS5 when SQLite has it (True), else a plain table read with LIKE."""
    try:
        con.execute("CREATE VIRTUAL TABLE notes USING fts5(path UNINDEXED, cls UNINDEXED, scope UNINDEXED, title, "
                    "tags, body)")
        return True
    except sqlite3.OperationalError:
        con.execute("CREATE TABLE notes (path, cls, scope, title, tags, body)")
        return False


def index(root: Path) -> Path:
    """Rebuild the index of the private and confidential notes when a note or a folder's class changed (paths,
    sizes, mtimes, the classes); a sealed note, by its folder or its own ``class``, never enters it. Written to a
    temporary file of this process, then renamed."""
    db = index_path(root)
    fc = folder_classes()
    files = note_files(root)
    stamp = hashlib.sha256(json.dumps([INDEX_V, sorted(fc.items()),
                                       [(str(f), f.stat().st_size, f.stat().st_mtime_ns) for f in files]])
                           .encode("utf-8")).hexdigest()
    mark = db.with_suffix(".stamp")
    if db.is_file() and mark.is_file() and mark.read_text(encoding="utf-8") == stamp:
        return db
    db.parent.mkdir(parents=True, exist_ok=True)
    tmp = db.with_name(f"{db.name}.{os.getpid()}.tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    try:
        _table(con)
        for f in files:
            rel = f.relative_to(root).as_posix()
            front, body = front_matter(f.read_text(encoding="utf-8", errors="replace"))
            cls = note_class(fc.get(rel.split("/", 1)[0], "private"), front)
            if cls not in ("private", "confidential"):
                continue
            front = front or {}
            con.execute("INSERT INTO notes VALUES (?, ?, ?, ?, ?, ?)",
                        (rel, cls, " ".join(strings(front.get("scope"))), str(front.get("title") or f.stem),
                         " ".join(strings(front.get("tags"))), body))
        con.commit()
    finally:
        con.close()
    os.replace(tmp, db)
    mark.write_text(stamp, encoding="utf-8")
    return db


def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def find(root: Path, words: str, *, confidential: bool = False, scope: str = "", limit: int = 20) -> list[dict]:
    """The notes that hold every word of ``words``, best first: private ones only unless ``confidential``; ``scope``
    keeps those of that scope id."""
    terms = re.findall(r"\w+", words)
    if not terms:
        return []
    con = sqlite3.connect(index(root))
    try:
        fts = "fts5" in con.execute("SELECT sql FROM sqlite_master WHERE name = 'notes'").fetchone()[0].lower()
        if fts:
            rows = con.execute("SELECT path, cls, scope, title, snippet(notes, 5, '[', ']', '...', 12) FROM notes "
                               "WHERE notes MATCH ? ORDER BY rank", (" ".join(f'"{t}"' for t in terms),)).fetchall()
        else:
            like = " AND ".join("(title || ' ' || tags || ' ' || body) LIKE ? ESCAPE '\\'" for _ in terms)
            rows = con.execute(f"SELECT path, cls, scope, title, substr(body, 1, 80) FROM notes WHERE {like}",
                               [_like(t) for t in terms]).fetchall()
    finally:
        con.close()
    classes = ("private", "confidential") if confidential else ("private",)
    out = [{"path": p, "class": c, "scope": s.split(), "title": t, "snippet": " ".join(snip.split())}
           for p, c, s, t, snip in rows if c in classes and (not scope or scope in s.split())]
    return out[:limit]
