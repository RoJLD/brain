import pytest
import yaml

from brain import cli, decisions, graph, milestones, resume

ORPHANS = ["wi-orph-dep", "wi-orph-none", "wi-orph-prop", "wi-orph-prop2", "wi-orph-spec", "wi-orph-theme",
           "wi-orph-tie"]


@pytest.fixture
def ms_store(store):
    """The store fixture with two pending milestones, a reached one, items in them and orphans of every kind."""
    schema = store / "schema.yaml"
    schema.write_text(schema.read_text(encoding="utf-8").replace("WorkItem: [todo, doing,", "WorkItem: [todo, doing, "
                                                                 "blocked,"), encoding="utf-8")
    nodes = store / "nodes" / "work.yaml"
    nodes.write_text(nodes.read_text(encoding="utf-8") + (
        "- {id: spec-y, type: Spec, status: active, title: \"Spec Y\"}\n"
        "- {id: ms-a, type: Milestone, status: pending, title: \"A\", props: {trigger: \"a\"}}\n"
        "- {id: ms-b, type: Milestone, status: pending, title: \"B\", props: {trigger: \"b\"}}\n"
        "- {id: ms-old, type: Milestone, status: reached, title: \"Old\", props: {trigger: \"o\"}}\n"
        "- {id: wi-in-a1, type: WorkItem, status: todo, title: \"In A\", props: {theme: \"3.1\"}}\n"
        "- {id: wi-in-a2, type: WorkItem, status: done, title: \"In A, done\"}\n"
        "- {id: wi-in-b1, type: WorkItem, status: todo, title: \"In B\", props: {theme: \"3.2\"}}\n"
        "- {id: wi-in-old, type: WorkItem, status: done, title: \"In Old\", props: {theme: \"3.2\"}}\n"
        "- {id: wi-gone, type: WorkItem, status: dropped, title: \"Dropped, in B\"}\n"
        "- {id: wi-orph-spec, type: WorkItem, status: todo, title: \"Spec X\"}\n"
        "- {id: wi-orph-dep, type: WorkItem, status: blocked, title: \"After B1\"}\n"
        "- {id: wi-orph-theme, type: WorkItem, status: todo, title: \"Theme\", props: {theme: \"3.2, 3.9\"}}\n"
        "- {id: wi-orph-none, type: WorkItem, status: doing, title: \"Nothing\"}\n"
        "- {id: wi-orph-prop, type: WorkItem, status: todo,\n"
        "   title: \"Waits on a new milestone\",\n"
        "   props: {priority_proposed: P2, milestone_proposed: ms-new}}\n"
        "- {id: wi-orph-prop2, type: WorkItem, status: todo, title: \"Proposed B\",\n"
        "   props: {milestone_proposed: ms-b}}\n"
        "- {id: wi-orph-tie, type: WorkItem, status: todo, title: \"Tie\"}\n"
        "- {id: wi-loose-done, type: WorkItem, status: done, title: \"Done, no milestone\"}\n"), encoding="utf-8")
    edges = store / "edges" / "work.yaml"
    edges.write_text(edges.read_text(encoding="utf-8") + (
        "- {from: wi-one, to: ms-a, type: part_of}\n"
        "- {from: wi-two, to: ms-b, type: part_of}\n"
        "- {from: wi-in-a1, to: ms-a, type: part_of}\n"
        "- {from: wi-in-a1, to: spec-x, type: specified_by}\n"
        "- {from: wi-in-a2, to: ms-a, type: part_of}\n"
        "- {from: wi-in-a2, to: spec-x, type: specified_by}\n"
        "- {from: wi-in-b1, to: ms-b, type: part_of}\n"
        "- {from: wi-in-b1, to: spec-x, type: specified_by}\n"
        "- {from: wi-in-old, to: ms-old, type: part_of}\n"
        "- {from: wi-gone, to: ms-b, type: part_of}\n"
        "- {from: wi-gone, to: spec-x, type: specified_by}\n"
        "- {from: wi-gone, to: spec-y, type: specified_by}\n"
        "- {from: wi-orph-spec, to: spec-x, type: specified_by}\n"
        "- {from: wi-orph-dep, to: wi-in-b1, type: depends_on}\n"
        "- {from: wi-orph-prop2, to: spec-x, type: specified_by}\n"
        "- {from: wi-orph-tie, to: spec-y, type: specified_by}\n"
        "- {from: wi-one, to: spec-y, type: specified_by}\n"
        "- {from: wi-two, to: spec-y, type: specified_by}\n"
        "- {from: wi-two, to: wi-orph-tie, type: depends_on}\n"), encoding="utf-8")
    return store


