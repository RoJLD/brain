"""wi-brain-backlog-forecast: brain forecast (brain.forecast), the Monte Carlo of spec-brain-psychohistory §4.1 under
the honesty bar of §4.4 (PSY-2), its reproducible JSON (§6), the brain status line and the Monday snapshot (PSY-5)."""

import json
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
    assert "ms-y" in text and "its trigger names 4 weeks, in a row (not modelled)" in text


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
