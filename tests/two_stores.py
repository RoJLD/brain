"""Two stores whose edges name each other's nodes (wi-brain-cross-store-edges), for the loader, view and CLI tests.

``home`` holds wi-a (it depends on parent's wi-s), wi-b (part of parent's milestone only), its milestone and an ADR;
``parent`` holds wi-s (decided by home's ADR) and a milestone that groups home's wi-a and home's milestone."""

from __future__ import annotations

from pathlib import Path

SCHEMA = """\
owner: Ada
node_types: [WorkItem, Milestone, ADR]
edge_types: [depends_on, part_of, decided_by]
statuses: [todo, doing, blocked, done, dropped, pending, reached, active]
layers:
  work: [WorkItem, Milestone]
  decisions: [ADR]
"""

HOME_NODES = """\
- {id: wi-a, type: WorkItem, status: todo, title: Home step}
- {id: wi-b, type: WorkItem, status: todo, title: Home extra}
- {id: ms-home, type: Milestone, status: pending, title: Home milestone}
- {id: adr-x, type: ADR, status: active, title: A decision}
"""
HOME_EDGES = """\
- {from: wi-a, to: wi-s, type: depends_on}
- {from: wi-a, to: ms-home, type: part_of}
- {from: wi-b, to: ms-parent, type: part_of}
"""
PARENT_NODES = """\
- {id: wi-s, type: WorkItem, status: todo, title: Parent step}
- {id: ms-parent, type: Milestone, status: pending, title: Parent milestone}
"""
PARENT_EDGES = """\
- {from: wi-s, to: ms-parent, type: part_of}
- {from: wi-s, to: adr-x, type: decided_by}
- {from: wi-a, to: ms-parent, type: part_of}
- {from: ms-home, to: ms-parent, type: part_of}
"""


def store(root: Path, name: str, nodes: str, edges: str) -> Path:
    s = root / name / "graph"
    (s / "nodes").mkdir(parents=True)
    (s / "edges").mkdir()
    (s / "schema.yaml").write_text(SCHEMA, encoding="utf-8")
    (s / "nodes" / "work.yaml").write_text(nodes, encoding="utf-8")
    (s / "edges" / "work.yaml").write_text(edges, encoding="utf-8")
    (s / "edges.yaml").write_text("[]\n", encoding="utf-8")
    return s


def two_stores(root: Path) -> tuple[Path, Path]:
    """(home, parent), each under ``root/<name>/graph``."""
    return store(root, "home", HOME_NODES, HOME_EDGES), store(root, "parent", PARENT_NODES, PARENT_EDGES)
