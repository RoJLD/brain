"""Tests for research_graph.sync — deriving Experiment/SDR stubs + lineage edges from the repo."""

from __future__ import annotations

import json
import textwrap

import networkx as nx
import yaml

from research_graph.loader import load_store
from research_graph.sync import (
    decision_stubs,
    derive,
    experiment_stubs,
    explore_nodes_edges,
    hypothesis_l1_stubs,
    hypothesis_nodes_edges,
    hypothesis_verdict_nodes_edges,
    lineage_edges,
    regenerate_edges_file_text,
    render_edges,
    render_stubs,
    sweep_nodes_edges,
)

_SCHEMA = textwrap.dedent("""
    node_types: [Experiment, SDR, ADR, Hypothesis]
    edge_types: [refines, tests]
    statuses: [active, validated, planned, open]
    """)


def _store(tmp_path, nodes_yaml="[]", edges_yaml="[]"):
    store = tmp_path / "graph"
    (store / "nodes").mkdir(parents=True)
    (store / "schema.yaml").write_text(_SCHEMA, encoding="utf-8")
    (store / "nodes" / "core.yaml").write_text(nodes_yaml, encoding="utf-8")
    (store / "edges.yaml").write_text(edges_yaml, encoding="utf-8")
    return store


def _exp(repo, name, lineage=None):
    d = repo / "experiments" / name
    d.mkdir(parents=True)
    cfg = "experiment:\n  name: x\n"
    if lineage:
        cfg += f'  lineage: "experiments/{lineage}"\n'
    (d / "config.yaml").write_text(cfg, encoding="utf-8")
    (d / "README.md").write_text(f"# {name} — title for {name}\n", encoding="utf-8")
    return d


def test_experiment_stubs_only_for_missing(tmp_path):
    store = _store(
        tmp_path,
        nodes_yaml="- {id: exp001_a, type: Experiment, title: x, status: validated}",
    )
    repo = tmp_path / "repo"
    _exp(repo, "exp001_a")  # already a node -> skipped
    _exp(repo, "exp002_b")  # missing -> stub
    graph = load_store(str(store))
    stubs = experiment_stubs(graph, repo)
    ids = [s["id"] for s in stubs]
    assert ids == ["exp002_b"]
    assert stubs[0]["type"] == "Experiment"
    assert "title for exp002_b" in stubs[0]["title"]


def test_lineage_edges_from_config(tmp_path):
    store = _store(
        tmp_path,
        nodes_yaml=(
            "- {id: exp001_a, type: Experiment, title: a, status: validated}\n"
            "- {id: exp002_b, type: Experiment, title: b, status: active}\n"
        ),
    )
    repo = tmp_path / "repo"
    _exp(repo, "exp001_a")
    _exp(repo, "exp002_b", lineage="exp001_a")
    _exp(repo, "exp003_c", lineage="notebooks/x.ipynb")  # non-node target -> skipped
    graph = load_store(str(store))
    edges = lineage_edges(graph, repo)
    assert {"from": "exp002_b", "to": "exp001_a", "type": "refines"} in edges
    # exp003_c's lineage points outside the node set -> no edge
    assert all(e["from"] != "exp003_c" for e in edges)


def test_decision_stubs_cover_heading_deficit(tmp_path):
    store = _store(tmp_path)
    repo = tmp_path / "repo"
    (repo / "notes").mkdir(parents=True)
    (repo / "notes" / "scientific_decisions.md").write_text(
        "## 2026-06-10 — first decision\n\nbody\n\n## 2026-06-10 — second decision\n\nbody\n",
        encoding="utf-8",
    )
    graph = load_store(str(store))
    stubs = decision_stubs(graph, repo)
    assert len(stubs) == 2  # two headings, zero existing nodes -> two stubs
    assert all(s["type"] == "SDR" for s in stubs)
    assert all(s["anchor"].startswith("notes/scientific_decisions.md#2026-06-10") for s in stubs)


