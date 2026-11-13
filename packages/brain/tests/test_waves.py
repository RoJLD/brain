"""Waves and eras (brain.waves): milestones of kind wave named by their release and of kind era holding milestones;
brain check's rules on them, the generated plan view, brain next, the closure the version PR makes (brain wave close)
and the import of the items' free-text props.wave. Fixtures only: the owner is the tests' Ada."""

import json

import pytest
import yaml

from brain import cli, decisions, governor, milestones, quota, waves


@pytest.fixture(autouse=True)
def _no_machine(monkeypatch):
    """brain next reads the guards' state for its lots (brain.lots): this test's, not the machine's running it."""
    monkeypatch.setattr(governor, "memory_info", lambda: {"committed": 40.0, "available_gb": 30.0})
    monkeypatch.setattr(quota, "load_status", lambda: {})

SCHEMA = (
    "node_types: [ADR, WorkItem, Milestone, Spec, DDR, Session, Action]\n"
    "edge_types: [decided_by, supersedes, part_of, depends_on, specified_by, raised_by, answered_in, about, "
    "produced_by, touches]\n"
    "statuses: [active, todo, doing, blocked, done, dropped, pending, reached, proposed, answered, integrated, "
    "archived, open, closed, recorded]\n"
    "status_by_type:\n  WorkItem: [todo, doing, blocked, done, dropped]\n  Milestone: [pending, reached, dropped]\n")

# An era of two milestones; three waves (1.0.0 closed, 1.1.0 current, 1.2.0 next) and a wave in no milestone.
NODES = """\
# Work layer
- {id: era-one, type: Milestone, status: pending, title: "The first era",
   props: {kind: era, exit: "Go to the second era?", stage_to: beta, serves: "phase one"}}
- {id: ms-core, type: Milestone, status: pending, title: "Core", props: {trigger: "the core runs"}}
- {id: ms-docs, type: Milestone, status: reached, title: "Docs", props: {trigger: "the docs exist"}}
- {id: ms-free, type: Milestone, status: pending, title: "Free", props: {trigger: "free"}}
- {id: wave-1.0.0, type: Milestone, status: reached, title: "Wave 1.0.0", props: {kind: wave, release: 1.0.0}}
- {id: wave-1.1.0, type: Milestone, status: pending, title: "Wave 1.1.0",
   props: {kind: wave, release: 1.1.0, week: "2030-01-07"}}
- {id: wave-1.2.0, type: Milestone, status: pending, title: "Wave 1.2.0", props: {kind: wave, release: 1.2.0}}
- {id: wi-old-done, type: WorkItem, status: done, title: "Done in 1.0.0"}
- {id: wi-carried, type: WorkItem, status: todo, title: "Carried from 1.0.0", props: {carried_to: 1.1.0}}
- {id: wi-start, type: WorkItem, status: todo, title: "Can start", props: {priority: P1}}
- {id: wi-start-p3, type: WorkItem, status: todo, title: "Can start, P3", props: {priority: P3}}
- {id: wi-open-q, type: WorkItem, status: todo, title: "Asks Ada", props: {open: "which option?"}}
- {id: wi-ext, type: WorkItem, status: blocked, title: "Blocked outside",
   props: {external_blocker: "Ada signs the form"}}
- {id: wi-ddr, type: WorkItem, status: todo, title: "Waits on a DDR"}
- {id: wi-after, type: WorkItem, status: todo, title: "After wi-start"}
- {id: wi-doing, type: WorkItem, status: doing, title: "In progress"}
- {id: wi-done, type: WorkItem, status: done, title: "Done in 1.1.0"}
- {id: wi-next, type: WorkItem, status: todo, title: "Next wave, can start"}
- {id: wi-next-after, type: WorkItem, status: todo, title: "Next wave, after"}
"""

EDGES = """\
# Work edges
- {from: ms-core, to: era-one, type: part_of}
- {from: ms-docs, to: era-one, type: part_of}
- {from: wave-1.0.0, to: ms-core, type: part_of}
- {from: wave-1.1.0, to: ms-core, type: part_of}
- {from: wave-1.2.0, to: ms-free, type: part_of}
- {from: wi-old-done, to: wave-1.0.0, type: part_of}
- {from: wi-carried, to: wave-1.0.0, type: part_of}
- {from: wi-start, to: wave-1.1.0, type: part_of}
- {from: wi-start-p3, to: wave-1.1.0, type: part_of}
- {from: wi-open-q, to: wave-1.1.0, type: part_of}
- {from: wi-ext, to: wave-1.1.0, type: part_of}
- {from: wi-ddr, to: wave-1.1.0, type: part_of}
- {from: wi-after, to: wave-1.1.0, type: part_of}
- {from: wi-after, to: wi-start, type: depends_on}
- {from: wi-doing, to: wave-1.1.0, type: part_of}
- {from: wi-done, to: wave-1.1.0, type: part_of}
- {from: wi-next, to: wave-1.2.0, type: part_of}
- {from: wi-next-after, to: wave-1.2.0, type: part_of}
- {from: wi-next-after, to: wi-doing, type: depends_on}
"""


def _write(store, nodes=NODES, edges=EDGES):
    (store / "nodes").mkdir(parents=True, exist_ok=True)
    (store / "edges").mkdir(exist_ok=True)
    (store / "schema.yaml").write_text(SCHEMA, encoding="utf-8")
    (store / "edges.yaml").write_text("", encoding="utf-8")
    (store / "nodes" / "work.yaml").write_text(nodes, encoding="utf-8", newline="\n")
    (store / "edges" / "work.yaml").write_text(edges, encoding="utf-8", newline="\n")
    return store


