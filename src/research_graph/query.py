"""Read-only queries over a graph store's work layer, for people: the backlog, one item, closed items, the roadmap
and the decisions waiting for the store's owner (``owner`` in ``schema.yaml``). Store-agnostic: they run on any
``--store`` (a project's, a person's brain, a team's) and on a graph with overlays. Every function returns plain dicts and
lists (``--json`` prints them as they are); ``report`` turns them into text. Git-backed history is ``history``.

    list_items(g, statuses=..., priorities=..., repo=..., props=..., text=..., ids=...)
    show_item(g, nid)               # props, edges both ways, ids named in props, nodes that name it
    closed_items(g, events=...)     # done / dropped items by date: props.done, else the git transition
    roadmap(g)                      # milestones: status, trigger, reached, the items that move each
    pending_decisions(g, repo_root) # props.open, spec questions without an answer, blocked on the owner, proposed specs
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping

import networkx as nx

from .history import Event
from .kanban import MILESTONE_ORDER, STATUS_ORDER
from .loader import apply_overlay, load_store
from .model import WORK_OPEN, LayeredGraph

PRIORITIES = ("P0", "P1", "P2", "P3")
CLOSED = ("done", "dropped")
_DATE = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})")
_ID_TOKEN = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)+")
_PR_REPO = re.compile(r"([A-Za-z][\w.-]*)\s+#\d+")


def _owner_re(owner: str | None) -> re.Pattern | None:
    """The owner's name as a word: an ``external_blocker`` that names them waits on them."""
    return re.compile(rf"\b{re.escape(owner)}\b") if owner else None


# ---------------------------------------------------------------- sources


@dataclass
class Source:
    """A loaded graph and where it comes from. ``name`` is the repository's folder name unless given."""

    name: str
    store: Path
    repo_root: Path
    graph: nx.DiGraph
    overlays: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"name": self.name, "store": str(self.store), "repo_root": str(self.repo_root),
                "overlays": self.overlays}


def load_source(store: str | Path, *, repo_root: str | Path | None = None, overlays: Iterable[str | Path] = (),
                name: str | None = None) -> Source:
    """Load ``store`` (``<repo>/notes/graph`` by convention, so the repo root defaults to two levels up) and apply
    the overlays. Raises ``loader.ValidationError`` like the ``research_graph`` command."""
    store = Path(store)
    root = Path(repo_root) if repo_root is not None else store.resolve().parents[1]
    g = load_store(store)
    for overlay in overlays:
        apply_overlay(g, overlay, root)
    return Source(name or root.resolve().name, store, root, g, [str(o) for o in overlays])


# ---------------------------------------------------------------- rows


def _props(g: nx.DiGraph, nid: str) -> dict:
    return g.nodes[nid].get("props") or {}


def leading_date(value: Any) -> str | None:
    """``2026-10-30`` from ``"2026-10-30: ..."`` / ``"2026-10-30 ..."`` (or a YAML date), else None."""
    if isinstance(value, date):
        return value.isoformat()
    m = _DATE.match(str(value)) if value is not None else None
    return m.group(1) if m else None


def repos_of(props: Mapping, default: str | None = None) -> list[str]:
    """Repositories an item belongs to: ``repo`` / ``repos`` props, the repos named in ``pr`` (``quant-marketdata
    #16``), else ``default`` (the store's own repository)."""
    names: list[str] = []
    for key in ("repo", "repos"):
        value = props.get(key)
        values = value if isinstance(value, list) else re.split(r"[,;]\s*|\s+and\s+", str(value or ""))
        names += [str(v).strip() for v in values if str(v).strip()]
    names += _PR_REPO.findall(str(props.get("pr") or ""))
    out = list(dict.fromkeys(names))
    return out or ([default] if default else [])


