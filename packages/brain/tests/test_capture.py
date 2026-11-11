import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import run_git

import brain
from brain import capture, schema

PLUGIN = Path(brain.__file__).resolve().parent / "adapters" / "claude"  # its hooks/ folder is a plugin's


def _run(event, payload, *extra):
    return capture.main([event, *extra], stdin=io.StringIO(json.dumps(payload)))


def _ledger(home, name):
    return [json.loads(line) for f in sorted((home / "ledger").glob(f"{name}-*.jsonl"))
            for line in f.read_text(encoding="utf-8").splitlines()]


def test_session_start_and_end_events(brain_home, capsys):
    assert _run("session-start", {"session_id": "s-1", "source": "startup", "model": "claude-opus-5-5",
                                  "cwd": "/w", "transcript_path": "/x/s-1.jsonl"}) == 0
    assert _run("session-end", {"session_id": "s-1", "reason": "other"}) == 0
    events = _ledger(brain_home, "events")
    assert [e["event"] for e in events] == ["session_start", "session_end"]
    assert events[0]["model"] == "claude-opus-5-5" and events[1]["reason"] == "other"
    assert capsys.readouterr().out == ""  # SessionStart stdout would enter Claude's context


def test_question_tool_becomes_an_answered_ddr(brain_home, fixture_transcript):
    q = {"question": "Which command shape?", "header": "Command", "multiSelect": True,
         "options": [{"label": "atlas", "description": "a new name"},
                     {"label": "brain (Recommended)", "description": "one command"},
                     {"label": "one per project", "description": "demo, brain"}]}
    payload = {"session_id": "s-1", "transcript_path": str(fixture_transcript), "tool_name": "AskUserQuestion",
               "tool_use_id": "toolu_01ABCDEF", "tool_input": {"questions": [q]},
               "tool_response": {"questions": [q], "answers": {q["question"]: "brain (Recommended), atlas"}}}
    assert _run("post-tool-use", payload) == 0
    (ddr,) = _ledger(brain_home, "ddr")
    assert schema.check("ddr", ddr)[0] == []
    assert [o["label"] for o in ddr["options"]] == ["brain", "atlas", "one per project"]
    assert ddr["recommendation"]["option"] == "brain"
    assert ddr["status"] == "answered" and ddr["answer"]["choices"] == ["brain", "atlas"]
    assert ddr["read"]["session"] == "s-1" and ddr["asked"]["model"] == "claude-sonnet-5-5"
    (ar,) = _ledger(brain_home, "ar")
    assert ar["kind"] == "ddr" and ar["ddr"] == ddr["id"]
    _run("post-tool-use", payload)  # the same call twice: recorded once
    assert len(_ledger(brain_home, "ddr")) == 1


def test_git_commit_hook(brain_home, git_repo, fixture_transcript):
    (git_repo / "f.txt").write_text("x", encoding="utf-8")
    run_git(git_repo, "add", "f.txt")
    run_git(git_repo, "commit", "-qm", "Add f")
    payload = {"session_id": "s-2", "transcript_path": str(fixture_transcript), "cwd": str(git_repo),
               "permission_mode": "auto", "effort": {"level": "high"}, "tool_name": "Bash",
               "tool_input": {"command": "git commit -qm 'Add f'"}, "tool_response": {"stdout": "", "stderr": ""},
               "tool_use_id": "toolu_x"}
    _run("post-tool-use", payload, "git")
    _run("post-tool-use", payload, "gh")  # the gh hook ignores git operations
    (ar,) = _ledger(brain_home, "ar")
    assert ar["kind"] == "commit" and ar["subject"] == "Add f"
    assert ar["session"] == {"id": "s-2", "tool": "claude-code", "model": "claude-sonnet-5-5", "version": "2.1.310",
                             "effort": "high", "permission_mode": "auto", "surface": "cli"}


def test_stop_writes_the_session_snapshot(brain_home, fixture_transcript, tmp_path):
    t = tmp_path / "s.jsonl"
    lines = fixture_transcript.read_text(encoding="utf-8").splitlines(keepends=True)
    t.write_bytes("".join(lines[:6]).encode())
    payload = {"session_id": "aaaabbbb-1111-2222-3333-444455556666", "transcript_path": str(t)}
    _run("stop", payload)
    t.write_bytes("".join(lines).encode())
    _run("stop", payload)
    sr = json.loads((brain_home / "sessions" / f"{payload['session_id']}.json").read_text(encoding="utf-8"))
    assert schema.check("sr", sr)[0] == []
    assert sr["tokens"]["messages"] == 3 and sr["status"] == "open"


def test_failures_never_break_the_session(brain_home, capsys):
    assert capture.main(["post-tool-use"], stdin=io.StringIO("{not json")) == 0
    assert "post-tool-use" in (brain_home / "ledger" / "errors.log").read_text(encoding="utf-8")
    assert capsys.readouterr().out == ""


def test_switch_off(brain_home, monkeypatch):
    monkeypatch.setenv("BRAIN_CAPTURE", "0")
    _run("session-start", {"session_id": "s"})
    assert not (brain_home / "ledger").exists()


def _bash():
    """Git Bash on Windows (what Claude Code runs hooks with), not WSL's System32 bash.exe."""
    found = shutil.which("bash")
    if found and "system32" not in found.lower():
        return found
    git = shutil.which("git")
    for cand in ([Path(git).parents[1] / "bin" / "bash.exe", Path(git).parents[1] / "usr" / "bin" / "bash.exe"]
                 if git else []):
        if cand.exists():
            return str(cand)
    return None