@pytest.fixture
def plan_root(tmp_path):
    """A brain root with the plan's store and a pending DDR on wi-ddr."""
    root = tmp_path / "root"
    _write(root / "notes" / "graph")
    (root / "notes" / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    decisions.ask(root, title="Which way", question="Which way for wi-ddr?", options=["Left: shorter", "Right: safer"],
                  why="shorter", at="2030-01-06T09:00:00Z", items=["wi-ddr"], project="demo")
    return root


def _store(root):
    return root / "notes" / "graph"


def _nodes(store):
    return {n["id"]: n for n in yaml.safe_load((store / "nodes" / "work.yaml").read_text(encoding="utf-8"))}


# --- the model and brain check's rules ---

def test_the_items_wave_now_and_the_groups(plan_root):
    plan = waves.load(_store(plan_root), plan_root)
    assert plan.waves == ["wave-1.0.0", "wave-1.1.0", "wave-1.2.0"]   # by release
    assert plan.eras == ["era-one"]
    assert plan.wave_of("wi-carried") == "wave-1.1.0" and plan.carried_in("wi-carried") == "wave-1.0.0"
    assert plan.items_of("wave-1.0.0") == ["wi-old-done"]   # carried out: no longer in it
    assert plan.carried_out("wave-1.0.0") == ["wi-carried"]
    rep = waves.wave_report(plan, "wave-1.1.0")
    ids = {k: [r["id"] for r in rep[k]] for k in ("carried", "startable", "waiting", "other", "closed")}
    assert ids == {"carried": ["wi-carried"], "startable": ["wi-start", "wi-start-p3"],
                   "waiting": ["wi-ddr", "wi-ext", "wi-open-q"], "other": ["wi-doing", "wi-after"],
                   "closed": ["wi-done"]}   # wi-doing unblocks wi-next-after: a higher score (brain.ranking)
    waits = {r["id"]: r["waits_on_owner"] for r in rep["waiting"]}
    assert waits["wi-open-q"] == ["open: which option?"]
    assert waits["wi-ext"] == ["external: Ada signs the form"]
    assert waits["wi-ddr"][0].startswith("DDR ") and "which-way" in waits["wi-ddr"][0]
    assert waves.problems(plan) == [] and waves.warnings(plan) == []


def test_check_refuses_what_breaks_the_rules(tmp_path):
    nodes = NODES + (
        "- {id: wave-bad, type: Milestone, status: pending, title: \"Bad\", props: {kind: wave, release: \"1.x\"}}\n"
        "- {id: wave-dup, type: Milestone, status: pending, title: \"Dup\", props: {kind: wave, release: 1.2.0}}\n"
        "- {id: ms-odd, type: Milestone, status: pending, title: \"Odd\", props: {kind: phase}}\n"
        "- {id: wi-kind, type: WorkItem, status: todo, title: \"Kind on an item\", props: {kind: wave}}\n"
        "- {id: ddr-x, type: DDR, status: answered, title: \"An action\", props: {kind: action}}\n"
        "- {id: wi-two-waves, type: WorkItem, status: todo, title: \"Two waves\"}\n"
        "- {id: wi-in-era, type: WorkItem, status: todo, title: \"An item in an era\"}\n"
        "- {id: wi-back, type: WorkItem, status: todo, title: \"Carried back\", props: {carried_to: 1.0.0}}\n"
        "- {id: wi-nowhere, type: WorkItem, status: todo, title: \"Carried nowhere\", props: {carried_to: 9.9.9}}\n"
        "- {id: wi-left, type: WorkItem, status: todo, title: \"Left in a reached wave\"}\n")
    edges = EDGES + (
        "- {from: ms-free, to: wave-1.1.0, type: part_of}\n"
        "- {from: wi-two-waves, to: wave-1.1.0, type: part_of}\n"
        "- {from: wi-two-waves, to: wave-1.2.0, type: part_of}\n"
        "- {from: wi-in-era, to: era-one, type: part_of}\n"
        "- {from: wi-back, to: wave-1.1.0, type: part_of}\n"
        "- {from: wi-nowhere, to: wave-1.1.0, type: part_of}\n"
        "- {from: wi-left, to: wave-1.0.0, type: part_of}\n")
    plan = waves.load(_write(tmp_path / "graph", nodes, edges))
    got = "\n".join(waves.problems(plan))
    assert "ms-odd: props.kind 'phase' is wave or era" in got
    assert "wi-kind: props.kind wave is a Milestone's, not a WorkItem's" in got
    assert "ddr-x" not in got   # a DDR's own kind (action, question) is not a milestone's
    assert "wave-bad: props.release is a release X.Y.Z (not '1.x')" in got
    assert "wave-dup: release 1.2.0 is also wave-1.2.0's (one wave per release)" in got
    assert "wave-1.1.0: a wave's members are work items, not ms-free" in got
    assert "era-one: an era's members are milestones, not wi-in-era" in got
    assert "wi-two-waves: in 2 waves (wave-1.1.0, wave-1.2.0): one wave per item at most" in got
    assert "wi-back: carried_to 1.0.0 is not after its wave 1.1.0" in got
    assert "wi-nowhere: props.carried_to '9.9.9' names no wave" in got
    # wi-back's carried_to makes 1.0.0 its wave again
    assert "wave-1.0.0: reached" not in got   # a warning since 2026-11-10 (the owner), not an error


def test_warnings_a_loose_wave_and_an_era_whose_exit_is_due(tmp_path):
    nodes = NODES.replace("status: pending, title: \"Core\"", "status: reached, title: \"Core\"") + (
        "- {id: era-two, type: Milestone, status: pending, title: \"Second\", props: {kind: era}}\n"
        "- {id: wave-2.0.0, type: Milestone, status: pending, title: \"Loose\", props: {kind: wave, release: 2.0.0}}\n")
    plan = waves.load(_write(tmp_path / "graph", nodes))
    got = waves.warnings(plan)
    assert "wave-2.0.0: a wave in no milestone or era (brain item link wave-2.0.0 part_of MS)" in got
    assert any(w.startswith("era-two: an era without its exit") for w in got)
    assert any(w.startswith("era-one: its milestones are all reached: its exit is due") and "Ada" in w for w in got)
    assert waves.exit_due(plan, "era-one") and not waves.exit_due(plan, "era-two")   # no milestone: nothing due


def test_a_wave_is_never_a_milestone_suggestion(tmp_path):
    nodes = NODES + "- {id: wi-orphan, type: WorkItem, status: todo, title: \"Orphan\"}\n"
    edges = EDGES + "- {from: wi-orphan, to: wi-start, type: depends_on}\n"   # its neighbour is only in a wave
    ix = milestones.index(_write(tmp_path / "graph", nodes, edges))
    assert "wave-1.1.0" not in ix.pending and "era-one" not in ix.pending and "ms-core" in ix.pending
    assert ix.suggest("wi-orphan") is None


# --- brain next and the view ---

def test_next_prints_carried_first_then_startable_then_the_owner_then_the_next_wave(plan_root, capsys):
    assert cli.main(["--root", str(plan_root), "next"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "Wave 1.1.0 (wave-1.1.0, week of 2030-01-07, part of ms-core): 8 open of 9 (1 done)"
    heads = [line.strip() for line in out if line.startswith("  ") and line.strip().endswith(":")]
    assert heads == ["carried from an earlier wave, first:", "startable:", "waits on Ada:", "other open:"]
    text = "\n".join(out)
    assert text.index("wi-carried [todo] Carried from 1.0.0 (carried from 1.0.0)") < text.index("wi-start [todo]")
    assert text.index("wi-start [todo] Can start (P1)") < text.index("wi-start-p3")   # by priority
    assert "wi-open-q [todo] Asks Ada (waits on Ada: open: which option?)" in text
    assert "wi-after [todo] After wi-start (after wi-start)" in text
    assert out[-2] == "Next: Wave 1.2.0 (wave-1.2.0, part of ms-free): 2 open of 2 (0 done)"
    assert out[-1] == "  startable: wi-next"
    assert cli.main(["--root", str(plan_root), "next", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["owner"] == "Ada" and data["current"]["release"] == "1.1.0" and data["next"]["release"] == "1.2.0"
    assert [r["id"] for r in data["current"]["carried"]] == ["wi-carried"]


def test_next_without_a_wave(tmp_path, capsys):
    store = _write(tmp_path / "root" / "notes" / "graph", "- {id: wi-a, type: WorkItem, status: todo, title: A}\n", "")
    assert cli.main(["--root", str(store.parents[1]), "next"]) == 0
    assert capsys.readouterr().out.startswith("No open wave")


def test_the_view_is_the_tree_era_milestone_wave_items(plan_root):
    text = waves.render(waves.load(_store(plan_root), plan_root))
    assert text.startswith("<!-- GENERATED by `brain sync` (brain.waves)")
    assert "## Next" in text and "Wave 1.1.0 (wave-1.1.0" in text
    order = ["## Era era-one — The first era [pending]", "### ms-core — Core [pending]",
             "#### Wave 1.0.0 [reached]", "#### Wave 1.1.0 [pending]",
             "## Milestones in no era", "### ms-free — Free [pending]", "#### Wave 1.2.0 [pending]"]
    assert [text.index(h) for h in order] == sorted(text.index(h) for h in order)
    assert "Exit (a Go/NoGo DDR once its 2 milestone(s) are reached, 1 so far): Go to the second era?" in text
    assert "Stage at its exit: beta" in text and "Serves: phase one" in text
    assert "- [ ] wi-carried [todo] Carried from 1.0.0 (carried to 1.1.0)" in text   # under 1.0.0, carried out
    assert "- [x] wi-done [done] Done in 1.1.0" in text
    wave = text[text.index("#### Wave 1.1.0"):text.index("## Milestones in no era")]
    assert wave.index("Carried from an earlier wave, first:") < wave.index("Startable:") < \
        wave.index("Waits on Ada:") < wave.index("Other open:") < wave.index("Closed:")
    assert waves.render(waves.load(_store(plan_root), plan_root)) == text   # no date of its own


def test_sync_writes_the_view_and_check_says_what_breaks(plan_root, capsys):
    store = _store(plan_root)
    view = plan_root / waves.VIEW
    assert waves.stale(plan_root, store)
    assert waves.write(plan_root, store) and not waves.write(plan_root, store)
    assert view.read_text(encoding="utf-8") == waves.render(waves.load(store, plan_root))
    assert cli.main(["--root", str(plan_root), "check"]) in (0, 1)
    out = capsys.readouterr().out
    assert "plan_graph.md is stale" not in out and "error: plan:" not in out
    nodes = store / "nodes" / "work.yaml"
    nodes.write_text(nodes.read_text(encoding="utf-8").replace("release: 1.2.0", "release: \"1.2\""),
                     encoding="utf-8")
    assert cli.main(["--root", str(plan_root), "check"]) == 1
    out = capsys.readouterr().out
    assert "error: plan: wave-1.2.0: props.release is a release X.Y.Z (not '1.2')" in out
    assert "warning: notes/plan_graph.md is stale: brain sync" in out


def test_a_store_without_waves_gets_no_view(tmp_path):
    store = _write(tmp_path / "graph", "- {id: ms-a, type: Milestone, status: pending, title: A}\n", "")
    assert not waves.applies(store)
    assert waves.applies(_write(tmp_path / "other"))


def test_the_view_goes_to_the_merge_driver_and_the_boundary():
    from pathlib import Path

    from brain import mergedriver
    line = "notes/plan_graph.md merge=brain"
    assert line in mergedriver.ATTRIBUTES
    tmpl = Path(waves.__file__).parent / "templates" / "generic"
    assert line in (tmpl / "gitattributes").read_text(encoding="utf-8")
    assert "notes/plan_graph.md" in (tmpl / "boundary.yaml").read_text(encoding="utf-8")


# --- the closure: brain wave close, brain wave check ---

def test_close_refuses_while_an_item_is_neither_carried_nor_dropped(plan_root, capsys):
    base = ["--root", str(plan_root), "wave"]
    assert cli.main(base + ["check", "1.1.0"]) == 1
    assert "holds 8 open item(s) neither carried nor dropped" in capsys.readouterr().out
    assert cli.main(base + ["close", "1.1.0", "--write"]) == 1
    assert "not closed, 8 open item(s)" in capsys.readouterr().err
    assert _nodes(_store(plan_root))["wave-1.1.0"]["status"] == "pending"   # nothing written
    assert cli.main(base + ["close", "1.1.0", "--carry-to", "1.0.0"]) == 1
    assert "not after 1.1.0" in capsys.readouterr().err
    assert cli.main(base + ["close", "1.1.0", "--carry-to", "next"]) == 1
    assert "not a release X.Y.Z to create" in capsys.readouterr().err
    assert cli.main(base + ["close", "1.1.0", "--carry-to", "1.2.0", "--drop", "wi-done"]) == 1
    assert "not an open item of wave-1.1.0" in capsys.readouterr().err
    assert cli.main(base + ["close", "1.0.0"]) == 1
    assert "already reached" in capsys.readouterr().err


def test_close_carries_drops_and_reaches_the_wave(plan_root, capsys):
    store = _store(plan_root)
    base = ["--root", str(plan_root), "wave"]
    assert cli.main(base + ["close", "1.1.0", "--carry-to", "1.2.0", "--drop", "wi-ext,wi-open-q"]) == 0
    assert "not written: --write" in capsys.readouterr().out
    assert _nodes(store)["wave-1.1.0"]["status"] == "pending"
    assert cli.main(base + ["close", "1.1.0", "--carry-to", "1.2.0", "--drop", "wi-ext,wi-open-q", "--write"]) == 0
    out = capsys.readouterr().out
    assert "wi-carried: carried to 1.2.0 (wave-1.2.0)" in out and "wi-ext: dropped" in out
    nodes = _nodes(store)
    assert nodes["wave-1.1.0"]["status"] == "reached"
    assert "closed by brain wave close (1 done, 6 carried to 1.2.0, 2 dropped)" in \
        nodes["wave-1.1.0"]["props"]["reached"]
    assert nodes["wi-start"]["props"]["carried_to"] == "wave-1.2.0"
    assert nodes["wi-carried"]["props"]["carried_to"] == "wave-1.2.0"   # carried again: its wave now
    assert nodes["wi-ext"]["status"] == "dropped" and "close of wave 1.1.0" in nodes["wi-ext"]["props"]["dropped"]
    assert cli.main(base + ["check", "1.1.0"]) == 0
    plan = waves.load(store, plan_root)
    assert waves.problems(plan) == []
    rep = waves.next_report(plan)
    assert rep["current"]["release"] == "1.2.0" and rep["next"] is None
    assert [r["id"] for r in rep["current"]["carried"]] == ["wi-start", "wi-start-p3", "wi-doing", "wi-after",
                                                             "wi-carried", "wi-ddr"]   # by priority, then score
    assert [r["id"] for r in rep["current"]["startable"]] == ["wi-next"]


def test_wave_add_gives_an_id_without_a_version_and_computes_the_release(plan_root, capsys):
    """wi-brain-wave-ids-decoupled (WAVES-4): wave-sN, its place; the release the next patch after the last wave's."""
    base = ["--root", str(plan_root), "wave", "add"]
    assert cli.main(base + ["--parent", "ms-free", "--week", "2030-01-21"]) == 0
    assert "wave-s4: added, release 1.2.1, part of ms-free" in capsys.readouterr().out
    node = _nodes(_store(plan_root))["wave-s4"]
    assert node["type"] == "Milestone" and node["props"] == {"kind": "wave", "seq": 4, "week": "2030-01-21"}
    plan = waves.load(_store(plan_root))
    assert plan.parents["wave-s4"] == ["ms-free"] and plan.label("wave-s4") == "1.2.1" and plan.waves[-1] == "wave-s4"
    assert cli.main(base + ["1.2.2"]) == 0 and "wave-s5: added, release 1.2.2" in capsys.readouterr().out
    assert "release" not in _nodes(_store(plan_root))["wave-s5"]["props"]   # the computed one: not pinned
    assert cli.main(base + ["1.2.2"]) == 1 and "already a wave" in capsys.readouterr().err
    assert cli.main(base + ["1.4.0"]) == 1 and "a new wave's release is computed, 1.2.3" in capsys.readouterr().err
    assert cli.main(base + ["1.3"]) == 1 and "a release X.Y.Z" in capsys.readouterr().err
    assert cli.main(base + ["--parent", "wi-start"]) == 1


def test_a_stores_first_wave_names_its_release(tmp_path, capsys):
    store = _write(tmp_path / "root" / "notes" / "graph", "- {id: ms-x, type: Milestone, status: pending, title: X}\n",
                   "")
    base = ["--root", str(store.parents[1]), "wave", "add"]
    assert cli.main(base) == 1 and "first wave names its release" in capsys.readouterr().err
    assert cli.main(base + ["0.1.0"]) == 0
    assert _nodes(store)["wave-s1"]["props"] == {"kind": "wave", "seq": 1, "release": "0.1.0"}


def test_the_commands_say_their_lines_in_the_help(capsys):
    from brain.commands import next as next_cmd
    from brain.commands import wave as wave_cmd
    assert next_cmd.run is next_cmd.cmd_next and wave_cmd.run is wave_cmd.cmd_wave
    for sub in ("add", "close", "check", "import", "plan"):
        assert f"brain wave {sub}" in wave_cmd.USAGE
    assert "brain next [--explain] [--json]" in next_cmd.USAGE
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    assert "brain wave close X.Y.Z" in out and "brain next [--explain] [--json]" in out and "{owner}" not in out


# --- the review of #82: a closed wave holds no open item, the waves an item went through, the era's count ---

def _status(text, wid, status):
    return text.replace(f"{{id: {wid}, type: Milestone, status: pending",
                        f"{{id: {wid}, type: Milestone, status: {status}")


def test_close_refuses_to_carry_into_a_wave_that_is_not_pending(tmp_path, capsys):
    root = tmp_path / "root"
    _write(root / "notes" / "graph", _status(NODES, "wave-1.2.0", "dropped") + (
        "- {id: wave-1.3.0, type: Milestone, status: pending, title: \"W\", props: {kind: wave, release: 1.3.0}}\n"),
        EDGES + "- {from: wave-1.3.0, to: ms-free, type: part_of}\n")
    base = ["--root", str(root), "wave", "close", "1.1.0", "--drop", "wi-ext,wi-open-q", "--write"]
    assert cli.main(base + ["--carry-to", "wave-1.2.0"]) == 1   # by its id: a dropped wave still resolves
    assert "--carry-to wave-1.2.0: wave-1.2.0 is dropped, not pending" in capsys.readouterr().err
    assert cli.main(base + ["--carry-to", "1.2.0"]) == 1   # by a release: a dropped wave holds none; a new one goes last
    assert "--carry-to 1.2.0: no live wave of that release, and a new wave goes last, from 1.3.1 on" in         capsys.readouterr().err
    assert _nodes(_store(root))["wave-1.1.0"]["status"] == "pending"   # nothing written
    assert cli.main(base + ["--carry-to", "1.3.0"]) == 0


def test_close_refuses_to_carry_into_a_reached_wave(tmp_path, capsys):
    root = tmp_path / "root"
    _write(root / "notes" / "graph", _status(NODES, "wave-1.2.0", "reached"))
    assert cli.main(["--root", str(root), "wave", "close", "1.1.0", "--carry-to", "1.2.0", "--write"]) == 1
    assert "--carry-to 1.2.0: wave-1.2.0 is reached, not pending" in capsys.readouterr().err


def test_check_refuses_a_dropped_wave_and_warns_of_a_reached_one_that_holds_an_open_item(tmp_path):
    nodes = _status(NODES, "wave-1.2.0", "dropped").replace(
        "title: \"Carried from 1.0.0\", props: {carried_to: 1.1.0}",
        "title: \"Into a dropped wave\", props: {carried_to: wave-1.2.0}")
    got = "\n".join(waves.problems(waves.load(_write(tmp_path / "graph", nodes))))
    # wi-next and wi-next-after are part_of it, wi-carried was carried into it: no live wave shows them
    assert ("wave-1.2.0: dropped, and 3 open item(s) still in it: wi-carried, wi-next, wi-next-after (carry each to "
            "a pending wave, brain item set ID props.carried_to=X.Y.Z, or drop it)") in got
    reached = waves.load(_write(tmp_path / "other", _status(NODES, "wave-1.2.0", "reached")))
    assert "wave-1.2.0: reached" not in "\n".join(waves.problems(reached))   # a warning, not an error (2026-11-10)
    assert "wave-1.2.0: reached, and 2 open item(s) still in it: wi-next, wi-next-after" in \
        "\n".join(waves.warnings(reached))


def test_close_creates_the_wave_it_carries_to_when_there_is_none(tmp_path, capsys):
    """--carry-to a release with no wave yet creates it, part of what the closed wave is part of (the owner,
    2026-11-10), instead of refusing."""
    store = _write(tmp_path / "graph", NODES)
    plan = waves.load(store)
    c = waves.close(store, "1.1.0", "3.0.0", write=True, today="2026-11-10")
    assert c.created and c.carry_to == "wave-s4" and not c.left   # an id without a version (WAVES-4)
    after = waves.load(store)
    assert after.resolve("3.0.0") == "wave-s4" and after.status("wave-s4") == "pending"
    assert _nodes(store)["wave-s4"]["props"]["release"] == "3.0.0"   # named by --carry-to: pinned
    assert after.parents.get("wave-s4") == plan.parents.get("wave-1.1.0")
    assert after.status("wave-1.1.0") == "reached" and _nodes(store)["wave-1.1.0"]["props"]["shipped_as"] == "1.1.0"
    assert all(after.wave_of(i) == "wave-s4" for i in c.carried)
    assert waves.problems(after) == []


def test_an_item_carried_twice_keeps_the_wave_it_went_through(plan_root, capsys):
    store = _store(plan_root)
    nodes = store / "nodes" / "work.yaml"
    nodes.write_text(nodes.read_text(encoding="utf-8") + (
        "- {id: wave-1.3.0, type: Milestone, status: pending, title: \"W\", props: {kind: wave, release: 1.3.0}}\n"),
        encoding="utf-8")
    base = ["--root", str(plan_root), "wave", "close"]
    assert cli.main(base + ["1.1.0", "--carry-to", "1.2.0", "--drop", "wi-ext,wi-open-q", "--write"]) == 0
    assert _nodes(store)["wi-carried"]["props"]["carried_via"] == "wave-1.1.0"   # 1.0.0, then 1.1.0, now 1.2.0
    assert "carried_via" not in _nodes(store)["wi-start"]["props"]   # carried once: its part_of edge says whence
    plan = waves.load(store, plan_root)
    assert plan.carried_in("wi-carried") == "wave-1.1.0" and plan.carried_in("wi-start") == "wave-1.1.0"
    assert "wi-carried" in plan.carried_out("wave-1.1.0") and "wi-carried" in plan.carried_out("wave-1.0.0")
    assert cli.main(base + ["1.2.0", "--carry-to", "1.3.0", "--drop", "wi-next-after", "--write"]) == 0
    capsys.readouterr()
    assert _nodes(store)["wi-carried"]["props"]["carried_via"] == "wave-1.1.0, wave-1.2.0"
    plan = waves.load(store, plan_root)
    assert plan.carried_in("wi-carried") == "wave-1.2.0" and plan.wave_of("wi-carried") == "wave-1.3.0"
    assert all("wi-carried" in plan.carried_out(w) for w in ("wave-1.0.0", "wave-1.1.0", "wave-1.2.0"))
    assert waves.problems(plan) == []
    assert "wi-carried [todo] Carried from 1.0.0 (carried from 1.2.0)" in waves.render(plan)
    bad = waves.load(_write(plan_root / "bad", NODES.replace("props: {carried_to: 1.1.0}",
                                                              "props: {carried_to: 1.1.0, carried_via: 9.9.9}")))
    assert "wi-carried: props.carried_via names no wave: 9.9.9" in waves.problems(bad)


def test_an_era_counts_the_members_its_exit_waits_for(tmp_path):
    nodes = NODES + (
        "- {id: era-w, type: Milestone, status: pending, title: \"Waves\", props: {kind: era, exit: \"Go?\"}}\n"
        "- {id: wave-3.0.0, type: Milestone, status: pending, title: \"W\", props: {kind: wave, release: 3.0.0}}\n")
    plan = waves.load(_write(tmp_path / "graph", nodes, EDGES + "- {from: wave-3.0.0, to: era-w, type: part_of}\n"))
    assert not waves.exit_due(plan, "era-w")
    assert "Exit (a Go/NoGo DDR once its 1 milestone(s) are reached, 0 so far): Go?" in waves.render(plan)


def test_an_item_in_two_waves_is_read_by_release_and_the_closure_says_so(tmp_path):
    nodes = NODES + (
        "- {id: wave-1.9.0, type: Milestone, status: pending, title: \"W\", props: {kind: wave, release: 1.9.0}}\n"
        "- {id: wave-1.10.0, type: Milestone, status: pending, title: \"W\", props: {kind: wave, release: 1.10.0}}\n"
        "- {id: wave-dup, type: Milestone, status: pending, title: \"Dup\", props: {kind: wave, release: 1.2.0}}\n"
        "- {id: wi-twice, type: WorkItem, status: todo, title: \"Twice\"}\n")
    edges = EDGES + ("- {from: wi-twice, to: wave-1.10.0, type: part_of}\n"
                     "- {from: wi-twice, to: wave-1.9.0, type: part_of}\n")
    plan = waves.load(_write(tmp_path / "graph", nodes, edges))
    assert plan.planned("wi-twice") == ["wave-1.9.0", "wave-1.10.0"]   # by release, not by id
    assert plan.wave_of("wi-twice") == "wave-1.9.0" and "wi-twice" not in plan.carried_out("wave-1.10.0")
    behind = [p for p in waves.closure_problems(plan, "1.10.0") if "pending below 1.10.0" in p]
    assert [p.split(" (")[0] for p in behind] == ["wave 1.1.0", "wave 1.2.0", "wave 1.2.0", "wave 1.9.0"]
    assert [p for p in waves.closure_problems(plan, "1.10.0") if p not in behind] == [
        "wi-twice: in 2 waves (wave-1.9.0, wave-1.10.0), wave-1.10.0 among them: one wave per item (brain check)",
        "wave 1.10.0 (wave-1.10.0) is still pending: brain wave close 1.10.0 --write reaches it, then brain sync"]
    assert waves.closure_problems(plan, "1.2.0") == [
        "release 1.2.0 names 2 waves (wave-1.2.0, wave-dup): one wave per release (brain check)"]


def test_the_closure_wants_the_wave_reached(plan_root, capsys):
    store = _store(plan_root)
    plan = waves.load(store, plan_root)
    assert waves.closure_problems(plan, "1.0.0") == []
    # 7.0.0 names no wave, but its PR would leave the pending 1.1.0 and 1.2.0 behind
    assert waves.closure_problems(plan, "7.0.0") == [
        f"wave {r} (wave-{r}) is pending below 7.0.0: close it first (brain wave close {r}), or unpin it (brain item "
        f"set wave-{r} props.release=) when a jump left its release behind" for r in ("1.1.0", "1.2.0")]
    nodes = store / "nodes" / "work.yaml"
    nodes.write_text(nodes.read_text(encoding="utf-8").replace("status: reached, title: \"Wave 1.0.0\"",
                                                               "status: pending, title: \"Wave 1.0.0\""),
                     encoding="utf-8")
    assert cli.main(["--root", str(plan_root), "wave", "check", "1.0.0"]) == 1
    assert "wave 1.0.0 (wave-1.0.0) is still pending: brain wave close 1.0.0 --write" in capsys.readouterr().out


def test_next_when_every_wave_is_closed(tmp_path, capsys):
    nodes = NODES.replace("status: pending, title: \"Wave", "status: reached, title: \"Wave")
    for status in ("todo", "doing", "blocked"):
        nodes = nodes.replace(f"status: {status}", "status: done")
    root = tmp_path / "root"
    _write(root / "notes" / "graph", nodes)
    assert cli.main(["--root", str(root), "next"]) == 0
    assert capsys.readouterr().out.startswith("No open wave: all 3 wave(s) are closed (reached or dropped); plan the "
                                              "next one: brain wave add --parent MS (its release computed)")


# --- the release forecast (wi-brain-wave-version-forecast): brain next and brain wave check say it ---

FORECAST = {"kind": "minor", "patch": "1.1.0", "minor": "1.2.0", "ref": "origin/main", "sha": "abc1234",
            "tipped_by": {"sha": "def5678", "subject": "Merge pull request #8 from a/b", "pr": 8},
            "reasons": [{"kind": "schema", "path": "s.json"}]}


def test_next_and_wave_check_say_the_release_forecast(plan_root, capsys, monkeypatch):
    from brain import nextrelease
    seen = []
    monkeypatch.setattr(nextrelease, "forecast", lambda repos, **kw: seen.append(repos) or FORECAST)
    assert cli.main(["--root", str(plan_root), "next"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[1].startswith("  release forecast: wave 1.1.0 ships as a minor, 1.2.0, not the patch 1.1.0")
    assert out[2] == "    first tipped by def5678 (PR #8): Merge pull request #8 from a/b"
    assert seen and all(isinstance(r, type(plan_root)) for r in seen[0])   # the project's repos' paths
    assert cli.main(["--root", str(plan_root), "next", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["forecast"]["kind"] == "minor"
    base = ["--root", str(plan_root), "wave", "check"]
    assert cli.main(base + ["1.1.0"]) == 1   # the exit stays the closure rule's
    assert "release forecast: wave 1.1.0 ships as a minor, 1.2.0" in capsys.readouterr().out
    assert cli.main(base + ["1.0.0"]) == 0   # a wave the forecast does not concern: nothing said
    assert "release forecast" not in capsys.readouterr().out


def test_next_without_an_engine_checkout_says_no_forecast(plan_root, capsys):
    assert cli.main(["--root", str(plan_root), "next", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["forecast"] is None
    assert cli.main(["--root", str(plan_root), "next"]) == 0
    assert "release forecast" not in capsys.readouterr().out


# --- wi-brain-wave-ids-decoupled: ids without a version, a computed release, the jump, the rename ---

JUMP_NODES = """\
- {id: ms-x, type: Milestone, status: pending, title: X}
- {id: wave-1.0.0, type: Milestone, status: reached, title: "Wave 1.0.0", props: {kind: wave, release: 1.0.0}}
- {id: wave-1.0.1, type: Milestone, status: pending, title: "Wave 1.0.1", props: {kind: wave, release: 1.0.1}}
- {id: wave-s3, type: Milestone, status: pending, title: "Wave s3", props: {kind: wave, seq: 3}}
- {id: wave-s4, type: Milestone, status: pending, title: "Wave s4", props: {kind: wave, seq: 4}}
- {id: wi-now, type: WorkItem, status: done, title: Now}
- {id: wi-later, type: WorkItem, status: todo, title: Later}
"""
JUMP_EDGES = """\
- {from: wave-1.0.1, to: ms-x, type: part_of}
- {from: wave-s3, to: ms-x, type: part_of}
- {from: wave-s4, to: ms-x, type: part_of}
- {from: wi-now, to: wave-1.0.1, type: part_of}
- {from: wi-later, to: wave-s3, type: part_of}
"""


def test_the_order_and_the_computed_release(tmp_path):
    plan = waves.load(_write(tmp_path / "graph", JUMP_NODES, JUMP_EDGES))
    assert plan.waves == ["wave-1.0.0", "wave-1.0.1", "wave-s3", "wave-s4"]
    assert [plan.label(w) for w in plan.waves] == ["1.0.0", "1.0.1", "1.0.2", "1.0.3"]
    assert plan.computed("wave-s3") and not plan.computed("wave-1.0.1")
    assert plan.resolve("1.0.2") == "wave-s3" and waves.problems(plan) == []
    assert waves.next_report(plan)["current"]["id"] == "wave-1.0.1"


def test_a_release_that_jumps_closes_the_current_wave_and_the_later_ones_follow(tmp_path, capsys):
    """Wave 1.0.1 ships as 1.1.0 (a moved schema): its version PR closes it by that version, and the waves after it
    are 1.1.1 and 1.1.2 without an edit (the renames of WAVES-1 and WAVES-2, no more)."""
    store = _write(tmp_path / "root" / "notes" / "graph", JUMP_NODES, JUMP_EDGES)
    plan = waves.load(store)
    assert plan.for_release("1.1.0") == "wave-1.0.1" and plan.for_release("2.0.0") == "wave-1.0.1"
    assert plan.for_release("1.2.0") is None and plan.for_release("1.0.5") is None   # not a jump of the current one
    assert "is still pending" in "\n".join(waves.closure_problems(plan, "1.1.0"))   # the version PR's rule, by 1.1.0
    base = ["--root", str(store.parents[1]), "wave"]
    assert cli.main(base + ["close", "1.1.0", "--write"]) == 0
    assert "wave 1.0.1 (wave-1.0.1, shipped as 1.1.0): closes with 1 done" in capsys.readouterr().out
    after = waves.load(store)
    assert _nodes(store)["wave-1.0.1"]["props"]["shipped_as"] == "1.1.0"
    assert after.label("wave-s3") == "1.1.1" and after.label("wave-s4") == "1.1.2"
    assert after.resolve("1.1.0") == "wave-1.0.1" and after.resolve("1.0.1") == "wave-1.0.1"
    assert waves.closure_problems(after, "1.1.0") == []
    assert cli.main(base + ["check", "1.1.0"]) == 0   # brain wave check and release_check --store resolve alike
    assert waves.next_report(after)["current"]["release"] == "1.1.1"
    assert cli.main(base + ["rename", "wave-s3", "wave-s4"]) == 1 and "already a node" in capsys.readouterr().err


def test_rename_once_rewrites_the_references_and_keeps_the_old_id(plan_root, capsys):
    """WAVES-5: wave-1.2.0 (pending) renamed wave-s3: its edges and the carried_to that name it rewritten, its
    props.release dropped (computed from then on), the old id in props.renamed_from (it resolves)."""
    store = _store(plan_root)
    nodes = store / "nodes" / "work.yaml"
    nodes.write_text(nodes.read_text(encoding="utf-8").replace(
        'title: "Can start", props: {priority: P1}}',
        'title: "Can start", props: {priority: P1, carried_to: wave-1.2.0}}'),
        encoding="utf-8")
    base = ["--root", str(plan_root), "wave", "rename"]
    before = nodes.read_text(encoding="utf-8")
    assert cli.main(base + ["1.2.0"]) == 0
    out = capsys.readouterr().out
    assert "edges/work.yaml: 3 reference(s) to wave-1.2.0" in out and "not written: --write" in out
    assert nodes.read_text(encoding="utf-8") == before
    assert cli.main(base + ["1.2.0", "wave-1.2.x"]) == 1 and "no dot" in capsys.readouterr().err
    assert cli.main(base + ["wave-1.2.0", "--write"]) == 0
    assert "wave-1.2.0 -> wave-s3 (seq 3)" in capsys.readouterr().out
    got = _nodes(store)
    assert "wave-1.2.0" not in got and got["wave-s3"]["props"]["seq"] == "3"
    assert "release" not in got["wave-s3"]["props"] and got["wi-start"]["props"]["carried_to"] == "wave-s3"
    assert got["wave-s3"]["props"]["renamed_from"].startswith("wave-1.2.0 (brain wave rename, ")
    plan = waves.load(store)
    assert plan.resolve("wave-1.2.0") == "wave-s3" and plan.label("wave-s3") == "1.1.1"   # after 1.1.0, computed
    assert plan.items_of("wave-s3") == ["wi-next", "wi-next-after", "wi-start"]
    assert plan.parents["wave-s3"] == ["ms-free"]
    assert waves.problems(plan) == []


# --- the review of #229: the close after a jump, pins left behind, dropped waves, an ambiguous release, places ---

JUMP_OPEN = JUMP_NODES + "- {id: wi-open, type: WorkItem, status: todo, title: Open}\n"
JUMP_OPEN_EDGES = JUMP_EDGES + "- {from: wi-open, to: wave-1.0.1, type: part_of}\n"


def _jump_store(tmp_path, name, nodes=JUMP_OPEN, edges=JUMP_OPEN_EDGES):
    return _write(tmp_path / name / "notes" / "graph", nodes, edges)


@pytest.mark.parametrize("carry, target, release, pinned", [
    ("1.1.1", "wave-s3", "1.1.1", None),   # the wave after the jump: no second wave of 1.1.1
    ("1.1.3", "wave-s5", "1.1.3", None),   # the next one: created, computed
    ("1.1.5", "wave-s5", "1.1.5", "1.1.5"),   # another one: created, pinned
])
def test_a_jump_close_carries_against_the_plan_after_the_close(tmp_path, capsys, carry, target, release, pinned):
    store = _jump_store(tmp_path, carry)
    base = ["--root", str(store.parents[1]), "wave", "close", "1.1.0", "--carry-to", carry, "--write"]
    assert cli.main(base) == 0
    out = capsys.readouterr().out
    assert f"1 carried to {release}" in _nodes(store)["wave-1.0.1"]["props"]["reached"]   # never « s5 »
    plan = waves.load(store)
    assert plan.wave_of("wi-open") == target and plan.label(target) == release
    assert _nodes(store)[target]["props"].get("release") == pinned
    assert waves.problems(plan) == [] and len(plan.same_release(release)) == 1, out


def test_a_created_wave_goes_last(tmp_path):
    """wave-s4 pinned 1.2.0: after the jump to 1.1.0, 1.1.5 has no wave and a new one would go after 1.2.0."""
    nodes = JUMP_OPEN.replace("props: {kind: wave, seq: 4}", "props: {kind: wave, seq: 4, release: 1.2.0}")
    plan = waves.load(_jump_store(tmp_path, "s", nodes))
    with pytest.raises(waves.WaveError, match="1.1.5: no live wave of that release, and a new wave goes last, from "
                                              "1.2.1 on"):
        waves.plan_close(plan, "1.1.0", "1.1.5")
    assert waves.plan_close(plan, "1.1.0", "1.2.1").created
    with pytest.raises(waves.WaveError, match="not after 1.1.0"):
        waves.plan_close(plan, "1.1.0", "1.0.9")


def test_a_pinned_release_a_jump_left_behind_is_refused(tmp_path):
    nodes = JUMP_NODES.replace("props: {kind: wave, seq: 3}", "props: {kind: wave, seq: 3, release: 1.0.2}")
    plan = waves.load(_write(tmp_path / "a", nodes, JUMP_EDGES))
    assert waves.problems(plan) == []   # 1.0.2 after 1.0.1: in order
    assert waves.closure_problems(plan, "1.1.0")[0].startswith(
        "wave 1.0.2 (wave-s3) is pending below 1.1.0: close it first")   # the jump would leave it behind
    shipped = nodes.replace("status: pending, title: \"Wave 1.0.1\", props: {kind: wave, release: 1.0.1}",
                            "status: reached, title: \"Wave 1.0.1\", props: {kind: wave, release: 1.0.1, "
                            "shipped_as: 1.1.0}")
    got = waves.problems(waves.load(_write(tmp_path / "b", shipped, JUMP_EDGES)))
    assert got == ["wave-s3: release 1.0.2 is not after wave-1.0.1's, which shipped as 1.1.0 (a pinned release a "
                   "jump left behind: brain item set wave-s3 props.release= computes it)"]


def test_a_release_equal_to_the_computed_one_is_not_pinned(tmp_path):
    store = _write(tmp_path / "graph", JUMP_NODES, JUMP_EDGES)
    assert waves.add(store, "1.0.4", pin=True)["props"].get("release") is None   # computed: it follows a jump
    assert waves.add(store, "2.0.0", pin=True)["props"]["release"] == "2.0.0"


def test_a_dropped_wave_holds_no_release(tmp_path):
    nodes = JUMP_NODES.replace("status: pending, title: \"Wave s3\"", "status: dropped, title: \"Wave s3\"")
    edges = JUMP_EDGES.replace("{from: wi-later, to: wave-s3", "{from: wi-later, to: wave-s4")
    plan = waves.load(_write(tmp_path / "graph", nodes, edges))
    assert plan.label("wave-s4") == "1.0.2" and plan.resolve("1.0.2") == "wave-s4"   # counted from 1.0.1
    assert plan.resolve("wave-s3") == "wave-s3" and plan.same_release("1.0.2") == ["wave-s4"]
    assert waves.problems(plan) == [] and waves.next_release(plan) == "1.0.3"
    with pytest.raises(waves.WaveError, match="wave-s3 is dropped, not pending"):
        waves.plan_close(plan, "1.0.1", "wave-s3")


def test_a_later_wave_labelled_as_the_jump_is_ambiguous(tmp_path, capsys):
    nodes = JUMP_NODES.replace("props: {kind: wave, seq: 4}", "props: {kind: wave, seq: 4, release: 1.1.0}")
    store = _write(tmp_path / "root" / "notes" / "graph", nodes, JUMP_EDGES)
    plan = waves.load(store)
    assert plan.candidates("1.1.0") == ["wave-s4", "wave-1.0.1"] and plan.for_release("1.1.0") is None
    (problem,) = waves.closure_problems(plan, "1.1.0")
    assert problem.startswith("release 1.1.0 is ambiguous: wave-s4 is labelled 1.1.0, and 1.1.0 is also the next "
                              "minor or major after the current wave wave-1.0.1 (1.0.1)")
    assert cli.main(["--root", str(store.parents[1]), "wave", "close", "1.1.0"]) == 1
    assert "is ambiguous" in capsys.readouterr().err


def test_a_quick_win_moved_by_id(tmp_path):
    nodes = JUMP_NODES.replace("title: Later}", "title: Later, props: {carried_to: wave-s3}}")
    plan = waves.load(_write(tmp_path / "graph", nodes, JUMP_EDGES))
    assert waves.move_command(plan, "wi-later", "wave-s4") == "brain item set wi-later props.carried_to=wave-s4"


def test_check_refuses_a_place_held_twice_or_zero(tmp_path):
    nodes = JUMP_NODES.replace("props: {kind: wave, seq: 3}", "props: {kind: wave, seq: 0}") + (
        "- {id: wave-x, type: Milestone, status: pending, title: X, props: {kind: wave, seq: 4}}\n")
    got = waves.problems(waves.load(_write(tmp_path / "graph", nodes, JUMP_EDGES + "- {from: wave-x, to: ms-x, "
                                                                                    "type: part_of}\n")))
    assert "wave-s3: props.seq is a whole number from 1 (not 0)" in got
    assert "wave-s4, wave-x: the same place 4 (props.seq or the id's wave-sN): one wave per place" in got
