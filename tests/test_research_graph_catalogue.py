"""research_graph layers: graph templates as layers (spec-brain-graph-templates, GT-1 and GT-5). The catalogue's layer
files, a schema composed from them (the brain's base and research_graph init's default reproduced, so no existing
store's schema moves), the edge endpoints research_graph check verifies, and adding a layer to a store by a plan that
keeps the schema's own text."""

from __future__ import annotations

import shutil
from importlib.resources import files
from pathlib import Path

import pytest
import yaml

from research_graph import layers
from research_graph.cli import main
from research_graph.code_layer import structure_errors
from research_graph.loader import load_store
from research_graph.schema import load_schema, parse_schema
from research_graph.validate import check_wiring, endpoint_errors

ROOT = Path(__file__).resolve().parents[1]
BRAIN_DEFAULT = ROOT / "packages" / "brain" / "src" / "brain" / "templates" / "schemas" / "default.yaml"
RG_DEFAULT = files("research_graph") / "templates" / "schema.yaml"
SHAPE = ("node_types", "edge_types", "statuses", "levels", "layers", "status_by_type", "required_props")
# the 13 layers the spec's catalogue proved in real stores (§3.3), and lessons, which the brain's base already holds
CATALOGUE = {"work", "decisions", "records", "ideas", "research", "data", "code", "docs_tests", "features",
             "operations", "fleet", "rules", "delivery", "lessons"}


def _template(text: str) -> dict:
    return yaml.safe_load(text.replace("{owner_line}", ""))


def _store(root: Path, schema_text: str, nodes=(), edges=()) -> Path:
    store = root / "graph"
    (store / "nodes").mkdir(parents=True)
    (store / "schema.yaml").write_text(schema_text, encoding="utf-8")
    (store / "nodes" / "n.yaml").write_text(yaml.safe_dump(list(nodes)), encoding="utf-8")
    (store / "edges.yaml").write_text(yaml.safe_dump(list(edges)), encoding="utf-8")
    return store


# --- the catalogue -------------------------------------------------------------------------------------------------

def test_the_catalogue_holds_the_proven_layers_each_type_in_one():
    cat = layers.catalogue()
    assert set(cat) == CATALOGUE
    seen: dict[str, str] = {}
    for la in cat.values():
        assert la.version >= 1 and la.mode in layers.MODES and la.title
        assert la.data.get("projection", {}).get("gitnexus") == "research-graph", la.name
        for t in la.node_types:
            assert t not in seen, (t, seen.get(t), la.name)
            seen[t] = la.name
            assert la.node_types[t], f"{la.name}.{t}: a line that says what it is"


@pytest.mark.parametrize("name", sorted(CATALOGUE))
def test_each_layer_s_examples_are_fictitious_and_pass_the_check(tmp_path, name):
    """The examples of a layer (with those of the work and decisions layers they point at) load against the layers'
    composition and pass its blocking checks, endpoints included; every id says it is an example."""
    resolved = layers.resolve([name, "work", "decisions"])
    nodes = [n for la in resolved for n in (la.data.get("examples") or {}).get("nodes") or []]
    edges = [e for la in resolved for e in (la.data.get("examples") or {}).get("edges") or []]
    own = layers.catalogue()[name].data["examples"]
    assert own["nodes"], f"layer {name}: no example"
    assert all("example" in str(n["id"]) for n in nodes)
    data = layers.compose_layers(resolved)
    store = _store(tmp_path, layers.render(data), nodes, edges)
    graph = load_store(store)
    schema = parse_schema(data)
    assert endpoint_errors(graph, schema) + structure_errors(graph) + check_wiring(graph, tmp_path) == []


