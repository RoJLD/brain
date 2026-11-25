"""The automation levels resolved (brain.automation, wi-brain-automation-config; spec-brain-automation-levels S2,
AUTO-1 and AUTO-5): the engine's default, then config.json's automation section v1, then the machine file
<BRAIN_HOME>/automation.json, which may only lower; fail closed (a level above its ceiling, unknown or unreadable, a
floor gesture's, a section or file this engine cannot read: manual); an id the catalogue does not hold ignored with a
note; brain config --check and brain automation explain."""

import json

import pytest

from brain import automation, cli, config, gestures, schema

FIXTURES = __import__("pathlib").Path(__file__).parent / "fixtures" / "formats" / "config" / "v1"


def write_config(tmp_path, monkeypatch, section=None, name="config.json", **extra) -> config.Config:
    data = {"v": 1, "identity": {"owner": "Ada"}, **extra}
    if section is not None:
        data["automation"] = section
    f = tmp_path / name
    f.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(f))
    return config.load()


def machine(tmp_path, data) -> automation.Layer:
    f = tmp_path / "automation.json"
    f.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return automation.machine_layer(f)


NO_MACHINE = automation.Layer("machine", "")


def levels(cfg, mach=NO_MACHINE, anchor=False) -> dict[str, str]:
    return {k: r.level for k, r in automation.resolve(cfg, anchor, mach).items()}


def defaults() -> dict[str, str]:
    return {a.id: gestures.effective(a, a.default) for a in gestures.CATALOGUE}


# --- the defaults: today's behaviour, never raised by the engine -----------------------------------------------------

def test_without_a_section_every_gesture_keeps_the_engines_default(tmp_path, monkeypatch):
    cfg = write_config(tmp_path, monkeypatch)
    got = automation.resolve(cfg, False, NO_MACHINE)
    assert {k: r.level for k, r in got.items()} == defaults()
    assert {r.source for r in got.values()} == {"default"}
    assert list(got) == [a.id for a in gestures.CATALOGUE]


def test_without_any_config_json_the_defaults_hold(tmp_path, monkeypatch):
    monkeypatch.delenv("BRAIN_CONFIG")
    cfg = config.Config(None, tmp_path)
    assert levels(cfg) == defaults()


def test_the_list_without_a_section_is_the_catalogue(tmp_path, monkeypatch):
    cfg = write_config(tmp_path, monkeypatch)
    assert automation.catalogue(automation.resolve(cfg, False, NO_MACHINE)) == gestures.catalogue()


# --- config.json's section ------------------------------------------------------------------------------------------

def test_the_section_sets_a_level_within_the_ceiling(tmp_path, monkeypatch):
    cfg = write_config(tmp_path, monkeypatch, {"v": 1, "levels": {"session-archive": "auto", "release-tag": "manual",
                                                                  "usage-allow": "ask"}})
    got = automation.resolve(cfg, False, NO_MACHINE)
    assert (got["session-archive"].level, got["session-archive"].source) == ("auto", "config")
    assert got["release-tag"].level == "manual" and got["usage-allow"].level == "ask"
    assert got["engine-clone-pull"].source == "default"
    assert got["session-archive"].steps == ("the engine's default: ask", f"config.json ({cfg.file}): auto")


@pytest.mark.parametrize("gesture, asked", [
    ("merge-go", "auto"),            # above its ceiling, ask
    ("uninstall", "ask"),            # above its ceiling, manual
    ("vault-open", "auto"),          # the floor's
    ("automation-raise", "ask"),     # raising a level is the floor's
    ("session-archive", "always"),   # no level
    ("session-archive", 3),          # not a string
    ("session-archive", None),
])
def test_a_level_above_its_ceiling_unknown_or_the_floors_reads_manual(tmp_path, monkeypatch, gesture, asked):
    cfg = write_config(tmp_path, monkeypatch, {"v": 1, "levels": {gesture: asked}})
    r = automation.resolve(cfg, False, NO_MACHINE)[gesture]
    assert (r.level, r.source) == ("manual", "config")
    assert "read as manual" in r.steps[-1]


