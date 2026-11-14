"""wi-brain-token-ledger: the token ledger (brain.usage): prices, commands, phases, the transcript scan, the ledger."""

import json
from datetime import datetime, timezone

import pytest

from brain import usage

OPUS = "claude-opus-5-5"


@pytest.fixture
def projects_dir(tmp_path, monkeypatch):
    d = tmp_path / "claude" / "projects"
    d.mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    return d


def _usage(out=100, read=0, write=0, inp=10):
    return {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": read,
            "cache_creation_input_tokens": write, "cache_creation": {"ephemeral_1h_input_tokens": write}}


def _asst(ts, mid, blocks, **u):
    return {"type": "assistant", "timestamp": ts, "sessionId": "s", "cwd": "/work/brain", "gitBranch": "feat",
            "message": {"id": mid, "model": OPUS, "content": blocks, "usage": _usage(**u)}}


def _tool(tid, name, **inp):
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


def _result(ts, tid, text="ok", error=False):
    return {"type": "user", "timestamp": ts, "sessionId": "s", "cwd": "/work/brain",
            "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "content": text, "is_error": error}]}}


def _prompt(ts, text):
    return {"type": "user", "timestamp": ts, "sessionId": "s", "cwd": "/work/brain", "message": {"content": text}}


def _write(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [{**r, "sessionId": path.stem} if "sessionId" in r else r for r in records]
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


BRIEF = ("Background (from the session that started this one):\nThe repo is the Brain.\n\nTask:\nBuild wi-a, the "
         "ledger, from the transcripts.\n**Task class:** standard. **Context budget:** 400k.\n")


def _child(projects_dir):
    t = "2026-11-02T10:00:"
    return _write(projects_dir / "proj" / "child.jsonl", [
        _prompt(f"{t}00Z", BRIEF),
        {"type": "custom-title", "customTitle": "Ledger (wi-a)", "sessionId": "s"},
        # one API message written as two records (a text block, then a tool call): counted once
        _asst(f"{t}05Z", "m1", [{"type": "text", "text": "reading"}], out=100, read=1000, write=0),
        _asst(f"{t}05Z", "m1", [_tool("t1", "Read", file_path="a.py")], out=100, read=1000, write=0),
        _result(f"{t}06Z", "t1", "x" * 50),
        _asst(f"{t}10Z", "m2", [_tool("t2", "Edit", file_path="a.py")], out=200, read=1100, write=100),
        _result(f"{t}11Z", "t2"),
        _asst(f"{t}20Z", "m3", [_tool("t3", "Bash", command="python -m pytest -q")], out=50, read=1200),
        _result(f"{t}21Z", "t3", "1 failed", error=True),
        _asst(f"{t}25Z", "m4", [_tool("t4", "Bash", command="python -m pytest -q")], out=50, read=1200),
        _result(f"{t}26Z", "t4", "1 failed", error=True),
        _asst(f"{t}30Z", "m5", [_tool("t5", "Bash", command="python -m pytest -q")], out=50, read=1200),
        _result(f"{t}31Z", "t5", "1 failed", error=True),
        _asst(f"{t}35Z", "m6", [_tool("t6", "Bash", command="git fetch origin && git merge origin/main")], out=50),
        _result(f"{t}36Z", "t6", "CONFLICT (content): Merge conflict in a.py"),
        # back after a long wait: the context is written again (a reload)
        _prompt("2026-11-02T12:00:00Z", "go on"),
        _asst("2026-11-02T12:00:05Z", "m7", [_tool("t7", "Bash", command="git add -A")], out=10, read=0,
              write=30_000),
        _result("2026-11-02T12:00:06Z", "t7"),
        _asst("2026-11-02T12:00:10Z", "m8", [_tool("t8", "Bash", command="git commit -m 'x | y'")], out=10,
              read=30_000),
        _result("2026-11-02T12:00:11Z", "t8"),
        _asst("2026-11-02T12:00:15Z", "m9", [_tool("t9", "Bash", command="git push origin feat && brain item close "
                                                                          "wi-a --pr \"r #7\"")], out=10, read=30_000),
        _result("2026-11-02T12:00:16Z", "t9"),
        _asst("2026-11-02T12:00:20Z", "m10", [_tool("t10", "mcp__ccd_turn__update_plan",
                                                     items=[{"content": "a"}, {"content": "b"}])], out=5, read=30_000),
        _result("2026-11-02T12:00:21Z", "t10"),
        {"type": "pr-link", "prRepository": "acme/engine", "prNumber": 7, "prUrl": "u", "sessionId": "s"},
    ])


def test_prices_reproduce_claude_codes_cost():
    # a session's cost-state of 2026-11-02 (claude-opus-5-5): totalCostUSD 14.0637984
    part = {"input": 134, "output": 133748, "cache_read": 25209792, "cache_write": 793293,
            "cache_write_1h": 793293, "cache_write_5m": 0}
    assert usage.message_cost(part, OPUS) == pytest.approx(14.0637984)
    assert usage.message_cost(part, OPUS, "fast") == pytest.approx(2 * 14.0637984)
    assert usage.message_cost({"output": 1_000_000}, "claude-opus-9-9") == pytest.approx(20.0)  # the family's
    assert usage.message_cost({"output": 1}, "gpt-x") is None
    assert usage.message_cost({"input": 200_000}, "claude-haiku-5-5") == pytest.approx(0.1)  # above 100k: 0.50
    assert usage.message_cost({"cache_write": 1_000_000}, OPUS) == pytest.approx(5.0)  # no TTL split: 5 min
    assert usage.tokens_cost({OPUS: {"output": 1_000_000}, "x": {"output": 5}}) == pytest.approx(20.0)


def test_plans():
    assert usage.plan_of("2026-11-02") == "Ultra" and usage.plan_of("2026-11-01") == "Pro"
    plans = usage.plans_from({"plans": [{"since": "", "plan": "Pro"}, {"since": "2026-12-01", "plan": "Max"}]})
    assert usage.plan_of("2026-12-05", plans) == "Max" and usage.plan_of("2026-11-05", plans) == "Pro"


@pytest.mark.parametrize("cmd, keys", [
    ('grep -n "^###\\|x" f | head -3', ["grep", "head"]),
    ("cd E:/x && git -C E:/y status && git push origin b", ["git status", "git push"]),
    ("python -m pytest -q 2>&1 | tail -3", ["python -m pytest", "tail"]),
    ('gh pr create --title "a | b" --body x', ["gh pr create"]),
    ('brain item close wi-x --pr "r #1"; brain refresh', ["brain item close", "brain refresh"]),
    ("cat > f.py <<EOF\nimport x | y\nEOF", ["cat"]),
    ('"C:/v/Scripts/python.exe" -m pytest', ["python -m pytest"]),
    ("FOO=1 npm run build", ["npm run"]),
    ("for f in a b; do wc -l $f; done", ["wc"]),
])
def test_commands_keep_program_and_subcommand_only(cmd, keys):
    assert usage.commands(cmd) == keys


def test_phases_strongest_first():
    bash = lambda c: {"name": "Bash", "input": {"command": c}}  # noqa: E731
    assert usage.phase_of([bash("git status"), bash("git rebase origin/main")]) == "merge"
    assert usage.phase_of([bash("gh pr diff 3"), {"name": "Edit"}]) == "review"
    assert usage.phase_of([bash("python -m pytest"), {"name": "Edit"}]) == "test"
    assert usage.phase_of([{"name": "Write"}, bash("git commit -m x")]) == "build"
    assert usage.phase_of([bash("git push"), {"name": "Read"}]) == "ship"
    assert usage.phase_of([{"name": "Skill", "input": {"skill": "code-review"}}]) == "review"
    assert usage.phase_of([{"name": "Agent", "input": {"subagent_type": "Explore", "description": "find"}}]) == \
        "explore"
    assert usage.phase_of([{"name": "AskUserQuestion"}]) == "wait"
    assert usage.phase_of([]) == ""


def test_scan_a_sub_session(projects_dir):
    row = usage.scan(_child(projects_dir))
    assert row["title"] == "Ledger (wi-a)" and row["title_items"] == ["wi-a"] and row["closed"] == ["wi-a"]
    assert row["brief"]["side"] and row["brief"]["class"] == "standard" and row["brief"]["budget"] == 400_000
    assert row["brief"]["items"] == ["wi-a"] and row["kind"] == "build"
    assert row["prs"] == ["acme/engine#7"]
    assert row["tokens"]["messages"] == 10 and row["tokens"]["output"] == 535  # m1 once
    assert row["cost"] == pytest.approx(sum(row["by_model"][OPUS][k] for k in ["cost"]))
    assert row["days"] == {"2026-11-02": pytest.approx(row["days"]["2026-11-02"])}
    ph = row["phases"]
    assert ph["explore"]["messages"] == 1 and ph["build"]["messages"] == 1 and ph["test"]["messages"] == 3
    assert ph["merge"]["messages"] == 1 and ph["ship"]["messages"] == 4
    assert ph["reload"]["cost"] == pytest.approx(30_000 * 8 / 1e6)  # m7's cache written again
    assert sum(p.get("cost", 0) for p in ph.values()) == pytest.approx(row["cost"], abs=1e-3)
    sig = row["signals"]
    assert sig["thrash"] == 1 and sig["max_fail_streak"] == 3 and sig["conflicts"] == 1 and sig["merges"] == 1
    assert sig["reloads"] == 1 and sig["files_edited"] == 1 and sig["prompts"] == 2 and sig["wait_s"] >= 7000
    assert sig["plan_first"] == sig["plan_last"] == 2
    assert row["commands"]["python -m pytest"]["calls"] == 3 and row["commands"]["python -m pytest"]["fails"] == 3
    assert row["tools"]["Read"]["result_chars"] == 50
    assert row["ngrams"]["git add > git commit > git push"][0] == 1
    assert row["start_cost"]["messages"] == 10
    assert "x | y" not in json.dumps(row)  # never a command's arguments


def _meta(path, **meta):
    path.with_name(f"{path.stem}.meta.json").write_text(json.dumps(meta), encoding="utf-8")


def _one(out):
    """The cost of one Opus message of 10 input tokens and ``out`` output tokens."""
    return usage.message_cost({"input": 10, "output": out, "cache_write_1h": 0}, OPUS)


def _near(x):
    return pytest.approx(x, abs=1e-4)


def _launcher(projects_dir):
    """wi-brain-usage-workflow-agents: a session that ran one plain subagent and a workflow of three agents (one
    labelled only in the run's journal), its transcript carrying a copy of the subagent's message (a sidechain)."""
    main = _write(projects_dir / "proj" / "boss.jsonl", [
        _prompt("2026-11-09T10:00:00Z", "run the wave"),
        _asst("2026-11-09T10:00:05Z", "b1", [_tool("w1", "Workflow")], out=100),
        _asst("2026-11-09T10:00:30Z", "x1", [{"type": "text", "text": "copy"}], out=1000),  # the subagent's copy
        _asst("2026-11-09T12:00:05Z", "b2", [{"type": "text", "text": "done"}], out=100),
    ])
    d = main.with_suffix("") / "subagents"
    plain = _write(d / "agent-aaa.jsonl", [_asst("2026-11-09T10:00:30Z", "x1", [], out=1000)])
    _meta(plain, agentType="general-purpose", description="Review lens: tests", model="sonnet")
    run = d / "workflows" / "wf_run1"
    a1 = _write(run / "agent-w01.jsonl", [_asst("2026-11-09T10:01:00Z", "y1", [], out=2000),
                                         _asst("2026-11-09T10:02:00Z", "y2", [], out=2000)])
    _meta(a1, agentType="workflow-subagent", description="impl:views", workflowPhase="Implement")
    a2 = _write(run / "agent-w02.jsonl", [_asst("2026-11-09T11:00:00Z", "y3", [], out=500)])
    _meta(a2, agentType="workflow-subagent", description="lens:views:correctness", workflowPhase="Review")
    _write(run / "agent-w03.jsonl", [_asst("2026-11-10T00:30:00Z", "y4", [], out=500)])  # no meta: the journal's
    (run / "journal.jsonl").write_text("".join(json.dumps(r) + "\n" for r in [
        {"type": "launched"}, {"type": "started", "agentId": "w03", "label": "fix:views", "phase": "Fix"},
        {"type": "result", "agentId": "w03", "result": {"summary": "not read"}}]), encoding="utf-8")
    return main


def test_scan_reads_subagents_and_workflow_agents_apart(projects_dir):
    row = usage.scan(_launcher(projects_dir))
    one, near = _one, _near
    main, plain = one(100) * 2, one(1000)
    wf = one(2000) * 2 + one(500) * 2
    # the subagent's message is its own, never also its parent's
    assert row["tokens"]["output"] == 200 and row["sub_tokens"]["output"] == 1000 + 5000
    assert row["main_cost"] == near(main) and row["cost"] == near(main + plain + wf)
    assert row["subagents"] == {"general-purpose": {"count": 1, "cost": near(plain)},
                                "workflow-subagent": {"count": 2, "cost": near(one(2000) * 2 + one(500))},
                                "?": {"count": 1, "cost": near(one(500))}}
    ag = row["agents"]
    assert ag["subagents"] == {"Review lens: tests": {"count": 1, "cost": pytest.approx(plain, abs=1e-4),
                                                      "output": 1000, "tokens": 1010}}
    run = ag["workflows"]["wf_run1"]
    assert run["agents"] == 3 and run["cost"] == pytest.approx(wf, abs=1e-4) and run["output"] == 5000
    assert run["start"] == "2026-11-09T10:01:00Z" and run["end"] == "2026-11-10T00:30:00Z"
    assert set(run["days"]) == {"2026-11-09", "2026-11-10"}
    assert {k: v["count"] for k, v in run["phases"].items()} == {"Implement": 1, "Review": 1, "Fix": 1}
    assert set(run["labels"]) == {"impl:views", "lens:views:correctness", "fix:views"}  # fix: from the journal
    # the quota and the governor read the hours: the agents' cost is in them
    assert sum(h["cost"] for h in row["hours"].values()) == pytest.approx(row["cost"], abs=1e-3)
    assert row["hours"]["2026-11-10T00"]["cost"] == pytest.approx(one(500), abs=1e-4)
    assert row["v"] == usage.SCAN_V == 4


def test_a_new_workflow_agent_rescans_its_session(projects_dir):
    main = _launcher(projects_dir)
    rows, n = usage.update()
    assert n == 1 and rows["proj/boss.jsonl"]["agents"]["workflows"]["wf_run1"]["agents"] == 3
    _write(main.with_suffix("") / "subagents" / "workflows" / "wf_run2" / "agent-z01.jsonl",
           [_asst("2026-11-10T09:00:00Z", "z1", [], out=10)])
    rows, n = usage.update()
    assert n == 1 and set(rows["proj/boss.jsonl"]["agents"]["workflows"]) == {"wf_run1", "wf_run2"}
    assert rows["proj/boss.jsonl"]["agents"]["workflows"]["wf_run2"]["labels"] == {
        usage.NO_LABEL: {"count": 1, "cost": pytest.approx(rows["proj/boss.jsonl"]["agents"]["workflows"]["wf_run2"]
                                                            ["cost"])}}


def test_a_label_written_after_the_transcript_rescans_its_session(projects_dir):
    """A workflow agent's meta (or its run's journal) that gains a label once its transcript stopped growing is read:
    the signature holds the agents' label files, not only their transcripts."""
    main = _launcher(projects_dir)
    rows, n = usage.update()
    assert n == 1 and "fix:views" in rows["proj/boss.jsonl"]["agents"]["workflows"]["wf_run1"]["labels"]
    _meta(main.with_suffix("") / "subagents" / "workflows" / "wf_run1" / "agent-w03.jsonl",
          agentType="workflow-subagent", description="fix:views:late", workflowPhase="Fix")
    rows, n = usage.update()
    assert n == 1 and "fix:views:late" in rows["proj/boss.jsonl"]["agents"]["workflows"]["wf_run1"]["labels"]
    with open(main.with_suffix("") / "subagents" / "workflows" / "wf_run1" / "journal.jsonl", "a",
              encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "started", "agentId": "w09", "label": "x", "phase": "Fix"}) + "\n")
    assert usage.update()[1] == 1   # the run's journal grew: scanned again
    assert usage.update()[1] == 0   # nothing changed since


