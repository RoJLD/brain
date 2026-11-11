"""``brain lesson``, ``brain retro`` and ``brain lint lessons``: the lessons loop at zero token
(wi-brain-lessons-registry, wi-brain-lessons-loop; the owner's LL-1 to LL-4: a short retro at every item's close, a
deep one at every wave, lessons as nodes that turn into a proposal when they recur).

A **Lesson** node (``nodes/lessons.yaml``) carries what a finished item, PR or incident taught:

- ``trigger``: the situation it happens in; ``anti_pattern``: what went wrong; ``check``: how one tells it happened
  again (a command, a test, a guard's refusal); the schema's ``required_props`` make these three mandatory;
- ``severity`` (high, medium, low), ``signal`` (the friction signal it shows in: merges, guards, tests, waits, tokens,
  owner, rework, other), ``prs`` (the PRs it was seen in), ``rule`` (an iron rule of a repo it restates), ``seen`` (how
  many times), ``why_not_script`` (a lesson no script can check says why);
- edges: ``learned_from`` (the item, ADR, DDR or session it came from), ``enforced_by`` (the hook, test or workflow
  that checks it), ``led_to`` (the item that fixes it).

Its status: open (nothing checks it yet), enforced (something does), resolved (the fix made it impossible), regressed
(it recurred after a fix), archived.

**Dedup.** ``brain lesson add`` compares the new lesson's words (title, trigger, anti-pattern) with every lesson's
(brain.lint's content words: Jaccard, or the share of the shorter found in the other): past ``NEAR`` it refuses and
names the close one, to mark with ``brain lesson seen`` instead (``--new`` overrides).

**Recurrence.** ``brain lesson seen <id> --from <node>|--pr <pr>`` counts one more occurrence. A lesson seen
``RECUR`` times (once when its severity is high) with nothing fixing it, or one that recurs after its fix (regressed),
files an item proposal (``priority_proposed``; P1 for a severe one) linked ``led_to``, its fix to choose in the order
script, hook, template, a rule last. The owner's ideation board (wi-brain-ideation-board) is not built: an Idea will
replace the item proposal then.

**The retro** (``brain retro <item>``, the close-item step): the friction signals of the sessions that served the item
(brain.cost's ledger: merge and rebase commands, conflicts, failing-command streaks, waits, questions to the owner and
the time they took, tokens against the estimate, the context peak against the brief's budget), the guard refusals of
the guards ledger in those sessions, the failed test runs, the pushes to the item's PRs after they were opened
(rework); the known lessons of the signals that fired; then the five lines the session answers. ``--record`` writes
``props.retro`` (the signals in one line, its friction points first) and ``props.retro_notes`` (the lines given with
``--note``). ``brain retro --wave W``: the deep retro, every item of the wave with its signals, the costliest
frictions, the retro notes recorded on them and the lessons learned from the wave's items. The wave's items are those
of a numbered wave (``W`` is ``X.Y.Z`` or ``wave-X.Y.Z``: the items ``part_of`` it and those carried to it by
``props.carried_to``, brain.waves) and those whose free-text ``props.wave`` names it (the letter waves, ``F``, and
``0.3.2, week of ...``); with ``--all``, each project's wave of that release.

**The iron rules** (``brain lesson rules``): the rule ids (``Σ-NAME`` or ``Sigma-NAME``) of each registered repo's
tracked Markdown, read only: where each is cited, its first sentence, the lessons that restate it.

**The linter** (``brain lint lessons``): an open lesson whose check names a command is a guard candidate (scripts
before rules); a lesson whose check no script can run and that says no ``why_not_script`` is flagged.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import config, graph, lint, paths, projects, resume, waves
from .inventory import AuditError, git

LESSON = "Lesson"
FILE = "nodes/lessons.yaml"
EDGES = "edges/lessons.yaml"
WORK_FILE = "nodes/work.yaml"
STATUSES = ("open", "enforced", "resolved", "regressed", "archived")
FIXED = ("enforced", "resolved")
SEVERITIES = ("high", "medium", "low")
SIGNALS = ("merges", "guards", "tests", "waits", "tokens", "owner", "rework", "other")
REQUIRED = ("trigger", "anti_pattern", "check")
RECUR = 2  # a lesson seen this many times with no fix files a proposal (once when severe)
NEAR = lint.NEAR
CONTAIN = lint.CONTAIN
LEARNED, ENFORCED, LED = "learned_from", "enforced_by", "led_to"
RULE_RE = re.compile(r"(?<![\w-])(?:Σ|Sigma)-[A-Z0-9](?:[A-Z0-9-]*[A-Z0-9])?")
RULE_FILES = ("*.md", "*.mdc")
QUOTE = 160
# a failed run of these commands is a failed test run; the shell's test builtin and Test-Path are not
TEST_CMD = re.compile(r"pytest|pester|\bunittest\b|\bvitest\b|\bjest\b|\btox\b|\bnox\b|"
                      r"^(?:npm|pnpm|yarn|bun|cargo|go|dotnet|make|uv run) test\b", re.I)
WAIT_FLAG = 600  # seconds waiting for a message before the retro flags the waits
FIVE = ("what cost the most", "what a script, a hook or a template would have prevented",
        "what to keep", "a lesson for the registry (brain lesson add), or a known one seen again (brain lesson seen)",
        "what to change in the next brief")


class LessonError(Exception):
    pass


# --- the registry ---

@dataclass
class Registry:
    store: Path
    nodes: dict[str, dict]
    edges: list[dict]

    @classmethod
    def load(cls, store: Path) -> "Registry":
        st = resume.Store.load(store)
        return cls(store, st.nodes, st.edges)

    def lessons(self) -> list[dict]:
        return sorted((n for n in self.nodes.values() if n.get("type") == LESSON), key=lambda n: n["id"])

    def out(self, nid: str, etype: str) -> list[str]:
        return [e["to"] for e in self.edges if e.get("from") == nid and e.get("type") == etype]


def _props(node: dict) -> dict:
    return node.get("props") or {}


def seen_of(node: dict) -> int:
    try:
        return max(1, int(str(_props(node).get("seen") or 1)))
    except ValueError:
        return 1


def threshold(node: dict) -> int:
    return 1 if _props(node).get("severity") == "high" else RECUR


def _text(node_or_props: dict) -> str:
    p = node_or_props.get("props", node_or_props)
    return " ".join(str(x) for x in (node_or_props.get("title", ""), p.get("trigger", ""), p.get("anti_pattern", "")))


def similarity(a: str, b: str) -> float:
    """brain.lint's measure of two texts: their content words' Jaccard index, or the share of the shorter's words
    found in the other once it has lint.MIN_WORDS of them."""
    wa, wb = lint.words(a), lint.words(b)
    if not wa or not wb:
        return 0.0
    jac = len(wa & wb) / len(wa | wb)
    small = min(wa, wb, key=len)
    contain = len(wa & wb) / len(small) if len(small) >= lint.MIN_WORDS else 0.0
    return round(max(jac, contain if contain >= CONTAIN else 0.0), 3)


def similar(reg: Registry, text: str, skip: str = "") -> list[tuple[float, str]]:
    out = [(similarity(text, _text(n)), n["id"]) for n in reg.lessons() if n["id"] != skip
           and n.get("status") != "archived"]
    return sorted((x for x in out if x[0] >= NEAR), reverse=True)


def _check_store(store: Path) -> None:
    schema = graph.load_schema(store)
    if LESSON not in (schema.get("node_types") or []):
        raise LessonError(f"{store / 'schema.yaml'} has no {LESSON} node type: add it (node_types, its statuses "
                          f"{', '.join(STATUSES)}, the edges {LEARNED}, {ENFORCED}, {LED}, as the engine's "
                          "docs/lessons.md shows) in a PR of its own; a retro goes on without it")
    missing = [e for e in (LEARNED, LED) if e not in (schema.get("edge_types") or [])]
    if missing:
        raise LessonError(f"{store / 'schema.yaml'}: edge type(s) {', '.join(missing)} missing")


def _pr_list(*values: str) -> str:
    seen: list[str] = []
    for v in values:
        for part in re.split(r"\s*[,;]\s*", str(v or "").strip()):
            if part and part not in seen:
                seen.append(part)
    return ", ".join(seen)


def _validate(lid: str, props: dict) -> None:
    for k in REQUIRED:
        if not str(props.get(k) or "").strip():
            raise LessonError(f"{lid}: a lesson needs its {k}")
    for k, allowed in (("severity", SEVERITIES), ("signal", SIGNALS)):
        if props[k] not in allowed:
            raise LessonError(f"{lid}: {k} {props[k]!r}: one of {', '.join(allowed)}")


def _refuse_close(reg: Registry, lid: str, text: str) -> None:
    close = similar(reg, text)
    if close:
        score, other = close[0]
        raise LessonError(f"{lid}: close to {other} ({score:.2f}): brain lesson seen {other} --from <item> "
                          "--pr <pr> counts it once more; --new if it is another lesson")


def _known(reg: Registry, ids: list[str]) -> None:
    for target in ids:
        if target not in reg.nodes:
            raise LessonError(f"{target}: unknown node")


def add(store: Path, lid: str, title: str, *, trigger: str, anti_pattern: str, check: str, severity: str = "medium",
        signal: str = "other", frm: list[str] | None = None, prs: str = "", rule: str = "", led_to: str = "",
        enforced_by: list[str] | None = None, why_not_script: str = "", source: str = "", status: str = "",
        new: bool = False, today: str | None = None, propose: bool = True) -> dict:
    """Write one Lesson node and its edges; refuse a near duplicate unless ``new``. Returns {"node", "filed"}: the
    item proposal it filed, when it is severe and nothing fixes it."""
    _check_store(store)
    today = today or date.today().isoformat()
    props = {"trigger": trigger, "anti_pattern": anti_pattern, "check": check, "severity": severity,
             "signal": signal, "learned": today}
    _validate(lid, props)
    reg = Registry.load(store)
    if not new:
        _refuse_close(reg, lid, " ".join((title, trigger, anti_pattern)))
    _known(reg, [*(frm or []), *([led_to] if led_to else []), *(enforced_by or [])])
    extra = {"prs": _pr_list(prs), "rule": rule, "why_not_script": why_not_script, "source": source}
    props.update({k: v for k, v in extra.items() if v})
    status = status or ("enforced" if enforced_by else "open")
    node = graph.add_item(store, lid, title, node_type=LESSON, status=status, props=props, file=FILE,
                          edges_file=EDGES, today=today)
    fixes = {led_to, *(enforced_by or [])}  # one edge per node pair: what fixes it wins over learned_from
    edges = _edges(lid, LEARNED, frm, skip=fixes) + _edges(lid, ENFORCED, enforced_by) + _edges(lid, LED, [led_to])
    graph.append_edges(store, edges, EDGES, f"{today}: {lid} (brain lesson add)")
    return {"node": node, **_proposal(store, lid, today, propose)}


def _edges(lid: str, etype: str, targets: list[str] | None, skip: set[str] = frozenset()) -> list[dict]:
    return [{"from": lid, "to": t, "type": etype} for t in dict.fromkeys(targets or []) if t and t not in skip]


def _fixed(reg: Registry, node: dict) -> bool:
    """Enforced or resolved, or an item it led_to is done: one more occurrence is a regression."""
    return node.get("status") in FIXED or any((reg.nodes.get(t) or {}).get("status") == "done"
                                              for t in reg.out(node["id"], LED))


def seen(store: Path, lid: str, frm: list[str] | None = None, pr: str = "", today: str | None = None,
         propose: bool = True) -> dict:
    """One more occurrence of a lesson: seen + 1, the PR added, a learned_from edge to each new node; a fixed one
    (enforced, resolved, or an item it led_to done) turns regressed, unless it was seen in that fix item's own work
    (--from the item it led_to). Files the proposal once the lesson recurs.
    Returns {"node", "filed", "linked", "regressed"}."""
    today = today or date.today().isoformat()
    reg = Registry.load(store)
    node = reg.nodes.get(lid)
    if not node or node.get("type") != LESSON:
        raise LessonError(f"{lid}: no such lesson")
    if not frm and not pr:
        raise LessonError(f"{lid}: say where it was seen again (--from <node> or --pr <pr>)")
    _known(reg, frm or [])
    regressed = _fixed(reg, node) and not set(frm or []) & set(reg.out(lid, LED))  # its fix's own work: no regression
    sets = [f"seen={seen_of(node) + 1}", f"last_seen={today}"]
    sets += [f"prs={_pr_list(_props(node).get('prs', ''), pr)}"] if pr else []
    sets += ["status=regressed", f"regressed={today}"] if regressed else []
    graph.set_item(store, lid, sets)
    linked = {e["to"] for e in reg.edges if e.get("from") == lid}
    graph.append_edges(store, _edges(lid, LEARNED, frm, skip=linked), EDGES,
                       f"{today}: {lid} (brain lesson seen)")
    out = _proposal(store, lid, today, propose, force=regressed)
    return {"node": Registry.load(store).nodes[lid], **out, "regressed": regressed}


def proposal_id(reg: Registry, lid: str) -> str:
    base = "wi-" + (lid[4:] if lid.startswith("les-") else f"lesson-{lid}")
    nid, n = base, 2
    while nid in reg.nodes:
        nid, n = f"{base}-{n}", n + 1
    return nid


def _proposal(store: Path, lid: str, today: str, propose: bool, force: bool = False) -> dict:
    """{"filed": the new item's id, "linked": the open item it was linked to instead}, each None when not."""
    got = _maybe_propose(store, lid, today, force) if propose else None
    return {"filed": got[0] if got and got[1] else None, "linked": got[0] if got and not got[1] else None}


def like_item(reg: Registry, node: dict) -> str | None:
    """The open WorkItem whose title is closest to the lesson's title, past NEAR: it already carries the fix. A node
    the lesson already links (learned_from) is never it: one edge per node pair."""
    linked = {e["to"] for e in reg.edges if e.get("from") == node["id"]}
    best = max(((similarity(str(node.get("title", "")), str(n.get("title", ""))), n["id"])
                for n in reg.nodes.values() if n.get("type") == "WorkItem" and n["id"] not in linked
                and n.get("status") in ("todo", "doing", "blocked")), default=(0.0, ""))
    return best[1] if best[0] >= NEAR else None


PRIORITY = {"high": "P1", "medium": "P2", "low": "P3"}  # a proposal's priority_proposed, by the lesson's severity


def _maybe_propose(store: Path, lid: str, today: str, force: bool = False,
                   why: str = "regressed after its fix") -> tuple[str, bool] | None:
    """File the item proposal of a lesson that recurred (seen >= its threshold) or regressed, unless an open item it
    led_to already carries the fix; an open item whose title is close to the lesson's (like_item) is linked led_to
    instead of a new one. (the item's id, new); the new item's id: the lesson's with wi- for les-. ``why``: what filed
    a forced proposal (a regression, the linter's guard candidate)."""
    reg = Registry.load(store)
    node = reg.nodes[lid]
    if node.get("status") == "archived":
        return None
    led = [t for t in reg.out(lid, LED) if (reg.nodes.get(t) or {}).get("status") not in ("done", "dropped")]
    if led:
        return None
    if not force and (seen_of(node) < threshold(node) or _fixed(reg, node)):
        return None  # not recurring yet, or fixed: enforced, resolved or its led_to item done
    same = like_item(reg, node)
    if same:
        graph.append_edges(store, [{"from": lid, "to": same, "type": LED}], EDGES,
                           f"{today}: {lid} (brain lesson, an open item carries the fix)")
        return same, False
    p = _props(node)
    nid = proposal_id(reg, lid)
    why = why if force else f"seen {seen_of(node)} time(s)"
    props = {"priority_proposed": PRIORITY.get(p.get("severity", ""), "P2"),
             "priority_reason": f"lesson {lid} {why}: {p.get('anti_pattern', '')}".strip(),
             "lesson": lid, "idea": f"brain lesson, {today}: {lid} {why}",
             "fix_ladder": "a script first, then a hook, then a template, a rule last (scripts before rules)",
             "check": p.get("check", "")}
    graph.add_item(store, nid, f"Prevent {node.get('title', lid)}", props=props, file=WORK_FILE,
                   edges_file=EDGES, today=today)
    graph.append_edges(store, [{"from": lid, "to": nid, "type": LED}], EDGES, f"{today}: {lid} (brain lesson, proposal)")
    return nid, True


# --- rows: the list, --follow, the panel's data ---

def rows(store: Path) -> list[dict]:
    """lessons_rows: one per lesson with its status, seen, severity, signal, what checks it, the items it led to (their
    status and PR), where it came from, and whether it recurred since its fix."""
    reg = Registry.load(store)
    out = []
    for n in reg.lessons():
        p = _props(n)
        led = [{"id": t, "status": (reg.nodes.get(t) or {}).get("status", ""),
                "pr": _props(reg.nodes.get(t) or {}).get("pr", ""),
                "done": str(_props(reg.nodes.get(t) or {}).get("done", ""))[:10]} for t in reg.out(n["id"], LED)]
        fixed_on = max((x["done"] for x in led if x["done"]), default="")
        last = str(p.get("last_seen") or p.get("learned") or "")
        again = str(p.get("last_seen") or "")  # a sighting after the first one (brain lesson seen)
        out.append({"id": n["id"], "status": n.get("status", ""), "title": " ".join(str(n.get("title", "")).split()),
                    "seen": seen_of(n), "severity": p.get("severity", ""), "signal": p.get("signal", ""),
                    "check": p.get("check", ""), "trigger": p.get("trigger", ""),
                    "anti_pattern": p.get("anti_pattern", ""), "rule": p.get("rule", ""),
                    "prs": p.get("prs", ""), "learned": str(p.get("learned", "")), "last_seen": last,
                    "learned_from": reg.out(n["id"], LEARNED), "enforced_by": reg.out(n["id"], ENFORCED),
                    "led_to": led, "fixed_on": fixed_on,
                    "recurred_since_fix": bool(fixed_on and again > fixed_on) or n.get("status") == "regressed",
                    "why_not_script": p.get("why_not_script", ""), "source": p.get("source", "")})
    return out


def select(rs: list[dict], status: str = "", signal: str = "") -> list[dict]:
    return [r for r in rs if (not status or r["status"] == status) and (not signal or r["signal"] == signal)]


def render_list(rs: list[dict]) -> list[str]:
    if not rs:
        return ["no lesson yet: brain lesson add <les-id> --title ... --trigger ... --anti-pattern ... --check ..."]
    by = Counter(r["status"] for r in rs)
    lines = [f"{len(rs)} lesson(s): " + ", ".join(f"{by[s]} {s}" for s in STATUSES if by[s])]
    for r in rs:
        fix = ", ".join(r["enforced_by"]) or ", ".join(x["id"] for x in r["led_to"]) or "-"
        lines.append(f"  {r['id']} [{r['status']}] seen {r['seen']}, {r['severity'] or '-'}, {r['signal'] or '-'}; "
                     f"fix {fix}: {r['title']}")
    return lines


def friction(store: Path) -> list[dict]:
    """The friction KPI: the friction points of each retro recorded on the items (props.retro), by ISO week of the
    retro's day: items, total, mean per item. It should fall (LL-2's Revisit if)."""
    weeks: dict[str, list[int]] = {}
    for n in resume.Store.load(store).of_type("WorkItem"):
        m = _RETRO_RE.match(str(_props(n).get("retro") or ""))
        if not m:
            continue
        y, w, _ = date.fromisoformat(m.group(1)).isocalendar()
        weeks.setdefault(f"{y}-W{w:02d}", []).append(int(m.group(2)))
    return [{"week": k, "items": len(v), "points": sum(v), "mean": round(sum(v) / len(v), 2)}
            for k, v in sorted(weeks.items())]


def _led(x: dict) -> str:
    return f"  led to {x['id']} [{x['status']}]" + (f" {x['pr']}" if x["pr"] else "") + \
        (f", done {x['done']}" if x["done"] else "")


def _lineage(r: dict) -> list[str]:
    last = f", last {r['last_seen']}" if r["last_seen"] and r["last_seen"] != r["learned"] else ""
    lines = [f"{r['id']} [{r['status']}] {r['title']}",
             f"  seen {r['seen']} ({r['learned']}{last}), {r['severity'] or '-'}, signal {r['signal'] or '-'}"]
    sources = r["learned_from"] + ([r["prs"]] if r["prs"] else [])
    lines += ["  learned from " + ", ".join(sources)] if sources else []
    lines += [_led(x) for x in r["led_to"]]
    lines += ["  enforced by " + ", ".join(r["enforced_by"])] if r["enforced_by"] else []
    if r["led_to"] or r["enforced_by"]:
        return lines + ["  recurred since its fix: " + ("yes" if r["recurred_since_fix"] else "no")]
    why = f" (why not a script: {r['why_not_script']})" if r["why_not_script"] else ""
    return lines + [f"  no fix yet{why}"]


def render_follow(rs: list[dict], kpi: list[dict]) -> list[str]:
    """``brain lessons --follow``: each lesson and what it led to, the lineage lesson > learned from > item > PR >
    recurrence, then the friction per item by week."""
    if not rs:
        return render_list(rs)
    lines = [x for r in rs for x in _lineage(r)] + [""]
    if kpi:
        lines.append("friction per item, by week (brain retro --record): "
                     + "; ".join(f"{k['week']} {k['mean']} ({k['items']} item(s))" for k in kpi))
    else:
        lines.append("friction per item: no retro recorded yet (brain retro <item> --record)")
    return lines


# --- the retro ---

_RETRO_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}) friction=(\d+)")


