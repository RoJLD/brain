"""The coordinators' succession (wi-brain-handover-command): ``brain handover write|check|root``.

A Brain coordinator hands over to the coordinator it starts (the private brain's coordinator-handover skill, the ADR of
2026-11-11): its hand-over note in ``<BRAIN_HOME>/handover/``, opening with its own app id, then Remote Control on for
the successor and off on itself, two calls the guard lets through only when its conditions hold
(:func:`brain.guards.remote_control`). This module writes the note and checks those conditions before the calls, at
zero token, from the same files the guard reads:

- :func:`write_note` writes ``coordinator-<date>-<name>.md``, whose first line is ``From <app id> (<name>), <date>
  UTC``: the guard reads the first app id in the note's opening as whose note it is;
- :func:`check` says, for a session (this one by default), whether each condition holds: a coordinator by name (or a
  chain root), started by a coordinator by name or by a chain root, its note written in the last 6 hours, its
  successors (the coordinators it started, live, detached), and its predecessor (the session that started it), which
  the incoming coordinator archives first (a session's own archive is refused);
- :func:`write_brief` writes, beside the note, the successor's brief (``<note>.brief.txt``, read by no guard: its
  first line carries the word ``ultracode``, the owner's decision of 2026-11-12, so that ultracode is on at every
  hand-over: the keyword in a session's first message turns it on there), to paste as start_session's prompt;
- :func:`wait` waits, bounded, for the successor's first turn (a transcript: live) before Remote Control on for it: a
  session started seconds ago has none yet, and an engine before 0.4.0 refuses it as unknown; on a refusal that says
  ``is unknown``, the procedure waits again and retries once;
- :func:`mark_root` and :func:`clear_root` are the owner's, in their own terminal (refused in a Claude Code session's
  shell; the guard refuses ``brain handover root`` and a write into the file or its folder to a session, like
  ``brain usage allow``: it holds against a mistake, not against a script that calls the engine): a chain root is a
  session the owner started (no parent in the app's files) and marked, ``<BRAIN_HOME>/handover/roots.json``. A root may
  hand over without a name or a coordinator parent, and the coordinators it starts pass the parent
  condition through it, until the owner clears the mark.

The standard library and brain only.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from . import guards, paths, sessions

NAME_SAFE = re.compile(r"[^a-z0-9-]+")
BRIEF_SUFFIX = ".brief.txt"   # beside the note; not *.md: the guard never reads it as a note
WAIT_S = 120       # brain handover wait's default bound, in seconds (the procedure's « about two minutes »)
WAIT_MAX_S = 600   # its longest: a starting successor counts for guards.HANDOVER_START_S (ten minutes)
POLL_S = 3.0


class SuccessionError(Exception):
    """A request that cannot be done: no app id, an unknown session, a root refused."""


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M")


def _own_id(host: str | None, env=None) -> str:
    host = (host or sessions.here(env)["host_id"] or "").strip()
    if not sessions.HOST_RE.match(host):
        raise SuccessionError("no app id: run it in a desktop app session (CLAUDE_CODE_HOST_SESSION_ID), or pass --id "
                              "local_<uuid>")
    return host


def note_name(name: str, now: float, host: str = "") -> str:
    """``coordinator-<YYYY-MM-DD>-<name>.md``, the name made safe; a session without a name (a root) takes
    ``root-<the first 8 hex digits of its app id>``, so that two of them never share a file."""
    slug = NAME_SAFE.sub("-", (name or "").lower()).strip("-").removeprefix("coordinator-")
    slug = slug or "root-" + (host.removeprefix("local_")[:8] or "x")
    return f"coordinator-{datetime.fromtimestamp(now, timezone.utc):%Y-%m-%d}-{slug}.md"


def write_note(body: str = "", *, host: str | None = None, name: str | None = None, successor: str = "",
               now: float | None = None, env=None) -> Path:
    """Write the session's hand-over note in <BRAIN_HOME>/handover/: its first line names its app id first (the guard
    reads the first app id of the opening as whose note it is), then the successor's name, then ``body``. A body
    whose opening names another app id before the session's cannot misplace it: the session's id comes first."""
    now = time.time() if now is None else now
    host = _own_id(host, env)
    if name is None:
        name = str(sessions.app_meta(host).get("name") or "")
    head = f"From {host} ({name or 'chain root'}), {_iso(now)} UTC"
    lines = [head]
    if successor:
        lines.append(f"Successor: {successor}")
    text = "\n".join(lines) + "\n\n" + (body.rstrip() + "\n" if body.strip() else "")
    d = paths.brain_home() / guards.HANDOVER_DIR
    d.mkdir(parents=True, exist_ok=True)
    f = d / note_name(name, now, host)
    if len(text.encode("utf-8")) > guards.HANDOVER_MAX:
        raise SuccessionError(f"the note is over {guards.HANDOVER_MAX} bytes: the guard would not read it; shorten it")
    other = _first_id(f)
    if other and other != host:
        raise SuccessionError(f"{f} is {other}'s note: pass another --id, or remove it if it is stale")
    f.write_text(text, encoding="utf-8")
    os.utime(f, (now, now))
    return f


def brief_text(host: str, name: str, successor: str, note: Path, body: str = "") -> str:
    """The successor's brief: its first line carries ``ultracode`` (ultracode on at every hand-over), then the note
    to read, the predecessor to archive first, the next steps; ``body`` follows."""
    head = (f"ultracode: you are {successor or 'the next Brain coordinator'}, taking over from {host} "
            f"({name or 'chain root'}).")
    steps = [head, "",
             f"1. Read the hand-over note {note.as_posix()} first; brain handover check --id <your id> reads the "
             "guard's conditions.",
             f"2. Archive your predecessor before anything else: archive_session {host} (the desktop app adds a "
             "session field: resend the same call once; refused while its Remote Control is on or it still works).",
             "3. Then the note's next steps: the open PRs, the running sessions and what waits on the owner."]
    tail = "\n" + body.rstrip() + "\n" if body.strip() else ""
    return "\n".join(steps) + "\n" + tail


def write_brief(note: Path, *, successor: str, host: str | None = None, name: str | None = None, body: str = "",
                env=None) -> Path:
    """Write the successor's brief beside ``note`` (``<note stem>.brief.txt``); the guard reads only ``*.md``."""
    host = _own_id(host, env)
    if name is None:
        name = str(sessions.app_meta(host).get("name") or "")
    f = note.with_name(note.stem + BRIEF_SUFFIX)
    f.write_text(brief_text(host, name, successor, note, body), encoding="utf-8")
    return f


