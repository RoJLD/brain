"""``brain usage`` and ``brain cost``: the token ledger (brain.usage) joined to the backlog, at zero token
(wi-brain-token-ledger, wi-brain-cost-estimation; the owner, 2026-11-02: know what costs the most, estimate, then
understand why a task cost more or less than its estimate).

A session serves the items it closed (``brain item close``), the items whose ``pr`` prop names one of its pull
requests, else the items its title names, else (a sub-session) the first item its brief names; its cost is shared
equally among them. An item's actual: the cost, output tokens, active time and sessions of the sessions that served
it (their subagents included), its context peak (the largest) against its brief's budget, and their token-free
signals. Its task class is its briefs' (the owner's sub-session rule: trivial, standard, strategic), its theme and
milestone the graph's, its kind the words of its title (spec, review, fix, build).

  brain usage    the window's sessions by project, item, PR, class, kind, theme, milestone, model, phase, tool,
                 command, skill, session, family (a session and the sub-sessions it started), workflow (each workflow
                 run: its agents, phases and the session that launched it), agent (the subagents' and workflow agents'
                 labels), day or week: the totals, their share, and the distribution per unit (median, p25-p75, p90),
                 not only the mean; the split of the cost between the main threads, the plain subagents and the
                 workflow agents; the repeated 3-step sequences (script candidates); the cost of a session's start
                 (its first messages).
  cost estimate  an item or a brief's text: the finished items most alike (the same class and theme, else class and
                 milestone, class and kind, class, all; the nearest half by brief size when there are enough), their
                 median and p25-p75 range of cost, output, context peak, active time and sessions, times the
                 class's calibration; ``--record`` writes it on the item (props.cost_estimate) when the work starts,
                 beside the brief's context budget.
  cost review    a finished item's actual against its recorded estimate (else the estimate the history before it
                 gives: a backtest) and its brief's budget; the gap explained by the signals that differ from the
                 class's finished items (phase shares, review rounds, merges and conflicts, reloads, compactions,
                 thrash, questions and waits, plan growth, sessions); ``--record`` writes props.cost_review.
  cost audit     the window's finished items reviewed, those off by more than ``OFF`` either way and why, the
                 calibration per class (median actual / backtest estimate: what the next estimates are multiplied
                 by), the costliest sessions and the script candidates; ``--write`` keeps it in
                 <BRAIN_HOME>/usage/<project>/audit-<since>_<until>.md.
"""

from __future__ import annotations

import json
import math
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from . import config, graph, paths, projects, queue, resume, usage

MIN_SIMILAR = 3
OFF = 1.5  # an actual above OFF x its estimate, or below estimate / OFF, is off
SEQ_SESSIONS = 3  # a sequence in this many sessions is a script candidate
ORCHESTRATOR = 2  # a session that started this many sub-sessions coordinates: it serves no item itself
# Steps that read, filter or edit: a sequence needs two other steps to be a script candidate (grep > head > sed is
# reading, not a procedure)
TRIVIAL_STEPS = {"grep", "head", "tail", "sed", "cat", "cut", "ls", "wc", "sort", "uniq", "awk", "find", "tr", "xargs",
                 "python", "python3", "py", "select-string", "get-content", "get-childitem", "select-object", "tee",
                 "Read", "Edit", "Write", "Grep", "Glob", "MultiEdit", "diff", "jq", "test", "[", "nl", "file"}
TOP = 10
CLASSES = ("trivial", "standard", "strategic")
SESSION_DIMS = ("project", "class", "kind", "model", "pr")
ITEM_DIMS = ("item", "theme", "milestone")
PART_DIMS = {"phase": "phases", "tool": "tools", "command": "commands", "skill": "skills"}
TIME_DIMS = ("day", "week")
AGENT_DIMS = ("workflow", "agent")  # a workflow run, an agent's label (wi-brain-usage-workflow-agents)
DIMS = ("summary", *SESSION_DIMS, *ITEM_DIMS, *PART_DIMS, "session", "family", *AGENT_DIMS, *TIME_DIMS, "sequences")
METRICS = ("cost", "output", "peak", "active_s", "sessions")
# The signals explain() names; {owner}: config.owner_of(), read when it runs.
EXPLAIN = (("review_rounds", "review rounds"), ("merges", "merge, rebase or pull commands"),
           ("conflicts", "merge conflicts"), ("rebases", "rebases"), ("compactions", "compactions"),
           ("reloads", "context reloads"), ("thrash", "failing-command streaks"), ("asks", "questions to {owner}"),
           ("wait_s", "seconds waiting for a message"), ("sessions", "sessions"), ("plan_growth", "plan steps added"),
           ("files_edited", "files edited"), ("prompts", "prompts"))
_PR_RE = re.compile(r"([A-Za-z0-9_.-]+)?\s*#(\d+)")
_EST_RE = re.compile(r"(\w+)=([^\s\[]+)")


@dataclass
class Item:
    id: str
    project: str
    title: str
    status: str
    theme: str
    milestone: str
    kind: str
    props: dict
    store: Path | None = None
    sessions: list[tuple[dict, float]] = field(default_factory=list)  # (row, share)

    @property
    def done_day(self) -> str:
        d = str(self.props.get("done") or "")[:10]
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            return d
        return max((r.get("end") or "")[:10] for r, _ in self.sessions) if self.sessions else ""

    @property
    def first_start(self) -> str:
        return min((r.get("start") or "") for r, _ in self.sessions) if self.sessions else ""


def _short_pr(pr: str) -> str:
    """``acme/brain#63`` -> ``brain#63``, lower case."""
    repo, _, n = pr.rpartition("#")
    return f"{repo.rsplit('/', 1)[-1].lower()}#{n}"


