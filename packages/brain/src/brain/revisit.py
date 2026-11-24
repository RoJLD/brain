"""The Revisit-if report: ``brain adr revisit [--json] [--all] [--today D]`` (wi-brain-adr-revisit-report; spec
decision premises, PREM-2 and PREM-4).

An ADR's « Revisit if » says when its decision should be looked at again. Nothing watched it: a trigger was met and
nobody noticed. This module reads the triggers from the ADRs' prose, at zero token, and says which are already met
or lapsed, each with its evidence. It writes nothing and changes no schema: the decision log stays as it was written.

The triggers it reads in the « Revisit if » of each ADR still in force (no ``supersedes`` edge reaches it, its node
not superseded; a field left TODO is skipped):

- **node**: an id of the graph (an item, a milestone, a feature, a rule, a DDR) now done, reached, have, retired,
  answered, integrated or archived: ``met``; dropped: ``lapsed`` (what the trigger waited for will not come). A wave
  milestone is a ``wave``.
- **wave**: a wave named in prose (``wave s9``, ``vague s9``, ``(s9)``; a bare ``s9`` is not read: « an s3 bucket »)
  or by the release it shipped as (``0.6.0``), now reached (closed): ``met``.
- **date**: a day (YYYY-MM-DD) after the ADR's day and now reached (today included), or a span from the ADR's day
  (« after a month », « in its first month », « après deux semaines », « au bout d'un mois ») now elapsed: ``lapsed``
  (the review it promised is due).
- **config**: a dotted key of the project's ``config.json`` (``floor.refuse``) whose value now differs from its value
  on the ADR's day, as git's first-parent history holds them (a commit is dated by the day it reached the branch, a
  merge's): ``met``, with both values and the commit that first changed it. A key that holds a mapping changes with
  any of its sub-keys.

« met » says what the trigger names is closed, never that the condition the prose states holds: an id read in a
consequence clause (« then wi-x ») or a release a trigger had to come before is read the same. The report points to
the ADRs to read again; the reader judges.

A node, wave or key closed on or before the ADR's own day is not a trigger: the ADR was written knowing it. A node
whose closing day is unknown is kept, its evidence says so.

A flagged ADR that a later ADR names by its id, dated on or after its newest trigger, is **reviewed**: left out of the
report but counted (``--all`` shows it). That is how a revisit is closed without a schema: the new ADR that says what
was looked at, a reversal (``brain adr new --reverses``, which supersedes it) or a plain ADR that cites it.

Its readers: ``brain adr revisit``; ``brain resume`` (a section, the flagged ADRs); ``brain digest`` (the triggers met
in its window); :func:`related`, the source a token-free ``brain spec context`` reads (wi-brain-spec-build-path).
The ``--json`` keys are a public contract (``v`` 1, keys only added): ``v, today, logs, adrs, with_revisit, flagged,
reviewed, counts``; each flagged ADR ``id, day, title, file, line, revisit, triggers, reviewed_by``; each trigger
``kind, ref, state, day, evidence``. An unknown kind a later engine adds is shown as it is.
"""

from __future__ import annotations

import calendar
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from . import actions, graph, notes, targets, waves

V = 1
KINDS = ("node", "wave", "date", "config")
# a node's status -> the trigger's state
STATES = {"done": "met", "reached": "met", "have": "met", "retired": "met", "answered": "met", "integrated": "met",
          "archived": "met", "dropped": "lapsed"}
CONFIG = "config.json"
_DATE_RE = re.compile(r"(?<![\d-])(\d{4}-\d{2}-\d{2})(?![\d-])")
_KEY_RE = re.compile(r"(?<![\w./-])([a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)+)(?![\w-])")
_VERSION_RE = re.compile(r"(?<![\w.-])(\d+\.\d+\.\d+)(?![\w-]|\.\d)")
_WAVE_RE = re.compile(r"(?<![\w-])(?:waves?|vagues?)\s+(s\d{1,3})(?![\w-])|\((s\d{1,3})\)", re.I)
_NUMBERS = {"a": 1, "an": 1, "one": 1, "un": 1, "une": 1, "two": 2, "deux": 2, "three": 3, "trois": 3, "four": 4,
            "quatre": 4, "five": 5, "cinq": 5, "six": 6}
