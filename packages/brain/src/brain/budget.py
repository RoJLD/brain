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
session, and a subagent's tool calls count but are not told: the notices they find due wait for the main thread's
next call.

The master's watch (wi-brain-master-watch; ST-3, ST-4, ST-10): a session that has started a session is a master: a
start_session call the owner asked for (``initiation`` user_asked or none, or a ``proposal_id`` the owner told it to
start) whose result is not an error, or a child the app's files name. A proposal (``offer``, ``own_initiative``) starts nothing: the app is asked at
each check whether the owner started one from it. Its context budget is its brief's, else ``usage.master_budget``,
else the model's window (brain.sessions.budget_of), and its context steps are 70, 80, 90 and 100 % instead of 80 and
100 (:data:`MASTER_STEPS`). Its children come from the desktop app's session files and the SessionStart events
(brain.sessions, a closed list of keys; read only when a check is due, and only for a master); a child is live until
the app archives it (a child the app does not know: until its end is recorded; brain.sessions.alive), and a child
detached to the top level (``lineageDetached``) is no longer its child.

  70 %  the room left in children before 80 %: what is left of the budget over the context one child costs the
        master, measured on its family (its context growth since its first child over the children it saw start),
        else :data:`CHILD_K`;
  80 %  start no new child, hand over to a fresh master and drain yours (answer them, review and merge their PRs,
        archive them; ask the owner nothing new, touch no other master's children), with a draft hand-over note: the
        live children with both ids, their items and their state now (their transcript's tail);
  90 %  drain only; compact only once no child is alive.

Each step also gives the cost of one wake after the prompt cache expired (the context rewritten at the model's
cache-write price), the reason to hand over before a long wait rather than after. The master's state
(``master``: pct, step, live children) stays in this file for the cockpit's row and brain alerts; the governor reads
it to remind a master past 80 % that calls start_session (brain.governor; ST-4: it reminds, it never refuses).

Cost: ``budget.sh`` compares the transcript's mtime with ``<BRAIN_HOME>/budget/<session>.mark`` in bash builtins and
starts no Python while the mark is newer. Python sets the mark's mtime in the future: the next check is due in
``CHECK_S`` seconds (sooner as the budget nears), never again once every notice is given, every ``IDLE_S`` when
there is nothing to watch (an estimate recorded later is then found). Each run reads only the transcript's new bytes
(``<session>.json`` keeps the offsets, the context, the cost and the notices given); marks older than ``KEEP_DAYS``
are pruned. ``<session>.json`` is written by this Python only (bash reads the mark), through brain.stateio: a backup
beside it, an atomic write (~10 ms, once per check, not per tool call); one a newer brain wrote is left to it and its
mark set ``IDLE_S`` ahead, and an unreadable one is set aside and the watch starts afresh.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

from . import paths, stateio, transcript, usage

DIR = "budget"
STATE_V = 1  # <session>.json's v (brain.stateio: truth-local, one session's life)
STEPS = (80, 100)
MASTER_STEPS = (70, 80, 90, 100)  # a master's (ST-3)
CHILD_K = 22_000  # the context a child costs its master when the family gives too few starts to measure (16k-28k)
CHILD_MIN, CHILD_MAX = 4_000, 120_000
_START_RE = re.compile(r"__start_session$")
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
            "warned": {"context": [], "cost": []}, "starts": 0, "model": "", "kids": {}}


def _file(sid: str) -> Path:
    return state_dir() / f"{sid}.json"


def _load(sid: str) -> dict | None:
    """A session's state, read-only (nothing moved): a newer brain's read as it is; None without one."""
    st = stateio.load(_file(sid), known=STATE_V, aside=False)
    return st.data if st.status in ("ok", "newer") else None


def _save(st: stateio.State, state: dict, next_s: float) -> None:
    """The state (brain.stateio: a backup, then an atomic write), then the mark: line 1 the transcript bash compares
    it with; its mtime ``next_s`` from now. A newer brain that wrote the state since the load keeps it: the mark
    then waits :data:`IDLE_S`."""
    try:
        stateio.save(st, state, indent=None, sort_keys=False)
    except stateio.StateError:
        next_s = IDLE_S
    _mark(state["session"], state["transcript"], next_s)


def _mark(sid: str, transcript_path: str, next_s: float) -> None:
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)
    mark = d / f"{sid}.mark"
    mark.write_text(Path(transcript_path).as_posix() + "\n", encoding="utf-8", newline="\n")
    t = time.time() + next_s
    os.utime(mark, (t, t))


