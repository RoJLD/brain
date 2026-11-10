"""``brain impact --diff [BASE|A..B]`` (wi-brain-impact-diff, ms-brain-impact): before merge, what a change's code
carries in the graph, as a checklist. Zero token, read-only.

The chain:
1. The change: the files from the base to the working tree (untracked files included) and their hunks, read as brain
   audit --diff reads them (brain.scout): from merge-base(BASE, HEAD), the newer merge base of the default branch and
   origin's when no BASE is given, or the commits A..B.
2. The symbols touched, from GitNexus's code index (brain.codeindex): the hunks of the diff from the indexed commit,
   on the files the change touches, matched to the indexed symbols whose lines they overlap. It is the query
   GitNexus's detect_changes runs, sent through its MCP cypher tool: detect_changes itself diffs GitNexus's own clone
   (in its container, at the default branch), never this checkout or its branch. Then the callers of those symbols
   along the CALLS edges GitNexus resolved (a call guessed from a name alone is left out), --depth levels up.
3. The CodeRefs: the code map (brain.codemap) names the CodeRefs of each touched symbol and caller; a file's CodeRef
   is touched by any change to the file; a symbol the index cannot place is looked up by the AST of both sides.
4. The graph: the nodes that rely on those CodeRefs (research_graph's reliance: implemented_by, part_of, depends_on,
   ...: Features, WorkItems, the quant layers), and around them the Doc sections that document them or name a changed
   file, the Test modules that test them (tested_by: brain sync's links, later wi-brain-test-links-auto's) or cover
   the touched code and the CI jobs that run those, the ADRs and SDRs linked to them (the current one of a superseded
   chain), their specs, the open items that deliver them and the DDRs pending on those.

The checklist: the features whose status may change, the docs to update, the ADRs and specs to re-read, the tests to
run (one pytest line), the open items and the pending decisions. ``--json`` prints all of it.

Without GitNexus (the stack down, the repo not indexed, its indexed commit not in this checkout) the impact is at the
file level, and its second line says so and why: every CodeRef of a changed file is touched, a Python symbol's
narrowed by the AST of both sides (research_graph code-check's lookup), and no caller is followed.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import codeindex, codemap, inventory, paths, projects, scout
from .inventory import AuditError, git

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
HEADS = (("--- ", "old"), ("+++ ", "new"), ("rename from ", "old"), ("rename to ", "new"))
DEPTH = 2
MIN_CONFIDENCE = 0.8   # GitNexus's CALLS guessed from a name alone (scope-resolution) score 0.5-0.55: left out
OPEN_ITEMS = ("todo", "doing", "blocked")
OPEN_DDRS = ("pending", "answered")
DECISIONS = ("ADR", "SDR")
SHOWN = 12   # touched symbols with no CodeRef listed in the text view
HINT = {"planned": "this change may make it partial or have", "partial": "this change may complete it (have)",
        "have": "check it still holds", "no": "it was dropped: is this code still wanted?"}


@dataclass
class Change:
    status: str                                          # A, M, D, R..., as git diff --name-status says
    old: str = ""                                        # '' when added
    new: str = ""                                        # '' when deleted
    old_lines: list = field(default_factory=list)       # (first, last) on the base side
    new_lines: list = field(default_factory=list)       # (first, last) on the change's side


@dataclass
class Touched:
    ref: str           # the CodeRef id
    how: str           # symbol, caller, file, ast, file (no index)
    via: str = ""      # the touched symbol a caller reaches, or what the AST found
    path: str = ""


@dataclass
class Report:
    project: str
    repo: str
    base: str
    base_ref: str
    new: str
    mode: str = "gitnexus"     # gitnexus, else files
    why_files: str = ""        # why the file level
    index: str = ""            # the indexed commit
    note: str = ""
    files: list = field(default_factory=list)
    symbols: list = field(default_factory=list)          # touched symbols: {id, name, label, path, lines}
    callers: list = field(default_factory=list)          # {id, name, label, path, callee, level}
    unmapped: list = field(default_factory=list)         # touched symbols no CodeRef names
    coderefs: list = field(default_factory=list)         # Touched
    nodes: dict = field(default_factory=dict)            # type -> ids relying on the touched code
    features: list = field(default_factory=list)
    docs: list = field(default_factory=list)
    decisions: list = field(default_factory=list)
    specs: list = field(default_factory=list)
    tests: list = field(default_factory=list)
    wider_tests: list = field(default_factory=list)      # tested_by tests whose modules cover none of the touched code
    workflows: list = field(default_factory=list)
    items: list = field(default_factory=list)
    ddrs: list = field(default_factory=list)
    stores: list = field(default_factory=list)           # problems loading a store
    malformed: list = field(default_factory=list)        # active CodeRef ids the grammar refuses: left out

    def as_dict(self) -> dict:
        d = asdict(self)
        d["impact"] = 1
        d["pytest"] = pytest_line(self.tests)
        return d

    def add(self, key: str, row: dict) -> None:
        """Append ``row`` to the list ``key`` unless a row with its id is there (several stores)."""
        rows = getattr(self, key)
        if row["id"] not in {r["id"] for r in rows}:
            rows.append(row)


# --- 1. the change ---

def _span(start: int, count: int) -> tuple[int, int] | None:
    """The lines one side of a hunk covers; an insertion (count 0) touches the line it follows."""
    if count:
        return start, start + count - 1
    return (start, start) if start else None


def _head(c: Change, line: str) -> bool:
    """Read a ---, +++ or rename line into ``c``: whether it was one."""
    for prefix, side in HEADS:
        if line.startswith(prefix):
            value = line[len(prefix):].rstrip("\t")
            setattr(c, side, "" if value == "/dev/null" else value[2:] if prefix[0] in "-+" else value)
            return True
    return False


def _hunk(c: Change, line: str) -> None:
    m = HUNK.match(line)
    if m:
        o = _span(int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1))
        n = _span(int(m.group(3)), int(m.group(4) if m.group(4) is not None else 1))
        c.old_lines += [o] if o else []
        c.new_lines += [n] if n else []


def hunks(top: Path, a: str, b: str = "", files=None) -> dict[str, Change]:
    """{path: its Change} of ``git diff -U0`` from ``a`` to ``b`` (the working tree when ''), renames found; keyed by
    the new path, the old one for a deletion. ``files``: only the changes with one of these paths (filtered here,
    never given to git: a large change would pass the Windows command line's limit). The a/ and b/ prefixes are
    asked for, whatever the user's diff.noprefix or diff.mnemonicPrefix; a file's header lines are read before its
    first hunk only, since a deleted line '-- x' reads '--- x' in the body."""
    out = git(top, "-c", "core.quotepath=off", "diff", "-U0", "--no-color", "--no-ext-diff", "-M", "--src-prefix=a/",
              "--dst-prefix=b/", a, *([b] if b else []), "--")
    changes: list[Change] = []
    body = False
    for line in out.splitlines():
        if line.startswith("diff --git "):
            changes.append(Change("M"))
            body = False
        elif changes and line.startswith("@@"):
            body = True
            _hunk(changes[-1], line)
        elif changes and not body:
            _head(changes[-1], line)
    keep = None if files is None else set(files)
    return {c.new or c.old: _status(c) for c in changes
            if (c.new or c.old) and (keep is None or {c.old, c.new} & keep)}


def _status(c: Change) -> Change:
    c.status = "A" if not c.old else "D" if not c.new else "R" if c.old != c.new else "M"
    return c


def _lines(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError:
        return 0


def changes_of(top: Path, base: str, new: str = "") -> list[Change]:
    """Every change from ``base`` to ``new`` (the working tree when ''): brain.scout's file list (untracked files as
    added), each with its hunks; an untracked file's lines are all new."""
    hk = hunks(top, base, new)
    out = []
    for st, old, path in scout.changed(top, base, new):
        old = old or ("" if st[0] == "A" else path)   # scout names the old path of a deletion or a rename only
        c = hk.get(path or old) or Change(st[0], old, path)
        c.status, c.old, c.new = st[0], old, path
        if st[0] == "A" and not c.new_lines and not new:
            n = _lines(top / path)
            c.new_lines = [(1, n)] if n else []
        out.append(c)
    return out


