"""The governor's usage-enforce hook (wi-brain-usage-enforce, brain.governor): ask at WARN, refuse at CRITICAL, the
stale reading, the memory, parallel sessions and brainstorms caps, the owner's override, on invented state: owner Ada,
her projects lab and notes, sessions of the desktop app written under a temporary LOCALAPPDATA."""

import io
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import pytest

from brain import cli, governor, projects, transcript

NOW = datetime(2026, 11, 4, 9, 0, tzinfo=timezone.utc)
RESETS = "2026-11-09T12:00:00Z"
START = "mcp__ccd_session__start_session"


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def ms(dt):
    return int(dt.timestamp() * 1000)


@pytest.fixture
def ada(tmp_path, monkeypatch, brain_home):
    """Ada's config.json (with the usage.guard she gives), her registry (lab, notes), an empty app folder, a machine
    at 50 % of committed memory; returns a helper to rewrite her config."""
    app = tmp_path / "local"
    (app / "Claude-Data" / "claude_t" / "claude-code-sessions" / "acct" / "org").mkdir(parents=True)
    monkeypatch.setenv("LOCALAPPDATA", str(app))
    monkeypatch.delenv("BRAIN_GUARD_ALLOW", raising=False)
    monkeypatch.setattr(governor, "memory_pct", lambda: 50.0)
    lab, notes = tmp_path / "lab", tmp_path / "notes"
    lab.mkdir()
    notes.mkdir()
    reg = tmp_path / "projects.yaml"
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    cfg = tmp_path / "config.json"
    monkeypatch.setenv("BRAIN_CONFIG", str(cfg))

    def setup(guard=None, lab_usage=None):
        data = {"v": 1, "identity": {"owner": "Ada", "kind": "person"}}
        if guard is not None:
            data["usage"] = {"guard": guard}
        cfg.write_text(json.dumps(data), encoding="utf-8")
        entry = f"lab: {{root: {lab.as_posix()}" + (f", usage: {json.dumps(lab_usage)}" if lab_usage else "") + "}"
        reg.write_text(entry + f"\nnotes: {{root: {notes.as_posix()}}}\n", encoding="utf-8")
        st = os.stat(cfg)   # a rewrite within the same tick must still change the cache's key
        os.utime(cfg, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))

    setup()
    (brain_home / "ledger").mkdir(parents=True)
    setup.lab, setup.notes, setup.app = lab, notes, app / "Claude-Data" / "claude_t" / "claude-code-sessions"
    return setup


def reading(brain_home, pct, at=NOW - timedelta(minutes=5), window="week", resets=None):
    if resets is None:   # a reading at the real time needs a reset after it, whatever the day the suite runs
        resets = RESETS if iso(at) < RESETS else iso(at + timedelta(days=7))
    f = brain_home / "usage" / "quota.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"v": 1, "at": iso(at), "window": window, "pct": pct, "resets": resets}) + "\n")


def forecast(brain_home, pct, at=NOW - timedelta(minutes=2), pct_h=0.0, usd_per_pct=30.0):
    (brain_home / "usage" / "quota.json").write_text(json.dumps({
        "v": 1, "window": "week", "now": iso(at), "pct_now": pct, "resets": RESETS, "pace": {"pct_h": pct_h},
        "conversion": {"usd_per_pct": usd_per_pct}}), encoding="utf-8")


def app_session(ada, sid, title, active=NOW - timedelta(minutes=1), archived=False, cli="", created=None):
    f = ada.app / "acct" / "org" / f"local_{sid}.json"
    f.write_text(json.dumps({"sessionId": f"local_{sid}", "cliSessionId": cli or f"cli-{sid}", "title": title,
                             "isArchived": archived, "lastActivityAt": ms(active),
                             "createdAt": ms(created or active - timedelta(minutes=30))}), encoding="utf-8")
    os.utime(f, (active.timestamp(), active.timestamp()))   # the app writes the file at its last activity
    return f


def hook(tool, folder, now=NOW, **inp):
    p = {"session_id": "s-ada", "cwd": str(folder), "hook_event_name": "PreToolUse", "tool_name": tool,
         "tool_input": inp, "tool_use_id": "toolu_01"}
    out = governor.decide(p, now)
    return out and (out["hookSpecificOutput"]["permissionDecision"], out["hookSpecificOutput"][
        "permissionDecisionReason"])


