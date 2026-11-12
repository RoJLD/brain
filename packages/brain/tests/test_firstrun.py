"""brain init's three screens (wi-brain-modules-installer; SIGMA-18): who you are (a preset of the catalogue, a
persona of a private one), your machine (what runs here), adjust (the boxes, their costs and dependencies); then the
plan as brain commands, each run and logged at --apply; offline, nothing written but through those commands."""

import json
import re

import pytest

from brain import __version__, catalogue, cli, firstrun, init, probe, skew, tiers

TIERS = """\
capabilities:
  base:
    title: the base
    class: core
    profile: lite
    provides: [base]
    requires: []
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
    resources: {ram_mb: 2048}
    fallback: the local probe
    recommend_when: [memory_gb >= 7]
    depends_on: [store]
  viewer:
    title: a viewer
    class: extra
    profile: custom
    provides: [viewer]
    requires: []
    resources: {vram_gb: 4}
    fallback: the text view
    depends_on: [agent]
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
    requires: [finder-tool]
    resources: {}
    fallback: nothing found
"""
BIG = {"os": "linux", "arch": "x86_64", "cpu_cores": 8, "memory_gb": 15.6, "gpu": True, "gpu_vram_gb": 8.0,
       "disk_free_gb": 100.0, "docker": True}
SMALL = {**BIG, "memory_gb": 1.5, "gpu": False, "gpu_vram_gb": 0.0, "docker": False}


@pytest.fixture
def engine(tmp_path, monkeypatch, brain_home):
    """The engine's capabilities replaced by TIERS, the probe's facts by BIG; an empty folder to become a brain."""
    f = tmp_path / "tiers.yaml"
    f.write_text(TIERS, encoding="utf-8")
    real = tiers.capabilities
    monkeypatch.setattr(tiers, "capabilities", lambda path=f: real(path))
    monkeypatch.setattr(firstrun, "facts_of", lambda root: dict(BIG))
    monkeypatch.setattr(tiers, "machine_facts", lambda *a, **k: dict(BIG))   # brain profile set recommended's
    monkeypatch.setattr(probe, "collect", lambda **k: {})
    monkeypatch.delenv("BRAIN_CONFIG", raising=False)
    monkeypatch.setenv("BRAIN_PROJECTS", str(tmp_path / "none.yaml"))
    monkeypatch.setattr(init, "machine_terms", lambda: {"users": ["ada-l"], "hosts": ["host-a"]})
    monkeypatch.setattr(skew, "running", lambda: [skew.Engine(d, __version__, f"v{__version__}", "0" * 40)
                                                  for d, _ in skew.DISTS])
    root = tmp_path / "ada-brain"
    root.mkdir()
    return root


def cat_of(root):
    return firstrun.catalogue_for(root)[0]


# --- the machine ------------------------------------------------------------------------------------------------------

def test_what_runs_here_is_the_requirements_and_the_costs(engine):
    mods = {m["id"]: m for m in cat_of(engine)["modules"]}
    assert firstrun.fit(mods["agent"], BIG).runs is True and firstrun.fit(mods["agent"], BIG).recommended
    small = firstrun.fit(mods["agent"], SMALL)
    assert small.runs is False and small.why == ["requires docker", "needs 2048 MiB of RAM, has 1536.0"]
    assert not small.recommended
    unknown = firstrun.fit(mods["viewer"], {**BIG, "gpu_vram_gb": None})
    assert unknown.runs is None and unknown.why == ["gpu_vram_gb unknown (needs 4 GiB of VRAM)"]


def test_an_env_requirement_is_read_from_the_environment(monkeypatch):
    m = {"id": "x", "name": "x", "requires": ["env:EXAMPLE_KEY"]}
    monkeypatch.delenv("EXAMPLE_KEY", raising=False)
    assert firstrun.fit(m, {}).runs is False
    monkeypatch.setenv("EXAMPLE_KEY", "set")
    assert firstrun.fit(m, {}).runs is True


# --- who you are and adjust -------------------------------------------------------------------------------------------

def test_a_preset_turns_on_its_modules_and_what_fits_here(engine):
    cat = cat_of(engine)
    assert firstrun.base_set(cat, firstrun._preset(cat, "lite"), BIG) == ["base"]
    assert firstrun.base_set(cat, firstrun._preset(cat, "default"), BIG) == ["base", "store"]
    assert firstrun.base_set(cat, firstrun._preset(cat, "recommended"), BIG) == ["base", "store", "agent"]
    assert firstrun.base_set(cat, firstrun._preset(cat, "recommended"), SMALL) == ["base", "store"]


