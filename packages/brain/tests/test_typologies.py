"""The typology catalog (brain.typologies, wi-brain-typology-catalog; spec-brain-typology-packs E1, TYPO-3): one
vocabulary of the kinds of project. Every id the engine already published (the layers' lifecycle ids, the standards'
profiles, the project templates' names) is an entry or a sub-profile; a sub-profile takes what its entry takes; a
brain renames labels and adds ids in config.json typologies; an unknown id is a note in read mode, an error in strict
mode. Fictitious names only."""

import json

import pytest
from brain import cli, config, init, scopes, standards, typologies

from research_graph import layers as rg_layers

# LC-1's typologies (spec-brain-product-lifecycle §3.1) and GT's addition (trading): the catalog maps them all
LC1 = {"software", "api-cli", "ai-ml", "hardware", "infra", "research", "compliance", "organisation"}
ENTRIES = ["software", "research", "hardware-cad", "creation", "strategy", "marketing", "organisation", "compliance"]


@pytest.fixture
def cat():
    return typologies.engine()


@pytest.fixture
def brain(store, monkeypatch):
    """A brain at the store fixture's root with a config.json the test fills."""
    root = store.parents[1]

    def write(**data) -> config.Config:
        (root / config.FILE).write_text(json.dumps({"v": 1, "identity": {"owner": "Ada"}, **data}), encoding="utf-8")
        return config.load(root)
    monkeypatch.setenv("BRAIN_CONFIG", str(root / config.FILE))
    monkeypatch.setenv("BRAIN_PROJECTS", str(root / "projects.yaml"))
    monkeypatch.delenv("BRAIN_SCOPES", raising=False)
    (root / "projects.yaml").write_text("alpha: {root: .}\n", encoding="utf-8")
    write()
    write.root = root
    return write


def test_the_engine_catalog_is_well_formed_and_its_entries_map_to_the_vision(cat):
    assert typologies.self_check() == []
    assert [t.id for t in cat.entries()] == ENTRIES
    assert {v for t in cat.entries() for v in t.vision} == {"J1", "J2", "J3", "K3", "K4"}
    for t in cat.typologies.values():
        assert t.labels.get("en") and t.labels.get("fr") and t.description, t.id
        assert not t.parent or cat.entry(t.parent) == t.parent, t.id   # one level: a sub-profile's parent is an entry


def test_every_id_the_engine_already_published_is_in_the_catalog(cat):
    """The 0.4.0 doors (wi-brain-typology-pretag): the layers' typologies, the standards' profiles, the profile
    templates' names and LC-1's list are entries or sub-profiles; the layers' stages are the catalog's (or a layer's
    own injected stage), and the standards' stages are mapped to them."""
    named = {t for la in rg_layers.catalogue().values() for t in la.lifecycle().get("typologies") or []}
    assert named - set(typologies.ANY) <= set(cat.typologies)
    assert set(standards.PROFILES) - {"any"} <= set(cat.typologies)
    assert {t for t in init.known_templates() if t != init.DEFAULT_TEMPLATE} <= set(cat.typologies)
    assert LC1 | {"trading"} <= set(cat.typologies)
    stages = {s for la in rg_layers.catalogue().values() for s in la.lifecycle().get("proposed_at") or []}
    assert stages - set(typologies.ANY) <= set(cat.stages)
    assert tuple(cat.standards_stages) == standards.STAGES == init.STAGES
    assert set(cat.standards_stages.values()) <= set(cat.stages)


