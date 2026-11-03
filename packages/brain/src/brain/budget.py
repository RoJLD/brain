"""The budget watch: ``hooks/budget.sh`` at ``PostToolUse`` (wi-brain-budget-watch; spec-brain-cost §3.1;
COST-1, 2026-11-02: warn once at 80 % and once at 100 % of the brief's context budget or the item's estimate; the
session decides, nothing stops it or blocks it on a question). Standard library only, never fails.

The owner's sub-session rule gives every delegated task a context budget in its brief and a checkpoint at about 80 % of
it (commit, hand-over note, report); this hook says when that moment comes, so the session does not have to watch
for it. What it compares, both read at zero token:

  context  the session's context (the latest API message's input, cache read and cache write, as
           ``brain.transcript`` counts ``ctx_last``) with its brief's context budget: the first prompts' « Context
           budget: 600k » (``transcript._BUDGET_RE``), the brief the session was started with; nothing else to set.
  cost     the cost of the open items the first prompt names that have a recorded estimate (props.cost_estimate,
           ``brain cost estimate ITEM --record``) with the sum of those estimates: this session's cost at API prices
           (its subagents' included, ``usage.message_cost``) plus what other sessions in the token ledger spent on
           them (the ledger as it is, read once).

At 80 % of either it injects the checkpoint reminder once as hook context; at 100 % once more (the task may be
expanded to the next step); both at once when a session starts past 100 %. It never blocks the tool call or the
session, and a subagent's tool calls count but are not told.

Cost: ``budget.sh`` compares the transcript's mtime with ``<BRAIN_HOME>/budget/<session>.mark`` in bash builtins and
starts no Python while the mark is newer. Python sets the mark's mtime in the future: the next check is due in
``CHECK_S`` seconds (sooner as the budget nears), never again once every notice is given, every ``IDLE_S`` when
there is nothing to watch (an estimate recorded later is then found). Each run reads only the transcript's new bytes
(``<session>.json`` keeps the offsets, the context, the cost and the notices given); marks older than ``KEEP_DAYS``
are pruned.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

from . import paths, transcript, usage

DIR = "budget"
STEPS = (80, 100)
CHECK_S = ((50, 120), (75, 30), (101, 10))  # (below this percent of a budget, the next check in seconds)
IDLE_S = 1800  # nothing to watch: look again (an estimate recorded since) this often
DONE_S = 10 * 365 * 86400  # every notice given: never again
KEEP_DAYS = 14
BRIEF_TEXTS = 5  # the first user texts that may hold the brief's budget (transcript.SessionStats reads as many)
OPEN = ("todo", "doing", "blocked")
_SID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_RECENT = 256


def state_dir() -> Path:
    return paths.brain_home() / DIR


def ktok(n: int) -> str:
    return usage.ktok(n)


# --- the state ---

def _new(sid: str, path: str) -> dict:
    return {"v": 1, "session": sid, "transcript": path, "offsets": {}, "recent": [], "ctx": 0, "cost": 0.0,
            "texts": 0, "budget": None, "items": [], "estimates": {}, "prior_usd": 0.0, "resolved_at": 0.0,
            "warned": {"context": [], "cost": []}}


def _load(sid: str) -> dict | None:
    try:
        state = json.loads((state_dir() / f"{sid}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return state if isinstance(state, dict) and state.get("v") == 1 else None


def _save(state: dict, next_s: float) -> None:
    """The state, then the mark: line 1 the transcript bash compares it with; its mtime ``next_s`` from now."""
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)
    sid = state["session"]
    (d / f"{sid}.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    mark = d / f"{sid}.mark"
    mark.write_text(Path(state["transcript"]).as_posix() + "\n", encoding="utf-8", newline="\n")
    t = time.time() + next_s
    os.utime(mark, (t, t))


def _prune(keep_days: int = KEEP_DAYS) -> None:
    limit = time.time() - keep_days * 86400
    try:
        with os.scandir(state_dir()) as it:
            for e in it:
                if e.name.endswith(".json") and e.stat().st_mtime < limit:
                    os.remove(e.path)
                    mark = Path(e.path).with_suffix(".mark")
                    if mark.exists():
                        os.remove(mark)
    except OSError:
        pass


# --- reading the transcript's new records ---

def _feed(state: dict, path: Path, main: bool) -> None:
    """The records of ``path`` past its offset: each API message's cost once (by message id); the main transcript's
    context (its latest message) and its first user texts (the brief)."""
    key = path.as_posix()
    recent = state["recent"]
    try:
        for rec, pos in transcript.iter_records(path, state["offsets"].get(key, 0)):
            state["offsets"][key] = pos
            t = rec.get("type")
            if t == "assistant":
                msg = rec.get("message") or {}
                mid, model = msg.get("id"), msg.get("model")
                if not mid or model == "<synthetic>" or mid in recent:
                    continue
                recent.append(mid)
                u = msg.get("usage") or {}
                part = transcript._usage_tokens(u)
                state["cost"] += usage.message_cost(part, model or "", u.get("speed") or "") or 0.0
                if main:
                    state["ctx"] = part["input"] + part["cache_read"] + part["cache_write"]
            elif (t == "user" and main and state["texts"] < BRIEF_TEXTS and not rec.get("isMeta")
                  and "toolUseResult" not in rec):
                text = transcript._text_of((rec.get("message") or {}).get("content"))
                if not text.strip():
                    continue
                state["texts"] += 1
                if state["texts"] == 1:
                    state["items"] = list(dict.fromkeys(usage._ID_RE.findall(text)))[:20]
                m = transcript._BUDGET_RE.search(text) if state["budget"] is None else None
                if m:
                    state["budget"] = int(float(m.group(1).replace(",", "."))
                                          * (1_000 if m.group(2).lower() == "k" else 1_000_000))
    except OSError:
        pass
    del recent[:-_RECENT]


# --- the items' estimates, read once ---

def _project_root(cwd: str) -> Path | None:
    here = Path(cwd or ".").resolve()
    return next((d for d in (here, *here.parents) if (d / ".git").exists()), None)


def estimates_of(cwd: str, items: list[str]) -> dict[str, float]:
    """{item: its recorded estimate in USD} for the open items of the project at ``cwd`` (its graph stores) among
    ``items``; {} without PyYAML or a graph."""
    from . import cost, projects, resume  # only when the first prompt names items

    root = _project_root(cwd)
    if root is None or not items:
        return {}
    try:
        p = projects.for_root(root)
        nodes = {}
        for s in p.stores:
            if (s / "nodes").is_dir():
                nodes.update(resume._nodes(s))
    except (SystemExit, ImportError, OSError, ValueError):
        return {}
    out = {}
    for i in items:
        n = nodes.get(i) or {}
        if n.get("type") != "WorkItem" or n.get("status") not in OPEN:
            continue
        usd = cost.parse_estimate(str((n.get("props") or {}).get("cost_estimate") or "")).get("usd")
        if usd:
            out[i] = float(usd)
    return out


def prior_cost(sid: str, items: list[str]) -> float:
    """What the other sessions of the token ledger (as it is, no scan) spent on ``items``: a session serves the items
    it closed, else its title's, else (a sub-session) the first its brief names, as brain.cost joins them, its cost
    shared equally (pull requests are not matched here)."""
    if not items:
        return 0.0
    total = 0.0
    for r in usage.load().values():
        if r.get("session_id") == sid:
            continue
        b = r.get("brief") or {}
        served = r.get("closed") or r.get("title_items") or ((b.get("items") or [])[:1] if b.get("side") else [])
        hit = [i for i in served if i in items]
        if hit:
            total += (r.get("cost") or 0.0) * len(hit) / len(served)
    return total


# --- the check ---

def measures(state: dict) -> dict[str, dict]:
    """{context|cost: {pct, used, budget}} for what has a budget."""
    out = {}
    if state.get("budget"):
        out["context"] = {"used": state["ctx"], "budget": state["budget"],
                          "pct": 100.0 * state["ctx"] / state["budget"]}
    est = sum((state.get("estimates") or {}).values())
    if est:
        used = state["cost"] + state.get("prior_usd", 0.0)
        out["cost"] = {"used": used, "budget": est, "pct": 100.0 * used / est}
    return out


def notices(state: dict) -> list[str]:
    """The notices due now (each step once per measure), marked as given."""
    out = []
    for what, m in measures(state).items():
        given = state["warned"].setdefault(what, [])
        due = [s for s in STEPS if m["pct"] >= s and s not in given]
        if not due:
            continue
        given += due
        out.append(text(what, max(due), m, state))
    return out


def text(what: str, step: int, m: dict, state: dict) -> str:
    pct = f"{m['pct']:.0f} %"
    if what == "context":
        head = (f"Budget watch (COST-1): this session's context is {ktok(m['used'])} tokens, {pct} of its brief's "
                f"context budget ({ktok(m['budget'])}).")
    else:
        items = ", ".join(sorted(state["estimates"]))
        prior = state.get("prior_usd") or 0.0
        head = (f"Budget watch (COST-1): {items} {'has' if len(state['estimates']) == 1 else 'have'} cost "
                f"{usage.usd(m['used'])} at API prices so far (this session {usage.usd(state['cost'])}"
                + (f", earlier sessions {usage.usd(prior)}" if prior else "")
                + f"), {pct} of the recorded estimate ({usage.usd(m['budget'])}, props.cost_estimate).")
    if step < 100:
        from . import config  # here: the hook's quiet calls never need it
        act = (f"{config.owner_of()}'s sub-session rule: checkpoint now: commit your work on your branch, write a "
               "hand-over note (done, left, how to resume) in the shared notes folder, and report. The next notice "
               "comes at 100 %.")
    else:
        act = ("Past the budget: if the task is unfinished, checkpoint and report so that it is expanded to the next "
               "step (400k, 600k, 800k, 1M): this session goes on when its context still helps, else a fresh one "
               "resumes from the hand-over note. Last notice for this budget.")
    return f"{head} {act} You decide; nothing stops or blocks the session."


def next_check(state: dict) -> float:
    """Seconds to the next check: sooner as a budget nears; ``IDLE_S`` while an estimate may still be recorded or
    the brief's budget still come; never again once nothing is left to say."""
    ms = measures(state)
    live = [m["pct"] for w, m in ms.items() if len(state["warned"].get(w, [])) < len(STEPS)]
    if live:
        top = max(live)
        return next((s for limit, s in CHECK_S if top < limit), CHECK_S[-1][1])
    waiting = (state.get("items") and "cost" not in ms) or (state.get("budget") is None
                                                            and state.get("texts", 0) < BRIEF_TEXTS)
    return IDLE_S if waiting else DONE_S


