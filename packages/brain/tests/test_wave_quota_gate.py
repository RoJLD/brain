"""The wave quota gate (wi-brain-wave-quota-gate; RETRO-5 of the waves retro: by the quota, three streams at most with
their reviews): the governor asks before a stream's start_session when the week's forecast at its reset plus the
stream's estimate goes over usage.guard.wave_quota.ask_over_pct, refuses a fourth live stream of the same master, and
fails open with a note; off while the key is absent. On invented state: owner Ada, her project lab, her coordinator's
children written as the desktop app's session files under a temporary LOCALAPPDATA, their transcripts under a
temporary CLAUDE_CONFIG_DIR; the forecast is a real ``usage/quota.json`` (and its reading) with the host renamed."""

# ruff: noqa: F811 - ada, the fixture imported from test_governor, is each test's parameter
import json
import os
import shutil
from datetime import datetime, timedelta, timezone

import pytest
from brain import cli, cockpit, config, governor, lots, wavegate
from conftest import FIXTURES
from test_governor import NOW, START, ada, forecast, iso, ledger, ms, reading  # noqa: F401 - ada is a fixture

MASTER, M_CLI = "local_aaaaaaaa-0000-4000-8000-00000000000a", "s-ada"
WAVE = {"ask_over_pct": 90, "max_streams": 3}
BRIEF = ("**Item:** `wi-lab-x`\n- **Cost estimate:** 2026-11-04 class=standard basis=size+class n=9 size=M "
         "usd=11.00 [7.63-13.01] out=80k [77k-89k]\nDo the work.")
QUOTA = FIXTURES / "quota"
REAL_NOW = datetime(2026, 11, 13, 12, 30, tzinfo=timezone.utc)   # 5 min after the real reading


def app_file(ada, host, cli_id, title, parent=None, created=NOW - timedelta(minutes=30), archived=False,
             detached=None, name=None):
    """One app session file, with the keys the app writes (and some the engine must never read)."""
    data = {"sessionId": host, "cliSessionId": cli_id, "title": title, "createdAt": ms(created),
            "lastActivityAt": ms(created + timedelta(seconds=20)), "isArchived": archived, "model": "claude-x",
            "lastTurnReport": "ada@example.invalid", "spawnSeed": "the brief"}
    if parent:
        data["spawnedFrom"] = {"sessionId": parent, "taskId": "task_1", "name": name or title.lower(),
                               "sideSession": True}
    if detached is not None:
        data["lineageDetached"] = detached
    f = ada.app / "acct" / "org" / f"{host}.json"
    f.write_text(json.dumps(data), encoding="utf-8")
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    return f


def transcript(tmp_path, sid, *records, at=NOW - timedelta(minutes=1)):
    f = tmp_path / "claude-config" / "projects" / "E--lab" / f"{sid}.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    os.utime(f, (at.timestamp(), at.timestamp()))
    return f


WORKING = ({"type": "user", "message": {"content": "the brief"}},
           {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash",
                                                          "input": {}}], "stop_reason": "tool_use"}})
DONE = (*WORKING, {"type": "assistant", "message": {"content": [{"type": "text", "text": "PR #7"}],
                                                    "stop_reason": "end_turn"}},
        {"type": "system", "subtype": "stop_hook_summary"})


def master(ada):
    app_file(ada, MASTER, M_CLI, "Ada's coordinator", created=NOW - timedelta(hours=3))


def child(ada, tmp_path, n, records=WORKING, **kw):
    """Child ``n`` of Ada's coordinator (named ``stream-n``), created ``30 - n`` minutes ago (the higher, the newer)."""
    host = f"local_bbbbbbbb-0000-4000-8000-00000000000{n}"
    app_file(ada, host, f"c-{n}", f"Stream {n}", parent=MASTER, name=f"stream-{n}",
             **{"created": NOW - timedelta(minutes=30 - n), **kw})
    if records:
        transcript(tmp_path, f"c-{n}", *records)
    return host