def test_an_unknown_gesture_id_is_ignored(tmp_path, monkeypatch):
    cfg = write_config(tmp_path, monkeypatch, {"v": 1, "levels": {"a-newer-gesture": "auto"}})
    assert levels(cfg) == defaults()
    layer = automation.config_layer(cfg)
    assert layer.notes == [f"{cfg.file} automation.levels 'a-newer-gesture': no gesture of this engine's catalogue, "
                           "ignored (brain automation list)"]


@pytest.mark.parametrize("section", [
    {"v": 2, "levels": {"session-archive": "auto"}},   # a newer brain's section
    {"v": "1", "levels": {}},
    {"v": True, "levels": {"session-archive": "auto"}},   # a bool is no version (True == 1 in Python)
    {"v": 1, "levels": ["session-archive"]},
    "auto",
    {"v": None},
    [],
])
def test_a_section_this_engine_cannot_read_makes_every_gesture_manual(tmp_path, monkeypatch, section):
    cfg = write_config(tmp_path, monkeypatch, section)
    got = automation.resolve(cfg, False, NO_MACHINE)
    assert {r.level for r in got.values()} == {"manual"}
    assert {r.source for r in got.values()} == {"config"}
    assert "fail closed" in got["engine-clone-pull"].steps[-1]


def test_a_newer_section_says_brain_update(tmp_path, monkeypatch):
    cfg = write_config(tmp_path, monkeypatch, {"v": 2})
    assert automation.config_layer(cfg).error.endswith("v2 is written by a newer brain, which this one cannot read: "
                                                       "brain update")


@pytest.mark.parametrize("text", ["{not json", "[1, 2]"])
def test_an_unreadable_config_json_makes_every_gesture_manual(tmp_path, monkeypatch, text):
    f = tmp_path / "config.json"
    f.write_text(text, encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(f))
    cfg = config.load()
    assert cfg.error
    assert set(levels(cfg).values()) == {"manual"}


