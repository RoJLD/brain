"""The owner's queue: ``brain queue [--project P | --all] [--kind K]... [--days N] [--json]``, ``brain queue add``,
``brain queue done`` (wi-brain-human-queue; spec 2026-11-01 context engine, section 4). The owner is config.json's
``identity.owner`` (brain.config); the views name them.

One list of what waits on the owner, in three kinds:

- ``decision``: a choice. A pending DDR of kind decision, an item's open question (``props.open``), an unanswered
  question of a spec, a spec still proposed;
- ``action``: what only the owner may do, always. A pending DDR of kind action, an item whose ``owner`` prop names
  the owner, and any entry whose text falls in one of the ``OWNER_ONLY`` categories (keys, money, arming, visibility,
  accounts, scheduled tasks or services, legal reading): an item's open question that asks the owner to rotate a
  password is an action;
- ``permission``: what an agent could do but a permission stopped. A denied tool call of the last ``--days`` days in
  the transcripts, a pending DDR of kind permission, an item prop that names the owner's approval. The owner grants a
  narrow allow rule (wi-brain-permission-grants) and the task goes back to the agent, or does it once themself.

The kind is computed, never asked: a permission or a question whose text falls in an ``OWNER_ONLY`` category is an
action, never granted by an allow rule. The categories carry out the rules' "<owner> decides" lists (config.json's
``rules``, and "<owner> decides" or "<owner>'s alone" in the project's ``CLAUDE.md``; "the owner" is read too): a term
of those lists that no category names is reported as uncovered, so a new term in the rules shows until a category
detects it.

Sources, all read at zero token: ``records/ddr``; the store's nodes and edges (PyYAML); ``research_graph pending``
for the spec questions (the project's venv, skipped by ``--no-graph``); the transcripts (``~/.claude/projects``, files
changed in the window); the ledger (``$BRAIN_HOME/ledger``): the core plugin's guard refusals are counted, not queued
(their reason tells the agent its own fix: a worktree, no attribution line, no secret), but those of the owner and
power guards are actions, with their exact command, folder and ref (``guard-...``) until ``brain queue add --guard
REF`` writes the DDR that carries them (its ``guard`` and ``command``: the cockpit's Apply); ``brain queue done``
stamps a denial or a guard refusal there (``queue-<month>.jsonl``) until it is denied again. A denial is also gone
when the same session later ran the same call without an error (the permission was granted). The owner's own refusals
("doesn't want to proceed") are their answer already: not queued.

Each entry says what it unblocks: the open items it is attached to (a DDR's ``links``, the items whose props name it,
the items of its specs when it names none; the item a denial's worktree is named after) and every open item or
pending milestone
downstream of them (``depends_on``, ``part_of``). The queue is sorted by that count, then blocking first, then oldest.

``build`` is the data function the TUI's panel calls (wi-brain-tui-cockpit); ``collect`` builds several projects with
one transcript scan and returns the denials outside any registered project too.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from functools import lru_cache

from . import actions, config, decisions, graph, guards, paths, permissions, records, resume, secretscan

KINDS = decisions.KINDS
DAYS = 7
OPEN = {"WorkItem": {"todo", "doing", "blocked"}, "Milestone": {"pending"}, "Spec": {"proposed", "active"}}
ITEM_TYPES = ("WorkItem", "Milestone")
OUTSIDE = "(other folders)"

# What only the owner may do: brain.permissions' never-grantable categories (keys, money, arming, visibility,
# accounts, scheduled tasks or services, legal reading), extended by the personal brain's permissions.yaml (never:).
OWNER_ONLY = permissions.NEVER
_PERMISSION_RE = re.compile(r"(?i)\bpermissions?\b|\ballow(?:ed)? rules?\b|\bapprov|\bgrant|\bgo-ahead\b|\brestart")
_PROPS = ("open", "owner", "external_blocker", "needs", "external_note")
_WORKTREE_RE = re.compile(r"[\\/]worktrees[\\/]([^\\/]+)")
_APPLY_RE = re.compile(r"^\s*(?:brain|(?:\.[\\/])?install\.ps1)(?:\s|$)", re.I)  # what the owner's Apply runs

# Denied tool calls, as the tool result's text says it (Claude Code 2.1.3xx, 2026-11-02).
_DENIALS = (
    ("auto-mode classifier", re.compile(r"^Permission for this action was denied by the Claude Code auto mode "
                                        r"classifier\. Reason: (.+?)(?:\. If you have|\s*$)", re.S)),
    ("safety check", re.compile(r"^Permission for this command was denied by a built-in Claude Code safety check")),
    ("permission rule", re.compile(r"^Permission to use (.{1,300}?) has been denied", re.S)),
)
GUARD_REQUESTS = ("owner", "power")   # the guards whose refusals are the owner's actions, with the exact command
_MARKERS = (b"Permission for this", b"Permission to use")


class QueueError(Exception):
    pass


def _short(text, n: int = 160) -> str:
    return decisions._short(text, n)


def _cut(line: str, n: int) -> str:
    return line if len(line) <= n else line[: n - 1] + "…"


def _date_in(*texts) -> str:
    """The first YYYY-MM-DD in the texts, else ''."""
    for t in texts:
        m = re.search(r"\b20\d\d-\d\d-\d\d\b", str(t or ""))
        if m:
            return m.group(0)
    return ""


def _days(since: str, today: date) -> int | None:
    try:
        return (today - date.fromisoformat(str(since)[:10])).days
    except ValueError:
        return None


# --- the rules' "<owner> decides" lists and the categories ---

@dataclass(frozen=True)
class Owner:
    """The owner's name and the patterns that find it: "<owner> decides:" / "<owner>'s alone:" lists (or "the
    owner"), the name, and "(<owner>, 2026-10-29)", who said something rather than who waits."""
    name: str
    lists: re.Pattern
    named: re.Pattern
    attribution: re.Pattern


