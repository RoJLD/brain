"""The session tree, the child's report and the master's watch (wi-brain-session-tree, wi-brain-child-report,
wi-brain-master-watch; ST-1 to ST-4, scale study gaps 17 and 19), on invented sessions: Ada's master and its
children, the desktop app's metadata files written under a temporary LOCALAPPDATA, transcripts under a temporary
CLAUDE_CONFIG_DIR."""

import io
import json
import os
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

    def put(host, cli_id, parent=None, name=None, archived=False, active=None, title="A session", detached=None):
        data = {"sessionId": host, "cliSessionId": cli_id, "title": title, "createdAt": 1_000,
                "lastActivityAt": active if active is not None else int(time.time() * 1000), "isArchived": archived,
                "model": OPUS, "effort": "high", "branch": "claude/x",
                "lastTurnReport": "ada@example.invalid wrote this", "pendingSystemReminder": "secret text",
                "promptAppendSnapshot": "the prompt", "remoteMcpServersConfig": {"token": "x"},
                "spawnSeed": "the brief"}
        if parent:
            data["spawnedFrom"] = {"sessionId": parent, "taskId": "task_1", "name": name, "sideSession": True,
                                   "title": "kept out"}
        if detached is not None:
            data["lineageDetached"] = detached
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


def test_a_family_of_app_ledger_and_brief_children_sorts_by_start():
    """The app's createdAt (an int, milliseconds), a ledger-only child's SessionStart (an ISO string: its app file
    deleted, or half-written while the app rewrites it) and a brief-only child (no time) meet in one family: the
    children sort on one kind of number instead of raising TypeError (review of #34, finding 4)."""
    at = 1793736000   # 2026-11-03T20:00:00Z
    app = {"local_boss": {"host_id": "local_boss", "session": "s-boss", "created": at * 1000},
           "local_late": {"host_id": "local_late", "session": "s-late", "parent": "local_boss",
                          "created": (at + 600) * 1000}}
    starts = {"s-gone": {"session": "s-gone", "host_id": "local_gone", "parent": "local_boss",
                         "started": "2026-11-03T20:05:00Z"}}
    tree = sessions.Tree(app, starts, {"s-brief": "s-boss"})
    assert tree.children["local_boss"] == ["s-brief", "local_gone", "local_late"]


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

