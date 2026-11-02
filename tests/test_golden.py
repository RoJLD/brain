"""Golden outputs: what the consumers of research_graph read, pinned byte for byte.

The ``brain`` command runs ``sync --write``, ``kanban --write``, ``check`` and ``pending --json`` on its stores; a
research platform runs every command, and its own backlog views wrap the query, history and report modules. Each case
runs the CLI in-process on a fresh copy of a small world and compares its exit code, stdout, stderr and the files it
wrote or changed with ``tests/golden/<world>/<case>.txt``.

The extraction (0.1.0) was checked with this harness: the same cases recorded from the module the engine came from and
from the package, every difference reviewed (only the deliberate changes of 0.1.0: the generated views' marker, the
store's owner instead of a name in the code). ``RESEARCH_GRAPH_MODULE`` names the module under test (default
``research_graph``); ``RESEARCH_GRAPH_GOLDEN=update`` rewrites the files instead of comparing them: review the diff.

Outputs are normalized only where they depend on the machine: the world's temporary root becomes ``<ROOT>`` (with
``/`` separators), commit hashes become ``<commit-N>`` in commit order, line endings become ``\\n``, and the wording of
a Python ``SyntaxError`` (it changes between Python versions) becomes ``<message>``.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest

from tests import backlog_world as bw

ENGINE = os.environ.get("RESEARCH_GRAPH_MODULE", "research_graph")
UPDATE = os.environ.get("RESEARCH_GRAPH_GOLDEN") == "update"
GOLDEN = Path(__file__).parent / "golden"
FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 11, 2)

cli = importlib.import_module(f"{ENGINE}.cli")
query = importlib.import_module(f"{ENGINE}.query")


class _Today(date):
    """``pending`` ages its questions from today: a fixed day keeps the outputs stable."""

    @classmethod
    def today(cls):
        return TODAY


# ---------------------------------------------------------------- the worlds

DECISIONS = """\
# Decisions

## 2026-10-01 — Store format: YAML flow nodes

Context: one node per line. Decision: flow style. Why: diffs. Revisit if: never.

## 2026-10-02 — Accents é, symbols & (parentheses)

Context: c. Decision: d. Why: w. Revisit if: r.

## 2026-10-02 — Accents é, symbols & (parentheses)

Context: the same title twice on one day. Decision: d. Why: w. Revisit if: r.

## 2026-10-03: REVERSAL: Store format: YAML flow nodes

Supersedes: 2026-10-01. Trigger: t. New decision: n. Migration: m.

## 2026-10-04 —

Context: an empty title. Decision: d.
"""

RESEARCH_SCHEMA = """\
node_types: [Experiment, SDR, ADR, Hypothesis, Verdict, WorkItem, Milestone]
edge_types: [lineage, decided_by, instantiates, tests, produces, validates, refutes, part_of, depends_on]
statuses: [active, validated, planned, open, proposed, rejected, todo, doing, blocked, done, dropped, pending, reached]
"""

RESEARCH_NODES = """\
- {id: exp001_base, type: Experiment, title: "Base experiment", status: validated}
- {id: M-x, type: Hypothesis, title: "Mechanism x", status: open, level: L1}
- {id: wi-run, type: WorkItem, status: todo, title: "Run the sweep", props: {priority: P1}}
- {id: ms-r, type: Milestone, status: pending, title: "Research milestone", props: {trigger: "a sweep ran"}}
"""

RESEARCH_EDGES = """\
- {from: wi-run, to: ms-r, type: part_of}

# --- auto-derived (research_graph sync) ---
- {from: exp009_gone, to: exp001_base, type: lineage}
"""

SDR = """\
# Scientific decisions

## 2026-09-01 — Funding horizon fixed at 8 h