def test_a_layer_file_is_checked():
    good = {"name": "lab", "version": 1, "title": "t", "mode": "written", "node_types": {"Bench": "a bench"},
            "statuses": ["active"]}
    assert layers.parse_layer(good).node_types == {"Bench": "a bench"}
    for bad, says in (({**good, "mode": "typed"}, "mode is one of"), ({**good, "colour": 1}, "unknown key"),
                      ({**good, "version": 0}, "version is a whole number"),
                      ({**good, "status_by_type": {"Bench": ["gone"]}}, "not in statuses"),
                      ({**good, "edge_types": {"sits_on": [{"from": ["Bench"]}]}}, "from and to"),
                      ({k: v for k, v in good.items() if k != "statuses"}, "misses statuses")):
        with pytest.raises(layers.LayerError, match=says):
            layers.parse_layer(bad, "lab.yaml")


# --- composition ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("names, template", [(["work", "decisions", "records", "lessons"], BRAIN_DEFAULT),
                                             (["work", "decisions", "lessons"], RG_DEFAULT)])
def test_the_base_schemas_are_compositions_of_the_catalogue(names, template):
    """brain init's default schema and research_graph init's are the catalogue's layers composed: a layer file that
    drifts from them fails here, and the stores they started never see their schema move."""
    data = layers.compose(names)
    want = _template(template.read_text(encoding="utf-8"))
    assert {k: data.get(k) for k in SHAPE} == {k: want.get(k) for k in SHAPE}


def test_compose_adds_what_a_layer_requires_and_records_the_versions():
    data = layers.compose(["research"], owner="Ada")
    assert [t["layer"] for t in data["templates"]] == ["work", "decisions", "research"]
    assert data["owner"] == "Ada" and data["levels"] == ["L0", "L1", "L2"]
    assert data["endpoints"]["tests"] == [{"from": ["Experiment"], "to": ["Hypothesis"]}]
    assert {"from": "*", "to": ["ADR"]} in data["endpoints"]["decided_by"]
    assert {"from": "*", "to": ["SDR"]} in data["endpoints"]["decided_by"]   # two layers share an edge name


def test_a_type_in_two_layers_and_an_unknown_layer_are_refused():
    twin = layers.parse_layer({"name": "lab", "version": 1, "title": "t", "mode": "written",
                               "node_types": {"WorkItem": "again"}, "statuses": ["todo"]})
    with pytest.raises(layers.LayerError, match="type WorkItem is in layers work and lab"):
        layers.compose(["work", "lab"], extra={"lab": twin})
    with pytest.raises(layers.LayerError, match="not in the catalogue"):
        layers.compose(["astrology"])
    with pytest.raises(layers.LayerError, match="a name of the catalogue"):
        layers.compose(["work"], extra={"work": twin})


def test_the_rendered_schema_reads_back_and_stays_in_width():
    names = sorted(CATALOGUE)
    data = layers.compose(names, owner="Ada")
    text = layers.render(data, layers.header_for(layers.resolve(names)))
    assert yaml.safe_load(text) == data
    assert max(len(line) for line in text.splitlines()) <= layers.WIDTH
    assert load_schema  # the loader takes it: parse_schema ran in compose


# --- the endpoints research_graph check verifies -----------------------------------------------------------------

def test_check_refuses_an_edge_outside_its_endpoints(tmp_path, capsys):
    data = layers.compose(["work", "decisions"])
    nodes = [{"id": "wi-a", "type": "WorkItem", "status": "todo", "title": "a"},
             {"id": "spec-a", "type": "Spec", "status": "active", "title": "s"}]
    store = _store(tmp_path, layers.render(data), nodes, [{"from": "spec-a", "to": "wi-a", "type": "part_of"},
                                                          {"from": "wi-a", "to": "spec-a", "type": "depends_on"}])
    assert main(["--store", str(store), "--repo-root", str(tmp_path), "--no-decisions", "check"]) == 1
    err = capsys.readouterr().err
    assert "edge spec-a->wi-a: part_of from Spec to WorkItem is outside its endpoints" in err
    assert "depends_on" not in err   # an edge type without endpoints is not checked


