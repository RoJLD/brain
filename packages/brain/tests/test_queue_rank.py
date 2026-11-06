"""The queue ranked by what each entry holds up (wi-brain-queue-priority) and the owner's display name
(wi-brain-owner-label), on fixtures owned by Ada."""

import json
import os
from datetime import date

import pytest

from brain import batch, cli, cockpit, config, decisions, forecast, projects, queue, status

AT = "2026-11-01T09:00:00Z"
TODAY = date(2026, 11, 3)


def _root(store):
    return store.parents[1]


def _graph(store):
    """wi-p0 (P0); wi-p3a..wi-p3f (P3) all part of ms-low; wi-p1 (P1) -> ms-near; wi-slack (P2) -> ms-near;
    wi-due (P2, due in 5 days); wi-free (no priority)."""
    with open(store / "nodes" / "work.yaml", "a", encoding="utf-8") as fh:
        fh.write("- {id: wi-p0, type: WorkItem, status: todo, title: \"P0\", props: {priority: P0}}\n"
                 + "".join(f"- {{id: wi-p3{c}, type: WorkItem, status: todo, title: \"P3 {c}\", props: {{priority: P3}}}}\n"
                           for c in "abcdef")
                 + "- {id: ms-low, type: Milestone, status: pending, title: \"Low\"}\n"
                   "- {id: ms-near, type: Milestone, status: pending, title: \"Near\"}\n"
                   "- {id: wi-p1, type: WorkItem, status: todo, title: \"P1\", props: {priority: P1}}\n"
                   "- {id: wi-slack, type: WorkItem, status: todo, title: \"Slack\", props: {priority: P2}}\n"
                   "- {id: wi-due, type: WorkItem, status: todo, title: \"Due\", props: {priority: P2, due: 2026-11-08}}\n"
                   "- {id: wi-free, type: WorkItem, status: todo, title: \"Free\"}\n")
    with open(store / "edges" / "work.yaml", "a", encoding="utf-8") as fh:
        fh.write("".join(f"- {{from: wi-p3{c}, to: wi-p3a, type: depends_on}}\n" for c in "bcdef")
                 + "".join(f"- {{from: wi-p3{c}, to: ms-low, type: part_of}}\n" for c in "abcdef")
                 + "- {from: wi-p1, to: ms-near, type: part_of}\n- {from: wi-slack, to: ms-near, type: part_of}\n")


FC = {"as_of": "2026-11-03T08:00:00", "milestones": [
    {"id": "ms-near", "days": {"p50": 6.0}, "dates": {"p50": "2026-11-09"}},
    {"id": "ms-low", "days": {"p50": 40.0}, "dates": {"p50": "2026-12-13"}}],
      "items": [{"id": "wi-p1", "milestone": "ms-near", "days": {"p50": 5.5}},       # the critical path
                {"id": "wi-slack", "milestone": "ms-near", "days": {"p50": 1.0}},    # 5 days of slack
                {"id": "wi-p3a", "milestone": "ms-low", "days": {"p50": 3.0}}]}


def _ask(root, title, items, **kw):
    return decisions.ask(root, title=title, question=f"{title}?", options=["Yes: go", "No"], why="simplest", at=AT,
                         items=items, project="demo", **kw)


def _queue(store):
    root = _root(store)
    _graph(store)
    _ask(root, "Many P3s", ["wi-p3a"])
    _ask(root, "One P0", ["wi-p0"])
    _ask(root, "Critical", ["wi-p1"])
    _ask(root, "Slack", ["wi-slack"])
    _ask(root, "Due item", ["wi-due"])
    _ask(root, "Free", ["wi-free"])
    queue.add(root, kind="action", title="Sign the pilot", what="the contract", at=AT, items=["wi-free"],
              due="2026-11-04", minutes=20)
    return root


def _by(data):
    return {e["title"]: e for e in data["entries"]}


