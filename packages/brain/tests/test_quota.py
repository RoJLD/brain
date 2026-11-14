"""wi-brain-quota-pacing: the ledger's hourly buckets, the plan quota readings (COST-3), the API-price to quota-share
conversion, the forecast at the weekly reset and its line in brain status (brain.quota)."""

import json
import os
from datetime import datetime, timedelta, timezone

import pytest
from test_cost import _history, project, row  # noqa: F401 - project is a fixture
from test_usage import _asst, _prompt, _tool, _write, projects_dir  # noqa: F401 - projects_dir is a fixture

from brain import cli, quota, status, usage

UTC = timezone.utc
NOW = datetime(2026, 11, 2, 21, 30, tzinfo=UTC)
RESET = "2026-11-09T12:00:00Z"  # the week started on 2026-11-02 at 12:00 UTC


def _hours(start: str, n: int, usd: float) -> dict:
    t = datetime.fromisoformat(start).replace(tzinfo=UTC)
    return {(t + timedelta(hours=i)).strftime("%Y-%m-%dT%H"): {"cost": usd, "messages": 1, "tokens": 1}
            for i in range(n)}


@pytest.fixture
def now(monkeypatch):
    monkeypatch.setattr(usage, "now_utc", lambda: NOW)
    return NOW


@pytest.fixture(autouse=True)
def one_reading_calibrates(monkeypatch):
    """The older tests convert from one reading; the per-plan tests set CAL_MIN back to 3."""
    monkeypatch.setattr(quota, "CAL_MIN", 1)


@pytest.fixture
def week():
    """$100 an hour from 12:00 to 21:00, then $50 in the 21:00 hour: $900 by the 21:00 reading."""
    return [{"session_id": "s1", "hours": {**_hours("2026-11-02T12:00", 9, 100.0), "2026-11-02T21": {"cost": 50.0}},
             "days": {"2026-11-02": {"cost": 950.0}}, "end": "2026-11-02T21:28:00Z"}]


def test_the_scan_buckets_cost_by_utc_hour(projects_dir):
    t = _write(projects_dir / "p" / "s.jsonl", [
        _prompt("2026-11-02T10:59:00Z", "go"),
        _asst("2026-11-02T10:59:30Z", "m1", [_tool("t1", "Read", file_path="a")], out=1000),
        _asst("2026-11-02T11:00:10Z", "m2", [_tool("t2", "Read", file_path="b")], out=2000)])
    r = usage.scan(t)
    assert r["v"] == usage.SCAN_V == 4
    assert set(r["hours"]) == {"2026-11-02T10", "2026-11-02T11"}
    assert r["hours"]["2026-11-02T11"]["cost"] == pytest.approx(2 * r["hours"]["2026-11-02T10"]["cost"], rel=0.01)
    assert sum(h["cost"] for h in r["hours"].values()) == pytest.approx(r["cost"], abs=1e-3)  # 4 decimals each


def test_cost_between_prorates_a_cut_bucket_and_spreads_an_old_rows_day():
    rows = [{"hours": {"2026-11-02T10": {"cost": 6.0}, "2026-11-02T11": {"cost": 2.0}}},
            {"days": {"2026-11-02": {"cost": 24.0}}}]  # scanned before the hours: its day over 24 h
    a, b = datetime(2026, 11, 2, 10, 30, tzinfo=UTC), datetime(2026, 11, 2, 11, 15, tzinfo=UTC)
    assert usage.cost_between(rows, a, b) == pytest.approx(3.0 + 0.5 + 0.75)
    assert usage.cost_between(rows, b, a) == 0.0


