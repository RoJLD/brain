"""Derive node stubs for the research knowledge graph from the repo itself.

The validator (``validate.check_coverage``) requires one ``Experiment`` node per
``experiments/expNNN_*/`` directory and at least one ``SDR``/``ADR`` node per dated
``## YYYY-MM-DD`` heading in ``notes/scientific_decisions.md`` / ``notes/decisions.md`` (or the logs
``--decisions`` names).
Keeping those by hand drifts (the arc exp007->032 was 27 experiments behind). This module
*derives* the missing stubs from the filesystem + decision headings so ``graph-check`` stays
green, and is the fill-step behind the ``/wrap-up`` discipline. Edges + precise statuses stay
hand-curated in the store -- this only closes the coverage gap, it does not invent semantics.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path

import networkx as nx
import yaml

from . import yamlio
from .validate import _key, _node_decision_date_counts, decision_logs

_HEADING_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})\s*[—:\-]*\s*(.*?)\s*$")
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_EXP_VERDICT_RE = re.compile(r"^v-(exp\d+.*)$")  # v-expNNN_*, not v-explore-*


def _slug(text: str, maxlen: int = 48) -> str:
    s = _SLUG_RE.sub("-", text.lower()).strip("-")
    return s[:maxlen].strip("-") or "entry"


def _title_from_readme(exp_dir: Path) -> str:
    readme = exp_dir / "README.md"
    if readme.exists():
        for line in readme.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                t = line[2:].strip()
                # drop a leading "expNNN — " prefix for a cleaner title
                return re.sub(r"^exp\d+\s*[—:\-]\s*", "", t)[:90]
    return exp_dir.name


def _headings(path: Path) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _HEADING_RE.match(line)
        if m:
            out.append((m.group(1), m.group(2)))
    return out


def experiment_stubs(graph: nx.DiGraph, repo_root: Path) -> list[dict]:
    """One Experiment node per experiments/exp*/ dir missing from the graph."""
    have = {n for n, a in graph.nodes(data=True) if a.get("type") == "Experiment"}
    exp_root = repo_root / "experiments"
    stubs: list[dict] = []
    if not exp_root.exists():
        return stubs
    for d in sorted(p for p in exp_root.glob("exp*") if p.is_dir()):
        if d.name in have:
            continue
        stubs.append(
            {
                "id": d.name,
                "type": "Experiment",
                "title": _title_from_readme(d),
                "status": "active",
            }
        )
    return stubs


def decision_stubs(
    graph: nx.DiGraph, repo_root: Path, logs: Iterable[str | Path] | None = None
) -> list[dict]:
    """SDR/ADR stubs to cover the deficit (headings - existing nodes) per (file, date), for each decision log the store
    covers (``logs``, relative to the repo root; None: notes/scientific_decisions.md and notes/decisions.md), each stub
    anchored at its log's path."""
    existing = _node_decision_date_counts(graph)
    out: list[dict] = []
    for rel, ntype in decision_logs(logs):
        f = repo_root / rel
        if not f.exists():
            continue
        by_date: dict[str, list[str]] = {}
        for date, title in _headings(f):
            by_date.setdefault(date, []).append(title)
        for date, titles in sorted(by_date.items()):
            deficit = len(titles) - existing.get((_key(rel), date), 0)
            # cover the deficit with the LAST `deficit` headings of that date (the new ones)
            for title in titles[len(titles) - deficit :] if deficit > 0 else []:
                slug = _slug(title) if title else "entry"
                out.append(
                    {
                        "id": f"{ntype.lower()}-{date}-{slug}",
                        "type": ntype,
                        "title": (title or f"{ntype} {date}")[:90],
                        "status": "active",
                        "anchor": f"{rel}#{date}-{slug}",
                    }
                )
    return out


