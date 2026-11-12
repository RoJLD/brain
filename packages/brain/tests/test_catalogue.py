"""catalogue/v1, the module catalogue's contract (wi-brain-catalogue-contract; docs/catalogue.md): the published schema,
the rules a schema cannot say, the evolution rule (an unknown key tolerated, a later version refused), the Brain's own
catalogue (brain catalogue emit) and brain catalogue validate."""

import copy
import json
from pathlib import Path

import pytest

from brain import catalogue, cli, schema, tiers

FIXTURES = Path(__file__).parent / "fixtures" / "formats" / "catalogue" / "v1"
DOCS = Path(__file__).resolve().parents[1] / "docs" / "catalogue.md"


def fixture(which: str) -> dict:
    return json.loads((FIXTURES / f"{which}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("which", ["older", "newer"])
def test_both_sides_of_the_version_hold_to_the_contract(which):
    """A first producer's catalogue and another's with keys of its own at every level, a persona, a typology id no
    catalogue holds yet and a soft dependency on another catalogue's module: both valid, even in strict mode."""
    doc = fixture(which)
    assert schema.validate("catalogue", doc, schema.STRICT) == ([], [])
    errors, notes = catalogue.validate(doc)
    assert errors == []
    if which == "newer":
        assert any("'teapot-sync' is not a module of the catalogue (another catalogue's?)" in n for n in notes)
        assert any("presets[tea-lover]: pulls kettle-core" in n for n in notes)
    else:
        assert notes == []


def test_the_schema_is_registered_and_its_keywords_implemented():
    assert "catalogue" in schema.SCHEMAS and schema.unsupported(schema.load("catalogue")) == []
    assert schema.known_v("catalogue") == 1   # versioned by its id, not by a top-level v


def test_the_vocabularies_are_the_schemas():
    """The module's lists and the published schema say the same thing: a reader in another language reads the
    schema only."""
    s = schema.load("catalogue")
    assert tuple(s["$defs"]["module"]["properties"]["class"]["enum"]) == catalogue.CLASSES
    assert tuple(s["$defs"]["preset"]["properties"]["kind"]["enum"]) == catalogue.PRESET_KINDS
    assert tuple(s["$defs"]["cost"]["properties"]) == catalogue.COST
    assert tuple(k for k in s["properties"] if k in catalogue.LISTS) == catalogue.LISTS
    assert s["$defs"]["module"]["properties"]["class"]["enum"] == list(tiers.CLASSES)   # the engine's classes


def test_the_clause_and_requirement_patterns_are_the_engines():
    """recommend_when and requires read as brain.tiers reads them: a clause the engine takes, the schema takes."""
    s = schema.load("catalogue")["$defs"]["module"]["properties"]
    import re
    clause, req = s["recommend_when"]["items"]["pattern"], s["requires"]["items"]["pattern"]
    for c in ("docker", "not wsl", "memory_gb >= 7", "gpu_vram_gb>=12", "os == windows"):
        assert re.search(clause, c) and tiers.CLAUSE.match(c), c
    for c in ("memory_gb >= 7 GB", ">= 7", ""):
        assert not re.search(clause, c) and not tiers.CLAUSE.match(c), c
    for r in ("git", "env:EXAMPLE_KEY", "container_runtime"):
        assert re.search(req, r) and tiers.REQUIREMENT.match(r), r
    assert not re.search(req, "Docker") and not tiers.REQUIREMENT.match("Docker")


def _broken(mutate, which="older") -> list[str]:
    doc = copy.deepcopy(fixture(which))
    mutate(doc)
    return catalogue.validate(doc)[0]


def _mod(doc, mid):
    return next(m for m in doc["modules"] if m["id"] == mid)


@pytest.mark.parametrize("mutate,expected", [
    (lambda d: d["modules"].append(dict(d["modules"][0])), "id 'kettle-core' used twice"),
    (lambda d: d["presets"].append(dict(d["presets"][0])), "id 'lite' used twice"),
    (lambda d: _mod(d, "kettle-meter")["depends_on"].append("kettle-x"), "'kettle-x' is not a module"),
    (lambda d: _mod(d, "kettle-meter").update(uses=["kettle-core"]),
     "'kettle-core' is both a hard (depends_on) and a soft (uses) dependency"),
    (lambda d: _mod(d, "kettle-core").update(depends_on=["kettle-core"]), "depends on or uses itself"),
    (lambda d: _mod(d, "kettle-core").update(depends_on=["kettle-meter"]),
     "a cycle of hard dependencies: kettle-core -> kettle-meter -> kettle-core"),
    (lambda d: _mod(d, "kettle-core").update(brick="Z"), "brick: 'Z' is not a brick"),
    (lambda d: _mod(d, "kettle-core").update(distributions=["nowhere"]), "'nowhere' is not a distribution"),
    (lambda d: d["presets"][0]["modules"].append("kettle-x"), "presets[lite].modules: 'kettle-x' is not a module"),
    (lambda d: d["presets"][2]["when_fits"].append("kettle-cloud"), "'kettle-cloud' is planned, not installable"),
    (lambda d: d["presets"][2]["when_fits"].append("kettle-meter"), "'kettle-meter' is both in modules and in"),
    (lambda d: d["presets"].append({"id": "p", "name": "P", "kind": "persona", "base": "nope", "modules": []}),
     "base: 'nope' is not a base preset"),
    (lambda d: d["presets"].append({"id": "p", "name": "P", "kind": "persona", "base": "q", "modules": []})
     or d["presets"].append({"id": "q", "name": "Q", "kind": "persona", "modules": []}),
     "base: 'q' is not a base preset"),
    (lambda d: _mod(d, "kettle-core").update({"class": "plugin"}), "'plugin' not in"),     # a new class is v2
    (lambda d: _mod(d, "kettle-core").update(status="beta"), "'beta' not in"),
    (lambda d: d["presets"][0].update(kind="team"), "'team' not in"),
    (lambda d: _mod(d, "kettle-core").pop("name"), "missing 'name'"),
    (lambda d: d["presets"][0].pop("modules"), "missing 'modules'"),
    (lambda d: _mod(d, "kettle-meter")["cost"].update(ram_mb=-1), "below 0"),
    (lambda d: _mod(d, "kettle-vision")["recommend_when"].append("vram >= 7 GB"), "does not match"),
    (lambda d: _mod(d, "kettle-vision")["requires"].append("GPU"), "does not match"),
    (lambda d: _mod(d, "kettle-core").update(id="kettle core"), "does not match"),
    (lambda d: d["distributions"][2]["source"].update(sha256="xyz"), "does not match"),
    (lambda d: d.pop("generated"), "missing 'generated'"),
    (lambda d: d["generated"].update(at="yesterday"), "is not a date-time"),
])
def test_what_breaks_the_contract_is_an_error(mutate, expected):
    errors = _broken(mutate)
    assert any(expected in e for e in errors), errors


def test_a_later_version_is_refused_and_judged_no_further():
    doc = fixture("newer")
    doc["schema"] = "catalogue/v2"
    doc["modules"] = "anything"        # its keys may mean something else: not judged
    errors, notes = catalogue.validate(doc, where="c.json")
    assert errors == ["c.json: schema: catalogue/v2 is a later contract than this engine's catalogue/v1: "
                      "brain update"]
    assert notes == []


def test_an_unknown_key_is_tolerated_at_every_level_and_a_named_one_keeps_its_type():
    doc = fixture("older")
    doc["v"] = 2                                       # a producer's own key: the version is schema's
    doc["extra"] = {"anything": [1, 2]}
    doc["bricks"][0]["extra"] = 1
    doc["modules"][0]["extra"] = 1
    doc["modules"][0]["cost"]["power_w"] = 30
    doc["distributions"][2]["source"]["mirror"] = "x"
    doc["presets"][0]["extra"] = 1
    assert catalogue.validate(doc) == ([], [])
    doc["modules"][0]["ai"] = "yes"
    assert any("expected boolean" in e for e in catalogue.validate(doc)[0])


def test_a_typology_id_no_catalogue_holds_is_kept_never_refused():
    doc = fixture("older")
    doc["modules"][0]["typologies"] = ["a-typology-no-engine-knows"]
    doc["presets"][0]["typologies"] = ["another"]
    assert catalogue.validate(doc) == ([], [])


def test_another_contract_is_an_error():
    doc = fixture("older")
    doc["schema"] = "docgraph/v1"
    assert any("must be 'catalogue/v1'" in e for e in catalogue.validate(doc)[0])


def test_a_malformed_document_is_reported_never_a_crash():
    doc = {"schema": "catalogue/v1", "generated": "now", "modules": [3, {"id": "a", "depends_on": "b"},
                                                                     {"id": ["x"]}],
           "presets": {"a": 1}, "bricks": "x", "distributions": [None]}
    errors, _ = catalogue.validate(doc)
    assert errors and all(isinstance(e, str) for e in errors)
    assert catalogue.summary(doc)["by"] is None


@pytest.mark.parametrize("value", [[], "x", None, 3])
def test_a_document_that_is_not_an_object_is_an_error(value):
    assert catalogue.validate(value, where="d")[0] == [f"d: expected a JSON object, got {type(value).__name__}"]


def test_load_takes_a_bom_and_refuses_unreadable_json(tmp_path):
    bom = tmp_path / "bom.json"
    bom.write_bytes(b"\xef\xbb\xbf" + (FIXTURES / "older.json").read_bytes())
    assert catalogue.validate(catalogue.load(bom))[0] == []
    for name, text in (("deep.json", "[" * 200_000), ("list.json", "[]")):
        (tmp_path / name).write_text(text, encoding="utf-8")
        with pytest.raises(catalogue.CatalogueError):
            catalogue.load(tmp_path / name)


def test_summary_counts():
    s = catalogue.summary(fixture("older"))
    assert s["modules"] == 4 and s["classes"] == {"core": 1, "extra": 1, "service": 2}
    assert s["statuses"] == {"built": 3, "planned": 1} and (s["bricks"], s["distributions"]) == (2, 3)
    assert s["presets"] == ["lite", "default", "recommended"]


def test_the_documented_keys_are_the_schemas():
    """docs/catalogue.md names every key the schema names (a reader learns the contract from the page)."""
    text = DOCS.read_text(encoding="utf-8")
    s = schema.load("catalogue")
    keys = set(s["properties"]) | {k for d in s["$defs"].values() for k in d.get("properties", {})}
    assert sorted(k for k in keys if f"`{k}`" not in text) == []


# --- the Brain's own catalogue ---------------------------------------------------------------------------------------

TIERS = """\
capabilities:
  base:
    title: the base
    class: core
    profile: lite
    provides: [base]
    requires: [git]
    resources: {disk_mb: 30}
  store:
    title: a store the agent reads
    class: extra
    profile: default
    provides: [store]
    requires: []
    resources: {disk_mb: 50}
    fallback: no store
    install: {pip: store}
  agent:
    title: an agent
    class: service
    profile: recommended
    provides: [agent]
    requires: [docker]
    resources: {ram_mb: 200, disk_gb: 1.5}
    fallback: the local probe
    recommend_when: [memory_gb >= 7]
    depends_on: [store]
  viewer:
    title: a viewer
    class: extra
    profile: custom
    provides: [viewer]
    requires: []
    resources: {}
    fallback: the text view
    uses: [agent]
  later:
    title: a capability still to build
    class: extra
    profile: recommended
    provides: [later]
    requires: []
    resources: {}
    fallback: nothing yet
    status: planned
    item: wi-later
  finder:
    title: a tool used whenever it is found
    class: extra
    profile: custom
    auto: true
    provides: [finder]
    requires: []
    resources: {}
    fallback: nothing found
"""
MODULES = """\
- {id: M1, name: core-mod, brick: M, phase: MVP, status: tree, capabilities: [base], definition: "the core"}
- {id: M2, name: agent-mod, brick: A, phase: MVP, status: tree, capabilities: [agent], ai: true}
- {id: M3, name: viewer-mod, brick: M, phase: MVP, status: tree, capabilities: [viewer], uses: [M2, M9]}
- {id: M4, name: store-mod, brick: M, phase: MVP, status: tree, capabilities: [store]}
- {id: M5, name: finder-mod, brick: M, phase: MVP, status: tree, capabilities: [finder]}
- {id: M9, name: elsewhere, brick: M, phase: V2, status: proposed}
"""


@pytest.fixture
def engine(tmp_path, monkeypatch):
    """The engine's capabilities replaced by TIERS; a brain at tmp_path/root with no registry yet."""
    root = tmp_path / "root"
    (root / "notes" / "graph").mkdir(parents=True)
    f = tmp_path / "tiers.yaml"
    f.write_text(TIERS, encoding="utf-8")
    real = tiers.capabilities
    monkeypatch.setattr(tiers, "capabilities", lambda path=f: real(path))
    monkeypatch.setenv("BRAIN_CONFIG", str(root / "config.json"))
    monkeypatch.setenv("BRAIN_PROJECTS", str(tmp_path / "none.yaml"))
    return root


def test_without_a_registry_each_capability_is_a_module_and_the_document_holds(engine):
    doc = catalogue.emit(engine, "brain test", at="2026-01-01T00:00:00Z")
    assert catalogue.validate(doc) == ([], [])
    mods = {m["id"]: m for m in doc["modules"]}
    assert list(mods) == ["base", "store", "agent", "viewer", "later", "finder"]
    agent = mods["agent"]
    assert (agent["name"], agent["description"], agent["class"]) == ("agent", "an agent", "service")
    assert agent["depends_on"] == ["store"] and mods["viewer"]["uses"] == ["agent"]
    assert agent["cost"] == {"disk_mb": 1536, "ram_mb": 200}           # disk_gb counted in MiB
    assert agent["requires"] == ["docker"] and agent["recommend_when"] == ["memory_gb >= 7"]
    assert mods["store"]["distributions"] == ["base", "extra-store"] and mods["base"]["distributions"] == ["base"]
    assert mods["later"]["status"] == "planned" and mods["finder"]["auto"] is True
    assert [d["id"] for d in doc["distributions"]] == ["base", "extra-store"]
    assert doc["distributions"][0]["bundled"] is True and doc["distributions"][1]["bundled"] is False
    presets = {p["id"]: p for p in doc["presets"]}
    assert presets["lite"]["modules"] == ["base"]
    assert presets["default"]["modules"] == ["base", "store"]
    assert presets["recommended"]["modules"] == ["base", "store"]
    assert presets["recommended"]["when_fits"] == ["agent"]          # never the planned one
    assert {p["kind"] for p in doc["presets"]} == {"base"} and doc["bricks"] == []
    assert doc["generated"]["from"] == ["tiers.yaml (brain " + catalogue_version() + ")"]


def catalogue_version() -> str:
    from brain import __version__
    return __version__


def test_with_a_registry_its_modules_bricks_and_dependencies_are_the_catalogue(engine):
    (engine / "notes" / "graph" / "modules.yaml").write_text(MODULES, encoding="utf-8")
    doc = catalogue.emit(engine, "brain test")
    errors, notes = catalogue.validate(doc)
    assert errors == [] and notes == []
    mods = {m["id"]: m for m in doc["modules"]}
    assert list(mods) == ["M1", "M2", "M3", "M4", "M5"]               # M9 lists no capability: not a module here
    assert mods["M1"]["name"] == "core-mod" and mods["M1"]["description"] == "the core"
    assert mods["M2"]["depends_on"] == ["M4"] and mods["M2"]["ai"] is True   # deduced from agent -> store
    assert mods["M3"]["uses"] == ["M2"]                                # M9 is not in the catalogue
    assert [b["id"] for b in doc["bricks"]] == ["A", "M"]
    assert {p["id"]: p.get("when_fits") for p in doc["presets"]}["recommended"] == ["M2"]
    assert doc["generated"]["from"][-1] == "modules.yaml"


def test_the_engines_own_catalogue_holds_to_the_contract(tmp_path, monkeypatch):
    """The real tiers.yaml, no registry: what brain catalogue emit prints on a fresh machine is valid."""
    monkeypatch.setenv("BRAIN_PROJECTS", str(tmp_path / "none.yaml"))
    monkeypatch.setenv("BRAIN_CONFIG", str(tmp_path / "config.json"))
    doc = catalogue.emit(None, "brain test")
    assert catalogue.validate(doc)[0] == []
    lite, default, rec = (set(p["modules"]) for p in doc["presets"])
    assert lite <= default == rec and lite


# --- brain catalogue --------------------------------------------------------------------------------------------------

def test_validate_needs_no_brain_and_exits_on_an_invalid_document(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("BRAIN_ROOT", raising=False)
    bad = tmp_path / "bad.json"
    doc = fixture("older")
    doc["presets"][0]["modules"].append("nothing")
    bad.write_text(json.dumps(doc), encoding="utf-8")
    assert cli.main(["catalogue", "validate", str(FIXTURES / "older.json"), str(FIXTURES / "newer.json")]) == 0
    out = capsys.readouterr().out
    assert "older.json: OK: 4 module(s), 3 distribution(s), presets lite, default, recommended" in out
    assert "note:" in out and "'teapot-sync'" in out
    assert cli.main(["catalogue", "validate", str(bad)]) == 1
    out = capsys.readouterr().out
    assert "bad.json: INVALID" in out and "'nothing' is not a module" in out


def test_validate_json_reports_a_later_version(tmp_path, capsys):
    later = tmp_path / "later.json"
    later.write_text(json.dumps({**fixture("older"), "schema": "catalogue/v3"}), encoding="utf-8")
    assert cli.main(["catalogue", "validate", "--json", str(later), str(FIXTURES / "newer.json")]) == 1
    rows = json.loads(capsys.readouterr().out)
    assert [r["ok"] for r in rows] == [False, True] and rows[0]["summary"] is None
    assert rows[1]["summary"]["presets"] == ["lite", "tea-lover"]


def test_emit_prints_or_writes_a_valid_document(engine, capsys, tmp_path):
    assert cli.main(["--root", str(engine), "catalogue", "emit"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["schema"] == "catalogue/v1" and catalogue.validate(doc)[0] == []
    out = tmp_path / "cat.json"
    assert cli.main(["--root", str(engine), "catalogue", "emit", "--out", str(out)]) == 0
    assert "6 module(s), 2 distribution(s), presets lite, default, recommended" in capsys.readouterr().out
    assert cli.main(["catalogue", "validate", str(out)]) == 0
