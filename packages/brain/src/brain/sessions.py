"""The session tree: ``brain sessions [tree [ID] | show ID] [--json]`` (wi-brain-session-tree, wi-brain-child-report;
spec-brain-session-telemetry §3.1, §3.2 and §9.3; ST-1, ST-2). Standard library only, read-only, zero token.

A session has two ids, and they serve different tools: the transcript's (``CLAUDE_CODE_SESSION_ID``: the ledger, the
session records, the budget watch, the cockpit) and the desktop app's ``local_`` id (``CLAUDE_CODE_HOST_SESSION_ID``:
SendMessage and the app's session tools). Nothing linked them but a note written by hand; here both are read and
either resolves, as does the short name the app gives a session it started (``f1-session-tree``).

Where the tree comes from, the first that knows wins:

  the app     each session's metadata file (``%LOCALAPPDATA%/Claude-Data/*/claude-code-sessions/*/*/local_*.json``),
              read through a closed list of keys (:data:`APP_KEYS`): both ids, the parent (``spawnedFrom``), the
              task, the short name, the title, the dates, whether it is archived or detached (``lineageDetached``),
              the model, the effort, the branch and the number of its PRs. Never ``lastTurnReport``, ``pendingSystemReminder``,
              ``promptAppendSnapshot``, ``remoteMcpServersConfig``, ``spawnSeed`` or any other key: they hold texts
              and, in most files, an e-mail address. Each file is parsed once per change (its size and mtime), the
              picked keys cached in ``<BRAIN_HOME>/cache/sessions-app.json``; nothing here ever writes the app's files;
  the ledger  the SessionStart events (``capture.session_start``: both ids, and the parent, task and name the app's
              file held when the session started), so a machine keeps what it saw after the app forgets it;
  the briefs  the token ledger's brief hash (``usage.link_families``: a sub-session's first prompt is the task a
              start_session call wrote), the parent of a session the app never knew (a command-line session, another
              machine's ledger), read from the token ledger as ``brain usage`` last left it.

A session's role is computed, never stored: ``master`` (it started sessions), ``sub`` (a session started it),
``relay`` (both), ``solo``. Its state: ``archived`` (the app's), ``ended`` (its SessionEnd event), else the cockpit's
reading of its transcript's tail (``running``, ``asking``, ``idle``, ``stale``); ``live`` is any state but archived and
ended. ``show`` says what a message to it would meet before one is sent (18 of 70 messages went to sessions archived
since, §9.3).

The child's report (wi-brain-child-report): at the end of each turn the Stop hook writes
``<BRAIN_HOME>/sessions/<session>.report.json`` (:func:`write_report`): its PRs and the head of its branch, the items
and DDRs it names, whether it waits on someone (the wrap-up marked blocked, a question pending) and on what, what
comes next (the wrap-up's question, else the plan's next step), its recap. ``brain sessions tree`` prints it under
each child, so a master learns what its children did without paging their transcripts; ``show ID --report`` prints
the child's last final message in full, read from its transcript on demand and never stored.

A master's budget (:func:`budget_of`): its brief's context budget, else ``usage.master_budget`` in config.json, else
the model's window (:data:`MODEL_WINDOW`); a session that is not a master and has no brief has none.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from . import paths, secretscan, transcript

HOST_ENV = "CLAUDE_CODE_HOST_SESSION_ID"
SESSION_ENV = ("CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID")
APP_GLOB = "Claude-Data/*/claude-code-sessions/*/*"
# The closed list of keys read from an app's session file (spec §3.1, §3.7): {our name: its key}; spawnedFrom's own
# keys below. Every other key is never read, never copied.
APP_KEYS = {"host_id": "sessionId", "session": "cliSessionId", "title": "title", "created": "createdAt",
            "active": "lastActivityAt", "archived": "isArchived", "turns": "completedTurns", "model": "model",
            "effort": "effort", "branch": "branch", "detached": "lineageDetached"}
SPAWN_KEYS = {"parent": "sessionId", "task": "taskId", "name": "name", "side": "sideSession"}
HOST_RE = re.compile(r"^local_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
LOCAL_RE = re.compile(r"\blocal_[0-9a-f][0-9a-f-]{7,35}\b")
MODEL_WINDOW = 1_000_000  # a master without a brief: the model's window (892k reached without compaction, §3.2)
ROLES = ("master", "sub", "relay", "solo")
LIVE = ("running", "asking", "idle", "stale", "unknown")
REPORT_TEXT = 600  # the recap and the waits kept in a report, at most (characters)
_DDR_RE = re.compile(r"\bddr-\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*[a-z0-9]")
_ITEM_RE = re.compile(r"\bwi-[a-z0-9][a-z0-9-]*[a-z0-9]")
_PR_RE = re.compile(r"github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)")
WRAP_UP = "mcp__ccd_turn__wrap_up"


# --- this session ---

def here(env=None) -> dict:
    """This session's ids from its environment: {session, host_id}, each '' when unknown."""
    env = os.environ if env is None else env
    host = str(env.get(HOST_ENV) or "")
    return {"session": next((str(env[v]) for v in SESSION_ENV if env.get(v)), ""),
            "host_id": host if HOST_RE.match(host) else ""}


