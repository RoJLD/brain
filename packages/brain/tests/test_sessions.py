"""The session tree, the child's report and the master's watch (wi-brain-session-tree, wi-brain-child-report,
wi-brain-master-watch; ST-1 to ST-4, scale study gaps 17 and 19), on invented sessions: Ada's master and its
children, the desktop app's metadata files written under a temporary LOCALAPPDATA, transcripts under a temporary
CLAUDE_CONFIG_DIR."""

import io
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from brain import alerts, budget, capture, cli, cockpit, decisions, governor, schema, sessions

MASTER = "local_11111111-1111-4111-8111-111111111111"
CHILD = "local_22222222-2222-4222-8222-222222222222"
OTHER = "local_33333333-3333-4333-8333-333333333333"
GHOST = "local_99999999-9999-4999-8999-999999999999"
M_CLI, C_CLI, O_CLI = "aaaaaaaa-0000-4000-8000-000000000001", "bbbbbbbb-0000-4000-8000-000000000002", \
    "cccccccc-0000-4000-8000-000000000003"
OPUS = "claude-opus-5-5"
SIDE = "Background (from the session that started this one):\nThe lab.\n\nTask:\n"


@pytest.fixture
def app(tmp_path, monkeypatch):
    """The app's session folder; ``put(host, cli, **keys)`` writes one metadata file with forbidden keys too."""
    d = tmp_path / "appdata" / "Claude-Data" / "claude_t" / "claude-code-sessions" / "acct" / "org"
    d.mkdir(parents=True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    monkeypatch.delenv(sessions.HOST_ENV, raising=False)
    monkeypatch.setattr(governor, "memory_pct", lambda: 50.0)

    def put(host, cli_id, parent=None, name=None, archived=False, active=None, title="A session"):
        data = {"sessionId": host, "cliSessionId": cli_id, "title": title, "createdAt": 1_000,
                "lastActivityAt": active if active is not None else int(time.time() * 1000), "isArchived": archived,
                "model": OPUS, "effort": "high", "branch": "claude/x",
                "lastTurnReport": "ada@example.invalid wrote this", "pendingSystemReminder": "secret text",
                "promptAppendSnapshot": "the prompt", "remoteMcpServersConfig": {"token": "x"},
                "spawnSeed": "the brief"}
        if parent:
            data["spawnedFrom"] = {"sessionId": parent, "taskId": "task_1", "name": name, "sideSession": True,
                                   "title": "kept out"}
        (d / f"{host}.json").write_text(json.dumps(data), encoding="utf-8")
        return d / f"{host}.json"
    return put


def _transcript(tmp_path, sid, *records):
    f = tmp_path / "claude-config" / "projects" / "E--lab" / f"{sid}.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, "a", encoding="utf-8", newline="\n") as fh:
        fh.writelines(json.dumps(r) + "\n" for r in records)
    return f


def _asst(mid, ctx, *blocks, stop="tool_use"):
    content = list(blocks) or [{"type": "tool_use", "id": f"t-{mid}", "name": "Read", "input": {}}]
    return {"type": "assistant", "timestamp": "2026-11-03T10:00:00Z", "cwd": "/lab",
            "message": {"id": mid, "model": OPUS, "content": content, "stop_reason": stop,
                        "usage": {"input_tokens": 10, "output_tokens": 100, "cache_read_input_tokens": ctx - 10,
                                  "cache_creation_input_tokens": 0}}}


def _prompt(text):
    return {"type": "user", "timestamp": "2026-11-03T10:00:00Z", "message": {"content": text}}


def _start(i):
    return {"type": "tool_use", "id": f"start-{i}", "name": "mcp__ccd_session__start_session",
            "input": {"title": f"child {i}"}}


def _family(app):
    app(MASTER, M_CLI, name=None, title="Ada's coordinator")
    app(CHILD, C_CLI, parent=MASTER, name="f1-tree", title="F1 tree")
    app(OTHER, O_CLI, parent=MASTER, name="f2-old", archived=True, title="F2 done")


# --- the app's metadata: a closed list of keys ---

def test_only_the_closed_list_of_keys_is_read_or_cached(app, brain_home):
    _family(app)
    meta = sessions.app_meta(CHILD)
    assert meta == {"host_id": CHILD, "session": C_CLI, "title": "F1 tree", "created": 1_000,
                    "active": meta["active"], "archived": False, "model": OPUS, "effort": "high",
                    "branch": "claude/x", "parent": MASTER, "task": "task_1", "name": "f1-tree", "side": True}
    index = sessions.app_index()
    assert set(index) == {MASTER, CHILD, OTHER}
    cached = (brain_home / "cache" / "sessions-app.json").read_text(encoding="utf-8")
    for forbidden in ("ada@example.invalid", "secret text", "the prompt", "token", "the brief", "kept out"):
        assert forbidden not in cached
    assert sessions.app_meta("local_not-an-id") == {} and sessions.app_index() == index  # the cache answers again


def test_no_app_on_the_machine(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "nothing"))
    assert sessions.app_index() is None and sessions.app_meta(CHILD) == {}