def test_a_box_ticked_pulls_its_hard_dependencies(engine):
    ch = firstrun.choose(cat_of(engine), "lite", BIG, with_=["viewer"])
    assert ch.on == ["base", "viewer", "agent", "store"] and ch.pulled == {"agent": "viewer", "store": "viewer"}
    assert ch.base == "lite" and ch.added == ["viewer", "agent", "store"] and ch.removed == []
    assert ch.fetch == ["extra-store"]


def test_a_box_unticked_and_the_order_of_the_steps(engine):
    """Leaving out the agent and the store of Recommended: the agent first (it needs the store)."""
    ch = firstrun.choose(cat_of(engine), "recommended", BIG, without=["store", "agent"])
    assert ch.on == ["base"] and ch.removed == ["agent", "store"] and ch.added == []
    steps = firstrun.steps(engine, ch)
    at = ["brain", "--root", str(engine)]
    assert steps == [[*at, "profile", "set", "recommended", "--apply"], [*at, "mod", "disable", "agent", "--apply"],
                     [*at, "mod", "disable", "store", "--apply"]]


@pytest.mark.parametrize("with_,without,facts,why", [
    (["nothing"], [], BIG, "--with nothing: no module 'nothing'"),
    (["later"], [], BIG, "--with later: planned"),
    (["finder"], [], BIG, "--with finder: used whenever it is found (auto)"),
    (["agent"], [], SMALL, "--with agent: this machine does not hold it (requires docker"),
    (["viewer"], [], {**BIG, "docker": False}, "viewer needs agent, which this machine does not hold"),
    ([], ["base"], BIG, "--without base: core, never off"),
    ([], ["finder"], BIG, "--without finder: auto, never off"),
    (["viewer"], ["store"], BIG, "--without store: needed by viewer"),
    ([], ["nothing"], BIG, "--without nothing: no module 'nothing'"),
])
def test_what_the_catalogue_or_the_machine_refuses(engine, with_, without, facts, why):
    with pytest.raises(firstrun.SetupError, match=re.escape(why)):
        firstrun.choose(cat_of(engine), "lite", facts, with_=with_, without=without)


def test_an_unknown_fact_is_chosen_not_checked(engine):
    ch = firstrun.choose(cat_of(engine), "default", {**BIG, "gpu_vram_gb": None}, with_=["viewer"])
    assert "viewer" in ch.on and any("chosen, not checked" in n for n in ch.notes)


def test_a_persona_of_a_private_catalogue_is_offered_on_its_base(engine, tmp_path):
    mine = tmp_path / "mine.json"
    mine.write_text(json.dumps({
        "schema": "catalogue/v1", "generated": {"at": "2026-01-01T00:00:00Z", "by": "example 1"},
        "modules": [{"id": "viewer", "name": "Viewer"}, {"id": "agent", "name": "Agent"},
                    {"id": "elsewhere", "name": "Elsewhere"}],
        "presets": [{"id": "lite", "name": "Lite", "modules": []},
                    {"id": "watcher", "name": "Watcher", "kind": "persona", "base": "lite",
                     "modules": ["viewer", "elsewhere"]},
                    {"id": "odd", "name": "Odd", "kind": "persona", "modules": ["viewer"]}]}), encoding="utf-8")
    cat, notes = firstrun.catalogue_for(engine, mine)
    assert [p["id"] for p in cat["presets"]] == ["lite", "default", "recommended", "watcher"]
    assert any("persona watcher: elsewhere not in this brain's catalogue" in n for n in notes)
    assert any("persona odd: base None is not a base" in n for n in notes)
    ch = firstrun.choose(cat, "watcher", BIG)
    assert ch.base == "lite" and ch.on == ["base", "viewer", "agent", "store"]


def test_a_private_catalogue_that_does_not_hold_to_the_contract_is_refused(engine, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "catalogue/v1", "modules": []}), encoding="utf-8")
    with pytest.raises(firstrun.SetupError, match="missing 'generated'"):
        firstrun.catalogue_for(engine, bad)


def test_the_costs_and_the_downloads(engine):
    c = firstrun.cost(cat_of(engine), ["base", "store", "agent"])
    assert c == {"ram_mb": 2048.0, "disk_mb": 80.0, "vram_gb": 0.0, "download_mb": 0.0, "fetch": ["extra-store"]}


# --- the screens -----------------------------------------------------------------------------------------------------

def test_the_three_screens_say_what_runs_costs_and_needs(engine):
    cat = cat_of(engine)
    ch = firstrun.choose(cat, "default", SMALL)
    text = "\n".join(firstrun.render_presets(cat, SMALL) + firstrun.render_machine(cat, SMALL)
                     + firstrun.render_adjust(cat, ch, SMALL))
    assert "1. Who you are: a preset" in text and "  2. default (" in text
    assert "agent            does not run here (requires docker; needs 2048 MiB of RAM, has 1536.0)" in text
    assert "[*]    base" in text and "[x]    store" in text and "(download: extra-store)" in text
    assert "later            planned, not built yet" in text
    assert "finder" in text and "not found here, its fallback serves" in text
    assert "total: disk 80 MiB; to download (not here: offline): extra-store" in text