def test_render_dedups_colliding_ids(tmp_path):
    nodes = [
        {"id": "sdr-x", "type": "SDR", "title": "a", "status": "active", "anchor": "f#2026-01-01"},
        {"id": "sdr-x", "type": "SDR", "title": "b", "status": "active", "anchor": "f#2026-01-01"},
    ]
    out = render_stubs(nodes)
    assert "id: sdr-x," in out
    assert "id: sdr-x-1," in out  # collision suffixed


def test_render_edges_format():
    out = render_edges([{"from": "a", "to": "b", "type": "refines"}])
    assert out == "- {from: a, to: b, type: refines}"


def _exp_hyp(repo, name, l1, prediction):
    d = repo / "experiments" / name
    d.mkdir(parents=True)
    (d / "config.yaml").write_text(
        "experiment:\n  name: x\n"
        f'hypothesis:\n  l1: {l1}\n  prediction: "{prediction}"\n'
        '  disconfirming_signature: "p >= 0.05"\n  family: fam\n',
        encoding="utf-8",
    )
    (d / "README.md").write_text(f"# {name}\n", encoding="utf-8")
    return d


def test_hypothesis_nodes_edges_from_config(tmp_path):
    repo = tmp_path / "repo"
    _exp_hyp(repo, "exp037_x", "M-growth", "growth generalises")
    nodes, edges = hypothesis_nodes_edges(repo)
    assert {
        "id": "h2-exp037_x",
        "type": "Hypothesis",
        "level": "L2",
        "status": "proposed",
        "title": "growth generalises",
    } in nodes
    assert {"from": "h2-exp037_x", "to": "M-growth", "type": "instantiates"} in edges
    assert {"from": "exp037_x", "to": "h2-exp037_x", "type": "tests"} in edges


def test_hypothesis_nodes_edges_skips_configs_without_block(tmp_path):
    repo = tmp_path / "repo"
    d = repo / "experiments" / "exp001_a"
    d.mkdir(parents=True)
    (d / "config.yaml").write_text("experiment:\n  name: x\n", encoding="utf-8")
    nodes, edges = hypothesis_nodes_edges(repo)
    assert nodes == [] and edges == []


def test_hypothesis_l1_stubs_for_uncurated(tmp_path):
    repo = tmp_path / "repo"
    _exp_hyp(repo, "exp040_x", "M-new", "some prediction")
    hand = nx.DiGraph()  # nothing curated
    stubs = hypothesis_l1_stubs(hand, repo)
    assert len(stubs) == 1
    assert stubs[0]["id"] == "M-new"
    assert stubs[0]["level"] == "L1"
    assert stubs[0]["status"] == "planned"
    assert "STUB" in stubs[0]["title"]


def test_hypothesis_l1_stubs_skips_curated(tmp_path):
    repo = tmp_path / "repo"
    _exp_hyp(repo, "exp040_x", "M-growth", "some prediction")
    hand = nx.DiGraph()
    hand.add_node("M-growth", type="Hypothesis", level="L1", status="active")
    assert hypothesis_l1_stubs(hand, repo) == []


def test_hand_edges_set_excludes_autoderived(tmp_path):
    from research_graph.sync import _hand_edges_set

    store = tmp_path / "graph"
    (store / "nodes").mkdir(parents=True)
    (store / "edges.yaml").write_text(
        "- {from: a, to: b, type: refines}\n"
        "# --- auto-derived (research_graph sync) ---\n"
        "- {from: x, to: y, type: tests}\n",
        encoding="utf-8",
    )
    s = _hand_edges_set(store)
    assert ("a", "b", "refines") in s
    assert ("x", "y", "tests") not in s  # auto-derived excluded


def test_regenerate_edges_drops_stale_autoderived(tmp_path):
    store = tmp_path / "graph"
    (store / "nodes").mkdir(parents=True)
    (store / "edges.yaml").write_text(
        "- {from: a, to: b, type: refines}\n\n"
        "# --- auto-derived (research_graph sync) ---\n"
        "- {from: stale, to: gone, type: tests}\n",
        encoding="utf-8",
    )
    out = regenerate_edges_file_text(store, "- {from: c, to: d, type: refines}")
    assert "from: a, to: b" in out  # hand edge kept
    assert "stale" not in out  # stale auto-derived dropped (the GC)
    assert "from: c, to: d" in out  # fresh auto-derived block written


