"""A project's code stores and their CodeRefs (brain.inventory): the CodeRef id grammar, and each store's CodeRef and
Repo nodes read from a repo's tree (committed state)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from . import graph

if TYPE_CHECKING:  # annotations only: brain.inventory imports this module
    from .inventory import RepoFacts, Tree

_SYMBOL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*")
_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


def parse_code_ref(cid: str) -> tuple[str, str, str]:
    """(repo, path, symbol) of ``code:<repo>:<path>[::<symbol>]``, research_graph's code_layer grammar; ValueError
    otherwise."""
    if not cid.startswith("code:"):
        raise ValueError("must start with 'code:'")
    repo, sep, rest = cid[5:].partition(":")
    if not sep or not _REPO.fullmatch(repo):
        raise ValueError("expected code:<repo>:<path>[::<symbol>]")
    path, sep, symbol = rest.partition("::")
    if sep and not _SYMBOL.fullmatch(symbol):
        raise ValueError(f"bad symbol {symbol!r}")
    if not path or "\\" in path or ":" in path or path.startswith("/") \
            or any(p in {"", ".", ".."} for p in path.split("/")):
        raise ValueError(f"bad path {path!r}")
    if sep and not path.endswith(".py"):
        raise ValueError("a symbol needs a .py file")
    return repo, path, symbol if sep else ""


@dataclass
class Store:
    repo: str
    path: str                      # its folder in that repo
    node_types: list
    code_refs: list[tuple[str, str]] = field(default_factory=list)   # (id, status)
    repo_nodes: set = field(default_factory=set)

    @property
    def code_layer(self) -> bool:
        return "CodeRef" in self.node_types


_YAML: dict[str, object] = {}


def _load_yaml(tree: Tree, path: str):
    key = tree.key(path) or f"{tree.repo}:{path}"
    if key not in _YAML:
        y = graph._yaml()
        try:
            _YAML[key] = graph.load_yaml(tree.text(path) or "")
        except y.YAMLError:
            _YAML[key] = None
    return _YAML[key]


def code_stores(repos: dict[str, RepoFacts], declared: list[tuple[str, str]]) -> list[Store]:
    """The project's stores (``declared``: (repo, folder)) and any ``notes/graph`` or ``ops/graph`` of a repo whose
    schema has CodeRef (trade-desk's operations graph), with their CodeRef and Repo nodes."""
    out, seen = [], set()
    auto = [(r, s) for r in repos for s in ("notes/graph", "ops/graph")]
    for repo, rel in list(declared) + auto:
        if (repo, rel) in seen or repo not in repos:
            continue
        seen.add((repo, rel))
        tree = repos[repo].tree
        if not tree.has(f"{rel}/schema.yaml"):
            continue
        schema = _load_yaml(tree, f"{rel}/schema.yaml") or {}
        types = list(schema.get("node_types") or []) if isinstance(schema, dict) else []
        if (repo, rel) not in declared and "CodeRef" not in types:
            continue
        st = Store(repo, rel, types)
        if st.code_layer:
            files = sorted(p for p in tree.files if p.startswith(f"{rel}/nodes/") and p.endswith(".yaml"))
            tree.prefetch(files)
            for f in files:
                text = tree.text(f) or ""
                if "CodeRef" not in text and "Repo" not in text:
                    continue
                for n in _load_yaml(tree, f) or []:
                    if isinstance(n, dict) and n.get("type") == "CodeRef":
                        st.code_refs.append((str(n.get("id")), str(n.get("status", ""))))
                    elif isinstance(n, dict) and n.get("type") == "Repo":
                        st.repo_nodes.add(str(n.get("id")))
        out.append(st)
    return out
