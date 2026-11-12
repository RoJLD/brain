"""Checking a decision against the target before it is accepted (wi-brain-adr-target-check; spec-brain-architecture-docs
11; docs/adr-target.md).

- **The register of future needs**, computed from the store, never written by hand (:func:`register`): the features
  still planned, the pending milestones with a trigger, the open items of the waves after the current one and of the
  pending eras. Each need keeps its source's status; the register records and never decides.
- **A one-way door's two fields** in an ADR: « Scope » (what it covers, up to which wave or era) and « Target
  compatibility » (the needs it touches, each compatible, an extension point or to review, and what it leaves open).
  ``brain adr new --scope --target ID=COMPAT --leaves-open`` writes them; an ADR written by hand states them as a
  label (``**Scope.**``) or a sentence (``Scope: ...``). An ADR with either is a one-way door; any other is a two-way
  door, never checked (the owner's answer of 2026-11-11).
- **The checks** (advisory: warnings, never a refusal), on the one-way doors only: ``decision.target-compat-missing``
  (a scope without a target compatibility), ``decision.review-trigger-missing`` (no « Revisit if », or a TODO) and
  ``decision.target-unreferenced`` (a need of a module the decision touches, open, that the target compatibility does
  not cite; run by brain.docjoin over the joined graph too). The compatibility section says what stays open: it never
  designs a later phase, and no check asks it to.

:func:`document` gives the same as a docgraph/v1 part (need nodes, the one-way decisions with their ``module`` and
``door``, constrains edges), which ``brain docgraph emit`` adds to the brain's documentation graph.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import graph, notes, waves

COMPAT = ("compatible", "extension-point", "to-review")
_COMPAT_RE = re.compile(r"\b(compatible|extension[- ]point|to[- ]review)\b", re.I)
_NAMES = r"Scope|Target\s+compatibility|Revisit\s+if"
# a field: a label (**Scope.**, **Scope:**) anywhere, or a sentence that opens a line or follows a sentence's end
_LABEL_RE = re.compile(rf"\*\*({_NAMES})[.:]\*\*|(?:^|(?<=[.!?]\s)|(?<=\n))[ \t]*({_NAMES}):", re.M)
_FIELD_END = re.compile(r"\n[ \t]*\n|\*\*[A-Z][^*]{0,40}[.:]\*\*")
_ID_RE = re.compile(r"(?<![\w./-])([a-z][a-z0-9]*(?:[-.][a-z0-9]+)+)(?![\w-])")
OPEN = ("todo", "doing", "blocked")


def _props(n: dict) -> dict:
    return n.get("props") if isinstance(n.get("props"), dict) else {}


# --- the register -----------------------------------------------------------------------------------------------------

def register(store: Path, root: Path | None = None) -> list[dict]:
    """The future needs of ``store``: {id, kind, title, phase, status, module, source}, sorted by kind then id."""
    nodes = {nid: node for nid, (_, node) in graph.node_index(store).items()}
    out = [_need(nid, n, "feature", str(_props(n).get("wave") or "later"), "planned")
           for nid, n in nodes.items() if n.get("type") == "Feature" and n.get("status") == "planned"]
    out += [_need(nid, n, "milestone", nid, "planned") for nid, n in nodes.items()
            if n.get("type") == "Milestone" and n.get("status") == "pending" and _props(n).get("trigger")]
    out += [_need(i, nodes[i], "item", phase, "open") for i, phase in _later_items(store, root, nodes)]
    return sorted(out, key=lambda x: (x["kind"], x["id"]))


def _later_items(store: Path, root: Path | None, nodes: dict) -> list[tuple[str, str]]:
    """(item, its wave, milestone or era) for the open items of the waves after the current one, and of the pending
    eras: their own items and those of their pending milestones (the current wave left out)."""
    if not waves.applies(store):
        return []
    plan = waves.load(store, root)
    pend = waves.pending_waves(plan)
    current = pend[0] if pend else ""
    seen: dict[str, str] = {}
    for w in pend[1:]:
        for i in plan.items_of(w):
            seen.setdefault(i, w)
    for era in sorted(m for m, n in nodes.items() if waves.kind(n) == "era" and n.get("status") == "pending"):
        for item, phase in _era_items(plan, nodes, era, current):
            seen.setdefault(item, phase)
    return sorted((i, p) for i, p in seen.items() if (nodes.get(i) or {}).get("type") == "WorkItem"
                  and nodes[i].get("status") in OPEN)


def _era_items(plan, nodes: dict, era: str, current: str) -> list[tuple[str, str]]:
    """(member, its phase) of a pending era: its own members, and the items of its pending milestones and waves (the
    current wave aside)."""
    out = []
    for x in sorted(plan.members.get(era, ())):
        if (nodes.get(x) or {}).get("type") != "Milestone":
            out.append((x, era))
        elif x != current and nodes[x].get("status") == "pending":
            members = plan.items_of(x) if waves.kind(nodes[x]) == "wave" else plan.members.get(x, ())
            out += [(i, x) for i in members]
    return out


def _need(nid: str, n: dict, kind: str, phase: str, status: str) -> dict:
    return {"id": nid, "kind": kind, "title": str(n.get("title") or nid), "phase": phase, "status": status,
            "native_status": str(n.get("status") or ""), "module": str(_props(n).get("module") or "")}


# --- an ADR's fields --------------------------------------------------------------------------------------------------

def _name(raw: str) -> str:
    return " ".join(raw.split())


def fields(text: str) -> dict[str, str]:
    """{"Scope", "Target compatibility", "Revisit if": its text} of an ADR's text, labelled (``**Scope.**``) or in a
    sentence that opens a line or follows a sentence's end (``Scope: ...``, its label possibly wrapped over two
    lines), up to the end of its paragraph or the next field; a label alone on its line takes the paragraph after it.
    Each line's spaces are folded, its line breaks kept (a list stays a list)."""
    out: dict[str, str] = {}
    hits = list(_LABEL_RE.finditer(text))
    for k, m in enumerate(hits):
        name = _name(m.group(1) or m.group(2))
        rest = text[m.end():hits[k + 1].start()] if k + 1 < len(hits) else text[m.end():]
        lead = len(rest) - len(rest.lstrip())
        body = rest[lead:]
        end = _FIELD_END.search(body)
        body = body[:end.start()] if end else body
        lines = [" ".join(line.split()) for line in body.split("\n")]
        out.setdefault(name, "\n".join(x for x in lines if x))
    return out


