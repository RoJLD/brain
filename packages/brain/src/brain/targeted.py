"""Targeted tests (wi-brain-targeted-tests): the test modules a change touches, from the coverage summary's test ->
code map (brain.testcov, ``<store>/coverage/<repo>.json``), run first; fail-safe: missing, stale or incomplete
evidence widens the answer to the whole suite, and static reachability only ever adds a test, never drops one.

The change: from merge-base(BASE, HEAD) (the scout's base, brain.scout.base_of) to the working tree, untracked files
included, and also from the commit the map measured (what changed since the evidence was taken has to be re-run too).
Each changed path:

- a test module: itself;
- a ``conftest.py``: every test module under its folder;
- a Python module the map measured: the test modules that ran one of its functions, and the test modules that import
  it; when its module level changed (anything but the function bodies and the docstrings: a constant, a signature, a
  decorator, an import), the same for every module that imports it, transitively;
- a Python file the map never measured (a new module, a script, a test helper): the test modules that import or name
  it, and the answer widens (a module loaded by name, a fixture read by path, are invisible to both);
- any other file (docs, data, configuration): the test modules whose text names it, and the answer widens: coverage
  sees no file a test reads (``--inert GLOB`` declares the paths no test reads, such as a changelog fragment).

The answer also widens with no map, a map measured on a dirty tree, or one whose commit is not in HEAD's history. A
test module the map never saw (new, or one that only starts processes: a subprocess's lines carry no test context)
is selected whenever the change touches a Python module.

Shadow mode, report-only (the default, spec-brain-three-repos 1.2): the selection runs, a widened answer is reported
and left to the CI's whole suite, the merge gate; each run is a line of ``<BRAIN_HOME>/ledger/targeted-tests.jsonl``
(head, base, map, selection, widened, pytest's exit) for the comparison with the CI's failures that will let the
selection gate. ``--strict`` applies the fail-safe for real: a widened answer runs the whole suite.
"""

from __future__ import annotations

import ast
import fnmatch
import json
import os
import posixpath
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import inventory, paths, testcov
from .inventory import git

LEDGER = "targeted-tests.jsonl"


class TargetError(Exception):
    pass


@dataclass
class Selection:
    repo: str
    head: str = ""
    base: str = ""            # the ref the change is measured from
    base_rev: str = ""        # merge-base(base, HEAD)
    map_commit: str = ""      # the commit the coverage map measured ('' with no map)
    changed: list[str] = field(default_factory=list)
    tests: dict[str, str] = field(default_factory=dict)    # test module -> why (the first reason)
    widen: list[str] = field(default_factory=list)         # why the evidence cannot answer: the whole suite is
    inert: list[str] = field(default_factory=list)         # changed paths --inert declared no test reads
    suite: list[str] = field(default_factory=list)         # every test module of the repo

    @property
    def complete(self) -> bool:
        return not self.widen

    def add(self, test: str, why: str) -> None:
        if test in self.suite:
            self.tests.setdefault(test, why)

    def to_json(self) -> dict:
        return {"repo": self.repo, "head": self.head, "base": self.base, "base_rev": self.base_rev,
                "map_commit": self.map_commit, "changed": self.changed, "complete": self.complete,
                "widen": self.widen, "inert": self.inert,
                "tests": [{"path": t, "why": w} for t, w in sorted(self.tests.items())],
                "suite_size": len(self.suite)}


# --- the evidence ---

