"""Presets and personas (brain.presets, wi-brain-sigma-personas): personas.yaml beside a store's modules.yaml, its
checks by brain modules --check, and the two checks of brain modules --personas: each preset's set closed under the
map's hard dependencies (incomplete while a module's are unclassified), and a preset without AI pulling no AI module
nor a distribution that ships one. Invented presets of an invented platform only."""

import json
from pathlib import Path

import pytest
from test_modulemap import _lab
from test_modules import _brain

from brain import cli, presets, schema

FORMATS = Path(__file__).parent / "fixtures" / "formats" / "personas" / "v1"

# K: the tea room (its kettle product ships K1); P: the kettle (P2 needs K1, shipped by the product and the engine);
# M: the lamp (shipped by the engine only, a declared dependency unclassified); Q: the oracle (AI, shipped by the
# engine: the engine is an AI distribution); R: a rack the map has not seen.
REGISTRY = """\
- {id: K1, name: tea-room, brick: K, phase: MVP, status: tree, map_review: proposed,
   realized_by: [{project: lab, kind: product, state: built, ships_in: kettle}]}
- {id: K2, name: tea-cart, brick: K, phase: V1, status: tree, placement: set aside}
- {id: K3, name: tea-shop, brick: K, phase: V2, status: proposed}
- {id: P2, name: kettle-core, brick: P, phase: MVP, status: tree, depends_on: [K1], map_review: proposed,
   realized_by: [{project: lab, kind: product, state: built, ships_in: kettle},
                 {project: lab, kind: brain, state: built, ships_in: engine}]}
- {id: M4, name: lamp-post, brick: M, phase: V1, status: tree, declared: [P2], map_review: proposed,
   realized_by: [{project: lab, kind: brain, state: built, ships_in: engine},
                 {project: lab, kind: product, state: retired, ships_in: kettle}]}
- {id: Q1, name: oracle, brick: Q, phase: V1, status: tree, ai: true, map_review: proposed,
   realized_by: [{project: lab, kind: brain, state: built, ships_in: engine}]}
- {id: Q2, name: seer, brick: Q, phase: V2, status: tree}
- {id: R1, name: rack, brick: R, phase: V2, status: tree}
"""
NODES = "- {id: wi-tea, type: WorkItem, status: todo, title: Tea, props: {module: K1}}\n"
PERSONAS = """\
v: 1
source: [{ref: "the packaging document", date: 2026-10-23}]
imported: 2026-11-24
expand: {skip_placement: ["set aside"]}
personas:
  - {id: tea-drinker, name: The tea drinker, bricks: [K], distributions: [kettle], ai: false,
     optional: {bricks: [Q]}}
  - {id: brewer, name: The brewer, modules: [P2]}
  - {id: lamplighter, name: The lamplighter, bricks: [M], ai: false}
  - {id: sage, name: The sage, bricks: [Q], ai: true}
  - {id: monk, name: The monk, bricks: [K], distributions: [engine, tea-cloud], ai: false}
  - {id: racker, name: The racker, bricks: [R]}
  - {id: host, name: The host, bricks: [K], modules: [K3, P2]}
"""


def _store(tmp_path, personas: str | None = PERSONAS, registry: str = REGISTRY):
    store = _brain(tmp_path, registry=registry, nodes=NODES)
    if personas is not None:
        (store / presets.FILE).write_text(personas, encoding="utf-8")
    return store


def _by(found: list[dict]) -> dict[str, dict]:
    return {r["id"] + r["variant"]: r for r in found}