def item_prs(pr_prop: str) -> list[str]:
    """``brain #63, #64`` -> [``brain#63``, ``brain#64``]."""
    out, repo = [], ""
    for m in _PR_RE.finditer(str(pr_prop or "")):
        repo = (m.group(1) or repo).lower()
        if repo:
            out.append(f"{repo}#{m.group(2)}")
    return out


class Ledger:
    """The ledger's rows (the projects placed by the registry) joined to the projects' backlogs."""

    def __init__(self, rows: list[dict], projs: list[projects.Project], placer=None) -> None:
        placer = placer or queue.Placer(projs)
        self.rows = []
        for r in rows:
            r = dict(r)
            r["project"] = (placer(r["folder"]) if r.get("folder") else "") or queue.OUTSIDE
            self.rows.append(r)
        self.parent = usage.link_families(self.rows)
        self.items: dict[str, Item] = {}
        for p in projs:
            store = resume.graph_store(p) if p.root.is_dir() else None
            if not store:
                continue
            st = resume.Store.load(store)
            part_of = {e["from"]: e["to"] for e in st.edges if e.get("type") == "part_of"
                       and str(e.get("to", "")).startswith("ms-")}
            for n in st.of_type("WorkItem"):
                props = n.get("props") or {}
                self.items[n["id"]] = Item(n["id"], p.name, " ".join(str(n.get("title") or "").split()),
                                           str(n.get("status") or ""), str(props.get("theme") or ""),
                                           part_of.get(n["id"], ""),
                                           usage.kind_of(str(n.get("title") or "").split(":")[0]), props, store)
        for r in self.rows:  # a sub-session is credited to the project of the item its brief names, wherever it ran
            b = r.get("brief") or {}
            named = [i for i in b.get("items") or [] if i in self.items] if b.get("side") else []
            if named:
                r["project"] = self.items[named[0]].project
        by_pr: dict[str, list[str]] = {}
        for it in self.items.values():
            for pr in item_prs(it.props.get("pr", "")):
                by_pr.setdefault(pr, []).append(it.id)
        for r in self.rows:
            ids = self.items_of(r, by_pr)
            r["served"] = ids
            for i in ids:
                self.items[i].sessions.append((r, 1 / len(ids)))

    def items_of(self, r: dict, by_pr: dict[str, list[str]]) -> list[str]:
        known = self.items
        if len(r.get("spawned") or []) >= ORCHESTRATOR and not r.get("title_items"):
            return []  # coordination: brain usage --by family shows it with its sub-sessions
        ids = [i for i in r.get("closed") or [] if i in known]
        ids += [i for pr in r.get("prs") or [] for i in by_pr.get(_short_pr(pr), []) if i not in ids]
        if not ids:
            ids = [i for i in r.get("title_items") or [] if i in known]
        b = r.get("brief") or {}
        if not ids and b.get("side"):
            ids = [i for i in b.get("items") or [] if i in known][:1]
        return list(dict.fromkeys(ids))

    def window(self, since: str, until: str) -> list[dict]:
        return [r for r in self.rows if usage.in_window(r, since, until)]


# --- an item's actual ---

def _class_of(rows) -> str:
    c = Counter((r.get("brief") or {}).get("class") or "" for r in rows)
    c.pop("", None)
    return c.most_common(1)[0][0] if c else ""


def actual(it: Item) -> dict:
    rows = [r for r, _ in it.sessions]
    sig = Counter()
    for r in rows:
        for k, v in (r.get("signals") or {}).items():
            if isinstance(v, (int, float)) and k not in ("plan_first", "plan_last"):
                sig[k] += v
        s = r.get("signals") or {}
        sig["plan_growth"] += max(0, (s.get("plan_last") or 0) - (s.get("plan_first") or 0))
    sig["sessions"] = len(rows)
    phases: dict[str, float] = {}
    for r, share in it.sessions:
        for ph, v in (r.get("phases") or {}).items():
            phases[ph] = phases.get(ph, 0.0) + share * (v.get("cost") or 0.0)
    budgets = [(r.get("brief") or {}).get("budget") for r in rows]
    return {"id": it.id, "project": it.project, "title": it.title, "status": it.status, "theme": it.theme,
            "milestone": it.milestone, "kind": it.kind, "class": _class_of(rows),
            "cost": round(sum(s * (r.get("cost") or 0) for r, s in it.sessions), 4),
            "output": int(sum(s * ((r.get("tokens") or {}).get("output", 0)
                                   + (r.get("sub_tokens") or {}).get("output", 0)) for r, s in it.sessions)),
            "active_s": int(sum(s * (r.get("active_s") or 0) for r, s in it.sessions)),
            "peak": max(((r.get("context") or {}).get("peak") or 0 for r in rows), default=0),
            "sessions": len(rows), "budget": max((b for b in budgets if b), default=None),
            "chars": max(((r.get("brief") or {}).get("chars") or 0 for r in rows), default=0),
            "phases": {k: round(v, 4) for k, v in phases.items()}, "signals": dict(sig),
            "first_start": it.first_start, "done_day": it.done_day,
            "session_ids": [r["session_id"] for r in rows]}


def history(led: Ledger, before: str = "") -> list[dict]:
    """The finished items with at least one session, closed before ``before`` (an ISO time; '' for all)."""
    out = []
    for it in led.items.values():
        if it.status != "done" or not it.sessions:
            continue
        a = actual(it)
        last_end = max((r.get("end") or "") for r, _ in it.sessions)
        if before and not last_end < before:
            continue
        if a["cost"] > 0:
            out.append(a)
    return sorted(out, key=lambda a: a["id"])


# --- estimates ---