def test_brain_config_naming_no_file_makes_every_gesture_manual(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_CONFIG", str(tmp_path / "missing.json"))
    assert set(levels(config.load()).values()) == {"manual"}


def test_a_config_json_above_this_engines_v_makes_every_gesture_manual(tmp_path, monkeypatch):
    f = tmp_path / "config.json"
    f.write_text(json.dumps({"v": 2, "identity": {"owner": "Ada"}, "automation": {"v": 1, "levels": {}}}),
                 encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(f))
    assert set(levels(config.load()).values()) == {"manual"}


# --- BRAIN_CONFIG never raises a level: the config.json found without it holds too -----------------------------------

def test_a_config_named_by_brain_config_never_raises_above_the_anchored_one(tmp_path, monkeypatch):
    real = write_config(tmp_path, monkeypatch, {"v": 1, "levels": {"session-archive": "ask", "release-tag": "ask"}},
                        name="real.json")
    worktree = write_config(tmp_path, monkeypatch, {"v": 1, "levels": {"session-archive": "auto",
                                                                       "release-tag": "manual"}})
    got = automation.resolve(worktree, real, NO_MACHINE)
    assert got["session-archive"].level == "ask"      # the anchor's lower level holds
    assert got["release-tag"].level == "manual"       # lowering through BRAIN_CONFIG is anyone's
    assert got["session-archive"].steps[-1].endswith("the lower holds")


def test_an_unreadable_anchor_makes_every_gesture_manual(tmp_path, monkeypatch):
    broken = tmp_path / "real.json"
    broken.write_text("{", encoding="utf-8")
    anchor = config._read(broken)
    cfg = write_config(tmp_path, monkeypatch, {"v": 1, "levels": {"session-archive": "auto"}})
    assert set(levels(cfg, anchor=anchor).values()) == {"manual"}


def test_the_anchor_is_read_when_brain_config_names_another_file(tmp_path, monkeypatch):
    """resolve() with no anchor given reads brain.config.anchored: the config.json in the places found without
    BRAIN_CONFIG (here $CLAUDE_BRAIN_DIR)."""
    home = tmp_path / "brain"
    home.mkdir()
    (home / "config.json").write_text(json.dumps({"v": 1, "identity": {"owner": "Ada"}, "automation": {
        "v": 1, "levels": {"session-archive": "ask"}}}), encoding="utf-8")
    monkeypatch.setenv("CLAUDE_BRAIN_DIR", str(home))
    cfg = write_config(tmp_path, monkeypatch, {"v": 1, "levels": {"session-archive": "auto"}}, name="wt.json")
    assert automation.resolve(cfg, None, NO_MACHINE)["session-archive"].level == "ask"


# --- the machine file: it may only lower ----------------------------------------------------------------------------

def test_the_machine_file_lowers_a_level(tmp_path, monkeypatch):
    cfg = write_config(tmp_path, monkeypatch, {"v": 1, "levels": {"session-archive": "auto"}})
    mach = machine(tmp_path, {"v": 1, "levels": {"session-archive": "ask", "engine-clone-pull": "manual"}})
    got = automation.resolve(cfg, False, mach)
    assert (got["session-archive"].level, got["session-archive"].source) == ("ask", "machine")
    assert (got["engine-clone-pull"].level, got["engine-clone-pull"].source) == ("manual", "machine")
    assert got["session-archive"].steps[-1].endswith(": ask, lowers it")


def test_the_machine_file_never_raises_a_level(tmp_path, monkeypatch):
    cfg = write_config(tmp_path, monkeypatch, {"v": 1, "levels": {"release-tag": "manual"}})
    mach = machine(tmp_path, {"levels": {"release-tag": "ask", "session-archive": "auto", "usage-allow": "manual"}})
    got = automation.resolve(cfg, False, mach)
    assert (got["release-tag"].level, got["release-tag"].source) == ("manual", "config")
    assert (got["session-archive"].level, got["session-archive"].source) == ("ask", "default")
    assert "ignored (it may only lower)" in got["session-archive"].steps[-1]
    assert got["usage-allow"].steps[-1].endswith("manual, the same")


def test_an_unknown_level_in_the_machine_file_lowers_to_manual(tmp_path, monkeypatch):
    cfg = write_config(tmp_path, monkeypatch)
    got = automation.resolve(cfg, False, machine(tmp_path, {"v": 1, "levels": {"session-archive": "later"}}))
    assert (got["session-archive"].level, got["session-archive"].source) == ("manual", "machine")


@pytest.mark.parametrize("text", ["{", "[]", json.dumps({"v": 2, "levels": {}}), json.dumps({"levels": "ask"})])
def test_an_unreadable_machine_file_makes_every_gesture_manual(tmp_path, monkeypatch, text):
    cfg = write_config(tmp_path, monkeypatch, {"v": 1, "levels": {"session-archive": "auto"}})
    got = automation.resolve(cfg, False, machine(tmp_path, text))
    assert {r.level for r in got.values()} == {"manual"} and {r.source for r in got.values()} == {"machine"}


def test_the_machine_file_is_read_from_brain_home(tmp_path, monkeypatch, brain_home):
    cfg = write_config(tmp_path, monkeypatch)
    assert automation.machine_file() == brain_home / "automation.json"
    assert not automation.machine_layer().present
    brain_home.mkdir(parents=True, exist_ok=True)
    (brain_home / "automation.json").write_text(json.dumps({"v": 1, "levels": {"engine-clone-pull": "ask"}}),
                                                encoding="utf-8")
    assert automation.resolve(cfg, False)["engine-clone-pull"].level == "ask"
    assert automation.level("engine-clone-pull", cfg) == "ask"
    assert automation.level("a-newer-gesture", cfg) == "manual"


def test_the_machine_files_unknown_ids_and_keys_are_notes(tmp_path):
    layer = machine(tmp_path, {"v": 1, "levels": {"a-newer-gesture": "ask"}, "until": "2027-01-01"})
    assert not layer.error and len(layer.notes) == 2


# --- brain config --check and brain check ---------------------------------------------------------------------------

def test_a_valid_section_passes_the_check(tmp_path, monkeypatch):
    write_config(tmp_path, monkeypatch, {"v": 1, "levels": {"session-archive": "auto", "release-tag": "ask",
                                                            "vault-open": "manual"}})
    assert config.check() == []


def test_a_floor_gesture_above_manual_is_an_error_in_both_modes(tmp_path, monkeypatch):
    write_config(tmp_path, monkeypatch, {"v": 1, "levels": {"vault-open": "ask"}})
    msg = ("config.json: automation.levels 'vault-open': ask, but vault-open is the floor's (keys): no config lifts "
           "it, it reads manual (set it to manual or remove it)")
    assert config.check() == [msg]
    monkeypatch.setenv("BRAIN_STRICT", "0")
    assert config.check() == [msg]


@pytest.mark.parametrize("levels_, part", [
    ({"a-newer-gesture": "auto"}, "no gesture of this engine's catalogue, ignored"),
    ({"session-archive": "always"}, "'always' is no level (manual, ask, auto): it reads manual"),
    ({"merge-go": "auto"}, "auto is above its ceiling, ask: it reads manual"),
])
def test_an_unknown_id_or_level_or_one_above_its_ceiling_is_a_note_then_an_error_in_strict(
        tmp_path, monkeypatch, capsys, levels_, part):
    write_config(tmp_path, monkeypatch, {"v": 1, "levels": levels_})
    errors = config.check()
    assert len(errors) == 1 and part in errors[0]
    monkeypatch.setenv("BRAIN_STRICT", "0")
    schema._NOTED.clear()
    assert config.check() == []
    assert part in capsys.readouterr().err


def test_a_retired_id_is_named_so(tmp_path, monkeypatch):
    monkeypatch.setattr(gestures, "RETIRED", ("an-old-gesture",))
    write_config(tmp_path, monkeypatch, {"v": 1, "levels": {"an-old-gesture": "ask"}})
    assert "a retired gesture, ignored" in config.check()[0]


@pytest.mark.parametrize("section, part", [
    ({"levels": {}}, "missing"),                          # v is required
    ({"v": 2, "levels": {}}, "must be 1"),
    ({"v": 1, "levels": {"session-archive": 1}}, "session-archive"),
    ({"v": 1, "levels": [], }, "levels"),
    ({"v": 1, "levels": {}, "notify": True}, "notify"),   # strict: a newer brain's key is an error
])
def test_the_schema_refuses_a_malformed_section(tmp_path, monkeypatch, section, part):
    write_config(tmp_path, monkeypatch, section)
    errors = config.check()
    assert errors and any(part in e for e in errors), errors


def test_a_section_this_engine_cannot_read_is_an_error_of_the_check(tmp_path, monkeypatch):
    """A v the schema's const lets through (true == 1) still reads every gesture manual: the check says so."""
    write_config(tmp_path, monkeypatch, {"v": True, "levels": {}})
    assert "config.json: automation: v is True, not 1 (every gesture reads manual)" in config.check()


def test_brain_check_reads_the_section(tmp_path, monkeypatch):
    """brain check's registry check (commands._stores.check_registry) adds config.check's errors: the floor's."""
    from brain.commands import _stores
    write_config(tmp_path, monkeypatch, {"v": 1, "levels": {"elevated": "auto"}})
    (tmp_path / "projects.yaml").write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(tmp_path / "projects.yaml"))
    assert any("automation.levels 'elevated'" in e for e in config.check(tmp_path))
    assert _stores.check_registry(tmp_path, []) == 1


