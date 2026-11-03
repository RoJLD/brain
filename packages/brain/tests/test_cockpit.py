"""wi-brain-tui-cockpit: the cockpit's data layer (brain.cockpit), its text view and brain tui."""

import io
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

import brain
from brain import alerts, cli, cockpit, digest, plan, projects, status

from test_project_views import _status_project

UPDATE, WRAP_UP = "mcp__ccd_turn__update_plan", "mcp__ccd_turn__wrap_up"
ITEMS = [{"content": "Read", "status": "in_progress"}, {"content": "Write", "status": "pending"},
         {"content": "Test", "status": "pending"}]


@pytest.fixture(autouse=True)
def claude_dir(tmp_path, monkeypatch):
    """Transcripts under a temporary CLAUDE_CONFIG_DIR, never the owner's."""
    d = tmp_path / "claude"
    (d / "projects").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(d))
    return d / "projects"


def _use(name, inp=None, i=0):
    return {"type": "assistant", "message": {"model": "claude-opus-5-5", "content": [
        {"type": "tool_use", "id": f"toolu_{name}_{i}", "name": name, "input": inp or {}}]}}


def _text(stop="end_turn", **usage):
    return {"type": "assistant", "effort": "high", "message": {"model": "claude-opus-5-5", "stop_reason": stop,
                                                               "content": [{"type": "text", "text": "ok"}],
                                                               "usage": usage}}


RESULT = {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "x", "content": "ok"}]}}
PROMPT = {"type": "user", "message": {"content": "go on"}}
STOP = {"type": "system", "subtype": "stop_hook_summary"}


def test_duration():
    assert [cockpit.duration(x) for x in ("500ms", "2s", "2", "5m", "5min", "1h", "1.5s")] == [
        0.5, 2, 2, 300, 300, 3600, 1.5]
    with pytest.raises(ValueError):
        cockpit.duration("soon")


def test_turn_reads_where_the_session_is_from_its_last_records():
    assert cockpit.turn([_use("Bash"), RESULT, _text(), STOP]) == "idle"
    assert cockpit.turn([PROMPT, _use(WRAP_UP, {"blocked": True}), RESULT, _text(), STOP]) == "asking"
    assert cockpit.turn([_use(WRAP_UP, {"blocked": True}), STOP, PROMPT, _text(), STOP]) == "idle"  # an older turn
    assert cockpit.turn([_use("AskUserQuestion")]) == "asking"
    assert cockpit.turn([_use("AskUserQuestion"), RESULT]) == "active"  # answered: the turn goes on
    assert cockpit.turn([_use("Bash")]) == cockpit.turn([PROMPT]) == cockpit.turn([]) == "active"
    assert cockpit.turn([_text(), {"type": "system", "subtype": "compact_boundary"}]) == "idle"
    assert cockpit.turn([_text(stop="tool_use")]) == "active"
    assert cockpit.state("active", 60) == "running" and cockpit.state("active", 3600) == "stale"
    assert cockpit.state("idle", 3600) == "idle" and cockpit.state("active", 1, ended=True) == "ended"


def test_meta_and_tail(tmp_path):
    records = [{"type": "custom-title", "customTitle": "My task"},
               {"type": "user", "cwd": "/w/demo", "gitBranch": "feat/x", "message": {"content": "go"}},
               _text(input_tokens=10, cache_read_input_tokens=1000, cache_creation_input_tokens=90),
               {"type": "assistant", "message": {"model": "<synthetic>", "content": []}}]
    assert cockpit.meta(records) == {"title": "My task", "folder": "/w/demo", "branch": "feat/x",
                                     "model": "claude-opus-5-5", "effort": "high", "context": 1100}
    f = tmp_path / "t.jsonl"
    f.write_bytes(b'{"type": "user", "x": "' + b"y" * 300 + b'"}\n' + json.dumps(STOP).encode() + b'\n{"type": "us')
    assert cockpit.tail(f, max_bytes=100) == [STOP]  # the cut first line and the partial last one are left out
    assert len(cockpit.tail(f)) == 2 and cockpit.tail(tmp_path / "gone.jsonl") == []


def _transcript(claude_dir, sid, records, age_s=0.0, folder="E--w-demo"):
    f = claude_dir / folder / f"{sid}.jsonl"
    f.parent.mkdir(exist_ok=True)
    f.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    t = time.time() - age_s
    os.utime(f, (t, t))
    return f


