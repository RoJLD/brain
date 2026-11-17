"""brain audit's trend and milestone (brain.audit): the last completed ISO weeks re-measured at their end commit
with today's rules, and whether ms-brain-conformance is met."""

from __future__ import annotations

from datetime import date, timedelta

from . import audit_checks as checks
from . import inventory, projects
from .audit_checks import SEVERITIES
from .audit_measure import _parallel, measure

MILESTONE = "ms-brain-conformance"
STREAK = 4


# --- the trend ---

def week_ends(n: int, today: date) -> list[tuple[str, str]]:
    """The last ``n`` completed ISO weeks: (YYYY-Www, the Monday after it, 00:00 UTC)."""
    monday = today - timedelta(days=today.weekday())
    out = []
    for k in range(n, 0, -1):
        end = monday - timedelta(weeks=k - 1)
        y, w, _ = (end - timedelta(days=7)).isocalendar()
        out.append((f"{y}-W{w:02d}", f"{end.isoformat()}T00:00:00Z"))
    return out


def falling(debts: list[int]) -> int:
    """Week-on-week falls in a row ending at the last week: strictly lower, or zero; a flat week breaks it."""
    k = 0
    for i in range(len(debts) - 1, 0, -1):
        if debts[i] < debts[i - 1] or debts[i] == 0:
            k += 1
        else:
            break
    return k


def trend(p: projects.Project, cfgs: list[projects.Repo], refs: dict[str, str], n: int, today: date,
          only: set[str] | None = None, layered: set[str] | None = None, linked: dict | None = None,
          featured: bool | None = None, coverage: dict | None = None) -> dict:
    """Each of the last ``n`` completed weeks re-measured at its end commit with today's rules and registry (and
    today's code layers, ``layered``, the stores that take today's Doc and Test links, ``linked``, and today's
    Feature type, ``featured``, and today's coverage summaries, ``coverage``); a repo with no commit at some week end leaves the whole window (like-for-like)."""
    weeks = week_ends(n, today)
    live = [c for c in cfgs if c.name in refs]
    commits = dict(zip([c.name for c in live], _parallel(
        lambda c: inventory.week_commits(c.path, refs[c.name], [end for _, end in weeks]), live)))
    scope = [c for c in cfgs if c.name in commits and all(commits[c.name])]
    out = []
    for i, (label, end) in enumerate(weeks if scope else []):
        trees = dict(zip([c.name for c in scope], _parallel(
            lambda c, i=i: inventory.git_tree(c.path, commits[c.name][i]), scope)))
        res = measure(p, scope, trees, only, layered, linked=linked, featured=featured, coverage=coverage,
                      stale=False)
        out.append({"week": label, "end": end[:10], "debt": {s: res["counts"][s] for s in SEVERITIES}})
    return {"weeks": out, "repos": [c.name for c in scope],
            "left": sorted(c.name for c in cfgs if c not in scope)}


def _total(w: dict) -> int:
    return sum(w["debt"][s] for s in SEVERITIES)


def merge_trends(trends: dict[str, dict]) -> dict:
    """Projects' trends summed week by week, with each project's debt."""
    trends = {k: t for k, t in trends.items() if t["weeks"]}   # a project with no repo over the window: out
    first = next(iter(trends.values()), {"weeks": []})
    weeks = []
    for i, w in enumerate(first["weeks"]):
        debt = {s: sum(t["weeks"][i]["debt"][s] for t in trends.values()) for s in SEVERITIES}
        weeks.append({"week": w["week"], "end": w["end"], "debt": debt,
                      "by_project": {name: _total(t["weeks"][i]) for name, t in trends.items()}})
    return {"weeks": weeks, "falling": falling([_total(w) for w in weeks]), "projects": sorted(trends)}


def trend_line(t: dict) -> str:
    if not t["weeks"]:
        return "trend: not measured (no repo has a commit at the end of every week of the window)"
    parts = []
    for i, w in enumerate(t["weeks"]):
        if i:
            prev, cur = _total(t["weeks"][i - 1]), _total(w)
            parts.append(">" if cur < prev else "=" if cur == prev else "<")
        parts.append(f"W{w['week'][-2:]} {_total(w)}")
    k = falling([_total(w) for w in t["weeks"]])
    return f"trend (like-for-like debt): {' '.join(parts)}  falling {min(k, STREAK)} of {STREAK}"


def milestone(projs: list[dict], tr: dict | None) -> dict:
    """ms-brain-conformance is met when every registered repo was audited, P0 = P1 = 0, no pending check that would
    carry P0 or P1 remains and the last four completed weeks all fell. Never set here: the evidence is printed."""
    p0 = sum(p["counts"]["P0"] for p in projs)
    p1 = sum(p["counts"]["P1"] for p in projs)
    lost = [r["name"] for p in projs for r in p["repos"] if r.get("error")]
    lost += [f"{r['name']} ({x['owner']})" for p in projs for r in p["repos"] for x in r.get("not_measured", [])
             if x["check"] == "test.module"]   # its modules could not be read (a layout error, Python < 3.11)
    pending = checks.PENDING
    pend = sorted({k for k, v in pending.items() if v.blocks and v.run is None}
                  | {x["check"] for p in projs for r in p["repos"] for x in r.get("not_measured", [])
                     if x["check"] in pending and pending[x["check"]].blocks})   # a generator's check not run there
    k = tr["falling"] if tr and tr["weeks"] else None
    reasons = ([f"not audited: {', '.join(lost)}"] if lost else []) + [f"P0 {p0}, P1 {p1}"]
    reasons += [f"{len(pend)} P0/P1 checks not measured"] if pend else []
    reasons += [f"falling {min(k, STREAK)} of {STREAK}" if k is not None else "trend not measured (--trend)"]
    met = not lost and p0 == p1 == 0 and not pend and k is not None and k >= STREAK
    return {"id": MILESTONE, "met": met, "reasons": reasons, "pending": pend}
