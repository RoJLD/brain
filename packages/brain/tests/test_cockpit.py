"""wi-brain-tui-cockpit: the cockpit's data layer (brain.cockpit), its text view and brain tui."""

import argparse
import io
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import brain
from brain import alerts, cli, cockpit, digest, plan, projects, resume, status
from brain.commands import tui as tui_command

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
                      "age_days": 1, "blocking": True, "unblocks": 2, "unblocked": ["wi-one"], "band": "now",
                      "score": 5.92, "recommended": "A", "how": "brain decision answer ddr-a <option>"}]},
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
    for line in ("Ada's queue (1: 1 decision, 0 action, 0 permission | now 1, this week 0, when you can 0); 1 "
                 "denial(s) outside every project (--all)",
                 "  now           5.92   2 decision         demo         1 d  ddr-a [blocking]: Pick one -> A",
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
    assert cockpit.table("queue", p["queue"]) == [("now", "5.92", "2", "decision", "demo", "1 d", "Pick one -> A",
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
        ("running", "abcdef12", "solo", "-", "-", "demo", "-", "x", "-", "-", "1.2M/600k", "-", "now", "b")]
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
    assert out.getvalue().count(f"brain {brain.__version__} cockpit: demo") == 1  # drawn once: nothing changed at the second tick


def test_brain_tui_once_and_json(tmp_path, monkeypatch, store, capsys):
    _cockpit(tmp_path, monkeypatch, store)
    assert cli.main(["tui", "--project", "demo", "--once", "--quick"]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"brain {brain.__version__} cockpit: demo; files read ") and "probes not run" in out
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
    assert _ids("queue", {}) == ["wi-x:needs", "ddr-q", "ddr-a"]  # by band and score; without them, the count
    assert _ids("queue", {"sort": "unblocks"}) == ["wi-x:needs", "ddr-q", "ddr-a"]  # what each unblocks
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
    assert cockpit.note("queue", PANELS["queue"], {}, sort=True) == "sort band"
    assert cockpit.note("queue", PANELS["queue"], None) == "" and cockpit.note("alerts", None, None, "x") == (
        "search 'x'")
    assert cockpit.table("queue", PANELS["queue"], {"kind": "action"}, project=False) == [
        ("-", "-", "5", "action:scheduled", "0 d", "Ada's go-ahead", "wi-x:needs")]
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
    assert state["scope"] == "other" and state["panels"]["queue"] == {"sort": "band", "reverse": False,
                                                                      "kind": "decision", "band": "all"}
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


SCORED = {"projects": [
    {"project": "demo", "entries": [
        _entry("ddr-lo", "decision", 1, 5, "Low score, now", band="now", score=2, since="2026-11-01"),
        _entry("ddr-hi", "decision", 0, 1, "High score, later", band="later", score=9.5, since="2026-11-05"),
        _entry("wi-x:needs", "action", 3, 3, "Tie, younger", band="week", score=4, since="2026-11-03"),
        _entry("ddr-old", "decision", 3, 17, "Tie, older", band="week", score=4, since="2026-10-20")]},
    {"project": "other", "entries": [
        _entry("ddr-more", "decision", 5, 2, "Tie, unblocks more", band="week", score=4, since="2026-11-04"),
        _entry("perm-none", "permission", 9, 0, "No score, unblocks most", band="now", since="2026-11-06"),
        _entry("perm-null", "permission", 1, 0, "A null score", band="now", score=None, since="2026-11-06")]}]}


def test_the_queue_sorts_by_score(brain_home, capsys, monkeypatch):
    """wi-brain-tui-queue-sort-score: the queue's Score column sorts; the highest score first across the bands, one
    without a score last, ties by what each unblocks, then the oldest."""
    def ids(view):
        return [e["id"] for e in cockpit.shown("queue", SCORED, view)]

    by_score = ["ddr-hi", "ddr-more", "ddr-old", "wi-x:needs", "ddr-lo", "perm-none", "perm-null"]
    assert ids({"sort": "score"}) == by_score
    assert ids({"sort": "score", "reverse": True}) == by_score[::-1]
    assert ids({}) == ["ddr-lo", "perm-none", "perm-null", "ddr-more", "wi-x:needs", "ddr-old", "ddr-hi"]  # by band
    assert ids({"sort": "score", "kind": "decision"}) == ["ddr-hi", "ddr-more", "ddr-old", "ddr-lo"]
    assert cockpit.SORTS["queue"][:2] == ("band", "score") and cockpit.SORT_COLUMNS["queue"]["Score"] == "score"
    for name, keys in cockpit.SORTS.items():  # every sort has its key, every sorting column is a column and a sort
        assert set(keys) == set(cockpit.SORT_KEYS[name])
        assert set(cockpit.SORT_COLUMNS[name]) <= set(cockpit.every_column(name))
        assert set(cockpit.SORT_COLUMNS[name].values()) <= set(keys)
    assert cockpit.parse_view(["queue:-score"]) == {"queue": {"sort": "score", "reverse": True}}
    assert cockpit.view_of("queue", {"sort": "score"})["sort"] == "score"
    cockpit.save_state({"panels": {"queue": {"sort": "score", "reverse": True}, "frontier": {"sort": "band"}}})
    state = cockpit.load_state()["panels"]
    assert (state["queue"]["sort"], state["queue"]["reverse"]) == ("score", True)  # tui.json keeps it
    assert state["frontier"]["sort"] == "priority"  # a sort the panel does not know: its default
    lines = cockpit.queue_lines(SCORED, view={"sort": "score"})
    assert lines[0].endswith("[sort score]")
    assert [next(i for i in by_score if f" {i}" in x) for x in lines[1:]] == by_score  # the text view, same order
    assert "9.5" in lines[1] and lines[-1].split()[1] == "-"  # its score shown, '-' without one
    monkeypatch.setenv("COLUMNS", "120")  # argparse wraps at the terminal's width
    with pytest.raises(SystemExit):
        cli.main(["tui", "--help"])
    assert "queue:band|score|unblocks|age|kind|project" in capsys.readouterr().out  # the help lists every sort


def test_an_empty_table_says_why_and_a_panel_not_probed_what_it_waits_for():
    """wi-brain-tui-states (spec 2026-11-02 cockpit-ux §4.10): why a table shows no row, what a probe waits for."""
    snap = {"scope": "demo", "panels": {"queue": SCORED, "sessions": {"hours": 24, "rows": []},
                                        "milestones": {"projects": []}, "frontier": {"projects": []}},
            "projects": [{"name": "demo", "root": "/w/demo", "found": True},
                         {"name": "far", "root": "../nowhere", "found": False}]}

    def why(name, view=None, search="", wait=""):
        return cockpit.why_empty(name, snap, view, search, wait)

    assert why("queue", {}) == "" and why("queue", {"kind": "action"}) == ""  # rows shown: nothing to say
    assert why("queue", {"kind": "action", "band": "later"}) == (
        "7 hidden by kind action, band later: f changes the filters")
    assert why("queue", {"kind": "action"}, " nothing ") == (
        "7 hidden by kind action, search 'nothing': f changes the filters, Escape clears the search")
    assert why("queue", None, "nothing") == "7 hidden by search 'nothing': Escape clears the search"
    missing = "; far is not on this machine (../nowhere)"
    assert why("sessions", {}) == "No session wrote its transcript in the last 24 h" + missing
    assert why("frontier", {}) == "No startable item in demo" + missing
    snap["scope"], snap["panels"]["queue"] = cockpit.ALL, {"projects": []}
    assert why("queue", {}) == "Nothing waits on Ada in every project" + missing  # the owner named
    assert why("milestones") == "No pending milestone in every project" + missing
    assert why("alerts") == "not probed yet" and why("alerts", wait="probing: demo 1/2") == "probing: demo 1/2"
    snap["errors"] = {"alerts": {"at": "2026-11-06T10:00:00Z", "error": "OSError: x"}}
    assert why("alerts") == "read failed: OSError: x"
    del snap["panels"]["queue"]
    assert why("queue") == "not read yet"
    assert cockpit.probe_wait({"what": "demo", "n": 1, "total": 2}) == "probing: demo 1/2"
    assert cockpit.probe_wait({"what": "the denied calls", "n": 0, "total": 2}) == "probing: the denied calls"
    assert cockpit.probe_wait(None, 100) == "not probed yet: probe in 1 min 40 (r for now)"
    assert cockpit.probe_wait(None) == cockpit.probe_wait(None, 0.4) == (
        "not probed yet: the probe starts at the next tick")
    assert cockpit.probe_wait(None, 100, paused=True) == "not probed yet: paused (space resumes, r probes now)"
    assert [cockpit.span(s) for s in (5, 60, 100, 3725)] == ["5 s", "1 min", "1 min 40", "1 h 02"]
    lines = cockpit.render({**snap, "panels": {"queue": {"projects": []}}, "errors": {}})
    assert "  (Nothing waits on Ada in every project" + missing + ")" in lines  # the text view says it too
    assert "  (not read yet)" in lines and "  (not probed yet)" not in lines  # the heading says it for a probe


def test_a_failed_read_keeps_the_last_content_and_is_read_again(tmp_path, monkeypatch, store, capsys):
    """wi-brain-tui-states: a read that fails is never raised; its panels keep their content, the error and the
    time of the data are in the snapshot, it is read again at the next tick, and a project the registry names but
    this machine lacks is labelled in the selector."""
    cp = _cockpit(tmp_path, monkeypatch, store)
    assert cockpit.scope_choices(cp.choices)[1:] == [("demo", "demo", True),
                                                     ("far (not on this machine)", "far", False)]
    assert cockpit.scope_choices({"x": None})[1] == ("x (not on this machine)", "x", False)
    assert cp.snapshot()["registry"] is True
    cp.refresh()
    before, read_at = cp.snapshot()["panels"]["frontier"], cp.snapshot()["read_at"]
    real, calls = status._store, []

    def gone(p):
        calls.append(p.name)
        raise OSError("disk gone")
    monkeypatch.setattr(status, "_store", gone)
    with (store / "nodes" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write("\n")  # a change: the graph is read again
    assert cp.refresh() == {"queue", "milestones", "frontier"}  # never raised; to draw again with the error
    snap = cp.snapshot()
    error = snap["errors"]["frontier"]
    assert error["error"] == "OSError: disk gone" and snap["panels"]["frontier"] == before  # the last content
    assert snap["panel_at"]["frontier"] <= error["at"] and "sessions" not in snap["errors"]
    assert snap["read_at"] == read_at  # nothing was read
    text = "\n".join(cockpit.render(snap, tz="utc"))
    assert f"  read failed at {cockpit.when(error['at'], 'utc')}: OSError: disk gone; data of " in text
    n = len(calls)
    assert cp.refresh() == set() and len(calls) > n  # read again, though no file changed; the same error: no redraw
    assert cp.snapshot()["errors"]["frontier"]["at"] == error["at"]  # its first time kept
    assert cli.main(["tui", "--project", "demo", "--once", "--quick"]) == 1  # a one-shot read says it failed
    assert "brain tui: reading queue, milestones, frontier failed: OSError: disk gone" in capsys.readouterr().err
    assert cli.main(["tui", "--project", "demo", "--detail", "wi-nope", "--quick"]) == 1
    err = capsys.readouterr().err  # no row: and why it may be missing
    assert "wi-nope: no row" in err and "reading queue, milestones, frontier failed: OSError: disk gone" in err
    monkeypatch.setattr(status, "_store", real)
    assert cp.refresh() == {"queue", "milestones", "frontier"} and cp.snapshot()["errors"] == {}
    assert cp.refresh() == set()  # back to reading on a change only


def test_the_probe_says_its_progress_and_a_stack_its_last_ok_measure(tmp_path, monkeypatch, store, brain_home):
    cp = _cockpit(tmp_path, monkeypatch, store)
    seen = []
    monkeypatch.setattr(status, "audit_of", lambda p, detail=0: seen.append(dict(cp.progress)) or {
        "counts": {}, "repos": 1, "unreadable": [], "by_repo": [], "top": []})
    monkeypatch.setattr(status, "_probes", lambda root, quick: (None, None))
    monkeypatch.setattr(alerts, "read_scheduler", lambda cfgs: {})
    monkeypatch.setattr(status, "alerts_of", lambda p, m, reg, sched, last: {"open": 0, "counts": {}, "alerts": []})
    states = iter(["OK", "DOWN", "DOWN"])
    monkeypatch.setattr(status, "probed", lambda p, reg, ix: {
        "stacks": [{"name": "gitnexus", "state": next(states), "why": "no container"}], "code_index": []})
    t0 = datetime(2026, 11, 6, 10, 0, tzinfo=timezone.utc)
    cp.probe(now=t0)
    assert seen == [{"what": "demo", "n": 1, "total": 1}]  # project n of total, while it is measured
    cp.probe(now=t0 + timedelta(hours=2))
    health = cp.snapshot()["panels"]["health"]
    assert health["projects"][0]["stacks"][0]["last_ok"] == "2026-11-06T10:00:00Z"
    assert "gitnexus DOWN (no container; last OK 3 h ago)" in cockpit.health_lines(
        health, now=t0 + timedelta(hours=3))[1]
    assert cp.refresh(probe=True) and cp.snapshot()["probing"] is None  # done: no progress left
    assert cp.snapshot()["errors"] == {}

    def fails(p, detail=0):
        raise OSError("audit gone")
    monkeypatch.setattr(status, "audit_of", fails)
    assert cp.refresh(probe=True) == set(cockpit.PROBE_PANELS)  # a failed probe: never raised
    snap = cp.snapshot()
    assert {n: e["error"] for n, e in snap["errors"].items()} == dict.fromkeys(cockpit.PROBE_PANELS,
                                                                               "OSError: audit gone")
    assert snap["panels"]["health"]["projects"] == health["projects"] and snap["probing"] is None  # kept
    cp.select("demo")  # another scope: the old scope's errors go
    assert cp.snapshot()["errors"] == {} and cp.snapshot()["panels"]["health"]["projects"] == health["projects"]


def test_the_tui_command_says_its_failed_reads_and_reads_its_durations(capsys):
    """brain.commands.tui, directly: one line per error, its panels named; a duration of at least 250 ms."""
    assert tui_command._failed_reads({"errors": {}}) is False and tui_command._failed_reads({}) is False
    assert capsys.readouterr().err == ""
    assert tui_command._failed_reads({"errors": {"audit": {"at": "t", "error": "OSError: x"},
                                                 "health": {"at": "t", "error": "OSError: x"},
                                                 "digest": {"at": "t", "error": "ValueError: y"}}}) is True
    assert capsys.readouterr().err.splitlines() == ["brain tui: reading audit, health failed: OSError: x",
                                                    "brain tui: reading digest failed: ValueError: y"]
    assert tui_command._duration("500ms") == 0.5 and tui_command._duration("5m") == 300
    for bad in ("100ms", "soon"):
        with pytest.raises(argparse.ArgumentTypeError):
            tui_command._duration(bad)


def test_brain_tui_all_without_a_registry_shows_this_folders_project(tmp_path, monkeypatch, store, capsys):
    root = store.parents[1]
    monkeypatch.setenv("BRAIN_PROJECTS", str(tmp_path / "no-registry.yaml"))
    assert cli.main(["--root", str(root), "tui", "--all", "--once", "--quick"]) == 0
    out, err = capsys.readouterr()
    assert "--all needs the project registry" in err and "brain tui shows this folder's project" in err
    assert out.startswith(f"brain {brain.__version__} cockpit: ") and "cockpit: all" not in out
    assert cockpit.Cockpit([resume.project_for(root)]).snapshot()["registry"] is False


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
    monkeypatch.setattr(cockpit, "watch", lambda cp, refresh_s, probe_s, views=None, search="", tz=None, tab=None: seen.update(
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
    assert out.startswith(f"brain {brain.__version__} cockpit: demo;")  # --once: the flags only, never the remembered state
    assert ("Ada's queue (1: 1 decision, 0 action, 0 permission | now 1, this week 0, when you can 0); denied calls "
            "read at the first probe; 1 denial(s) outside every project (--all) [0 of 1 shown; kind permission]"
            "\n") in out
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
    assert head == f"brain {brain.__version__} cockpit: x; files read 2026-11-02 18:29:04 (utc), probes not run"
    assert set(cockpit.HELP) == {*cockpit.PANELS, *cockpit.FRAMES, "overview", "settings"}
    assert "the arrows" in cockpit.help_lines("overview")[-1] and "m full view" not in cockpit.help_lines("overview")[-1]
    assert cockpit.heading("overview", None) == "Overview"
    for name in cockpit.HELP:
        lines = cockpit.help_lines(name)
        assert lines[0] and any(x.startswith("From: ") for x in lines) and any(x.startswith("Detail: ") for x in lines)
        assert ("s next sort" in lines[-1]) == (name in cockpit.SORTS)


def test_the_settings_are_remembered(tmp_path, monkeypatch, store, capsys):
    cockpit.save_state({"scope": "demo", "settings": {"theme": "nord", "tz": "mars", "x": 1}})
    assert cockpit.load_state()["settings"] == {"theme": "nord"}  # an unknown timezone or key is left out
    _cockpit(tmp_path, monkeypatch, store)
    seen = {}
    monkeypatch.setattr(cockpit, "watch", lambda cp, refresh_s, probe_s, views=None, search="", tz=None, tab=None:
                        seen.update(tz=tz, tab=tab) or 0)
    assert cli.main(["tui", "--project", "demo", "--plain", "--tz", "utc"]) == 0
    assert seen["tz"] == "utc" and cockpit.load_state()["settings"] == {"theme": "nord", "tz": "utc"}
    assert cli.main(["tui", "--project", "demo", "--plain"]) == 0 and seen["tz"] == "utc"  # remembered
    assert cli.main(["tui", "--project", "demo", "--plain", "--reset"]) == 0 and seen["tz"] == "local"  # the default
    assert cli.main(["tui", "--project", "demo", "--once", "--quick", "--tz", "utc"]) == 0
    assert "(utc), probes not run" in capsys.readouterr().out.splitlines()[0]


# --- the tabs (wi-brain-tui-layout, UX-18) ---

def test_the_tabs_are_the_eleven_of_ux18_with_their_keys():
    assert [(n, t["key"]) for n, t in cockpit.TABS.items()] == [
        ("overview", "0"), ("queue", "1"), ("sessions", "2"), ("frontier", "3"), ("milestones", "4"), ("ideas", "5"),
        ("lessons", "6"), ("features", "7"), ("health", "8"), ("resources", "9"), ("settings", ",")]
    assert cockpit.built_tabs() == ("overview", "queue", "sessions", "frontier", "milestones", "health", "settings")
    for name, t in cockpit.TABS.items():
        assert set(t["label"]) == set(cockpit.LANGS) and set(t["question"]) == set(cockpit.LANGS)
        assert t["views"] or t["arrives"], name  # a tab not built says what brings it
    # every panel and frame has a tab, and each view its words
    assert {p for t in cockpit.built_tabs() for p in cockpit.tab_panels(t)} == {*cockpit.PANELS, *cockpit.FRAMES, "settings"}
    assert {v for t in cockpit.TABS.values() for v in t["views"]} <= set(cockpit.VIEW_LABELS)
    assert [cockpit.panel_tab(p) for p in ("queue", "alerts", "exec", "digest")] == ["queue", "health", "health",
                                                                                      "overview"]


def test_a_tab_label_says_its_state_in_digits_and_signs(tmp_path, monkeypatch):
    panels = {"queue": {"projects": [{"project": "d", "entries": [{"id": "a", "band": "now"}, {"id": "b", "band": "week"},
                                                                  {"id": "c", "band": "now"}]}]},
              "sessions": {"rows": [{"state": "asking"}, {"state": "running"}]},
              "alerts": {"projects": [{"project": "d", "alerts": [{"key": "k"}]}]}}
    snap = {"panels": panels}
    assert [cockpit.tab_count(n, snap) for n in ("queue", "sessions", "health", "frontier")] == ["2", "1!", "1", ""]
    assert cockpit.tab_count("queue", {}) == "" and cockpit.tab_count("health", {"panels": {"alerts": None}}) == ""
    assert cockpit.tab_label("sessions", snap) == "2 Sessions 1!" and cockpit.tab_label("frontier", snap) == "3 Frontier"
    monkeypatch.setenv("BRAIN_LANG", "fr")
    assert cockpit.tab_label("health", snap) == "8 Santé 1" and cockpit.tab_question("queue").startswith("Que dois-je")
    assert cockpit.tab_label("queue", snap).startswith(("1 File d'", "1 File de "))  # the owner's name, in French
    assert cockpit.not_built("ideas") == "Idées is not here yet: it arrives with the ideas board"


def test_the_bar_is_reduced_to_its_numbers_when_narrow_or_when_it_does_not_fit(monkeypatch):
    snap = {"panels": {"sessions": {"rows": [{"state": "asking"}]}}}
    assert not cockpit.narrow(120, 30) and cockpit.narrow(119, 30) and cockpit.narrow(120, 29)
    wide = cockpit.tab_labels(snap, "queue", 160, 48)
    assert wide["sessions"] == "2 Sessions 1!" and list(wide) == list(cockpit.built_tabs())
    assert cockpit.tab_labels(snap, "sessions", 100, 48) == {"overview": "0", "queue": "1", "sessions": "2 Sessions 1!",
                                                             "frontier": "3", "milestones": "4", "health": "8", "settings": ","}
    assert cockpit.tab_labels(snap, "queue", 160, 29)["sessions"] == "2"  # short too
    # the eleven, once built: more than 120 columns with their counts, so their numbers there, and it fits
    every = {n: {**t, "views": t["views"] or {"list": ()}} for n, t in cockpit.TABS.items()}
    monkeypatch.setattr(cockpit, "TABS", every)
    assert len(cockpit.built_tabs()) == 11
    at_120 = cockpit.tab_labels(snap, "queue", 120, 40)
    assert at_120["frontier"] == "3" and at_120["settings"] == ","
    assert sum(len(x) + cockpit.TAB_PADDING for x in at_120.values()) <= 120
    assert cockpit.tab_labels(snap, "queue", 200, 40)["settings"] == ", Settings"


def test_a_tabs_views_and_the_grid_on_a_narrow_terminal():
    assert cockpit.tab_views("overview") == ("cards", "grid", "digest")
    assert cockpit.tab_views("overview", True) == ("cards", "digest")
    assert cockpit.tab_view("overview") == "cards" and cockpit.tab_view("overview", "digest") == "digest"
    assert cockpit.tab_view("overview", "grid", True) == "cards"  # no grid here, and its choice kept for a wide one
    assert cockpit.tab_view("overview", "gone") == "cards"
    assert cockpit.tab_panels("overview", "cards") == ()
    assert cockpit.tab_panels("overview", "digest") == ("digest",) and cockpit.tab_panels("overview") == cockpit.PANELS
    assert cockpit.tab_panels("health", "frames") == ("alerts", "audit", "health", "exec")


def test_the_last_tab_and_views_are_remembered_and_a_foreign_one_left_out(tmp_path):
    f = tmp_path / "tui.json"
    cockpit.save_state({"tab": "health", "tabs": {"overview": {"view": "digest"}}}, f)
    assert cockpit.load_state(f) == {"tab": "health", "tabs": {"overview": {"view": "digest"}}}
    cockpit.save_state({"tab": "ideas", "tabs": {"overview": {"view": "x"}, "nope": {"view": "grid"}, "queue": 3,
                                                 "health": {"view": ["frames"]}}}, f)
    assert cockpit.load_state(f) == {"tabs": {}}  # not built yet, an unknown view or tab: left out


def test_the_text_view_prints_one_tab(tmp_path, monkeypatch):
    health = {"projects": [{"project": "demo", "stacks": [], "code_index": []}],
              "exec": {"days": 7, "runs": 3, "failed": 1, "regressions": [{"task": "sync", "change": 0.5}],
                       "slowest": [{"project": "demo", "task": "sync", "runs": 3, "failed": 1, "median_s": 2.5,
                                    "max_s": 9}]}}
    snap = {"scope": "demo", "panels": {"health": health, "queue": {"projects": []}}}
    lines = cockpit.render(snap, tab="health")
    assert "Exec times (3 run(s) in 7 d, 1 failed)" in lines and "Stacks and index" in lines
    assert "Audit debt: not probed yet" in lines
    assert "  2.5 s (max 9 s, 3 run(s), 1 failed) demo: sync" in lines and "  regression: sync +50%" in lines
    assert not any(x.startswith("Ada's queue") for x in lines)
    assert any(x.startswith("Ada's queue") for x in cockpit.render(snap, tab="queue"))
    every = cockpit.render(snap)  # no tab: the panels, the exec line in the stacks' frame and no frame of its own
    assert any(x.startswith("Ada's queue") for x in every) and not any(x.startswith("Exec times") for x in every)
    assert cockpit.exec_lines(None) == ["Exec times: not probed yet"]
    assert cockpit.exec_lines({"projects": []}) == ["Exec times", "  no run read"]
    assert cockpit.heading("exec", None) == "Exec times: not probed yet"


def test_the_global_bar_says_the_last_change_and_the_next_probe():
    at = "2026-11-08T10:15:00Z"
    assert cockpit.bar_status(at, 125, tz="utc") == "changed 10:15 · probe in 2 min 05"
    assert cockpit.bar_status(None, None, tz="utc") == "changed - · probe now"
    assert cockpit.bar_status(at, 0.5, tz="utc").endswith("probe now")
    assert cockpit.bar_status(at, 60, probing=True, tz="utc").endswith("probing")
    assert cockpit.bar_status(at, 60, paused=True, tz="utc").endswith("paused")


def _card_of(snap, tab, wait=""):
    return next(c for c in cockpit.cards(snap, wait) if c["tab"] == tab)


def test_the_cards_say_what_counts_in_each_tab():
    """UX-19, spec §4.0.3: each built tab's card, at most four lines, and what it opens with."""
    def entry(i, band):
        return {"id": f"d{i}", "kind": "action", "band": band, "title": f"Entry  {i}\nmore", "unblocks": 0, "age_days": 0,
                "since": "", "score": 10 - i}
    panels = {
        "queue": {"projects": [{"project": "p", "entries": [entry(1, "now"), entry(2, "now"), entry(3, "now"),
                                                            entry(4, "now"), entry(5, "week"), entry(6, "later")]}]},
        "sessions": {"hours": 24, "rows": [
            {"state": "asking", "session_id": "aaaaaaaa11", "project": "p", "title": "Waits", "step": "", "branch": "",
             "age_s": 1},
            {"state": "running", "session_id": "bbbbbbbb22", "project": "p", "title": "Runs", "step": "", "branch": "",
             "age_s": 1, "name": "runner"},
            {"state": "ended", "session_id": "cccccccc33", "project": "p", "title": "", "step": "", "branch": "",
             "age_s": 1}]},
        "milestones": {"projects": [{"project": "brain", "reached": 2, "pending": [
            {"id": "ms-brain-far", "title": "Far", "items": 10, "done": 1},
            {"id": "ms-brain-near", "title": "Near", "items": 4, "done": 3}]}]},
        "frontier": {"projects": [{"project": "brain", "items": [
            {"id": "wi-brain-b", "priority": "P2", "unblocks": 1, "title": "B", "milestone": ""},
            {"id": "wi-brain-a", "priority": "P0", "unblocks": 4, "title": "A", "milestone": ""}]}]},
        "alerts": {"projects": [{"project": "p", "alerts": [{"level": "warn", "key": "k", "message": "the  canary"}]}]},
        "audit": {"projects": [{"project": "p", "counts": {"P0": 1}}, {"project": "broken", "error": "x"}]}}
    snap = {"scope": "p", "panels": panels}
    assert cockpit.card_tabs() == ("queue", "sessions", "milestones", "frontier", "health")
    assert [c["tab"] for c in cockpit.cards(snap)] == list(cockpit.card_tabs())
    q = _card_of(snap, "queue")
    assert q["title"].endswith("· 4 now") and q["title"].startswith("1 ")
    assert q["lines"] == ["Entry 1 more", "Entry 2 more", "Entry 3 more", "1 this week · 1 when you can"]  # flat, and whole
    assert q["filters"] == {"queue": {"kind": "all", "band": "now"}}  # over the owner's: its count is what opens
    assert q["foot"] == "Enter: the queue, band now"
    s = _card_of(snap, "sessions")
    assert s["title"] == "2 Sessions · 1 asking" and s["filters"] == {"sessions": {"state": "asking"}}
    assert s["lines"] == ["! aaaaaaaa: Waits", "1 running"]  # who waits first; an ended one counts for nothing
    m = _card_of(snap, "milestones")
    assert m["title"] == "4 Milestones · 2 pending" and m["filters"] == {}
    assert m["lines"] == ["near 3/4 ########..", "far 1/10 #.........", "2 reached"]  # the nearest first
    f = _card_of(snap, "frontier")
    assert f["title"] == "3 Frontier · 2 startable"
    assert f["lines"] == ["P0 a: unblocks 4", "P2 b: unblocks 1"]
    h = _card_of(snap, "health")
    assert h["title"] == "8 Health · 1 alert(s)" and h["lines"] == ["warn the canary", "audit p: P0 1, P1 0, P2 0, info 0"]


def test_the_cards_when_nothing_presses():
    def snap(**panels):
        return {"scope": "p", "panels": panels}
    later = {"projects": [{"project": "p", "entries": [{"id": "a", "kind": "action", "band": "later", "title": "Later",
                                                        "unblocks": 0, "age_days": 0, "since": ""}]}]}
    q = _card_of(snap(queue=later), "queue")
    assert q["lines"] == ["Later", "1 when you can"] and q["filters"] == {} and q["foot"] == "Enter: the queue"
    assert "now" not in q["title"]

    def session(state, **kw):
        return {"state": state, "session_id": "abcdefgh12", "title": "", "step": "", "branch": "", **kw}
    s = _card_of(snap(sessions={"rows": [session("running", name="one", step="2/3 Write"),
                                         session("running", name="two", branch="b"), session("running", name="three"),
                                         session("idle", name="four")]}), "sessions")
    assert s["lines"] == ["one: 2/3 Write", "two: b", "three", "3 running · 1 idle"]  # none asking: who runs; never « x: »
    assert s["filters"] == {} and s["foot"] == "Enter: the sessions" and s["title"] == "2 Sessions"
    assert _card_of(snap(sessions={"rows": [session("ended", name="x")]}), "sessions")["lines"] == ["1 ended"]
    assert _card_of(snap(sessions={"rows": [session("asking", name="x")]}), "sessions")["lines"] == ["! x"]
    m = _card_of(snap(milestones={"projects": [{"project": "b", "reached": 0, "pending": [
        {"id": "ms-b-empty", "title": "E", "items": 0, "done": 0}, {"id": "ms-b-half", "title": "H", "items": 2, "done": 1}]}]}),
        "milestones")
    assert m["lines"] == ["half 1/2 #####.....", "empty 0/0 .........."]  # an item-less milestone: last, no division


def test_a_card_is_at_most_four_lines_and_the_worst_alert_comes_first():
    alert = {"projects": [
        {"project": "a", "alerts": [{"level": "warn", "key": f"k{i}", "message": f"warn {i}"} for i in range(3)]},
        {"project": "b", "alerts": [{"level": "critical", "key": "c", "message": "the worst"}]},
        {"project": "c", "error": "bad alerts:"}]}
    h = _card_of({"scope": "all", "panels": {"alerts": alert, "audit": {"projects": [{"project": "a", "counts": {}}]}}},
                 "health")
    assert h["lines"] == ["c: error: bad alerts:", "critical the worst", "warn warn 0", "audit a: P0 0, P1 0, P2 0, info 0"]
    assert h["title"] == "8 Health · 4 alert(s)"  # a config that cannot be read is said, never « no open alert »
    assert _card_of({"scope": "c", "panels": {"alerts": {"projects": [{"project": "c", "error": "bad"}]}}},
                    "health")["lines"] == ["c: error: bad"]
    many = {"projects": [{"project": "p", "items": [{"id": f"wi-{i}", "priority": "P1", "unblocks": 0, "title": "x",
                                                     "milestone": ""} for i in range(9)]}]}
    assert len(_card_of({"panels": {"frontier": many}}, "frontier")["lines"]) == cockpit.CARD_LINES


def test_a_card_says_why_it_has_nothing():
    """The states of wi-brain-tui-states in a card: not read yet, not probed yet, nothing in the scope; no filter."""
    snap = {"scope": "demo", "panels": {}}
    assert _card_of(snap, "queue")["lines"] == ["not read yet"] and _card_of(snap, "queue")["filters"] == {}
    assert _card_of(snap, "sessions")["lines"] == ["not read yet"] and _card_of(snap, "sessions")["filters"] == {}
    assert _card_of(snap, "health", "probe in 2 min")["lines"] == ["probe in 2 min"]
    empty = {"scope": "demo", "panels": {"queue": {"projects": []}, "alerts": {"projects": []},
                                         "frontier": {"projects": []}, "milestones": {"projects": []},
                                         "sessions": {"hours": 24, "rows": []}}}
    assert _card_of(empty, "queue")["lines"][0].startswith("Nothing waits on ")
    assert _card_of(empty, "health")["lines"] == ["No open alert in demo"]
    assert _card_of(empty, "frontier")["lines"] == ["No startable item in demo"]
    assert _card_of(empty, "milestones")["lines"] == ["No pending milestone in demo"]
    assert _card_of(empty, "sessions")["lines"] == ["No session wrote its transcript in the last 24 h"]
    assert _card_of(empty, "queue")["title"] == f"1 {cockpit.title('queue')}"  # no count to say


def test_the_text_view_prints_the_overviews_cards():
    snap = {"scope": "demo", "panels": {"frontier": {"projects": [{"project": "p", "items": [
        {"id": "wi-a", "priority": "P1", "unblocks": 2, "title": "A", "milestone": ""}]}]}}}
    lines = cockpit.render(snap, tab="overview")
    assert "3 Frontier · 1 startable" in lines and "  P1 a: unblocks 2" in lines
    assert "  not probed yet" in lines and not any(x.startswith("Enter") for x in lines)  # a text view has no Enter


def test_the_digest_under_its_frame_does_not_repeat_its_title():
    panel = {"projects": [{"project": "demo", "digest": "last-week", "written": True, "records": {"journals": []},
                           "text": "# Digest of demo\n\n## Items closed\n"}]}
    assert cockpit.digest_lines(panel)[:2] == ["Digest demo (last-week, written); journal -", "  # Digest of demo"]
    assert cockpit.digest_lines(panel, titled=False) == ["demo (last-week, written); journal -", "  ## Items closed"]


def _session_row():
    return {"state": "running", "session_id": "abcdef1234567890", "project": "p", "step": "2/3 Write", "model": "m",
            "effort": "high", "context": 1000, "budget": 2000, "output_tokens": 10, "age_s": 5, "title": "A long title",
            "branch": "b", "cost_usd": 12.5, "host_id": "local_0123456789abcdef"}


def test_a_tables_columns_can_be_chosen():
    row = _session_row()
    assert cockpit.columns("sessions") == cockpit.COLUMNS["sessions"]  # the default: the extras hidden
    assert cockpit.every_column("sessions")[-4:] == ("Cost", "App id", "Id", "Branch")
    assert cockpit.every_column("queue") == cockpit.COLUMNS["queue"]
    chosen = {"shown": ["Title", "Cost", "App id", "Id", "Branch", "Project", "State"]}
    assert cockpit.columns("sessions", True, chosen) == ("Title", "Cost", "App id", "Id", "Branch", "Project", "State")
    assert cockpit.cells("sessions", row, True, None, chosen) == ("A long title", "$12.50", "local_01234567", "abcdef12", "b",
                                                                  "p", "running")
    assert cockpit.columns("sessions", False, chosen)[-2:] == ("Branch", "State")  # one project: no Project column
    assert cockpit.cells("sessions", row, False, None, chosen)[-2:] == ("b", "running")
    only = {"shown": ["Project"]}
    assert cockpit.columns("sessions", False, only) == tuple(c for c in cockpit.COLUMNS["sessions"] if c != "Project")
    assert cockpit.columns("sessions", True, {"shown": ["Nope"]}) == cockpit.COLUMNS["sessions"]  # none left: the default
    assert cockpit.cells("sessions", row, True, None, {"shown": ["Title"], "width": 6}) == ("A lon…",)
    assert cockpit.SORT_COLUMNS["sessions"]["Cost"] == "cost"
    # a row with nothing to say in an extra column
    bare = {**row, "cost_usd": None, "host_id": "", "branch": ""}
    assert cockpit.cells("sessions", bare, True, None, {"shown": ["Cost", "App id", "Branch"]}) == ("-", "-", "-")
    # no chosen: the row is what it always was, aligned with its columns
    assert len(cockpit.cells("sessions", row)) == len(cockpit.columns("sessions"))
    assert cockpit.cells("sessions", row, False)[:2] == ("running", "local_01234567")


def test_the_chosen_columns_are_remembered_and_a_foreign_one_left_out(tmp_path):
    f = tmp_path / "tui.json"
    cockpit.save_state({"columns": {"sessions": {"shown": ["Title", "Nope", 3], "width": 60},
                                    "queue": {"shown": [], "width": 41}, "audit": {"shown": ["x"]}, "frontier": "x",
                                    "alerts": {"shown": "Level", "width": True}}}, f)
    assert cockpit.load_state(f)["columns"] == {"sessions": {"shown": ["Title"], "width": 60}}
    cockpit.save_state({"columns": {}}, f)
    assert "columns" not in cockpit.load_state(f)
    cockpit.save_state({"columns": {"sessions": {"shown": 3}, "queue": {"shown": True, "width": True},
                                    "frontier": {"shown": ["Id", "Id", "P"], "width": False}}}, f)
    assert cockpit.load_state(f)["columns"] == {"frontier": {"shown": ["Id", "P"], "width": 0}}  # damaged: never raised


def test_the_palette_reaches_every_sort_and_filter():
    does = {e["do"] for e in cockpit.palette({})}
    assert {("sort", n, k) for n in cockpit.SORTS for k in cockpit.SORTS[n]} <= does
    assert {("filter", n, f, v) for n in cockpit.FILTERS for f, vals in cockpit.FILTERS[n].items() for v in vals} <= does


def test_the_palette_reaches_every_tab_project_and_table():
    entries = cockpit.palette({"demo": None, "quant": None})
    titles = [e["title"] for e in entries]
    assert len(titles) == len(set(titles))  # the palette finds an entry by its words
    does = {e["do"] for e in entries}
    assert {("tab", n) for n in cockpit.built_tabs()} <= does and ("tab", "ideas") not in does
    assert {("view", "overview", v) for v in cockpit.tab_views("overview")} <= does and ("view", "queue", "list") not in does
    assert {("scope", "all"), ("scope", "demo"), ("scope", "quant")} <= does
    assert {("columns", n) for n in cockpit.COLUMNS} <= does and ("reset",) in does
    assert ("view", "overview", "grid") not in {e["do"] for e in cockpit.palette({}, is_narrow=True)}
    assert "Go to Frontier" in titles and "Frontier: sort by unblocks" in titles and "Reset the views" in titles
    assert "Project: quant (not on this machine)" in titles
    assert next(e for e in entries if e["do"] == ("tab", "frontier"))["help"] == "key 3: What can start?"


def test_brain_tui_gives_the_app_its_columns(tmp_path, monkeypatch, store):
    pytest.importorskip("textual")
    from brain import tui
    _cockpit(tmp_path, monkeypatch, store)
    seen = {}
    monkeypatch.setattr(tui, "run", lambda cp, **kw: seen.update(kw) or 0)
    chosen = {"sessions": {"shown": ["Title"], "width": 40}}
    cockpit.save_state({"scope": "demo", "columns": chosen})
    assert cli.main(["tui", "--project", "demo"]) == 0
    assert seen["columns"] == chosen and cockpit.load_state()["columns"] == chosen  # kept by the start's own save
    assert cli.main(["tui", "--project", "demo", "--reset"]) == 0
    assert seen["columns"] == {} and "columns" not in cockpit.load_state()  # forgotten


def test_brain_tui_tab_starts_there_and_prints_it(tmp_path, monkeypatch, store, capsys):
    _cockpit(tmp_path, monkeypatch, store)
    assert cli.main(["tui", "--project", "demo", "--once", "--quick", "--tab", "frontier"]) == 0
    out = capsys.readouterr().out
    assert "Frontier (" in out and "Milestones (" not in out
    seen = {}
    monkeypatch.setattr(cockpit, "watch", lambda cp, refresh_s, probe_s, views=None, search="", tz=None, tab=None:
                        seen.update(tab=tab) or 0)
    assert cli.main(["tui", "--project", "demo", "--plain", "--tab", "health"]) == 0
    assert seen["tab"] == "health" and cockpit.load_state()["tab"] == "health"
    assert cli.main(["tui", "--project", "demo", "--plain"]) == 0
    assert seen["tab"] is None and cockpit.load_state()["tab"] == "health"  # the text view prints all, the tab is kept
    with pytest.raises(SystemExit):
        cli.main(["tui", "--tab", "ideas"])  # not built yet: not a choice


def test_brain_tui_gives_the_app_the_tab_it_is_told_or_the_one_it_last_showed(tmp_path, monkeypatch, store):
    pytest.importorskip("textual")
    from brain import tui
    _cockpit(tmp_path, monkeypatch, store)
    seen = {}
    monkeypatch.setattr(tui, "run", lambda cp, **kw: seen.update(tab=kw["tab"], tabs=kw["tabs"]) or 0)
    cockpit.save_state({"scope": "demo", "tab": "frontier", "tabs": {"overview": {"view": "digest"}}})
    assert cli.main(["tui", "--project", "demo"]) == 0
    assert seen == {"tab": "frontier", "tabs": {"overview": {"view": "digest"}}}  # the last ones shown
    assert cli.main(["tui", "--project", "demo", "--tab", "health"]) == 0
    assert seen["tab"] == "health" and cockpit.load_state()["tabs"] == {"overview": {"view": "digest"}}
    assert cli.main(["tui", "--project", "demo", "--reset"]) == 0
    assert seen == {"tab": None, "tabs": {}}  # forgotten


def test_a_newer_brains_tui_json_is_shown_never_written(tmp_path, monkeypatch, store, capsys):
    """wi-brain-state-safe-io-rest: the interactive cockpit opens on a newer brain's tui.json, says it will not
    remember the views, and leaves the file as it was."""
    text = json.dumps({"v": 2, "scope": "demo", "settings": {"theme": "nord"}})
    cockpit.state_path().parent.mkdir(parents=True, exist_ok=True)
    cockpit.state_path().write_text(text, encoding="utf-8")
    _cockpit(tmp_path, monkeypatch, store)
    monkeypatch.setattr(cockpit, "watch", lambda cp, refresh_s, probe_s, views=None, search="", tz=None, tab=None: 0)
    assert cli.main(["tui", "--project", "demo", "--plain"]) == 0
    err = capsys.readouterr().err
    assert "newer brain" in err and "views are not remembered" in err
    assert cockpit.state_path().read_text(encoding="utf-8") == text

