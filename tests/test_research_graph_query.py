"""Backlog, item, closed, roadmap and pending-decision queries (research_graph.query) on a small graph, and the
spec question parser."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from research_graph import query
from research_graph.history import Commit, Event
from tests.backlog_world import write_brain, write_store


@pytest.fixture
def src(tmp_path):
    write_store(tmp_path / "research-lab")
    return query.load_source(tmp_path / "research-lab" / "notes" / "graph")


def _ids(rows):
    return [r["id"] for r in rows]


def test_source_defaults_to_the_repo_two_levels_up(src, tmp_path):
    assert src.name == "research-lab" and src.repo_root == tmp_path / "research-lab"
    assert src.to_json()["overlays"] == []


def test_list_sorts_by_status_then_priority_then_id(src):
    rows = query.list_items(src.graph, statuses=["doing", "todo", "blocked"])
    assert _ids(rows) == ["wi-doing", "wi-todo", "wi-free", "wi-prereq", "wi-ext", "wi-ext2"]
    todo = rows[1]
    assert todo["priority_proposed"] == "P2" and todo["blockers"] == ["wi-doing"]
    assert todo["milestones"] == ["ms-sub"]
    assert query.counts(rows) == {"doing": 1, "todo": 3, "blocked": 2}
    assert _ids(query.list_items(src.graph, statuses=["done", "dropped"])) == [
        "wi-done-dated", "wi-done-undated", "wi-dropped"]


def test_priority_filters_validated_proposed_and_none(src):
    g = src.graph
    assert _ids(query.list_items(g, priorities=["P1"])) == ["wi-doing"]
    assert _ids(query.list_items(g, priorities=["p2?"])) == ["wi-todo"]
    assert "wi-todo" in _ids(query.list_items(g, priorities=["none"]))
    assert "wi-doing" not in _ids(query.list_items(g, priorities=["none"]))
    assert query.priority_label(query.item_row(g, "wi-todo")) == "P2?"
    assert query.priority_label(query.item_row(g, "wi-free")) == "-"


def test_repo_prop_and_text_filters(src):
    g = src.graph
    assert _ids(query.list_items(g, repo="Ops-Repo")) == ["wi-doing"]
    assert _ids(query.list_items(g, repo="quant-marketdata")) == ["wi-free"]
    # no repo prop, no repo in pr: the store's own repo
    assert "wi-prereq" in _ids(query.list_items(g, repo="research-lab", default_repo="research-lab"))
    assert "wi-doing" not in _ids(query.list_items(g, repo="research-lab", default_repo="research-lab"))
    assert _ids(query.list_items(g, props={"external_blocker": None})) == ["wi-ext", "wi-ext2"]
    assert _ids(query.list_items(g, props={"external_blocker": "ada"})) == ["wi-ext"]
    assert _ids(query.list_items(g, text="funding item")) == ["wi-free"]
    assert _ids(query.list_items(g, text="funding", types=None)) == ["wi-free", "exp-1"]  # unknown status last
    assert _ids(query.list_items(g, ids={"wi-ext"})) == ["wi-ext"]


def test_repos_of_reads_repo_repos_and_pr():
    assert query.repos_of({"repos": "research-lab, ops-repo"}) == ["research-lab", "ops-repo"]
    assert query.repos_of({"pr": "research-lab #19 (F6), #30 (F7)"}) == ["research-lab"]
    assert query.repos_of({"pr": "my-brain #2, team-brain #1"}) == ["my-brain", "team-brain"]
    assert query.repos_of({}, "research-lab") == ["research-lab"]


def test_show_item_links_both_ways_and_ids_named_in_props(src):
    d = query.show_item(src.graph, "wi-todo")
    assert [(e["edge"], e["id"]) for e in d["out"]] == [
        ("depends_on", "wi-doing"), ("part_of", "ms-sub"), ("specified_by", "spec-draft")]
    assert d["in"] == [] and d["mentions"] == []  # spec-draft is named in props but already linked
    doing = query.show_item(src.graph, "wi-doing")
    assert [m["id"] for m in doing["mentioned_by"]] == ["wi-free"]  # after: "wi-doing stage 1"
    assert doing["waiting_on_it"] == ["wi-todo"] and doing["prerequisites"] == ["wi-prereq"]
    free = query.show_item(src.graph, "wi-free")
    assert [m["id"] for m in free["mentions"]] == ["wi-doing"]
    with pytest.raises(KeyError):
        query.show_item(src.graph, "wi-nope")


def _event(nid, new, day):
    return Event(nid, "WorkItem", "status", Commit("a" * 40, datetime.fromisoformat(f"{day}T12:00:00+00:00"),
                                                     "Merge pull request #9 from x/y"), "todo", new)


def test_closed_items_dates_from_props_then_git(src):
    rows = query.closed_items(src.graph)
    assert [(r["id"], r["date"], r["date_source"]) for r in rows] == [
        ("wi-done-dated", "2026-10-20", "props.done"),
        ("wi-dropped", "2026-10-10", "props.done"),
        ("wi-done-undated", None, None),
    ]
    assert rows[0]["outcome"] == "shipped it" and rows[0]["pr"] == "research-lab #5"
    rows = query.closed_items(src.graph, events=[_event("wi-done-undated", "done", "2026-10-25"),
                                                 _event("wi-done-dated", "done", "2026-10-01")])
    assert [(r["id"], r["date"], r["date_source"], r["commit"]) for r in rows][:2] == [
        ("wi-done-undated", "2026-10-25", "git", "#9"), ("wi-done-dated", "2026-10-20", "props.done", None)]
    assert _ids(query.closed_items(src.graph, since="2026-10-15")) == ["wi-done-dated"]


def test_roadmap_orders_milestones_and_lists_what_moves_them(src):
    ms = query.roadmap(src.graph)
    assert _ids(ms) == ["ms-sub", "ms-top", "ms-old", "ms-older"]  # pending by id, then reached newest first
    top = ms[1]
    assert top["trigger"] == "all done" and top["sub_milestones"] == ["ms-sub"]
    assert _ids(top["part_of"]) == ["wi-doing", "wi-todo", "wi-done-dated"]  # through ms-sub too
    assert _ids(top["depends_on"]) == ["wi-prereq"]  # open prerequisite outside the milestone
    assert _ids(top["mentions"]) == ["wi-ext2"]  # names ms-top in a prop, not already listed
    assert top["by_status"] == {"doing": 1, "done": 1, "todo": 1}
    assert top["critical_path"] == ["wi-doing", "wi-todo"]
    old = ms[2]
    assert old["reached_date"] == "2026-09-15" and old["reached"] == "2026-09-15: evidence"
    assert ms[0]["parents"] == ["ms-top"]


def test_spec_questions_numbered_answer_markers_and_closed_sections(src, tmp_path):
    qs = query.spec_questions((tmp_path / "research-lab" / "docs" / "specs" / "2026-10-01-draft.md")
                              .read_text(encoding="utf-8"))
    assert [(q["label"], q["answered"]) for q in qs] == [("1", False), ("2", True), ("3", False)]
    assert qs[0]["question"] == "Cadence: daily or hourly? A second line of the same question."


def test_spec_questions_labels_ticks_decision_tables_and_reformulations(tmp_path):
    from tests.backlog_world import GOV_SPEC

    qs = {q["label"]: q for q in query.spec_questions(GOV_SPEC)}
    assert set(qs) == {"Q1", "Q2", "Q3", "-1"}  # the "pour mémoire" section and the code block are ignored
    assert qs["Q1"]["answered"] and qs["Q1"]["decision"] == "A : public"  # decision table
    assert qs["Q2"]["answered"]  # ticked box
    assert not qs["Q3"]["answered"] and qs["Q3"]["decision"].startswith("Ouverte")
    assert qs["Q3"]["question"] == "reformulée : one command or one per project? (one choice)"
    assert qs["Q3"]["section"] == "8. Décisions de Ada (2026-10-21)"
    assert not qs["-1"]["answered"] and qs["-1"]["question"] == "which database?"


def test_spec_questions_do_not_take_a_topic_for_an_answer():
    text = "## 5. Questions ouvertes\n\n1. **Décision de publier le cœur** : Ada, oui/non/quand.\n" \
           "2. **Volume** : à estimer.\n   Ada : 15 venues suffisent.\n"
    assert [(q["label"], q["answered"]) for q in query.spec_questions(text, "Ada")] == [("1", False), ("2", True)]
    # "<owner> :" marks an answer only for the store's owner
    assert [q["answered"] for q in query.spec_questions(text)] == [False, False]


def test_pending_decisions(src):
    d = query.pending_decisions(src.graph, src.repo_root, today=date(2026, 10, 31))
    assert [(r["id"], r["open"]) for r in d["open_questions"]] == [("spec-gov", "Q3 (command shape)"),
                                                                    ("wi-ext", "which venue")]
    specs = {s["id"]: [q["label"] for q in s["questions"]] for s in d["spec_questions"]}
    # spec-live is validated without props.open: settled, its file is not even read
    assert specs == {"spec-draft": ["1", "3"], "spec-gov": ["Q3", "-1"]}
    assert [r["id"] for r in d["blocked_on_owner"]] == ["wi-ext"]  # wi-ext2 waits on the cluster
    assert d["owner"] == "Ada"
    assert [(r["id"], r["date"], r["age_days"]) for r in d["proposed_specs"]] == [("spec-draft", "2026-10-01", 30)]


def test_pending_without_an_owner_names_nobody(tmp_path):
    """A store whose schema.yaml declares no owner: nothing is blocked on a person, the report says "the owner"."""
    from research_graph import report
    from tests.backlog_world import SCHEMA

    store = write_store(tmp_path / "lab")
    (store / "schema.yaml").write_text(SCHEMA.replace("owner: Ada\n", ""), encoding="utf-8")
    s = query.load_source(store)
    d = query.pending_decisions(s.graph, s.repo_root, today=date(2026, 10, 31))
    assert d["owner"] is None and d["blocked_on_owner"] == []
    assert "Blocked on the owner (external_blocker): 0" in report.pending(d)


def test_overlay_items_carry_their_overlay(tmp_path):
    write_store(tmp_path / "research-lab")
    over = tmp_path / "hf" / "ops" / "graph"
    (over / "nodes").mkdir(parents=True)
    (over / "edges").mkdir()
    (over / "schema.yaml").write_text("node_types: [WorkItem]\nedge_types: [depends_on]\n"
                                      "statuses: [todo, done]\n", encoding="utf-8")
    (over / "nodes" / "ops.yaml").write_text("- {id: wi-hf, type: WorkItem, status: todo, title: hf}\n",
                                             encoding="utf-8")
    (over / "external.yaml").write_text("- {id: wi-doing}\n", encoding="utf-8")
    (over / "edges" / "ops.yaml").write_text("- {from: wi-hf, to: wi-doing, type: depends_on}\n", encoding="utf-8")
    s = query.load_source(tmp_path / "research-lab" / "notes" / "graph", overlays=[over])
    row = next(r for r in query.list_items(s.graph) if r["id"] == "wi-hf")
    assert row["overlay"] == str(over) and row["blockers"] == ["wi-doing"]


def test_brain_store_loads_on_its_own(tmp_path):
    write_brain(tmp_path / "my-brain")
    b = query.load_source(tmp_path / "my-brain" / "notes" / "graph")
    assert b.name == "my-brain"
    assert _ids(query.list_items(b.graph)) == ["wi-brain-x"]
    assert _ids(query.roadmap(b.graph)[0]["part_of"]) == ["wi-brain-x"]


def test_leading_date():
    assert query.leading_date("2026-10-30: x") == "2026-10-30"
    assert query.leading_date(date(2026, 1, 2)) == "2026-01-02"
    assert query.leading_date("splits, beta") is None and query.leading_date(None) is None