def priority_key(row: Mapping) -> float:
    """P0..P3 first, then proposals (P2? after P2), then no priority."""
    if row.get("priority") in PRIORITIES:
        return PRIORITIES.index(row["priority"])
    if row.get("priority_proposed") in PRIORITIES:
        return PRIORITIES.index(row["priority_proposed"]) + 0.5
    return len(PRIORITIES)


def priority_label(row: Mapping) -> str:
    if row.get("priority"):
        return str(row["priority"])
    if row.get("priority_proposed"):
        return f"{row['priority_proposed']}?"
    return "-"


def milestones_of(g: nx.DiGraph, nid: str) -> list[str]:
    return sorted(d for _, d, e in g.out_edges(nid, data=True)
                  if e.get("type") == "part_of" and g.nodes[d].get("type") == "Milestone")


def item_row(g: nx.DiGraph, nid: str, default_repo: str | None = None) -> dict:
    a = g.nodes[nid]
    props = a.get("props") or {}
    status = a.get("status")
    row = {
        "id": nid, "type": a.get("type"), "status": status, "title": a.get("title") or "",
        "priority": props.get("priority"), "priority_proposed": props.get("priority_proposed"),
        "repos": repos_of(props, default_repo), "milestones": milestones_of(g, nid),
        "blockers": LayeredGraph(g).blockers(nid) if status in WORK_OPEN else [],
        "external_blocker": props.get("external_blocker"),
    }
    if a.get("overlay"):
        row["overlay"] = a["overlay"]
    return row


def sort_rows(rows: list[dict]) -> list[dict]:
    rank = {s: i for i, s in enumerate(STATUS_ORDER)}
    return sorted(rows, key=lambda r: (rank.get(r["status"], len(rank)), priority_key(r), r["id"]))


def _text_of(g: nx.DiGraph, nid: str) -> str:
    a = g.nodes[nid]
    parts = [nid, a.get("title") or "", a.get("anchor") or ""]
    for k, v in (a.get("props") or {}).items():
        parts += [str(k), str(v)]
    return " ".join(parts).lower()


def _matches(g: nx.DiGraph, nid: str, text: str) -> bool:
    hay = _text_of(g, nid)
    return all(word in hay for word in text.lower().split())


def _prop_matches(props: Mapping, key: str, value: str | None) -> bool:
    if key not in props:
        return False
    return value is None or value.lower() in str(props[key]).lower()


def list_items(g: nx.DiGraph, *, statuses: Iterable[str] | None = None, priorities: Iterable[str] | None = None,
               repo: str | None = None, props: Mapping[str, str | None] | None = None, text: str | None = None,
               ids: Iterable[str] | None = None, types: Iterable[str] | None = ("WorkItem",),
               default_repo: str | None = None) -> list[dict]:
    """Items matching every filter given, sorted by status, priority and id.

    ``priorities``: ``P0``..``P3`` match ``props.priority``; ``P1?`` matches a proposal (``props.priority_proposed``)
    not validated yet; ``none`` matches items without ``props.priority``. ``repo``: see ``repos_of``
    (case-insensitive). ``props``: key -> None (the key is set) or a substring of its value. ``text``: every word in
    the id, title, anchor or props (case-insensitive). ``ids``: only these ids (e.g. those changed since a date).
    """
    statuses = set(statuses) if statuses else None
    wanted = {p.upper() if p.lower() != "none" else "none" for p in priorities} if priorities else None
    types = set(types) if types else None
    ids = set(ids) if ids is not None else None
    out = []
    for n, a in g.nodes(data=True):
        if types and a.get("type") not in types:
            continue
        if statuses and a.get("status") not in statuses:
            continue
        if ids is not None and n not in ids:
            continue
        p = a.get("props") or {}
        if wanted:
            keys = {str(p["priority"]) if p.get("priority") else "none"}
            if p.get("priority_proposed") and not p.get("priority"):
                keys.add(f"{p['priority_proposed']}?")
            if not keys & wanted:
                continue
        if repo and repo.lower() not in (r.lower() for r in repos_of(p, default_repo)):
            continue
        if props and not all(_prop_matches(p, k, v) for k, v in props.items()):
            continue
        if text and not _matches(g, n, text):
            continue
        out.append(item_row(g, n, default_repo))
    return sort_rows(out)


