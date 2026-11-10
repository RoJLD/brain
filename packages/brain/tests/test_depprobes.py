"""wi-brain-dependency-probes: loud fallbacks. The probe kinds (file-age, json-age, command, http), their declarations
in config.json, this machine's list, the run and its record, the alerts they raise through the alerts pass (sent once,
resolved once), brain status's probes row, the cockpit's health line and brain probes."""

import http.server
import json
import os
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from brain import alerts, cli, cockpit, config, depprobes, notify, projects, status

from test_notify import ENV, Fake

NOTIFY = """\
    channels:
      ntfy: {type: ntfy, server: https://ntfy.sh, topic_env: T_TOPIC}
    levels: {info: [ntfy], warn: [ntfy], error: [ntfy], critical: [ntfy]}
"""


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    """No run of another test is read back: each test starts with this process's memory empty."""
    monkeypatch.setattr(depprobes, "_LATEST", {})


def _config(tmp_path, monkeypatch, probes) -> config.Config:
    f = tmp_path / "personal" / "config.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"v": 1, "identity": {"owner": "Ada"}, "probes": probes}), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(f))
    return config.load()


def _age(path, hours: float) -> None:
    t = time.time() - hours * 3600
    os.utime(path, (t, t))


def _brain(tmp_path, monkeypatch, notify_entry="", name="brain"):
    root = tmp_path / f"{name}-repo"
    root.mkdir(exist_ok=True)
    text = f"{name}:\n  root: {root.as_posix()}\n" + (f"  notify:\n{notify_entry}" if notify_entry else "")
    (tmp_path / "projects.yaml").write_text(text, encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(tmp_path / "projects.yaml"))
    return projects.load()[name]


# --- the declarations ---

def test_each_kind_parses_with_its_defaults():
    p = depprobes.parse("backup", {"kind": "file-age", "path": "D:/b/*.zip", "max_age": "26h"})
    assert p["level"] == "warn" and p["timeout"] == depprobes.TIMEOUT and p["max_age"] == 26 * 3600
    assert p["machines"] == []
    c = depprobes.parse("login", {"kind": "command", "argv": ["tool", "auth", "status"], "expect": "in",
                                  "timeout": "20s", "level": "error", "machines": ["host-a"]})
    assert c["ok_exit"] == [0] and c["timeout"] == 20 and c["level"] == "error"
    h = depprobes.parse("ui", {"kind": "http", "url": "http://127.0.0.1:1/x?q=1"})
    assert h["ok_status"] == []
    j = depprobes.parse("sent", {"kind": "json-age", "path": "a.jsonl", "field": "at", "max_age": "7d",
                                 "where": {"outcome": "sent"}})
    assert j["where"] == {"outcome": "sent"}


@pytest.mark.parametrize("name, conf, says", [
    ("x", {"kind": "ping"}, "kind 'ping'"),
    ("x", {"kind": "file-age", "path": "a"}, "needs max_age"),
    ("x", {"kind": "file-age", "path": "a", "max_age": "1d", "argv": ["a"]}, "unknown key(s) argv"),
    ("x", {"kind": "file-age", "path": "a", "max_age": 5}, "a duration"),
    ("x", {"kind": "file-age", "path": "a", "max_age": "soon"}, "a duration such as"),
    ("x", {"kind": "command", "argv": ["git"], "timeout": "5m"}, "at most 120s"),
    ("x", {"kind": "command", "argv": ["powershell", "-c", "x"]}, "a shell or an interpreter"),
    ("x", {"kind": "command", "argv": ["C:\\Python\\python.exe", "-c", "x"]}, "a shell or an interpreter"),
    ("x", {"kind": "command", "argv": ["bash", "-c", "x"]}, "a shell or an interpreter"),
    ("x", {"kind": "command", "argv": ["git"], "expect": "("}, "expect:"),
    ("x", {"kind": "command", "argv": ["git"], "ok_exit": [True]}, "whole numbers"),
    ("x", {"kind": "http", "url": "https://user:pw@example.invalid/"}, "no user or password"),  # gitleaks:allow
    ("x", {"kind": "http", "url": "ftp://example.invalid/"}, "an http or https URL"),
    ("x", {"kind": "file-age", "path": "a", "max_age": "1d", "level": "loud"}, "level 'loud'"),
    ("Bad Name", {"kind": "file-age", "path": "a", "max_age": "1d"}, "a name of lowercase"),
])
def test_a_bad_declaration_is_refused_with_its_reason(name, conf, says):
    with pytest.raises(depprobes.ProbeError, match=None) as exc:
        depprobes.parse(name, conf)
    assert says in str(exc.value)


