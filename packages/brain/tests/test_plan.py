"""wi-brain-tui-cockpit: a session's plan (its steps n/m) from the plan tools, by the hook and from a transcript."""

import io
import json
from pathlib import Path

import brain
from brain import capture, paths, plan

PLUGIN = Path(brain.__file__).resolve().parent / "adapters" / "claude"  # its hooks/ folder is a plugin's
UPDATE, WRAP_UP = "mcp__ccd_turn__update_plan", "mcp__ccd_turn__wrap_up"
ITEMS = [{"content": "Read the spec", "status": "in_progress"}, {"content": "Write the code", "status": "pending"},
         {"content": "Test it", "status": "pending"}]


def _statuses(steps):
    return [s["status"][0] for s in steps]  # p, i, c


def test_update_plan_items_advance_done_and_start():
    steps = plan.apply([], UPDATE, {"items": ITEMS, "scope": "first_task"})
    assert _statuses(steps) == ["i", "p", "p"] and steps[0]["content"] == "Read the spec"
    steps = plan.apply(steps, UPDATE, {"advance": True})
    assert _statuses(steps) == ["c", "i", "p"]
    assert plan.label(steps) == "2/3 Write the code"
    steps = plan.apply(steps, UPDATE, {"done": [2], "start": 3})
    assert _statuses(steps) == ["c", "c", "i"]
    steps = plan.apply(steps, UPDATE, {"advance": True})  # the last step: none left to start
    assert _statuses(steps) == ["c", "c", "c"] and plan.label(steps) == "3/3 done"


def test_start_out_of_order_puts_the_step_in_progress_back_to_pending():
    steps = plan.apply([], UPDATE, {"items": ITEMS})
    steps = plan.apply(steps, UPDATE, {"done": [2], "start": 3})
    assert _statuses(steps) == ["p", "c", "i"]
    assert plan.progress(steps) == {"total": 3, "done": 1, "step": 3, "current": "Test it"}


def test_wrap_up_checks_the_list_off_and_todowrite_replaces_it():
    steps = plan.apply(plan.apply([], UPDATE, {"items": ITEMS}), WRAP_UP, {"recap": "done"})
    assert _statuses(steps) == ["c", "c", "c"]
    todos = [{"content": "A", "status": "completed", "activeForm": "Doing A"}, {"content": "B", "status": "weird"}]
    assert _statuses(plan.apply(steps, "TodoWrite", {"todos": todos})) == ["c", "p"]


def test_what_is_not_a_plan_call_changes_nothing():
    steps = plan.apply([], UPDATE, {"items": ITEMS})
    assert plan.apply(steps, "Bash", {"command": "ls"}) is None
    assert plan.apply(steps, UPDATE, "not a dict") is None
    assert plan.apply(steps, UPDATE, {"done": [True, 0, 9, "2"], "start": True}) == steps  # no step number in it
    assert plan.apply(steps, UPDATE, {"done": 2}) == steps
    assert plan.apply([], UPDATE, {"items": [{"content": "  "}, "x", {"content": "ok"}]}) == [
        {"content": "ok", "status": "pending"}]
    assert plan.label([]) == "" and plan.label(plan.apply(steps, UPDATE, {"done": [1]})) == "1/3"


def _hook(payload):
    payload = {"tool_response": {}, **payload}   # what every real PostToolUse payload carries (capture.PAYLOAD_KEYS)
    return capture.main(["post-tool-use"], stdin=io.StringIO(json.dumps(payload)))


def test_the_hook_keeps_one_plan_file_per_session(brain_home):
    assert _hook({"session_id": "s-1", "tool_name": UPDATE, "tool_input": {"items": ITEMS}}) == 0
    assert _hook({"session_id": "s-1", "tool_name": UPDATE, "tool_input": {"advance": True}}) == 0
    assert _hook({"session_id": "s-2", "tool_name": "TodoWrite",
                  "tool_input": {"todos": [{"content": "x", "status": "in_progress"}]}}) == 0
    one = plan.read("s-1")
    assert one["tool"] == UPDATE and plan.label(one["steps"]) == "2/3 Write the code"
    assert plan.label(plan.read("s-2")["steps"]) == "1/1 x"
    # brain.stateio: the second write of s-1 backed up the first beside it
    assert sorted(f.name for f in paths.sessions_dir().iterdir()) == ["s-1.plan.json", "s-1.plan.json.bak",
                                                                     "s-2.plan.json"]
    assert not (brain_home / "ledger" / "errors.log").exists()
    assert plan.read("s-3") is None


def test_the_hook_drops_a_secret_from_a_step(brain_home):
    secret = "ghp_" + "a1B2" * 9
    _hook({"session_id": "s-1", "tool_name": UPDATE, "tool_input": {"items": [{"content": f"use {secret}"}]}})
    assert secret not in plan.plan_file("s-1").read_text(encoding="utf-8")


def _call(i, name, inp):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": f"toolu_{i}", "name": name,
                                                          "input": inp}]}}


def test_replay_reads_a_transcript_incrementally(tmp_path):
    t = tmp_path / "s.jsonl"
    lines = [{"type": "user", "message": {"content": "go"}}, _call(1, UPDATE, {"items": ITEMS}),
             _call(2, "Bash", {"command": f"echo {UPDATE}"}), _call(3, UPDATE, {"advance": True})]
    t.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    r = plan.Replay()
    assert plan.label(r.steps(t)) == "2/3 Write the code"
    with t.open("a", encoding="utf-8") as f:
        f.write(json.dumps(_call(3, UPDATE, {"advance": True})) + "\n")  # the same call written twice
        f.write(json.dumps(_call(4, UPDATE, {"advance": True})) + "\n")
        f.write(json.dumps(_call(5, UPDATE, {"advance": True}))[:30])  # partial: read next time
    assert plan.label(r.steps(t)) == "3/3 Test it"
    t.write_text(json.dumps(_call(9, "TodoWrite", {"todos": [{"content": "new", "status": "pending"}]})) + "\n",
                 encoding="utf-8")  # rewritten, shorter: read again from the start
    assert plan.label(r.steps(t)) == "0/1"
    assert r.steps(tmp_path / "gone.jsonl") == []


def test_hooks_json_captures_the_plan_tools():
    post = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]["PostToolUse"]
    (m,) = [m for m in post if "update_plan" in m.get("matcher", "")]  # the budget watch has no matcher
    assert set(m["matcher"].split("|")) == set(plan.PLAN_TOOLS)
    (h,) = m["hooks"]
    assert h["async"] and h["command"].endswith("capture.sh\" post-tool-use")