def test_a_message_two_subagents_hold_is_counted_once(projects_dir):
    """A forked agent's transcript copies its parent agent's prefix: the shared message is the first agent's, the
    fork's own messages stay its own."""
    main = _write(projects_dir / "proj" / "fork.jsonl", [_asst("2026-11-09T10:00:00Z", "m1", [], out=100)])
    d = main.with_suffix("") / "subagents"
    _meta(_write(d / "agent-aaa.jsonl", [_asst("2026-11-09T10:01:00Z", "z1", [], out=1000)]),
          agentType="general-purpose", description="first")
    _meta(_write(d / "agent-bbb.jsonl", [_asst("2026-11-09T10:01:00Z", "z1", [], out=1000),
                                         _asst("2026-11-09T10:02:00Z", "z2", [], out=500)]),
          agentType="general-purpose", description="fork")
    row = usage.scan(main)
    one = _one
    assert row["tokens"]["output"] == 100 and row["sub_tokens"]["output"] == 1000 + 500
    subs = row["agents"]["subagents"]
    assert subs["first"]["output"] == 1000 and subs["fork"]["output"] == 500
    assert subs["fork"]["cost"] == pytest.approx(one(500), abs=1e-4)
    assert row["cost"] == pytest.approx(one(100) + one(1000) + one(500), abs=1e-4)


