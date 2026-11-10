"""The read commands' hint (wi-brain-read-commands): a PreToolUse hook on Read, Grep, Bash and PowerShell that, when
the call reads a registered brain's graph YAML (a store's nodes/ or edges/, or the store itself), its decision log,
its journal or one of its generated views by hand, adds hook context naming the brain command that answers (brain
item show, brain items, brain adr show, brain journal last, brain next, brain decision pending, brain features).

Never a refusal: it prints no permissionDecision, only additionalContext, and nothing at all on an error (logged to
<BRAIN_HOME>/ledger/errors.log). readhint.sh starts it only when the hook's JSON names one of those files, with bash
builtins; a shell command counts only when it reads (grep, rg, cat, head, tail, sed, awk, Select-String,
Get-Content...). "Registered": the file is under the root of a project of the brain's registry, or of a worktree of
its checkout (read from the worktree's .git file, no git started). Opt-in: registered in the rendered hooks.json
only when config.json hints.read is true (brain.render.OPTIONAL_HOOKS); BRAIN_READ_HINT=0 turns it off while on.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from . import projects

KINDS = (   # (a path's posix form, its kind), the first that matches
    (re.compile(r"(^|/)(nodes|edges)/[^/]+\.ya?ml$", re.I), "graph"),
    (re.compile(r"(^|/)(graph|graph/nodes|graph/edges)/?$", re.I), "graph"),
    (re.compile(r"(^|/)(scientific_)?decisions\.md$", re.I), "adr"),
    (re.compile(r"(^|/)journal\.md$", re.I), "journal"),
    (re.compile(r"(^|/)(kanban_graph|roadmap_graph)\.md$", re.I), "board"),
    (re.compile(r"(^|/)plan_graph\.md$", re.I), "plan"),
    (re.compile(r"(^|/)decision_queue\.md$", re.I), "queue"),
    (re.compile(r"(^|/)FEATURES\.md$"), "features"),
)
WHAT = {"graph": "graph YAML", "adr": "decision log", "journal": "journal", "board": "generated board",
        "plan": "generated plan", "queue": "generated decision queue", "features": "generated feature matrix"}
READER = re.compile(r"(^|[\s;&|(`])(grep|egrep|fgrep|rg|cat|head|tail|less|more|sed|awk|gawk|wc|nl|select-string|sls|"
                    r"get-content|gc|type|findstr)(\.exe)?(?=[\s\"']|$)", re.I)
TOKEN = re.compile(r"""[^\s'"|;&<>()`]+""")
ID = re.compile(r"\b((?:wi|spec|ms|adr|sdr|rule|feat|wave|era)-[A-Za-z0-9][A-Za-z0-9._-]*)")


def kind_of(path: str) -> str:
    p = path.replace("\\", "/")
    return next((k for rx, k in KINDS if rx.search(p)), "")


def _targets(tool: str, inp: dict) -> tuple[list[str], str]:
    """(the paths the call reads, the text its ids are looked for in)."""
    if tool == "Read":
        return [str(inp.get("file_path") or "")], ""
    if tool == "Grep":
        path = str(inp.get("path") or "")
        paths = [path] + ([f"{path.rstrip('/') or '.'}/{inp['glob']}"] if inp.get("glob") else [])
        return paths, str(inp.get("pattern") or "")
    command = str(inp.get("command") or "")
    if not READER.search(command):
        return [], ""
    return [t for t in TOKEN.findall(command) if kind_of(t)], command


def _worktree_main(d: Path) -> Path | None:
    """The main checkout of a linked worktree at ``d``, read from its .git file (gitdir: <main>/.git/worktrees/x)."""
    try:
        line = (d / ".git").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    m = re.match(r"gitdir:\s*(.+?)[/\\]\.git[/\\]worktrees[/\\][^/\\]+$", line)
    return Path(m.group(1)) if m else None


def _files(p: projects.Project) -> list[Path]:
    """A project's stores, journals and decision logs, relative to its root."""
    return [f.relative_to(p.root) for f in [*p.stores, *p.journals, *p.decision_logs] if f.is_relative_to(p.root)]


def _pick(here: list[projects.Project], rel: Path) -> str:
    """Of the projects registered at one root, the one whose store, journal or decision log holds ``rel``, else the
    root's owner (the first registered there)."""
    for p in here:
        if any(rel == f or f in rel.parents for f in _files(p)):
            return p.name
    return here[0].name


def owner(path: Path) -> tuple[str, Path] | None:
    """(the registered project, the root) a file is under: a project's root, or a worktree of its checkout."""
    roots: dict[str, list[projects.Project]] = {}
    for p in projects.load().values():
        roots.setdefault(os.path.normcase(str(p.root)), []).append(p)
    for d in path.parents:
        here = roots.get(os.path.normcase(str(d)))
        if not here and (d / ".git").is_file():
            main = _worktree_main(d)
            here = roots.get(os.path.normcase(str(main.resolve()))) if main else None
        if here:
            return _pick(here, path.relative_to(d)), d
        if (d / ".git").exists():
            return None
    return None


def _is_brain_file(kind: str, path: Path, root: Path) -> bool:
    """A graph file is in a store (a folder above it, below the root, holds schema.yaml); the others are under the
    root."""
    if kind != "graph":
        return True
    here = path if path.suffix == "" else path.parent
    return any((d / "schema.yaml").is_file() for d in (here, *here.parents) if d == root or root in d.parents)


def _command(kind: str, project: str, text: str) -> str:
    """The command that answers, with the id the call looked for when it names one."""
    ids = ID.findall(text or "")
    nid = ids[0] if ids else ""
    p = f"brain --project {project}"
    if kind == "graph" or (kind in ("board", "plan") and nid):
        if nid.startswith(("adr-", "sdr-")):
            return f"`{p} adr show {nid}` (the ADR's text)"
        if nid:
            return (f"`{p} item show {nid}` (its props in full, edges both ways, the ADRs and DDRs behind it; "
                    "--history: its changes)")
        return (f"`{p} item show <id>` (one node and all that bears on it) or `{p} items --text WORDS` (filters: "
                "--status, --priority, --wave, --milestone, --prop K=V, --type)")
    return {
        "adr": f"`{p} adr show {nid or '<adr-id|title|rule-id>'}` (an ADR's text, or the ADRs that decide a node; "
               "--titles lists them)",
        "journal": f"`{p} journal last [N]` (the last N entries; --titles: their headings)",
        "board": f"`{p} items` (filters: --status, --priority, --wave, --milestone, --prop K=V, --text)",
        "plan": f"`{p} next` (the current wave) or `{p} items --wave X.Y.Z`",
        "queue": f"`{p} decision pending`",
        "features": f"`{p} features list|search WORDS|show ID`",
    }[kind]


def hint(data: dict) -> str:
    """The hint for a hook payload, '' when the call reads none of a registered brain's files."""
    tool = str(data.get("tool_name") or "")
    inp = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
    paths, text = _targets(tool, inp)
    cwd = Path(str(data.get("cwd") or os.getcwd()))
    for raw in paths:
        kind = kind_of(raw)
        if not kind:
            continue
        path = Path(raw.replace("\\", "/").split("*", 1)[0].rstrip("/") or ".")
        path = (path if path.is_absolute() else cwd / path).resolve()
        found = owner(path)
        if not found or not _is_brain_file(kind, path, found[1]):
            continue
        rel = path.relative_to(found[1]).as_posix() if path.is_relative_to(found[1]) else path.as_posix()
        return (f"brain read hint: {rel} is the {WHAT[kind]} of the brain {found[0]}; "
                f"{_command(kind, found[0], text or raw)} answers this without reading the file by hand. A hint, "
                "not a refusal: go on if you need the raw file.")
    return ""


def hook_main(argv: list[str], stdin=None) -> int:
    """PreToolUse hook: the hook JSON on stdin, the hint as additionalContext on stdout. Never fails."""
    try:
        raw = stdin.read() if stdin is not None else getattr(sys.stdin, "buffer", sys.stdin).read()
        if isinstance(raw, bytes):   # the real stdin: UTF-8 bytes, whatever the console's codepage
            raw = raw.decode("utf-8-sig", "replace")
        data = json.loads(raw.lstrip("﻿") or "{}")
        out = hint(data) if isinstance(data, dict) else ""
        if out:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": out}},
                             ensure_ascii=True))
    except Exception as exc:   # a hint never stands in a tool call's way
        from .capture import _log_error
        _log_error("read-hint", exc)
    return 0
