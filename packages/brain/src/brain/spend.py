"""``brain usage --by context`` and ``--by output``: where the tokens go (wi-brain-cache-report; spec token-spend
1.3, 1.5, 1.6, slice S3), read back at zero token from the ledger's ``spend`` field (:class:`Spend`, which
brain.usage's scanner keeps, SCAN_V 5).

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

from collections import Counter

from . import cost, usage  # both import this module: nothing of theirs is read at import time

CTX_STEP = 100_000  # the context buckets of ``spend`` (brain usage --by context)
SIM_CEILINGS = (300_000, 400_000, 500_000)  # the hand-over simulation's ceilings
SIM_RESTART = 120_000  # a fresh session's context after a hand-over: the base, the hand-over note, a re-read
CHARS_PER_TOKEN = 3.6  # an output's tokens, estimated from its characters
IMAGE_CHARS = 6_000  # an image in a tool result, counted as this many characters
OUTPUT_KEEP = 40  # output classes kept per row, the main thread's and the agents' each (the costliest downstream)
BASES_KEEP = 200  # agents' first-message contexts kept per row
SPEND_SKIP = {"prompt_snapshot"}  # attachments that are not sent to the model
TEXT_FIELDS = ("content", "text", "prompt", "addedLines", "addedBlocks", "context", "snapshot", "files", "date")
DIMS = ("context", "output")  # brain usage --by
HANDOVER_USD = 3.0  # a hand-over's price in the simulation: the note, the restart, the cache written again
ROLES = ("coordinator", "sub-session", "session")


class Spend:
    """Where a thread's tokens go (wi-brain-cache-report; spec token-spend 1.3, 1.5, 1.6): each message's context, cost
    and token rates, and each output put into the context (a tool result, a prompt, an attachment, a hook's context),
    so that ``brain usage --by context`` and ``--by output`` read them back from the ledger:

      buckets   the messages and their cost by the context they were sent with (``CTX_STEP`` buckets);
      split     the cost by token kind: input, output, cache read, cache write;
      sim       the hand-over simulation: past each ceiling of ``SIM_CEILINGS`` above the last restart, a fresh
                session restarts at ``SIM_RESTART`` tokens; the cache reads it saves (gross, USD) and the hand-overs
                it takes (the report charges each hand-over its price);
      outputs   by class (a tool's name, a shell command's program and subcommand, ``prompt``, ``injected``,
                ``attachment:<type>``, ``hook:<event>``): count, estimated tokens (characters / ``CHARS_PER_TOKEN``)
                and downstream cost: written once by the next message, then read by every later message of the same
                segment (a compaction ends a segment);
      base      the first message's context.
    """

    def __init__(self) -> None:
        self.msgs: list[tuple[int, float, float, float, int]] = []  # (context, cost, read rate, write rate, segment)
        self.outs: list[tuple[str, int, int, int]] = []  # (class, characters, index of the next message, segment)
        self.segment = 0
        self.split = {"input": 0.0, "output": 0.0, "read": 0.0, "write": 0.0}

    def message(self, part: dict, usd: float, parts: dict | None, rates: tuple[float, float]) -> None:
        ctx = part.get("input", 0) + part.get("cache_read", 0) + part.get("cache_write", 0)
        self.msgs.append((ctx, usd, rates[0], rates[1], self.segment))
        for k, v in (parts or {}).items():
            self.split[k] += v

    def output(self, cls: str, chars: int, pending: bool = False) -> None:
        """An output put into the context; ``pending``: an assistant message seen but not yet counted precedes it."""
        if cls and chars > 0:
            self.outs.append((cls, chars, len(self.msgs) + (1 if pending else 0), self.segment))

    def attachment(self, a: dict, kind: str, pending: bool = False) -> None:
        """An attachment (``attachment:<type>``) by the length of its text fields (``TEXT_FIELDS``: its metadata is
        not sent), or the context a hook injects (``hook:<event>``, its ``hook_additional_context``; a hook's run
        record, success or error, is not sent apart from it)."""
        if not kind or kind in SPEND_SKIP or (kind.startswith("hook_") and kind != "hook_additional_context"):
            return
        event = a.get("hookEvent") or str(a.get("hookName") or "?").split(":")[0]
        self.output(f"hook:{event}" if kind.startswith("hook_") else f"attachment:{kind}",
                    sum(_text_len(a.get(k)) for k in TEXT_FIELDS), pending)

    def result(self, name: str, keys: list[str], content, text: str) -> None:
        """A tool's result, classed by its tool, a shell command's by its first program and subcommand (``keys``):
        its text and ``IMAGE_CHARS`` per image."""
        images = sum(1 for x in content if isinstance(x, dict) and x.get("type") == "image") \
            if isinstance(content, list) else 0
        self.output(keys[0] if keys else name, len(text) + images * IMAGE_CHARS)

    def compaction(self) -> None:
        self.segment += 1

    def buckets(self) -> dict[str, list]:
        """{bucket's lower bound in k: [messages, USD]}."""
        out: dict[str, list] = {}
        for ctx, usd, *_ in self.msgs:
            b = out.setdefault(str(ctx // CTX_STEP * (CTX_STEP // 1000)), [0, 0.0])
            b[0] += 1
            b[1] += usd
        return {k: [n, round(c, 4)] for k, (n, c) in out.items()}

    def base(self) -> int:
        return self.msgs[0][0] if self.msgs else 0

    def simulate(self) -> dict[str, list]:
        """{ceiling in k: [cache reads saved (USD), hand-overs]}: the thread replayed with a hand-over each time its
        context passes the ceiling above the last restart's offset; a context that drops below the offset (a
        compaction) ends the offset."""
        out = {}
        for th in SIM_CEILINGS:
            off, saved, n = 0, 0.0, 0
            for ctx, _usd, read, _w, _s in self.msgs:
                if ctx - off > th:
                    off, n = ctx - SIM_RESTART, n + 1
                if ctx < off:
                    off = 0
                saved += min(off, ctx) * read
            out[str(th // 1000)] = [round(saved, 4), n]
        return out

    def outputs(self) -> dict[str, list]:
        """{class: [count, estimated tokens, downstream USD]}, the ``OUTPUT_KEEP`` costliest."""
        reads = [0.0] * (len(self.msgs) + 1)  # reads[i]: the read rates of messages i.. within message i's segment
        for i in range(len(self.msgs) - 1, -1, -1):
            same = i + 1 < len(self.msgs) and self.msgs[i + 1][4] == self.msgs[i][4]
            reads[i] = self.msgs[i][2] + (reads[i + 1] if same else 0.0)
        agg: dict[str, list] = {}
        for cls, chars, idx, seg in self.outs:
            tok = chars / CHARS_PER_TOKEN
            sent = idx < len(self.msgs) and self.msgs[idx][4] == seg
            a = agg.setdefault(cls, [0, 0.0, 0.0])
            a[0] += 1
            a[1] += tok
            # written by message idx, then read by the later messages of its segment
            a[2] += tok * (reads[idx] - self.msgs[idx][2] + self.msgs[idx][3]) if sent else 0.0
        top = sorted(agg.items(), key=lambda kv: (-kv[1][2], kv[0]))[:OUTPUT_KEEP]
        return {k: [n, int(round(t)), round(d, 4)] for k, (n, t, d) in top}


def _text_len(v) -> int:
    """The characters of the strings in a value (a string, a list or a dict of them)."""
    if isinstance(v, str):
        return len(v)
    if isinstance(v, dict):
        return sum(_text_len(x) for x in v.values())
    return sum(_text_len(x) for x in v) if isinstance(v, list) else 0


def merge_outputs(many: list[dict]) -> dict[str, list]:
    """Several threads' ``Spend.outputs`` summed, the ``OUTPUT_KEEP`` costliest."""
    agg: dict[str, list] = {}
    for outs in many:
        for k, (n, t, d) in outs.items():
            a = agg.setdefault(k, [0, 0, 0.0])
            a[0] += n
            a[1] += t
            a[2] += d
    top = sorted(agg.items(), key=lambda kv: (-kv[1][2], kv[0]))[:OUTPUT_KEEP]
    return {k: [n, t, round(d, 4)] for k, (n, t, d) in top}


def _sum_lists(many: list[dict]) -> dict[str, list]:
    out: dict[str, list] = {}
    for d in many:
        for k, vals in d.items():
            row = out.setdefault(k, [0] * len(vals))
            for i, v in enumerate(vals):
                row[i] += v
    return {k: [round(v, 4) if isinstance(v, float) else v for v in vals] for k, vals in out.items()}


def row_of(sp: Spend, agents: list[Spend]) -> dict:
    """A ledger row's ``spend``: the main thread's and its agents' apart."""
    return {"step": CTX_STEP // 1000, "restart": SIM_RESTART, "messages": len(sp.msgs), "base": sp.base(),
            "buckets": sp.buckets(), "split": {k: round(v, 4) for k, v in sp.split.items()},
            "sim": sp.simulate(), "outputs": sp.outputs(),
            "agents": {"messages": sum(len(a.msgs) for a in agents),
                       "bases": [a.base() for a in agents if a.msgs][:BASES_KEEP],
                       "buckets": _sum_lists([a.buckets() for a in agents]),
                       "split": {k: round(sum(a.split[k] for a in agents), 4) for k in sp.split},
                       "outputs": merge_outputs([a.outputs() for a in agents])}}


def role_of(row: dict) -> str:
    """A session's role from its row, at zero token: coordinator, sub-session or session."""
    if len(row.get("spawned") or []) >= cost.ORCHESTRATOR:
        return "coordinator"
    return "sub-session" if (row.get("brief") or {}).get("side") else "session"


def _add_buckets(into: dict, buckets: dict) -> None:
    for k, (n, c) in (buckets or {}).items():   # a row's keys are strings, a group's integers
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


KINDS = ("input", "output", "read", "write")


def _role_group() -> dict:
    return {"sessions": 0, "messages": 0, "buckets": {}, "bases": [], "sim": {}, "base_reread": 0.0}


def _add_row(g: dict, r: dict) -> None:
    """One row's main thread into its role's group."""
    sp = r["spend"]
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


def _role_out(g: dict, step: int, ceiling_k: int, handover_usd: float) -> dict:
    """A role's group as the report shows it: its buckets, the cost above the ceiling, its base, the simulation with
    each hand-over charged, and the ceiling that saves the most (None when none saves anything)."""
    sim = [{"ceiling_k": th, "handovers": n, "saved": round(saved, 4), "net": round(saved - n * handover_usd, 4)}
           for th, (saved, n) in sorted(g["sim"].items())]
    best = max(sim, key=lambda s: s["net"], default=None)
    return {"sessions": g["sessions"], "messages": g["messages"],
            "cost": round(sum(c for _, c in g["buckets"].values()), 4), "buckets": _bucket_rows(g["buckets"], step),
            "above": _above(g["buckets"], ceiling_k), "base": usage.quantiles(g["bases"]),
            "base_reread": round(g["base_reread"], 4), "sim": sim, "best": best if best and best["net"] > 0 else None}


def _scanned(rows: list[dict]) -> tuple[list[dict], dict]:
    """The rows that hold ``spend``, and the counts every view starts with."""
    have = [r for r in rows if isinstance(r.get("spend"), dict)]
    return have, {"sessions": len(rows), "scanned": len(have), "older": len(rows) - len(have)}


def _split(spends: list[dict]) -> dict:
    return {k: round(sum((sp.get("split") or {}).get(k, 0.0) for sp in spends), 4) for k in KINDS}


def _reloads(have: list[dict]) -> dict:
    cost_ = sum(((r.get("phases") or {}).get("reload") or {}).get("cost") or 0.0 for r in have)
    return {"messages": sum((r.get("signals") or {}).get("reloads") or 0 for r in have), "cost": round(cost_, 4)}


def _agents(agent_rows: list[dict], step: int) -> dict:
    buckets: dict[int, list] = {}
    for a in agent_rows:
        _add_buckets(buckets, a.get("buckets"))
    return {"messages": sum(a.get("messages") or 0 for a in agent_rows), "buckets": _bucket_rows(buckets, step),
            "base": usage.quantiles([b for a in agent_rows for b in a.get("bases") or [] if b])}


def context_view(rows: list[dict], handover_usd: float = HANDOVER_USD, ceiling_k: int = 400) -> dict:
    """The --by context report of the window's rows."""
    have, counts = _scanned(rows)
    step = max((int(r["spend"].get("step") or 0) for r in have), default=0) or CTX_STEP // 1000
    agent_rows = [r["spend"].get("agents") or {} for r in have]
    groups: dict[str, dict] = {}
    for r in have:
        _add_row(groups.setdefault(role_of(r), _role_group()), r)
    every: dict[int, list] = {}
    for g in groups.values():
        _add_buckets(every, g["buckets"])
    return {**counts, "step_k": step, "handover_usd": handover_usd, "restart": SIM_RESTART,
            "split": {"main": _split([r["spend"] for r in have]), "agents": _split(agent_rows)},
            "reloads": _reloads(have), "all": {"buckets": _bucket_rows(every, step), "above": _above(every, ceiling_k)},
            "roles": {name: _role_out(groups[name], step, ceiling_k, handover_usd) for name in ROLES if name in groups},
            "agents": _agents(agent_rows, step)}


def _output_table(outs: dict) -> list[dict]:
    total = sum(d for _, _, d in outs.values()) or 1e-9
    return [{"key": k, "count": n, "tokens": t, "per_output": int(t / n) if n else 0, "downstream": d,
             "share": round(d / total, 4)} for k, (n, t, d) in sorted(outs.items(), key=lambda kv: (-kv[1][2], kv[0]))]


def output_view(rows: list[dict]) -> dict:
    """The --by output report of the window's rows: the main threads' and the agents' outputs by class."""
    have, counts = _scanned(rows)
    main = merge_outputs([r["spend"].get("outputs") or {} for r in have])
    agents = merge_outputs([(r["spend"].get("agents") or {}).get("outputs") or {} for r in have])
    return {**counts, "chars_per_token": CHARS_PER_TOKEN, "main": _output_table(main), "agents": _output_table(agents)}


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


def render(rep: dict, top: int = 10) -> list[str]:
    """The views a ``brain.cost.report`` holds, as text."""
    return ((["", *render_context(rep["context"])] if "context" in rep else [])
            + (["", *render_output(rep["output"], top)] if "output" in rep else []))


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


def _off_map(expected: str | None, models: Counter) -> dict:
    """A role's row against the agent-model map (brief.agent_models): the model expected and how many of its agents
    ran on another (the alias read in the model id: sonnet in claude-sonnet-5-5); nothing for a role off the map."""
    if not expected:
        return {}
    return {"expected": expected, "off": sum(n for m, n in models.items() if expected not in str(m))}


def agents_table(rows: list[dict], dim: str, since: str, until: str, total: float,
                 agent_models: dict[str, str]) -> list[dict]:
    """brain usage --by agent (each label) or --by role (wi-brain-review-model-routing: each role, its models' counts
    and, for a role of ``agent_models``, how many ran off it): the subagents and the workflow runs in the window."""
    per: dict[str, dict] = {}

    def add(label: str, v: dict, kind: str, run: str = "") -> None:
        a = per.setdefault(label if dim == "agent" else v.get("role") or "-",
                           {"total": 0.0, "n": 0, "kinds": set(), "runs": set(), "models": Counter()})
        a["total"] += v.get("cost") or 0.0
        a["n"] += v.get("count") or 0
        a["kinds"].add(kind)
        a["models"].update(v.get("models") or {})
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
    return [{"key": k, "total": round(a["total"], 4), "share": a["total"] / total, "n": a["n"],
             "kind": "+".join(sorted(a["kinds"])), "runs": len(a["runs"]), "models": dict(a["models"]),
             **(_off_map(agent_models.get(k), a["models"]) if dim == "role" else {})} for k, a in per.items()]
