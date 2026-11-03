"""The digest: ``brain digest [--project p | --all] [--since WHEN] [--until WHEN] [--budget N] [--write] [--offline]
[--json]`` (wi-brain-digest; spec 2026-10-30 governance brainstorm §3.13, the owner's "mémoire morte"; spec 2026-11-02
learned harness §3.16: the resume pack holds the present state, the digest a past period).

What happened in a project over a window, assembled at zero token from what the Brain records already, so that a
session reads one page instead of the journals. Newest first in each section:

  1. the narrative summary of the window, when one was written beside the digest (below);
  2. the milestones reached;
  3. the items closed, done or dropped, with their PR and outcome;
  4. the ADRs dated in the window, with their decision's first sentence;
  5. the DDRs asked, answered, applied or archived in the window, with their state now;
  6. the merged PRs (gh; --offline skips them), less those already on a closed item's line;
  7. the session records (SR) started in the window;
  8. the token cost of the window's sessions, from the token ledger (brain.usage, brain.cost): the total at API
     prices, its distribution, the costliest items and phases, the script candidates;
  9. the journal's entries.

WHEN is a day (YYYY-MM-DD), today, yesterday, last-week (seven days before today), last-month (the same day a month
before) or a milestone id (the day it was reached); both ends are included. A closed item's day is the date its
``props.done`` (or ``dropped``) starts with, as ``brain item close`` writes it, and a milestone's the date of its
``props.reached``; a closed node without such a date gets the day of the commit that closed it, from one ``git log
-p`` of the store's nodes.

It condenses by levels before it cuts: with a budget (tokens estimated at four characters each), the sections are
lowered one level at a time, the journal first, from their full text to one line per record, then to a count or a
list of ids that points to the source; only when that is not enough are lines dropped from the end (the oldest
journal entries). The header and the last section stay, and the last one says what was condensed. ``--json`` prints
the records gathered, before any condensing. ``--write`` keeps the digest in
``<BRAIN_HOME>/digest/<project>/<since>_<until>.md``, outside the repo like the resume pack, whose journal section
names the latest one.

The narrative summary is a later, optional step, and nothing here calls a model or schedules one. Its hook point: a
summarizer (once a week or per milestone, with a fixed budget) reads ``brain digest --json`` or the written digest and
writes its text to ``<BRAIN_HOME>/digest/<project>/<since>_<until>.summary.md``; ``brain digest`` over the same window
then puts it first, condensed under the budget like any section, and ``--json`` carries it.
"""

from __future__ import annotations

import calendar
import re
import textwrap
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import actions, cost, decisions, notes, paths, projects, resume

BUDGET = 4000  # tokens; 0: no limit
WIDTH = resume.WIDTH
DIGEST_DIR = "digest"
SUMMARY = ".summary.md"
PR_LIMIT = 300
DETAIL_LINES = 3  # an outcome, a decision or a DDR's history: wrapped to this many lines at most
CLOSED = {"WorkItem": ("done", "dropped"), "Milestone": ("reached",)}
DAY_PROPS = ("done", "dropped", "closed", "reached", "reached_at")
DDR_EVENTS = (("asked", "asked"), ("answer", "answered"), ("applied", "applied"), ("archived", "archived"))
WHEN = "YYYY-MM-DD, today, yesterday, last-week, last-month or a milestone id"
_DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DATED_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\b[\s:,;.—-]*(.*)$", re.S)
_GIT_NODE_RE = re.compile(r"^([-+])- \{id: ([^,\s}]+),.*?\btype: (WorkItem|Milestone)\b.*?\bstatus: ([\w-]+)")
_DECISION_RE = re.compile(r"^\*\*(?:new decision|nouvelle décision|decision|décision)\s*\.?\*\*\s*:?\s*(.*)$",
                          re.I | re.S)
_FIELD_RE = re.compile(r"^\*\*[^*]{1,40}\*\*\s*:?\s*")
_SENTENCE_RE = re.compile(r"^(.+?[.!?])(?=\s+[A-ZÀ-Ý«\"`(*]|$)", re.S)
_SUB_RE = re.compile(r"^\s+(?:[-*]|\d+\.)\s")
_PR_REF_RE = re.compile(r"(?<![\w-])(?:([\w.-]+)\s+)?#(\d+)\b")


class DigestError(Exception):
    pass


