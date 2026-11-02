"""``research_graph init``: a new store from the package's templates, for someone starting their own graphs.

    research_graph [--store notes/graph] [--repo-root .] init [--owner NAME] [--examples]

Writes ``schema.yaml`` (with ``owner`` when given), ``edges.yaml``, ``nodes/work.yaml`` and ``edges/work.yaml`` in the
store, and the ADR log ``notes/decisions.md`` in the repo when it has none. ``--examples`` fills them with a spec, a
milestone, three work items and an ADR, to read and then replace. The CLI then runs ``sync --write`` and
``kanban --write``, so ``check`` passes at once. Nothing is overwritten: an existing store is refused, an existing ADR
log or spec is kept.
"""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

TEMPLATES = files(__package__) / "templates"
EXAMPLE_SPEC = "docs/specs/2026-01-01-example-spec.md"


def template(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def init_store(store: str | Path, repo_root: str | Path, *, owner: str | None = None,
               examples: bool = False) -> list[Path]:
    """Write a new store (and the repo's ADR log when missing); the files written, in order."""
    store, root = Path(store), Path(repo_root)
    if (store / "schema.yaml").exists():
        raise FileExistsError(f"{store / 'schema.yaml'} exists: {store} is already a store; nothing written")
    log = root / "notes" / "decisions.md"
    with_adr = examples and not log.exists()
    work_edges = template("example_work_edges.yaml" if examples else "work_edges.yaml")
    if examples and not with_adr:  # the example ADR goes only into a new log: no edge to it
        work_edges = "".join(ln for ln in work_edges.splitlines(keepends=True) if "decided_by}" not in ln)
    out = {
        store / "schema.yaml": template("schema.yaml").replace(
            "{owner_line}", f"owner: {json.dumps(owner, ensure_ascii=False)}\n" if owner else ""),
        store / "edges.yaml": template("edges.yaml"),
        store / "nodes" / "work.yaml": template("example_work.yaml" if examples else "work.yaml").replace(
            "{owner}", (owner or "the owner").replace('"', "'")),
        store / "edges" / "work.yaml": work_edges,
    }
    if not log.exists():
        out[log] = template("decisions.md") + (template("example_decisions.md") if with_adr else "")
    if examples and not (root / EXAMPLE_SPEC).exists():
        out[root / EXAMPLE_SPEC] = template("example_spec.md")
    for path, text in out.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return list(out)
