"""brain.resources' sample in words: the cockpit's band (RES-1) and ``brain resources``' text, one function per
section (wi-brain-resources-view)."""

from __future__ import annotations

from . import usage
from .resources import CRITICAL, WARN, level, pct_text, rate_text, size_text

SECTIONS = {"machine": "machine", "project": "projects", "session": "sessions", "container": "containers",
            "store": "stores"}   # --by: the document's key of each


def band_parts(b: dict, narrow: bool = False) -> list[tuple[str, str]]:
    """The band's words, each with its level (ok, warn, critical, unknown): CPU, RAM, disk, network, tokens today,
    quota and pace (RES-1; under 120 columns: CPU, RAM and the quota)."""
    if b.get("error"):
        return [("resources: " + str(b["error"])[:60], "unknown")]
    parts = [(f"CPU {pct_text(b.get('cpu_pct'))}", level(b.get("cpu_pct"))),
             (f"RAM {pct_text(b.get('mem_pct'))}", level(b.get("mem_pct")))]
    if not narrow:
        drive = (b.get("disk") or "disk").rstrip("\\").rstrip("/") or "/"
        parts.append((f"{drive} {pct_text(b.get('disk_pct'))}", level(b.get("disk_pct"))))
        parts.append((f"\u2191{short_rate(b.get('up_bps'))} \u2193{short_rate(b.get('down_bps'))}", "ok"))
        parts.append((f"{usage.ktok(b.get('tokens')) if b.get('tokens') is not None else '-'} tok", "ok"))
    q = b.get("quota_pct")
    qtext = f"quota {pct_text(q)}" + (f" {b['pace_x']:.1f}x" if isinstance(b.get("pace_x"), (int, float)) else "")
    parts.append((qtext if q is not None else "quota -", b.get("quota_level") or "unknown"))
    return parts


def short_rate(n) -> str:
    """A throughput in the band's few characters: ``512B``, ``1.4M``, ``12K``."""
    if not isinstance(n, (int, float)):
        return "-"
    for unit in ("B", "K", "M", "G"):
        if n < 1024 or unit == "G":
            return f"{n:.0f}{unit}" if unit == "B" or n >= 10 else f"{n:.1f}{unit}"
        n /= 1024
    return "-"


def band_text(b: dict, narrow: bool = False) -> str:
    return " \u00b7 ".join(t for t, _ in band_parts(b, narrow))


def section(doc: dict, by: str) -> dict:
    """``--by``: the document's head and one section (machine, project, session, container, store)."""
    key = SECTIONS[by]
    out = {k: doc[k] for k in ("v", "at", "levels")}
    out[key] = doc[key]
    if by == "machine":
        out.update({k: doc[k] for k in ("tokens", "quota", "overhead", "processes", "one_more_session_bytes")})
    return out


def _who(s: dict) -> str:
    ident = s["session"][:14] or (s["cli"][:8] if s["cli"] else "?")
    return f"{ident} {s['title']}".strip()


def machine_lines(m: dict) -> list[str]:
    mem, net = m["memory"], m["network"]
    commit = f" ({size_text(mem['commit_total'])} of {size_text(mem['commit_limit'])})" if mem.get("commit_limit") \
        else ""
    pool = f"; non-paged pool {size_text(mem['nonpaged'])}" if mem.get("nonpaged") else ""
    out = ["", f"machine {m['name']} ({m['os']}, {m['cores']} logical cores, read with {m['source']})",
           f"  cpu       {pct_text(m['cpu_pct'])} busy",
           f"  memory    {pct_text(mem['committed_pct'])} committed{commit}; {size_text(mem['available'])} of "
           f"{size_text(mem['total'])} RAM available{pool}",
           f"  network   up {rate_text(net['up_bps'])}, down {rate_text(net['down_bps'])} (the machine's "
           f"throughput{'; ' + net['why'] if net.get('why') else ''})"]
    return out + [f"  disk      {d['path']} {pct_text(d['used_pct'])} used, {size_text(d['free_bytes'])} free "
                  f"({', '.join(d['for'])})" for d in m["disks"]]


