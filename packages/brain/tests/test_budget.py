"""wi-brain-budget-watch: the budget watch hook (brain.budget, hooks/budget.sh; COST-1: warn once at 80 % and once
at 100 % of the brief's context budget or the item's recorded estimate, the session decides, nothing blocks)."""

import io
import json
import os
import subprocess
import sys
import time

import pytest
from test_capture import PLUGIN, _bash

from brain import budget, transcript, usage

OPUS = "claude-opus-5-5"
SIDE = "Background (from the session that started this one):\nThe Brain.\n\nTask:\n"


def _asst(mid, ctx, out=100):
    return {"type": "assistant", "timestamp": "2026-11-02T10:00:00Z", "sessionId": "s-1",
            "message": {"id": mid, "model": OPUS, "content": [{"type": "tool_use", "id": f"t-{mid}", "name": "Read",
                                                               "input": {}}],
                        "usage": {"input_tokens": 10, "output_tokens": out, "cache_read_input_tokens": ctx - 10,
                                  "cache_creation_input_tokens": 0}}}


def _prompt(text):
    return {"type": "user", "timestamp": "2026-11-02T10:00:00Z", "sessionId": "s-1", "message": {"content": text}}


def _append(path, *records):
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.writelines(json.dumps(r) + "\n" for r in records)


@pytest.fixture
def session(tmp_path):
    t = tmp_path / "proj" / "s-1.jsonl"
    t.parent.mkdir(parents=True)
    _append(t, _prompt(SIDE + "Build wi-a.\n**Task class:** standard. **Context budget:** 400k.\n"))
    return t


def _run(t, cwd=None, **extra):
    out = io.StringIO()
    sys_stdout, sys.stdout = sys.stdout, out
    try:
        budget.hook_main([], stdin=io.StringIO(json.dumps({"session_id": "s-1", "transcript_path": str(t),
                                                           "cwd": str(cwd or t.parent), "hook_event_name": "PostToolUse",
                                                           **extra})))
    finally:
        sys.stdout = sys_stdout
    text = out.getvalue()
    return json.loads(text)["hookSpecificOutput"]["additionalContext"] if text else ""


def test_brief_budget_with_markdown_markers_is_read():
    """« **Context budget:** 600k » (a Markdown brief) is the budget, in the SR and the ledger as in the watch."""
    for text, n in (("**Context budget:** 600k.", 600_000), ("Context budget: 1M", 1_000_000),
                    ("context budget = 400k", 400_000), ("context budget 0.8M", 800_000)):
        m = transcript._BUDGET_RE.search(text)
        assert m and int(float(m.group(1)) * (1e3 if m.group(2).lower() == "k" else 1e6)) == n, text
    assert usage._BUDGET_RE is transcript._BUDGET_RE


def test_context_warned_once_at_80_and_once_at_100(session):
    _append(session, _asst("m1", 100_000))
    assert _run(session) == ""
    state = json.loads((budget.state_dir() / "s-1.json").read_text(encoding="utf-8"))
    assert (state["budget"], state["ctx"]) == (400_000, 100_000) and state["items"] == ["wi-a"]
    assert budget.next_check(state) == 120  # 25 %: two minutes
    _append(session, _asst("m2", 330_000))
    note = _run(session)
    assert "330k tokens, 82 % of its brief's context budget (400k)" in note
    assert "checkpoint now: commit your work" in note and "nothing stops or blocks" in note
    _append(session, _asst("m3", 350_000))
    assert _run(session) == ""  # once
    _append(session, _asst("m4", 420_000))
    note = _run(session)
    assert "105 % of its brief's context budget" in note and "expanded to the next step" in note
    _append(session, _asst("m5", 500_000))
    assert _run(session) == ""
    state = json.loads((budget.state_dir() / "s-1.json").read_text(encoding="utf-8"))
    assert state["warned"]["context"] == [80, 100]
    assert budget.next_check(state) == budget.IDLE_S  # wi-a may still get an estimate


def test_a_session_started_past_the_budget_gets_one_notice(session):
    _append(session, _asst("m1", 450_000))
    note = _run(session)
    assert note.count("Budget watch") == 1 and "past the budget" in note.lower()
    assert json.loads((budget.state_dir() / "s-1.json").read_text(encoding="utf-8"))["warned"]["context"] == [80, 100]


def test_a_message_split_in_records_is_priced_once_and_subagents_count(session):
    _append(session, _asst("m1", 1000, out=1000), _asst("m1", 1000, out=1000))
    sub = session.with_suffix("") / "subagents" / "agent-x.jsonl"
    sub.parent.mkdir(parents=True)
    _append(sub, _asst("a1", 50_000, out=1000))
    _run(session)
    state = json.loads((budget.state_dir() / "s-1.json").read_text(encoding="utf-8"))
    one = usage.message_cost(transcript._usage_tokens(_asst("m1", 1000, out=1000)["message"]["usage"]), OPUS)
    sub_cost = usage.message_cost(transcript._usage_tokens(_asst("a1", 50_000, out=1000)["message"]["usage"]), OPUS)
    assert state["cost"] == pytest.approx(one + sub_cost)
    assert state["ctx"] == 1000  # the subagent's context is not the session's


