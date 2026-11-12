"""Reading several docgraph/v1 documents as one graph (wi-brain-docgraph-read; docs/docgraph.md, « Reading several
documents »).

A brain reads the documentation graphs of the projects it only reads (``access: read`` in the registry) without ever
writing to them, joins them with its own and with the documents it keeps for itself, and runs the named checks again
across the joined graph, where an edge of one document may reach a node of another.

- **Pinned copies.** ``brain docgraph pin <project> --from <a clone> --ref <commit|tag> --file <path>`` reads the
  project's document from a local clone with ``git show <ref>:<path>`` (never a checkout, never a write there),
  validates it (:func:`brain.docgraph.validate`) and writes it to ``docgraph/<project>.json`` under the brain's root,
  with one key added by the reader: ``pinned`` (``ref``: the commit it was read at, ``file``, ``at``). The registry
  entry is unchanged (title, access, parent, classes): the copy is committed and reviewed like any change, and every
  machine reads it offline. A read project's document without ``pinned`` is refused.
- **The brain's own documents.** Any other ``docgraph/<name>.json`` is a document the brain keeps for itself (what
  stays private: an import of documents kept elsewhere, coded decisions, review findings); its edges may name another
  document's node by its joined id.
- **Namespaces.** Every node id becomes ``<type>:<namespace>/<native id>`` (``item:example/25``), the namespace being
  the project's name (the file's stem); a node's ``phase`` becomes ``<namespace>/<phase>``. An edge end or a finding's
  subject written ``<type>:@<namespace>/<native id>`` (``criterion:@example/S2-13`` in the brain's own document) names
  another document's node; the ``@`` keeps it apart from a native id that merely starts like a namespace. The joined
  graph is itself a docgraph/v1 document: ids stay prefixed by their type and unique.
- **The checks, run again** (:data:`RUN`) over the joined graph, each finding marked ``by: join``, which replaces the
  producers' findings of the same checks (an edge of another document may settle them), doc.stale apart: a producer's
  is kept beside the join's (its history knows what dates cannot show). The producers' findings of the other checks
  are kept, marked ``by: <namespace>``. The checks that need what a document does not carry (a decision's text and
  history, its numbering, the citations of a reported node, the register of needs) are listed as not run, unless a
  producer reported them.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import docgraph, projects

DIR = "docgraph"         # under the brain's root: the pinned copies and the brain's own documents
PINNED = "pinned"        # the one key the reader adds to a pinned copy
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
GIT_TIMEOUT = 60
EXEMPT_KINDS = ("generated", "dated-spec")
RUN = ("criterion.no-item", "item.no-criterion", "test.uncarried", "test.carried-twice", "threat.untested",
       "depends.cross-phase", "phase.review-incomplete", "cycle", "proposed.cited-as-decided", "doc.stale",
       "decision.target-unreferenced")
NEED_CLOSED = ("done", "closed", "dropped", "superseded")
CYCLE_TYPES = ("depends_on", "part_of", "supersedes")
PRODUCER_KEPT = ("doc.stale",)   # a check the join runs whose producers' findings it keeps beside its own
REF = "@"                        # <type>:@<namespace>/<native id>: another document's node


@dataclass
class Source:
    """A document of the join: its namespace, where it was read, and what its validation said."""
    name: str
    path: str                                   # relative to the root, or "(emitted)" for the brain's own graph
    doc: dict | None = None
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    read_only: bool = False                     # an access: read project's pinned copy
    emitted: bool = False                       # the brain's own documentation graph, emitted at the call

    @property
    def ok(self) -> bool:
        return self.doc is not None and not self.errors

    @property
    def ref(self) -> str:
        """The commit the document describes: the pin's, else its producer's ``generated.ref``."""
        doc = self.doc or {}
        pin = doc.get(PINNED) if isinstance(doc.get(PINNED), dict) else {}
        gen = doc.get("generated") if isinstance(doc.get("generated"), dict) else {}
        return str(pin.get("ref") or gen.get("ref") or "")


# --- pinning ----------------------------------------------------------------------------------------------------------

def _git(checkout: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(checkout), *args], capture_output=True, timeout=GIT_TIMEOUT)


def _refused(root: Path, project: str, checkout: Path, ref: str, file: str) -> str:
    """Why a pin is refused before git runs: "" when it may run."""
    if project not in projects.readonly(root):
        return f"{project!r} is not an access: read project of the registry (brain projects lists them)"
    if not NAME_RE.match(project):
        return f"{project!r}: a pinned copy is named after its project: lower-case letters, digits, - and _"
    if not ref or not file or ref.startswith("-") or file.startswith("-"):
        return f"--ref {ref!r} and --file {file!r}: a commit or a tag, and a path in the repository"
    if not Path(checkout).is_dir():
        return f"{checkout}: no such folder (give a local clone of {project})"
    return ""


def _read_at(checkout: Path, ref: str, file: str) -> tuple[str, dict | None, str]:
    """(the commit ``ref`` names, the JSON document at ``file`` there, the error that stopped the read or "")."""
    try:
        rev = _git(checkout, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        sha = rev.stdout.decode("ascii", "replace").strip()
        if rev.returncode or not sha:
            return "", None, f"{checkout}: {ref!r} is not a commit of this clone (git fetch it first)"
        shown = _git(checkout, "show", f"{sha}:{file}")
    except (OSError, subprocess.SubprocessError) as exc:
        return "", None, f"{checkout}: git could not read it ({exc})"
    if shown.returncode:
        return sha, None, f"{checkout}: no {file} at {sha[:12]}"
    try:
        return sha, json.loads(shown.stdout.decode("utf-8-sig")), ""
    except (ValueError, RecursionError) as exc:
        return sha, None, f"{file} at {sha[:12]}: not a JSON document ({exc})"


def pin(root: Path, project: str, checkout: Path, ref: str, file: str,
        now: datetime | None = None) -> tuple[Path | None, list[str], list[str]]:
    """Read ``file`` at ``ref`` from the clone ``checkout`` of the read project ``project`` and write its pinned copy
    to ``<root>/docgraph/<project>.json``. (the copy's path or None, errors, notes): nothing is written on an error.
    Only git's read commands run in the clone (rev-parse, show): its working tree and refs are never touched."""
    file = file.replace("\\", "/").lstrip("/")   # git's <rev>:<path> takes forward slashes only
    refused = _refused(root, project, checkout, ref, file)
    if refused:
        return None, [refused], []
    sha, doc, error = _read_at(checkout, ref, file)
    if error:
        return None, [error], []
    where = f"{project}@{sha[:12]}:{file}"
    errors, notes = docgraph.validate(doc, where=where)
    if errors:
        return None, errors, notes
    if PINNED in doc:
        notes.append(f"{where}: its own {PINNED!r} key is replaced by the pin")
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc[PINNED] = {"ref": sha, "file": file, "at": stamp}
    out = Path(root) / DIR / f"{project}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return out, [], notes


# --- reading ----------------------------------------------------------------------------------------------------------

def sources(root: Path, own: tuple[str, dict] | None = None, own_name: str = "") -> list[Source]:
    """The documents of the join: the brain's own graph (``own``: its namespace and its emitted document), then every
    ``docgraph/*.json`` under ``root``, each validated. A read project's copy without its pin, a file whose name is
    not a namespace, or one named as the brain's own project (``own``'s, else ``own_name``): errors, the document
    left out of the join."""
    read_only = set(projects.readonly(root))
    out: list[Source] = []
    if own:
        name, doc = own
        own_name = name
        errors, notes = docgraph.validate(doc, where=f"{name} (emitted)")
        out.append(Source(name, "(emitted)", doc, errors, notes, emitted=True))
    folder = Path(root) / DIR
    for f in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        src = Source(f.stem, f"{DIR}/{f.name}", read_only=f.stem in read_only)
        out.append(src)
        if not NAME_RE.match(f.stem):
            src.errors.append(f"{src.path}: its name is its namespace: lower-case letters, digits, - and _")
            continue
        if own_name and f.stem == own_name:
            src.errors.append(f"{src.path}: {f.stem!r} is the brain's own project, whose graph is emitted")
            continue
        try:
            src.doc = docgraph.load(f)
        except docgraph.DocgraphError as exc:
            src.errors.append(str(exc))
            continue
        src.errors, src.notes = docgraph.validate(src.doc, where=src.path)
        pin_ = src.doc.get(PINNED)
        if src.read_only and not (isinstance(pin_, dict) and pin_.get("ref")):
            src.errors.append(f"{src.path}: {f.stem} is an access: read project, whose document is a pinned copy "
                              f"(brain docgraph pin {f.stem} --from <a clone> --ref <commit> --file <path>)")
    return out


def check_lines(root: Path, own_name: str = "") -> list[str]:
    """brain check's warnings on the documents under ``docgraph/``: one line per document left out of the join
    (``own_name``: the brain's own project, whose graph is emitted, never read from a file)."""
    return [f"docgraph: {e}" for s in sources(root, own_name=own_name) for e in s.errors[:3]]


# --- joining ----------------------------------------------------------------------------------------------------------

def _node_id(nid: str, ns: str) -> str:
    t, sep, native = str(nid).partition(":")
    return f"{t}:{ns}/{native}" if sep else f"{ns}/{nid}"


def _end(nid, ns: str):
    """An edge end or a subject: ``<type>:@<namespace>/<native id>`` names another document's node (its joined id),
    any other id is the document's own, namespaced by ``ns``. The ``@`` marks it: a native id may start like a
    namespace (``document:docs/a.md`` beside a document named ``docs``)."""
    if not isinstance(nid, str):
        return nid
    t, sep, native = nid.partition(":")
    if sep and native.startswith(REF) and "/" in native:
        return f"{t}:{native[len(REF):]}"
    return _node_id(nid, ns)


def _joined_node(n: dict, ns: str) -> dict:
    out = {**n, "id": _node_id(n.get("id", ""), ns), "project": ns}
    if isinstance(n.get("phase"), str):
        out["phase"] = f"{ns}/{n['phase']}"
    return out


def _subjects(f: dict) -> list:
    return f["subjects"] if isinstance(f.get("subjects"), list) else []


def _from_source(s: Source) -> tuple[list[dict], list[dict], list[dict]]:
    """A document's nodes, edges and findings, namespaced by ``s.name`` (its findings marked ``by``)."""
    ns = s.name
    nodes = [_joined_node(n, ns) for n in docgraph._list(s.doc, "nodes") if isinstance(n, dict)]
    edges = [{**e, "from": _end(e.get("from"), ns), "to": _end(e.get("to"), ns), "project": ns}
             for e in docgraph._list(s.doc, "edges") if isinstance(e, dict)]
    found = [{**f, "subjects": [_end(x, ns) for x in _subjects(f)], "by": ns}
             for f in docgraph._list(s.doc, "checks") if isinstance(f, dict)]
    return nodes, edges, found


def _kept(producers: list[dict], found: list[dict]) -> list[dict]:
    """The producers' findings the join keeps: those of the checks it does not run, and doc.stale (a producer may know
    from its history what the join's dates cannot show) unless the join found the same one."""
    seen = {(f["id"], frozenset(map(str, f["subjects"]))) for f in found}
    return [f for f in producers if (f.get("id") not in RUN or f.get("id") in PRODUCER_KEPT)
            and (f.get("id"), frozenset(map(str, f["subjects"]))) not in seen]


def _source_line(s: Source) -> dict:
    gen = s.doc.get("generated") if isinstance(s.doc.get("generated"), dict) else {}
    return {"ref": s.ref, "by": str(gen.get("by", "")), "pinned": isinstance(s.doc.get(PINNED), dict)}


def join(srcs: list[Source], by: str, now: datetime | None = None) -> dict:
    """The valid documents of ``srcs`` as one docgraph/v1 document, ids namespaced, then the checks of :data:`RUN`
    run across it (:func:`run_checks`)."""
    ok = [s for s in srcs if s.ok]
    nodes, edges, producers = [], [], []
    for s in ok:
        n, e, p = _from_source(s)
        nodes, edges, producers = nodes + n, edges + e, producers + p
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc = {"schema": docgraph.ID,
           "generated": {"at": stamp, "by": by, "sources": {s.name: _source_line(s) for s in ok}},
           "nodes": nodes, "edges": edges}
    found = run_checks(doc)
    kept = _kept(producers, found)
    reported = {str(f.get("id")) for f in kept}   # a producer ran it: never also listed as not run
    doc["checks"] = found + kept
    doc["checks_run"] = list(RUN)
    doc["checks_not_run"] = [c for c in docgraph.CHECK_IDS if c not in RUN and c not in reported]
    return doc


# --- the checks, across the joined graph ------------------------------------------------------------------------------

def _when(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _later(a, b) -> bool:
    """Whether ``a`` is after ``b``, compared at the coarser of their two granularities (a date against a date-time
    compares the days: a node changed the day a document was is not later than it)."""
    wa, wb = _when(a), _when(b)
    if wa is None or wb is None:
        return False
    if len(str(a)) <= 10 or len(str(b)) <= 10:
        return wa.date() > wb.date()
    return wa > wb


def _native(nid: str) -> str:
    return str(nid).partition(":")[2]


def _finding(cid: str, subjects: list[str], message: str) -> dict:
    sev = next(c.severity for c in docgraph.CHECKS if c.id == cid)
    return {"id": cid, "severity": sev, "subjects": subjects, "message": message, "by": "join"}


def _phase_of(n: dict, out: dict, nodes: dict) -> str:
    """The milestone a node belongs to: its ``phase``, else the first milestone it is part_of."""
    if isinstance(n.get("phase"), str):
        return n["phase"]
    for t in out.get(("part_of", n["id"]), []):
        if nodes.get(t, {}).get("type") == "milestone":
            return _native(t)
    return ""


def _sccs(pairs: list[tuple[str, str]]) -> list[list[str]]:
    """The loops of a directed graph, one per strongly connected component (bounded, unlike every simple cycle)."""
    import networkx as nx
    g = nx.DiGraph(pairs)
    return sorted(sorted(c) for c in nx.strongly_connected_components(g)
                  if len(c) > 1 or any(g.has_edge(x, x) for x in c))


@dataclass
class _Graph:
    """A document indexed for the checks: its nodes by id, its edges, both directions by type, each node's phase."""
    nodes: dict
    edges: list
    into: dict
    out: dict
    phase: dict

    def of(self, t: str) -> list[dict]:
        return [n for n in self.nodes.values() if n.get("type") == t]


def _graph(doc: dict) -> _Graph:
    nodes = {n["id"]: n for n in docgraph._list(doc, "nodes") if isinstance(n, dict) and isinstance(n.get("id"), str)}
    edges = [e for e in docgraph._list(doc, "edges") if isinstance(e, dict)]
    into, out = defaultdict(list), defaultdict(list)
    for e in edges:
        into[(e.get("type"), e.get("to"))].append(e.get("from"))
        out[(e.get("type"), e.get("from"))].append(e.get("to"))
    return _Graph(nodes, edges, into, out, {nid: _phase_of(n, out, nodes) for nid, n in nodes.items()})


def run_checks(doc: dict) -> list[dict]:
    """The findings of the checks of :data:`RUN` over ``doc`` (a joined document, or any docgraph/v1 one)."""
    g = _graph(doc)
    found: list[dict] = []
    for check in (_criteria, _tests, _cross_phase, _reviews, _cycles, _decided, _stale, _targets):
        found += check(g)
    return found


def _criteria(g: _Graph) -> list[dict]:
    """criterion.no-item and item.no-criterion."""
    criteria = g.of("criterion")
    found = [_finding("criterion.no-item", [c["id"]], "no item serves it")
             for c in criteria if not g.into[("serves", c["id"])]]
    with_criteria = {g.phase[c["id"]] for c in criteria if g.phase[c["id"]]}
    return found + [_finding("item.no-criterion", [i["id"]], f"its phase {g.phase[i['id']]} has criteria; it serves "
                                                              "none")
                    for i in g.of("item") if g.phase[i["id"]] in with_criteria and i.get("kind") != "review"
                    and not any(g.nodes.get(t, {}).get("type") == "criterion" and g.phase.get(t) == g.phase[i["id"]]
                                for t in g.out[("serves", i["id"])])]


def _tests(g: _Graph) -> list[dict]:
    """test.uncarried, test.carried-twice and threat.untested."""
    found = []
    for t in g.of("test"):
        carriers = sorted(set(g.into[("carries", t["id"])]))
        if not carriers:
            found.append(_finding("test.uncarried", [t["id"]], "no item carries it"))
        elif len(carriers) > 1:
            found.append(_finding("test.carried-twice", [t["id"], *carriers], f"{len(carriers)} items carry it"))
    return found + [_finding("threat.untested", [t["id"]], "no test covers it") for t in g.of("threat")
                    if not g.into[("covers", t["id"])]]


def _cross_phase(g: _Graph) -> list[dict]:
    found = []
    for i in g.of("item"):
        for t in g.out[("depends_on", i["id"])]:
            other = g.nodes.get(t)
            if other is None:
                found.append(_finding("depends.cross-phase", [i["id"]], f"depends on {t}, which no document holds"))
            elif (other.get("type") == "item" and g.phase[t] and g.phase[i["id"]] and g.phase[t] != g.phase[i["id"]]
                  and other.get("status") in ("closed", "dropped")):
                found.append(_finding("depends.cross-phase", [i["id"], t],
                                      f"depends on {t} of {g.phase[t]}, which is {other['status']}"))
    return found


def _reviews(g: _Graph) -> list[dict]:
    found = []
    items = g.of("item")
    for r in items:
        p = g.phase[r["id"]]
        if r.get("kind") != "review" or not p:
            continue
        missing = sorted(i["id"] for i in items if g.phase[i["id"]] == p and i["id"] != r["id"]
                         and i["id"] not in g.out[("depends_on", r["id"])])
        if missing:
            more = f" (+{len(missing) - 5})" if len(missing) > 5 else ""
            found.append(_finding("phase.review-incomplete", [r["id"], *missing],
                                  f"the exit review of {p} does not depend on {', '.join(missing[:5])}{more}"))
    return found


def _cycles(g: _Graph) -> list[dict]:
    return [_finding("cycle", c, f"{etype} edges loop") for etype in CYCLE_TYPES
            for c in _sccs([(e["from"], e["to"]) for e in g.edges if e.get("type") == etype
                            and isinstance(e.get("from"), str) and isinstance(e.get("to"), str)])]


def _decided(g: _Graph) -> list[dict]:
    return [_finding("proposed.cited-as-decided", [nid, d], f"decided by {d}, which is still proposed")
            for nid in sorted(g.nodes) for d in g.out[("decided_by", nid)]
            if g.nodes.get(d, {}).get("type") == "decision" and g.nodes[d].get("status") == "proposed"]


def _modules(n: dict) -> set[tuple[str, str]]:
    """A node's modules (its optional ``module`` key, one or a list), each with its project: a module id means
    something within one project only."""
    mods = n.get("module")
    mods = [mods] if isinstance(mods, str) else mods if isinstance(mods, list) else []
    return {(str(n.get("project") or ""), str(m)) for m in mods if m}


def _linked(g: _Graph) -> dict[str, set[str]]:
    """Each node's neighbours by a declared link (``origin: declared``, but contradicts and constrains): what
    « touches » means beside a shared module."""
    linked: dict[str, set[str]] = defaultdict(set)
    for e in g.edges:
        a, b = e.get("from"), e.get("to")
        if (e.get("origin") == "declared" and e.get("type") not in ("constrains", "contradicts")
                and isinstance(a, str) and isinstance(b, str)):
            linked[a].add(b)
            linked[b].add(a)
    return linked


def _targets(g: _Graph) -> list[dict]:
    """decision.target-unreferenced: a decision (not marked ``door: two-way``) that touches an open need (a shared
    module, or a declared link between them) without a constrains edge to it."""
    needs = [n for n in g.of("need") if n.get("status") not in NEED_CLOSED]
    if not needs:
        return []
    by_module: dict[tuple[str, str], set[str]] = defaultdict(set)
    for n in needs:
        for m in _modules(n):
            by_module[m].add(n["id"])
    need_ids = {n["id"] for n in needs}
    linked = _linked(g)
    found = []
    for d in g.of("decision"):
        if d.get("door") == "two-way":
            continue
        touched = {x for m in _modules(d) for x in by_module.get(m, ())} | (linked[d["id"]] & need_ids)
        left = sorted(touched - set(g.out[("constrains", d["id"])]))
        if left:
            more = f" (+{len(left) - 5})" if len(left) > 5 else ""
            found.append(_finding("decision.target-unreferenced", [d["id"], *left[:5]],
                                  f"touches {len(left)} need(s) without citing them: {', '.join(left[:5])}{more}"))
    return found


def _stale_pair(e: dict, nodes: dict) -> tuple[str, str] | None:
    """(the document, what it follows) when ``e`` makes a hand-written document follow a node: a citation, or a
    declared parent document."""
    if e.get("type") == "documented_in":
        doc_end, other = e.get("to"), e.get("from")
    elif e.get("type") == "depends_on":
        doc_end, other = e.get("from"), e.get("to")
    else:
        return None
    d, o = nodes.get(doc_end), nodes.get(other)
    if not d or not o or d.get("type") != "document" or d.get("kind") in EXEMPT_KINDS:
        return None
    if e["type"] == "depends_on" and o.get("type") != "document":
        return None
    return doc_end, other


def _stale(g: _Graph) -> list[dict]:
    """doc.stale from the ``updated`` dates: a hand-written document a cited node, or a declared parent document,
    changed after."""
    found = []
    for e in g.edges:
        pair = _stale_pair(e, g.nodes)
        if pair is None:
            continue
        if _later(g.nodes[pair[1]].get("updated"), g.nodes[pair[0]].get("updated")):
            what = "cites" if e["type"] == "documented_in" else "depends on"
            found.append(_finding("doc.stale", list(pair), f"{what} {pair[1]}, which changed after it"))
    return found


def summary_lines(srcs: list[Source], doc: dict) -> list[str]:
    """What ``brain docgraph join`` prints: each document, then the findings of the join."""
    lines = []
    for s in srcs:
        if s.ok:
            sm = docgraph.summary(s.doc)
            ref = f" @ {s.ref[:12]}" if s.ref else ""
            kind = "pinned" if s.read_only else "emitted" if s.emitted else "own"
            lines.append(f"{s.name} ({s.path}, {kind}{ref}): {sum(sm['nodes'].values())} node(s), "
                         f"{sum(sm['edges'].values())} edge(s)")
        else:
            lines.append(f"{s.name} ({s.path}): left out")
            lines += [f"  error: {e}" for e in s.errors]
    checks = doc.get("checks", [])
    lines.append(f"join: {len(doc['nodes'])} node(s), {len(doc['edges'])} edge(s), {len(checks)} finding(s) "
                 f"({sum(1 for f in checks if f.get('severity') == 'error')} error)")
    lines += [f"  {f.get('severity')}: {f.get('id')} [{f.get('by')}] {', '.join(map(str, f.get('subjects', [])))}: "
              f"{f.get('message', '')}" for f in checks]
    return lines