def stamp(env=None) -> dict:
    """The ids a record of this session carries (scale study gap 19): {host_id, machine} when the app's id is known,
    {} otherwise; the transcript's id is the record's own ``by`` or ``session``."""
    h = here(env)["host_id"]
    if not h:
        return {}
    from .timing import host
    return {"host_id": h, "machine": host()}


# --- the app's metadata, a closed list of keys ---

def app_dirs() -> list[Path]:
    base = os.environ.get("LOCALAPPDATA")
    return sorted(Path(base).glob(APP_GLOB)) if base else []


def pick(data: dict) -> dict:
    """The closed list of keys of an app's session file, renamed (:data:`APP_KEYS`, :data:`SPAWN_KEYS`)."""
    out = {ours: data.get(theirs) for ours, theirs in APP_KEYS.items() if data.get(theirs) not in (None, "")}
    sp = data.get("spawnedFrom")
    if isinstance(sp, dict):
        out.update({ours: sp.get(theirs) for ours, theirs in SPAWN_KEYS.items() if sp.get(theirs) not in (None, "")})
    prs = data.get("prs")
    if isinstance(prs, list):
        out["prs"] = len(prs)
    out["archived"] = bool(out.get("archived"))
    return {k: v for k, v in out.items() if isinstance(v, (str, int, float, bool))}


def app_file(host_id: str) -> Path | None:
    """The app's metadata file of one session, None when it is not on this machine."""
    if not HOST_RE.match(host_id or ""):
        return None
    return next((d / f"{host_id}.json" for d in app_dirs() if (d / f"{host_id}.json").is_file()), None)


def app_meta(host_id: str) -> dict:
    """One session's picked keys from its own app file (the SessionStart hook reads only this one), {} without it."""
    f = app_file(host_id)
    try:
        data = json.loads(f.read_text(encoding="utf-8")) if f else None
    except (OSError, ValueError):
        return {}
    return pick(data) if isinstance(data, dict) else {}


def _stat(f: Path) -> list | None:
    try:
        st = f.stat()
    except OSError:
        return None
    return [st.st_size, st.st_mtime_ns]


def _read_json(f: Path):
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_json(f: Path, data) -> None:
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, f)
    except OSError:
        pass


def _picked(f: Path, st: list, cache: dict) -> dict | None:
    """The cached picked keys of ``f`` while its stat is the same, else parsed again; None for a file to skip."""
    hit = cache.get(str(f))
    if isinstance(hit, dict) and hit.get("stat") == st:
        return hit
    data = _read_json(f)
    if not isinstance(data, dict) or not data.get("sessionId"):
        return None
    return {"stat": st, "meta": pick(data)}


def app_index() -> dict[str, dict] | None:
    """{host_id: picked keys} of every session the app has on this machine; None when the app is not here. A file is
    parsed again only when its size or mtime changed (``<BRAIN_HOME>/cache/sessions-app.json``)."""
    dirs = app_dirs()
    if not dirs:
        return None
    cache_f = paths.brain_home() / "cache" / "sessions-app.json"
    cache = _read_json(cache_f)
    cache = cache if isinstance(cache, dict) else {}
    fresh = {}
    for f in (f for d in dirs for f in sorted(d.glob("local_*.json"))):   # sorted: children started together keep
        # one order on every system (a directory lists in its own order on Linux)
        st = _stat(f)
        hit = _picked(f, st, cache) if st else None
        if hit:
            fresh[str(f)] = hit
    if fresh != cache:
        _write_json(cache_f, fresh)
    return {h["meta"]["host_id"]: h["meta"] for h in fresh.values() if h["meta"].get("host_id")}


# --- the ledger's SessionStart events ---

def _months(now: float, back: int = 2) -> list[str]:
    out = []
    t = datetime.fromtimestamp(now, timezone.utc)
    y, m = t.year, t.month
    for _ in range(back):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return sorted(out)


