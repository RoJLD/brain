from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import yamlio


@dataclass
class Schema:
    node_types: frozenset[str]
    edge_types: frozenset[str]
    statuses: frozenset[str]
    levels: frozenset[str] = frozenset()
    # node type -> layer name (research, decisions, work, data, risk, platform). Optional.
    layers: dict[str, str] = field(default_factory=dict)
    # node type -> statuses allowed for that type; types not listed accept every global status.
    status_by_type: dict[str, frozenset[str]] = field(default_factory=dict)
    # who decides for this store (a person or a team): `pending` lists the items blocked on them. Optional.
    owner: str | None = None

    def layer_of(self, node_type: str | None) -> str | None:
        return self.layers.get(node_type) if node_type else None

    def allowed_statuses(self, node_type: str | None) -> frozenset[str]:
        return self.status_by_type.get(node_type, self.statuses) if node_type else self.statuses


def load_schema(path: str | Path) -> Schema:
    data = yamlio.load(path) or {}
    for key in ("node_types", "edge_types", "statuses"):
        if key not in data:
            raise ValueError(f"schema missing required key: {key}")
    node_types = frozenset(data["node_types"])
    statuses = frozenset(data["statuses"])
    layers: dict[str, str] = {}
    for layer, types in (data.get("layers") or {}).items():
        for t in types or []:
            if t not in node_types:
                raise ValueError(f"schema layers: {layer!r} lists unknown node type {t!r}")
            if t in layers:
                raise ValueError(f"schema layers: node type {t!r} is in {layers[t]!r} and {layer!r}")
            layers[t] = layer
    status_by_type: dict[str, frozenset[str]] = {}
    for t, allowed in (data.get("status_by_type") or {}).items():
        if t not in node_types:
            raise ValueError(f"schema status_by_type: unknown node type {t!r}")
        unknown = set(allowed) - statuses
        if unknown:
            raise ValueError(f"schema status_by_type[{t}]: statuses not in `statuses`: {sorted(unknown)}")
        status_by_type[t] = frozenset(allowed)
    return Schema(
        node_types=node_types,
        edge_types=frozenset(data["edge_types"]),
        statuses=statuses,
        levels=frozenset(data.get("levels", [])),
        layers=layers,
        status_by_type=status_by_type,
        owner=str(data["owner"]) if data.get("owner") else None,
    )
