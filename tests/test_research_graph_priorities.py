"""Priority proposals and `priorities apply` (research_graph.priorities): textual edits of a node's props that
touch nothing else, dry run by default, the owner's overrides."""

from __future__ import annotations

import pytest
import yaml

from research_graph import priorities
from research_graph.cli import main
from research_graph.loader import load_store
from research_graph.priorities import EditError, apply_priorities, edit_props, propose
from tests.backlog_world import write_store

TEXT = """\
# comment kept
- {id: wi-a, type: WorkItem, status: todo, title: "a, with: commas"}
- {id: wi-b, type: WorkItem, status: todo,
   title: "b",
   props: {spec: spec-x, note: "it's {quoted}, really"}}
- {id: wi-c, type: WorkItem, status: todo, title: c,
   props: {branch: feat/c,
           measured: "long"}}
- {id: wi-e, type: WorkItem, status: todo, title: e, props: {}}
"""


def _props(text, nid):
    return next(n for n in yaml.safe_load(text) if n["id"] == nid).get("props")


def test_edit_adds_props_where_there_were_none():
    out = edit_props(TEXT, "wi-a", set_={"priority_proposed": "P2", "priority_reason": 'why: "quoted"'})
    assert _props(out, "wi-a") == {"priority_proposed": "P2", "priority_reason": 'why: "quoted"'}
    assert out.startswith("# comment kept\n")
    assert '- {id: wi-a, type: WorkItem, status: todo, title: "a, with: commas",\n   props: {priority_proposed: P2' in out
    assert edit_props(TEXT, "wi-e", set_={"priority": "P1"}).count("props: {priority: P1}") == 1


def test_edit_appends_on_a_new_line_aligned_with_the_first_key():
    out = edit_props(TEXT, "wi-b", set_={"priority_proposed": "P1", "priority_reason": "r"})
    assert '   props: {spec: spec-x, note: "it\'s {quoted}, really",\n           priority_proposed: P1, ' \
           'priority_reason: r}}' in out
    out = edit_props(TEXT, "wi-c", set_={"priority": "P3"})
    assert '           measured: "long",\n           priority: P3}}' in out
    assert all(_props(out, nid) == _props(TEXT, nid) for nid in ("wi-a", "wi-b", "wi-e"))


def test_edit_renames_and_replaces_values():
    text = edit_props(TEXT, "wi-b", set_={"priority_proposed": "P2", "priority_reason": "r"})
    out = edit_props(text, "wi-b", rename={"priority_proposed": "priority"}, set_={"priority": "P0"})
    assert _props(out, "wi-b") == {"spec": "spec-x", "note": "it's {quoted}, really", "priority": "P0",
                                   "priority_reason": "r"}
    out = edit_props(out, "wi-b", set_={"note": "new"})
    assert _props(out, "wi-b")["note"] == "new"
    with pytest.raises(EditError, match="not found"):
        edit_props(TEXT, "wi-zz", set_={"x": 1})
    with pytest.raises(EditError, match="no props.priority_proposed"):
        edit_props(TEXT, "wi-b", rename={"priority_proposed": "priority"})


def test_check_refuses_an_edit_that_changes_anything_else():
    with pytest.raises(EditError, match="changed another node"):
        priorities._check(TEXT, TEXT.replace("spec: spec-x", "spec: spec-y"), "wi-a", {"priority"})
    with pytest.raises(EditError, match="other props"):
        priorities._check(TEXT, TEXT.replace("spec: spec-x", "spec: spec-y"), "wi-b", {"priority"})


@pytest.fixture
def store(tmp_path):
    return write_store(tmp_path / "research-lab")


def _priority(store, nid):
    return (load_store(store).nodes[nid].get("props") or {})


def test_propose_then_apply_with_dry_run_skip_and_overrides(store):
    with pytest.raises(EditError, match="already has a priority"):
        propose(store, {"wi-doing": ("P2", "x")})
    propose(store, {"wi-free": ("P3", "later"), "wi-prereq": ("P1", "unblocks ms-top")}, write=True)
    assert _priority(store, "wi-free")["priority_proposed"] == "P3"
    before = (store / "nodes" / "work.yaml").read_bytes()
    changes = apply_priorities(store)  # dry run
    assert [c.line() for c in changes] == ["wi-free: P3? -> P3", "wi-prereq: P1? -> P1", "wi-todo: P2? -> P2"]
    assert (store / "nodes" / "work.yaml").read_bytes() == before
    changes = apply_priorities(store, skip=["wi-prereq"], overrides={"wi-free": "p1", "wi-ext": "P0"}, write=True)
    assert [c.line() for c in changes] == ["wi-ext: -? -> P0 (the owner's value)", "wi-free: P3? -> P1 (the owner's value)",
                                           "wi-todo: P2? -> P2"]
    assert _priority(store, "wi-free") == {"pr": "acme-data #16", "after": "wi-doing stage 1",
                                           "priority": "P1", "priority_reason": "later"}
    assert _priority(store, "wi-prereq")["priority_proposed"] == "P1"  # skipped: still a proposal
    assert apply_priorities(store, only=["wi-prereq"])[0].id == "wi-prereq"
    assert [c.id for c in apply_priorities(store)] == ["wi-prereq"]  # validated ones are left alone
    with pytest.raises(EditError, match="unknown ids"):
        apply_priorities(store, only=["wi-nope"])
    with pytest.raises(EditError, match="not one of"):
        apply_priorities(store, overrides={"wi-prereq": "P5"})


def test_proposal_table_groups_by_proposed_priority(store):
    propose(store, {"wi-free": ("P3", "later | maybe"), "wi-prereq": ("P1", "unblocks")}, write=True)
    text = priorities.render_proposal(load_store(store))
    assert [ln for ln in text.splitlines() if ln.startswith("## ")] == ["## P1 (1)", "## P2 (1)", "## P3 (1)"]
    assert "| `wi-free` | todo | Free item about funding | later / maybe |" in text
    assert priorities.render_proposal(load_store(write_store(store.parents[2] / "empty", "", ""))) == \
        "(no proposal)\n"


def test_cli_priorities(store, capsys):
    args = ["--store", str(store), "--repo-root", str(store.parents[1]), "priorities"]
    assert main(args + ["proposal"]) == 0
    assert "## P2 (1)" in capsys.readouterr().out
    assert main(args + ["apply", "--set", "wi-free=P1"]) == 0
    out = capsys.readouterr().out
    assert "wi-free: -? -> P1 (the owner's value)" in out and "dry run" in out
    assert "priority" not in _priority(store, "wi-free")
    assert main(args + ["apply", "--only", "wi-todo", "--write"]) == 0
    assert "1 priority(ies) written; now: research_graph kanban --write" in capsys.readouterr().out
    assert _priority(store, "wi-todo")["priority"] == "P2"
    assert main(args + ["apply", "--set", "wi-free"]) == 2
    assert main(args + ["apply", "--only", "wi-nope"]) == 1