def _overlaps(ranges, first: int, last: int) -> bool:
    return any(a <= last and first <= b for a, b in ranges)


# --- 2. the symbols touched, from GitNexus ---

def index_state(top: Path, folder: str, root: Path | None) -> tuple[codeindex.Indexer | None, list, str, str]:
    """(the indexer, GitNexus's registry, the indexed commit, '') when ``folder`` is indexed at a commit this
    checkout has; else (.., .., '', why the impact falls back to the file level)."""
    try:
        ix, _ = codeindex.load(root)
    except codeindex.CodeIndexError as exc:
        return None, [], "", f"the code index's declaration: {exc}"
    if ix is None:
        return None, [], "", "no stack declares index: (the GitNexus stack)"
    entries = codeindex.registry(ix)
    if entries is None:
        return ix, [], "", (f"{ix.stack.name} does not answer at {ix.api}: brain up {ix.stack.name}, then brain "
                            f"index {folder}")
    sha = str((codeindex._entry(entries, ix, folder) or {}).get("lastCommit") or "")
    if not sha:
        return ix, entries, "", f"{folder} is not indexed: brain index {folder}"
    if not git(top, "rev-parse", "--verify", "-q", f"{sha}^{{commit}}", allow=(0, 1)).strip():
        return ix, entries, "", f"the indexed commit {sha[:7]} is not in this checkout: git fetch"
    return ix, entries, sha, ""