def load_map(path: Path) -> dict | None:
    """A coverage summary (brain.testcov) read from ``path``; None when there is none, it is unreadable, or of
    another version."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ok = isinstance(data, dict) and data.get("version") == testcov.VERSION and isinstance(data.get("files"), dict)
    return data if ok else None


def map_path(store: Path, repo: str) -> Path:
    return store / testcov.FOLDER / f"{repo.lower()}.json"


class _Skeleton(ast.NodeTransformer):
    """A module with its function bodies and docstrings dropped: what runs at import."""

    @staticmethod
    def _undoc(body: list) -> list:
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            return body[1:]
        return body

    def _fn(self, node):
        node.body = [ast.Pass()]
        return node

    visit_FunctionDef = visit_AsyncFunctionDef = _fn

    def visit_ClassDef(self, node):
        node.body = self._undoc(node.body) or [ast.Pass()]
        self.generic_visit(node)
        return node


def skeleton(text: str | None) -> str | None:
    """What of a module runs at import, as an AST dump (positions left out); None when it does not parse."""
    if text is None:
        return None
    try:
        mod = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    mod.body = _Skeleton._undoc(mod.body)
    return ast.dump(_Skeleton().visit(mod), include_attributes=False)


def _imports(text: str, dotted: str, is_pkg: bool) -> set[str]:
    """The dotted names a module imports (each ``from M import n`` as M and M.n), relative imports resolved."""
    out: set[str] = set()
    pkg = dotted.split(".") if is_pkg else dotted.split(".")[:-1]
    for mod, level, names in inventory.text_imports(text):
        if level:
            base = pkg[:len(pkg) - (level - 1)] if level - 1 <= len(pkg) else []
            mod = ".".join([*base, *([mod] if mod else [])])
        if not mod:
            continue
        out.add(mod)
        out.update(f"{mod}.{n}" for n in names)
    return out


def importers(tree: inventory.Tree, mods: dict[str, str]) -> dict[str, set[str]]:
    """Source path -> the source paths that import it (``mods``: dotted -> path)."""
    out: dict[str, set[str]] = {}
    for d, p in mods.items():
        for name in _imports(tree.text(p) or "", d, p.endswith("/__init__.py")):
            target = mods.get(name)
            if target and target != p:
                out.setdefault(target, set()).add(p)
    return out


def closure(start: set[str], users: dict[str, set[str]]) -> set[str]:
    """``start`` and every source path that imports one of them, transitively."""
    seen, todo = set(start), list(start)
    while todo:
        for u in users.get(todo.pop(), ()):
            if u not in seen:
                seen.add(u)
                todo.append(u)
    return seen


# --- the change ---

def changed_paths(top: Path, rev: str) -> set[str]:
    """Every path a change from ``rev`` to the working tree touches: both ends of a rename, untracked files."""
    from .scout import changed
    out: set[str] = set()
    for _, old, new in changed(top, rev):
        out.update(p for p in (old, new) if p)
    return out


def _ancestor(top: Path, a: str, b: str) -> bool:
    return inventory._run_git(top, ["merge-base", "--is-ancestor", a, b])[0] == 0


def _known(top: Path, rev: str) -> bool:
    return inventory._run_git(top, ["cat-file", "-e", f"{rev}^{{commit}}"])[0] == 0


def suite_of(tree: inventory.Tree) -> list[str]:
    """The repo's Python test modules pytest collects: ``test_*.py`` anywhere, ``*_test.py`` under a test folder (an
    installer's ``stranger_test.py`` is a script)."""
    return sorted(p for p in tree.files if p.endswith(".py") and inventory.is_test(p)
                  and (posixpath.basename(p).startswith("test_") or inventory.in_tests(p)))


def _map_revs(top: Path, summary: dict | None, sel: Selection) -> list[str]:
    """[the map's commit] when its evidence can be read against HEAD, else [] and why the answer widens."""
    if not summary or not summary.get("test_modules"):
        sel.widen.append("no coverage map (brain coverage --write, or --map FILE)")
        return []
    sel.map_commit = str(summary.get("commit") or "")
    if summary.get("dirty"):
        sel.widen.append(f"the map was measured on a dirty tree at {sel.map_commit[:7]}")
        return []
    if not sel.map_commit or not _known(top, sel.map_commit) or not _ancestor(top, sel.map_commit, "HEAD"):
        sel.widen.append(f"the map's commit {sel.map_commit[:7] or '?'} is not in HEAD's history")
        return []
    return [sel.map_commit]