def _jsonl(prefix: str) -> list[dict]:
    out = []
    d = paths.ledger_dir()
    for f in sorted(d.glob(f"{prefix}-*.jsonl")) if d.is_dir() else []:
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if isinstance(r, dict):
                    out.append(r)
    return out


def guard_refusals(session_ids: set[str]) -> list[dict]:
    """The guards ledger's refusals (decision denied) in these sessions."""
    return [r for r in _jsonl("guards") if r.get("session_id") in session_ids and r.get("decision") == "denied"]


def _short(repo: str) -> str:
    return str(repo or "").rsplit("/", 1)[-1].lower()


def rework(prs: list[str], actions: list[dict] | None = None) -> dict[str, int]:
    """The pushes to each PR's branch after it was opened and before it merged (the action records): review fixes,
    a merge of main, a red CI; ``brain#31`` -> count. The branch: the last push of the opening session, in that repo,
    before the PR was created."""
    acts = _jsonl("ar") if actions is None else actions
    out = {}
    for pr in prs:
        n = _pushes_after_opening(acts, *pr.partition("#")[::2])
        if n is not None:
            out[pr] = n
    return out


def _pr_events(acts: list[dict], repo: str, num: str) -> dict[str, dict]:
    """The first record of each action (created, merged) of a PR."""
    out: dict[str, dict] = {}
    for a in sorted(acts, key=lambda a: a.get("at", "")):
        pr = a.get("pr") or {}
        if a.get("kind") == "pr" and _short(a.get("repo")) == repo and str(pr.get("number")) == num:
            out.setdefault(str(pr.get("action")), a)
    return out


