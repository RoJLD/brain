"""Text rendering of the ``query`` and ``history`` results, shared by ``research_graph`` and the commands built on it
(a backlog, roadmap or pending-decisions view). Each function returns lines; ``--json`` prints the underlying dicts
instead."""

from __future__ import annotations

from typing import Iterable, Mapping

from .history import Event
from .query import counts, priority_label

TITLE = 100
TEXT = 160


def short(text: object, n: int = TITLE) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def _holds(row: Mapping) -> str:
    notes = []
    if row.get("blockers"):
        notes.append("needs " + ", ".join(row["blockers"]))
    if row.get("status") == "blocked":
        notes.append(f"external: {short(row.get('external_blocker'), 80)}" if row.get("external_blocker")
                     else "external blocker")
    return f"  ← {'; '.join(notes)}" if notes else ""


def rows(items: list[dict], *, title_width: int = TITLE) -> list[str]:
    """One line per item: id, status, priority (``P2?`` = proposed), title, what holds it."""
    if not items:
        return ["(no item)"]
    width = min(max(len(r["id"]) for r in items), 40)
    out = [f"{r['id']:<{width}}  {r['status']:<7}  {priority_label(r):<3}  {short(r['title'], title_width)}"
           + _holds(r) for r in items]
    out.append(f"{len(items)} item(s): " + ", ".join(f"{k} {v}" for k, v in counts(items).items()))
    return out


def event_line(e: Event, *, with_id: bool = True) -> str:
    who = f"{e.id}  " if with_id else ""
    return f"{e.day}  {e.commit.ref:<8} {who}{e.describe()}"


def item(detail: Mapping, events: list[Event] | None, git_error: str | None = None) -> list[str]:
    """Everything about one node: header, props, links, blockers, and its history from git."""
    out = [f"{detail['id']}  [{detail['type']} {detail['status']}]  priority {priority_label(detail)}",
           f"  {detail['title']}"]
    if detail.get("anchor"):
        out.append(f"  anchor: {detail['anchor']}")
    if detail.get("repos"):
        out.append(f"  repo: {', '.join(detail['repos'])}")
    if detail.get("props"):
        out.append("props:")
        out += [f"  {k}: {short(v, 400)}" for k, v in detail["props"].items()]
    for key, heading in (("out", "links out"), ("in", "links in")):
        if detail.get(key):
            out.append(f"{heading}:")
            out += [f"  {e['edge']:<13} {e['id']} [{e['status']}]  {short(e['title'], 80)}" for e in detail[key]]
    if detail.get("mentions"):
        out.append("named in its props (no edge yet):")
        out += [f"  {e['id']} [{e['type']} {e['status']}]  {short(e['title'], 80)}" for e in detail["mentions"]]
    if detail.get("mentioned_by"):
        out.append("named by:")
        out += [f"  {e['id']} [{e['type']} {e['status']}]  {short(e['title'], 80)}" for e in detail["mentioned_by"]]
    if detail.get("blockers"):
        out.append("blocked by: " + ", ".join(detail["blockers"]))
    if detail.get("waiting_on_it"):
        out.append("open items waiting on it: " + ", ".join(detail["waiting_on_it"]))
    if git_error:
        out.append(f"history: unavailable ({git_error})")
    elif events is not None:
        out.append(f"history (git, first-parent): {len(events)} change(s)")
        out += ["  " + event_line(e, with_id=False) for e in events]
    return out


def closed(items: list[dict]) -> list[str]:
    if not items:
        return ["(nothing closed)"]
    out = []
    for r in items:
        when = r["date"] or "????-??-??"
        src = {"git": f" (git {r['commit']})", "props.done": ""}.get(r["date_source"], " (no date)")
        out.append(f"{when}  {r['status']:<7}  {r['id']}{src}  {short(r['title'], 90)}")
        detail = r["outcome"] if isinstance(r["outcome"], str) and r["outcome"] else None
        if detail or r.get("pr"):
            out.append("            " + "  ".join(x for x in (f"pr {r['pr']}" if r.get("pr") else "",
                                                               short(detail, TEXT) if detail else "") if x))
    out.append(f"{len(items)} closed item(s)")
    return out


def events(evts: Iterable[Event]) -> list[str]:
    evts = list(evts)
    return [event_line(e) for e in evts] + [f"{len(evts)} change(s)"]


def roadmap(milestones: list[dict], *, items: bool = True) -> list[str]:
    """Compact roadmap: one line per milestone, its trigger or reached evidence, and for pending milestones the
    open items that move it."""
    if not milestones:
        return ["(no milestone)"]
    out = []
    for m in milestones:
        done = m["by_status"].get("done", 0)
        when = f" {m['reached_date']}" if m["status"] == "reached" and m["reached_date"] else ""
        out.append(f"{m['id']}  [{m['status']}{when}]  {done}/{m['items']} done  {short(m['title'], 90)}")
        if m["status"] == "reached":
            if m["reached"]:
                out.append(f"    reached: {short(m['reached'], TEXT)}")
            continue
        if m["trigger"]:
            out.append(f"    trigger: {short(m['trigger'], TEXT)}")
        if m["critical_path"]:
            out.append("    critical path: " + " → ".join(m["critical_path"]))
        if not items:
            continue
        open_part = [r for r in m["part_of"] if r["status"] in ("doing", "todo", "blocked")]
        for heading, group in (("moves it", open_part), ("prerequisite", m["depends_on"]),
                               ("names it", m["mentions"])):
            for r in group:
                out.append(f"    {heading:<12} {r['id']} [{r['status']}] {priority_label(r)}"
                           f"  {short(r['title'], 80)}{_holds(r)}")
    return out


def pending(d: Mapping) -> list[str]:
    out = [f"Open questions recorded on items and specs (props.open): {len(d['open_questions'])}"]
    for r in d["open_questions"]:
        out.append(f"  {r['id']} [{r['status']}]  {short(r['title'], 90)}")
        out.append(f"      open: {short(r['open'], TEXT)}")
    n_q = sum(len(s["questions"]) for s in d["spec_questions"])
    out.append(f"Spec questions without a recorded answer: {n_q} in {len(d['spec_questions'])} spec(s)")
    for s in sorted(d["spec_questions"], key=lambda s: (s["status"] != "proposed", s["id"])):
        note = "" if s["status"] == "proposed" else "  (active spec: record the answers its implementation settled)"
        out.append(f"  {s['id']} [{s['status']}{', ' + s['date'] if s['date'] else ''}]  "
                   f"{(s['anchor'] or '').split('#')[0]}{note}")
        for q in s["questions"]:
            label = q["label"] if q["label"].startswith("Q") else ("-" if q["label"].startswith("-")
                                                                   else f"{q['label']}.")
            extra = f"  [decision table: {short(q['decision'], 40)}]" if q.get("decision") else ""
            out.append(f"      {label} {short(q['question'], TEXT)}{extra}")
    out.append(f"Blocked on {d.get('owner') or 'the owner'} (external_blocker): {len(d['blocked_on_owner'])}")
    for r in d["blocked_on_owner"]:
        out.append(f"  {r['id']} [{r['status']}]  {short(r['title'], 90)}")
        out.append(f"      external: {short(r['external_blocker'], TEXT)}")
    out.append(f"Proposed specs without a decision: {len(d['proposed_specs'])}")
    for r in d["proposed_specs"]:
        age = f"{r['age_days']} d" if r["age_days"] is not None else "? d"
        out.append(f"  {r['id']}  {age:>5}  {short(r['title'], 100)}")
    return out