Hypothesis: h. Evidence base: e. Sensitivity: s. Validation plan: v. Reproducibility: r.
"""

VENUE_PY = '''"""A fake venue adapter."""
from fake_pkg.store import save as reexported

RATE_CAP: float = 0.04


class FakeVenue:
    name = "fake"

    def funding(self, symbol):
        return symbol


async def normalize(frame):
    return frame
'''


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _world_backlog(root: Path) -> dict:
    """The backlog world of the query tests, with an ADR log and a sibling operations store read as an overlay."""
    repo = root / "research-lab"
    store = bw.write_store(repo)
    _write(repo / "notes" / "decisions.md", DECISIONS)
    over = root / "hf" / "ops" / "graph"
    _write(over / "schema.yaml", "node_types: [WorkItem]\nedge_types: [depends_on]\nstatuses: [todo, done]\n")
    _write(over / "nodes" / "ops.yaml", '- {id: wi-hf, type: WorkItem, status: todo, title: hf, anchor: "ops/a.md#x"}\n')
    _write(over / "external.yaml", "- {id: wi-doing}\n")
    _write(over / "edges" / "ops.yaml", "- {from: wi-hf, to: wi-doing, type: depends_on}\n")
    return {"repo": repo, "store": store, "overlay": over}


def _world_history(root: Path) -> dict:
    repo = bw.make_history(root)
    return {"repo": repo, "store": repo / "notes" / "graph"}


def _world_fixture(name: str):
    def build(root: Path) -> dict:
        repo = root / "repo"
        store = repo / "notes" / "graph"
        shutil.copytree(FIXTURES / name, store)
        return {"repo": repo, "store": store}
    return build


def _world_code(root: Path) -> dict:
    out = _world_fixture("code_layer")(root)
    pkg = root / "fake-repo" / "src" / "fake_pkg"
    _write(pkg / "__init__.py", "")
    _write(pkg / "venue.py", VENUE_PY)
    _write(pkg / "store.py", "def save():\n    return None\n")
    _write(pkg / "broken.py", "def oops(:\n")
    _write(root / "fake-repo" / "scripts" / "run.ps1", "Write-Output hi\n")
    return out


def _world_research(root: Path) -> dict:
    """Experiments with lineage and hypotheses, a verdict from diagnostics, a sweep, an explore campaign, both
    decision logs, and a stale auto-derived edge for sync to drop."""
    repo = root / "repo"
    store = repo / "notes" / "graph"
    _write(store / "schema.yaml", RESEARCH_SCHEMA)
    _write(store / "nodes" / "core.yaml", RESEARCH_NODES)
    _write(store / "edges.yaml", RESEARCH_EDGES)
    exp = repo / "experiments"
    _write(exp / "exp001_base" / "config.yaml", "experiment:\n  name: base\n")
    _write(exp / "exp001_base" / "README.md", "# exp001 — Base experiment\n")
    _write(exp / "exp002_child" / "config.yaml",
           'experiment:\n  name: child\n  lineage: "experiments/exp001_base"\n'
           'hypothesis:\n  l1: M-x\n  prediction: "beta > 0"\n  disconfirming_signature: "p >= 0.05"\n'
           "  family: fam\n")
    _write(exp / "exp002_child" / "README.md", "# exp002 — Child of the base\n")
    _write(exp / "exp003_verdict" / "config.yaml",
           "hypothesis:\n  l1: M-y\n  prediction: p\n"
           "  verdict: {field: stats.p, op: lt, threshold: 0.05, pass: validates, fail: refutes}\n")
    _write(exp / "exp003_verdict" / "README.md", "# exp003\n")
    _write(exp / "exp003_verdict" / "results" / "diagnostics.json", json.dumps({"stats": {"p": 0.01}}))
    _write(repo / "results" / "sweeps" / "fam.json", json.dumps({
        "family": "fam", "l1": "M-x", "prediction": "p", "disconfirming_signature": "d",
        "cells": {"classifiers=iorb": {"n_survivors": 1, "verdict": "validates"},
                  "classifiers=cp_ois": {"n_survivors": 0, "verdict": "refutes"}}}))
    camp = repo / "results" / "explore" / "camp"
    cells = (("classifiers=['vix']__n_regimes=2", "refuted"), ("classifiers=iorb", "confirmed"))
    _write(camp / "campaign.json", json.dumps({
        "name": "camp", "l1_id": "M-x", "held_out": "2024-01-01", "seed": 7,
        "candidates": [{"cell_id": c, "parent_l1": "M-x", "family": "fam", "cfg": {},
                        "disconfirming_signature": "d"} for c, _ in cells]}))
    _write(camp / "verdict_report.json", json.dumps({
        "family_size": len(cells), "fdr_threshold": 0.05,
        "cells": [{"cell_id": c, "parent_l1": "M-x", "verdict": v, "disconfirming_signature": "d"}
                  for c, v in cells]}))
    _write(repo / "notes" / "decisions.md", DECISIONS)
    _write(repo / "notes" / "scientific_decisions.md", SDR)
    return {"repo": repo, "store": store}


WORLDS = {
    "backlog": _world_backlog,
    "history": _world_history,
    "layered": _world_fixture("layered_graph"),
    "research": _world_research,
    "researchfx": _world_fixture("research_graph"),
    "code": _world_code,
}

# ---------------------------------------------------------------- the cases
# (world, case, argv after --store/--repo-root). "{each:<type>|*}" runs the command once per node of that type (or
# every node), in sorted order, and pins the outputs together. "{out}" is a file under the world's root.

CASES = [
    # the brain command's calls, then a research platform's
    ("backlog", "sync", ["sync"]),
    ("backlog", "sync-write", ["sync", "--write"]),
    ("backlog", "kanban", ["kanban"]),
    ("backlog", "kanban-write", ["kanban", "--write"]),
    ("backlog", "check", ["check"]),
    ("backlog", "pending", ["pending"]),
    ("backlog", "pending-json", ["pending", "--json"]),
    ("backlog", "items", ["items"]),
    ("backlog", "items-json-all", ["items", "--all", "--json"]),
    ("backlog", "items-filters", ["items", "--priority", "P1", "--priority", "none", "--text", "funding"]),
    ("backlog", "items-prop", ["items", "--all", "--prop", "pr", "--prop", "external_blocker=Ada", "--json"]),
    ("backlog", "items-repo", ["items", "--all", "--repo", "ops-repo", "--json"]),
    ("backlog", "items-overlay", ["--overlay", "{overlay}", "items", "--all", "--json"]),
    ("backlog", "item-each", ["item", "{each:*}", "--no-git", "--json"]),
    ("backlog", "closed", ["closed", "--no-git"]),
    ("backlog", "closed-json", ["closed", "--no-git", "--json", "--since", "2026-10-15"]),
    ("backlog", "roadmap", ["roadmap"]),
    ("backlog", "roadmap-json", ["roadmap", "--json"]),
    ("backlog", "roadmap-markdown", ["roadmap", "--markdown"]),
    ("backlog", "roadmap-write", ["roadmap", "--write"]),
    ("backlog", "roadmap-refuse", ["roadmap", "--write", "--out", "{handwritten}"]),
    ("backlog", "priorities-proposal", ["priorities", "proposal"]),
    ("backlog", "priorities-proposal-json", ["priorities", "proposal", "--json"]),
    ("backlog", "priorities-apply", ["priorities", "apply"]),
    ("backlog", "priorities-apply-write", ["priorities", "apply", "--set", "wi-free=P3", "--write"]),
    ("backlog", "work-frontier", ["work-frontier"]),
    ("backlog", "blocked", ["blocked"]),
    ("backlog", "milestone-each", ["milestone", "{each:Milestone}"]),
    ("backlog", "decisions-each", ["decisions", "{each:*}"]),
    ("backlog", "unknown-node", ["item", "nope", "--no-git"]),
    ("backlog", "bad-day", ["items", "--since", "2026-13-01"]),
    ("history", "items-since", ["items", "--all", "--since", "2026-10-03", "--json"]),
    ("history", "item", ["item", "wi-a"]),
    ("history", "item-json", ["item", "wi-b", "--json"]),
    ("history", "closed", ["closed"]),
    ("history", "events", ["events"]),
    ("history", "events-json", ["events", "--all-types", "--json", "--since", "2026-10-03"]),
    ("history", "events-id", ["events", "--id", "wi-a", "--id", "wi-d"]),
    ("history", "asof", ["asof", "2026-10-04", "--all"]),
    ("history", "asof-json", ["asof", "2026-10-02", "--json"]),
    ("history", "asof-before", ["asof", "2026-09-01"]),
    ("layered", "build", ["build"]),
    ("layered", "check", ["check"]),
    ("layered", "frontier", ["frontier"]),
    ("layered", "gated", ["gated"]),
    ("layered", "work-frontier", ["work-frontier"]),
    ("layered", "blocked", ["blocked"]),
    ("layered", "layer-each", ["layer", "{each:layer}"]),
    ("layered", "milestone-each", ["milestone", "{each:Milestone}"]),
    ("layered", "impact-each", ["impact", "{each:*}"]),
    ("layered", "decisions-each", ["decisions", "{each:*}"]),
    ("layered", "provenance-each", ["provenance", "{each:*}"]),
    ("layered", "kanban", ["kanban"]),
    ("layered", "roadmap-markdown", ["roadmap", "--markdown"]),
    ("layered", "export", ["export-gitnexus", "--out", "{out}"]),
    ("layered", "export-typed", ["export-gitnexus", "--out", "{out}", "--mode", "typed", "--layers", "work", "data"]),
    ("research", "sync", ["sync"]),
    ("research", "sync-write", ["sync", "--write"]),
    ("research", "check", ["check"]),
    ("research", "frontier", ["frontier"]),
    ("research", "gated", ["gated"]),
    ("researchfx", "build", ["build"]),
    ("researchfx", "check", ["check"]),
    ("researchfx", "frontier", ["frontier"]),
    ("researchfx", "gated", ["gated"]),
    ("researchfx", "provenance-each", ["provenance", "{each:*}"]),
    ("code", "check", ["check"]),
    ("code", "code-each", ["code", "{each:*}"]),
    ("code", "impact-each", ["impact", "{each:*}"]),
    ("code", "code-check", ["code-check", "--platform-root", "{root}", "--json", "{out}"]),
    ("code", "export", ["export-gitnexus", "--out", "{out}", "--mode", "typed"]),
]


@pytest.fixture(scope="session")
def templates(tmp_path_factory) -> dict:
    """Each world built once; every case runs on its own copy."""
    out = {}
    for name, build in WORLDS.items():
        root = tmp_path_factory.mktemp(f"world-{name}")
        out[name] = (root, build(root))
    return out


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and ".git" not in p.relative_to(root).parts}


def _commits(repo: Path) -> list[str]:
    if not (repo / ".git").exists():
        return []
    res = subprocess.run(["git", "-C", str(repo), "rev-list", "--all", "--reverse", "--date-order"],
                         capture_output=True, text=True)
    return res.stdout.split()


def _normalize(text: str, root: Path, commits: list[str]) -> str:
    text = text.replace("\r\n", "\n")
    for spelling in {str(root.resolve()), str(root), root.resolve().as_posix(), root.as_posix(),
                     json.dumps(str(root.resolve()))[1:-1], json.dumps(str(root))[1:-1]}:
        text = text.replace(spelling, "<ROOT>")
    text = "\n".join(re.sub(r"<ROOT>[^\s\"'`)]*", lambda m: m.group(0).replace("\\\\", "/").replace("\\", "/"), line)
                     for line in text.split("\n"))
    for i, sha in enumerate(commits):
        text = text.replace(sha, f"<commit-{i}>").replace(sha[:7], f"<commit-{i}>")
    return re.sub(r"SyntaxError: [^(\n\"]*\(", "SyntaxError: <message> (", text)  # its wording varies by Python


def _each(token: str, store: Path) -> list[str]:
    kind = token[len("{each:"):-1]
    if kind == "layer":
        schema = importlib.import_module(f"{ENGINE}.schema").load_schema(store / "schema.yaml")
        return sorted(set(schema.layers.values()))
    g = importlib.import_module(f"{ENGINE}.loader").load_store(store)
    return sorted(n for n, a in g.nodes(data=True) if kind == "*" or a.get("type") == kind)


def _run(argv: list[str], root: Path, capsys) -> str:
    code = cli.main(argv)
    out, err = capsys.readouterr()
    return f"exit: {code}\n--- stdout\n{out}--- stderr\n{err}"


@pytest.mark.parametrize("world, case, args", CASES, ids=[f"{w}-{c}" for w, c, _ in CASES])
def test_golden(world, case, args, templates, tmp_path, capsys, monkeypatch):
    src_root, _ = templates[world]
    root = tmp_path / "w"
    shutil.copytree(src_root, root)
    paths = {k: Path(str(v).replace(str(src_root), str(root))) for k, v in templates[world][1].items()}
    handwritten = root / "handwritten.md"
    handwritten.write_text("# A hand-written board\n", encoding="utf-8")
    monkeypatch.chdir(root)
    monkeypatch.setattr(query, "date", _Today)
    subs = {"{root}": str(root), "{out}": str(root / "out" / "payload.json"), "{handwritten}": str(handwritten),
            "{overlay}": str(paths.get("overlay", ""))}
    base = ["--store", str(paths["store"]), "--repo-root", str(paths["repo"])]
    argv = [subs.get(a, a) for a in args]
    before = _snapshot(root)
    each = next((a for a in argv if a.startswith("{each:")), None)
    if each:
        parts = []
        for nid in _each(each, paths["store"]):
            parts.append(f"=== {nid}\n" + _run(base + [nid if a == each else a for a in argv], root, capsys))
        result = "".join(parts)
    else:
        result = _run(base + argv, root, capsys)
    after = _snapshot(root)
    for rel in sorted(after):
        if before.get(rel) != after[rel]:
            result += f"--- file {rel}\n" + after[rel].decode("utf-8")
    for rel in sorted(set(before) - set(after)):
        result += f"--- removed {rel}\n"
    shown = " ".join(args)
    text = _normalize(f"$ research_graph {shown}\n{result}", root, _commits(paths["repo"]))
    golden = GOLDEN / world / f"{case}.txt"
    if UPDATE:
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(text, encoding="utf-8", newline="\n")
        return
    assert golden.exists(), f"no golden file {golden}: record it with RESEARCH_GRAPH_GOLDEN=update"
    assert text == golden.read_text(encoding="utf-8")