class _Selector:
    """One selection's evidence, and its rule for each kind of changed path."""

    def __init__(self, top: Path, tree: inventory.Tree, sel: Selection, summary: dict | None, revs: list[str],
                 roots: list[str] | None):
        self.tree, self.sel = tree, sel
        self.files = (summary or {}).get("files") or {}
        self.mapped = set((summary or {}).get("test_modules") or [])
        lay = inventory.layout(tree, roots)
        self.mods = inventory.module_index(tree, lay)[0] if lay.roots is not None else {}
        self.dotted = {p: d for d, p in self.mods.items()}
        self.ev = inventory.evidence(tree, sel.suite)
        self.olds = [inventory.git_tree(top, rev) for rev in revs]   # each end's text, one cat-file per end
        for o in self.olds:
            o.prefetch([p for p in sel.changed if p.endswith(".py")])
        self.level: set[str] = set()   # source modules whose module level changed
        self.touched_py = False

    def by_import(self, path: str, why: str) -> None:
        for t in self.ev.imports.get(self.dotted.get(path, ""), ()):
            self.sel.add(t, why)

    def by_name(self, path: str) -> int:
        """The test modules whose text names the file (its whole name); how many."""
        name = posixpath.basename(path)
        named = re.compile(r"(?<![\w.-])" + re.escape(name) + r"(?![\w-])")
        hits = [t for t in self.sel.suite if named.search(self.tree.text(t) or "")]
        for t in hits:
            self.sel.add(t, f"names {name}")
        return len(hits)

    def path(self, p: str) -> None:
        if inventory.is_test(p):
            if p in self.tree.files:
                self.sel.add(p, "changed here")
        elif posixpath.basename(p) == "conftest.py":
            d = posixpath.dirname(p)
            for t in self.sel.suite:
                if not d or t.startswith(d + "/"):
                    self.sel.add(t, f"under {p}")
        elif not p.endswith(".py"):
            n = self.by_name(p)
            self.sel.widen.append(f"{p}: a file coverage cannot see ({n} test module(s) name it)")
        elif p not in self.files:
            self.touched_py = True
            self.by_import(p, f"imports {p}")
            self.by_name(p)
            self.sel.widen.append(f"{p}: never measured by the map")
        else:
            self.touched_py = True
            self.module(p)

    def module(self, p: str) -> None:
        """A module the map measured: the tests that ran it or import it; its module level compared at each end."""
        for t in (self.files[p].get("tests") or {}):
            self.sel.add(t, f"ran {p}")
        self.by_import(p, f"imports {p}")
        now = (self.tree.text(p) or "") if p in self.tree.files else None
        sk = skeleton(now)
        if now is None or any(skeleton(o.text(p)) != sk for o in self.olds):
            self.level.add(p)

    def finish(self) -> None:
        """A changed module level's importers, transitively; the test modules the map never saw."""
        why = "(imports a changed module level)"
        for q in sorted(closure(self.level, importers(self.tree, self.mods)) - self.level) if self.level else ():
            for t in ((self.files.get(q) or {}).get("tests") or {}):
                self.sel.add(t, f"ran {q} {why}")
            self.by_import(q, f"imports {q} {why}")
        if self.touched_py and self.mapped:
            for t in self.sel.suite:
                if t not in self.mapped:
                    self.sel.add(t, "not in the map")


def select(top: Path, repo: str, base: str, base_rev: str, summary: dict | None, roots: list[str] | None = None,
           inert: list[str] | None = None) -> Selection:
    """The test modules the change from ``base_rev`` to the working tree of ``top`` touches, by the coverage map
    ``summary`` (None: there is none); ``widen`` says why the evidence cannot answer."""
    tree = inventory.work_tree(top)
    sel = Selection(repo=repo, head=git(top, "rev-parse", "HEAD").strip(), base=base, base_rev=base_rev,
                    suite=suite_of(tree))
    revs = [base_rev, *_map_revs(top, summary, sel)]
    changed = set().union(*(changed_paths(top, rev) for rev in revs))
    sel.inert = sorted(p for p in changed if any(fnmatch.fnmatchcase(p, g) for g in inert or ()))
    sel.changed = sorted(changed - set(sel.inert))
    s = _Selector(top, tree, sel, summary, revs, roots)
    for p in sorted(sel.changed, key=lambda q: not inventory.is_test(q)):   # a changed test says so first
        s.path(p)
    s.finish()
    return sel


