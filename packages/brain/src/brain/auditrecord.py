"""The cost audit's weekly record (``brain cost audit --write``; the owner's weekly cost audit, spec-brain-cost): the
series a KPI reads week by week, and the line ``brain digest`` names the latest audit with. Standard library only, at
zero token.

  context    :func:`context_of`: a window's sessions against their context, from the token ledger's rows (brain.usage:
             ``context.peak``, ``brief.budget``): how many had a brief's budget, how many peaked past 80 % and 100 %
             of it, how many peaked above :data:`CEILING` (the context a brief starts a session under,
             brain.brief.CEILING) and their cost at API prices: the before and after of the ceiling.
  record     :func:`audit_record`: one JSON line (``v: 1``) appended to ``<BRAIN_HOME>/usage/<project>/audits.jsonl``
             (:func:`append_record`, under the folder's lock like every ledger, never rewritten): when and over which
             window the audit ran, its sessions and cost, the estimates' error (the backtests, how many within x1.5,
             their share, the typical factor; the window's finished items and how many were off) and the context
             counts. The audit of one window written twice leaves two lines: the last one wins.
  series     :func:`series`: the series a KPI reads, oldest first: the ``v: 1`` lines alone (a higher ``v`` is
             skipped), one per window, the last line of a window winning (:func:`window_of`: its ``since`` and its
             end, ``until`` or else the day of ``at``; a rerun the same day over an open window replaces the
             earlier line, a rerun another day covers another window and is its own line). :func:`audit_records`
             is the raw log: every line that is a JSON object, as written.
  latest     :func:`latest_audit`: the last record, else the newest ``audit-*.md`` alone (an audit written before the
             records); :func:`latest_audit_line` says it in one line (a record of a higher ``v``: its file alone).

A torn line, a line that is not a JSON object or a byte that is not UTF-8 is skipped, never fatal.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import paths, usage

CEILING = 400_000
AUDITS = "audits.jsonl"


def _dict(v) -> dict:
    return v if isinstance(v, dict) else {}


def _num(v) -> float:
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def context_of(rows: list[dict], ceiling: int = CEILING) -> dict:
    """The sessions against their context: those whose brief gave a budget (``brief.budget``), how many peaked past
    80 % and past 100 % of it, and those that peaked above ``ceiling`` with their cost at API prices; a row without a
    peak or a budget counts nowhere."""
    peaks = [(_num(_dict(r.get("context")).get("peak")), _num(_dict(r.get("brief")).get("budget")), r) for r in rows]
    use = [p / b for p, b, _ in peaks if b > 0]
    over = [r for p, _, r in peaks if p > ceiling]
    return {"ceiling": ceiling, "briefed": len(use), "past_80": sum(1 for u in use if u >= 0.8),
            "past_100": sum(1 for u in use if u >= 1), "over_ceiling": len(over),
            "over_ceiling_cost": round(sum(_num(r.get("cost")) for r in over), 2)}


def context_line(c: dict) -> str:
    return (f"- {c['briefed']} session(s) with a brief's context budget: {c['past_80']} passed 80 % of it, "
            f"{c['past_100']} passed 100 %; {c['over_ceiling']} session(s) peaked above {usage.ktok(c['ceiling'])} "
            f"({usage.usd(c['over_ceiling_cost'])} at API prices)")


def audit_record(au: dict, project: str, at: str, path: Path | str = "") -> dict:
    """The audit's line in ``audits.jsonl``: when (``at``, UTC ISO) and over which window it ran, its sessions and
    cost, the estimates' error (the backtests, how many within x1.5, brain.cost.OFF, their share, the typical
    factor; the window's finished items and how many were off) and its context counts (:func:`context_of`)."""
    bt = au["backtests"]
    return {"v": 1, "at": at, "project": project, "since": au["since"], "until": au["until"], "path": str(path),
            "sessions": au["sessions"], "cost": round(au["cost"], 2),
            "estimates": {"backtests": bt["n"], "within": bt["within"],
                          "share_within": round(bt["within"] / bt["n"], 3) if bt["n"] else None,
                          "typical_factor": bt["median_factor"], "items": len(au["reviews"]), "off": len(au["off"])},
            "context": au.get("context") or context_of([])}


