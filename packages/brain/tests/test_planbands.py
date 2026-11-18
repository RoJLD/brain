"""wi-brain-tui-trajectories-bands: the Milestones tab's Trajectories, the Gantt as bands (brain.planbands;
spec-brain-plan-views §3.3 and §3.6; VIZ-1): one row per milestone, era and wave from the forecast's latest.json, never
recomputed, sorted by its median; p10-p80, p80-p90 and the median as shapes; the 6-week horizon; the gates; « (no
milestone) » and the backlog's flow; the text twin (brain tui --once --tab milestones --view trajectories)."""

import json

import pytest
from brain import cli, cockpit, forecast, planbands, projects, resume
from test_planviews import EDGES, NODES  # the fixture graph of the Tree

FCB = {"forecast": 1, "project": "demo", "as_of": "2026-11-18T08:00+00:00",
       "calibration": {"state": "uncalibrated", "judged": 1, "needed": 5},
       "milestones": [
           {"id": "era-demo-one", "open": 5, "shown": "partial", "days": {"p10": 10, "p50": 20, "p80": 35, "p90": 50},
            "gates": ["go/no-go ddr-go"], "held": "", "undated": [], "durations": []},
           {"id": "ms-demo-core", "open": 3, "shown": "range", "days": {"p10": 2, "p50": 5, "p80": 8, "p90": 10},
            "gates": ["calendar 28 days"], "held": "", "undated": [], "durations": ["four weeks"]},
           {"id": "wave-s2", "open": 3, "shown": "range", "days": {"p10": 1, "p50": 4, "p80": 6, "p90": 9},
            "gates": ["hardware gpu-box"], "held": "", "undated": [], "durations": []},
           {"id": "ms-demo-loose", "open": 1, "shown": "undated", "days": None, "held": "", "undated": ["wi-e"],
            "part": {"days": {"p10": 3, "p50": 6, "p80": 9, "p90": 12}}, "gates": [], "durations": []},
           {"id": "ms-demo-sub", "open": 1, "shown": "undated", "days": None, "held": "external blocker: vendor",
            "undated": [], "gates": ["external acme:wi-z"], "durations": []},
           {"id": "wave-s1", "open": 0, "shown": "range", "days": {"p10": 1, "p50": 1, "p80": 1, "p90": 1}},
           {"id": "ms-demo-gone", "open": 1, "shown": "range", "days": {"p10": 1, "p50": 1, "p80": 1, "p90": 1}}],
       "no_milestone": {"open": 4, "shown": "undated", "days": None,
                        "part": {"days": {"p10": 2, "p50": 4, "p80": 7, "p90": 9}}},
       "gates": {"undated": [{"id": "wi-e", "why": "after another project: acme wi-z", "milestone": "ms-demo-loose"},
                             {"id": "wi-ext", "why": "blocked", "milestone": ""}]},
       "backlog": {"open": 9, "shown": "growing", "undated": 2, "days": None,
                   "frozen": {"days": {"p10": 2, "p50": 20, "p80": 30, "p90": 40}}},
       "flow": {"days": 20, "created_per_day": 3.5, "closed_per_day": 1.25, "growing": True}}