# --- the run ---

def _config_dir(top: Path, test: str) -> str:
    d = posixpath.dirname(test)
    while d and not testcov._has_pytest_config(top / d):
        d = posixpath.dirname(d)
    return d


def commands(top: Path, tests: list[str], python: str = "", workers: str = "",
             extra: list[str] | None = None) -> list[tuple[Path, list[str]]]:
    """(the folder pytest runs in, its command) per pytest configuration the test modules fall under."""
    groups: dict[str, list[str]] = {}
    for t in sorted(tests):
        cfg = _config_dir(top, t)
        groups.setdefault(cfg, []).append(t[len(cfg) + 1:] if cfg else t)
    py = python or sys.executable
    return [(top / cfg if cfg else top, [py, "-m", "pytest", *mods, *(["-n", workers] if workers else []),
                                         *(extra or [])]) for cfg, mods in sorted(groups.items())]


def _handle(stream):
    """The stream's file descriptor, flushed, for a child to write to: without one, a child started with no window
    (brain.nowindow, a session's shell) writes pytest's report nowhere. None when the stream has none (a capture)."""
    try:
        stream.flush()
        return stream.fileno()
    except (AttributeError, OSError, ValueError):
        return None


def run(top: Path, tests: list[str], python: str = "", workers: str = "", extra: list[str] | None = None,
        echo=print) -> int:
    """pytest on ``tests``; the worst exit code (5, nothing collected, counts as 0)."""
    worst = 0
    for cwd, cmd in commands(top, tests, python, workers, extra):
        shown = " ".join(cmd[3:])
        echo(f"brain test: {posixpath.relpath(cwd.as_posix(), top.as_posix())}: pytest "
             f"{shown if len(shown) < 300 else shown[:300] + '...'}")
        rc = subprocess.run(cmd, cwd=cwd, env=dict(os.environ), stdout=_handle(sys.stdout),
                            stderr=_handle(sys.stderr)).returncode
        worst = max(worst, 0 if rc == 5 else rc)
    return worst


def record(sel: Selection, mode: str, ran: int, rc: int | None) -> Path:
    """The run's line in the shadow ledger: what a later comparison with the CI's whole suite reads."""
    f = paths.ledger_dir() / LEDGER
    f.parent.mkdir(parents=True, exist_ok=True)
    line = {"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "mode": mode, "repo": sel.repo,
            "head": sel.head, "base_rev": sel.base_rev, "map_commit": sel.map_commit, "complete": sel.complete,
            "widen": sel.widen, "selected": sorted(sel.tests), "suite_size": len(sel.suite), "ran": ran, "rc": rc}
    with f.open("a", encoding="utf-8", newline="\n") as out:
        out.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
    return f


def lines(sel: Selection, limit: int = 40) -> list[str]:
    """The selection in text."""
    out = [f"brain test: {sel.repo}: {len(sel.changed)} changed path(s) since {sel.base} ({sel.base_rev[:7]})"
           + (f" and the map's {sel.map_commit[:7]}" if sel.map_commit and not any(
               "map" in w for w in sel.widen) else "")
           + f"; {len(sel.tests)} of {len(sel.suite)} test module(s) selected"]
    for t, why in sorted(sel.tests.items())[:limit]:
        out.append(f"  {t}  ({why})")
    if len(sel.tests) > limit:
        out.append(f"  ... and {len(sel.tests) - limit} more (--json lists them all)")
    if sel.inert:
        out.append(f"inert (--inert): {', '.join(sel.inert)}")
    if sel.widen:
        out.append("widened to the whole suite: the evidence cannot answer for")
        out.extend(f"  - {w}" for w in sel.widen[:limit])
        if len(sel.widen) > limit:
            out.append(f"  ... and {len(sel.widen) - limit} more")
    else:
        out.append("complete: the map answers for every changed path")
    return out