def test_each_preset_is_checked_closed_and_without_ai(tmp_path):
    store = _store(tmp_path)
    assert presets.problems(store) == []
    r = _by(presets.report(store))
    assert list(r) == ["tea-drinker", "tea-drinker+Q", "brewer", "lamplighter", "sage", "monk", "racker", "host"]
    # a brick gives its modules but a skipped placement (K2) and a proposed one (K3, the default skip_status)
    assert r["tea-drinker"]["modules"] == ["K1"]
    assert (r["tea-drinker"]["closure"], r["tea-drinker"]["no_ai"]) == ("closed", "ok")
    # the optional variant pulls the oracle: AI modules, Q1 shipped only by the engine, which ships AI; Q2 unshipped
    plus = r["tea-drinker+Q"]
    assert plus["modules"] == ["K1", "Q1", "Q2"] and plus["no_ai"] == "violated"
    assert plus["ai_modules"] == ["Q1"] and plus["only_ai"] == {"Q1": ["engine"]} and plus["unshipped"] == ["Q2"]
    assert plus["closure"] == "incomplete" and plus["unclassified"] == ["Q2"]   # Q2 carries no map
    # a hard dependency missing: open, and who needs it; the AI check does not run (ai not said)
    assert (r["brewer"]["closure"], r["brewer"]["missing"], r["brewer"]["no_ai"]) == ("open", {"K1": ["P2"]}, "-")
    # a declared dependency unclassified: incomplete, never closed; shipped by the AI distribution only: violated,
    # its retired realisation in the kettle not counted
    lamp = r["lamplighter"]
    assert (lamp["closure"], lamp["unclassified"], lamp["no_ai"]) == ("incomplete", ["M4"], "violated")
    assert lamp["only_ai"] == {"M4": ["engine"]} and lamp["ai_modules"] == []
    assert (r["sage"]["no_ai"], r["sage"]["closure"]) == ("-", "incomplete")   # it uses AI: not checked
    # listing the AI distribution is a violation; a distribution no realisation ships in is shown, never counted
    monk = r["monk"]
    assert monk["no_ai"] == "violated" and monk["ai_distributions"] == ["engine"]
    assert monk["unknown_distributions"] == ["tea-cloud"]
    assert (r["racker"]["closure"], r["racker"]["unclassified"]) == ("incomplete", ["R1"])
    # a module named alone is taken whatever its status (K3 proposed), and its hard dependency is held
    assert r["host"]["modules"] == ["K1", "K3", "P2"] and r["host"]["missing"] == {}
    assert r["host"]["closure"] == "incomplete" and r["host"]["unclassified"] == ["K3"]


def test_the_closure_follows_hard_dependencies_through_pulled_modules(tmp_path):
    chain = "".join(f"- {{id: C{i}, name: c{i}, brick: C, phase: V1, status: tree, map_review: proposed, "
                    f"depends_on: [C{i + 1}]}}\n" for i in range(1, 400)) + \
        "- {id: C400, name: c400, brick: C, phase: V1, status: tree, map_review: proposed}\n"
    store = _store(tmp_path, "v: 1\npersonas: [{id: one, name: One, modules: [C1], ai: false}]\n", chain)
    (r,) = presets.report(store)
    assert r["closure"] == "open" and len(r["missing"]) == 399 and r["missing"]["C400"] == ["C399"]
    assert r["no_ai"] == "ok" and r["unshipped"][:2] == ["C1", "C2"]   # 400 modules, no recursion error


def test_a_soft_dependency_is_never_pulled_and_a_classified_one_closes(tmp_path):
    reg = REGISTRY.replace("declared: [P2], map_review", "declared: [P2], uses: [P2], map_review")
    store = _store(tmp_path, "v: 1\npersonas: [{id: lamp, name: Lamp, bricks: [M]}]\n", reg)
    (r,) = presets.report(store)
    assert (r["closure"], r["missing"], r["unclassified"]) == ("closed", {}, [])


def test_check_refuses_what_the_file_gets_wrong(tmp_path):
    bad = """\
v: 1
imported: 2026-11-01
source: [{ref: "the packaging document", date: 2026-11-20}, {ref: other, date: someday}]
expand: {skip_status: proposed}
personas:
  - {id: tea, name: Tea, bricks: [K, Z], modules: [Z9], optional: {modules: [Y1]}, ai: maybe}
  - {id: tea, name: Again, kind: guru}
  - {id: "no id!", name: Odd}
  - {name: Nameless}
"""
    assert presets.problems(_store(tmp_path, bad)) == [
        "personas.yaml.expand.skip_status: expected array, got str",
        "personas.yaml.personas[0].ai: expected boolean, got str",
        "personas.yaml.personas[1].kind: 'guru' not in ['persona', 'preset']",
        "personas.yaml.personas[2].id: its value (6 character(s)) does not match ^[A-Za-z0-9][A-Za-z0-9_.-]*$",
        "personas.yaml.personas[3]: missing 'id'",
        "personas.yaml.source[0]: dated 2026-11-20, after the import of 2026-11-01",
        "personas.yaml.source[1].date: 'someday' is not a day (YYYY-MM-DD)",
        "tea: brick Z is the brick of no module of modules.yaml",
        "tea: module Z9 is not in modules.yaml",
        "tea: module Y1 is not in modules.yaml",
        "personas.yaml: preset tea given twice",
    ]