def start(ada, now=NOW, **inp):
    """The hook's whole output for a start_session call of Ada's coordinator."""
    inp = {"title": "Stream next", "initiation": "user_asked", "prompt": BRIEF, **inp}
    return governor.decide({"session_id": M_CLI, "cwd": str(ada.lab), "hook_event_name": "PreToolUse",
                            "tool_name": START, "tool_input": inp, "tool_use_id": "toolu_01"}, now)


def decision(out):
    return out and (out["hookSpecificOutput"].get("permissionDecision"),
                    out["hookSpecificOutput"].get("permissionDecisionReason")
                    or out["hookSpecificOutput"].get("additionalContext"))


@pytest.fixture
def wave(ada, brain_home):
    """Ada's gate on, her week at 60 % read 5 minutes ago and its forecast: 0.3 %/h, $30 per % (a $11 stream: 0.37 %),
    the reset 5 d 3 h away: 60 + 0.3 x 123 = 96.9 at the reset with no stream (over 90); her coordinator in the app."""
    ada({"wave_quota": WAVE, "sessions": 20})   # the parallel sessions cap never speaks first here
    master(ada)
    reading(brain_home, 60)
    return brain_home


def test_the_key_absent_turns_the_gate_off(ada, brain_home, tmp_path):
    master(ada)
    reading(brain_home, 60)
    forecast(brain_home, 60, pct_h=1.0)   # 183 % at the reset
    for n in range(1, 5):
        child(ada, tmp_path, n)
    assert start(ada) is None   # neither asked nor refused, no note
    assert governor.settings(str(ada.lab))["limits"]["wave_quota"] is None
    assert not (brain_home / "usage" / "starts.jsonl").exists()   # no stream noted either