def _iso_ago(seconds):
    return datetime.fromtimestamp(time.time() - seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
    good = {"at": _iso_ago(3600), "by": C_CLI, "host_id": CHILD, "machine": "po-test"}
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

def _budget(t, sid=M_CLI, **extra):
    out = io.StringIO()
    sys_stdout, sys.stdout = sys.stdout, out
    try:
        budget.hook_main([], stdin=io.StringIO(json.dumps({"session_id": sid, "transcript_path": str(t),
                                                           "cwd": str(t.parent), **extra})))
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


# --- the review of #34: findings 22 to 27 and 50 to 56 ---

NESTED = "eeeeeeee-0000-4000-8000-000000000005"


def _events(brain_home, *events):
    f = brain_home / "ledger" / f"events-{datetime.now(timezone.utc):%Y-%m}.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, "a", encoding="utf-8", newline="\n") as fh:
        fh.writelines(json.dumps(e) + "\n" for e in events)


def _call(tid, **inp):
    return {"type": "tool_use", "id": tid, "name": "mcp__ccd_session__start_session", "input": {"title": "x", **inp}}


def _watch(brain_home, sid):
    return json.loads((brain_home / "budget" / f"{sid}.json").read_text(encoding="utf-8"))


def test_a_proposal_or_a_refused_start_makes_no_master(app, tmp_path, brain_home, monkeypatch):
    """Finding 22: a proposal card (own_initiative, offer) and a call whose result is an error start nothing: the
    worker keeps its COST-1 checkpoint at 80 %. A proposal the owner then starts (``proposal_id``) counts."""
    _family(app)
    monkeypatch.setenv(sessions.HOST_ENV, CHILD)
    refused = {"type": "user", "timestamp": "2026-11-03T10:00:01Z", "toolUseResult": "Error: denied",
               "message": {"content": [{"type": "tool_result", "tool_use_id": "r1", "is_error": True,
                                        "content": "denied by a guard"}]}}
    t = _transcript(tmp_path, C_CLI, _prompt(SIDE + "Build wi-a. Context budget: 400k."),
                    _asst("m1", 100_000, _call("o1", initiation="own_initiative"), _call("o2", initiation="offer"),
                          _call("r1", initiation="user_asked")), refused)
    assert _budget(t, C_CLI) == ""
    state = _watch(brain_home, C_CLI)
    assert (state["starts"], state["offers"]) == (0, 2) and not budget.is_master(state)
    _transcript(tmp_path, C_CLI, _asst("m2", 325_000))
    text = _budget(t, C_CLI)
    assert text.startswith("Budget watch (COST-1)") and "checkpoint now: commit your work" in text
    assert "Master's watch" not in text
    _transcript(tmp_path, C_CLI, _asst("m3", 326_000, {"type": "tool_use", "id": "p1",
                                                       "name": "mcp__ccd_session__start_session",
                                                       "input": {"proposal_id": "task_1"}}))
    _budget(t, C_CLI)
    assert _watch(brain_home, C_CLI)["starts"] == 1


def test_a_proposal_the_owner_started_makes_a_master(app, tmp_path, brain_home, monkeypatch):
    """Finding 22: the app's files say whether the owner started a session from the card."""
    app(MASTER, M_CLI, title="Ada's worker")
    monkeypatch.setenv(sessions.HOST_ENV, MASTER)
    t = _transcript(tmp_path, M_CLI, _prompt("Work."), _asst("m1", 100_000, _call("o1", initiation="offer")))
    assert _budget(t) == "" and budget.master_of(M_CLI) is None
    app(CHILD, C_CLI, parent=MASTER, name="f1-tree")
    _transcript(tmp_path, M_CLI, _asst("m2", 720_000))
    text = _budget(t)
    assert text.startswith("Master's watch (ST-3)") and "1 live child(ren) of 1 started" in text


def test_a_state_from_before_the_masters_watch_asks_the_app(app, tmp_path, brain_home, monkeypatch):
    """Finding 53: a coordinator's state kept from before the watch (no ``starts``) asks the app at its next check,
    although that check feeds new records."""
    _family(app)
    monkeypatch.setenv(sessions.HOST_ENV, MASTER)
    t = _transcript(tmp_path, M_CLI, _prompt("Coordinate the wave."), _asst("m1", 100_000))
    _budget(t)
    f = brain_home / "budget" / f"{M_CLI}.json"
    state = json.loads(f.read_text(encoding="utf-8"))
    for k in ("starts", "kids", "master_budget", "master", "host_id"):
        state.pop(k, None)
    f.write_text(json.dumps(state), encoding="utf-8")
    _transcript(tmp_path, M_CLI, _asst("m2", 850_000))
    text = _budget(t)
    assert text.startswith("Master's watch (ST-3): this master's context is 850k tokens, 85 %")
    assert "1 live child(ren) of 2 started" in text and budget.master_of(M_CLI)["live"] == 1


def test_a_subagents_call_leaves_the_masters_notice_to_the_main_thread(app, tmp_path, brain_home, monkeypatch):
    """Finding 25: a subagent's PostToolUse (the master's session_id) does not use up the 80 % notice."""
    _family(app)
    monkeypatch.setenv(sessions.HOST_ENV, MASTER)
    t = _transcript(tmp_path, M_CLI, _prompt("Coordinate the wave."), _asst("m1", 600_000, _start(1)))
    _budget(t)
    _transcript(tmp_path, M_CLI, _asst("m2", 820_000))
    assert _budget(t, agent_id="agent-1") == ""
    assert _watch(brain_home, M_CLI)["warned"]["context"] == []
    assert "Start no new child. Hand over to a fresh master" in _budget(t)


def test_an_unarchived_app_child_with_a_recorded_end_stays_live(app, tmp_path, brain_home, monkeypatch):
    """Finding 24: the app resumes its own sessions on a message, so their SessionEnd does not make them dead to the
    master's watch, its draft or the cockpit (as brain sessions reads them)."""
    _family(app)
    _transcript(tmp_path, M_CLI, _prompt("Coordinate."), _asst("m1", 850_000, _start(1)))
    kid = _transcript(tmp_path, C_CLI, _prompt(SIDE + "Build."), _asst("m2", 40_000, {"type": "text", "text": "x"},
                                                                       stop="end_turn"))
    old = time.time() - 1860
    os.utime(kid, (old, old))
    _events(brain_home, {"at": _iso_ago(1800), "event": "session_end", "session_id": C_CLI, "reason": "other"})
    kids = budget.children({"host_id": MASTER})
    assert [k["live"] for k in kids] == [True, False]  # f2-old is archived
    assert budget.handover_draft(kids)[0].startswith(f"- f1-tree: app {CHILD}")
    rows = {r["session_id"]: r for r in cockpit.Sessions(lambda f: "lab").rows()}
    assert rows[M_CLI]["kids_live"] == 1
    assert sessions.alive({"session": "s-cli", "source": "ledger"}, {"s-cli": "2026-11-03T10:00:00Z"}) is False


def test_master_alerts_read_the_masters_family_now(app, brain_home):
    """Finding 26: the alert follows the tree, not the state file's age: archived children or an archived master
    close it at once; a master that waits on its live children for hours keeps it."""
    _family(app)
    d = brain_home / "budget"
    d.mkdir(parents=True, exist_ok=True)

    def state(sid, host, hours):
        f = d / f"{sid}.json"
        f.write_text(json.dumps({"v": 1, "session": sid, "master": {
            "pct": 85.0, "step": 80, "live": 3, "started": 3, "budget": 1_000_000, "host_id": host,
            "at": time.time() - hours * 3600}}), encoding="utf-8")
        t = time.time() - hours * 3600
        os.utime(f, (t, t))

    def keys():
        return {a.key: a.message for a in alerts.master_alerts(alerts.Config("brain"), datetime.now(timezone.utc))}

    state(M_CLI, MASTER, 8)  # 8 h without a tool call: waiting on its children
    state("s-old", "", 8)  # a master the tree does not know: its kept count, 6 h at most
    state("s-new", "", 1)
    got = keys()
    assert set(got) == {f"session:master:{MASTER}", "session:master:s-new"}
    assert "with 1 live child(ren)" in got[f"session:master:{MASTER}"]  # f1-tree; f2-old is archived
    app(CHILD, C_CLI, parent=MASTER, name="f1-tree", archived=True, title="F1 tree!")  # the owner archived it
    assert f"session:master:{MASTER}" not in keys()
    app(CHILD, C_CLI, parent=MASTER, name="f1-tree", title="F1 tree")
    app(MASTER, M_CLI, title="Ada's coordinator", archived=True)  # it handed over and was archived
    assert f"session:master:{MASTER}" not in keys()


def test_a_detached_session_is_no_longer_its_old_masters_child(app, brain_home):
    """Finding 27: lineageDetached takes a session out of its old master's family; a parent the app's file no longer
    names does not come back from the SessionStart event."""
    _family(app)
    app(GHOST, "dddddddd-0000-4000-8000-000000000004", parent=MASTER, name="f3-next", detached=True)
    app(CHILD, C_CLI, title="F1 tree")  # the app removed its spawnedFrom
    _events(brain_home, {"at": _iso_ago(60), "event": "session_start", "session_id": C_CLI, "host_id": CHILD,
                         "parent": MASTER, "task": "task_1", "name": "f1-tree"})
    tree = sessions.load(briefs=False)
    assert tree.role(GHOST) == "solo" and tree.nodes[GHOST]["detached_from"] == MASTER
    assert tree.nodes[GHOST]["name"] == "f3-next" and "parent" not in tree.nodes[GHOST]
    assert tree.role(CHILD) == "solo" and tree.nodes[CHILD]["name"] == "f1-tree"  # the name back, not the parent
    assert tree.children[MASTER] == [OTHER]
    assert [k["host_id"] for k in budget.children({"host_id": MASTER})] == [OTHER]


def test_the_brief_hash_gives_no_parent_back_to_a_session_the_app_knows(app, brain_home, monkeypatch, capsys):
    """Finding 27, as ``brain sessions`` loads the tree by default (with the briefs): the brief hash links a
    hand-over's fresh master to the session that started it, but the app detached it; and the app removed another's
    spawnedFrom. Neither comes back under its old master; a session the app never knew still takes the briefs'."""
    from brain import usage
    raw = sessions.Tree({"fapp": {"host_id": "fapp", "session": "fcli", "detached": True, "parent": "mapp"},
                         "mapp": {"host_id": "mapp", "session": "mcli"}}, {}, {"fcli": "mcli"})
    assert raw.role("fapp") == "solo" and raw.role("mapp") == "solo" and "parent" not in raw.nodes["fapp"]
    _family(app)
    app(GHOST, "dddddddd-0000-4000-8000-000000000004", parent=MASTER, name="f3-next", detached=True)
    app(CHILD, C_CLI, title="F1 tree")  # the app removed its spawnedFrom
    monkeypatch.setattr(usage, "load", lambda *a, **k: {})
    monkeypatch.setattr(usage, "link_families", lambda rows: {
        "dddddddd-0000-4000-8000-000000000004": M_CLI, C_CLI: M_CLI, "cli-only": M_CLI})
    tree = sessions.load()
    assert tree.role(GHOST) == "solo" and tree.role(CHILD) == "solo" and "parent" not in tree.nodes[GHOST]
    assert tree.children[MASTER] == ["cli-only", OTHER]  # a brief-only child has no start time: first
    assert tree.nodes["cli-only"]["parent_source"] == "briefs"
    assert cli.main(["sessions", "tree", MASTER, "--json"]) == 0  # the command's own load, briefs included
    (fam,) = json.loads(capsys.readouterr().out)
    assert [c["key"] for c in fam["children"]] == ["cli-only", OTHER]
    assert cli.main(["sessions", "show", "f3-next", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert (shown["role"], shown["parent"]) == ("solo", "")


def test_a_masters_earlier_transcript_raises_no_alert(app, brain_home):
    """Finding 26: a /clear gives the app's master a new transcript under the same app id; the earlier transcript's
    state (85 %) no longer raises the alert for days, the current transcript's own state decides."""
    app(MASTER, "ffffffff-0000-4000-8000-000000000006", title="Ada's coordinator")  # its transcript after /clear
    app(CHILD, C_CLI, parent=MASTER, name="f1-tree", title="F1 tree")
    d = brain_home / "budget"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{M_CLI}.json").write_text(json.dumps({"v": 1, "session": M_CLI, "master": {
        "pct": 85.0, "step": 80, "live": 1, "started": 1, "budget": 1_000_000, "host_id": MASTER,
        "at": time.time() - 3600}}), encoding="utf-8")
    assert alerts.master_alerts(alerts.Config("brain"), datetime.now(timezone.utc)) == []
    app(MASTER, M_CLI, title="Ada's coordinator")  # the same transcript: the alert stands
    (a,) = alerts.master_alerts(alerts.Config("brain"), datetime.now(timezone.utc))
    assert a.key == f"session:master:{MASTER}" and "1 live child(ren)" in a.message


