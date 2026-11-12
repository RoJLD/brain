"""wi-brain-command-plugins-cockpit: a plugged project's cockpit panels and tabs, declared as data (brain.plugin_panels,
brain.cockpit's plug): its columns, sorts, filters, help and title in the cockpit's own tables, so the search, the
views, the text view and the detail work on it with no Textual code of the plugin's."""

import json

import pytest

from brain import cli, cockpit, detail, plugin_panels, projects

DECL = {
    "v": 1,
    "panels": {
        "runs": {"title": {"en": "Runs", "fr": "Exécutions"}, "rows": "out/runs.json",
                 "columns": [{"key": "id", "title": "Id"}, {"key": "state", "title": "State"},
                             {"key": "sharpe", "title": "Sharpe"}],
                 "sorts": ["sharpe", "state"], "filters": {"state": ["ok", "failed"]},
                 "help": "The last backtests.", "colour": "teal"},
        "broken": {"title": "No source"},
    },
    "layout": "wide",
}
ROWS = [{"id": "r1", "state": "ok", "sharpe": 1.4}, {"id": "r2", "state": "failed", "sharpe": None},
        {"id": "r3", "state": "ok", "sharpe": 2.1}]


@pytest.fixture(autouse=True)
def _unplugged():
    yield
    cockpit.plug(plugin_panels.Plugged())  # the built-in tables back, whatever a test plugged