def test_endpoints_are_optional_and_checked_for_shape():
    base = {"node_types": ["A"], "edge_types": ["e"], "statuses": ["s"]}
    assert parse_schema(base).endpoints == {} and parse_schema(base).templates == ()
    s = parse_schema({**base, "endpoints": {"e": {"from": "*", "to": ["A", "B"]}},
                      "templates": [{"layer": "work", "version": 1}]})
    assert s.endpoints == {"e": ((None, frozenset({"A", "B"})),)} and s.templates == (("work", 1),)
    for bad, says in (({"endpoints": {"x": {"from": "*", "to": "*"}}}, "unknown edge type"),
                      ({"endpoints": {"e": [{"from": "*"}]}}, "from and to"),
                      ({"templates": [{"layer": "work"}]}, "templates")):
        with pytest.raises(ValueError, match=says):
            parse_schema({**base, **bad})


# --- adding a layer: a plan, then its write ------------------------------------------------------------------------

def _init(root: Path, *extra: str) -> Path:
    assert main(["--store", str(root / "notes" / "graph"), "--repo-root", str(root), "init", *extra]) == 0
    return root / "notes" / "graph"


def test_adding_a_layer_keeps_the_schema_s_text_and_records_the_layers(tmp_path, capsys):
    store = _init(tmp_path / "me", "--owner", "Ada")
    before = (store / "schema.yaml").read_text(encoding="utf-8")
    capsys.readouterr()
    args = ["--store", str(store), "--repo-root", str(tmp_path / "me")]
    assert main(args + ["layers", "add", "research"]) == 0
    out = capsys.readouterr().out
    assert "add layer research v1 (written)" in out and "(plan only: --write writes it)" in out
    assert "already in the store without endpoints: left unchecked" in out   # decided_by, supersedes
    assert (store / "schema.yaml").read_text(encoding="utf-8") == before
    assert main(args + ["layers", "add", "research", "--write"]) == 0
    after = (store / "schema.yaml").read_text(encoding="utf-8")
    kept = [ln for ln in before.splitlines() if ln.startswith("#")]
    assert all(ln in after.splitlines() for ln in kept)   # the owner's comments stay
    data = yaml.safe_load(after)
    assert data["owner"] == "Ada"
    assert data["templates"] == [{"layer": n, "version": 1} for n in ("work", "decisions", "lessons", "research")]
    assert data["layers"]["research"] == list(layers.catalogue()["research"].node_types)
    assert "tests" in data["endpoints"] and "decided_by" not in data["endpoints"]
    capsys.readouterr()
    assert main(args + ["check"]) == 0
    assert main(args + ["layers", "add", "research"]) == 0
    assert "layer research: already in the store" in capsys.readouterr().out


def test_a_layer_whose_types_the_store_has_is_refused_and_nothing_written(tmp_path, capsys):
    store = _init(tmp_path / "me")
    shutil.copy(BRAIN_DEFAULT, store / "schema.yaml")
    text = (store / "schema.yaml").read_text(encoding="utf-8").replace("{owner_line}", "")
    text = text.replace("  records: [DDR, Session, Action]\n", "").replace("  decisions: [ADR]\n",
                                                                           "  decisions: [ADR, DDR, Session, Action]\n")
    (store / "schema.yaml").write_text(text, encoding="utf-8")
    plan = layers.add_plan(store, ["records"])
    assert plan.problems and "type(s) DDR, Session, Action already in the store (layer decisions)" in plan.problems[0]
    with pytest.raises(layers.LayerError):
        layers.write(plan)
    assert (store / "schema.yaml").read_text(encoding="utf-8") == text


BLOCK = """# a store of the owner's, in block style, with comments
owner: Ada
node_types:
  - WorkItem   # a task
  - Milestone
  - Spec
edge_types:
  - depends_on  # a task waits on a task
  - part_of
  - specified_by
statuses: [todo, doing, blocked, done, dropped, pending, reached, proposed, active, superseded]
layers:
  work: [WorkItem, Milestone, Spec]
# the statuses of each type
status_by_type:
  WorkItem: [todo, doing, blocked, done, dropped]   # the board's columns
  Milestone: [pending, reached, dropped]
  Spec: [proposed, active, superseded]
"""