@dataclass(frozen=True)
class Window:
    since: str  # YYYY-MM-DD, included
    until: str  # YYYY-MM-DD, included
    asked: str = ""  # how it was asked: "--since last-week --until today"

    def has(self, day) -> bool:
        return bool(day) and self.since <= str(day)[:10] <= self.until


# --- the window ---

def _month_before(d: date) -> date:
    y, m = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)
    return d.replace(year=y, month=m, day=min(d.day, calendar.monthrange(y, m)[1]))


def resolve(when: str, today: date, project: projects.Project | None = None, st: resume.Store | None = None) -> str:
    """The day a WHEN names (see the module's doc); a milestone must be reached."""
    w = (when or "").strip()
    rel = {"today": today, "yesterday": today - timedelta(days=1), "last-week": today - timedelta(days=7),
           "last-month": _month_before(today)}
    if w.lower() in rel:
        return rel[w.lower()].isoformat()
    if _DAY_RE.fullmatch(w):
        try:
            return date.fromisoformat(w).isoformat()
        except ValueError:
            raise DigestError(f"{w}: not a day") from None
    node = (st.nodes if st else {}).get(w)
    if node is None:
        raise DigestError(f"{w!r}: expected {WHEN}" + (" (no such node in the store)" if w.startswith("ms-") else ""))
    if node.get("type") != "Milestone":
        raise DigestError(f"{w}: a {node.get('type')}, not a milestone")
    if node.get("status") != "reached":
        raise DigestError(f"{w} is {node.get('status')}, not reached: give a day")
    day = closed_on(node)[0]
    store = resume.graph_store(project) if project is not None else None
    if not day and store:
        day = git_closures(project.root, store).get(w, ("", ""))[0]
    if not day:
        raise DigestError(f"{w}: reached, but neither props.reached nor git dates it: give a day")
    return day


def window(project: projects.Project, st: resume.Store, since: str, until: str, today: date | None = None) -> Window:
    today = today or date.today()
    w = Window(resolve(since, today, project, st), resolve(until, today, project, st),
               f"--since {since} --until {until}")
    if w.since > w.until:
        raise DigestError(f"the window starts after it ends ({w.since} > {w.until})")
    return w


# --- the records of the window ---

def closed_on(node: dict) -> tuple[str, str]:
    """(day, text) of the dated prop that closed a node, as brain item close writes it (``done: "<day> <outcome>"``,
    ``dropped``; a milestone's ``reached``); ('', '') when none starts with a day."""
    props = node.get("props") or {}
    for key in dict.fromkeys((str(node.get("status") or ""), *DAY_PROPS)):
        m = _DATED_RE.match(" ".join(str(props.get(key) or "").split()))
        if m:
            return m.group(1), m.group(2)
    return "", ""


def git_closures(root: Path, store: Path, since: str = "", until: str = "") -> dict[str, tuple[str, str]]:
    """{node id: (day, status)}: the newest commit that turned each work item done or dropped, or each milestone
    reached, from one ``git log -p`` of the store's nodes (a day of margin on each side; the caller filters by day);
    {} outside git."""
    try:
        rel = store.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return {}
    args = ["log", "--format=%x00%cs", "-p", "-U0", "--no-color", "--no-renames", "--no-ext-diff"]
    if since:
        args.append(f"--since={date.fromisoformat(since) - timedelta(days=1)}")
    if until:
        args.append(f"--until={date.fromisoformat(until) + timedelta(days=2)}")
    out = actions.git(root, *args, "--", f"{rel}/nodes", timeout=60)
    found: dict[str, tuple[str, str]] = {}
    for chunk in out.split("\x00")[1:]:
        day, _, diff = chunk.partition("\n")
        before: dict[str, str] = {}
        after: dict[str, tuple[str, str]] = {}
        for ln in diff.splitlines():
            m = _GIT_NODE_RE.match(ln)
            if m and m.group(1) == "-":
                before[m.group(2)] = m.group(4)
            elif m:
                after[m.group(2)] = (m.group(3), m.group(4))
        for nid, (ntype, status) in after.items():
            if status in CLOSED[ntype] and before.get(nid) != status:
                found.setdefault(nid, (day.strip(), status))
    return found


def _newest_first(rows: list[dict], key: str = "day") -> list[dict]:
    return sorted(sorted(rows, key=lambda r: r["id"]), key=lambda r: r[key], reverse=True)


