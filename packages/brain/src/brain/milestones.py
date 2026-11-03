"""Milestone links without tokens: ``brain milestone suggest|apply|add``, and the orphans ``brain check`` flags
(wi-brain-milestone-autolink).

An orphan is an open work item (todo, doing, blocked) attached to no milestone: no ``part_of`` edge to a Milestone,
so the roadmap does not see it. The owner's ADR of 2026-11-01 ("Jalons : toujours proposer, jamais rattacher seul"):
a suggestion is only a proposal, ``props.milestone_proposed`` with ``props.milestone_reason``, shown ``ms-x?`` like a
proposed priority; ``apply`` writes the ``part_of`` edges once the owner has validated, the way research_graph's
``priorities apply`` does; a new milestone goes through the decision queue (``add``).

``suggest`` counts validated ``part_of`` edges towards the pending milestones, from three deterministic signals:

  1. spec: the milestone most other items of the same spec (``specified_by``) belong to;
  2. depends_on: the milestone most of its ``depends_on`` neighbours (both ways) belong to;
  3. theme: the milestone most other items of the same ``props.theme`` (each comma-separated part) belong to.

The first signal decides, the next ones break its ties, then the milestone id. A proposal already on an item is never
overwritten: ``suggest`` shows it, with the signals' choice when they disagree.

``add`` is run twice with the same flags: the first run asks the owner (a DDR whose first option creates the
milestone) and proposes the milestone on the items that have no proposal; once the owner chose that option, the second
run writes the Milestone node and the items' ``part_of`` edges. The owner is config.json's (brain.config).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import config, decisions, graph

WORK_OPEN = ("todo", "doing", "blocked")
SIGNALS = ("spec", "depends_on", "theme")
PROPOSED, REASON = "milestone_proposed", "milestone_reason"
LIST_MAX = 20  # ids named in brain check's line of orphans without a proposal (suggest lists them all)


def _load_list(path: Path) -> list:
    """A YAML list, read with libyaml's loader when PyYAML has it (a large store loads faster)."""
    if not path.is_file():
        return []
    data = graph.load_yaml_file(path)
    return data if isinstance(data, list) else []


def load(store: Path) -> tuple[dict[str, dict], list[dict]]:
    nodes = {str(n["id"]): n for f in sorted((store / "nodes").glob("*.yaml")) for n in _load_list(f)
             if isinstance(n, dict) and n.get("id")}
    files = [store / "edges.yaml", *sorted((store / "edges").glob("*.yaml"))]
    return nodes, [e for f in files for e in _load_list(f) if isinstance(e, dict) and e.get("from")]


def _props(node: dict) -> dict:
    p = node.get("props")
    return p if isinstance(p, dict) else {}


def themes(node: dict) -> list[str]:
    raw = _props(node).get("theme")
    return [" ".join(t.split()) for t in str(raw).split(",") if t.strip()] if raw not in (None, "") else []


@dataclass(frozen=True)
class Suggestion:
    milestone: str
    signal: str
    reason: str


@dataclass(frozen=True)
class Orphan:
    id: str
    status: str
    proposed: str  # props.milestone_proposed already on the item, '' when none
    exists: bool  # the proposed milestone is a Milestone of the store
    suggestion: Suggestion | None

    def line(self, ddr: str = "") -> str:
        s = self.suggestion
        if self.proposed:
            what = "proposed"
            if not self.exists:
                what += f"; not a milestone yet: {ddr}" if ddr else "; not a milestone yet: brain milestone add"
            elif s and s.milestone == self.proposed:
                what += "; the signals agree"
            elif s:
                what += f"; the signals say {s.milestone}? ({s.reason})"
            return f"{self.id} [{self.status}]: {self.proposed}? ({what})"
        if s:
            return f"{self.id} [{self.status}]: {s.milestone}? (new: {s.reason})"
        return f"{self.id} [{self.status}]: no signal (brain milestone add, or apply --set {self.id}=MS)"


