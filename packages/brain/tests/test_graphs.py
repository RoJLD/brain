"""wi-brain-graph-registry: ``brain graphs`` lists every graph layer and external graph of a project, or of every
project, at zero token and writing nothing (brain.graphs; docs/graphs.md)."""

import json
import os
from pathlib import Path

import pytest

from brain import cbm, cli, codeindex, docgraph, graphs

from conftest import run_git

SCHEMA = ("node_types: [ADR, WorkItem, Milestone, Spec, Lesson, Gadget]\n"
          "edge_types: [decided_by, part_of, depends_on, specified_by, learned_from, wires]\n"
          "statuses: [active, todo, done, pending, open]\n")


def _store(root: Path, *, nodes: dict, edges: dict | None = None, schema: str = SCHEMA) -> Path:
    s = root / "notes" / "graph"
    (s / "nodes").mkdir(parents=True)
    (s / "edges").mkdir()
    (s / "schema.yaml").write_text(schema, encoding="utf-8")
    (s / "edges.yaml").write_text("", encoding="utf-8")
    for name, text in nodes.items():
        (s / "nodes" / name).write_text(text, encoding="utf-8")
    for name, text in (edges or {}).items():
        (s / "edges" / name).write_text(text, encoding="utf-8")
    return s


def _commit(root: Path) -> None:
    run_git(root, "init", "-q", "-b", "main")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-q", "-m", "store")


LAB_NODES = {
    "work.yaml": "- {id: wi-a, type: WorkItem, status: todo, title: A}\n"
                 "- {id: wi-b, type: WorkItem, status: done, title: B}\n"
                 "- {id: ms-a, type: Milestone, status: pending, title: M}\n",
    "_generated_decisions.yaml": "- {id: adr-2026-01-01-x, type: ADR, status: active, title: X}\n",
    "local.yaml": "- {id: gadget-1, type: Gadget, status: active, title: G}\n",
}
LAB_EDGES = {"work.yaml": "- {from: wi-a, to: ms-a, type: part_of}\n- {from: wi-a, to: adr-2026-01-01-x, "
                          "type: decided_by}\n- {from: gadget-1, to: wi-a, type: wires}\n"}
OTHER_NODES = {"lessons.yaml": "- {id: les-1, type: Lesson, status: open, title: L}\n"
                               "- {id: les-2, type: Lesson, status: open, title: L2}\n"}