_UNIT = r"days?|weeks?|months?|years?|jours?|semaines?|mois|ans?|années?"
_SPAN_RE = re.compile(
    rf"(?<!\w)(?:(?:after|in|within|dans|après|sous|au bout de|d['’]ici)\s+|au bout d['’]\s?)(?:(?:its|their|the|"
    rf"son|sa|ses|le|la|les)\s+)?(?P<n>\d{{1,3}}|{'|'.join(_NUMBERS)})\s+(?P<u>{_UNIT})(?!\w)"
    rf"|(?<!\w)(?:(?:in|within|during|dans|pendant|au|en)\s+(?:(?:its|their|the|son|sa|ses|le|la|les)\s+)?)?"
    rf"(?:first|premier|première)\s+(?P<u1>week|month|year|semaine|mois|année)(?!\w)", re.I)


@dataclass
class Trigger:
    kind: str
    ref: str
    state: str
    day: str          # when it was met or lapsed ('' unknown)
    evidence: str

    def row(self) -> dict:
        return {"kind": self.kind, "ref": self.ref, "state": self.state, "day": self.day, "evidence": self.evidence}


@dataclass
class Context:
    """What the triggers are checked against, loaded once."""
    nodes: dict[str, dict]
    plan: waves.Plan | None
    today: str
    root: Path | None
    store: Path | None
    _config: "ConfigHistory | None" = None
    _closures: dict[str, tuple[str, str]] | None = None

    def config(self) -> "ConfigHistory":
        if self._config is None:
            self._config = ConfigHistory(self.root)
        return self._config

    def closed_day(self, nid: str) -> str:
        """The day a node was closed: its dated prop (brain item close); a DDR's, the day of its answer in its record;
        else, for an item or a milestone, the commit that closed it (one ``git log -p`` of the store's nodes, read
        only when such a node has no dated prop); '' unknown."""
        from .digest import closed_on, git_closures   # brain.digest imports brain.resume, which reads this module
        n = self.nodes.get(nid) or {}
        day = closed_on(n)[0]
        if day or not self.root:
            return day
        if n.get("type") == "DDR":
            return _ddr_day(self.root, n)
        if not self.store or n.get("type") not in ("WorkItem", "Milestone"):
            return ""
        if self._closures is None:
            self._closures = git_closures(self.root, self.store)
        return (self._closures.get(nid) or ("", ""))[0]


def _ddr_day(root: Path, node: dict) -> str:
    """The day a DDR node's record was answered (its ``answer.at``), from the record its anchor names; '' unknown."""
    rel = str(node.get("anchor") or "").partition("#")[0]
    rec = graph.load_yaml_file(root / rel) if rel.endswith(".yaml") and (root / rel).is_file() else None
    at = str(((rec or {}).get("answer") or {}).get("at") or "") if isinstance(rec, dict) else ""
    return at[:10] if _day(at[:10]) else ""


class ConfigHistory:
    """The project's config.json along git's first-parent history (a merge dated by the day it reached the branch):
    its commits, oldest first, and each version, read in one ``git cat-file --batch``; a version that is not a JSON
    object is skipped, a commit without the file reads as {}."""

    def __init__(self, root: Path | None):
        self.root = root
        out = actions.git(root, "log", "--first-parent", "--format=%H %cs", "--", CONFIG, timeout=30) if root else ""
        commits = [tuple(line.split(" ", 1)) for line in reversed(out.splitlines()) if " " in line]
        docs = _versions(root, [sha for sha, _ in commits]) if commits else {}
        self.versions = [(sha, day, docs[sha]) for sha, day in commits if docs.get(sha) is not None]

    def changed(self, key: str, after: str) -> Trigger | None:
        """``key`` (a dotted path) when its value now (the newest version) differs from its value on the day
        ``after`` (the newest version on or before it), with the commit that first changed it; None when it is the
        same, or when neither version has it (not a key of config.json)."""
        before = [v for v in self.versions if v[1] <= after]
        later = [v for v in self.versions if v[1] > after]
        if not later:
            return None
        base = lookup(before[-1][2], key) if before else _MISSING
        now = lookup(later[-1][2], key)
        if now == base:
            return None
        sha, day, _ = next(v for v in later if lookup(v[2], key) != base)
        return Trigger("config", key, "met", day, f"{key}: {_show(base)} on the ADR's day, {_show(now)} now; first "
                                                  f"changed in {sha[:8]} ({day}, {CONFIG})")


