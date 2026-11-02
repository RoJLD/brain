"""research_graph init: a new store from the package's templates, empty or with examples, that passes check at once;
never overwriting a store, an ADR log or a spec."""

from __future__ import annotations

import yaml

from research_graph import query
from research_graph.cli import main
from research_graph.init import TEMPLATES
from research_graph.loader import load_store


def _args(root):
    return ["--store", str(root / "notes" / "graph"), "--repo-root", str(root)]


def test_templates_ship_with_the_package():
    names = {p.name for p in TEMPLATES.iterdir()}
    assert {"schema.yaml", "edges.yaml", "work.yaml", "work_edges.yaml", "decisions.md", "example_work.yaml",
            "example_work_edges.yaml", "example_decisions.md", "example_spec.md"} <= names


def test_init_empty_store_passes_check(tmp_path, capsys):
    root = tmp_path / "me"
    assert main(_args(root) + ["init"]) == 0
    store = root / "notes" / "graph"
    assert "owner" not in yaml.safe_load((store / "schema.yaml").read_text(encoding="utf-8"))
    assert load_store(store).number_of_nodes() == 0
    assert (root / "notes" / "kanban_graph.md").exists() and (root / "notes" / "roadmap_graph.md").exists()
    capsys.readouterr()
    assert main(_args(root) + ["check"]) == 0
    assert "graph-check OK" in capsys.readouterr().out


def test_init_with_examples_and_an_owner(tmp_path, capsys):
    root = tmp_path / "team"
    assert main(_args(root) + ["init", "--owner", "Data team", "--examples"]) == 0
    capsys.readouterr()
    assert main(_args(root) + ["check"]) == 0
    capsys.readouterr()
    s = query.load_source(root / "notes" / "graph")
    assert s.graph.graph["owner"] == "Data team"
    assert "adr-2026-01-01-keep-the-work-state-in-this-graph" in s.graph
    d = query.pending_decisions(s.graph, s.repo_root)
    assert [r["id"] for r in d["blocked_on_owner"]] == ["wi-needs-a-decision"]
    assert [q["label"] for x in d["spec_questions"] for q in x["questions"]] == ["1"]
    assert main(_args(root) + ["work-frontier"]) == 0
    assert capsys.readouterr().out.startswith("wi-first-step")


def test_init_never_overwrites(tmp_path, capsys):
    root = tmp_path / "repo"
    log = root / "notes" / "decisions.md"
    log.parent.mkdir(parents=True)
    log.write_text("# My decisions\n\n## 2026-02-01 — Mine\n\nContext: c.\n", encoding="utf-8")
    assert main(_args(root) + ["init", "--examples"]) == 0
    assert log.read_text(encoding="utf-8").startswith("# My decisions")  # kept, and no example ADR in it
    edges = (root / "notes" / "graph" / "edges" / "work.yaml").read_text(encoding="utf-8")
    assert "decided_by" not in edges.split("\n- ", 1)[1]
    capsys.readouterr()
    assert main(_args(root) + ["check"]) == 0
    assert main(_args(root) + ["init"]) == 1
    assert "already a store" in capsys.readouterr().err
