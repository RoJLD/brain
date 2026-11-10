"""``brain status [--project p | --all] [--quick] [--json]``: each project's indicators on one screen, aggregated at
zero token (wi-brain-project-views, spec 2026-10-30 §3.14; Q3 A: ``brain status --project p`` or ``--all``).

Per project, from what the Brain already reads:

  items       the work items by status, the open ones (todo, doing, blocked) by priority, and the frontier: the todo
              items whose depends_on and gated_by targets are satisfied, with its P0/P1 part;
  decisions   the DDRs waiting on the owner (the blocking ones counted) and answered, to integrate; the items' open
              questions (``props.open``); the owner's queue by kind when brain.queue is there (wi-brain-human-queue);
  milestones  how many are reached, and each pending one with its items done out of its live items;
  audit       the findings by severity, measured as ``brain audit --json`` measures them (brain.audit);
  stacks      each stack's state as ``brain health`` prints it: OK, DOWN, STALE or OFF (brain.stacks);
  code index  each repo's state as ``brain index`` prints it: OK, STALE, NOT INDEXED, MISSING, ERROR (brain.codeindex);
  alerts      the open alerts by level, the first ones named, and the last notify pass (brain.alerts: the scheduler,
              the stacks, the code index, the audit debt, the project's alert events and files);
  records     the journals' last day, the records (DDR, SR, AR), the ledgers the registry names (size and last
              write), and the latest digest when brain.digest is there (wi-brain-digest);
  tokens      the last 7 days of its sessions in the token ledger (brain.usage, brain.cost): their cost at API
              prices, its distribution, the costliest items and phases (``--quick``: the ledger as it is, no scan);
  forecast    the nearest dated milestone's p10-p90 and the backlog's verdict (brain.forecast, 300 futures, saved;
              ``--quick``: the last forecast saved, invalidated once the open items moved by more than 20 %).

Once for all the projects shown, ``quota``: the plan's weekly window from the readings the sessions noted, the percent
at the reset at the last 24 h's pace and the advice (brain.quota; ``--quick``: without the live sessions and queue);
and ``probes``: this machine's dependency probes (brain.depprobes), run first so that the brain's alerts row counts
them (``--quick``: their last run), the row shown once one is declared here.

``--all`` adds the totals, the ids found in more than one store (``brain check --all`` fails on them), the projects
the brain reads and never writes (``access: read``, counted by name) and the tenant
mounts, counted and never read into (whether each one's contract export is there, not what it says). ``--quick``
skips what probes or measures (audit, stacks, code index, the scheduler): the files only. ``--json`` prints the data with stable keys
and no timestamp. Status reports and exits 0; ``brain check``, ``brain health`` and ``brain audit --fail-on`` fail.
``collect`` is the data function the HTML views read (wi-brain-html-views); the cockpit (brain.cockpit, brain tui)
reads its parts: ``frontier``, ``milestones``, ``queue_rows``, ``audit_of``, ``probed``, ``records_of``.
"""

from __future__ import annotations

import importlib
import json
import textwrap
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import (alerts, audit, codeindex, config, cost, forecast, graph, notes, projects, quiet, quota, records,
               resume, stacks, usage)

STATUS_ORDER = ("todo", "doing", "blocked", "done", "dropped")
QUICK = "skipped (--quick)"
WIDTH = 118


def _optional(name: str):
    """The module brain.<name> when it exists (built by a session running beside this one), else None."""
    try:
        return importlib.import_module(f".{name}", __package__)
    except ModuleNotFoundError as exc:
        if exc.name == f"{__package__}.{name}":
            return None
        raise


def _ordered(counts: Counter, first: tuple[str, ...]) -> dict[str, int]:
    """``counts`` with the keys of ``first`` in that order, then the others sorted ('none' last)."""
    rest = sorted(k for k in counts if k not in first and k != "none")
    return {k: counts[k] for k in (*first, *rest, "none") if counts.get(k)}


def _store(p: projects.Project) -> resume.Store:
    """Every store of ``p`` read as one (nodes by id, edges appended)."""
    nodes, edges = {}, []
    for s in p.stores:
        if (s / "nodes").is_dir():
            st = resume.Store.load(s)
            nodes.update(st.nodes)
            edges += st.edges
    return resume.Store(nodes, edges)


# --- the sections' data ---