def test_a_cli_session_started_from_a_desktop_session_keeps_its_own_identity(app, brain_home, monkeypatch):
    """Finding 50: a ``claude`` started from a desktop session's shell inherits its CLAUDE_CODE_HOST_SESSION_ID; the
    app's file of that id names another transcript, so the nested session takes neither its id nor its place."""
    _family(app)
    monkeypatch.setenv(sessions.HOST_ENV, CHILD)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", NESTED)  # what the hooks of the nested session see
    assert sessions.host_for(NESTED) == "" and sessions.host_for(C_CLI) == CHILD
    assert sessions.stamp() == {} and decisions.who() == {"session": NESTED}
    capture.main(["session-start"], stdin=io.StringIO(json.dumps({"session_id": NESTED, "source": "startup"})))
    (ev,) = [json.loads(x) for f in (brain_home / "ledger").glob("events-*.jsonl")
             for x in f.read_text(encoding="utf-8").splitlines()]
    assert ev["session_id"] == NESTED and not {"host_id", "parent", "name", "task"} & set(ev)
    tree = sessions.load(briefs=False)
    assert tree.key_of(NESTED) == NESTED and tree.key_of(C_CLI) == CHILD
    assert capture._tree_fields(NESTED) == {}
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", C_CLI)
    assert sessions.stamp()["host_id"] == CHILD