def closures(project: projects.Project, st: resume.Store, w: Window) -> tuple[list[dict], list[dict]]:
    """(milestones reached, items closed) in the window, newest first."""
    nodes = [n for n in st.nodes.values() if n.get("status") in CLOSED.get(n.get("type"), ())]
    dated = {n["id"]: closed_on(n) for n in nodes}
    store = resume.graph_store(project)
    git = git_closures(project.root, store, w.since, w.until) if store and not all(
        d for d, _ in dated.values()) else {}
    miles, items = [], []
    for n in nodes:
        (day, text), source = dated[n["id"]], "props"
        if not day and n["id"] in git:
            day, source = git[n["id"]][0], "git"
        if not w.has(day):
            continue
        props = n.get("props") or {}
        row = {"id": n["id"], "type": n["type"], "status": n["status"], "day": day, "day_from": source,
               "title": " ".join(str(n.get("title") or "").split()), "priority": resume._priority(n),
               "pr": " ".join(str(props.get("pr") or "").split()), "outcome": text}
        (miles if n["type"] == "Milestone" else items).append(row)
    return _newest_first(miles), _newest_first(items)


def _paragraphs(lines: list[str]) -> list[str]:
    return [" ".join(p.split()) for p in "\n".join(lines).split("\n\n") if p.strip()]


def adrs(path: Path | None, w: Window) -> list[dict]:
    """The decision log's entries dated in the window, newest first: id (research_graph sync's), day, title, the
    decision field's first paragraph (Decision, Décision, New decision) or, when it has none, its first paragraph
    (lead)."""
    if not path or not path.is_file():
        return []
    text, _ = notes.read(path)
    seen: list[tuple[str, str]] = []
    entries: list[dict] = []
    cur: dict | None = None
    for ln in text.split("\n"):
        m = notes._HEADING_RE.match(ln)
        if m:
            cur = {"id": notes.adr_id(m.group(1), m.group(2), seen), "day": m.group(1), "title": m.group(2),
                   "body": []}
            seen.append((m.group(1), m.group(2)))
            entries.append(cur)
        elif ln.startswith("## "):
            cur = None
        elif cur is not None:
            cur["body"].append(ln)
    out = []
    for e in entries:
        if not w.has(e["day"]):
            continue
        paras = _paragraphs(e.pop("body"))
        e["decision"] = next((_DECISION_RE.match(p).group(1) for p in paras if _DECISION_RE.match(p)), "")
        e["lead"] = "" if e["decision"] or not paras else _FIELD_RE.sub("", paras[0])
        out.append(e)
    return out[::-1]  # the log is in date order


def ddrs(root: Path, w: Window) -> list[dict]:
    """The DDRs with an event (asked, answered, applied, archived) in the window, newest event first."""
    out = []
    for d in resume.record_files(root, "ddr"):
        events = {name: decisions._day(d.get(key)) for key, name in DDR_EVENTS if decisions._day(d.get(key))}
        if not any(w.has(day) for day in events.values()):
            continue
        out.append({"id": d["id"], "day": max(events.values()), "title": " ".join(str(d.get("title", "")).split()),
                    "status": d.get("status", ""), "blocking": bool(d.get("blocking")), "events": events,
                    "recommendation": (d.get("recommendation") or {}).get("option") or "",
                    "answer": decisions._answer_text(d) if d.get("answer") else "",
                    "applied_in": list((d.get("applied") or {}).get("in") or [])})
    return _newest_first(out)


def sessions(root: Path, w: Window) -> list[dict]:
    """The session records started in the window, newest first."""
    out = []
    for sr in resume.record_files(root, "sr"):
        day = str(sr.get("start", ""))[:10]
        if w.has(day):
            out.append({"id": sr["id"], "day": day, "status": sr.get("status", ""),
                        "title": " ".join(str(sr.get("summary") or sr.get("title") or "").split()),
                        "model": sr.get("model", ""), "effort": sr.get("effort", ""),
                        "active_s": int(sr.get("active_s") or 0),
                        "output_tokens": int((sr.get("tokens") or {}).get("output") or 0),
                        "prs": [f"{p.get('repo')}#{p.get('number')}" for p in sr.get("prs") or []]})
    return _newest_first(out)