@lru_cache(maxsize=8)
def owner_patterns(name: str) -> Owner:
    who = rf"(?:{re.escape(name)}|the owner)"
    return Owner(name, re.compile(rf"(?i)\b(?:{who} decides|{who}'s alone)\W{{0,3}}:\s*(.*)"),
                 re.compile(rf"\b{re.escape(name)}\b"),
                 re.compile(rf"\(?\b{re.escape(name)},? 20\d\d-\d\d-\d\d\)?"))


def _owner(owner: str | None = None) -> Owner:
    return owner_patterns(owner or config.owner_of())


def guard_mark() -> str:
    """How the core plugin's guards sign a refusal (brain.guards): ``<plugin> guard:``, the plugin of config.json's
    adapters.claude."""
    return f"{config.claude(config.load())['plugin']} guard:"


def owner_only(text: str) -> str:
    """The first never-grantable category ``text`` falls in (brain.permissions: ``OWNER_ONLY`` and permissions.yaml's
    never), else ''."""
    return permissions.never_category(text)


def _list_terms(text: str, owner: str | None = None) -> list[str]:
    """The terms of each "<owner> decides:" / "<owner>'s alone:" list: the rest of its line and its indented
    continuation, without parentheses, split on commas, 'and' and 'or'."""
    out = []
    lines = text.splitlines()
    pats = _owner(owner)
    for i, line in enumerate(lines):
        m = pats.lists.search(line)
        if not m:
            continue
        body = [m.group(1)]
        for nxt in lines[i + 1:]:
            if not nxt.startswith("  ") or nxt.lstrip().startswith(("- ", "* ")):
                break
            body.append(nxt.strip())
        flat = re.sub(r"\([^)]*\)", "", " ".join(body)).split(". ")[0]
        out += [t.strip(" .*") for t in re.split(r",|\band\b|\bor\b", flat) if t.strip(" .*")]
    return out


def rules(project=None, owner: str | None = None) -> dict:
    """The rules' lists of what the owner decides (config.json's ``rules``, then the project's CLAUDE.md), and the
    terms no category names (``uncovered``)."""
    cfg = config.load()
    owner = owner or config.owner(cfg)
    files = config.rules_files(cfg) + ([project.root / "CLAUDE.md"] if project is not None else [])
    terms, read = [], []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        read.append(f.as_posix())
        terms += [t for t in _list_terms(text, owner) if t not in terms]
    cats = permissions.default_categories()
    uncovered = [t for t in terms if not any(c.names and c.names.search(t) for c in cats)]
    return {"files": read, "terms": terms, "uncovered": uncovered, "categories": [c.name for c in cats]}


# --- the graph: open items and what waits on them ---

