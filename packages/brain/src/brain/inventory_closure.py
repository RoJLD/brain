"""The static production closure of a project's repos (brain.inventory): the index of their modules, packages and
console scripts, the edges of a file (what it imports, the modules, scripts and commands it runs) and the walk from
the declared entries."""

from __future__ import annotations

import posixpath
import re
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .inventory_python import DOTTED_FULL, FILE_REF, IDENT, WORD, PyFacts, _norm, facts

if TYPE_CHECKING:  # annotations only: brain.inventory imports this module
    from .inventory import RepoFacts

DASH_M_ARG = re.compile(r"(?<![\w-])-m\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)(?:[ \t]+([A-Za-z][\w-]*)(?=[\s'\"`;|&)]|$))?",
                        re.M)


@dataclass
class Index:
    """Every repo of a project: the modules, packages, ``__main__`` modules and console scripts by name."""
    modules: dict[str, tuple[str, str]] = field(default_factory=dict)
    packages: dict[str, tuple[str, str]] = field(default_factory=dict)
    mains: dict[str, tuple[str, str]] = field(default_factory=dict)
    console: dict[str, tuple[str, str]] = field(default_factory=dict)
    dotted_of: dict[tuple[str, str], str] = field(default_factory=dict)

    @classmethod
    def build(cls, repos: dict[str, RepoFacts]) -> "Index":
        idx = cls()
        for name, rf in repos.items():
            for d, p in rf.modules.items():
                idx.modules.setdefault(d, (name, p))
                idx.dotted_of[(name, p)] = d
                if p.endswith("/__main__.py"):
                    idx.mains.setdefault(d.rsplit(".", 1)[0], (name, p))
            for d, p in rf.packages.items():
                idx.packages.setdefault(d, (name, p))
            for c, target in rf.console.items():
                path = rf.modules.get(target) or (target if rf.tree.has(target) else "")
                if path:
                    idx.console.setdefault(c, (name, path))
        return idx

    def top_packages(self) -> set[str]:
        if "_tops" not in self.__dict__:
            self._tops = {d.split(".")[0] for d in self.packages} | {d.split(".")[0] for d in self.modules}
        return self._tops

    def module_file(self, dotted: str, main: bool = False) -> tuple[str, str] | None:
        """The file ``python -m dotted`` (``main``: a module, or a package with a ``__main__.py``; a package without
        one cannot run) or ``import dotted`` runs."""
        if main and dotted in self.mains:
            return self.mains[dotted]
        if main and dotted in self.packages:
            return None
        return self.modules.get(dotted)


def _resolve_import(mod: str, level: int, names: tuple, own: str, idx: Index) -> list[str]:
    if level:
        parts = own.split(".") if own else []
        if level - 1 > len(parts):
            return []
        mod = ".".join(parts[:len(parts) - (level - 1)] + ([mod] if mod else []))
    if not mod:
        return []
    out = [f"{mod}.{n}" for n in names if f"{mod}.{n}" in idx.modules]
    parts = mod.split(".")
    for i in range(len(parts), 0, -1):  # the module itself, else its longest importable prefix; then its parents
        d = ".".join(parts[:i])
        if d in idx.modules:
            out.append(d)
    return out


def _label(node: tuple[str, str], idx: Index) -> str:
    d = idx.dotted_of.get(node)
    if d:
        return d.split(".", 1)[1] if "." in d else d
    return node[1].rsplit("/", 1)[-1]


ALL = "*"   # every subcommand of a command module may run


def subcommand_of(func: str, subs: frozenset) -> str:
    """The argparse subcommand a function implements (cmd_publish, do_publish, publish_cmd -> publish), or ''."""
    n = func.lstrip("_")
    for pre in ("cmd_", "command_", "do_", "run_", "handle_"):
        if n.startswith(pre):
            n = n[len(pre):]
            break
    for suf in ("_cmd", "_command"):
        if n.endswith(suf):
            n = n[:-len(suf)]
    return n if n in {s.replace("-", "_") for s in subs} else ""


def _listed(node: tuple[str, str], f: PyFacts, pkg: str, idx: Index) -> list[tuple[tuple[str, str], object]]:
    """The modules a package's __init__ lists to import them (``discovers``: a command registry): each one of its
    package, in its repo."""
    if not (f.discovers and node[1].endswith("/__init__.py") and pkg):
        return []
    return [(n, ALL) for d, n in idx.modules.items() if d.rsplit(".", 1)[0] == pkg and n[0] == node[0]]


def _py_edges(node: tuple[str, str], rf: RepoFacts, idx: Index, allowed) -> list[tuple[tuple[str, str], object]]:
    """A Python file's imports and string constants equal to a module or a command. An import inside the function of
    an argparse subcommand counts only when that subcommand may run (``allowed``: ALL or the subcommands named). A
    package's __init__ that lists its own modules (``discovers``: a command registry) imports each one of them."""
    f = facts(rf.tree, node[1])
    own = idx.dotted_of.get(node, "")
    own_pkg = own if node[1].endswith("/__init__.py") else own.rsplit(".", 1)[0] if "." in own else ""
    out = _listed(node, f, own_pkg, idx)
    for mod, level, names, func in f.imports:
        if func and allowed != ALL and f.subcommands:
            sub = subcommand_of(func, f.subcommands)
            if sub and sub not in allowed:
                continue
        out += [(idx.modules[d], ALL) for d in _resolve_import(mod, level, names, own_pkg, idx)]
    for s in f.strings:
        hit = idx.modules.get(s) or (idx.console.get(s) if not IDENT.fullmatch(s) else None)
        if hit:
            out.append((hit, ALL))
    return out