def counts(rows: Iterable[Mapping]) -> dict[str, int]:
    c: dict[str, int] = {}
    for r in rows:
        c[r["status"]] = c.get(r["status"], 0) + 1
    rank = {s: i for i, s in enumerate(STATUS_ORDER)}
    return dict(sorted(c.items(), key=lambda kv: (rank.get(kv[0], len(rank)), kv[0])))


# ---------------------------------------------------------------- one item


def _brief(g: nx.DiGraph, nid: str) -> dict:
    a = g.nodes[nid]
    return {"id": nid, "type": a.get("type"), "status": a.get("status"), "title": a.get("title") or ""}


def named_ids(g: nx.DiGraph, nid: str) -> list[str]:
    """Ids of other nodes named in a node's title or props (``spec: spec-x``, ``after: "wi-y stage 1"``)."""
    a = g.nodes[nid]
    texts = [a.get("title") or ""] + [str(v) for v in (a.get("props") or {}).values()]
    found = {t for text in texts for t in _ID_TOKEN.findall(text)}
    return sorted(t for t in found if t != nid and t in g)


def show_item(g: nx.DiGraph, nid: str, *, default_repo: str | None = None) -> dict:
    """Everything the graph says about a node: its row and props, its edges both ways, the ids its props name
    (links not yet in edges), the nodes that name it, its blockers and what waits on it."""
    if nid not in g:
        raise KeyError(nid)
    rg = LayeredGraph(g)
    out_edges = [dict(_brief(g, d), edge=e.get("type")) for _, d, e in g.out_edges(nid, data=True)]
    in_edges = [dict(_brief(g, s), edge=e.get("type")) for s, _, e in g.in_edges(nid, data=True)]
    linked = {e["id"] for e in out_edges} | {e["id"] for e in in_edges}
    mentions = [_brief(g, m) for m in named_ids(g, nid) if m not in linked]
    mentioned_by = sorted((_brief(g, n) for n in g.nodes if n != nid and n not in linked
                           and nid in named_ids(g, n)), key=lambda b: b["id"])
    waiting = sorted(s for s, _, e in g.in_edges(nid, data=True) if e.get("type") in {"depends_on", "gated_by"}
                     and g.nodes[s].get("status") in WORK_OPEN)
    a = g.nodes[nid]
    return {
        **item_row(g, nid, default_repo),
        "anchor": a.get("anchor"),
        "props": a.get("props") or {},
        "out": sorted(out_edges, key=lambda e: (e["edge"], e["id"])),
        "in": sorted(in_edges, key=lambda e: (e["edge"], e["id"])),
        "mentions": mentions,
        "mentioned_by": mentioned_by,
        "prerequisites": rg.prerequisites(nid),
        "waiting_on_it": waiting,
    }


# ---------------------------------------------------------------- closed items


def closed_items(g: nx.DiGraph, *, since: str | None = None, events: Iterable[Event] | None = None,
                 default_repo: str | None = None) -> list[dict]:
    """Done and dropped work items, newest first. The date is ``props.done``'s leading date when it has one, else
    the day git saw the item turn done / dropped (``events`` from ``history.timeline``), else unknown (listed last,
    and left out when ``since`` is given)."""
    closed_on: dict[str, Event] = {}
    for e in events or ():
        if e.kind in ("status", "created") and e.new in CLOSED:
            closed_on[e.id] = e
    out = []
    for n, a in g.nodes(data=True):
        if a.get("type") != "WorkItem" or a.get("status") not in CLOSED:
            continue
        p = a.get("props") or {}
        day = leading_date(p.get("done"))
        source, ref = ("props.done", None) if day else (None, None)
        if not day and n in closed_on:
            day, source, ref = closed_on[n].day, "git", closed_on[n].commit.ref
        if since and (not day or day < since):
            continue
        outcome = p.get("done")
        if isinstance(outcome, str) and day and source == "props.done":
            outcome = _DATE.sub("", outcome).lstrip(" :-")
        out.append({**item_row(g, n, default_repo), "date": day, "date_source": source, "commit": ref,
                    "pr": p.get("pr"), "outcome": outcome})
    return sorted(out, key=lambda r: (r["date"] is None, "" if r["date"] is None else _neg(r["date"]), r["id"]))


