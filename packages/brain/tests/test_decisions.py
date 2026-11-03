import io
import json
from datetime import date

import pytest
import yaml

from brain import decisions, graph, projects, records

AT = "2026-11-01T09:00:00Z"
OPTS = ["Telegram: one bot, already set up", "Email: SMTP", "Both:: twice the noise"]


def _root(store):
    return store.parents[1]


def _ask(root, **kw):
    args = dict(title="Alert channel", question="Which channel for the alerts?", options=OPTS, why="already set up",
                at=AT, items=["wi-one"], project="demo")
    args.update(kw)
    return decisions.ask(root, **args)


def test_ask_writes_a_pending_decision_and_refuses_bad_ones(store):
    root = _root(store)
    ddr, path = _ask(root, blocking=True, context="two lines")
    assert path == root / "records" / "ddr" / "ddr-2026-11-01-alert-channel.yaml"
    assert ddr["kind"] == "decision" and ddr["status"] == "pending"
    assert [o["label"] for o in ddr["options"]] == ["Telegram", "Email", "Both"]
    assert ddr["recommendation"] == {"option": "Telegram", "why": "already set up"}
    assert ddr["links"] == {"items": ["wi-one"], "project": "demo"}
    assert records.check(root) == ([], [])
    with pytest.raises(decisions.QueueError, match="2 to 4"):
        _ask(root, options=OPTS[:1], slug="one")
    with pytest.raises(decisions.QueueError, match="2 to 4"):
        _ask(root, options=OPTS + ["D", "E"], slug="five")
    with pytest.raises(decisions.QueueError, match="--why"):
        _ask(root, why=" ", slug="nowhy")
    with pytest.raises(decisions.QueueError, match="must come first"):
        _ask(root, recommend="Email", slug="second")
    with pytest.raises(SystemExit, match="exists"):
        _ask(root)


def test_answer_ack_archive_lifecycle(store):
    root = _root(store)
    _ask(root)
    _ask(root, title="Several", multi=True, slug="several")
    with pytest.raises(decisions.QueueError, match="not one of the options"):
        decisions.answer(root, "alert-channel", ["Pigeon"], at=AT)
    with pytest.raises(decisions.QueueError, match="takes one choice"):
        decisions.answer(root, "alert-channel", ["1", "2"], at=AT)
    with pytest.raises(decisions.QueueError, match="only an answered"):
        decisions.ack(root, "alert-channel", ["wi-one"], at=AT)
    assert decisions.answer(root, "alert-channel", ["tele"], at=AT)["answer"]["choices"] == ["Telegram"]
    multi = decisions.answer(root, "several", ["2", "both"], other="and a log line", at=AT)
    assert multi["answer"]["choices"] == ["Email", "Both"] and multi["answer"]["other"] == "and a log line"
    with pytest.raises(decisions.QueueError, match="not pending"):
        decisions.answer(root, "alert-channel", ["Email"], at=AT)
    ddr, unknown = decisions.ack(root, "alert-channel", ["adr-2026-10-30-x", "wi-one", "wi-later", "spec §3"],
                                 at=AT, session="s1", store=store)
    assert ddr["status"] == "archived" and unknown == ["wi-later"]
    assert ddr["links"]["adrs"] == ["adr-2026-10-30-x"] and ddr["links"]["items"] == ["wi-one", "wi-later"]
    assert ddr["applied"]["in"] == ["adr-2026-10-30-x", "wi-one", "wi-later", "spec §3"]
    kept, _ = decisions.ack(root, "several", ["wi-one"], at=AT, archive=False)
    assert kept["status"] == "integrated"
    assert decisions.archive(root, [], at=AT) == ["ddr-2026-11-01-several"]
    assert records.check(root) == ([], [])
    with pytest.raises(decisions.QueueError, match="several DDRs match"):
        decisions.find(root, "ddr-2026-11-01")


