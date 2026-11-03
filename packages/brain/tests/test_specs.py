import json

import pytest
import yaml

from brain import cli, decisions, graph, specs

AT = "2026-11-02T09:00:00Z"
OPTS = ["A: the first", "B: the second"]

THINKING_DOC = """# Futures

## 3. Forecast

The marker below is quoted, not set: `<!-- thinking: open -->`.

```markdown
<!-- thinking: open -->
```

## 4. The heading's distance
<!-- thinking: open: the distance function -->
Ada's words, « à réfléchir », are not a marker.
"""


@pytest.fixture
def spec_store(store):
    """The store fixture with proposed specs in every state, their documents and the DDRs that name them."""
    root = store.parents[1]
    nodes = store / "nodes" / "work.yaml"
    nodes.write_text(nodes.read_text(encoding="utf-8") + (
        "- {id: spec-ready, type: Spec, status: proposed, title: \"Ready\", anchor: \"docs/ready.md#top\",\n"
        "   props: {idea: \"Ada, 2026-11-02\"}}\n"
        "- {id: spec-open-ddr, type: Spec, status: proposed, title: \"Open DDR\", anchor: \"docs/open.md#top\"}\n"
        "- {id: spec-kept, type: Spec, status: proposed, title: \"Kept\",\n"
        "   props: {keep_proposed: \"waits on the pilot\"}}\n"
        "- {id: spec-thinking, type: Spec, status: proposed, title: \"Thinking\", anchor: \"docs/thinking.md#top\"}\n"
        "- {id: spec-none, type: Spec, status: proposed, title: \"No decision\"}\n"
        "- {id: spec-validated, type: Spec, status: proposed, title: \"Validated\",\n"
        "   props: {validated: \"Ada, 2026-11-02\"}}\n"
        "- {id: spec-open-prop, type: Spec, status: proposed, title: \"Open prop\",\n"
        "   props: {open: \"which venue first?\"}}\n"
        "- {id: spec-live, type: Spec, status: active, title: \"Live\"}\n"), encoding="utf-8")
    docs = root / "docs"
    docs.mkdir()
    (docs / "ready.md").write_text("# Ready\n\n## Decisions\n\n| Q1 | A, Ada 2026-11-02 |\n", encoding="utf-8")
    (docs / "open.md").write_text("# Open\n", encoding="utf-8")
    (docs / "thinking.md").write_text(THINKING_DOC, encoding="utf-8")

    def ddr(title, spec_refs, state):
        d, _ = decisions.ask(root, title=title, question=f"{title}?", options=OPTS, why="first", at=AT,
                             specs=spec_refs)
        if state in ("answered", "archived"):
            decisions.answer(root, d["id"], ["A"], at=AT)
        if state == "archived":
            decisions.ack(root, d["id"], ["adr-2026-11-02-x"], at=AT)
        return d["id"]

    ddr("Ready one", ["spec-ready 4.2"], "archived")  # a section after the id: still the spec's
    ddr("Ready two", ["spec-ready", "spec-thinking"], "archived")
    ddr("Open answered", ["spec-open-ddr"], "answered")
    ddr("Open pending", ["spec-open-ddr"], "pending")
    ddr("Kept one", ["spec-kept"], "archived")
    ddr("Prop one", ["spec-open-prop"], "archived")
    return store


@pytest.fixture
def no_questions(monkeypatch):
    """research_graph pending, faked: no unanswered spec question; the calls are counted."""
    calls = []

    def fake(root, store, *args):
        calls.append(args)
        return {"open_questions": [], "spec_questions": [], "blocked_on_owner": [], "proposed_specs": []}
    monkeypatch.setattr(graph, "research_graph_json", fake)
    return calls


def _nodes(store):
    return {n["id"]: n for n in yaml.safe_load((store / "nodes" / "work.yaml").read_text(encoding="utf-8"))}


def _rows(store, full=False):
    return {r.id: r for r in specs.readiness(store.parents[1], store, full=full)}