# --- SessionStart: both ids, and the parent from the session's own file ---

def test_session_start_records_both_ids_and_the_parent(app, brain_home, monkeypatch):
    _family(app)
    monkeypatch.setenv(sessions.HOST_ENV, CHILD)
    capture.main(["session-start"], stdin=io.StringIO(json.dumps({"session_id": C_CLI, "source": "startup"})))
    (ev,) = [json.loads(x) for x in (brain_home / "ledger").glob("events-*.jsonl").__next__().read_text(
        encoding="utf-8").splitlines()]
    assert ev["host_id"] == CHILD and ev["parent"] == MASTER and ev["name"] == "f1-tree" and ev["task"] == "task_1"
    assert "title" not in ev  # what the event takes from the app: the parent, the task and the name


def test_the_ledger_keeps_the_tree_once_the_app_forgets(app, brain_home, monkeypatch, tmp_path):
    _family(app)
    monkeypatch.setenv(sessions.HOST_ENV, CHILD)
    capture.main(["session-start"], stdin=io.StringIO(json.dumps({"session_id": C_CLI, "source": "startup"})))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "gone"))  # another machine's view: the ledger only
    tree = sessions.load(briefs=False)
    assert tree.resolve("f1-tree") == [CHILD] and tree.nodes[CHILD]["parent"] == MASTER


# --- the tree: resolve either id or the name, roles, the brief hash ---

def test_resolve_either_id_a_prefix_or_the_name(app):
    _family(app)
    tree = sessions.load(briefs=False)
    for ref in (CHILD, CHILD.removeprefix("local_"), "local_22222222", "22222222", C_CLI, C_CLI[:8], "F1-TREE"):
        assert tree.resolve(ref) == [CHILD], ref
    assert tree.resolve("2222") == [] and tree.resolve("nobody") == []
    assert [tree.role(k) for k in (MASTER, CHILD, OTHER)] == ["master", "sub", "sub"]
    assert tree.parent_name(CHILD) == sessions.short(MASTER) and tree.root(CHILD) == MASTER


def test_the_brief_hash_fills_in_without_the_app(brain_home):
    """A command-line session the app never knew: its parent from the token ledger's brief hash (transcript ids)."""
    tree = sessions.Tree(None, {}, {"kid-1": "boss-1", "kid-2": "boss-1"})
    assert tree.role("boss-1") == "master" and tree.resolve("boss-1") == ["boss-1"]
    assert tree.nodes["kid-1"]["parent"] == "boss-1" and tree.nodes["kid-1"]["parent_source"] == "briefs"
    assert tree.children["boss-1"] == ["kid-1", "kid-2"] and tree.role("kid-1") == "sub"


def test_a_relay_has_both(app):
    _family(app)
    app(GHOST, "dddddddd-0000-4000-8000-000000000004", parent=CHILD, name="grandchild")
    assert sessions.load(briefs=False).role(CHILD) == "relay"