def _nodes(store):
    return {n["id"]: n for n in yaml.safe_load((store / "nodes" / "work.yaml").read_text(encoding="utf-8"))}


def _edges(store):
    return yaml.safe_load((store / "edges" / "work.yaml").read_text(encoding="utf-8"))


def test_orphans_and_signals_in_order(ms_store):
    ix = milestones.index(ms_store)
    assert ix.orphans() == ORPHANS  # done items, items in a milestone and dropped ones are not orphans
    got = {o: ix.suggest(o) for o in ORPHANS}
    # spec-x: wi-one (ms-a), wi-in-a1 and wi-in-a2 (ms-a), wi-in-b1 (ms-b); the dropped wi-gone does not count
    assert got["wi-orph-spec"] == milestones.Suggestion("ms-a", "spec", "spec spec-x: 3 of 5 item(s) in ms-a")
    assert got["wi-orph-dep"] == milestones.Suggestion("ms-b", "depends_on", "depends_on: 1 of 1 neighbour(s) in ms-b")
    # theme 3.2: wi-in-b1 (ms-b) and wi-in-old (a reached milestone: not a candidate)
    assert got["wi-orph-theme"] == milestones.Suggestion("ms-b", "theme", "theme 3.2, 3.9: 1 of 2 item(s) in ms-b")
    assert got["wi-orph-none"] is None
    # spec-y ties ms-a (wi-one) and ms-b (wi-two); wi-two is also a depends_on neighbour: ms-b
    assert got["wi-orph-tie"].milestone == "ms-b" and got["wi-orph-tie"].signal == "spec"


def test_orphan_rows_keep_existing_proposals(ms_store):
    rows = {r.id: r for r in milestones.suggest(ms_store)}
    assert rows["wi-orph-prop"].line() == ("wi-orph-prop [todo]: ms-new? (proposed; not a milestone yet: "
                                           "brain milestone add)")
    assert rows["wi-orph-prop2"].line() == ("wi-orph-prop2 [todo]: ms-b? (proposed; the signals say ms-a? "
                                            "(spec spec-x: 3 of 5 item(s) in ms-a))")
    assert rows["wi-orph-spec"].line() == "wi-orph-spec [todo]: ms-a? (new: spec spec-x: 3 of 5 item(s) in ms-a)"
    assert rows["wi-orph-none"].line().endswith("no signal (brain milestone add, or apply --set wi-orph-none=MS)")


def test_suggest_write_stores_new_proposals_only(ms_store):
    before = _nodes(ms_store)
    milestones.suggest(ms_store, only=["wi-orph-spec", "wi-orph-prop", "wi-orph-none"], write=True)
    after = _nodes(ms_store)
    assert after["wi-orph-spec"]["props"] == {"milestone_proposed": "ms-a",
                                              "milestone_reason": "spec spec-x: 3 of 5 item(s) in ms-a"}
    assert after["wi-orph-prop"] == before["wi-orph-prop"]  # an existing proposal is never overwritten
    assert after["wi-orph-none"] == before["wi-orph-none"]  # no signal, nothing written
    assert {k: v for k, v in after.items() if k != "wi-orph-spec"} == \
        {k: v for k, v in before.items() if k != "wi-orph-spec"}
    with pytest.raises(graph.GraphError, match="unknown ids: wi-nope"):
        milestones.suggest(ms_store, only=["wi-nope"])


