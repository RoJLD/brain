"""Edges between the stores of one registry (wi-brain-cross-store-edges).

An edge of a store may name a node another store of the same registry holds (``projects.yaml``: every store of every
registered project on this machine): a programme's items moved to a parent project's store keep their edges to the
child's milestones, specs and decisions, and the parent's milestones group the children's. Ids are unique across the
registry's stores already (``brain check --all``: ``projects.collisions``), so an id names one node.

- **research_graph** loads such a store only when it is told the other stores' ids: every brain command that runs it
  (:func:`engine_args`, given before the subcommand: ``--foreign-store <project>:<store>=<path>``) or loads it in this
  process (:func:`foreign_nodes`) passes the stores that hold an id the store's edges name. A store whose edges name
  only its own ids gets nothing: its runs are what they were.
- **The views** (the board and the roadmap) show the other store's node by its id and that store's label
  (``wi-x (parent:parent/graph)``), never among the store's own items.
- **brain check --all** reads every edge of every store of the registry and refuses one whose end is in no store
  (:func:`check`): such an edge was refused before too, by the store's own check. Without ``--all`` (a brain's own
  root checks the registry too) it is a warning: that store's own check refuses it.
- **brain item link** and **brain item add** accept another store's id as one end (:func:`registry_ids`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import graph, projects


@dataclass
class Report:
    """What :func:`check` read: the stores, the edges whose other end another store holds, and the dangling ones."""
    stores: int = 0
    cross: list[str] = field(default_factory=list)      # "<label>: a -> b (b in <label>)"
    dangling: list[str] = field(default_factory=list)   # "<label>: a -> b: b is in no store of the registry ..."


def _key(store: Path) -> str:
    return projects._norm(store.resolve())


def _rel(store: Path, root: Path) -> str:
    return store.relative_to(root).as_posix() if store.is_relative_to(root) else store.as_posix()


def stores(projs: list[projects.Project]) -> list[tuple[str, Path]]:
    """(label, store) of every store of ``projs`` on this machine (a folder with ``schema.yaml``, as brain sync and
    check read them), each once (a store two entries name, a worktree's registry, is read once), in the registry's
    order; the label is ``<project>:<store relative to its root>``."""
    out, seen = [], set()
    for p in projs:
        for store in projects.stores_of(p):
            if not (store / "schema.yaml").is_file() or _key(store) in seen:
                continue
            seen.add(_key(store))
            out.append((f"{p.name}:{_rel(store, p.root)}", store))
    return out


def _registry(root: Path | None) -> list[tuple[str, Path]]:
    return stores(list(projects.load(root).values()))


def _unreadable() -> tuple[type[BaseException], ...]:
    """What a YAML file that does not parse or read raises (its store's own check says why)."""
    return graph._yaml().YAMLError, OSError, ValueError


def _ids(store: Path) -> set[str]:
    try:
        return set(projects.node_ids(store))
    except _unreadable():
        return set()


def edges(store: Path) -> list[dict]:
    """Every edge of ``store`` as research_graph loads them (``edges.yaml``, ``edges/*.yaml``, generated ones too)."""
    files = [store / "edges.yaml", *sorted((store / "edges").glob("*.yaml"))]
    out = []
    for f in files:
        try:
            out += [e for e in graph.load_yaml_list(f) if isinstance(e, dict)]
        except _unreadable():
            continue
    return out


def outside(store: Path, own: set[str] | None = None) -> set[str]:
    """The ids the edges of ``store`` name that it does not hold."""
    own = _ids(store) if own is None else own
    return {str(e.get(k)) for e in edges(store) for k in ("from", "to") if e.get(k) is not None} - own


def _others(root: Path | None, store: Path) -> list[tuple[str, Path]]:
    return [(label, s) for label, s in _registry(root) if _key(s) != _key(store)]


def holders(root: Path | None, store: Path) -> list[tuple[str, Path]]:
    """The other stores of the registry that hold an id an edge of ``store`` names, (label, store); [] when its edges
    name only its own ids (nothing is read beyond the store then)."""
    if not (store / "nodes").is_dir():
        return []
    wanted = outside(store)
    if not wanted:
        return []
    return [(label, s) for label, s in _others(root, store) if wanted & _ids(s)]


def engine_args(root: Path | None, store: Path) -> list[str]:
    """research_graph's options for ``store``, before its subcommand: ``--foreign-store LABEL=PATH`` for each store of
    :func:`holders`; [] for a store whose edges name only its own ids."""
    return [a for label, s in holders(root, store) for a in ("--foreign-store", f"{label}={s}")]


def foreign_nodes(root: Path | None, store: Path) -> dict | None:
    """``load_store``'s ``foreign`` for ``store`` (research_graph.loader.read_foreign of :func:`holders`), None when
    its edges name only its own ids."""
    found = holders(root, store)
    if not found:
        return None
    from research_graph.loader import read_foreign
    return read_foreign(found)


def registry_ids(root: Path | None, store: Path) -> dict[str, str]:
    """{id: the label of its store} of every node the registry's other stores hold: the ids ``brain item link`` and
    ``brain item add`` accept as an edge's other end."""
    out: dict[str, str] = {}
    for label, s in _others(root, store):
        for nid in _ids(s):
            out.setdefault(nid, label)
    return out


def check(projs: list[projects.Project]) -> Report:
    """Every edge of every store of ``projs`` whose end that store does not hold: in another store (counted, the
    holder named), or in none (dangling)."""
    found = stores(projs)
    ids = {label: _ids(s) for label, s in found}
    where: dict[str, str] = {}
    for label, held in ids.items():
        for nid in held:
            where.setdefault(nid, label)
    rep = Report(len(found))
    for label, s in found:
        for e in edges(s):
            for end in (e.get("from"), e.get("to")):
                if end is None or str(end) in ids[label]:
                    continue
                line = f"{label}: {e.get('from')} -> {e.get('to')}"
                if str(end) in where:
                    rep.cross.append(f"{line} ({end} in {where[str(end)]})")
                else:
                    rep.dangling.append(f"{line}: {end} is in no store of the registry on this machine")
    return rep
