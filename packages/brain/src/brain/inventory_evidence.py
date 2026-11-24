"""The test evidence of a repo's units (brain.inventory): what its tests name, import and run, the files their
imports reach, and each module's, script's and command's evidence from them."""

from __future__ import annotations

import posixpath
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .inventory_closure import Index, _py_edges, _resolve_import
from .inventory_python import DOTTED, FILE_REF, WORD, facts, run_mentions, text_imports, without_fixtures

if TYPE_CHECKING:  # annotations only: brain.inventory imports this module
    from .inventory import RepoFacts, Tree, Unit


@dataclass
class Evidence:
    names: dict[str, set] = field(default_factory=dict)   # stem of test_<stem>.py / test_*_<stem>.py -> tests
    exact: dict[str, set] = field(default_factory=dict)   # stem of test_<stem>.py or Pester <stem>.Tests.ps1
    imports: dict[str, set] = field(default_factory=dict)
    from_names: dict[str, dict] = field(default_factory=dict)   # module -> name imported from it -> tests
    dotted: dict[str, set] = field(default_factory=dict)  # dotted names in the text (and their prefixes)
    files: dict[str, set] = field(default_factory=dict)   # file paths in the text (and their path suffixes)
    runs: dict[str, set] = field(default_factory=dict)    # the script paths a test runs (and their path suffixes)
    per_test: dict[str, tuple] = field(default_factory=dict)   # Python test -> (imports, dotted names, words)


def _add(d: dict, k: str, v: str) -> None:
    d.setdefault(k, set()).add(v)


def _suffixes(tok: str):
    segs = tok.replace("\\", "/").split("/")
    return ("/".join(segs[i:]) for i in range(len(segs)))


def text_tokens(text: str, dotted: dict, files: dict, src: str, tops: set | None = None) -> None:
    for tok in set(DOTTED.findall(text)):
        if tops is not None and tok.split(".", 1)[0] not in tops:
            continue
        parts = tok.split(".")
        for i in range(2, len(parts) + 1):
            _add(dotted, ".".join(parts[:i]), src)
    for tok in set(FILE_REF.findall(text)):
        for suf in _suffixes(tok):
            _add(files, suf, src)


def evidence(tree: Tree, tests: list[str], tops: set | None = None) -> Evidence:
    """What the tests name. A Python test's triple-quoted value strings (sample code, expected output) are left out
    of its imports and names; a script counts as run only where the test starts a process with it."""
    ev = Evidence()
    for t in tests:
        base = t.rsplit("/", 1)[-1]
        if base.startswith("test_") and base.endswith(".py"):
            parts = base[5:-3].split("_")
            _add(ev.exact, base[5:-3], t)
            for i in range(len(parts)):
                _add(ev.names, "_".join(parts[i:]), t)
        elif base.endswith(".Tests.ps1"):
            _add(ev.exact, base[:-10], t)
        raw = tree.text(t) or ""
        if not t.endswith(".py"):   # a Pester or shell test runs what it names
            text_tokens(raw, ev.dotted, ev.files, t, tops)
            for tok in set(FILE_REF.findall(raw)):
                for suf in _suffixes(tok):
                    _add(ev.runs, suf, t)
            continue
        text = without_fixtures(raw)
        imps = []
        for mod, level, names in text_imports(text):
            if level or not mod:
                continue
            imps.append((mod, names))
            _add(ev.imports, mod, t)
            for n in names:
                _add(ev.imports, f"{mod}.{n}", t)
                ev.from_names.setdefault(mod, {}).setdefault(n, set()).add(t)
        text_tokens(text, ev.dotted, ev.files, t, tops)
        for tok in set(run_mentions(raw)):
            for suf in _suffixes(tok):
                _add(ev.runs, suf, t)
        ev.per_test[t] = (imps, set(DOTTED.findall(text)), set(WORD.findall(raw.lower())))
    return ev


