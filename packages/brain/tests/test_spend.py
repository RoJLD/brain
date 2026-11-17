"""wi-brain-cache-report: where the tokens go (brain.usage.Spend, the scanner's ``spend``; brain.spend, the views):
brain usage --by context (the buckets, the cost by token kind, the base, the hand-over simulation) and --by output
(the downstream cost of each kind of output)."""

import json

import pytest
from brain import cli, projects, spend, usage

OPUS = "claude-opus-5-5"
READ, W5, W1 = 0.2e-6, 5e-6, 8e-6   # Opus 5.5's USD per token: cache read, cache write 5 min and 1 h


@pytest.fixture
def projects_dir(tmp_path, monkeypatch):
    d = tmp_path / "claude" / "projects"
    d.mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    return d


def _asst(ts, mid, blocks, out=100, read=0, write=0, inp=10):
    return {"type": "assistant", "timestamp": ts, "sessionId": "s", "cwd": "/work/brain",
            "message": {"id": mid, "model": OPUS, "content": blocks,
                        "usage": {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": read,
                                  "cache_creation_input_tokens": write,
                                  "cache_creation": {"ephemeral_1h_input_tokens": write}}}}


def _tool(tid, name, **inp):
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


def _result(ts, tid, content):
    return {"type": "user", "timestamp": ts, "sessionId": "s",
            "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "content": content}]}}


def _write(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def _session(projects_dir):
    t = "2026-11-16T10:00:"
    hook = {"type": "hook_additional_context", "hookEvent": "PostToolUse", "hookName": "PostToolUse:Read",
            "content": ["y" * 100]}
    return _write(projects_dir / "proj" / "s1.jsonl", [
        {"type": "user", "timestamp": f"{t}00Z", "sessionId": "s", "message": {"content": "go"}},
        _asst(f"{t}05Z", "m1", [_tool("t1", "Read", file_path="a.py")], read=50_000),
        _result(f"{t}06Z", "t1", "x" * 3600),                                   # 1,000 tokens
        {"type": "attachment", "timestamp": f"{t}06Z", "attachment": hook},
        {"type": "attachment", "timestamp": f"{t}06Z", "attachment": {"type": "prompt_snapshot", "tools": ["z" * 999]}},
        {"type": "user", "timestamp": f"{t}07Z", "sessionId": "s", "isMeta": True,
         "message": {"content": "r" * 36}},
        _asst(f"{t}10Z", "m2", [_tool("t2", "Bash", command="git diff --stat")], read=150_000, write=3_600),
        _result(f"{t}11Z", "t2", [{"type": "text", "text": "d" * 360}, {"type": "image", "source": {}}]),
        {"type": "system", "subtype": "compact_boundary", "timestamp": f"{t}20Z"},
        _asst(f"{t}25Z", "m3", [{"type": "text", "text": "done"}], read=20_000),
    ])


def test_the_scan_keeps_buckets_split_base_and_outputs(projects_dir):
    row = usage.scan(_session(projects_dir))
    sp = row["spend"]
    assert row["v"] == usage.SCAN_V == 5
    assert sp["messages"] == 3 and sp["base"] == 50_010 and sp["step"] == 100 and sp["restart"] == spend.SIM_RESTART
    assert {k: n for k, (n, _) in sp["buckets"].items()} == {"0": 2, "100": 1}
    assert sum(c for _, c in sp["buckets"].values()) == pytest.approx(row["main_cost"], abs=1e-3)
    assert sum(sp["split"].values()) == pytest.approx(row["main_cost"], abs=1e-4)
    assert sp["split"]["read"] == pytest.approx(220_000 * READ, abs=1e-4)
    assert sp["split"]["write"] == pytest.approx(3_600 * W1, abs=1e-4)
    outs = sp["outputs"]
    # the Read result: written by m2 (a 1 h write), read by m2; m3 is past the compaction
    assert outs["Read"] == [1, 1000, pytest.approx(1000 * (READ + W1), abs=1e-4)]
    # a shell result by its program and subcommand, an image counted; sent after the compaction only: no cost
    assert outs["git diff"][:2] == [1, round((360 + spend.IMAGE_CHARS) / spend.CHARS_PER_TOKEN)]
    assert outs["git diff"][2] == 0
    assert set(outs) == {"Read", "git diff", "hook:PostToolUse", "injected", "prompt"}   # no prompt_snapshot
    assert outs["injected"][1] == 10 and outs["prompt"][0] == 1
    assert sp["agents"] == {"messages": 0, "bases": [], "buckets": {}, "split": {k: 0.0 for k in sp["split"]},
                            "outputs": {}}


def test_the_hand_over_simulation():
    s = spend.Spend()
    for ctx in (100_000, 250_000, 350_000, 450_000, 550_000, 50_000, 400_000):   # a compaction before 50k
        s.message({"cache_read": ctx}, 0.0, None, (1e-6, 0.0))
    # 300k: hand-overs at 350k (offset 230k), 550k (430k), then after the drop at 400k (280k)
    assert s.simulate() == {"300": [pytest.approx(1.17), 3], "400": [pytest.approx(0.66), 1],
                            "500": [pytest.approx(0.43), 1]}
    assert spend.Spend().simulate() == {"300": [0.0, 0], "400": [0.0, 0], "500": [0.0, 0]}


def test_an_output_after_an_uncounted_message_is_read_from_the_next_one():
    s = spend.Spend()
    s.output("attachment:x", 3600, pending=True)   # an assistant record seen, its message not yet counted
    s.message({"cache_read": 10}, 0.0, None, (1e-6, 2e-6))
    s.message({"cache_read": 10}, 0.0, None, (1e-6, 2e-6))
    s.output("attachment:x", 3600)                 # after the last message: never sent
    assert s.outputs() == {"attachment:x": [2, 2000, pytest.approx(1000 * 1e-6 + 1000 * 2e-6)]}


def _row(sid, buckets, sim, base=80_000, messages=100, spawned=(), side=False, read_tokens=1_000_000, **kw):
    r = {"session_id": sid, "spawned": list(spawned), "brief": {"side": side}, "tokens": {"cache_read": read_tokens},
         "phases": {"reload": {"cost": 0.5}}, "signals": {"reloads": 1},
         "spend": {"step": 100, "restart": 120_000, "messages": messages, "base": base, "buckets": buckets,
                   "split": {"input": 0.0, "output": 1.0, "read": 2.0, "write": 1.0}, "sim": sim,
                   "outputs": {"Read": [2, 2000, 0.5], "grep": [4, 1000, 0.25]},
                   "agents": {"messages": 10, "bases": [60_000], "buckets": {"0": [10, 0.4]},
                              "split": {"input": 0.0, "output": 0.1, "read": 0.2, "write": 0.1},
                              "outputs": {"attachment:skill_listing": [1, 7000, 0.3]}}}}
    r.update(kw)
    return r


def test_the_context_view_by_role():
    rows = [
        _row("coord", {"0": [10, 1.0], "400": [20, 4.0]}, {"300": [12.0, 2], "400": [10.0, 1], "500": [1.0, 1]},
             spawned=["k1", "k2"]),
        _row("lot", {"100": [30, 3.0], "500": [10, 2.0]}, {"300": [2.0, 1], "400": [1.0, 1], "500": [0.0, 0]},
             side=True),
        _row("old", {}, {}, spend=None),   # scanned before SCAN_V 5, its transcript gone
    ]
    v = spend.context_view(rows, handover_usd=3.0)
    assert (v["sessions"], v["scanned"], v["older"]) == (3, 2, 1)
    assert v["split"]["main"] == {"input": 0.0, "output": 2.0, "read": 4.0, "write": 2.0}
    assert v["reloads"] == {"messages": 2, "cost": 1.0}
    c = v["roles"]["coordinator"]
    assert c["above"] == {"ceiling_k": 400, "messages": 20, "cost": 4.0, "share": 0.8}
    assert [s["net"] for s in c["sim"]] == [6.0, 7.0, -2.0] and c["best"]["ceiling_k"] == 400
    assert v["roles"]["sub-session"]["best"] is None   # no ceiling pays
    assert "session" not in v["roles"]
    # the base: 80k read by 100 messages at the row's mean read rate ($2 over 1M tokens)
    assert c["base"]["median"] == 80_000 and c["base_reread"] == pytest.approx(80_000 * 100 * 2e-6)
    assert [b["from_k"] for b in v["all"]["buckets"]] == [0, 100, 400, 500]
    assert v["all"]["above"]["cost"] == 6.0 and v["agents"]["base"]["n"] == 2
    text = "\n".join(spend.render_context(v))
    assert "1 session(s) scanned by an older scanner" in text
    assert "coordinator: at 300k: 2 hand-over(s), saves $12.00, net $6.00" in text and "-> 400k" in text
    assert "-> no ceiling pays" in text and "above 400k 20 msg, $4.00 (80%)" in text
    assert spend.context_view(rows, handover_usd=0.0)["roles"]["coordinator"]["best"]["ceiling_k"] == 300


def test_roles():
    assert spend.role_of({"spawned": ["a", "b"], "brief": {"side": True}}) == "coordinator"
    assert spend.role_of({"spawned": ["a"], "brief": {"side": True}}) == "sub-session"
    assert spend.role_of({}) == "session"


def test_the_output_view():
    rows = [_row("a", {}, {}), _row("b", {}, {}), _row("old", {}, {}, spend=None)]
    v = spend.output_view(rows)
    assert v["older"] == 1
    assert [(r["key"], r["count"], r["tokens"], r["downstream"]) for r in v["main"]] == [
        ("Read", 4, 4000, 1.0), ("grep", 8, 2000, 0.5)]
    assert v["main"][0]["per_output"] == 1000 and v["main"][0]["share"] == pytest.approx(2 / 3, abs=1e-4)
    assert v["agents"][0]["key"] == "attachment:skill_listing"
    text = "\n".join(spend.render_output(v, top=1))
    assert "Main threads (top 1 of 2): $1.50 downstream" in text and "grep" not in text


def test_an_empty_window():
    assert spend.render_context(spend.context_view([]))[-1] == "  none"
    assert "  none" in spend.render_output(spend.output_view([]))


@pytest.fixture
def project(store):
    return projects.Project(name="demo", root=store.parents[1], stores=[store])


def test_cli_usage_by_context_and_output(project, capsys):
    r = _row("coord", {"0": [10, 1.0], "400": [20, 4.0]}, {"300": [12.0, 2], "400": [10.0, 1], "500": [1.0, 1]},
             spawned=["k1", "k2"], folder=str(project.root), start="2026-11-16T10:00:00Z",
             end="2026-11-16T11:00:00Z", cost=6.0, days={"2026-11-16": {"cost": 6.0}})
    usage.save({"p/coord.jsonl": r})
    root = str(project.root)
    base = ["--root", root, "usage", "--since", "2026-11-01", "--no-scan"]
    assert cli.main([*base, "--by", "context", "--handover-usd", "5"]) == 0
    out = capsys.readouterr().out
    assert "By context" in out and "$5.00 charged per hand-over" in out and "net $2.00" in out
    assert cli.main([*base, "--by", "context", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["context"]["roles"]["coordinator"]["best"]["ceiling_k"] == 400 and data["tables"] == {}
    assert cli.main([*base, "--by", "output"]) == 0
    assert "By output" in capsys.readouterr().out
    for bad in (["--by", "output", "--handover-usd", "1"], ["--by", "context", "--handover-usd", "-1"]):
        with pytest.raises(SystemExit, match="--handover-usd"):
            cli.main([*base, *bad])
    assert spend.DIMS == ("context", "output")