def test_a_row_of_an_older_scanner_is_scanned_again_into_agents(projects_dir):
    _launcher(projects_dir)
    rows, _ = usage.update()
    old = dict(rows["proj/boss.jsonl"], v=2)
    old.pop("agents")
    usage.save({"proj/boss.jsonl": old}, usage.ledger(write=True))
    assert "agents" not in usage.load()["proj/boss.jsonl"]
    rows, n = usage.update()
    assert n == 1 and rows["proj/boss.jsonl"]["v"] == usage.SCAN_V
    assert rows["proj/boss.jsonl"]["agents"]["workflows"]["wf_run1"]["agents"] == 3


def test_families_link_a_sub_session_to_its_parent(projects_dir):
    child = _child(projects_dir)
    task = BRIEF.split("Task:\n", 1)[1]
    parent = _write(projects_dir / "proj" / "parent.jsonl", [
        _prompt("2026-11-02T09:00:00Z", "plan the day"),
        _asst("2026-11-02T09:00:05Z", "p1", [_tool("s1", "mcp__ccd_session__start_session", title="Ledger",
                                                     prompt=task)])])
    rows = [usage.scan(child), usage.scan(parent)]
    assert usage.link_families(rows) == {"child": "parent"}
    assert rows[1]["spawned"] == [rows[0]["brief"]["key"]]