def drop_brief(note: Path) -> bool:
    """Remove the successor's brief beside ``note`` (a note written again without a successor): whether one was."""
    f = note.with_name(note.stem + BRIEF_SUFFIX)
    try:
        f.unlink()
    except FileNotFoundError:
        return False
    return True


def _first_id(f: Path) -> str:
    """The first app id of an existing note's opening (whose note it is), '' when there is none."""
    try:
        m = guards.LOCAL_ID.search(f.read_text(encoding="utf-8", errors="replace")[:guards.HANDOVER_HEAD])
    except OSError:
        return ""
    return m.group(0) if m else ""


def read_body(path: str) -> str:
    """A note's body from a file: UTF-8 (a BOM allowed), or UTF-16 with its BOM (PowerShell 5.1's ``>``)."""
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SuccessionError(f"{path} is neither UTF-8 nor UTF-16 with a BOM") from exc
    return text.replace("\r\n", "\n")


def _app(host: str) -> tuple[dict, object, dict]:
    """(index, meta, the session's own app file), or SuccessionError when the app's files cannot tell."""
    index = sessions.app_index()
    if index is None:
        raise SuccessionError("the desktop app's session files are not on this machine")
    meta = guards.app_reader(index)
    me = meta(host)
    if not me:
        raise SuccessionError(f"{host} is not in the desktop app's session files (or its file is in two folders)")
    return index, meta, me