def test_forecast_waiting_is_the_slip_per_day_and_the_nearest_milestone():
    w = forecast.waiting(FC, ["wi-p1", "wi-slack"], 7, TODAY)
    assert w["items"]["wi-p1"] == {"milestone": "ms-near", "slack_days": 0.5, "slip": 0.929, "p50": "2026-11-09"}
    assert w["items"]["wi-slack"]["slip"] == pytest.approx(2 / 7, abs=1e-3)   # 5 days of slack absorb most of a week
    assert (w["slip"], w["slip_milestone"], w["nearest"], w["nearest_days"]) == (0.929, "ms-near", "ms-near", 6.0)
    assert forecast.waiting({}, ["wi-p1"]) == {} and forecast.waiting(FC, ["wi-free"])["slip"] == 0.0
    later = forecast.waiting(FC, ["ms-low"], 7, date(2026, 11, 13))   # a forecast 10 days old: the p50 comes closer
    assert later["nearest_days"] == 30.0


def test_the_score_ranks_by_what_each_entry_holds_up(store):
    root = _queue(store)
    data = queue.build(projects.for_root(root), today=TODAY, with_graph=False, transcripts=False, fc=FC,
                       owner_order={})
    by = _by(data)
    # a P0 above six P3s, whatever their count; the count is capped
    assert by["One P0"]["score"] > by["Many P3s"]["score"] and by["Many P3s"]["terms"]["count"] == 1.75
    assert by["One P0"]["band"] == "now" and by["One P0"]["band_why"] == "a P0"
    # the critical path: almost a day of slip per day of waiting; the slack absorbs most of it
    assert by["Critical"]["band"] == "now" and by["Critical"]["slip"] == 0.929
    assert by["Critical"]["terms"]["slip"] == 5.57 and by["Slack"]["terms"]["slip"] == 1.72
    assert by["Slack"]["band"] == "week" and by["Slack"]["band_why"] == "a slip on ms-near"
    assert by["Critical"]["nearest"] == "ms-near" and by["Critical"]["terms"]["milestone"] == pytest.approx(2.57)
    # a stated deadline weighs above the count: the item's own (in 5 days), the DDR's (tomorrow)
    assert by["Due item"]["band"] == "week" and by["Due item"]["due"] == "2026-11-08"
    assert by["Due item"]["terms"]["deadline"] == 6.0 > queue.COUNT_MAX
    pilot = by["Sign the pilot"]
    assert pilot["band"] == "now" and pilot["due"] == "2026-11-04" and pilot["terms"]["deadline"] == 10.0
    assert pilot["minutes"] == 20 and pilot["terms"]["effort"] == pytest.approx(0.33)   # a long one: little bonus
    assert by["Free"]["band"] == "later" and by["Free"]["terms"]["age"] == 0.2
    assert data["bands"] == {"now": 3, "week": 2, "later": 2}
    assert [e["band"] for e in data["entries"]] == ["now"] * 3 + ["week"] * 2 + ["later"] * 2
    now = [e["title"] for e in data["entries"][:3]]
    assert now == sorted(now, key=lambda t: -by[t]["score"])   # the score orders each band
    line = queue.explain(by["Critical"])
    assert line.startswith("score ") and "slip 5.57 (0.929 d per day of waiting on ms-near)" in line
    assert "milestone 2.57 (ms-near p50 2026-11-09)" in line and "; band now: the critical path of ms-near" in line
    text = "\n".join(queue.render(data, why=True))
    assert " now (3): blocking, the critical path" in text and " this week (2): " in text
    assert "          score " in text and "| now 3, this week 2, when you can 2" in text


def test_without_a_forecast_the_terms_are_zero_and_said(store):
    root = _queue(store)
    data = queue.build(projects.for_root(root), today=TODAY, with_graph=False, transcripts=False, owner_order={})
    assert all(e["terms"]["slip"] == 0 and e["terms"]["milestone"] == 0 for e in data["entries"])
    assert any("no forecast saved" in n for n in data["notes"])
    assert "; no forecast" in queue.explain(data["entries"][0])
    forecast.save({**FC, "project": projects.for_root(root).name})   # brain forecast's latest.json is read
    again = queue.build(projects.for_root(root), today=TODAY, with_graph=False, transcripts=False, owner_order={})
    assert _by(again)["Critical"]["slip"] == 0.929