def test_sessions_panel(claude_dir, brain_home):
    here = {"type": "user", "cwd": "/w/demo/.claude/worktrees/x", "gitBranch": "claude/x", "message": {"content": "go"}}
    _transcript(claude_dir, "s-run", [here, _use(UPDATE, {"items": ITEMS}), _use(UPDATE, {"advance": True}, 1),
                                      _use("Bash")], age_s=30)
    _transcript(claude_dir, "s-ask", [here, _use(WRAP_UP, {"blocked": True}), RESULT, _text(), STOP], age_s=600)
    _transcript(claude_dir, "s-stale", [here, _use("Bash")], age_s=3600)
    _transcript(claude_dir, "s-idle", [{**here, "cwd": "/elsewhere"}, _text(), STOP], age_s=7200)
    _transcript(claude_dir, "s-end", [here, _text(), STOP], age_s=60)
    _transcript(claude_dir, "s-old", [here, _text(), STOP], age_s=3 * 86400)
    (claude_dir / "E--w-demo" / "s-run" / "subagents").mkdir(parents=True)  # a subagent's is not a session
    _transcript(claude_dir, "agent-1", [here], folder="E--w-demo/s-run/subagents")
    (brain_home / "ledger").mkdir(parents=True)
    now = time.time()
    events = [(3600, "session_start", "s-end"), (50, "session_end", "s-end"),
              (7200, "session_end", "s-run"), (3600, "session_start", "s-run"),  # ended, then started again
              (7200, "session_end", "s-stale")]  # resumed without a start event: it wrote after its end
    (brain_home / "ledger" / f"events-{cockpit._iso(now)[:7]}.jsonl").write_text("".join(
        json.dumps({"at": cockpit._iso(now - ago), "event": ev, "session_id": sid}) + "\n" for ago, ev, sid in events)
        + "not json\n", encoding="utf-8")
    plan.capture({"session_id": "s-ask", "tool_name": UPDATE, "tool_input": {"items": ITEMS}})  # the hook's file wins
    (brain_home / "sessions" / "s-ask.json").write_text(json.dumps(
        {"title": "From the snapshot", "tokens": {"output": 4500}, "context": {"budget": 600000, "last": 1}}),
        encoding="utf-8")
    sess = cockpit.Sessions(lambda folder: "demo" if "/w/demo" in folder else "")
    rows = sess.rows()
    assert [(r["session_id"], r["state"], r["project"]) for r in rows] == [
        ("s-ask", "asking", "demo"), ("s-run", "running", "demo"), ("s-stale", "stale", "demo"),
        ("s-idle", "idle", cockpit.OUTSIDE), ("s-end", "ended", "demo")]
    run, ask = rows[1], rows[0]
    assert run["step"] == "2/3 Write" and run["plan"]["source"] == "transcript" and run["branch"] == "claude/x"
    assert ask["step"] == "1/3 Read" and ask["plan"]["source"] == "hook" and ask["title"] == "From the snapshot"
    assert (ask["output_tokens"], ask["budget"], ask["effort"]) == (4500, 600000, "high")
    assert [r["session_id"] for r in sess.rows(only={"demo"})] == ["s-ask", "s-run", "s-stale", "s-end"]
    assert sess.rows(only=set()) == []


def _cockpit(tmp_path, monkeypatch, store):
    _status_project(tmp_path, monkeypatch, store)
    monkeypatch.setattr(status, "queue_rows", lambda projs, every, root=None, **kw: [
        {"project": "demo", "counts": {"decision": 1, "action": 0, "permission": 0}, "guard_refusals": 0,
         "entries": [{"id": "ddr-a", "kind": "decision", "source": "ddr", "title": "Pick one", "since": "2026-11-01",
                      "age_days": 1, "blocking": True, "unblocks": 2, "unblocked": ["wi-one"],
                      "recommended": "A", "how": "brain decision answer ddr-a <option>"}]},
        {"project": cockpit.OUTSIDE, "counts": {"permission": 1}, "entries": [{"id": "perm-1"}]}])
    return cockpit.Cockpit([projects.load()["demo"]])