def test_observe_appends_and_infers_the_weekly_reset(now):
    with pytest.raises(quota.QuotaError, match="no reset known"):
        quota.observe(20)
    rec = quota.observe(28, at=quota.parse_time("2026-11-02T21:05Z", now), resets=quota.parse_time(RESET, now))
    assert (rec["window"], rec["pct"], rec["resets"], rec["plan"]) == ("week", 28.0, RESET, "Ultra")
    later = quota.observe(30)  # now, the same week: its reset taken from the last reading
    assert later["resets"] == RESET and later["at"] == "2026-11-02T21:30:00Z"
    jitter = quota.observe(31, resets=quota.parse_time("2026-11-09T11:59:59.654Z", now))  # get_usage's jitter
    assert jitter["resets"] == RESET
    assert [r["pct"] for r in quota.load_readings()] == [28.0, 30.0, 31.0]
    assert quota.infer_resets(quota.load_readings(), "week", NOW + timedelta(days=8)) == datetime(
        2026, 11, 16, 12, tzinfo=UTC)
    assert quota.infer_resets(quota.load_readings(), "5h", NOW) is None
    for bad, match in (({"pct": 120}, "between 0 and 100"), ({"pct": 5, "window": "day"}, "one of"),
                       ({"pct": 5, "at": NOW + timedelta(hours=1)}, "future"),
                       ({"pct": 5, "resets": NOW - timedelta(hours=1)}, "resets after it"),
                       ({"pct": 5, "resets": NOW + timedelta(days=8)}, "within")):
        with pytest.raises(quota.QuotaError, match=match):
            quota.observe(**bad)
    assert quota.parse_time("2026-11-09T12:00:00.433Z", NOW) == datetime(2026, 11, 9, 12, 0, 0, 433000, tzinfo=UTC)
    assert quota.parse_time("2026-11-02 21:05", NOW).tzinfo == UTC and quota.parse_time("now", NOW) == NOW
    with pytest.raises(quota.QuotaError):
        quota.parse_time("tomorrow", NOW)


def test_forecast_converts_paces_and_advises(week):
    readings = [{"at": "2026-11-02T20:00:00Z", "window": "week", "pct": 20.0, "resets": "2026-11-09T11:59:59Z"},
                {"at": "2026-11-02T21:00:00Z", "window": "week", "pct": 28.0, "resets": RESET, "host": "box1"}]
    fc = quota.forecast(week, readings[1:], NOW)
    assert quota.forecast(week, readings[::-1], NOW)["reading"]["pct"] == 28.0  # the same window a second apart
    c = fc["conversion"]
    assert c["n"] == 1 and c["pct_per_usd"] == pytest.approx(28 / 900, rel=1e-4)
    assert c["quota_usd"] == pytest.approx(900 * 100 / 28, rel=1e-4)  # the week at API prices
    assert fc["reading"] == {"at": "2026-11-02T21:00:00Z", "pct": 28.0, "since_usd": 25.0}
    assert fc["pct_now"] == pytest.approx(28 + 25 * 28 / 900, abs=0.05) and fc["estimated"] is False
    p = fc["pace"]
    assert p["usd"] == pytest.approx(925.0) and p["pct_h"] == pytest.approx(925 / 24 * 28 / 900, abs=1e-3)
    assert p["at_reset"] > 100 and p["full_at"].startswith("2026-11-05")  # Thursday, before Monday's reset
    assert fc["level"] == "none" and fc["advice"] == "open no new wave, finish the live ones"
    assert fc["line"].startswith("week 29 % now (read 28 % at 21:00 UTC); at the last 24 h's pace 100 % on Thu "
                                 "2026-11-05")
    assert fc["line"].endswith("before the reset Mon 2026-11-09 12:00 UTC: open no new wave, finish the live ones "
                               "(brain usage quota)")
    text = "\n".join(quota.render(fc))
    assert "the week window is about $3,214" in text and "on box1: $900 since the window started" in text