class Index:
    """The links ``suggest`` reads: who is part of which milestone, specs, depends_on neighbours and themes."""

    def __init__(self, nodes: dict[str, dict], edges: list[dict]):
        self.nodes = nodes
        self.milestones = {k for k, n in nodes.items() if n.get("type") == "Milestone"}
        self.pending = {m for m in self.milestones if nodes[m].get("status") == "pending"}
        self.member: dict[str, set[str]] = defaultdict(set)
        self.specs: dict[str, set[str]] = defaultdict(set)
        self.by_spec: dict[str, set[str]] = defaultdict(set)
        self.deps: dict[str, set[str]] = defaultdict(set)
        self.by_theme: dict[str, set[str]] = defaultdict(set)
        for e in edges:
            src, dst, etype = str(e.get("from")), str(e.get("to")), e.get("type")
            if etype == "part_of" and dst in self.milestones:
                self.member[src].add(dst)
            elif etype == "specified_by":
                self.specs[src].add(dst)
                self.by_spec[dst].add(src)
            elif etype == "depends_on":
                self.deps[src].add(dst)
                self.deps[dst].add(src)
        for k, n in nodes.items():
            if n.get("type") == "WorkItem":
                for t in themes(n):
                    self.by_theme[t].add(k)

    def _live(self, nid: str) -> bool:
        n = self.nodes.get(nid) or {}
        return n.get("type") == "WorkItem" and n.get("status") != "dropped"

    def orphans(self) -> list[str]:
        return sorted(k for k, n in self.nodes.items() if n.get("type") == "WorkItem"
                      and n.get("status") in WORK_OPEN and not self.member.get(k))

    def suggest(self, nid: str) -> Suggestion | None:
        node = self.nodes[nid]
        specs, ths = sorted(self.specs.get(nid, ())), themes(node)
        others = {"spec": set().union(*(self.by_spec[s] for s in specs)),
                  "depends_on": set(self.deps.get(nid, ())),
                  "theme": set().union(*(self.by_theme[t] for t in ths))}
        others = {sig: {o for o in group if o != nid and self._live(o)} for sig, group in others.items()}
        counts = {sig: Counter(m for o in group for m in self.member.get(o, ()) if m in self.pending)
                  for sig, group in others.items()}
        candidates = set().union(*counts.values())
        if not candidates:
            return None
        best = min(candidates, key=lambda m: (tuple(-counts[s][m] for s in SIGNALS), m))
        signal = next(s for s in SIGNALS if counts[s][best])
        n, of = counts[signal][best], len(others[signal])
        if signal == "spec":
            reason = f"spec {', '.join(specs)}: {n} of {of} item(s) in {best}"
        elif signal == "depends_on":
            reason = f"depends_on: {n} of {of} neighbour(s) in {best}"
        else:
            reason = f"theme {', '.join(ths)}: {n} of {of} item(s) in {best}"
        return Suggestion(best, signal, reason)

    def orphan(self, nid: str) -> Orphan:
        n = self.nodes[nid]
        proposed = str(_props(n).get(PROPOSED) or "")
        return Orphan(nid, str(n.get("status")), proposed, proposed in self.milestones, self.suggest(nid))


def index(store: Path) -> Index:
    return Index(*load(store))


# --- suggest ---

def suggest(store: Path, only: list[str] | None = None, write: bool = False) -> list[Orphan]:
    """The orphans with their proposal or a suggestion; ``write`` stores the new suggestions as
    ``props.milestone_proposed`` and ``props.milestone_reason`` (an existing proposal is never touched)."""
    ix = index(store)
    orphans = ix.orphans()
    if only:
        unknown = sorted(set(only) - set(ix.nodes))
        if unknown:
            raise graph.GraphError(f"unknown ids: {', '.join(unknown)}")
        orphans = [o for o in orphans if o in set(only)]
    rows = [ix.orphan(o) for o in orphans]
    if write:
        for r in rows:
            if not r.proposed and r.suggestion:
                graph.set_item(store, r.id, [f"{PROPOSED}={r.suggestion.milestone}",
                                             f"{REASON}={r.suggestion.reason}"])
    return rows