@pytest.fixture
def two(tmp_path, monkeypatch):
    """Two projects, each its own store in its own repo, and a project the brain only reads."""
    lab, other = tmp_path / "lab", tmp_path / "other"
    _store(lab, nodes=LAB_NODES, edges=LAB_EDGES)
    (lab / "notes" / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    _store(other, nodes=OTHER_NODES)
    _commit(lab)
    _commit(other)
    reg = tmp_path / "reg" / "projects.yaml"
    reg.parent.mkdir()
    stacks = "{web: {start: x, health: {cmd: x}}}"
    reg.write_text(f"lab: {{root: {lab.as_posix()}, title: The lab, stacks: {stacks}}}\n"
                   f"other: {{root: {other.as_posix()}}}\n"
                   "upstream: {title: a project the brain reads, access: read}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    return lab, other


def _json(capsys, argv) -> dict:
    capsys.readouterr()
    assert cli.main(argv) == 0
    return json.loads(capsys.readouterr().out)


def _layers(entry: dict) -> dict:
    return {la["name"]: la for la in entry["stores"][0]["layers"]}


def test_one_projects_counts_never_reach_the_other(two, capsys):
    lab = _json(capsys, ["--project", "lab", "graphs", "--json"])
    other = _json(capsys, ["graphs", "--json", "--project", "other"])   # the parent's flag after the subcommand
    assert [p["name"] for p in lab["projects"]] == ["lab"] and [p["name"] for p in other["projects"]] == ["other"]
    assert lab["projects"][0]["stores"][0]["nodes"] == 5 and other["projects"][0]["stores"][0]["nodes"] == 2
    assert "lessons" not in _layers(lab["projects"][0]) and list(_layers(other["projects"][0])) == ["lessons"]
    assert lab["v"] == 1 and lab["scope"] == "project"


def test_layers_by_the_stores_own_mapping_then_the_catalogue(two, capsys):
    lab = _layers(_json(capsys, ["--project", "lab", "graphs", "--json"])["projects"][0])
    assert set(lab) == {"work", "decisions", None}
    work, dec, none = lab["work"], lab["decisions"], lab[None]
    assert work["types"] == {"Milestone": 1, "WorkItem": 2} and work["nodes"] == 3 and work["catalogue"]
    assert work["mode"] == "written" and work["generator"] == ""
    assert dec["mode"] == "mixed"   # its ADR generated, its decided_by edge written in edges/work.yaml
    assert dec["generator"].startswith("research_graph sync") and dec["edges"] == {"decided_by": 1}
    assert work["edges"] == {"part_of": 1}
    assert none["types"] == {"Gadget": 1} and none["edges"] == {"wires": 1} and not none["catalogue"]
    assert work["version"] is None and work["catalogue_version"] == 1    # not recorded by templates:
    assert "research_graph items" in work["query"] and work["impact"] == ["research_graph impact <id>"]
    assert "brain next" in work["read_by"]


def test_the_schema_names_the_layer_and_its_recorded_version(tmp_path, monkeypatch, capsys):
    root = tmp_path / "p"
    _store(root, schema=SCHEMA + "layers:\n  work: [WorkItem, Milestone, Spec, Lesson]\n"
                                 "templates:\n  - {layer: work, version: 1}\n",
           nodes={"x.yaml": "- {id: les-1, type: Lesson, status: open, title: L}\n"})
    reg = tmp_path / "projects.yaml"
    reg.write_text(f"p: {{root: {root.as_posix()}}}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    store = _json(capsys, ["--project", "p", "graphs", "--json"])["projects"][0]["stores"][0]
    assert [la["name"] for la in store["layers"]] == ["work"] and store["layers"][0]["version"] == 1
    assert store["layers"][0]["types"] == {"Lesson": 1}
    assert store["layers"][0]["freshness"] is None          # not a git checkout
    planned = {p["name"]: p for p in store["planned"]}
    assert "work" not in planned and "lessons" in planned
    store_path = (root / "notes" / "graph").resolve().as_posix()
    assert planned["lessons"]["add"] == f"research_graph --store {store_path} layers add lessons"   # runs anywhere
    over = graphs.store_entry(root / "notes" / "graph", root, read_only=True)
    assert over["planned"] == []                             # nothing is proposed for another repo's store


def test_an_edge_type_several_layers_declare_counts_in_its_ends_layer():
    from research_graph import layers
    cat = layers.catalogue()
    shared = next(et for et, names in graphs._edge_layers(cat).items() if len(names) > 1)
    names = graphs._edge_layers(cat)[shared]
    tally = graphs._Tally({}, cat, {})
    tally.found = {n: {} for n in names}
    assert tally.edge_layer(shared, names[-1], None) == names[-1]      # its source's layer declares it
    assert tally.edge_layer(shared, "elsewhere", names[-1]) == names[-1]  # else its target's
    assert tally.edge_layer("an-uncatalogued-type", "work", None) == "work"   # never the no-layer bucket
    tally.found[None] = {}
    assert tally.edge_layer("an-uncatalogued-type", "work", None) == "work"


def test_odd_values_never_stop_the_json(tmp_path, monkeypatch, capsys):
    root = tmp_path / "p"
    _store(root, schema=SCHEMA + "templates:\n  - {layer: work, version: 2026-01-01}\n",
           nodes={"x.yaml": "- {id: wi-1, type: WorkItem, status: todo, title: W}\n"})
    (root / "docgraph").mkdir()
    (root / "docgraph" / "odd.json").write_text(json.dumps({"schema": docgraph.ID, "nodes": 5, "edges": True}),
                                                encoding="utf-8")
    reg = tmp_path / "projects.yaml"
    reg.write_text(f"p: {{root: {root.as_posix()}}}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    p = _json(capsys, ["--project", "p", "graphs", "--json"])["projects"][0]
    assert p["stores"][0]["layers"][0]["version"] == "2026-01-01"
    assert [(d["nodes"], d["edges"], d["ok"]) for d in p["docgraph"]] == [(0, 0, False)]


def test_freshness_is_the_last_commit_and_says_uncommitted_changes(two, capsys):
    lab, _ = two
    sha = run_git(lab, "rev-parse", "--short", "HEAD").strip()
    layers = _layers(_json(capsys, ["--project", "lab", "graphs", "--json"])["projects"][0])
    assert layers["work"]["freshness"]["commit"] == sha and not layers["work"]["freshness"]["uncommitted"]
    more = "- {id: wi-c, type: WorkItem, status: todo, title: C}\n"
    (lab / "notes" / "graph" / "nodes" / "work.yaml").write_text(LAB_NODES["work.yaml"] + more, encoding="utf-8")
    layers = _layers(_json(capsys, ["--project", "lab", "graphs", "--json"])["projects"][0])
    assert layers["work"]["freshness"]["uncommitted"] and layers["work"]["nodes"] == 4
    assert not layers["decisions"]["freshness"]["uncommitted"]   # its files are untouched
    (lab / "notes" / "graph" / "nodes" / "new.yaml").write_text("- {id: wi-d, type: WorkItem, status: todo, "
                                                                 "title: D}\n", encoding="utf-8")
    layers = _layers(_json(capsys, ["--project", "lab", "graphs", "--json"])["projects"][0])
    assert "nodes/new.yaml" in layers["work"]["files"] and layers["work"]["freshness"]["uncommitted"]
    run_git(lab, "mv", "notes/decisions.md", "notes/log.md")   # a staged rename: both of its paths changed
    graphs._clear()
    assert {"notes/log.md", "notes/decisions.md"} <= graphs._dirty(graphs._top(str(lab))[0])
    src = {s["name"]: s for s in _json(capsys, ["--project", "lab", "graphs", "--json"])["projects"][0]["sources"]}
    assert not src["decisions"]["exists"]

def test_a_malformed_file_or_a_folder_without_a_store_never_stops_the_list(two, capsys):
    lab, _ = two
    (lab / "notes" / "graph" / "nodes" / "bad.yaml").write_text("- {id: [unclosed\n", encoding="utf-8")
    entry = graphs.store_entry(lab / "notes" / "graph", lab)
    assert entry["nodes"] == 5 and entry["error"] == "left out, not parsed: nodes/bad.yaml"
    (lab / "notes" / "graph" / "nodes" / "bad.yaml").unlink()
    (lab / "notes" / "graph" / "schema.yaml").write_text("node_types: [\n", encoding="utf-8")
    assert graphs.store_entry(lab / "notes" / "graph", lab)["error"].startswith("schema.yaml does not parse")
    assert "not a graph store" in graphs.store_entry(lab / "nowhere", lab)["error"]


def test_sources_beside_the_graph(two, capsys):
    p = _json(capsys, ["--project", "lab", "graphs", "--json"])["projects"][0]
    src = {s["name"]: s for s in p["sources"]}
    assert src["decisions"]["exists"] and src["decisions"]["files"] == 1 and src["decisions"]["kind"] == "files"
    assert src["decisions"]["paths"] == ["notes/decisions.md"] and src["decisions"]["freshness"]["commit"]
    assert not src["journals"]["exists"]                     # the default journal, never written
    assert src["stacks"]["kind"] == "inline" and src["stacks"]["paths"] == []
    assert "brain up" in src["stacks"]["read_by"]


def test_docgraph_documents_and_the_read_projects_pinned_copy(two, capsys):
    lab, _ = two
    folder = lab / "docgraph"
    folder.mkdir()
    node = {"id": "item:1", "type": "item", "title": "x", "source": {"path": "docs/x.md"}}
    doc = {"schema": docgraph.ID, "generated": {"at": "2026-01-01T00:00:00Z", "by": "t 0.1"}, "nodes": [node],
           "edges": [], "checks": []}
    (folder / "notes.json").write_text(json.dumps(doc), encoding="utf-8")
    (folder / "upstream.json").write_text(json.dumps({**doc, "pinned": {"ref": "abc1234def", "file": "g.json",
                                                                        "at": "2026-01-02"}}), encoding="utf-8")
    (folder / "broken.json").write_text("{", encoding="utf-8")
    one = _json(capsys, ["--project", "lab", "graphs", "--json"])["projects"][0]
    rows = {d["name"]: d for d in one["docgraph"]}
    assert set(rows) == {"notes", "broken", "upstream"}      # without --all the brain's documents stay together
    assert rows["notes"]["ok"] and rows["notes"]["nodes"] == 1 and rows["notes"]["kind"] == "federated"
    assert not rows["broken"]["ok"] and "not a JSON document" in rows["broken"]["error"]
    every = _json(capsys, ["--root", str(lab), "graphs", "--all", "--json"])
    by = {p["name"]: p for p in every["projects"]}
    assert every["scope"] == "all" and set(by) == {"lab", "other", "upstream"}
    assert {d["name"] for d in by["lab"]["docgraph"]} == {"notes", "broken"}
    up = by["upstream"]
    assert up["access"] == "read" and [d["ref"] for d in up["docgraph"]] == ["abc1234def"] and up["stores"] == []


def _no_service(*a, **k):
    raise AssertionError("brain graphs called a service")


def test_code_index_rows_from_the_records_and_git_alone(two, capsys, monkeypatch):
    lab, other = two
    reg = Path(os.environ["BRAIN_PROJECTS"])
    reg.write_text(reg.read_text(encoding="utf-8").replace("title: The lab,", f"title: The lab, code_index: "
                                                                               f"[{other.as_posix()}],"),
                   encoding="utf-8")
    p = _json(capsys, ["--project", "lab", "graphs", "--json"])["projects"][0]
    assert [(c["backend"], c["state"]) for c in p["code_index"]] == [("", "ERROR")]   # no backend on this machine
    assert "codebase-memory-mcp is not installed" in p["code_index"][0]["why"]
    monkeypatch.setattr(cbm, "installed", lambda: True)
    monkeypatch.setattr(codeindex, "_http", _no_service)    # GitNexus is never asked
    sha = run_git(other, "rev-parse", "HEAD").strip()
    codeindex._save("other", {"sha": sha, "indexed_at": "2026-01-01T00:00:00Z"})
    p = _json(capsys, ["--project", "lab", "graphs", "--json"])["projects"][0]
    rows = {c["backend"]: c for c in p["code_index"]}
    assert rows["gitnexus"]["state"] == "OK" and rows["gitnexus"]["repo"] == "other"
    assert rows["cbm"]["state"] == "NOT INDEXED" and "xerj" not in rows
    assert rows["gitnexus"]["kind"] == "federated" and "brain code-map" in rows["gitnexus"]["read_by"]
    (other / "f.txt").write_text("x", encoding="utf-8")
    run_git(other, "add", "-A")
    run_git(other, "commit", "-q", "-m", "more")
    p = _json(capsys, ["--project", "lab", "graphs", "--json"])["projects"][0]
    assert {c["backend"]: c["state"] for c in p["code_index"]}["gitnexus"] == "STALE"
    other_p = _json(capsys, ["--project", "other", "graphs", "--json"])["projects"][0]
    assert other_p["code_index"] == []                       # the repo is lab's declaration, not other's


def test_the_json_keys_are_the_contract(two, capsys):
    reg = _json(capsys, ["--project", "lab", "graphs", "--json"])
    assert set(reg) == {"v", "scope", "projects"}
    p = reg["projects"][0]
    assert set(p) == {"name", "title", "root", "access", "found", "stores", "code_index", "docgraph", "sources"}
    s = p["stores"][0]
    assert set(s) == {"path", "kind", "read_only", "error", "nodes", "edges", "layers", "planned"}
    assert set(s["layers"][0]) == {"name", "catalogue", "version", "catalogue_version", "title", "mode",
                                   "generator", "files", "types", "nodes", "edges", "edge_count", "freshness",
                                   "query", "impact", "read_by"}
    assert set(s["layers"][0]["freshness"]) == {"commit", "day", "uncommitted"}
    assert set(p["sources"][0]) == {"name", "kind", "paths", "exists", "files", "freshness", "read_by"}
    assert set(s["planned"][0]) == {"name", "catalogue_version", "title", "add"}


def test_the_text_and_the_flags(two, capsys):
    capsys.readouterr()
    assert cli.main(["--project", "lab", "graphs"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("lab: The lab\n  store notes/graph: 5 node(s), 3 edge(s)\n")
    assert "    work (catalogue v1, not recorded): written; Milestone 1, WorkItem 2; 1 edge(s); " in out
    assert "    (no layer) (the store's own): written; Gadget 1; 1 edge(s); " in out
    assert "  source decisions: notes/decisions.md (1 file(s), " in out
    with pytest.raises(SystemExit, match="--project or --all"):
        cli.main(["--project", "lab", "graphs", "--all"])


def test_the_text_keeps_each_value_on_its_line():
    title = 'two\nlines, "quoted" 100% $HOME &amp;'
    reg = {"v": 1, "scope": "project", "projects": [
        {"name": "x", "title": title, "root": "/x", "access": "write", "found": True, "stores": [], "docgraph": [],
         "code_index": [{"repo": "r", "backend": "cbm", "state": "ERROR", "why": "a\nb"}], "sources": []}]}
    assert graphs.lines(reg) == ['x: two lines, "quoted" 100% $HOME &amp;', "  code index r (cbm): ERROR, a b"]
    assert json.loads(json.dumps(reg))["projects"][0]["title"] == title     # the JSON keeps it as it is


def test_it_writes_nothing(two, capsys):
    lab, _ = two
    before = run_git(lab, "status", "--porcelain", "--untracked-files=all")
    assert cli.main(["--root", str(lab), "graphs", "--all"]) == 0
    assert run_git(lab, "status", "--porcelain", "--untracked-files=all") == before
