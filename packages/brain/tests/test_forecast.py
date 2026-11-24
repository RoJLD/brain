"""wi-brain-backlog-forecast: brain forecast (brain.forecast), the Monte Carlo of spec-brain-psychohistory §4.1 under
the honesty bar of §4.4 (PSY-2), its reproducible JSON (§6), the brain status line and the Monday snapshot (PSY-5)."""

import json
from collections import Counter
from datetime import datetime, timezone

import pytest

from brain import __version__, cli, cost, forecast, projects, status, usage

NOW = datetime(2026, 11, 2, 21, 0, tzinfo=timezone.utc)

ITEMS = """
- {id: ms-y, type: Milestone, status: pending, title: "Milestone Y", props: {trigger: "y for 4 weeks in a row"}}
- {id: wi-h1, type: WorkItem, status: done, title: "Build H1", props: {theme: "3.9", done: "2026-10-30 ok"}}
- {id: wi-h2, type: WorkItem, status: done, title: "Build H2", props: {theme: "3.9", done: "2026-10-31 ok"}}
- {id: wi-h3, type: WorkItem, status: done, title: "Build H3", props: {theme: "3.9", done: "2026-11-01 ok"}}
- {id: wi-h4, type: WorkItem, status: done, title: "Build H4", props: {theme: "3.9", done: "2026-11-02 ok"}}
- {id: wi-p1, type: WorkItem, status: todo, title: "Build P1", props: {priority: P1, theme: "3.9"}}
- {id: wi-p2, type: WorkItem, status: todo, title: "Build P2", props: {priority_proposed: P2, theme: "3.9"}}
- {id: wi-after, type: WorkItem, status: todo, title: "Build after P1", props: {priority: P1, theme: "3.9"}}
- {id: wi-ice, type: WorkItem, status: deferred, title: "Build iced", props: {priority: P3, theme: "3.9"}}
- {id: wi-thaw, type: WorkItem, status: todo, title: "Build after the iced", props: {priority: P2, theme: "3.9"}}
- {id: wi-ext, type: WorkItem, status: todo, title: "Build external", props: {priority: P2, theme: "3.9",
   after_external: "acme wi-z"}}
"""
EDGES = """
- {from: wi-p1, to: ms-x, type: part_of}
- {from: wi-after, to: ms-x, type: part_of}
- {from: wi-ice, to: ms-x, type: part_of}
- {from: wi-ext, to: ms-y, type: part_of}
- {from: wi-after, to: wi-p1, type: depends_on}
- {from: wi-thaw, to: wi-ice, type: depends_on}
"""