def cited(target: str, known: set[str]) -> dict[str, str]:
    """{need id: compatibility} of the ids a target compatibility text names (only the ids ``known`` holds): the
    compatibility is the word that follows the id in its clause (up to a ``;``, a line's end or the next need named),
    ``to-review`` when none is said."""
    hits = [m for m in _ID_RE.finditer(target) if m.group(1) in known]
    out: dict[str, str] = {}
    for k, m in enumerate(hits):
        if m.group(1) in out:
            continue
        stop = hits[k + 1].start() if k + 1 < len(hits) else len(target)
        clause = re.split(r"[;\n]", target[m.end():stop], maxsplit=1)[0]
        word = _COMPAT_RE.search(clause)
        out[m.group(1)] = word.group(1).lower().replace(" ", "-") if word else "to-review"
    return out


def target_text(targets: list[str], leaves_open: str) -> str:
    """The Target compatibility field ``brain adr new`` writes from ``--target ID=COMPAT[:note]`` and
    ``--leaves-open``: one line per need, then what it leaves open. ValueError on a compatibility not in
    :data:`COMPAT`."""
    lines = []
    for t in targets:
        nid, _, rest = t.partition("=")
        compat, _, note = rest.partition(":")
        compat = compat.strip()
        if not nid.strip() or compat not in COMPAT:
            raise ValueError(f"--target {t!r}: ID=COMPAT[:note], COMPAT one of {', '.join(COMPAT)}")
        lines.append(f"- `{nid.strip()}`: {compat}" + (f" ({note.strip()})" if note.strip() else ""))
    if leaves_open.strip():
        lines.append(f"- Leaves open: {leaves_open.strip()}")
    return "\n".join(lines)


# --- the one-way decisions and the checks -----------------------------------------------------------------------------

def decisions(store: Path, logs: list[Path], root: Path | None = None) -> list[dict]:
    """The ADRs of ``logs`` that are one-way doors (a Scope or a Target compatibility) and still in force (no
    supersedes edge reaches it, its node not superseded): {id, title, scope, target, revisit, modules (of the nodes
    it decides), file (relative to ``root``), line}; an id two logs give is read once, from the first."""
    nodes = {nid: node for nid, (_, node) in graph.node_index(store).items()}
    decides, gone = _decided(store, nodes)
    out, seen = [], set()
    for log in logs:
        if not log.is_file():
            continue
        rel = _rel(log, root)
        for a in notes.adr_entries(log.read_text(encoding="utf-8")):
            f = fields(a["text"])
            if a["id"] in seen or a["id"] in gone or not ({"Scope", "Target compatibility"} & set(f)):
                continue
            seen.add(a["id"])
            mods = sorted({str(_props(nodes.get(x, {})).get("module") or "") for x in decides.get(a["id"], ())} - {""})
            out.append({"id": a["id"], "title": a["title"], "scope": f.get("Scope", ""),
                        "target": f.get("Target compatibility", ""), "revisit": f.get("Revisit if", ""),
                        "modules": mods, "file": rel, "line": a["line"]})
    return out