# --- brain sessions: list, tree, show ---

def test_show_tells_the_state_before_a_message(app, tmp_path, capsys):
    _family(app)
    _transcript(tmp_path, C_CLI, _prompt(SIDE + "Build wi-a."), _asst("m1", 50_000, {"type": "text", "text": "Done."},
                                                                       stop="end_turn"))
    assert cli.main(["sessions", "show", "f1-tree"]) == 0
    out = capsys.readouterr().out
    assert f"app {CHILD}; transcript {C_CLI}" in out and "state     idle: live, idle: a message starts" in out
    assert f"parent    {sessions.short(MASTER)} (app {MASTER}; transcript {M_CLI}; from app)" in out
    assert cli.main(["sessions", "show", OTHER]) == 0
    assert "archived: a message would be lost" in capsys.readouterr().out


def test_show_refuses_an_unknown_ref(app):
    _family(app)
    with pytest.raises(SystemExit, match="no session by that app id"):
        cli.main(["sessions", "show", "nobody"])


def test_list_and_tree_with_the_child_report(app, tmp_path, brain_home, capsys):
    _family(app)
    _budget(_transcript(tmp_path, M_CLI, _prompt("Coordinate the wave."), _asst("m1", 600_000, _start(1))))
    sessions.write_report(C_CLI, {"v": 1, "session": C_CLI, "at": "2026-11-03T10:00:00Z", "turn": "idle",
                                  "blocked": True, "prs": [{"repo": "ada/lab", "number": 7}], "head": "abc1234",
                                  "items": ["wi-a"], "waits_on": "the coordinator's review", "recap": "PR open."})
    assert cli.main(["sessions"]) == 0
    out = capsys.readouterr().out
    assert sessions.short(MASTER) in out and "master" in out and "1/2" in out  # kids live/started
    assert "f2-old" not in out  # archived: --all
    assert cli.main(["sessions", "tree"]) == 0
    out = capsys.readouterr().out
    assert "f1-tree" in out and "PR lab#7; head abc1234; items wi-a" in out
    assert "waits on: the coordinator's review" in out and "(1 archived: --all shows them)" in out
    assert cli.main(["sessions", "tree", "f1-tree", "--json"]) == 0
    (root,) = json.loads(capsys.readouterr().out)
    assert root["host_id"] == MASTER and root["ctx_pct"] == 60.0  # a master without a brief: the model's window
    assert [c["name"] for c in root["children"]] == ["f1-tree", "f2-old"]
    assert root["children"][0]["report"]["prs"][0]["number"] == 7


def test_show_report_reads_the_last_message_in_full(app, tmp_path, capsys):
    _family(app)
    long_text = "Done: " + "x" * 900 + " the end."
    _transcript(tmp_path, C_CLI, _prompt("Task."), _asst("m1", 9_000, {"type": "text", "text": long_text},
                                                         stop="end_turn"))
    assert cli.main(["sessions", "show", C_CLI, "--report"]) == 0
    assert long_text in capsys.readouterr().out  # never cut at 400 characters


# --- the Stop hook: the SR's place in the tree, and the child's report ---

def test_stop_writes_the_tree_fields_and_the_report(app, tmp_path, brain_home, monkeypatch):
    _family(app)
    monkeypatch.setenv(sessions.HOST_ENV, CHILD)
    wrap = {"type": "tool_use", "id": "w1", "name": sessions.WRAP_UP,
            "input": {"recap": "The tree is built; PR open for wi-lab-tree, waits on ddr-2026-11-03-pick-one.",
                      "ask": "Merge it?", "blocked": True}}
    t = _transcript(tmp_path, C_CLI, _prompt(SIDE + "Build wi-a. Context budget: 400k."), _asst("m1", 80_000, wrap),
                    {"type": "system", "subtype": "stop_hook_summary", "timestamp": "2026-11-03T10:01:00Z"})
    capture.main(["stop"], stdin=io.StringIO(json.dumps({"session_id": C_CLI, "transcript_path": str(t)})))
    sr = json.loads((brain_home / "sessions" / f"{C_CLI}.json").read_text(encoding="utf-8"))
    assert sr["host_id"] == CHILD and sr["parent"] == MASTER and sr["role"] == "sub" and sr["name"] == "f1-tree"
    assert schema.check("sr", sr)[0] == []
    rep = sessions.read_report(C_CLI)
    assert rep["blocked"] is True and rep["waits_on"] == "Merge it?" and rep["turn"] == "asking"
    assert "wi-lab-tree" in rep["items"] and rep["ddrs"] == ["ddr-2026-11-03-pick-one"] and rep["parent"] == MASTER
    assert rep["recap"].startswith("The tree is built")