def _neg(day: str) -> str:
    """Sort key putting later ISO dates first."""
    return "".join(chr(ord("9") - ord(c) + ord("0")) if c.isdigit() else c for c in day)


def changed_since(events: Iterable[Event], since: str) -> set[str]:
    return {e.id for e in events if e.day >= since}


# ---------------------------------------------------------------- roadmap


def _upstream_items(g: nx.DiGraph, start: Iterable[str]) -> set[str]:
    """WorkItems the ``start`` items need first, transitively through ``depends_on``."""
    seen: set[str] = set()
    stack = list(start)
    while stack:
        cur = stack.pop()
        for _, d, e in g.out_edges(cur, data=True):
            if e.get("type") == "depends_on" and d not in seen and g.nodes[d].get("type") == "WorkItem":
                seen.add(d)
                stack.append(d)
    return seen


def roadmap(g: nx.DiGraph, *, default_repo: str | None = None) -> list[dict]:
    """Milestones (pending first, then reached, newest first, then dropped), each with its trigger, ``reached``
    evidence, progress and critical path, and the items that move it: ``part_of`` (directly or through
    sub-milestones), ``depends_on`` (open prerequisites outside it that its open items need first) and ``mentions``
    (items naming it in their title or props)."""
    rg = LayeredGraph(g)
    out = []
    for m in (n for n, a in g.nodes(data=True) if a.get("type") == "Milestone"):
        a = g.nodes[m]
        props = a.get("props") or {}
        info = rg.milestone(m)
        part = [n for n in rg.milestone_items(m) if g.nodes[n].get("type") == "WorkItem"]
        open_part = [n for n in part if g.nodes[n].get("status") in WORK_OPEN]
        deps = sorted(n for n in _upstream_items(g, open_part) - set(part)
                      if g.nodes[n].get("status") in WORK_OPEN)
        mentions = sorted(n for n, b in g.nodes(data=True) if b.get("type") == "WorkItem"
                          and n not in part and n not in deps and m in named_ids(g, n))
        out.append({
            "id": m, "title": a.get("title") or "", "status": a.get("status"),
            "trigger": props.get("trigger"), "reached": props.get("reached"),
            "reached_date": leading_date(props.get("reached")), "note": props.get("note"),
            "parents": milestones_of(g, m),
            "sub_milestones": sorted(s for s, _, e in g.in_edges(m, data=True)
                                     if e.get("type") == "part_of" and g.nodes[s].get("type") == "Milestone"),
            "items": info["items"], "by_status": info["by_status"],
            "critical_path": info["critical_path"], "cycle": info["cycle"],
            "part_of": sort_rows([item_row(g, n, default_repo) for n in part]),
            "depends_on": sort_rows([item_row(g, n, default_repo) for n in deps]),
            "mentions": sort_rows([item_row(g, n, default_repo) for n in mentions]),
        })
    return sorted(out, key=lambda r: (MILESTONE_ORDER.get(r["status"], 3),
                                      _neg(r["reached_date"]) if r["reached_date"] else "~", r["id"]))