def edges(node: tuple[str, str], repos: dict[str, RepoFacts], idx: Index, allowed=ALL) \
        -> list[tuple[tuple[str, str], object]]:
    """(file, subcommands) for each file a file names: Python imports and string constants equal to a module or a
    command; in other text, ``-m <dotted> [subcommand]``, script and config file names that resolve to a file of the
    same repo, command names (.exe). The subcommands are ALL, or the set a ``-m`` line names."""
    repo, path = node
    rf = repos[repo]
    if path.endswith(".py"):
        return [(n, s) for n, s in _py_edges(node, rf, idx, allowed) if n != node]
    out: list = []
    text = rf.tree.text(path) or ""
    tops = idx.top_packages()
    for d, sub in DASH_M_ARG.findall(text):
        if d.split(".")[0] in tops:
            hit = idx.module_file(d, main=True)
            if hit:
                out.append((hit, frozenset([sub.replace("-", "_")]) if sub else ALL))
    for tok in set(FILE_REF.findall(text)):
        tok = tok.replace("\\", "/")
        base = tok.rsplit("/", 1)[-1]
        cands = [p for p in rf.tree.by_base(base) if p == tok or p.endswith("/" + tok.lstrip("./"))] \
            or rf.tree.by_base(base)
        here = [p for p in cands if posixpath.dirname(p) == posixpath.dirname(path)]
        out += [((repo, p), ALL) for p in (here or (cands if len(cands) <= 3 else []))]
    for w in set(WORD.findall(text)) & set(idx.console):
        if not IDENT.fullmatch(w) or f"{w}.exe" in text or command_at(text, w):
            out.append((idx.console[w], ALL))
    return [(n, s) for n, s in out if n != node]


def command_at(text: str, name: str) -> bool:
    """A plain-word command name (brain, acme) counts only where a command starts: at a line's start, or after
    ``&``, ``|``, ``;``, ``(`` or a quote; not in prose ("the acme platform")."""
    return re.search(rf"(?m)(?:^\s*|[&|;(`'\"]\s*){re.escape(name)}(?=[\s'\"`)]|$)", text) is not None


def closure(repos: dict[str, RepoFacts], seeds: dict[str, list[str]], idx: Index) \
        -> tuple[dict[tuple[str, str], tuple[int, tuple]], dict[str, list[str]]]:
    """Breadth-first from the seeds: every file reached, with (depth, labels of the files before it), and the seeds
    that resolve to nothing, by repo. A seed is ``script:<console script>``, a repo file or a dotted module. A command
    module run as ``-m <dotted> <subcommand>`` reaches the imports of that subcommand's function only (the scheduler
    runs ``alloc shadow``, not ``alloc publish``); imported, or run without a subcommand, it reaches them all."""
    reached: dict[tuple[str, str], tuple[int, tuple]] = {}
    allowed: dict[tuple[str, str], object] = {}
    missing: dict[str, list[str]] = {}
    queue: deque = deque()

    def visit(node, depth: int, chain: tuple, subs) -> None:
        old = allowed.get(node)
        new = ALL if ALL in (old, subs) else frozenset(old or ()) | subs
        if node not in reached:
            reached[node] = (depth, chain)
        if old is None or new != old:
            allowed[node] = new
            queue.append(node)

    for repo, specs in seeds.items():
        rf = repos[repo]
        for spec in specs:
            if spec.startswith("script:"):
                node = idx.console.get(spec[7:])
            elif rf.tree.has(_norm(spec)):
                node = (repo, _norm(spec))
            elif DOTTED_FULL.fullmatch(spec) or IDENT.fullmatch(spec):
                node = idx.module_file(spec, main=True) or idx.module_file(spec)
            else:
                node = None
            if node is None:
                missing.setdefault(repo, []).append(spec)
            else:
                visit(node, 0, (), ALL)
    while queue:
        node = queue.popleft()
        depth, chain = reached[node]
        # in sorted order: edges() yields a node's neighbours in set order, and the first path the walk takes is the
        # unit's chain, so an unsorted walk gives the same commit different chains under two hash seeds
        for nxt, subs in sorted(edges(node, repos, idx, allowed[node]), key=_edge_key):
            visit(nxt, depth + 1, chain + (_label(node, idx),), subs)
    return reached, missing


def _edge_key(edge: tuple[tuple[str, str], object]) -> tuple:
    """A total order on :func:`edges`' items: the file, then its subcommands (ALL first, else the sorted set)."""
    nxt, subs = edge
    return nxt, () if subs == ALL else (1, *sorted(subs))