def _target_why(host: str, target: str, tm: dict, now: float) -> str:
    """'' when Remote Control on for ``target`` (its app file ``tm``) passes the target's conditions, else why not."""
    if not target:
        return "it has started no coordinator to succeed it"
    if not tm or tm.get("parent") != host:
        return f"{target} was not started by this session"
    if not guards._coordinator(tm):
        return f"{target} is not a Brain coordinator (the name this session gave it)"
    st, how = guards.successor_state_of(tm, now)   # a successor with no transcript yet counts while starting
    return "" if st in guards.RC_LIVE + ("starting",) else f"{target} is {st}" + (f": {how}" if how else "")


def check(host: str | None = None, *, successor: str = "", now: float | None = None, env=None) -> dict:
    """Each condition of the hand-over for session ``host`` (this one by default), as the guard reads them:
    {id, name, root, coordinator, parent, parent_name, parent_ok, note, note_age_min, successors, successor, why, ok,
    on, on_why, off, off_why}. ``ok``: the session may hand over (``why`` is '' then); ``on``: Remote Control on for
    ``successor`` (else the first successor found) would pass; ``off``: off on itself would pass."""
    now = time.time() if now is None else now
    host = _own_id(host, env)
    index, meta, me = _app(host)
    parent = str(me.get("parent") or "")
    pm = meta(parent) if parent else {}
    parent_ok = bool(pm) and (guards._coordinator(pm) or guards.chain_root(parent, pm))
    note = guards.handover_note(host, now)
    age = round((now - note.stat().st_mtime) / 60) if note else None
    why = guards.handover_why(host, me, meta, now)
    succ = guards.successors(host, index, meta, now)
    target = successor or next(iter(succ), "")
    on_why = why or _target_why(host, target, meta(target) if target else {}, now)
    off_why = why or ("it has started no live coordinator to succeed it, detached" * (not succ))
    return {"id": host, "name": me.get("name") or "", "root": guards.chain_root(host, me),
            "coordinator": guards._coordinator(me), "parent": parent, "parent_name": pm.get("name") or "",
            "parent_ok": parent_ok, "note": str(note or ""), "note_age_min": age,
            "successors": succ, "successor": target, "why": why, "ok": not why,
            "on": not on_why, "on_why": on_why, "off": not off_why, "off_why": off_why}


def wait(successor: str, host: str | None = None, *, timeout: float = WAIT_S, poll: float = POLL_S, env=None,
         clock=time.monotonic, sleep=time.sleep) -> dict:
    """Wait, at most ``timeout`` seconds, for the successor's first turn: {id, successor, state, waited_s, ok, why,
    detached} (``detached``: Remote Control off on this session needs it too).
    ``ok`` once it has a transcript and is live (Remote Control on for it then passes any engine's guard); not ``ok``
    at once when it is not this session's coordinator successor or is archived, ended or unknown beyond its start
    window; not ``ok`` with state ``starting`` when the bound passed first (an engine from 0.4.0 still lets on through
    while it starts)."""
    host = _own_id(host, env)
    if not sessions.HOST_RE.match(successor or ""):
        raise SuccessionError(f"{successor!r} is not an app id (local_<uuid>)")
    timeout = max(0.0, min(float(timeout), WAIT_MAX_S))
    t0 = clock()
    while True:
        _, meta, _ = _app(host)
        tm = meta(successor)
        st, how = guards.successor_state_of(tm, time.time()) if tm else ("unknown", "not in the app's files yet")
        why = _target_why(host, successor, tm, time.time()) if tm else ""
        waited = round(clock() - t0, 1)
        r = {"id": host, "successor": successor, "state": st, "waited_s": waited, "ok": False, "why": why,
             "detached": bool(tm) and tm.get("detached") is True}
        if tm and not why and st in guards.RC_LIVE:
            return {**r, "ok": True}
        if why:   # not this session's coordinator successor, archived, ended, beyond its start window: at once
            return r
        if waited >= timeout:
            got = f"no first turn after {int(timeout)} s ({how})" if tm else \
                f"not in the desktop app's session files after {int(timeout)} s (a wrong id?)"
            return {**r, "state": "starting" if tm else "unknown", "why": got}
        sleep(min(poll, max(0.1, timeout - waited)))


