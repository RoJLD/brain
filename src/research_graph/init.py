"""``research_graph init``: a new store from the package's templates, for someone starting their own graphs.

    research_graph [--store notes/graph] [--repo-root .] [--decisions PATH | --no-decisions] [--views DIR] init
                   [--owner NAME] [--examples] [--layers NAME,NAME...]

Writes ``schema.yaml`` (with ``owner`` when given), ``edges.yaml``, ``nodes/work.yaml`` and ``edges/work.yaml`` in the
store, and the ADR log ``notes/decisions.md`` in the repo when it has none (the first ADR log ``--decisions`` gives;
none with ``--no-decisions``). ``--examples`` fills them with a spec, a
milestone, three work items and an ADR, to read and then replace. The CLI then runs ``sync --write`` and
``kanban --write``, so ``check`` passes at once. Nothing is overwritten: an existing store is refused, an existing ADR
log or spec is kept. ``--layers`` composes ``schema.yaml`` from the catalogue's layers (research_graph layers, with
what they require and ``templates:``) instead of the default schema (the work, decisions and lessons layers).
"""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

TEMPLATES = files(__package__) / "templates"
EXAMPLE_SPEC = "docs/specs/2026-01-01-example-spec.md"


def template(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def schema_text(owner: str | None = None, layer_names=None) -> str:
    """The schema.yaml of a new store: the default one, or the one ``layer_names`` compose (layers.LayerError)."""
    if not layer_names:
        return template("schema.yaml").replace(
            "{owner_line}", f"owner: {json.dumps(owner, ensure_ascii=False)}\n" if owner else "")
    from . import layers
    resolved = layers.resolve(layer_names)
    return layers.render(layers.compose_layers(resolved, owner), layers.header_for(resolved))


def init_store(store: str | Path, repo_root: str | Path, *, owner: str | None = None,
               examples: bool = False, log: str | None = "notes/decisions.md", layer_names=None) -> list[Path]:
    """Write a new store (and the repo's ADR log ``log``, relative to the repo root, when missing; None: no log); the
    files written, in order. ``layer_names``: the catalogue's layers its schema is composed of (the default schema
    without)."""
    store, root = Path(store), Path(repo_root)
    if (store / "schema.yaml").exists():
        raise FileExistsError(f"{store / 'schema.yaml'} exists: {store} is already a store; nothing written")
    schema = schema_text(owner, layer_names)
    if examples and layer_names and not {"WorkItem", "ADR"} <= set(_types(schema)):
        raise ValueError("--examples needs the work and decisions layers (its items and its ADR)")
    log = root / log if log else None
    with_adr = examples and log is not None and not log.exists()
    work_edges = template("example_work_edges.yaml" if examples else "work_edges.yaml")
    if examples and not with_adr:  # the example ADR goes only into a new log: no edge to it
        work_edges = "".join(ln for ln in work_edges.splitlines(keepends=True) if "decided_by}" not in ln)
    out = {
        store / "schema.yaml": schema,
        store / "edges.yaml": template("edges.yaml"),
        store / "nodes" / "work.yaml": template("example_work.yaml" if examples else "work.yaml").replace(
            "{owner}", (owner or "the owner").replace('"', "'")),
        store / "edges" / "work.yaml": work_edges,
    }
    if log is not None and not log.exists():
        out[log] = template("decisions.md") + (template("example_decisions.md") if with_adr else "")
    if examples and not (root / EXAMPLE_SPEC).exists():
        out[root / EXAMPLE_SPEC] = template("example_spec.md")
    for path, text in out.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return list(out)


def _types(schema: str) -> list[str]:
    from . import yamlio
    return list((yamlio.loads(schema) or {}).get("node_types") or [])