def test_apply_plans_then_writes_validated_edges(ms_store):
    nodes_text = (ms_store / "nodes" / "work.yaml").read_text(encoding="utf-8")
    plan = milestones.apply(ms_store)
    assert [c.line() for c in plan] == ["wi-orph-prop2: ms-b? -> ms-b"]  # ms-new does not exist yet
    assert (ms_store / "nodes" / "work.yaml").read_text(encoding="utf-8") == nodes_text  # no --write, no change
    changes = milestones.apply(ms_store, overrides={"wi-orph-none": "ms-a", "wi-orph-prop2": "ms-a"}, write=True,
                               today="2026-11-02")
    assert [c.line() for c in changes] == ["wi-orph-none: -? -> ms-a (Ada's value)",
                                           "wi-orph-prop2: ms-b? -> ms-a (Ada's value)"]
    assert _edges(ms_store)[-2:] == [{"from": "wi-orph-none", "to": "ms-a", "type": "part_of"},
                                     {"from": "wi-orph-prop2", "to": "ms-a", "type": "part_of"}]
    text = (ms_store / "edges" / "work.yaml").read_text(encoding="utf-8")
    assert "# 2026-11-02: brain milestone apply (validated by Ada)" in text
    nodes = _nodes(ms_store)
    assert "props" not in nodes["wi-orph-prop2"]  # the proposal is cleared once the edge is written
    assert nodes["wi-orph-prop"]["props"]["milestone_proposed"] == "ms-new"
    assert milestones.waiting(ms_store) == ["wi-orph-prop: ms-new?"]
    assert milestones.index(ms_store).orphans() == ["wi-orph-dep", "wi-orph-prop", "wi-orph-spec", "wi-orph-theme",
                                                    "wi-orph-tie"]


def test_apply_only_skip_and_refusals(ms_store):
    graph.set_item(ms_store, "wi-orph-spec", ["milestone_proposed=ms-a"])
    assert [c.id for c in milestones.apply(ms_store, only=["wi-orph-spec"])] == ["wi-orph-spec"]
    assert [c.id for c in milestones.apply(ms_store, skip=["wi-orph-spec"])] == ["wi-orph-prop2"]
    with pytest.raises(graph.GraphError, match="unknown ids"):
        milestones.apply(ms_store, only=["wi-nope"])
    with pytest.raises(graph.GraphError, match="not a milestone"):
        milestones.apply(ms_store, overrides={"wi-orph-none": "ms-new"})
    graph.link(ms_store, "wi-orph-spec", "part_of", "ms-a")  # attached by hand meanwhile: only the prop is cleared
    change = milestones.apply(ms_store, only=["wi-orph-spec"], write=True)[0]
    assert change.linked and change.line().endswith("(already linked: proposal cleared)")
    assert sum(1 for e in _edges(ms_store) if (e["from"], e["to"]) == ("wi-orph-spec", "ms-a")) == 1
    assert "props" not in _nodes(ms_store)["wi-orph-spec"]


def test_orphan_lines_group_by_proposal(ms_store, monkeypatch):
    lines = milestones.orphan_lines(ms_store)
    assert lines[0] == ("warning: 7 open item(s) attached to no milestone, outside the roadmap "
                        "(brain milestone suggest)")
    assert lines[1] == ("  proposed, waiting on Ada (then brain milestone apply --write): ms-b? wi-orph-prop2; "
                        "ms-new? (not a milestone yet: brain milestone add) wi-orph-prop")
    assert lines[2] == ("  no proposal (brain milestone suggest --write): wi-orph-dep, wi-orph-none, wi-orph-spec, "
                        "wi-orph-theme, wi-orph-tie")
    monkeypatch.setattr(milestones, "LIST_MAX", 2)
    assert milestones.orphan_lines(ms_store)[2].endswith(": wi-orph-dep, wi-orph-none and 3 more")
    section = resume._milestones(resume.Store.load(ms_store))
    assert "Outside every milestone: 7 open item(s), 2 with a proposal waiting on Ada (`brain milestone " \
           "suggest`)." in section.lines


def test_orphan_lines_silent_without_milestones(store):
    text = (store / "nodes" / "work.yaml").read_text(encoding="utf-8")  # the fixture's only milestone, ms-x, removed
    (store / "nodes" / "work.yaml").write_text(text[:text.index("- {id: ms-x,")] + text[text.index("# --- items"):],
                                               encoding="utf-8")
    assert milestones.index(store).orphans() == ["wi-one", "wi-two"]
    assert milestones.orphan_lines(store) == []