def _versions(root: Path, shas: list[str]) -> dict[str, dict | None]:
    """{commit: config.json at it, parsed}: {} when the commit has no such file, None when it is not a JSON object;
    read in one process."""
    prefix = actions.git(root, "rev-parse", "--show-prefix")
    spec = "".join(f"{sha}:{prefix}{CONFIG}\n" for sha in shas).encode()
    try:
        raw = subprocess.run(["git", "-C", str(root), "cat-file", "--batch"], input=spec, capture_output=True,
                             timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    out: dict[str, dict | None] = {}
    pos = 0
    for sha in shas:
        end = raw.find(b"\n", pos)
        if end < 0:
            break
        head = raw[pos:end].split()
        pos = end + 1
        if len(head) == 3 and head[1] == b"blob" and head[2].isdigit():
            size = int(head[2])
            body, pos = raw[pos:pos + size], pos + size + 1
            try:
                d = json.loads(body.decode("utf-8"))
            except ValueError:
                d = None
            out[sha] = d if isinstance(d, dict) else None
        else:   # "<spec> missing": the file is not in that commit
            out[sha] = {}
    return out


_MISSING = object()


def lookup(doc, key: str):
    """The value at a dotted ``key`` of ``doc``, else _MISSING."""
    cur = doc
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


def _show(v) -> str:
    if v is _MISSING:
        return "(absent)"
    text = json.dumps(v, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= 40 else text[:39] + "…"


def add_span(day: date, n: int, unit: str) -> date:
    """``day`` plus ``n`` units (a month is a calendar month, its day kept or the month's last)."""
    u = unit.lower()
    if u.startswith(("day", "jour")):
        return day + timedelta(days=n)
    if u.startswith(("week", "semaine")):
        return day + timedelta(weeks=n)
    months = n * (12 if u.startswith(("year", "an")) else 1)
    y, m = divmod(day.month - 1 + months, 12)
    y, m = day.year + y, m + 1
    return date(y, m, min(day.day, calendar.monthrange(y, m)[1]))


def _day(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


# --- the triggers of one ADR -----------------------------------------------------------------------------------------

def triggers(text: str, adr_day: str, ctx: Context, own: str = "") -> list[Trigger]:
    """The met or lapsed triggers of a « Revisit if » ``text`` written on ``adr_day``; ``own``: the ADR's id, never
    a trigger of itself."""
    out: dict[tuple[str, str], Trigger] = {}

    def keep(t: Trigger | None) -> None:
        if t and (t.kind, t.ref) not in out and (not t.day or t.day > adr_day):
            out[(t.kind, t.ref)] = t

    for m in targets._ID_RE.finditer(text):
        nid = m.group(1).rstrip(".")
        if nid != own and nid in ctx.nodes:
            keep(_node(nid, ctx))
    for m in _WAVE_RE.finditer(text):
        wid = f"wave-{(m.group(1) or m.group(2)).lower()}"
        if waves.kind(ctx.nodes.get(wid) or {}) == waves.WAVE:
            keep(_node(wid, ctx, f"{m.group(0).strip()}"))
    if ctx.plan is not None:
        for m in _VERSION_RE.finditer(text):
            wid = ctx.plan.resolve(m.group(1))
            if wid:
                keep(_node(wid, ctx, m.group(1)))
    keep_dates(text, adr_day, ctx.today, keep)
    for m in _KEY_RE.finditer(text):
        key = m.group(1)
        if key in ctx.nodes or not ctx.root:
            continue
        keep(ctx.config().changed(key, adr_day))
    return sorted(out.values(), key=lambda t: (KINDS.index(t.kind) if t.kind in KINDS else len(KINDS), t.ref))


def _node(nid: str, ctx: Context, said: str = "") -> Trigger | None:
    n = ctx.nodes.get(nid) or {}
    status = str(n.get("status") or "")
    state = STATES.get(status)
    if not state:
        return None
    kind = "wave" if waves.kind(n) == waves.WAVE else "node"
    day = ctx.closed_day(nid)
    shipped = (n.get("props") or {}).get("shipped_as") if kind == "wave" else ""
    ev = f"{nid} ({n.get('type', '?')}) {status}" + (f" {day}" if day else ", its day unknown") \
        + (f", shipped as {shipped}" if shipped else "") + (f" (named « {said} »)" if said and said != nid else "")
    return Trigger(kind, nid, state, day, ev)


def keep_dates(text: str, adr_day: str, today: str, keep) -> None:
    """The days and spans of ``text`` past by ``today``: a day after the ADR's, a span counted from it."""
    start = _day(adr_day)
    for m in _DATE_RE.finditer(text):
        d = m.group(1)
        if _day(d) and adr_day < d <= today:
            keep(Trigger("date", d, "lapsed", d, f"the day {d} named is past (today {today})"))
    if not start:
        return
    for m in _SPAN_RE.finditer(text):
        said_n = (m.group("n") or "").lower()
        n = (_NUMBERS.get(said_n) or int(said_n)) if said_n else 1
        unit = m.group("u") or m.group("u1")
        due = add_span(start, n, unit).isoformat()
        if due <= today:
            said = " ".join(m.group(0).split())
            keep(Trigger("date", said, "lapsed", due, f"« {said} » from {adr_day}: due {due}, past (today {today})"))


# --- the report -------------------------------------------------------------------------------------------------------

def context(store: Path | None, root: Path | None, today: str) -> tuple[Context, set[str]]:
    """What the triggers are checked against, and the ADRs no longer in force (a supersedes edge reaches it, or its
    node says superseded): the store read once."""
    has = bool(store and store.is_dir())
    nodes = {nid: n for nid, (_, n) in graph.node_index(store).items()} if has else {}
    edges = targets._edges(store) if has else []
    plan = waves.build(nodes, edges) if any(waves.kind(n) in waves.KINDS for n in nodes.values()) else None
    gone = {str(e["to"]) for e in edges if e.get("type") == "supersedes"}
    gone |= {nid for nid, n in nodes.items() if n.get("status") == "superseded"}
    return Context(nodes, plan, today, root, store), gone


def report(store: Path | None, logs: list[Path], root: Path | None = None, today: str = "",
           show_all: bool = False) -> dict:
    """The report over the decision ``logs`` (an id two logs give read once, from the first)."""
    today = today or date.today().isoformat()
    ctx, gone = context(store, root, today)
    used, entries = _entries(logs, root)
    live = [(f, a) for f, a in entries if a["id"] not in gone]
    texts = _revisits(live)
    rows = [r for r in (_flag(rel, a, text, ctx, entries) for rel, a, text in texts) if r]
    flagged = _ordered([r for r in rows if show_all or not r["reviewed_by"]])
    return {"v": V, "today": today, "logs": used, "adrs": len(live), "with_revisit": len(texts),
            "flagged": flagged, "reviewed": sum(1 for r in rows if r["reviewed_by"]), "counts": _counts(flagged)}


def _revisits(live: list[tuple[str, dict]]) -> list[tuple[str, dict, str]]:
    """(log, ADR, its « Revisit if ») of the ADRs whose field is said and not TODO."""
    out = [(rel, a, targets.fields(a["text"]).get("Revisit if", "")) for rel, a in live]
    return [(rel, a, text) for rel, a, text in out if text.strip() and not targets._todo(text)]


def _ordered(rows: list[dict]) -> list[dict]:
    """The newest trigger first, then by id."""
    return sorted(sorted(rows, key=lambda x: x["id"]), key=lambda x: max(t["day"] for t in x["triggers"]),
                  reverse=True)


def _counts(rows: list[dict]) -> dict[str, int]:
    return {k: sum(1 for f in rows for t in f["triggers"] if t["kind"] == k) for k in KINDS}


def _entries(logs: list[Path], root: Path | None) -> tuple[list[str], list[tuple[str, dict]]]:
    """(the logs read, relative; each ADR with its log's path), an id two logs give read once, from the first."""
    used, entries, seen = [], [], set()
    for log in logs:
        if not log or not log.is_file():
            continue
        rel = targets._rel(log, root)
        used.append(rel)
        for a in notes.adr_entries(log.read_text(encoding="utf-8")):
            if a["id"] not in seen:
                seen.add(a["id"])
                entries.append((rel, a))
    return used, entries


def _flag(rel: str, a: dict, text: str, ctx: Context, entries: list[tuple[str, dict]]) -> dict | None:
    """The report's row of the ADR ``a`` when its « Revisit if » ``text`` has a trigger met or lapsed, with the
    later ADRs that name it on or after its newest trigger (reviewed_by); None when none has."""
    found = triggers(text, a["day"], ctx, own=a["id"])
    if not found:
        return None
    newest = max(t.day for t in found)
    named = re.compile(rf"(?<![\w-]){re.escape(a['id'])}(?![\w-])")   # the id itself, never a prefix of another
    by = [b["id"] for _, b in entries
          if b["id"] != a["id"] and b["day"] > a["day"] and b["day"] >= newest and named.search(b["text"])]
    return {"id": a["id"], "day": a["day"], "title": notes.ADR_SUFFIX_RE.sub("", a["title"]), "file": rel,
            "line": a["line"], "revisit": text, "triggers": [t.row() for t in found], "reviewed_by": by}


def summary(rep: dict) -> str:
    counts = ", ".join(f"{k} {n}" for k, n in rep["counts"].items() if n) or "none"
    return (f"revisit: {rep['adrs']} ADR(s) in force, {rep['with_revisit']} with a Revisit if; "
            f"{len(rep['flagged'])} with a trigger met or lapsed (triggers: {counts}); "
            f"{rep['reviewed']} reviewed by a later ADR")


def trigger_text(t: dict) -> str:
    return f"{t['state']} {t['kind']}: {t['evidence']}"


def render(rep: dict) -> list[str]:
    lines = [summary(rep) + (" (shown)" if any(f["reviewed_by"] for f in rep["flagged"]) else
                             " (--all shows them)" if rep["reviewed"] else "")]
    for f in rep["flagged"]:
        lines.append(f"- {f['id']} ({f['file']}:{f['line']}): {f['title']}"
                     + (f" [reviewed by {', '.join(f['reviewed_by'])}]" if f["reviewed_by"] else ""))
        lines += [f"    {trigger_text(t)}" for t in f["triggers"]]
    if not rep["flagged"]:
        lines.append("No Revisit-if trigger met or lapsed.")
    return lines


def in_window(rep: dict, since: str, until: str) -> list[dict]:
    """The flagged ADRs with a trigger met or lapsed in [since, until] (a day known), only those triggers kept: the
    weekly digest's section."""
    out = []
    for f in rep["flagged"]:
        hits = [t for t in f["triggers"] if t["day"] and since <= t["day"] <= until]
        if hits:
            out.append({**f, "triggers": hits})
    return out


def related(rep: dict, refs: set[str] | None = None, words: list[str] | None = None) -> list[dict]:
    """The flagged ADRs a subject touches: a trigger's ref among ``refs`` (node ids, keys), or every one of
    ``words`` (case folded) in the ADR's title or its « Revisit if ». The source ``brain spec context`` reads
    (wi-brain-spec-build-path): the decisions a brainstorm may reopen."""
    refs = set(refs or ())
    words = [w.lower() for w in words or [] if w.strip()]
    out = []
    for f in rep["flagged"]:
        hay = f"{f['title']} {f['revisit']}".lower()
        if (refs and refs & {t["ref"] for t in f["triggers"]}) or (words and all(w in hay for w in words)):
            out.append(f)
    return out