@pytest.fixture
def project(store):
    with (store / "nodes" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write(ITEMS)
    with (store / "edges" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write(EDGES)
    root = store.parents[1]
    return projects.Project(name="demo", root=root, stores=[store])


def row(sid, day, closed, active_h=2.0, usd=10.0):
    return {"session_id": sid, "folder": "", "start": f"{day}T10:00:00Z", "end": f"{day}T13:00:00Z", "title": "",
            "branch": "b", "kind": "build", "cost": usd, "active_s": int(active_h * 3600), "tokens": {"output": 1000},
            "sub_tokens": {}, "days": {day: {"cost": usd, "messages": 10, "output": 1000}},
            "brief": {"side": True, "key": sid, "class": "standard", "budget": 400_000, "items": [], "chars": 2000},
            "spawned": [], "closed": closed, "title_items": [], "prs": [], "context": {"peak": 300_000},
            "phases": {}, "signals": {}, "ngrams": {}, "tools": {}, "commands": {}, "skills": {},
            "start_cost": {"cost": 1.0}}


def rows():
    return [row("s1", "2026-10-30", ["wi-h1"], 1.0, 5.0), row("s2", "2026-10-31", ["wi-h2"], 2.0, 10.0),
            row("s3", "2026-11-01", ["wi-h3"], 3.0, 20.0), row("s4", "2026-11-02", ["wi-h4"], 4.0, 40.0)]


def ledger(project):
    rs = rows()
    for r in rs:
        r["folder"] = str(project.root)
    return cost.Ledger(rs, [project])


def model(**kw):
    """A model as brain.forecast.gather returns it, written by hand: ``n`` items of 1-2 h, one capacity day of 8 h."""
    n = kw.pop("n", 3)
    items = [{"id": f"wi-{k}", "title": f"Item {k}", "status": "todo", "priority": "P1", "proposed": False,
              "milestone": "ms-a", "class": "standard", "basis": "class", "n": 3,
              "hours": {"p25": 1.0, "median": 1.5, "p75": 2.0}, "usd": {"p25": 5.0, "median": 7.0, "p75": 9.0},
              "spent_h": 0.0, "order": None, "deps": [], "ddr": [], "why": "", "score": 1.0} for k in range(n)]
    m = {"project": "demo", "now": NOW.isoformat(timespec="minutes"), "items": items, "deferred": [],
         "milestones": [{"id": "ms-a", "title": "A", "members": [i["id"] for i in items], "done": 0,
                         "durations": []}],
         "reached": [], "ratios": {"*": [0.5, 1.0, 1.5, 2.0, 3.0]}, "usd_ratios": {"*": [1.0]}, "history": 5,
         "capacity": {"days": [{"day": "2026-11-02", "hours": 8.0, "lanes": 2}], "since": "2026-11-02"},
         "keep": {"kept": 1, "dropped": 0, "rate": 1.0}, "delays_h": [], "flow": {"days": 0, "created": 0,
                                                                                  "closed": 0},
         "inputs": {"store_commit": "", "store_digest": "", "model_digest": "", "settings_digest": ""}}
    m.update(kw)
    return m


def test_a_fixed_seed_gives_the_same_output_and_the_json_carries_it(project):
    m = forecast.gather(project, ledger(project), NOW)
    a = forecast.as_json(forecast.run(m, 200, seed=7))
    assert a == forecast.as_json(forecast.run(forecast.gather(project, ledger(project), NOW), 200, seed=7))
    assert a != forecast.as_json(forecast.run(m, 200, seed=8))
    res = json.loads(a)
    assert res["seed"] == 7 and res["runs"] == 200 and res["code"] == {"brain": __version__, "model": forecast.MODEL_V}
    assert set(res["inputs"]) == {"store_commit", "store_digest", "model_digest", "settings_digest"}
    assert res["inputs"]["store_digest"].startswith("sha256:") and res["inputs"]["model_digest"].startswith("sha256:")
    ids = {i["id"] for i in res["items"]}
    assert ids == {"wi-one", "wi-two", "wi-p1", "wi-p2", "wi-after"}  # wi-ext waits on acme, wi-thaw on the ice
    p1, after = (next(i for i in res["items"] if i["id"] == k) for k in ("wi-p1", "wi-after"))
    assert after["days"]["p10"] >= p1["days"]["p10"] and set(p1["days"]) == {"p10", "p50", "p80", "p90"}


def test_deferred_items_stay_out_of_every_date_and_are_shown_apart(project):
    res = forecast.run(forecast.gather(project, ledger(project), NOW), 200)
    assert "wi-ice" not in {i["id"] for i in res["items"]}
    assert res["deferred"]["items"] == 1 and res["deferred"]["ids"] == ["wi-ice"] and res["deferred"]["hours"] > 0
    undated = {u["id"]: u["why"] for u in res["gates"]["undated"]}
    assert undated == {"wi-thaw": "after a deferred item: wi-ice", "wi-ext": "after another project: acme wi-z"}
    ms = {m["id"]: m for m in res["milestones"]}
    assert ms["ms-x"]["deferred"] == ["wi-ice"] and ms["ms-x"]["open"] == 2 and ms["ms-x"]["dates"]
    assert ms["ms-y"]["shown"] == "undated" and ms["ms-y"]["dates"] is None  # its only item waits on another project
    text = "\n".join(forecast.render(res, show_items=True))
    assert "1 deferred item(s) out" in text and "1 item(s) in the icebox, out of every date" in text
    assert "wi-thaw" in text and "not dated: after a deferred item" in text
    assert "ms-y" in text and "its trigger names 4 weeks, in a row with no gate (not modelled)" in text


def test_an_item_in_a_wave_and_a_thematic_milestone_keeps_both(project):
    """wi-brain-forecast-two-parents: an item part of a wave and of a thematic milestone keeps both in its row,
    whichever edge comes last; one in a wave alone counts in « (no milestone) »; each milestone reads its members."""
    store = project.stores[0]
    with (store / "nodes" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write('- {id: wave-s9, type: Milestone, status: pending, title: "Wave 9", props: {kind: wave}}\n'
                '- {id: wave-s8, type: Milestone, status: reached, title: "Wave 8", props: {kind: wave}}\n'
                '- {id: wi-carry, type: WorkItem, status: todo, title: "Build carried", props: {priority: P2, '
                'theme: "3.9", carried_to: wave-s9}}\n')
    with (store / "edges" / "work.yaml").open("a", encoding="utf-8") as f:   # the wave edge after the thematic one
        f.write("- {from: wi-p1, to: wave-s9, type: part_of}\n- {from: wi-p2, to: wave-s9, type: part_of}\n"
                "- {from: wi-carry, to: wave-s8, type: part_of}\n")
    model = forecast.gather(project, ledger(project), NOW)
    rows = {i["id"]: i for i in model["items"]}
    assert (rows["wi-p1"]["milestone"], rows["wi-p1"]["wave"], rows["wi-p1"]["parents"]) == (
        "ms-x", "wave-s9", ["ms-x", "wave-s9"])
    assert (rows["wi-p2"]["milestone"], rows["wi-p2"]["wave"], rows["wi-p2"]["parents"]) == ("", "wave-s9", ["wave-s9"])
    assert (rows["wi-one"]["milestone"], rows["wi-one"]["wave"], rows["wi-one"]["parents"]) == ("", "", [])
    # carried out of a closed wave: its wave is the one it was carried to, the planned one kept among its parents
    assert (rows["wi-carry"]["wave"], rows["wi-carry"]["parents"]) == ("wave-s9", ["wave-s8", "wave-s9"])
    res = json.loads(forecast.as_json(forecast.run(model, 100)))
    out = {i["id"]: i for i in res["items"]}
    assert (out["wi-p1"]["milestone"], out["wi-p1"]["wave"], out["wi-p1"]["parents"]) == (
        "ms-x", "wave-s9", ["ms-x", "wave-s9"])
    loose = sorted(i["id"] for i in model["items"] if not i["milestone"])
    assert "wi-p2" in loose and "wi-p1" not in loose and res["no_milestone"]["open"] == len(loose)
    ms = {m["id"]: m for m in res["milestones"]}
    assert ms["ms-x"]["open"] == 2   # wi-p1 counted in both
    # a wave's members are the items in it now (wi-brain-forecast-starts-critical): wi-carry, carried in, counts
    assert ms["wave-s9"]["open"] == 3 and "wave-s9" in out["wi-carry"]["critical"]
    # the slip of a day of waiting reads every milestone of the item: the tightest one sets it
    fc = {"milestones": [{"id": "ms-x", "days": {"p50": 30.0}}, {"id": "wave-s9", "days": {"p50": 5.0}}],
          "items": [{"id": "wi-p1", "milestone": "ms-x", "parents": ["ms-x", "wave-s9"], "days": {"p50": 4.0}}]}
    w = forecast.waiting(fc, ["wi-p1"], 7)
    assert w["items"]["wi-p1"]["milestone"] == "wave-s9" and w["slip"] == round(6 / 7, 3) and w["nearest"] == "wave-s9"


def test_a_growing_backlog_has_no_date_and_its_frozen_scope_is_apart():
    grow = {"days": 3, "created": 30, "closed": 6, "created_per_day": 10.0, "closed_per_day": 2.0, "growing": True}
    res = forecast.run(model(flow=grow), 100)
    b = res["backlog"]
    assert b["dates"] is None and b["shown"] == "growing" and b["frozen"]["dates"]
    line = forecast.backlog_line(res)
    assert line.startswith("no date: it grows faster than it empties (created 10/day, closed 2/day")
    assert "backlog no date" in forecast.status_line(res)
    calm = dict(grow, created=3, created_per_day=1.0, growing=False)
    res = forecast.run(model(flow=calm), 100)
    assert res["backlog"]["dates"] and res["backlog"]["shown"] == "range"
    assert forecast.backlog_line(res).endswith("(d); the inflow is not simulated")


def test_the_shared_error_keeps_the_range_wide():
    """Independent errors cancel out: without the shared factor, 40 items finish in a far narrower range."""
    wide = forecast.run(model(n=40), 300)["backlog"]["days"]
    narrow = forecast.run(model(n=40, ratios={"*": [1.5]}), 300)["backlog"]["days"]
    assert (wide["p90"] - wide["p10"]) > 3 * (narrow["p90"] - narrow["p10"])


def test_beyond_six_weeks_no_date_and_the_p50_alone_only_once_calibrated():
    slow = {"days": [{"day": "2026-11-02", "hours": 0.03, "lanes": 1}], "since": "2026-11-02"}
    res = forecast.run(model(capacity=slow), 50)
    assert res["milestones"][0]["shown"] == "beyond" and forecast.span(res["milestones"][0]) == "beyond 6 weeks"
    res = forecast.run(model(), 50)
    m = res["milestones"][0]
    assert m["shown"] == "range" and " – " in forecast.span(m) and " · " in forecast.span(m, calibrated=True)
    assert "uncalibrated" in forecast.status_line(res)


def test_the_scheduler_follows_priority_dependencies_and_gates():
    # one lane, three items of 2 h: the rank is the index; item 2 waits on 0; item 1 is released at 5 h
    done = forecast._schedule([2.0, 2.0, 2.0], [True] * 3, [0.0, 5.0, 0.0], [[], [], [0]], [[2], [], []], 1)
    assert done == [2.0, 7.0, 4.0]
    # an item left out of the future holds no lane and satisfies its dependents at once
    done = forecast._schedule([2.0, 2.0], [False, True], [0.0, 0.0], [[], [0]], [[1], []], 1)
    assert done[1] == 2.0
    m = model(n=2)
    m["items"][0].update(priority="P2")
    m["items"][1].update(priority="P0")
    assert [t["id"] for t in forecast._plan(m)["dated"]] == ["wi-1", "wi-0"]


def test_a_proposed_item_stays_with_the_keep_rate_and_a_blocking_ddr_waits_for_robin():
    m = model(n=2, keep={"kept": 1, "dropped": 1, "rate": 0.5}, delays_h=[48.0])
    m["items"][0]["proposed"] = True
    m["items"][1]["ddr"] = ["ddr-x"]
    res = forecast.run(m, 400)
    kept = {i["id"]: i["kept"] for i in res["items"]}
    assert 0.4 < kept["wi-0"] < 0.6 and kept["wi-1"] == 1.0
    gated = next(i for i in res["items"] if i["id"] == "wi-1")
    assert gated["days"]["p10"] > 2.0 and res["gates"]["ddr"] == ["ddr-x"]  # 48 h of the owner's first


def test_the_judge_labels_calibrated_after_five_milestones_covered():
    reached = [{"id": f"ms-{k}", "reached": "2026-11-20"} for k in range(5)]

    def snap(hits: int) -> dict:
        return {"as_of": "2026-11-09T09:00+00:00", "milestones": [
            {"id": f"ms-{k}", "dates": {"p10": "2026-11-15", "p90": "2026-11-25" if k < hits else "2026-11-18"}}
            for k in range(5)]}

    assert forecast.calibration(reached, [snap(4)])["state"] == "calibrated"
    c = forecast.calibration(reached, [snap(2)])
    assert c["state"] == "uncalibrated" and c["judged"] == 5 and c["coverage"] == 0.4
    assert forecast.calibration(reached[:4], [snap(4)])["state"] == "uncalibrated"  # four are not enough
    assert forecast.calibration(reached, [])["judged"] == 0


def test_capacity_and_keep_rate_are_measured():
    rs = rows() + [row("s5", "2026-11-02", ["wi-h4"], 2.0)]
    for r in rs:
        r["served"] = r["closed"]
    cap = forecast.capacity(rs + [dict(row("idle", "2026-11-02", []), served=[])], datetime(2026, 10, 30).date(),
                            datetime(2026, 11, 2).date())
    by = {d["day"]: d for d in cap["days"]}
    assert by["2026-11-02"]["hours"] == 6.0 and by["2026-10-30"]["hours"] == 1.0
    assert by["2026-11-02"]["lanes"] == 2  # 6 active hours over the 3 hours a session was open
    work = [{"id": "a", "status": "todo", "props": {"validated": "Ada"}},
            {"id": "b", "status": "done", "props": {"priority_proposed": "P2"}},
            {"id": "c", "status": "dropped", "props": {"priority_proposed": "P3"}}]
    assert forecast.keep_rate(work) == {"kept": 2, "dropped": 1, "rate": 0.6}


def test_flow_counts_the_items_created_and_closed_from_git(make_repo):
    nodes = "notes/graph/nodes/work.yaml"
    repo = make_repo("r", {nodes: "- {id: wi-a, type: WorkItem, status: todo, title: A}\n"},
                     date="2026-10-31T12:00:00Z")
    make_repo.commit(repo, {nodes: "- {id: wi-a, type: WorkItem, status: done, title: A}\n"
                                   "- {id: wi-b, type: WorkItem, status: todo, title: B}\n"
                                   "- {id: wi-c, type: WorkItem, status: todo, title: C}\n"},
                     date="2026-11-01T12:00:00Z")
    fl = forecast.flow(repo / "notes" / "graph", datetime(2026, 11, 2).date())
    assert fl["days"] == 3 and fl["created"] == 3 and fl["closed"] == 1 and fl["growing"] is True
    assert forecast.flow(repo / "nowhere", datetime(2026, 11, 2).date())["days"] == 0


def test_the_status_line_reads_the_last_forecast_and_the_quota_degrades(project, monkeypatch):
    assert forecast.status_of(project, None, NOW, quick=True)["line"] == "no forecast saved (brain forecast)"
    res = forecast.run(forecast.gather(project, ledger(project), NOW), 50)
    forecast.save(res)
    line = forecast.status_of(project, None, NOW, quick=True)["line"]
    assert line.startswith("next ms-x ") and "uncalibrated" in line and "as of 2026-11-02 21:00 UTC" in line
    data = status.collect(project, quick=True)
    assert "forecast" in data and "forecast    next ms-x" in "\n".join(status.render({"projects": [data]}))
    real = forecast.importlib.import_module

    def no_quota(name, package=None):
        if name == ".quota":
            raise ModuleNotFoundError(name)
        return real(name, package)

    monkeypatch.setattr(forecast.importlib, "import_module", no_quota)
    assert forecast.quota_pace() == "quota pace unknown"


def test_cli_forecast_and_the_monday_snapshot(project, capsys):
    saved = {f"p/{r['session_id']}.jsonl": r for r in rows()}
    for r in saved.values():
        r["folder"] = str(project.root)
    usage.save(saved)
    root = str(project.root)
    assert cli.main(["--root", root, "forecast", "--runs", "50", "--no-scan", "--json"]) == 0
    res = json.loads(capsys.readouterr().out)
    name = res["project"]  # the folder's name: the root is not registered
    assert res["runs"] == 50 and res["scope"]["open"] == 7 and (forecast.folder(name) / "latest.json").is_file()
    assert cli.main(["--root", root, "forecast", "--runs", "50", "--no-scan", "--items"]) == 0
    out = capsys.readouterr().out
    assert "UNCALIBRATED" in out and "Whole backlog" in out and "  quota " in out and "wi-thaw" in out
    assert cli.main(["--root", root, "cost", "audit", "--since", "2026-10-01", "--write"]) == 0
    assert "forecast snapshot:" in capsys.readouterr().out
    snaps = forecast.load_snapshots(name)
    assert len(snaps) == 1 and snaps[0]["project"] == name and snaps[0]["milestones"]
    with pytest.raises(SystemExit):
        cli.main(["--root", root, "forecast", "--runs", "0"])


# --- wi-brain-forecast-starts-critical: the starts, the criticality index and the chains (MODEL_V 3) ---

def test_the_scheduler_traces_what_each_start_waited_on():
    # one lane: 0 at once; 2 after its dependency 0; 1 released by a gate at 5 h
    trace = {}
    done = forecast._schedule([2.0, 2.0, 2.0], [True] * 3, [0.0, 5.0, 0.0], [[], [], [0]], [[2], [], []], 1,
                              trace=trace)
    assert done == [2.0, 7.0, 4.0]
    assert trace == {"start": [0.0, 5.0, 2.0], "pred": [-1, -1, 0], "by": ["now", "gate", "dependency"]}
    # two items and one lane: the second waits for the lane the first frees
    trace = {}
    forecast._schedule([2.0, 3.0], [True, True], [0.0, 0.0], [[], []], [[], []], 1, trace=trace)
    assert trace["start"] == [0.0, 2.0] and trace["pred"] == [-1, 0] and trace["by"] == ["now", "lane"]
    # no trace asked: the finishes alone, as before
    assert forecast._schedule([1.0], [True], [0.0], [[]], [[]], 1) == [1.0]


def _chain_model(lanes=4):
    m = model(n=4, capacity={"days": [{"day": "2026-11-02", "hours": 8.0, "lanes": lanes}], "since": "2026-11-02"})
    a, b, c, d = m["items"]
    b["deps"], c["deps"] = ["wi-0"], ["wi-1"]          # a known chain: wi-0 → wi-1 → wi-2
    d["hours"] = {"p25": 0.05, "median": 0.1, "p75": 0.15}   # wi-3 alone, far shorter
    return m


def test_a_known_chain_gets_index_one_and_is_the_milestones_chain():
    res = forecast.run(_chain_model(), 200, seed=3)
    items = {i["id"]: i for i in res["items"]}
    assert [items[k]["critical"]["ms-a"] for k in ("wi-0", "wi-1", "wi-2", "wi-3")] == [1.0, 1.0, 1.0, 0.0]
    assert set(items["wi-0"]["critical"]) == {"ms-a", "*"}   # every group it is a member of
    chain = next(m for m in res["milestones"] if m["id"] == "ms-a")["chain"]
    assert chain == {"items": ["wi-0", "wi-1", "wi-2"], "by": ["now", "dependency", "dependency"],
                     "index": [1.0, 1.0, 1.0], "share": 1.0, "gated": 0.0}
    assert res["backlog"]["chain"]["items"] == chain["items"] and forecast.bound(chain) == "dependency-bound"
    # each item's start: after its dependency's end, as p10-p90 days and dates; its drawn hours
    s0, s1 = items["wi-0"]["start"], items["wi-1"]["start"]
    assert s0["days"]["p90"] == 0.0 and s1["days"]["p10"] > 0 and set(s1["dates"]) == {"p10", "p50", "p80", "p90"}
    assert s1["days"]["p50"] <= items["wi-1"]["days"]["p50"] and items["wi-3"]["hours"]["p90"] < 1.0
    assert res["code"]["model"] == forecast.MODEL_V == 3 and res["forecast"] == forecast.FORMAT == 1


def test_one_lane_makes_the_chain_capacity_bound():
    m = model(n=3, capacity={"days": [{"day": "2026-11-02", "hours": 8.0, "lanes": 1}], "since": "2026-11-02"})
    res = forecast.run(m, 100, seed=1)
    chain = res["backlog"]["chain"]
    assert chain["items"] == ["wi-0", "wi-1", "wi-2"] and chain["by"] == ["now", "lane", "lane"]
    assert forecast.bound(chain) == "capacity-bound"
    text = forecast.chain_text(chain, "demo", res)
    assert text.startswith("wi-0 100% → wi-1 100% → wi-2 100%") and "capacity-bound: 1 lane(s)" in text


def test_a_milestone_whose_own_gate_sets_its_finish_has_no_chain_in_that_future():
    out = {"finish": {"wi-0": [1.0]}, "mgate": {"ms-a": [(9.0, 0.0)]}, "chains": {"ms-a": Counter()},
           "on_chain": {"ms-a": Counter()}, "gated": Counter()}
    forecast._chains(out, {"ms-a": [0]}, [1.0], [True], {"pred": [-1], "by": ["now"]}, [{"id": "wi-0"}])
    assert out["gated"]["ms-a"] == 1 and not out["chains"]["ms-a"]
    sim = {"runs": 1, **out}
    assert forecast._chain(sim, "ms-a") == {"items": [], "by": [], "index": [], "share": 0.0, "gated": 1.0}
    assert "its own gate sets its finish in 100%" in forecast.chain_text(forecast._chain(sim, "ms-a"))


def test_the_new_keys_are_additive_and_an_older_result_still_reads():
    res = forecast.run(_chain_model(), 50, seed=1)
    old_item = {"id", "priority", "milestone", "wave", "parents", "status", "basis", "kept", "days", "dates", "ddr",
                "action", "gates", "due", "late"}
    assert old_item <= set(res["items"][0]) and {"start", "hours", "critical"} <= set(res["items"][0])
    assert "chain" in res["milestones"][0] and "chain" in res["backlog"] and "past" in res
    # a model-2 result (no start, critical, chain): the readers degrade, never fail
    for it in res["items"]:
        for k in ("start", "hours", "critical"):
            it.pop(k)
    for blk in (*res["milestones"], res["backlog"], res["no_milestone"]):
        blk.pop("chain")
    lines = forecast.critical_lines(res)
    assert lines[-1] == "  no chain: nothing simulated"
    assert "no chain" in "\n".join(forecast.critical_lines(res, "ms-a"))
    assert forecast.waiting(res, ["wi-0"])["items"]


def test_critical_lines_name_a_milestone_by_its_id_or_short_name():
    res = forecast.run(_chain_model(), 50, seed=1)
    assert forecast.group_of(res, "ms-a")[0] == "ms-a" and forecast.group_of(res, "backlog")[0] == "*"
    assert forecast.group_of(res, "-")[0] == "" and forecast.group_of(res, "nope") is None
    one = forecast.critical_lines(res, "ms-a")
    assert one[1].startswith("  ms-a: wi-0 100% → wi-1 100% → wi-2 100%")
    assert any(x.startswith("  ◆ wi-0") for x in one) and any(x.startswith("    wi-3") for x in one)
    every = forecast.critical_lines(res)
    assert any(x.startswith("  backlog") for x in every) and any(x.startswith("  ms-a") for x in every)
    with pytest.raises(forecast.ForecastError):
        forecast.critical_lines(res, "nope")


def test_the_past_keeps_the_ledgers_first_session_and_done_day(project):
    m = forecast.gather(project, ledger(project), NOW)
    assert m["past"] == {}   # no done or doing member of an open milestone has a session here
    led = ledger(project)
    it = cost.Item("wi-h1", "demo", "Build H1", "done", "", "", "build", {"done": "2026-10-30"})
    it.sessions = [(rows()[0], 1.0)]
    led.items["wi-h1"] = it
    past = forecast._past(led, {"wi-h1": "done", "wi-p1": "todo"}, {"wi-h1", "wi-p1"})
    assert past == {"wi-h1": {"first": "2026-10-30", "done": "2026-10-30", "hours": 1.0, "sessions": 1}}


def test_cli_forecast_critical(project, capsys):
    saved = {f"p/{r['session_id']}.jsonl": r for r in rows()}
    for r in saved.values():
        r["folder"] = str(project.root)
    usage.save(saved)
    root = str(project.root)
    assert cli.main(["--root", root, "forecast", "--runs", "30", "--no-scan", "--critical"]) == 0
    out = capsys.readouterr().out
    assert "--critical:" in out and "Van Slyke" in out and "  backlog" in out
    assert cli.main(["--root", root, "forecast", "--runs", "30", "--no-scan", "--critical", "backlog"]) == 0
    assert "  backlog: " in capsys.readouterr().out
    assert cli.main(["--root", root, "forecast", "--runs", "30", "--no-scan", "--critical", "ms-nope"]) == 2
    assert "no such milestone" in capsys.readouterr().err


def test_an_item_of_another_milestone_holding_the_lane_lies_on_the_chain_outside_the_group():
    m = model(n=3, capacity={"days": [{"day": "2026-11-02", "hours": 8.0, "lanes": 1}], "since": "2026-11-02"})
    m["items"][0].update(priority="P0", milestone="ms-b")   # served first, in the one lane, but not ms-a's
    m["milestones"] = [{"id": "ms-a", "title": "A", "members": ["wi-1", "wi-2"], "done": 0, "durations": []},
                       {"id": "ms-b", "title": "B", "members": ["wi-0"], "done": 0, "durations": []}]
    res = forecast.run(m, 50, seed=2)
    chain = next(x for x in res["milestones"] if x["id"] == "ms-a")["chain"]
    assert chain["items"] == ["wi-0", "wi-1", "wi-2"] and chain["by"] == ["now", "lane", "lane"]
    w0 = next(i for i in res["items"] if i["id"] == "wi-0")
    assert "ms-a" not in w0["critical"] and w0["critical"]["ms-b"] == 1.0
    lines = forecast.critical_lines(res, "ms-a")
    assert lines[-1] == "  and 1 item(s) of other groups on its chain: wi-0"
    assert not any(x.startswith("  ◆ wi-0") for x in lines)