def test_the_owners_order_wins(store, capsys):
    root = _queue(store)
    proj = projects.for_root(root)
    free = next(e["id"] for e in queue.build(proj, today=TODAY, with_graph=False, transcripts=False)["entries"]
                if e["title"] == "Free")
    assert "Ada's order 1" in queue.order(free, at="2026-11-03T10:00:00Z", position=1, band="now")
    data = queue.build(proj, today=TODAY, with_graph=False, transcripts=False, fc=FC)
    first = data["entries"][0]
    assert (first["id"], first["band"], first["order"], first["band_why"]) == (free, "now", 1, "Ada's band")
    assert "#1" in "\n".join(queue.render(data)) and "Ada's order 1" in queue.explain(first)
    assert cli.main(["--root", str(root), "queue", "order", free, "--clear", "--at", "2026-11-03T11:00:00Z"]) == 0
    assert "back to the score's order" in capsys.readouterr().out
    after = _by(queue.build(proj, today=TODAY, with_graph=False, transcripts=False, fc=FC))["Free"]
    assert after["band"] == "later" and after["order"] is None
    with pytest.raises(queue.QueueError):
        queue.order(free, at=AT, band="soon")
    with pytest.raises(queue.QueueError):
        queue.order(free, at=AT)


def _app(tmp_path, sessions):
    """The desktop app's session files: {app id: (cli id, archived)}."""
    d = tmp_path / "appdata" / "Claude-Data" / "acct" / "claude-code-sessions" / "a" / "b"
    d.mkdir(parents=True, exist_ok=True)
    for sid, (cli_id, archived) in sessions.items():
        (d / f"{sid}.json").write_text(json.dumps({"sessionId": sid, "cliSessionId": cli_id, "cwd": str(tmp_path),
                                                   "isArchived": archived}), encoding="utf-8")


