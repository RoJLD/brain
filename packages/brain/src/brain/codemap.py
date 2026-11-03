"""The code map (wi-brain-code-map; the code layer's design of 2026-10-17, §3.7): each active CodeRef of a project's
graph stores resolved to its node in the GitNexus code index (brain.codeindex), the bridge between the graph and the
code that ``brain impact --diff`` crosses.

A CodeRef ``code:<repo>:<path>[::<symbol>]`` is matched as the spec's correspondence says: <repo> is the indexed
repo's name (its folder, as brain index names it); the path, resolved as code-check resolves it (``src/<path>``, else
``<path>``), is a File node's ``filePath``; the symbol's last segment is a node's ``name``: for a top-level name a
``Class`` or ``Function`` no other definition encloses, else a ``Variable`` (an assignment); for ``A.b`` a member of
class ``A`` (its HAS_METHOD and HAS_PROPERTY edges). A symbol the index does not hold leaves the CodeRef unresolved,
its File named as the stand-in (an assignment GitNexus keeps no node for, or code gone since the indexed commit).
Each repo costs three or four Cypher queries through GitNexus's MCP tool, which opens the index read-only (a REST
read can leave a WAL behind, brain.codeindex): its files, the nodes of the files the CodeRefs name, their classes'
members, the count of its symbols.

``brain code-map [--project P] [--json]`` writes ``<BRAIN_HOME>/code-map/<project>.json`` (derived and machine-local:
rebuilt from the index, never written into a store) and prints per repo the indexed commit, the CodeRefs resolved and
the coverage, symbols with a CodeRef over all symbols (Class, Function, Method) and files with a CodeRef over the
indexed files, then each CodeRef that does not resolve and why. Exit 1 when GitNexus does not answer (nothing
written), 2 on a declaration error. The map is research_graph's code layer meeting the index, but research_graph never
calls a service (the core runs without one): the map lives with the code index, in this package.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import codeindex, graph, inventory, paths, projects, stacks

DIR = "code-map"
VERSION = 1
SYMBOLS = ("Class", "Function", "Method")         # the coverage's symbols
TOP = ("Class", "Function")                        # what a one-part symbol names first
VALUE = ("Variable", "Const", "Constant", "Property")   # an assignment
MEMBER_EDGES = ("HAS_METHOD", "HAS_PROPERTY")
_INT = re.compile(r"-?\d+")


@dataclass
class Ref:
    id: str
    repo: str
    symbol: str = ""      # the CodeRef's symbol ('' for a file)
    path: str = ""        # the file in the repo (GitNexus's filePath), '' when not found
    name: str = ""        # the node's name
    label: str = ""       # Class, Function, Method, File, Variable...
    node: str = ""        # GitNexus's node id
    start: int | None = None
    end: int | None = None
    store: str = ""
    why: str = ""         # '' when resolved; else why not (the File, when there is one, stands in)


@dataclass
class RepoMap:
    name: str
    indexed: str = ""     # the indexed commit
    branch: str = ""
    files: int = 0
    symbols: int = 0
    refs: int = 0
    resolved: int = 0
    files_with_ref: int = 0
    symbols_with_ref: int = 0
    why: str = ""         # '' when the index was read


@dataclass
class CodeMap:
    project: str
    generated_at: str = ""
    stores: list[str] = field(default_factory=list)
    repos: dict[str, RepoMap] = field(default_factory=dict)
    refs: dict[str, Ref] = field(default_factory=dict)

    def unresolved(self) -> list[Ref]:
        return [r for r in self.refs.values() if r.why]

    def as_dict(self) -> dict:
        return {"code_map": VERSION, "project": self.project, "generated_at": self.generated_at,
                "stores": self.stores, "repos": {k: asdict(v) for k, v in self.repos.items()},
                "refs": {k: asdict(v) for k, v in self.refs.items()}}


# --- GitNexus's answers ---

def lit(text: str) -> str:
    """A Cypher string literal."""
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _cell(text: str):
    text = text.strip()
    return None if text == "" else int(text) if _INT.fullmatch(text) else text


def table(text: str) -> tuple[list[dict], str]:
    """(the rows, '') of the MCP cypher tool's answer (a markdown table, or [] when nothing matched), else ([], why)."""
    head = text.split("\n\n---", 1)[0].strip()
    try:
        data = json.loads(head)
    except ValueError:
        return [], f"not a cypher answer: {stacks.useful_line(head) or 'empty'}"
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)], ""
    if not isinstance(data, dict):
        return [], "not a cypher answer"
    if data.get("error"):
        return [], stacks.useful_line(str(data["error"]))
    lines = str(data.get("markdown") or "").splitlines()
    if len(lines) < 2:
        return [], ""
    keys = [k.strip() for k in lines[0].strip().strip("|").split("|")]
    rows = []
    for ln in lines[2:]:
        cells = ln.strip()[1:-1].split(" | ") if ln.strip().startswith("|") else []
        if len(cells) == len(keys):
            rows.append({k: _cell(c) for k, c in zip(keys, cells, strict=True)})
    return rows, ""