NOT_MARKED = "NOT a coordinator by name, nor a marked root"


def _started_line(r: dict) -> str:
    if r["root"]:
        return "started by   the owner (a chain root: the parent condition is lifted)"
    if r["parent"]:
        return (f"started by   {r['parent']} ({r['parent_name'] or 'no name'}): "
                + ("ok" if r["parent_ok"] else NOT_MARKED))
    return f"started by   the owner, unmarked: the owner marks it in their own terminal (brain handover root {r['id']})"


def _call_line(r: dict, case: str, call: str) -> str:
    return f"{case:<13}" + (f"ok ({call})" if r[case] else "refused: " + r[case + "_why"])


def lines(r: dict) -> list[str]:
    """The check, for a person: one line per condition, then what the incoming coordinator does first."""
    who = r["name"] or ("chain root" if r["root"] else "no name")
    kind = "a chain root the owner marked" if r["root"] else "a coordinator by name" if r["coordinator"] else NOT_MARKED
    note = (f"{r['note']} ({r['note_age_min']} min old)" if r["note"] else
            f"NONE of {r['id']} in {guards.HANDOVER_DIR}/ in the last {guards.HANDOVER_NOTE_S // 3600} h "
            "(brain handover write)")
    out = [f"session      {r['id']} ({who}): {kind}", _started_line(r), f"note         {note}",
           "successors   " + (", ".join(r["successors"]) or "none (a coordinator it started, live and detached)"),
           _call_line(r, "on", f"set_remote_control {r['successor']} enabled true"),
           _call_line(r, "off", "set_remote_control self enabled false")]
    if r["parent"]:
        out.append(f"predecessor  {r['parent']}: an incoming coordinator archives it first (archive_session; its "
                   "Remote Control off, its work finished)")
    return out


def _refused(env=None) -> str:
    env = os.environ if env is None else env
    return ("the chain root is the owner's mark, in their own terminal: not from a Claude Code session's shell "
            "(CLAUDECODE is set)" if "CLAUDECODE" in env else "")


def _load_roots() -> dict:
    try:
        data = json.loads(guards.roots_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"v": 1, "roots": {}}
    if not isinstance(data, dict) or not isinstance(data.get("roots"), dict):
        return {"v": 1, "roots": {}}
    return data


def _save_roots(data: dict) -> Path:
    f = guards.roots_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, f)
    return f


def mark_root(host: str, reason: str = "", *, now: float | None = None, env=None) -> dict:
    """The owner marks ``host`` a chain root: refused in a Claude Code session's shell, for an id that is not an app
    id, and for a session the app's files say another session started (a root is the owner's)."""
    why = _refused(env)
    if why:
        raise SuccessionError(why)
    if not sessions.HOST_RE.match(host or ""):
        raise SuccessionError(f"{host!r} is not an app id (local_<uuid>)")
    m = sessions.app_meta(host)
    if not m:
        raise SuccessionError(f"{host} is not in the desktop app's session files on this machine")
    if m.get("parent"):
        raise SuccessionError(f"{host} was started by {m['parent']}, not by the owner: no chain root")
    now = time.time() if now is None else now
    data = _load_roots()
    data["roots"][host] = {"at": _iso(now) + " UTC", "reason": reason, "title": str(m.get("title") or "")[:120]}
    data["v"] = 1
    _save_roots(data)
    return data["roots"][host]


def clear_root(host: str, *, env=None) -> bool:
    """The owner removes a chain root's mark; whether it was marked."""
    why = _refused(env)
    if why:
        raise SuccessionError(why)
    data = _load_roots()
    if host not in data["roots"]:
        return False
    del data["roots"][host]
    _save_roots(data)
    return True


def roots() -> dict:
    """The marked chain roots: {app id: {at, reason, title}}."""
    return guards.chain_roots()