def _similar(pool: list[dict], target: dict) -> tuple[str, list[dict]]:
    cls = target.get("class") or ""
    tiers = (("class+theme", lambda a: a["class"] == cls and target.get("theme") and a["theme"] == target["theme"]),
             ("class+milestone", lambda a: a["class"] == cls and target.get("milestone")
              and a["milestone"] == target["milestone"]),
             ("class+kind", lambda a: a["class"] == cls and a["kind"] == target.get("kind")),
             ("class", lambda a: a["class"] == cls), ("all", lambda a: True))
    for name, ok in tiers:
        found = [a for a in pool if ok(a)]
        if len(found) >= MIN_SIMILAR or name == "all":
            chars = target.get("chars") or 0
            if chars and len(found) >= 2 * MIN_SIMILAR:  # the nearest half by brief size
                found = sorted(found, key=lambda a: (abs(math.log((a["chars"] or 1) / chars)), a["id"]))
                found = found[:max(MIN_SIMILAR, len(found) // 2)]
            return name, found
    return "all", []


def raw_estimate(pool: list[dict], target: dict) -> dict:
    basis, found = _similar(pool, target)
    out = {"basis": basis, "n": len(found), "similar": [(a["id"], a["cost"]) for a in found]}
    for m in METRICS:
        q = usage.quantiles([a[m] for a in found if a.get(m) is not None])
        out[m] = {k: q[k] for k in ("p25", "median", "p75")} if q["n"] else None
    return out


def backtests(led: Ledger, metric: str = "cost") -> list[dict]:
    """Every finished item against the estimate the items finished before it started would have given, in
    ``metric`` (the cost; the active time for brain.forecast's shared error)."""
    out = []
    for a in history(led):
        pool = history(led, before=a["first_start"])
        est = raw_estimate(pool, a)
        if est[metric] and est[metric]["median"]:
            out.append({"id": a["id"], "class": a["class"], "actual": a[metric], "estimate": est[metric]["median"],
                        "ratio": a[metric] / est[metric]["median"], "basis": est["basis"], "n": est["n"]})
    return out


def calibration(tests: list[dict]) -> dict[str, dict]:
    """{class: {factor, n}}: the median ratio actual / backtest estimate of the class's items (3 at least; the
    '*' key: every item's), what the next estimates are multiplied by."""
    out = {}
    groups: dict[str, list[float]] = {"*": [t["ratio"] for t in tests]}
    for t in tests:
        groups.setdefault(t["class"] or "", []).append(t["ratio"])
    for k, ratios in groups.items():
        if len(ratios) >= MIN_SIMILAR:
            out[k] = {"factor": round(statistics.median(ratios), 3), "n": len(ratios)}
    return out


def target_of(led: Ledger, what: str, cls: str | None = None) -> dict:
    """An item id (its graph props, its sessions so far) or a brief's text, as the estimator's target."""
    it = led.items.get(what.strip())
    if it:
        rows = [r for r, _ in it.sessions]
        budgets = [(r.get("brief") or {}).get("budget") for r in rows if (r.get("brief") or {}).get("budget")]
        return {"id": it.id, "project": it.project, "title": it.title, "class": cls or str(
            it.props.get("task_class") or "") or _class_of(rows) or "standard", "theme": it.theme,
                "milestone": it.milestone, "kind": it.kind, "budget": max(budgets) if budgets else None,
                "chars": max(((r.get("brief") or {}).get("chars") or 0 for r in rows), default=0), "store": it.store}
    text = what
    ids = [i for i in usage._ID_RE.findall(text) if i in led.items]
    ref = led.items[ids[0]] if ids else None
    m_class, m_budget = usage._CLASS_RE.search(text), usage._BUDGET_RE.search(text)
    budget = (int(float(m_budget.group(1).replace(",", ".")) * (1e3 if m_budget.group(2).lower() == "k" else 1e6))
              if m_budget else None)
    return {"id": ref.id if ref else "", "project": ref.project if ref else "", "title": " ".join(text.split())[:80],
            "class": cls or (m_class.group(1).lower() if m_class else "standard"),
            "theme": ref.theme if ref else "", "milestone": ref.milestone if ref else "",
            "kind": usage.kind_of(text), "budget": budget, "chars": len(text), "store": ref.store if ref else None}


def estimate(led: Ledger, target: dict, today: str) -> dict:
    pool = [a for a in history(led) if a["id"] != target.get("id")]
    est = raw_estimate(pool, target)
    cal = calibration(backtests(led))
    c = cal.get(target.get("class") or "") or cal.get("*") or {"factor": 1.0, "n": 0}
    est["calibration"] = c
    for m in ("cost", "output", "active_s"):  # the size of the work; not the context peak or the sessions
        if est[m]:
            est[m] = {k: v * c["factor"] for k, v in est[m].items()}
    est.update(target={k: v for k, v in target.items() if k != "store"}, day=today)
    return est


def estimate_text(est: dict) -> str:
    """The one line kept in props.cost_estimate (read back by cost review)."""
    t = est["target"]

    def rng(m: str, fmt) -> str:
        q = est.get(m)
        return f"{fmt(q['median'])} [{fmt(q['p25'])}-{fmt(q['p75'])}]" if q else "-"

    return (f"{est['day']} class={t['class']} basis={est['basis']} n={est['n']} "
            f"usd={rng('cost', lambda x: f'{x:.2f}')} out={rng('output', usage.ktok)} "
            f"active={rng('active_s', lambda x: f'{x / 3600:.1f}h')} peak={rng('peak', usage.ktok)} "
            f"budget={usage.ktok(t.get('budget')) if t.get('budget') else '-'} cal=x{est['calibration']['factor']:.2f}")


def parse_estimate(text: str) -> dict:
    """props.cost_estimate back: {day, class, basis, n, usd, ...} (usd as a number)."""
    out: dict = {"day": str(text or "")[:10]}
    for k, v in _EST_RE.findall(str(text or "")):
        out[k] = v
    try:
        out["usd"] = float(out["usd"])
    except (KeyError, ValueError):
        out.pop("usd", None)
    return out


def render_estimate(est: dict) -> list[str]:
    t = est["target"]
    head = t["id"] or f"brief: {t['title']}"
    lines = [f"brain cost estimate {head} (class {t['class']}"
             + "".join(f", {k} {t[k]}" for k in ("theme", "milestone", "kind") if t.get(k)) + ")"]
    if not est["n"]:
        return lines + ["  no finished item with sessions in the ledger yet: nothing to estimate from"]
    sim = ", ".join(f"{i} ({usage.usd(c)})" for i, c in est["similar"][:6])
    lines.append(f"  basis {est['basis']}: {est['n']} finished item(s): {sim}" + (" ..." if est["n"] > 6 else ""))
    cal = est["calibration"]
    fmt = {"cost": usage.usd, "output": usage.ktok, "peak": usage.ktok, "active_s": usage.hours,
           "sessions": lambda x: f"{x:.0f}"}
    for m in METRICS:
        q = est.get(m)
        if not q:
            continue
        line = f"  {m:<9} {fmt[m](q['median']):>8}  (p25-p75 {fmt[m](q['p25'])} - {fmt[m](q['p75'])})"
        if m == "cost" and cal["n"]:
            line += f"  x{cal['factor']:.2f} calibration ({cal['n']} backtests)"
        if m == "peak" and t.get("budget"):
            line += f"  against the brief's budget {usage.ktok(t['budget'])}"
        lines.append(line)
    return lines


# --- reviews ---

def _median_of(pool: list[dict], key) -> float:
    xs = [key(a) for a in pool]
    return statistics.median(xs) if xs else 0.0


def explain(a: dict, pool: list[dict]) -> list[str]:
    """Why ``a`` cost what it did, against ``pool`` (its class's finished items): the phases whose share of the cost
    differs most, then the signals at 1.5 times their median or more (or less), largest gap first."""
    out: list[tuple[float, str]] = []
    total = a["cost"] or 1e-9
    for ph in usage.PHASES:
        share = (a["phases"].get(ph) or 0) / total
        med = _median_of(pool, lambda x: (x["phases"].get(ph) or 0) / (x["cost"] or 1e-9))
        excess = (share - med) * total
        if abs(share - med) >= 0.08 and abs(excess) >= 0.5:
            sign = "+" if excess > 0 else "-"
            out.append((abs(excess), f"{sign} {ph} {usage.usd(a['phases'].get(ph) or 0)} ({share:.0%} of the cost; "
                                     f"median {med:.0%})"))
    for key, label in EXPLAIN:
        label = label.replace("{owner}", config.owner_of()) if "{owner}" in label else label
        v = a["signals"].get(key, 0)
        med = _median_of(pool, lambda x: x["signals"].get(key, 0))
        if v >= max(1.0, 1.5 * med) and v > med:
            out.append((v / max(med, 1.0), f"+ {v:,.0f} {label} (median {med:,.0f})"))
        elif med >= 1 and v <= med / 1.5:
            out.append((med / max(v, 1.0) * 0.5, f"- {v:,.0f} {label} (median {med:,.0f})"))
    return [t for _, t in sorted(out, key=lambda x: -x[0])]


def review(led: Ledger, item_id: str) -> dict:
    it = led.items.get(item_id)
    if not it:
        raise KeyError(item_id)
    a = actual(it)
    rec = parse_estimate(it.props.get("cost_estimate", "")) if it.props.get("cost_estimate") else {}
    pool = history(led, before=a["first_start"]) if a["first_start"] else []
    back = raw_estimate([x for x in pool if x["id"] != a["id"]], a)
    est_usd = rec.get("usd") or (back["cost"]["median"] if back["cost"] else None)
    same = [x for x in history(led) if x["id"] != a["id"] and x["class"] == a["class"]] or \
        [x for x in history(led) if x["id"] != a["id"]]
    return {"item": a, "recorded": rec, "backtest": {"usd": back["cost"]["median"] if back["cost"] else None,
                                                     "basis": back["basis"], "n": back["n"]},
            "estimate": est_usd, "source": "recorded" if rec.get("usd") else "backtest" if est_usd else "",
            "ratio": a["cost"] / est_usd if est_usd else None,
            "budget_use": a["peak"] / a["budget"] if a.get("budget") else None,
            "why": explain(a, same), "pool": len(same)}


def verdict(ratio: float | None) -> str:
    if ratio is None:
        return "no estimate"
    return "over" if ratio > OFF else "under" if ratio < 1 / OFF else "within"


def review_text(rv: dict, today: str) -> str:
    a = rv["item"]
    est = f" est={rv['estimate']:.2f} x{rv['ratio']:.2f} ({rv['source']})" if rv["estimate"] else ""
    peak = f" peak={usage.ktok(a['peak'])}/{usage.ktok(a['budget'])}" if a.get("budget") else ""
    why = "; ".join(rv["why"][:4])
    return f"{today} usd={a['cost']:.2f}{est}{peak} sessions={a['sessions']}" + (f" why: {why}" if why else "")


def render_review(rv: dict) -> list[str]:
    a = rv["item"]
    head = f"{a['id']} ({a['class'] or 'no class'}, {a['kind']}): {usage.usd(a['cost'])}"
    if rv["estimate"]:
        head += (f" against the {rv['source']} estimate {usage.usd(rv['estimate'])}: x{rv['ratio']:.2f}, "
                 f"{verdict(rv['ratio'])}")
    else:
        head += ", no estimate (no finished item before it)"
    lines = [head]
    if rv["recorded"]:
        lines.append(f"  recorded {rv['recorded'].get('day')}: basis {rv['recorded'].get('basis', '-')}, "
                     f"n {rv['recorded'].get('n', '-')}")
    use = f" of the brief's {usage.ktok(a['budget'])} ({rv['budget_use']:.0%})" if rv["budget_use"] else ""
    lines.append(f"  context peak {usage.ktok(a['peak'])}{use}; {a['sessions']} session(s), "
                 f"{usage.hours(a['active_s'])} active, {usage.ktok(a['output'])} output tokens")
    if rv["why"]:
        lines.append(f"  why, against {rv['pool']} finished item(s) of its class:")
        lines += [f"    {w}" for w in rv["why"][:8]]
    return lines


# --- brain usage ---

def _session_rows(rows: list[dict], dim: str) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for r in rows:
        if dim == "pr":
            keys = [_short_pr(p) for p in r.get("prs") or []] or ["(none)"]
        elif dim == "class":
            keys = [(r.get("brief") or {}).get("class") or "(no brief)"]
        else:
            keys = [r.get(dim) or "(none)"]
        for k in keys:
            groups.setdefault(k, []).append(r)
    return groups


def table_of(led: Ledger, rows: list[dict], dim: str, since: str, until: str) -> list[dict]:
    """The rows of one ``--by``: each group's total, share and distribution (per session, or per item)."""
    total = sum(r.get("cost") or 0 for r in rows) or 1e-9
    out = []
    if dim in SESSION_DIMS:
        for k, rs in _session_rows(rows, dim).items():
            q = usage.quantiles([r.get("cost") or 0 for r in rs])
            out.append({"key": k, "share": q["total"] / total, "unit": "session", **q,
                        "output": sum((r.get("tokens") or {}).get("output", 0) for r in rs),
                        "active_s": sum(r.get("active_s") or 0 for r in rs)})
    elif dim in ITEM_DIMS:
        ids = {i for r in rows for i in r.get("served") or []}
        acts = [actual(led.items[i]) for i in ids]
        groups: dict[str, list[dict]] = {}
        for a in acts:
            groups.setdefault(a["id"] if dim == "item" else a[dim] or "(none)", []).append(a)
        for k, acs in groups.items():
            q = usage.quantiles([a["cost"] for a in acs])
            row = {"key": k, "share": q["total"] / total, "unit": "item", **q,
                   "output": sum(a["output"] for a in acs), "active_s": sum(a["active_s"] for a in acs)}
            if dim == "item":
                a = acs[0]
                row.update(title=a["title"], cls=a["class"], status=a["status"], sessions=a["sessions"],
                           peak=a["peak"], budget=a["budget"])
            out.append(row)
    elif dim in PART_DIMS:
        field_ = PART_DIMS[dim]
        per: dict[str, list[float]] = {}
        calls: Counter = Counter()
        for r in rows:
            for k, v in (r.get(field_) or {}).items():
                per.setdefault(k, []).append(v.get("cost") or 0.0)
                calls[k] += v.get("calls") or v.get("messages") or 0
        for k, xs in per.items():
            q = usage.quantiles(xs)
            out.append({"key": k, "share": q["total"] / total, "unit": "session", **q, "calls": calls[k]})
    elif dim == "session":
        for r in rows:
            out.append({"key": r["session_id"][:8], "total": r.get("cost") or 0, "share": (r.get("cost") or 0) / total,
                        "project": r["project"], "cls": (r.get("brief") or {}).get("class") or "-",
                        "kind": r.get("kind"), "title": r.get("title") or r.get("branch") or "",
                        "items": r.get("served") or [], "peak": (r.get("context") or {}).get("peak"),
                        "budget": (r.get("brief") or {}).get("budget"), "active_s": r.get("active_s") or 0,
                        "parent": led.parent.get(r["session_id"], "")[:8]})
    elif dim == "family":
        ids = {r["session_id"] for r in rows}

        def root(sid: str) -> str:
            seen = set()
            while sid in led.parent and sid not in seen:
                seen.add(sid)
                sid = led.parent[sid]
            return sid

        fam: dict[str, list[dict]] = {}
        for r in rows:
            fam.setdefault(root(r["session_id"]), []).append(r)
        titles = {r["session_id"]: r.get("title") or r.get("branch") or "" for r in led.rows}
        for k, rs in fam.items():
            q = usage.quantiles([r.get("cost") or 0 for r in rs])
            out.append({"key": k[:8], "share": q["total"] / total, "unit": "session", **q,
                        "title": titles.get(k, ""), "in_window": k in ids})
    elif dim == "workflow":
        for r in rows:
            for run, w in ((r.get("agents") or {}).get("workflows") or {}).items():
                if not usage.in_window(w, since, until):
                    continue
                phases = sorted((w.get("phases") or {}).items(), key=lambda kv: -(kv[1].get("cost") or 0))
                out.append({"key": run, "total": w.get("cost") or 0.0, "share": (w.get("cost") or 0.0) / total,
                            "agents": w.get("agents") or 0, "session": r["session_id"][:8], "project": r["project"],
                            "title": r.get("title") or r.get("branch") or "", "start": w.get("start") or "",
                            "phases": [[k, v.get("count") or 0, round(v.get("cost") or 0.0, 4)] for k, v in phases],
                            "output": w.get("output") or 0})
    elif dim == "agent":
        per: dict[str, dict] = {}

        def add(label: str, v: dict, kind: str, run: str = "") -> None:
            a = per.setdefault(label, {"total": 0.0, "n": 0, "kinds": set(), "runs": set()})
            a["total"] += v.get("cost") or 0.0
            a["n"] += v.get("count") or 0
            a["kinds"].add(kind)
            if run:
                a["runs"].add(run)

        for r in rows:
            ag = r.get("agents") or {}
            for label, v in (ag.get("subagents") or {}).items():
                add(label, v, "subagent")
            for run, w in (ag.get("workflows") or {}).items():
                if usage.in_window(w, since, until):
                    for label, v in (w.get("labels") or {}).items():
                        add(label, v, "workflow", run)
        for k, a in per.items():
            out.append({"key": k, "total": round(a["total"], 4), "share": a["total"] / total, "n": a["n"],
                        "kind": "+".join(sorted(a["kinds"])), "runs": len(a["runs"])})
    elif dim in TIME_DIMS:
        buckets: dict[str, dict] = {}
        for r in rows:
            for d, v in (r.get("days") or {}).items():
                if (since and d < since) or (until and d >= until):
                    continue
                key = d if dim == "day" else _week(d)
                b = buckets.setdefault(key, {"total": 0.0, "output": 0, "messages": 0, "sessions": set(),
                                             "projects": Counter()})
                b["total"] += v.get("cost") or 0
                b["output"] += v.get("output") or 0
                b["messages"] += v.get("messages") or 0
                b["sessions"].add(r["session_id"])
                b["projects"][r["project"]] += v.get("cost") or 0
        for k, b in buckets.items():
            out.append({"key": k, "total": round(b["total"], 4), "share": b["total"] / total, "output": b["output"],
                        "messages": b["messages"], "sessions": len(b["sessions"]),
                        "top": b["projects"].most_common(1)[0][0] if b["projects"] else ""})
        return sorted(out, key=lambda x: x["key"])
    return sorted(out, key=lambda x: (-x["total"], x["key"]))


def _week(day: str) -> str:
    y, w, _ = datetime.fromisoformat(day).isocalendar()
    return f"{y}-W{w:02d}"


def sequences(rows: list[dict], min_sessions: int = SEQ_SESSIONS) -> list[dict]:
    """The 3-step sequences repeated in ``min_sessions`` sessions or more, costliest first: script candidates."""
    agg: dict[str, dict] = {}
    for r in rows:
        for k, (n, c) in (r.get("ngrams") or {}).items():
            a = agg.setdefault(k, {"key": k, "count": 0, "total": 0.0, "sessions": 0})
            a["count"] += n
            a["total"] += c
            a["sessions"] += 1
    out = [a for a in agg.values() if a["sessions"] >= min_sessions
           and sum(1 for step in a["key"].split(" > ") if step not in TRIVIAL_STEPS) >= 2]
    return sorted(out, key=lambda a: (-a["total"], a["key"]))


def agents_split(rows: list[dict], since: str = "", until: str = "") -> dict:
    """Whose the sessions' cost is: the main threads', the plain subagents' and the workflow agents' (with the count
    of the runs that have a day in [since, until) and of their agents), from the rows' ``main_cost`` and ``agents``; a
    row scanned before ``agents`` (SCAN_V 2, its transcript gone) has all its subagents' cost plain."""
    out = {"main": 0.0, "subagents": {"cost": 0.0, "count": 0}, "workflows": {"cost": 0.0, "runs": 0, "agents": 0}}
    for r in rows:
        c = r.get("cost") or 0.0
        main = r["main_cost"] if isinstance(r.get("main_cost"), (int, float)) else c
        ag = r.get("agents")
        wf = 0.0
        for w in ((ag or {}).get("workflows") or {}).values():
            wf += w.get("cost") or 0.0
            if usage.in_window(w, since, until):
                out["workflows"]["runs"] += 1
                out["workflows"]["agents"] += w.get("agents") or 0
        out["main"] += main
        out["workflows"]["cost"] += wf
        out["subagents"]["cost"] += max(0.0, c - main - wf)
        plain = ag.get("subagents") if isinstance(ag, dict) else r.get("subagents")
        out["subagents"]["count"] += sum(v.get("count") or 0 for v in (plain or {}).values())
    out["main"] = round(out["main"], 4)
    out["subagents"]["cost"] = round(out["subagents"]["cost"], 4)
    out["workflows"]["cost"] = round(out["workflows"]["cost"], 4)
    return out


def report(led: Ledger, since: str, until: str, by: str, plans=None) -> dict:
    rows = led.window(since, until)
    total = sum(r.get("cost") or 0 for r in rows)
    tokens = Counter()
    for r in rows:
        for k in ("input", "output", "cache_read", "cache_write"):
            tokens[k] += (r.get("tokens") or {}).get(k, 0) + (r.get("sub_tokens") or {}).get(k, 0)
    days = sorted({d for r in rows for d in r.get("days") or {} if (not since or d >= since)
                   and (not until or d < until)})
    start = usage.quantiles([(r.get("start_cost") or {}).get("cost") or 0 for r in rows])
    rep = {"since": since, "until": until, "by": by, "sessions": len(rows), "cost": round(total, 4),
           "tokens": dict(tokens), "plans": sorted({usage.plan_of(d, plans) for d in days}),
           "unpriced": sum(r.get("unpriced") or 0 for r in rows), "start": start,
           "agents": agents_split(rows, since, until)}
    dims = ("project", "item", "class", "phase", "tool", "command") if by == "summary" else (by,)
    rep["tables"] = {d: (sequences(rows) if d == "sequences" else table_of(led, rows, d, since, until)) for d in dims}
    if by == "summary":
        if rep["agents"]["workflows"]["runs"]:
            rep["tables"]["workflow"] = table_of(led, rows, "workflow", since, until)
        rep["tables"]["sequences"] = sequences(rows)
    return rep


def _pct(x: float) -> str:
    return f"{x:.0%}"


def render_report(rep: dict, top: int = TOP) -> list[str]:
    win = f"{rep['since'] or 'the start'} to {rep['until'] or 'now'}"
    t = rep["tokens"]
    lines = [f"brain usage: {rep['sessions']} session(s) from {win}: {usage.usd(rep['cost'])} at API prices "
             f"(plan {', '.join(p for p in rep['plans'] if p) or '-'}); input {usage.ktok(t.get('input'))}, output "
             f"{usage.ktok(t.get('output'))}, cache read {usage.ktok(t.get('cache_read'))}, cache write "
             f"{usage.ktok(t.get('cache_write'))}" + (f"; {rep['unpriced']} message(s) of unknown models unpriced"
                                                     if rep["unpriced"] else "")]
    a = rep.get("agents")
    if a and (a["subagents"]["cost"] or a["workflows"]["cost"]):
        whole = rep["cost"] or 1e-9
        lines.append(f"  whose: main threads {usage.usd(a['main'])} ({_pct(a['main'] / whole)}), subagents "
                     f"{usage.usd(a['subagents']['cost'])} ({_pct(a['subagents']['cost'] / whole)}, "
                     f"{a['subagents']['count']} agent(s)), workflows {usage.usd(a['workflows']['cost'])} "
                     f"({_pct(a['workflows']['cost'] / whole)}, {a['workflows']['runs']} run(s), "
                     f"{a['workflows']['agents']} agent(s))")
    s = rep["start"]
    if s["n"]:
        lines.append(f"  a session's start ({usage.START_MESSAGES} first messages): median {usage.usd(s['median'])}, "
                     f"p90 {usage.usd(s['p90'])}")
    for dim, rows in rep["tables"].items():
        lines += ["", *_render_table(dim, rows, top)]
    return lines


def _dist(r: dict) -> str:
    if r.get("n", 0) < 2:
        return ""
    return f"median {usage.usd(r['median'])} (p25-p75 {usage.usd(r['p25'])}-{usage.usd(r['p75'])}, " \
           f"p90 {usage.usd(r['p90'])})"


def _render_table(dim: str, rows: list[dict], top: int) -> list[str]:
    shown = rows[:top or None]
    more = f" (top {top} of {len(rows)})" if top and len(rows) > top else ""
    if dim == "sequences":
        lines = [f"Script candidates: 3-step sequences in {SEQ_SESSIONS}+ sessions{more}"]
        lines += [f"  {usage.usd(r['total']):>9} {r['count']:>5}x {r['sessions']:>3} sess  {r['key']}" for r in shown]
        return lines if rows else lines + ["  none"]
    if dim in TIME_DIMS:
        lines = [f"By {dim}"]
        lines += [f"  {r['key']:<10} {usage.usd(r['total']):>9} {_pct(r['share']):>4}  {r['sessions']:>3} sess  "
                  f"{r['messages']:>5} msg  out {usage.ktok(r['output']):>5}  top {r['top']}" for r in rows]
        return lines
    if dim == "workflow":
        lines = [f"By workflow run{more}: its agents, the session that launched it"]
        for r in shown:
            ph = ", ".join(f"{k} {n} {usage.usd(c)}" for k, n, c in r["phases"][:4])
            lines.append(f"  {r['key'][:18]:<18} {usage.usd(r['total']):>9} {_pct(r['share']):>4}  {r['agents']:>3} "
                         f"agent(s)  <{r['session']} {r['start'][:10]}  {ph}  {r['title'][:40]}".rstrip())
        return lines if rows else lines + ["  none"]
    if dim == "agent":
        lines = [f"By agent label{more}: the subagents and the workflow agents"]
        lines += [f"  {str(r['key'])[:40]:<40} {usage.usd(r['total']):>9} {_pct(r['share']):>4}  n {r['n']:>3}  "
                  f"{r['kind']}" + (f", {r['runs']} run(s)" if r["runs"] else "") for r in shown]
        return lines if rows else lines + ["  none"]
    if dim == "session":
        lines = [f"By session{more}"]
        for r in shown:
            budget = f"/{usage.ktok(r['budget'])}" if r.get("budget") else ""
            items = ",".join(r["items"][:2])
            lines.append(f"  {r['key']} {usage.usd(r['total']):>9} {_pct(r['share']):>4}  {r['project'][:12]:<12} "
                         f"{r['cls'][:9]:<9} {usage.ktok(r['peak']):>5}{budget:<6} {usage.hours(r['active_s']):>6}  "
                         + (f"<{r['parent']} " if r["parent"] else "") + f"{items + ' ' if items else ''}"
                         f"{r['title'][:60]}")
        return lines
    unit = rows[0].get("unit", "session") if rows else "session"
    lines = [f"By {dim}{more}" + (f": per {unit}" if dim not in PART_DIMS else ": per session using it")]
    for r in shown:
        extra = ""
        if dim == "item":
            budget = f"/{usage.ktok(r['budget'])}" if r.get("budget") else ""
            extra = f" {r['cls'] or '-'} {r['status']} {r['sessions']} sess peak {usage.ktok(r['peak'])}{budget}"
        elif dim in PART_DIMS:
            extra = f" {r.get('calls', 0)} call(s)" if dim != "phase" else f" {r.get('calls', 0)} msg"
        elif dim == "family":
            extra = f" {r['title'][:50]}"
        lines.append(f"  {str(r['key'])[:40]:<40} {usage.usd(r['total']):>9} {_pct(r['share']):>4}  "
                     f"n {r.get('n', 1):>3}{extra}  {_dist(r)}".rstrip())
    return lines


# --- the audit ---

def audit(led: Ledger, since: str, until: str, top: int = TOP) -> dict:
    tests = backtests(led)
    cal = calibration(tests)
    done = [a for a in history(led) if (not since or a["done_day"] >= since) and (not until or a["done_day"] < until)]
    reviews = [review(led, a["id"]) for a in done]
    off = [rv for rv in reviews if verdict(rv["ratio"]) in ("over", "under")]
    rows = led.window(since, until)
    errs = [abs(math.log(t["ratio"])) for t in tests if t["ratio"] > 0]
    return {"since": since, "until": until, "reviews": reviews, "off": off, "calibration": cal,
            "backtests": {"n": len(tests), "within": sum(1 for t in tests if verdict(t["ratio"]) == "within"),
                          "median_factor": round(math.exp(statistics.median(errs)), 3) if errs else None},
            "costliest": table_of(led, rows, "session", since, until)[:top],
            "phases": table_of(led, rows, "phase", since, until),
            "sequences": sequences(rows)[:top], "cost": round(sum(r.get("cost") or 0 for r in rows), 4),
            "sessions": len(rows)}


def render_audit(au: dict, project: str, generated: str) -> str:
    win = f"{au['since'] or 'the start'} to {au['until'] or 'now'}"
    bt = au["backtests"]
    lines = [f"# Cost audit, {project}: {win}", "",
             f"Generated {generated} by `brain cost audit` from the token ledger (brain.usage), at zero token. "
             f"{au['sessions']} session(s), {usage.usd(au['cost'])} at API prices.", "",
             "## Estimates against actuals", ""]
    if bt["n"]:
        lines.append(f"Backtests (each finished item against what the items finished before it predicted): {bt['n']}, "
                     f"{bt['within']} within x{OFF}; the typical error is x{bt['median_factor']}.")
    lines.append("")
    if not au["reviews"]:
        lines.append("No item finished in the window.")
    for rv in sorted(au["reviews"], key=lambda r: -(abs(math.log(r["ratio"])) if r["ratio"] else 0)):
        mark = verdict(rv["ratio"])
        lines.append(f"- **{rv['item']['id']}** ({mark}): " + render_review(rv)[0].split(": ", 1)[1])
        lines += [f"  {x.strip()}" for x in render_review(rv)[1:]]
    lines += ["", "## Calibration (median actual / estimate, applied to the next estimates)", ""]
    for k, c in sorted(au["calibration"].items()):
        lines.append(f"- {'every class' if k == '*' else k or 'no class'}: x{c['factor']} over {c['n']} item(s)")
    if not au["calibration"]:
        lines.append(f"- not enough finished items yet ({MIN_SIMILAR} per class)")
    lines += ["", "## Where the cost went", ""]
    lines += [f"- {r['key']}: {usage.usd(r['total'])} ({_pct(r['share'])})" for r in au["phases"]]
    lines += ["", "## Costliest sessions", ""]
    lines += [f"- {r['key']} {usage.usd(r['total'])} {r['project']} {r['cls']}: {r['title'][:80]}"
              for r in au["costliest"]]
    lines += ["", "## Script candidates (3-step sequences repeated across sessions)", ""]
    lines += [f"- `{r['key']}`: {r['count']} times in {r['sessions']} sessions, {usage.usd(r['total'])}"
              for r in au["sequences"]] or ["- none"]
    return "\n".join(lines) + "\n"


def audit_path(project: str, since: str, until: str) -> Path:
    return paths.brain_home() / "usage" / project / f"audit-{since or 'start'}_{until or 'now'}.md"


# --- brain status and brain digest ---

STATUS_DAYS = 7


def summary_of(led: Ledger, name: str, since: str, until: str = "", top: int = 3) -> dict:
    """One project's sessions in [since, until): their cost and distribution, the costliest items (their cost so
    far), the phases' shares and the script candidates; what brain status and brain digest show."""
    rows = [r for r in led.window(since, until) if r["project"] == name]
    q = usage.quantiles([r.get("cost") or 0 for r in rows])
    return {"since": since, "until": until, "sessions": len(rows), "cost": q["total"], "median": q.get("median"),
            "p90": q.get("p90"),
            "items": [[r["key"], round(r["total"], 2)] for r in table_of(led, rows, "item", since, until)[:top]],
            "phases": [[r["key"], round(r["share"], 3)] for r in table_of(led, rows, "phase", since, until)[:top]],
            "candidates": [[r["key"], r["sessions"], round(r["total"], 2)] for r in sequences(rows)[:top]]}


def summary_line(s: dict) -> str:
    if not s.get("sessions"):
        return "no session in the token ledger"
    items = ", ".join(f"{i} {usage.usd(c)}" for i, c in s["items"])
    phases = ", ".join(f"{p} {x:.0%}" for p, x in s["phases"])
    return (f"{usage.usd(s['cost'])} at API prices over {s['sessions']} session(s), median {usage.usd(s['median'])}, "
            f"p90 {usage.usd(s['p90'])}" + (f"; costliest items {items}" if items else "")
            + (f"; {phases}" if phases else "") + " (brain usage)")


def status_of(p: projects.Project, root: Path | None, now: datetime, quick: bool = False) -> dict:
    """The last ``STATUS_DAYS`` days of ``p``'s sessions; --quick reads the ledger as it is (no scan)."""
    try:
        led = load([p], root, refresh=not quick)
    except (OSError, ValueError) as exc:
        return {"error": str(exc)}
    since = str((now - timedelta(days=STATUS_DAYS)).date())
    return {"days": STATUS_DAYS, **summary_of(led, p.name, since)}


# --- the commands ---

def load(projs: list[projects.Project], root: Path | None = None, refresh: bool = True) -> Ledger:
    """The ledger brought up to date (``refresh``) and joined to ``projs``' backlogs; the registry places the
    sessions' folders."""
    rows, _ = usage.update() if refresh else (usage.load(), 0)
    try:
        registry = list(projects.load(root).values())
    except (OSError, ValueError):
        registry = []
    return Ledger(list(rows.values()), projs, queue.Placer(registry + list(projs)))


def scoped(led: Ledger, projs: list[projects.Project], every: bool) -> Ledger:
    if not every:
        names = {p.name for p in projs}
        led.rows = [r for r in led.rows if r["project"] in names]
    return led


def record(it_store: Path | None, item_id: str, key: str, text: str) -> None:
    if not it_store:
        raise graph.GraphError(f"{item_id}: no graph store to record {key} in")
    graph.set_item(it_store, item_id, [f"{key}={text}"])


def as_json(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True, default=str)