@pytest.mark.parametrize("text, want", [
    ("v: 2\npersonas: whatever\n", "v2 is written by brain"),   # refused alone: its other keys not judged
    ("- a list\n", "expected a mapping (v, personas), got list"),
    ("v: [1\n", "not a YAML document"),
    ("personas: []\n", "missing 'v'"),
])
def test_a_file_this_engine_does_not_read_is_refused(tmp_path, text, want):
    store = _store(tmp_path, text)
    found = presets.problems(store)
    assert len(found) == 1 and want in found[0]
    assert presets.report(store) == [] or want == "missing 'v'"


def test_without_the_file_or_a_registry_nothing_is_concerned(tmp_path):
    store = _store(tmp_path, None)
    assert presets.problems(store) == presets.report(store) == presets.warnings(store) == []
    assert presets.lines([]) == ["no personas.yaml beside the registry (or none this engine reads: brain modules "
                                 "--check)"]
    bare = _brain(tmp_path / "bare", registry=None)
    (bare / presets.FILE).write_text(PERSONAS, encoding="utf-8")   # no registry: the file is not read
    assert presets.path(bare) is None and presets.problems(bare) == presets.report(bare) == []


def test_another_store_reading_the_registry_does_not_check_the_file_twice(tmp_path, monkeypatch):
    from test_modules import _programme
    lab, lab_store, prog_store, _ = _programme(tmp_path, monkeypatch, "prog")
    (prog_store / presets.FILE).write_text("v: 1\npersonas: [{id: x, name: X, bricks: [Z]}]\n", encoding="utf-8")
    assert presets.path(lab_store, lab) == prog_store / presets.FILE   # beside the registry it reads
    assert presets.problems(lab_store, lab) == presets.report(lab_store, lab) == []   # prog's check says it, once
    assert presets.problems(prog_store, lab) == ["x: brick Z is the brick of no module of modules.yaml"]