def touched_symbols(ix: codeindex.Indexer, folder: str, at_index: dict[str, Change]) -> tuple[list[dict], str]:
    """The indexed symbols whose lines the old side of ``at_index`` (the diff from the indexed commit) overlaps."""
    olds = {c.old: c.old_lines for c in at_index.values() if c.old and c.old_lines}
    if not olds:
        return [], ""
    rows, why = codemap.nodes_of(ix, folder, olds)
    hit = [{"id": str(r["id"]), "name": str(r.get("name") or ""), "label": str(r.get("label") or ""),
            "path": str(r["path"]), "lines": [r["startLine"], r["endLine"]]} for r in rows
           if r.get("label") != "File" and isinstance(r.get("startLine"), int) and isinstance(r.get("endLine"), int)
           and _overlaps(olds.get(r.get("path"), ()), r["startLine"], r["endLine"])]
    return sorted(hit, key=lambda r: (r["path"], r["lines"][0], r["id"])), why


def callers(ix: codeindex.Indexer, folder: str, ids, depth: int) -> tuple[list[dict], str]:
    """The callers of ``ids`` (CALLS edges GitNexus resolved, not guessed by name), ``depth`` levels up, each with the
    callee it reaches and its level."""
    seen, frontier, out = set(ids), set(ids), []
    for level in range(1, depth + 1):
        if not frontier:
            break
        rows, why = codemap.cypher(ix, folder, "MATCH (c)-[r:CodeRelation]->(n) WHERE r.type = 'CALLS' AND "
                                               f"r.confidence >= {MIN_CONFIDENCE} AND n.id IN "
                                               f"{codemap.in_list(frontier)} RETURN c.id AS id, c.name AS name, "
                                               "label(c) AS label, c.filePath AS path, n.id AS callee")
        if why:
            return out, why
        frontier = set()
        for r in sorted(rows, key=lambda r: (str(r.get("id")), str(r.get("callee")))):
            if str(r.get("id")) not in seen:
                seen.add(str(r.get("id")))
                frontier.add(str(r.get("id")))
                out.append({"id": str(r.get("id")), "name": str(r.get("name") or ""),
                            "label": str(r.get("label") or ""), "path": str(r.get("path") or ""),
                            "callee": str(r.get("callee")), "level": level})
    return out, ""


# --- 3. the CodeRefs ---

def _show(top: Path, rev: str, path: str) -> str | None:
    """A file's text at ``rev`` (the working tree when ''), None when it is not there."""
    if not rev:
        f = top / path
        return f.read_text(encoding="utf-8", errors="replace") if f.is_file() else None
    code, out, _ = inventory._run_git(top, ["show", f"{rev}:{path}"])
    return out.decode("utf-8", "replace") if code == 0 else None


def _ast_span(text: str | None, symbol: str):
    from research_graph import code_layer
    if text is None:
        return None
    try:
        return code_layer.symbol_span(ast.parse(text), symbol) or None
    except (SyntaxError, ValueError):
        return "unparsable"


def ast_touch(top: Path, base: str, new: str, c: Change, symbol: str) -> str:
    """How a change touches ``symbol`` of its Python file by the AST of both sides: '' when it does not."""
    old = _ast_span(_show(top, base, c.old), symbol) if c.old else None
    now = _ast_span(_show(top, new, c.new), symbol) if c.new else None
    if "unparsable" in (old, now):
        return "unparsable, counted as touched"
    if old is None or now is None:
        return "" if old == now else "removed" if now is None else "added"
    return "modified" if _overlaps(c.old_lines, old[1], old[2]) or _overlaps(c.new_lines, now[1], now[2]) else ""


