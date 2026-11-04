from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

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


def test_cli_check_reads_another_repos_anchors_in_the_checkout_given(capsys, tmp_path):
    store, eng = tmp_path / "graph", tmp_path / "eng"
    (store / "nodes").mkdir(parents=True)
    (store / "schema.yaml").write_text("node_types: [Repo, Doc]\nedge_types: [part_of]\nstatuses: [active]\n",
                                       encoding="utf-8")
    (store / "nodes" / "n.yaml").write_text(
        "- {id: repo-eng, type: Repo, status: active}\n"
        "- {id: doc-a, type: Doc, status: active, repo: eng, anchor: 'docs/a.md#a'}\n", encoding="utf-8")
    (store / "edges.yaml").write_text("[]", encoding="utf-8")
    (eng / "docs").mkdir(parents=True)
    (eng / "docs" / "a.md").write_text("# a\n", encoding="utf-8")
    base = ["--store", str(store), "--repo-root", str(tmp_path)]
    assert main([*base, "check", "--repo-path", f"eng={eng}"]) == 0
    assert "not checked" not in capsys.readouterr().out
    assert main([*base, "check"]) == 0   # no checkout given: not checked, said
    assert "1 anchor(s) of repo 'eng' not checked" in capsys.readouterr().out
    (eng / "docs" / "a.md").unlink()
    assert main([*base, "check", "--repo-path", f"eng={eng}"]) == 1
    assert "doc-a: anchor file missing: docs/a.md (repo eng)" in capsys.readouterr().err
    with pytest.raises(SystemExit) as exc:
        main([*base, "check", "--repo-path", "eng"])
    assert exc.value.code == 2 and "NAME=PATH" in capsys.readouterr().err


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


_LOG_SCHEMA = "node_types: [ADR, WorkItem]\nedge_types: [decided_by]\nstatuses: [active, todo]\n"


def _two_logs(tmp_path):
    """A repo whose notes/decisions.md is another store's, and the log lab/decisions.md of the store lab/graph."""
    repo = tmp_path / "repo"
    store = repo / "lab" / "graph"
    (store / "nodes").mkdir(parents=True)
    (store / "schema.yaml").write_text(_LOG_SCHEMA, encoding="utf-8")
    (store / "edges.yaml").write_text("", encoding="utf-8")
    (repo / "notes").mkdir()
    (repo / "notes" / "decisions.md").write_text("## 2026-06-10 — Not this store's\n\nbody\n", encoding="utf-8")
    (repo / "lab" / "decisions.md").write_text("## 2026-06-11 — The lab's\n\nbody\n", encoding="utf-8")
    return repo, ["--store", str(store), "--repo-root", str(repo)]


def test_cli_sync_and_check_cover_the_decision_logs_given(tmp_path, capsys):
    repo, args = _two_logs(tmp_path)
    assert main(args + ["--decisions", "lab/decisions.md", "sync", "--write"]) == 0
    gen = (repo / "lab" / "graph" / "nodes" / "_generated_decisions.yaml").read_text(encoding="utf-8")
    assert 'anchor: "lab/decisions.md#2026-06-11-the-lab-s"' in gen and "not-this-store" not in gen
    capsys.readouterr()
    assert main(args + ["--decisions", "lab/decisions.md", "check"]) == 0
    assert "graph-check OK" in capsys.readouterr().out
    assert main(args + ["check"]) == 1  # the defaults read notes/decisions.md, which this store does not cover
    assert "notes/decisions.md: 2026-06-10 has 1 heading(s) but 0 SDR/ADR node(s)" in capsys.readouterr().err


def test_cli_no_decisions_covers_no_log_and_refuses_decisions_too(tmp_path, capsys):
    repo, args = _two_logs(tmp_path)
    assert main(args + ["--no-decisions", "sync", "--write"]) == 0
    assert not (repo / "lab" / "graph" / "nodes" / "_generated_decisions.yaml").exists()
    assert main(args + ["--no-decisions", "check"]) == 0
    with pytest.raises(SystemExit) as exc:
        main(args + ["--no-decisions", "--decisions", "lab/decisions.md", "check"])
    assert exc.value.code == 2
    capsys.readouterr()
    assert main(args + ["--decisions", str(tmp_path / "elsewhere.md"), "check"]) == 2
    err = capsys.readouterr().err
    assert "--decisions" in err and "not inside --repo-root" in err
    assert main(args + ["--decisions", str(repo / "lab" / "decisions.md"), "sync", "--write"]) == 0
    gen = (repo / "lab" / "graph" / "nodes" / "_generated_decisions.yaml").read_text(encoding="utf-8")
    assert 'anchor: "lab/decisions.md#2026-06-11-the-lab-s"' in gen  # a path inside the root is made relative


def test_cli_sync_empties_the_generated_decisions_once_no_log_derives_them(tmp_path):
    repo, args = _two_logs(tmp_path)
    assert main(args + ["sync", "--write"]) == 0  # the defaults: notes/decisions.md, not this store's
    gen = repo / "lab" / "graph" / "nodes" / "_generated_decisions.yaml"
    assert "not-this-store" in gen.read_text(encoding="utf-8")
    assert main(args + ["--no-decisions", "sync", "--write"]) == 0
    assert "adr-" not in gen.read_text(encoding="utf-8")  # derived from the logs, in git: none left is authoritative
    assert main(args + ["--no-decisions", "check"]) == 0
