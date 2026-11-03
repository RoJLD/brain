"""A session's plan, the steps n/m the cockpit shows (wi-brain-tui-cockpit; spec 2026-10-30 §3.6: "l'étape vient
du plan que la session tient déjà, capturé par un hook PostToolUse").

The plan is the task list a session already keeps, through one of the ``PLAN_TOOLS``:

- the desktop app's ``mcp__ccd_turn__update_plan``: ``items`` (the whole list, each ``content`` and ``status``),
  ``advance`` (the step in progress completed, the next pending one started), ``done`` (1-based steps completed) and
  ``start`` (the step started; any other in progress goes back to pending); its ``mcp__ccd_turn__wrap_up`` checks the
  whole list off;
- Claude Code's ``TodoWrite``: ``todos``, the whole list (``content``, ``status``).

``apply`` is the one reading of those calls. Two writers use it, both at zero token:

- the brain's hook (``capture.sh post-tool-use`` on those tools, PostToolUse: ``tool_name`` and ``tool_input``,
  a documented payload) keeps ``<BRAIN_HOME>/sessions/<session_id>.plan.json`` current, one file per session;
- ``Replay`` reads the plan calls from a transcript, from where it stopped the last time, for a session that has no
  plan file (the hook not installed yet when it started, or another tool's session); the transcript format is not a
  public API, so the hook's file wins whenever it exists.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import paths, secretscan, transcript

PLAN_TOOLS = {"mcp__ccd_turn__update_plan": "update", "mcp__ccd_turn__wrap_up": "wrap_up", "TodoWrite": "todos"}
_NEEDLES = tuple(f'"{name}"'.encode() for name in PLAN_TOOLS)
STATUSES = ("pending", "in_progress", "completed")
SUFFIX = ".plan.json"
TEXT_MAX = 200


def _steps(items) -> list[dict]:
    out = []
    for it in items if isinstance(items, list) else []:
        text = " ".join(str(it.get("content") or "").split()) if isinstance(it, dict) else ""
        if text:
            out.append({"content": text[:TEXT_MAX],
                        "status": it.get("status") if it.get("status") in STATUSES else "pending"})
    return out


def _index(value, n: int) -> int | None:
    """A 1-based step number as a 0-based index, None when it is not one (a bool is not a number here)."""
    return value - 1 if type(value) is int and 1 <= value <= n else None


def apply(steps: list[dict], tool: str, inp) -> list[dict] | None:
    """The plan's steps after one call of a plan tool; None when ``tool`` is not one or its input is not a dict."""
    kind = PLAN_TOOLS.get(tool)
    if kind is None or not isinstance(inp, dict):
        return None
    if kind == "todos":
        return _steps(inp.get("todos"))
    steps = [dict(s) for s in steps]
    if kind == "wrap_up":
        return [{**s, "status": "completed"} for s in steps]
    if "items" in inp:
        steps = _steps(inp["items"])
    if inp.get("advance") is True:
        cur = next((i for i, s in enumerate(steps) if s["status"] == "in_progress"), None)
        if cur is not None:
            steps[cur]["status"] = "completed"
        pending = [i for i, s in enumerate(steps) if s["status"] == "pending"]
        nxt = next((i for i in pending if cur is None or i > cur), pending[0] if pending else None)
        if nxt is not None:
            steps[nxt]["status"] = "in_progress"
    done = inp.get("done")
    for n in done if isinstance(done, list) else []:
        i = _index(n, len(steps))
        if i is not None:
            steps[i]["status"] = "completed"
    start = _index(inp.get("start"), len(steps))
    if start is not None:
        for s in steps:
            if s["status"] == "in_progress":
                s["status"] = "pending"
        steps[start]["status"] = "in_progress"
    return steps


def progress(steps: list[dict]) -> dict:
    """{total, done, step (the 1-based step in progress, else None), current (its text)}."""
    cur = next((i for i, s in enumerate(steps) if s.get("status") == "in_progress"), None)
    return {"total": len(steps), "done": sum(1 for s in steps if s.get("status") == "completed"),
            "step": None if cur is None else cur + 1, "current": "" if cur is None else steps[cur]["content"]}


def label(steps: list[dict]) -> str:
    """``3/8 Build the panels``, ``8/8 done``, ``2/5`` (none in progress) or '' without a plan."""
    p = progress(steps)
    if not p["total"]:
        return ""
    if p["step"]:
        return f"{p['step']}/{p['total']} {p['current']}"
    return f"{p['done']}/{p['total']}" + (" done" if p["done"] == p["total"] else "")


# --- the hook's file ---

def plan_file(session_id: str) -> Path:
    return paths.sessions_dir() / f"{session_id}{SUFFIX}"


def read(session_id: str) -> dict | None:
    """The plan the hook keeps for a session ({session_id, at, tool, steps}), None without one."""
    f = plan_file(session_id)
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("steps"), list) else None


def capture(payload: dict, now: str | None = None) -> bool:
    """The PostToolUse hook on a plan tool: the session's plan file updated; False when the call is not one."""
    sid, tool = payload.get("session_id"), payload.get("tool_name") or ""
    if not sid or tool not in PLAN_TOOLS:
        return False
    old = read(sid)
    steps = apply(old["steps"] if old else [], tool, payload.get("tool_input"))
    if steps is None:
        return False
    at = now or transcript.iso(datetime.now(timezone.utc))
    rec, _ = secretscan.clean({"v": 1, "session_id": sid, "at": at, "tool": tool, "steps": steps})
    d = paths.sessions_dir()
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f"{sid}{SUFFIX}.tmp"
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(plan_file(sid))
    return True


# --- from a transcript ---

class Replay:
    """The plans of transcripts, read incrementally: each call reads only what was appended since the last one."""

    SEEN_MAX = 64

    def __init__(self) -> None:
        self.state: dict[str, dict] = {}

    def steps(self, path: str | Path) -> list[dict]:
        key = str(path)
        st = self.state.setdefault(key, {"offset": 0, "steps": [], "seen": []})
        try:
            if Path(path).stat().st_size < st["offset"]:  # rewritten: start over
                st.update(offset=0, steps=[], seen=[])
        except OSError:
            return st["steps"]
        try:
            with open(path, "rb") as fh:
                fh.seek(st["offset"])
                for raw in fh:
                    if not raw.endswith(b"\n"):  # a partial last line is read next time
                        break
                    st["offset"] += len(raw)
                    if any(n in raw for n in _NEEDLES):  # parse only the lines that name a plan tool
                        self._feed(st, raw)
        except OSError:
            pass
        return st["steps"]

    def _feed(self, st: dict, raw: bytes) -> None:
        try:
            rec = json.loads(raw)
        except ValueError:
            return
        if not isinstance(rec, dict) or rec.get("type") != "assistant":
            return
        for b in (rec.get("message") or {}).get("content") or []:
            if not (isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in PLAN_TOOLS):
                continue
            if b.get("id") and b["id"] in st["seen"]:  # the same call written twice
                continue
            new = apply(st["steps"], b["name"], b.get("input"))
            if new is not None:
                st["steps"] = new
            if b.get("id"):
                st["seen"] = (st["seen"] + [b["id"]])[-self.SEEN_MAX:]