@pytest.fixture
def st(store):
    with (store / "nodes" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write(NODES)
    with (store / "edges" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write(EDGES)
    return resume.Store.load(store)


def _rows(st):
    b = planbands.collect(st, FCB, "demo")
    return b, {r["id"] or r["name"]: r for r in [*b["rows"], *b["tail"]]}


def test_the_rows_are_the_dated_milestones_by_median_then_their_dated_parts_then_the_undated(st):
    b, rows = _rows(st)
    assert [r["id"] for r in b["rows"]] == ["wave-s2", "ms-demo-core", "era-demo-one", "ms-demo-loose", "ms-demo-sub"]
    # the reached wave and the dropped milestone of the graph left out, though the forecast has them
    assert "wave-s1" not in rows and "ms-demo-gone" not in rows
    assert [rows[i]["name"] for i in ("wave-s2", "ms-demo-core", "era-demo-one")] == ["wave 0.2.0", "core",
                                                                                      "era-demo-one"]
    assert [rows[i]["kind"] for i in ("wave-s2", "ms-demo-core", "era-demo-one")] == ["wave", "milestone", "era"]
    loose, sub = rows["ms-demo-loose"], rows["ms-demo-sub"]
    assert loose["part"] and loose["days"]["p50"] == 6 and planbands.note_text(loose["notes"]) == (
        "⊘ dated part only: 1 after another project")
    assert sub["days"] is None and planbands.note_text(sub["notes"]) == (
        "⊘ not dated: external blocker · ⇢ external acme:wi-z")
    assert planbands.note_text(rows["era-demo-one"]["notes"]) == "◆ go/no-go ddr-go"
    assert planbands.note_text(rows["ms-demo-core"]["notes"]) == "⧗ calendar 28 days · ⧗ four weeks (not modelled)"
    assert planbands.note_text(rows["wave-s2"]["notes"]) == "⚙ hardware gpu-box"
    assert b["heading"].startswith("ranges p10–p90 UNCALIBRATED (1 of 5 judged)")
    assert b["heading"].endswith("· beyond 6 weeks: order only")


def test_no_milestone_and_the_backlog_close_the_chart(st):
    b, rows = _rows(st)
    nm, back = b["tail"]
    assert (nm["name"], nm["open"], nm["part"]) == ("(no milestone)", 4, True)
    assert planbands.note_text(nm["notes"]) == "⊘ dated part only: 1 blocked"   # the undated items of no milestone
    # growing faster than it empties: no band, its flow said
    assert back["days"] is None and planbands.note_text(back["notes"]) == (
        "in 3.5/day · out 1.25/day: does not empty at this rate")
    steady = {**FCB, "backlog": {"open": 9, "shown": "range", "days": {"p10": 2, "p50": 5, "p80": 8, "p90": 9}},
              "no_milestone": {"open": 0}}
    tail = planbands.collect(st, steady, "demo")["tail"]
    assert [r["name"] for r in tail] == ["backlog"] and tail[0]["days"]["p50"] == 5   # no item of no milestone
    assert planbands.note_text(tail[0]["notes"]) == "the inflow is not simulated"


def test_without_a_forecast_no_band_and_how_to_get_one(st):
    b = planbands.collect(st, None, "demo")
    assert (b["rows"], b["tail"], b["heading"]) == ([], [], "no forecast yet: brain forecast")
    assert planbands.lines({"projects": [{"project": "demo", "bands": b}]}) == [
        "Milestones · Trajectories", "  no forecast yet: brain forecast"]


def test_a_band_is_p10_to_p80_then_p80_to_p90_with_its_median():
    core = {"p10": 2, "p50": 5, "p80": 8, "p90": 10}
    assert planbands.band(core, 12, 1) == "  ▒▒▒█▒▒░░  "
    assert planbands.band(core, 12, 1, plain=True) == "  ===#==--  "   # the legacy console's shapes
    assert planbands.band(core, 6, 2) == " ▒█▒░ "   # two days a cell
    assert planbands.band(core, 8, 1, offset=4) == "▒█▒▒░░  "   # panned four cells
    assert planbands.band(None, 4, 1) == "    "


def test_beyond_the_horizon_the_band_stops_and_says_it_goes_on():
    h = forecast.HORIZON_DAYS
    era = planbands.band({"p10": 10, "p50": 20, "p80": 35, "p90": 50}, h + 3, 1)
    assert era[20] == "█" and era[h - 1] == "░" and era[h:] == "▸  "
    late = planbands.band({"p10": 44, "p50": 50, "p80": 60, "p90": 70}, h + 3, 1)
    assert late == " " * h + "▸  " and "█" not in late   # its median beyond the horizon: the order only
    assert planbands.band({"p10": 1, "p50": 2, "p80": 3, "p90": 4}, h + 3, 1)[h] == " "   # ends before: no ▸
    assert planbands.band({"p10": 10, "p50": 20, "p80": 35, "p90": 50}, 3, 1, offset=h + 5) == "▸  "   # panned past


def test_the_scale_and_the_pan_stay_within_their_steps():
    assert planbands.default_scale(56) == 1 and planbands.default_scale(20) == 3
    assert planbands.zoom(1, -1) == 0.5 and planbands.zoom(1, 1) == 2
    assert planbands.zoom(planbands.SCALES[0], -1) == planbands.SCALES[0]
    assert planbands.zoom(planbands.SCALES[-1], 1) == planbands.SCALES[-1]
    assert planbands.pan(0, 1, 1) == 7 and planbands.pan(7, 1, -1) == 0 and planbands.pan(0, 1, -1) == 0
    assert planbands.pan(0, 7, 1) == 1 and planbands.rescaled(14, 1, 2) == 7


def test_the_dates_row_names_each_monday_where_it_fits():
    # Wednesday Nov 18 08:00: the next Monday is 4 days 16 hours on
    assert planbands.ticks(FCB["as_of"], 20, 1) == "    Nov 23 Nov 30   "
    assert planbands.ticks(FCB["as_of"], 20, 0.5) == "         Nov 23     "
    assert planbands.ticks(None, 4, 1) == "    "


def test_the_text_twin_draws_the_chart_within_its_width(st, monkeypatch):
    panel = {"projects": [{"project": "demo", "bands": planbands.collect(st, FCB, "demo")}]}
    out = planbands.lines(panel, 120, plain=False)
    assert out[0] == "Milestones · Trajectories" and out[1].startswith("  ranges p10–p90 UNCALIBRATED")
    assert out[2].startswith("  Milestone") and "Nov 23" in out[2]
    names = [x[2:24].rstrip() for x in out[3:-1]]
    assert names == ["wave 0.2.0", "core", "era-demo-one", "loose", "sub", "(no milestone)", "backlog"]
    assert "█" in out[3] and "◆ go/no-go ddr-go" in out[5] and "▸" in out[5]
    assert out[-1].startswith("  ▒ p10–p80 · ░ p80–p90 · █ median · ▸ beyond 6 weeks")
    assert all(len(x) <= 120 for x in out)
    monkeypatch.setenv("TERM", "linux")   # the legacy console: ASCII and words
    plain = "\n".join(planbands.lines(panel, 120))
    assert "#" in plain and not any(g in plain for g in "▒░█▸◆⧗⚙⇢⊘")
    assert "go/no-go ddr-go" in plain and "= p10–p80" in plain


def test_brain_tui_once_prints_the_trajectories_and_the_cockpit_heading(st, store, capsys):
    root = store.parents[1]
    forecast.folder(root.name).mkdir(parents=True, exist_ok=True)
    (forecast.folder(root.name) / "latest.json").write_text(json.dumps(FCB), encoding="utf-8")
    assert cli.main(["--root", str(root), "tui", "--once", "--quick", "--tab", "milestones", "--view",
                     "trajectories"]) == 0
    out = capsys.readouterr().out
    assert "Milestones · Trajectories" in out and "wave 0.2.0" in out and "Milestones (" not in out
    assert "· Tree ·" not in out
    assert cli.main(["--root", str(root), "tui", "--once", "--quick", "--tab", "milestones"]) == 0
    assert "Milestones · Trajectories" not in capsys.readouterr().out   # a plan view only when asked
    p = projects.Project(name=root.name, root=root, stores=[store])
    cp = cockpit.Cockpit([p], root=root)
    cp.refresh()
    plan = cp.snapshot()["panels"]["plan"]
    assert [r["id"] for r in plan["projects"][0]["bands"]["rows"]][:2] == ["wave-s2", "ms-demo-core"]
    assert cockpit.heading("traj", plan).startswith("Milestones · Trajectories · ranges p10–p90 UNCALIBRATED")
    assert cockpit.heading("traj", {"projects": []}) == "Milestones · Trajectories"


def test_the_trajectories_are_a_view_of_the_milestones_tab():
    assert cockpit.TABS["milestones"]["views"]["trajectories"] == ("traj",)
    assert cockpit.FRAMES["traj"] == "plan" and cockpit.panel_tab("traj") == "milestones"
    assert cockpit.plan_view("traj") and cockpit.plan_view("plan") and not cockpit.plan_view("milestones")
    assert cockpit.VIEW_LABELS["trajectories"] == {"en": "Trajectories", "fr": "Trajectoires"}
    assert "[ ] the scale" in cockpit.HELP["traj"]["what"] and "latest.json" in cockpit.HELP["traj"]["from"]