def ref_file(path: str, present) -> str:
    """The repo file a CodeRef's path names: src/<path> when it is there (``present``: the paths of both sides),
    else <path> (code-check's order)."""
    return f"src/{path}" if f"src/{path}" in present else path


def _touch(r: codemap.Ref, by_path: dict[str, Change], syms: set[str], calls: dict[str, dict], top: Path,
           base: str, new: str, indexed: bool) -> Touched | None:
    """How the change touches CodeRef ``r``, None when it does not. A CodeRef whose file the change deletes or moves
    away is touched whatever the index holds: it now names a path that is gone."""
    _, path, symbol = inventory.parse_code_ref(r.id)
    f = r.path or ref_file(path, by_path)
    c, level = by_path.get(f), "file" if indexed else "file (no index)"
    placed = bool(indexed and r.node and not r.why)      # the index holds its symbol or file
    hit = _gone(r, f, c, level) or (_indexed(r, f, syms, calls) if placed else None)
    if hit or c is None or (placed and symbol):
        return hit
    if symbol and f.endswith(".py"):
        how = ast_touch(top, base, new, c, symbol)
        return Touched(r.id, "ast", how, f) if how else None
    return Touched(r.id, level, path=f)


def _gone(r: codemap.Ref, f: str, c: Change | None, level: str) -> Touched | None:
    """``r`` touched because the change deletes or moves away its file ``f``."""
    if c is None or f != c.old or c.status not in ("D", "R"):
        return None
    return Touched(r.id, level, "removed with its file" if c.status == "D" else f"its file moved to {c.new}", f)


def _indexed(r: codemap.Ref, f: str, syms: set[str], calls: dict[str, dict]) -> Touched | None:
    """``r`` touched as the index says: its symbol touched, or a caller of one."""
    if r.node in syms:
        return Touched(r.id, "symbol", path=f)
    if r.node in calls:
        return Touched(r.id, "caller", f"{calls[r.node]['callee']} (depth {calls[r.node]['level']})", f)
    return None


def touched_refs(refs: list[codemap.Ref], changes: list[Change], symbols: list[dict], calls: list[dict], top: Path,
                 base: str, new: str, indexed: bool) -> list[Touched]:
    """The CodeRefs of the changed repo (``refs``, resolved by the code map when ``indexed``) the change touches."""
    by_path = {p: c for c in changes for p in (c.old, c.new) if p}
    syms, by_id = {s["id"] for s in symbols}, {k["id"]: k for k in calls}
    hit = (_touch(r, by_path, syms, by_id, top, base, new, indexed) for r in refs)
    return sorted((t for t in hit if t), key=lambda t: t.ref)


# --- 4. the graph ---

def _load(store: Path, root: Path | None = None):
    from research_graph.loader import ValidationError, load_store

    from . import crossstore
    try:   # an edge may name another store's node (brain.crossstore)
        return load_store(store, foreign=crossstore.foreign_nodes(root, store)), ""
    except ValidationError as exc:
        more = f" (and {len(exc.errors) - 3} more)" if len(exc.errors) > 3 else ""
        return None, f"{store.as_posix()} does not load: {'; '.join(exc.errors[:3])}{more}"


