"""wi-brain-project-alerts: the alert event, the sources (scheduler, ledger, stacks, code index, audit, events,
files), the 2-missed-passes rule, the notify pass and the alerts row of brain status."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from brain import alerts, cli, notify, projects, schema, stacks, status, timing

from test_notify import ENV, Fake

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
EVERY_15 = [{"type": "MSFT_TaskDailyTrigger", "enabled": True, "interval": "PT15M", "duration": "P1D", "days": 1}]
DAILY = [{"type": "MSFT_TaskDailyTrigger", "enabled": True, "interval": None, "duration": None, "days": 1}]
ALERTS_MD = """\
# Alerts

## 2026-10-20 — freshness monitor
FAIL  freshness:old_source  MISSING (age 9 d > max 7 d; data/old.parquet)

## 2026-11-01 — freshness monitor
WARN  freshness:returns_matic  STALE (age 781.0 d > max 7 d; data/m.parquet)
WARN  freshness:gone  STALE (age 8 d > max 7 d)

## 2026-11-02 — freshness monitor
WARN  freshness:returns_matic  STALE (age 782.0 d > max 7 d; data/m.parquet)
FAIL  freshness:prices  MISSING (age 3 d > max 1 d; data/p.parquet)

## 2026-10-29 — scan funding_diff v2
WARN  scan:funding_diff  WTI short lighter / long extended  3 consecutive passes

