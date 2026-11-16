from __future__ import annotations

import posixpath
import re
from collections.abc import Iterable
from pathlib import Path

import networkx as nx
import yaml  # noqa: F401 - kept importable as validate.yaml, as before the research pack's move

from . import yamlio  # noqa: F401 - kept importable as validate.yamlio

_DECISION_FILES = ("scientific_decisions.md", "decisions.md")
# the decision logs a store covers when none is given (--decisions): an SDR log, then an ADR log
DEFAULT_DECISIONS = tuple(f"notes/{f}" for f in _DECISION_FILES)
_HEADING_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})\b")
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _posix(path: str | Path) -> str:
    return posixpath.normpath(str(path).replace("\\", "/"))


def _key(path: str | Path) -> str:
    """A log's path as coverage compares it: posix, normalised, case folded (a case-insensitive file system resolves
    ``Notes/decisions.md`` to the log, so it counts for it)."""
    return _posix(path).casefold()


def decision_logs(logs: Iterable[str | Path] | None = None) -> list[tuple[str, str]]:
    """(path relative to the repo root, node type) of each decision log a store covers: ``logs`` as given, else
    :data:`DEFAULT_DECISIONS` (``[]``: none). A file named scientific_decisions.md holds SDRs, any other ADRs."""
    paths = DEFAULT_DECISIONS if logs is None else logs
    return [(_posix(p), "SDR" if Path(p).name == "scientific_decisions.md" else "ADR") for p in paths]


def _node_decision_date_counts(graph: nx.DiGraph) -> dict[tuple[str, str], int]:
    """SDR and ADR nodes per (the log their anchor names, relative to the repo root; the date of their heading): a
    node covers the log at its anchor's path, not another log of the same file name."""
    counts: dict[tuple[str, str], int] = {}
    for _, a in graph.nodes(data=True):
        if a.get("type") not in {"SDR", "ADR"}:
            continue
        anchor = a.get("anchor") or ""
        if "#" not in anchor:
            continue
        path, frag = anchor.split("#", 1)
        m = _DATE_RE.match(frag)
        if m:
            key = (_key(path), m.group(1))
            counts[key] = counts.get(key, 0) + 1
    return counts


def _heading_dates(path: Path) -> list[str]:
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _HEADING_RE.match(line)
        if m:
            out.append(m.group(1))
    return out


def missing_decision_nodes(
    graph: nx.DiGraph, repo_root: Path, logs: Iterable[str | Path] | None = None
) -> list[str]:
    """A dated heading of a decision log the store covers (:func:`decision_logs`) without its SDR/ADR node."""
    node_counts = _node_decision_date_counts(graph)
    problems: list[str] = []
    for rel, _ in decision_logs(logs):
        f = repo_root / rel
        if not f.exists():
            continue
        head_counts: dict[str, int] = {}
        for date in _heading_dates(f):
            head_counts[date] = head_counts.get(date, 0) + 1
        for date, hc in sorted(head_counts.items()):
            nc = node_counts.get((_key(rel), date), 0)
            if nc < hc:
                problems.append(f"{rel}: {date} has {hc} heading(s) but {nc} SDR/ADR node(s)")
    return problems


def _checkout(repos: dict[str, Path] | None, repo: str) -> Path | None:
    """The checkout given for ``repo`` (case-insensitive), None when none is given or it is not on this machine."""
    root = {k.lower(): Path(v) for k, v in (repos or {}).items()}.get(repo.lower())
    return root if root is not None and root.is_dir() else None


def anchor_errors(graph: nx.DiGraph, repo_root: Path, repos: dict[str, Path] | None = None) -> list[str]:
    """Anchors that do not resolve. An anchor is ``<path>#<fragment>``, the path relative to ``repo_root``; a node
    whose ``repo`` names another repo (a Doc, Test or Workflow node derived from that repo's tree) has its path
    relative to that repo's checkout, given in ``repos`` (name -> checkout), and names a Repo node as a CodeRef does.
    Such an anchor is not checked when its repo has no checkout here (:func:`unchecked_anchors`)."""
    problems: list[str] = []
    for nid, a in graph.nodes(data=True):
        anchor = a.get("anchor")
        if not anchor:
            continue
        if "#" not in anchor:
            problems.append(f"{nid}: malformed anchor {anchor!r}")
            continue
        root, repo = repo_root, str(a.get("repo") or "")
        if repo:
            rnode = f"repo-{repo.lower()}"
            if rnode not in graph or graph.nodes[rnode].get("type") != "Repo":
                problems.append(f"{nid}: anchor of repo {repo!r}: no Repo node {rnode!r}")
                continue
            root = _checkout(repos, repo)
            if root is None:
                continue
        path, frag = anchor.split("#", 1)
        f = root / path
        if not f.exists():
            problems.append(f"{nid}: anchor file missing: {path}" + (f" (repo {repo})" if repo else ""))
            continue
        m = _DATE_RE.match(frag)
        if m and m.group(1) not in _heading_dates(f):
            problems.append(f"{nid}: no heading dated {m.group(1)} in {path}")
    return problems