# ---------------------------------------------------------------- pending decisions

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_Q_SECTION = re.compile(r"(?i)\bquestions?\b")
_D_SECTION = re.compile(r"(?i)\bd[ée]cisions?\b")
_CLOSED_SECTION = re.compile(r"(?i)r[ée]solu|resolved|pour m[ée]moire|for the record|\banswered\b|tranch[ée]")
_LABELLED = re.compile(r"^\*\*(Q[A-Z0-9]+)\b[^*]*?\*\*|^\*\*(Q[A-Z0-9]+)\b")
_NUMBERED = re.compile(r"^(\d+)\.\s+(.*)$")
_BULLET = re.compile(r"^[-*]\s+(?!\[[ xX]\])(.*)$")
_REMAINING = re.compile(r"(?i)^(\*\*)?\s*(questions?\s+(qui\s+restent|restantes?|ouvertes?)|open questions"
                        r"|remaining questions)")
_ROW = re.compile(r"^\|\s*(Q[A-Z0-9]+|\d+)\s*\|(.*)\|\s*$")
_OPEN_WORD = re.compile(r"(?i)\b(ouverte?s?|open|en attente|pending|à décider|to decide|à trancher)\b")
# An answer written under the question: "Décision :", "**Réponse** :", "Answer:", "<owner> :", "(<owner>, 2026",
# a ticked box, "résolu".
_ANSWER = r"(?i)\[x\]|\b(d[ée]cision|r[ée]ponse|answer{owner})\s*(\*\*)?\s*:{dated}|\br[ée]solue?s?\b|\bresolved\b" \
          r"|\btranchée?s?\b|✅"


def _answer_re(owner: str | None) -> re.Pattern:
    name = re.escape(owner) if owner else ""
    return re.compile(_ANSWER.format(owner=f"|{name}" if owner else "", dated=rf"|\({name}, 20\d\d" if owner else ""))


def _clean(text: str) -> str:
    text = re.sub(r"\*\(([^)]*)\)\*", r"(\1)", text.replace("**", ""))
    return re.sub(r"\s+", " ", text).strip()


def _question_text(label: str, text: str) -> str:
    """The question without its label and without the answer options (``- [ ] A. ...``) under it."""
    lines = []
    for line in text.split("\n"):
        if line.startswith(("- [", "* [")):
            break
        lines.append(line)
    out = _clean(" ".join(lines))
    return re.sub(rf"^{re.escape(label)}\s*[.,:]?\s*", "", out) if label.startswith("Q") else out


def spec_questions(text: str, owner: str | None = None) -> list[dict]:
    """Questions of a spec and whether each has an answer, read from its markdown.

    Questions are the numbered items (``1. ...``) of a section whose heading says "question(s)" (not "resolved" /
    "pour mémoire"), the labelled ones (``**Q3. ...**``) of a question or decision section, and the bullets after a
    "Questions qui restent" / "Open questions" line. A question is answered when its own text has a ticked box or
    an answer marker (Décision, Réponse, Answer:, ``<owner>:``, résolu, resolved, tranché, decided), or when a decision
    table row (``| Q3 | ... |``, ``| 2 | ... |``) has its label and does not say it is still open. A label seen
    again (a question reformulated later) replaces the earlier one."""
    entries: dict[str, dict] = {}
    decisions: dict[str, str] = {}
    in_q = in_d = remaining = in_code = False
    current: dict | None = None
    section = ""
    bullets = 0
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        h = _HEADING.match(line)
        if h:
            section = h.group(2)
            in_q = bool(_Q_SECTION.search(section)) and not _CLOSED_SECTION.search(section)
            in_d = bool(_D_SECTION.search(section)) and not _CLOSED_SECTION.search(section)
            remaining, current = False, None
            continue
        if not (in_q or in_d):
            continue
        row = _ROW.match(line)
        if row:
            decisions[row.group(1)] = row.group(2)
            current = None
            continue
        if _REMAINING.match(line):
            remaining, current = True, None
            continue
        label = None
        body = ""
        lab = _LABELLED.match(line)
        num = _NUMBERED.match(line) if in_q else None
        bul = _BULLET.match(line) if remaining else None
        if lab:
            label, body = lab.group(1) or lab.group(2), line
        elif num:
            label, body = num.group(1), num.group(2)
        elif bul:
            bullets += 1
            label, body = f"-{bullets}", bul.group(1)
        if label:
            current = {"label": label, "text": body, "section": section}
            entries.pop(label, None)
            entries[label] = current
            continue
        if current is not None and line and (raw[:1].isspace() or line.lstrip().startswith(("- [", "* ["))):
            current["text"] += "\n" + line.strip()
        elif not line:
            continue
        elif current is not None and not raw[:1].isspace():
            current = None
    out = []
    answer = _answer_re(owner)
    for label, e in entries.items():
        decided = decisions.get(label)
        answered = bool(answer.search(e["text"])) or (decided is not None and not _OPEN_WORD.search(decided))
        out.append({"label": label, "question": _question_text(label, e["text"]), "section": e["section"],
                    "answered": answered, "decision": _clean(decided) if decided is not None else None})
    return out