def test_thinking_marks_read_the_marker_only():
    marks = specs.thinking_marks(THINKING_DOC)
    assert marks == [{"line": 12, "section": "4. The heading's distance", "note": "the distance function"}]
    assert specs.thinking_marks("## A\n<!-- THINKING: open -->\n") == [{"line": 2, "section": "A", "note": ""}]
    assert specs.thinking_marks("## A\n<!-- thinking: closed 2026-11-03 -->\nà réfléchir\n") == []


def test_readiness_flips_only_the_settled_specs(spec_store, no_questions):
    rows = _rows(spec_store)
    assert sorted(rows) == ["spec-kept", "spec-none", "spec-open-ddr", "spec-open-prop", "spec-ready",
                            "spec-thinking", "spec-validated"]  # proposed ones only
    assert rows["spec-ready"].ready and rows["spec-ready"].ddrs == ["ddr-2026-11-02-ready-one",
                                                                    "ddr-2026-11-02-ready-two"]
    assert rows["spec-validated"].ready and rows["spec-validated"].closed_by() == "props.validated"
    assert not rows["spec-open-ddr"].ready
    assert rows["spec-open-ddr"].waits == [
        "1 DDR(s) waiting on Ada (ddr-2026-11-02-open-pending)",
        "1 DDR(s) answered, not applied: brain decision ack (ddr-2026-11-02-open-answered)"]
    assert rows["spec-kept"].kept == "waits on the pilot" and not rows["spec-kept"].ready
    assert rows["spec-kept"].line() == "spec-kept: kept proposed (props.keep_proposed: waits on the pilot)"
    assert rows["spec-thinking"].waits == ["open for thinking under '4. The heading's distance' (line 12: the "
                                           "distance function)"]
    assert rows["spec-none"].waits[0].startswith("no decision recorded")
    assert rows["spec-open-prop"].waits == ["props.open: which venue first?"]
    assert len(no_questions) == 1  # the engine ran once, for the candidates


def test_unanswered_questions_keep_a_spec_proposed(spec_store, monkeypatch):
    monkeypatch.setattr(graph, "research_graph_json", lambda root, store, *a: {"spec_questions": [
        {"id": "spec-ready", "questions": [{"label": "Q2"}, {"label": "Q3"}]}]})
    rows = _rows(spec_store)
    assert rows["spec-ready"].waits == ["2 unanswered question(s) in its document (Q2, Q3)"]
    assert rows["spec-validated"].ready
    monkeypatch.setattr(graph, "research_graph_json", lambda *a: None)  # the engine failed: nothing flips
    assert not any(r.ready for r in _rows(spec_store).values())


def test_the_engine_runs_only_for_candidates_unless_full(spec_store, no_questions):
    nodes = spec_store / "nodes" / "work.yaml"
    text = nodes.read_text(encoding="utf-8").replace("status: proposed, title: \"Ready\"", "status: active, "
                                                     "title: \"Ready\"").replace("status: proposed, title: \"Valid",
                                                                                 "status: active, title: \"Valid")
    nodes.write_text(text, encoding="utf-8")
    _rows(spec_store)
    assert no_questions == []  # every proposed spec waits on something cheaper to read
    _rows(spec_store, full=True)
    assert no_questions == [("pending",)]