def stem(u: Unit) -> str:
    base = u.path.rsplit("/", 1)[-1][:-3]
    return u.name.split(".")[-1] if base == "__init__" else base


def reexports(rf: RepoFacts) -> dict[str, set]:
    """Module -> names its package's __init__ re-exports from it (one level)."""
    out: dict[str, set] = {}
    for pkg, init in rf.packages.items():
        if not init:
            continue
        for mod, level, names, _ in facts(rf.tree, init).imports:
            target = f"{pkg}.{mod}" if level == 1 and mod and "." not in mod else \
                mod if level == 0 and mod.startswith(pkg + ".") and mod.count(".") == pkg.count(".") + 1 else ""
            if target:
                out.setdefault(target, set()).update(names)
    return out


@dataclass
class Reach:
    """Which tests reach each module of a repo through imports (bit i stands for tests[i])."""
    tests: list[str]
    named: dict[str, set]   # test -> the module paths it imports or names (not their parent packages)
    near: dict[str, int]    # module path -> tests that import it or a module that imports it
    far: dict[str, int]     # module path -> tests whose import closure reaches it

    def of(self, mask: int) -> list[str]:
        return [t for i, t in enumerate(self.tests) if mask >> i & 1]


def tests_reach(rf: RepoFacts, ev: Evidence, idx: "Index") -> Reach:
    """The static import closure of each Python test inside its repo: every import (in functions too, a package's
    parents) and string constants equal to a module, as the production closure follows them."""
    name = rf.name
    tests = sorted(ev.per_test)
    named: dict[str, set] = {}
    direct: dict[str, int] = {}

    def hit(path: str, i: int) -> None:
        direct[path] = direct.get(path, 0) | 1 << i

    for i, t in enumerate(tests):
        imps, dotted, _ = ev.per_test[t]
        mine = named.setdefault(t, set())
        for mod, names in imps:
            explicit = [f"{mod}.{n}" for n in names if f"{mod}.{n}" in idx.modules]
            if not explicit:
                parts = mod.split(".")
                explicit = next(([".".join(parts[:k])] for k in range(len(parts), 0, -1)
                                 if ".".join(parts[:k]) in idx.modules), [])
            mine.update(idx.modules[d][1] for d in explicit if idx.modules[d][0] == name)
            for d in _resolve_import(mod, 0, names, "", idx):
                if idx.modules[d][0] == name:
                    hit(idx.modules[d][1], i)
        for tok in dotted:   # -m p.mod, run_module('p.mod')
            parts = tok.split(".")
            for k in range(len(parts), 1, -1):
                got = idx.modules.get(".".join(parts[:k]))
                if got and got[0] == name:
                    mine.add(got[1])
                    hit(got[1], i)
                    break
    succ = {p: {q for (r, q), _ in _py_edges((name, p), rf, idx, "*") if r == name and q != p}
            for p in rf.modules.values()}
    near = dict(direct)
    for p, outs in succ.items():
        if direct.get(p):
            for q in outs:
                near[q] = near.get(q, 0) | direct[p]
    far = dict(direct)
    work = deque(far)
    while work:
        p = work.popleft()
        for q in succ.get(p, ()):
            old = far.get(q, 0)
            if old | far[p] != old:
                far[q] = old | far[p]
                work.append(q)
    return Reach(tests, named, near, far)


def _confirmed(t: str, u: Unit, reach: Reach | None, strict: bool) -> bool:
    """A test named after a module tests it when it imports nothing of the repo (it runs it some other way; not for
    an ambiguous stem), or imports the module or a module of its package, or reaches it through its imports."""
    if reach is None:
        return not strict
    mine = reach.named.get(t, set())
    if not mine and not strict:
        return True
    folder = posixpath.dirname(u.path)
    if any(posixpath.dirname(p) == folder for p in mine):
        return True
    i = reach.tests.index(t) if t in reach.tests else -1
    return i >= 0 and bool(reach.far.get(u.path, 0) >> i & 1)