def test_brain_config_check_reports_a_bad_probe_and_accepts_good_ones(tmp_path, monkeypatch):
    _config(tmp_path, monkeypatch, {"ok": {"kind": "file-age", "path": "a", "max_age": "1d"},
                                    "bad": {"kind": "command", "argv": ["cmd", "/c", "dir"]}})
    errors = config.check()
    assert len(errors) == 1 and "probes.bad" in errors[0] and "shell" in errors[0]
    _config(tmp_path, monkeypatch, {"ok": {"kind": "file-age", "path": "a", "max_age": "1d"}})
    assert config.check() == []
    _config(tmp_path, monkeypatch, {"ok": {"kind": "file-age", "path": "a", "max_age": "1d", "colour": "red"}})
    assert any("colour" in e for e in config.check())   # the schema refuses an unknown key too


def test_machines_choose_where_a_probe_runs(tmp_path, monkeypatch):
    cfg = _config(tmp_path, monkeypatch, {
        "everywhere": {"kind": "file-age", "path": "a", "max_age": "1d"},
        "only-a": {"kind": "file-age", "path": "a", "max_age": "1d", "machines": ["Host-A"]},
        "only-b": {"kind": "file-age", "path": "a", "max_age": "1d", "machines": ["host-b"]}})
    probes, errors = depprobes.declared(cfg)
    assert not errors
    assert [p["name"] for p in depprobes.mine(probes, "host-a")] == ["everywhere", "only-a"]
    monkeypatch.setenv("BRAIN_HOST", "HOST-B")
    assert [p["name"] for p in depprobes.mine(probes)] == ["everywhere", "only-b"]


# --- the kinds ---

def test_file_age_takes_the_newest_match_and_says_stale_or_missing(tmp_path):
    d = tmp_path / "backups"
    d.mkdir()
    (d / "old.zip").write_text("x", encoding="utf-8")
    _age(d / "old.zip", 50)
    p = depprobes.parse("backup", {"kind": "file-age", "path": f"{d.as_posix()}/*.zip", "max_age": "26h"})
    now = datetime.now(timezone.utc)
    state, why, age = depprobes.probe_file_age(p, now)
    assert state == "STALE" and "> 26 h" in why and age > 26 * 3600
    (d / "new.zip").write_text("x", encoding="utf-8")
    _age(d / "new.zip", 1)
    assert depprobes.probe_file_age(p, now)[0] == "OK"
    gone = depprobes.parse("gone", {"kind": "file-age", "path": f"{d.as_posix()}/*.tar", "max_age": "1d"})
    assert depprobes.probe_file_age(gone, now)[:2] == ("FAIL", "no file matches its path")


def test_json_age_reads_a_nested_field_epoch_seconds_and_the_brain_home(tmp_path, brain_home):
    now = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    (brain_home / "tool").mkdir(parents=True)
    f = brain_home / "tool" / "meta.json"
    f.write_text(json.dumps({"index": {"updated": "2026-11-10T06:00:00Z"}, "epoch": now.timestamp() - 3 * 86400}),
                 encoding="utf-8")
    nested = depprobes.parse("idx", {"kind": "json-age", "path": "$BRAIN_HOME/tool/meta.json",
                                     "field": "index.updated", "max_age": "12h"})
    assert depprobes.probe_json_age(nested, now)[0] == "OK"
    epoch = depprobes.parse("ep", {"kind": "json-age", "path": "${BRAIN_HOME}/tool/meta.json", "field": "epoch",
                                   "max_age": "2d"})
    assert depprobes.probe_json_age(epoch, now)[0] == "STALE"
    none = depprobes.parse("no", {"kind": "json-age", "path": "$BRAIN_HOME/tool/meta.json", "field": "index",
                                  "max_age": "2d"})
    assert depprobes.probe_json_age(none, now)[:2] == ("FAIL", "index is not a time")
    f.write_text("{not json", encoding="utf-8")
    assert depprobes.probe_json_age(nested, now)[:2] == ("FAIL", "not JSON")