def hypothesis_nodes_edges(repo_root: str | Path) -> tuple[list[dict], list[dict]]:
    """Derive L2 Hypothesis stubs + (instantiates, tests) edges from each config `hypothesis:`."""
    root = Path(repo_root)
    exp_root = root / "experiments"
    nodes: list[dict] = []
    edges: list[dict] = []
    if not exp_root.exists():
        return nodes, edges
    for d in sorted(p for p in exp_root.glob("exp*") if p.is_dir()):
        cfg = d / "config.yaml"
        if not cfg.exists():
            continue
        try:
            data = yamlio.load(cfg) or {}
        except yaml.YAMLError:
            continue
        h = data.get("hypothesis")
        if not isinstance(h, dict) or not h.get("l1"):
            continue
        l2_id = f"h2-{d.name}"
        nodes.append(
            {
                "id": l2_id,
                "type": "Hypothesis",
                "level": "L2",
                "status": "proposed",
                "title": str(h.get("prediction", d.name))[:90],
            }
        )
        edges.append({"from": l2_id, "to": str(h["l1"]), "type": "instantiates"})
        edges.append({"from": d.name, "to": l2_id, "type": "tests"})
    return nodes, edges


def hypothesis_l1_stubs(hand_graph: nx.DiGraph, repo_root: str | Path) -> list[dict]:
    """One L1 Hypothesis stub per `l1:` referenced in a config hypothesis: block with no
    hand-curated node yet (keeps the L2 `instantiates -> L1` edge from dangling). Self-heals:
    once the L1 is curated in a hand file, the deficit drops the stub at the next sync."""
    root = Path(repo_root)
    exp_root = root / "experiments"
    seen: dict[str, str] = {}  # l1 id -> first declaring experiment
    if exp_root.exists():
        for d in sorted(p for p in exp_root.glob("exp*") if p.is_dir()):
            cfg = d / "config.yaml"
            if not cfg.exists():
                continue
            try:
                data = yamlio.load(cfg) or {}
            except yaml.YAMLError:
                continue
            h = data.get("hypothesis")
            if not isinstance(h, dict) or not h.get("l1"):
                continue
            seen.setdefault(str(h["l1"]), d.name)
    out: list[dict] = []
    for l1, exp in sorted(seen.items()):
        if l1 in hand_graph:
            continue
        out.append(
            {
                "id": l1,
                "type": "Hypothesis",
                "level": "L1",
                "status": "planned",
                "title": f"{l1} — STUB (declared by {exp}; needs curated prose)",
            }
        )
    return out


_VERDICT_STATUS = {"validates": "validated", "refutes": "rejected", "inconclusive": "inconclusive"}


def _dig(d, path: str):
    """Navigate a dotted key path through nested dicts; None if any part is missing."""
    cur = d
    for part in str(path).split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _eval_verdict(value, op: str, threshold) -> bool:
    if op == "lt":
        return value < threshold
    if op == "gt":
        return value > threshold
    return value == threshold  # default / "eq"