def test_activate_writes_the_ready_ones_through_the_graph_editor(spec_store, no_questions):
    before = (spec_store / "nodes" / "work.yaml").read_text(encoding="utf-8")
    done = specs.activate(spec_store, specs.readiness(spec_store.parents[1], spec_store), via="brain refresh",
                          today="2026-11-02")
    assert [n["id"] for n in done] == ["spec-ready", "spec-validated"]
    nodes = _nodes(spec_store)
    assert nodes["spec-ready"]["status"] == "active"
    assert nodes["spec-ready"]["props"] == {
        "idea": "Ada, 2026-11-02",
        "activated": "2026-11-02 by brain refresh (every decision taken and applied, no thinking phase left)",
        "activated_by": "ddr-2026-11-02-ready-one, ddr-2026-11-02-ready-two"}
    assert nodes["spec-validated"]["props"]["activated_by"] == "props.validated"
    for nid in ("spec-open-ddr", "spec-kept", "spec-thinking", "spec-none", "spec-open-prop"):
        assert nodes[nid]["status"] == "proposed", nid
    after = (spec_store / "nodes" / "work.yaml").read_text(encoding="utf-8")
    assert after.startswith(before.split("- {id: spec-ready")[0])  # nothing above the flipped node moved
    assert specs.readiness(spec_store.parents[1], spec_store) and not any(
        r.ready for r in specs.readiness(spec_store.parents[1], spec_store))  # a second run flips nothing


def test_cli_spec_activate_plans_then_writes(spec_store, no_questions, capsys):
    base = ["--root", str(spec_store.parents[1]), "spec", "activate"]
    assert cli.main(base) == 0
    out = capsys.readouterr().out
    assert "spec-ready: ready, turns active (closed by ddr-2026-11-02-ready-one, ddr-2026-11-02-ready-two)" in out
    assert "spec-kept: kept proposed" in out
    assert out.rstrip().endswith("specs: 7 proposed, 2 ready (not written: --write)")
    assert _nodes(spec_store)["spec-ready"]["status"] == "proposed"
    assert cli.main(base + ["--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [s["id"] for s in data[0]["specs"] if s["ready"]] == ["spec-ready", "spec-validated"]
    assert cli.main(base + ["--write"]) == 0
    assert "specs: 7 proposed, 2 turned active" in capsys.readouterr().out
    assert _nodes(spec_store)["spec-ready"]["props"]["activated"].startswith(
        f"{__import__('datetime').date.today().isoformat()} by brain spec activate")
    with pytest.raises(SystemExit, match="takes one project"):
        cli.main(base + ["--write", "--all"])


def test_sync_flips_and_check_reports(spec_store, no_questions, monkeypatch, capsys):
    root = spec_store.parents[1]
    calls = []
    monkeypatch.setattr(graph, "research_graph", lambda r, s, *a: calls.append(a) or 0)
    assert cli.main(["--root", str(root), "check"]) == 0  # a warning, not an error; nothing written
    out = capsys.readouterr().out
    assert "warning: spec spec-ready is ready to turn active (closed by ddr-2026-11-02-ready-one, " \
           "ddr-2026-11-02-ready-two): brain refresh, or brain spec activate --write" in out
    assert _nodes(spec_store)["spec-ready"]["status"] == "proposed"
    calls.clear()
    assert cli.main(["--root", str(root), "sync", "--offline"]) == 0
    out = capsys.readouterr().out
    assert "spec spec-ready: turned active (closed by ddr-2026-11-02-ready-one, ddr-2026-11-02-ready-two)" in out
    assert "spec spec-validated: turned active (closed by props.validated)" in out
    nodes = _nodes(spec_store)
    assert nodes["spec-ready"]["status"] == "active" and "by brain sync" in nodes["spec-ready"]["props"]["activated"]
    assert nodes["spec-open-ddr"]["status"] == nodes["spec-kept"]["status"] == "proposed"
    assert calls[0] == ("sync", "--write")  # the flip came before the graph sync
    assert cli.main(["--root", str(root), "check"]) == 0
    assert "is ready to turn active" not in capsys.readouterr().out


def test_real_engine_reads_a_question_left_open(spec_store):
    pytest.importorskip("research_graph")
    if graph.engine() is None:
        pytest.skip("the research_graph engine is not importable in this Python")
    root = spec_store.parents[1]
    (root / "docs" / "ready.md").write_text("# Ready\n\n## Questions\n\n1. Which venue first?\n", encoding="utf-8")
    rows = _rows(spec_store)
    assert rows["spec-ready"].waits == ["1 unanswered question(s) in its document (1)"]
    assert rows["spec-validated"].ready  # props.validated: the engine reads no question
