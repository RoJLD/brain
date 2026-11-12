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
  subject whose native part starts with a namespace of the join (``item:example/25`` in another document) already
  names a joined node and is kept as it is. The joined graph is itself a docgraph/v1 document: ids stay prefixed by
  their type and unique.
- **The checks, run again** (:data:`RUN`) over the joined graph, each finding marked ``by: join``; a producer's own
  findings are kept, marked ``by: <namespace>``, unless the join found the same one. The checks that need what a
  document does not carry (a decision's text and history, its numbering, the citations of a reported node, the
  register of needs) are listed as not run.
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
       "depends.cross-phase", "phase.review-incomplete", "cycle", "proposed.cited-as-decided", "doc.stale")
CYCLE_TYPES = ("depends_on", "part_of", "supersedes")


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


def pin(root: Path, project: str, checkout: Path, ref: str, file: str,
        now: datetime | None = None) -> tuple[Path | None, list[str], list[str]]:
    """Read ``file`` at ``ref`` from the clone ``checkout`` of the read project ``project`` and write its pinned copy
    to ``<root>/docgraph/<project>.json``. (the copy's path or None, errors, notes): nothing is written on an error.
    Only git's read commands run in the clone (rev-parse, show): its working tree and refs are never touched."""
    if project not in projects.readonly(root):
        return None, [f"{project!r} is not an access: read project of the registry (brain projects lists them)"], []
    if not NAME_RE.match(project):
        return None, [f"{project!r}: a pinned copy is named after its project: lower-case letters, digits, - and _"], []
    if ref.startswith("-") or file.startswith("-") or not ref or not file:
        return None, [f"--ref {ref!r} and --file {file!r}: a commit or a tag, and a path in the repository"], []
    if not Path(checkout).is_dir():
        return None, [f"{checkout}: no such folder (give a local clone of {project})"], []
    try:
        rev = _git(checkout, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        sha = rev.stdout.decode("ascii", "replace").strip()
        if rev.returncode or not sha:
            return None, [f"{checkout}: {ref!r} is not a commit of this clone (git fetch it first)"], []
        shown = _git(checkout, "show", f"{sha}:{file.lstrip('/')}")
    except (OSError, subprocess.SubprocessError) as exc:
        return None, [f"{checkout}: git could not read it ({exc})"], []
    if shown.returncode:
        return None, [f"{checkout}: no {file} at {sha[:12]}"], []
    where = f"{project}@{sha[:12]}:{file}"
    try:
        doc = json.loads(shown.stdout.decode("utf-8-sig"))
    except (ValueError, RecursionError) as exc:
        return None, [f"{where}: not a JSON document ({exc})"], []
    errors, notes = docgraph.validate(doc, where=where)
    if errors:
        return None, errors, notes
    if PINNED in doc:
        notes.append(f"{where}: its own {PINNED!r} key is replaced by the pin")
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc[PINNED] = {"ref": sha, "file": file.lstrip("/"), "at": stamp}
    out = Path(root) / DIR / f"{project}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return out, [], notes


# --- reading ----------------------------------------------------------------------------------------------------------

def sources(root: Path, own: tuple[str, dict] | None = None) -> list[Source]:
    """The documents of the join: the brain's own graph (``own``: its namespace and its emitted document), then every
    ``docgraph/*.json`` under ``root``, each validated. A read project's copy without its pin, a file whose name is
    not a namespace, or one named as the brain's own project: errors, the document left out of the join."""
    read_only = set(projects.readonly(root))
    out: list[Source] = []
    if own:
        name, doc = own
        errors, notes = docgraph.validate(doc, where=f"{name} (emitted)")
        out.append(Source(name, "(emitted)", doc, errors, notes, emitted=True))
    folder = Path(root) / DIR
    for f in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        src = Source(f.stem, f"{DIR}/{f.name}", read_only=f.stem in read_only)
        out.append(src)
        if not NAME_RE.match(f.stem):
            src.errors.append(f"{src.path}: its name is its namespace: lower-case letters, digits, - and _")
            continue
        if own and f.stem == own[0]:
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


def check_lines(root: Path) -> list[str]:
    """brain check's warnings on the documents under ``docgraph/``: one line per document left out of the join."""
    return [f"docgraph: {e}" for s in sources(root) for e in s.errors[:3]]


# --- joining ----------------------------------------------------------------------------------------------------------

def _node_id(nid: str, ns: str) -> str:
    t, sep, native = str(nid).partition(":")
    return f"{t}:{ns}/{native}" if sep else f"{ns}/{nid}"


def _end(nid, ns: str, names: set[str]):
    """An edge end or a subject: a joined id already (another document's node) is kept, any other is namespaced."""
    if not isinstance(nid, str):
        return nid
    t, sep, native = nid.partition(":")
    head, slash, _ = native.partition("/")
    if sep and slash and head in names:
        return nid
    return _node_id(nid, ns)


def join(srcs: list[Source], by: str, now: datetime | None = None) -> dict:
    """The valid documents of ``srcs`` as one docgraph/v1 document, ids namespaced, then the checks of :data:`RUN`
    run across it (:func:`run_checks`)."""
    ok = [s for s in srcs if s.ok]
    names = {s.name for s in ok}
    nodes, edges, producers = [], [], []
    for s in ok:
        for n in docgraph._list(s.doc, "nodes"):
            if not isinstance(n, dict):
                continue
            n = {**n, "id": _node_id(n.get("id", ""), s.name), "project": s.name}
            if isinstance(n.get("phase"), str):
                n["phase"] = f"{s.name}/{n['phase']}"
            nodes.append(n)
        for e in docgraph._list(s.doc, "edges"):
            if isinstance(e, dict):
                edges.append({**e, "from": _end(e.get("from"), s.name, names),
                              "to": _end(e.get("to"), s.name, names), "project": s.name})
        for f in docgraph._list(s.doc, "checks"):
            if isinstance(f, dict):
                subjects = f.get("subjects") if isinstance(f.get("subjects"), list) else []
                producers.append({**f, "subjects": [_end(x, s.name, names) for x in subjects], "by": s.name})
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc = {"schema": docgraph.ID,
           "generated": {"at": stamp, "by": by,
                         "sources": {s.name: {"ref": s.ref, "by": str((s.doc.get("generated") or {}).get("by", "")),
                                              "pinned": isinstance(s.doc.get(PINNED), dict)} for s in ok}},
           "nodes": nodes, "edges": edges}
    found = run_checks(doc)
    seen = {(f["id"], tuple(f["subjects"])) for f in found}
    kept = [f for f in producers if (f.get("id"), tuple(f["subjects"])) not in seen]
    doc["checks"] = found + kept
    doc["checks_run"] = list(RUN)
    doc["checks_not_run"] = [c for c in docgraph.CHECK_IDS if c not in RUN]
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


def run_checks(doc: dict) -> list[dict]:
    """The findings of the checks of :data:`RUN` over ``doc`` (a joined document, or any docgraph/v1 one)."""
    nodes = {n["id"]: n for n in docgraph._list(doc, "nodes") if isinstance(n, dict) and isinstance(n.get("id"), str)}
    edges = [e for e in docgraph._list(doc, "edges") if isinstance(e, dict)]
    into, out = defaultdict(list), defaultdict(list)
    for e in edges:
        into[(e.get("type"), e.get("to"))].append(e.get("from"))
        out[(e.get("type"), e.get("from"))].append(e.get("to"))
    of = lambda t: [n for n in nodes.values() if n.get("type") == t]   # noqa: E731
    phase = {nid: _phase_of(n, out, nodes) for nid, n in nodes.items()}
    found: list[dict] = []
    criteria, items = of("criterion"), of("item")
    found += [_finding("criterion.no-item", [c["id"]], "no item serves it")
              for c in criteria if not into[("serves", c["id"])]]
    with_criteria = {phase[c["id"]] for c in criteria if phase[c["id"]]}
    found += [_finding("item.no-criterion", [i["id"]], f"its phase {phase[i['id']]} has criteria; it serves none")
              for i in items if phase[i["id"]] in with_criteria and i.get("kind") != "review"
              and not any(nodes.get(t, {}).get("type") == "criterion" for t in out[("serves", i["id"])])]
    for t in of("test"):
        carriers = sorted(set(into[("carries", t["id"])]))
        if not carriers:
            found.append(_finding("test.uncarried", [t["id"]], "no item carries it"))
        elif len(carriers) > 1:
            found.append(_finding("test.carried-twice", [t["id"], *carriers], f"{len(carriers)} items carry it"))
    found += [_finding("threat.untested", [t["id"]], "no test covers it") for t in of("threat")
              if not into[("covers", t["id"])]]
    found += _cross_phase(items, nodes, out, phase)
    found += _reviews(items, out, phase)
    for etype in CYCLE_TYPES:
        found += [_finding("cycle", c, f"{etype} edges loop") for c in
                  _sccs([(e["from"], e["to"]) for e in edges if e.get("type") == etype
                         and isinstance(e.get("from"), str) and isinstance(e.get("to"), str)])]
    found += [_finding("proposed.cited-as-decided", [nid, d], f"decided by {d}, which is still proposed")
              for nid in sorted(nodes) for d in out[("decided_by", nid)]
              if nodes.get(d, {}).get("type") == "decision" and nodes[d].get("status") == "proposed"]
    found += _stale(nodes, edges)
    return found


def _cross_phase(items: list[dict], nodes: dict, out: dict, phase: dict) -> list[dict]:
    found = []
    for i in items:
        for t in out[("depends_on", i["id"])]:
            other = nodes.get(t)
            if other is None:
                found.append(_finding("depends.cross-phase", [i["id"]], f"depends on {t}, which no document holds"))
            elif (other.get("type") == "item" and phase[t] and phase[i["id"]] and phase[t] != phase[i["id"]]
                  and other.get("status") in ("closed", "dropped")):
                found.append(_finding("depends.cross-phase", [i["id"], t],
                                      f"depends on {t} of {phase[t]}, which is {other['status']}"))
    return found


def _reviews(items: list[dict], out: dict, phase: dict) -> list[dict]:
    found = []
    for r in items:
        p = phase[r["id"]]
        if r.get("kind") != "review" or not p:
            continue
        missing = sorted(i["id"] for i in items if phase[i["id"]] == p and i["id"] != r["id"]
                         and i["id"] not in out[("depends_on", r["id"])])
        if missing:
            more = f" (+{len(missing) - 5})" if len(missing) > 5 else ""
            found.append(_finding("phase.review-incomplete", [r["id"], *missing],
                                  f"the exit review of {p} does not depend on {', '.join(missing[:5])}{more}"))
    return found


def _stale(nodes: dict, edges: list[dict]) -> list[dict]:
    """doc.stale from the ``updated`` dates: a hand-written document a cited node, or a declared parent document,
    changed after."""
    found = []
    for e in edges:
        doc_end, other = ((e.get("to"), e.get("from")) if e.get("type") == "documented_in" else
                          (e.get("from"), e.get("to")) if e.get("type") == "depends_on" else (None, None))
        d, o = nodes.get(doc_end), nodes.get(other)
        if not d or not o or d.get("type") != "document" or d.get("kind") in EXEMPT_KINDS:
            continue
        if e.get("type") == "depends_on" and o.get("type") != "document":
            continue
        dw, ow = _when(d.get("updated")), _when(o.get("updated"))
        if dw and ow and ow > dw:
            what = "cites" if e["type"] == "documented_in" else "depends on"
            found.append(_finding("doc.stale", [doc_end, other], f"{what} {other}, which changed after it"))
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
