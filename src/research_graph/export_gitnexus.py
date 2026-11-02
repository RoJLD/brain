"""Export the layered graph to the GitNexus graphs sidecar format.

The sidecar (GitNexus fork, ``graphs-sidecar/``) exposes ``POST /g/<name>/create {ddl}`` and
``POST /g/<name>/ingest {nodes, edges}`` over a Kùzu store. This module builds that payload from the YAML
store, which stays the source of truth: the GitNexus graph is derived and disposable.

Two modes:

- ``single`` (default): one ``Node`` table carrying ``type`` as a property. Works with the sidecar as it is:
  its ``ingest`` matches edge endpoints without a label, which Kùzu only accepts when a single node table
  exists ("Create rel bound by multiple node labels is not supported").
- ``typed``: one node table per type. Edges carry ``from_table`` / ``to_table`` so an ingest can match
  ``(a:<from_table> {id})``; the current sidecar ignores them, so this mode needs a sidecar patch.

Code layer: a table holding ``CodeRef`` nodes also gets ``repo``, ``path`` and ``symbol`` columns, parsed from
the CodeRef id, so a Cypher query can select code nodes by repo or file. The DDL is unchanged when the export
holds no CodeRef.
"""

from __future__ import annotations

import json
import urllib.request
from collections import defaultdict

import networkx as nx

from .code_layer import CODE_TYPE, parse_code_ref

NODE_PROPS = ("title", "status", "layer", "anchor", "level")
SINGLE_TABLE = "Node"
CODE_PROPS = ("repo", "path", "symbol")


def _table(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)


def _text(value) -> str:
    return "" if value is None else str(value)


def _code_props(nid: str) -> dict[str, str]:
    try:
        ref = parse_code_ref(nid)
    except ValueError:
        return dict.fromkeys(CODE_PROPS, "")
    return {"repo": ref.repo, "path": ref.path, "symbol": ref.symbol or ""}


def build_payload(graph: nx.DiGraph, layers: set[str] | None = None, *, mode: str = "single") -> dict:
    """``{ddl, nodes, edges}`` for the sidecar; ``layers`` keeps only nodes of those layers."""
    if mode not in {"single", "typed"}:
        raise ValueError(f"mode must be 'single' or 'typed', got {mode!r}")
    keep = {
        n for n, a in graph.nodes(data=True)
        if layers is None or (a.get("layer") or "research") in layers
    }

    def table_of(n: str) -> str:
        return SINGLE_TABLE if mode == "single" else _table(graph.nodes[n].get("type") or "Node")

    props = ("type",) + NODE_PROPS if mode == "single" else NODE_PROPS
    node_tables = sorted({table_of(n) for n in keep})
    code_tables = {table_of(n) for n in keep if graph.nodes[n].get("type") == CODE_TYPE}

    def columns(t: str) -> tuple[str, ...]:
        return props + CODE_PROPS if t in code_tables else props

    ddl = [
        f"CREATE NODE TABLE {t}(id STRING, " + ", ".join(f"{p} STRING" for p in columns(t)) + ", PRIMARY KEY(id))"
        for t in node_tables
    ]
    pairs: dict[str, set[tuple[str, str]]] = defaultdict(set)
    edges = []
    for s, d, a in graph.edges(data=True):
        if s not in keep or d not in keep:
            continue
        rel = _table(a.get("type") or "related")
        src, dst = table_of(s), table_of(d)
        pairs[rel].add((src, dst))
        edge = {"table": rel, "from": s, "to": d, "props": {"id": f"{s}->{rel}->{d}"}}
        if mode == "typed":
            edge.update(from_table=src, to_table=dst)
        edges.append(edge)
    ddl += [
        # The sidecar MERGEs relationships on an ``id`` property, so every REL table declares it.
        f"CREATE REL TABLE {rel}(" + ", ".join(f"FROM {a} TO {b}" for a, b in sorted(p)) + ", id STRING)"
        for rel, p in sorted(pairs.items())
    ]
    nodes = []
    for n in sorted(keep):
        row = {"id": n, **{p: _text(graph.nodes[n].get(p)) for p in props}}
        if table_of(n) in code_tables:
            is_code = graph.nodes[n].get("type") == CODE_TYPE
            row.update(_code_props(n) if is_code else dict.fromkeys(CODE_PROPS, ""))
        nodes.append({"table": table_of(n), "props": row})
    return {"ddl": ddl, "nodes": nodes, "edges": edges}


def push(payload: dict, base_url: str, name: str, *, timeout: float = 60.0) -> dict:
    """POST the payload to a running sidecar: create the tables, then ingest nodes and edges."""
    def post(action: str, body: dict) -> dict:
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/g/{name}/{action}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (local sidecar)
            return json.load(resp)

    created = post("create", {"ddl": payload["ddl"]})
    ingested = post("ingest", {"nodes": payload["nodes"], "edges": payload["edges"]})
    return {"create": created, "ingest": ingested}
