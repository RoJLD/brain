"""The mid-session announcement: ``hooks/midsession.sh`` at ``UserPromptSubmit`` (standard library only, never fails).

``announce.sh`` tells a session when it starts which answers its project has not integrated; a coordination session
runs for hours and the owner answers meanwhile. At each prompt this hook compares the project's queue with the session's
mark and puts one line per decision answered or newly asked since then into the context, then moves the mark; it
prints nothing when none was.

- The queue is ``records/ddr`` of the project's main checkout: a session in a worktree reads the main checkout's, not
  its copy (spec 2026-11-02 §3.7), found from the worktree's ``.git`` file without running git.
- The mark is ``<BRAIN_HOME>/announce/<session>.json`` (each DDR file's mtime, size and status) and ``<session>.mark``
  (the session's folder and the queue's, its mtime a second before the last scan). SessionStart sets it
  (``decisions.hook_main``, right after announcing the answers not integrated); a session without one, say after a
  plugin update, gets it at its first prompt, silently.
- Cost: ``midsession.sh`` compares the mtimes of the queue folder (a DDR added or removed) and of the pending DDRs (an
  answer) with ``<session>.mark`` in bash builtins and starts no Python when none is newer: about 10 ms on Windows
  past bash's own start, flat as archived DDRs pile up. Python compares each file's (mtime, size) with the mark and
  reads only the files that changed, line by line (``decisions._top``, no YAML parser).
- A decision this session asked itself is not announced back as asked; its answer is.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import paths

DIR = "announce"
MAX_ROWS = 8
CAP = 2000  # characters: well under Claude Code's cap on a hook's context
KEEP_DAYS = 14
_SID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def state_dir() -> Path:
    return paths.brain_home() / DIR


def _main_checkout(root: Path) -> Path:
    """The main checkout of the repo whose top folder is ``root``, from files only: a worktree's ``.git`` file names
    ``<common>/worktrees/<name>``, whose ``commondir`` leads to ``<main>/.git``. ``root`` when it is not a worktree."""
    dot = root / ".git"
    try:
        if dot.is_file():
            gitdir = Path(dot.read_text(encoding="utf-8").split("gitdir:", 1)[1].strip())
            gitdir = gitdir if gitdir.is_absolute() else root / gitdir
            common = (gitdir / (gitdir / "commondir").read_text(encoding="utf-8").strip()).resolve()
            if common.name == ".git":
                return common.parent
    except (OSError, IndexError):
        pass
    return root


def queue_dir(cwd: str | Path) -> Path | None:
    """The queue a session in ``cwd`` watches: ``records/ddr`` of its project's main checkout (the project is the
    nearest folder above with notes/graph/schema.yaml), else the project's own; None outside a project."""
    here = Path(cwd).resolve()
    root = next((d for d in (here, *here.parents) if (d / "notes" / "graph" / "schema.yaml").is_file()), None)
    if root is None:
        return None
    for base in (_main_checkout(root), root):
        if (base / "records" / "ddr").is_dir():
            return base / "records" / "ddr"
    return None


def _files(queue: Path | None) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    if queue is None:
        return out
    with os.scandir(queue) as it:
        for e in it:
            if e.name.endswith(".yaml") and e.is_file():
                st = e.stat()
                out[e.name] = [st.st_mtime_ns, st.st_size]
    return out