def cypher(ix: codeindex.Indexer, repo: str, statement: str) -> tuple[list[dict], str]:
    """The rows of ``statement`` on ``repo``'s index through GitNexus's MCP cypher tool, else ([], why not)."""
    text, why = codeindex._mcp_tool(f"{ix.api}/api/mcp", "cypher", {"repo": repo, "query": statement})
    return ([], why) if why else table(text)


def in_list(values) -> str:
    return "[" + ", ".join(lit(v) for v in sorted(set(values))) + "]"


def nodes_of(ix: codeindex.Indexer, repo: str, files) -> tuple[list[dict], str]:
    """Every named node of ``files`` with its label and lines (BasicBlock rows of a --pdg index left out)."""
    return cypher(ix, repo, f"MATCH (n) WHERE n.filePath IN {in_list(files)} AND n.name IS NOT NULL "
                            "AND NOT n.id STARTS WITH 'BasicBlock:' RETURN n.id AS id, n.name AS name, "
                            "label(n) AS label, n.filePath AS path, n.startLine AS startLine, n.endLine AS endLine")


def members_of(ix: codeindex.Indexer, repo: str, files) -> tuple[dict[str, set[str]], str]:
    """{class node id: its methods' and properties' node ids} for the classes of ``files``."""
    rows, why = cypher(ix, repo, f"MATCH (c:Class)-[r:CodeRelation]->(m) WHERE c.filePath IN {in_list(files)} "
                                 f"AND r.type IN {in_list(MEMBER_EDGES)} RETURN c.id AS class, m.id AS member")
    out: dict[str, set[str]] = {}
    for r in rows:
        out.setdefault(str(r["class"]), set()).add(str(r["member"]))
    return out, why


# --- the correspondence (spec §3.7) ---

def file_of(path: str, files: set[str]) -> str:
    """The indexed file a CodeRef's path names: src/<path>, else <path> (code-check's order); '' when neither."""
    return next((p for p in (f"src/{path}", path) if p in files), "")


def _span(n: dict) -> tuple[int, int]:
    s = n.get("startLine") if isinstance(n.get("startLine"), int) else 0
    e = n.get("endLine") if isinstance(n.get("endLine"), int) else s
    return s, e


def _enclosed(n: dict, defs: list[dict]) -> bool:
    """``n`` lies inside another definition (a nested def, a method)."""
    s, e = _span(n)
    return any(o["id"] != n["id"] and _span(o)[0] <= s and e <= _span(o)[1] and _span(o) != (s, e) for o in defs)


def _member(mine: list[dict], named: list[dict], cls: str, members: dict[str, set[str]]) -> dict | None:
    """The first of ``named`` that a class ``cls`` of the file has (HAS_METHOD, HAS_PROPERTY)."""
    classes = [n["id"] for n in mine if n.get("label") == "Class" and n.get("name") == cls]
    return next((n for n in named if any(n["id"] in members.get(c, ()) for c in classes)), None)


def _top(mine: list[dict], named: list[dict], members: dict[str, set[str]]) -> dict | None:
    """The first of ``named`` defined at the top: a Class or a Function, else a Variable; never a member, never
    inside another definition."""
    defs = [n for n in mine if n.get("label") in SYMBOLS]
    inner = set().union(*members.values()) if members else set()
    free = [n for n in named if n["id"] not in inner and not _enclosed(n, defs)]
    return next((n for labels in (TOP, VALUE) for n in free if n.get("label") in labels), None)