@dataclass
class Graph:
    nodes: dict = field(default_factory=dict)
    down: dict = field(default_factory=dict)  # node -> the nodes that wait on it (depends_on, part_of)
    by_spec: dict = field(default_factory=dict)  # spec -> the nodes it specifies
    text: dict = field(default_factory=dict)  # open node -> its props as text (who names a DDR id)

    def is_open(self, nid: str) -> bool:
        n = self.nodes.get(nid) or {}
        return n.get("status") in OPEN.get(n.get("type"), ())

    def mentioning(self, ref: str) -> set[str]:
        return {nid for nid, t in self.text.items() if ref in t}

    def unblocks(self, attached) -> list[str]:
        """The open items and pending milestones among ``attached`` and downstream of them."""
        seen: set[str] = set()
        stack = [a for a in attached if self.is_open(a)]
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            stack += [y for y in self.down.get(x, ()) if y not in seen and self.is_open(y)]
        return sorted(n for n in seen if self.nodes[n].get("type") in ITEM_TYPES)


def load_graph(store: Path | None) -> Graph:
    g = Graph()
    if store is None or not (store / "nodes").is_dir():
        return g
    g.nodes = resume._nodes(store)  # libyaml's loader when there is one: a large store loads faster
    for e in resume._edges(store):
        src, dst, kind = str(e.get("from")), str(e.get("to")), e.get("type")
        if kind == "depends_on":
            g.down.setdefault(dst, set()).add(src)
        elif kind == "part_of":
            g.down.setdefault(src, set()).add(dst)
        elif kind == "specified_by":
            g.by_spec.setdefault(dst, set()).add(src)
    g.text = {nid: json.dumps(n.get("props") or {}, ensure_ascii=False) for nid, n in g.nodes.items()
              if g.is_open(nid)}
    return g


# --- entries ---

def _entry(kind: str, source: str, eid: str, title: str, *, since: str, today: date, g: Graph, attached=(),
           **extra) -> dict:
    unblocked = g.unblocks(attached)
    e = {"id": eid, "kind": kind, "source": source, "title": " ".join(str(title).split()), "since": since[:10],
         "age_days": _days(since, today), "blocking": False, "unblocks": len(unblocked), "unblocked": unblocked}
    e.update({k: v for k, v in extra.items() if v not in (None, "", [])})
    return e


def _ddr_entries(project, g: Graph, kinds, today: date) -> list[dict]:
    if not (project.root / records.RECORDS_DIR / "ddr").is_dir():
        return []
    out = []
    for _, d in decisions.load(project.root):
        kind = decisions.kind_of(d)
        if d.get("status") != "pending" or kind not in kinds:
            continue
        links = d.get("links") or {}
        attached = set(links.get("items") or []) | g.mentioning(d["id"])
        for s in links.get("specs") or [] if not attached else []:
            attached |= g.by_spec.get(s, set())
        rec = (d.get("recommendation") or {}).get("option")
        how = (f"brain decision answer {d['id']} <option>" if kind == "decision" else
               f"brain queue apply {d['id']} (or the cockpit's A): shows {d['command']}, runs it once "
               f"{config.owner_of()} confirms, then marks it done" if kind == "action" and d.get("command") else
               f"do it, then brain queue done {d['id']}" if kind == "action" else
               f"grant a narrow allow rule or do it once, then brain queue done {d['id']}")
        e = _entry(kind, "ddr", d["id"], d.get("title", ""), since=str((d.get("asked") or {}).get("at", "")),
                   today=today, g=g, attached=attached, detail=" ".join(str(d.get("question", "")).split()),
                   recommended=rec, how=how, due=d.get("due"), command=d.get("command"), guard=d.get("guard"))
        e["blocking"] = bool(d.get("blocking"))
        out.append(e)
    return out


def _prop_kind(prop: str, value: str, owner: Owner) -> str:
    """The kind of an item prop that waits on the owner, '' when it does not."""
    if prop == "owner":
        return "action" if owner.named.search(value) else ""
    if owner_only(value):
        return "action"
    if prop == "open":
        return "decision"
    if not owner.named.search(owner.attribution.sub("", value)):
        return ""
    return "permission" if _PERMISSION_RE.search(value) else "action"


def _prop_entries(g: Graph, kinds, today: date, owner: Owner) -> list[dict]:
    out = []
    for nid, n in sorted(g.nodes.items()):
        if not g.is_open(nid):
            continue
        props = n.get("props") or {}
        for prop in _PROPS:
            value = " ".join(str(props.get(prop) or "").split())
            kind = _prop_kind(prop, value, owner) if value else ""
            if kind not in kinds:
                continue
            text = n.get("title", "") if prop == "owner" else value
            category = owner_only(text) or ("owner" if prop == "owner" else "")
            how = ("answer it; the model records it on the item (brain decision ask, or the item's props)"
                   if kind == "decision" else f"once done, the model clears it: brain item set {nid} {prop}=")
            if prop == "owner":
                how = f"do it, then the model closes it: brain item close {nid}"
            attached = [nid, *g.by_spec.get(nid, ())]  # a spec's open question waits on the items it specifies
            out.append(_entry(kind, f"prop:{prop}", f"{nid}:{prop}", text, since=_date_in(value, props.get("idea")),
                              today=today, g=g, attached=attached, item=nid, category=category if kind == "action"
                              else "", how=how))
    return out