def merged_prs(root: Path, w: Window, offline: bool) -> tuple[list[dict] | None, str]:
    """The PRs merged in the window (gh), newest first, or None and why."""
    if offline:
        return None, "--offline"
    prs, why = resume.gh_json(root, ["pr", "list", "--state", "merged", "--search", f"merged:{w.since}..{w.until}",
                                     "--limit", str(PR_LIMIT), "--json", "number,title,mergedAt,headRefName"],
                              timeout=30)
    if prs is None:
        return None, why
    rows = [{"number": int(p.get("number") or 0), "day": str(p.get("mergedAt", ""))[:10],
             "title": " ".join(str(p.get("title", "")).split()), "branch": p.get("headRefName", "")}
            for p in prs if isinstance(p, dict) and w.has(str(p.get("mergedAt", ""))[:10])]
    return sorted(rows, key=lambda p: (p["day"], p["number"]), reverse=True), ""


def journal(path: Path | None, w: Window) -> list[dict]:
    """The journal's entries dated in the window, newest first: day, title and bullets (with their continuation
    lines)."""
    out = []
    for head, groups in resume.journal_entries(path):
        m = notes._HEADING_RE.match(f"## {head}")
        if m and w.has(m.group(1)):
            out.append({"day": m.group(1), "title": m.group(2), "bullets": ["\n".join(g) for g in groups]})
    return out[::-1]  # append-only, in date order


def summary_path(name: str, w: Window) -> Path:
    return digest_dir(name) / f"{w.since}_{w.until}{SUMMARY}"


def gather(project: projects.Project, since: str = "last-week", until: str = "today", *, offline: bool = False,
           today: date | None = None) -> dict:
    """Every record of the window, as ``--json`` prints it."""
    store = resume.graph_store(project)
    st = resume.Store.load(store) if store else resume.Store({}, [])
    w = window(project, st, since, until, today)
    miles, items = closures(project, st, w) if store else ([], [])
    prs, why = merged_prs(project.root, w, offline)
    summary = summary_path(project.name, w)
    return {"project": project.name, "since": w.since, "until": w.until, "asked": w.asked,
            "summary": {"path": str(summary), "text": summary.read_text(encoding="utf-8")}
            if summary.is_file() else None,
            "milestones": miles, "items": items, "adrs": adrs(project.decisions, w),
            "ddrs": ddrs(project.root, w), "prs": prs, "prs_why": why, "sessions": sessions(project.root, w),
            "cost": tokens(project, w), "journal": journal(project.journal, w)}


def tokens(project: projects.Project, w: Window) -> dict:
    """The window's sessions in the token ledger (brain.cost.summary_of), the ledger scanned first."""
    try:
        led = cost.load([project])
    except (OSError, ValueError) as exc:
        return {"error": str(exc), "sessions": 0}
    until = str(date.fromisoformat(w.until) + timedelta(days=1)) if w.until else ""
    return cost.summary_of(led, project.name, w.since, until)


# --- the text, by levels ---

@dataclass
class Part:
    """A section written at several levels, from the full text (0) to a count or a list of ids (the last)."""
    key: str
    title: str
    levels: list[list[str]]
    names: list[str] = field(default_factory=list)  # what each level keeps, for the condensed note
    level: int = 0
    keep: bool = False

    def section(self) -> resume.Section:
        return resume.Section(self.title, list(self.levels[self.level]), self.keep)


# The steps that lower a section to a level, in order. The journal goes first and down to its headings, its bullets
# mostly retelling the closed items and the ADRs; then the DDRs (the queue has them all), the session records and
# the PRs; the substance last: the ADRs' decisions, the items' outcomes, the narrative summary. Then the last levels.
STEPS = (("journal", 1), ("journal", 2), ("ddrs", 1), ("sessions", 1), ("cost", 1), ("prs", 1), ("adrs", 1),
         ("milestones", 1), ("items", 1), ("summary", 1), ("journal", 3), ("ddrs", 2), ("sessions", 2), ("cost", 2),
         ("prs", 2), ("adrs", 2), ("milestones", 2), ("items", 2), ("summary", 2))
LABELS = {"journal": "journal", "ddrs": "DDRs", "sessions": "session records", "cost": "token cost", "prs": "PRs",
          "adrs": "ADRs", "milestones": "milestones", "items": "items", "summary": "summary"}


def _detail(text: str, indent: str = "  ") -> list[str]:
    return textwrap.wrap(" ".join(str(text).split()), WIDTH, initial_indent=indent, subsequent_indent=indent,
                         break_long_words=False, break_on_hyphens=False, max_lines=DETAIL_LINES, placeholder=" …")


