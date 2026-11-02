"""Code layer of the research graph.

A ``CodeRef`` node names the code that implements a graph node, in any repo of the platform (the siblings
under one parent directory). Its id is ``code:<repo>:<path>[::<symbol>]``:

- ``<repo>``: the repo's directory under the platform root (its GitHub name); it must match a ``Repo``
  node, ``repo-<repo lowercased>``;
- ``<path>``: POSIX, relative to the repo's import root: ``src/`` when the file is there, else the repo root;
- ``<symbol>``: optional, a top-level ``def`` / ``class`` / assignment or a dotted path into classes
  (``LighterVenue.funding``). Python files only; without it the CodeRef names the whole file.

Graph nodes point at their code with ``implemented_by``. Two checks:

- :func:`structure_errors` runs in ``graph check`` (CI too): id grammar and the layer's edge rules. It reads
  no sibling repo.
- :func:`check_code_refs` is the dev-local ``code-check``: it reads the sibling checkouts with :mod:`ast`
  (never imports or runs them) and reports CodeRefs whose file or symbol is gone. Repos that are not checked
  out are skipped, like ``scripts/check_platform_pins.py``.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import networkx as nx

CODE_TYPE = "CodeRef"
PREFIX = "code:"
_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_SYMBOL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*")

# code-check verdicts
OK = "OK"
SKIPPED = "SKIPPED"  # repo not checked out under the platform root
MISSING_FILE = "MISSING_FILE"
MISSING_SYMBOL = "MISSING_SYMBOL"
UNPARSABLE = "UNPARSABLE"
MALFORMED = "MALFORMED"
FAILING = frozenset({MISSING_FILE, MISSING_SYMBOL, UNPARSABLE, MALFORMED})


@dataclass(frozen=True)
class CodeRef:
    repo: str
    path: str
    symbol: str | None = None

    @property
    def id(self) -> str:
        return f"{PREFIX}{self.repo}:{self.path}" + (f"::{self.symbol}" if self.symbol else "")

    @property
    def repo_node(self) -> str:
        return f"repo-{self.repo.lower()}"


def parse_code_ref(cid: str) -> CodeRef:
    """Parse ``code:<repo>:<path>[::<symbol>]``; the ValueError says what is wrong."""
    if not cid.startswith(PREFIX):
        raise ValueError(f"must start with {PREFIX!r}")
    repo, sep, rest = cid[len(PREFIX) :].partition(":")
    if not sep or not _REPO.fullmatch(repo):
        raise ValueError("expected code:<repo>:<path>[::<symbol>]")
    path, sep, symbol = rest.partition("::")
    if sep and not _SYMBOL.fullmatch(symbol):
        raise ValueError(f"bad symbol {symbol!r} (identifiers joined by dots)")
    if (
        not path
        or "\\" in path
        or ":" in path
        or path.startswith("/")
        or any(p in {"", ".", ".."} for p in path.split("/"))
    ):
        raise ValueError(f"bad path {path!r} (relative POSIX path, no '.' or '..' segment)")
    if sep and not path.endswith(".py"):
        raise ValueError("a symbol needs a .py file")
    return CodeRef(repo, path, symbol if sep else None)


def code_refs(graph: nx.DiGraph) -> list[str]:
    return sorted(n for n, a in graph.nodes(data=True) if a.get("type") == CODE_TYPE)


# --- graph check (CI-safe: no sibling repo is read) --------------------------------------------------


def structure_errors(graph: nx.DiGraph) -> list[str]:
    """BLOCKING: CodeRef ids parse and name a Repo node; ``implemented_by`` points at a CodeRef; a CodeRef has
    no outgoing edge and receives only ``implemented_by`` (calls, imports and inheritance stay in GitNexus).
    """
    problems: list[str] = []
    for nid, a in graph.nodes(data=True):
        if a.get("type") != CODE_TYPE:
            if str(nid).startswith(PREFIX):
                problems.append(f"{nid}: ids under {PREFIX!r} are reserved for CodeRef nodes")
            continue
        try:
            ref = parse_code_ref(nid)
        except ValueError as exc:
            problems.append(f"{nid}: malformed CodeRef id: {exc}")
            continue
        if ref.repo_node not in graph or graph.nodes[ref.repo_node].get("type") != "Repo":
            problems.append(f"{nid}: no Repo node {ref.repo_node!r} for repo {ref.repo!r}")
        for _, d in graph.out_edges(nid):
            problems.append(
                f"{nid}->{d}: a CodeRef has no outgoing edge (the code graph stays in GitNexus)"
            )
        for s, _, e in graph.in_edges(nid, data=True):
            if e.get("type") != "implemented_by":
                problems.append(
                    f"{s}->{nid}: only implemented_by may point at a CodeRef, got {e.get('type')!r}"
                )
    for s, d, e in graph.edges(data=True):
        if e.get("type") == "implemented_by" and graph.nodes[d].get("type") != CODE_TYPE:
            problems.append(f"{s}->{d}: implemented_by must point at a CodeRef")
    return problems


def orphan_code_refs(graph: nx.DiGraph) -> list[str]:
    """Advisory: a CodeRef that no node is implemented by."""
    return [
        f"{n}: CodeRef with no implemented_by" for n in code_refs(graph) if graph.in_degree(n) == 0
    ]


# --- code-check (dev-local: reads the sibling checkouts) ----------------------------------------------


@dataclass
class Finding:
    id: str
    verdict: str
    file: str | None = None  # resolved, relative to the repo root (GitNexus's filePath)
    kind: str | None = None  # module, file, class, function, method, assign
    line: int | None = None
    detail: str = ""


def _target_names(target: ast.expr) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [n for elt in target.elts for n in _target_names(elt)]
    return []  # x[0] = ..., x.y = ...: not a definition of a name


def _definitions(body: list[ast.stmt]):
    """(name, node) for the definitions of a module or class body, looking into if/try blocks."""
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield stmt.name, stmt
        elif isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                for name in _target_names(t):
                    yield name, stmt
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            yield stmt.target.id, stmt
        elif isinstance(stmt, ast.If):
            yield from _definitions(stmt.body)
            yield from _definitions(stmt.orelse)
        elif isinstance(stmt, ast.Try) or type(stmt).__name__ == "TryStar":
            yield from _definitions(stmt.body)
            for handler in stmt.handlers:
                yield from _definitions(handler.body)
            yield from _definitions(stmt.orelse)
            yield from _definitions(stmt.finalbody)


def find_symbol(tree: ast.Module, symbol: str) -> tuple[str, int] | None:
    """(kind, line) of ``symbol`` (``name`` or ``Class.attr``) in a parsed module, or None. Imports and names
    defined inside functions do not count: a CodeRef names where the code is defined."""
    body: list[ast.stmt] = tree.body
    node: ast.stmt | None = None
    parts = symbol.split(".")
    for i, part in enumerate(parts):
        if i:
            if not isinstance(node, ast.ClassDef):
                return None
            body = node.body
        node = next((n for name, n in _definitions(body) if name == part), None)
        if node is None:
            return None
    if isinstance(node, ast.ClassDef):
        kind = "class"
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        kind = "method" if len(parts) > 1 else "function"
    else:
        kind = "assign"
    return kind, node.lineno


def _exact_file(base: Path, parts: list[str]) -> Path | None:
    """``base/parts...`` if it is a file whose every segment matches in case (Windows matches any case, Linux
    and GitNexus do not)."""
    cur = base
    for part in parts:
        try:
            if part not in os.listdir(cur):
                return None
        except OSError:
            return None
        cur = cur / part
    return cur if cur.is_file() else None


def _exact_dir(root: Path, name: str) -> Path | None:
    try:
        return root / name if name in os.listdir(root) and (root / name).is_dir() else None
    except OSError:
        return None


def _parse(path: Path, cache: dict[Path, ast.Module]) -> ast.Module:
    if path not in cache:
        cache[path] = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return cache[path]


def check_code_refs(graph: nx.DiGraph, platform_root: str | Path) -> list[Finding]:
    """One finding per ``active`` CodeRef, read from the checkouts under ``platform_root`` as they are."""
    root = Path(platform_root)
    cache: dict[Path, ast.Module] = {}
    out: list[Finding] = []
    for nid in code_refs(graph):
        if graph.nodes[nid].get("status") != "active":
            continue
        try:
            ref = parse_code_ref(nid)
        except ValueError as exc:
            out.append(Finding(nid, MALFORMED, detail=str(exc)))
            continue
        if _exact_dir(root, ref.repo) is None:
            out.append(Finding(nid, SKIPPED, detail=f"{ref.repo} not checked out under {root}"))
            continue
        repo_dir = root / ref.repo
        parts = ref.path.split("/")
        target = _exact_file(repo_dir, ["src", *parts]) or _exact_file(repo_dir, parts)
        if target is None:
            out.append(
                Finding(
                    nid, MISSING_FILE, detail=f"neither src/{ref.path} nor {ref.path} in {ref.repo}"
                )
            )
            continue
        rel = target.relative_to(repo_dir).as_posix()
        if ref.symbol is None:
            out.append(Finding(nid, OK, rel, "module" if rel.endswith(".py") else "file"))
            continue
        try:
            tree = _parse(target, cache)
        except (SyntaxError, ValueError, UnicodeDecodeError) as exc:
            out.append(Finding(nid, UNPARSABLE, rel, detail=f"{type(exc).__name__}: {exc}"))
            continue
        found = find_symbol(tree, ref.symbol)
        if found is None:
            out.append(
                Finding(nid, MISSING_SYMBOL, rel, detail=f"{ref.symbol} is not defined in {rel}")
            )
        else:
            out.append(Finding(nid, OK, rel, found[0], found[1]))
    return out


def _git(repo_dir: Path, *args: str) -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", str(repo_dir), *args], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def repo_heads(graph: nx.DiGraph, platform_root: str | Path) -> dict[str, str]:
    """``branch@sha`` (``+dirty`` with uncommitted changes) of each checked-out repo the CodeRefs name, so that a
    code-check result says which checkout it read."""
    root = Path(platform_root)
    repos = set()
    for nid in code_refs(graph):
        try:
            repos.add(parse_code_ref(nid).repo)
        except ValueError:
            continue
    heads: dict[str, str] = {}
    for repo in sorted(repos):
        if _exact_dir(root, repo) is None:
            heads[repo] = "not checked out"
            continue
        branch = _git(root / repo, "rev-parse", "--abbrev-ref", "HEAD")
        sha = _git(root / repo, "rev-parse", "--short", "HEAD")
        if not branch or not sha:
            heads[repo] = "not a git checkout"
            continue
        dirty = _git(root / repo, "status", "--porcelain", "--untracked-files=no")
        heads[repo] = f"{branch}@{sha}" + ("+dirty" if dirty else "")
    return heads
