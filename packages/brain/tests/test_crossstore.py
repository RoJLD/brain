"""wi-brain-cross-store-edges: an edge of a store may name a node another store of the same registry holds. brain
gives research_graph those stores (--foreign-store) whenever it runs or loads such a store, so the store loads and its
board names the other store's node with its label; brain check --all refuses an edge whose end is in no store, as the
store's own check already did. Run with the real research_graph engine, nothing faked."""

from __future__ import annotations

from research_graph.cli import main as research_graph

from brain import cli, crossstore, graph, projects
from brain.commands._stores import check_registry

HOME_NODES = ("- {id: wi-a, type: WorkItem, status: todo, title: Home step}\n"
              "- {id: ms-home, type: Milestone, status: pending, title: Home milestone}\n")
PARENT_NODES = ("- {id: wi-s, type: WorkItem, status: todo, title: Parent step}\n"
               "- {id: ms-parent, type: Milestone, status: pending, title: Parent milestone}\n")


def _project(tmp_path, name: str, nodes: str, edges: str):
    root = tmp_path / name
    store = root / "notes" / "graph"
    assert research_graph(["--store", str(store), "--repo-root", str(root), "init", "--owner", "Ada"]) == 0
    (store / "nodes" / "work.yaml").write_text(nodes, encoding="utf-8")
    (store / "edges" / "work.yaml").write_text(edges, encoding="utf-8")
    return root, store


def _two(tmp_path, monkeypatch, *, parent: bool = True):
    """home (wi-a depends on parent's wi-s) and parent (its milestone groups home's wi-a and home's milestone)."""
    home, hstore = _project(tmp_path, "home", HOME_NODES, "- {from: wi-a, to: wi-s, type: depends_on}\n"
                                                          "- {from: wi-a, to: ms-home, type: part_of}\n")
    sig, sstore = _project(tmp_path, "parent", PARENT_NODES, "- {from: wi-s, to: ms-parent, type: part_of}\n"
                                                           "- {from: wi-a, to: ms-parent, type: part_of}\n"
                                                           "- {from: ms-home, to: ms-parent, type: part_of}\n")
    reg = tmp_path / "brain" / "projects.yaml"
    reg.parent.mkdir(exist_ok=True)
    text = f"home:\n  root: {home.as_posix()}\n"
    reg.write_text(text + (f"parent:\n  root: {sig.as_posix()}\n" if parent else ""), encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    return hstore, sstore


def test_sync_and_check_load_an_edge_to_another_stores_node_and_name_it_by_its_store(tmp_path, monkeypatch, capsys):
    hstore, sstore = _two(tmp_path, monkeypatch)
    assert cli.main(["sync", "--all", "--offline"]) == 0
    home_board = (hstore.parents[1] / "notes" / "kanban_graph.md").read_text(encoding="utf-8")
    assert "- [ ] wi-a — Home step  ← blocked by wi-s (parent:notes/graph) [todo]" in home_board
    parent_board = (sstore.parents[1] / "notes" / "kanban_graph.md").read_text(encoding="utf-8")
    assert "Sub-milestones: ms-home (home:notes/graph) [pending]." in parent_board
    assert "- [ ] wi-a (home:notes/graph) — Home step" in parent_board and "1 work items: todo 1." in parent_board
    roadmap = (sstore.parents[1] / "notes" / "roadmap_graph.md").read_text(encoding="utf-8")
    assert "| ms-parent — Parent milestone | pending | 0/2 | - |" in roadmap
    capsys.readouterr()
    assert cli.main(["check", "--all"]) == 0
    out = capsys.readouterr().out
    assert "cross-store edges: 3 (an edge's end held by another store of the registry)" in out
    assert "registry: 2 project(s), 2 store(s), ids unique" in out


def test_an_edge_to_an_id_in_no_store_is_still_refused(tmp_path, monkeypatch, capsys):
    hstore, _ = _two(tmp_path, monkeypatch)
    with (hstore / "edges" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write("- {from: ms-home, to: wi-ghost, type: depends_on}\n")
    assert cli.main(["check", "--all"]) == 1
    cap = capsys.readouterr()
    assert ("error: edge home:notes/graph: ms-home -> wi-ghost: wi-ghost is in no store of the registry on this "
            "machine") in cap.out
    assert "edge ms-home->wi-ghost: unknown target 'wi-ghost'" in cap.err   # the store's own check, as before
    rc =check_registry(None, list(projects.load().values()))   # a brain's own root, without --all: a warning
    out = capsys.readouterr().out
    assert rc == 0 and "warning: edge home:notes/graph: ms-home -> wi-ghost: wi-ghost is in no store" in out


def test_without_the_other_store_in_the_registry_the_edge_is_refused_as_before(tmp_path, monkeypatch, capsys):
    hstore, _ = _two(tmp_path, monkeypatch, parent=False)
    assert crossstore.engine_args(None, hstore) == []
    assert graph.research_graph(hstore.parents[1], hstore, "check") == 1
    assert "edge wi-a->wi-s: unknown target 'wi-s'" in capsys.readouterr().err


def test_engine_args_name_only_the_stores_that_hold_an_id_the_edges_name(tmp_path, monkeypatch):
    hstore, sstore = _two(tmp_path, monkeypatch)
    assert crossstore.engine_args(None, hstore) == ["--foreign-store", f"parent:notes/graph={sstore}"]
    assert crossstore.engine_args(None, sstore) == ["--foreign-store", f"home:notes/graph={hstore}"]
    (sstore / "edges" / "work.yaml").write_text("- {from: wi-s, to: ms-parent, type: part_of}\n", encoding="utf-8")
    assert crossstore.engine_args(None, sstore) == []   # its edges name only its own ids: nothing more is read
    assert crossstore.foreign_nodes(None, hstore)["wi-s"] == {"store": "parent:notes/graph", "type": "WorkItem",
                                                              "title": "Parent step", "status": "todo"}
    assert crossstore.foreign_nodes(None, sstore) is None
    # it loads, so its board is measured: stale, written by init before the items (a store that does not load: [])
    assert graph.board_stale(hstore.parents[1], hstore, "notes") == ["notes/kanban_graph.md", "notes/roadmap_graph.md"]


def test_item_link_and_add_accept_another_stores_id_as_one_end(tmp_path, monkeypatch, capsys):
    hstore, _ = _two(tmp_path, monkeypatch)
    root = ["--root", str(hstore.parents[1]), "--project", "home"]
    assert cli.main([*root, "item", "link", "ms-home", "part_of", "ms-parent"]) == 0
    assert "- {from: ms-home, to: ms-parent, type: part_of}" in (hstore / "edges" / "work.yaml").read_text(
        encoding="utf-8")
    assert cli.main([*root, "item", "add", "wi-b", "--title", "Home extra", "--milestone", "ms-parent"]) == 0
    assert cli.main([*root, "item", "link", "wi-a", "depends_on", "wi-ghost"]) == 1
    assert "brain: wi-ghost: unknown node" in capsys.readouterr().err
    assert cli.main([*root, "item", "link", "wi-s", "depends_on", "ms-parent"]) == 1
    assert "neither end is a node of this store" in capsys.readouterr().err
    assert cli.main(["check", "--all"]) == 0