def test_add_asks_then_creates_once_the_owner_chose_it(ms_store):
    root = ms_store.parents[1]
    ddr, kept = milestones.ask(root, ms_store, "ms-new", title="New one", trigger="x runs: y", why="none fits",
                               items=["wi-orph-prop", "wi-orph-none", "wi-orph-prop2"], at="2026-11-02T10:00:00Z",
                               project="demo")
    assert ddr["id"] == "ddr-2026-11-02-new-milestone-ms-new" and ddr["title"] == "New milestone ms-new?"
    labels = [o["label"] for o in ddr["options"]]
    assert labels == ["Create ms-new", "Use ms-a", "No milestone"]
    assert ddr["options"][0]["consequences"] == ("«New one», reached when: x runs: y; part_of it: wi-orph-prop, "
                                                 "wi-orph-none, wi-orph-prop2")
    assert kept == ["wi-orph-prop2 (ms-b?)"]  # its own proposal stays
    nodes = _nodes(ms_store)
    assert nodes["wi-orph-none"]["props"] == {"milestone_proposed": "ms-new",
                                              "milestone_reason": "new milestone, ddr-2026-11-02-new-milestone-ms-new"}
    assert nodes["wi-orph-prop2"]["props"] == {"milestone_proposed": "ms-b"}
    assert milestones.milestone_ddr(root, "ms-new")["id"] == ddr["id"]
    assert milestones.ddr_note(root, "ms-new") == f"{ddr['id']} [pending]"

    with pytest.raises(milestones.Pending) as waiting:
        milestones.create(root, ms_store, "ms-new", ddr, title="New one", trigger="x runs: y", items=[])
    assert not waiting.value.answered and "waits on Ada" in str(waiting.value)

    ddr = decisions.answer(root, ddr["id"], ["2"], at="2026-11-02T11:00:00Z")
    with pytest.raises(milestones.Pending, match="not the creation") as refused:
        milestones.create(root, ms_store, "ms-new", ddr, title="New one", trigger="x runs: y", items=[])
    assert refused.value.answered
    assert "ms-new" not in _nodes(ms_store)

    ddr = decisions.answer(root, ddr["id"], ["Create"], at="2026-11-03T09:00:00Z", again=True)
    changes = milestones.create(root, ms_store, "ms-new", ddr, title="New one", trigger="x runs: y", items=[],
                                parent="ms-a", today="2026-11-03")
    assert [c.id for c in changes] == ["wi-orph-prop", "wi-orph-none", "wi-orph-prop2"]  # the DDR's items
    nodes = _nodes(ms_store)
    assert nodes["ms-new"] == {"id": "ms-new", "type": "Milestone", "status": "pending", "title": "New one",
                               "props": {"trigger": "x runs: y",
                                         "decided": "Ada, 2026-11-03 (ddr-2026-11-02-new-milestone-ms-new)"}}
    assert nodes["wi-orph-prop"]["props"] == {"priority_proposed": "P2"}
    edges = _edges(ms_store)
    assert {"from": "ms-new", "to": "ms-a", "type": "part_of"} in edges
    assert edges[-3:] == [{"from": i, "to": "ms-new", "type": "part_of"}
                          for i in ("wi-orph-prop", "wi-orph-none", "wi-orph-prop2")]
    # run again: the milestone and its edges exist, nothing is duplicated
    again = milestones.create(root, ms_store, "ms-new", ddr, title="New one", trigger="x runs: y", items=[])
    assert all(c.linked for c in again) and len(_edges(ms_store)) == len(edges)


def test_add_finds_a_ddr_asked_by_hand(ms_store):
    root = ms_store.parents[1]
    ddr, _ = decisions.ask(root, title="Q6 — New milestone ms-new?", question="?", why="w", at="2026-11-02T10:00:00Z",
                           options=["Créer ms-new: x", "Élargir ms-b: y"], items=["wi-orph-prop"], slug="tiers")
    assert milestones.milestone_ddr(root, "ms-new")["id"] == "ddr-2026-11-02-tiers"
    assert milestones.milestone_ddr(root, "ms-ne") is None and milestones.milestone_ddr(root, "ms-b") is None
    ddr = decisions.answer(root, ddr["id"], ["1"], at="2026-11-02T11:00:00Z")
    changes = milestones.create(root, ms_store, "ms-new", ddr, title="New", trigger="t", items=[])
    assert [c.id for c in changes] == ["wi-orph-prop"]