class Walk:
    """One store's graph around the touched CodeRefs."""

    def __init__(self, g, touched: set[str]):
        import networkx as nx
        from research_graph.model import LayeredGraph
        self.g, self.lg = g, LayeredGraph(g)
        rel = self.lg._reliance()
        self.here = [t for t in sorted(touched) if t in g]
        self.deps = set().union(*(nx.ancestors(rel, t) for t in self.here)) if self.here else set()

    def type(self, n: str):
        return self.g.nodes[n].get("type")

    def status(self, n: str):
        return self.g.nodes[n].get("status")

    def title(self, n: str) -> str:
        return " ".join(str(self.g.nodes[n].get("title") or "").split())

    def anchor(self, n: str) -> str:
        return str(self.g.nodes[n].get("anchor") or "").split("#", 1)[0]

    def edges(self, n: str, etype: str, out: bool = True) -> list[str]:
        es = self.g.out_edges(n, data=True) if out else self.g.in_edges(n, data=True)
        return sorted((d if out else s) for s, d, a in es if a.get("type") == etype)

    def row(self, n: str, **extra) -> dict:
        return {"id": n, "status": self.status(n), "title": self.title(n), **extra}

    def features(self, rep: Report) -> None:
        direct = {s for t in self.here for s in self.edges(t, "implemented_by", out=False)}
        for n in sorted(x for x in self.deps if self.type(x) == "Feature"):
            code = [d for d in self.edges(n, "implemented_by") if d in self.here]
            rep.add("features", self.row(n, how="implemented by " + ", ".join(code) if code else
                                         "part of a touched feature", direct=n in direct))

    def items(self, rep: Report) -> set[str]:
        """The open items relying on the code or delivering a feature that does."""
        found = {n for n in self.deps if self.type(n) == "WorkItem"}
        found |= {s for f in self.deps if self.type(f) == "Feature" for s in self.edges(f, "delivers", out=False)}
        found = {n for n in found if self.type(n) == "WorkItem" and self.status(n) in OPEN_ITEMS}
        for n in sorted(found):
            rep.add("items", self.row(n))
        return found

    def decisions(self, rep: Report, around: set[str]) -> None:
        """The decisions linked to ``around`` either way (a superseded one gives the current one), the specs they are
        specified_by, the DDRs pending on them."""
        for n in sorted(around):
            for m in sorted({d for _, d in self.g.out_edges(n)} | {s for s, _ in self.g.in_edges(n)}):
                if self.type(m) in DECISIONS:
                    cur = self.lg.current_decision(m)
                    rep.add("decisions", self.row(cur, type=self.type(cur), via=n,
                                                  **({"supersedes": m} if cur != m else {})))
            for m in self.edges(n, "specified_by"):
                rep.add("specs", self.row(m, via=n))
            for m in self.edges(n, "about", out=False):
                if self.type(m) == "DDR" and self.status(m) in OPEN_DDRS:
                    rep.add("ddrs", self.row(m, via=n))

    def props(self, n: str) -> dict:
        return self.g.nodes[n].get("props") or {}

    def linked(self, files: set[str]) -> tuple[dict, dict, set]:
        """({doc: why}, {test: why}, wider tests) linked to the relying nodes (documented_in, tested_by). A tested_by
        test covering none of ``files`` is one of the nodes' wider tests."""
        docs, tests, wider = {}, {}, set()
        for n in sorted(self.deps):
            for d in self.edges(n, "documented_in"):
                docs.setdefault(d, f"documents {n}")
            for t in self.edges(n, "tested_by"):
                covers = set(self.props(t).get("covers") or [])
                if covers and not covers & files:
                    wider.add(t)
                else:
                    tests.setdefault(t, f"tests {n}")
        return docs, tests, wider

    def named(self, kind: str, key: str, among: set[str], changed: set[str], repo_match) -> dict:
        """{node: why} of the changed repo's ``kind`` nodes (Doc, Test) edited by the change, or whose props
        ``key`` (paths, covers) meet ``among``."""
        out = {}
        for n, a in self.g.nodes(data=True):
            if a.get("type") != kind or not repo_match(a.get("repo")):
                continue
            hit = sorted(set(self.props(n).get(key) or []) & among)
            if self.anchor(n) in changed or hit:
                out[n] = "changed here" if self.anchor(n) in changed else \
                    ("names " if kind == "Doc" else "covers ") + ", ".join(hit)
        return out

    def docs_tests(self, rep: Report, changed: set[str], files: set[str], repo_match, gone: set[str]) -> None:
        """The docs and tests of the relying nodes, then those of the changed repo that name a changed file or
        cover the touched code. A doc whose file the change deletes or moves away says so; such a test is left out
        (the pytest line must run)."""
        docs, tests, wider = self.linked(files)
        docs = _first_why(self.named("Doc", "paths", changed, changed, repo_match), docs)
        docs = {d: "removed by this change" if self.anchor(d) in gone else why for d, why in docs.items()}
        tests = _first_why(self.named("Test", "covers", files, changed, repo_match), tests)
        tests = {t: why for t, why in tests.items() if self.anchor(t) not in gone}
        for d, why in sorted(docs.items()):
            rep.add("docs", {"id": d, "path": self.anchor(d), "title": self.title(d), "why": why,
                             "repo": self.g.nodes[d].get("repo") or ""})
        for t, why in sorted(tests.items()):
            rep.add("tests", {"id": t, "path": self.anchor(t), "why": why, "repo": self.g.nodes[t].get("repo") or "",
                              "framework": self.props(t).get("framework") or ""})
        rep.wider_tests = sorted((set(rep.wider_tests) | wider) - {t["id"] for t in rep.tests})

    def workflows(self, rep: Report) -> None:
        """The CI jobs that run a chosen test or a folder above it."""
        up = {t["id"] for t in rep.tests if t["id"] in self.g}
        stack = list(up)
        while stack:
            for d in self.edges(stack.pop(), "part_of"):
                if self.type(d) == "Test" and d not in up:
                    up.add(d)
                    stack.append(d)
        for w, a in sorted(self.g.nodes(data=True)):
            if a.get("type") == "Workflow" and set(self.edges(w, "runs")) & up:
                rep.add("workflows", {"id": w, "title": self.title(w)})