def test_a_sub_profile_takes_what_its_entry_takes(cat):
    assert cat.entry("cli") == "software" and cat.entry("software") == "software" and cat.entry("video-x") == ""
    assert cat.kinds("cli") == ["cli", "software"] and cat.kinds("video-x") == ["video-x"]
    assert cat.meets("cli", ["software", "research"]) == ["software"]
    assert cat.meets("cli", ["*"]) == ["*"] and cat.meets("strategy", ["software"]) == []
    assert cat.stage("mvp") == "build" and cat.stage("deliver") == "deliver"
    assert cat.stage("preregistration-backtest") == "preregistration-backtest"   # a layer's own stage, as given
    # code.yaml names software, not cli: a cli project at its mvp is proposed the code layer through its entry
    assert "cli" not in rg_layers.catalogue()["code"].lifecycle()["typologies"]
    got = typologies.layers(cat, "cli", "mvp")
    assert {"code", "docs_tests", "features", "work"} <= set(got) and "research" not in got
    assert "research" in typologies.layers(cat, "trading", "explore")
    assert typologies.layers(cat, "video-x", "build") == typologies.layers(cat, "creation", "build")   # only the *'s


def test_a_brain_renames_labels_and_adds_its_own_ids(brain):
    cfg = brain(typologies={"software": {"fr": "Produit logiciel", "vision": ["J1", "A6"]},
                            "podcast": {"en": "Podcast", "fr": "Podcast", "parent": "creation"},
                            "pitch": {"en": "Pitch deck", "parent": "venture"},   # a brain's entry, named later
                            "venture": {"en": "Venture", "vision": ["K3"]}})
    assert typologies.check(cfg) == []
    cat = typologies.load(cfg)
    sw = cat.typologies["software"]
    assert sw.label("fr") == "Produit logiciel" and sw.label("en") == "Software" and sw.vision == ("J1", "A6")
    assert cat.entry("podcast") == "creation" and cat.typologies["podcast"].origin == config.FILE
    assert cat.entry("venture") == "venture" and "venture" in [t.id for t in cat.entries()]
    assert cat.entry("pitch") == "venture" and cat.kinds("pitch") == ["pitch", "venture"]
    assert config.check(brain.root) == []


@pytest.mark.parametrize("given, needle", [
    ([], "typologies is a mapping"),
    ({"Bad Id": {"en": "x"}}, "lowercase letters"),
    ({"x": "a label"}, "a mapping of"),
    ({"x": {"en": " "}}, "en is a label"),
    ({"x": {"vision": "J1"}}, "vision is a list"),
    ({"cli": {"parent": "research"}}, "keeps its place"),
    ({"x": {"parent": "cli"}}, "no entry"),
    ({"x": {"parent": "nowhere"}}, "no entry"),
    ({"cli": {"vision": ["K4"]}}, "vision is an entry's"),
    ({"x": {"parent": "creation", "vision": ["J3"]}}, "vision is an entry's"),
])
def test_a_bad_brain_catalog_is_named(brain, given, needle):
    errors = typologies.check(brain(typologies=given))
    assert any(needle in e for e in errors), errors


def test_an_unknown_key_or_id_is_a_note_in_read_mode_an_error_in_strict_mode(brain, cat, monkeypatch):
    cfg = brain(typologies={"x": {"en": "X", "colour": "red"}})
    assert any("unknown key(s) colour" in e for e in typologies.check(cfg))   # the suite reads strictly, as CI
    assert typologies.unknown("here", ["software", "*", "video-x"], cat) == [
        "here: typology 'video-x' is not in the typology catalog (brain typologies)"]
    monkeypatch.setenv("BRAIN_STRICT", "0")
    notes: list[str] = []
    assert typologies.check(cfg) == []
    assert typologies.unknown("here", ["video-x"], cat, notes=notes) == [] and "video-x" in notes[0]


def test_a_standards_profile_is_a_catalog_id_and_a_sub_profile_meets_its_entry_rows():
    assert {"software", "creation", "hardware-cad"} <= set(standards.profiles())
    assert standards.row_errors("r", {"profiles": ["creation"], "stage": "mvp"}, strict=True) == []
    assert standards.row_errors("r", {"profiles": ["video-x"]}, strict=True)
    rows = [standards.Row(id="sw-x", catalog="c", domain="d", statement="s", profiles=["software"], stage="mvp",
                          enforcement="check", check="a lint", languages=["any"], status="proposed"),
            standards.Row(id="sw-y", catalog="c", domain="d", statement="s", profiles=["service"], stage="mvp",
                          enforcement="check", check="a lint", languages=["any"], status="proposed")]
    got = {r.id: why for r, why in standards.applicable(rows, standards.selection({"profiles": ["cli"],
                                                                                   "stage": "v1"}))}
    assert got == {"sw-x": "profile software, from mvp"}   # not sw-y: a sibling sub-profile is not met