def _pushes_after_opening(acts: list[dict], repo: str, num: str) -> int | None:
    ev = _pr_events(acts, repo, num)
    if "created" not in ev:
        return None
    created, merged = ev["created"]["at"], (ev.get("merged") or {}).get("at", "~")
    opener = (ev["created"].get("session") or {}).get("id")
    pushes = [a for a in acts if a.get("kind") == "push" and _short(a.get("repo")) == repo]
    before = [a for a in pushes if a["at"] <= created and (a.get("session") or {}).get("id") == opener]
    if not before:
        return None
    branch = max(before, key=lambda a: a["at"]).get("branch")
    return sum(1 for a in pushes if a.get("branch") == branch and created < a["at"] < merged)


def failed_tests(session_rows: list[dict]) -> int:
    return sum(int((v or {}).get("fails") or 0) for r in session_rows for k, v in (r.get("commands") or {}).items()
               if TEST_CMD.search(k))


def _signals(a: dict, rv: dict, refusals: list[dict], rw: dict[str, int], tests: int, off: float) -> dict:
    s = a["signals"]

    def n(k: str) -> int:
        return int(s.get(k, 0))
    return {"merges": n("merges"), "conflicts": n("conflicts"), "rebases": n("rebases"), "guards": len(refusals),
            "guard_checks": dict(Counter(f"{g.get('guard')}:{g.get('check') or '-'}" for g in refusals)),
            "tests": tests, "thrash": n("thrash"), "wait_s": n("wait_s"), "asks": n("asks"),
            "owner_s": n("ask_wait_s"), "compactions": n("compactions"), "review_rounds": n("review_rounds"),
            "rework": rw, "cost": a["cost"], "estimate": rv["estimate"], "ratio": rv["ratio"],
            "over": rv["ratio"] is not None and rv["ratio"] > off, "peak": a["peak"], "budget": a["budget"],
            "sessions": a["sessions"], "active_s": a["active_s"]}