def _first_why(named: dict, linked: dict) -> dict:
    """One reason per node: a doc or test the change edits says so, else its link to a relying node, else what it
    names or covers."""
    return {**named, **linked, **{n: why for n, why in named.items() if why == "changed here"}}


def walk(rep: Report, g, touched: set[str], changed: set[str], files: set[str], repo_match,
         gone: set[str] = frozenset()) -> None:
    """Add to ``rep`` what in graph ``g`` relies on the ``touched`` CodeRefs, and the docs and tests of the
    ``changed`` files of the changed repo (``repo_match``: whether a Doc or Test node's repo is it). A test is to run
    when the modules it covers meet ``files`` (the changed files and the touched CodeRefs', a caller's included), or
    when it tests a node relying on the touched code and says nothing of what it covers; the other tests of those
    nodes are their wider tests. ``gone``: the paths the change deletes or moves away."""
    w = Walk(g, touched)
    for n in sorted(w.deps):
        rep.nodes.setdefault(str(w.type(n)), []).append(n)
    w.features(rep)
    w.decisions(rep, w.deps | w.items(rep))
    w.docs_tests(rep, changed, files, repo_match, gone)
    w.workflows(rep)


def pytest_line(tests: list[dict]) -> str:
    mods = sorted({t["path"] for t in tests if t.get("framework") == "pytest" and t["path"].endswith(".py")})
    return "pytest " + " ".join(mods) if mods else ""


# --- the command ---

def _range(top: Path, spec: str) -> tuple[str, str, str]:
    """(base ref, base commit, new commit or '' for the working tree) of --diff's ``spec``."""
    if ".." not in spec:
        return (*scout.base_of(top, spec), "")
    a, b = spec.split("..", 1)
    return (a, git(top, "rev-parse", "--verify", f"{a}^{{commit}}").strip(),
            git(top, "rev-parse", "--verify", f"{b or 'HEAD'}^{{commit}}").strip())


def _at_index(rep: Report, top: Path, changes: list[Change]) -> dict[str, Change]:
    """The changes as seen from the indexed commit: their old side holds the index's lines."""
    if rep.index == rep.base:
        return {ch.new or ch.old: ch for ch in changes}
    return hunks(top, rep.index, "" if rep.new == "worktree" else rep.new,
                 {x for ch in changes for x in (ch.old, ch.new) if x})


def _by_index(rep: Report, p: projects.Project, folder: str, top: Path, changes: list[Change], depth: int,
              ix: codeindex.Indexer, entries: list) -> tuple[list[codemap.Ref], str]:
    """The changed repo's CodeRefs resolved by the code map, and the touched symbols and their callers into ``rep``;
    '' when GitNexus answered, else why not."""
    cm = codemap.build(p, ix, entries, only={folder.lower()})
    refs = [r for r in cm.refs.values() if r.repo.lower() == folder.lower()]
    if cm.repos.get(folder) is not None and cm.repos[folder].why:   # the map failed: nothing placed, say so
        return refs, f"the code map of {folder}: {cm.repos[folder].why}"
    rep.symbols, why = touched_symbols(ix, folder, _at_index(rep, top, changes))
    if not why and rep.symbols:
        rep.callers, why = callers(ix, folder, [s["id"] for s in rep.symbols], depth)
    if why:
        rep.symbols, rep.callers = [], []
        return refs, f"GitNexus: {why}"
    if rep.index != rep.base:
        rep.note = (f"the index is at {rep.index[:7]}, the base at {rep.base[:7]}: in the changed files, symbols that "
                    f"differ between the two count as touched too (brain index {folder})")
    return refs, ""