def test_under_the_threshold_a_stream_starts(ada, wave, tmp_path):
    forecast(wave, 60, pct_h=0.2)   # 60.0 + 0.2 x 123.03 h = 84.6; + 0.37 % = 85.0
    child(ada, tmp_path, 1)
    assert start(ada) is None
    (rec,) = [json.loads(x) for x in (wave / "usage" / "starts.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rec["stream"] is True and rec["brainstorm"] is False and rec["by"] == M_CLI and rec["title"] == "Stream next"


def test_over_the_threshold_it_asks_the_owner_with_the_arithmetic(ada, wave):
    forecast(wave, 60, pct_h=0.3)
    d, reason = decision(start(ada))
    assert d == "ask" and "a new stream: the week's forecast at its reset 2026-11-09 12:00 UTC is 97 %" in reason
    assert ("(60 % at 08:58 UTC + 0.30 %/h x 123.0 h) plus this stream's 0.4 % ($11.00, the brief's estimate): "
            "97 %") in reason
    assert "over 90 % (usage.guard.wave_quota.ask_over_pct); start it anyway?" in reason
    assert ledger(wave)[-1]["check"] == "wave_quota" and ledger(wave)[-1]["decision"] == "asked"
    ada({"wave_quota": {"ask_over_pct": 98}})
    assert start(ada) is None
    ada({"wave_quota": {"ask_over_pct": 0}})   # 0: no quota check
    assert start(ada) is None


def test_the_stream_s_own_estimate_tips_it_over(ada, wave):
    """84.6 % at the reset: a $11 stream (0.37 %) passes, a $200 one (6.67 %) goes over 90; without an estimate in the
    brief, the median session's cost stands in, said so."""
    forecast(wave, 60, pct_h=0.2)
    assert start(ada) is None
    d, reason = decision(start(ada, prompt=BRIEF.replace("usd=11.00", "usd=200")))
    assert d == "ask" and "plus this stream's 6.7 % ($200.00, the brief's estimate): 91 %" in reason
    q = json.loads((wave / "usage" / "quota.json").read_text(encoding="utf-8"))
    q["live"] = {"median_session_usd": 240.0}
    (wave / "usage" / "quota.json").write_text(json.dumps(q), encoding="utf-8")
    d, reason = decision(start(ada, prompt="Do the work."))
    assert d == "ask" and "($240.00, the median session's cost, the brief giving no estimate)" in reason


def test_a_fourth_live_stream_of_the_same_master_is_refused(ada, wave, tmp_path):
    forecast(wave, 30, pct_h=0.0)   # the quota leaves room: only the streams cap speaks
    for n in (1, 2, 3):
        child(ada, tmp_path, n)
    d, reason = decision(start(ada))
    assert d == "deny" and "this session already has 3 live stream(s) (stream-3, stream-2, stream-1)" in reason
    assert "the cap is 3 (usage.guard.wave_quota.max_streams" in reason and "brain usage allow" in reason
    assert ledger(wave)[-1]["check"] == "streams"
    ada({"wave_quota": {"max_streams": 4}})
    assert start(ada) is None


def test_what_counts_as_a_live_stream(ada, wave, tmp_path):
    """Running (a turn under way, written in the last 30 min) and starting (created in the last 10 min, no
    transcript yet) count; a child that ended its turn, asks, went quiet, is archived or detached, another master's
    child, and a proposal card do not."""
    forecast(wave, 30)
    child(ada, tmp_path, 1)                                                     # running
    child(ada, tmp_path, 2, records=(), created=NOW - timedelta(minutes=2))     # starting
    child(ada, tmp_path, 3, records=DONE)                                       # its turn ended: idle
    child(ada, tmp_path, 4, records=(*WORKING, {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "q", "name": "AskUserQuestion", "input": {}}]}}))   # asking
    child(ada, tmp_path, 5, archived=True)
    child(ada, tmp_path, 6, detached=True)
    child(ada, tmp_path, 7, records=())                                         # no transcript, not new
    host8 = child(ada, tmp_path, 8)
    transcript(tmp_path, "c-8", *WORKING, at=NOW - timedelta(minutes=45))     # quiet for 45 min
    app_file(ada, "local_cccccccc-0000-4000-8000-00000000000c", "other-cli", "Other's", parent="local_other")
    lim = governor.caps(governor.settings(str(ada.lab)), "lab")
    s = wavegate.live_streams(M_CLI, NOW, lim)
    assert s["n"] == 2 and s["names"] == ["stream-2", "stream-1"] and s["host_id"] == MASTER
    assert wavegate.live_streams(MASTER, NOW, lim)["n"] == 2   # the app's id names the master too
    assert wavegate.child_state({"session": "c-8", "host_id": host8}, NOW, lim) == "quiet"
    child(ada, tmp_path, 9)
    assert decision(start(ada))[0] == "deny" and ledger(wave)[-1]["check"] == "streams"
    for card in ({"initiation": "offer", "prompt": ""}, {"initiation": "own_initiative"}):
        assert start(ada, **card) is None   # a card starts nothing: neither checked nor noted
    assert decision(start(ada, initiation=None, proposal_id="task_9", title=""))[0] == "deny"   # a proposal's start


def test_a_start_counts_before_the_app_shows_it(ada, wave, tmp_path):
    """Parallel starts in one message: each sees the others for a minute, until the app shows their children."""
    forecast(wave, 30)
    child(ada, tmp_path, 1)
    assert start(ada, title="Stream two") is None
    assert start(ada, title="Stream three", now=NOW + timedelta(seconds=20)) is None
    d, reason = decision(start(ada, title="Stream four", now=NOW + timedelta(seconds=40)))
    assert d == "deny" and "3 live stream(s) (stream-1, Stream two, Stream three)" in reason
    # the app shows Stream two (no transcript yet: starting): counted once, not twice
    app_file(ada, "local_bbbbbbbb-0000-4000-8000-0000000000e2", "c-two", "Stream two", parent=MASTER,
             created=NOW + timedelta(seconds=5))
    lim = governor.caps(governor.settings(str(ada.lab)), "lab")
    assert wavegate.live_streams(M_CLI, NOW + timedelta(seconds=50), lim)["n"] == 3
    # a minute on, the start no child matched is forgotten; Stream two still starts
    assert wavegate.live_streams(M_CLI, NOW + timedelta(minutes=2), lim)["names"] == ["stream two", "stream-1"]


def _streams(ada, at):
    return wavegate.live_streams(M_CLI, at, governor.caps(governor.settings(str(ada.lab)), "lab"))


