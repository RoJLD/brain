"""Backfill the records from the transcripts already on this machine (``brain record backfill``), at zero token.

For each main transcript under the projects folder (``paths.projects_dir``) whose session started in [since, until):
- its ARs: first the local ledger's (the hooks' live capture, with every commit's SHA), then the transcript's and its
  subagents' (``actions.from_transcript``: pushes, pull requests, and the commits the repos' history confirms; a
  subagent's type goes to ``session.agent``). An AR already recorded is skipped: same id, or same tool call, kind,
  branch and PR (a push the hook keyed by its SHA and the transcript by its tool call). So is an AR of an unpublished
  repo (neither registered nor with a pull request: a scratch or test repo, a clone of a local folder);
- its SR (``transcript.SessionStats``, subagents' tokens included), written ``closed`` with the session's ARs, the
  items they and its ``brain item`` commands touched, its DDRs and its SessionEnd reason, once the transcript has been
  quiet for ``quiet_hours`` (a live session's SR waits for a later run). An SR already in records/sr is kept; with
  ``update``, one whose transcript grew since is rewritten, keeping its summary when it differs from its title and
  every id it listed.
Every record is secret-scanned and validated before it is written; a second run on the same transcripts writes
nothing.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import actions, paths, projects, records, transcript

QUIET_HOURS = 12
_ITEM_RE = re.compile(r"^(wi|ms|spec)-[a-z0-9-]+$")
_TS_TYPES = ("user", "assistant", "attachment", "system")  # the records SessionStats takes its times from


def first_ts(path: Path) -> str:
    """The time of a transcript's first timed record (the SR's start), '' when it has none."""
    for rec, _ in transcript.iter_records(path):
        if rec.get("type") in _TS_TYPES and rec.get("timestamp"):
            return rec["timestamp"]
    return ""


def main_transcripts(since: str = "", until: str = "") -> list[tuple[str, Path]]:
    """(start, path) of the main transcripts whose session started in [since, until), oldest first."""
    root = paths.projects_dir()
    out = []
    for f in root.glob("*/*.jsonl") if root.is_dir() else []:
        start = first_ts(f)
        if start and (not since or start >= since) and (not until or start < until):
            out.append((start, f))
    return sorted(out)


def known_repos(root: Path) -> list[Path]:
    """The work trees of the registered projects' repos (roots, production checkouts, repos and code_index entries),
    where the commits of a removed scratchpad worktree are looked for."""
    out: list[Path] = []
    for p in projects.load(root).values():
        folders = [p.root, *p.production]
        for e in [*(p.repos if isinstance(p.repos, list) else []), *p.code_index]:
            rel = e.get("path") if isinstance(e, dict) else e
            if rel:
                folders.append(Path(os.path.normpath(p.root / str(rel))))
        for d in folders:
            top = actions.git(d, "rev-parse", "--show-toplevel") if d.is_dir() else ""
            if top and Path(top) not in out:
                out.append(Path(top))
    return out


def _fingerprint(ar: dict) -> tuple | None:
    """What one action is, whatever its id: its tool call, kind, branch and PR (None without a tool call)."""
    if not ar.get("tool_use_id"):
        return None
    pr = ar.get("pr") or {}
    return (ar["tool_use_id"], ar["kind"], ar.get("branch", ""), pr.get("number"), pr.get("action"),
            ar.get("sha", "") if ar["kind"] in ("commit", "adr") else "", (ar.get("adr") or {}).get("id"))


def _end_reasons() -> dict[str, str]:
    """The last SessionEnd reason of each session, from the ledger's events."""
    out = {}
    for f in sorted(paths.ledger_dir().glob("events-*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("event") == "session_end" and ev.get("session_id") and ev.get("reason"):
                out[ev["session_id"]] = ev["reason"]
    return out


def _quiet_since(stats: transcript.SessionStats, path: Path) -> datetime | None:
    last = transcript.parse_ts(stats.last_ts)
    try:
        mtime = datetime.fromtimestamp(os.path.getmtime(path), timezone.utc)
    except OSError:
        return last
    return max(last, mtime) if last else mtime


def _merge(old: dict, new: dict) -> dict:
    """The rewritten SR of ``update``: the new numbers, the old summary when it was written by hand, every id."""
    if old.get("summary") and old.get("summary") != old.get("title"):
        new["summary"] = old["summary"]
    for k in ("actions", "items", "ddrs"):
        ids = list(dict.fromkeys((old.get(k) or []) + (new.get(k) or [])))
        if ids:
            new[k] = sorted(ids) if k != "items" else ids
    return new


def run(root: Path, since: str = "", until: str = "", quiet_hours: float = QUIET_HOURS, subagents: bool = True,
        ledger: bool = True, update: bool = False, dry_run: bool = False,
        now: datetime | None = None) -> dict[str, Counter]:
    """Backfill; the counts per month (of the SR's start, of the AR's time): sr, sr-kept, sr-live, sr-stale,
    sr-updated, ar-<kind>, ar-known, ar-unpublished."""
    now = now or datetime.now(timezone.utc)
    report: dict[str, Counter] = defaultdict(Counter)
    found = main_transcripts(since, until)
    refused: list[records.Bad] = []
    recs = records.load(root, refused)
    have_ids = {a["id"] for _, a in recs["ar"]} | records.ar_ids(root)   # a newer brain's lines included
    refused_files = {b.where for b in refused}
    have_fp = {fp for _, a in recs["ar"] if (fp := _fingerprint(a))}
    by_session: dict[str, list[dict]] = defaultdict(list)
    for _, a in recs["ar"]:
        by_session[a["session"]["id"]].append(a)
    srs = {sr.get("session_id"): (f, sr) for f, sr in recs["sr"]}

    def add(ars: list[dict]) -> None:
        fresh = []
        for a in sorted(ars, key=lambda r: (r["at"], r["id"])):
            fp = _fingerprint(a)
            if a.get("repo") and a["repo"] not in published:
                report[a["at"][:7]]["ar-unpublished"] += 1
                continue
            if a["id"] in have_ids or (fp and fp in have_fp):
                report[a["at"][:7]]["ar-known"] += 1
                continue
            fresh.append(a)
            have_ids.add(a["id"])
            if fp:
                have_fp.add(fp)
        written = [records.validate("ar", a) for a in fresh] if dry_run else records.append_ars(root, fresh, set())
        for a in written:
            report[a["at"][:7]][f"ar-{a['kind']}"] += 1
            by_session[a["session"]["id"]].append(a)

    # ARs: the ledger first (live capture, richer), then each transcript and its subagents
    sessions = {}
    stats_of = {}
    for start, path in found:
        if subagents:
            main, subs, n_subs = transcript.session_stats(path)
        else:
            main, subs, n_subs = transcript.SessionStats(), None, 0
            main.feed_file(path)
        sid = main.session_id or path.stem
        sessions[sid] = path
        stats_of[sid] = (main, subs, n_subs)
    found_ars = []
    if ledger:
        found_ars.append([a for a in records.ledger_records("ar") if a.get("session", {}).get("id") in sessions
                          or ((not since or a.get("at", "") >= since) and (not until or a.get("at", "") < until))])
    repos = known_repos(root)
    recorded = {a["sha"] for ars in by_session.values() for a in ars if a["kind"] == "commit" and a.get("sha")}
    recorded |= {a["sha"] for ars in found_ars for a in ars if a["kind"] == "commit" and a.get("sha")}
    history = actions.History(repos, recorded=recorded)
    for sid, path in sessions.items():
        ars = actions.from_transcript(path, history=history)
        if subagents:
            for f in transcript.subagent_files(path):
                ars += actions.from_transcript(f, agent=transcript.agent_type(f), history=history)
        found_ars.append(ars)
    # a published repo: a registered one, or one with a pull request; a scratch or test repo's commits are left out
    candidates = [a for ars in [*by_session.values(), *found_ars] for a in ars]
    published = {history.name(r) for r in repos} | {a["repo"] for a in candidates if a["kind"] == "pr" and a.get("repo")}
    for ars in found_ars:
        add(ars)

    # SRs
    ddrs_by: dict[str, list[str]] = defaultdict(list)
    for d in records.ledger_records("ddr"):
        ddrs_by[(d.get("asked") or {}).get("by", "")].append(d["id"])
    for _, d in recs["ddr"]:
        for owner in ((d.get("asked") or {}).get("by"), (d.get("links") or {}).get("session")):
            if owner:
                ddrs_by[owner].append(d["id"])
    reasons = _end_reasons()
    for sid, path in sessions.items():
        main, subs, n_subs = stats_of[sid]
        month = (main.first_ts or "")[:7]
        quiet = _quiet_since(main, path)
        if quiet and (now - quiet).total_seconds() < quiet_hours * 3600:
            report[month]["sr-live"] += 1
            continue
        old = srs.get(sid)
        if old and not (update and (old[1].get("end") or "") < main.last_ts):
            report[month]["sr-stale" if (old[1].get("end") or "") < main.last_ts else "sr-kept"] += 1
            continue
        ars = by_session.get(sid, [])
        items = [i for a in ars for i in a.get("items", []) if _ITEM_RE.match(i)]
        sr = main.record(path, status="closed", extra_items=items, actions=[a["id"] for a in ars],
                         ddrs=ddrs_by.get(sid), subagents=subs, subagent_count=n_subs,
                         end_reason=reasons.get(sid, ""))
        if not old and records.record_path(root, "sr", sr) in refused_files:
            report[month]["sr-refused"] += 1      # a newer brain's SR, or an unreadable one: never replaced
            continue
        carry: frozenset[str] = frozenset()
        if old:
            sr, carry = records.keep_unknown("sr", old[1], _merge(old[1], sr))
        sr = records.validate("sr", sr, carry)
        if not dry_run:
            if old and records.record_path(root, "sr", sr) != old[0]:
                old[0].unlink()
            records.write(root, "sr", sr, replace=bool(old))
        report[month]["sr-updated" if old else "sr"] += 1
    return dict(report)


def _written(c: Counter) -> dict[str, int]:
    return {k[3:]: n for k, n in sorted(c.items()) if k.startswith("ar-") and k not in ("ar-known", "ar-unpublished")}


def format_report(report: dict[str, Counter], dry_run: bool = False) -> str:
    lines = []
    total: Counter = Counter()
    for month in sorted(report):
        c = report[month]
        total.update(c)
        kinds = ", ".join(f"{k} {n}" for k, n in _written(c).items())
        lines.append(f"{month}: {c['sr']} SR written, {c['sr-updated']} updated, {c['sr-kept']} kept, "
                     f"{c['sr-stale']} stale, {c['sr-live']} live; {sum(_written(c).values())} AR written"
                     + (f" ({kinds})" if kinds else "") + f", {c['ar-known']} already recorded"
                     + (f", {c['ar-unpublished']} of unpublished repos left out" if c["ar-unpublished"] else ""))
    n_ar = sum(_written(total).values())
    lines.append(("dry run: would write " if dry_run else "backfill: ")
                 + f"{total['sr'] + total['sr-updated']} SR, {n_ar} AR"
                 + (f"; {total['sr-stale']} SR older than their transcript (--update rewrites them)"
                    if total["sr-stale"] else ""))
    return "\n".join(lines)