def _spec_entries(project, store: Path, g: Graph, today: date) -> tuple[list[dict], str]:
    """The unanswered spec questions and the specs still proposed, from research_graph pending."""
    data = graph.research_graph_json(project.root, store, "pending")
    if not isinstance(data, dict):
        return [], "research_graph pending did not run: spec questions not listed"
    out = []
    for s in data.get("spec_questions") or []:
        for q in s.get("questions") or []:
            out.append(_entry("decision", "spec", f"{s['id']}:{q['label']}", q.get("question", ""),
                              since=str(s.get("date") or ""), today=today, g=g, attached=g.by_spec.get(s["id"], ()),
                              detail=q.get("section"),
                              how=f"answer in the spec's decisions section ({s.get('anchor')})"))
    for s in data.get("proposed_specs") or []:
        out.append(_entry("decision", "spec", f"{s['id']}:validate", f"validate the spec: {s.get('title', '')}",
                          since=str(s.get("date") or ""), today=today, g=g, attached=g.by_spec.get(s["id"], ()),
                          how=f"validate it (props.validated) or ask for changes ({s.get('anchor')})"))
    return out, ""


# --- denied tool calls: transcripts and ledger ---

def _call_key(name: str, inp) -> str:
    inp = inp if isinstance(inp, dict) else {}
    for k in ("command", "file_path", "notebook_path", "url", "path"):
        if inp.get(k):
            return f"{name}: {inp[k]}"
    return f"{name}: {json.dumps(inp, sort_keys=True, ensure_ascii=False)}"


def _result_text(block: dict) -> str:
    t = block.get("content")
    if isinstance(t, list):
        t = "\n".join(x.get("text", "") for x in t if isinstance(x, dict))
    t = str(t or "").strip()
    for prefix in ("<tool_use_error>", "Error: "):
        if t.startswith(prefix):
            t = t[len(prefix):]
    return t


def _denial(text: str) -> tuple[str, str] | None:
    """(via, reason) when a tool result's text is a permission denial, else None."""
    for via, rx in _DENIALS:
        m = rx.search(text)
        if m:
            return via, " ".join((m.group(1) if m.groups() else via).split()).strip("[]")
    return None