def test_a_failed_start_retried_holds_no_slot(ada, wave, tmp_path):
    """Review of #222, finding 1a: a start the governor let through but the app refused (no child ever comes), then
    retried: the first is forgotten after a minute, the retry counts once."""
    forecast(wave, 30)
    child(ada, tmp_path, 1)
    child(ada, tmp_path, 2)
    assert start(ada, title="Stream three") is None   # the app refuses it: no child
    assert _streams(ada, NOW + timedelta(seconds=30))["n"] == 3
    assert start(ada, title="Stream three", now=NOW + timedelta(minutes=2)) is None   # the retry passes
    app_file(ada, "local_bbbbbbbb-0000-4000-8000-0000000000f3", "c-three", "Stream three", parent=MASTER,
             created=NOW + timedelta(minutes=2, seconds=4))
    assert _streams(ada, NOW + timedelta(minutes=2, seconds=30))["n"] == 3


def test_a_quick_child_archived_or_detached_holds_no_slot(ada, wave, tmp_path):
    """Finding 1b: a review that ran and was archived (or detached) within the minute matches its start: no slot."""
    forecast(wave, 30)
    child(ada, tmp_path, 1)
    assert start(ada, title="Review one") is None
    assert start(ada, title="Review two", now=NOW + timedelta(seconds=10)) is None
    app_file(ada, "local_bbbbbbbb-0000-4000-8000-0000000000a1", "c-r1", "Review one", parent=MASTER,
             created=NOW + timedelta(seconds=3), archived=True)
    app_file(ada, "local_bbbbbbbb-0000-4000-8000-0000000000a2", "c-r2", "Review two", parent=MASTER,
             created=NOW + timedelta(seconds=13), detached=True)
    s = _streams(ada, NOW + timedelta(seconds=30))
    assert s["n"] == 1 and s["names"] == ["stream-1"]


def test_a_child_whose_title_differs_matches_its_start_by_time(ada, wave, tmp_path):
    """Finding 1c: the app shows another title (renamed, or cut at 60 characters): the start is matched on its
    creation time; the title and the short name only break a tie."""
    forecast(wave, 30)
    long = "A stream whose title runs well past the sixty characters the app keeps for it"
    assert start(ada, title=long, name="long-one") is None
    assert start(ada, title="Short", name="short", now=NOW + timedelta(seconds=1)) is None
    app_file(ada, "local_bbbbbbbb-0000-4000-8000-0000000000b1", "c-b1", long[:60], parent=MASTER,
             created=NOW + timedelta(seconds=4), name="long-one")
    app_file(ada, "local_bbbbbbbb-0000-4000-8000-0000000000b2", "c-b2", "Renamed by the owner", parent=MASTER,
             created=NOW + timedelta(seconds=4), name="other")
    s = _streams(ada, NOW + timedelta(seconds=20))
    assert s["n"] == 2 and sorted(s["names"]) == ["long-one", "other"]   # both starting, no start left over
    starts = wavegate._stream_starts(NOW + timedelta(seconds=20), M_CLI)
    kids = [{"created": ms(NOW + timedelta(seconds=4)), "title": "x", "name": "short"},
            {"created": ms(NOW + timedelta(seconds=4)), "title": long[:60], "name": "long-one"}]
    assert wavegate._unmatched(starts, kids) == []
    assert wavegate._unmatched(starts, kids[:1]) == ["Short"]   # the tie goes to the name: long-one is the one left