def test_ledger_scans_what_changed_and_keeps_what_is_gone(projects_dir):
    child = _child(projects_dir)
    rows, n = usage.update()
    assert n == 1 and list(rows) == ["proj/child.jsonl"]
    assert usage.update()[1] == 0  # unchanged: nothing scanned
    with open(child, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(_asst("2026-11-03T08:00:00Z", "m11", [], out=1000)) + "\n")
    rows, n = usage.update()
    assert n == 1 and "2026-11-03" in rows["proj/child.jsonl"]["days"]
    child.unlink()
    rows, n = usage.update()
    assert n == 0 and "proj/child.jsonl" in usage.load()  # the ledger is the history


def test_windows_and_distributions():
    now = datetime(2026, 11, 2, 15, tzinfo=timezone.utc)
    assert usage.parse_when("7d", now) == "2026-10-26" and usage.parse_when("1w", now) == "2026-10-26"
    assert usage.parse_when("yesterday", now) == "2026-11-01" and usage.parse_when("2026-10-01", now) == "2026-10-01"
    with pytest.raises(ValueError):
        usage.parse_when("soon", now)
    assert usage.in_window({"days": {"2026-11-01": {}}}, "2026-11-01", "2026-11-02")
    assert not usage.in_window({"days": {"2026-11-02": {}}}, "2026-11-01", "2026-11-02")
    q = usage.quantiles([1, 2, 3, 4, 10])
    assert q["n"] == 5 and q["median"] == 3 and q["p25"] == 2 and q["p75"] == 4 and q["total"] == 20
    assert usage.quantiles([])["n"] == 0