def test_personas_run_from_a_store_reading_the_registry_checks_the_owners_file(tmp_path, monkeypatch, capsys):
    """An explicit brain modules --personas never passes on the file it skipped: run from the store that reads the
    registry (modules.store), it checks the file beside that registry and names its store."""
    from test_modules import _programme
    lab, lab_store, prog_store, _ = _programme(tmp_path, monkeypatch, "prog")
    (prog_store / presets.FILE).write_text("v: 1\npersonas: [{id: x, name: X, bricks: [Z]}]\n", encoding="utf-8")
    assert cli.main(["modules", "--personas"]) == 1   # lab, the default project: prog's file refused
    out = capsys.readouterr().out
    assert out.startswith("personas.yaml of prog:notes/graph (the registry this store reads)\n")
    assert "x: brick Z is the brick of no module of modules.yaml" in out and "no personas.yaml" not in out
    assert cli.main(["modules", "--personas", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["problems"] == ["x: brick Z is the brick of no module of modules.yaml"]
    (prog_store / presets.FILE).write_text("v: 1\npersonas: [{id: k, name: K, bricks: [K], ai: false}]\n",
                                           encoding="utf-8")
    assert cli.main(["modules", "--personas"]) == 0
    assert "k (K): " in capsys.readouterr().out


@pytest.mark.parametrize("which", ["older", "newer"])
def test_the_fixtures_are_read_in_read_mode(tmp_path, monkeypatch, which):
    monkeypatch.setenv("BRAIN_STRICT", "0")
    registry = REGISTRY + "- {id: P12, name: kettle-meter, brick: P, phase: V1.5, status: proposed}\n"
    store = _store(tmp_path, FORMATS.joinpath(f"{which}.yaml").read_text(encoding="utf-8"), registry)
    monkeypatch.setattr(schema, "_NOTED", set())
    assert presets.problems(store) == []   # the newer one's keys: a note on stderr, kept
    assert [r["id"] for r in presets.report(store)][:1] == ["tea-drinker"]
    if which == "newer":   # strict mode (CI, every write) refuses a newer brain's keys
        monkeypatch.setenv("BRAIN_STRICT", "1")
        assert presets.problems(store) == ["personas.yaml: unknown field 'catalogue'",
                                           "personas.yaml.personas[0]: unknown field 'cost'"]


def test_the_older_fixture_passes_strict_and_holds_every_key_of_the_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_STRICT", "1")
    doc = presets.load(FORMATS / "older.yaml")[0]
    s = schema.load("personas")
    assert set(doc) == set(s["properties"])
    assert set().union(*(p.keys() for p in doc["personas"])) == set(s["$defs"]["preset"]["properties"])
    registry = REGISTRY + "- {id: P12, name: kettle-meter, brick: P, phase: V1.5, status: proposed}\n"
    store = _store(tmp_path, (FORMATS / "older.yaml").read_text(encoding="utf-8"), registry)
    assert presets.problems(store) == []


def test_the_schema_is_registered_and_fully_implemented():
    assert "personas" in schema.SCHEMAS and schema.unsupported(schema.load("personas")) == []
    assert schema.known_v("personas") == 1


def test_brain_modules_personas_and_check(tmp_path, monkeypatch, capsys):
    lab, store = _lab(tmp_path, monkeypatch, REGISTRY, NODES)
    (store / presets.FILE).write_text(PERSONAS, encoding="utf-8")
    assert cli.main(["modules", "--personas"]) == 1   # brewer is open, lamplighter and monk violated
    out = capsys.readouterr().out
    assert "tea-drinker (The tea drinker): 1 module(s), closure closed, no AI ok" in out
    assert "  brewer: misses K1, a hard dependency of P2" in out
    assert "  lamplighter: without AI, M4 is shipped only by engine, which ship AI modules" in out
    assert "  monk: without AI, lists engine, a distribution that ships AI modules" in out
    assert "  tea-drinker +Q: without AI, pulls the AI module Q1" in out
    assert "  to classify (1): M4" in out and "  distributions no realisation ships in: tea-cloud" in out
    assert out.rstrip().endswith("8 preset variant(s): 4 open or violated, 5 incomplete")
    assert cli.main(["modules", "--personas", "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["problems"] == [] and [r["closure"] for r in data["presets"]][:3] == ["closed", "incomplete", "open"]
    # the faults are warnings of brain modules --check and brain check, never a failure
    assert cli.main(["modules", "--check"]) == 0
    assert "warning: brewer: misses K1, a hard dependency of P2" in capsys.readouterr().out
    from brain import projects, views
    from brain.commands._stores import _module_warnings
    lines = _module_warnings(projects.load(lab)["lab"], lab, store, views.Stale())
    assert "module map: monk: without AI, lists engine, a distribution that ships AI modules" in lines
    # the file's own problems are refused by both
    (store / presets.FILE).write_text("v: 1\npersonas: [{id: x, name: X, bricks: [Z]}]\n", encoding="utf-8")
    assert cli.main(["modules", "--check"]) == 1
    assert "x: brick Z is the brick of no module of modules.yaml" in capsys.readouterr().out
    assert cli.main(["modules", "--personas"]) == 1
    capsys.readouterr()
    (store / presets.FILE).write_text("v: 1\nexpand: {skip_placement: [set aside]}\n"
                                      "personas: [{id: tea, name: Tea, bricks: [K], ai: false}]\n", encoding="utf-8")
    assert cli.main(["modules", "--personas"]) == 0
    assert "1 preset variant(s): 0 open or violated, 0 incomplete" in capsys.readouterr().out


@pytest.mark.parametrize("extra", [["--check"], ["--diff"], ["--diff", "HEAD~1"]])
def test_personas_with_check_or_diff_is_refused_never_one_dropped(tmp_path, monkeypatch, extra):
    _lab(tmp_path, monkeypatch, REGISTRY, NODES)
    with pytest.raises(SystemExit) as e:
        cli.main(["modules", "--personas", *extra])
    assert "--personas runs alone" in str(e.value.code)


def test_the_personas_flag_takes_the_parents_flags_after_the_subcommand(tmp_path, monkeypatch, capsys):
    lab, store = _lab(tmp_path, monkeypatch, REGISTRY, NODES)
    (store / presets.FILE).write_text(PERSONAS, encoding="utf-8")
    assert cli.main(["modules", "--personas", "--project", "lab"]) == 1
    assert "brewer: misses K1" in capsys.readouterr().out