def module_evidence(u: Unit, rf: RepoFacts, ev: Evidence, stems: dict[str, int], rex: dict[str, set],
                    reach: Reach | None = None) -> tuple[str, list[str]]:
    """(via, tests) of a module, strongest first: 'name' (a unique test_<stem>.py or test_*_<stem>.py that does not
    test another package), 'import', 're-export' (one level, through the package __init__), 'invocation' (its dotted
    or file path in a test's text, fixtures left out), 'name (ambiguous stem)' (confirmed by the test's imports),
    'indirect' (a test imports a module that imports it, and names its stem), 'indirect (unnamed)' (only reached
    through what the tests import: P2 at most); ('', []) when no test."""
    s = stem(u)
    ambiguous = stems.get(s, 0) > 1
    named = [t for t in sorted(ev.names.get(s, ())) if _confirmed(t, u, reach, ambiguous)]
    if named and not ambiguous:
        return "name", named
    if ev.imports.get(u.name):
        return "import", sorted(ev.imports[u.name])
    pkg = u.name.rsplit(".", 1)[0] if "." in u.name else ""
    got = [t for n in rex.get(u.name, ()) for t in ev.from_names.get(pkg, {}).get(n, ())]
    if got:
        return "re-export", sorted(set(got))
    root = rf.root_of.get(u.path, "")
    hits = ev.dotted.get(u.name, set()) | ev.files.get(u.path, set()) \
        | (ev.files.get(u.path[len(root) + 1:], set()) if root else set())
    if hits:
        return "invocation", sorted(hits)
    if named:
        return "name (ambiguous stem)", named
    if reach is not None:
        near = [t for t in reach.of(reach.near.get(u.path, 0)) if s.lower() in ev.per_test[t][2]]
        if near:
            return "indirect", near
        far = reach.of(reach.far.get(u.path, 0))
        if far:
            return "indirect (unnamed)", far
    return "", []


def script_evidence(u: Unit, ev: Evidence) -> tuple[str, list[str]]:
    """('name', tests) for test_<stem>.py or Pester <stem>.Tests.ps1, ('runs', tests) for a test that runs it; else
    ('', the tests that only name it)."""
    base = u.name
    s = base.rsplit(".", 1)[0]
    if ev.exact.get(s):
        return "name", sorted(ev.exact[s])
    hits = ev.runs.get(base, set()) | ev.runs.get(u.path, set())
    if hits:
        return "runs", sorted(hits)
    return "", sorted(ev.files.get(base, set()) | ev.files.get(u.path, set()))


def unit_evidence(rf: RepoFacts, idx: "Index", tops: set | None) -> dict[str, tuple[str, list[str]]]:
    """Module path -> (via, tests) for every module unit of a repo (module_evidence, with the repo's stems,
    re-exports and import reach); sets ``rf.evidence`` and ``rf.reach``."""
    ev = rf.evidence = evidence(rf.tree, rf.tests, tops)
    reach = rf.reach = tests_reach(rf, ev, idx)
    mods = [u for u in rf.units if u.kind == "module"]
    stems: dict[str, int] = {}
    for u in mods:
        stems[stem(u)] = stems.get(stem(u), 0) + 1
    rex = reexports(rf)
    return {u.path: module_evidence(u, rf, ev, stems, rex, reach) for u in mods}


def shim_target(u: Unit, rf: RepoFacts, idx: "Index") -> tuple[str, str] | None:
    """A .py script of 20 lines or fewer that imports one project module takes that module's evidence: (repo, path)
    of that module."""
    if not u.path.endswith(".py"):
        return None
    f = facts(rf.tree, u.path)
    if f.lines > 20:
        return None
    hits = {_resolve_import(m, lv, n, "", idx)[0] for m, lv, n, _ in f.imports
            if not lv and _resolve_import(m, lv, n, "", idx)}
    return idx.modules[hits.pop()] if len(hits) == 1 else None