def _prune(keep_days: int = KEEP_DAYS) -> None:
    """The states older than ``keep_days``, with their mark, backup and set-aside copies."""
    limit = time.time() - keep_days * 86400
    try:
        with os.scandir(state_dir()) as it:
            for e in it:
                own = e.name.endswith(".json")
                if (own or e.name.endswith(".json" + stateio.BACKUP) or ".json" + stateio.ASIDE in e.name) \
                        and e.stat().st_mtime < limit:
                    os.remove(e.path)
                    mark = Path(e.path).with_suffix(".mark")
                    if own and mark.exists():
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
                if main:  # each block is in one record only: before the dedupe
                    _count_starts(state, msg.get("content"))
                if not mid or model == "<synthetic>" or mid in recent:
                    continue
                recent.append(mid)
                u = msg.get("usage") or {}
                part = transcript._usage_tokens(u)
                state["cost"] += usage.message_cost(part, model or "", u.get("speed") or "") or 0.0
                if main:
                    state["ctx"] = part["input"] + part["cache_read"] + part["cache_write"]
                    state["model"] = model or state.get("model") or ""
            elif t == "user" and main:
                _feed_user(state, rec)
    except OSError:
        pass
    del recent[:-_RECENT]


def _feed_user(state: dict, rec: dict) -> None:
    """A user record of the main transcript: a start_session call refused (its result an error), else one of the
    first user texts (the brief: its items, its context budget)."""
    content = (rec.get("message") or {}).get("content")
    if state.get("start_ids"):
        _refused_starts(state, content)
    if state["texts"] >= BRIEF_TEXTS or rec.get("isMeta") or "toolUseResult" in rec:
        return
    text = transcript._text_of(content)
    if not text.strip():
        return
    state["texts"] += 1
    if state["texts"] == 1:
        state["items"] = list(dict.fromkeys(usage._ID_RE.findall(text)))[:20]
    m = transcript._BUDGET_RE.search(text) if state["budget"] is None else None
    if m:
        state["budget"] = int(float(m.group(1).replace(",", "."))
                              * (1_000 if m.group(2).lower() == "k" else 1_000_000))


def _is_start(block) -> bool:
    return isinstance(block, dict) and block.get("type") == "tool_use" \
        and bool(_START_RE.search(str(block.get("name") or "")))


def _starts_a_child(block: dict) -> bool:
    """A start_session call that starts a session now: the owner asked for it (``initiation`` user_asked, or none) or
    it starts a proposal the owner told it to start (``proposal_id``); not a proposal card (``offer``,
    ``own_initiative``: nothing runs until the owner starts it; review of #34, finding 22)."""
    inp = block.get("input") if isinstance(block.get("input"), dict) else {}
    return bool(inp.get("proposal_id")) or inp.get("initiation") in ("user_asked", None)


def _count_starts(state: dict, content) -> None:
    """The start_session calls of an assistant record: one that starts a child counts (its id kept until its result
    says it was refused); a proposal only asks the app later whether a child came of it (``offers``)."""
    for b in content if isinstance(content, list) else []:
        if not _is_start(b):
            continue
        if _starts_a_child(b):
            state["starts"] = state.get("starts", 0) + 1
            state["start_ids"] = [*state.get("start_ids", []), str(b.get("id") or "")][-_RECENT:]
        else:
            state["offers"] = state.get("offers", 0) + 1