def _fired(sig: dict) -> set[str]:
    """The signals a retro flags, by the lesson signal they show in."""
    return {k for k, on in (("merges", sig["conflicts"] > 0), ("guards", sig["guards"] > 0),
                            ("tests", sig["tests"] > 0 or sig["thrash"] > 0), ("waits", sig["wait_s"] >= WAIT_FLAG),
                            ("tokens", sig["over"]), ("owner", sig["asks"] > 0),
                            ("rework", sum(sig["rework"].values()) > 0)) if on}


def retro(led, item_id: str, store: Path | None = None, actions: list[dict] | None = None,
          guards: list[dict] | None = None) -> dict:
    """The friction signals of an item (brain.cost's ledger joined to the guards ledger and the action records), the
    known lessons of the signals that fired, and its friction points."""
    from . import cost
    rv = cost.review(led, item_id)
    a = rv["item"]
    it = led.items[item_id]
    ids = set(a["session_ids"])
    refusals = guard_refusals(ids) if guards is None else [g for g in guards if g.get("session_id") in ids
                                                          and g.get("decision") == "denied"]
    prs = cost.item_prs(it.props.get("pr", ""))
    sig = _signals(a, rv, refusals, rework(prs, actions), failed_tests([r for r, _ in it.sessions]), cost.OFF)
    points = (sig["conflicts"] + sig["guards"] + sig["tests"] + sig["thrash"] + sum(sig["rework"].values())
              + sig["compactions"] + int(sig["over"]))
    fired = _fired(sig)
    st = store or it.store
    known = [r for r in rows(st) if r["signal"] in fired and r["status"] != "archived"] \
        if st and (st / FILE).is_file() else []
    return {"item": item_id, "title": a["title"], "class": a["class"], "kind": a["kind"], "prs": prs,
            "signals": sig, "friction": points, "fired": sorted(fired), "known": known,
            "session_ids": sorted(ids), "why": rv["why"]}