def _repo_of(cid: str) -> str:
    """The repo of a CodeRef id, '' when the id is malformed."""
    try:
        return inventory.parse_code_ref(cid)[0]
    except ValueError:
        return ""


def _bare_refs(p: projects.Project, folder: str) -> list[codemap.Ref]:
    """The changed repo's well-formed active CodeRefs, unresolved (the file level)."""
    return [codemap.Ref(cid, folder) for cid, _ in codemap.active_refs(p) if _repo_of(cid).lower() == folder.lower()]


def _coderefs(rep: Report, root: Path | None, p: projects.Project, registered: bool, folder: str, top: Path,
              changes: list[Change], depth: int) -> list[Touched]:
    """Steps 2 and 3: the touched symbols and their callers when GitNexus can say, else the file level; then the
    CodeRefs the change touches."""
    ix, entries, rep.index, why = index_state(top, folder, root)
    why = why if registered else "the repo is in no registered project: no CodeRef, no graph"
    rep.malformed = sorted(cid for cid, _ in codemap.active_refs(p) if not _repo_of(cid)) if registered else []
    refs: list[codemap.Ref] = []
    if not why:
        refs, why = _by_index(rep, p, folder, top, changes, depth, ix, entries)
    if why:
        rep.mode, rep.why_files, rep.index = "files", why, ""
        refs = _bare_refs(p, folder) if registered else []
    new = "" if rep.new == "worktree" else rep.new
    hit = touched_refs(refs, changes, rep.symbols, rep.callers, top, rep.base, new, rep.mode == "gitnexus")
    rep.coderefs = [asdict(t) for t in hit]
    rep.unmapped = _unmapped(refs, rep.symbols)
    return hit


def _unmapped(refs: list[codemap.Ref], symbols: list[dict]) -> list[dict]:
    """The touched symbols (Class, Function, Method) no resolved CodeRef names."""
    named = {r.node for r in refs if r.node and not r.why}
    return [s for s in symbols if s["id"] not in named and s["label"] in codemap.SYMBOLS]


def _graph(rep: Report, p: projects.Project, repo_match, hit: list[Touched], changes: list[Change]) -> None:
    """Step 4 in each store of the project, then the test files the change adds or edits that no store names yet
    (never a path it deletes or moves away: the pytest line must run)."""
    now = {ch.new for ch in changes if ch.new}
    changed = now | {ch.old for ch in changes if ch.old}
    for store in (s for s in p.stores if (s / "schema.yaml").is_file()):
        g, problem = _load(store, p.root)
        if g is None:
            rep.stores.append(problem)
            continue
        walk(rep, g, {t.ref for t in hit}, changed, changed | {t.path for t in hit}, repo_match, changed - now)
    _new_tests(rep, now)


def _new_tests(rep: Report, now: set[str]) -> None:
    """The test modules the change adds or edits that no store names yet."""
    known = {t["path"] for t in rep.tests}
    rep.tests += [{"id": "", "path": f, "framework": "pytest" if f.endswith(".py") else "", "why": "changed here",
                   "repo": ""} for f in sorted(now) if inventory.is_test(f) and f not in known]


def run(args, root: Path | None) -> Report:
    p, _, c, top, registered = scout.resolve(args, root)
    base_ref, base, new = _range(top, args.diff or "")
    main = (paths.main_checkout(top) or top).resolve()
    folder = c.folder or main.name
    rep = Report(p.name, c.name, base, base_ref, new or "worktree")
    changes = changes_of(top, base, new)
    rep.files = [{"status": ch.status, "old": ch.old, "new": ch.new} for ch in changes]
    if not changes:
        return rep
    hit = _coderefs(rep, root, p, registered, folder, top, changes, DEPTH if args.depth is None else args.depth)
    own = main == (paths.main_checkout(p.root) or p.root).resolve()

    def repo_match(repo) -> bool:
        """A Doc or Test node of the changed repo: no repo: prop in the store's own repo, else its name."""
        return not repo if own else str(repo or "").lower() in (c.name.lower(), folder.lower())

    if registered:
        _graph(rep, p, repo_match, hit, changes)
    return rep


# --- the text view ---