def test_json_age_takes_the_last_matching_line_of_a_jsonl_file(tmp_path):
    now = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    f = tmp_path / "2026-11.jsonl"
    lines = [{"at": "2026-11-01T10:00:00Z", "outcome": "sent"}, {"at": "2026-11-10T11:00:00Z", "outcome": "failed"}]
    f.write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n", encoding="utf-8")
    p = depprobes.parse("sent", {"kind": "json-age", "path": str(tmp_path / "*.jsonl"), "field": "at",
                                 "where": {"outcome": "sent"}, "max_age": "7d"})
    state, why, _ = depprobes.probe_json_age(p, now)
    assert state == "STALE" and why == "at 9.1 d old > 1 w"   # the sent line, not the later failed one
    any_line = depprobes.parse("any", {"kind": "json-age", "path": str(f), "field": "at", "max_age": "7d"})
    assert depprobes.probe_json_age(any_line, now)[0] == "OK"
    never = depprobes.parse("never", {"kind": "json-age", "path": str(f), "field": "at", "max_age": "7d",
                                      "where": {"outcome": "held"}})
    assert depprobes.probe_json_age(never, now)[:2] == ("FAIL", "no line with at matching where")
    # a new month's file with no sent line yet: last month's sent line still counts
    new = tmp_path / "2026-12.jsonl"
    new.write_text(json.dumps({"at": "2026-11-10T11:30:00Z", "outcome": "failed"}) + "\n", encoding="utf-8")
    os.utime(new, (time.time() + 60, time.time() + 60))
    assert depprobes.probe_json_age(p, now)[:2] == ("STALE", "at 9.1 d old > 1 w")


def test_command_checks_the_exit_and_the_output_without_ever_showing_it():
    now = datetime.now(timezone.utc)
    ok = depprobes.parse("git", {"kind": "command", "argv": ["git", "--version"], "expect": r"git version \d"})
    assert depprobes.probe_command(ok, now) == ("OK", "exit 0", None)
    nomatch = depprobes.parse("git", {"kind": "command", "argv": ["git", "--version"], "expect": "^logged in$"})
    state, why, _ = depprobes.probe_command(nomatch, now)
    assert state == "FAIL" and "does not match" in why and "git version" not in why
    bad = depprobes.parse("git", {"kind": "command", "argv": ["git", "no-such-subcommand-here"]})
    state, why, _ = depprobes.probe_command(bad, now)
    assert state == "FAIL" and why.startswith("exit ") and "no-such" not in why
    accepted = depprobes.parse("git", {"kind": "command", "argv": ["git", "no-such-subcommand-here"],
                                       "ok_exit": [0, 1]})
    assert depprobes.probe_command(accepted, now)[0] == "OK"
    missing = depprobes.parse("gone", {"kind": "command", "argv": ["no-such-program-anywhere"]})
    assert depprobes.probe_command(missing, now)[:2] == ("FAIL", "no-such-program-anywhere not found")


def test_command_that_runs_past_its_timeout_is_timeout(monkeypatch):
    def slow(argv, **kw):
        assert kw["timeout"] == 3 and kw["stdin"] is subprocess.DEVNULL and kw["encoding"] == "utf-8"
        raise subprocess.TimeoutExpired(argv, kw["timeout"])
    monkeypatch.setattr(depprobes.subprocess, "run", slow)
    p = depprobes.parse("git", {"kind": "command", "argv": ["git", "--version"], "timeout": "3s"})
    assert depprobes.probe_command(p, datetime.now(timezone.utc))[0] == "TIMEOUT"


@pytest.fixture
def server():
    """A local HTTP server: /ok answers 200, anything else 503."""
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200 if self.path.startswith("/ok") else 503)
            self.end_headers()

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_http_checks_the_status_and_never_names_the_url(server):
    now = datetime.now(timezone.utc)
    ok = depprobes.parse("ui", {"kind": "http", "url": f"{server}/ok?key=secret-in-query", "timeout": "5s"})
    assert depprobes.probe_http(ok, now) == ("OK", "HTTP 200", None)
    down = depprobes.parse("ui", {"kind": "http", "url": f"{server}/down", "timeout": "5s"})
    assert depprobes.probe_http(down, now)[:2] == ("FAIL", "HTTP 503")
    accepted = depprobes.parse("ui", {"kind": "http", "url": f"{server}/down", "ok_status": [503], "timeout": "5s"})
    assert depprobes.probe_http(accepted, now)[0] == "OK"
    closed = depprobes.parse("ui", {"kind": "http", "url": "http://127.0.0.1:9/", "timeout": "2s"})
    state, why, _ = depprobes.probe_http(closed, now)
    assert state in ("FAIL", "TIMEOUT") and "127.0.0.1" not in why