# --- brain init ------------------------------------------------------------------------------------------------------

def test_the_plan_shows_the_screens_the_steps_and_the_same_command(engine, capsys):
    assert cli.main(["init", str(engine), "--owner", "Ada", "--preset", "default", "--with", "agent"]) == 0
    out = capsys.readouterr().out
    assert "3. Adjust (preset default)" in out
    assert f"  brain --root {engine} profile set default --apply" in out
    assert f"  brain --root {engine} mod enable agent --apply" in out
    assert f"the same, without the screens: brain init {engine} --owner Ada --preset default --with agent --apply" \
        in out
    assert not (engine / "config.json").exists() and not list(firstrun.paths.ledger_dir().glob("setup-*"))


def test_apply_runs_each_step_logs_it_and_a_second_apply_changes_nothing(engine, capsys):
    args = ["init", str(engine), "--owner", "Ada", "--preset", "recommended", "--without", "agent", "--apply"]
    assert cli.main(args) == 0
    out = capsys.readouterr().out
    assert f"ok (0): brain --root {engine} profile set recommended --apply" in out
    assert f"ok (0): brain --root {engine} mod disable agent --apply" in out
    assert json.loads((engine / "config.json").read_text(encoding="utf-8"))["tier"] == {"base": "default"}
    machine = json.loads(tiers.machine_file().read_text(encoding="utf-8"))
    assert machine["base"] == "recommended"
    reg, _ = tiers.registry(engine)
    assert "agent" not in tiers.active(reg, tiers.choice(engine))[0]   # frozen on by Recommended, then off
    rows = [json.loads(x) for f in firstrun.paths.ledger_dir().glob("setup-*.jsonl")
            for x in f.read_text(encoding="utf-8").splitlines()]
    assert [r["command"].split()[3:5] if r["command"].startswith("brain --root") else ["init"] for r in rows] == [
        ["init"], ["profile", "set"], ["mod", "disable"]]
    assert all(r["event"] == "setup-step" and r["via"] == "init" and r["exit"] == 0 for r in rows)
    before = tiers.machine_file().read_text(encoding="utf-8")
    assert cli.main(args) == 0
    out = capsys.readouterr().out
    assert "keep     config.json" in out and "this machine is already as chosen: no step run" in out
    assert tiers.machine_file().read_text(encoding="utf-8") == before   # not written again, not even its date


def test_a_refused_choice_plans_nothing(engine, capsys):
    assert cli.main(["init", str(engine), "--owner", "Ada", "--preset", "lite", "--without", "base"]) == 2
    assert "brain init: --without base: core, never off" in capsys.readouterr().out
    assert cli.main(["init", str(engine), "--owner", "Ada", "--preset", "nobody"]) == 2
    assert "no preset 'nobody'" in capsys.readouterr().out


def test_a_failed_step_stops_the_others(engine, capsys, monkeypatch):
    real = firstrun.run

    def failing(words, cwd, runner=None, by=""):
        return real(words, cwd, (lambda argv: 3) if "enable" in words else None, by)
    monkeypatch.setattr(firstrun, "run", failing)
    assert cli.main(["init", str(engine), "--owner", "Ada", "--preset", "lite", "--with", "store", "--apply"]) == 1
    assert f"FAILED (3): brain --root {engine} mod enable store --apply" in capsys.readouterr().out


def test_without_the_screens_init_is_as_before_and_names_them(engine, capsys):
    assert cli.main(["init", str(engine), "--owner", "Ada"]) == 0
    out = capsys.readouterr().out
    assert "1. Who you are" not in out and "brain init --interactive (who you are, your machine, adjust)" in out


def test_interactive_asks_the_three_screens_then_applies(engine, capsys, monkeypatch):
    answers = iter(["9", "default", "", "+viewer -nothing", "+viewer", "+later", "-store", "", "y"])
    monkeypatch.setattr(firstrun, "ASK", lambda prompt: next(answers))
    monkeypatch.setattr(firstrun, "tty", lambda: True)
    assert cli.main(["init", str(engine), "--owner", "Ada", "--interactive"]) == 0
    out = capsys.readouterr().out
    assert "refused: no preset '9'" in out and "refused: --with later: planned" in out
    assert "refused: --without nothing: no module 'nothing'" in out
    assert "refused: --without store: needed by viewer" in out
    assert (f"the same, without the screens: brain init {engine} --owner Ada --preset default --with viewer "
            "--apply") in out
    assert f"ok (0): brain --root {engine} mod enable viewer --apply" in out
    assert json.loads(tiers.machine_file().read_text(encoding="utf-8"))["components"].get("viewer") is True