def ledger(brain_home):
    return [json.loads(line) for f in (brain_home / "ledger").glob("guards-*.jsonl")
            for line in f.read_text(encoding="utf-8").splitlines()]


def test_the_tools_it_checks():
    assert [governor.kind(t) for t in (START, "mcp__other__start_session", "Agent", "Task", "Workflow", "Bash",
                                       "TaskCreate", "mcp__ccd_session__start_session_x")] == [
        "session", "session", "agent", "agent", "workflow", "", "", ""]


def test_nothing_noted_lets_everything_through(ada, brain_home):
    for tool in (START, "Agent", "Workflow"):
        assert hook(tool, ada.lab, title="x") is None


def test_critical_refuses_every_tool_with_the_reason_and_the_override(ada, brain_home):
    reading(brain_home, 96)
    for tool in (START, "Agent", "Workflow"):
        decision, reason = hook(tool, ada.lab, title="x", initiation="user_asked")
        assert decision == "deny" and "the week quota is at 96 % (CRITICAL from 95 %" in reason
        assert "Override (Ada only): brain usage allow --hours 2 in their own terminal" in reason
        assert "BRAIN_GUARD_ALLOW=usage" in reason and reason.startswith("brain-core usage guard: ")
    assert {(r["guard"], r["check"], r["decision"]) for r in ledger(brain_home)} == {("usage", "critical", "denied")}


def test_warn_asks_the_owner(ada, brain_home):
    reading(brain_home, 85)
    decision, reason = hook("Agent", ada.lab)
    assert decision == "ask" and "WARN from 80 %" in reason and "start it anyway?" in reason
    assert ledger(brain_home)[-1]["decision"] == "asked"
    ada({"warn": 90, "critical": 99})
    assert hook("Agent", ada.lab) is None


def test_the_five_hour_window_counts_too(ada, brain_home):
    reading(brain_home, 40)
    reading(brain_home, 97, window="5h", resets=iso(NOW + timedelta(hours=2)))
    decision, reason = hook("Workflow", ada.lab)
    assert decision == "deny" and "the 5h quota is at 97 %" in reason
    reading(brain_home, 99, at=NOW - timedelta(hours=6), window="5h", resets=iso(NOW - timedelta(hours=1)))
    rows = (brain_home / "usage" / "quota.jsonl").read_text(encoding="utf-8").splitlines()
    (brain_home / "usage" / "quota.jsonl").write_text("\n".join([rows[0], rows[2]]) + "\n", encoding="utf-8")
    assert hook("Workflow", ada.lab) is None   # a window that reset is not in force


def test_the_forecast_and_the_pace_move_the_reading(ada, brain_home):
    reading(brain_home, 70, at=NOW - timedelta(minutes=40))
    forecast(brain_home, 78, at=NOW - timedelta(minutes=30), pct_h=6.0)   # +3 % in the 30 min since
    s = governor.state({"tool_name": "Agent", "cwd": str(ada.lab)}, NOW)
    assert s["quota"]["windows"]["week"]["pct"] == 81.0 and s["quota"]["windows"]["week"]["how"].startswith("forecast")
    assert hook("Agent", ada.lab)[0] == "ask"


def test_a_stale_reading_refuses_a_start_until_both_windows_are_read(ada, brain_home):
    reading(brain_home, 40, at=NOW - timedelta(hours=2))
    decision, reason = hook(START, ada.lab, title="x")
    assert decision == "deny" and "the newest reading is 120 min old" in reason
    assert "call get_usage" in reason and "--window 5h" in reason
    assert hook("Workflow", ada.lab)[1].startswith("brain-core usage guard: a workflow refused until")
    assert hook("Agent", ada.lab) is None   # a subagent reads the cached state only
    ada({"fresh_minutes": 0})
    assert hook(START, ada.lab, title="x") is None
    ada()
    assert hook(START, ada.lab, now=NOW + timedelta(days=8), title="x") is None   # no reading in 7 days: not checked


def test_the_machine_memory_cap(ada, brain_home, monkeypatch):
    monkeypatch.setattr(governor, "memory_pct", lambda: 93.0)
    decision, reason = hook(START, ada.lab, title="x")
    assert decision == "deny" and "committed memory is at 93 % (cap 90 %)" in reason
    assert hook("Workflow", ada.lab)[0] == "deny" and hook("Agent", ada.lab) is None
    ada({"memory": 95})
    assert hook(START, ada.lab, title="x") is None