def _ids(label: str, ids: list[str]) -> list[str]:
    return textwrap.wrap(f"{label}: {', '.join(ids)}.", WIDTH, break_long_words=False, break_on_hyphens=False)


def first_sentence(text: str, n: int = WIDTH) -> str:
    text = " ".join(str(text).split())
    m = _SENTENCE_RE.match(text)
    return decisions._short(m.group(1) if m else text, n)


def _plural(n: int, word: str) -> str:
    return f"{n} {word if n == 1 else word[:-1] + 'ies' if word.endswith('y') else word + 's'}"


def _summary(data: dict) -> Part | None:
    s = data.get("summary")
    if not s:
        return None
    lines = str(s["text"]).replace("\r\n", "\n").strip().split("\n")
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    body = "\n".join(lines).strip()
    paras = body.split("\n\n")
    where = resume._display(Path(s["path"]))
    return Part("summary", f"Narrative summary ({where})",
                [body.split("\n"), paras[0].split("\n") + ["(its first paragraph; the rest in the file)"],
                 [f"A narrative summary of the window is in {where}."]], ["full", "first paragraph", "pointer"])


def _milestones(rows: list[dict]) -> Part | None:
    if not rows:
        return None
    full, one = [], []
    for m in rows:
        row = resume._row(f"- {m['id']} reached {m['day']}", m["title"])
        one.append(row)
        full += [row] + (_detail(m["outcome"]) if m["outcome"] else [])
    ids = _ids("Reached", [m["id"] for m in rows])
    return Part("milestones", f"Milestones reached ({len(rows)})", [full, one, ids], ["full", "one line each", "ids"])


def _items(rows: list[dict]) -> Part | None:
    if not rows:
        return None
    full, one = [], []
    for i in rows:
        head = f"- {i['id']}{'' if i['status'] == 'done' else ' ' + i['status']} {i['day']}" + \
            (f" [{i['priority']}]" if i["priority"] else "") + (f" ({i['pr']})" if i["pr"] else "")
        row = resume._row(head, i["title"])
        one.append(row)
        full += [row] + (_detail(i["outcome"]) if i["outcome"] else [])
    done = [i["id"] for i in rows if i["status"] == "done"]
    dropped = [i["id"] for i in rows if i["status"] != "done"]
    ids = (_ids("Done", done) if done else []) + (_ids("Dropped", dropped) if dropped else [])
    return Part("items", f"Items closed ({len(done)} done, {len(dropped)} dropped)", [full, one, ids],
                ["full", "one line each", "ids"])


def _adrs(rows: list[dict], where: str) -> Part | None:
    if not rows:
        return None
    full, one = [], []
    for a in rows:
        row = resume._row(f"- {a['day']}", notes.ADR_SUFFIX_RE.sub("", a["title"]))
        one.append(row)
        gist = f"Decision: {a['decision']}" if a["decision"] else a["lead"]
        full += [row] + (_detail(first_sentence(gist, WIDTH * DETAIL_LINES)) if gist else [])
    count = [f"{_plural(len(rows), 'ADR')} from {rows[-1]['day']} to {rows[0]['day']}: {where}."]
    return Part("adrs", f"ADRs ({len(rows)}, {where})", [full, one, count], ["full", "titles", "a count"])


def _ddr_history(d: dict) -> str:
    ev = d["events"]
    parts = [f"asked {ev['asked']}" if ev.get("asked") else ""]
    if ev.get("answered"):
        parts.append(f"answered {ev['answered']}: {d['answer']}")
    elif d["recommendation"]:
        parts.append(f"recommended: {d['recommendation']}")
    if ev.get("applied"):
        parts.append(f"applied {ev['applied']}" + (f" in {', '.join(d['applied_in'])}" if d["applied_in"] else ""))
    if ev.get("archived"):
        parts.append(f"archived {ev['archived']}")
    return "; ".join(p for p in parts if p)