def frontier(st: resume.Store) -> list[dict]:
    """The todo items whose depends_on and gated_by targets are all satisfied (the cockpit lists them)."""
    deps: dict[str, list[str]] = {}
    for e in st.edges:
        if e.get("type") in ("depends_on", "gated_by"):
            deps.setdefault(e["from"], []).append(e["to"])
    return [n for n in st.of_type("WorkItem") if n.get("status") == "todo"
            and all(st.status(t) in resume.SATISFIED for t in deps.get(n["id"], []))]


def items(st: resume.Store) -> dict:
    work = st.of_type("WorkItem")
    front = frontier(st)
    open_ = [n for n in work if n.get("status") in resume.WORK_OPEN]
    return {"total": len(work), "by_status": _ordered(Counter(str(n.get("status") or "none") for n in work),
                                                      STATUS_ORDER),
            "open_by_priority": _ordered(Counter(resume._priority(n) or "none" for n in open_),
                                         ("P0", "P1", "P2", "P3")),
            "frontier": len(front),
            "frontier_p0_p1": sum(1 for n in front if resume._priority(n) in resume.PRIORITIES)}


def milestones(st: resume.Store) -> dict:
    ms = [m for m in st.of_type("Milestone") if m.get("status") != "dropped"]
    pending = []
    for m in (m for m in ms if m.get("status") != "reached"):
        live = [i for i in st.milestone_items(m["id"]) if st.status(i) != "dropped"]
        pending.append({"id": m["id"], "title": str(m.get("title") or ""), "items": len(live),
                        "done": sum(1 for i in live if st.status(i) == "done")})
    return {"reached": sum(1 for m in ms if m.get("status") == "reached"), "pending": pending}


def _ddrs(root: Path) -> list[dict]:
    found = [graph.load_yaml_file(f)  # the DDRs only: records.load also parses every SR and AR
             for f in sorted((root / records.RECORDS_DIR / "ddr").glob("*.yaml"))]
    return [d for d in found if isinstance(d, dict) and d.get("id")]


def decisions_of(p: projects.Project, st: resume.Store, queue: dict | None = None) -> dict:
    ddrs = _ddrs(p.root)
    pend = [d for d in ddrs if d.get("status") == "pending"]
    out = {"pending": len(pend), "blocking": sum(1 for d in pend if d.get("blocking")),
           "answered": sum(1 for d in ddrs if d.get("status") == "answered"),
           "open_questions": sum(1 for n in st.of_type("WorkItem") if n.get("status") in resume.WORK_OPEN
                                 and (n.get("props") or {}).get("open"))}
    if queue is not None:
        out["queue"] = queue
    return out


def queue_rows(projs: list[projects.Project], every: bool, root: Path | None = None, **kw) -> list[dict]:
    """brain.queue.collect's rows for the projects in scope, called as brain queue calls it: the denials placed among
    every registered project, ``only`` the one in scope without --all; ``kw`` goes to collect; [] without it."""
    q = _optional("queue")
    if q is None or not hasattr(q, "collect"):
        return []
    return (q.collect([p for p in projs if p.root.is_dir()], **kw) if every
            else q.collect(list(projects.load(root).values()), only=projs[0], **kw) if projs else [])


def queues(projs: list[projects.Project], quick: bool, every: bool, root: Path | None = None) -> dict[str, dict]:
    """The owner's queue counted by kind for each project, and by band (``bands``: now, week, later), through
    brain.queue's data function when it is there: one transcript scan (none with --quick); {} without it."""
    rows = queue_rows(projs, every, root, with_graph=False, transcripts=not quick)
    return {r["project"]: {**(r.get("counts") or {}), **({"bands": r["bands"]} if r.get("bands") else {})}
            for r in rows if r.get("project")}


def audit_of(p: projects.Project, detail: int = 0) -> dict:
    """The findings by severity, measured as brain audit --json measures them (every repo of the project); with
    ``detail``, each repo's counts and the first ``detail`` findings, P0 first (the cockpit's audit panel)."""
    try:
        cfgs = projects.repos_of(p)
        trees, _, errors = audit.trees_now(cfgs)
        res = audit.measure(p, cfgs, trees)
    except (audit.AuditError, projects.RepoError) as exc:
        return {"error": str(exc)}
    out = {"counts": res["counts"], "repos": len(cfgs), "unreadable": sorted(errors)}
    if detail:
        out["by_repo"] = [{"repo": r["name"], "counts": r.get("counts") or {}} for r in res["repos"]]
        found = [{"repo": r["name"], **{k: f[k] for k in ("severity", "check", "unit", "why")}}
                 for r in res["repos"] for f in r.get("findings") or [] if f["severity"] in audit.SEVERITIES]
        out["top"] = sorted(found, key=lambda f: f["severity"])[:detail]
    return out