def _session_events(now: float):
    """The session events of this month's and last month's ledger, in order."""
    for month in _months(now):
        try:
            lines = (paths.ledger_dir() / f"events-{month}.jsonl").read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                ev = json.loads(line) if '"session_' in line else None
            except ValueError:
                continue
            if isinstance(ev, dict) and ev.get("session_id"):
                yield ev


def ledger_events(now: float | None = None) -> tuple[dict[str, dict], dict[str, str]]:
    """({session: what its SessionStart events recorded, merged}, {session: when it ended, unless resumed since})."""
    starts: dict[str, dict] = {}
    ends: dict[str, str] = {}
    for ev in _session_events(time.time() if now is None else now):
        sid, at = ev["session_id"], str(ev.get("at") or "")
        if ev.get("event") == "session_start":
            s = starts.setdefault(sid, {"session": sid, "started": at})
            s.update({k: ev[k] for k in ("host_id", "parent", "task", "name", "cwd") if ev.get(k)})
            if at >= ends.get(sid, ""):  # resumed after its end
                ends.pop(sid, None)
        elif ev.get("event") == "session_end":
            ends[sid] = max(at, ends.get(sid, ""))
    return starts, ends


# --- the tree ---

def _started_at(node: dict) -> float:
    """When a node started, in seconds since the epoch: the app's createdAt (milliseconds), else the ledger's
    SessionStart (ISO), else 0. One kind of number for every node: a family that mixes app and ledger-only children
    sorts (an int and a str never meet)."""
    created = node.get("created")
    if isinstance(created, (int, float)) and not isinstance(created, bool) and created:
        return created / 1000
    dt = transcript.parse_ts(str(node.get("started") or ""))
    if dt is None:
        return 0.0
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()


class Tree:
    """Every session the app, the ledger and the briefs know, by key (the app's id when known, else the
    transcript's), with the indexes that resolve an id or a name, and each one's parent and children."""

    def __init__(self, app: dict[str, dict] | None = None, starts: dict[str, dict] | None = None,
                 families: dict[str, str] | None = None, ends: dict[str, str] | None = None) -> None:
        self.app_seen = app is not None
        self.nodes: dict[str, dict] = {}
        self.by_session: dict[str, str] = {}
        self.ends = ends or {}
        for meta in (app or {}).values():
            self._add({**meta, "source": "app"})
        for sid, ev in (starts or {}).items():
            self._merge_start(sid, ev)
        for child, parent in (families or {}).items():  # the brief hash: transcript ids on both sides
            self._merge_family(child, parent)
        self.children: dict[str, list[str]] = {}
        for key, node in self.nodes.items():
            self._link(key, node)
        for kids in self.children.values():
            kids.sort(key=lambda k: _started_at(self.nodes[k]))

    def _add(self, node: dict) -> str:
        key = node.get("host_id") or node.get("session")
        self.nodes[key] = node
        if node.get("session"):
            self.by_session[node["session"]] = key
        return key

    def _merge_start(self, sid: str, ev: dict) -> None:
        """A SessionStart event: a node of its own, else what the app's file has forgotten (the file wins)."""
        key = self.by_session.get(sid) or ev.get("host_id") or sid
        node = self.nodes.get(key)
        if node is None:
            self._add({**ev, "source": "ledger"})
            return
        for k, v in ev.items():
            node.setdefault(k, v)
        self.by_session.setdefault(sid, key)

    def _merge_family(self, child: str, parent: str) -> None:
        """The brief hash's parent of ``child``, unless a better source gave one; either may be new."""
        key = self.by_session.get(child) or self._add({"session": child, "source": "briefs"})
        node = self.nodes[key]
        if node.get("parent"):
            return
        if parent not in self.by_session:
            self._add({"session": parent, "source": "briefs"})
        node["parent"], node["parent_source"] = self.by_session[parent], "briefs"

    def _link(self, key: str, node: dict) -> None:
        if not node.get("parent"):
            return
        p = self.key_of(node["parent"])
        if p == key:
            return
        node["parent_key"] = p or node["parent"]
        node.setdefault("parent_source", "app" if node.get("source") == "app" else "ledger")
        self.children.setdefault(node["parent_key"], []).append(key)

    def key_of(self, ref: str) -> str:
        """The node's key for an app id or a transcript id, '' when unknown."""
        if not ref:
            return ""
        if ref in self.nodes:
            return ref
        return self.by_session.get(ref, "")

    def resolve(self, ref: str) -> list[str]:
        """The sessions ``ref`` names: an app id (``local_`` optional, a prefix of 8 or more), a transcript id (a
        prefix of 8 or more) or a short name (exact, case ignored); an exact match wins."""
        ref = (ref or "").strip()
        exact = (self.key_of(ref) or self.key_of(f"local_{ref}")) if ref else ""
        if not ref or exact:
            return [exact] if exact else []
        low = ref.lower()
        named = [k for k, n in self.nodes.items() if str(n.get("name") or "").lower() == low]
        if named:
            return sorted(named, key=lambda k: -(self.nodes[k].get("active") or 0))
        bare = low.removeprefix("local_")
        return sorted({k for k, n in self.nodes.items() if _starts(n, bare)}) if len(bare) >= 8 else []

    def role(self, key: str) -> str:
        has_parent, has_kids = bool(self.nodes[key].get("parent")), bool(self.children.get(key))
        return "relay" if has_parent and has_kids else "master" if has_kids else "sub" if has_parent else "solo"

    def root(self, key: str) -> str:
        seen = {key}
        while True:
            p = self.nodes.get(key, {}).get("parent_key")
            if not p or p in seen or p not in self.nodes:
                return key
            seen.add(p)
            key = p

    def parent_name(self, key: str) -> str:
        p = self.nodes[key].get("parent_key") or ""
        n = self.nodes.get(p) or {}
        return str(n.get("name") or short(n.get("host_id") or n.get("session") or p))


