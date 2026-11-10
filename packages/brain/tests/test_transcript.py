import json

from brain import actions, schema, transcript


def test_session_record_from_fixture(fixture_transcript):
    stats, subs, n = transcript.session_stats(fixture_transcript)
    sr = stats.record(fixture_transcript, status="closed")
    assert schema.check("sr", sr) == ([], [])
    assert sr["id"] == "sr-2026-10-30-aaaabbbb"
    assert sr["title"] == sr["summary"] == "Build the thing"
    # one API message is several records with the same usage: counted once; <synthetic> errors are not
    assert sr["tokens"] == {"messages": 3, "input": 16, "output": 160, "thinking": 40, "cache_read": 4800,
                            "cache_write": 500, "cache_write_1h": 500, "cache_write_5m": 0}
    assert sr["models"] == {"claude-opus-5-5": 2, "claude-sonnet-5-5": 1} and sr["model"] == "claude-opus-5-5"
    assert sr["efforts"] == {"xhigh": 2, "medium": 1} and sr["effort"] == "xhigh"
    assert sr["versions"] == ["2.1.309", "2.1.310"]
    assert sr["permission_modes"] == ["auto"] and sr["surface"] == "cli"
    assert sr["context"] == {"budget": 400000, "peak": 2005, "last": 1801, "compactions": 1}
    assert sr["duration_s"] == 1319 and sr["active_s"] == 179  # the 19-minute pause is not active time
    assert sr["prs"] == [{"repo": "RoJLD/brain-test", "number": 7,
                          "url": "https://github.com/RoJLD/brain-test/pull/7", "actions": ["created", "linked"]}]
    assert sr["items"] == ["wi-brain-record-formats"]
    assert sr["api_errors"] == 1 and sr["cost_usd"] == 1.25 and sr["tools"] == {"Bash": 2}
    assert sr["branch"] == "main" and sr["folder"] == "/work/brain"


def test_incremental_feed_matches_a_full_read(fixture_transcript, tmp_path):
    lines = fixture_transcript.read_text(encoding="utf-8").splitlines(keepends=True)
    part = tmp_path / "t.jsonl"
    part.write_bytes(("".join(lines[:5]) + lines[5][:40]).encode())  # a partial last line
    s = transcript.SessionStats()
    s.feed_file(part)
    assert s.offset == len("".join(lines[:5]).encode())
    s = transcript.SessionStats.from_state(json.loads(json.dumps(s.to_state())))
    part.write_bytes("".join(lines).encode())
    s.feed_file(part)
    full, _, _ = transcript.session_stats(fixture_transcript)
    assert s.record(part) == full.record(part)


def test_last_assistant_reads_the_tail(fixture_transcript):
    meta = transcript.last_assistant(fixture_transcript)
    assert meta == {"model": "claude-sonnet-5-5", "version": "2.1.310", "effort": "medium", "cwd": "/work/brain/sub",
                    "branch": "feat", "surface": "cli"}


def test_actions_recovered_from_a_transcript(fixture_transcript):
    ars = actions.from_transcript(fixture_transcript)
    assert [a["id"] for a in ars] == ["ar-2026-10-30-push-brain-test-feat-lu-push1",
                                      "ar-2026-10-30-pr-brain-test-7-created"]
    push, pr = ars
    assert push["repo"] == "RoJLD/brain-test" and push["branch"] == "feat" and push["refs"] == ["feat -> feat"]
    assert pr["pr"] == {"number": 7, "url": "https://github.com/RoJLD/brain-test/pull/7", "action": "created"}
    assert pr["session"] == {"id": "aaaabbbb-1111-2222-3333-444455556666", "tool": "claude-code",
                             "model": "claude-opus-5-5", "version": "2.1.309", "effort": "xhigh",
                             "permission_mode": "auto", "surface": "cli"}
    for a in ars:
        assert schema.check("ar", a) == ([], [])


def test_agent_info_reads_the_meta_then_the_workflow_journal(tmp_path):
    """wi-brain-usage-workflow-agents: who a subagent's transcript is, on an invented session."""
    subs = tmp_path / "proj" / "sess" / "subagents"
    run = subs / "workflows" / "wf_r1"
    run.mkdir(parents=True)
    plain, labelled, bare = subs / "agent-a1.jsonl", run / "agent-b1.jsonl", run / "agent-b2.jsonl"
    for f in (plain, labelled, bare):
        f.write_text("", encoding="utf-8")
    (subs / "agent-a1.meta.json").write_text(json.dumps({"agentType": "Explore", "description": "find the hooks",
                                                         "model": "haiku"}), encoding="utf-8")
    (run / "agent-b1.meta.json").write_text(json.dumps({"agentType": "workflow-subagent", "description": "impl:x",
                                                        "workflowPhase": "Implement"}), encoding="utf-8")
    (run / "journal.jsonl").write_text(
        json.dumps({"type": "started", "agentId": "b2", "label": "review:x", "phase": "Review"}) + "\nnot json\n",
        encoding="utf-8")
    assert transcript.agent_info(plain) == {"id": "a1", "type": "Explore", "label": "find the hooks", "phase": "",
                                            "run": "", "model": "haiku"}
    assert transcript.agent_info(labelled)["label"] == "impl:x" and transcript.agent_info(labelled)["run"] == "wf_r1"
    cache = {}
    assert transcript.agent_info(bare, cache) == {"id": "b2", "type": "", "label": "review:x", "phase": "Review",
                                                  "run": "wf_r1", "model": ""}
    assert list(cache) == [str(run)]   # the run's journal read once
    assert transcript.subagent_files(tmp_path / "proj" / "sess.jsonl") == sorted([plain, labelled, bare])