def test_the_report_reads_the_wrap_up_of_its_last_turn_only():
    """Finding 51: a blocked wrap-up of a turn whose question was answered since is not this turn's state."""
    wrap = {"type": "tool_use", "id": "w1", "name": sessions.WRAP_UP,
            "input": {"recap": "PR #12 open, CI green.", "ask": "Merge PR #12?", "blocked": True}}
    recs = [_prompt("Open the PR."), _asst("m1", 1_000, wrap),
            {"type": "system", "subtype": "stop_hook_summary", "timestamp": "2026-11-03T10:01:00Z"},
            _prompt("Yes, merge it."), _asst("m2", 1_000, {"type": "text", "text": "Merged #12."}, stop="end_turn")]
    first = sessions.build_report("s-1", recs[:3], {}, {}, at="2026-11-03T10:01:00Z")
    assert first["blocked"] is True and first["waits_on"] == "Merge PR #12?"
    rep = sessions.build_report("s-1", recs, {}, {}, at="2026-11-03T10:05:00Z")
    assert rep["turn"] == "idle" and rep["blocked"] is False
    assert "waits_on" not in rep and "recap" not in rep


def test_the_handover_draft_reads_each_childs_state_now(app, tmp_path):
    """Finding 52: a child whose last report waits on an answered question and that works now is listed as running;
    one whose report says idle and that asks the owner now, as asking."""
    _family(app)
    sessions.write_report(C_CLI, {"v": 1, "session": C_CLI, "at": "2026-11-03T10:00:00Z", "turn": "asking",
                                  "blocked": True, "items": ["wi-lab-a"], "waits_on": "Merge it?"})
    _transcript(tmp_path, C_CLI, _prompt(SIDE + "Build."), _asst("m1", 40_000))  # a Read call running
    kids = budget.children({"host_id": MASTER})
    (line,) = budget.handover_draft(kids)
    assert line.endswith("items wi-lab-a; running")
    sessions.write_report(C_CLI, {"v": 1, "session": C_CLI, "at": "2026-11-03T10:05:00Z", "turn": "idle",
                                  "blocked": False, "items": ["wi-lab-a"]})
    _transcript(tmp_path, C_CLI, {"type": "user", "timestamp": "2026-11-03T10:06:00Z", "toolUseResult": "ok",
                                  "message": {"content": [{"type": "tool_result", "tool_use_id": "t-m1"}]}},
                _asst("m2", 41_000, {"type": "tool_use", "id": "q1", "name": "AskUserQuestion", "input": {}}))
    assert budget.handover_draft(kids)[0].endswith("items wi-lab-a; asking")