def _starts(node: dict, prefix: str) -> bool:
    """The session's app id (without ``local_``) or transcript id starts with ``prefix``."""
    host = str(node.get("host_id") or "").removeprefix("local_")
    return host.startswith(prefix) or str(node.get("session") or "").startswith(prefix)


def short(ident: str) -> str:
    """An id as the cockpit shows it: ``local_`` and eight characters, or a transcript's first eight."""
    ident = str(ident or "")
    return ident[:14] if ident.startswith("local_") else ident[:8]


def load(now: float | None = None, briefs: bool = True) -> Tree:
    """The tree from the app, the ledger and (``briefs``) the token ledger's brief hash."""
    families = {}
    if briefs:
        from . import usage
        families = usage.link_families(list(usage.load().values()))
    starts, ends = ledger_events(now)
    return Tree(app_index(), starts, families, ends)


# --- a session's state, context and budget ---

def state_of(node: dict, ends: dict[str, str] | None = None, now: float | None = None) -> str:
    """archived, ended, else the state the cockpit reads in its transcript's tail; unknown without a transcript."""
    if node.get("archived"):
        return "archived"
    sid = node.get("session") or ""
    f = paths.find_transcript(sid) if sid else None
    if f is None:
        return "ended" if sid in (ends or {}) else "unknown"
    from . import cockpit
    now = time.time() if now is None else now
    try:
        mtime = f.stat().st_mtime
    except OSError:
        return "unknown"
    ended = (ends or {}).get(sid, "") >= transcript.iso(datetime.fromtimestamp(mtime - cockpit.END_SLACK_S,
                                                                              timezone.utc))
    if ended and node.get("source") == "app":  # its process ended, but the app resumes it on a message
        ended = False
    return cockpit.state(cockpit.turn(cockpit.tail(f)), max(0.0, now - mtime), ended)


def is_live(state: str) -> bool:
    return state in LIVE


def message_advice(state: str) -> str:
    """What a message sent now would meet (§9.3)."""
    return {"running": "live, working: a message waits in its queue until its turn ends",
            "asking": "live, waiting on the owner's answer: a message is read once the question is answered",
            "idle": "live, idle: a message starts its next turn",
            "stale": "live but silent for 15 minutes or more (a long command, a prompt, or a dead process)",
            "archived": "archived: a message would be lost; write to the session that took over, or unarchive it",
            "ended": "ended: a message would be lost",
            "unknown": "unknown on this machine (no transcript here): check its id"}.get(state, state)