def match(symbol: str, path: str, nodes: list[dict], members: dict[str, set[str]]) -> tuple[dict | None, str]:
    """(the index node a CodeRef names in the indexed file ``path``, '') or (None, why). ``nodes``: that file's nodes;
    ``members``: its classes' members."""
    mine = [n for n in nodes if n.get("path") == path]
    if not symbol:
        f = next((n for n in mine if n.get("label") == "File"), None)
        return (f, "") if f else (None, f"no File node for {path}")
    parts = symbol.split(".")
    named = sorted((n for n in mine if n.get("name") == parts[-1]), key=_span)
    if len(parts) > 1:
        hit = _member(mine, named, parts[-2], members)
        return (hit, "") if hit else (None, f"{symbol}: no member {parts[-1]} of a class {parts[-2]} in {path}")
    hit = _top(mine, named, members)
    return (hit, "") if hit else (None, f"{symbol}: not in the index of {path}")


# --- building the map ---

def active_refs(p: projects.Project) -> list[tuple[str, str]]:
    """(CodeRef id, its store relative to the root) of every active CodeRef of ``p``'s stores, sorted."""
    out = {}
    for store in p.stores:
        if not (store / "nodes").is_dir():
            continue
        rel = os.path.relpath(store, p.root).replace(os.sep, "/")
        for nid, (_, node) in graph.node_index(store).items():
            if node.get("type") == "CodeRef" and node.get("status", "active") == "active":
                out.setdefault(nid, rel)
    return sorted(out.items())


def _by_repo(cm: CodeMap, p: projects.Project, only: set[str] | None) -> dict[str, list[Ref]]:
    """The active CodeRefs of ``p`` into ``cm.refs``, grouped by repo (a malformed id is unresolved)."""
    by_repo: dict[str, list[Ref]] = {}
    for cid, store in active_refs(p):
        try:
            repo, _, symbol = inventory.parse_code_ref(cid)
        except ValueError as exc:
            cm.refs[cid] = Ref(cid, "", store=store, why=f"malformed: {exc}")
            continue
        if only is None or repo.lower() in only:
            by_repo.setdefault(repo, []).append(cm.refs.setdefault(cid, Ref(cid, repo, symbol, store=store)))
    return by_repo


def build(p: projects.Project, ix: codeindex.Indexer, entries: list, only: set[str] | None = None) -> CodeMap:
    """The code map of ``p``: ``entries`` is GitNexus's registry (/api/repos); ``only``: these repos (lowercase)."""
    cm = CodeMap(p.name, codeindex._now(), [os.path.relpath(s, p.root).replace(os.sep, "/") for s in p.stores])
    record = codeindex.read_record()
    for repo, refs in sorted(_by_repo(cm, p, only).items()):
        cm.repos[repo] = _map_repo(ix, codeindex._entry(entries, ix, repo), record.get(repo) or {}, repo, refs)
    return cm


def _map_repo(ix: codeindex.Indexer, e: dict | None, rec: dict, repo: str, refs: list[Ref]) -> RepoMap:
    """``refs`` resolved in ``repo``'s index (``e``: its registry entry, ``rec``: brain index's record of it)."""
    rm = RepoMap(repo, refs=len(refs))
    if e is None:
        rm.why = f"not indexed (brain index {repo})"
    else:
        rm.indexed, rm.branch = str(e.get("lastCommit") or ""), str(e.get("branch") or rec.get("branch") or "")
        rm.why = _resolve_repo(ix, rm, refs)
    for r in refs:
        r.why = r.why or ("" if r.node else rm.why)
    done = [r for r in refs if not r.why]
    rm.resolved, rm.files_with_ref = len(done), len({r.path for r in done})
    rm.symbols_with_ref = len({r.node for r in done if r.label in SYMBOLS})
    return rm


def _resolve_repo(ix: codeindex.Indexer, rm: RepoMap, refs: list[Ref]) -> str:
    """Resolve ``refs`` against ``rm``'s index and count its files and symbols: '' when the index answered."""
    files, why = _census(ix, rm)
    if why:
        return f"GitNexus: {why}"
    wanted = {r.id: file_of(inventory.parse_code_ref(r.id)[1], files) for r in refs}
    for r in refs:
        r.why = "" if wanted[r.id] else f"not in the index (GitNexus indexes no such file at {rm.indexed[:7] or '?'})"
    names = {f for f in wanted.values() if f}
    if not names:
        return ""
    nodes, why = nodes_of(ix, rm.name, names)
    members, why = members_of(ix, rm.name, names) if not why else ({}, why)
    for r in ([] if why else refs):
        if not r.why:
            _place(r, wanted[r.id], nodes, members)
    return f"GitNexus: {why}" if why else ""