def retro_text(r: dict, today: str) -> str:
    """The one line ``--record`` writes on the item (props.retro): the day, the friction points, then each signal."""
    s = r["signals"]
    parts = [f"{today} friction={r['friction']}", f"merges={s['merges']}", f"conflicts={s['conflicts']}",
             f"guards={s['guards']}", f"tests={s['tests']}", f"thrash={s['thrash']}", f"rework={sum(s['rework'].values())}",
             f"wait={s['wait_s'] // 60}m", f"owner={s['owner_s'] // 60}m", f"compactions={s['compactions']}"]
    if s["ratio"] is not None:
        parts.append(f"tokens=x{s['ratio']:.2f}")
    return " ".join(parts)


def _mins(sec: int) -> str:
    return f"{sec // 3600}h{(sec % 3600) // 60:02d}" if sec >= 3600 else f"{sec // 60} min"


def _tokens(s: dict) -> str:
    est = (f"${s['cost']:.2f} against ${s['estimate']:.2f}: x{s['ratio']:.2f}" + (", over" if s["over"] else "")
           if s["estimate"] else f"${s['cost']:.2f}, no estimate")
    return est + f"; context peak {s['peak'] // 1000}k" + (f" of {s['budget'] // 1000}k" if s["budget"] else "")


def render_retro(r: dict, owner: str = "") -> list[str]:
    owner = owner or config.owner_of()
    s = r["signals"]
    gchecks = ", ".join(f"{k} x{v}" for k, v in sorted(s["guard_checks"].items()))
    rw = ", ".join(f"{k} {v} push(es) after opening" for k, v in s["rework"].items() if v) or "none"
    lines = [f"retro {r['item']} ({r['class'] or 'no class'}, {r['kind']}): {s['sessions']} session(s), "
             f"{_mins(s['active_s'])} active, friction {r['friction']} point(s)",
             f"  merges    {s['merges']} merge, rebase or pull command(s), {s['conflicts']} conflict(s)",
             f"  guards    {s['guards']} refusal(s)" + (f" ({gchecks})" if gchecks else ""),
             f"  tests     {s['tests']} failed test run(s), {s['thrash']} failing-command streak(s)",
             f"  waits     {_mins(s['wait_s'])} waiting for a message, {s['compactions']} compaction(s)",
             f"  tokens    {_tokens(s)}",
             f"  {owner[:9]:<9} {s['asks']} question(s), {_mins(s['owner_s'])} until the answers",
             f"  PRs       {', '.join(r['prs']) or 'none named'}; rework: {rw}"]
    if r["why"]:
        lines.append("  why (against the class's finished items): " + "; ".join(r["why"][:3]))
    if r["known"]:
        lines.append("known lessons for the signals that fired (" + ", ".join(r["fired"]) + "):")
        lines += [f"  {k['id']} [{k['status']}] seen {k['seen']}: {k['title']}" for k in r["known"][:8]]
    lines.append("answer in five lines (brain retro <item> --record --note LINE ...):")
    lines += [f"  {i}. {q}" for i, q in enumerate(FIVE, 1)]
    lines.append("a lesson: brain lesson add les-<project>-<slug> --title ... --trigger ... --anti-pattern ... "
                 f"--check ... --signal {'|'.join(r['fired'] or SIGNALS[:-1])} --from {r['item']}; a known one seen "
                 f"again: brain lesson seen <id> --from {r['item']}")
    return lines