def _exp_verdict(repo, name, l1, verdict_block, diag):
    d = repo / "experiments" / name
    (d / "results").mkdir(parents=True)
    (d / "config.yaml").write_text(
        f"hypothesis:\n  l1: {l1}\n  prediction: p\n  verdict: {verdict_block}\n",
        encoding="utf-8",
    )
    (d / "results" / "diagnostics.json").write_text(diag, encoding="utf-8")
    (d / "README.md").write_text(f"# {name}\n", encoding="utf-8")
    return d


def test_hypothesis_verdict_validates_from_diagnostics(tmp_path):
    repo = tmp_path / "repo"
    _exp_verdict(
        repo,
        "exp037_x",
        "M-growth",
        "{field: growth_sign_test_p, op: lt, threshold: 0.05, pass: validates, fail: refutes}",
        '{"verdict": {"growth_sign_test_p": 0.0039}}',
    )
    nodes, edges = hypothesis_verdict_nodes_edges(repo)
    assert {"id": "v-exp037_x", "type": "Verdict", "status": "validated"}.items() <= nodes[
        0
    ].items()
    assert {"from": "v-exp037_x", "to": "M-growth", "type": "validates"} in edges
    assert {"from": "exp037_x", "to": "v-exp037_x", "type": "produces"} in edges


def test_hypothesis_verdict_refutes_when_condition_fails(tmp_path):
    repo = tmp_path / "repo"
    _exp_verdict(
        repo,
        "exp035_x",
        "M-valuation",
        "{field: any_valuation_moderation, op: eq, threshold: true, pass: validates, fail: refutes}",
        '{"verdict": {"any_valuation_moderation": false}}',
    )
    nodes, edges = hypothesis_verdict_nodes_edges(repo)
    assert nodes[0]["status"] == "rejected"
    assert {"from": "v-exp035_x", "to": "M-valuation", "type": "refutes"} in edges


def test_hypothesis_verdict_skips_without_diagnostics(tmp_path):
    repo = tmp_path / "repo"
    d = repo / "experiments" / "exp040_x"
    d.mkdir(parents=True)
    (d / "config.yaml").write_text(
        "hypothesis:\n  l1: M-x\n  prediction: p\n"
        "  verdict: {field: f, op: lt, threshold: 0.05, pass: validates, fail: refutes}\n",
        encoding="utf-8",
    )
    assert hypothesis_verdict_nodes_edges(repo) == ([], [])


def test_hypothesis_verdict_navigates_nested_field(tmp_path):
    repo = tmp_path / "repo"
    _exp_verdict(
        repo,
        "exp008_x",
        "M-residual-us",
        "{field: arm_a.h_survival, op: eq, threshold: true, pass: validates, fail: refutes}",
        '{"verdict": {"arm_a": {"h_survival": true}}}',
    )
    nodes, edges = hypothesis_verdict_nodes_edges(repo)
    assert {"from": "v-exp008_x", "to": "M-residual-us", "type": "validates"} in edges


def test_hypothesis_verdict_surrogate_collapse_voids_validates(tmp_path):
    # v2 guard: a passing point-estimate whose surrogate null collapsed (surrogate_survived=false)
    # does NOT count as a validation -> the edge is downgraded to `inconclusive`.
    repo = tmp_path / "repo"
    _exp_verdict(
        repo,
        "exp010_x",
        "M-funding-flight",
        "{field: flight_p, op: lt, threshold: 0.05, pass: validates, fail: refutes}",
        '{"verdict": {"flight_p": 0.001, "surrogate_survived": false}}',
    )
    nodes, edges = hypothesis_verdict_nodes_edges(repo)
    assert nodes[0]["status"] == "inconclusive"
    assert "voided" in nodes[0]["title"]
    assert {"from": "v-exp010_x", "to": "M-funding-flight", "type": "inconclusive"} in edges
    assert {"from": "v-exp010_x", "to": "M-funding-flight", "type": "validates"} not in edges


