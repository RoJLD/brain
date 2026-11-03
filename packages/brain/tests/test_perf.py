import io
import json
from datetime import datetime, timedelta, timezone

import pytest

from brain import cli, perf, timing

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


def _day(month, day, hour=6):
    return datetime(2026, month, day, hour, tzinfo=timezone.utc)


def _ev(task, end, d, exit=0, project="quant", version="a1", ledger=None):
    timing.write_event(timing.make_event(task, end - timedelta(seconds=d), end, d, exit, project=project,
                                         version=version), ledger)


@pytest.fixture
def ledger(brain_home):
    for day, d in ((10, 100), (12, 110), (14, 90), (16, 100)):
        _ev("cycle L4", _day(10, day), d)
    for day, d in ((28, 200), (30, 210)):
        _ev("cycle L4", _day(10, day), d, version="b2")
    _ev("cycle L4", _day(11, 1), 190, version="b2")
    _ev("cycle L4", _day(10, 31), 50, exit=2, version="b2")
    for month, day, d in ((10, 8, 2460), (10, 20, 2400), (10, 29, 2500), (11, 1, 2440)):
        _ev("download f1v2", _day(month, day), d)
    for month, day, d in ((10, 6, 30), (10, 27, 31), (11, 2, 29)):
        _ev("pytest", _day(month, day), d, project="brain", version="c3")
    _ev("pytest", _day(9, 30), 999, project="brain", version="c3")  # before the period: its month is not read
    with open(brain_home / "ledger" / "exec-2026-10.jsonl", "a", encoding="utf-8") as fh:
        fh.write("not json\n")
        fh.write(json.dumps({"v": 1, "kind": "exec", "at": "2026-10-20T00:00:00Z", "task": "no duration"}) + "\n")
        fh.write(json.dumps({"v": 1, "kind": "error", "at": "2026-10-20T00:00:00Z", "host": "h", "task": "cycle",
                             "code": 2, "severity": "error"}) + "\n")
    return brain_home / "ledger"


def _report(**kw):
    since = perf.parse_since(kw.pop("since", None), NOW)
    runs, skipped = perf.load(kw.pop("sources", None), since, NOW, kw.pop("project", None), kw.pop("task", None))
    return perf.report(runs, skipped, since, NOW, **kw)


def test_slowest_steps(ledger):
    rep = _report()
    assert (rep["runs"], rep["tasks"], rep["skipped"], rep["projects"]) == (15, 3, 2, ["brain", "quant"])
    assert [r["task"] for r in rep["slowest"]] == ["download f1v2", "cycle L4", "pytest"]
    l4 = rep["slowest"][1]
    assert (l4["runs"], l4["failed"], l4["median_s"], l4["p90_s"], l4["max_s"]) == (8, 1, 110, 210, 210)
    assert l4["total_s"] == 100 + 110 + 90 + 100 + 200 + 210 + 190 + 50


def test_trends_and_regressions(ledger):
    rep = _report()
    trends = {r["task"]: r for r in rep["trends"]}
    assert trends["cycle L4"]["verdict"] == "slower" and trends["cycle L4"]["change"] == 1.0
    assert (trends["cycle L4"]["before_s"], trends["cycle L4"]["recent_s"]) == (100, 200)
    assert trends["download f1v2"]["verdict"] == "" and abs(trends["download f1v2"]["change"]) < 0.05
    assert "pytest" not in trends  # one run before the last 7 days: MIN_RUNS (2) are needed on each side
    assert [(r["task"], r["from"], r["to"], r["before_s"], r["after_s"]) for r in rep["regressions"]] == [
        ("cycle L4", "a1", "b2", 100, 200)]


def test_time_lost_per_week(ledger):
    weeks = {r["week"]: r for r in _report()["weeks"]}
    w44 = weeks["2026-W44"]
    assert w44["failed_s"] == 50  # the failed run must be redone
    assert w44["slow_s"] == (200 - 110) + (210 - 110) + (190 - 110)  # over the median, runs slower than x1.5
    assert w44["lost_s"] == w44["failed_s"] + w44["slow_s"]
    assert weeks["2026-W41"]["lost_s"] == 0
    assert sum(r["runs"] for r in weeks.values()) == 15


def test_filters_and_sources(ledger, tmp_path):
    assert {r["task"] for r in _report(project="brain")["slowest"]} == {"pytest"}
    assert {r["task"] for r in _report(task="CYCLE")["slowest"]} == {"cycle L4"}
    assert _report(since="2026-10-27")["runs"] == 8
    other = tmp_path / "events"
    _ev("collector", _day(10, 30), 12, project="quant", ledger=other)
    rep = _report(sources=[str(other)])
    assert [r["task"] for r in rep["slowest"]] == ["collector"] and rep["skipped"] == 0
    with pytest.raises(perf.PerfError):
        _report(sources=[str(tmp_path / "missing")])


def test_parse_since():
    assert perf.parse_since(None, NOW) == NOW - timedelta(days=28)
    assert perf.parse_since("10d", NOW) == NOW - timedelta(days=10)
    assert perf.parse_since("2w", NOW) == NOW - timedelta(days=14)
    assert perf.parse_since("2026-10-20", NOW) == datetime(2026, 10, 20, tzinfo=timezone.utc)
    assert perf.parse_since("2026-10-20T06:00:00Z", NOW) == datetime(2026, 10, 20, 6, tzinfo=timezone.utc)
    with pytest.raises(perf.PerfError):
        perf.parse_since("last tuesday", NOW)


def test_main_text_json_and_empty(ledger, capsys):
    out = io.StringIO()
    assert perf.main(out=out, now=NOW) == 0
    text = out.getvalue()
    assert text.startswith("perf: 15 run(s) of 3 task(s), 2 project(s), 2026-10-05 to 2026-11-02 (2 line(s) skipped)")
    for header in ("slowest steps", "trends", "regressions after a change", "time lost per week"):
        assert header in text
    assert "a1 -> b2" in text and "1 min 40 s" in text and "+100%" in text and "2026-W44" in text
    out = io.StringIO()
    assert perf.main(as_json=True, top=1, out=out, now=NOW) == 0
    data = json.loads(out.getvalue())
    assert len(data["slowest"]) == 1 and data["regressions"][0]["to"] == "b2"
    out = io.StringIO()
    assert perf.main(project="nobody", out=out, now=NOW) == 0
    assert out.getvalue().startswith("perf: no exec event since 2026-10-05") and "brain timed" in out.getvalue()
    assert perf.main(since="soon", now=NOW) == 2
    assert "--since" in capsys.readouterr().err


def test_cli_perf(brain_home, capsys):
    now = datetime.now(timezone.utc)
    _ev("recent step", now - timedelta(hours=1), 3.5, project="p1")
    _ev("other step", now - timedelta(hours=1), 1.5, project="p2")
    assert cli.main(["perf", "--json", "--project", "p1"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["project"] == "p1" and [r["task"] for r in data["slowest"]] == ["recent step"]
    assert cli.main(["--project", "p2", "perf", "--since", "1d"]) == 0
    assert "other step" in capsys.readouterr().out