def test_the_parallel_sessions_cap(ada, brain_home):
    ada({"sessions": 3})
    app_session(ada, "a", "Lab: fit the model")
    app_session(ada, "b", "Notes: tidy")
    assert hook(START, ada.lab, title="x") is None
    app_session(ada, "c", "Lab: plots")
    app_session(ada, "d", "Old work", archived=True)
    app_session(ada, "e", "Idle", active=NOW - timedelta(hours=2))
    decision, reason = hook(START, ada.lab, title="x")
    assert decision == "deny" and "3 session(s) running in parallel, the cap is 3 (usage.guard.sessions 3)" in reason
    assert hook("Agent", ada.lab) is None   # a subagent is not a session


def test_the_cap_follows_the_weeks_room(ada, brain_home):
    ada({"warn": 99, "critical": 99.5})
    reading(brain_home, 90)
    forecast(brain_home, 90, usd_per_pct=30.0)   # 10 % left = $300; / (4 h x $14) = 5, minus the master: 4
    for sid in "abcd":
        app_session(ada, sid, f"Lab {sid}")
    decision, reason = hook(START, ada.lab, title="x")
    assert "the cap is 4 (what the week's room pays for: 10 % left, 4 h at $14 per session-hour" in reason
    ada({"warn": 99, "critical": 99.5, "wave_hours": 2})
    assert hook(START, ada.lab, title="x") is None   # $300 / $28 = 10, minus 1: 9, then the cap of 8


def test_a_measured_session_hour_above_the_configured_one_lowers_the_cap(ada, brain_home):
    """wi-brain-usage-workflow-agents: brain usage quota's session-hour (its workflow agents' cost included) counts
    when it is above usage.guard.session_hour_usd, never below it."""
    ada({"warn": 99, "critical": 99.5})
    reading(brain_home, 90)
    forecast(brain_home, 90, usd_per_pct=30.0)
    status = json.loads((brain_home / "usage" / "quota.json").read_text(encoding="utf-8"))
    for sid in "ab":
        app_session(ada, sid, f"Lab {sid}")
    for usd, cap in ((37.5, 1), (5.0, 4)):   # $300 / (4 h x $37.5) = 2, minus the master: 1; $5 < $14: the config's
        status["session_hour"] = {"usd": usd, "hours": 30, "total_usd": usd * 30, "days": 7}
        (brain_home / "usage" / "quota.json").write_text(json.dumps(status), encoding="utf-8")
        s = governor.state({"tool_name": START, "tool_input": {"title": "x"}, "cwd": str(ada.lab)}, NOW)
        assert s["quota_cap"] == cap and s["session_hour_usd"] == max(usd, 14.0)
    status["session_hour"] = {"usd": 37.5}
    (brain_home / "usage" / "quota.json").write_text(json.dumps(status), encoding="utf-8")
    decision, reason = hook(START, ada.lab, title="x")
    assert decision == "deny" and "the cap is 1 (what the week's room pays for: 10 % left, 4 h at $37.5 per " \
                                  "session-hour" in reason


@pytest.mark.parametrize("inp,expected", [
    ({"title": "Brainstorm: the cockpit, round 3"}, True),
    ({"title": "Ideas", "prompt": "**Task class:** brainstorm. **Context budget:** 400k."}, True),
    ({"title": "Ideas #brainstorm"}, True),
    ({"title": "Record the brainstorm's answers", "prompt": "**Task class:** standard"}, False),
    ({"title": "Fix the parser", "prompt": "Task class: strategic"}, False),
])
def test_how_a_brainstorm_is_known(inp, expected):
    assert governor.is_brainstorm(inp, governor.DEFAULTS) is expected


def test_the_brainstorms_cap_counts_the_whole_machine(ada, brain_home):
    app_session(ada, "a", "Brainstorm: lab methods")   # in lab
    app_session(ada, "b", "Ideas for notes", cli="cli-b")   # its brief's class, in the session record
    (brain_home / "sessions").mkdir()
    (brain_home / "sessions" / "cli-b.json").write_text(json.dumps({"task_class": "brainstorm"}), encoding="utf-8")
    app_session(ada, "c", "Brainstorm: archived", archived=True)
    app_session(ada, "d", "Brainstorm: last week", active=NOW - timedelta(days=2))
    decision, reason = hook(START, ada.notes, title="Brainstorm: notes, round 2")
    assert decision == "deny" and "2 brainstorm(s) open on this machine" in reason and "the cap is 2" in reason
    assert hook(START, ada.notes, title="Fix the notes index") is None   # not a brainstorm
    ada({"brainstorms": 3})   # the owner's own setting
    assert hook(START, ada.notes, title="Brainstorm: notes, round 2") is None


