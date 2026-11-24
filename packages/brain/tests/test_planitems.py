"""wi-brain-tui-trajectories-items: the Trajectories' item level (brain.planbands ``levels``, ``item_chart``,
``zoom_lines``; spec-brain-plan-views §3.4 and §3.6; VIZ-1, VIZ-3): a milestone's, an era's or a wave's items as Gantt
lanes, each one's past bar, start-to-finish band, est. h and criticality index from the forecast's latest.json (model
3: start, hours, critical, chain, past), the chain marked; a model-2 forecast read with its finish bands alone; the
text twin (brain tui --once --tab milestones --view trajectories --zoom <milestone>)."""

import copy
import json

import pytest
from brain import cli, forecast, planbands, planviews, resume
from test_planbands import FCB
from test_planviews import EDGES, NODES  # the fixture graph of the Tree

# FCB (a model-2 forecast, as 0.6.1 wrote it) and what model 3 adds: per item its start, hours and critical, per
# milestone its chain, the past of its done and doing members
FCI = copy.deepcopy(FCB)
FCI["code"] = {"model": 3}
FCI["items"] = [
    {"id": "wi-a", "priority": "P2", "status": "doing", "days": {"p10": 1, "p50": 2, "p80": 3, "p90": 4},
     "start": {"days": {"p10": 0, "p50": 0, "p80": 0, "p90": 0}}, "hours": {"p10": 0.5, "p50": 1.0, "p80": 1.5,
                                                                            "p90": 2.0},
     "critical": {"ms-demo-core": 0.7, "era-demo-one": 0.4, "wave-s2": 0.9, "*": 0.3}},
    {"id": "wi-b", "priority": "P1", "status": "todo", "days": {"p10": 3, "p50": 5, "p80": 7, "p90": 9},
     "start": {"days": {"p10": 1, "p50": 2, "p80": 3, "p90": 4}}, "hours": {"p10": 1.0, "p50": 2.0, "p80": 3.0,
                                                                            "p90": 4.0},
     "critical": {"ms-demo-core": 1.0, "ms-demo-sub": 1.0, "era-demo-one": 0.6, "*": 0.5}},
    {"id": "wi-carry", "priority": "P1", "status": "todo", "days": {"p10": 1, "p50": 1, "p80": 2, "p90": 2},
     "start": {"days": {"p10": 0, "p50": 0, "p80": 0, "p90": 1}}, "hours": {"p10": 0.2, "p50": 0.3, "p80": 0.4,
                                                                            "p90": 0.5},
     "critical": {"ms-demo-core": 0.0, "wave-s2": 0.1, "*": 0.0}}]
for m in FCI["milestones"]:
    if m["id"] == "ms-demo-core":
        m["chain"] = {"items": ["wi-a", "wi-b"], "by": ["now", "lane"], "index": [0.7, 1.0], "share": 0.6,
                      "gated": 0.0}
FCI["past"] = {"wi-a": {"first": "2026-11-15", "done": "", "hours": 1.5, "sessions": 2},
               "wi-c": {"first": "2026-11-05", "done": "2026-11-09", "hours": 2.25, "sessions": 1}}


