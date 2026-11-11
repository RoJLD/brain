"""wi-brain-wave-lot-planner: brain wave plan, a wave's lots at zero token (brain.lots): items that share a file that
is not hot in one lot, in rounds by their depends_on, sized by the caps in force; brain next shows the first round.
Fixtures only: the owner is the tests' Ada."""

import json

import pytest

from brain import cli, governor, lots, quota

SCHEMA = (
    "node_types: [WorkItem, Milestone, Feature]\n"
    "edge_types: [part_of, depends_on, delivers, implemented_by]\n"
    "statuses: [todo, doing, blocked, done, dropped, pending, reached, have]\n"
    "status_by_type:\n  WorkItem: [todo, doing, blocked, done, dropped]\n  Milestone: [pending, reached, dropped]\n"
    "  Feature: [have]\n")

NODES = """\
- {id: wave-1.0.0, type: Milestone, status: reached, title: "Wave 1.0.0", props: {kind: wave, release: 1.0.0}}
- {id: wave-1.1.0, type: Milestone, status: pending, title: "Wave 1.1.0", props: {kind: wave, release: 1.1.0}}
- {id: wave-1.2.0, type: Milestone, status: pending, title: "Wave 1.2.0", props: {kind: wave, release: 1.2.0}}
- {id: feat-cli, type: Feature, status: have, title: "The CLI"}
- {id: wi-cli-fix, type: WorkItem, status: todo, title: "The CLI's output", props: {priority: P1}}
- {id: wi-cli-help, type: WorkItem, status: todo, title: "A help text in cli.py", props: {priority: P2}}
- {id: wi-views, type: WorkItem, status: todo, title: "views.py and README.md", props: {priority: P2}}
- {id: wi-views-more, type: WorkItem, status: todo, title: "More of views.py", props: {priority: P3}}
- {id: wi-lots, type: WorkItem, status: todo, title: "lots.py, README.md and changes/wi-lots.md",
   props: {priority: P3}}
- {id: wi-after, type: WorkItem, status: todo, title: "lots_view.py after the lots", props: {priority: P1}}
- {id: wi-blank, type: WorkItem, status: todo, title: "Something with no file named"}
- {id: wi-done, type: WorkItem, status: done, title: "Done: cli.py"}
- {id: wi-carried, type: WorkItem, status: todo, title: "Carried: guard.sh", props: {carried_to: 1.1.0}}
- {id: wi-outside, type: WorkItem, status: todo, title: "Next wave: other.py"}
"""

EDGES = """\
- {from: wi-cli-fix, to: wave-1.1.0, type: part_of}
- {from: wi-cli-fix, to: feat-cli, type: delivers}
- {from: feat-cli, to: "code:engine:packages/brain/src/brain/cli.py", type: implemented_by}
- {from: wi-cli-help, to: wave-1.1.0, type: part_of}
- {from: wi-views, to: wave-1.1.0, type: part_of}
- {from: wi-views-more, to: wave-1.1.0, type: part_of}
- {from: wi-views-more, to: wi-views, type: depends_on}
- {from: wi-lots, to: wave-1.1.0, type: part_of}
- {from: wi-after, to: wave-1.1.0, type: part_of}
- {from: wi-after, to: wi-lots, type: depends_on}
- {from: wi-blank, to: wave-1.1.0, type: part_of}
- {from: wi-blank, to: wi-outside, type: depends_on}
- {from: wi-done, to: wave-1.1.0, type: part_of}
- {from: wi-carried, to: wave-1.0.0, type: part_of}
- {from: wi-outside, to: wave-1.2.0, type: part_of}
"""


@pytest.fixture
def root(tmp_path, monkeypatch):
    store = tmp_path / "root" / "notes" / "graph"
    (store / "nodes").mkdir(parents=True)
    (store / "edges").mkdir()
    (store / "schema.yaml").write_text(SCHEMA, encoding="utf-8")
    (store / "edges.yaml").write_text("", encoding="utf-8")
    (store / "nodes" / "work.yaml").write_text(NODES, encoding="utf-8", newline="\n")
    (store / "edges" / "work.yaml").write_text(EDGES, encoding="utf-8", newline="\n")
    # the machine's memory and the quota forecast are this test's, not the machine's running it
    monkeypatch.setattr(governor, "memory_info", lambda: {"committed": 40.0, "available_gb": 30.0})
    monkeypatch.setattr(quota, "load_status", lambda: {})
    return tmp_path / "root"


def _plan(root, **kw):
    return lots.plan(root / "notes" / "graph", root, **kw)


