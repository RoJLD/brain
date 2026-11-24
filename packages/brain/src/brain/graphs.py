"""The registry of the graphs: ``brain graphs [--project P | --all] [--json]`` (wi-brain-graph-registry; spec decision
premises, section 8.2).

No command listed every graph a project has with its state: ``research_graph layers`` says one store's layers,
``brain projects`` its stores, overlays and code index, ``brain index`` the code index's state, ``brain docgraph join``
the documentation graphs read from other projects. This module assembles what they already know, at zero token, and
writes nothing: no store, no record, no cache.

For each project in scope it lists:

- **stores** (kind ``intention``): each graph store of the project, then each overlay (another repo's store read with
  the first, ``read_only``). A store's nodes are counted by layer: a node type is in the layer the store's own
  ``schema.yaml`` ``layers:`` names, else in the catalogue's layer that holds it (research_graph layers), else in no
  layer (``name`` null). An edge counts in the catalogue's layer that declares its type when the store has that
  layer, else in its source node's layer. Each layer says its version (as the schema's ``templates:`` recorded it;
  ``null`` when not recorded), the catalogue's version, whether its nodes are written by commands or generated
  (files named ``_generated_*``, by ``brain sync``) or both, the files that hold them, their freshness (the last
  commit of those files and whether any has uncommitted changes), its query and impact entries and what reads it. The
  catalogue's layers the store does not hold are ``planned``, each with the command that adds it.
- **code index** (kind ``federated``): each repo the project declares under ``code_index:``, once per backend this
  machine has or that recorded it (GitNexus, codebase-memory-mcp, xerj), with its state against the branch head
  (OK, STALE, NOT INDEXED, ERROR), as ``brain index`` says it, from the records and git alone: no service is called.
- **docgraph** (kind ``federated``): the documentation graphs under the project's root ``docgraph/`` (a read
  project's pinned copy goes under that project with ``--all``), with their node and edge counts and the commit they
  describe.
- **sources**: the files a layer is generated from or a command reads beside the graph (decision logs, journals,
  records, ledgers, stacks, schedules, memory notes, the neutral source of rules and procedures, config.json), each
  with whether it exists, how many files it holds and its last commit.

The ``--json`` keys are a public contract (``v`` 1, keys only added; docs/graphs.md): ``v, scope, projects``; each
project ``name, title, root, access, found, stores, code_index, docgraph, sources``; each store ``path, kind,
read_only, error, nodes, edges, layers, planned``; each layer ``name, catalogue, version, catalogue_version, title,
mode, generator, files, types, nodes, edges, edge_count, freshness, query, impact, read_by``; each code index row
``repo, backend, kind, state, why, query, impact, read_by``; each docgraph row ``name, path, kind, read_only, ok,
error, ref, nodes, edges``; each source ``name, kind, paths, exists, files, freshness, read_by``. A reader keeps a key
it does not know and shows a layer, kind, mode or state it does not know as it is.
"""

from __future__ import annotations

import functools
import subprocess
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml
from research_graph import layers as rg_layers
from research_graph import yamlio

from . import cbm, codebackends, codeindex, docjoin, neutral, projects, xerj

V = 1
GENERATED = "_generated_"   # a node or edge file brain sync regenerates
GIT_TIMEOUT = 30
WORKERS = 8   # git calls side by side: each costs a process start, most of the list's time
UNREADABLE = (OSError, ValueError, yaml.YAMLError)   # a YAML file that cannot be read (UnicodeDecodeError: ValueError)
STORE_IMPACT = ("research_graph impact <id>",)
CODE_IMPACT = ("brain impact --diff",)

# The engine's commands that read a catalogue layer, beside its own commands (the layer file's ``commands``). A
# consumer that is not built yet (brain context, the code-question packet, the cockpit's Graphs tab) is added here
# the day it ships: the list says what reads a layer now.
READ_BY = {
    "work": ("brain next", "brain forecast", "brain tui (plan, frontier, milestones)", "brain mcp (brain_items)"),
    "decisions": ("brain adr show", "brain adr revisit", "brain mcp (brain_adr_show)"),
    "records": ("brain decision pending", "brain sessions", "brain tui (sessions, queue)"),
    "features": ("brain features list|search|show", "brain impact --diff"),
    "code": ("brain code-map", "brain impact --diff"),
    "docs_tests": ("brain audit", "brain docgraph emit", "brain impact --diff"),
    "lessons": ("brain lesson", "brain retro"),
}
CODE_QUERY = {"gitnexus": ("brain code-map", "GitNexus's MCP query"), "cbm": ("brain impact --diff",),
              "xerj": ("brain index --backend xerj",)}
