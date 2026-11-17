"""``brain usage --by context`` and ``--by output``: where the tokens go (wi-brain-cache-report; spec token-spend
1.3, 1.5, 1.6, slice S3), read back from the ledger's ``spend`` field (brain.usage.Spend, SCAN_V 5) at zero token.

  --by context  the cost split by token kind (input, output, cache read, cache write) and the context reloads; the
                base (the first message's context) of the sessions and of their agents, and what re-reading it
                costs; the messages and their cost by the context they were sent with, per role (a coordinator
                started ``brain.cost.ORCHESTRATOR`` sub-sessions or more; a sub-session was started by another session;
                any other session), the agents apart; the hand-over simulation: past each ceiling a fresh session
                restarts with a smaller context; what it saves in cache reads, less ``--handover-usd`` per hand-over
                (the note, the restart, the lost cache), and the ceiling that saves the most per role.
  --by output   each kind of output put into the context (a tool's result by tool, a shell command's by program and
                subcommand, prompts, injected text, attachments, hooks' context): its count, its estimated tokens
                and its downstream cost (written once, then re-read by every later message until a compaction), the
                main threads and the agents apart.

A row scanned by an older scanner, whose transcript is gone, has no ``spend``: the views count it apart.
"""

from __future__ import annotations

from . import cost, usage

HANDOVER_USD = 3.0  # a hand-over's price in the simulation: the note, the restart, the cache written again
ROLES = ("coordinator", "sub-session", "session")


def role_of(row: dict) -> str:
    """A session's role from its row, at zero token: coordinator, sub-session or session."""
    if len(row.get("spawned") or []) >= cost.ORCHESTRATOR:
        return "coordinator"
    return "sub-session" if (row.get("brief") or {}).get("side") else "session"


def _add_buckets(into: dict, buckets: dict) -> None:
    for k, (n, c) in (buckets or {}).items():
        b = into.setdefault(int(k), [0, 0.0])
        b[0] += n
        b[1] += c


def _bucket_rows(buckets: dict, step: int) -> list[dict]:
    total = sum(c for _, c in buckets.values()) or 1e-9
    return [{"from_k": k, "to_k": k + step, "messages": n, "cost": round(c, 4), "per_message": round(c / n, 4) if n
             else 0.0, "share": round(c / total, 4)} for k, (n, c) in sorted(buckets.items())]


def _above(buckets: dict, ceiling_k: int) -> dict:
    n = sum(v[0] for k, v in buckets.items() if k >= ceiling_k)
    c = sum(v[1] for k, v in buckets.items() if k >= ceiling_k)
    total = sum(v[1] for v in buckets.values()) or 1e-9
    return {"ceiling_k": ceiling_k, "messages": n, "cost": round(c, 4), "share": round(c / total, 4)}


def _read_rate(row: dict) -> float:
    """The main thread's mean USD per cache-read token (its split's read cost over its read tokens)."""
    tok = (row.get("tokens") or {}).get("cache_read") or 0
    return ((row.get("spend") or {}).get("split") or {}).get("read", 0.0) / tok if tok else 0.0