def unchecked_anchors(graph: nx.DiGraph, repos: dict[str, Path] | None = None) -> list[str]:
    """Advisory: per repo, the anchors of its nodes left unchecked because it has no checkout here."""
    counts: dict[str, int] = {}
    for _, a in graph.nodes(data=True):
        repo = str(a.get("repo") or "")
        if repo and a.get("anchor") and "#" in a["anchor"] and _checkout(repos, repo) is None:
            counts[repo] = counts.get(repo, 0) + 1
    return [f"{n} anchor(s) of repo {r!r} not checked: no checkout of it here (check --repo-path {r}=PATH)"
            for r, n in sorted(counts.items())]


def check_coverage(
    graph: nx.DiGraph,
    repo_root: str | Path,
    repos: dict[str, Path] | None = None,
    decisions: Iterable[str | Path] | None = None,
) -> list[str]:
    """``decisions``: the decision logs the store covers (None: :data:`DEFAULT_DECISIONS`)."""
    repo = Path(repo_root)
    return (
        missing_experiment_nodes(graph, repo)
        + missing_decision_nodes(graph, repo, decisions)
        + anchor_errors(graph, repo, repos)
    )


def _ends(allowed) -> str:
    return "any type" if allowed is None else "|".join(sorted(allowed))


def endpoint_errors(graph: nx.DiGraph, schema) -> list[str]:
    """BLOCKING when the schema declares them (``endpoints``, research_graph layers): an edge whose source or target
    type is outside every (from, to) pair its type allows. An edge type without pairs is not checked; an end whose
    type is unknown (another store's node without one) is not checked; an overlay's edges are not checked here (its own check validates its store)."""
    rules = getattr(schema, "endpoints", None) or {}
    problems: list[str] = []
    for s, d, e in graph.edges(data=True) if rules else ():
        pairs = () if e.get("overlay") else rules.get(e.get("type"))
        st, dt = _end_type(graph, s), _end_type(graph, d)
        if pairs and st and dt and not _fits(pairs, st, dt):
            allowed = ", ".join(f"{_ends(f)} -> {_ends(t)}" for f, t in pairs)
            problems.append(f"edge {s}->{d}: {e.get('type')} from {st} to {dt} is outside its endpoints ({allowed}; "
                            "schema.yaml endpoints)")
    return problems


def _end_type(graph: nx.DiGraph, node: str) -> str | None:
    return graph.nodes[node].get("type") or graph.nodes[node].get("foreign_type")


def _fits(pairs, st: str, dt: str) -> bool:
    return any((f is None or st in f) and (t is None or dt in t) for f, t in pairs)


def staged_module_without_test(staged_files: list[str], repo_root: str | Path) -> list[str]:
    """Every staged src/<package>/**/*.py (but __init__) BLOCKS without a matching test.

    Two naming conventions are accepted: tests/test_<stem>.py (e.g. coinmetrics) and
    tests/test_<parent>_<stem>.py (e.g. research_graph/validate -> test_research_graph_validate).
    """
    repo = Path(repo_root)
    tests_dir = repo / "tests"
    problems: list[str] = []
    for raw in staged_files:
        f = raw.replace("\\", "/")
        if not f.startswith("src/") or f.count("/") < 2 or not f.endswith(".py"):
            continue
        stem = Path(f).stem
        if stem == "__init__":
            continue
        has_test = tests_dir.is_dir() and (
            (tests_dir / f"test_{stem}.py").exists() or any(tests_dir.glob(f"test_*_{stem}.py"))
        )
        if not has_test:
            problems.append(
                f"{f}: staged module with no test (expected tests/test_{stem}.py or test_*_{stem}.py)"
            )
    return problems


def empty_decision_bodies(repo_root: str | Path) -> list[str]:
    """Every dated ## heading in scientific_decisions.md / decisions.md must have a non-empty body."""
    repo = Path(repo_root)
    problems: list[str] = []
    for fname in _DECISION_FILES:
        f = repo / "notes" / fname
        if not f.exists():
            continue
        lines = f.read_text(encoding="utf-8").splitlines()
        heads = [
            (i, m.group(1)) for i, line in enumerate(lines) for m in [_HEADING_RE.match(line)] if m
        ]
        for k, (i, date) in enumerate(heads):
            end = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
            body = "\n".join(lines[i + 1 : end]).strip()
            if not body:
                problems.append(f"notes/{fname}: heading {date} (line {i + 1}) has an empty body")
    return problems


# The research pack's gates (wi-brain-research-pack): moved to research_graph.research_pack, importable from here as
# before (a research project's own checks import them from validate). A monkeypatch on validate's name no
# longer reaches the moved callers: patch research_graph.research_pack's.
from .research_pack import (  # noqa: E402,F401 - re-exported names, after the core's own
    # (research_pack never imports validate at module level: keep it so, or the import cycles)
    _EDGE_ASSERTED,
    _EXP_PATH_RE,
    _edge_nodes,
    _experiment_gaps,
    _experiment_is_methodological,
    _experiment_spec,
    _experiment_targets_edges,
    _exploited,
    _preregistration_gap,
    all_experiment_gaps,
    check_consistency,
    check_wiring,
    edge_coverage,
    edge_drift,
    edge_predictive_on_contemporaneous,
    experiment_tests_no_hypothesis,
    experiments_missing_from_kanban,
    hypothesis_stub_needs_prose,
    hypothesis_validated_without_support,
    l2_without_parent,
    missing_experiment_nodes,
    staged_experiment_gaps,
    staged_experiment_ids,
)