@pytest.fixture
def orbit(tmp_path, monkeypatch, store):
    """The registry's project demo plugs orbit_cli, whose COCKPIT declares a runs panel read from out/runs.json."""
    root = store.parents[1]
    (root / "out").mkdir(exist_ok=True)
    (root / "out" / "runs.json").write_text(json.dumps({"rows": ROWS}), encoding="utf-8")
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "orbit_cli.py").write_text("COCKPIT = " + repr(DECL) + "\n\ndef main(argv):\n    return 0\n",
                                      encoding="utf-8")
    monkeypatch.syspath_prepend(str(lib))
    reg = tmp_path / "brain" / "projects.yaml"
    reg.parent.mkdir()
    reg.write_text(f"demo: {{root: {root.as_posix()}, plugin: 'orbit_cli:main'}}\n"
                   f"other: {{root: {root.as_posix()}/other, plugin: 'missing_cli:'}}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    return root


def test_a_declaration_gives_panels_and_a_tab_and_notes_what_it_leaves_out():
    notes = []
    panels, tabs = plugin_panels.parse("Orbit Lab", "orbit_cli:", DECL, notes)
    (p,) = panels.values()
    assert p.name == "orbit-lab-runs" and p.title == {"en": "Runs", "fr": "Exécutions"}
    assert p.columns == (("id", "Id"), ("state", "State"), ("sharpe", "Sharpe")) and p.sorts == ("sharpe", "state")
    assert p.filters == {"state": ("all", "ok", "failed")} and p.rows_file == "out/runs.json"
    assert list(tabs) == ["orbit-lab"] and tabs["orbit-lab"].panels == ("orbit-lab-runs",)  # one tab, the project's
    assert any("'layout' unknown" in n for n in notes) and any("'colour' unknown" in n for n in notes)
    assert any("panel 'broken': neither rows" in n for n in notes)
    notes = []
    assert plugin_panels.parse("q", "x", ["not", "a", "mapping"], notes) == ({}, {}) and "a mapping" in notes[0]
    _, tabs = plugin_panels.parse("q", "x", {**DECL, "tabs": [{"id": "lab", "label": "Lab", "panels": ["runs"]},
                                                              {"id": "none", "panels": ["nowhere"]}]}, notes)
    assert list(tabs) == ["q-lab"] and tabs["q-lab"].label == {"en": "Lab", "fr": "Lab"}
    assert any("tab 'none' names no panel" in n for n in notes)


def test_the_registry_plugs_each_declared_panel_and_a_plugin_that_cannot_load_is_noted(orbit):
    notes = cockpit.plug_registry()
    assert list(cockpit.PLUGGED) == ["demo-runs"]
    assert any(n.startswith("other: plugin 'missing_cli:'") for n in notes)
    names = list(cockpit.TABS)
    assert names.index("demo") == names.index("settings") - 1  # after Resources, before the settings
    assert cockpit.TABS["demo"]["key"] == "" and "demo" in cockpit.built_tabs()
    assert cockpit.tab_label("demo", {}) == "demo"  # no number
    assert cockpit.COLUMNS["demo-runs"] == ("Project", "Id", "State", "Sharpe")
    assert cockpit.SORTS["demo-runs"] == ("sharpe", "state", "project")
    assert cockpit.view_of("demo-runs") == {"sort": "sharpe", "reverse": False, "state": "all"}
    assert cockpit.panel_tab("demo-runs") == "demo" and cockpit.title("demo-runs") == "Runs"
    assert "The last backtests." in cockpit.help_lines("demo-runs")[0]
    assert any(e["title"] == "Runs: sort by sharpe" for e in cockpit.palette({}))
    cockpit.plug(plugin_panels.Plugged())
    assert "demo-runs" not in cockpit.SORTS and "demo" not in cockpit.TABS and not cockpit.PLUGGED


def test_a_plugged_panel_is_read_sorted_filtered_and_searched_as_the_others(orbit):
    cockpit.plug_registry()
    cp = cockpit.Cockpit([projects.load()["demo"]])
    assert "demo-runs" in cp.refresh()
    panel = cp.snapshot()["panels"]["demo-runs"]
    assert [r["id"] for r in cockpit.shown("demo-runs", panel, {})] == ["r1", "r3", "r2"]  # numbers, an empty last
    assert [r["id"] for r in cockpit.shown("demo-runs", panel, {"sort": "sharpe", "reverse": True})] == ["r2", "r3",
                                                                                                         "r1"]
    assert [r["id"] for r in cockpit.shown("demo-runs", panel, {"state": "failed"})] == ["r2"]
    assert [r["id"] for r in cockpit.shown("demo-runs", panel, None, "2.1")] == ["r3"]  # the search: its cells
    assert cockpit.cells("demo-runs", cockpit.entries("demo-runs", panel)[1]) == ("demo", "r2", "failed", "-")
    assert cockpit.heading("demo-runs", panel) == "Runs (3)"
    assert cp.refresh() == set()  # read again at a probe only
    (orbit / "out" / "runs.json").write_text("not json", encoding="utf-8")
    assert "demo-runs" in cp.refresh(probe=True)
    snap = cp.snapshot()
    assert "JSONDecodeError" in snap["errors"]["demo-runs"]["error"] and snap["panels"]["demo-runs"] == panel  # kept
    d = detail.of("demo-runs", cockpit.entries("demo-runs", panel)[0], cp)
    assert d["title"] == "Runs" and "sharpe: 1.4" in d["sections"][0][1]
    assert detail.find(cp.snapshot()["panels"], "r3")[0] == "demo-runs"


def test_a_read_callable_gives_the_rows(orbit, tmp_path):
    (tmp_path / "lib" / "orbit_rows.py").write_text(
        "def runs(root):\n    return [{'name': 'a', 'n': 2}, {'n': 1}]\n", encoding="utf-8")
    p = plugin_panels.Panel("demo-live", "demo", "live", {"en": "Live", "fr": "Live"}, (("n", "N"),), ("n",), {},
                            id_field="name", read="orbit_rows:runs")
    rows = plugin_panels.rows(p, projects.load()["demo"])
    assert [(r["id"], r["project"]) for r in rows] == [("a", "demo"), ("#2", "demo")]  # no id: its rank
    bad = plugin_panels.Panel("demo-bad", "demo", "bad", {}, (), (), {}, rows_file="out/runs.json")
    (orbit / "out" / "runs.json").write_text('{"rows": 3}', encoding="utf-8")
    with pytest.raises(ValueError, match="a list of objects"):
        plugin_panels.rows(bad, projects.load()["demo"])


def test_brain_tui_prints_a_plugged_tab_and_names_what_it_left_out(orbit, capsys):
    assert cli.main(["tui", "--project", "demo", "--once", "--quick", "--tab", "demo"]) == 0
    out, err = capsys.readouterr()
    assert "\nRuns (3)\n  Project  Id  State   Sharpe\n" in out and "  demo     r2  failed  -" in out
    assert "Sessions" not in out  # that tab's panels alone
    assert "brain tui: plugin: other: plugin 'missing_cli:'" in err
    with pytest.raises(SystemExit, match="--tab nowhere: one of overview"):
        cli.main(["tui", "--project", "demo", "--once", "--tab", "nowhere"])
    assert cli.main(["tui", "--project", "demo", "--once", "--quick", "--sort", "demo-runs:-state"]) == 0
    assert "Runs (3) [sort state reversed]" in capsys.readouterr().out  # the views work on it too