def test_a_project_lowers_the_cap_never_raises_it(ada, brain_home):
    app_session(ada, "a", "Brainstorm: notes")
    ada({"brainstorms": 3}, lab_usage={"brainstorms": 1})
    decision, reason = hook(START, ada.lab, title="Brainstorm: lab")
    assert decision == "deny" and "the cap is 1 for lab" in reason
    assert hook(START, ada.notes, title="Brainstorm: notes 2") is None   # notes keeps 3
    app_session(ada, "b", "Brainstorm: notes 2")
    ada({"brainstorms": 2}, lab_usage={"brainstorms": 5})
    assert "the cap is 2 for lab" in hook(START, ada.lab, title="Brainstorm: lab")[1]
    start_cwd = hook(START, ada.notes, title="Brainstorm: lab", cwd=str(ada.lab / "sub"))   # the start's own folder
    assert "for lab" in start_cwd[1]


def test_a_brainstorm_start_counts_before_its_session_shows(ada, brain_home):
    assert hook(START, ada.lab, title="Brainstorm: one", initiation="user_asked") is None
    assert hook(START, ada.lab, title="Brainstorm: two", initiation="user_asked",
                now=NOW + timedelta(minutes=1)) is None
    decision, reason = hook(START, ada.lab, title="Brainstorm: three", initiation="user_asked",
                            now=NOW + timedelta(minutes=2))
    assert decision == "deny" and "Brainstorm: one, Brainstorm: two" in reason
    app_session(ada, "a", "Brainstorm: one", created=NOW + timedelta(seconds=10))   # shown: counted once
    assert "2 brainstorm(s)" in hook(START, ada.lab, title="Brainstorm: three", now=NOW + timedelta(minutes=3))[1]
    s = governor.sessions_now(NOW + timedelta(minutes=12), governor.DEFAULTS)
    assert s["brainstorms"] == 1   # the start not shown is forgotten after 10 minutes; the shown one stays


def test_the_owners_override(ada, brain_home, monkeypatch):
    reading(brain_home, 97, at=datetime.now(timezone.utc) - timedelta(minutes=1))
    now = datetime.now(timezone.utc)
    assert hook("Agent", ada.lab, now=now)[0] == "deny"
    rec = governor.allow(2, "the pilot demo")
    assert rec["reason"] == "the pilot demo" and hook("Agent", ada.lab, now=now) is None
    assert ledger(brain_home)[-1]["decision"] == "overridden"
    governor.allow(0)
    assert hook("Agent", ada.lab, now=now)[0] == "deny"
    monkeypatch.setenv("BRAIN_GUARD_ALLOW", "usage")
    assert hook("Agent", ada.lab, now=now) is None


def test_the_decision_takes_under_50_ms_with_a_cached_reading(ada, brain_home):
    reading(brain_home, 60)
    forecast(brain_home, 61)
    for sid in "abcdef":
        app_session(ada, sid, f"Session {sid}")
    payload = {"tool_name": START, "cwd": str(ada.lab), "tool_input": {"title": "Brainstorm: x"}}
    governor.decide(payload, NOW)   # builds the settings and the app sessions' caches
    best = min(_timed(lambda: governor.decide(payload, NOW)) for _ in range(5))
    assert best < 0.050, f"{best * 1000:.1f} ms"


def _timed(fn):
    t = time.perf_counter()
    fn()
    return time.perf_counter() - t