CODE_READERS = (("code-map", "brain code-map"), ("impact", "brain impact --diff"),
                ("health", "brain health code-index"))
DOCGRAPH_READ = ("brain docgraph join",)


# --- git, read only -------------------------------------------------------------------------------------------------

def _git(folder: Path, *args: str) -> str | None:
    """git's output in ``folder``, None when git fails, times out or ``folder`` is not in a checkout. Never a write:
    ``--no-optional-locks`` keeps git status from refreshing the index (and taking index.lock) under a concurrent
    commit or pull."""
    try:
        done = subprocess.run(["git", "--no-optional-locks", "-C", str(folder), *args], capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def _pmap(fn, items) -> list:
    """``fn`` over ``items`` in threads, results in order (each one mostly waits on git)."""
    items = list(items)
    if len(items) < 2:
        return [fn(i) for i in items]
    with ThreadPoolExecutor(max_workers=min(WORKERS, len(items))) as pool:
        return list(pool.map(fn, items))


@functools.lru_cache(maxsize=None)
def _top(folder: str) -> tuple[str, str] | None:
    """(the checkout's top level, ``folder``'s prefix in it) or None when ``folder`` is not in a checkout."""
    out = _git(Path(folder), "rev-parse", "--show-toplevel", "--show-prefix")
    if out is None:
        return None
    top, _, prefix = out.partition("\n")
    return top.strip(), prefix.strip()


@functools.lru_cache(maxsize=None)
def _dirty(top: str) -> frozenset[str]:
    """The paths of the checkout at ``top`` with uncommitted changes (modified, deleted, staged, untracked and not
    ignored), relative to it."""
    out = _git(Path(top), "status", "--porcelain=v1", "-z", "--untracked-files=all") or ""
    found, parts = set(), iter(out.split("\0"))
    for entry in parts:
        if len(entry) > 3:
            found.add(entry[3:])
            if entry[0] in "RC":
                found.add(next(parts, ""))   # a rename's or copy's original path follows: changed too
    return frozenset(found)


def _clear() -> None:
    """A run's git caches dropped: each run reads the checkouts as they are."""
    _top.cache_clear()
    _dirty.cache_clear()


def freshness(folder: Path, names: list[str]) -> dict | None:
    """``{commit, day, uncommitted}`` of the files ``names`` (relative to ``folder``): the last commit that touched
    them, its day, and whether one of them has uncommitted changes. None when ``folder`` is not in a git checkout."""
    where = _top(str(folder))
    if where is None:
        return None
    out = _git(folder, "log", "-1", "--format=%h %cs", "--", *names) if names else ""
    if out is None:
        return None
    commit, _, day = out.strip().partition(" ")
    dirty, prefix = _dirty(where[0]), where[1]
    mine = [(prefix + n).rstrip("/") for n in names]
    return {"commit": commit or None, "day": day or None,
            "uncommitted": any(m in dirty or any(d.startswith(m + "/") for d in dirty) for m in mine)}


# --- a store's layers ---------------------------------------------------------------------------------------------

def _yaml_list(path: Path) -> list | None:
    """A node or edge file's entries; None when it does not parse (named on the store's row; brain check says why)."""
    try:
        data = yamlio.load(path)
    except UNREADABLE:
        return None
    return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []


def _schema(store: Path) -> tuple[dict, str]:
    try:
        data = yamlio.load(store / "schema.yaml")
    except UNREADABLE as exc:   # shown on the store's row
        return {}, f"schema.yaml does not parse: {(str(exc).splitlines() or [type(exc).__name__])[0]}"
    return (data, "") if isinstance(data, dict) else ({}, "schema.yaml is not a mapping")


def _type_layers(schema: dict, cat: dict) -> dict[str, str]:
    """node type -> its layer: the store's own ``layers:``, then the catalogue's."""
    out = {t: la.name for la in cat.values() for t in la.node_types}
    own = schema.get("layers") if isinstance(schema.get("layers"), dict) else {}
    for name, types in own.items():
        for t in types if isinstance(types, list) else []:
            out[str(t)] = str(name)
    return out


def _edge_layers(cat: dict) -> dict[str, list[str]]:
    """edge type -> the catalogue layers that declare it (several may: part_of, implemented_by)."""
    out: dict[str, list[str]] = {}
    for la in cat.values():
        for et in la.edges:
            out.setdefault(et, []).append(la.name)
    return out


def _version(value):
    """A recorded version as the contract carries it: an integer, else its text (YAML may read a date), else None."""
    if value is None or (isinstance(value, int) and not isinstance(value, bool)):
        return value
    return str(value)


def _new_layer(name: str | None, cat: dict, recorded: dict) -> dict:
    la = cat.get(name) if name else None
    data = la.data if la else {}
    return {"name": name, "catalogue": la is not None, "version": _version(recorded.get(name)),
            "catalogue_version": la.version if la else None, "title": la.title if la else "",
            "mode": "", "generator": "", "files": [], "types": Counter(), "nodes": 0, "edges": Counter(),
            "edge_count": 0, "freshness": None, "query": list(data.get("commands") or []),
            "impact": list(STORE_IMPACT + (CODE_IMPACT if name == "code" else ())),
            "read_by": list(READ_BY.get(name or "", ())), "_generated": set(),
            "_generator": str(data.get("generator") or "")}


def _mode(generated: set[bool]) -> str:
    return "mixed" if len(generated) > 1 else "generated" if True in generated else "written"


class _Tally:
    """A store's layers as its files are read: each node and edge counted in its layer, each file in the layers it
    feeds."""

    def __init__(self, schema: dict, cat: dict, recorded: dict):
        self.cat, self.recorded = cat, recorded
        self.by_type, self.by_edge = _type_layers(schema, cat), _edge_layers(cat)
        self.found: dict[str | None, dict] = {}
        self.node_layer: dict[str, str | None] = {}
        self.unreadable: list[str] = []

    def _layer(self, name: str | None, rel: str) -> dict:
        la = self.found.setdefault(name, _new_layer(name, self.cat, self.recorded))
        if rel not in la["files"]:
            la["files"].append(rel)
            la["_generated"].add(Path(rel).name.startswith(GENERATED))
        return la

    def node(self, n: dict, rel: str) -> None:
        name = self.by_type.get(str(n.get("type")))
        la = self._layer(name, rel)
        la["types"][str(n.get("type"))] += 1
        la["nodes"] += 1
        self.node_layer[str(n.get("id"))] = name

    def edge_layer(self, et: str, src: str | None, dst: str | None) -> str | None:
        """An edge's layer: among the catalogue's layers that declare its type, its source node's, else its target
        node's, else the first the store holds; a type no held layer declares goes to its source node's layer."""
        declared = self.by_edge.get(et, [])
        for end in (src, dst):
            if end is not None and end in declared:
                return end
        return next((name for name in declared if name in self.found), src)

    def edge(self, e: dict, rel: str) -> None:
        et = str(e.get("type"))
        name = self.edge_layer(et, self.node_layer.get(str(e.get("from"))), self.node_layer.get(str(e.get("to"))))
        la = self._layer(name, rel)
        la["edges"][et] += 1
        la["edge_count"] += 1


def _finish(la: dict) -> dict:
    """A layer's mode, generator and sorted counts, its working keys dropped."""
    la["mode"] = _mode(la.pop("_generated"))
    generator = la.pop("_generator")
    la["generator"] = (generator or "brain sync") if la["mode"] != "written" else ""
    la["types"], la["edges"] = dict(sorted(la["types"].items())), dict(sorted(la["edges"].items()))
    return la


def _edge_files(store: Path) -> list[Path]:
    folder = store / "edges"
    return [f for f in [store / "edges.yaml"] + (sorted(folder.glob("*.yaml")) if folder.is_dir() else [])
            if f.is_file()]


def store_entry(store: Path, base: Path, *, read_only: bool = False) -> dict:
    """One store as the registry lists it (see the module's docstring); ``base`` is what its path is relative to."""
    label = _rel(store, base)
    entry = {"path": label, "kind": "intention", "read_only": read_only, "error": "", "nodes": 0, "edges": 0,
             "layers": [], "planned": []}
    if not (store / "schema.yaml").is_file() or not (store / "nodes").is_dir():
        entry["error"] = "no schema.yaml or no nodes/ (not a graph store)"
        return entry
    schema, error = _schema(store)
    cat = rg_layers.catalogue()
    recorded = _recorded(schema)
    tally = _Tally(schema, cat, recorded)
    found = _read(store, tally)
    for la, fresh in zip(found, _pmap(lambda la: freshness(store, la["files"]), found), strict=True):
        la["freshness"] = fresh
    if tally.unreadable:
        error = "; ".join(filter(None, [error, f"left out, not parsed: {', '.join(tally.unreadable)}"]))
    own = schema.get("layers") if isinstance(schema.get("layers"), dict) else {}
    held = {la["name"] for la in found} | set(recorded) | {str(n) for n in own}
    # an overlay is another repo's store, read only: nothing is proposed to add to it
    planned = [] if read_only else [_planned(la, store) for la in cat.values() if la.name not in held]
    entry.update(error=error, layers=sorted(found, key=lambda la: (la["name"] is None, la["name"] or "")),
                 nodes=sum(la["nodes"] for la in found), edges=sum(la["edge_count"] for la in found),
                 planned=planned)
    return entry


def _recorded(schema: dict) -> dict:
    """{layer: version} as the schema's ``templates:`` recorded them."""
    templates = schema.get("templates") if isinstance(schema.get("templates"), list) else []
    return {str(t.get("layer")): t.get("version") for t in templates if isinstance(t, dict)}


def _read(store: Path, tally: _Tally) -> list[dict]:
    """The store's node files, then its edge files, counted into ``tally``: its layers, finished. A file that does
    not parse is left out and named in ``tally.unreadable``."""
    for nf in sorted((store / "nodes").glob("*.yaml")):
        for n in _entries(nf, f"nodes/{nf.name}", tally):
            tally.node(n, f"nodes/{nf.name}")
    for ef in _edge_files(store):
        rel = ef.relative_to(store).as_posix()
        for e in _entries(ef, rel, tally):
            tally.edge(e, rel)
    return [_finish(la) for la in tally.found.values()]


def _entries(path: Path, rel: str, tally: _Tally) -> list:
    got = _yaml_list(path)
    if got is None:
        tally.unreadable.append(rel)
    return got or []


def _planned(la, store: Path) -> dict:
    """A catalogue layer the store lacks, with the command that adds it (the store's full path: it runs anywhere)."""
    return {"name": la.name, "catalogue_version": la.version, "title": la.title,
            "add": f"research_graph --store {store.resolve().as_posix()} layers add {la.name}"}


def _rel(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


# --- federated graphs -----------------------------------------------------------------------------------------------

def _code_row(repo: str, backend: str, state: str, why: str) -> dict:
    serves = codebackends.BACKENDS[backend].serves if backend in codebackends.BACKENDS else frozenset()
    return {"repo": repo, "backend": backend, "kind": "federated", "state": state, "why": why,
            "query": list(CODE_QUERY.get(backend, ())), "impact": list(CODE_IMPACT) if "impact" in serves else [],
            "read_by": [cmd for purpose, cmd in CODE_READERS if purpose in serves]}


def code_index(project: projects.Project, root: Path) -> list[dict]:
    """The project's ``code_index:`` repos, once per backend this machine has or that recorded the repo, with their
    state from the records and git alone (no service called)."""
    if not project.code_index:
        return []
    try:
        ix, repos = codeindex.load(root, opt_in=True)
    except codeindex.CodeIndexError as exc:   # the declarations are read for every project at once (brain index)
        return [_code_row("", "", "ERROR", f"the registry's code_index declarations: {exc}")]
    mine = codeindex.of_project(repos, project.name)
    records = {"gitnexus": codeindex.read_record(), "cbm": cbm.read_record(), "xerj": xerj.read_record()}
    have = {"gitnexus": ix is not None, "cbm": cbm.installed(), "xerj": xerj.installed()}
    wanted = [(r, b, records[b].get(r.name)) for r in mine.values() for b in codebackends.BACKENDS
              if records[b].get(r.name) or (have[b] and not codebackends.BACKENDS[b].opt_in)]

    def row(item) -> dict:
        r, backend, rec = item
        if backend == "gitnexus":
            s = codeindex.state(ix, r, rec, None)   # entries None: GitNexus's own registry is not asked
            state, why = s.state, s.why
        elif backend == "cbm":
            state, why = codebackends.cbm_state(r, rec)
        else:
            state, why = codebackends.xerj_state(r, rec)
        return _code_row(r.name, backend, state, why)
    return _pmap(row, wanted)


def _docgraph_row(s: docjoin.Source) -> dict:
    doc = s.doc or {}

    def count(key: str) -> int:   # a document whose nodes or edges is not a list counts none (its error says why)
        value = doc.get(key)
        return sum(1 for x in value if isinstance(x, dict)) if isinstance(value, list) else 0
    return {"name": s.name, "path": s.path, "kind": "federated", "read_only": s.read_only, "ok": s.ok,
            "error": s.errors[0] if s.errors else "", "ref": s.ref or None, "nodes": count("nodes"),
            "edges": count("edges"), "read_by": list(DOCGRAPH_READ)}


def docgraph_documents(root: Path) -> list[dict]:
    """The documentation graphs under ``root``'s ``docgraph/`` folder (brain.docjoin), each read and validated."""
    if not (root / docjoin.DIR).is_dir():
        return []
    try:
        return [_docgraph_row(s) for s in docjoin.sources(root)]
    except (OSError, ValueError) as exc:
        return [{"name": "", "path": docjoin.DIR, "kind": "federated", "read_only": False, "ok": False,
                 "error": str(exc), "ref": None, "nodes": 0, "edges": 0, "read_by": list(DOCGRAPH_READ)}]


# --- sources --------------------------------------------------------------------------------------------------------

def _declared(value, root: Path) -> list[Path]:
    """A registry key that is a YAML file relative to the root (a string), else nothing (an inline mapping)."""
    return [projects._resolve_root(value, root)] if isinstance(value, str) and value else []


def _source(spec: tuple) -> dict:
    name, root, paths, read_by, inline = spec
    existing = [p for p in paths if p.exists()]
    files = sum(sum(1 for f in p.rglob("*") if f.is_file()) if p.is_dir() else 1 for p in existing)
    inside = [n for n in (_rel(p, root) for p in existing) if not Path(n).is_absolute()]   # git -C root reads these
    return {"name": name, "kind": "inline" if inline else "files", "paths": [_rel(p, root) for p in paths],
            "exists": bool(existing) or inline, "files": files,
            "freshness": freshness(root, inside) if inside and root.is_dir() else None, "read_by": list(read_by)}


def sources(project: projects.Project, owns_root: bool) -> list[dict]:
    """The files the project's layers are generated from or its commands read beside the graph: those its entry
    declares, then, for the project that owns its root, the root's records, memory notes, neutral source (rules,
    procedures, MCP servers) and config.json, when present."""
    root = project.root
    specs = []
    for name, paths, read_by in (("decisions", project.decision_logs, ("brain sync", "brain adr")),
                                 ("journals", project.journals, ("brain journal", "brain resume")),
                                 ("ledgers", list(project.ledgers.values()), ("brain status",))):
        if paths:
            specs.append((name, root, list(paths), read_by, False))
    for key, read_by in (("stacks", ("brain up", "brain down", "brain health")), ("schedules", ("brain schedule",))):
        value = getattr(project, key)
        if value:
            specs.append((key, root, _declared(value, root), read_by, not isinstance(value, str)))
    if owns_root:
        optional = (("records", root / "records", ("brain sync", "brain decision", "brain sessions")),
                    ("memory", root / "memory", ("brain memory",)),
                    ("neutral", neutral.folder(root), ("brain render", "brain rules", "brain mcp")),
                    ("config", root / "config.json", ("brain config", "brain classes")))
        specs += [(name, root, [path], read_by, False) for name, path, read_by in optional if path.exists()]
    return _pmap(_source, specs)


# --- the registry -------------------------------------------------------------------------------------------------

def project_entry(project: projects.Project, root: Path, read_only_docs: set[str]) -> dict:
    """One project's graphs. ``read_only_docs``: the docgraph documents left to their read project's entry."""
    owns_root = not project.shares_root_with
    # the files are read in this thread (the YAML memo is not shared across threads); only git runs side by side
    stores = [store_entry(s, project.root) for s in projects.stores_of(project)]
    stores += [store_entry(o, project.root, read_only=True) for o in project.overlays]
    docs = [d for d in docgraph_documents(project.root) if d["name"] not in read_only_docs] if owns_root else []
    return {"name": project.name, "title": project.title, "root": project.root.as_posix(), "access": "write",
            "found": project.root.is_dir(), "stores": stores, "code_index": code_index(project, root),
            "docgraph": docs, "sources": sources(project, owns_root)}


def read_only_entry(r: projects.ReadOnly, docs: list[dict]) -> dict:
    """A project the brain only reads: no store, its pinned documentation graph when one is kept."""
    return {"name": r.name, "title": r.title, "root": None, "access": "read", "found": bool(docs), "stores": [],
            "code_index": [], "docgraph": docs, "sources": []}


def registry(root: Path, scope: list[projects.Project], every: bool) -> dict:
    """The registry of ``scope``'s graphs; ``every`` (--all) adds the projects the brain only reads."""
    _clear()
    read_only = projects.readonly(root) if every else {}
    pinned: dict[str, list[dict]] = {}
    if every:
        for d in docgraph_documents(root):
            if d["name"] in read_only:
                pinned.setdefault(d["name"], []).append(d)
    out = [project_entry(p, root, set(read_only)) for p in scope]
    out += [read_only_entry(r, pinned.get(name, [])) for name, r in read_only.items()]
    return {"v": V, "scope": "all" if every else "project", "projects": out}


# --- the text --------------------------------------------------------------------------------------------------

def _fresh(f: dict | None) -> str:
    if not f:
        return "not in git"
    day = f"{f['day']} {f['commit']}" if f.get("commit") else "never committed"
    return day + (", uncommitted changes" if f.get("uncommitted") else "")


def _layer_line(la: dict) -> str:
    name = la["name"] or "(no layer)"
    version = f" v{la['version']}" if la["version"] is not None else (
        f" (catalogue v{la['catalogue_version']}, not recorded)" if la["catalogue"] else " (the store's own)")
    types = ", ".join(f"{t} {n}" for t, n in la["types"].items()) or "no node"
    return (f"    {name}{version}: {la['mode']}{', by ' + la['generator'] if la['generator'] else ''}; {types}; "
            f"{la['edge_count']} edge(s); {_fresh(la['freshness'])}")


def _store_lines(s: dict) -> list[str]:
    ro = ", read only (an overlay)" if s["read_only"] else ""
    out = [f"  store {s['path']}{ro}: {s['nodes']} node(s), {s['edges']} edge(s)"
           + (f"; {_one(s['error'])}" if s["error"] else "")]
    out += [_layer_line(la) for la in s["layers"]]
    if s["planned"]:
        add = s["planned"][0]["add"].rsplit(" ", 1)[0] + " NAME"
        out.append(f"    in the catalogue, not in this store: {', '.join(p['name'] for p in s['planned'])} ({add})")
    return out


def _one(text) -> str:
    """A value on one line of the text: its newlines and runs of spaces made one space (the JSON keeps it as is)."""
    return " ".join(str(text).split())


def _code_line(c: dict) -> str:
    return f"  code index {c['repo'] or '-'} ({c['backend'] or 'declaration'}): {c['state']}, {_one(c['why'])}"


def _docgraph_line(d: dict) -> str:
    what = f"{d['nodes']} node(s), {d['edges']} edge(s)" + (f", at {d['ref'][:12]}" if d["ref"] else "")
    return f"  docgraph {d['name'] or d['path']} ({d['path']}): " + (what if d["ok"] else _one(d["error"]))


def _source_line(src: dict) -> str:
    where = ", ".join(src["paths"]) or "inline in the registry"
    if not src["exists"]:
        state = "missing"
    elif src["kind"] == "inline" and not src["paths"]:
        state = "inline"
    else:
        state = f"{src['files']} file(s), {_fresh(src['freshness'])}"
    return f"  source {src['name']}: {where} ({state}); read by {', '.join(src['read_by'])}"


def _project_lines(p: dict) -> list[str]:
    read = p["access"] == "read"
    head = p["name"] + (" (read only)" if read else "") + (f": {_one(p['title'])}" if p["title"] else "")
    out = [head + ("" if p["found"] or read else " (not found on this machine)")]
    for s in p["stores"]:
        out += _store_lines(s)
    out += [_code_line(c) for c in p["code_index"]] + [_docgraph_line(d) for d in p["docgraph"]]
    out += [_source_line(src) for src in p["sources"]]
    if not (p["stores"] or p["code_index"] or p["docgraph"]):
        out.append("  no pinned documentation graph (brain docgraph pin)" if read else "  no graph")
    return out


def lines(reg: dict) -> list[str]:
    """The registry as text, one block per project."""
    return [line for p in reg["projects"] for line in _project_lines(p)]