def test_report_next_comes_from_the_plan_when_not_blocked():
    steps = [{"content": "Build", "status": "completed"}, {"content": "Test it", "status": "pending"}]
    recs = [_asst("m1", 1_000, {"type": "text", "text": "See https://github.com/ada/lab/pull/12"}, stop="end_turn")]
    rep = sessions.build_report("s-1", recs, {}, {}, steps, [], "", "2026-11-03T10:00:00Z", brief_items=["wi-lab-x"])
    assert rep["items"] == ["wi-lab-x"]  # the items its brief names (the budget watch read them)
    assert rep["next"] == "Test it" and rep["plan"] == "1/2" and rep["prs"] == [{"repo": "ada/lab", "number": 12}]
    assert rep["blocked"] is False and "waits_on" not in rep


# --- the DDRs carry both ids; brain check refuses a local_ id that matches no session ---

def _store(tmp_path):
    root = tmp_path / "ada"
    (root / "records" / "ddr").mkdir(parents=True)
    return root


def test_ask_answer_and_ack_stamp_both_ids(app, tmp_path, monkeypatch):
    _family(app)
    monkeypatch.setenv(sessions.HOST_ENV, CHILD)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", C_CLI)
    monkeypatch.setenv("BRAIN_HOST", "po-test")
    root = _store(tmp_path)
    ddr, _ = decisions.ask(root, title="Pick", question="Which?", options=["A", "B"], why="A is simpler",
                           at="2026-11-03T10:00:00Z")
    assert ddr["asked"] == {"at": "2026-11-03T10:00:00Z", "by": C_CLI, "host_id": CHILD, "machine": "po-test",
                            "via": "cli"}
    ddr = decisions.answer(root, ddr["id"], ["A"], at="2026-11-03T11:00:00Z")
    assert ddr["answer"]["session"] == C_CLI and ddr["answer"]["host_id"] == CHILD
    ddr, _ = decisions.ack(root, ddr["id"], ["adr-x"], at="2026-11-03T12:00:00Z")
    assert ddr["applied"]["host_id"] == CHILD and ddr["archived"]["session"] == C_CLI
    assert decisions.who("local_33333333-3333-4333-8333-333333333333")["host_id"] == OTHER  # --session as an app id


def test_check_refuses_an_unknown_local_id_stamped_here(app, tmp_path, monkeypatch, capsys):
    _family(app)
    monkeypatch.setenv("BRAIN_HOST", "po-test")
    root = _store(tmp_path)
    good = {"at": "2026-11-03T10:00:00Z", "by": C_CLI, "host_id": CHILD, "machine": "po-test"}
    bad = {**good, "host_id": GHOST}
    legacy = {"at": "2026-11-03T10:00:00Z", "by": "local_d62f20e2-4968-4e1e-8e48-2a0dcde93065"}
    ddrs = [(Path("a.yaml"), {"id": "ddr-a", "asked": good}), (Path("b.yaml"), {"id": "ddr-b", "asked": bad}),
            (Path("c.yaml"), {"id": "ddr-c", "asked": legacy}),
            (Path("d.yaml"), {"id": "ddr-d", "asked": {**good, "host_id": GHOST, "machine": "lab-laptop"}})]
    refused, warned = sessions.unknown_ids(ddrs)
    assert refused == [f"ddr-b: asked names {GHOST}, which matches no session on po-test"]
    assert [w.split(":")[0] for w in warned] == ["ddr-c", "ddr-d"]  # elsewhere, or before stamps named a machine
    for _, d in ddrs[:2]:
        (root / "records" / "ddr" / f"{d['id']}.yaml").write_text(yaml.safe_dump(d), encoding="utf-8")
    assert cli._check_session_ids(root) == 1
    assert "error: ddr-b: asked names" in capsys.readouterr().out