def stacks_of(p: projects.Project, reg: dict, off: dict | None = None) -> list[dict]:
    """Each of ``p``'s stacks and its state; ``off``: the stacks outside this machine's profile (OFF when not up)."""
    off = stacks.profile_off(reg) if off is None else off
    return [{"name": s.name, "state": state, "why": why}
            for s in reg.values() if s.project == p.name
            for state, why in [stacks.state(s, off[s.name]) if s.name in off else stacks.state(s)]]


def code_index_of(p: projects.Project, ix, repos: dict, rec: dict, entries) -> list[dict]:
    return [{"repo": r.name, "state": s.state, "why": s.why}
            for r in codeindex.of_project(repos, p.name).values() for s in [codeindex.state(ix, r, rec.get(r.name),
                                                                                             entries)]]


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix() if path.is_relative_to(root) else path.as_posix()


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts).date().isoformat()


def _ledger(path: Path) -> dict:
    """A ledger's lines and last write: a file, or a folder of files (monthly JSONL, say)."""
    files = sorted(f for f in path.rglob("*") if f.is_file()) if path.is_dir() else [path] if path.is_file() else []
    if not files:
        return {"lines": None, "last_write": None}
    return {"lines": sum(f.read_bytes().count(b"\n") for f in files),
            "last_write": _day(max(f.stat().st_mtime for f in files))}


def tenants_of(root: Path | None = None) -> list[dict]:
    """The registry's tenant mounts (spec-brain-hmaas §6), counted and never read into: each one's name and title, and
    whether its contract export is declared and found, with its last write. The export is not opened: reading it by
    its schema is wi-brain-tenant-export's."""
    out = []
    for m in projects.mounts(root).values():
        found = bool(m.export and m.export.is_file())
        out.append({"name": m.name, "title": m.title, "export": m.export.as_posix() if m.export else None,
                    "export_found": found, "export_written": _day(m.export.stat().st_mtime) if found else None})
    return out


def records_of(p: projects.Project) -> dict:
    base = p.root / records.RECORDS_DIR
    journals = [{"path": _rel(j, p.root), "exists": j.is_file(),
                 "last": notes.last_day(j.read_text(encoding="utf-8")) if j.is_file() else None} for j in p.journals]
    out = {"journals": journals,
           "records": {"ddr": len(list((base / "ddr").glob("*.yaml"))), "sr": len(list((base / "sr").rglob("*.yaml"))),
                       "ar": sum(f.read_bytes().count(b"\n") for f in (base / "ar").glob("*.jsonl"))}
           if base.is_dir() and not p.shares_root_with else None,   # the root's records: its owner's
           "ledgers": [{"name": k, "path": _rel(v, p.root), **_ledger(v)} for k, v in p.ledgers.items()]}
    d = _optional("digest")
    if d is not None and hasattr(d, "latest"):
        latest = d.latest(p.name)
        out["digest"] = latest.stem if latest else None
    return out


# --- one project, every project ---

def alerts_of(p: projects.Project, out: dict, stack_reg, sched: dict | None, last: dict) -> dict:
    """The project's open alerts (brain.alerts) from what this status measured; {"error": ...} on a bad alerts:."""
    def rows(key):
        return out.get(key) if isinstance(out.get(key), list) else None

    watched = {n for n, s in stack_reg.items() if s.watch} if isinstance(stack_reg, dict) else set()
    try:
        found = alerts.of_project(p, stacks_rows=rows("stacks"), index_rows=rows("code_index"),
                                  audit=out.get("audit") if "counts" in (out.get("audit") or {}) else None,
                                  sched=sched, watched=watched)
    except alerts.AlertsError as exc:
        return {"error": str(exc)}
    d = alerts.summary(found, (last.get(p.name) or {}).get("last_pass"))
    from . import schedule
    try:
        w = schedule.watch(schedule.parse(p))  # the dead-man of the alerts pass this project schedules here
    except schedule.ScheduleError:
        w = None  # brain check --all reports it
    if w:
        d["pass"] = w
    return d