def wave_items(led, wave: str, store: Path | None = None) -> list[str]:
    """The items of a wave (wi-brain-retro-numbered-waves): those of the numbered wave ``X.Y.Z`` or ``wave-X.Y.Z``
    in the items' stores and ``store`` (brain.waves: part_of it, or carried to it by props.carried_to; carried out
    of it left out), and those whose props.wave names it, alone or followed by a space, a comma or a parenthesis
    (the letter waves, ``F``, and the numbered ones written ``0.3.2, week of ...``). A store's wave counts only its own
    items: with several projects (``--all``), each project's wave of that release, never an id of another store."""
    wave = str(wave).strip()
    name = wave.removeprefix("wave-")
    if not name:
        return []
    rx = re.compile(rf"^(?:wave-)?{re.escape(name)}(?:[\s,(]|$)")
    ids = {i for i, it in led.items.items() if rx.match(str(it.props.get("wave") or "").strip())}
    for st in sorted({it.store for it in led.items.values() if it.store} | ({store} if store else set())):
        ids |= _numbered_wave(led, st, wave, name)
    return sorted(ids)


def _numbered_wave(led, st: Path, wave: str, name: str) -> set[str]:
    """The items of ``st``'s wave ``wave`` (or ``name``, its release) that the ledger places in ``st``."""
    if not (st / "nodes").is_dir() or not waves.applies(st):
        return set()
    plan = waves.load(st)
    wid = plan.resolve(wave) or plan.resolve(name)
    if not wid:
        return set()
    here = st.resolve()
    return {i for i in plan.items_of(wid) if i in led.items and led.items[i].store
            and led.items[i].store.resolve() == here}