def _scan_file(f: Path, since: str) -> list[dict]:
    """The denials of one transcript at or after ``since`` (ISO), each resolved or not. A refusal of the core
    plugin's guards is not one: the ledger counts those."""
    mark = guard_mark()
    found: dict[str, dict] = {}
    errors: set[str] = set()
    with open(f, "rb") as fh:
        for raw in fh:
            if b'"is_error":true' not in raw and b'"is_error": true' not in raw:
                continue
            try:
                rec = json.loads(raw)
            except ValueError:
                continue
            content = (rec.get("message") or {}).get("content") if isinstance(rec, dict) else None
            for b in content if isinstance(content, list) else []:
                if not (isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error")):
                    continue
                errors.add(str(b.get("tool_use_id")))
                if not any(m in raw for m in _MARKERS) or str(rec.get("timestamp", "")) < since:
                    continue
                text = _result_text(b)
                hit = None if mark in text[:200] else _denial(text)
                if hit:
                    found[str(b.get("tool_use_id"))] = {
                        "via": hit[0], "reason": hit[1], "at": str(rec.get("timestamp", ""))[:19] + "Z",
                        "session": rec.get("sessionId") or "", "cwd": rec.get("cwd") or "",
                        "branch": rec.get("gitBranch") or ""}
    if not found:
        return []
    calls = []
    with open(f, "rb") as fh:
        for raw in fh:
            if b'"tool_use"' not in raw:
                continue
            try:
                rec = json.loads(raw)
            except ValueError:
                continue
            content = (rec.get("message") or {}).get("content") if isinstance(rec, dict) else None
            for b in content if isinstance(content, list) else []:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    calls.append((str(rec.get("timestamp", "")), str(b.get("id")), b.get("name") or "?",
                                  b.get("input")))
    by_id = {c[1]: c for c in calls}
    out = []
    for tuid, d in found.items():
        call = by_id.get(tuid)
        if call is None:
            continue
        key = _call_key(call[2], call[3])
        d["tool"], d["key"] = call[2], key
        d["resolved"] = any(c[0] > call[0] and c[1] not in errors and _call_key(c[2], c[3]) == key for c in calls)
        out.append(d)
    return out


def _ledger_guards(since: str = "") -> list[dict]:
    rows = []
    for f in sorted(paths.ledger_dir().glob("guards-*.jsonl")):
        if f.stem[7:] < since[:7]:
            continue
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("decision") == "denied" and str(r.get("at", "")) >= since:
                rows.append(r)
    return rows


def done_stamps() -> dict[str, str]:
    """id -> time of the last ``brain queue done`` of a denial (``<BRAIN_HOME>/ledger/queue-<month>.jsonl``)."""
    out: dict[str, str] = {}
    for f in sorted(paths.ledger_dir().glob("queue-*.jsonl")):
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("event") == "queue-done" and r.get("id"):
                out[r["id"]] = max(out.get(r["id"], ""), str(r.get("at", "")))
    return out


def scan(days: int = DAYS, today: date | None = None, projects_dir: Path | None = None) -> dict:
    """The denied tool calls of the last ``days`` days in the transcripts, grouped by call (tool and input) with their
    occurrences, minus the resolved ones; and the guard refusals of the ledger (``guards``)."""
    today = today or date.today()
    since = (today - timedelta(days=days)).isoformat()
    start = datetime.combine(today - timedelta(days=days), datetime.min.time(), timezone.utc).timestamp()
    base = projects_dir or paths.projects_dir()
    occurrences = []
    if base.is_dir():
        for f in sorted(base.rglob("*.jsonl")):
            try:
                if f.stat().st_mtime >= start:
                    occurrences += _scan_file(f, since)
            except OSError:
                continue
    stamps = done_stamps()
    groups: dict[str, dict] = {}
    for o in sorted(occurrences, key=lambda o: o["at"]):
        gid = "perm-" + hashlib.sha1(o["key"].encode("utf-8")).hexdigest()[:10]
        g = groups.setdefault(gid, {"id": gid, "tool": o["tool"], "call": o["key"], "occurrences": []})
        g["occurrences"].append(o)
    denials = []
    for g in groups.values():
        live = [o for o in g["occurrences"] if not o["resolved"] and o["at"] > stamps.get(g["id"], "")]
        if not live:
            continue
        last = live[-1]
        call, _ = secretscan.clean_text(g["call"])
        denials.append({"id": g["id"], "tool": g["tool"], "call": call, "via": last["via"], "reason": last["reason"],
                        "first": live[0]["at"], "last": last["at"], "count": len(live),
                        "sessions": sorted({o["session"] for o in live if o["session"]}),
                        "cwds": sorted({o["cwd"] for o in live if o["cwd"]}),
                        "branches": sorted({o["branch"] for o in live if o["branch"]})})
    guards, requests = [], {}
    for r in _ledger_guards(since):
        req = r.get("request") if r.get("guard") in GUARD_REQUESTS else None
        if isinstance(req, dict) and req.get("ref"):
            requests.setdefault(req["ref"], []).append(r)
        else:
            guards.append(r)
    for ref, rows in requests.items():
        live = [r for r in rows if str(r.get("at", "")) > stamps.get(ref, "")]
        if not live:
            continue
        req = live[-1]["request"]
        denials.append({"id": ref, "tool": live[-1].get("tool"), "call": req.get("command") or req.get("what", ""),
                        "via": f"guard {live[-1]['guard']}", "reason": live[-1].get("reason", ""),
                        "first": live[0]["at"], "last": live[-1]["at"], "count": len(live),
                        "sessions": sorted({r["session_id"] for r in live if r.get("session_id")}),
                        "cwds": sorted({str(r["cwd"]) for r in live if r.get("cwd")}), "branches": [],
                        "guard": live[-1]["guard"], "category": req.get("category", ""), "request": req})
    return {"since": since, "denials": denials, "guards": guards}


def guard_request(ref: str) -> tuple[dict, dict]:
    """(the ledger row, its request) of the last refusal of the owner or power guard whose ref is ``ref``."""
    for r in reversed(_ledger_guards()):
        req = r.get("request")
        if r.get("guard") in GUARD_REQUESTS and isinstance(req, dict) and req.get("ref") == ref:
            return r, req
    raise QueueError(f"no refusal {ref} of the owner or power guard in {paths.ledger_dir().as_posix()}/guards-*.jsonl")


# --- denials -> projects and items ---

def _norm(p) -> str:
    return os.path.normcase(os.path.normpath(str(p)))


class Placer:
    """The registered project a folder belongs to: under its root (worktrees under .claude/worktrees included), else
    the project whose root is the folder's main checkout (a worktree elsewhere)."""

    def __init__(self, projects_list):
        roots = {(_norm(p.root), p.name) for p in projects_list}
        for p in projects_list:  # a registry read in a worktree resolves "root: ." to the worktree
            main = paths.main_checkout(p.root) if p.root.is_dir() else None
            if main:
                roots.add((_norm(main), p.name))
        self.roots = sorted(roots, key=lambda r: -len(r[0]))
        self.cache: dict[str, str] = {}

    def __call__(self, cwd: str) -> str:
        if cwd in self.cache:
            return self.cache[cwd]
        name = self._under(_norm(cwd))
        if not name and Path(cwd).is_dir():
            main = paths.main_checkout(cwd)
            name = self._under(_norm(main)) if main else ""
        self.cache[cwd] = name
        return name

    def _under(self, c: str) -> str:
        for root, name in self.roots:
            if c == root or c.startswith(root.rstrip(os.sep) + os.sep):
                return name
        return ""


def _worktree_items(g: Graph, folders) -> set[str]:
    """Open items named like a worktree the call ran in: ``.../worktrees/human-queue-a765ad`` -> wi-*-human-queue."""
    out = set()
    for cwd in folders:
        m = _WORKTREE_RE.search(cwd)
        if not m:
            continue
        name = re.sub(r"-[0-9a-f]{6}$", "", m.group(1))
        out |= {nid for nid in g.text if nid == name or nid.endswith(f"-{name}")}
    return out


def _denial_entry(d: dict, g: Graph, today: date, owner: str) -> dict:
    attached = _worktree_items(g, d["cwds"] + d["branches"])
    category = d.get("category") or owner_only(f"{d['call']} {d['reason']}")
    kind = "action" if category or d.get("guard") else "permission"
    if d.get("guard"):   # refused by the owner or power guard: the owner's, never an allow rule
        how = (f"queue it with its item: brain queue add --kind action --guard {d['id']} --item ID; or {owner} does it, "
               f"then brain queue done {d['id']}")
    elif kind == "action":
        how = f"only {owner} may: do it yourself, then brain queue done {d['id']}"
    else:
        how = f"grant a narrow allow rule (wi-brain-permission-grants) or run it once, then brain queue done {d['id']}"
    return _entry(kind, "guard" if d.get("guard") else "denial", d["id"], d["call"], since=d["first"], today=today,
                  g=g, attached=attached,
                  detail=f"{d['via']}: {d['reason']}" if d["reason"] != d["via"] else d["via"], last=d["last"][:10],
                  count=d["count"], sessions=d["sessions"], folders=d["cwds"], category=category, how=how)


# --- the queue ---

def _carried(projects_list) -> set[str]:
    """The guard refusals a DDR of these projects already carries (its ``guard``): queued, not listed twice."""
    out = set()
    for p in projects_list:
        if (p.root / records.RECORDS_DIR / "ddr").is_dir():
            out |= {d["guard"] for _, d in decisions.load(p.root) if d.get("guard")}
    return out


def _sort(entries: list[dict]) -> list[dict]:
    return sorted(entries, key=lambda e: (-e["unblocks"], not e["blocking"], e["since"] or "9999", e["id"]))


def build(project, *, kinds=KINDS, days: int = DAYS, today: date | None = None, with_graph: bool = True,
          transcripts: bool = True, scanned: dict | None = None, placer=None, owner: str | None = None) -> dict:
    """The owner's queue for one project: its entries sorted by what each unblocks, their counts by kind, the guard
    refusals not queued, the rules' terms no category detects. The TUI's data function."""
    today = today or date.today()
    kinds = tuple(kinds)
    owner = owner or config.owner_of()
    store = next((s for s in project.stores if (s / "schema.yaml").is_file()), None)
    g = load_graph(store)
    notes = []
    entries = _ddr_entries(project, g, kinds, today) + _prop_entries(g, kinds, today, _owner(owner))
    if with_graph and store is not None and "decision" in kinds:
        specs, note = _spec_entries(project, store, g, today)
        entries += specs
        if note:
            notes.append(note)
    guards = 0
    if transcripts and ("permission" in kinds or "action" in kinds):
        scanned = scanned if scanned is not None else scan(days, today)
        place = placer or Placer([project])
        carried = _carried([project])
        for d in scanned["denials"]:
            if d["id"] not in carried and place(d["cwds"][0] if d["cwds"] else "") == project.name:
                e = _denial_entry(d, g, today, owner)
                if e["kind"] in kinds:
                    entries.append(e)
        guards = sum(1 for r in scanned["guards"] if place(str(r.get("cwd") or "")) == project.name)
    entries = _sort(entries)
    return {"project": project.name, "root": str(project.root), "today": today.isoformat(), "days": days,
            "owner": owner, "entries": entries, "counts": {k: sum(1 for e in entries if e["kind"] == k) for k in KINDS},
            "guard_refusals": guards, "rules": rules(project, owner), "notes": notes}


def collect(projects_list, *, only=None, kinds=KINDS, days: int = DAYS, today: date | None = None,
            with_graph: bool = True, transcripts: bool = True, scanned: dict | None = None) -> list[dict]:
    """``build`` for each project (or only the one given: a worktree's layout, say) with one transcript scan, the
    denials placed among all of them; then the denials outside every one, as the project ``OUTSIDE`` (when any).
    ``scanned``: a ``scan`` already made (the cockpit's, refreshed on its probe interval) instead of a new one."""
    today = today or date.today()
    owner = config.owner_of()
    if scanned is None:
        scanned = scan(days, today) if transcripts else {"denials": [], "guards": []}
    place = Placer(list(projects_list) + ([only] if only is not None else []))
    targets = [only] if only is not None else [p for p in projects_list if p.root.is_dir()]
    out = [build(p, kinds=kinds, days=days, today=today, with_graph=with_graph, transcripts=transcripts,
                 scanned=scanned, placer=place, owner=owner) for p in targets]
    carried = _carried(list(projects_list) + ([only] if only is not None else []))
    rest = [_denial_entry(d, Graph(), today, owner) for d in scanned["denials"]
            if d["id"] not in carried and not place(d["cwds"][0] if d["cwds"] else "")]
    rest = _sort([e for e in rest if e["kind"] in kinds])
    if rest:
        out.append({"project": OUTSIDE, "root": None, "today": today.isoformat(), "days": days, "owner": owner,
                    "entries": rest,
                    "counts": {k: sum(1 for e in rest if e["kind"] == k) for k in KINDS},
                    "guard_refusals": sum(1 for r in scanned["guards"] if not place(str(r.get("cwd") or ""))),
                    "rules": {}, "notes": []})
    return out


LEGEND = ["  a decision: brain decision answer ID <option>; an action done or a permission granted: "
          "brain queue done ID",
          "  brain queue --json: each entry's how, detail and the items it unblocks"]


def render(data: dict, width: int = 118, outside: int = 0, legend: bool = True) -> list[str]:
    c = data["counts"]
    total = sum(c.values())
    where = f" ({data['root']})" if data.get("root") else ""
    owner = data.get("owner") or config.NO_OWNER
    lines = [f"{data['project']}{where}: {total} waiting on {owner}: {c['decision']} decision(s), {c['action']} "
             f"action(s), {c['permission']} permission(s)"]
    if total:
        lines.append("  unblocks  kind  id  age: what (sorted by the open items and milestones each unblocks)")
    for e in data["entries"]:
        tag = e["kind"] + (f":{e['category']}" if e.get("category") else "")
        flags = (" [blocking]" if e["blocking"] else "") + (f" x{e['count']}" if e.get("count", 1) > 1 else "")
        age = f"{e['age_days']} d" if e.get("age_days") is not None else "-"
        text = e["title"] + (f" -> recommended: {e['recommended']}" if e.get("recommended") else "")
        if e["source"] == "denial":
            text = f"{e['title']} ({e['detail']})"
        lines.append(_cut(f"  {e['unblocks']:>3}  {tag:<17} {e['id']}{flags} {age}: {' '.join(text.split())}",
                          width))
    if legend and total:
        lines += LEGEND
    rest = []
    if data.get("guard_refusals"):
        rest.append(f"{data['guard_refusals']} guard refusal(s) in the last {data['days']} d (the agent corrects "
                    "them)")
    if outside:
        rest.append(f"{outside} denial(s) outside any registered project (brain queue --all)")
    if rest:
        lines.append("  not queued: " + "; ".join(rest))
    for t in (data.get("rules") or {}).get("uncovered", []):
        lines.append(f"  warning: the rules name {t!r} as {owner}'s, and no category of brain.permissions (NEVER, "
                     "never:) finds it")
    lines += [f"  note: {n}" for n in data.get("notes", [])]
    return lines


# --- add and done ---

def add(root: Path, *, kind: str, title: str, what: str, at: str, context: str = "", blocks: str = "",
        items: list[str] | None = None, specs: list[str] | None = None, blocking: bool = False, due: str = "",
        project: str = "", session: str = "", slug: str = "", command: str = "", cwd: str = "",
        dry_run: bool = False, guard: str = "") -> tuple[dict, Path | None, str]:
    """An action or a permission put to the owner, as a DDR of that kind (no options). A permission whose text falls
    in an ``OWNER_ONLY`` category is written as an action (never granted by an allow rule): the third value says so.
    ``command`` (and ``cwd``): the exact command the owner's Apply runs (brain queue apply, the cockpit's A).
    ``guard``, the ref of a refusal of the owner or power guard, fills the title, the question (its exact command) and the context
    from the guards ledger, as an action; and the command and its folder when Apply runs it (a brain or install.ps1
    command)."""
    if kind not in ("action", "permission"):
        raise QueueError("brain queue add takes --kind action or permission (a decision: brain decision ask)")
    if guard:
        row, req = guard_request(guard)
        kind = "action"
        title = title or guards.request_title(req)
        what = what or req.get("command") or req.get("what", "")
        context = context or str(row.get("reason", ""))
        session = session or str(row.get("session_id") or "")
        if not command and req.get("command") and _APPLY_RE.match(req["command"]):
            command, cwd = req["command"], cwd or req.get("cwd") or ""
    if not title or not what:
        raise QueueError("brain queue add needs --title and --what, or --guard REF")
    if command and not _APPLY_RE.match(command):
        raise QueueError(f"--command {command!r}: the owner's Apply runs a brain or an install.ps1 command only")
    category = owner_only(f"{title} {what} {context}")
    note = ""
    if kind == "permission" and category:
        kind, note = "action", (f"written as an action: {category} is {config.owner_of()}'s alone, never granted by "
                                "an allow rule")
    ddr = {"v": 1, "id": f"ddr-{at[:10]}-{actions.slug(slug or title, 48)}", "kind": kind, "title": title,
           "question": what}
    for k, v in (("context", context), ("blocks", blocks), ("guard", guard)):
        if v:
            ddr[k] = v
    ddr["blocking"] = blocking
    if due:
        ddr["due"] = due
    for k, v in (("command", " ".join(command.split())), ("cwd", cwd)):
        if v:
            ddr[k] = v
    ddr["status"] = "pending"
    ddr["asked"] = {"at": at, "by": session or "unknown", "via": "cli"}
    links = {k: v for k, v in {"items": items, "specs": specs}.items() if v}
    if project:
        links["project"] = project
    if links:
        ddr["links"] = links
    if dry_run:
        return records.validate("ddr", ddr), None, note
    return ddr, records.write(root, "ddr", ddr), note


def done(root: Path, ref: str, *, at: str, note: str = "", by: str = "") -> str:
    """The owner did an action or granted a permission (``by``: config.json's owner by default). A DDR of kind action
    or permission is answered (the model in charge then checks the effect and acknowledges it); a denial or a guard
    refusal (perm-, guard-) is stamped in the ledger until it is denied again."""
    by = by or config.owner_of()
    if ref.startswith(("perm-", "guard-")):
        d = paths.ledger_dir()
        d.mkdir(parents=True, exist_ok=True)
        row = {"at": at, "event": "queue-done", "id": ref, "by": by}
        if note:
            row["note"] = note
        with open(d / f"queue-{at[:7]}.jsonl", "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        return f"{ref}: done, stamped in {d.as_posix()}/queue-{at[:7]}.jsonl (back in the queue if denied again)"
    if ":" in ref and not ref.startswith("ddr-"):
        nid, _, prop = ref.partition(":")
        raise QueueError(f"{ref} is the prop {prop} of {nid}: the model in charge clears it by a PR once done "
                         f"(brain item set {nid} {prop}=), or closes the item")
    try:
        _, ddr = decisions.find(root, ref)
    except decisions.QueueError as exc:
        raise QueueError(str(exc)) from exc
    if decisions.kind_of(ddr) == "decision":
        raise QueueError(f"{ddr['id']} is a decision: brain decision answer {ddr['id']} <option>")
    text = "done" + (f": {note}" if note else "")
    ddr = decisions.answer(root, ddr["id"], [], other=text, by=by, via="cli", at=at)
    return (f"{ddr['id']}: answered ({text}); the model in charge checks the effect, then brain decision ack "
            f"{ddr['id']} --applied <where>")
