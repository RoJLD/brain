"""wi-brain-otel-telemetry: the collector's processors (compose/sovereign/otelcol.yaml), the reader of its files
(brain.otel) and brain telemetry summary / status.

The fixtures (fixtures/otel) are real lines of the collector's files, written before its processors dropped the
account's attributes, scrubbed: every identifier, address, user, plugin and server name replaced with an invented one,
the times moved to 2026-01-05 (the rotated backups) and 2026-01-06 (the current files); the metric and event names,
the attribute keys and the value kinds are Claude Code's (its 2.1 export). They still carry user.email and the
account's ids, invented: the reader must drop them."""

import json
import os
import shutil
import socket
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml
from brain import bundles, cli, config, otel

FIXTURES = Path(__file__).parent / "fixtures" / "otel"
COLLECTOR = bundles.ROOT / "sovereign" / "otelcol.yaml"
# what the collector must drop and the reader never yields (ST-7, ST-8)
DROPPED = {"user.email", "user.account_uuid", "user.account_id", "process.owner", "prompt", "prompt_text", "response",
           "tool_parameters", "error"}
DAY1, DAY2 = datetime(2026, 1, 5, tzinfo=timezone.utc).timestamp(), datetime(2026, 1, 6, tzinfo=timezone.utc).timestamp()