def test_check_says_nothing_where_no_session_is_known(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "nothing"))
    ddrs = [(Path("b.yaml"), {"id": "ddr-b", "asked": {"at": "x", "host_id": GHOST, "machine": "po-test"}})]
    assert sessions.unknown_ids(ddrs) == ([], [])


# --- both ids from the environment (the resume pack prints them: test_resume) ---

def test_here_reads_both_ids_from_the_environment(monkeypatch):
    monkeypatch.setenv(sessions.HOST_ENV, CHILD)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", C_CLI)
    assert sessions.here() == {"session": C_CLI, "host_id": CHILD}
    monkeypatch.setenv(sessions.HOST_ENV, "local_not-a-uuid")
    assert sessions.here()["host_id"] == ""


# --- the master's watch ---

def _budget(t, sid=M_CLI):
    out = io.StringIO()
    sys_stdout, sys.stdout = sys.stdout, out
    try:
        budget.hook_main([], stdin=io.StringIO(json.dumps({"session_id": sid, "transcript_path": str(t),
                                                           "cwd": str(t.parent)})))
    finally:
        sys.stdout = sys_stdout
    text = out.getvalue()
    return json.loads(text)["hookSpecificOutput"]["additionalContext"] if text else ""


def test_a_master_without_a_brief_gets_the_70_80_90_steps(app, tmp_path, brain_home, monkeypatch):
    _family(app)
    monkeypatch.setenv(sessions.HOST_ENV, MASTER)
    t = _transcript(tmp_path, M_CLI, _prompt("Coordinate the wave."), _asst("m1", 100_000, _start(1)))
    assert _budget(t) == ""  # 10 % of the model's window
    state = json.loads((brain_home / "budget" / f"{M_CLI}.json").read_text(encoding="utf-8"))
    assert state["master_budget"] == sessions.MODEL_WINDOW and state["master"]["live"] == 1
    _transcript(tmp_path, M_CLI, _asst("m2", 720_000))
    text = _budget(t)
    assert text.startswith("Master's watch (ST-3): this master's context is 720k tokens, 72 % of its budget (the "
                           "model's window") and "Room before 80 %: about 3 more child(ren) at 22k each" in text
    assert "1 live child(ren) of 2 started" in text and "nothing stops or blocks the session (ST-4)" in text
    _transcript(tmp_path, M_CLI, _asst("m3", 810_000))
    text = _budget(t)
    assert "Start no new child. Hand over to a fresh master" in text and "ask the owner nothing new" in text
    assert f"- f1-tree: app {CHILD}, transcript {C_CLI}" in text and "f2-old" not in text  # the live ones only
    assert "One wake after the prompt cache expired costs about $" in text
    assert budget.master_of(M_CLI)["step"] == 80
    _transcript(tmp_path, M_CLI, _asst("m4", 905_000))
    assert "Drain only: no new child, no new work; compact only once no child is alive (1 still live)." in _budget(t)
    _transcript(tmp_path, M_CLI, _asst("m5", 950_000))
    assert _budget(t) == ""  # each step once


def test_a_session_that_started_nothing_has_no_master_steps(app, tmp_path, brain_home, monkeypatch):
    monkeypatch.setenv(sessions.HOST_ENV, CHILD)
    _family(app)
    t = _transcript(tmp_path, C_CLI, _prompt("Plain work."), _asst("m1", 950_000))
    assert _budget(t, C_CLI) == ""  # no brief, no child: nothing to compare with
    assert budget.master_of(C_CLI) is None