def _refused_starts(state: dict, content) -> None:
    """A start_session call whose result is an error (a guard denied it, the app refused it) started nothing."""
    ids = state["start_ids"]
    for b in content if isinstance(content, list) else []:
        if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error") and b.get("tool_use_id") in ids:
            ids.remove(b["tool_use_id"])
            state["starts"] = max(0, state.get("starts", 0) - 1)


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


# --- the master's watch ---

def is_master(state: dict) -> bool:
    return bool(state.get("starts") or state.get("kids"))


def steps_of(state: dict, what: str) -> tuple[int, ...]:
    return MASTER_STEPS if what == "context" and is_master(state) else STEPS


def children(state: dict) -> list[dict]:
    """The master's children from the app's files and the SessionStart events (brain.sessions): {host_id, session,
    name, title, live}; each one's context at first sight kept in ``state["kids"]`` (the family's measure)."""
    from . import sessions

    host = state.get("host_id") or ""
    if not host:
        return []
    starts, ends = sessions.ledger_events()
    tree = sessions.Tree(sessions.app_index(), starts, None, ends)
    key = tree.key_of(host)
    out = []
    for k in tree.children.get(key, []) if key else []:
        n = tree.nodes[k]
        sid = n.get("session") or ""
        out.append({"host_id": n.get("host_id") or "", "session": sid, "name": n.get("name") or "",
                    "title": n.get("title") or "", "source": n.get("source") or "",
                    "live": sessions.alive(n, ends), "ended": ends.get(sid, "")})
        state.setdefault("kids", {}).setdefault(n.get("host_id") or n.get("session") or k, state.get("ctx", 0))
    return out


def per_child(state: dict) -> tuple[int, bool]:
    """(the context one child costs this master, measured): its growth since the first child it saw over the
    children seen, from three children on; else :data:`CHILD_K`."""
    seen = list((state.get("kids") or {}).values())
    if len(seen) >= 3 and state.get("ctx", 0) > min(seen):
        k = int((state["ctx"] - min(seen)) / len(seen))
        if CHILD_MIN <= k <= CHILD_MAX:
            return k, True
    return CHILD_K, False


def wake_cost(state: dict) -> float | None:
    """One wake after the prompt cache expired: the whole context written again at the model's cache-write price."""
    ctx, model = state.get("ctx") or 0, state.get("model") or ""
    return usage.message_cost({"cache_write": ctx}, model) if ctx and model else None


def kid_state(kid: dict, rep: dict) -> str:
    """A child's state now: its transcript's tail (brain.sessions.state_of: running, asking, idle, stale); what its
    last report says it waits on while that report is still its state (its turn ended since, or it still asks); the
    report's turn only without a transcript here (review of #34, finding 52)."""
    from . import sessions

    node = {"session": kid.get("session") or "", "source": kid.get("source") or ""}
    now = sessions.state_of(node, {node["session"]: kid["ended"]} if kid.get("ended") else {})
    if rep.get("waits_on") and now in ("idle", "unknown", rep.get("turn")):
        return "waits on " + rep["waits_on"][:60]
    return now if now != "unknown" else rep.get("turn") or "live"


def handover_draft(kids: list[dict]) -> list[str]:
    """The draft hand-over note's lines: each live child with both ids, its items (from its report) and its state
    now (:func:`kid_state`)."""
    from . import sessions

    out = []
    for k in kids:
        if not k["live"]:
            continue
        rep = sessions.read_report(k["session"]) if k["session"] else {}
        items = ", ".join((rep.get("items") or [])[:3]) or "-"
        state = kid_state(k, rep)
        prs = ", ".join(f"#{p.get('number')}" for p in rep.get("prs") or [])
        out.append(f"- {k['name'] or k['title'][:40] or '-'}: app {k['host_id'] or '-'}, transcript "
                   f"{k['session'] or '-'}; items {items}; {state}" + (f"; PR {prs}" if prs else ""))
    return out