def test_cli_milestone_commands(ms_store, monkeypatch, capsys):
    root = ms_store.parents[1]
    base = ["--root", str(root), "milestone"]
    assert cli.main(base + ["suggest"]) == 0
    out = capsys.readouterr().out
    assert "wi-orph-spec [todo]: ms-a? (new: spec spec-x" in out
    assert "suggest: 7 open item(s) attached to no milestone, 2 proposed already, 4 new suggestion(s) " \
           "(not written: --write)" in out
    assert cli.main(base + ["suggest", "--only", "wi-orph-spec,wi-orph-dep", "--write"]) == 0
    assert _nodes(ms_store)["wi-orph-dep"]["props"]["milestone_proposed"] == "ms-b"
    assert cli.main(base + ["apply", "--skip", "wi-orph-prop2"]) == 0
    out = capsys.readouterr().out
    assert "wi-orph-dep: ms-b? -> ms-b\nwi-orph-spec: ms-a? -> ms-a\napply: 2 change(s) (not written" in out
    assert "left as proposals (milestone not created yet: brain milestone add): wi-orph-prop: ms-new?" in out
    assert cli.main(base + ["apply", "--set", "wi-orph-none=ms-a", "--only", "wi-orph-dep", "--write"]) == 0
    assert {"from": "wi-orph-none", "to": "ms-a", "type": "part_of"} in _edges(ms_store)
    assert cli.main(base + ["apply", "--set", "wi-orph-none=ms-nope"]) == 1
    assert cli.main(base + ["add", "ms-a", "--title", "t", "--trigger", "t"]) == 1  # exists already
    assert cli.main(base + ["add", "ms-new", "--title", "t", "--trigger", "t"]) == 1  # --why needed to ask
    assert cli.main(base + ["add", "ms-new", "--title", "New", "--trigger", "t", "--item", "wi-orph-prop",
                            "--why", "none fits", "--at", "2026-11-02T10:00:00Z"]) == 0
    assert "asked ddr-2026-11-02-new-milestone-ms-new" in capsys.readouterr().out
    assert (root / "notes" / "decision_queue.md").is_file()
    assert cli.main(base + ["add", "ms-new", "--title", "New", "--trigger", "t"]) == 0
    assert "waits on Ada" in capsys.readouterr().out
    decisions.answer(root, "new-milestone-ms-new", ["1"], at="2026-11-02T11:00:00Z")
    assert cli.main(base + ["add", "ms-new", "--title", "New", "--trigger", "t"]) == 0
    assert "add: ms-new in the graph, 1 item(s) part of it" in capsys.readouterr().out
    assert _nodes(ms_store)["ms-new"]["type"] == "Milestone"


def test_item_add_prints_the_suggestion_and_check_flags_orphans(ms_store, monkeypatch, capsys):
    root = ms_store.parents[1]
    assert cli.main(["--root", str(root), "item", "add", "wi-fresh", "--title", "Fresh", "--spec", "spec-x"]) == 0
    out = capsys.readouterr().out
    assert "milestone: none; suggested ms-a? (spec spec-x: 3 of 6 item(s) in ms-a); keep it as a proposal: " \
           "brain milestone suggest --write --only wi-fresh" in out
    assert cli.main(["--root", str(root), "item", "add", "wi-lone", "--title", "Lone"]) == 0
    assert "no signal suggests one" in capsys.readouterr().out
    assert cli.main(["--root", str(root), "item", "add", "wi-placed", "--title", "P", "--milestone", "ms-a"]) == 0
    assert "milestone:" not in capsys.readouterr().out
    monkeypatch.setattr(graph, "research_graph", lambda *a: 0)
    assert cli.main(["--root", str(root), "check"]) == 0  # a warning, not an error
    assert "warning: 9 open item(s) attached to no milestone" in capsys.readouterr().out