def milestone_ddr(root: Path, mid: str) -> dict | None:
    """The newest DDR about creating ``mid``: one ``brain milestone add`` asked (id ending in new-milestone-<mid>),
    else one whose title names it ("New milestone ms-x?")."""
    word = re.compile(rf"(?<![A-Za-z0-9-]){re.escape(mid)}(?![A-Za-z0-9-])")
    hits = [d for _, d in decisions.load(root) if str(d.get("id", "")).endswith(f"-new-milestone-{mid}")
            or word.search(str(d.get("title", "")))]
    return max(hits, key=lambda d: (str((d.get("asked") or {}).get("at", "")), d["id"])) if hits else None


def ddr_note(root: Path | None, mid: str) -> str:
    d = milestone_ddr(root, mid) if root and (root / "records" / "ddr").is_dir() else None
    return f"{d['id']} [{d.get('status')}]" if d else ""


def orphan_lines(store: Path, root: Path | None = None) -> list[str]:
    """``brain check``'s warning about the orphans, grouped by proposal; nothing when the store has no milestone."""
    ix = index(store)
    if not ix.milestones:
        return []
    orphans = [ix.orphan(o) for o in ix.orphans()]
    if not orphans:
        return []
    by_ms: dict[str, list[str]] = defaultdict(list)
    for o in orphans:
        if o.proposed:
            by_ms[o.proposed].append(o.id)
    bare = [o.id for o in orphans if not o.proposed]
    lines = [f"warning: {len(orphans)} open item(s) attached to no milestone, outside the roadmap "
             "(brain milestone suggest)"]
    if by_ms:
        groups = []
        for ms, ids in sorted(by_ms.items()):
            note = "" if ms in ix.milestones else ddr_note(root, ms) or "brain milestone add"
            groups.append(f"{ms}?" + (f" (not a milestone yet: {note})" if note else "") + f" {', '.join(ids)}")
        lines.append(f"  proposed, waiting on {config.name_of()} (then brain milestone apply --write): "
                     f"{'; '.join(groups)}")
    if bare:
        more = f" and {len(bare) - LIST_MAX} more" if len(bare) > LIST_MAX else ""
        lines.append(f"  no proposal (brain milestone suggest --write): {', '.join(bare[:LIST_MAX])}{more}")
    return lines


# --- apply ---

@dataclass(frozen=True)
class Change:
    id: str
    proposed: str
    milestone: str
    linked: bool  # the part_of edge exists already: only the proposal is cleared

    def line(self) -> str:
        how = (f"{self.proposed}? -> {self.milestone}" if self.proposed == self.milestone
               else f"{self.proposed or '-'}? -> {self.milestone} ({config.name_of()}'s value)")
        return f"{self.id}: {how}" + (" (already linked: proposal cleared)" if self.linked else "")


def _pairs(store: Path) -> dict[tuple[str, str], str]:
    files = [store / "edges.yaml", *sorted((store / "edges").glob("*.yaml"))]
    return {(str(e.get("from")), str(e.get("to"))): str(e.get("type")) for f in files for e in _load_list(f)
            if isinstance(e, dict)}


def _write_links(store: Path, changes: list[Change], via: str, today: str | None) -> None:
    edges = [{"from": c.id, "to": c.milestone, "type": "part_of"} for c in changes if not c.linked]
    graph.append_edges(store, edges, "edges/work.yaml", f"{today or date.today().isoformat()}: {via}")
    for c in changes:
        node = graph.node_index(store, generated=False)[c.id][1]
        if PROPOSED in _props(node) or REASON in _props(node):
            graph.set_item(store, c.id, [f"{PROPOSED}=", f"{REASON}="])