def _head_lines(rep: Report) -> list[str]:
    new = rep.new if rep.new == "worktree" else rep.new[:7]
    out = [f"== impact {rep.project}/{rep.repo}: {rep.base_ref}@{rep.base[:7]}..{new}, "
           f"{len(rep.files)} file(s) changed"]
    if not rep.files:
        return out + ["no file changed"]
    if rep.mode == "files":
        out.append(f"FILE LEVEL (no symbol, no caller): {rep.why_files}")
    else:
        out.append(f"symbols (GitNexus, index at {rep.index[:7]}): {len(rep.symbols)} touched in "
                   f"{len({s['path'] for s in rep.symbols})} file(s), {len(rep.callers)} caller(s)")
    out += [f"note: {rep.note}"] if rep.note else []
    out.append(f"CodeRefs touched ({len(rep.coderefs)}):")
    return out + [f"  {t['ref']}  {t['how']}" + (f": {t['via']}" if t["via"] else "") for t in rep.coderefs]


def _doc_lines(rep: Report) -> list[str]:
    by_file: dict[str, list[dict]] = {}
    for d in rep.docs:
        by_file.setdefault((f"{d['repo']}:" if d["repo"] else "") + d["path"], []).append(d)
    out = [f"[ ] docs to update ({len(rep.docs)} section(s) in {len(by_file)} file(s)):"]
    for path, ds in sorted(by_file.items()):
        rest = [d for d in ds if d["why"] != "changed here"]
        edited = "edited by this change" + ("; still " if rest else "") if len(rest) < len(ds) else ""
        more = f"; and {len(rest) - 6} more" if len(rest) > 6 else ""
        out.append(f"    {path}: {edited}"
                   + "; ".join(f"{d['title'].split(' § ', 1)[-1]} ({d['why']})" for d in rest[:6]) + more)
    return out


def _test_lines(rep: Report) -> list[str]:
    out = [f"[ ] tests to run ({len(rep.tests)}):"]
    out += [f"    {pytest_line(rep.tests)}"] if pytest_line(rep.tests) else []
    out += [f"    {t['path']} ({t['framework'] or 'test'})" for t in rep.tests
            if not (t.get("framework") == "pytest" and t["path"].endswith(".py"))]
    out += ["    CI: " + ", ".join(w["id"].split(":", 2)[-1] for w in rep.workflows)] if rep.workflows else []
    if rep.wider_tests:
        out.append(f"    and {len(rep.wider_tests)} wider test module(s) of these features, covering none of the "
                   "touched code (--json: wider_tests)")
    return out


def render(rep: Report) -> list[str]:
    out = _head_lines(rep)
    if not rep.files:
        return out
    out.append("checklist:")
    out.append(f"[ ] features whose status may change ({len(rep.features)}):")
    out += [f"    {f['id']} ({f['status']}): {f['how']}; {HINT.get(f['status'], 'check its status')}"
            + ("" if f["direct"] else " (through its part)") for f in rep.features]
    out += _doc_lines(rep)
    out.append(f"[ ] ADRs and specs to re-read ({len(rep.decisions) + len(rep.specs)}):")
    out += [f"    {d['id']} ({d['status']}): {d['title'][:90]} (via {d['via']})" for d in rep.decisions + rep.specs]
    out += _test_lines(rep)
    out.append(f"[ ] open items that deliver these features ({len(rep.items)}):")
    out += [f"    {i['id']} ({i['status']}): {i['title'][:90]}" for i in rep.items]
    if rep.ddrs:
        out.append(f"[ ] decisions pending on them ({len(rep.ddrs)}):")
        out += [f"    {d['id']} ({d['status']}): {d['title'][:90]}" for d in rep.ddrs]
    if rep.unmapped:
        shown = ", ".join(f"{s['path']}::{s['name']}" for s in rep.unmapped[:SHOWN])
        out.append(f"touched symbols no CodeRef names ({len(rep.unmapped)}; the graph does not see them): {shown}"
                   + (", ..." if len(rep.unmapped) > SHOWN else ""))
    out += [f"malformed CodeRef(s) left out ({len(rep.malformed)}): {', '.join(rep.malformed)}"] if rep.malformed else []
    return out + [f"store: {s}" for s in rep.stores]


def main(args, root: Path | None) -> int:
    try:
        rep = run(args, root)
    except (AuditError, projects.RepoError) as exc:
        print(f"brain impact: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(rep.as_dict(), ensure_ascii=False, indent=1, sort_keys=True))
    else:
        print("\n".join(render(rep)))
    return 0