def test_config_errors_are_reported_and_leave_the_defaults(ada, brain_home, tmp_path):
    lim, errors = governor.limits_of({"warn": "high", "sessions": -1, "brainstorm_title": "(", "x": 1})
    assert lim["warn"] == 80 and lim["sessions"] == 8 and lim["brainstorm_title"] == governor.DEFAULTS[
        "brainstorm_title"]
    assert errors == ["usage.guard.warn: a number of 0 or more", "usage.guard.sessions: a number of 0 or more",
                      "usage.guard.x: unknown (known: " + ", ".join(governor.DEFAULTS) + ")",
                      "usage.guard.brainstorm_title: not a regular expression (missing ), unterminated subpattern "
                      "at position 0)"]
    ada(lab_usage={"brainstorms": "two", "cpus": 2})
    assert projects.check() == ["project lab: usage.brainstorms: a whole number of 0 or more",
                                "project lab: usage.cpus: unknown (known: sessions, brainstorms)"]
    assert "usage" in projects.KEYS


def test_an_error_lets_the_call_through(ada, brain_home, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("bad state")

    monkeypatch.setattr(governor, "state", boom)
    out = io.StringIO()
    assert governor.main(stdin=io.StringIO(json.dumps({"tool_name": "Agent"})), stdout=out) == 0
    assert out.getvalue() == "" and "governor: RuntimeError: bad state" in (
        brain_home / "ledger" / "errors.log").read_text(encoding="utf-8")


def test_the_hook_script_end_to_end(ada, brain_home):
    from test_capture import _bash
    from test_guards import PLUGIN
    sh = _bash()
    if not sh:
        pytest.skip("no bash")
    reading(brain_home, 99, at=datetime.now(timezone.utc) - timedelta(minutes=1))
    env = dict(os.environ, BRAIN_PYTHON=sys.executable)
    p = {"tool_name": "Workflow", "cwd": str(ada.lab), "tool_input": {}, "session_id": "s-ada"}
    out = subprocess.run([sh, str(PLUGIN / "hooks" / "governor.sh")], input=json.dumps(p), capture_output=True,
                         text=True, env=env, timeout=60)
    assert out.returncode == 0
    hso = json.loads(out.stdout)["hookSpecificOutput"]
    assert hso["permissionDecision"] == "deny" and "CRITICAL" in hso["permissionDecisionReason"]
    p["tool_name"] = "Bash"
    assert subprocess.run([sh, str(PLUGIN / "hooks" / "governor.sh")], input=json.dumps(p), capture_output=True,
                          text=True, env=env, timeout=60).stdout == ""


def test_brain_usage_guard_and_allow(ada, brain_home, capsys, monkeypatch):
    monkeypatch.chdir(ada.lab)
    reading(brain_home, 85, at=datetime.now(timezone.utc) - timedelta(minutes=1))
    assert cli.main(["usage", "guard"]) == 0
    out = capsys.readouterr().out
    assert "usage guard (on; project lab): warn 80 %" in out and "agent      ask (warn)" in out
    assert cli.main(["usage", "guard", "--json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["workflow"]["decision"] == "ask" and rep["state"]["owner"] == "Ada"
    assert cli.main(["usage", "allow", "--hours", "1.5", "--reason", "demo"]) == 0
    assert "usage guard lifted until" in capsys.readouterr().out
    assert json.loads(governor.allow_file().read_text(encoding="utf-8"))["reason"] == "demo"
    assert cli.main(["usage", "allow", "--hours", "0"]) == 0 and not governor.allow_file().exists()


def test_the_session_record_has_ultracode_and_the_task_class(tmp_path):
    f = tmp_path / "s.jsonl"
    rows = [{"type": "user", "timestamp": "2026-11-03T10:00:00Z", "sessionId": "ada00001-0000",
             "message": {"content": "**Task class:** brainstorm. **Context budget:** 400k. Ideas for the lab."}},
            {"type": "attachment", "timestamp": "2026-11-03T10:01:00Z", "sessionId": "ada00001-0000",
             "attachment": {"type": "ultra_effort_enter", "reminderType": "full"}}]
    f.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    st = transcript.SessionStats()
    st.feed_file(f)
    sr = st.record(f)
    assert sr["task_class"] == "brainstorm" and sr["ultracode"] is True and sr["context"]["budget"] == 400_000
    st = transcript.SessionStats.from_state(json.loads(json.dumps(st.to_state())))
    assert st.ultracode and st.task_class == "brainstorm"
    plain = transcript.SessionStats()
    plain.feed(rows[0] | {"message": {"content": "Fix it."}})
    assert plain.record()["ultracode"] is False and "task_class" not in plain.record()
    from brain import schema
    assert schema.check("sr", sr)[0] == []