def apply(store: Path, *, only: list[str] | None = None, skip: list[str] | None = None,
          overrides: dict[str, str] | None = None, write: bool = False, today: str | None = None) -> list[Change]:
    """Turn proposals into ``part_of`` edges once the owner has validated them. Every work item with a proposal is
    validated as proposed, except those in ``skip`` (and, with ``only``, those not in it); ``overrides`` (id ->
    milestone) validates an item with the owner's milestone instead, and may attach an item that has no proposal. A
    proposal naming no milestone of the store (one still waiting on ``brain milestone add``) is left as it is. The
    proposal props are removed once the edge is written. Returns the changes; writes only with ``write``."""
    ix = index(store)
    overrides = dict(overrides or {})
    only_set = set(only) if only is not None else None
    skip_set = set(skip or ())
    unknown = sorted((set(overrides) | (only_set or set()) | skip_set) - set(ix.nodes))
    if unknown:
        raise graph.GraphError(f"unknown ids: {', '.join(unknown)}")
    for nid, ms in overrides.items():
        if ms not in ix.milestones:
            raise graph.GraphError(f"{nid}={ms}: {ms} is not a milestone (brain milestone add)")
        if ix.nodes[nid].get("type") != "WorkItem":
            raise graph.GraphError(f"{nid}: not a work item")
    pairs = _pairs(store)
    changes = []
    for nid, node in sorted(ix.nodes.items()):
        if node.get("type") != "WorkItem" or node.get("status") == "dropped" or nid in skip_set:
            continue
        if only_set is not None and nid not in only_set and nid not in overrides:
            continue
        proposed = str(_props(node).get(PROPOSED) or "")
        target = overrides.get(nid, proposed)
        if not target or target not in ix.milestones:
            continue
        if ix.nodes[target].get("status") == "dropped":
            raise graph.GraphError(f"{nid}: {target} is dropped")
        existing = pairs.get((nid, target))
        if existing and existing != "part_of":
            raise graph.GraphError(f"{nid} -> {target}: already linked ({existing}), not part_of")
        changes.append(Change(nid, proposed, target, existing == "part_of"))
    if write and changes:
        _write_links(store, changes, f"brain milestone apply (validated by {config.owner_of()})", today)
    return changes


def waiting(store: Path) -> list[str]:
    """Proposals that ``apply`` leaves: their milestone is not in the store yet."""
    ix = index(store)
    return sorted(f"{k}: {_props(n)[PROPOSED]}?" for k, n in ix.nodes.items() if n.get("type") == "WorkItem"
                  and n.get("status") != "dropped" and _props(n).get(PROPOSED)
                  and str(_props(n)[PROPOSED]) not in ix.milestones)


# --- add ---

class Pending(Exception):
    """The DDR waits on the owner (``answered`` False), or their answer is not the creation (True)."""

    def __init__(self, message: str, answered: bool):
        super().__init__(message)
        self.answered = answered


def _best_existing(ix: Index, items: list[str]) -> Suggestion | None:
    found = [s for s in (ix.suggest(i) for i in items if i in ix.nodes) if s]
    if not found:
        return None
    votes = Counter(s.milestone for s in found)
    best = min(votes, key=lambda m: (-votes[m], m))
    return next(s for s in found if s.milestone == best)