def test_items_that_share_a_file_share_a_lot_and_a_hot_file_does_not(root):
    wp = _plan(root, wave="1.1.0")
    by = {i: lot for lot in wp.lots for i in lot.items}
    assert set(wp.units) == {"wi-cli-fix", "wi-cli-help", "wi-views", "wi-views-more", "wi-lots", "wi-after",
                             "wi-blank", "wi-carried"}   # open, carried in included, done left out
    assert by["wi-cli-fix"] is by["wi-cli-help"]   # a feature's CodeRef meets the file name cli.py
    assert {"items": ["wi-cli-fix", "wi-cli-help"], "files": ["engine:packages/brain/src/brain/cli.py"]} in wp.conflicts
    assert by["wi-views"] is by["wi-views-more"] and by["wi-views"].items == ["wi-views", "wi-views-more"]
    assert by["wi-views"] is not by["wi-lots"]   # README.md is hot: counted apart, never a reason to share a lot
    assert wp.hot == {"README.md": ["wi-lots", "wi-views"]}
    assert wp.units["wi-lots"].hot == ["README.md", "changes/wi-lots.md"]
    assert not by["wi-blank"].checked and wp.units["wi-blank"].outside == ["wi-outside"]
    assert by["wi-carried"].files == ["guard.sh"]


def test_a_lot_comes_after_the_lots_that_hold_its_prerequisites(root):
    wp = _plan(root, wave="wave-1.1.0", at_once=2)
    round_of = {i: lot.round for lot in wp.lots for i in lot.items}
    assert round_of["wi-after"] > round_of["wi-lots"]
    assert all(len(r) <= 2 for r in wp.rounds)
    first = [wp.lots[n - 1] for n in wp.rounds[0]]
    assert first[0].items == ["wi-lots"] and first[0].unblocks == 1   # the lot that unblocks the most first
    assert [lot.n for lot in wp.lots] == list(range(1, len(wp.lots) + 1))


def test_lots_that_depend_on_each_other_are_merged():
    units = {"wi-a": lots.Unit("wi-a", "", "todo", "P1", ["a.py"], after=["wi-b"]),
             "wi-b": lots.Unit("wi-b", "", "todo", "P2", ["b.py"], after=["wi-a"])}
    found, conflicts = lots.lots_of(units)
    assert len(found) == 1 and sorted(found[0].items) == ["wi-a", "wi-b"] and conflicts == []


def test_the_caps_in_force_size_the_rounds_and_the_guards_say_now(root, monkeypatch):
    wp = _plan(root, wave="1.1.0")
    assert wp.caps["sessions"] == governor.DEFAULTS["sessions"] - 1 and wp.caps["verify"] == lots.AT_ONCE
    assert wp.caps["at_once"] == min(wp.caps["sessions"], lots.AT_ONCE) and wp.caps["now"] == wp.caps["at_once"]
    monkeypatch.setattr(governor, "memory_info", lambda: {"committed": 99.0, "available_gb": 30.0})
    wp = _plan(root, wave="1.1.0", at_once=1)
    assert wp.caps["at_once"] == 1 and all(len(r) == 1 for r in wp.rounds)
    assert wp.caps["memory_refuses"] and wp.caps["now"] == 0
    text = "\n".join(lots.render(wp))
    assert "memory guard refuses a new session now" in text and "no lot can start now" in text
    monkeypatch.setattr(governor, "memory_info", lambda: {"committed": 40.0, "available_gb": 30.0})
    monkeypatch.setattr(quota, "load_status", lambda: {"pct_now": 80, "pace": {"at_reset": 120},
                                                       "now": "2999-01-01T00:00Z", "resets": "2999-01-05T12:00Z"})
    wp = _plan(root, wave="1.1.0")
    assert wp.caps["now"] == 0 and "(the last forecast, 2999-01-01T00:00Z)" in wp.caps["quota_advice"]
    monkeypatch.setattr(quota, "load_status", lambda: {"pct_now": 80, "pace": {"at_reset": 120},
                                                       "now": "2026-01-01T00:00Z", "resets": "2026-01-05T12:00Z"})
    wp = _plan(root, wave="1.1.0")   # its window has reset since: that forecast answers nothing now
    assert wp.caps["quota"] == "unknown" and wp.caps["now"] == wp.caps["at_once"]
    assert "from before the window's reset" in wp.caps["quota_advice"]
    monkeypatch.setattr(quota, "load_status", lambda: {"pct_now": 80, "pace": {"at_reset": 50}, "live": "x"})
    assert _plan(root, wave="1.1.0").caps["quota"] == "unknown"   # a quota.json no engine wrote breaks nothing
    assert _plan(root, wave="1.1.0", at_once=-2).caps["at_once"] == 1