def audits_path(project: str) -> Path:
    return paths.brain_home() / "usage" / project / AUDITS


def append_record(project: str, rec: dict) -> Path:
    """Append ``rec`` to the project's ``audits.jsonl`` (one line, never rewritten: a log of the usage store, kept,
    appended under the folder's lock by brain.timing.append_text like every ledger); its path."""
    from . import timing  # here: only a write needs the lock
    out = audits_path(project)
    timing.append_text(out, json.dumps(rec, sort_keys=True) + "\n")
    return out


def audit_records(project: str) -> list[dict]:
    """The project's audit records as written, oldest first (the raw log: :func:`series` is what a KPI reads); a
    line that is not a JSON object, or that holds a byte that is not UTF-8, is skipped."""
    try:
        data = audits_path(project).read_bytes()
    except OSError:
        return []
    out = []
    for raw in data.splitlines():
        try:
            rec = json.loads(raw.decode("utf-8"))
        except ValueError:   # a torn line, or a byte that is not UTF-8 (UnicodeDecodeError is a ValueError)
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def window_of(rec: dict) -> tuple[str, str, str]:
    """The window a record covers, its key in :func:`series`: its project, its ``since`` and its end (``until``,
    else the day of ``at``: an open window ends the day the audit ran)."""
    return (str(rec.get("project") or ""), str(rec.get("since") or ""),
            str(rec.get("until") or str(rec.get("at") or "")[:10]))


def series(project: str) -> list[dict]:
    """The series a KPI reads, oldest first: the ``v: 1`` records alone (a line of a higher ``v`` is skipped), one
    per window (:func:`window_of`), the last line of a window winning, in the place of its first line."""
    last: dict[tuple[str, str, str], dict] = {}
    for rec in audit_records(project):
        if rec.get("v") == 1:
            last[window_of(rec)] = rec   # a key written again keeps its first place, takes the last line
    return list(last.values())


def latest_audit(project: str) -> dict | None:
    """The latest audit of ``project``: its last record in ``audits.jsonl``, else the newest ``audit-*.md`` (by
    mtime) as ``{"path": ...}`` alone; None when none was written."""
    recs = audit_records(project)
    if recs:
        return recs[-1]
    try:
        mds = sorted(audits_path(project).parent.glob("audit-*.md"), key=lambda q: q.stat().st_mtime)
    except OSError:
        return None
    return {"path": str(mds[-1])} if mds else None


def latest_audit_line(rec: dict | None) -> str:
    """One line naming the latest audit, for brain digest; empty without one."""
    if not rec:
        return ""
    if rec.get("v") != 1 or not isinstance(rec.get("estimates"), dict):   # a newer record: its file alone
        return f"Latest cost audit: {rec.get('path')}."
    from .cost import OFF  # here: brain.cost imports this module
    e, c = _dict(rec.get("estimates")), _dict(rec.get("context"))
    share = e.get("share_within")
    err = (f"typical estimate error x{e.get('typical_factor')}, {share:.0%} within x{OFF}"
           if isinstance(share, (int, float)) and not isinstance(share, bool) else "no backtest yet")
    ctx = (f"; {c.get('past_100', 0)} of {c.get('briefed', 0)} briefed session(s) past their budget, "
           f"{c.get('over_ceiling', 0)} above {usage.ktok(_num(c.get('ceiling')) or CEILING)}" if c else "")
    return (f"Latest cost audit ({rec.get('since') or 'the start'} to {rec.get('until') or 'now'}, written "
            f"{str(rec.get('at') or '')[:10]}): {err}{ctx}" + (f" ({rec['path']})." if rec.get("path") else "."))