def tokens_lines(t: dict | None, q: dict | None) -> list[str]:
    out = []
    if t is not None:
        spent = usage.ktok(t["tokens"]) if t["tokens"] is not None else "-"
        scanned = f"; ledger scanned {t['ledger_at']}" if t.get("ledger_at") else f"; {t.get('why', '')}"
        out.append(f"  tokens    {spent} today ({t['day']} UTC), {usage.usd(t['usd'])} at API prices, "
                   f"{t['sessions']} session(s){scanned}")
    if q is None:
        return out
    if q.get("pct_now") is None:
        return out + [f"  quota     {q.get('why') or 'not known (brain usage quota)'}"]
    pace = f", pace {q['pace_x']:.2f}x (1.0: 100 % at the reset)" if q.get("pace_x") is not None else ""
    out.append(f"  quota     {q['window']} {pct_text(q['pct_now'])} now{pace}, {q['level']} (forecast of "
               f"{q.get('at') or '-'})")
    cap = q.get("capacity")
    if cap:
        out.append(f"  capacity  room for about {cap['session_hours']:g} session-hours; 20 sessions: "
                   f"{cap['for_20']:g} h (a session-hour {usage.usd(cap['session_hour_usd'])})")
    return out


def extra_lines(doc: dict) -> list[str]:
    """The overhead, the processes' availability and the cost of one more session."""
    out = []
    ov = doc.get("overhead")
    if ov:
        out.append(f"  overhead  {ov['why']}" if ov["state"] == "pending" else
                   f"  overhead  {usage.ktok(ov['tokens'])} ({ov['share_pct']:g} % of the tokens)")
    pr = doc.get("processes")
    if pr is not None and not pr.get("available"):
        out.append(f"  processes {pr.get('why')}")
    if doc.get("one_more_session_bytes"):
        out.append(f"  one more session costs about {size_text(doc['one_more_session_bytes'])} (the median CLI's "
                   f"process tree)")
    return out


def project_lines(rows: list[dict]) -> list[str]:
    out = ["", "projects  (live sessions, their memory and CPU, tokens today, containers)"]
    out += [f"  {p['project'] or '(no project)':24} {p['sessions_live']:>2} live  {size_text(p['tree_bytes']):>9} "
            f"{p['cpu_pct']:>5.1f} %  {usage.ktok(p['tokens_today']):>6} tok {usage.usd(p['usd_today']):>8}  "
            f"{p['containers']} container(s) {size_text(p['container_bytes'])}" for p in rows]
    return out + ([] if rows else ["  none"])


def session_lines(rows: list[dict], width: int) -> list[str]:
    out = ["", "sessions  (each CLI tied to its session: how; its process tree's memory; tokens today)"]
    for s in rows:
        mem = (f"{size_text(s['tree_bytes'])} ({s['children']} child process(es)), CPU {pct_text(s['cpu_pct'])}"
               if s["live"] else "not running here")
        out.append(f"  {_who(s)[:48]:48} {s['project'] or '-':14} {mem}; {usage.ktok(s['tokens_today'])} tok "
                   f"{usage.usd(s['usd_today'])}; tied by {s['how']}"[:width])
    return out + ([] if rows else ["  none"])


def container_lines(c: dict) -> list[str]:
    out = ["", f"containers ({c['state']}{': ' + c['why'] if c.get('why') else ''})"]
    return out + [f"  {r['name'][:32]:32} {pct_text(r['cpu_pct']):>5} CPU  {size_text(r['mem_bytes']):>9}  "
                  + (f"stack {r['stack']} ({r['project']})" if r["stack"] else "declared by no stack")
                  for r in c.get("rows", [])]


def store_lines(s: dict, width: int) -> list[str]:
    out = ["", f"stores    ({s['state']}{': ' + s['why'] if s.get('why') else ''})"]
    return out + [f"  {r['name'][:32]:32} {('' if r['complete'] else 'at least ') + size_text(r['bytes']):>18}  "
                  f"{r['path']}"[:width] for r in s.get("rows", [])]


def render(doc: dict, width: int = 120) -> list[str]:
    """``brain resources``: the sections the document holds, in words."""
    out = [f"resources at {doc['at']}" + (f" (sampled in {doc['cost_ms']:.0f} ms)" if "cost_ms" in doc else "")]
    out += [f"  {lv['level'].upper():8} {lv['text']} (WARN at {WARN:g} %, CRITICAL at {CRITICAL:g} %)"
            for lv in doc.get("levels") or []]
    if doc.get("machine"):
        out += machine_lines(doc["machine"])
    out += tokens_lines(doc.get("tokens"), doc.get("quota")) + extra_lines(doc)
    for key, lines in (("projects", lambda: project_lines(doc["projects"])),
                       ("sessions", lambda: session_lines(doc["sessions"], width)),
                       ("containers", lambda: container_lines(doc["containers"])),
                       ("stores", lambda: store_lines(doc["stores"], width))):
        if key in doc:
            out += lines()
    return out