def collect(p: projects.Project, *, quick: bool = False, stack_reg: dict | None = None, index: tuple | None = None,
            queue: dict | None = None, sched: dict | None = None) -> dict:
    """The status of one project (the TUI's and the HTML views' data). ``stack_reg`` (brain.stacks.load),
    ``index`` ((indexer, repos, record, GitNexus's entries), from brain.codeindex) and ``sched`` (the scheduler's
    tasks, brain.alerts.read_scheduler) are read once for every project; an Exception stands for a registry error."""
    out = {"project": p.name, "title": p.title, "root": str(p.root), "found": p.root.is_dir()}
    if not out["found"]:
        return out
    st = _store(p)
    out.update(items=items(st), decisions=decisions_of(p, st, queue), milestones=milestones(st))
    if quick:
        out.update(audit={"skipped": QUICK}, stacks={"skipped": QUICK}, code_index={"skipped": QUICK})
    else:
        out["audit"] = audit_of(p)
        out.update(probed(p, stack_reg, index))
    out["alerts"] = alerts_of(p, out, stack_reg, sched, alerts.state_load())
    out.update(records_of(p))
    out["tokens"] = cost.status_of(p, None, datetime.now(timezone.utc), quick=quick)
    out["forecast"] = forecast.status_of(p, None, datetime.now(timezone.utc), quick=quick)
    return out


def probed(p: projects.Project, stack_reg, index) -> dict:
    """{stacks, code_index}: each state of ``p``'s stacks and code index repos (an Exception stands for a registry
    error); ``stack_reg`` and ``index`` as ``_probes`` reads them."""
    return {"stacks": ({"error": str(stack_reg)} if isinstance(stack_reg, Exception)
                       else stacks_of(p, stack_reg or {})),
            "code_index": ({"error": str(index)} if isinstance(index, Exception)
                           else code_index_of(p, *index) if index and index[0] else [])}


def _probes(root: Path | None, quick: bool) -> tuple:
    if quick:
        return None, None
    try:
        stack_reg = stacks.load(root)
    except stacks.StackError as exc:
        stack_reg = exc
    try:
        ix, repos = codeindex.load(root)
        index = (ix, repos, codeindex.read_record(), codeindex.registry(ix) if ix and repos else None)
    except codeindex.CodeIndexError as exc:
        index = exc
    return stack_reg, index


def _bad(rows) -> list[dict]:
    return [r for r in rows if r.get("state") != "OK"] if isinstance(rows, list) else []


def total(data: list[dict]) -> dict:
    found = [d for d in data if d.get("found")]
    by_status, by_priority, findings = Counter(), Counter(), Counter()
    for d in found:
        by_status.update(d["items"]["by_status"])
        by_priority.update(d["items"]["open_by_priority"])
        findings.update((d.get("audit") or {}).get("counts") or {})
    return {"projects": len(data), "found": len(found),
            "items": {"total": sum(d["items"]["total"] for d in found),
                      "by_status": _ordered(by_status, STATUS_ORDER),
                      "open_by_priority": _ordered(by_priority, ("P0", "P1", "P2", "P3")),
                      "frontier": sum(d["items"]["frontier"] for d in found)},
            "decisions": {k: sum(d["decisions"][k] for d in found) for k in ("pending", "blocking", "answered",
                                                                              "open_questions")},
            "milestones": {"reached": sum(d["milestones"]["reached"] for d in found),
                           "pending": sum(len(d["milestones"]["pending"]) for d in found)},
            "audit": dict(findings),
            "alerts": {lvl: sum((d.get("alerts") or {}).get("counts", {}).get(lvl, 0) for d in found)
                       for lvl in reversed(alerts.LEVELS)},
            "stacks_not_ok": sum(len(_bad(d.get("stacks"))) for d in found),
            "code_index_not_ok": sum(len(_bad(d.get("code_index"))) for d in found)}


def _alert_configs(projs: list[projects.Project]) -> list:
    out = []
    for p in projs:
        try:
            out.append(alerts.config(p))
        except alerts.AlertsError:
            pass  # reported in the project's alerts row
    return out