def test_a_block_style_schema_takes_the_additions_in_its_own_style(tmp_path):
    store = _store(tmp_path, BLOCK)
    plan = layers.add_plan(store, ["features", "code"])
    assert plan.problems == [] and plan.added == ["features", "code"]
    layers.write(plan)
    text = (store / "schema.yaml").read_text(encoding="utf-8")
    assert "  - WorkItem   # a task\n" in text and "  - Feature\n" in text and "  - implemented_by\n" in text
    assert "# the statuses of each type\nstatus_by_type:" in text
    data = yaml.safe_load(text)
    assert data["templates"] == [{"layer": "work", "version": 1}, {"layer": "features", "version": 1},
                                 {"layer": "code", "version": 1}]
    assert data["status_by_type"]["Feature"] == ["have", "partial", "planned", "no"]
    assert data["endpoints"]["implemented_by"] == [{"from": "*", "to": ["CodeRef"]}]
    assert "part_of" not in data["endpoints"]   # already there, unchecked: a layer never starts checking old edges


def test_a_long_flow_list_wraps_under_its_first_item():
    lines = ["node_types: [" + ", ".join(f"Type{i:02d}" for i in range(12)) + "]", "statuses: [a]"]
    layers._append_list(lines, "node_types", [f"Added{i:02d}" for i in range(20)])
    assert max(len(ln) for ln in lines) <= layers.WIDTH
    data = yaml.safe_load("\n".join(lines))
    assert data["node_types"][-1] == "Added19" and len(data["node_types"]) == 32 and data["statuses"] == ["a"]
    assert lines[1].startswith(" " * len("node_types: ["))


# --- the command ---------------------------------------------------------------------------------------------------

def test_the_command_lists_shows_composes_and_proposes(tmp_path, capsys):
    store = _init(tmp_path / "me")
    args = ["--store", str(store), "--repo-root", str(tmp_path / "me")]
    capsys.readouterr()
    assert main(args + ["layers"]) == 0
    out = capsys.readouterr().out
    assert "* work" in out and "  research" in out and f"* in {store}" in out
    assert main(args + ["layers", "show", "research"]) == 0
    out = capsys.readouterr().out
    assert "research v1 (written)" in out and "-tests-> [Experiment] -> [Hypothesis]" in out
    assert main(["layers", "compose", "research", "--owner", "Ada"]) == 0
    composed = yaml.safe_load(capsys.readouterr().out)
    assert composed["owner"] == "Ada" and "WorkItem" in composed["node_types"]
    assert main(args + ["layers", "propose", "--typology", "research", "--stage", "explore"]) == 0
    out = capsys.readouterr().out
    assert "ideas" in out and "research" in out and "layers add" in out and "operations" not in out
    assert main(args + ["layers", "show", "astrology"]) == 2
    assert "not in the catalogue" in capsys.readouterr().err


def test_init_composes_its_schema_from_layers(tmp_path, capsys):
    store = _init(tmp_path / "lab", "--owner", "Ada", "--layers", "records,research", "--examples")
    data = yaml.safe_load((store / "schema.yaml").read_text(encoding="utf-8"))
    assert [t["layer"] for t in data["templates"]] == ["work", "decisions", "records", "research"]
    capsys.readouterr()
    assert main(["--store", str(store), "--repo-root", str(tmp_path / "lab"), "check"]) == 0
    assert main(["--store", str(tmp_path / "x" / "graph"), "--repo-root", str(tmp_path / "x"), "init", "--layers",
                 "code", "--examples"]) == 1
    assert "--examples needs the work and decisions layers" in capsys.readouterr().err