def _denied(tmp_path, monkeypatch, sid):
    cfg = tmp_path / "claude"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    d = cfg / "projects" / "p1"
    d.mkdir(parents=True, exist_ok=True)
    rows = [{"type": "assistant", "timestamp": "2026-11-02T10:00:00Z", "sessionId": sid, "cwd": str(tmp_path),
             "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "x"}}]}},
            {"type": "user", "timestamp": "2026-11-02T10:00:01Z", "sessionId": sid, "cwd": str(tmp_path),
             "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": True,
                                      "content": "Permission to use Bash has been denied."}]}}]
    (d / f"{sid}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_a_denial_expires_when_its_session_is_archived_or_gone(tmp_path, monkeypatch, brain_home):
    _denied(tmp_path, monkeypatch, "cli-1")
    assert [d["call"] for d in queue.scan(7, TODAY)["denials"]] == ["Bash: x"]   # no app here: never expires
    _app(tmp_path, {"local_1": ("cli-1", False)})
    assert queue.scan(7, TODAY)["expired"] == []                                 # its session is live
    _app(tmp_path, {"local_1": ("cli-1", True)})
    s = queue.scan(7, TODAY)
    assert s["denials"] == [] and s["expired"][0]["why"] == "its session is archived"
    state = queue.session_states(tmp_path / "claude" / "projects")
    assert state("cli-1") == "archived" and state("cli-x") == "gone"   # neither in the app nor a transcript
    ledger = brain_home / "ledger"
    ledger.mkdir(parents=True, exist_ok=True)
    (ledger / "guards-2026-11.jsonl").write_text(json.dumps(  # a guard refusal of a session long gone
        {"at": "2026-11-02T10:00:00Z", "guard": "owner", "decision": "denied", "session_id": "cli-gone",
         "cwd": str(tmp_path), "reason": "r", "request": {"ref": "guard-abc", "command": "brain x"}}) + "\n",
        encoding="utf-8")
    s = queue.scan(7, TODAY)
    assert {x["id"]: x["why"] for x in s["expired"]}["guard-abc"] == "its session is gone"
    assert queue.stale({"sessions": ["cli-1", "cli-gone"]}, state) == "its sessions are archived or gone"
    assert queue.stale({"sessions": []}, state) == "" and queue.stale({"sessions": ["cli-1"]}, None) == ""


def test_status_and_zen_show_the_bands(store, capsys, monkeypatch):
    class Today(date):   # brain status reads the real date: pinned to the fixture's day, or the bands drift with it
        @classmethod
        def today(cls):
            return TODAY
    monkeypatch.setattr(queue, "date", Today)
    root = _queue(store)
    proj = projects.for_root(root)
    forecast.save({**FC, "project": proj.name})
    q = status.queues([proj], quick=True, every=False, root=root)
    assert q[proj.name]["bands"] == {"now": 3, "week": 2, "later": 2}
    line = status._decisions({"pending": 7, "blocking": 0, "answered": 0, "open_questions": 0, "queue": q[proj.name]})
    assert line.startswith("7 waiting on Ada") and "(now 3, this week 2, when you can 2)" in line
    data = batch.build(proj, today=TODAY)
    assert [b["band"] for b in data["batches"]][0] == "now" and batch.session(data, 1) >= 1
    zen = "\n".join(batch.zen(data, minutes=0))
    assert "Batch 1/" in zen and " · now · " in zen


# --- the owner's display name (UX-16) ---

def _config(tmp_path, monkeypatch, identity):
    f = tmp_path / "brain" / "config.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"v": 1, "identity": identity}), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(f))
    return f


def test_the_display_name_titles_the_views_and_the_id_stays(tmp_path, monkeypatch, store):
    _config(tmp_path, monkeypatch, {"owner": "Ada", "display_name": "Ada L."})
    assert (config.owner_of(), config.name_of()) == ("Ada", "Ada L.")
    assert config.describe(config.load())["display_name"] == "Ada L." and config.check() == []
    assert cockpit.queue_title() == "Ada L.'s queue" and cockpit.title("queue") == "Ada L.'s queue"
    assert "What waits on Ada L.:" in cockpit.help_lines("queue")[0]
    args = cli.build_parser().parse_args(["queue", "done", "x"])
    assert args.by == "Ada"   # the records keep the owner's id
    _config(tmp_path, monkeypatch, {"owner": "Ada"})
    assert config.name_of() == "Ada" and cockpit.queue_title() == "Ada's queue"


def test_the_queue_title_by_language_unnamed_and_free(tmp_path, monkeypatch, brain_home):
    assert cockpit.queue_title("Ada", "fr") == "File d'Ada" and cockpit.queue_title("Bob", "fr") == "File de Bob"
    assert cockpit.queue_title("Ada", "en") == "Ada's queue"
    assert cockpit.queue_title(config.NO_OWNER, "en") == "My queue" and cockpit.queue_title("", "fr") == "Ma file"
    monkeypatch.setenv("BRAIN_LANG", "fr")
    assert cockpit.lang() == "fr" and cockpit.title("queue") == "File d'Ada"
    monkeypatch.delenv("BRAIN_LANG")
    assert cockpit.save_state({"settings": {"lang": "fr", "titles": {"queue": "Ma file à moi", "nope": "x",
                                                                       "frontier": " "}}})
    got = cockpit.load_state()["settings"]
    assert got == {"lang": "fr", "titles": {"queue": "Ma file à moi"}}   # an unknown panel or a blank title: left out
    assert cockpit.title("queue") == "Ma file à moi" and cockpit.title("frontier") == "Frontier"
    assert cockpit.queue_lines({"projects": []})[0].startswith("Ma file à moi (0: ")
    _config(tmp_path, monkeypatch, {"owner": "Ada", "display_name": "Ada L."})
    cockpit.save_state({"settings": {"lang": "fr"}})
    assert cockpit.title("queue") == "File d'Ada L."


def test_no_one_named_is_my_queue(tmp_path, monkeypatch, brain_home):
    f = tmp_path / "empty" / "config.json"
    f.parent.mkdir()
    f.write_text(json.dumps({"v": 1}), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(f))
    assert config.name_of() == config.NO_OWNER and cockpit.title("queue") == "My queue"


def test_the_settings_are_read_again_when_two_writes_share_a_time(brain_home):
    """Windows stamps file times from a coarse clock: two writes in a row can leave one mtime."""
    path = cockpit.state_path()
    assert cockpit.save_state({"settings": {"titles": {"queue": "Ma file à moi"}}})
    assert cockpit.title("queue") == "Ma file à moi"
    stamp = path.stat().st_mtime_ns
    assert cockpit.save_state({"settings": {"lang": "fr"}})   # the same process: its cache is cleared
    os.utime(path, ns=(stamp, stamp))
    assert cockpit.title("queue") == "File d'Ada"
    path.write_text(json.dumps({"cockpit": 1, "settings": {"titles": {"queue": "Another writer's title"}}}),
                    encoding="utf-8")   # another process (the TUI): the same time, another size
    os.utime(path, ns=(stamp, stamp))
    assert cockpit.title("queue") == "Another writer's title"