def run(projs: list[projects.Project], *, every: bool = False, quick: bool = False, root: Path | None = None) -> dict:
    """{status: 1, projects: [...]}, with the totals and the ids shared across stores when ``every`` (--all)."""
    # this machine's dependency probes, run first: the brain's alerts row reads them
    from . import depprobes
    probes_ = depprobes.last() if quick else depprobes.run()
    stack_reg, index = _probes(root, quick)
    sched = {} if quick else alerts.read_scheduler(_alert_configs(projs))
    qs = queues(projs, quick, every, root)
    data = {"status": 1, "projects": [collect(p, quick=quick, stack_reg=stack_reg, index=index,
                                              queue=qs.get(p.name) if qs else None, sched=sched) for p in projs]}
    if every:
        data["total"] = total(data["projects"])
        data["ids"] = projects.collisions([p for p in projs if p.root.is_dir()])
        data["tenants"] = tenants_of(root)
        data["total"]["tenants"] = len(data["tenants"])
        data["read_only"] = [{"name": r.name, "title": r.title} for r in projects.readonly(root).values()]
        data["total"]["read_only"] = len(data["read_only"])
    fc = quota.status_of(projs, root, usage.now_utc(), quick=quick)
    data["quota"] = {k: v for k, v in fc.items() if k != "now"}
    data["quiet"] = quiet.summary(projs)
    data["probes"] = {k: probes_[k] for k in ("host", "at", "probes", "errors")}
    return data


# --- text ---

def queue_band(band: str) -> str:
    """A band's words (brain.queue.BAND_NAMES): now, this week, when you can."""
    q = _optional("queue")
    return getattr(q, "BAND_NAMES", {}).get(band, band) if q is not None else band


def _counts(d: dict) -> str:
    return ", ".join(f"{n} {k}" for k, n in d.items()) or "none"


def _states(rows, what: str) -> str:
    if isinstance(rows, dict):
        return rows.get("skipped") or f"error: {rows.get('error')}"
    if not rows:
        return f"no {what} declared"
    bad = _bad(rows)
    head = f"{len(rows) - len(bad)} of {len(rows)} OK"
    return head + ("; " + "; ".join(f"{r.get('name') or r.get('repo')} {r['state']}" + (f" ({r['why']})" if r["why"]
                                                                                           else "") for r in bad)
                   if bad else "")


def _audit(a: dict) -> str:
    if "counts" not in a:
        return a.get("skipped") or f"error: {a.get('error')}"
    c = a["counts"]
    line = ", ".join(f"{k} {c.get(k, 0)}" for k in (*audit.SEVERITIES, "info")) + f" ({a['repos']} repo(s)"
    return line + (f"; not read: {', '.join(a['unreadable'])})" if a.get("unreadable") else ")")


def _decisions(d: dict) -> str:
    line = (f"{d['pending']} waiting on {config.name_of()}" + (f" ({d['blocking']} blocking)" if d["blocking"] else "")
            + f", {d['answered']} answered to integrate, {d['open_questions']} open question(s) on items")
    if d.get("queue"):
        q = dict(d["queue"])
        b = q.pop("bands", None) or {}
        line += "; queue: " + _counts(q) + (" (" + ", ".join(f"{queue_band(k)} {n}" for k, n in b.items()) + ")"
                                            if any(b.values()) else "")
    return line


def _milestones(m: dict) -> str:
    pend = m["pending"]
    return f"{m['reached']} reached, {len(pend)} pending" + (": " + ", ".join(
        f"{x['id']} {x['done']}/{x['items']}" for x in pend) if pend else "")


def _records(d: dict) -> list[str]:
    rows = [("journal", "; ".join(f"{Path(x['path']).name} " + (f"last entry {x['last']}" if x["last"] else "no entry"
                                                                  if x["exists"] else "missing")
                                  for x in d["journals"]))]  # the name: brain projects shows the path
    if d.get("records"):
        r = d["records"]
        rows.append(("records", f"{r['ddr']} DDR, {r['sr']} SR, {r['ar']} AR"))
    for led in d["ledgers"]:
        size = f"{led['lines']} line(s), last write {led['last_write']}" if led["lines"] is not None else "missing"
        rows.append((f"ledger {led['name']}", f"{led['path']} {size}"))
    if "digest" in d:
        rows.append(("digest", d["digest"] or "none written (brain digest --write)"))
    return rows