def context_view(rows: list[dict], handover_usd: float = HANDOVER_USD, ceiling_k: int = 400) -> dict:
    """The --by context report of the window's rows."""
    have = [r for r in rows if isinstance(r.get("spend"), dict)]
    step = max((int(r["spend"].get("step") or 0) for r in have), default=usage.CTX_STEP // 1000) or 100
    split = {"main": {"input": 0.0, "output": 0.0, "read": 0.0, "write": 0.0},
             "agents": {"input": 0.0, "output": 0.0, "read": 0.0, "write": 0.0}}
    reload_cost = sum(((r.get("phases") or {}).get("reload") or {}).get("cost") or 0.0 for r in have)
    reloads = sum((r.get("signals") or {}).get("reloads") or 0 for r in have)
    roles: dict[str, dict] = {}
    agents = {"buckets": {}, "bases": [], "messages": 0}
    for r in have:
        sp = r["spend"]
        for k in split["main"]:
            split["main"][k] += (sp.get("split") or {}).get(k, 0.0)
            split["agents"][k] += ((sp.get("agents") or {}).get("split") or {}).get(k, 0.0)
        g = roles.setdefault(role_of(r), {"sessions": 0, "messages": 0, "buckets": {}, "bases": [], "sim": {},
                                          "base_reread": 0.0})
        g["sessions"] += 1
        g["messages"] += sp.get("messages") or 0
        _add_buckets(g["buckets"], sp.get("buckets"))
        if sp.get("base"):
            g["bases"].append(sp["base"])
            g["base_reread"] += sp["base"] * (sp.get("messages") or 0) * _read_rate(r)
        for th, (saved, n) in (sp.get("sim") or {}).items():
            s = g["sim"].setdefault(int(th), [0.0, 0])
            s[0] += saved
            s[1] += n
        ag = sp.get("agents") or {}
        _add_buckets(agents["buckets"], ag.get("buckets"))
        agents["bases"] += [b for b in ag.get("bases") or [] if b]
        agents["messages"] += ag.get("messages") or 0
    out_roles = {}
    every = {}
    for name in ROLES:
        g = roles.get(name)
        if not g:
            continue
        _add_buckets(every, {str(k): v for k, v in g["buckets"].items()})
        sim = [{"ceiling_k": th, "handovers": n, "saved": round(saved, 4),
                "net": round(saved - n * handover_usd, 4)} for th, (saved, n) in sorted(g["sim"].items())]
        best = max(sim, key=lambda s: s["net"], default=None)
        out_roles[name] = {"sessions": g["sessions"], "messages": g["messages"],
                           "cost": round(sum(c for _, c in g["buckets"].values()), 4),
                           "buckets": _bucket_rows(g["buckets"], step), "above": _above(g["buckets"], ceiling_k),
                           "base": usage.quantiles(g["bases"]), "base_reread": round(g["base_reread"], 4),
                           "sim": sim, "best": best if best and best["net"] > 0 else None}
    return {"sessions": len(rows), "scanned": len(have), "older": len(rows) - len(have), "step_k": step,
            "handover_usd": handover_usd, "restart": usage.SIM_RESTART,
            "split": {w: {k: round(v, 4) for k, v in s.items()} for w, s in split.items()},
            "reloads": {"messages": reloads, "cost": round(reload_cost, 4)},
            "all": {"buckets": _bucket_rows(every, step), "above": _above(every, ceiling_k)},
            "roles": out_roles,
            "agents": {"messages": agents["messages"], "buckets": _bucket_rows(agents["buckets"], step),
                       "base": usage.quantiles(agents["bases"])}}


def output_view(rows: list[dict]) -> dict:
    """The --by output report of the window's rows: the main threads' and the agents' outputs by class."""
    have = [r for r in rows if isinstance(r.get("spend"), dict)]
    main = usage.merge_outputs([r["spend"].get("outputs") or {} for r in have])
    agents = usage.merge_outputs([(r["spend"].get("agents") or {}).get("outputs") or {} for r in have])

    def table(outs: dict) -> list[dict]:
        total = sum(d for _, _, d in outs.values()) or 1e-9
        return [{"key": k, "count": n, "tokens": t, "per_output": int(t / n) if n else 0, "downstream": d,
                 "share": round(d / total, 4)} for k, (n, t, d) in sorted(outs.items(), key=lambda kv: (-kv[1][2],
                                                                                                       kv[0]))]
    return {"sessions": len(rows), "scanned": len(have), "older": len(rows) - len(have),
            "chars_per_token": usage.CHARS_PER_TOKEN, "main": table(main), "agents": table(agents)}


# --- rendering ---

def _pct(x: float) -> str:
    return f"{x:.0%}"


def _older(v: dict) -> list[str]:
    return [f"  {v['older']} session(s) scanned by an older scanner, their transcripts gone: not in these views"] \
        if v["older"] else []


def _split_line(name: str, s: dict) -> str:
    total = sum(s.values()) or 1e-9
    return (f"  {name}: " + ", ".join(f"{k} {usage.usd(s[k])} ({_pct(s[k] / total)})"
                                      for k in ("read", "write", "output", "input")))


def _base(q: dict) -> str:
    if not q.get("n"):
        return "-"
    return (f"median {usage.ktok(q['median'])} (p25-p75 {usage.ktok(q['p25'])}-{usage.ktok(q['p75'])}, "
            f"p90 {usage.ktok(q['p90'])}), n {q['n']}")


def _buckets(rows: list[dict]) -> list[str]:
    return [f"    {r['from_k']:>4}-{r['to_k']:<4}k {r['messages']:>7} msg {usage.usd(r['cost']):>9} "
            f"{_pct(r['share']):>4}  {usage.usd(r['per_message']):>7}/msg" for r in rows]


def render_context(v: dict) -> list[str]:
    lines = [f"By context: {v['scanned']} session(s); messages by the context they were sent with "
             f"({v['step_k']}k buckets)"] + _older(v)
    if not v["scanned"]:
        return lines + ["  none"]
    lines += ["Cost by token kind", _split_line("main threads", v["split"]["main"]),
              _split_line("agents", v["split"]["agents"]),
              f"  context reloads (the cache written again): {v['reloads']['messages']} message(s), "
              f"{usage.usd(v['reloads']['cost'])}", "", "The base (the first message's context)"]
    for name, g in v["roles"].items():
        lines.append(f"  {name}: {_base(g['base'])}; its re-read by every message {usage.usd(g['base_reread'])}")
    lines.append(f"  agents: {_base(v['agents']['base'])}")
    a = v["all"]["above"]
    lines += ["", f"Main threads: above {a['ceiling_k']}k {a['messages']} msg, {usage.usd(a['cost'])} "
                  f"({_pct(a['share'])} of their cost)", *_buckets(v["all"]["buckets"])]
    for name, g in v["roles"].items():
        ab = g["above"]
        lines += ["", f"{name}: {g['sessions']} session(s), {g['messages']} msg, {usage.usd(g['cost'])}; above "
                      f"{ab['ceiling_k']}k {ab['messages']} msg, {usage.usd(ab['cost'])} ({_pct(ab['share'])})",
                  *_buckets(g["buckets"])]
    if v["agents"]["buckets"]:
        lines += ["", f"agents: {v['agents']['messages']} msg", *_buckets(v["agents"]["buckets"])]
    lines += ["", f"Hand-over simulation: past the ceiling a fresh session restarts at {usage.ktok(v['restart'])}; "
                  f"{usage.usd(v['handover_usd'])} charged per hand-over"]
    for name, g in v["roles"].items():
        sims = "; ".join(f"at {s['ceiling_k']}k: {s['handovers']} hand-over(s), saves {usage.usd(s['saved'])}, net "
                         f"{usage.usd(s['net']) if s['net'] >= 0 else '-' + usage.usd(-s['net'])}" for s in g["sim"])
        best = f" -> {g['best']['ceiling_k']}k" if g["best"] else " -> no ceiling pays"
        lines.append(f"  {name}: {sims}{best}")
    return lines


def render_output(v: dict, top: int = 10) -> list[str]:
    lines = [f"By output: {v['scanned']} session(s); what each kind of output costs downstream (est. "
             f"{v['chars_per_token']:g} characters a token; written once, re-read by every later message until a "
             f"compaction)"] + _older(v)
    for name in ("main", "agents"):
        rows = v[name]
        shown = rows[:top or None]
        more = f" (top {top} of {len(rows)})" if top and len(rows) > top else ""
        total = sum(r["downstream"] for r in rows)
        lines += ["", f"{'Main threads' if name == 'main' else 'Agents'}{more}: {usage.usd(total)} downstream, "
                      f"{usage.ktok(sum(r['tokens'] for r in rows))} tokens"]
        lines += [f"  {r['key'][:40]:<40} {r['count']:>6}x {usage.ktok(r['tokens']):>6} {r['per_output']:>6}/out "
                  f"{usage.usd(r['downstream']):>9} {_pct(r['share']):>4}" for r in shown]
        if not rows:
            lines.append("  none")
    return lines
