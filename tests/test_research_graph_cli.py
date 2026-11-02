from __future__ import annotations

import textwrap
from pathlib import Path

from research_graph.cli import main

STORE = str(Path(__file__).parent / "fixtures" / "research_graph")

_SCHEMA = textwrap.dedent("""
    node_types: [Experiment, Hypothesis]
    edge_types: [tests]
    statuses: [active, open]
    levels: [L0, L1, L2]
    """)


def _adv_store(tmp_path):
    store = tmp_path / "graph"
    (store / "nodes").mkdir(parents=True)
    (store / "schema.yaml").write_text(_SCHEMA, encoding="utf-8")
    (store / "nodes" / "core.yaml").write_text(
        "- {id: exp007_x, type: Experiment, status: active}", encoding="utf-8"
    )
    (store / "edges.yaml").write_text("[]", encoding="utf-8")
    return store


def test_cli_build_ok(capsys):
    rc = main(["--store", STORE, "build"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "11 nodes" in out


def test_cli_frontier(capsys):
    rc = main(["--store", STORE, "frontier"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "exp002" in out


def test_cli_check_reports_missing(capsys, tmp_path):
    # Point check at a repo root with no experiments/notes -> coverage clean,
    # but the fixture anchors reference files that don't exist there -> errors.
    rc = main(["--store", STORE, "--repo-root", str(tmp_path), "check"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "anchor file missing" in err


def test_cli_provenance_unknown_node(capsys):
    rc = main(["--store", STORE, "provenance", "nope"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "unknown node: nope" in err


def test_cli_check_wiring_blocks_untested_experiment(tmp_path, capsys):
    store = _adv_store(tmp_path)  # exp007_x Experiment, no tests edge, no methodological marker
    rc = main(["--store", str(store), "--repo-root", str(tmp_path), "check"])
    err = capsys.readouterr().err
    assert rc == 1  # experiment_tests_no_hypothesis is now BLOCKING (check_wiring)
    assert "tests no Hypothesis" in err


def test_cli_check_methodological_marker_exempts(tmp_path, capsys):
    store = _adv_store(tmp_path)
    cfg = tmp_path / "experiments" / "exp007_x"
    cfg.mkdir(parents=True)
    (cfg / "config.yaml").write_text(
        "experiment:\n  name: x\nmethodological: true\n", encoding="utf-8"
    )
    rc = main(["--store", str(store), "--repo-root", str(tmp_path), "check"])
    assert rc == 0  # an explicit methodological declaration clears the blocking gate


def test_cli_check_advisory_prints_but_exit_zero(tmp_path, capsys):
    # An orphan L2 (no instantiates parent) is a soft advisory: printed, does not block.
    store = tmp_path / "graph"
    (store / "nodes").mkdir(parents=True)
    (store / "schema.yaml").write_text(_SCHEMA, encoding="utf-8")
    (store / "nodes" / "core.yaml").write_text(
        "- {id: h2-x, type: Hypothesis, status: open, level: L2}", encoding="utf-8"
    )
    (store / "edges.yaml").write_text("[]", encoding="utf-8")
    rc = main(["--store", str(store), "--repo-root", str(tmp_path), "check"])
    out = capsys.readouterr().out
    assert rc == 0  # advisory does not block
    assert "advisory:" in out
    assert "L2 without" in out


def test_cli_sync_writes_hypotheses(tmp_path, capsys):
    store = _adv_store(tmp_path)
    repo = tmp_path / "repo"
    d = repo / "experiments" / "exp037_x"
    d.mkdir(parents=True)
    (d / "config.yaml").write_text(
        "experiment:\n  name: x\nhypothesis:\n  l1: M-growth\n"
        '  prediction: "p"\n  disconfirming_signature: "d"\n  family: f\n',
        encoding="utf-8",
    )
    (d / "README.md").write_text("# exp037_x\n", encoding="utf-8")
    main(["--store", str(store), "--repo-root", str(repo), "sync", "--write"])
    gen = (store / "nodes" / "_generated_hypotheses.yaml").read_text(encoding="utf-8")
    assert "h2-exp037_x" in gen