def test_file_panels_are_read_again_only_when_their_files_change(tmp_path, monkeypatch, store):
    cp = _cockpit(tmp_path, monkeypatch, store)
    assert cp.refresh() == {"sessions", "queue", "milestones", "frontier"}
    assert cp.refresh() == set()
    with (store / "nodes" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write("- {id: wi-six, type: WorkItem, status: todo, title: \"Sixth\", props: {priority_proposed: P1}}\n")
    assert cp.refresh() == {"queue", "milestones", "frontier"}
    p = cp.snapshot()["panels"]
    assert [(i["priority"], i["id"]) for i in p["frontier"]["projects"][0]["items"]] == [
        ("P0", "wi-one"), ("P1", "wi-three"), ("P1?", "wi-six")]  # wi-five waits on wi-two
    (ms,) = p["milestones"]["projects"][0]["pending"]
    assert (ms["id"], ms["done"], ms["items"]) == ("ms-x", 1, 2) and p["milestones"]["projects"][0]["reached"] == 1
    assert p["queue"]["denials_read"] is False and p["queue"]["projects"][0]["entries"][0]["id"] == "ddr-a"
    assert [g["project"] for g in p["queue"]["projects"]] == ["demo"] and p["queue"]["outside"] == 1  # as brain queue
    assert p["sessions"] == {"hours": cockpit.HOURS, "rows": []} and "audit" not in p


def test_probe_fills_audit_health_and_digest(tmp_path, monkeypatch, store, brain_home):
    cp = _cockpit(tmp_path, monkeypatch, store)
    monkeypatch.setattr(status, "audit_of", lambda p, detail=0: {
        "counts": {"P0": 1, "P1": 2, "P2": 0, "info": 3}, "repos": 1, "unreadable": [],
        "by_repo": [{"repo": "demo", "counts": {"P0": 1}}],
        "top": [{"repo": "demo", "severity": "P0", "check": "cmd.documented", "unit": "x", "why": "not in the README"}]})
    monkeypatch.setattr(status, "_probes", lambda root, quick: (None, None))
    monkeypatch.setattr(alerts, "read_scheduler", lambda cfgs: {})
    seen = {}
    monkeypatch.setattr(status, "alerts_of", lambda p, measured, stack_reg, sched, last: seen.update(m=measured) or {
        "open": 1, "counts": {"error": 1}, "last_pass": None, "alerts": [
            {"level": "error", "key": "task:cycle:missed", "source": "scheduler", "subject": "cycle",
             "message": "2 passes missed", "since": "2026-11-02T08:00:00Z"}]})
    written = brain_home / "digest" / "demo" / "2026-10-26_2026-11-02.md"
    written.parent.mkdir(parents=True)
    written.write_text("# Digest of demo\n\n## Items closed\n- wi-four\n", encoding="utf-8")
    assert cp.refresh(probe=True) == set(cockpit.PANELS)
    snap = cp.snapshot()
    assert seen["m"]["audit"]["counts"]["P0"] == 1 and seen["m"]["stacks"] == []  # what the probe measured, once
    assert cockpit.table("alerts", snap["panels"]["alerts"]) == [("error", "demo", "task:cycle:missed",
                                                                  "2026-11-02 08:00", "2 passes missed")]
    assert snap["probed_at"] and snap["panels"]["queue"]["denials_read"] is True
    d = snap["panels"]["digest"]["projects"][0]
    assert (d["digest"], d["written"], d["records"]["journals"][0]["last"]) == ("2026-10-26_2026-11-02", True,
                                                                                 "2026-11-02")
    assert snap["panels"]["health"]["exec"]["runs"] == 0
    text = "\n".join(cockpit.render(snap))
    for line in ("Ada's queue (1: 1 decision, 0 action, 0 permission); 1 denial(s) outside every project (--all)",
                 "    2 decision         demo         1 d  ddr-a [blocking]: Pick one -> A",
                 "Alerts (1 open, 1 error)", "  ERROR    demo       task:cycle:missed: 2 passes missed",
                 "Milestones (1 reached, 1 pending)", "  demo         1/2   #####.....  ms-x: Milestone X",
                 "Frontier (2 startable, 2 of them P0/P1)", "  demo: P0 1, P1 2, P2 0, info 3 (1 repo(s))",
                 "    P0 demo cmd.documented x: not in the README", "  demo: stacks no stack declared; code index no repo "
                 "declared", "  exec ledger: 0 run(s) in 7 d, 0 failed, 0 regression(s)",
                 "Digest demo (2026-10-26_2026-11-02, written); journal journal.md 2026-11-02; 3 DDR, 0 SR, 2 AR",
                 "  ## Items closed"):
        assert line in text, line
    monkeypatch.setattr(digest, "latest", lambda name: None)  # none written: last week's, built offline
    monkeypatch.setattr(digest, "build", lambda p, offline=False: f"# built for {p.name}, offline={offline}")
    assert cockpit.digest_of(projects.load()["demo"])["text"] == "# built for demo, offline=True"


def test_tables_and_headings(tmp_path, monkeypatch, store):
    cp = _cockpit(tmp_path, monkeypatch, store)
    cp.refresh()
    p = cp.snapshot()["panels"]
    assert cockpit.table("queue", p["queue"]) == [("2", "decision", "demo", "1 d", "Pick one -> A",
                                                    "ddr-a [blocking]")]
    assert cockpit.table("milestones", p["milestones"]) == [("demo", "1/2", "#####.....", "ms-x", "Milestone X")]
    row = cockpit.table("frontier", p["frontier"])[0]  # its age: from the idea's date (Ada, 2026-10-30) to today
    assert row[:4] + row[5:] == ("P0", "demo", "1", "x", "wi-one", "First: with a colon, and a comma")
    assert row[4].endswith(" d") and cockpit.table("frontier", p["frontier"], project=False)[0] == row[:1] + row[2:]
    for name in cockpit.COLUMNS:
        assert all(len(row) == len(cockpit.COLUMNS[name]) for row in cockpit.table(name, p.get(name)))
    row = {"state": "running", "session_id": "abcdef123456", "project": "demo", "step": "", "model": "claude-x",
           "effort": "", "context": 1_250_000, "budget": 600_000, "output_tokens": None, "age_s": 5, "title": "",
           "branch": "b"}
    assert cockpit.table("sessions", {"rows": [row]}) == [
        ("running", "abcdef12", "demo", "-", "x", "-", "1.2M/600k", "-", "now", "b")]
    assert cockpit.heading("sessions", None) == "Sessions (0 in the last 24 h)"
    assert cockpit.heading("audit", None) == "Audit debt: not probed yet"
    assert cockpit.heading("alerts", None) == "Alerts: not probed yet" and cockpit.table("alerts", None) == []
    assert cockpit.heading("milestones", p["milestones"]) == "Milestones (1 reached, 1 pending)"
    with pytest.raises(KeyError):
        cockpit.table("audit", {})


def test_watch_draws_the_text_view(tmp_path, monkeypatch, store):
    cp = _cockpit(tmp_path, monkeypatch, store)
    monkeypatch.setattr(cp, "probe", lambda: None)
    out = io.StringIO()
    assert cockpit.watch(cp, refresh_s=0.01, ticks=2, out=out) == 0
    assert out.getvalue().count("brain cockpit: demo") == 1  # drawn once: nothing changed at the second tick


def test_brain_tui_once_and_json(tmp_path, monkeypatch, store, capsys):
    _cockpit(tmp_path, monkeypatch, store)
    assert cli.main(["tui", "--project", "demo", "--once", "--quick"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("brain cockpit: demo; files read ") and "probes not run" in out
    assert "Audit debt: not probed yet" in out
    assert cli.main(["tui", "--project", "demo", "--json", "--quick"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["cockpit"] == 1 and data["scope"] == "demo" and set(data["panels"]) == {
        "sessions", "queue", "milestones", "frontier"}
    with pytest.raises(SystemExit):
        cli.main(["tui", "--refresh", "100ms"])


def test_brain_tui_without_the_extra_falls_back_to_the_text_view(tmp_path, monkeypatch, store, capsys):
    _cockpit(tmp_path, monkeypatch, store)
    for name in [m for m in sys.modules if m.startswith("textual.")]:  # imported by test_tui, say
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setitem(sys.modules, "textual", None)  # the tui extra not installed
    monkeypatch.delitem(sys.modules, "brain.tui", raising=False)
    monkeypatch.delattr(brain, "tui", raising=False)
    seen = {}
    monkeypatch.setattr(cockpit, "watch", lambda cp, refresh_s, probe_s, **kw: seen.update(r=refresh_s, p=probe_s)
                        or 0)
    assert cli.main(["tui", "--project", "demo", "--refresh", "500ms", "--probe", "1m"]) == 0
    assert seen == {"r": 0.5, "p": 60.0}
    assert "needs the tui extra" in capsys.readouterr().err


# --- the view: the project selector, filters, sort, search, the remembered state (spec 2026-11-02 cockpit-ux) ---

def test_frontier_rows_carry_their_milestone_what_they_unblock_and_their_age():
    from brain import resume
    nodes = {n["id"]: n for n in [
        {"id": "ms-demo-x", "type": "Milestone", "status": "pending"},
        {"id": "wi-a", "type": "WorkItem", "status": "todo", "title": "A",
         "props": {"priority": "P2", "idea": "Ada, 2026-10-30 (in a chat)"}},
        {"id": "wi-b", "type": "WorkItem", "status": "todo", "title": "B",
         "props": {"priority_proposed": "P1", "milestone_proposed": "ms-demo-y"}},
        {"id": "wi-c", "type": "WorkItem", "status": "todo", "title": "C waits on A"},
        {"id": "wi-d", "type": "WorkItem", "status": "done", "title": "D, done"},
        {"id": "wi-e", "type": "WorkItem", "status": "todo", "title": "E waits on C"}]}
    edges = [{"from": "wi-a", "to": "ms-demo-x", "type": "part_of"}, {"from": "wi-c", "to": "wi-a", "type": "depends_on"},
             {"from": "wi-e", "to": "wi-c", "type": "gated_by"}, {"from": "wi-d", "to": "wi-a", "type": "depends_on"}]
    rows = cockpit.frontier_rows(resume.Store(nodes, edges), today=datetime(2026, 11, 2, tzinfo=timezone.utc))
    assert [(r["id"], r["priority"], r["milestone"], r["unblocks"], r["since"], r["age_days"]) for r in rows] == [
        ("wi-b", "P1?", "ms-demo-y?", 0, "", None),  # a proposed P1 before a set P2
        ("wi-a", "P2", "ms-demo-x", 3, "2026-10-30", 3)]  # ms-demo-x, wi-c and wi-e through it; wi-d is done
    assert cockpit.short_milestone("ms-demo-x", "demo") == "x" and cockpit.short_milestone("ms-y?", "demo") == "y?"


def _session(sid, state, project, age_s, context=None):
    return {"session_id": sid, "state": state, "project": project, "age_s": age_s, "context": context, "step": "",
            "title": f"Task {sid}", "branch": "b", "model": "claude-x", "effort": "", "budget": None,
            "output_tokens": None}


def _entry(eid, kind, unblocks, age, title, **kw):
    return {"id": eid, "kind": kind, "unblocks": unblocks, "age_days": age, "title": title, "since": "", **kw}


def _item(iid, priority, milestone, unblocks, age, title):
    return {"id": iid, "priority": priority, "milestone": milestone, "unblocks": unblocks, "age_days": age,
            "since": "", "title": title}


PANELS = {
    "sessions": {"hours": 24, "rows": [_session("s-ask", "asking", "demo", 30), _session("s-run", "running", "other", 5,
                                                                                         context=900_000),
                                       _session("s-end", "ended", "demo", 60), _session("s-idle", "idle", "demo", 600)]},
    "queue": {"projects": [
        {"project": "demo", "entries": [_entry("ddr-a", "decision", 2, 1, "Pick a cockpit layout"),
                                        _entry("wi-x:needs", "action", 5, 0, "Ada's go-ahead", category="scheduled")]},
        {"project": "other", "entries": [_entry("ddr-q", "decision", 3, 4, "Exchange data terms")]}]},
    "frontier": {"projects": [
        {"project": "demo", "items": [_item("wi-one", "P0", "ms-demo-x", 1, 2, "First"),
                                      _item("wi-two", "P2", "", 4, None, "Second, the TUI"),
                                      _item("wi-three", "", "ms-demo-x?", 0, 9, "Third")]},
        {"project": "other", "items": [_item("wi-q", "P1?", "ms-q", 0, 10, "Other item")]}]},
}


def _ids(name, view=None, search=""):
    return [r.get("session_id") or r["id"] for r in cockpit.shown(name, PANELS[name], view, search)]


def test_views_filter_sort_and_search_the_tables():
    assert _ids("sessions") == ["s-ask", "s-run", "s-end", "s-idle"]  # no view: everything, in the panel's order
    assert _ids("sessions", {}) == ["s-ask", "s-run", "s-idle"]  # the defaults: not ended, by state
    assert _ids("sessions", {"state": "all", "sort": "age"}) == ["s-run", "s-ask", "s-end", "s-idle"]
    assert _ids("sessions", {"state": "ended"}) == ["s-end"]
    assert _ids("sessions", {"sort": "context"})[0] == "s-run" and _ids("sessions", {"sort": "project"})[-1] == "s-run"
    assert _ids("queue", {}) == ["wi-x:needs", "ddr-q", "ddr-a"]  # by what each unblocks, across the projects
    assert _ids("queue", {"kind": "decision"}) == ["ddr-q", "ddr-a"]
    assert _ids("queue", {"sort": "age"}) == ["ddr-q", "ddr-a", "wi-x:needs"]  # the oldest first
    assert _ids("queue", {"sort": "age", "reverse": True}) == ["wi-x:needs", "ddr-a", "ddr-q"]
    assert _ids("frontier", {}) == ["wi-one", "wi-q", "wi-two", "wi-three"]  # by priority, a proposed one after
    assert _ids("frontier", {"priority": "P0-P1"}) == ["wi-one", "wi-q"]
    assert _ids("frontier", {"priority": "none"}) == ["wi-three"]
    assert _ids("frontier", {"milestone": "ms-demo-x"}) == ["wi-one", "wi-three"]  # a proposed one too
    assert _ids("frontier", {"milestone": "none"}) == ["wi-two"]
    assert _ids("frontier", {"sort": "unblocks"}) == ["wi-two", "wi-one", "wi-q", "wi-three"]
    assert _ids("frontier", {"sort": "age"}) == ["wi-q", "wi-three", "wi-one", "wi-two"]  # an unknown age last
    assert _ids("frontier", {"sort": "milestone"})[:2] == ["wi-one", "wi-three"]
    assert _ids("frontier", {}, search="the TUI") == ["wi-two"] and _ids("queue", {}, search="OTHER exchange") == [
        "ddr-q"]  # every word, case ignored, the project too
    assert _ids("frontier", {"sort": "nope", "priority": "P9", "reverse": 1}) == list(
        reversed(_ids("frontier", {})))  # an unknown value is left out
    assert cockpit.choices("frontier", "milestone", PANELS["frontier"]) == ("all", "none", "ms-demo-x", "ms-q")
    assert cockpit.choices("queue", "kind", None) == ("all", "decision", "action", "permission")
    assert cockpit.note("sessions", PANELS["sessions"], {}) == "3 of 4 shown; state open"
    assert cockpit.note("frontier", PANELS["frontier"], {"priority": "P0-P1", "sort": "age"}, "first") == (
        "1 of 4 shown; priority P0-P1; search 'first'; sort age")
    assert cockpit.note("queue", PANELS["queue"], {}, sort=True) == "sort unblocks"
    assert cockpit.note("queue", PANELS["queue"], None) == "" and cockpit.note("alerts", None, None, "x") == (
        "search 'x'")
    assert cockpit.table("queue", PANELS["queue"], {"kind": "action"}, project=False) == [
        ("5", "action:scheduled", "0 d", "Ada's go-ahead", "wi-x:needs")]
    assert cockpit.row_key("queue", cockpit.entries("queue", PANELS["queue"])[2]) == "other/ddr-q"
    lines = cockpit.render({"scope": "all", "panels": PANELS}, views={"frontier": {"priority": "P0-P1"}})
    assert "Frontier (4 startable, 1 of them P0/P1) [2 of 4 shown; priority P0-P1]" in lines
    assert "Sessions (4 in the last 24 h, 1 asking, 1 running, 1 idle, 1 ended) [3 of 4 shown; state open]" in lines
    assert not any("s-end" in x for x in lines) and any("s-end" in x for x in cockpit.render(
        {"scope": "all", "panels": PANELS}))  # no views: everything


def test_parse_view_and_the_remembered_state(brain_home):
    assert cockpit.parse_view(["frontier:-unblocks", "queue:age"], ["sessions:state=all", "frontier:milestone=ms-x",
                                                                    "queue:kind=decision"]) == {
        "frontier": {"sort": "unblocks", "reverse": True, "milestone": "ms-x"},
        "queue": {"sort": "age", "reverse": False, "kind": "decision"}, "sessions": {"state": "all"}}
    for sorts, filters in ((["frontier"], []), (["alerts:level"], []), (["queue:priority"], []),
                           ([], ["queue:kind=idea"]), ([], ["frontier:status=todo"]), ([], ["sessions:state="])):
        with pytest.raises(ValueError):
            cockpit.parse_view(sorts, filters)
    assert cockpit.load_state() == {}
    assert cockpit.save_state({"scope": "other", "panels": {"queue": {"kind": "decision"}}})
    state = cockpit.load_state()
    assert state["scope"] == "other" and state["panels"]["queue"] == {"sort": "unblocks", "reverse": False,
                                                                      "kind": "decision"}
    assert json.loads(cockpit.state_path().read_text(encoding="utf-8"))["cockpit"] == 1
    cockpit.state_path().write_text('{"scope": 3, "panels": {"queue": {"kind": "idea"}, "audit": {}, "frontier": 1}}',
                                    encoding="utf-8")
    assert cockpit.load_state() == {"panels": {"queue": cockpit.view_of("queue")}}  # what it does not know is left out
    cockpit.state_path().write_text("not json", encoding="utf-8")
    assert cockpit.load_state() == {}
    assert cockpit.save_state({}, path=brain_home / "missing" / "x" / "tui.json")  # its folder is made
    blocked = brain_home / "file"
    blocked.write_text("", encoding="utf-8")
    assert cockpit.save_state({}, path=blocked / "tui.json") is False  # never raised


def test_the_project_selector_switches_the_scope_and_keeps_each_probe(tmp_path, monkeypatch, store):
    cp = _cockpit(tmp_path, monkeypatch, store)
    calls = []
    monkeypatch.setattr(status, "audit_of", lambda p, detail=0: calls.append(p.name) or {
        "counts": {"P0": 1}, "repos": 1, "unreadable": [], "by_repo": [], "top": []})
    monkeypatch.setattr(status, "_probes", lambda root, quick: (None, None))
    monkeypatch.setattr(alerts, "read_scheduler", lambda cfgs: {})
    monkeypatch.setattr(status, "alerts_of", lambda p, m, reg, sched, last: {"open": 0, "counts": {}, "alerts": []})
    assert set(cp.choices) == {"demo", "far"} and cp.scope == "demo" and not cp.multi
    assert cp.needs_probe()
    cp.refresh(probe=True)
    assert calls == ["demo"] and not cp.needs_probe() and cp.snapshot()["probed_at"]
    cp.select("all")
    assert (cp.scope, cp.every, cp.multi) == ("all", True, True)
    assert cp.refresh() == set(cockpit.PANELS)  # everything drawn again for the new scope
    snap = cp.snapshot()
    assert [g["project"] for g in snap["panels"]["audit"]["projects"]] == ["demo"]  # its last probe, kept
    assert not cp.needs_probe() and calls == ["demo"]  # far is not on this machine: nothing to probe
    assert [g["project"] for g in snap["panels"]["frontier"]["projects"]] == ["demo"]
    cp.select("demo")
    assert cp.scope == "demo" and cp.refresh() == set(cockpit.PANELS) and calls == ["demo"]
    with pytest.raises(KeyError):
        cp.select("nowhere")


def test_brain_tui_starts_from_the_remembered_scope_and_views(tmp_path, monkeypatch, store, capsys):
    root = _cockpit(tmp_path, monkeypatch, store).projs[0].root
    seen = {}
    monkeypatch.setattr(cockpit, "watch", lambda cp, refresh_s, probe_s, views=None, search="", tz=None: seen.update(
        scope=cp.scope, views=views, search=search, tz=tz) or 0)
    assert cli.main(["tui", "--project", "demo", "--plain", "--sort", "frontier:-unblocks", "--filter",
                     "queue:kind=decision", "--search", "pick"]) == 0
    assert seen["scope"] == "demo" and seen["views"]["frontier"] == {"sort": "unblocks", "reverse": True}
    assert seen["search"] == "pick"
    state = cockpit.load_state()
    assert state["scope"] == "demo" and state["panels"]["queue"]["kind"] == "decision"
    assert state["panels"]["frontier"]["reverse"] is True
    cockpit.save_state({**state, "scope": "all"})
    assert cli.main(["--root", str(root), "tui", "--plain"]) == 0
    assert seen["scope"] == "all" and seen["views"]["queue"]["kind"] == "decision"  # no flag: what it last showed
    assert cli.main(["--root", str(root), "tui", "--plain", "--reset"]) == 0
    assert seen["scope"] == "demo" and seen["views"] == {n: {} for n in cockpit.SORTS}  # the defaults
    cockpit.save_state({"scope": "gone", "panels": {}})
    assert cli.main(["--root", str(root), "tui", "--plain"]) == 0 and seen["scope"] == "demo"  # no longer registered
    cockpit.save_state({"scope": "all", "panels": {"queue": {"kind": "action"}}})
    assert cli.main(["--root", str(root), "tui", "--once", "--quick", "--filter", "queue:kind=permission"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("brain cockpit: demo;")  # --once: the flags only, never the remembered state
    assert ("Ada's queue (1: 1 decision, 0 action, 0 permission); denied calls read at the first probe; 1 denial(s) "
            "outside every project (--all) [0 of 1 shown; kind permission]\n") in out
    assert "Sessions (0 in the last 24 h)\n" in out  # a default filter is named only when it hides a row
    with pytest.raises(SystemExit):
        cli.main(["tui", "--project", "demo", "--once", "--sort", "queue:priority"])


def test_times_follow_the_timezone_and_every_panel_has_its_help(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    assert cockpit.when("2026-11-02T18:29:04Z", "utc") == "18:29:04"
    assert cockpit.when("2026-11-02T18:29:04+01:00", "utc", "%Y-%m-%d %H:%M") == "2026-11-02 17:29"
    assert cockpit.when(None) == "-" and cockpit.when("soon", "utc") == "soon"
    local = datetime(2026, 11, 2, 18, 29, 4, tzinfo=timezone.utc).astimezone()
    assert cockpit.when("2026-11-02T18:29:04Z") == local.strftime("%H:%M:%S")  # this machine's, by default
    alert = {"projects": [{"project": "demo", "alerts": [{"level": "warn", "key": "k", "message": "m",
                                                          "since": "2026-10-31T00:00:00Z"}]}]}
    assert cockpit.table("alerts", alert)[0][3] == "2026-10-31 00:00"  # as recorded
    assert cockpit.table("alerts", alert, tz="utc")[0][3] == "2026-10-31 00:00"
    assert cockpit.table("alerts", alert, tz="local")[0][3] == datetime(
        2026, 10, 31, tzinfo=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    head = cockpit.render({"scope": "x", "read_at": "2026-11-02T18:29:04Z", "panels": {}}, tz="utc")[0]
    assert head == "brain cockpit: x; files read 2026-11-02 18:29:04 (utc), probes not run"
    assert set(cockpit.HELP) == set(cockpit.PANELS)
    for name in cockpit.PANELS:
        lines = cockpit.help_lines(name)
        assert lines[0] and any(x.startswith("From: ") for x in lines) and any(x.startswith("Detail: ") for x in lines)
        assert ("s next sort" in lines[-1]) == (name in cockpit.SORTS)


def test_the_settings_are_remembered(tmp_path, monkeypatch, store, capsys):
    cockpit.save_state({"scope": "demo", "settings": {"theme": "nord", "tz": "mars", "x": 1}})
    assert cockpit.load_state()["settings"] == {"theme": "nord"}  # an unknown timezone or key is left out
    _cockpit(tmp_path, monkeypatch, store)
    seen = {}
    monkeypatch.setattr(cockpit, "watch", lambda cp, refresh_s, probe_s, views=None, search="", tz=None: seen.update(
        tz=tz) or 0)
    assert cli.main(["tui", "--project", "demo", "--plain", "--tz", "utc"]) == 0
    assert seen["tz"] == "utc" and cockpit.load_state()["settings"] == {"theme": "nord", "tz": "utc"}
    assert cli.main(["tui", "--project", "demo", "--plain"]) == 0 and seen["tz"] == "utc"  # remembered
    assert cli.main(["tui", "--project", "demo", "--plain", "--reset"]) == 0 and seen["tz"] == "local"  # the default
    assert cli.main(["tui", "--project", "demo", "--once", "--quick", "--tz", "utc"]) == 0
    assert "(utc), probes not run" in capsys.readouterr().out.splitlines()[0]
