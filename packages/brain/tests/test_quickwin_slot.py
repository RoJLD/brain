"""wi-brain-wave-quickwin-slot: a wave keeps about a fifth of its places for quick wins (size S, a high value):
brain.waves.quickwin_slot says the slot, what fills it and the startable quick wins outside the wave that would;
brain next and brain wave plan show it (spec-brain-sizing-prioritization 5.3)."""

import json

import pytest

from brain import cli, governor, lots, quota, waves

SCHEMA = (
    "node_types: [WorkItem, Milestone]\n"
    "edge_types: [part_of, depends_on]\n"
    "statuses: [todo, doing, blocked, done, dropped, pending, reached]\n"
    "status_by_type:\n  WorkItem: [todo, doing, blocked, done, dropped]\n  Milestone: [pending, reached, dropped]\n")

QW = "size: S, size_reason: a flag, value: high, value_reason: the pilot"


def _nodes(n_plain: int, inside: str = "") -> str:
    rows = [
        '- {id: wave-1.0.0, type: Milestone, status: reached, title: "Wave 1.0.0", props: {kind: wave, release: 1.0.0}}',
        '- {id: wave-1.1.0, type: Milestone, status: pending, title: "Wave 1.1.0", props: {kind: wave, release: 1.1.0}}',
        '- {id: wave-1.2.0, type: Milestone, status: pending, title: "Wave 1.2.0", props: {kind: wave, release: 1.2.0}}',
        f'- {{id: wi-loose, type: WorkItem, status: todo, title: "Loose", props: {{priority: P2, {QW}}}}}',
        f'- {{id: wi-later, type: WorkItem, status: todo, title: "Later", props: {{priority: P1, {QW}}}}}',
        f'- {{id: wi-old, type: WorkItem, status: todo, title: "Old wave", props: {{priority: P1, {QW}}}}}',
        f'- {{id: wi-held, type: WorkItem, status: todo, title: "Held", props: {{priority: P0, {QW}}}}}',
        '- {id: wi-big, type: WorkItem, status: todo, title: "Big", props: {priority: P0, size: XL, size_reason: x, '
        'value: high, value_reason: x}}',
        f'- {{id: wi-gone, type: WorkItem, status: dropped, title: "Dropped", props: {{{QW}}}}}',
    ]
    rows += [f'- {{id: wi-p{k}, type: WorkItem, status: todo, title: "Plain {k}", props: {{size: M, size_reason: x}}}}'
             for k in range(n_plain)]
    if inside:
        rows.append(f'- {{id: {inside}, type: WorkItem, status: done, title: "Inside", props: {{{QW}}}}}')
    return "\n".join(rows) + "\n"


def _edges(n_plain: int, inside: str = "") -> str:
    rows = ["- {from: wi-later, to: wave-1.2.0, type: part_of}", "- {from: wi-old, to: wave-1.0.0, type: part_of}",
            "- {from: wi-held, to: wi-p0, type: depends_on}", "- {from: wi-gone, to: wave-1.1.0, type: part_of}"]
    rows += [f"- {{from: wi-p{k}, to: wave-1.1.0, type: part_of}}" for k in range(n_plain)]
    if inside:
        rows.append(f"- {{from: {inside}, to: wave-1.1.0, type: part_of}}")
    return "\n".join(rows) + "\n"


@pytest.fixture
def make(tmp_path, monkeypatch):
    monkeypatch.setattr(governor, "memory_info", lambda: {"committed": 40.0, "available_gb": 30.0})
    monkeypatch.setattr(quota, "load_status", lambda: {})

    def _make(n_plain: int, inside: str = ""):
        store = tmp_path / "root" / "notes" / "graph"
        (store / "nodes").mkdir(parents=True, exist_ok=True)
        (store / "edges").mkdir(exist_ok=True)
        (store / "schema.yaml").write_text(SCHEMA, encoding="utf-8")
        (store / "edges.yaml").write_text("", encoding="utf-8")
        (store / "nodes" / "work.yaml").write_text(_nodes(n_plain, inside), encoding="utf-8", newline="\n")
        (store / "edges" / "work.yaml").write_text(_edges(n_plain, inside), encoding="utf-8", newline="\n")
        return store
    return _make


def test_a_free_slot_proposes_the_startable_quick_wins_outside_the_wave(make):
    store = make(9)   # 9 plain items and a dropped quick win: 10 places, 2 kept, none filled
    slot = waves.quickwin_slot(waves.load(store), "wave-1.1.0")
    # wi-later (P1, a later wave) before wi-loose (P2, no wave); wi-old is in an earlier wave, wi-held waits on an
    # item, wi-big is not small, wi-gone is dropped
    assert slot == {"share": 0.2, "places": 10, "slot": 2, "filled": [], "free": 2,
                    "candidates": ["wi-later", "wi-loose"]}
    line = waves.slot_line(slot, "wave-1.1.0")
    assert line == ("quick-win slot: 2 of 10 place(s) (20%, size S and a high value); filled by none; 2 free: "
                    "candidate(s) wi-later, wi-loose (brain item link wi-later part_of wave-1.1.0)")


def test_a_filled_slot_names_what_fills_it_even_once_done(make):
    store = make(4, inside="wi-in")   # 5 places: one kept, filled by a quick win already done
    slot = waves.quickwin_slot(waves.load(store), "wave-1.1.0")
    assert (slot["places"], slot["slot"], slot["filled"], slot["free"], slot["candidates"]) == (6, 1, ["wi-in"], 0, [])
    assert waves.slot_line(slot, "wave-1.1.0").endswith("filled by wi-in")
    pl = waves.load(store)
    assert waves.quickwin_slot(pl, "wave-1.2.0")["slot"] == 1   # one item: one place at least
    assert waves.slot_line({"slot": 0}, "w") == ""


def test_brain_next_and_brain_wave_plan_show_the_slot(make, capsys):
    store = make(9)
    root = store.parents[1]
    assert cli.main(["--root", str(root), "next"]) == 0
    out = capsys.readouterr().out
    assert "  quick-win slot: 2 of 10 place(s)" in out and "candidate(s) wi-later, wi-loose" in out
    assert cli.main(["--root", str(root), "next", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["current"]["slot"]["candidates"] == ["wi-later", "wi-loose"]
    wp = lots.plan(store, root)
    assert wp.slot["slot"] == 2 and wp.as_dict()["slot"]["free"] == 2
    assert any(x.startswith("Quick-win slot: 2 of 10 place(s)") for x in lots.render(wp))