def wave_retro(led, wave: str, store: Path | None = None) -> dict:
    """The deep retro of a wave: each item's retro, the totals by signal, the costliest frictions, the retro notes
    recorded on the wave's items (props.retro_notes) and the lessons learned from them."""
    acts, guards = _jsonl("ar"), _jsonl("guards")
    members = wave_items(led, wave, store)
    items = [retro(led, i, store, acts, guards) for i in members if led.items[i].sessions]
    tot = Counter()
    for r in items:
        s = r["signals"]
        for k in ("conflicts", "guards", "tests", "thrash", "compactions", "asks", "owner_s", "wait_s"):
            tot[k] += s[k]
        tot["rework"] += sum(s["rework"].values())
        tot["cost"] += s["cost"]
    ids = {r["item"] for r in items} | set(members)
    return {"wave": wave, "items": sorted(items, key=lambda r: -r["friction"]), "totals": dict(tot),
            "learned": _learned(led, ids, store), "notes": _notes(led, ids),
            "open": sorted(ids - {r["item"] for r in items})}


def _learned(led, ids: set[str], store: Path | None) -> list[dict]:
    """The lessons learned from ``ids``, in their stores and ``store``."""
    learned = []
    stores = {led.items[i].store for i in ids if led.items[i].store} | ({store} if store else set())
    for st in stores:
        if st and (st / FILE).is_file():
            learned += [x for x in rows(st) if set(x["learned_from"]) & ids]
    return learned


def _notes(led, ids: set[str]) -> dict[str, str]:
    """The retro notes recorded on ``ids`` (props.retro_notes), by item."""
    return {i: str(led.items[i].props["retro_notes"]) for i in sorted(ids) if led.items[i].props.get("retro_notes")}


def render_wave(w: dict) -> list[str]:
    t = w["totals"]
    lines = [f"deep retro, wave {w['wave']}: {len(w['items'])} item(s) with sessions, ${t.get('cost', 0):.2f}; "
             f"{t.get('conflicts', 0)} conflict(s), {t.get('guards', 0)} guard refusal(s), {t.get('tests', 0)} failed "
             f"test run(s), {t.get('rework', 0)} rework push(es), {t.get('asks', 0)} question(s) "
             f"({_mins(int(t.get('owner_s', 0)))} until the answers)"]
    for r in w["items"]:
        lines.append(f"  {r['item']}: friction {r['friction']} ({', '.join(r['fired']) or 'no signal'})")
    if w["open"]:
        lines.append("  no session yet: " + ", ".join(w["open"]))
    if w.get("notes"):
        lines.append(f"retro notes recorded on the wave's items: {len(w['notes'])}")
        lines += [f"  {i}: {n}" for i, n in w["notes"].items()]
    lines.append(f"lessons learned from the wave's items: {len(w['learned'])}")
    lines += [f"  {x['id']} [{x['status']}] seen {x['seen']}: {x['title']}" for x in w["learned"]]
    lines.append("the coordinator answers: what slowed the wave most, what the next wave's briefs change, which "
                 "lessons recur (brain lesson seen), which fix to file first")
    return lines


# --- the iron rules of the registered repos (read only) ---