## 2026-10-01 — reconfirm monitor
FAIL  reconfirm:exp-1  verdict FLIPPED 2 consecutive runs
"""


@pytest.fixture(autouse=True)
def frozen(monkeypatch):
    monkeypatch.setattr(alerts, "_now", lambda: NOW)


def _project(tmp_path, monkeypatch, alerts_entry="", notify_entry="", root=None):
    root = root or tmp_path / "demo"
    root.mkdir(parents=True, exist_ok=True)
    text = f"demo:\n  root: {root.as_posix()}\n"
    if alerts_entry:
        text += "  alerts:\n" + "".join(f"    {line}\n" for line in alerts_entry.strip("\n").splitlines())
    if notify_entry:
        text += "  notify:\n" + "".join(f"    {line}\n" for line in notify_entry.strip("\n").splitlines())
    reg = tmp_path / "projects.yaml"
    reg.write_text(text, encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    return projects.load()["demo"]


def _row(name, last_run, result=0, state="Ready", triggers=EVERY_15, folder="\\demo\\"):
    return {"name": name, "folder": folder, "state": state, "last_run": last_run and alerts._iso(last_run),
            "last_result": result, "triggers": triggers}


def _keys(found):
    return {a.key: a.level for a in found}


# --- the event ---

def test_the_alert_event_follows_the_shared_schema_and_folds_by_key(tmp_path, monkeypatch):
    p = _project(tmp_path, monkeypatch)
    ev = alerts.emit("demo", "freshness:prices", "error", "MISSING (age 3 d)", task="prices", source="freshness",
                     code=2, at=NOW - timedelta(hours=2))
    assert schema.check("event", ev) == ([], [])
    assert ev["kind"] == "alert" and ev["state"] == "open" and ev["severity"] == "error"
    f = tmp_path / "brain-home" / "ledger" / "alert-2026-11.jsonl"
    assert json.loads(f.read_text(encoding="utf-8").splitlines()[0])["key"] == "freshness:prices"
    alerts.emit("demo", "freshness:other", "warn", "STALE", at=NOW - timedelta(hours=1))
    alerts.emit("demo", "freshness:prices", state="resolved", level="info", at=NOW - timedelta(minutes=5))
    alerts.emit("elsewhere", "x:y", "critical", "another project's", at=NOW)
    found = alerts.of_project(p)
    assert _keys(found) == {"freshness:other": "warn"}
    assert found[0].source == "events" and found[0].since == "2026-11-02T11:00:00.000Z"
    bad = dict(ev, key="has a space")
    assert schema.check("event", bad)[0] and schema.check("event", {k: v for k, v in ev.items() if k != "state"})[0]
    with pytest.raises(ValueError):
        alerts.emit("demo", "k", "loud", "x")


def test_error_events_stay_open_until_their_task_succeeds_or_a_day_passes(tmp_path, monkeypatch):
    d = tmp_path / "events"
    d.mkdir()
    lines = [
        {"v": 1, "kind": "error", "at": "2026-11-02T08:00:00Z", "host": "h", "project": "demo", "task": "download",
         "code": "HTTP_429", "severity": "warn", "details": "rate limited"},
        {"v": 1, "kind": "error", "at": "2026-11-02T09:00:00Z", "host": "h", "project": "demo", "task": "cycle",
         "code": 2, "severity": "error"},
        {"v": 1, "kind": "exec", "at": "2026-11-02T10:00:00Z", "host": "h", "project": "demo", "task": "cycle",
         "start": "2026-11-02T09:59:00Z", "end": "2026-11-02T10:00:00Z", "duration_s": 60, "exit": 0},
        {"v": 1, "kind": "error", "at": "2026-10-31T09:00:00Z", "host": "h", "project": "demo", "task": "old",
         "code": 1, "severity": "error"},
    ]
    (d / "2026-11-02.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n", encoding="utf-8")
    p = _project(tmp_path, monkeypatch, f"events: ['{d.as_posix()}']")
    found = alerts.of_project(p)
    assert _keys(found) == {"error:download:HTTP_429": "warn"}
    assert found[0].message == "download: error HTTP_429: rate limited"


# --- the scheduler and the ledger ---

def test_cadence_from_the_triggers():
    assert alerts.cadence({"triggers": EVERY_15}) == 900
    assert alerts.cadence({"triggers": DAILY}) == 86400
    window = [{"type": "MSFT_TaskDailyTrigger", "interval": "PT15M", "duration": "PT2H", "days": 1}]
    assert alerts.cadence({"triggers": window}) == 86400  # a window: watched at its day
    assert alerts.cadence({"triggers": [{"type": "MSFT_TaskWeeklyTrigger", "weeks": 2}]}) == 14 * 86400
    assert alerts.cadence({"triggers": [{"type": "MSFT_TaskLogonTrigger"}]}) is None
    assert alerts.cadence({"triggers": DAILY + EVERY_15}) == 900
    assert alerts.cadence({"triggers": [dict(EVERY_15[0], enabled=False)]}) is None
    assert alerts.seconds("15m") == 900 and alerts.seconds("1d") == 86400 and alerts.seconds(30) == 1800
    assert alerts.iso_seconds("PT1H30M") == 5400 and alerts.iso_seconds("") is None


@pytest.mark.parametrize("minutes, expected", [
    (10, {}),
    (16, {}),                                    # within the grace (a tenth of the cadence, a minute at least)
    (20, {"task:snap:missed": "info"}),          # one missed pass: late, shown, not an alert
    (31, {"task:snap:missed": "info"}),
    (32, {"task:snap:missed": "error"}),         # two missed passes (Ada, 2026-10-30): 30 minutes plus the grace
])
def test_a_15_minute_task_alerts_after_two_missed_passes(minutes, expected):
    row = _row("snap", NOW - timedelta(minutes=minutes))
    assert _keys(alerts.task_alerts("demo", alerts.Task("snap"), row, [], {}, NOW)) == expected


def test_missed_message_and_a_running_task_is_never_missed():
    row = _row("snap", NOW - timedelta(minutes=50))
    [a] = alerts.task_alerts("demo", alerts.Task("snap"), row, [], {}, NOW)
    assert a.message == "snap: 3 passes missed, every 15 min, last run started 2026-11-02 11:10Z"
    assert a.since == "2026-11-02T11:25:00Z" and a.source == "scheduler"
    assert alerts.task_alerts("demo", alerts.Task("snap"), dict(row, state="Running", last_result=0x41301), [], {},
                              NOW) == []
    daily = _row("cycle", NOW - timedelta(hours=26), triggers=DAILY)
    assert _keys(alerts.task_alerts("demo", alerts.Task("cycle"), daily, [], {}, NOW)) == {"task:cycle:missed": "info"}
    assert _keys(alerts.task_alerts("demo", alerts.Task("cycle", missed=1), daily, [], {}, NOW)) == \
        {"task:cycle:missed": "error"}


@pytest.mark.parametrize("result, exits, expected", [
    (0, {}, {}),
    (0x41306, {}, {"task:t:killed": "error"}),                  # terminated at its time limit
    (-1073741510, {}, {"task:t:killed": "error"}),              # 0xC000013A as a signed int
    (2, {}, {"task:t:result": "error"}),
    (1, {1: "warn", 10: "ok"}, {"task:t:result": "warn"}),
    (10, {1: "warn", 10: "ok"}, {}),                            # a project's "not due"
    (0x8004131F, {}, {}),                                       # an instance was already running
    (0x80070002, {}, {"task:t:result": "error"}),
    (0x8BADF00D, {}, {"task:t:result": "error"}),               # uncatalogued
])
def test_the_last_result_is_read_through_the_catalogue_and_exits(result, exits, expected):
    row = _row("t", NOW - timedelta(minutes=5), result=result)
    found = alerts.task_alerts("demo", alerts.Task("t"), row, [], exits, NOW)
    assert _keys(found) == expected
    if result == 0x8BADF00D:
        assert found[0].code == "0x8BADF00D" and "uncatalogued" in found[0].message


def test_disabled_permanent_unproven_and_silent_tasks():
    disabled = _row("t", NOW - timedelta(days=3), state="Disabled")
    assert _keys(alerts.task_alerts("demo", alerts.Task("t"), disabled, [], {}, NOW)) == {"task:t:disabled": "info"}
    rec = alerts.Task("rec", running=True)
    assert alerts.task_alerts("demo", rec, _row("rec", NOW - timedelta(days=1), state="Running"), [], {}, NOW) == []
    assert _keys(alerts.task_alerts("demo", rec, _row("rec", NOW - timedelta(hours=1)), [], {}, NOW)) == \
        {"task:rec:stopped": "error"}
    assert _keys(alerts.task_alerts("demo", alerts.Task("new"), _row("new", None, result=0x41303), [], {}, NOW)) == \
        {"task:new:unproven": "warn"}
    # ran at 11:45 by the scheduler, but the last proof in the exec ledger is from 11:30
    t = alerts.Task("snap", ledger="snapshot*")
    runs = [{"kind": "exec", "task": "snapshot", "start": "2026-11-02T11:30:00Z", "at": "2026-11-02T11:31:00Z",
             "exit": 0}]
    found = alerts.task_alerts("demo", t, _row("snap", NOW - timedelta(minutes=15)), runs, {}, NOW)
    assert _keys(found) == {"task:snap:silent": "warn"}
    assert "without its proof in the exec ledger" in found[0].message
    proven = [dict(runs[0], start="2026-11-02T11:45:01Z", at="2026-11-02T11:46:00Z")]
    assert alerts.task_alerts("demo", t, _row("snap", NOW - timedelta(minutes=15)), proven, {}, NOW) == []


def test_a_task_proven_by_the_ledger_alone(tmp_path, monkeypatch):
    p = _project(tmp_path, monkeypatch, "tasks:\n  cycle: {every: 1h, ledger: 'cycle L*'}\n  nothing: {every: 1d}")
    t0 = NOW - timedelta(hours=4)  # the last run started 3 h ago: two hourly passes missed
    timing.write_event(timing.make_event("cycle L4", t0, t0 + timedelta(minutes=5), 300, 0, project="demo",
                                         version="abc"))
    timing.write_event(timing.make_event("cycle L4", t0 + timedelta(hours=1), t0 + timedelta(hours=1, minutes=1), 60,
                                         130, project="demo", version="abc", error="interrupted"))
    found = {a.key: a for a in alerts.of_project(p)}
    assert found["task:cycle:missed"].level == "error" and found["task:cycle:missed"].source == "ledger"
    assert "1 h" in found["task:cycle:missed"].message
    assert found["task:cycle:killed"].level == "error" and "interrupted" in found["task:cycle:killed"].message
    assert found["task:nothing:unproven"].message == "nothing: no run proven yet (no scheduler task and no ledger: " \
                                                     "pattern)"


def test_scheduler_folders_errors_and_quick(tmp_path, monkeypatch):
    p = _project(tmp_path, monkeypatch, "scheduler: ['\\Demo']\ntasks:\n  rec: {running: true}")  # YAML: '\Demo'
    calls = []

    def fake(folders):
        calls.append(folders)
        return [_row("snap", NOW - timedelta(hours=1)), _row("rec", NOW - timedelta(hours=1)),
                _row("other", NOW - timedelta(days=9), folder="\\elsewhere\\")], ""

    monkeypatch.setattr(alerts, "_scheduler", fake)
    cfg = alerts.config(p)
    sched = alerts.read_scheduler([cfg, alerts.Config("none")])
    assert calls == [["\\Demo"]]
    assert _keys(alerts.of_project(p, sched=sched)) == {"task:snap:missed": "error", "task:rec:stopped": "error"}
    assert alerts.of_project(p, sched={}) == []  # --quick: the scheduler is not read
    monkeypatch.setattr(alerts, "_scheduler", lambda folders: ([], "the scheduler could not be read: access denied"))
    [a] = alerts.of_project(p, sched=alerts.read_scheduler([cfg]))
    assert (a.key, a.level, a.message) == ("scheduler", "warn", "not read: the scheduler could not be read: access "
                                                                "denied")
    assert alerts.read_scheduler([alerts.Config("none")]) == {}


# --- stacks, code index, audit, files ---

def test_stacks_code_index_and_levels(tmp_path, monkeypatch):
    p = _project(tmp_path, monkeypatch, "stacks: [db]\nlevels: {code-index: warn}")
    rows = [{"name": "web", "state": "DOWN", "why": "refused"}, {"name": "db", "state": "STALE", "why": "drift"},
            {"name": "idle", "state": "DOWN", "why": "on demand"}]
    ix = [{"repo": "lab", "state": "STALE", "why": "main is 2 commits past"}, {"repo": "ok", "state": "OK", "why": ""}]
    found = alerts.of_project(p, stacks_rows=rows, index_rows=ix, watched={"web"})
    assert _keys(found) == {"stack:web": "error", "stack:db": "warn", "code-index:lab": "warn"}
    assert found[0].message == "stack web DOWN: refused"  # sorted by level first
    assert "brain index lab" in {a.key: a for a in found}["code-index:lab"].message


def test_audit_debt_above_the_written_view(tmp_path, monkeypatch):
    p = _project(tmp_path, monkeypatch)
    (p.root / "notes").mkdir()
    (p.root / "notes" / "audit.md").write_text("# Conformance audit\n\n**demo: P0 0, P1 4, P2 23.**\n",
                                               encoding="utf-8")
    measured = {"counts": {"P0": 0, "P1": 5, "P2": 20, "info": 3}, "repos": 1, "unreadable": []}
    [a] = alerts.of_project(p, audit=measured)
    assert (a.key, a.level) == ("audit:debt", "warn") and a.message.endswith("P1 4 -> 5")
    assert alerts.of_project(p, audit={"counts": {"P0": 0, "P1": 4, "P2": 23}}) == []
    assert _keys(alerts.of_project(p, audit={"counts": {"P0": 1, "P1": 4, "P2": 30}})) == {"audit:debt": "error"}
    assert alerts.of_project(p, audit={"error": "bad repos"}) == []
    (p.root / "notes" / "audit.md").unlink()
    assert alerts.of_project(p, audit=measured) == []  # no baseline, no alert


def test_markdown_alert_files_each_writers_latest_block(tmp_path, monkeypatch):
    p = _project(tmp_path, monkeypatch, "files: [notes/alerts.md, notes/none.md]")
    (p.root / "notes").mkdir()
    (p.root / "notes" / "alerts.md").write_text(ALERTS_MD, encoding="utf-8")
    found = {a.key: a for a in alerts.of_project(p)}
    assert {k: a.level for k, a in found.items()} == {"freshness:prices": "error", "freshness:returns_matic": "warn",
                                                     "scan:funding_diff": "warn"}  # gone and old_source closed
    a = found["freshness:returns_matic"]
    assert a.message == "STALE (age 782.0 d > max 7 d; data/m.parquet) (demo/notes/alerts.md, freshness monitor " \
                        "2026-11-02)"  # named with its repo's folder
    assert a.subject == "returns_matic" and a.source == "file" and a.since == "2026-11-02T00:00:00Z"
    blocks = alerts.parse_file("## 2026-11-02 08:00:00 - ALERT\n**Issues:**\n- something\n")
    assert blocks == [{"date": "2026-11-02", "time": "08:00:00", "writer": "ALERT", "lines": []}]


@pytest.mark.parametrize("entry, error", [
    ("bogus: 1", "unknown key(s) bogus"),
    ("tasks:\n  t: {every: often}", "every: 'often': a duration"),
    ("tasks:\n  t: {missed: 0}", "missed is a number of passes"),
    ("tasks:\n  t: {level: loud}", "a level"),
    ("tasks:\n  t: {when: now}", "unknown key(s) when"),
    ("exits: {1: maybe}", "exits: 1: 'maybe'"),
    ("levels: {weather: warn}", "unknown source 'weather'"),
    ("files: notes/a.md\nstacks: [1]", "alerts stacks: a list of strings"),
])
def test_configuration_errors(tmp_path, monkeypatch, entry, error):
    p = _project(tmp_path, monkeypatch, entry)
    with pytest.raises(alerts.AlertsError, match=error.replace("(", r"\(").replace(")", r"\)")):
        alerts.config(p)
    assert alerts.check(projects.load()) and projects.check() == []  # the registry knows the key


def test_an_alerts_file_relative_to_the_root(tmp_path, monkeypatch):
    root = tmp_path / "demo"
    root.mkdir()
    (root / "alerts.yaml").write_text("files: [a.md]\nlevels: {file: critical}\n", encoding="utf-8")
    (tmp_path / "projects.yaml").write_text(f"demo: {{root: {root.as_posix()}, alerts: alerts.yaml}}\n",
                                            encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(tmp_path / "projects.yaml"))
    (root / "a.md").write_text("## 2026-11-02 — m\nWARN  m:x  bad\n", encoding="utf-8")
    assert _keys(alerts.of_project(projects.load()["demo"])) == {"m:x": "critical"}


# --- the notify pass ---

NOTIFY = """\
channels:
  ntfy: {type: ntfy, server: https://ntfy.sh, topic_env: T_TOPIC}
levels: {info: [ntfy], warn: [ntfy], error: [ntfy], critical: [ntfy]}
"""


def _pass(p, dry_run=False):
    data = alerts.run([p], quick=True)
    return data, alerts.notify_pass(data, {p.name: p}, dry_run=dry_run, env=ENV)


def test_the_pass_sends_new_risen_failed_and_resolved_alerts_once(tmp_path, monkeypatch):
    fake = Fake()
    monkeypatch.setattr(notify, "_post_json", fake.post)
    p = _project(tmp_path, monkeypatch, "files: [a.md]", NOTIFY)
    md = p.root / "a.md"
    md.write_text("## 2026-11-02 — m\nWARN  m:x  bad\n", encoding="utf-8")
    _, lines = _pass(p, dry_run=True)
    assert lines[0] == "demo: warn m:x: dry-run" and not fake.posts
    assert not (tmp_path / "brain-home" / "alerts" / "state.json").exists()
    _, lines = _pass(p)
    assert lines[0] == "demo: warn m:x: delivered" and len(fake.posts) == 1
    sent = fake.posts[0][1]
    assert sent["title"] == "[demo warn] bad (demo/a.md, m 2026-11-02)" and sent["priority"] == 3
    _, lines = _pass(p)
    assert lines == ["demo: 1 open, 0 new, risen or retried, 0 resolved"] and len(fake.posts) == 1  # once
    md.write_text("## 2026-11-02 — m\nFAIL  m:x  worse\n", encoding="utf-8")
    _pass(p)
    assert fake.posts[-1][1]["priority"] == 4 and len(fake.posts) == 2   # the level rose: sent again
    md.write_text("## 2026-11-02 — m\n", encoding="utf-8")
    _, lines = _pass(p)
    assert lines[0] == "demo: resolved m:x: delivered" and fake.posts[-1][1]["title"] == "[demo info] resolved: " \
                                                                                        "worse (demo/a.md, m 2026-11-02)"
    state = alerts.state_load()["demo"]
    assert state == {"open": {}, "last_pass": "2026-11-02T12:00:00Z"}
    hist = (tmp_path / "brain-home" / "alerts" / "alert-2026-11.jsonl").read_text(encoding="utf-8").splitlines()
    events = [json.loads(x) for x in hist]
    assert [(e["state"], e["severity"]) for e in events] == [("open", "warn"), ("open", "error"), ("resolved", "error")]
    assert all(schema.check("event", e) == ([], []) for e in events)


def test_a_failed_send_is_retried_and_no_route_is_not(tmp_path, monkeypatch):
    fake = Fake(fail={"ntfy"})
    monkeypatch.setattr(notify, "_post_json", fake.post)
    p = _project(tmp_path, monkeypatch, "files: [a.md]", NOTIFY.replace("info: [ntfy], ", ""))
    (p.root / "a.md").write_text("## 2026-11-02 — m\nWARN  m:x  bad\nINFO  m:y  fyi\n", encoding="utf-8")
    _, lines = _pass(p)
    assert set(lines[:2]) == {"demo: warn m:x: failed", "demo: info m:y: no-route"}
    fake.fail.clear()
    _, lines = _pass(p)
    assert lines[0] == "demo: warn m:x: delivered" and len(lines) == 2  # m:y is not sent again
    (p.root / "a.md").write_text("## 2026-11-02 — m\n", encoding="utf-8")
    _, lines = _pass(p)
    assert "demo: resolved m:y: not sent (its alert was not delivered)" in lines


def test_the_pass_reaches_nothing_without_a_route_and_with_notify_off(tmp_path, monkeypatch):
    fake = Fake()
    monkeypatch.setattr(notify, "_post_json", fake.post)
    p = _project(tmp_path, monkeypatch, "files: [a.md]")
    (p.root / "a.md").write_text("## 2026-11-02 — m\nFAIL  m:x  bad\n", encoding="utf-8")
    data = alerts.run([p], quick=True)
    assert alerts.notify_pass(data, {p.name: p})[0] == "demo: error m:x: no-route"
    p = _project(tmp_path, monkeypatch, "files: [a.md]", NOTIFY)
    (tmp_path / "brain-home" / "alerts" / "state.json").unlink()
    assert alerts.notify_pass(alerts.run([p], quick=True), {p.name: p})[0] == "demo: error m:x: off"  # BRAIN_NOTIFY
    assert not fake.posts


# --- brain status and the CLI ---

def test_status_shows_the_alerts_row_and_the_totals(tmp_path, monkeypatch, store, capsys):
    root = store.parents[1]
    p = _project(tmp_path, monkeypatch, "files: [a.md]", root=root)
    (root / "a.md").write_text(ALERTS_MD, encoding="utf-8")
    d = status.collect(p, quick=True)
    assert d["alerts"]["open"] == 3 and d["alerts"]["counts"] == {"error": 1, "warn": 2}
    line = alerts.status_line(d["alerts"])
    assert line.startswith("3 open: 1 error, 2 warn; freshness:prices (error), ") and line.endswith(
        "(brain alerts); last notify pass never")
    assert cli.main(["status", "--project", "demo", "--quick"]) == 0
    assert "  alerts      3 open: 1 error, 2 warn; freshness:prices (error)" in capsys.readouterr().out
    data = status.run([p], every=True, quick=True)
    assert data["total"]["alerts"] == {"critical": 0, "error": 1, "warn": 2, "info": 0}
    assert "  alerts      1 error, 2 warn open" in status.render(data)
    s = stacks.Stack("web", "demo", ["run"], watch=True)
    monkeypatch.setattr(stacks, "state", lambda s: ("DOWN", "refused"))
    monkeypatch.setattr(status, "audit_of", lambda p: {"counts": {"P0": 0, "P1": 0, "P2": 0}, "repos": 1,
                                                       "unreadable": []})
    full = status.collect(p, stack_reg={"web": s}, index=(None, {}, {}, None), sched={})
    assert {"stack:web": "error"}.items() <= {a["key"]: a["level"] for a in full["alerts"]["alerts"]}.items()
    _project(tmp_path, monkeypatch, "bogus: 1", root=root)
    assert status.collect(projects.load()["demo"], quick=True)["alerts"] == {
        "error": "demo: alerts: unknown key(s) bogus (known: events, exits, files, levels, scheduler, stacks, tasks)"}


def test_cli_view_fail_on_raise_resolve_and_notify(tmp_path, monkeypatch, capsys):
    p = _project(tmp_path, monkeypatch)
    assert cli.main(["alerts", "raise", "freshness:prices", "MISSING (age 3 d)", "--level", "error", "--project",
                     "demo", "--source", "freshness", "--code", "2"]) == 0
    assert capsys.readouterr().out == "alert open: demo freshness:prices (error)\n"
    assert cli.main(["alerts", "--project", "demo", "--quick"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines() == ["demo: 1 open (1 error); last notify pass never (--quick: scheduler, stacks, code "
                                "index and audit not read)",
                                "  ERROR    freshness:prices  MISSING (age 3 d) [freshness]"]
    assert cli.main(["alerts", "--project", "demo", "--quick", "--fail-on", "error"]) == 1
    assert cli.main(["alerts", "--project", "demo", "--quick", "--fail-on", "critical"]) == 0
    capsys.readouterr()
    assert cli.main(["alerts", "--project", "demo", "--quick", "--json", "--notify"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["projects"][0]["alerts"][0]["code"] == 2 and data["notify"][0] == "demo: error freshness:prices: " \
                                                                                  "no-route"
    assert alerts.state_load()["demo"]["last_pass"] == "2026-11-02T12:00:00Z"
    assert cli.main(["alerts", "resolve", "freshness:prices", "--project", "demo"]) == 0
    capsys.readouterr()
    assert cli.main(["alerts", "--project", "demo", "--quick", "--notify"]) == 0
    out = capsys.readouterr().out
    assert "demo: 0 open; last notify pass 2026-11-02T12:00:00Z" in out
    assert "  demo: resolved freshness:prices: not sent (its alert was not delivered)" in out
    with pytest.raises(SystemExit):
        cli.main(["alerts", "--project", "demo", "--dry-run"])
    assert p.name == "demo"