def _census(ix: codeindex.Indexer, rm: RepoMap) -> tuple[set[str], str]:
    """The indexed files of ``rm``'s repo, its file and symbol counts into ``rm``; '' when the index answered."""
    rows, why = cypher(ix, rm.name, "MATCH (f:File) RETURN f.filePath AS path")
    files = {str(r["path"]) for r in rows if r.get("path")}
    counts, _ = cypher(ix, rm.name, f"MATCH (n) WHERE label(n) IN {in_list(SYMBOLS)} RETURN count(*) AS n") \
        if not why else ([], "")
    rm.files, rm.symbols = len(files), int(counts[0]["n"]) if counts and isinstance(counts[0].get("n"), int) else 0
    return files, why


def _place(r: Ref, path: str, nodes: list[dict], members: dict[str, set[str]]) -> None:
    """Resolve ``r`` in its indexed file ``path``; a symbol the index does not hold leaves it unresolved, its File
    standing in."""
    r.path = path
    hit, miss = match(r.symbol, path, nodes, members)
    if hit is None:
        hit, _ = match("", path, nodes, members)
        r.why = miss + (" (the File stands in)" if hit else "")
    if hit is not None:
        r.node, r.label, r.name = str(hit["id"]), str(hit.get("label") or ""), str(hit.get("name") or "")
        r.start, r.end = (hit.get("startLine"), hit.get("endLine")) if r.label != "File" else (None, None)


# --- the record ---

def map_file(project: str) -> Path:
    return paths.brain_home() / DIR / f"{project}.json"


def write(cm: CodeMap) -> Path:
    f = map_file(cm.project)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cm.as_dict(), indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, f)
    return f


def read(project: str) -> dict:
    """The last code map written for ``project``, {} when none."""
    try:
        data = json.loads(map_file(project).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) and data.get("code_map") == VERSION else {}


def _pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.1f} %)" if d else f"{n}/0"


def render(cm: CodeMap, where: Path | None = None) -> list[str]:
    out = [f"== code map {cm.project}: {len(cm.refs)} active CodeRef(s) in {', '.join(cm.stores) or 'no store'}"]
    for rm in cm.repos.values():
        if rm.why and not rm.indexed:
            out.append(f"{rm.name}: {rm.refs} CodeRef(s), none resolved: {rm.why}")
            continue
        at = f"{rm.branch}@{rm.indexed[:7]}" if rm.branch else rm.indexed[:7]
        out.append(f"{rm.name} ({at}): {rm.resolved}/{rm.refs} CodeRef(s) resolved; coverage: symbols "
                   f"{_pct(rm.symbols_with_ref, rm.symbols)}, files {_pct(rm.files_with_ref, rm.files)}"
                   + (f"; {rm.why}" if rm.why else ""))
    bad = [r for r in cm.unresolved() if not (cm.repos.get(r.repo) and r.why == cm.repos[r.repo].why)]
    if bad:
        out.append(f"unresolved ({len(bad)}):")
        out += [f"  {r.id}: {r.why}" for r in bad]
    if where:
        out.append(f"written: {where.as_posix()}")
    return out


def main(p: projects.Project, root: Path | None = None, as_json: bool = False, out=None) -> int:
    """``brain code-map``: build, write and print the map of ``p``."""
    out = out or sys.stdout
    try:
        ix, _ = codeindex.load(root)
    except codeindex.CodeIndexError as exc:
        print(f"brain code-map: {exc}", file=sys.stderr)
        return 2
    if ix is None:
        print("brain code-map: no stack declares index: (the GitNexus stack): nothing to resolve against",
              file=sys.stderr)
        return 2
    entries = codeindex.registry(ix)
    if entries is None:
        print(f"brain code-map: {ix.stack.name} does not answer at {ix.api}; brain up {ix.stack.name} starts it",
              file=out)
        return 1
    cm = build(p, ix, entries)
    where = write(cm)
    if as_json:
        print(json.dumps(cm.as_dict(), indent=1, ensure_ascii=False, sort_keys=True), file=out)
    else:
        print("\n".join(render(cm, where)), file=out)
    return 0