def iron_rules(repos: list[projects.Repo], linked: dict[str, list[str]] | None = None) -> list[dict]:
    """Each repo's rule ids (``RULE_RE``) in its tracked Markdown, read with git ls-files and never written: the id,
    its mentions, the files and lines that cite it, its first citation's sentence, the lessons whose props.rule names
    it. A repo whose checkout is missing is listed as missing."""
    linked = linked or {}
    out = []
    for r in repos:
        entry = {"repo": r.name, "path": r.path.as_posix(), "missing": "", "rules": []}
        if not (r.path / ".git").exists():
            entry["missing"] = "no checkout"
            out.append(entry)
            continue
        try:
            files = [f for f in git(r.path, "ls-files", "-z", "--", *RULE_FILES).split("\0") if f]
        except AuditError as exc:
            entry["missing"] = str(exc)
            out.append(entry)
            continue
        found: dict[str, dict] = {}
        for f in files:
            try:
                text = (r.path / f).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for n, line in enumerate(text.splitlines(), 1):
                for m in RULE_RE.finditer(line):
                    rid = m.group(0).replace("Sigma-", "Σ-")
                    e = found.setdefault(rid, {"id": rid, "mentions": 0, "cited": [], "text": "",
                                               "lessons": linked.get(rid, [])})
                    e["mentions"] += 1
                    where = f"{f}:{n}"
                    if where not in e["cited"]:
                        e["cited"].append(where)
                    if not e["text"]:
                        e["text"] = _sentence(line, m.start())
        entry["rules"] = sorted(found.values(), key=lambda e: (-e["mentions"], e["id"]))
        out.append(entry)
    return out


def _sentence(line: str, at: int) -> str:
    s = re.sub(r"[*_`>#|]+", "", line).strip()
    s = " ".join(s.split())
    return s if len(s) <= QUOTE else s[:QUOTE - 1] + "…"


def rule_links(store: Path | None) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if store and (store / FILE).is_file():
        for r in rows(store):
            if r["rule"]:
                out.setdefault(r["rule"].replace("Sigma-", "Σ-"), []).append(r["id"])
    return out


def render_rules(index: list[dict], top: int = 0) -> list[str]:
    lines = []
    for e in index:
        if e["missing"]:
            lines.append(f"{e['repo']}: missing ({e['missing']}) at {e['path']}")
            continue
        n = sum(r["mentions"] for r in e["rules"])
        lines.append(f"{e['repo']}: {len(e['rules'])} iron rule(s), {n} mention(s)")
        for r in e["rules"][:top or None]:
            les = f" [lesson {', '.join(r['lessons'])}]" if r["lessons"] else ""
            more = f" (+{len(r['cited']) - 1} more)" if len(r["cited"]) > 1 else ""
            lines.append(f"  {r['id']} x{r['mentions']}: {r['cited'][0]}{more}{les}")
    return lines or ["no registered repo"]


# --- the linter: scripts before rules ---

_ENV_PREFIX = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)+")
_TOOLS = re.compile(r"^(?:grep|rg|od|awk|sed|find|test|diff|jq|yq|curl|ls|wc|cmp|Select-String|Get-Content|"
                    r"Test-Path)\b")


def is_command(code: str) -> bool:
    """Inline code a shell runs: brain.lint's commands, or a reading tool (grep, od, awk...), after any VAR=value."""
    c = _ENV_PREFIX.sub("", code.strip())
    return bool(lint._COMMAND.search(c) or _TOOLS.search(c))


def lint_lessons(store: Path) -> list[dict]:
    """The open or regressed lessons nothing enforces: a guard candidate when their check names a command (inline
    code a shell runs: git, gh, brain, pytest...), else a prose lesson to justify (props.why_not_script)."""
    out = []
    for r in rows(store):
        if r["status"] not in ("open", "regressed") or r["enforced_by"]:
            continue
        cmds = [c for c in lint._CODE.findall(r["check"]) if is_command(c)]
        pending = [x["id"] for x in r["led_to"] if x["status"] not in ("done", "dropped")]
        if cmds:
            out.append({"lesson": r["id"], "kind": "guard", "command": cmds[0], "fix": pending,
                        "say": f"its check is a command (`{cmds[0]}`): a test, a hook or brain check can run it"
                               + (f"; {', '.join(pending)} carries the fix" if pending else
                                  "; brain lint lessons --propose files the item")})
        elif not r["why_not_script"]:
            out.append({"lesson": r["id"], "kind": "prose", "command": "", "fix": pending,
                        "say": "its check names no command: give one in backticks, or say why not a script "
                               f"(brain item set {r['id']} why_not_script=...)"})
    return out


def propose_guards(store: Path, findings: list[dict], today: str | None = None) -> dict[str, list[str]]:
    """File the item proposal of each guard candidate that no open item fixes yet: {"filed": the new items,
    "linked": the open items close to a lesson, linked led_to instead}."""
    today = today or date.today().isoformat()
    out: dict[str, list[str]] = {"filed": [], "linked": []}
    for f in findings:
        if f["kind"] == "guard" and not f["fix"]:
            got = _maybe_propose(store, f["lesson"], today, force=True,
                                 why="is a guard candidate of brain lint lessons (its check is a command)")
            if got:
                out["filed" if got[1] else "linked"].append(got[0])
    return out


def render_lint(findings: list[dict]) -> list[str]:
    if not findings:
        return ["lessons: every open lesson is enforced, has a fix item, or says why it is not a script"]
    g = sum(1 for f in findings if f["kind"] == "guard")
    lines = [f"lessons: {g} guard candidate(s), {len(findings) - g} prose lesson(s) to justify"]
    lines += [f"  {f['kind']:<6} {f['lesson']}: {f['say']}" for f in findings]
    return lines


def store_of(project: projects.Project, root: Path | None = None) -> Path:
    stores = [s for s in project.stores if (s / "schema.yaml").is_file()]
    if not stores:
        raise LessonError(f"{project.name}: no graph store")
    return stores[0]