def _raw_records(folder: Path):
    """The fixtures' raw OTLP records, read without brain.otel: (kind, name, attrs dict, value)."""
    for f in sorted(folder.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            doc = json.loads(line)
            for rm in doc.get("resourceMetrics", []):
                for sm in rm["scopeMetrics"]:
                    for m in sm["metrics"]:
                        for dp in m.get("sum", {}).get("dataPoints", []):
                            yield "metric", m["name"], {a["key"]: a["value"] for a in dp["attributes"]}, dp["asDouble"]
            for rl in doc.get("resourceLogs", []):
                for sl in rl["scopeLogs"]:
                    for lr in sl["logRecords"]:
                        yield "event", lr["body"]["stringValue"], {a["key"]: a["value"] for a in lr["attributes"]}, None


def _copy(tmp_path) -> Path:
    d = tmp_path / "otel-collector"
    shutil.copytree(FIXTURES, d)
    return d


def _event_line(name: str, attrs: dict, at: float = DAY2 + 3600) -> str:
    """One collector line of one event, in the export's shape (an int as a string, as Claude Code sends them)."""
    def value(v):
        return ({"boolValue": v} if isinstance(v, bool) else {"intValue": str(v)} if isinstance(v, int)
                else {"doubleValue": v} if isinstance(v, float) else {"stringValue": v})
    rec = {"timeUnixNano": str(int(at * 1e9)), "observedTimeUnixNano": str(int(at * 1e9)),
           "body": {"stringValue": f"claude_code.{name}"},
           "attributes": [{"key": k, "value": value(v)} for k, v in {"event.name": name, **attrs}.items()]}
    return json.dumps({"resourceLogs": [{"resource": {"attributes": [
        {"key": "process.owner", "value": {"stringValue": "ada"}}]},
        "scopeLogs": [{"scope": {"name": "com.anthropic.claude_code"}, "logRecords": [rec]}]}]})


# --- the collector's configuration ------------------------------------------------------------------------------

def _deleted(actions) -> set[str]:
    return {a["key"] for a in actions if a.get("action") == "delete"}


def _check_collector(cfg: dict) -> None:
    procs = cfg["processors"]
    assert _deleted(procs["attributes/private"]["actions"]) == DROPPED
    assert _deleted(procs["resource/private"]["attributes"]) == DROPPED
    pipelines = cfg["service"]["pipelines"]
    assert set(pipelines) >= {"metrics", "logs"}
    for name, p in pipelines.items():   # every pipeline, one added later too: none exports before the drop
        ps = p["processors"]
        assert "attributes/private" in ps and "resource/private" in ps, name
        assert ps.index("attributes/private") < ps.index("batch") and ps.index("resource/private") < ps.index("batch")
    logs = pipelines["logs"]["processors"]   # the tool names are kept before the parameters go
    assert logs.index("transform/tool-names") < logs.index("attributes/private")
    statements = "\n".join(procs["transform/tool-names"]["log_statements"][0]["statements"])
    for kept in ("mcp_server.name", "mcp_tool.name", "skill.name"):
        assert f'attributes["{kept}"]' in statements


def test_the_collector_drops_the_account_and_the_texts_in_every_pipeline():
    """ST-8: user.email, the account's uuid and id (and the system's user name) leave no pipeline, on a data point's
    or an event's attributes or on the resource; ST-7: no error text, no tool parameters; no prompt or response."""
    _check_collector(yaml.safe_load(COLLECTOR.read_text(encoding="utf-8")))
    assert DROPPED == set(otel.PRIVATE)   # the reader drops what the collector drops, for the files written before


def test_the_rendering_with_the_token_keeps_the_processors(tmp_path):
    """brain bundle apply with ipc.require_token re-dumps the configuration (brain.bundles.collector_auth): the
    processors and their resolved lists stay."""
    cfg = yaml.safe_load(bundles.collector_auth(COLLECTOR.read_bytes()).decode("utf-8"))
    _check_collector(cfg)
    assert cfg["receivers"]["otlp"]["protocols"]["http"]["auth"] == {"authenticator": "bearertokenauth"}


# --- the reader ---------------------------------------------------------------------------------------------------

def test_records_read_the_current_and_rotated_files_without_a_private_attribute():
    stats = otel.Stats()
    recs = list(otel.records(FIXTURES, stats=stats))
    raw = list(_raw_records(FIXTURES))
    assert (stats.files, stats.bad, stats.records, len(recs)) == (4, 0, len(raw), len(raw))
    assert "user.email" in raw[0][2]   # the fixture holds what the reader must drop
    assert set().union(*(r.attrs for r in recs)).isdisjoint(DROPPED)
    text = json.dumps([r.attrs for r in recs])
    assert "example.invalid" not in text
    assert "user_01ExampleAccount" not in text


def test_records_keep_the_exports_names_sessions_days_and_value_kinds():
    recs = list(otel.records(FIXTURES))
    assert {r.session for r in recs} == {"11111111-1111-4111-8111-111111111111",
                                         "22222222-2222-4222-8222-222222222222"}
    assert {r.day for r in recs} == {"2026-01-05", "2026-01-06"}
    assert {"claude_code.token.usage", "claude_code.cost.usage", "claude_code.session.count",
            "claude_code.api_request", "claude_code.tool_decision", "claude_code.tool_result",
            "claude_code.hook_execution_complete", "claude_code.user_prompt"} <= {r.name for r in recs}
    by_event = {r.event: r for r in recs}
    api, hook = by_event["api_request"], by_event["hook_execution_complete"]
    assert (type(api.attrs["input_tokens"]), type(api.attrs["cost_usd"])) == (int, float)
    assert isinstance(hook.attrs["total_duration_ms"], str)   # Claude Code sends it as a string
    assert hook.num("total_duration_ms") >= 0
    mcp = {(r.text("mcp_server.name"), r.text("mcp_tool.name")) for r in recs if r.text("tool_name") == "mcp_tool"}
    assert mcp == {("docs", "search")}   # from the tool's parameters, which are dropped


def test_records_since_skip_older_records_and_older_backups(tmp_path):
    """A backup last written before ``since`` (git gives the fixtures a fresh time: os.utime sets theirs): a logs one
    is not opened, a metrics one only skimmed for its cumulative series."""
    d = _copy(tmp_path)
    for f in d.glob("*-2026-01-05T18-00-00.000.jsonl"):
        os.utime(f, (DAY1 + 18 * 3600, DAY1 + 18 * 3600))
    stats = otel.Stats()
    recs = list(otel.records(d, since=DAY2, stats=stats))
    assert recs
    assert {r.day for r in recs} == {"2026-01-06"}
    assert (stats.files, stats.seeded, stats.records) == (2, 1, len(recs))   # the current files; the metrics backup
    stats = otel.Stats()
    assert len(list(otel.records(d, stats=stats))) > len(recs)
    assert (stats.files, stats.seeded) == (4, 0)


def _cumulative_line(v: float, at: float) -> str:
    dp = {"attributes": [{"key": "session.id", "value": {"stringValue": "s1"}},
                         {"key": "type", "value": {"stringValue": "input"}}],
          "startTimeUnixNano": "1", "timeUnixNano": str(int(at * 1e9)), "asDouble": v}
    return json.dumps({"resourceMetrics": [{"scopeMetrics": [{"metrics": [
        {"name": "claude_code.token.usage", "sum": {"aggregationTemporality": 2, "isMonotonic": True,
                                                    "dataPoints": [dp]}}]}]}]})


def test_a_cumulative_series_is_seeded_from_a_backup_older_than_since(tmp_path):
    """--days: a cumulative series' value before ``since`` comes from a backup that is not otherwise read, so the
    first record after it is its increment, not the whole count."""
    backup, current = tmp_path / "metrics-2026-01-05T00-00-00.000.jsonl", tmp_path / "metrics.jsonl"
    backup.write_text(_cumulative_line(10, DAY1 + 3600) + "\n", encoding="utf-8")
    os.utime(backup, (DAY1 + 3600, DAY1 + 3600))
    current.write_text(_cumulative_line(25, DAY2 + 3600) + "\n", encoding="utf-8")
    stats = otel.Stats()
    assert [r.value for r in otel.records(tmp_path, since=DAY2, stats=stats)] == [15]
    assert (stats.files, stats.seeded) == (1, 1)


def test_a_missing_folder_an_empty_one_garbage_and_a_truncated_last_line(tmp_path):
    assert list(otel.records(tmp_path / "none")) == []
    (tmp_path / "empty").mkdir()
    assert list(otel.records(tmp_path / "empty")) == []
    d = _copy(tmp_path)
    whole = len(list(otel.records(d)))
    logs = d / "logs.jsonl"
    text = logs.read_text(encoding="utf-8")
    logs.write_text("not json\n[1, 2]\n\n" + text + text.splitlines()[0][:500], encoding="utf-8")  # cut mid-line
    stats = otel.Stats()
    assert len(list(otel.records(d, stats=stats))) == whole
    assert stats.bad == 3   # the garbage line, a JSON that is no object, the truncated last line
    (d / "metrics.jsonl").write_bytes(b"\xff\xfe\x00garbage\n")
    assert otel.parse('{"resourceMetrics": "x", "resourceLogs": [{"scopeLogs": [{"logRecords": [7]}]}]}') == []


def test_a_cumulative_sum_is_read_as_increments_and_a_reset_starts_over():
    def line(v: float) -> str:
        return _cumulative_line(v, DAY2)
    last: dict = {}
    assert [otel.parse(line(v), last)[0].value for v in (10, 25, 5)] == [10, 15, 5]
    delta = json.loads(line(10).replace('"aggregationTemporality": 2', '"aggregationTemporality": 1'))
    assert otel.parse(json.dumps(delta), {})[0].value == 10


def test_tool_parameters_keep_the_names_only_and_an_error_text_never_comes_out(tmp_path):
    d = tmp_path / "c"
    d.mkdir()
    secret = "stderr of a command: the-secret-text"
    lines = [_event_line("tool_result", {"session.id": "s9", "tool_name": "Skill", "success": "false",
                                         "error_type": "ShellError", "error": secret, "duration_ms": "12",
                                         "tool_parameters": json.dumps({"skill_name": "close-item",
                                                                        "bash_command": "rm -rf the-secret-text"})}),
             _event_line("tool_decision", {"session.id": "s9", "tool_name": "Bash", "decision": "reject",
                                           "source": "user_reject", "tool_parameters": "{not json"})]
    (d / "logs.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    recs = list(otel.records(d))
    assert recs[0].attrs["skill.name"] == "close-item" and "process.owner" not in recs[0].attrs
    doc = otel.summary(recs, d).as_dict()
    assert "the-secret-text" not in json.dumps([r.attrs for r in recs]) + json.dumps(doc)
    assert doc["tools"][0] == {"tool": "Skill close-item", "runs": 1, "failures": 1, "error_types": {"ShellError": 1},
                               "p50_ms": 12.0, "p90_ms": 12.0, "max_ms": 12.0}
    assert doc["tool_decisions"] == [{"decision": "reject", "source": "user_reject", "count": 1}]


# --- the summary ------------------------------------------------------------------------------------------------

def test_the_summary_replays_the_fixtures_totals():
    """Tokens and cost per day equal the raw data points' sums (read here without brain.otel); requests, decisions,
    tool failures and hooks as the fixtures hold them."""
    stats = otel.Stats()
    doc = otel.summary(otel.records(FIXTURES, stats=stats), FIXTURES, stats=stats).as_dict()
    sums = _raw_sums()
    tot = doc["totals"]
    assert tot["tokens"] == {t: sums.get(t, 0) for t in otel.TOKEN_TYPES}
    assert tot["cost_usd"] == pytest.approx(sums["cost"], abs=1e-3)
    assert [r["day"] for r in doc["by_day"]] == ["2026-01-05", "2026-01-06"]
    assert sum(r["tokens_total"] for r in doc["by_day"]) == tot["tokens_total"]
    assert (tot["api_requests"], tot["sessions"], tot["api_errors"]) == (5, 2, 0)
    assert [r["model"] for r in doc["by_model"]] == ["claude-opus-5-5"]
    assert {(d["decision"], d["source"]): d["count"] for d in doc["tool_decisions"]} == {("accept", "config"): 5,
                                                                                         ("reject", "hook"): 1}
    assert doc["tool_rejects"] == {"mcp_tool docs/search": 1}
    bash = next(t for t in doc["tools"] if t["tool"] == "Bash")
    assert (bash["runs"], bash["failures"], bash["error_types"]) == (6, 3, {"ShellError": 3})
    start = next(h for h in doc["hooks"] if h["hook"] == "SessionStart:startup")
    assert start["runs"] == 2
    assert start["p50_ms"] <= start["p90_ms"] <= start["max_ms"]
    assert (doc["read"]["first"][:10], doc["read"]["last"][:10]) == ("2026-01-05", "2026-01-06")


def _raw_sums() -> dict:
    """The token data points' sums by type and the cost's, from the raw fixtures."""
    sums: dict = {}
    for _kind, name, attrs, value in _raw_records(FIXTURES):
        key = {"claude_code.token.usage": attrs.get("type", {}).get("stringValue"),
               "claude_code.cost.usage": "cost"}.get(name)
        if key:
            sums[key] = sums.get(key, 0) + value
    return sums


def test_the_summary_of_one_session_and_the_api_errors_and_retries(tmp_path):
    d = _copy(tmp_path)
    extra = [_event_line("api_error", {"session.id": "22222222-2222-4222-8222-222222222222", "model": "m-test",
                                       "status_code": "529", "attempt": 2, "duration_ms": 900}),
             _event_line("api_request", {"session.id": "22222222-2222-4222-8222-222222222222", "model": "m-test",
                                         "attempt": 3, "cost_usd": 0.5, "input_tokens": 3})]
    with (d / "logs.jsonl").open("a", encoding="utf-8") as fh:
        fh.write("\n".join(extra) + "\n")
    doc = otel.summary(otel.records(d), d, session="2222").as_dict()
    assert [r["session"] for r in doc["by_session"]] == ["22222222-2222-4222-8222-222222222222"]
    tot = doc["totals"]
    assert (tot["api_requests"], tot["api_errors"], tot["retries"], tot["sessions"]) == (3, 1, 2, 1)
    assert doc["api_error_status"] == {"529": 1}
    m = next(r for r in doc["by_model"] if r["model"] == "m-test")
    assert (m["api_requests"], m["api_errors"], m["retries"]) == (1, 1, 2)


def test_every_attribute_key_of_the_fixtures_is_reviewed():
    """PRIVATE is a denylist: a key Claude Code adds would pass it. Every key of the real payloads is either in
    KNOWN_KEYS (reviewed: kept) or in PRIVATE (dropped); a fixture refreshed from a newer version fails here on a
    new key until it is reviewed."""
    keys = {k for _, _, attrs, _ in _raw_records(FIXTURES) for k in attrs}
    for f in FIXTURES.glob("*.jsonl"):
        for line in f.read_text(encoding="utf-8").splitlines():
            doc = json.loads(line)
            for res in doc.get("resourceLogs", []) + doc.get("resourceMetrics", []):
                keys |= {a["key"] for a in res["resource"]["attributes"]}
    assert sorted(keys - otel.KNOWN_KEYS - otel.PRIVATE) == []
    assert otel.KNOWN_KEYS.isdisjoint(otel.PRIVATE)


def test_the_summary_names_an_attribute_key_not_reviewed(tmp_path):
    (tmp_path / "logs.jsonl").write_text(_event_line("tool_result", {"session.id": "s1", "tool_name": "Bash",
                                                                     "brand_new_key": "x"}) + "\n", encoding="utf-8")
    doc = otel.summary(otel.records(tmp_path), tmp_path).as_dict()
    assert doc["unreviewed_keys"] == ["brand_new_key"]
    assert "brand_new_key" in otel.render(doc)[1]
    assert otel.summary(otel.records(FIXTURES), FIXTURES).as_dict()["unreviewed_keys"] == []


def test_a_session_prefix_that_matches_nothing_is_said(capsys):
    assert cli.main(["telemetry", "summary", "--dir", str(FIXTURES), "--days", "0", "--session", "ffff"]) == 0
    out = capsys.readouterr().out
    assert "0 record(s) summarized of 68 read" in out
    assert "no record for a session whose id starts with 'ffff'" in out
    assert "per day" not in out


def test_render_says_no_record_and_the_lines_not_read(tmp_path):
    (tmp_path / "logs.jsonl").write_text("garbage\n", encoding="utf-8")
    stats = otel.Stats()
    lines = otel.render(otel.summary(otel.records(tmp_path, stats=stats), tmp_path, stats=stats).as_dict())
    assert "1 line(s) not read" in lines[1] and "no record" in lines[2]


# --- the command --------------------------------------------------------------------------------------------------

def test_brain_telemetry_summary_json_text_and_a_missing_folder(tmp_path, capsys):
    assert cli.main(["telemetry", "summary", "--dir", str(FIXTURES), "--days", "0", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["totals"]["sessions"] == 2 and "example.invalid" not in json.dumps(doc)
    assert cli.main(["telemetry", "summary", "--dir", str(FIXTURES), "--days", "0", "--session", "1111",
                     "--top", "1"]) == 0
    out = capsys.readouterr().out
    assert "11111111-1111-4111-8111-111111111111" in out and "22222222" not in out and "per day (UTC)" in out
    assert cli.main(["telemetry", "summary", "--dir", str(FIXTURES)]) == 0   # the last 7 days: none of 2026-01
    assert "no record since" in capsys.readouterr().out
    assert cli.main(["telemetry", "summary", "--dir", str(tmp_path / "none")]) == 1
    assert "no collector folder" in capsys.readouterr().err
    with pytest.raises(SystemExit):   # machine-wide: no --project after it
        cli.main(["telemetry", "summary", "--project", "lab"])


def test_the_default_folder_is_the_collectors_under_brain_home(capsys):
    home = Path(otel.paths.brain_home())
    assert otel.folder() == home / "stacks" / "sovereign" / "data" / "otel-collector"
    shutil.copytree(FIXTURES, otel.folder())
    assert cli.main(["telemetry", "summary", "--days", "0", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["totals"]["api_requests"] == 5


# --- the status -----------------------------------------------------------------------------------------------------

class _Health(BaseHTTPRequestHandler):
    body = b'{"status":"Server available","upSince":"2026-01-06T08:00:00Z","uptime":"1h"}'
    code = 200

    def do_GET(self):
        self.send_response(self.code)
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args):
        pass


@pytest.fixture
def health():
    """A health endpoint on loopback: the collector's answer by default, a test sets another body or code."""
    handler = type("H", (_Health,), {})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield handler, f"http://127.0.0.1:{srv.server_address[1]}/"
    srv.shutdown()
    srv.server_close()


def _settings(on: bool, signals=("metrics", "logs")) -> Path:
    f = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "settings.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    env = {"CLAUDE_CODE_ENABLE_TELEMETRY": "1" if on else "0", "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:4318",
           **{f"OTEL_{s.upper()}_EXPORTER": "otlp" for s in signals}}
    f.write_text(json.dumps({"env": env, "otelHeadersHelper": "brain ipc otel-headers"}), encoding="utf-8")
    return f


def _states(res) -> list[str]:
    return [line["state"] for line in res["lines"]]


def test_status_ok_when_the_export_is_on_the_collector_answers_and_the_records_are_fresh(health):
    handler, url = health
    _settings(True)
    res = otel.status(config.load(), FIXTURES, url=url, now=DAY2 + 3 * 3600)
    assert res["exit"] == 0 and _states(res) == ["OK", "OK", "OK", "OK"], res["lines"]
    assert res["collector"] == {"url": url, "state": "up", "seen": "Server available"}
    assert res["signals"]["logs"]["last"].startswith("2026-01-06") and res["signals"]["metrics"]["files"] == 2


def _transcript(at: float, sub: bool = False) -> Path:
    """A transcript Claude Code wrote at ``at`` (its modification time), under $CLAUDE_CONFIG_DIR/projects."""
    folder = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects" / "C--work-lab"
    f = folder / "sess" / "subagents" / "agent-1.jsonl" if sub else folder / f"sess-{int(at)}.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("{}\n", encoding="utf-8")
    os.utime(f, (at, at))
    return f


def test_status_fails_a_collector_that_receives_nothing_while_claude_code_is_active(health):
    """The last records are of 2026-01-06 09:09; 40 h later, a transcript written 30 h after them: Claude Code
    worked and nothing came in."""
    _, url = health
    _settings(True)
    _transcript(DAY2 + 39 * 3600, sub=True)   # a subagent's transcript counts (three levels deep)
    res = otel.status(config.load(), FIXTURES, url=url, now=DAY2 + 40 * 3600)
    assert res["exit"] == 1
    assert _states(res).count("FAIL") == 2   # metrics and logs
    assert "Claude Code was active" in res["lines"][2]["line"]
    assert res["activity"]["last"].startswith("2026-01-07T15")
    _settings(True, signals=("metrics",))   # logs not exported: their age fails nothing
    res = otel.status(config.load(), FIXTURES, url=url, now=DAY2 + 40 * 3600)
    assert _states(res) == ["OK", "OK", "FAIL", "OK"]


def test_status_warns_on_a_quiet_spell_with_no_transcript_after_the_last_record(health):
    """Claude Code exports only while a session runs: 40 h without a record and without a transcript after it (or
    one written within the window after it) is no activity, a warning, exit 0."""
    _, url = health
    _settings(True)
    res = otel.status(config.load(), FIXTURES, url=url, now=DAY2 + 40 * 3600)
    assert (res["exit"], _states(res)) == (0, ["OK", "OK", "warning", "warning"])
    assert "no activity" in res["lines"][2]["line"]
    _transcript(DAY2 + 12 * 3600)   # 3 h after the last record: inside the 24 h window
    res = otel.status(config.load(), FIXTURES, url=url, now=DAY2 + 40 * 3600)
    assert (res["exit"], _states(res)) == (0, ["OK", "OK", "warning", "warning"])
    _settings(False)
    res = otel.status(config.load(), FIXTURES, url=url, now=DAY2 + 40 * 3600)
    assert (res["exit"], _states(res)) == (0, ["OFF", "OK", "warning", "warning"])
    assert "no source" in res["lines"][2]["line"]


def test_status_without_any_record_fails_only_when_claude_code_was_active_lately(health, tmp_path):
    _, url = health
    _settings(True)
    (tmp_path / "empty").mkdir()
    _transcript(DAY1)
    res = otel.status(config.load(), tmp_path / "empty", url=url, now=DAY2 + 40 * 3600)
    assert (res["exit"], _states(res)[2:]) == (0, ["warning", "warning"])
    _transcript(DAY2 + 39 * 3600)
    res = otel.status(config.load(), tmp_path / "empty", url=url, now=DAY2 + 40 * 3600)
    assert (res["exit"], _states(res)[2:]) == (1, ["FAIL", "FAIL"])


def test_the_walk_of_the_transcripts_is_bounded(tmp_path):
    for i in range(30):
        f = tmp_path / f"p{i}" / f"s{i}.jsonl"
        f.parent.mkdir()
        f.write_text("{}", encoding="utf-8")
        os.utime(f, (DAY1 + i, DAY1 + i))
    assert otel.last_activity(tmp_path) == (DAY1 + 29, True)
    newest, whole = otel.last_activity(tmp_path, limit=10)
    assert not whole
    assert newest <= DAY1 + 29
    assert otel.last_activity(tmp_path / "none") == (0.0, True)


def test_status_fails_when_the_export_is_on_and_the_collector_is_down_or_answers_garbage(health, tmp_path):
    handler, url = health
    _settings(True)
    handler.body = b"<html>not the collector</html>"
    res = otel.status(config.load(), FIXTURES, url=url, now=DAY2)
    assert (res["collector"]["state"], res["exit"]) == ("garbage", 1)
    handler.body, handler.code = b'{"status":"Server not available"}', 503
    assert otel.status(config.load(), FIXTURES, url=url, now=DAY2)["collector"]["state"] == "unavailable"
    with socket.socket() as s:   # a port nothing listens on any more
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
    t0 = time.monotonic()
    res = otel.status(config.load(), tmp_path / "none", url=f"http://127.0.0.1:{free}/", timeout=0.5, now=DAY2)
    assert time.monotonic() - t0 < 1.5   # the probe's whole deadline, Windows' retried connect included
    assert res["collector"]["state"] in ("down", "slow")   # refused at once, or retried past 0.5 s (Windows)
    assert "stopped" in res["collector"]["seen"]
    assert (res["exit"], _states(res)) == (1, ["OK", "FAIL", "OFF"])


def test_the_health_probe_ends_on_a_collector_that_never_answers():
    with socket.socket() as s:   # accepts the connection (the backlog) and never answers
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        t0 = time.monotonic()
        state, seen = otel.probe(f"http://127.0.0.1:{s.getsockname()[1]}/", timeout=0.3)
    assert (state, "0.3 s" in seen) == ("slow", True)
    assert time.monotonic() - t0 < 1.0


def test_the_health_probe_ends_on_an_answer_that_trickles():
    """One header byte every 0.2 s: each read is within the socket's timeout, the whole is not."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    stop = threading.Event()

    def trickle():
        conn, _ = srv.accept()
        with conn:
            for b in b"HTTP/1.1 200 OK\r\nX-Slow: " + b"a" * 200:
                if stop.is_set():
                    return
                conn.sendall(bytes([b]))
                time.sleep(0.2)   # the server under test is slow on purpose

    threading.Thread(target=trickle, daemon=True).start()
    t0 = time.monotonic()
    state, _ = otel.probe(f"http://127.0.0.1:{srv.getsockname()[1]}/", timeout=0.5)
    elapsed = time.monotonic() - t0
    stop.set()
    srv.close()
    assert state == "slow"
    assert elapsed < 1.5


def test_the_health_probe_follows_no_redirect(health):
    """A 302 to another loopback server is not followed: garbage, and the target never asked."""
    handler, url = health
    hit = []

    class Target(_Health):
        def do_GET(self):
            hit.append(self.path)
            super().do_GET()

    target = ThreadingHTTPServer(("127.0.0.1", 0), Target)
    threading.Thread(target=target.serve_forever, daemon=True).start()

    def redirect(self):
        self.send_response(302)
        self.send_header("Location", f"http://127.0.0.1:{target.server_address[1]}/elsewhere")
        self.end_headers()

    handler.do_GET = redirect
    try:
        state, seen = otel.probe(url, timeout=1.0)
    finally:
        target.shutdown()
        target.server_close()
    assert (state, seen) == ("garbage", "HTTP 302: a redirect, not followed")
    assert hit == []


def test_status_warns_when_config_asks_for_the_export_and_the_settings_do_not_have_it(health, tmp_path, monkeypatch):
    _, url = health
    _settings(False)
    f = tmp_path / "cfg" / "config.json"
    f.parent.mkdir()
    f.write_text(json.dumps({"v": 1, "identity": {"owner": "Ada", "kind": "person"},
                             "adapters": {"claude": {"telemetry": {"enabled": True}}}}), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(f))
    res = otel.status(config.load(), tmp_path / "none", url=url, now=DAY2)
    assert res["export"]["config"] is True and res["export"]["settings"] is False
    assert any("install.ps1 -Apply" in line["line"] for line in res["lines"] if line["state"] == "warning")
    assert any("Docker volume" in line["line"] for line in res["lines"])   # the collector up, no folder


def test_brain_telemetry_status_command(health, capsys):
    _, url = health
    _settings(True)
    assert cli.main(["telemetry", "status", "--url", url, "--dir", str(FIXTURES), "--stale-hours", "1e9"]) == 0
    out = capsys.readouterr().out
    assert "telemetry OK the collector answers" in out
    _transcript(time.time())   # Claude Code active now, the fixtures' records of 2026-01
    assert cli.main(["telemetry", "status", "--url", url, "--dir", str(FIXTURES), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["exit"] == 1
    assert cli.main(["telemetry", "status", "--url", "http://example.org:13133/"]) == 2
    assert "not a loopback" in capsys.readouterr().err


# --- the real collector, when its image is on this machine ------------------------------------------------------------

def _image() -> str:
    doc = yaml.safe_load((bundles.ROOT / "sovereign" / "compose.yaml").read_text(encoding="utf-8"))
    return doc["services"]["otel-collector"]["image"]


def _docker_has(image: str) -> bool:
    if not shutil.which("docker"):
        return False
    try:
        p = subprocess.run(["docker", "image", "inspect", image], capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return p.returncode == 0


def _test_config(tmp_path: Path) -> Path:
    """The shipped configuration with its file exporters alone, writing to /out (no Prometheus, Loki or health)."""
    cfg = yaml.safe_load(COLLECTOR.read_text(encoding="utf-8"))
    cfg["exporters"] = {"file/metrics": {"path": "/out/metrics.jsonl"}, "file/logs": {"path": "/out/logs.jsonl"}}
    for signal in ("metrics", "logs"):
        cfg["service"]["pipelines"][signal]["exporters"] = [f"file/{signal}"]
    cfg["extensions"], cfg["service"]["extensions"] = {}, []
    (tmp_path / "out").mkdir()
    (tmp_path / "out").chmod(0o777)   # the collector's user is not this one
    f = tmp_path / "config.yaml"
    f.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return f


def _to_send() -> list[tuple[str, str]]:
    """(signal, OTLP JSON line): the fixtures, then an event with tool details on and an error text."""
    lines = [("metrics" if f.name.startswith("metrics") else "logs", line)
             for f in sorted(FIXTURES.glob("*.jsonl")) for line in f.read_text(encoding="utf-8").splitlines()]
    params = json.dumps({"skill_name": "close-item", "bash_command": "the-secret-text"})
    return lines + [("logs", _event_line("tool_result", {
        "session.id": "s9", "user.email": "ada@example.invalid", "tool_name": "Skill", "success": "false",
        "error": "the-secret-text", "tool_parameters": params}))]


def _send(port: int, lines: list[tuple[str, str]], deadline: float) -> int:
    """POST each line to the collector's OTLP HTTP receiver, again while it starts (until ``deadline``)."""
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    sent = 0
    while sent < len(lines) and time.monotonic() < deadline:
        signal, line = lines[sent]
        req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/{signal}", data=line.encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        try:
            opener.open(req, timeout=10).read()
            sent += 1
        except OSError:
            time.sleep(0.5)   # the collector is still starting: no event to wait on but its port answering
    return sent


def _written(out: Path) -> bool:
    """Both files written, the last event sent among the logs (the batch processor flushes within a second)."""
    try:
        return (out / "metrics.jsonl").stat().st_size > 0 and "close-item" in (out / "logs.jsonl").read_text("utf-8")
    except OSError:
        return False


@pytest.mark.docker
def test_the_pinned_collector_drops_them_end_to_end(tmp_path):
    """The shipped processors run in the pinned collector (never pulled: skipped where the image is absent, the CI):
    the fixtures and an event with tool details and an error text sent over OTLP HTTP come out without a private
    attribute, the MCP and skill names kept."""
    image = _image()
    if not _docker_has(image):
        pytest.skip("the collector's pinned image is not on this machine (it is never pulled by a test)")
    config_file, out = _test_config(tmp_path), tmp_path / "out"
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    name = f"brain-test-otel-{uuid.uuid4().hex[:8]}"
    run = subprocess.run(["docker", "run", "-d", "--rm", "--name", name, "-p", f"127.0.0.1:{port}:4318",
                          "-v", f"{config_file}:/etc/otelcol/config.yaml:ro", "-v", f"{out}:/out", image,
                          "--config=/etc/otelcol/config.yaml"], capture_output=True, text=True, timeout=120)
    if run.returncode != 0:
        pytest.skip(f"docker could not run the collector here: {run.stderr.strip()[:200]}")
    lines, deadline = _to_send(), time.monotonic() + 60
    try:
        assert _send(port, lines, deadline) == len(lines)
        while time.monotonic() < deadline and not _written(out):
            time.sleep(0.5)   # the file exporter writes on its own schedule: nothing to wait on but the file
    finally:
        subprocess.run(["docker", "stop", name], capture_output=True, timeout=60)
    raw = (out / "logs.jsonl").read_text(encoding="utf-8") + (out / "metrics.jsonl").read_text(encoding="utf-8")
    assert [key for key in sorted(DROPPED) if f'"key":"{key}"' in raw] == []
    assert "the-secret-text" not in raw
    assert "example.invalid" not in raw
    recs = list(otel.records(out))
    assert "close-item" in {r.text("skill.name") for r in recs}
    assert "docs" in {r.text("mcp_server.name") for r in recs if r.event == "tool_result"}