def test_a_sessions_cap_with_no_room_beside_the_master_lets_no_lot_start(root, monkeypatch):
    monkeypatch.setattr(governor, "settings", lambda cwd: {"limits": dict(governor.DEFAULTS, sessions=1),
                                                           "projects": {}})
    wp = _plan(root, wave="1.1.0")
    assert wp.caps["at_once"] == 1 and wp.caps["sessions_left"] == 0 and wp.caps["now"] == 0
    text = "\n".join(lots.render(wp))
    assert "the sessions cap leaves no session beside the master's" in text and "no lot can start now" in text


def test_a_prerequisite_reached_through_an_item_outside_the_wave_orders_the_rounds(root):
    store = root / "notes" / "graph"
    edges = store / "edges" / "work.yaml"
    edges.write_text(edges.read_text(encoding="utf-8") + "- {from: wi-outside, to: wi-cli-fix, type: depends_on}\n",
                     encoding="utf-8", newline="\n")
    wp = _plan(root, wave="1.1.0")
    round_of = {i: lot.round for lot in wp.lots for i in lot.items}
    assert wp.units["wi-blank"].after == ["wi-cli-fix"] and wp.units["wi-blank"].outside == ["wi-outside"]
    assert round_of["wi-blank"] > round_of["wi-cli-fix"]


def test_the_command_refuses_an_at_once_below_one(root, capsys):
    for bad in ("0", "-2", "x"):
        with pytest.raises(SystemExit):
            cli.main(["--root", str(root), "wave", "plan", "--at-once", bad])
    assert "a whole number of 1 or more" in capsys.readouterr().err


def test_is_hot_and_meet():
    assert lots.is_hot("packages/brain/README.md") and lots.is_hot("README.md")
    assert lots.is_hot("packages/brain/changes/wi-x.md") and not lots.is_hot("src/brain/changes.py")
    assert lots.is_hot("src/x.py", ("x.py",)) and not lots.is_hot("src/xx.py", ("x.py",))
    assert lots.meet("packages/brain/src/brain/cli.py", "cli.py") and not lots.meet("src/mycli.py", "cli.py")
    assert lots.meet("brain:src/x.py", "x.py") and lots.meet("brain:src/x.py", "brain:src/x.py")
    assert not lots.meet("brain:src/x.py", "other:src/x.py")   # one path in two repos: two files
    assert lots.is_hot("brain:packages/brain/README.md")


def test_the_command_prints_the_plan_and_its_json(root, capsys):
    assert cli.main(["--root", str(root), "wave", "plan", "1.1.0", "--at-once", "2", "--hot", "views.py"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Wave 1.1.0 (wave-1.1.0): 8 open item(s) in ")
    assert "Round 1 (2 lot(s)):" in out and "Predicted conflicts (1)" in out
    assert "wi-blank [waits on wi-outside outside the wave]" in out and "unchecked: no known surface" in out
    assert "wi-views [P2] -> " not in out and "hot: views.py" in out   # --hot views.py: no longer a reason to share
    assert cli.main(["--root", str(root), "wave", "plan", "1.1.0"]) == 0
    assert "wi-views [P2] -> wi-views-more [P3, after wi-views]" in capsys.readouterr().out   # the depends_on order
    assert cli.main(["--root", str(root), "wave", "plan", "--json"]) == 0   # the current wave by default
    data = json.loads(capsys.readouterr().out)
    assert data["wave"] == "1.1.0" and data["unknown"] == ["wi-blank"] and data["outside"] == {"wi-blank": ["wi-outside"]}
    assert cli.main(["--root", str(root), "wave", "plan", "9.9.9"]) == 1
    assert "no wave of that release" in capsys.readouterr().err


def test_next_shows_the_first_round_before_the_next_wave(root, capsys):
    assert cli.main(["--root", str(root), "next"]) == 0
    out = capsys.readouterr().out.splitlines()
    at = next(k for k, line in enumerate(out) if line.startswith("Lots (brain wave plan 1.1.0): "))
    assert out[at + 1].startswith("  Lot 1: ") and any(line.startswith("Next: Wave 1.2.0") for line in out[at:])
    assert cli.main(["--root", str(root), "next", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["lots"]["wave"] == "1.1.0"