def test_a_containers_lifecycle_typologies_are_read_against_the_catalog(brain, monkeypatch):
    brain(typologies={"podcast": {"en": "Podcast", "parent": "creation"}})
    (brain.root / scopes.FILE).write_text(
        "v: 1\nscopes:\n  pro: {type: sphere, lifecycle: {typologies: [software, podcast]}}\n"
        "  lab: {type: sphere, lifecycle: {typologies: [video-x]}}\n"
        "  odd: {type: sphere, lifecycle: {typologies: software}}\n", encoding="utf-8")
    errors, _ = scopes.check(brain.root)
    assert [e for e in errors if "typolog" in e] == [
        "scope lab: lifecycle.typologies: typology 'video-x' is not in the typology catalog (brain typologies)",
        "scope odd: lifecycle.typologies is a list of typology ids (brain typologies)"]
    monkeypatch.setenv("BRAIN_STRICT", "0")
    errors, _ = scopes.check(brain.root)
    assert [e for e in errors if "typolog" in e] == [
        "scope odd: lifecycle.typologies is a list of typology ids (brain typologies)"]


def test_brain_typologies_lists_and_shows(brain, capsys):
    brain(typologies={"software": {"fr": "Produit logiciel"}, "podcast": {"en": "Podcast", "parent": "creation"}})
    root = str(brain.root)
    assert cli.main(["--root", root, "typologies"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("  software    Software [J1]: ") and "    podcast   Podcast (config.json)" in out
    assert "standards stages: prototype -> explore, mvp -> build, v1 -> launch, scale -> grow" in out
    assert cli.main(["--root", root, "typologies", "--lang", "fr", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [e["id"] for e in data["entries"]] == ENTRIES
    assert data["entries"][0]["label"] == "Produit logiciel" and "cli" in data["entries"][0]["sub"]
    assert cli.main(["--root", root, "typologies", "show", "cli", "--stage", "mvp", "--json"]) == 0
    one = json.loads(capsys.readouterr().out)
    assert one["entry"] == "software" and one["stage"] == "build" and "code" in one["layers"]
    assert cli.main(["--root", root, "typologies", "show", "cli", "--stage", "mvp"]) == 0
    assert "layers proposed at mvp (read as build): " in capsys.readouterr().out
    assert cli.main(["--root", root, "typologies", "--json", "--lang", "fr", "show", "cli"]) == 0   # before show
    one = json.loads(capsys.readouterr().out)
    assert one["label"] == "Outil en ligne de commande"
    assert cli.main(["--root", root, "typologies", "show", "video-x"]) == 1
    assert "not in the typology catalog" in capsys.readouterr().out


def test_the_catalog_is_parsed_once_and_a_broken_one_leaves_the_standards_as_before(monkeypatch):
    typologies._read.cache_clear()
    typologies.engine()
    typologies.engine()
    assert typologies._read.cache_info().hits >= 1
    monkeypatch.setattr(typologies, "engine", lambda: (_ for _ in ()).throw(typologies.CatalogError("broken")))
    assert standards.profiles() == list(standards.PROFILES) and standards.kinds("cli") == ["cli"]


def test_standards_list_profile_meets_the_entry_rows():
    from types import SimpleNamespace

    from brain.commands import standards as cmd
    row = standards.Row(id="sw-x", catalog="c", domain="d", statement="s", profiles=["software"], stage="mvp",
                        enforcement="check", check="a lint", languages=["any"], status="proposed")
    assert cmd._matches(row, SimpleNamespace(profile="cli")) and not cmd._matches(row, SimpleNamespace(profile="research"))
