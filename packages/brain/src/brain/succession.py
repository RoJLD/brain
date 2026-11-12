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
- :func:`mark_root` and :func:`clear_root` are the owner's, in their own terminal (refused in a Claude Code session's
  shell; the guard refuses ``brain handover root`` and a write into the file to every session): a chain root is a
  session the owner started (no parent in the app's files) and marked, ``<BRAIN_HOME>/handover/roots.json``. A root may
  hand over without a name or a coordinator parent, and its first successor's parent condition holds through it.

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


def note_name(name: str, now: float) -> str:
    """``coordinator-<YYYY-MM-DD>-<name>.md``, the name made safe (a root has none: ``root``)."""
    slug = NAME_SAFE.sub("-", (name or "root").lower()).strip("-") or "root"
    slug = slug.removeprefix("coordinator-").removeprefix("coordinateur-") or "root"
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
    f = d / note_name(name, now)
    if len(text.encode("utf-8")) > guards.HANDOVER_MAX:
        raise SuccessionError(f"the note is over {guards.HANDOVER_MAX} bytes: the guard would not read it; shorten it")
    f.write_text(text, encoding="utf-8")
    os.utime(f, (now, now))
    return f


def check(host: str | None = None, *, successor: str = "", now: float | None = None, env=None) -> dict:
    """Each condition of the hand-over for session ``host`` (this one by default), as the guard reads them:
    {id, name, root, coordinator, parent, parent_name, parent_ok, note, note_age_min, successors, successor, why, ok,
    on, off}. ``ok``: the session may hand over (``why`` is '' then); ``on``: Remote Control on for ``successor`` (else
    the first successor found) would pass; ``off``: off on itself would pass."""
    now = time.time() if now is None else now
    host = _own_id(host, env)
    index = sessions.app_index()
    if index is None:
        raise SuccessionError("the desktop app's session files are not on this machine")
    meta = guards.app_reader(index)
    me = meta(host)
    if not me:
        raise SuccessionError(f"{host} is not in the desktop app's session files (or its file is in two folders)")
    parent = str(me.get("parent") or "")
    pm = meta(parent) if parent else {}
    note = guards.handover_note(host, now)
    why = guards.handover_why(host, me, meta, now)
    succ = guards.successors(host, index, meta, now)
    target = successor or (succ[0] if succ else "")
    tm = meta(target) if target else {}
    st = ("archived" if tm.get("archived") else sessions.state_of(tm, {}, now)) if tm else ""
    on_why = why or ("" if target else "it has started no coordinator to succeed it") or \
        ("" if tm and tm.get("parent") == host else f"{target} was not started by this session") or \
        ("" if guards._coordinator(tm) else f"{target} is not a Brain coordinator (the name this session gave it)") or \
        ("" if st in guards.RC_LIVE else f"{target} is {st or 'unknown'}")
    off_why = why or ("" if succ else "it has started no live coordinator to succeed it, detached")
    return {"id": host, "name": me.get("name") or "", "root": guards.chain_root(host, me),
            "coordinator": guards._coordinator(me), "parent": parent, "parent_name": pm.get("name") or "",
            "parent_ok": bool(pm) and (guards._coordinator(pm) or guards.chain_root(parent, pm)),
            "note": str(note) if note else "",
            "note_age_min": round((now - note.stat().st_mtime) / 60) if note else None,
            "successors": succ, "successor": target, "why": why, "ok": not why,
            "on": not on_why, "on_why": on_why, "off": not off_why, "off_why": off_why}


def lines(r: dict) -> list[str]:
    """The check, for a person: one line per condition, then what the incoming coordinator does first."""
    who = r["name"] or ("chain root" if r["root"] else "no name")
    out = [f"session      {r['id']} ({who}): "
           + ("a chain root the owner marked" if r["root"] else
              "a coordinator by name" if r["coordinator"] else "NOT a coordinator by name, nor a marked root")]
    if r["root"]:
        out.append("started by   the owner (a chain root: the parent condition is lifted)")
    elif r["parent"]:
        out.append(f"started by   {r['parent']} ({r['parent_name'] or 'no name'}): "
                   + ("ok" if r["parent_ok"] else "NOT a coordinator by name, nor a marked root"))
    else:
        out.append("started by   the owner, unmarked: the owner marks it in their own terminal "
                   f"(brain handover root {r['id']})")
    out.append(f"note         {r['note']} ({r['note_age_min']} min old)" if r["note"] else
               f"note         NONE of {r['id']} in {guards.HANDOVER_DIR}/ in the last "
               f"{guards.HANDOVER_NOTE_S // 3600} h (brain handover write)")
    out.append("successors   " + (", ".join(r["successors"]) if r["successors"] else
                                  "none (a coordinator it started, live and detached)"))
    out.append(f"on           {'ok' if r['on'] else 'refused: ' + r['on_why']}"
               + (f" (set_remote_control {r['successor']} enabled true)" if r["on"] else ""))
    out.append(f"off          {'ok' if r['off'] else 'refused: ' + r['off_why']}"
               + (" (set_remote_control self enabled false)" if r["off"] else ""))
    if r["parent"]:
        out.append(f"predecessor  {r['parent']}: an incoming coordinator archives it first (archive_session; its "
                   "Remote Control off, its work finished)")
    return out


def _refused(env=None) -> str:
    env = os.environ if env is None else env
    return ("the chain root is the owner's mark, in their own terminal: not from a Claude Code session's shell "
            "(CLAUDECODE is set)" if env.get("CLAUDECODE") else "")


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
