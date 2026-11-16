"""wi-brain-evidence-views: props.evidence (brain item close --evidence) shown where props.pr is: the cockpit's item
detail, the digest's closed items, the lessons' items, research_graph's closed report and the journal's close line
brain item close prints. Fictitious names only."""

import pytest
from brain import cli, detail, digest, graph, lessons, projects, status
from research_graph import report


@pytest.fixture
def brain(store, monkeypatch):
    """The store fixture's root registered as the project demo, a non-code project: it closes with --evidence."""
    root = store.parents[1]
    monkeypatch.setenv("BRAIN_PROJECTS", str(root / "projects.yaml"))
    monkeypatch.delenv("BRAIN_CONFIG", raising=False)
    (root / "projects.yaml").write_text("demo:\n  root: .\n  lifecycle: {typologies: [strategy]}\n", encoding="utf-8")
    return root


@pytest.fixture
def demo(store):
    return projects.Project("demo", store.parents[1], stores=[store]), None


def test_proof_names_the_pr_and_the_evidence_on_one_line():
    assert graph.proof({"pr": "demo #7"}) == "demo #7"
    assert graph.proof({"evidence": "memo v3; ddr-x"}) == "evidence memo v3; ddr-x"
    assert graph.proof({"pr": "demo #7", "evidence": "a build"}) == "demo #7; evidence a build"
    assert graph.proof({"evidence": "two\nlines  and\ttabs"}) == "evidence two lines and tabs"
    assert graph.proof({}) == graph.proof(None) == graph.proof({"pr": "", "evidence": None}) == ""


def test_the_close_line_carries_the_proof_and_the_outcome():
    node = {"id": "wi-one", "status": "done", "props": {"evidence": "memo v3", "done": "2026-11-16 shipped: 50% of $X"}}
    assert graph.close_line(node) == "- wi-one done (evidence memo v3): shipped: 50% of $X"
    dropped = {"id": "wi-two", "status": "dropped", "props": {"evidence": "superseded", "dropped": "2026-11-16"}}
    assert graph.close_line(dropped) == "- wi-two dropped (evidence superseded)"
    assert graph.close_line({"id": "wi-3", "status": "done", "props": None}) == "- wi-3 done"


def test_brain_item_close_prints_the_journal_line_with_its_evidence(brain, capsys):
    assert cli.main(["--root", str(brain), "item", "close", "wi-one", "--evidence", "the memo v3", "--outcome",
                     "approved"]) == 0
    out = capsys.readouterr().out
    assert "journal line (brain journal add): - wi-one done (evidence the memo v3): approved" in out


def test_the_item_detail_shows_the_evidence_beside_the_pr(demo):
    p, _ = demo
    st = status._store(p)
    st.nodes["wi-one"]["props"]["evidence"] = "the memo v3"
    s = dict(detail.item("wi-one", p, st)["sections"])
    assert s["Evidence"] == ["the memo v3"] and "PR" not in s
    st.nodes["wi-one"]["props"]["pr"] = "demo #7"
    s = dict(detail.item("wi-one", p, st)["sections"])
    assert s["PR"] == ["demo #7"] and s["Evidence"] == ["the memo v3"]


def _row(**more):
    return {"id": "wi-one", "status": "done", "day": "2026-11-16", "priority": "", "title": "One", "outcome": "",
            "pr": "", "evidence": "", "proof": "", **more}


@pytest.mark.parametrize("row, shown", [
    (_row(evidence="memo v3", proof="evidence memo v3"), "(evidence memo v3)"),
    (_row(pr="demo #7", proof="demo #7"), "(demo #7)"),
])
def test_the_digest_shows_the_proof_of_a_closed_item(row, shown):
    part = digest._items([row])
    assert any(shown in line for line in part.levels[0])


def test_a_digest_row_without_a_proof_key_still_reads():
    row = _row()
    del row["proof"]
    assert digest._items([row]).levels[0][0].startswith("- wi-one 2026-11-16")


def test_a_lesson_shows_the_proof_of_the_item_it_led_to():
    assert lessons._led({"id": "wi-one", "status": "done", "pr": "", "evidence": "memo v3", "done": "2026-11-16"}) \
        == "  led to wi-one [done] evidence memo v3, done 2026-11-16"
    assert lessons._evidence({"evidence": "memo v3"}) == {"evidence": "memo v3"} and lessons._evidence({}) == {}
    assert lessons._led({"id": "wi-one", "status": "todo", "pr": "", "done": ""}) == "  led to wi-one [todo]"


def test_research_graph_closed_report_shows_the_evidence():
    rows = [{"id": "wi-one", "status": "done", "title": "One", "date": "2026-11-16", "date_source": "props.done",
             "commit": None, "pr": None, "evidence": "memo v3", "outcome": "approved"},
            {"id": "wi-two", "status": "done", "title": "Two", "date": "2026-11-15", "date_source": "props.done",
             "commit": None, "pr": "demo #7", "outcome": None}]                     # an older row: no evidence key
    lines = report.closed(rows)
    assert lines[1].split() == ["evidence", "memo", "v3", "approved"]
    assert lines[3].split() == ["pr", "demo", "#7"]