def hypothesis_verdict_nodes_edges(repo_root: str | Path) -> tuple[list[dict], list[dict]]:
    """Derive a Verdict node + (produces, validates/refutes/inconclusive) edges from each config
    `hypothesis.verdict` block evaluated against the experiment's `results/diagnostics.json`.

    The verdict thus comes from the DATA (not a hand assertion): `{field, op, threshold, pass, fail}`
    reads `diagnostics["verdict"][field]` (or top-level), compares, and picks the pass/fail edge type.
    No diagnostics / no verdict block -> no edge (graceful; results/ is gitignored & may be absent).
    """
    root = Path(repo_root)
    exp_root = root / "experiments"
    nodes: list[dict] = []
    edges: list[dict] = []
    if not exp_root.exists():
        return nodes, edges
    for d in sorted(p for p in exp_root.glob("exp*") if p.is_dir()):
        cfg = d / "config.yaml"
        if not cfg.exists():
            continue
        try:
            data = yamlio.load(cfg) or {}
        except yaml.YAMLError:
            continue
        h = data.get("hypothesis")
        if not isinstance(h, dict) or not h.get("l1"):
            continue
        v = h.get("verdict")
        if not isinstance(v, dict) or "field" not in v:
            continue
        diag_path = d / "results" / "diagnostics.json"
        if not diag_path.exists():
            continue
        try:
            diag = json.loads(diag_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        field = v["field"]
        value = _dig(diag.get("verdict"), field)
        if value is None:
            value = _dig(diag, field)
        if value is None:
            continue
        passed = _eval_verdict(value, str(v.get("op", "eq")), v.get("threshold"))
        etype = v.get("pass") if passed else v.get("fail")
        # v2 surrogate guard: a `validates` that did NOT survive its surrogate/permutation null does
        # not count as a validation — it is downgraded to `inconclusive`. An ABSENT field is tolerated
        # (an experiment is not penalised for never running a surrogate test, e.g. exp037's sign-test).
        # Catches the funding-flight pattern: a point estimate "passes" but the surrogate family
        # collapses the effect. Field read from diagnostics["verdict"]["surrogate_survived"] or top level.
        downgraded = False
        if etype == "validates":
            surv = _dig(diag.get("verdict"), "surrogate_survived")
            if surv is None:
                surv = _dig(diag, "surrogate_survived")
            if surv is False:
                etype = "inconclusive"
                downgraded = True
        if etype not in _VERDICT_STATUS:
            continue
        vid = f"v-{d.name}"
        note = " (validates voided: surrogate_survived=false)" if downgraded else ""
        nodes.append(
            {
                "id": vid,
                "type": "Verdict",
                "status": _VERDICT_STATUS[etype],
                "title": f"{d.name} {v['field']}={value} -> {etype}{note} (auto from diagnostics)",
            }
        )
        edges.append({"from": d.name, "to": vid, "type": "produces"})
        edges.append({"from": vid, "to": str(h["l1"]), "type": etype})
    return nodes, edges


def sweep_nodes_edges(repo_root: str | Path) -> tuple[list[dict], list[dict]]:
    """Derive L2-per-cell Hypothesis nodes + typed verdict edges from results/sweeps/*.json.

    Each sweep cell becomes one L2 (`proposed`) instantiating the sweep's L1; the cell's family-FDR
    verdict (validates/refutes/inconclusive) becomes a Verdict node + typed edge. ALL cells are
    written -- refuted ones too (the graph must keep the refutations; that is the honesty that makes
    Station 3 possible). Mirrors hypothesis_*_nodes_edges so the edge-GC handles idempotency.
    """
    root = Path(repo_root)
    sweeps = root / "results" / "sweeps"
    nodes: list[dict] = []
    edges: list[dict] = []
    if not sweeps.is_dir():
        return nodes, edges
    for f in sorted(sweeps.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        fam, l1 = data.get("family"), data.get("l1")
        cells = data.get("cells")
        if not fam or not l1 or not isinstance(cells, dict):
            continue
        for cid, c in cells.items():
            etype = c.get("verdict")
            if etype not in _VERDICT_STATUS:
                continue
            l2 = f"h2-sweep-{fam}-{cid}"
            vid = f"v-sweep-{fam}-{cid}"
            nodes.append(
                {
                    "id": l2,
                    "type": "Hypothesis",
                    "level": "L2",
                    "status": "proposed",
                    "title": f"{fam} cell {cid}: {data.get('prediction', '')}"[:90],
                }
            )
            nodes.append(
                {
                    "id": vid,
                    "type": "Verdict",
                    "status": _VERDICT_STATUS[etype],
                    "title": f"{fam}/{cid} family-FDR -> {etype} ({c.get('n_survivors', 0)} surv)"[
                        :90
                    ],
                }
            )
            edges.append({"from": l2, "to": str(l1), "type": "instantiates"})
            edges.append({"from": vid, "to": str(l1), "type": etype})
    return nodes, edges


_EXPLORE_VERDICT = {"confirmed": "validates", "refuted": "refutes", "inconclusive": "inconclusive"}


def _safe_id(s: str) -> str:
    """YAML-flow-safe id fragment: collapse any char outside [0-9A-Za-z=_.-] to '-'.

    Discovery cell_ids embed list reprs (e.g. ``classifiers=['vix']__n_regimes=2``); the ``[`` / ``'``
    would break the unquoted flow-style node id the sync renderer emits. The full cell_id is kept
    verbatim in the (quoted) node title; only the id is sanitised."""
    return re.sub(r"[^0-9A-Za-z=_.-]+", "-", str(s))


def explore_nodes_edges(repo_root: str | Path) -> tuple[list[dict], list[dict]]:
    """Derive L2-per-cell Hypothesis nodes + typed verdict edges from results/explore/*/.

    Twin of sweep_nodes_edges for the Station 3 discovery loop. Each campaign cell becomes one L2
    (`proposed`) instantiating the campaign's L1; the cell's confirmed/refuted/inconclusive verdict
    becomes a Verdict node + typed edge (confirmed->validates, refuted->refutes). ALL cells are
    written -- refuted ones too (the graph must keep the refutations; the honesty that makes Station 3
    legitimate). Reads campaign.json (family + held_out for titles) + verdict_report.json (verdicts),
    paired by cell_id; a run missing either file is skipped.
    """
    root = Path(repo_root)
    base = root / "results" / "explore"
    nodes: list[dict] = []
    edges: list[dict] = []
    if not base.is_dir():
        return nodes, edges
    for d in sorted(p for p in base.glob("*") if p.is_dir()):
        cj, rj = d / "campaign.json", d / "verdict_report.json"
        if not (cj.exists() and rj.exists()):
            continue
        try:
            camp = json.loads(cj.read_text(encoding="utf-8"))
            rep = json.loads(rj.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        name = camp.get("name", d.name)
        held_out = camp.get("held_out", "")
        cands = camp.get("candidates") or []
        family = (cands[0].get("family") if cands else None) or "explore"
        cells = rep.get("cells")
        if not isinstance(cells, list):
            continue
        for c in cells:
            etype = _EXPLORE_VERDICT.get(c.get("verdict"))
            l1 = c.get("parent_l1")
            cid = c.get("cell_id")
            if etype not in _VERDICT_STATUS or not l1 or not cid:
                continue
            l2 = f"h2-explore-{_safe_id(name)}-{_safe_id(cid)}"
            vid = f"v-explore-{_safe_id(name)}-{_safe_id(cid)}"
            nodes.append(
                {
                    "id": l2,
                    "type": "Hypothesis",
                    "level": "L2",
                    "status": "proposed",
                    "title": f"{family} cell {cid} (campaign {name})"[:90],
                }
            )
            nodes.append(
                {
                    "id": vid,
                    "type": "Verdict",
                    "status": _VERDICT_STATUS[etype],
                    "title": f"{name}/{cid} discovery -> {etype} (held_out {held_out})"[:90],
                }
            )
            edges.append({"from": l2, "to": str(l1), "type": "instantiates"})
            edges.append({"from": vid, "to": str(l1), "type": etype})
    return nodes, edges


def lineage_edges(graph: nx.DiGraph, repo_root: Path) -> list[dict]:
    """Derive `refines` edges (Experiment -> parent Experiment) from each config.yaml `lineage:`."""
    nodes = set(graph.nodes)
    exp_root = repo_root / "experiments"
    out: list[dict] = []
    if not exp_root.exists():
        return out
    for d in sorted(p for p in exp_root.glob("exp*") if p.is_dir()):
        cfg = d / "config.yaml"
        if not cfg.exists():
            continue
        try:
            data = yamlio.load(cfg) or {}
        except yaml.YAMLError:
            continue
        # lineage lives under `experiment:` in these configs, but tolerate a top-level key too
        raw = data.get("lineage")
        if not raw and isinstance(data.get("experiment"), dict):
            raw = data["experiment"].get("lineage")
        if not isinstance(raw, str) or not raw.strip():
            continue
        target = Path(raw.strip()).name  # "experiments/exp028_growth_tilt" -> "exp028_growth_tilt"
        src = d.name
        if target == src or src not in nodes or target not in nodes:
            continue
        if graph.has_edge(src, target):
            continue
        out.append({"from": src, "to": target, "type": "refines"})
    return out


def render_edges(edges: list[dict]) -> str:
    return "\n".join(f"- {{from: {e['from']}, to: {e['to']}, type: {e['type']}}}" for e in edges)


def _fmt(node: dict) -> str:
    parts = [f"id: {node['id']}", f"type: {node['type']}"]
    parts.append('title: "{}"'.format(str(node["title"]).replace('"', "'")))
    parts.append(f"status: {node['status']}")
    if node.get("level"):
        parts.append(f"level: {node['level']}")
    if node.get("anchor"):
        parts.append(f'anchor: "{node["anchor"]}"')
    # dedup ids that collide after slugging by appending a numeric suffix is the caller's job
    return "- {" + ", ".join(parts) + "}"


def render_stubs(nodes: list[dict]) -> str:
    """Render a list of node dicts as flow-style YAML lines, deduping colliding ids."""
    seen: dict[str, int] = {}
    lines: list[str] = []
    for n in nodes:
        nid = n["id"]
        if nid in seen:
            seen[nid] += 1
            n = {**n, "id": f"{nid}-{seen[nid]}"}
        else:
            seen[nid] = 0
        lines.append(_fmt(n))
    return "\n".join(lines)


_GENERATED_PREFIX = "_generated_"


def _hand_graph(store: Path) -> nx.DiGraph:
    """Node-only view of the store EXCLUDING auto-generated files (no edges, no validation).

    Deficit must be measured against the *hand-curated* store only; counting the previous
    generation would make `--write` regenerate a shrinking set and lose prior coverage.
    """
    g = nx.DiGraph()
    for nf in sorted((store / "nodes").glob("*.yaml")):
        if nf.name.startswith(_GENERATED_PREFIX):
            continue
        data = yamlio.load(nf) or []
        for n in data:
            if isinstance(n, dict) and n.get("id"):
                g.add_node(
                    n["id"], type=n.get("type"), status=n.get("status"), anchor=n.get("anchor")
                )
    return g


def _all_nodes_graph(store: Path) -> nx.DiGraph:
    """All node ids (hand + generated stubs), no edges, no validation — for endpoint resolution.

    Unlike ``load_store`` this never raises on a dangling edge (the very state the edge-GC fixes),
    so ``derive`` can regenerate even when ``edges.yaml`` currently holds stale auto-derived edges.
    """
    g = nx.DiGraph()
    for nf in sorted((store / "nodes").glob("*.yaml")):
        data = yamlio.load(nf) or []
        if not isinstance(data, list):
            continue
        for n in data:
            if isinstance(n, dict) and n.get("id"):
                g.add_node(n["id"], type=n.get("type"), status=n.get("status"))
    return g


_EDGES_MARKER = "# --- auto-derived"


def _hand_edges_text(store: Path) -> str:
    """edges.yaml content up to (excluding) the first auto-derived block = the hand-curated edges."""
    f = store / "edges.yaml"
    if not f.exists():
        return ""
    text = f.read_text(encoding="utf-8")
    idx = text.find(_EDGES_MARKER)
    return text[:idx] if idx != -1 else text


def _hand_edges_set(store: Path) -> set[tuple]:
    """(from, to, type) of the hand-curated edges only (excludes any auto-derived block)."""
    data = yamlio.loads(_hand_edges_text(store)) or []
    if not isinstance(data, list):
        return set()
    return {(e.get("from"), e.get("to"), e.get("type")) for e in data if isinstance(e, dict)}


def regenerate_edges_file_text(store: str | Path, edge_txt: str) -> str:
    """Full edges.yaml = hand-curated prefix + a freshly regenerated auto-derived block.

    Replaces any prior auto-derived block, so stale/dangling auto-edges are GC'd instead of
    accumulating (the old behaviour appended a new block every sync and never removed dead edges).
    """
    hand = _hand_edges_text(Path(store)).rstrip()
    parts = [hand] if hand else []
    if edge_txt:
        parts.append("# --- auto-derived (research_graph sync) ---\n" + edge_txt)
    return ("\n\n".join(parts) + "\n") if parts else ""


def _prev_generated(store: Path) -> tuple[list[dict], list[dict]]:
    """Hypothesis stubs + auto-derived edges written by the previous sync (empty if none)."""
    nodes: list[dict] = []
    f = store / "nodes" / f"{_GENERATED_PREFIX}hypotheses.yaml"
    if f.exists():
        data = yamlio.load(f) or []
        if isinstance(data, list):
            nodes = [n for n in data if isinstance(n, dict) and n.get("id")]
    edges: list[dict] = []
    ef = store / "edges.yaml"
    if ef.exists():
        text = ef.read_text(encoding="utf-8")
        idx = text.find(_EDGES_MARKER)
        if idx != -1:
            data = yamlio.loads(text[idx:]) or []
            if isinstance(data, list):
                edges = [
                    {"from": e["from"], "to": e["to"], "type": e["type"]}
                    for e in data
                    if isinstance(e, dict) and {"from", "to", "type"} <= e.keys()
                ]
    return nodes, edges


def _local_only_source_absent(node_id: str, root: Path) -> bool:
    """True if `node_id` was derived from a local-only artifact that is absent on this checkout.

    Verdicts, sweep and explore cells come from run outputs (experiments/*/results/ is gitignored,
    results/sweeps|explore are not committed), so a fresh clone or another machine lacks them.
    Absence of the artifact is NOT evidence the stub is stale: only a still-declared verdict with
    no diagnostics, or a sweep family / explore campaign with no run on disk, qualifies. When the
    artifact is present the fresh derivation is authoritative and the normal GC applies.
    """
    m = _EXP_VERDICT_RE.match(node_id)
    if m:
        d = root / "experiments" / m.group(1)
        cfg = d / "config.yaml"
        if not cfg.exists() or (d / "results" / "diagnostics.json").exists():
            return False
        try:
            data = yamlio.load(cfg) or {}
        except yaml.YAMLError:
            return False
        h = data.get("hypothesis")
        v = h.get("verdict") if isinstance(h, dict) and h.get("l1") else None
        return isinstance(v, dict) and "field" in v
    for prefix in ("h2-sweep-", "v-sweep-"):
        if node_id.startswith(prefix):
            fams = set()
            for f in (root / "results" / "sweeps").glob("*.json"):
                try:
                    fams.add(str(json.loads(f.read_text(encoding="utf-8")).get("family")))
                except (OSError, ValueError, AttributeError):
                    continue
            return not any(node_id.startswith(f"{prefix}{fam}-") for fam in fams)
    for prefix in ("h2-explore-", "v-explore-"):
        if node_id.startswith(prefix):
            names = set()
            for d in (root / "results" / "explore").glob("*"):
                cj = d / "campaign.json"
                if not (cj.exists() and (d / "verdict_report.json").exists()):
                    continue
                try:
                    names.add(
                        _safe_id(json.loads(cj.read_text(encoding="utf-8")).get("name", d.name))
                    )
                except (OSError, ValueError, AttributeError):
                    continue
            return not any(node_id.startswith(f"{prefix}{n}-") for n in names)
    return False


def _carry_forward(
    store: Path, root: Path, derived_ids: set[str]
) -> tuple[dict[str, list[dict]], list[dict]]:
    """Previous stubs (by kind: verdict/sweep/explore) + their edges whose local-only source is absent."""
    prev_nodes, prev_edges = _prev_generated(store)
    kept: dict[str, list[dict]] = {"verdict": [], "sweep": [], "explore": []}
    for n in prev_nodes:
        nid = str(n["id"])
        if nid in derived_ids or not _local_only_source_absent(nid, root):
            continue
        kind = (
            "verdict" if _EXP_VERDICT_RE.match(nid) else "sweep" if "-sweep-" in nid else "explore"
        )
        kept[kind].append(n)
    ids = {str(n["id"]) for ns in kept.values() for n in ns}
    edges = [e for e in prev_edges if str(e["from"]) in ids or str(e["to"]) in ids]
    return kept, edges


def derive(
    store: str | Path, repo_root: str | Path, decisions: Iterable[str | Path] | None = None
) -> dict[str, list[dict]]:
    """Return the Experiment + decision + hypothesis stubs and the regenerated auto-derived edges.

    Stubs are computed against the hand-curated store only (so `--write` is idempotent). The
    auto-derived edges are produced in full and deduped only against the HAND edges, so stale
    auto-edges are never resurrected — the CLI rewrites the auto-derived block from this set.
    ``decisions``: the decision logs the store covers (None: the defaults of :func:`decision_stubs`).
    """
    store = Path(store)
    root = Path(repo_root)
    hand = _hand_graph(store)
    exp = experiment_stubs(hand, root)
    dec = decision_stubs(hand, root, decisions)
    hyp_nodes, hyp_edges = hypothesis_nodes_edges(root)
    hyp_l1 = hypothesis_l1_stubs(hand, root)
    v_nodes, v_edges = hypothesis_verdict_nodes_edges(root)
    sw_nodes, sw_edges = sweep_nodes_edges(root)
    ex_nodes, ex_edges = explore_nodes_edges(root)
    # verdict/sweep/explore stubs derive from run outputs that are not in git; when the output is
    # absent here, keep the previous generation instead of GC-ing it (absent != stale).
    derived_ids = {n["id"] for n in hyp_l1 + hyp_nodes + v_nodes + sw_nodes + ex_nodes}
    kept, kept_edges = _carry_forward(store, root, derived_ids)
    hyps = (
        hyp_l1
        + hyp_nodes
        + v_nodes
        + kept["verdict"]
        + sw_nodes
        + kept["sweep"]
        + ex_nodes
        + kept["explore"]
    )
    # endpoint resolution against ALL known node ids (hand + generated + about-to-write stubs);
    # auto-derived edges are produced in full and deduped only against the HAND edges, so a stale
    # auto-edge (whose node vanished) is simply not re-derived -> dropped by the CLI rewrite.
    nodes_only = _all_nodes_graph(store)
    for n in exp + hyps:
        if n["id"] not in nodes_only:
            nodes_only.add_node(n["id"], type=n.get("type"), status=n.get("status"))
    # a carried edge survives only if both endpoints still exist after this regeneration
    gone = {str(n["id"]) for n in _prev_generated(store)[0]} - {str(n["id"]) for n in hyps}
    kept_edges = [
        e
        for e in kept_edges
        if all(x in nodes_only and str(x) not in gone for x in (e["from"], e["to"]))
    ]
    hand_e = _hand_edges_set(store)
    candidate = lineage_edges(nodes_only, root) + hyp_edges + v_edges + sw_edges + ex_edges
    fresh = {(e["from"], e["to"], e["type"]) for e in candidate}
    candidate += [e for e in kept_edges if (e["from"], e["to"], e["type"]) not in fresh]
    edges = [e for e in candidate if (e["from"], e["to"], e["type"]) not in hand_e]
    return {
        "experiments": exp,
        "decisions": dec,
        "hypotheses": hyps,
        "edges": edges,
    }