def test_a_probe_that_hangs_is_timeout_and_one_that_raises_is_fail(monkeypatch):
    monkeypatch.setattr(depprobes, "GRACE", 0.05)
    release = threading.Event()

    def hang(p, now):
        release.wait(5)
        return "OK", "", None

    def boom(p, now):
        raise RuntimeError("secret detail")
    monkeypatch.setitem(depprobes.RUNNERS, "file-age", hang)
    monkeypatch.setitem(depprobes.RUNNERS, "http", boom)
    hung = depprobes.parse("hung", {"kind": "file-age", "path": "a", "max_age": "1d", "timeout": "0.1s"})
    raised = depprobes.parse("raised", {"kind": "http", "url": "http://127.0.0.1:9/"})
    try:
        rows = depprobes.measure([hung, raised])
    finally:
        release.set()
    assert [(r["name"], r["state"]) for r in rows] == [("hung", "TIMEOUT"), ("raised", "FAIL")]
    assert rows[1]["why"] == "the probe failed (RuntimeError)"


# --- the run and its record ---

def test_a_run_records_each_state_its_last_ok_and_since(tmp_path, monkeypatch, brain_home):
    f = tmp_path / "data.bin"
    f.write_text("x", encoding="utf-8")
    _config(tmp_path, monkeypatch, {"data": {"kind": "file-age", "path": str(f), "max_age": "1h", "about": "the "
                                             "collector"}})
    t0 = datetime.now(timezone.utc)
    first = depprobes.run(now=t0)
    assert first["saved"] and first["probes"][0]["state"] == "OK" and first["probes"][0]["last_ok"]
    _age(f, 3)
    t1 = t0 + timedelta(minutes=15)
    second = depprobes.run(now=t1)["probes"][0]
    assert second["state"] == "STALE" and second["last_ok"] == alerts._iso(t0) and second["since"] == alerts._iso(t1)
    third = depprobes.run(now=t1 + timedelta(minutes=15))["probes"][0]
    assert third["since"] == alerts._iso(t1)   # still stale since the second run
    monkeypatch.setattr(depprobes, "_LATEST", {})
    back = depprobes.last()
    assert back["probes"][0]["state"] == "STALE" and back["probes"][0]["last_ok"] == alerts._iso(t0)
    state = json.loads((brain_home / "probes" / "state.json").read_text(encoding="utf-8"))
    assert state["_run"]["at"] == alerts._iso(t1 + timedelta(minutes=15)) and "path" not in state["data"]


def test_nothing_is_written_when_no_probe_runs_here(tmp_path, monkeypatch, brain_home):
    _config(tmp_path, monkeypatch, {"elsewhere": {"kind": "file-age", "path": "a", "max_age": "1d",
                                                  "machines": ["another-host"]}})
    d = depprobes.run()
    assert d["probes"] == [] and not d["saved"] and not (brain_home / "probes").exists()
    assert depprobes.last()["probes"] == []


# --- the alerts, the pass, status, the cockpit, the command ---

def test_the_brain_project_raises_a_probe_alert_and_the_pass_sends_it_once_then_resolved(tmp_path, monkeypatch):
    fake = Fake()
    monkeypatch.setattr(notify, "_post_json", fake.post)
    p = _brain(tmp_path, monkeypatch, NOTIFY)
    f = tmp_path / "summary.json"
    f.write_text("{}", encoding="utf-8")
    _age(f, 30)
    _config(tmp_path, monkeypatch, {"summaries": {"kind": "file-age", "path": str(f), "max_age": "1d",
                                                  "level": "error", "about": "the session archive's summaries"}})
    depprobes.run()
    found = alerts.of_project(p)
    assert [(a.key, a.level, a.source) for a in found] == [("probe:summaries", "error", "probe")]
    assert "dependency summaries STALE" in found[0].message and "the session archive's summaries" in found[0].message
    lines = alerts.notify_pass(alerts.run([p], quick=True), {p.name: p}, env=ENV)
    assert "brain: error probe:summaries: delivered" in lines and len(fake.posts) == 1
    alerts.notify_pass(alerts.run([p], quick=True), {p.name: p}, env=ENV)
    assert len(fake.posts) == 1   # once
    _age(f, 1)
    depprobes.run()
    lines = alerts.notify_pass(alerts.run([p], quick=True), {p.name: p}, env=ENV)
    assert "brain: resolved probe:summaries: delivered" in lines and len(fake.posts) == 2