def test_hypothesis_verdict_surrogate_survived_keeps_validates(tmp_path):
    # surrogate_survived=true (or absent) leaves a validates intact.
    repo = tmp_path / "repo"
    _exp_verdict(
        repo,
        "exp011_x",
        "M-move-amplif",
        "{field: amp_p, op: lt, threshold: 0.05, pass: validates, fail: refutes}",
        '{"verdict": {"amp_p": 0.001, "surrogate_survived": true}}',
    )
    nodes, edges = hypothesis_verdict_nodes_edges(repo)
    assert nodes[0]["status"] == "validated"
    assert {"from": "v-exp011_x", "to": "M-move-amplif", "type": "validates"} in edges


def test_sweep_nodes_edges_one_l2_per_cell(tmp_path):
    repo = tmp_path / "repo"
    sd = repo / "results" / "sweeps"
    sd.mkdir(parents=True)
    (sd / "fam.json").write_text(
        json.dumps(
            {
                "family": "fam",
                "l1": "M-x",
                "prediction": "p",
                "disconfirming_signature": "d",
                "cells": {
                    "classifiers=iorb": {"n_survivors": 1, "verdict": "validates"},
                    "classifiers=cp_ois": {"n_survivors": 0, "verdict": "refutes"},
                },
            }
        ),
        encoding="utf-8",
    )
    nodes, edges = sweep_nodes_edges(repo)
    ids = {n["id"] for n in nodes}
    assert "h2-sweep-fam-classifiers=iorb" in ids
    assert any(n.get("level") == "L2" and n.get("status") == "proposed" for n in nodes)
    assert "h2-sweep-fam-classifiers=cp_ois" in ids  # refuted cell written too (honesty)
    assert {"from": "h2-sweep-fam-classifiers=iorb", "to": "M-x", "type": "instantiates"} in edges
    assert any(e["to"] == "M-x" and e["type"] == "validates" for e in edges)
    assert any(e["to"] == "M-x" and e["type"] == "refutes" for e in edges)


def _write_explore_run(
    repo,
    name="camp",
    verdicts=(("classifiers=iorb", "confirmed"), ("classifiers=vix", "refuted")),
):
    d = repo / "results" / "explore" / name
    d.mkdir(parents=True)
    (d / "campaign.json").write_text(
        json.dumps(
            {
                "name": name,
                "l1_id": "M-x",
                "held_out": "2024-01-01",
                "seed": 7,
                "candidates": [
                    {
                        "cell_id": cid,
                        "parent_l1": "M-x",
                        "family": "fam",
                        "cfg": {},
                        "disconfirming_signature": "d",
                    }
                    for cid, _ in verdicts
                ],
            }
        ),
        encoding="utf-8",
    )
    (d / "verdict_report.json").write_text(
        json.dumps(
            {
                "family_size": len(verdicts),
                "fdr_threshold": 0.05,
                "cells": [
                    {
                        "cell_id": cid,
                        "parent_l1": "M-x",
                        "verdict": v,
                        "disconfirming_signature": "d",
                    }
                    for cid, v in verdicts
                ],
            }
        ),
        encoding="utf-8",
    )
    return d