def test_hook_script_end_to_end(brain_home, tmp_path):
    bash = _bash()
    if not bash:
        pytest.skip("no bash")
    payload = json.dumps({"session_id": "s-9", "source": "startup"})
    env = dict(os.environ, BRAIN_HOME=str(brain_home), BRAIN_PYTHON=sys.executable)
    out = subprocess.run([bash, str(PLUGIN / "hooks" / "capture.sh"), "session-start"], input=payload,
                         capture_output=True, text=True, env=env, timeout=60)
    assert out.returncode == 0 and out.stdout == ""
    assert _ledger(brain_home, "events")[0]["session_id"] == "s-9"


def test_hooks_json_declares_the_capture_hooks():
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    assert set(hooks) == {"SessionStart", "UserPromptSubmit", "SubagentStart", "PreToolUse", "PostToolUse", "Stop",
                          "SessionEnd"}
    ifs = [h.get("if") for m in hooks["PostToolUse"] for h in m["hooks"]]
    assert ifs == ["Bash(git *)", "Bash(gh *)", "PowerShell(git *)", "PowerShell(gh *)", None, None, None]  # the
    # question tool, the plan tools (test_plan), then the budget watch (test_budget)
    for event, matchers in hooks.items():
        for m in matchers:
            for h in m["hooks"]:
                if "capture.sh" in h["command"]:
                    assert h.get("async") or event == "SessionEnd", event


# --- the external contracts (wi-brain-external-contracts) ----------------------------------------------------------

CLAUDE = Path(__file__).parent / "fixtures" / "claude"


@pytest.mark.parametrize("event", sorted(capture.PAYLOAD_KEYS))
def test_each_hook_payload_fixture_is_what_capture_reads(event):
    payload = json.loads((CLAUDE / "hooks" / f"{event}.json").read_text(encoding="utf-8"))
    assert capture.payload_contract(event, payload) == []
    assert capture.payload_contract(event, {**payload, "new_key": 1}) == ["unknown new_key"]
    required = sorted(capture.PAYLOAD_KEYS[event][0])
    assert capture.payload_contract(event, {k: v for k, v in payload.items() if k != required[0]}) == \
        [f"missing {required[0]}"]


def _contracts(brain_home):
    return json.loads((brain_home / "ledger" / capture.CONTRACTS).read_text(encoding="utf-8"))


def test_an_unknown_key_is_counted_logged_once_and_shown_once(brain_home):
    """Tolerant reading made loud: the capture goes on, the key is counted, errors.log says it at its first sighting
    and the SessionStart health names it once."""
    payload = json.loads((CLAUDE / "hooks" / "session-end.json").read_text(encoding="utf-8"))
    payload["exit_detail"] = "x"
    for _ in range(2):
        assert capture.main(["session-end"], stdin=io.BytesIO(json.dumps(payload).encode())) == 0
    entry = _contracts(brain_home)["keys"]["hook session-end: unknown exit_detail"]
    assert entry["count"] == 2 and entry["shown"] is False
    errors = (brain_home / "ledger" / "errors.log").read_text(encoding="utf-8")
    assert errors.count("contract: Claude Code's format changed: hook session-end: unknown exit_detail") == 1
    (line,) = capture.contract_notes()
    assert "hook session-end: unknown exit_detail (2x)" in line and "Nothing is refused" in line
    assert capture.contract_notes() == [] and _contracts(brain_home)["keys"]["hook session-end: unknown exit_detail"][
        "shown"] is True
    events = (brain_home / "ledger").glob("events-*.jsonl")
    assert any('"session_end"' in f.read_text(encoding="utf-8") for f in events)   # captured all the same


def test_a_newer_brains_ledger_is_left_as_it_is(brain_home):
    f = brain_home / "ledger" / capture.CONTRACTS
    f.parent.mkdir(parents=True)
    f.write_text('{"v": 2, "keys": {"x": {"shown": false}}}', encoding="utf-8")
    assert capture.note_contract("hook stop", ["unknown y"]) == [] and capture.contract_notes() == []
    assert json.loads(f.read_text(encoding="utf-8")) == {"v": 2, "keys": {"x": {"shown": False}}}


def test_the_transcript_fixture_reads_clean_and_a_new_type_is_counted(tmp_path, brain_home):
    from brain import transcript
    stats = transcript.SessionStats()
    stats.feed_file(CLAUDE / "transcript.jsonl")
    assert stats.contract == {} and stats.tokens["output"] == 20 and stats.title == "Add the demo"
    t = tmp_path / "s.jsonl"
    lines = (CLAUDE / "transcript.jsonl").read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[6])
    del rec["message"]["usage"]
    t.write_text("\n".join(lines + ['{"type": "hologram", "sessionId": "s"}', json.dumps(rec)]) + "\n",
                 encoding="utf-8")
    stats = transcript.SessionStats()
    stats.feed_file(t)
    assert stats.contract == {"unknown type hologram": 1, "missing message.usage": 1}
    assert "_contract" not in stats.to_state() and "contract" not in stats.to_state()
    payload = {"session_id": "s-1", "transcript_path": str(t), "cwd": str(tmp_path)}
    assert capture.main(["stop"], stdin=io.BytesIO(json.dumps(payload).encode())) == 0
    assert _contracts(brain_home)["keys"]["transcript: unknown type hologram"]["count"] == 1