def test_a_start_asked_about_is_noted(ada, wave, tmp_path):
    """Finding 2: a start the governor asks the owner about may pass: a parallel start counts it (for a minute)."""
    forecast(wave, 60, pct_h=0.3)   # every stream asks
    child(ada, tmp_path, 1)
    child(ada, tmp_path, 2)
    assert decision(start(ada, title="Stream three"))[0] == "ask"
    rec = json.loads((wave / "usage" / "starts.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert rec["stream"] is True and rec["asked"] is True and rec["brainstorm"] is False
    assert decision(start(ada, title="Stream four", now=NOW + timedelta(seconds=5)))[0] == "deny"
    assert decision(start(ada, title="Stream four", now=NOW + timedelta(minutes=2)))[0] == "ask"   # declined: gone


def test_the_projection_runs_from_the_reading_not_from_the_capped_now(ada, wave):
    """Finding 3: 60 % read 5 h ago at 1 %/h with fresh_minutes 0: quota_now's percent now stays at 60 (its pace is
    capped at fresh_minutes), but the forecast at the reset runs from the reading: 60 + 1 x 128 h = 188, not 183."""
    ada({"wave_quota": WAVE, "sessions": 20, "fresh_minutes": 0})
    (wave / "usage" / "quota.jsonl").unlink()
    reading(wave, 60, at=NOW - timedelta(hours=5))
    forecast(wave, 60, at=NOW - timedelta(hours=5), pct_h=1.0)
    lim = governor.caps(governor.settings(str(ada.lab)), "lab")
    q = governor.quota_now(NOW, lim)
    assert q["windows"]["week"]["pct"] == 60.0 and q["windows"]["week"]["base_pct"] == 60.0
    p = wavegate.projection(q, NOW)
    assert p["at_reset"] == 188.0 and p["hours"] == 128.0 and p["now_pct"] == 65.0 and p["hours_left"] == 123.0
    d, reason = decision(start(ada))
    assert d == "ask" and "is 188 % (60 % at 04:00 UTC + 1.00 %/h x 128.0 h)" in reason


def test_a_last_record_past_64_kb_is_read_once_larger(ada, wave, tmp_path):
    """Finding 4: a turn that ended on a record past 64 KB reads idle (a 1 MB tail), not active; one past 1 MB is
    unknown, never live."""
    lim = governor.caps(governor.settings(str(ada.lab)), "lab")
    big = {"type": "assistant", "message": {"content": [{"type": "text", "text": "x" * 70_000}],
                                            "stop_reason": "end_turn"}}
    child(ada, tmp_path, 1, records=(*WORKING, big))
    node = {"session": "c-1", "created": ms(NOW - timedelta(minutes=29))}
    assert wavegate.child_state(node, NOW, lim) == "idle"
    huge = dict(big, message=dict(big["message"], content=[{"type": "text", "text": "x" * 1_100_000}]))
    transcript(tmp_path, "c-1", *WORKING, huge)
    assert wavegate.child_state(node, NOW, lim) == "unknown"
    young = dict(node, created=ms(NOW - timedelta(minutes=2)))
    assert wavegate.child_state(young, NOW, lim) == "starting"


def test_an_unreadable_forecast_lets_the_start_through_with_a_note(ada, wave, tmp_path):
    for garbage in (None, "{not json", json.dumps({"window": "week", "now": iso(NOW), "resets": "2026-11-09T12:00Z",
                                                   "pace": {"pct_h": "fast"}, "conversion": {"usd_per_pct": True}})):
        f = wave / "usage" / "quota.json"
        if garbage is None:
            f.unlink(missing_ok=True)
        else:
            f.write_text(garbage, encoding="utf-8")
        (wave / "usage" / "starts.jsonl").unlink(missing_ok=True)   # each start let through is a stream noted
        out = start(ada)
        assert "permissionDecision" not in out["hookSpecificOutput"]
        assert "Wave quota gate (usage.guard.wave_quota): the week's forecast cannot be read" in decision(out)[1]
        assert "the start goes through unchecked by it." in decision(out)[1]
    # the last forecast is of last week (its reset another): its pace is not this week's
    (wave / "usage" / "quota.json").write_text(json.dumps({
        "v": 1, "window": "week", "now": iso(NOW - timedelta(days=8)), "pct_now": 90, "resets": "2026-11-02T12:00:00Z",
        "pace": {"pct_h": 5.0}, "conversion": {"usd_per_pct": 30.0}}), encoding="utf-8")
    (wave / "usage" / "starts.jsonl").unlink(missing_ok=True)
    out = start(ada)
    assert "permissionDecision" not in out["hookSpecificOutput"]
    assert "the week's forecast cannot be read" in decision(out)[1]


def test_a_missing_ledger_or_app_and_a_slow_count_let_it_through_with_a_note(ada, brain_home, tmp_path, monkeypatch):
    ada({"wave_quota": WAVE})
    out = start(ada)   # no reading, no forecast, the master not in the app
    text = decision(out)[1]
    assert "the week's forecast cannot be read" in text and "this session is not one of the desktop app's" in text
    master(ada)
    child(ada, tmp_path, 1)
    monkeypatch.setattr(wavegate, "BUDGET_S", -1.0)   # a count that times out, timed from before the app is read
    assert "the live streams were not counted within -1 s" in decision(start(ada))[1]
    monkeypatch.setattr(wavegate, "BUDGET_S", 2.0)
    monkeypatch.delenv("LOCALAPPDATA")
    assert "the desktop app's sessions are not on this machine" in decision(start(ada))[1]


def test_a_failure_inside_the_gate_lets_it_through_with_a_note(ada, wave, monkeypatch):
    forecast(wave, 30)

    def boom(*a, **k):
        raise OSError("disk gone")

    monkeypatch.setattr(wavegate, "live_streams", boom)
    out = start(ada)
    assert "permissionDecision" not in out["hookSpecificOutput"]
    assert "the gate failed (OSError: disk gone)" in decision(out)[1]


def test_the_owners_override_lifts_it(ada, wave, tmp_path, monkeypatch):
    forecast(wave, 60, pct_h=0.3)
    for n in (1, 2, 3):
        child(ada, tmp_path, n)
    monkeypatch.setenv("BRAIN_GUARD_ALLOW", "usage")
    assert start(ada) is None and ledger(wave)[-1]["decision"] == "overridden"


def test_an_allow_lifts_the_gate_s_checks_only_when_named(ada, wave, tmp_path, monkeypatch):
    """The gate's checks follow the governor's override scope (RETRO-8): an allow without --check (the machine's caps)
    leaves both on and the refusal names the allow that lifts it; --check streams lets the next check (wave_quota)
    decide; naming both lets the start through; BRAIN_GUARD_ALLOW=usage:CHECK lifts one."""
    forecast(wave, 60, pct_h=0.3)   # wave_quota holds too, behind streams
    for n in (1, 2, 3):
        child(ada, tmp_path, n)
    governor.allow(hours=1, now=NOW)
    d, reason = decision(start(ada))
    assert d == "deny" and "brain usage allow --check streams" in reason
    governor.allow(hours=1, now=NOW, checks=["streams"])
    d, reason = decision(start(ada))
    assert d == "ask" and "over 90 % (usage.guard.wave_quota.ask_over_pct)" in reason
    assert [(r["check"], r["decision"], r.get("by")) for r in ledger(wave)[-2:]] == [
        ("streams", "overridden", "allow"), ("wave_quota", "asked", None)]
    governor.allow(hours=1, now=NOW, checks=["wave_quota"])
    assert start(ada) is None
    governor.allow(hours=0, now=NOW)
    monkeypatch.setenv("BRAIN_GUARD_ALLOW", "usage:streams")
    d, _ = decision(start(ada))
    assert d == "ask" and ledger(wave)[-2]["by"] == "BRAIN_GUARD_ALLOW"


def test_the_threshold_on_a_real_forecast(ada, brain_home):
    """A real ``usage/quota.json`` (brain usage quota's, the host renamed) and its reading: 78 % read at 12:24:41,
    2.157 %/h over the last 24 h, the reset Monday 12:00 UTC: at 12:30, 78.19 + 2.157 x 71.5 h = 232.4 % at the
    reset, so a stream asks; at a slower pace of 0.05 %/h, 81.8 %: a $11 stream (0.65 % at 0.058719 %/$) passes and a
    $150 one (8.8 %) goes over 90."""
    ada({"wave_quota": WAVE})
    (brain_home / "usage").mkdir(parents=True, exist_ok=True)
    shutil.copy(QUOTA / "quota.json", brain_home / "usage" / "quota.json")
    shutil.copy(QUOTA / "quota.jsonl", brain_home / "usage" / "quota.jsonl")
    lim = governor.caps(governor.settings(str(ada.lab)), "lab")
    q = governor.quota_now(REAL_NOW, lim)
    p = wavegate.projection(q, REAL_NOW)
    got = wavegate.inputs(q)
    assert got == {"pct_h": 2.157, "pct_per_usd": 0.058719, "median_session_usd": 26.4}
    assert p["now_pct"] == 78.2 and p["hours_left"] == 71.5 and p["at_reset"] == 232.4
    d, reason = decision(start(ada, now=REAL_NOW))
    assert d == "ask" and ("is 232 % (78 % at 12:24 UTC + 2.16 %/h x 71.6 h) plus this stream's 0.7 % ($11.00, "
                           "the brief's estimate): 233 %") in reason
    data = json.loads((QUOTA / "quota.json").read_text(encoding="utf-8"))
    data["pace"]["pct_h"] = 0.05
    (brain_home / "usage" / "quota.json").write_text(json.dumps(data), encoding="utf-8")
    p = wavegate.projection(governor.quota_now(REAL_NOW, lim), REAL_NOW)
    assert p["now_pct"] == 78.0 and round(p["at_reset"]) == 82
    assert decision(start(ada, now=REAL_NOW))[0] is None   # a note (the master is not in the app), no question
    d, reason = decision(start(ada, now=REAL_NOW, prompt=BRIEF.replace("usd=11.00", "usd=200.00")))
    assert d == "ask" and "plus this stream's 11.7 % ($200.00, the brief's estimate): 93 %" in reason


def test_the_config_key_is_validated(ada, brain_home):
    lim, errors = governor.limits_of({"wave_quota": {"ask_over_pct": 120, "max_streams": 2.5, "streams": 3}})
    assert lim["wave_quota"] == {"ask_over_pct": 90.0, "max_streams": 3}
    assert errors == ["usage.guard.wave_quota.ask_over_pct: a number from 0 to 100",
                      "usage.guard.wave_quota.max_streams: a whole number of 0 or more",
                      "usage.guard.wave_quota.streams: unknown (known: ask_over_pct, max_streams)"]
    assert governor.limits_of({"wave_quota": True}) == (dict(governor.DEFAULTS), [
        "usage.guard.wave_quota: a mapping of ask_over_pct, max_streams (the gate stays off)"])
    assert governor.limits_of({"wave_quota": {}})[0]["wave_quota"] == wavegate.DEFAULTS
    ada({"wave_quota": WAVE})
    assert config.check() == []   # the schema knows the key
    ada({"wave_quota": {"max_streams": -1}})
    assert config.check()


def test_the_turn_reads_as_the_cockpit_reads_it():
    """The hook's own turn reader (the cockpit's import costs a second) agrees with brain.cockpit.turn on whether a
    turn is under way, over every prefix of the real transcripts of the fixtures and of the shapes above."""
    sets = [list(WORKING), list(DONE)]
    for f in (FIXTURES / "transcript.jsonl", FIXTURES / "claude" / "transcript.jsonl"):
        sets.append([json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()])
    for recs in sets:
        for i in range(len(recs) + 1):
            assert (wavegate.turn(recs[:i]) == "active") == (cockpit.turn(recs[:i]) == "active"), (recs[:i])


def test_brain_usage_guard_says_how_many_fit(ada, wave, tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(ada.lab)
    monkeypatch.delenv("CLAUDE_CODE_HOST_SESSION_ID", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", M_CLI)
    monkeypatch.setattr(governor, "_now", lambda: NOW)
    forecast(wave, 60, pct_h=0.2)   # 84.6 % at the reset; 30 $/% : the median $60 stream is 2 %
    q = json.loads((wave / "usage" / "quota.json").read_text(encoding="utf-8"))
    q["live"] = {"median_session_usd": 60.0}
    (wave / "usage" / "quota.json").write_text(json.dumps(q), encoding="utf-8")
    child(ada, tmp_path, 1)
    assert cli.main(["usage", "guard"]) == 0
    out = capsys.readouterr().out
    assert ("  waves     ask over 90 % at the reset, 3 stream(s) at most a master; fit now 2 (by the quota 2: the "
            "week 60 % now, 85 % at its reset 2026-11-09 12:00 UTC at the last forecast's pace, asked over 90 %, a "
            "stream 2.0 %; by the streams 2: 1 live of 3 (stream-1); usage.guard.wave_quota)") in out
    assert cli.main(["usage", "guard", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["waves"]["fit"] == 2
    governor.allow(hours=1, now=NOW, checks=["streams"])   # the line says the allow; the count ignores it
    assert cli.main(["usage", "guard"]) == 0
    out = capsys.readouterr().out
    assert "usage.guard.wave_quota) (lifted by the allow in force: streams; the count ignores it)" in out
    governor.allow(hours=0, now=NOW)
    ada()
    assert cli.main(["usage", "guard"]) == 0
    assert "  waves     off (usage.guard.wave_quota not set)" in capsys.readouterr().out


def test_an_ask_goes_out_when_its_start_cannot_be_noted(ada, wave, monkeypatch):
    """The starts log unwritable (a sharing violation): the ask still reaches the owner, the failure in errors.log."""
    forecast(wave, 60, pct_h=0.3)

    def locked(*a, **kw):
        raise PermissionError("sharing violation")

    monkeypatch.setattr(governor, "_note_start", locked)
    d, reason = decision(start(ada))
    assert d == "ask" and "usage.guard.wave_quota.ask_over_pct" in reason
    assert "governor note_start" in (wave / "ledger" / "errors.log").read_text(encoding="utf-8")


def test_brain_wave_plan_sizes_its_rounds_by_the_streams(ada, wave, tmp_path, monkeypatch):
    """brain wave plan: a round holds at most max_streams lots, and says how many fit now, each lot at its items'
    recorded estimates (the first lot $150: 5 %, the others the median $30: 1 %; 84.6 % at the reset: 5 + 1 > 90 - 84.6
    leaves the first only)."""
    from test_wave_plan import EDGES, NODES, SCHEMA
    store = tmp_path / "root" / "notes" / "graph"
    (store / "nodes").mkdir(parents=True)
    (store / "edges").mkdir()
    (store / "schema.yaml").write_text(SCHEMA, encoding="utf-8")
    (store / "edges.yaml").write_text("", encoding="utf-8")
    nodes = NODES.replace('changes/wi-lots.md",\n   props: {priority: P3}}',
                          'changes/wi-lots.md",\n   props: {priority: P3, cost_estimate: "2026-11-04 usd=150.00"}}')
    assert nodes != NODES
    (store / "nodes" / "work.yaml").write_text(nodes, encoding="utf-8", newline="\n")
    (store / "edges" / "work.yaml").write_text(EDGES, encoding="utf-8", newline="\n")
    monkeypatch.setattr(governor, "_now", lambda: NOW)
    monkeypatch.delenv("CLAUDE_CODE_HOST_SESSION_ID", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", M_CLI)
    forecast(wave, 60, pct_h=0.2)
    q = json.loads((wave / "usage" / "quota.json").read_text(encoding="utf-8"))
    q["live"] = {"median_session_usd": 30.0}
    (wave / "usage" / "quota.json").write_text(json.dumps(q), encoding="utf-8")
    ada({"wave_quota": {"ask_over_pct": 90, "max_streams": 2}})
    wp = lots.plan(store, ada.lab, wave="1.1.0", at_once=5)
    assert wp.caps["max_streams"] == 2 and wp.caps["at_once"] == 2 and all(len(r) <= 2 for r in wp.rounds)
    assert wp.lots[0].items == ["wi-lots"] and lots.lot_usd(wp.lots[0], wp.units) == 150.0
    assert wp.caps["streams"]["by_quota"] == 1 and wp.caps["now"] == 1
    text = "\n".join(lots.render(wp))
    assert ", the streams of one master (2, usage.guard.wave_quota)" in text
    assert "Streams that fit now: 1 (by the quota 1: the week 60 % now, 85 % at its reset" in text
    assert "by the streams 2: 0 live of 2; usage.guard.wave_quota)" in text
    assert "  streams that fit now: 1 " in "\n".join(lots.summary(wp))
    ada()
    wp = lots.plan(store, ada.lab, wave="1.1.0", at_once=5)
    assert wp.caps["max_streams"] is None and wp.caps["streams"] is None and "Streams that fit" not in "\n".join(
        lots.render(wp))