# --- the format: an older engine's file, a newer one's, the round trip -----------------------------------------------

def test_the_newer_fixture_reads_its_known_levels_and_ignores_the_rest(tmp_path, monkeypatch, capsys):
    """config/v1/newer.json holds a newer brain's automation section: a gesture this engine does not know and a key
    of the section it does not know. Read mode reads the known level, notes the rest, and keeps the file as written."""
    monkeypatch.setenv("BRAIN_STRICT", "0")
    f = tmp_path / "config.json"
    f.write_bytes((FIXTURES / "newer.json").read_bytes())
    (tmp_path / "projects.yaml").write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(f))
    cfg = config.load()
    got = automation.resolve(cfg, False, NO_MACHINE)
    assert (got["engine-clone-pull"].level, got["engine-clone-pull"].source) == ("auto", "config")
    assert {k: r.level for k, r in got.items() if k != "engine-clone-pull"} == \
        {k: v for k, v in defaults().items() if k != "engine-clone-pull"}
    notes = automation.config_layer(cfg).notes
    assert any("'a-newer-gesture'" in n for n in notes) and any("'notify'" in n for n in notes)
    assert config.check() == []
    assert f.read_bytes() == (FIXTURES / "newer.json").read_bytes()


def test_the_older_fixture_has_no_section_and_reads_the_defaults(tmp_path, monkeypatch):
    f = tmp_path / "config.json"
    f.write_bytes((FIXTURES / "older.json").read_bytes())
    monkeypatch.setenv("BRAIN_CONFIG", str(f))
    assert "automation" not in config.load().data
    assert levels(config.load()) == defaults()