def test_item_cost_against_its_recorded_estimate(git_repo, tmp_path, brain_home):
    work = git_repo / "notes" / "graph" / "nodes" / "work.yaml"
    work.write_text(work.read_text(encoding="utf-8").replace(
        "props: {priority: P1}", 'props: {priority: P1, cost_estimate: "2026-11-02 class=standard usd=2.00 '
                                 '[1.00-3.00]"}'), encoding="utf-8")
    (git_repo / "notes" / "graph" / "schema.yaml").write_text("node_types: [WorkItem]\n", encoding="utf-8")
    # an earlier session that served wi-a (its first brief item) spent $0.50 on it
    usage.save({"old.jsonl": {"session_id": "s-0", "cost": 0.5, "closed": [], "title_items": [],
                              "brief": {"side": True, "items": ["wi-a", "wi-b"]}}})
    t = tmp_path / "s-1.jsonl"
    _append(t, _prompt("Finish wi-a and look at wi-b (done elsewhere)."))
    _append(t, _asst("m1", 10_000, out=40_000))  # $0.80 + cache: below 80 % of $2 with the $0.50 before
    assert _run(t, git_repo) == ""
    state = json.loads((budget.state_dir() / "s-1.json").read_text(encoding="utf-8"))
    assert state["estimates"] == {"wi-a": 2.0} and state["prior_usd"] == 0.5 and state["budget"] is None
    _append(t, _asst("m2", 10_000, out=20_000))  # $0.40 more: 85 %
    note = _run(t, git_repo)
    assert "wi-a has cost $1.70 at API prices so far (this session $1.20, earlier sessions $0.50)" in note
    assert "85 % of the recorded estimate ($2.00, props.cost_estimate)" in note and "checkpoint now" in note


def test_a_subagents_tool_call_counts_but_is_not_told(session):
    _append(session, _asst("m1", 390_000))
    assert _run(session, agent_id="a-1") == ""
    assert json.loads((budget.state_dir() / "s-1.json").read_text(encoding="utf-8"))["warned"]["context"] == [80]


def test_no_budget_no_items_stops_watching_after_the_brief(tmp_path):
    t = tmp_path / "s-1.jsonl"
    _append(t, _prompt("hello"), _asst("m1", 900_000))
    assert _run(t) == ""
    state = json.loads((budget.state_dir() / "s-1.json").read_text(encoding="utf-8"))
    assert budget.next_check(state) == budget.IDLE_S  # a later prompt may still give a budget
    state["texts"] = budget.BRIEF_TEXTS
    assert budget.next_check(state) == budget.DONE_S


def test_a_broken_payload_never_fails(capsys):
    assert budget.hook_main([], stdin=io.StringIO("not json")) == 0
    assert capsys.readouterr().out == ""
    assert budget.hook_main([], stdin=io.StringIO(json.dumps({"session_id": "../x", "transcript_path": "t"}))) == 0


def test_hook_script_fast_path(session, tmp_path, brain_home):
    """budget.sh starts no Python while the mark is newer than the transcript; Python sets the mark ahead."""
    bash = _bash()
    if not bash:
        pytest.skip("no bash")
    _append(session, _asst("m1", 100_000))
    payload = json.dumps({"session_id": "s-1", "transcript_path": str(session), "cwd": str(tmp_path)})
    ran = tmp_path / "python-ran"
    fake = tmp_path / "fake-python"
    fake.write_text(f"#!/usr/bin/env bash\necho ran >> '{ran.as_posix()}'\n", encoding="utf-8", newline="\n")
    fake.chmod(0o755)

    def run(python, **env_extra):
        env = dict(os.environ, BRAIN_HOME=str(brain_home), BRAIN_PYTHON=python, CLAUDE_PLUGIN_ROOT=str(PLUGIN),
                   **env_extra)
        out = subprocess.run([bash, str(PLUGIN / "hooks" / "budget.sh")], input=payload, capture_output=True,
                             text=True, env=env, timeout=60)
        assert out.returncode == 0 and out.stderr == ""
        return out.stdout

    def runs():
        return ran.read_text().count("ran") if ran.exists() else 0

    assert run(fake.as_posix()) == "" and runs() == 1  # no mark: Python decides
    assert run(sys.executable) == ""  # the real one: sets the mark two minutes ahead
    mark = brain_home / "budget" / "s-1.mark"
    assert mark.stat().st_mtime > time.time() + 60
    assert run(fake.as_posix()) == "" and runs() == 1  # fast path
    due = session.stat().st_mtime - 10
    os.utime(mark, (due, due))  # the check is due
    assert run(fake.as_posix()) == "" and runs() == 2
    assert run(fake.as_posix(), BRAIN_BUDGET_WATCH="0") == "" and runs() == 2  # turned off


def test_hooks_json_runs_the_watch_after_every_tool():
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    (entry,) = [(m, h) for m in hooks["PostToolUse"] for h in m["hooks"] if "budget.sh" in h["command"]]
    matcher, hook = entry
    assert "matcher" not in matcher and not hook.get("async") and hook["timeout"] <= 10