def test_the_session_hour_counts_the_agents(projects_dir, week):
    """wi-brain-usage-workflow-agents: a session-hour's cost holds its workflow agents' (their hours are merged into
    the session's), and an hour of crumbs is not a session-hour."""
    assert quota.forecast(week, [], NOW)["session_hour"] == {"usd": pytest.approx(950 / 10, abs=0.01), "hours": 10,
                                                             "total_usd": 950.0, "days": 7}
    crumbs = [{"session_id": "c", "hours": {"2026-11-02T08": {"cost": 0.1}, "2026-11-02T09": {"cost": 0.2}}}]
    assert quota.session_hour(crumbs, NOW) is None   # below SESSION_HOUR_MIN_USD: no session-hour
    old = [{"session_id": "o", "hours": _hours("2026-10-20T08:00", 5, 9.0)}]
    assert quota.session_hour(old, NOW) is None      # older than the 7 days
    boss = _write(projects_dir / "p" / "boss.jsonl", [
        _prompt(f"2026-11-02T{h:02d}:00:00Z", "go") for h in range(10, 14)] + [
        _asst(f"2026-11-02T{h:02d}:00:05Z", f"b{h}", [], out=100_000) for h in range(10, 14)])
    alone = quota.session_hour([usage.scan(boss)], NOW)
    agent = _write(projects_dir / "p" / "boss" / "subagents" / "workflows" / "wf_1" / "agent-x.jsonl", [
        _asst(f"2026-11-02T{h:02d}:10:00Z", f"x{h}", [], out=300_000) for h in range(10, 14)])
    assert usage.scan(boss)["agents"]["workflows"]["wf_1"]["agents"] == 1   # the agent is read as its session's
    with_agents = quota.session_hour([usage.scan(boss)], NOW)
    assert alone["hours"] == with_agents["hours"] == 4
    assert with_agents["usd"] == pytest.approx(4 * alone["usd"], rel=0.01)   # the agents' cost in the same hours
    assert any(x.startswith("  session-h") for x in quota.render(quota.forecast([usage.scan(boss)], [], NOW)))


def test_advice_levels():
    base = {"readings": 1, "conversion": {"pct_per_usd": 0.03}, "pct_now": 40.0}
    assert quota.advice({**base, "pace": {"at_reset": 70.0}})[0] == "room"
    assert quota.advice({**base, "pace": {"at_reset": 90.0}}) == ("p0p1", "open only P0/P1 waves")
    assert quota.advice({**base, "pace": {"at_reset": 120.0}})[0] == "none"
    assert quota.advice({**base, "pace": {"at_reset": 70.0}, "live": {"left_pct": 65.0}})[0] == "none"
    assert quota.advice({**base, "pace": {"at_reset": 70.0}, "queue": {"items": 4, "fit": 3}}) == (
        "room", "room for waves: about 3 of the 4 startable P0/P1 item(s) fit")
    assert quota.advice({"readings": 0, "pct_now": None})[1].startswith("read get_usage, then brain usage quota")


def test_without_a_reading_this_week_the_percent_is_estimated(week):
    old = [{"at": "2026-10-28T20:00:00Z", "window": "week", "pct": 50.0, "resets": "2026-11-02T12:00:00Z",
            "plan": "Ultra"}]
    rows = week + [{"session_id": "s0", "hours": _hours("2026-10-26T12:00", 10, 50.0)}]  # $500 in last week's window
    fc = quota.forecast(rows, old, NOW)
    assert fc["resets"] == RESET and fc["estimated"] is True and fc["reading"] is None
    assert fc["pct_now"] == pytest.approx(925 * 50 / 500, abs=0.05)
    assert "(estimated: no reading in this window)" in fc["line"]


def test_nothing_known_says_how_to_read_the_quota():
    fc = quota.forecast([], [], NOW)
    assert fc["level"] == "unknown" and fc["pct_now"] is None and fc["conversion"] is None
    assert fc["line"].startswith("week: not known; uncalibrated: Ultra has 0 of 1")
    assert fc["line"].endswith("; read get_usage, then brain usage quota --observe N --resets T (brain usage quota)")
    small = [{"at": "2026-11-02T13:00:00Z", "window": "week", "pct": 1.0, "resets": RESET}]
    fc = quota.forecast([{"hours": {"2026-11-02T12": {"cost": 2.0}}}], small, NOW)
    assert fc["conversion"] is None and "needs $5 of ledger cost" in fc["advice"] and "uncalibrated" in fc["advice"]


def test_the_live_sessions_left_and_how_many_queue_items_fit(week):
    readings = [{"at": "2026-11-02T21:00:00Z", "window": "week", "pct": 28.0, "resets": RESET}]
    live = {"sessions": 2, "items": ["wi-l"], "last_hour_usd": 50.0, "left_usd": 450.0, "median_session_usd": 15.0}
    queue = [{"id": f"wi-{i}", "project": "p", "priority": "P1", "usd": 600.0, "basis": "similar"} for i in range(5)]
    fc = quota.forecast(week, readings, NOW, live=live, queue=queue)
    f = 28 / 900
    assert fc["live"]["left_pct"] == pytest.approx(450 * f, abs=0.05)
    q = fc["queue"]
    assert q["room_pct"] == pytest.approx(100 - fc["pct_now"] - 450 * f, abs=0.1)
    assert q["fit"] == int(q["room_pct"] / (600 * f)) == 3 and q["fit_usd"] == 1800.0 and q["items"] == 5
    rows = [x for x in quota.render(fc) if x.startswith("  ") and x[2] != " " and x != "  readings"]
    assert any(x.startswith("  live      2 session(s)") for x in rows)
    assert all(x[11] == " " and x[12] != " " for x in rows), rows   # one label column: every value at column 12