def test_explore_nodes_edges_one_l2_per_cell(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_explore_run(repo)
    nodes, edges = explore_nodes_edges(repo)
    ids = {n["id"] for n in nodes}
    assert "h2-explore-camp-classifiers=iorb" in ids
    assert "h2-explore-camp-classifiers=vix" in ids  # refuted cell written too (honesty)
    assert any(n.get("level") == "L2" and n.get("status") == "proposed" for n in nodes)
    assert {
        "from": "h2-explore-camp-classifiers=iorb",
        "to": "M-x",
        "type": "instantiates",
    } in edges
    assert any(
        e["to"] == "M-x" and e["type"] == "validates" for e in edges
    )  # confirmed -> validates
    assert any(e["to"] == "M-x" and e["type"] == "refutes" for e in edges)  # refuted -> refutes


def test_explore_nodes_edges_skips_incomplete_run(tmp_path):
    repo = tmp_path / "repo"
    (repo / "results" / "explore" / "halfrun").mkdir(parents=True)
    # campaign.json present but no verdict_report.json -> skipped, no exception
    (repo / "results" / "explore" / "halfrun" / "campaign.json").write_text("{}", encoding="utf-8")
    nodes, edges = explore_nodes_edges(repo)
    assert nodes == [] and edges == []


def test_explore_node_ids_are_yaml_safe(tmp_path):
    # discovery cell_ids embed list reprs (classifiers=['vix']...) whose [ ' ] would break the
    # unquoted flow-style node id -> the rendered store must round-trip through load_store.
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_explore_run(
        repo, name="camp", verdicts=(("classifiers=['vix']__n_regimes=2", "refuted"),)
    )
    nodes, edges = explore_nodes_edges(repo)
    ids = [n["id"] for n in nodes]
    assert ids, "expected nodes"
    assert all(ch not in nid for nid in ids for ch in "[]' "), ids  # no YAML-unsafe chars
    # the edges reference the same sanitised ids
    l2_ids = {n["id"] for n in nodes if n.get("level") == "L2"}
    assert any(e["from"] in l2_ids and e["type"] == "instantiates" for e in edges)


# --- derive keeps stubs whose local-only source (results/) is absent on this checkout ---------

_PREV_HYP = (
    "- {id: v-exp040_x, type: Verdict, title: 'exp040_x f=0.01 -> validates', status: validated}\n"
    "- {id: h2-sweep-fam-classifiers=iorb, type: Hypothesis, title: 'fam cell', status: proposed, level: L2}\n"
    "- {id: v-sweep-fam-classifiers=iorb, type: Verdict, title: 'fam/iorb', status: validated}\n"
    "- {id: h2-explore-camp-classifiers=vix, type: Hypothesis, title: 'camp cell', status: proposed, level: L2}\n"
    "- {id: v-explore-camp-classifiers=vix, type: Verdict, title: 'camp/vix', status: rejected}\n"
)
_PREV_AUTO_EDGES = (
    "- {from: exp040_x, to: v-exp040_x, type: produces}\n"
    "- {from: v-exp040_x, to: M-x, type: validates}\n"
    "- {from: h2-sweep-fam-classifiers=iorb, to: M-x, type: instantiates}\n"
    "- {from: v-sweep-fam-classifiers=iorb, to: M-x, type: validates}\n"
    "- {from: h2-explore-camp-classifiers=vix, to: M-x, type: instantiates}\n"
    "- {from: v-explore-camp-classifiers=vix, to: M-x, type: refutes}\n"
)
_VERDICT_CFG = (
    "hypothesis:\n  l1: M-x\n  prediction: p\n"
    "  verdict: {field: f, op: lt, threshold: 0.05, pass: validates, fail: refutes}\n"
)


def _synced_store(tmp_path, cfg=_VERDICT_CFG):
    """A store as left by a sync on a machine that had the run outputs; this repo has none."""
    repo = tmp_path / "repo"
    d = repo / "experiments" / "exp040_x"
    d.mkdir(parents=True)
    (d / "config.yaml").write_text(cfg, encoding="utf-8")
    store = _store(
        tmp_path,
        nodes_yaml="- {id: exp040_x, type: Experiment, title: t, status: active}\n"
        "- {id: M-x, type: Hypothesis, title: m, status: open, level: L1}\n",
        edges_yaml="[]\n\n# --- auto-derived (research_graph sync) ---\n" + _PREV_AUTO_EDGES,
    )
    (store / "nodes" / "_generated_hypotheses.yaml").write_text(_PREV_HYP, encoding="utf-8")
    return store, repo


def _ids(res):
    return {n["id"] for n in res["hypotheses"]}


def _etuples(res):
    return {(e["from"], e["to"], e["type"]) for e in res["edges"]}


def test_derive_keeps_stubs_when_results_absent(tmp_path):
    # regression: on a checkout without results/ (gitignored / never committed), sync --write
    # used to GC every verdict, sweep and explore stub plus their edges (64 stubs, 100 edges).
    store, repo = _synced_store(tmp_path)
    res = derive(store, repo)
    assert {
        "v-exp040_x",
        "h2-sweep-fam-classifiers=iorb",
        "v-sweep-fam-classifiers=iorb",
        "h2-explore-camp-classifiers=vix",
        "v-explore-camp-classifiers=vix",
    } <= _ids(res)
    assert {(e["from"], e["to"], e["type"]) for e in yaml.safe_load(_PREV_AUTO_EDGES)} <= _etuples(
        res
    )


def test_derive_drops_verdict_whose_declaration_is_gone(tmp_path):
    store, repo = _synced_store(tmp_path, cfg="hypothesis:\n  l1: M-x\n  prediction: p\n")
    res = derive(store, repo)
    assert "v-exp040_x" not in _ids(res)  # GC still applies: the config no longer declares it
    assert not any("v-exp040_x" in (e["from"], e["to"]) for e in res["edges"])
    assert "v-explore-camp-classifiers=vix" in _ids(res)  # v-explore-* is not a v-expNNN verdict


def test_derive_rederives_when_results_present(tmp_path):
    store, repo = _synced_store(tmp_path)
    res_dir = repo / "experiments" / "exp040_x" / "results"
    res_dir.mkdir()
    (res_dir / "diagnostics.json").write_text('{"verdict": {"f": 0.5}}', encoding="utf-8")
    _write_explore_run(repo, name="camp", verdicts=(("classifiers=iorb", "confirmed"),))
    res = derive(store, repo)
    v = next(n for n in res["hypotheses"] if n["id"] == "v-exp040_x")
    assert v["status"] == "rejected"  # fresh data wins over the carried stub
    assert ("v-exp040_x", "M-x", "validates") not in _etuples(res)
    # the campaign ran here: its fresh cells are authoritative, the old cell is GC'd
    assert "h2-explore-camp-classifiers=iorb" in _ids(res)
    assert "v-explore-camp-classifiers=vix" not in _ids(res)
    assert "v-sweep-fam-classifiers=iorb" in _ids(res)  # sweep family still absent -> kept


def test_decision_stubs_cover_the_logs_given_anchored_at_their_path(tmp_path):
    store = _store(tmp_path)
    repo = tmp_path / "repo"
    for rel in ("notes/decisions.md", "lab/decisions.md", "lab/scientific_decisions.md"):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(f"## 2026-06-10 — from {rel}\n\nbody\n", encoding="utf-8")
    graph = load_store(str(store))
    stubs = decision_stubs(graph, repo, logs=["lab/scientific_decisions.md", "lab/decisions.md"])
    assert [(s["type"], s["anchor"]) for s in stubs] == [
        ("SDR", "lab/scientific_decisions.md#2026-06-10-from-lab-scientific-decisions-md"),
        ("ADR", "lab/decisions.md#2026-06-10-from-lab-decisions-md"),
    ]  # notes/decisions.md is not a log of this store: no stub from it
    assert decision_stubs(graph, repo, logs=[]) == []
    assert [s["anchor"].split("#")[0] for s in decision_stubs(graph, repo)] == ["notes/decisions.md"]  # the default


def test_a_node_covers_the_log_its_anchor_names_not_another_of_the_same_name(tmp_path):
    store = _store(tmp_path, nodes_yaml=(
        '- {id: adr-2026-06-10-a, type: ADR, status: active, anchor: "notes/decisions.md#2026-06-10-a"}\n'))
    repo = tmp_path / "repo"
    for rel, title in (("notes/decisions.md", "a"), ("lab/decisions.md", "b")):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(f"## 2026-06-10 — {title}\n\nbody\n", encoding="utf-8")
    graph = load_store(str(store))
    assert decision_stubs(graph, repo, logs=["notes/decisions.md"]) == []
    assert [s["anchor"] for s in decision_stubs(graph, repo, logs=["lab/decisions.md"])] == [
        "lab/decisions.md#2026-06-10-b"]  # the node of notes/decisions.md does not cover it
    assert [s["id"] for s in derive(store, repo, decisions=["lab/decisions.md"])["decisions"]] == ["adr-2026-06-10-b"]