def test_only_the_brain_project_carries_the_probe_alerts(tmp_path, monkeypatch):
    _config(tmp_path, monkeypatch, {"gone": {"kind": "file-age", "path": str(tmp_path / "none"), "max_age": "1d"}})
    depprobes.run()
    assert not alerts.of_project(_brain(tmp_path, monkeypatch, name="demo"))
    rows = [{"name": "gone", "state": "FAIL", "why": "x", "level": "warn"}, {"name": "ok", "state": "OK"}]
    p = _brain(tmp_path, monkeypatch)
    assert [a.key for a in alerts.of_project(p, probe_rows=rows)] == ["probe:gone"]   # the rows given win
    assert [a.key for a in alerts.of_project(p)] == ["probe:gone"]                    # else the last run


def test_the_alerts_pass_runs_the_probes_when_the_brain_is_in_scope(tmp_path, monkeypatch):
    p = _brain(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(depprobes, "run", lambda *a, **k: calls.append(1) or {"probes": []})
    monkeypatch.setattr(status, "_probes", lambda root, quick: (None, None))
    monkeypatch.setattr(status, "audit_of", lambda p, detail=0: {"skipped": "test"})
    alerts.run([p], quick=True)
    assert calls == []   # --quick: the last run is read, nothing run
    alerts.run([p], quick=False)
    assert calls == [1]


def test_brain_status_shows_a_probes_row_once_one_is_declared(tmp_path, monkeypatch):
    p = _brain(tmp_path, monkeypatch)
    data = status.run([p], quick=True)
    assert data["probes"]["probes"] == [] and not any(x.lstrip().startswith("probes ") for x in status.render(data))
    _config(tmp_path, monkeypatch, {"gone": {"kind": "file-age", "path": str(tmp_path / "none"), "max_age": "1d"}})
    depprobes.run()
    data = status.run([p], quick=True)
    row = [x for x in status.render(data) if x.lstrip().startswith("probes ")]
    assert row and "0 of 1 OK; gone FAIL (no file matches its path; never OK here)" in row[0]
    assert data["projects"][0]["alerts"]["counts"] == {"warn": 1}


def test_the_cockpit_health_panel_shows_the_probes():
    panel = {"projects": [], "probes": {"at": "2026-11-10T12:00:00Z", "errors": [], "probes": [
        {"name": "login", "kind": "command", "state": "FAIL", "why": "exit 1", "last_ok": "2026-11-09T08:00:00Z"},
        {"name": "backup", "kind": "file-age", "state": "OK", "why": "newest file 2.0 h old"}]}}
    text = "\n".join(cockpit.health_lines(panel, width=200))
    assert "dependency probes: 1 of 2 OK; login FAIL (exit 1; last OK 2026-11-09 08:00Z)" in text


def test_brain_probes_runs_lists_and_exits_by_state(tmp_path, monkeypatch, capsys):
    f = tmp_path / "fresh.txt"
    f.write_text("x", encoding="utf-8")
    _config(tmp_path, monkeypatch, {"fresh": {"kind": "file-age", "path": str(f), "max_age": "1h"},
                                    "away": {"kind": "file-age", "path": "a", "max_age": "1h",
                                             "machines": ["another-host"]}})
    assert cli.main(["probes"]) == 0
    out = capsys.readouterr().out
    assert "OK       fresh" in out and "away" not in out
    assert cli.main(["probes", "--list", "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert {p["name"]: p["here"] for p in listed["probes"]} == {"fresh": True, "away": False}
    assert str(f) not in json.dumps(listed)   # no target is listed
    _age(f, 2)
    assert cli.main(["probes"]) == 1
    assert "STALE" in capsys.readouterr().out
    assert cli.main(["probes", "--last", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["probes"][0]["state"] == "STALE"
    assert cli.main(["probes", "--kinds", "--json"]) == 0
    assert set(json.loads(capsys.readouterr().out)) == set(depprobes.KINDS)
    _config(tmp_path, monkeypatch, {"bad": {"kind": "command", "argv": ["sh", "-c", "true"]}})
    assert cli.main(["probes"]) == 2
    assert "bad declaration" in capsys.readouterr().out