def test_every_frozen_config_reads_the_defaults(tmp_path, monkeypatch):
    """What each released engine wrote (config/v1/<tag>.json) holds no section: every gesture keeps its default."""
    frozen = sorted(FIXTURES.glob("v*.json"))
    assert frozen
    for f in frozen:
        monkeypatch.setenv("BRAIN_CONFIG", str(f))
        assert levels(config.load()) == defaults(), f.name


def test_the_section_round_trips(tmp_path, monkeypatch):
    section = {"v": 1, "levels": {"session-archive": "auto", "usage-allow": "ask"}}
    cfg = write_config(tmp_path, monkeypatch, section)
    again = json.loads(json.dumps(cfg.data))
    assert again["automation"] == section
    (tmp_path / "again.json").write_text(json.dumps(again), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(tmp_path / "again.json"))
    assert levels(config.load()) == levels(cfg)


def test_the_schema_documents_the_section():
    keys = dict(config.keys())
    assert "automation.v" in keys and "automation.levels" in keys and "machine file" in keys["automation"]


# --- brain automation explain and list --------------------------------------------------------------------------------

def test_explain_json_gives_the_layers_and_each_gestures_steps(tmp_path, monkeypatch, capsys, brain_home):
    write_config(tmp_path, monkeypatch, {"v": 1, "levels": {"session-archive": "auto"}})
    brain_home.mkdir(parents=True, exist_ok=True)
    (brain_home / "automation.json").write_text(json.dumps({"v": 1, "levels": {"session-archive": "ask"}}),
                                                encoding="utf-8")
    assert cli.main(["automation", "explain", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [x["name"] for x in data["layers"]] == ["config", "machine"]
    assert data["section_v"] == 1 and data["levels"] == list(gestures.LEVELS)
    assert [g["id"] for g in data["gestures"]] == [a.id for a in gestures.CATALOGUE]
    arch = next(g for g in data["gestures"] if g["id"] == "session-archive")
    assert (arch["level"], arch["source"], arch["config"], arch["machine"]) == ("ask", "machine", "auto", "ask")
    assert len(arch["steps"]) == 3


def test_explain_one_gesture_as_text(tmp_path, monkeypatch, capsys):
    write_config(tmp_path, monkeypatch, {"v": 1, "levels": {"vault-open": "auto"}})
    assert cli.main(["automation", "explain", "vault-open"]) == 0
    out = capsys.readouterr().out
    assert "vault-open: manual (config)  ceiling manual  runs: terminal  locked: keys" in out
    assert "1. the engine's default: manual" in out and "read as manual (the floor's: keys)" in out
    assert "note: " in out and out.rstrip().endswith("(docs/automation.md).")
    assert "the machine file: none (" in out


def test_explain_an_unknown_gesture_exits_1(capsys):
    assert cli.main(["automation", "explain", "a-newer-gesture"]) == 1
    assert "'a-newer-gesture' is no gesture of the catalogue" in capsys.readouterr().err


def test_list_shows_each_levels_source(tmp_path, monkeypatch, capsys):
    write_config(tmp_path, monkeypatch, {"v": 1, "levels": {"session-archive": "auto"}})
    assert cli.main(["automation", "list", "--json"]) == 0
    arch = next(g for g in json.loads(capsys.readouterr().out)["gestures"] if g["id"] == "session-archive")
    assert (arch["level"], arch["source"]) == ("auto", "config")
    assert cli.main(["automation", "list"]) == 0
    assert "session-archive" in capsys.readouterr().out
