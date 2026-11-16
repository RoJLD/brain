"""The research pack's gates (wi-brain-research-pack, spec-brain-typology-packs E5, TYPO-1): what a research project
adds to the graph's generic checks, moved out of :mod:`research_graph.validate`'s core. The experiments' folders
(``experiments/exp*``) and their Experiment nodes, the kanban, the pre-registration of a staged
experiment (its spec:, or a legacy SDR), the hypothesis graph's wiring (an Experiment tests a Hypothesis, a validated Hypothesis has its
Verdict) and its advisories, and the Edge gates (drift, coverage, a predictive edge on contemporaneous data).

Their behaviour is unchanged and is a contract a research project's own checks rely on (spec-brain-typology-packs
§4, door 10): ``research_graph check`` runs the coverage, wiring and advisory kinds as before, a project's own
pre-commit the notebook kind, each silent on a store without their nodes or folders, and
:mod:`research_graph.validate` keeps every name importable (a monkeypatch reaches the moved callers through this
module's names, no longer validate's). A new research rule lands here, never in the core.
:data:`GATES` names them, by kind, for the engine's research typology pack (brain typologies packs).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

import networkx as nx
import yaml

from . import yamlio


def missing_experiment_nodes(graph: nx.DiGraph, repo_root: Path) -> list[str]:
    exp_root = repo_root / "experiments"
    if not exp_root.exists():
        return []
    dirs = sorted(p.name for p in exp_root.glob("exp*") if p.is_dir())
    have = {n for n, a in graph.nodes(data=True) if a.get("type") == "Experiment"}
    return [f"experiments/{d}: no Experiment node" for d in dirs if d not in have]


def experiments_missing_from_kanban(repo_root: str | Path) -> list[str]:
    """Every experiments/expNNN_*/ must be mentioned in notes/kanban_experiments.md (by id or number)."""
    repo = Path(repo_root)
    kanban = repo / "notes" / "kanban_experiments.md"
    exp_root = repo / "experiments"
    if not kanban.exists() or not exp_root.exists():
        return []
    text = kanban.read_text(encoding="utf-8")
    problems: list[str] = []
    for d in sorted(p.name for p in exp_root.glob("exp*") if p.is_dir()):
        if d not in text and d.split("_")[0] not in text:
            problems.append(f"experiments/{d}: not mentioned in notes/kanban_experiments.md")
    return problems





_EXP_PATH_RE = re.compile(r"experiments/(exp\d+_[a-z0-9_]+)/")


def staged_experiment_ids(staged_files: list[str]) -> set[str]:
    """Experiment dir ids (expNNN_*) extraits des chemins stagés (slash ou backslash)."""
    out: set[str] = set()
    for f in staged_files:
        m = _EXP_PATH_RE.search(f.replace("\\", "/"))
        if m:
            out.add(m.group(1))
    return out


def _experiment_spec(repo_root: str | Path | None, exp_id: str) -> str | None:
    """The ``spec:`` pointer in experiments/<exp_id>/config.yaml (repo-relative), or None.

    The spec IS the pre-registration under the convention that replaced SDRs: the workspace
    CLAUDE.md has mandated a spec before any plan/code since 2026-05-26, and
    notes/scientific_decisions.md took its last entry 2026-06-28. Specs are named by slug, not by
    expNNN, so without this key no gate can mechanically find an experiment's pre-registration.
    """
    if repo_root is None:
        return None
    cfg = Path(repo_root) / "experiments" / exp_id / "config.yaml"
    if not cfg.exists():
        return None
    try:
        data = yamlio.load(cfg) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    spec = data.get("spec")
    return spec if isinstance(spec, str) and spec.strip() else None


def _preregistration_gap(repo: Path, exp_id: str, sdr_text: str, *, qualifier: str) -> str | None:
    """None if <exp_id> is pre-registered, else the problem string.

    ERA-AWARE: an experiment is pre-registered by a LEGACY SDR (notes/scientific_decisions.md —
    convention closed 2026-06-28, its records stay valid for their era) OR by a ``spec:`` pointing
    at an existing design doc (current convention). It is an OR, never a substitution: replacing
    SDR *by* spec would flag every legacy experiment that holds a legitimate SDR — creating debt
    while claiming to resolve it. A NEW experiment cannot obtain an SDR (the convention is closed),
    so this rule forces ``spec:`` going forward with no special case.
    """
    num = exp_id.split("_")[0]
    if exp_id in sdr_text or num in sdr_text:
        return None
    spec = _experiment_spec(repo, exp_id)
    if spec is None:
        return (
            f"experiments/{exp_id}: {qualifier}no pre-registration (no SDR in "
            f"notes/scientific_decisions.md, no spec: in config.yaml)"
        )
    if not (repo / spec).exists():
        return f"experiments/{exp_id}: {qualifier}spec: points at a missing file ({spec})"
    return None


def _experiment_gaps(repo_root: str | Path, exp_ids: Iterable[str], *, staged: bool) -> list[str]:
    """Shared rigor-debt rule for BOTH gates.

    ``staged_experiment_gaps`` (pre-commit, BLOCKING) and ``all_experiment_gaps`` (repo-wide,
    advisory) were near-duplicates and drifted: the advisory kept demanding a *Scientific* Decision
    Record from trading/methodological experiments that the blocking gate had already exempted.
    They share one implementation so that cannot recur. No-op if notes/ is absent. Substring match
    (full id OR bare expNNN number).
    """
    repo = Path(repo_root)
    notes = repo / "notes"
    if not notes.is_dir():
        return []

    def _text(name: str) -> str:
        f = notes / name
        return f.read_text(encoding="utf-8") if f.exists() else ""

    kanban = _text("kanban_experiments.md")
    sdr = _text("scientific_decisions.md")
    cahier = _text("cahier_laboratoire.md")
    qualifier = "staged but " if staged else ""
    problems: list[str] = []
    for d in sorted(exp_ids):
        num = d.split("_")[0]
        if d not in kanban and num not in kanban:
            problems.append(f"experiments/{d}: {qualifier}absent from notes/kanban_experiments.md")
        prereg = _preregistration_gap(repo, d, sdr, qualifier=qualifier)
        if prereg is not None:
            problems.append(prereg)
        ran = (repo / "experiments" / d / "results" / "manifest.json").exists()
        # Trading experiments are exempt from the cahier: the Edge's `backtest:` prose IS their lab
        # notebook, and it is richer than the cahier — the same reasoning the BLOCKING gate already
        # applies when it exempts them from the Hypothesis requirement.
        if ran and not _experiment_targets_edges(repo, d) and d not in cahier and num not in cahier:
            problems.append(
                f"experiments/{d}: ran (manifest.json) but absent from notes/cahier_laboratoire.md"
            )
    return problems


def staged_experiment_gaps(repo_root: str | Path, staged_ids: set[str]) -> list[str]:
    """Pour chaque exp stagée : BLOQUE si absente de kanban / non pré-enregistrée, ou (a tourné)
    absente du cahier. Règle partagée avec l'audit repo-wide — cf. :func:`_experiment_gaps`.
    """
    return _experiment_gaps(repo_root, staged_ids, staged=True)


def all_experiment_gaps(repo_root: str | Path) -> list[str]:
    """Repo-wide completeness audit (NOT staged-scoped): every experiments/expNNN_*/ must be in the
    kanban, be pre-registered (legacy SDR OR ``spec:``), and — unless it is a trading experiment —
    be in the cahier if it ran.

    The pre-commit gate (:func:`staged_experiment_gaps`) only sees ``git diff --cached``, so
    already-committed *legacy* debt never trips it. This audit scans the whole ``experiments/``
    tree to surface that debt. Advisory by construction — callers decide whether to block. No-op if
    notes/ or experiments/ is absent.
    """
    repo = Path(repo_root)
    exp_root = repo / "experiments"
    if not exp_root.is_dir():
        return []
    return _experiment_gaps(
        repo_root, (p.name for p in exp_root.glob("exp*") if p.is_dir()), staged=False
    )


def hypothesis_validated_without_support(graph: nx.DiGraph) -> list[str]:
    """A Hypothesis status=validated must have >=1 'validates' edge from a validated
    Verdict AND no incoming 'refutes' edge. (The structural guard for the H1 landmine.)"""
    problems: list[str] = []
    for nid, a in graph.nodes(data=True):
        if a.get("type") != "Hypothesis" or a.get("status") != "validated":
            continue
        ins = list(graph.in_edges(nid, data=True))
        refutes = [s for s, _, e in ins if e.get("type") == "refutes"]
        supports = [
            s
            for s, _, e in ins
            if e.get("type") == "validates"
            and graph.nodes[s].get("type") == "Verdict"
            and graph.nodes[s].get("status") == "validated"
        ]
        if refutes:
            problems.append(f"{nid}: status validated but has {len(refutes)} refutes verdict(s)")
        elif not supports:
            problems.append(f"{nid}: status validated but no validated 'validates' verdict")
    return problems


def _experiment_is_methodological(repo_root: str | Path | None, exp_id: str) -> bool:
    """True if experiments/<exp_id>/config.yaml declares ``methodological: true`` — an explicit
    statement that the experiment validates machinery/robustness and tests no mechanism. The
    blocking wiring gate honours this so the absence of a hypothesis reads as intentional, not an
    oversight (a diagnostic/foundational run is not the ledger/arc divergence the gate hunts)."""
    if repo_root is None:
        return False
    cfg = Path(repo_root) / "experiments" / exp_id / "config.yaml"
    if not cfg.exists():
        return False
    try:
        data = yamlio.load(cfg) or {}
    except yaml.YAMLError:
        return False
    return isinstance(data, dict) and data.get("methodological") is True


def _experiment_targets_edges(repo_root: str | Path | None, exp_id: str) -> bool:
    """True if experiments/<exp_id>/config.yaml declares a non-empty ``edges:`` list — a TRADING
    experiment (a backtest of trading Edges). Its claim is an Edge's viability, recorded via the
    Edge's ``backtest`` note + the scorecard, not a research Hypothesis/mechanism. The hypothesis-
    wiring gate honours this so a trading backtest's absence of a tested Hypothesis reads as
    intentional (it lives on the Edge side of the graph, not the mechanism side)."""
    if repo_root is None:
        return False
    cfg = Path(repo_root) / "experiments" / exp_id / "config.yaml"
    if not cfg.exists():
        return False
    try:
        data = yamlio.load(cfg) or {}
    except yaml.YAMLError:
        return False
    edges = data.get("edges") if isinstance(data, dict) else None
    return isinstance(edges, list) and len(edges) > 0


def experiment_tests_no_hypothesis(
    graph: nx.DiGraph, repo_root: str | Path | None = None
) -> list[str]:
    """Every Experiment must ``tests`` >=1 Hypothesis (detects the ledger/arc divergence), UNLESS it
    explicitly declares ``methodological: true`` (a diagnostic/robustness/foundational run that tests
    no mechanism) OR a non-empty ``edges:`` list (a TRADING experiment that validates an Edge, not a
    Hypothesis) in its config. Pass ``repo_root`` to enable the exemption lookup; omit it for
    graph-only use (then every untested Experiment is flagged)."""
    problems: list[str] = []
    for nid, a in graph.nodes(data=True):
        if a.get("type") != "Experiment":
            continue
        tested = [
            d
            for _, d, e in graph.out_edges(nid, data=True)
            if e.get("type") == "tests" and graph.nodes[d].get("type") == "Hypothesis"
        ]
        if tested:
            continue
        if _experiment_is_methodological(repo_root, nid):
            continue
        if _experiment_targets_edges(repo_root, nid):
            continue
        problems.append(f"{nid}: tests no Hypothesis")
    return problems


def l2_without_parent(graph: nx.DiGraph) -> list[str]:
    """Every L2 Hypothesis must have an `instantiates` edge to a parent (L1)."""
    problems: list[str] = []
    for nid, a in graph.nodes(data=True):
        if a.get("type") != "Hypothesis" or a.get("level") != "L2":
            continue
        parents = [
            d for _, d, e in graph.out_edges(nid, data=True) if e.get("type") == "instantiates"
        ]
        if not parents:
            problems.append(f"{nid}: L2 without instantiates -> L1 parent")
    return problems


def hypothesis_stub_needs_prose(graph: nx.DiGraph) -> list[str]:
    """L0/L1 Hypothesis nodes still in `planned` status are auto-stubs awaiting curated prose."""
    problems: list[str] = []
    for nid, a in graph.nodes(data=True):
        if (
            a.get("type") == "Hypothesis"
            and a.get("level") in {"L0", "L1"}
            and a.get("status") == "planned"
        ):
            problems.append(f"{nid}: L1/L0 stub needs curated prose (status planned)")
    return problems


def check_wiring(graph: nx.DiGraph, repo_root: str | Path | None = None) -> list[str]:
    """BLOCKING hypothesis-graph wiring invariants — ``graph-check`` fails (exit 1) on these.

    (1) ``experiment_tests_no_hypothesis`` — every Experiment must ``tests`` a Hypothesis or declare
    itself ``methodological``; (2) ``hypothesis_validated_without_support`` — the anti-landmine guard:
    a ``validated`` Hypothesis must have a ``validates`` Verdict and no ``refutes`` (prevents asserting
    a validated claim the data does not back — exactly how the H1 artefact slipped in). Kept separate
    from ``check_coverage`` (node/decision coverage) and ``check_consistency`` (softer advisories).
    """
    return (
        experiment_tests_no_hypothesis(graph, repo_root)
        + hypothesis_validated_without_support(graph)
        + edge_drift(graph)
        + edge_predictive_on_contemporaneous(graph)
    )


def check_consistency(graph: nx.DiGraph) -> list[str]:
    """Hypothesis-graph consistency advisories (non-blocking; surfaced but do not fail the check).

    The blocking gates (Experiment-tests-a-Hypothesis, validated-claim-has-support) live in
    ``check_wiring``; these two stay advisory — an orphan L2 and an L1/L0 stub awaiting curated prose
    are in-progress curation, not hard structural breaks."""
    return l2_without_parent(graph) + hypothesis_stub_needs_prose(graph) + edge_coverage(graph)


# --- Edge Graph gates (2026-06-15) -------------------------------------------

_EDGE_ASSERTED = {"live", "active"}  # an edge whose claim is in force (vs `proposed` candidate)


def _edge_nodes(graph: nx.DiGraph):
    return [(nid, a) for nid, a in graph.nodes(data=True) if a.get("type") == "Edge"]


def _exploited(graph: nx.DiGraph, edge_id: str):
    """Mechanism ids an Edge `exploits` (out-edges of type exploits)."""
    return [d for _, d, e in graph.out_edges(edge_id, data=True) if e.get("type") == "exploits"]


def edge_coverage(graph: nx.DiGraph) -> list[str]:
    """Advisory: a supported L1 mechanism (status active/validated) with no incoming `exploits`
    edge and no ``props.no_edge`` flag has no mapped trading implication — surface it."""
    problems: list[str] = []
    for nid, a in graph.nodes(data=True):
        if a.get("type") != "Hypothesis" or a.get("level") != "L1":
            continue
        if a.get("status") not in {"active", "validated"}:
            continue
        if (a.get("props") or {}).get("no_edge"):
            continue
        exploited_by = [s for s, _, e in graph.in_edges(nid, data=True) if e.get("type") == "exploits"]
        if not exploited_by:
            problems.append(f"{nid}: supported mechanism with no trading Edge (exploits) mapped")
    return problems


def edge_drift(graph: nx.DiGraph) -> list[str]:
    """BLOCKING: an asserted (live/active) NON-constraint Edge whose exploited mechanism is
    rejected/inconclusive must be reconciled (retired) — keeps strategies off dead findings.
    Constraint edges are exempt (they are SUPPOSED to ground in a rejected mechanism)."""
    problems: list[str] = []
    for nid, a in _edge_nodes(graph):
        if a.get("status") not in _EDGE_ASSERTED:
            continue
        if (a.get("props") or {}).get("edge_type") == "constraint":
            continue
        for mech in _exploited(graph, nid):
            ms = graph.nodes[mech].get("status")
            if ms in {"rejected", "inconclusive"}:
                problems.append(
                    f"{nid}: {a.get('status')} edge exploits {mech} which is {ms} — reconcile (retire the edge?)"
                )
    return problems


def edge_predictive_on_contemporaneous(graph: nx.DiGraph) -> list[str]:
    """BLOCKING honesty guard: an asserted (live/active) Edge with ``props.signal_nature ==
    predictive`` must exploit a SUPPORTED (active/validated) mechanism whose ``props.nature ==
    predictive``. Grounding a predictive edge on a contemporaneous/structural (or rejected)
    finding is forbidden — the trading analogue of the H1 anti-landmine. ``proposed`` edges are
    candidates and exempt."""
    problems: list[str] = []
    for nid, a in _edge_nodes(graph):
        if a.get("status") not in _EDGE_ASSERTED:
            continue
        if (a.get("props") or {}).get("signal_nature") != "predictive":
            continue
        grounded = False
        for mech in _exploited(graph, nid):
            m = graph.nodes[mech]
            if (m.get("props") or {}).get("nature") == "predictive" and m.get("status") in {
                "active",
                "validated",
            }:
                grounded = True
        if not grounded:
            problems.append(
                f"{nid}: predictive edge not grounded in a supported predictive mechanism "
                f"(the research established no lead) — keep it proposed or ground it in a dedicated experiment"
            )
    return problems


# The gates by kind: research_graph check runs coverage, wiring and advisories; a research project's own
# pre-commit runs the notebook kind.
GATES = {
    "coverage": ("missing_experiment_nodes",),
    "notebook": ("experiments_missing_from_kanban", "staged_experiment_gaps", "all_experiment_gaps"),
    "wiring": ("experiment_tests_no_hypothesis", "hypothesis_validated_without_support", "edge_drift",
               "edge_predictive_on_contemporaneous"),
    "advisories": ("l2_without_parent", "hypothesis_stub_needs_prose", "edge_coverage"),
}