def test_live_sessions_and_the_queue_from_the_ledger(project, now):
    led = _history(project)
    led.rows.append(dict(row("live", day="2026-11-02", usd=4.0, title_items=["wi-e"]), end="2026-11-02T21:25:00Z",
                         served=["wi-e"], project="demo"))
    led.items["wi-e"].sessions.append((led.rows[-1], 1.0))
    est = quota.estimator(led)
    usd, basis = est("wi-e")
    assert basis == "similar" and usd > 0
    lv = quota.live_of(led, NOW, est)
    assert lv["sessions"] == 1 and lv["items"] == ["wi-e"]
    assert lv["left_usd"] == pytest.approx(max(0.0, usd - 9.0), abs=0.01)  # wi-e's s5 ($5) and the live one ($4)
    q = quota.queue_of(led, [project], [], est)
    assert [x["id"] for x in q] == ["wi-one"] and q[0]["priority"] == "P0"


def test_cli_notes_a_reading_and_status_shows_the_line(project, now, capsys):
    root = str(project.root)
    assert cli.main(["--root", root, "usage", "quota", "--observe", "28", "--resets", RESET, "--at",
                     "2026-11-02T21:00Z", "--no-scan"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("noted: week 28 % at 2026-11-02T21:00:00Z, resets 2026-11-09T12:00:00Z")
    assert "quota (week, Ultra): week 28 % now (read 28 % at 21:00 UTC)" in out  # no ledger cost: not converted
    assert cli.main(["--root", root, "usage", "quota", "--json", "--no-scan"]) == 0
    fc = json.loads(capsys.readouterr().out)
    assert fc["readings"] == 1 and fc["queue"]["first"] == ["wi-one"]
    assert quota.load_status()["line"] == fc["line"]  # the cockpit's file
    with pytest.raises(SystemExit, match="go with --observe"):
        cli.main(["--root", root, "usage", "quota", "--at", "2026-11-02T21:00Z", "--no-scan"])
    with pytest.raises(SystemExit, match="between 0 and 100"):
        cli.main(["--root", root, "usage", "quota", "--observe", "130", "--no-scan"])
    data = status.run([project], quick=True)
    assert data["quota"]["line"] == fc["line"] and "now" not in data["quota"]
    assert any(x.startswith("  quota       week 28 % now") for x in status.render(data))


PLANS = (("2026-11-06", "Pro"), ("", "Ultra"))  # Ultra until the 6th, then Pro


def _rd(at, pct, plan=None, window="week", resets=RESET):
    return {"at": at, "window": window, "pct": pct, "resets": resets, **({"plan": plan} if plan else {})}


def test_a_plan_change_leaves_the_old_plans_readings_out(monkeypatch):
    monkeypatch.setattr(quota, "CAL_MIN", 3)
    now = datetime(2026, 11, 8, 12, tzinfo=UTC)
    rows = [{"hours": _hours("2026-10-26T12", 400, 10.0)}]  # $10 an hour throughout
    ultra = [_rd(f"2026-11-0{d}T20:00:00Z", 30.0, resets=f"2026-11-0{d + 1}T12:00:00Z") for d in (3, 4, 5)]
    fc = quota.forecast(rows, ultra, now, plans=PLANS)  # three Ultra readings, but the plan in force is Pro
    assert fc["plan"] == "Pro" and fc["readings"] == 0 and fc["conversion"] is None
    assert fc["uncalibrated"] == {"plan": "Pro", "n": 0, "needed": 3}
    assert fc["level"] == "unknown" and fc["advice"].startswith("uncalibrated: Pro has 0 of 3")
    # the same readings with the plan in force being theirs convert
    assert quota.forecast(rows, ultra, now, plans=(("", "Ultra"),))["conversion"]["n"] == 3


def test_an_uncalibrated_plan_estimates_from_the_5h_window(monkeypatch):
    monkeypatch.setattr(quota, "CAL_MIN", 3)
    now = datetime(2026, 11, 8, 12, tzinfo=UTC)
    rows = [{"hours": _hours("2026-11-08T07", 5, 10.0)}]  # $10 an hour since 07:00
    readings = [_rd("2026-11-08T10:00:00Z", 20.0, "Pro", "5h", "2026-11-08T12:00:00Z"),  # $30 since the window began
                _rd("2026-11-08T11:00:00Z", 10.0, "Pro"),
                _rd("2026-11-03T20:00:00Z", 60.0, "Ultra")]  # another plan: never in the median
    fc = quota.forecast(rows, readings, now + timedelta(minutes=-30), plans=PLANS)
    assert fc["uncalibrated"] == {"plan": "Pro", "n": 1, "needed": 3} and fc["conversion"] is None  # one Pro reading
    w5 = fc["window_5h"]
    assert w5["read_pct"] == 20.0 and w5["converted"] is True
    assert w5["pct_now"] == pytest.approx(20 + 15 * 20 / 30, abs=0.05)  # $15 since the reading at 20 % per $30
    text = " | ".join(quota.render(fc))
    assert "uncalibrated: Pro has 1 of 3" in text and "5h window about 30 %" in text
    assert "uncalibrated" in fc["line"] and "the 5h window is about 30 %" in fc["line"]


def test_a_calibrated_plan_converts_with_its_own_readings_only(monkeypatch):
    monkeypatch.setattr(quota, "CAL_MIN", 3)
    now = datetime(2026, 11, 9, 12, tzinfo=UTC)
    rows = [{"hours": _hours("2026-11-01T12", 200, 10.0)}]
    pro = [_rd(f"2026-11-0{d}T10:00:00Z", p, "Pro", resets=f"2026-11-0{d + 1}T12:00:00Z") for d, p in
           ((6, 10.0), (7, 20.0), (8, 40.0))]
    ultra = [_rd("2026-11-03T20:00:00Z", 5.0, "Ultra", resets="2026-11-04T12:00:00Z")]  # a wildly other factor
    with_ultra = quota.forecast(rows, ultra + pro, now, plans=PLANS)
    pro_only = quota.forecast(rows, pro, now, plans=PLANS)
    assert with_ultra["conversion"] == pro_only["conversion"] and with_ultra["uncalibrated"] is None
    assert with_ultra["conversion"]["n"] == 3 and with_ultra["plan"] == "Pro"
    assert "window_5h" not in with_ultra
    # a median over the Ultra reading too would have been lower: it is not in
    assert quota.calibrate(rows, ultra + pro, "week", now)["n"] == 4


def test_the_readings_are_read_across_the_monthly_files(now, brain_home):
    """wi-brain-logs-unclassified: quota.jsonl rotates monthly (brain.stateio.rotate_log, 12 months kept) and
    load_readings, the reader the forecast and the wave planner go through, reads every month in order."""
    rec = quota.observe(28, at=quota.parse_time("2026-11-02T21:05Z", now), resets=quota.parse_time(RESET, now))
    f = quota.readings_file()
    old = datetime(2026, 10, 30, tzinfo=UTC).timestamp()
    os.utime(f, (old, old))                               # last written in October: the next reading rotates it
    (f.parent / "quota-2026-09.jsonl").write_text(json.dumps({**rec, "at": "2026-09-30T10:00:00Z", "pct": 90.0,
                                                              "resets": "2026-10-05T12:00:00Z"}) + "\n",
                                                  encoding="utf-8")
    quota.observe(30)
    assert sorted(p.name for p in f.parent.glob("quota*.jsonl")) == ["quota-2026-09.jsonl", "quota-2026-10.jsonl",
                                                                       "quota.jsonl"]
    assert [r["pct"] for r in quota.load_readings()] == [90.0, 28.0, 30.0]
    (f.parent / "quota-2025-10.jsonl").write_text("{}\n", encoding="utf-8")   # past the 12 months
    os.utime(f, (old, old))
    quota.observe(31)
    assert not (f.parent / "quota-2025-10.jsonl").exists() and (f.parent / "quota-2026-09.jsonl").exists()
