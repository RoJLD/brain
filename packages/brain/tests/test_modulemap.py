"""The map of realisations (wi-brain-sigma-map, brain.modulemap): a registry entry's hand fields (wanted, capabilities,
depends_on, uses, ai, realized_by, map_review), brain modules --check's checks of them, the view's sections. Only an
entry that carries the map is concerned: a registry written before it is checked and rendered as before."""

import json
from datetime import date
from pathlib import Path

import pytest
from conftest import run_git
from test_modules import NODES, REGISTRY, _brain

from brain import cli, modulemap, modules, schema

FORMATS = Path(__file__).parent / "fixtures" / "formats" / "modules" / "v1"


def _lab(tmp_path, monkeypatch, registry: str, nodes: str = NODES):
    """A project lab (a git repo with notes/ committed) whose store keeps ``registry``, registered."""
    lab = tmp_path / "lab"
    store = _brain(lab, registry=registry, nodes=nodes)
    run_git(lab, "init", "-q")
    run_git(lab, "add", "-A")
    run_git(lab, "commit", "-q", "-m", "lab")
    reg = tmp_path / "projects.yaml"
    reg.write_text(f"lab:\n  root: {lab.as_posix()}\nshop:\n  title: a project read only\n  access: read\n",
                   encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    monkeypatch.setenv("BRAIN_ROOT", str(lab))
    return lab, store


def test_the_older_fixture_passes_and_a_registry_without_the_map_is_not_concerned(tmp_path, monkeypatch):
    lab, store = _lab(tmp_path, monkeypatch, FORMATS.joinpath("older.yaml").read_text(encoding="utf-8"))
    assert modulemap.problems(store, lab) == [] and modules.registry_problems(store, lab) == []
    assert [m["id"] for m in modulemap.data(modules.registry(store, lab))] == ["P2", "P12"]
    hand = _brain(tmp_path / "hand")
    assert modulemap.problems(hand) == [] and modulemap.warnings(hand) == []
    assert modulemap.view_lines(modules.registry(hand)) == []   # its view is what it was
    assert "## Realisations" not in modules.render(hand)


def test_check_refuses_what_the_map_gets_wrong(tmp_path, monkeypatch, capsys):
    reg = REGISTRY + """\
- {id: Q1, name: queue, brick: Q, phase: V1, status: tree, wanted: true, capabilities: [backlog, teleport],
   depends_on: [K1, Z9], uses: [K1], ai: maybe,
   realized_by: [{project: lab, kind: lab, state: running, paths: [notes/graph, src/absent.py]},
                 {project: nowhere, kind: product, state: shipped},
                 {project: shop, kind: app, state: built, paths: [any/path]}]}
- {id: Q2, name: wish, brick: Q, phase: V2, status: tree, wanted: true}
- {id: Q3, name: drop, brick: Q, phase: V2, status: tree, wanted: true, realized_by: [{project: lab, kind: lab,
   state: retired}]}
"""
    lab, store = _lab(tmp_path, monkeypatch, reg)
    assert modulemap.problems(store, lab) == [
        "Q1.ai: expected boolean, got str",
        "Q1.realized_by[1].state: 'shipped' not in ['planned', 'building', 'pr-open', 'partial', 'built', 'running', "
        "'retired']",
        "Q1: depends_on Z9 is not in modules.yaml",
        "Q1: depends_on K1 is also in uses",
        "Q1: capability teleport is not in tiers.yaml",
        "Q1: realized_by 1 (lab): path src/absent.py is not in lab at HEAD",
        "Q1: realized_by 2 (nowhere): project nowhere is not in the projects registry",
        "Q2: wanted, with no realisation and no open item that builds it",
        "Q3: wanted, with no realisation and no open item that builds it",   # a retired one does not count
    ]   # shop is read only: registered, no checkout here, its paths unchecked
    assert cli.main(["modules", "--check"]) == 1
    out = capsys.readouterr().out
    assert "Q2: wanted, with no realisation and no open item that builds it" in out


def test_an_open_item_of_a_store_that_reads_the_registry_counts_for_a_wanted_module(tmp_path, monkeypatch):
    from test_modules import _programme
    lab, lab_store, prog_store, _ = _programme(tmp_path, monkeypatch, "prog")
    with (prog_store / "modules.yaml").open("a", encoding="utf-8") as f:
        f.write("- {id: W1, name: wish, brick: W, phase: V2, status: tree, wanted: true}\n")
    assert modulemap.problems(prog_store, lab) == ["W1: wanted, with no realisation and no open item that builds it"]
    with (lab_store / "nodes" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write('- {id: wi-wish, type: WorkItem, status: todo, title: "Build it", props: {module: W1}}\n')
    assert modulemap.readers(prog_store, lab) == [prog_store, lab_store]
    assert modulemap.problems(prog_store, lab) == []
    assert modulemap.problems(lab_store, lab) == []   # the store that keeps the registry says it, once


def test_a_realisations_unknown_key_is_a_note_in_read_mode_an_error_in_strict(tmp_path, monkeypatch):
    lab, store = _lab(tmp_path, monkeypatch, FORMATS.joinpath("newer.yaml").read_text(encoding="utf-8"))
    assert modulemap.problems(store, lab) == [
        "P2.realized_by[0]: unknown field 'since'"]   # strict, as in CI (conftest)
    monkeypatch.setenv("BRAIN_STRICT", "0")
    assert modulemap.problems(store, lab) == []   # a newer brain's key, kept


def test_a_wanted_module_with_nothing_for_90_days_is_warned_never_failed(tmp_path, monkeypatch):
    reg = REGISTRY + ("- {id: Q4, name: sleepy, brick: Q, phase: V2, status: tree, wanted: true, since: 2026-01-01,\n"
                      "   realized_by: [{project: lab, kind: brain, state: planned}]}\n")
    lab, store = _lab(tmp_path, monkeypatch, reg)
    assert modulemap.warnings(store, lab, today=date(2026, 3, 31)) == []
    assert modulemap.warnings(store, lab, today=date(2026, 4, 1)) == [
        "Q4: wanted since 2026-01-01, no item done or open in 90 days: dormant, to put back to sleep"]
    assert modulemap.problems(store, lab) == []


def test_the_view_shows_the_realisations_the_gaps_and_what_is_left_to_classify(tmp_path, monkeypatch):
    lab, store = _lab(tmp_path, monkeypatch, FORMATS.joinpath("older.yaml").read_text(encoding="utf-8") + """\
- {id: L1, name: lab-only, brick: L, phase: MVP, status: tree, wanted: true, declared: [K1],
   realized_by: [{project: lab, kind: lab, state: running}]}
- {id: L2, name: wish, brick: L, phase: Later, status: tree, wanted: true}
""")
    text = modules.render(store, "notes/graph", lab)
    assert "4 module(s) carry the map, 1 proposed and waiting on the owner's review." in text
    assert "| P2 | kettle-core | yes | lab | lab | the kettle bench | running | lab | proposed |" in text
    assert "| P2 | kettle-core | yes | lab | brain | the brain's kettle view | built | brain | proposed |" in text
    assert "| P12 | kettle-meter | no | - | - | - | - | - | validated |" in text
    assert "- L1: a lab realisation, no target realisation (product, brain or app)" in text
    assert "- L1: product phase MVP, no product realisation" in text and "- L2: wanted, no realisation" in text
    assert "- P2: product phase MVP, no product realisation" in text   # P12 is proposed: not the product's yet
    assert "- L1: K1 (declared, counted soft until classified)" in text and "- P2:" not in text.split(
        "## Dependencies to classify")[1]   # P2 classified both
    assert text.index("## Gaps") < text.index("## Realisations") < text.index("## K1")
    got = json.loads(json.dumps(modules.data(store, lab), default=str))
    assert [m["id"] for m in got["map"]] == ["P2", "P12", "L1", "L2"]
    assert got["map_problems"] == ["L2: wanted, with no realisation and no open item that builds it"]


def test_the_schema_is_registered_implemented_and_a_new_format():
    assert "modules" in schema.SCHEMAS and schema.unsupported(schema.load("modules")) == []
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "release_check", Path(modules.__file__).parents[2] / "installer" / "release_check.py")
    rc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rc)
    assert rc.SCHEMAS["modules"] == (f"{rc.SRC}/schemas/modules.schema.json",)


@pytest.mark.parametrize("which", ["older", "newer"])
def test_the_format_fixtures_load_as_registries(which):
    entries = modules.graph.load_yaml(FORMATS.joinpath(f"{which}.yaml").read_text(encoding="utf-8"))
    assert entries and all(isinstance(m, dict) and m.get("id") for m in entries)