def _tenants(rows: list[dict]) -> str:
    def export(t: dict) -> str:
        if t["export_found"]:
            return f"export written {t['export_written']}"
        return "export missing" if t["export"] else "no export declared"
    return f"{len(rows)} mounted, opaque (never read into): " + "; ".join(f"{t['name']} {export(t)}" for t in rows)


def _row(label: str, text: str) -> list[str]:
    """``  label      text``, the text wrapped under itself."""
    return textwrap.wrap(text, WIDTH, initial_indent=f"  {label:<11} ", subsequent_indent=" " * 14,
                         break_on_hyphens=False, break_long_words=False) or [f"  {label}"]


def render(data: dict) -> list[str]:
    lines = []
    if data.get("quiet") and quiet.line(data["quiet"]):
        lines.append(f"quiet: {quiet.line(data['quiet'])}")
    for d in data["projects"]:
        head = f"{d['project']} ({d['root']})" + (f": {d['title']}" if d.get("title") else "")
        lines.append(head if d["found"] else f"{head}: not found on this machine")
        if not d["found"]:
            continue
        it = d["items"]
        rows = [("items", f"{it['total']}: {_counts(it['by_status'])}; open by priority: "
                          f"{_counts(it['open_by_priority'])}"),
                ("frontier", f"{it['frontier']} startable, {it['frontier_p0_p1']} of them P0/P1"),
                ("decisions", _decisions(d["decisions"])), ("milestones", _milestones(d["milestones"])),
                ("audit", _audit(d["audit"])), ("stacks", _states(d["stacks"], "stack")),
                ("code index", _states(d["code_index"], "repo under code_index:")),
                ("alerts", alerts.status_line(d["alerts"])), *_records(d)]
        if "tokens" in d:
            t = d["tokens"]
            rows.append(("tokens", f"error: {t['error']}" if "error" in t
                         else f"{t['days']} d: {cost.summary_line(t)}"))
        if "forecast" in d:
            f = d["forecast"]
            rows.append(("forecast", f"error: {f['error']}" if "error" in f else f["line"]))
        lines += [x for k, v in rows for x in _row(k, v)]
    if "total" in data:
        t = data["total"]
        lines.append(f"all ({t['found']} of {t['projects']} project(s) found)")
        rows = [("items", f"{t['items']['total']}: {_counts(t['items']['by_status'])}; open by priority: "
                          f"{_counts(t['items']['open_by_priority'])}; frontier {t['items']['frontier']}"),
                ("decisions", f"{t['decisions']['pending']} waiting on {config.name_of()} "
                              f"({t['decisions']['blocking']} blocking), "
                              f"{t['decisions']['answered']} answered to integrate, {t['decisions']['open_questions']} "
                              "open question(s) on items"),
                ("milestones", f"{t['milestones']['reached']} reached, {t['milestones']['pending']} pending"),
                ("audit", _counts(t["audit"]) if t["audit"] else "not measured"),
                ("alerts", _counts({k: v for k, v in t["alerts"].items() if v}) + " open"
                           if any(t["alerts"].values()) else "none open"),
                ("not OK", f"{t['stacks_not_ok']} stack(s), {t['code_index_not_ok']} code index repo(s)")]
        ids = data["ids"]
        live = [c for c in ids["collisions"] if not c["waived"]]
        rows.append(("ids", f"{len(live)} shared by two stores or more, {len(ids['collisions']) - len(live)} waived, "
                            f"across {ids['stores']} store(s)" + ("; brain check --all lists them" if live else "")))
        if data.get("read_only"):
            rows.append(("read only", f"{len(data['read_only'])} (the brain reads them, never writes): "
                                      + ", ".join(r["name"] for r in data["read_only"])))
        if data.get("tenants"):
            rows.append(("tenants", _tenants(data["tenants"])))
        lines += [x for k, v in rows for x in _row(k, v)]
    if "quota" in data:
        q = data["quota"]
        lines += _row("quota", f"error: {q['error']}" if "error" in q else q["line"])
    if (data.get("probes") or {}).get("probes") or (data.get("probes") or {}).get("errors"):
        from . import depprobes
        lines += _row("probes", depprobes.status_line(data["probes"]))
    return lines


def render_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True)