def test_a_master_with_a_brief_keeps_its_brief_budget(app, tmp_path, monkeypatch):
    _family(app)
    monkeypatch.setenv(sessions.HOST_ENV, MASTER)
    t = _transcript(tmp_path, M_CLI, _prompt(SIDE + "Coordinate. Context budget: 400k."),
                    _asst("m1", 330_000, _start(1)))
    text = _budget(t)
    assert "82 % of its brief's context budget, 400k" in text and "Start no new child" in text
    assert "Room before 80 %" not in text  # the steps past are not said again below the one given


def test_master_budget_from_config(app, tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"v": 1, "identity": {"owner": "Ada", "kind": "person"},
                               "usage": {"master_budget": 500_000}}), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(cfg))
    assert sessions.master_budget(str(tmp_path)) == 500_000
    assert sessions.budget_of(None, "master", str(tmp_path)) == 500_000
    assert sessions.budget_of(None, "sub") is None and sessions.budget_of(300_000, "sub") == 300_000


def test_the_family_measures_a_child(monkeypatch):
    state = {"ctx": 400_000, "kids": {"a": 300_000, "b": 320_000, "c": 350_000, "d": 380_000}}
    assert budget.per_child(state) == (25_000, True)
    assert budget.per_child({"ctx": 1, "kids": {"a": 0}}) == (budget.CHILD_K, False)


def test_the_governor_reminds_a_master_past_80_and_lets_the_call_through(app, tmp_path, brain_home, monkeypatch):
    _family(app)
    monkeypatch.setenv(sessions.HOST_ENV, MASTER)
    t = _transcript(tmp_path, M_CLI, _prompt("Coordinate the wave."), _asst("m1", 850_000, _start(1)))
    _budget(t)
    mark = brain_home / "budget" / f"{M_CLI}.mark"
    assert mark.stat().st_mtime > time.time()
    out = governor.decide({"tool_name": "mcp__ccd_session__start_session", "session_id": M_CLI, "cwd": str(tmp_path),
                           "tool_input": {"title": "one more"}})
    hso = out["hookSpecificOutput"]
    assert "permissionDecision" not in hso and "past 80 % a master starts no new child" in hso["additionalContext"]
    assert mark.stat().st_mtime < time.time()  # the watch checks at the next call
    assert governor.master_note(C_CLI) == ""


def test_alerts_name_a_master_past_80_with_live_children(app, tmp_path, brain_home, monkeypatch):
    _family(app)
    monkeypatch.setenv(sessions.HOST_ENV, MASTER)
    t = _transcript(tmp_path, M_CLI, _prompt("Coordinate the wave."), _asst("m1", 920_000, _start(1)))
    _budget(t)
    (a,) = alerts.master_alerts(alerts.Config("brain"), datetime.now(timezone.utc))
    assert a.key == f"session:master:{MASTER}" and a.level == "error" and "1 live child(ren)" in a.message


# --- the cockpit's columns ---

def test_the_cockpit_rows_carry_role_parent_kids_and_ctx(app, tmp_path, monkeypatch):
    _family(app)
    _transcript(tmp_path, M_CLI, _prompt("Coordinate."), _asst("m1", 850_000, _start(1)))
    _transcript(tmp_path, C_CLI, _prompt(SIDE + "Build."), _asst("m2", 40_000))
    rows = {r["session_id"]: r for r in cockpit.Sessions(lambda f: "lab").rows()}
    m, c = rows[M_CLI], rows[C_CLI]
    assert (m["role"], m["kids"], m["kids_live"], m["ctx_pct"], m["ctx_step"]) == ("master", 2, 1, 85.0, 80)
    assert (c["role"], c["name"], c["parent_name"], c["ctx_pct"]) == ("sub", "f1-tree", sessions.short(MASTER), None)
    cells = cockpit.cells("sessions", m)
    assert cells[1:5] == (sessions.short(MASTER), "master", "-", "1/2") and cells[9] == "85 %"
    assert cockpit.cells("sessions", c)[1] == "f1-tree"  # the short name: what SendMessage needs, the ids in detail