def test_pending_lists_the_queue_and_the_graph(store, monkeypatch):
    root = _root(store)
    _ask(root, blocking=True)
    _ask(root, title="Answered one", slug="answered")
    decisions.answer(root, "answered", ["Email"], at=AT)
    graph_data = {"open_questions": [{"id": "wi-one", "open": "Ada picks the host"}],
                  "spec_questions": [{"id": "spec-x", "questions": [{"label": "Q2", "question": "Which venue?"}]}],
                  "blocked_on_owner": [{"id": "wi-two", "external_blocker": "Ada adds the key"}],
                  "proposed_specs": [], "owner": "Ada"}
    monkeypatch.setattr(graph, "research_graph_json", lambda *a: dict(graph_data))
    data = decisions.pending(projects.for_root(root), today=date(2026, 11, 3))
    assert [e["id"] for e in data["pending"]] == ["ddr-2026-11-01-alert-channel"]
    assert data["pending"][0]["age_days"] == 2 and data["pending"][0]["blocking"]
    assert [e["id"] for e in data["answered"]] == ["ddr-2026-11-01-answered"]
    assert data["waiting_on_owner"] == 4 and data["owner"] == "Ada"
    text = "\n".join(decisions.render_pending(data))
    assert "ddr-2026-11-01-alert-channel [blocking] 2 d: Alert channel -> recommended: Telegram" in text
    assert "wi-one: Ada picks the host" in text and "spec-x Q2: Which venue?" in text
    assert "blocked on Ada (1)" in text and "wi-two: Ada adds the key" in text
    assert "ddr-2026-11-01-answered: Email" in text
    # an older copy of the engine (brain's fallback before research-graph 0.1.0) named the list blocked_on_robin
    legacy = {k: v for k, v in graph_data.items() if k not in ("blocked_on_owner", "owner")}
    legacy["blocked_on_robin"] = graph_data["blocked_on_owner"]
    monkeypatch.setattr(graph, "research_graph_json", lambda *a: dict(legacy))
    old = decisions.pending(projects.for_root(root), today=date(2026, 11, 3))
    old_text = "\n".join(decisions.render_pending(old))
    assert old["waiting_on_owner"] == 4 and "wi-two: Ada adds the key" in old_text
    assert "blocked on Ada (1)" in old_text  # no owner from the engine: config.json's
    monkeypatch.setattr(graph, "research_graph_json", lambda *a: None)
    assert "did not run" in "\n".join(decisions.render_pending(decisions.pending(projects.for_root(root))))
    assert decisions.pending(projects.for_root(root), kinds=("action",))["pending"] == []


def test_view_is_generated_and_checked_for_staleness(store):
    root = _root(store)
    _ask(root, blocking=True)
    _ask(root, title="Done one", slug="done")
    decisions.answer(root, "done", ["Email"], at=AT)
    decisions.ack(root, "done", ["wi-one"], at=AT)
    text = decisions.view(root, "demo")
    assert text.startswith("# Decision queue — demo\n\nGENERATED")
    assert "## Waiting on Ada (1)" in text and "- [ ] **Telegram** (recommended): one bot, already set up" in text
    assert "- [ ] Other: free text" in text and "## Archived (1)" in text
    assert "| `ddr-2026-11-01-done` | Done one | Email | wi-one | 2026-11-01 |" in text
    assert not decisions.view_stale(root, "demo")  # no view file yet: nothing stale
    decisions.write_view(root, "demo")
    assert not decisions.view_stale(root, "demo")
    decisions.answer(root, "alert-channel", ["Email"], at=AT)
    assert decisions.view_stale(root, "demo")


def test_announce_and_hook(store):
    root = _root(store)
    long_title = "A title long enough to wrap: " + "word " * 14
    _ask(root, title=long_title.strip()[:100], slug="long")
    assert decisions.announce(root) == ""
    decisions.answer(root, "long", ["Both"], at=AT)
    _ask(root, title="Other one", slug="other")
    decisions.answer(root, "other", [], other="it's 'quoted'", at=AT)
    text = decisions.announce(root / "notes")
    assert text.startswith("Ada answered 2 decision(s) that root has not integrated yet.")
    assert "- ddr-2026-11-01-long: Both (A title long enough to wrap:" in text
    assert "- ddr-2026-11-01-other: other: it's 'quoted' (Other one)" in text
    out = io.StringIO()
    import contextlib
    with contextlib.redirect_stdout(out):
        assert decisions.hook_main(["SessionStart"], stdin=io.StringIO(json.dumps({"cwd": str(root)}))) == 0
    hook = json.loads(out.getvalue())
    assert hook["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert hook["hookSpecificOutput"]["additionalContext"] == text
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert decisions.hook_main([], stdin=io.StringIO("not json")) == 0
    assert out.getvalue() == ""


def test_action_kind_validates_without_options(store):
    root = _root(store)
    rec = {"v": 1, "id": "ddr-2026-11-01-enter-the-key", "kind": "action", "title": "Enter the key",
           "question": "Put the exchange key in the vault", "status": "pending", "asked": {"at": AT}}
    records.write(root, "ddr", rec)
    assert records.check(root) == ([], [])
    bad = dict(rec, id="ddr-2026-11-01-no-options", kind="decision")
    with pytest.raises(SystemExit, match="options"):
        records.write(root, "ddr", bad)
    assert yaml.safe_load((root / "records" / "ddr" / f"{rec['id']}.yaml").read_text(encoding="utf-8"))["kind"] \
        == "action"


def test_hook_script_runs_isolated(store):
    """announce.py runs with python -I (no site-packages, so no PyYAML): the announcement needs the standard library
    only."""
    import subprocess
    import sys
    from pathlib import Path
    root = _root(store)
    _ask(root)
    decisions.answer(root, "alert-channel", ["Email"], at=AT)
    import brain
    script = Path(brain.__file__).resolve().parents[1] / "hooks" / "announce.py"
    out = subprocess.run([sys.executable, "-I", str(script), "SessionStart"], input=json.dumps({"cwd": str(root)}),
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0 and out.stderr == ""
    assert "ddr-2026-11-01-alert-channel: Email" in json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]