def _ddrs(rows: list[dict]) -> Part | None:
    if not rows:
        return None
    full, one = [], []
    for d in rows:
        row = resume._row(f"- {d['id']} [{d['status']}{', blocking' if d['blocking'] else ''}]", d["title"])
        one.append(row)
        full += [row] + _detail(_ddr_history(d))
    states: dict[str, int] = {}
    for d in rows:
        states[d["status"]] = states.get(d["status"], 0) + 1
    now = ", ".join(f"{n} {s}" for s, n in sorted(states.items()))
    count = [f"{_plural(len(rows), 'DDR')} with an event in the window ({now}): `brain decision pending`, "
             "records/ddr/."]
    return Part("ddrs", f"DDRs ({len(rows)} with an event in the window; now {now})", [full, one, count],
                ["full", "one line each", "a count"])


def cited_prs(items: list[dict], repo: str) -> set[int]:
    """The PR numbers of this repo the closed items cite in props.pr ("brain #42", "#42", "PR #42")."""
    short = repo.split("/")[-1].lower()
    return {int(m.group(2)) for i in items for m in _PR_REF_RE.finditer(i["pr"])
            if m.group(1) is None or m.group(1).lower() in (short, "pr")}


def _prs(rows: list[dict] | None, why: str, cited: set[int]) -> Part:
    if rows is None:
        return Part("prs", "Merged PRs", [[f"Not read ({why})."]], ["full"])
    rest = [p for p in rows if p["number"] not in cited]
    on_items = len(rows) - len(rest)
    cites = f"; the {on_items} a closed item cites are on its line" if on_items else ""
    title = f"Merged PRs ({len(rows)}{cites})"
    if not rows:
        return Part("prs", title, [["None."]], ["full"])
    full = [resume._row(f"- #{p['number']} {p['day']}", p["title"]) for p in rest] or ["All on the items' lines."]
    ids = _ids("Merged" if not on_items else "The others", [f"#{p['number']}" for p in rest]) if rest else full
    return Part("prs", title, [full, ids, [f"{_plural(len(rows), 'PR')} merged (gh pr list --state merged)."]],
                ["full", "numbers", "a count"])


def _hours(seconds: int) -> str:
    return f"{seconds / 3600:.1f} h"


def _sessions(rows: list[dict]) -> Part | None:
    if not rows:
        return None
    full, one = [], []
    for s in rows:
        how = " ".join(x for x in (s["model"], s["effort"]) if x)
        row = resume._row(f"- {s['day']} {s['id']}" + (f" [{how}]" if how else ""), s["title"])
        one.append(row)
        full += [row] + _detail(f"{_hours(s['active_s'])} active, {s['output_tokens']:,} output tokens"
                                + (f"; PRs {', '.join(s['prs'])}" if s["prs"] else ""))
    total = [f"{_plural(len(rows), 'session record')}: {_hours(sum(s['active_s'] for s in rows))} active, "
             f"{sum(s['output_tokens'] for s in rows):,} output tokens (records/sr/)."]
    return Part("sessions", f"Session records ({len(rows)})", [full, one, total], ["full", "one line each", "totals"])


def _cost(c: dict | None) -> Part | None:
    if not c or not c.get("sessions"):
        return None
    line = cost.summary_line(c)
    full = [line] + [f"- script candidate: {k} ({n} sessions, ${usd:,.2f})" for k, n, usd in c.get("candidates") or []]
    total = [f"${c['cost']:,.2f} at API prices over {c['sessions']} session(s) (brain usage)."]
    return Part("cost", "Token cost", [full, [line], total], ["full", "one line", "total"])


def _first_bullet_sentence(bullet: str) -> str:
    """A journal bullet's first sentence, its sub-bullets left out."""
    lines = bullet.split("\n")
    lead = [lines[0]]
    for ln in lines[1:]:
        if _SUB_RE.match(ln):
            break
        lead.append(ln)
    return "- " + first_sentence(re.sub(r"^[-*]\s+", "", " ".join(x.strip() for x in lead)), WIDTH - 2)


def _journal(rows: list[dict], where: str) -> Part | None:
    if not rows:
        return None
    full, firsts, heads = [], [], []
    for e in rows:
        head = f"### {e['day']} — {e['title']}"
        full += [head] + [ln for b in e["bullets"] for ln in b.split("\n")]
        firsts += [head] + [_first_bullet_sentence(b) for b in e["bullets"]]
        heads.append(resume._row(f"- {e['day']}", f"{e['title']} ({_plural(len(e['bullets']), 'bullet')})"))
    count = [f"{_plural(len(rows), 'entry')} from {rows[-1]['day']} to {rows[0]['day']}: {where}."]
    return Part("journal", f"Journal ({where}, newest first)", [full, firsts, heads, count],
                ["full", "first sentences", "headings", "a count"])