def _decided(store: Path, nodes: dict) -> tuple[dict[str, set[str]], set[str]]:
    """({ADR: the nodes it decides}, the ADRs no longer in force: a supersedes edge reaches it, or its node says
    superseded)."""
    edges = _edges(store)
    decides: dict[str, set[str]] = {}
    for e in edges:
        if e.get("type") == "decided_by":
            decides.setdefault(str(e["to"]), set()).add(str(e["from"]))
    gone = {str(e["to"]) for e in edges if e.get("type") == "supersedes"}
    return decides, gone | {nid for nid, n in nodes.items() if n.get("status") == "superseded"}


def _rel(log: Path, root: Path | None) -> str:
    try:
        return log.resolve().relative_to(Path(root).resolve()).as_posix() if root else log.name
    except ValueError:   # a log outside the root: its name
        return log.name


def _edges(store: Path) -> list[dict]:
    files = [store / "edges.yaml", *sorted((store / "edges").glob("*.yaml"))]
    return [e for f in files for e in graph.load_yaml_list(f) if isinstance(e, dict) and e.get("from") and e.get("to")]


def _todo(text: str) -> bool:
    return not text.strip() or text.strip().upper().startswith(notes.TODO)


def check(decs: list[dict], needs: list[dict]) -> list[dict]:
    """The advisory findings on the one-way decisions: {id, severity, subjects, message} as docgraph/v1 findings."""
    known = {n["id"] for n in needs}
    open_by_module: dict[str, list[str]] = {}
    for n in needs:
        if n["module"]:
            open_by_module.setdefault(n["module"], []).append(n["id"])
    out = []
    for d in decs:
        if _todo(d["target"]):
            out.append(_finding("decision.target-compat-missing", d, "a one-way door with no target compatibility"))
        if _todo(d["revisit"]):
            out.append(_finding("decision.review-trigger-missing", d, "a one-way door with no « Revisit if »"))
        touched = sorted({x for m in d["modules"] for x in open_by_module.get(m, ())} - set(cited(d["target"], known)))
        if touched:
            more = f" (+{len(touched) - 5})" if len(touched) > 5 else ""
            out.append(_finding("decision.target-unreferenced", d,
                                f"touches {len(touched)} need(s) of its module(s) {', '.join(d['modules'])} its target "
                                f"compatibility does not cite: {', '.join(touched[:5])}{more}"))
    return out


def _finding(cid: str, d: dict, message: str) -> dict:
    return {"id": cid, "severity": "warning", "subjects": [f"decision:{d['id']}"], "message": message}


# --- as docgraph/v1 ---------------------------------------------------------------------------------------------------

def document(decs: list[dict], needs: list[dict]) -> dict:
    """The register and the one-way decisions as docgraph/v1 nodes and edges (to add to the brain's own document):
    need nodes, decision nodes with ``module`` and ``door: one-way``, a constrains edge per cited need."""
    known = {n["id"] for n in needs}
    nodes = [{"id": f"need:{n['id']}", "type": "need", "kind": n["kind"], "title": n["title"],
              "status": n["status"], "native_status": n["native_status"], "phase": n["phase"],
              **({"module": n["module"]} if n["module"] else {}), "source": {"path": "notes/graph"}} for n in needs]
    edges = []
    for d in decs:
        nodes.append({"id": f"decision:{d['id']}", "type": "decision", "kind": "adr", "title": d["title"],
                      "status": "accepted", "door": "one-way", **({"module": d["modules"]} if d["modules"] else {}),
                      "source": {"path": d["file"], "line": d["line"]}})
        edges += [{"from": f"decision:{d['id']}", "to": f"need:{nid}", "type": "constrains", "compatibility": compat,
                   "origin": "derived", "source": {"path": d["file"], "line": d["line"]}}
                  for nid, compat in sorted(cited(d["target"], known).items())]
    return {"nodes": nodes, "edges": edges}


PRESENCE = ("decision.target-compat-missing", "decision.review-trigger-missing", "decision.target-unreferenced")


def add_to(doc: dict, store: Path, root: Path, logs: list[Path]) -> dict:
    """``doc`` (the brain's own docgraph/v1 document) with the register, the one-way decisions (a node the document
    already holds gains ``door`` and ``module``), their constrains edges and the findings of :data:`PRESENCE`, which
    then count as run."""
    needs = register(store, root)
    decs = decisions(store, logs, root)
    part = document(decs, needs)
    held = {n["id"]: n for n in doc["nodes"]}
    for n in part["nodes"]:
        if n["id"] in held:
            held[n["id"]].update({k: n[k] for k in ("door", "module") if k in n})
        else:
            doc["nodes"].append(n)
    doc["edges"] += part["edges"]
    doc["checks"] += check(decs, needs)
    doc["checks_run"] = list(dict.fromkeys([*doc.get("checks_run", []), *PRESENCE]))
    doc["checks_not_run"] = [c for c in doc.get("checks_not_run", []) if c not in PRESENCE]
    return doc