def _spec_day(g: nx.DiGraph, nid: str) -> str | None:
    anchor = g.nodes[nid].get("anchor") or ""
    m = re.search(r"(\d{4}-\d{2}-\d{2})", Path(anchor.split("#")[0]).name)
    return m.group(1) if m else None


def _anchor_path(repo_root: Path, anchor: str | None) -> Path | None:
    if not anchor:
        return None
    path = Path(anchor.split("#")[0])
    return path if path.is_absolute() else repo_root / path


def pending_decisions(g: nx.DiGraph, repo_root: str | Path, *, today: date | None = None) -> dict:
    """What waits on the store's owner (``owner`` in ``schema.yaml``, kept in ``g.graph["owner"]``), in four lists:

    - ``open_questions``: open items, pending milestones and live specs with ``props.open`` (the explicit record);
    - ``spec_questions``: specs whose questions or decisions section still has unanswered questions (see
      ``spec_questions``). A spec with ``props.validated`` and no ``props.open`` is settled (its defaults were kept);
    - ``blocked_on_owner``: open items whose ``external_blocker`` names the owner (none when the store has no owner);
    - ``proposed_specs``: specs still ``proposed`` with neither ``validated`` nor ``decided`` in their props, with
      their age in days (from the date in the spec's file name).

    ``owner`` repeats the owner's name (None when the store declares none).
    """
    repo_root = Path(repo_root)
    today = today or date.today()
    owner = g.graph.get("owner")
    named = _owner_re(owner)
    live = {"WorkItem": WORK_OPEN, "Milestone": {"pending"}, "Spec": {"proposed", "active"}}
    open_questions, spec_qs, blocked, proposed = [], [], [], []
    for n in sorted(g.nodes):
        a = g.nodes[n]
        t, status, p = a.get("type"), a.get("status"), a.get("props") or {}
        if t not in live or status not in live[t]:
            continue
        if p.get("open"):
            open_questions.append({**_brief(g, n), "open": p["open"]})
        if t == "WorkItem" and p.get("external_blocker") and named and named.search(str(p["external_blocker"])):
            blocked.append({**_brief(g, n), "external_blocker": p["external_blocker"]})
        if t != "Spec":
            continue
        day = _spec_day(g, n)
        if status == "proposed" and not (p.get("validated") or p.get("decided")):
            age = (today - date.fromisoformat(day)).days if day else None
            proposed.append({**_brief(g, n), "date": day, "age_days": age, "anchor": a.get("anchor")})
        if p.get("validated") and not p.get("open"):
            continue
        path = _anchor_path(repo_root, a.get("anchor"))
        if path is None or not path.is_file():
            continue
        questions = [q for q in spec_questions(path.read_text(encoding="utf-8"), owner) if not q["answered"]]
        if questions:
            spec_qs.append({**_brief(g, n), "date": day, "anchor": a.get("anchor"), "questions": questions})
    return {"open_questions": open_questions, "spec_questions": spec_qs, "blocked_on_owner": blocked,
            "proposed_specs": proposed, "owner": owner}