def check(data: dict) -> str:
    """The notices due for this session at this tool call ('' when none), the state and mark moved."""
    sid = str(data.get("session_id") or "")
    path = str(data.get("transcript_path") or "")
    if not _SID_RE.match(sid) or not path:
        return ""
    state = _load(sid)
    if state is None:
        state = _new(sid, path)
        _prune()
    state["transcript"] = path
    main = Path(path)
    _feed(state, main, True)
    for f in transcript.subagent_files(main):
        _feed(state, f, False)
    if state["items"] and not state["estimates"] and time.time() - state.get("resolved_at", 0) >= IDLE_S:
        state["estimates"] = estimates_of(str(data.get("cwd") or "."), state["items"])
        state["prior_usd"] = prior_cost(sid, list(state["estimates"]))
        state["resolved_at"] = time.time()
    out = notices(state)
    _save(state, next_check(state))
    return "" if data.get("agent_id") else "\n".join(out)


def read_payload(stdin=None) -> dict:
    raw = stdin.read() if stdin is not None else getattr(sys.stdin, "buffer", sys.stdin).read()
    if isinstance(raw, bytes):   # the real stdin: UTF-8 bytes; a text stream in its place has no buffer
        raw = raw.decode("utf-8-sig", "replace")
    raw = raw.lstrip("﻿")
    data = json.loads(raw) if raw.strip() else {}
    return data if isinstance(data, dict) else {}


def hook_main(argv: list[str], stdin=None) -> int:
    """PostToolUse hook: the hook JSON on stdin, the notices as additionalContext on stdout. Never fails: an error
    goes to <BRAIN_HOME>/ledger/errors.log."""
    try:
        data = read_payload(stdin)
        out = check(data)
        if out:
            event = argv[0] if argv else str(data.get("hook_event_name") or "PostToolUse")
            print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": out}},
                             ensure_ascii=True))
    except BaseException as exc:  # noqa: BLE001 - a hook never blocks a tool call, SystemExit included
        from .capture import _log_error
        _log_error("budget-watch", exc)
    return 0