def test_the_tree_keeps_hours_for_sessions_the_app_does_not_know(brain_home):
    """Finding 55: ledger-only and brief-only families outside --hours are not drawn as recent."""
    starts = {"aaaa0001": {"session": "aaaa0001", "started": "2026-10-02T10:00:00Z"},
              "bbbb0002": {"session": "bbbb0002", "started": "2026-10-02T11:00:00Z", "parent": "aaaa0001"}}
    tree = sessions.Tree(None, starts, {"cccc0003": "dddd0004"})
    assert sessions.families(tree, hours=24) == [] == sessions.recent_rows(tree, 24)
    assert sessions.families(tree, hours=1e9) == ["aaaa0001", "dddd0004"]


def test_sessions_options_before_the_subcommand_are_kept(app, capsys):
    """Finding 56: ``brain sessions --json tree`` gives JSON; an option after the subcommand still wins."""
    _family(app)
    assert cli.main(["sessions", "--json", "tree"]) == 0
    assert [r["host_id"] for r in json.loads(capsys.readouterr().out)] == [MASTER]
    args = cli.build_parser().parse_args(["sessions", "--all", "--hours", "2", "--no-briefs", "tree"])
    assert (args.all, args.hours, args.no_briefs, args.json) == (True, 2.0, True, False)
    args = cli.build_parser().parse_args(["sessions", "--hours", "2", "show", "x", "--hours", "5", "--json"])
    assert (args.hours, args.json, args.all) == (5.0, True, False)


def test_check_warns_on_an_old_stamp_whose_session_left_the_app_and_the_ledger(app, monkeypatch):
    """Finding 23: a stamp older than REFUSE_DAYS whose session is gone can no longer be checked: a warning, not a
    refusal that would keep brain check red on an append-only record."""
    _family(app)
    monkeypatch.setenv("BRAIN_HOST", "po-test")
    old = {"at": _iso_ago(40 * 86400), "by": "s-gone", "host_id": GHOST, "machine": "po-test"}
    refused, warned = sessions.unknown_ids([(Path("e.yaml"), {"id": "ddr-e", "asked": old})])
    assert refused == [] and warned[0].startswith(f"ddr-e: asked names {GHOST}, which matches no session on po-test")
    assert "stamped over 7 days ago" in warned[0]
    recent = {**old, "at": _iso_ago(86400)}
    assert sessions.unknown_ids([(Path("e.yaml"), {"id": "ddr-e", "asked": recent})])[0]