def _header(project: projects.Project, data: dict) -> Part:
    repo = (paths.main_checkout(project.root) or project.root).name
    prs = data["prs"]
    counts = [_plural(len(data["milestones"]), "milestone") + " reached",
              _plural(len(data["items"]), "item") + " closed", _plural(len(data["adrs"]), "ADR"),
              _plural(len(data["ddrs"]), "DDR") + " with an event",
              (_plural(len(prs), "PR") + " merged") if prs is not None else "PRs not read",
              _plural(len(data["sessions"]), "session record"), _plural(len(data["journal"]), "journal entry")]
    lines = ["Generated by `brain digest` at zero token from the graph, the decision log, the DDRs, the SRs, gh and "
             "the journal: what happened in the window, newest first. The present state: `brain resume`.",
             f"Window: {data['since']} to {data['until']}, both included ({data['asked']}).",
             f"In it: {', '.join(counts)}."]
    title = f"Digest — {project.name} ({repo}), {data['since']} to {data['until']}"
    return Part("header", title, [lines], ["full"], keep=True)


def _footer(generated: str, parts: list[Part], budget: int) -> Part:
    lines = [generated]
    lowered = [f"{LABELS[p.key]} {p.names[p.level]}" for p in parts if p.level]
    if lowered:
        lines.append(f"Condensed for --budget {budget}: {'; '.join(lowered)}. `brain digest --budget 0` prints "
                     "everything.")
    return Part("footer", "Generated", [lines], ["full"], keep=True)


def condense(parts: list[Part], fits) -> None:
    """Lower the parts by STEPS until ``fits()``."""
    by_key = {p.key: p for p in parts}
    for key, level in STEPS:
        p = by_key.get(key)
        if p and p.level < level < len(p.levels):
            if fits():
                return
            p.level = level


def render(project: projects.Project, data: dict, *, budget: int = BUDGET, now: datetime | None = None) -> str:
    """The digest's text: every section at its fullest level, lowered by STEPS until it fits the budget; then lines
    dropped from the end."""
    now = now or datetime.now(timezone.utc)
    head = actions.git(project.root, "rev-parse", "--short", "HEAD")
    branch = actions.git(project.root, "rev-parse", "--abbrev-ref", "HEAD")
    generated = f"Generated {now.strftime('%Y-%m-%d %H:%M')} UTC" + (f" at {head} on {branch}" if head else "") + "."
    cited = cited_prs(data["items"], actions.repo_name(project.root))
    parts = [p for p in (_summary(data), _milestones(data["milestones"]), _items(data["items"]),
                         _adrs(data["adrs"], resume.relative(project, project.decisions)), _ddrs(data["ddrs"]),
                         _prs(data["prs"], data["prs_why"], cited), _sessions(data["sessions"]),
                         _cost(data.get("cost")),
                         _journal(data["journal"], resume.relative(project, project.journal))) if p]
    header = _header(project, data)

    def sections() -> list[resume.Section]:
        return [s.section() for s in (header, *parts, _footer(generated, parts, budget))]

    if budget > 0:
        condense(parts, lambda: resume.tokens(resume.render(sections())) <= budget)
    return resume.render(resume.fit(sections(), budget, "the end (the oldest journal entries first)",
                                    "brain digest"))


def build(project: projects.Project, since: str = "last-week", until: str = "today", *, budget: int = BUDGET,
          offline: bool = False, now: datetime | None = None, today: date | None = None) -> str:
    return render(project, gather(project, since, until, offline=offline, today=today), budget=budget, now=now)


# --- written digests ---

def digest_dir(name: str) -> Path:
    return paths.brain_home() / DIGEST_DIR / name


def digest_path(name: str, w: Window) -> Path:
    return digest_dir(name) / f"{w.since}_{w.until}.md"


def write(name: str, data: dict, text: str) -> Path:
    f = digest_path(name, Window(data["since"], data["until"]))
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8", newline="\n")
    return f


def latest(name: str) -> Path | None:
    """The written digest whose window ends last (then starts last), its summary files left out."""
    d = digest_dir(name)
    found = [f for f in d.glob("*_*.md") if not f.name.endswith(SUMMARY)] if d.is_dir() else []
    return max(found, key=lambda f: tuple(reversed(f.stem.split("_", 1))), default=None)