# --- the check ---

def measures(state: dict) -> dict[str, dict]:
    """{context|cost: {pct, used, budget}} for what has a budget: the brief's context budget, else a master's
    (brain.sessions.master_budget, kept in ``state["master_budget"]``)."""
    out = {}
    budget = state.get("budget") or (state.get("master_budget") if is_master(state) else None)
    if budget:
        out["context"] = {"used": state["ctx"], "budget": budget, "pct": 100.0 * state["ctx"] / budget,
                          "brief": bool(state.get("budget"))}
    est = sum((state.get("estimates") or {}).values())
    if est:
        used = state["cost"] + state.get("prior_usd", 0.0)
        out["cost"] = {"used": used, "budget": est, "pct": 100.0 * used / est}
    return out


def notices(state: dict) -> list[str]:
    """The notices due now (each step once per measure, none below one already given), marked as given."""
    out = []
    for what, m in measures(state).items():
        given = state["warned"].setdefault(what, [])
        top = max(given, default=0)
        due = [s for s in steps_of(state, what) if m["pct"] >= s and s not in given and s > top]
        if not due:
            continue
        given += due
        if what == "context" and is_master(state):
            out.append(master_text(max(due), m, state))
        else:
            out.append(text(what, max(due), m, state))
    return out


def master_text(step: int, m: dict, state: dict) -> str:
    """The master's notice at ``step`` (ST-3, ST-4): what to do, its live children, the room left, a wake's cost."""
    kids = state.get("_children") or []
    live = [k for k in kids if k["live"]]
    whose = "its brief's context budget" if m.get("brief") else "its budget (the model's window, usage.master_budget)"
    head = (f"Master's watch (ST-3): this master's context is {ktok(m['used'])} tokens, {m['pct']:.0f} % of {whose}, "
            f"{ktok(m['budget'])}; {len(live)} live child(ren) of {len(kids)} started.")
    wake = wake_cost(state)
    tail = (f" One wake after the prompt cache expired costs about {usage.usd(wake)} (the context written again): "
            "hand over before a long wait, not after." if wake else "")
    if step == 70:
        k, measured = per_child(state)
        room = max(0, int((0.8 * m["budget"] - m["used"]) / k))
        act = (f"Room before 80 %: about {room} more child(ren) at {ktok(k)} each "
               f"({'measured on this family' if measured else 'the default: the family gives too few starts yet'}). "
               "At 80 % start no new child, hand over to a fresh master and drain yours.")
    elif step == 80:
        draft = handover_draft(kids)
        act = ("Start no new child. Hand over to a fresh master (a new session with its own brief: the waves still to "
               "start) and drain yours: answer them, review and merge their PRs, archive them; ask the owner nothing "
               "new and touch no other master's children. Compact only once no child is alive. Draft hand-over note "
               "(the live children, both ids):\n" + ("\n".join(draft) if draft else "- no live child") + "\n")
    elif step == 90:
        act = ("Drain only: no new child, no new work; compact only once no child is alive"
               + (f" ({len(live)} still live)." if live else " (none is: compacting or handing over is safe now)."))
    else:
        act = ("Past the budget: drain what is live and hand over; a fresh master resumes from the hand-over note. "
               "Last notice for this budget.")
    return f"{head} {act}{tail} You decide; nothing stops or blocks the session (ST-4)."


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
    the brief's budget still come; never again once nothing is left to say (a start_session call makes the
    governor expire the mark: a session that becomes a master is checked again)."""
    ms = measures(state)
    live = [m["pct"] for w, m in ms.items() if max(state["warned"].get(w, []), default=0) < steps_of(state, w)[-1]]
    if live:
        top = max(live)
        return next((s for limit, s in CHECK_S if top < limit), CHECK_S[-1][1])
    waiting = (state.get("items") and "cost" not in ms) or (state.get("budget") is None
                                                            and state.get("texts", 0) < BRIEF_TEXTS)
    return IDLE_S if waiting or _proposed(state) else DONE_S


def _proposed(state: dict) -> bool:
    """A session that proposed a session (an offer, a proposal card) and has no child yet: the app is asked at each
    check whether the owner started one from it."""
    return bool(state.get("offers")) and not is_master(state)


def master_summary(state: dict) -> dict | None:
    """What the cockpit, brain alerts and the governor read of a master: {pct, step, live, started, budget}."""
    m = measures(state).get("context")
    if not is_master(state) or not m:
        return None
    kids = state.get("_children") or []
    return {"pct": round(m["pct"], 1), "step": max((s for s in MASTER_STEPS[:-1] if m["pct"] >= s), default=0),
            "live": sum(1 for k in kids if k["live"]), "started": len(kids), "budget": m["budget"],
            "host_id": state.get("host_id") or "", "at": time.time()}


def _watch_master(state: dict, data: dict, legacy: bool) -> None:
    """A master's children (``state["_children"]``, for this check only) and budget: its app id from the
    environment (when it is this session's: brain.sessions.host_for); the app asked once for a state kept from
    before the master's watch (``legacy``: judged before the new records are fed, which add ``starts``; review of
    #34, finding 53), and at each check for a session that proposed one (:func:`_proposed`)."""
    from . import sessions

    if not state.get("host_id") and not data.get("agent_id"):
        state["host_id"] = sessions.host_for(str(data.get("session_id") or ""))
    if not (is_master(state) or legacy or _proposed(state)):
        return
    state.setdefault("starts", 0)
    state["_children"] = children(state)
    if is_master(state) and not state.get("budget") and not state.get("master_budget"):
        state["master_budget"] = sessions.master_budget(str(data.get("cwd") or "."))


def check(data: dict) -> str:
    """The notices due for this session at this tool call ('' when none), the state and mark moved."""
    sid = str(data.get("session_id") or "")
    path = str(data.get("transcript_path") or "")
    if not _SID_RE.match(sid) or not path:
        return ""
    st = stateio.load(_file(sid), known=STATE_V)
    if not st.writable:   # a newer brain's watch (or a locked file): left to it; bash skips Python until the mark
        _mark(sid, path, IDLE_S)
        return ""
    state = st.data if st.status == "ok" and st.data else None
    if state is None:
        state = _new(sid, path)
        _prune()
    legacy = "starts" not in state  # kept from before the master's watch: before _feed adds the key
    state["transcript"] = path
    main = Path(path)
    _feed(state, main, True)
    for f in transcript.subagent_files(main):
        _feed(state, f, False)
    if state["items"] and not state["estimates"] and time.time() - state.get("resolved_at", 0) >= IDLE_S:
        state["estimates"] = estimates_of(str(data.get("cwd") or "."), state["items"])
        state["prior_usd"] = prior_cost(sid, list(state["estimates"]))
        state["resolved_at"] = time.time()
    _watch_master(state, data, legacy)
    # a subagent's call counts but is not told, and leaves the steps due to the main thread's next call: marked given
    # here, they would never be shown (review of #34, finding 25)
    out = [] if data.get("agent_id") else notices(state)
    state["master"] = master_summary(state)
    state.pop("_children", None)
    _save(st, state, next_check(state))
    return "\n".join(out)


def master_of(session: str) -> dict | None:
    """The master's summary the watch last kept for ``session`` (brain.governor, brain.alerts)."""
    state = _load(session) if _SID_RE.match(session or "") else None
    return (state or {}).get("master")


def expire(session: str) -> None:
    """Make the next tool call check now (the governor, at a start_session call: the session may be a master)."""
    mark = state_dir() / f"{session}.mark"
    try:
        if _SID_RE.match(session or "") and mark.exists():
            os.utime(mark, (0, 0))
    except OSError:
        pass


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