def test_interactive_needs_a_terminal(engine, capsys, monkeypatch):
    monkeypatch.setattr(firstrun, "tty", lambda: False)
    assert cli.main(["init", str(engine), "--owner", "Ada", "-i"]) == 2
    assert "--interactive needs a terminal" in capsys.readouterr().out


def test_the_catalogue_read_is_the_brains_own_emit(engine):
    """The screens read brain catalogue emit's document: one catalogue for the installer and the Modules tab."""
    cat = cat_of(engine)
    assert catalogue.validate(cat)[0] == [] and cat["schema"] == catalogue.ID


# --- the review's cases ----------------------------------------------------------------------------------------------

def test_a_recommended_module_whose_dependency_does_not_run_is_left_out():
    """As tiers.recommend: rec2 is recommended, but it needs agent, which this machine does not hold."""
    cat = {"modules": [{"id": "agent", "name": "a", "class": "service", "requires": ["docker"]},
                       {"id": "rec2", "name": "r", "class": "extra", "depends_on": ["agent"]}],
           "presets": [{"id": "recommended", "name": "R", "kind": "base", "modules": [], "when_fits": ["rec2"]}]}
    assert firstrun.base_set(cat, cat["presets"][0], SMALL) == []
    assert firstrun.choose(cat, "recommended", SMALL).on == []


def _persona_file(tmp_path):
    mine = tmp_path / "mine.json"
    mine.write_text(json.dumps({
        "schema": "catalogue/v1", "generated": {"at": "2026-01-01T00:00:00Z", "by": "example 1"},
        "modules": [{"id": "viewer", "name": "Viewer"}],
        "presets": [{"id": "lite", "name": "Lite", "modules": []},
                    {"id": "watcher", "name": "Watcher", "kind": "persona", "base": "lite", "modules": ["viewer"]}]}),
        encoding="utf-8")
    return mine


def test_a_persona_module_the_machine_does_not_hold_is_refused(engine, tmp_path):
    cat, _ = firstrun.catalogue_for(engine, _persona_file(tmp_path))
    with pytest.raises(firstrun.SetupError, match="persona watcher: viewer: this machine does not hold it"):
        firstrun.choose(cat, "watcher", {**BIG, "gpu_vram_gb": 1.0})


def test_the_tier_is_the_chosen_presets_base(engine, tmp_path, capsys):
    """A persona on lite writes tier.base lite; --tier still wins."""
    assert cli.main(["init", str(engine), "--owner", "Ada", "--catalogue", str(_persona_file(tmp_path)),
                     "--preset", "watcher", "--apply"]) == 0
    assert json.loads((engine / "config.json").read_text(encoding="utf-8"))["tier"] == {"base": "lite"}
    assert "(person, lite)" in capsys.readouterr().out


def test_interactive_writes_the_tier_of_the_preset_it_picked(engine, capsys, monkeypatch):
    answers = iter(["default", "", "", "y"])
    monkeypatch.setattr(firstrun, "ASK", lambda prompt: next(answers))
    monkeypatch.setattr(firstrun, "tty", lambda: True)
    assert cli.main(["init", str(engine), "--owner", "Ada", "-i"]) == 0
    assert json.loads((engine / "config.json").read_text(encoding="utf-8"))["tier"] == {"base": "default"}


def test_a_closed_input_cancels_with_nothing_written(engine, capsys, monkeypatch):
    def eof(prompt):
        raise EOFError
    monkeypatch.setattr(firstrun, "ASK", eof)
    monkeypatch.setattr(firstrun, "tty", lambda: True)
    assert cli.main(["init", str(engine), "--owner", "Ada", "-i", "--apply"]) == 2
    assert "brain init: cancelled, nothing written" in capsys.readouterr().out
    assert not (engine / "config.json").exists()


def test_a_step_that_raises_is_logged_as_a_failure(engine, tmp_path):
    def boom(argv):
        raise OSError("disk full")
    r = firstrun.run(["brain", "profile", "set", "lite", "--apply"], tmp_path, runner=boom, by="Ada")
    assert r["exit"] == 1 and "OSError: disk full" in r["output"]
    [row] = [json.loads(x) for f in firstrun.paths.ledger_dir().glob("setup-*.jsonl")
             for x in f.read_text(encoding="utf-8").splitlines()]
    assert row["exit"] == 1 and row["by"] == "Ada"


def test_the_log_names_the_new_brains_owner(engine):
    assert cli.main(["init", str(engine), "--owner", "Ada", "--preset", "lite", "--apply"]) == 0
    rows = [json.loads(x) for f in firstrun.paths.ledger_dir().glob("setup-*.jsonl")
            for x in f.read_text(encoding="utf-8").splitlines()]
    assert rows and {r["by"] for r in rows} == {"Ada"}