def _read(f: Path) -> dict:
    from .decisions import _top  # here: decisions imports the record modules, only needed when a file changed

    try:
        return _top(f.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return {}


def _load(sid: str) -> dict | None:
    try:
        state = json.loads((state_dir() / f"{sid}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return state if isinstance(state, dict) and state.get("v") == 1 else None


def _save(sid: str, cwd: str, queue: Path | None, files: dict, seen: dict, started: float) -> None:
    """The state, then the mark the bash fast path reads: line 1 the session's folder as the hook JSON spells it, line
    2 the queue (empty outside a project), then the pending DDRs (and the unreadable ones), the files an answer
    rewrites; a DDR added or removed moves the folder's mtime. The mark's mtime is a whole second before the scan
    began, so a DDR written during or after the scan is newer even where mtimes count in seconds. An answer given
    again to a decision already answered or archived (``--again``) is seen at the next run of Python."""
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)
    state = {"v": 1, "session": sid, "cwd": cwd, "queue": str(queue) if queue else None, "files": files,
             "seen": seen, "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    (d / f"{sid}.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    watch = sorted(n for n, status in seen.items() if status in (None, "pending"))
    mark = d / f"{sid}.mark"
    mark.write_text("\n".join([json.dumps(cwd, ensure_ascii=False)[1:-1], queue.as_posix() if queue else "", *watch])
                    + "\n", encoding="utf-8", newline="\n")
    t = int(started) - 1
    os.utime(mark, (t, t))


def _prune(keep_days: int = KEEP_DAYS) -> None:
    limit = time.time() - keep_days * 86400
    try:
        with os.scandir(state_dir()) as it:
            for e in it:
                if e.name.endswith((".json", ".mark")) and e.stat().st_mtime < limit:
                    os.remove(e.path)
    except OSError:
        pass


def baseline(data: dict) -> bool:
    """Set the session's mark to the queue as it is now (SessionStart, after announce); prunes old marks."""
    sid, cwd = str(data.get("session_id") or ""), str(data.get("cwd") or ".")
    if not _SID_RE.match(sid):
        return False
    started = time.time()
    queue = queue_dir(cwd)
    files = _files(queue)
    seen = {n: _read(queue / n).get("status") for n in files} if queue else {}
    _save(sid, cwd, queue, files, seen, started)
    _prune()
    return True


def check(data: dict) -> str:
    """The lines to announce at this prompt ('' when nothing was answered or asked since the mark), and the mark
    moved. Without a mark, or once the session moved to another project, it sets one and says nothing."""
    sid, cwd = str(data.get("session_id") or ""), str(data.get("cwd") or ".")
    if not _SID_RE.match(sid):
        return ""
    started = time.time()
    state = _load(sid)
    queue = queue_dir(cwd)
    if state is None or state.get("queue") != (str(queue) if queue else None):
        baseline(data)
        return ""
    files, before, seen = _files(queue), state.get("files") or {}, state.get("seen") or {}
    changed = sorted(n for n, sig in files.items() if before.get(n) != sig)
    tops = {n: _read(queue / n) for n in changed}
    answered, asked = [], []
    for n in changed:
        top, was = tops[n], seen.get(n)
        if top.get("status") == "answered" and was != "answered":
            answered.append(top | {"file": n})
        elif top.get("status") == "pending" and n not in seen and top.get("asked_by") != sid:
            asked.append(top | {"file": n})
    seen = {n: (tops[n].get("status") or seen.get(n)) if n in tops else seen.get(n) for n in files}
    _save(sid, cwd, queue, files, seen, started)
    return render(queue, answered, asked) if answered or asked else ""


def render(queue: Path, answered: list[dict], asked: list[dict]) -> str:
    from .decisions import _short

    project = queue.parents[1].name
    counts = ", ".join(t for t in (f"{len(answered)} answered" if answered else "",
                                   f"{len(asked)} newly asked" if asked else "") if t)
    from . import config  # here: the hook's quiet path never needs it
    owner = config.owner_of()
    head = f"{owner}'s decision queue in {project} changed during this session: {counts}."
    if answered:
        head += (" Apply each answer (ADR, item props, spec), then `brain decision ack <id> --applied <where>`; "
                 "the queue: `brain decision pending`.")
    rows = []
    for top in answered:
        choice = "; ".join(top["choices"]) or (f"other: {top['other']}" if top.get("other") else "answered")
        rows.append(f"- answered {top.get('id') or top['file'][:-5]}: {_short(choice, 80)} "
                    f"({_short(top.get('title', ''), 80)})")
    rows += [f"- asked {top.get('id') or top['file'][:-5]}: {_short(top.get('title', ''), 100)} (waits on {owner})"
             for top in asked]
    if len(rows) > MAX_ROWS:
        rows = rows[:MAX_ROWS - 1] + [f"- and {len(rows) - MAX_ROWS + 1} more: `brain decision pending`"]
    return "\n".join([head, *rows])[:CAP]


def read_payload(stdin=None) -> dict:
    """The hook JSON on stdin, read as UTF-8 bytes with a BOM dropped (Python decodes its stdin with the Windows
    codepage, and a PowerShell pipe adds a BOM); {} when it is not a JSON object."""
    raw = stdin.read() if stdin is not None else sys.stdin.buffer.read().decode("utf-8-sig", "replace")
    raw = raw.lstrip("﻿")
    data = json.loads(raw) if raw.strip() else {}
    return data if isinstance(data, dict) else {}


def hook_main(argv: list[str], stdin=None) -> int:
    """UserPromptSubmit hook: the hook JSON on stdin, the announcement as additionalContext on stdout. Never fails: an
    error goes to <BRAIN_HOME>/ledger/errors.log."""
    try:
        data = read_payload(stdin)
        text = check(data)
        if text:
            event = argv[0] if argv else "UserPromptSubmit"
            print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}},
                             ensure_ascii=True))
    except BaseException as exc:  # noqa: BLE001 - a hook never blocks a prompt, SystemExit included
        from .capture import _log_error
        _log_error("midsession-announce", exc)
    return 0
