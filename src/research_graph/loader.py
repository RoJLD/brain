from __future__ import annotations

import os
from pathlib import Path

import networkx as nx
import yaml

from .schema import Schema, load_schema


class ValidationError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"{len(errors)} store validation error(s):\n" + "\n".join(errors))


def _load_yaml_list(path: Path) -> list:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValidationError([f"malformed YAML in {path}: {exc}"]) from exc
    if data is None:
        return []
    if not isinstance(data, list):
        raise ValidationError([f"{path}: expected a YAML list, got {type(data).__name__}"])
    return data


def load_store(store_dir: str | Path, schema: Schema | None = None) -> nx.DiGraph:
    store = Path(store_dir)

    structural: list[str] = []
    if schema is None and not (store / "schema.yaml").exists():
        structural.append(f"missing schema.yaml in store: {store}")
    if not (store / "nodes").is_dir():
        structural.append(f"missing nodes/ directory in store: {store}")
    if not (store / "edges.yaml").exists():
        structural.append(f"missing edges.yaml in store: {store}")
    if structural:
        raise ValidationError(structural)

    if schema is None:
        schema = load_schema(store / "schema.yaml")

    raw_nodes: list = []
    for nf in sorted((store / "nodes").glob("*.yaml")):
        raw_nodes.extend(_load_yaml_list(nf))
    raw_edges = _load_yaml_list(store / "edges.yaml")
    # Layer edges (work, data, risk, platform) live beside edges.yaml, which `sync` regenerates.
    if (store / "edges").is_dir():
        for ef in sorted((store / "edges").glob("*.yaml")):
            raw_edges.extend(_load_yaml_list(ef))

    errors: list[str] = []
    g = nx.DiGraph()
    if schema.owner:
        g.graph["owner"] = schema.owner
    seen: set[str] = set()

    for rn in raw_nodes:
        if not isinstance(rn, dict):
            errors.append(f"node entry is not a mapping: {rn!r}")
            continue
        nid = rn.get("id")
        if nid is None:
            errors.append(f"node without id: {rn!r}")
            continue
        if nid in seen:
            errors.append(f"duplicate node id: {nid}")
            continue
        seen.add(nid)
        if rn.get("type") not in schema.node_types:
            errors.append(f"node {nid}: unknown type {rn.get('type')!r}")
        if rn.get("status") not in schema.statuses:
            errors.append(f"node {nid}: unknown status {rn.get('status')!r}")
        elif rn.get("status") not in schema.allowed_statuses(rn.get("type")):
            errors.append(
                f"node {nid}: status {rn.get('status')!r} not allowed for type {rn.get('type')!r}"
            )
        level = rn.get("level")
        if level is not None and schema.levels and level not in schema.levels:
            errors.append(f"node {nid}: unknown level {level!r}")
        g.add_node(
            nid,
            type=rn.get("type"),
            title=rn.get("title", ""),
            status=rn.get("status"),
            level=level,
            layer=schema.layer_of(rn.get("type")),
            anchor=rn.get("anchor"),
            props=rn.get("props", {}),
        )

    for re_ in raw_edges:
        if not isinstance(re_, dict):
            errors.append(f"edge entry is not a mapping: {re_!r}")
            continue
        s, d, et = re_.get("from"), re_.get("to"), re_.get("type")
        ok = True
        if et not in schema.edge_types:
            errors.append(f"edge {s}->{d}: unknown type {et!r}")
            ok = False
        if s not in seen:
            errors.append(f"edge {s}->{d}: unknown source {s!r}")
            ok = False
        if d not in seen:
            errors.append(f"edge {s}->{d}: unknown target {d!r}")
            ok = False
        if ok:
            if g.has_edge(s, d):
                # A DiGraph keeps one edge per node pair: the later edge replaces the earlier one.
                g.graph.setdefault("collapsed_edges", []).append(
                    f"{s}->{d}: {g.edges[s, d]['type']!r} replaced by {et!r} (one edge per node pair)"
                )
            g.add_edge(s, d, type=et, props=re_.get("props", {}))

    if errors:
        raise ValidationError(errors)
    return g


def apply_overlay(g: nx.DiGraph, overlay_dir: str | Path, repo_root: str | Path = ".") -> nx.DiGraph:
    """Add a sibling repo's graph store (e.g. ``../ops-repo/ops/graph``) to ``g``, read-only.

    The overlay has its own ``schema.yaml`` (its nodes are validated against it, not against this repo's
    schema), ``nodes/*.yaml``, ``edges/*.yaml`` and ``external.yaml`` listing the ids of ``g`` it points to;
    each must exist in ``g``. Overlay ids must not clash with ``g``. Anchors are rewritten relative to
    ``repo_root`` so the overlay's files stay resolvable. Nothing is ever written to the overlay.
    """
    overlay = Path(overlay_dir)
    repo_root = Path(repo_root)
    schema = load_schema(overlay / "schema.yaml")
    overlay_repo = overlay.resolve().parents[1]
    errors: list[str] = []
    added: list[str] = []
    for nf in sorted((overlay / "nodes").glob("*.yaml")):
        for rn in _load_yaml_list(nf):
            nid = rn.get("id")
            if nid in g:
                errors.append(f"overlay node {nid}: id already used by this graph")
                continue
            ntype, status = rn.get("type"), rn.get("status")
            if ntype not in schema.node_types:
                errors.append(f"overlay node {nid}: unknown type {ntype!r}")
            if status not in schema.allowed_statuses(ntype):
                errors.append(f"overlay node {nid}: status {status!r} not allowed for type {ntype!r}")
            anchor = rn.get("anchor")
            if anchor:
                path, _, frag = anchor.partition("#")
                try:
                    rel = Path(os.path.relpath(overlay_repo / path, repo_root.resolve())).as_posix()
                except ValueError:  # Windows: overlay and repo on different drives -> keep it absolute
                    rel = (overlay_repo / path).as_posix()
                anchor = f"{rel}#{frag}" if frag else rel
            g.add_node(nid, type=ntype, title=rn.get("title", ""), status=status, level=None,
                       layer=schema.layer_of(ntype), anchor=anchor, props=rn.get("props", {}),
                       overlay=str(overlay))
            added.append(nid)
    for ext in _load_yaml_list(overlay / "external.yaml"):
        if ext.get("id") not in g or ext.get("id") in added:
            errors.append(f"overlay external {ext.get('id')!r} does not exist in this graph")
    for ef in sorted((overlay / "edges").glob("*.yaml")):
        for re_ in _load_yaml_list(ef):
            s, d, et = re_.get("from"), re_.get("to"), re_.get("type")
            if et not in schema.edge_types:
                errors.append(f"overlay edge {s}->{d}: unknown type {et!r}")
            elif s not in g or d not in g:
                errors.append(f"overlay edge {s}->{d}: unknown endpoint")
            else:
                g.add_edge(s, d, type=et, props=re_.get("props", {}), overlay=str(overlay))
    if errors:
        raise ValidationError(errors)
    g.graph.setdefault("overlays", []).append(str(overlay))
    return g