def ask(root: Path, store: Path, mid: str, *, title: str, trigger: str, items: list[str], why: str, at: str,
        parent: str = "", options: list[str] | None = None, context: str = "", project: str = "",
        session: str = "") -> tuple[dict, list[str]]:
    """Put the creation of ``mid`` to the owner: a DDR whose first (recommended) option creates it with its items, then
    the alternatives given, else the best existing milestone for the items, then no milestone. The items without a
    proposal get ``milestone_proposed: mid``. Returns the DDR and the items whose other proposal was kept."""
    ix = index(store)
    unknown = sorted(set(items) - set(ix.nodes))
    if unknown:
        raise graph.GraphError(f"unknown ids: {', '.join(unknown)}")
    if parent and parent not in ix.milestones:
        raise graph.GraphError(f"{parent}: not a milestone (--parent)")
    listed = ", ".join(items) if items else "no item yet"
    opts = [f"Create {mid}:: «{title}», reached when: {trigger}; part_of it: {listed}"
            + (f"; part of {parent}" if parent else "")]
    if options:
        opts += list(options)
    else:
        best = _best_existing(ix, items)
        if best:
            opts.append(f"Use {best.milestone}:: no new milestone, the items go to {best.milestone} ({best.reason})")
        opts.append("No milestone:: the items stay outside the roadmap, brain check keeps flagging them")
    ddr, _ = decisions.ask(root, title=f"New milestone {mid}?", question=f"Create the milestone {mid} «{title}»?",
                           options=opts, why=why, at=at, context=context or f"Trigger: {trigger}",
                           blocks=f"the part_of edges of {listed}" if items else "", items=items or None,
                           project=project, session=session, slug=f"new-milestone-{mid}")
    kept = []
    for i in items:
        p = str(_props(ix.nodes[i]).get(PROPOSED) or "")
        if p and p != mid:
            kept.append(f"{i} ({p}?)")
        elif not p:
            graph.set_item(store, i, [f"{PROPOSED}={mid}", f"{REASON}=new milestone, {ddr['id']}"])
    return ddr, kept


def _chose_creation(ddr: dict, mid: str) -> bool:
    first = ((ddr.get("options") or [{}])[0]).get("label", "")
    chosen = (ddr.get("answer") or {}).get("choices") or []
    return first in chosen and mid in first


def create(root: Path, store: Path, mid: str, ddr: dict, *, title: str, trigger: str, items: list[str],
           parent: str = "", today: str | None = None) -> list[Change]:
    """The owner chose the creation in ``ddr``: write the Milestone node (unless it exists already), then the part_of
    edges of the items (``items`` and the DDR's linked items), clearing their proposals."""
    owner = config.owner_of()
    if ddr.get("status") == "pending":
        raise Pending(f"{ddr['id']} waits on {owner}: brain decision answer {ddr['id']} <option>", False)
    ans = ddr.get("answer") or {}
    if not _chose_creation(ddr, mid):
        said = ", ".join(ans.get("choices") or []) or ans.get("other") or "no answer"
        raise Pending(f"{ddr['id']}: {ans.get('by') or owner} answered «{said}», not the creation of {mid}; apply "
                      f"that answer instead (brain milestone apply --set ID=MS, brain item set)", True)
    index_ = graph.node_index(store)
    day = today or date.today().isoformat()
    if mid not in index_:
        answered = str((ddr.get("answer") or {}).get("at", ""))[:10] or day
        graph.add_item(store, mid, title, node_type="Milestone", status="pending",
                       props={"trigger": trigger, "decided": f"{ans.get('by') or owner}, {answered} ({ddr['id']})"},
                       milestone=parent, today=day)
    elif index_[mid][1].get("type") != "Milestone":
        raise graph.GraphError(f"{mid}: exists and is not a milestone")
    linked = list(dict.fromkeys(list(items) + list((ddr.get("links") or {}).get("items") or [])))
    ix = index(store)
    linked = [i for i in linked if (ix.nodes.get(i) or {}).get("type") == "WorkItem"]
    pairs = _pairs(store)
    changes = [Change(i, str(_props(ix.nodes[i]).get(PROPOSED) or ""), mid, pairs.get((i, mid)) == "part_of")
               for i in linked]
    clash = [f"{c.id} ({pairs[(c.id, mid)]})" for c in changes if (c.id, mid) in pairs and not c.linked]
    if clash:
        raise graph.GraphError(f"already linked to {mid} by another edge type: {', '.join(clash)}")
    if changes:
        _write_links(store, changes, f"brain milestone add {mid} ({ddr['id']})", day)
    return changes