def snapshot(session: str) -> dict:
    try:
        data = json.loads((paths.sessions_dir() / f"{session}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def watch_state(session: str) -> dict:
    """The budget watch's state of a session (``<BRAIN_HOME>/budget/<session>.json``: ctx, budget), {} without one."""
    try:
        data = json.loads((paths.brain_home() / "budget" / f"{session}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def master_budget(cwd: str | None = None) -> int:
    """``usage.master_budget`` in config.json (tokens), else :data:`MODEL_WINDOW`; read through the governor's cached
    settings, so a hook pays ~1 ms."""
    try:
        from . import governor
        value = governor.settings(cwd or ".").get("master_budget")
    except (Exception, SystemExit):  # a budget is never worth a failure: the default
        value = None
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 \
        else MODEL_WINDOW


def budget_of(brief_budget: int | None, role: str, cwd: str | None = None) -> int | None:
    """A session's context budget: its brief's; else, for a master or a relay, :func:`master_budget`; else None."""
    if brief_budget:
        return int(brief_budget)
    return master_budget(cwd) if role in ("master", "relay") else None


# --- the child's report ---

def report_file(session: str) -> Path:
    return paths.sessions_dir() / f"{session}.report.json"


def read_report(session: str) -> dict:
    try:
        data = json.loads(report_file(session).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _cut(text: str, n: int = REPORT_TEXT) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def last_wrap_up(records: list[dict]) -> dict:
    """The input of the last wrap-up call among ``records`` (recap, ask, blocked, actions), {} without one."""
    for r in reversed(records):
        if r.get("type") != "assistant":
            continue
        content = (r.get("message") or {}).get("content")
        for b in reversed(content if isinstance(content, list) else []):
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == WRAP_UP:
                return b.get("input") if isinstance(b.get("input"), dict) else {}
    return {}


def last_text(records: list[dict]) -> str:
    """The last final message of the session's turn: the text of its last assistant record that has one."""
    for r in reversed(records):
        if r.get("type") != "assistant":
            continue
        content = (r.get("message") or {}).get("content")
        parts = [b.get("text") or "" for b in content if isinstance(b, dict) and b.get("type") == "text"] \
            if isinstance(content, list) else [content] if isinstance(content, str) else []
        text = "\n".join(p for p in parts if p.strip())
        if text.strip():
            return text
    return ""


def _report_prs(sr: dict, final: str) -> list[dict]:
    """The session record's PRs, then the GitHub PR links its last message names."""
    prs = [{k: p[k] for k in ("repo", "number", "url", "state") if p.get(k)} for p in sr.get("prs") or []]
    numbers = {str(p.get("number")) for p in prs}
    for repo, num in _PR_RE.findall(final):
        if num not in numbers:
            prs.append({"repo": repo, "number": int(num)})
            numbers.add(num)
    return prs


def _waits(wrap: dict, turn_: str, plan_steps: list[dict]) -> tuple[bool, str, str]:
    """(blocked, what it waits on, what comes next): the wrap-up marked blocked or a question pending wait on
    someone; next is the wrap-up's question, else the plan's next step."""
    blocked = bool(wrap.get("blocked")) or turn_ == "asking"
    ask = str(wrap.get("ask") or "")
    if blocked:
        return True, ask or ("a question to the owner" if turn_ == "asking" else ""), ""
    pending = [s for s in plan_steps if s.get("status") != "completed"]
    return False, "", ask or (str(pending[0].get("content") or "") if pending else "")


def build_report(session: str, records: list[dict], sr: dict, meta: dict, plan_steps: list[dict] | None = None,
                 ddrs_pending: list[str] | None = None, head: str = "", at: str = "",
                 brief_items: list[str] | None = None) -> dict:
    """The child's report from what is already on disk (zero token): the last wrap-up, the SR, the session's own
    ids, its plan, its pending DDRs and the items its brief names (the budget watch's); texts cut to
    :data:`REPORT_TEXT` characters and secret-scanned."""
    from . import cockpit
    wrap, final, turn_ = last_wrap_up(records), last_text(records), cockpit.turn(records)
    plan_steps = plan_steps or []
    named = " ".join([str(wrap.get("recap") or ""), str(wrap.get("ask") or ""), final])
    blocked, waits, nxt = _waits(wrap, turn_, plan_steps)
    done = sum(1 for s in plan_steps if s.get("status") == "completed")
    rep = {"v": 1, "session": session, "at": at or transcript.iso(datetime.now(timezone.utc)),
           **{k: meta.get(k) for k in ("host_id", "parent", "name")}, "turn": turn_, "blocked": blocked,
           "branch": sr.get("branch"), "head": head, "prs": _report_prs(sr, final),
           "items": list(dict.fromkeys([*(brief_items or []), *(sr.get("items") or []),
                                        *_ITEM_RE.findall(named)]))[:20],
           "ddrs": list(dict.fromkeys([*(ddrs_pending or []), *_DDR_RE.findall(named)]))[:20],
           "waits_on": _cut(waits), "next": _cut(nxt), "recap": _cut(wrap.get("recap") or ""),
           "plan": f"{done}/{len(plan_steps)}" if plan_steps else ""}
    return secretscan.clean({k: v for k, v in rep.items() if v or k in ("turn", "blocked")})[0]

def write_report(session: str, report: dict) -> Path:
    d = paths.sessions_dir()
    d.mkdir(parents=True, exist_ok=True)
    f = report_file(session)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, f)
    return f


# --- the rows the commands and the cockpit show ---

def _context(sid: str, role: str) -> tuple[int | None, int | None, dict]:
    """(context used, its budget, the session record): the budget watch's state first (fresher while a turn goes on),
    else the session record's; the budget per :func:`budget_of`."""
    sr = snapshot(sid) if sid else {}
    ctx = sr.get("context") if isinstance(sr.get("context"), dict) else {}
    watch = watch_state(sid) if sid else {}
    return watch.get("ctx") or ctx.get("last"), budget_of(watch.get("budget") or ctx.get("budget"), role,
                                                           sr.get("folder")), sr


def row(tree: Tree, key: str, now: float | None = None, states: dict[str, str] | None = None) -> dict:
    """One session as ``brain sessions`` and the cockpit show it: both ids, name, title, role, parent, kids
    (live/started), state, context against its budget, and its report."""
    node, kids = tree.nodes[key], tree.children.get(key, [])
    states = _states(tree, [key, *kids], {} if states is None else states, now)
    role, sid = tree.role(key), node.get("session") or ""
    used, budget, sr = _context(sid, role)
    out = {k: node.get(k) or "" for k in ("host_id", "name", "parent", "parent_source", "task")}
    out.update({k: node.get(k) or sr.get(k) or "" for k in ("title", "model", "branch")})
    out.update({"key": key, "session": sid, "role": role, "state": states[key], "active": node.get("active") or 0,
                "parent_name": tree.parent_name(key) if out["parent"] else "",
                "kids_live": sum(1 for k in kids if is_live(states[k])), "kids": len(kids),
                "context": used, "budget": budget, "ctx_pct": _pct(used, budget)})
    rep = read_report(sid) if sid else {}
    return {**out, "report": rep} if rep else out


def _states(tree: Tree, keys: list[str], states: dict[str, str], now: float | None) -> dict[str, str]:
    """``states`` with the state of each of ``keys`` it lacks (a transcript's tail read once per command)."""
    for k in keys:
        if k not in states:
            states[k] = state_of(tree.nodes[k], tree.ends, now)
    return states


def _pct(used, budget) -> float | None:
    return round(100.0 * used / budget, 1) if used and budget else None

def kids_text(r: dict) -> str:
    return f"{r['kids_live']}/{r['kids']}" if r.get("kids") else "-"


def ctx_text(r: dict) -> str:
    return f"{r['ctx_pct']:.0f} %" if r.get("ctx_pct") is not None else "-"


def ids_text(r: dict) -> str:
    return f"{r['host_id'] or '(no app id)'} / {r['session'] or '(no transcript id)'}"


def report_lines(rep: dict, indent: str = "    ") -> list[str]:
    """A child's report in a few lines."""
    out = []
    head = []
    if rep.get("prs"):
        head.append("PR " + ", ".join(f"{(p.get('repo') or '').split('/')[-1]}#{p.get('number')}" for p in rep["prs"]))
    if rep.get("head"):
        head.append(f"head {rep['head']}")
    if rep.get("plan"):
        head.append(f"plan {rep['plan']}")
    if rep.get("items"):
        head.append("items " + ", ".join(rep["items"][:5]) + (" …" if len(rep["items"]) > 5 else ""))
    if rep.get("ddrs"):
        head.append("DDRs " + ", ".join(rep["ddrs"][:3]) + (" …" if len(rep["ddrs"]) > 3 else ""))
    if head:
        out.append(indent + "; ".join(head))
    if rep.get("waits_on"):
        out.append(f"{indent}waits on: {rep['waits_on']}")
    if rep.get("next"):
        out.append(f"{indent}next: {rep['next']}")
    if rep.get("recap"):
        out.append(f"{indent}recap ({str(rep.get('at') or '')[:16].replace('T', ' ')} UTC): {rep['recap']}")
    return out


def _has_live(tree: Tree, key: str, seen: set[str] | None = None) -> bool:
    """The session or one of its descendants is not archived (the app's flag: no transcript read)."""
    seen = seen or set()
    if not tree.nodes.get(key, {}).get("archived"):
        return True
    return any(_has_live(tree, k, seen | {key}) for k in tree.children.get(key, []) if k not in seen)


def tree_lines(tree: Tree, roots: list[str], now: float | None = None, reports: bool = True,
               archived: bool = False) -> list[str]:
    """The families under ``roots``, each child with its report; an archived branch with no live session is counted,
    not drawn, unless ``archived``."""
    states: dict[str, str] = {}
    out: list[str] = []

    def walk(key: str, depth: int, seen: set[str]) -> None:
        r = row(tree, key, now, states)
        pad = "  " * depth
        name = r["name"] or (r["title"][:40] if r["title"] else "")
        out.append(f"{pad}- {short(r['host_id']) or '-':<14} {short(r['session']) or '-':<8} {r['role']:<6} "
                   f"{r['state']:<8} ctx {ctx_text(r):>5} kids {kids_text(r):<5} {name}")
        if reports and r.get("report") and depth:
            out.extend(report_lines(r["report"], pad + "    "))
        hidden = 0
        for k in tree.children.get(key, []):
            if k in seen:
                continue
            if not archived and not _has_live(tree, k):
                hidden += 1
                continue
            walk(k, depth + 1, seen | {k})
        if hidden:
            out.append(f"{pad}  ({hidden} archived: --all shows them)")

    for k in roots:
        walk(k, 0, {k})
    return out


def families(tree: Tree, now: float | None = None, hours: float = 24.0) -> list[str]:
    """The roots of the families with a member active in the last ``hours`` and not archived, newest first."""
    now = time.time() if now is None else now
    floor = (now - hours * 3600) * 1000
    keep: dict[str, float] = {}
    for key, node in tree.nodes.items():
        if node.get("archived") or not (tree.children.get(key) or node.get("parent")):
            continue
        act = float(node.get("active") or 0)
        if act and act < floor:
            continue
        root = tree.root(key)
        keep[root] = max(keep.get(root, 0.0), act)
    return sorted(keep, key=lambda k: -keep[k])


def _numbers(r: dict) -> str:
    if not (r.get("context") and r.get("budget")):
        return ""
    return f" ({r['context']:,} of {r['budget']:,})".replace(",", " ")


def show_lines(tree: Tree, key: str, now: float | None = None) -> list[str]:
    """``brain sessions show``: one session, its ids, state and what a message would meet, its family, its report."""
    states: dict[str, str] = {}
    r = row(tree, key, now, states)
    out = [f"{r['name'] or r['title'] or short(r['host_id'] or r['session'])}",
           f"  ids       app {r['host_id'] or '(none)'}; transcript {r['session'] or '(none)'}",
           f"  title     {r['title'] or '-'}",
           f"  state     {r['state']}: {message_advice(r['state'])}",
           f"  role      {r['role']}" + (f"; task {r['task']}" if r["task"] else ""),
           f"  context   {ctx_text(r)}{_numbers(r)}"]
    p = tree.nodes.get(tree.nodes[key].get("parent_key") or "") or {}
    out += [f"  parent    {r['parent_name']} (app {p.get('host_id') or '-'}; transcript {p.get('session') or '-'}; "
            f"from {r['parent_source']})"] if r["parent"] else []
    kids = [row(tree, k, now, states) for k in tree.children.get(key, [])]
    out += [f"  children  {r['kids_live']} live of {r['kids']}"] if kids else []
    out += [f"    - {k['host_id'] or '-'} {short(k['session']) or '-':<8} {k['state']:<8} {k['name'] or k['title'][:50]}"
            for k in kids]
    out += ["  report", *report_lines(r["report"], "    ")] if r.get("report") else []
    return out


def full_report(session: str) -> str:
    """The session's last final message, in full, read from its transcript now (never stored)."""
    f = paths.find_transcript(session) if session else None
    if f is None:
        return ""
    from . import cockpit
    return last_text(cockpit.tail(f, 2 * 1024 * 1024))


# --- brain sessions [tree [ID] | show ID] ---

class SessionsError(Exception):
    pass


def resolve_one(tree: Tree, ref: str) -> str:
    """The one session ``ref`` names; SessionsError when none or several do."""
    hits = tree.resolve(ref)
    if not hits:
        raise SessionsError(f"{ref}: no session by that app id, transcript id or name on this machine")
    if len(hits) > 1:
        raise SessionsError(f"{ref} names {len(hits)} sessions: "
                            + ", ".join(short(tree.nodes[k].get("host_id") or k) for k in hits[:8]))
    return hits[0]


def last_seen(node: dict) -> float:
    """When the session was last active (ms): the app's last activity, else its SessionStart event."""
    if node.get("active"):
        return float(node["active"])
    started = transcript.parse_ts(str(node.get("started") or "")) if node.get("started") else None
    return started.timestamp() * 1000 if started else 0.0


def recent_rows(tree: Tree, hours: float, every: bool = False, now: float | None = None) -> list[dict]:
    """The rows of the sessions active in the last ``hours`` and not archived (``every``: all of them), newest first."""
    now = time.time() if now is None else now
    floor = (now - hours * 3600) * 1000
    keys = [k for k, n in tree.nodes.items() if every or last_seen(n) >= floor]
    rows = sorted((row(tree, k, now) for k in keys), key=lambda r: -last_seen(tree.nodes[r["key"]]))
    return rows if every else [r for r in rows if r["state"] != "archived"]


def list_lines(rows: list[dict], hours: float) -> list[str]:
    if not rows:
        return [f"no session active in the last {hours:g} h (--all: every session)"]
    out = [f"{'app id':<14} {'transcr.':<8} {'role':<6} {'state':<8} {'ctx':>5} {'kids':<5} {'parent':<20} name | title"]
    out += [f"{short(r['host_id']) or '-':<14} {short(r['session']) or '-':<8} {r['role']:<6} {r['state']:<8} "
            f"{ctx_text(r):>5} {kids_text(r):<5} {r['parent_name'][:20] or '-':<20} {r['name'] or '-'} | {r['title'][:60]}"
            for r in rows]
    return out


def family_json(tree: Tree, key: str, seen: set[str] | None = None) -> dict:
    seen = (seen or set()) | {key}
    r = row(tree, key)
    r["children"] = [family_json(tree, c, seen) for c in tree.children.get(key, []) if c not in seen]
    return r


def message_lines(text: str) -> list[str]:
    return ["  last message", *(["    " + line for line in text.splitlines()] if text else ["    (none on this machine)"])]


def main(action: str, ref: str = "", hours: float = 24.0, every: bool = False, briefs: bool = True,
         as_json: bool = False, report: bool = False) -> str:
    """What ``brain sessions`` prints; SessionsError for a ref that names no session or several."""
    tree = load(briefs=briefs)
    key = resolve_one(tree, ref) if ref else ""
    if action == "show":
        r = row(tree, key)
        if as_json:
            r["children"] = [row(tree, k) for k in tree.children.get(key, [])]
            r.update({"last_message": full_report(r["session"])} if report else {})
            return json.dumps(r, indent=2, ensure_ascii=False)
        return "\n".join([*show_lines(tree, key), *(message_lines(full_report(r["session"])) if report else [])])
    if action == "tree":
        roots = [tree.root(key)] if key else families(tree, hours=1e9 if every else hours)
        if as_json:
            return json.dumps([family_json(tree, k) for k in roots], indent=2, ensure_ascii=False)
        lines = tree_lines(tree, roots, archived=every)
        return "\n".join(lines) or f"no family with a member active in the last {hours:g} h (--all: every family)"
    rows = recent_rows(tree, hours, every)
    return json.dumps(rows, indent=2, ensure_ascii=False) if as_json else "\n".join(list_lines(rows, hours))


# --- brain check: an app id that matches no session (scale study gap 19) ---

STAMPS = ("asked", "answer", "read", "applied", "archived")


def _stamped_ids(d: dict):
    """(where, the stamp, a local_ id it names) for each app id a DDR's stamps carry."""
    for where in STAMPS:
        st = d.get(where)
        if isinstance(st, dict):
            ids = (str(st.get(k) or "") for k in ("host_id", "by", "session"))
            for ident in dict.fromkeys(i for i in ids if i.startswith("local_")):
                yield where, st, ident


def unknown_ids(ddrs: list[tuple[Path, dict]], tree: Tree | None = None) -> tuple[list[str], list[str]]:
    """(refusals, warnings) for the ``local_`` ids the DDRs carry: a stamp written on this machine (its ``machine``)
    whose app id matches no session the app or the ledger knows is refused, as is one that is not an app id at all;
    one written elsewhere, or before stamps named their machine, is a warning only when the app is on this machine.
    Nothing when neither knows a session."""
    from .timing import host
    tree = tree or Tree(app_index(), ledger_events()[0])
    if not tree.app_seen and not tree.nodes:
        return [], []
    me = host()
    known = {n.get("host_id") for n in tree.nodes.values() if n.get("host_id")}
    refused, warned = [], []
    for f, d in ddrs:
        for where, st, ident in _stamped_ids(d):
            if ident in known:
                continue
            line = f"{d.get('id') or f.name}: {where} names {ident}, which matches no session"
            if not HOST_RE.match(ident):
                refused.append(f"{line} (not an app id: local_ and a UUID)")
            elif st.get("machine") == me:
                refused.append(f"{line} on {me}")
            elif tree.app_seen:
                warned.append(f"{line} here" + (f" (stamped on {st['machine']})" if st.get("machine") else ""))
    return refused, warned