@pytest.fixture
def st(store):
    with (store / "nodes" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write(NODES)
    with (store / "edges" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write(EDGES)
    return resume.Store.load(store)


def _bands(st, fc=FCI):
    trees = planviews.collect(st, fc, "demo")["trees"]
    return planbands.collect(st, fc, "demo", trees)


def test_each_milestone_era_and_wave_row_has_its_item_level_in_the_schedulers_order(st):
    b = _bands(st)
    assert set(b["levels"]) == {r["key"] for r in b["rows"]}
    core = b["levels"]["demo:ms-demo-core"]
    assert core["by"] == "order" and core["name"] == "core"
    ids = [r.get("id") or r["name"] for r in core["rows"]]
    # the dated ones as the scheduler served them (the forecast's order), the done one last under its group
    assert ids == ["wi-a", "wi-b", "wi-carry", "✓ 1 done", "wi-c"]   # wi-b through ms-demo-sub, wi-d dropped
    rows = {r["id"]: r for r in core["rows"] if r["kind"] == "item"}
    assert rows["wi-b"]["critical"] == 1.0 and rows["wi-b"]["on_chain"] and not rows["wi-carry"]["on_chain"]
    assert rows["wi-a"]["start"] == {"p10": 0, "p50": 0, "p80": 0, "p90": 0} and rows["wi-a"]["past"]["first"] == (
        "2026-11-15")
    assert rows["wi-c"]["past"] == {"first": "2026-11-05", "done": "2026-11-09", "hours": 2.25}
    assert core["chain_text"] == "wi-a 70% → wi-b 100% · capacity-bound · this chain in 60% of futures"
    # the era's level reads every item through its milestones; a wave's the items in it now
    era = {r.get("id") for r in b["levels"]["demo:era-demo-one"]["rows"]}
    assert {"wi-a", "wi-b", "wi-c", "wi-carry"} <= era
    wave = [r["id"] for r in b["levels"]["demo:wave-s2"]["rows"] if r["kind"] == "item"]
    assert set(wave) >= {"wi-a", "wi-w", "wi-carry"}


def test_a_wave_is_grouped_by_its_lots(st):
    lv = _bands(st)["levels"]["demo:wave-s2"]
    groups = [r["name"] for r in lv["rows"] if r["kind"] == "group"]
    assert lv["by"] == "lot" and groups and groups[0].startswith("round 1 · lot 1")


def test_an_items_band_runs_from_its_start_to_its_finish():
    r = {"days": {"p10": 2, "p50": 3, "p80": 4, "p90": 5}, "start": {"p10": 0, "p50": 1, "p80": 1, "p90": 2}}
    assert planbands.item_band(r, 7, 1.0) == "░▒▒█░  "
    assert planbands.item_band(r, 7, 1.0, plain=True) == "-==#-  "
    # a model-2 forecast keeps no start: the finish band alone, as a milestone's
    old = {"days": r["days"], "start": None}
    assert planbands.item_band(old, 7, 1.0) == planbands.band(r["days"], 7, 1.0)
    # undated: why, in its cells; beyond the horizon: ▸
    assert planbands.item_band({"days": None, "undated": "after another project: acme wi-z", "state": "todo"},
                               40, 1.0).startswith("┄┄ undated: after another project")
    far = {"days": {"p10": 40, "p50": 50, "p80": 60, "p90": 70}, "start": {"p10": 30, "p50": 35, "p80": 38, "p90": 39}}
    assert planbands.item_band(far, 50, 1.0).rstrip().endswith("▸")


def test_the_past_bar_runs_from_the_first_session_to_the_done_day():
    as_of = "2026-11-18T08:00+00:00"
    done = {"state": "done", "past": {"first": "2026-11-15", "done": "2026-11-17"}}
    assert planbands.past_cells(done, as_of, 1.0) == "       ━━━"
    doing = {"state": "doing", "past": {"first": "2026-11-16", "done": ""}}
    assert planbands.past_cells(doing, as_of, 1.0) == "        ━━"   # up to the forecast's day
    old = {"state": "done", "past": {"first": "2026-10-01", "done": "2026-10-03"}}
    assert planbands.past_cells(old, as_of, 1.0) == "  ✓ Oct 3"[-planbands.PAST_W:].rjust(planbands.PAST_W)
    no_first = {"state": "done", "past": {"first": "", "done": "2026-11-09"}}
    assert planbands.past_cells(no_first, as_of, 1.0).strip() == "✓ Nov 9"
    assert planbands.past_cells({"state": "todo", "past": {}}, as_of, 1.0) == " " * planbands.PAST_W
    assert planbands.past_cells(done, as_of, 1.0, plain=True) == "       ~~~"
    # in words, the done tick keeps its whole day within PAST_W (the longest month-day: « Sep 13 »)
    sep = {"state": "done", "past": {"first": "2026-09-10", "done": "2026-09-13"}}
    assert planbands.past_cells(sep, "2026-11-24T08:00+00:00", 1.0, plain=True) == " ok Sep 13"
    assert planbands.past_cells(sep, "2026-11-24T08:00+00:00", 1.0) == "  ✓ Sep 13"


def test_the_chart_has_its_columns_and_marks_the_chain_when_asked(st):
    lv = _bands(st)["levels"]["demo:ms-demo-core"]
    head, rows = planbands.item_chart(lv, FCI["as_of"], 140, chain=True)
    assert head[0].startswith("critical (most futures): ") and "est. h" in head[1] and "crit." in head[1]
    text = {r.get("id"): t for r, t in rows}
    assert text["wi-b"].endswith("100% ◆") and "1.0–4.0" in text["wi-b"]
    assert text["wi-c"].endswith("2.2 act     -")   # a done item: its actual hours, no index
    assert all(len(t) <= 140 for _, t in rows)
    head, rows = planbands.item_chart(lv, FCI["as_of"], 140, chain=False)
    assert not head[0].startswith("critical") and "◆" not in "".join(t for _, t in rows)
    # every row's « │ » at the same column
    cols = {t.index("│") for r, t in rows if r["kind"] == "item"}
    assert len(cols) == 1


def test_a_model_2_forecast_reads_with_its_finish_bands_and_no_crit(st):
    old = copy.deepcopy(FCB)
    old["items"] = [{"id": "wi-a", "days": {"p10": 1, "p50": 2, "p80": 3, "p90": 4}}]
    lv = _bands(st, old)["levels"]["demo:ms-demo-core"]
    a = next(r for r in lv["rows"] if r.get("id") == "wi-a")
    assert a["critical"] is None and a["start"] is None and a["hours"] is None and lv["chain"] is None
    head, rows = planbands.item_chart(lv, old["as_of"], 120)
    assert not head[0].startswith("critical") and planbands._crit(a) == "-" and planbands._est(a) == "-"
    assert planbands.collect(st, None, "demo")["levels"] == {}


def test_find_level_takes_an_id_a_short_name_or_the_charts_name(st):
    b = _bands(st)
    for ref in ("ms-demo-core", "core", "demo:ms-demo-core"):
        assert planbands.find_level(b, "demo", ref)["id"] == "ms-demo-core"
    assert planbands.find_level(b, "demo", "wave 0.2.0")["id"] == "wave-s2"
    assert planbands.find_level(b, "demo", "nope") is None


def test_brain_tui_once_zoom_prints_the_item_level(st, store, capsys):
    root = store.parents[1]
    forecast.folder(root.name).mkdir(parents=True, exist_ok=True)
    fc = {**FCI, "project": root.name}
    (forecast.folder(root.name) / "latest.json").write_text(json.dumps(fc), encoding="utf-8")
    assert cli.main(["--root", str(root), "tui", "--once", "--quick", "--zoom", "ms-demo-core"]) == 0
    out = capsys.readouterr().out
    assert "Milestones · Trajectories · items" in out and "› demo-core › items" in out and "critical (most futures)" in out
    assert "◆" in out and "Milestones (" not in out
    assert cli.main(["--root", str(root), "tui", "--once", "--quick", "--zoom", "nope"]) == 0
    assert "nope: no milestone, era or wave" in capsys.readouterr().out
    for bad in (["--zoom", "core"], ["--once", "--zoom", "core", "--view", "tree", "--tab", "milestones"],
                ["--once", "--zoom", "core", "--axis", "waves"]):
        with pytest.raises(SystemExit):
            cli.main(["--root", str(root), "tui", *bad])
