"""docgraph/v1, the documentation graph's neutral contract (wi-brain-docgraph-contract; docs/docgraph.md).

A documentation graph's nodes (decisions, documents and their sections, milestones, criteria, items, changes, tests,
threats, modules, owner decisions, findings, needs), their normalised statuses, typed edges named as the Brain names
them, a source on every node and every derived edge, declared links with their reason and whether they are confirmed,
and the findings of the named checks (:data:`CHECKS`). Any program may emit it (a repository's own docs command, the
Brain's doc graph, an import of documents kept elsewhere); the Brain reads it read only.

The JSON schema (``schemas/docgraph.schema.json``) holds the shape; :func:`validate` adds what a schema cannot say:
ids unique and prefixed by their type, a source that names a file or a tracker object, the checks run and not run kept
apart. Evolution (the status contract's rule): an optional key may be added in v1 and a reader ignores the ones it
does not know; a new node type, edge type or status, or a change of a key's meaning, is ``docgraph/v2``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import schema

ID = "docgraph/v1"
KIND = "docgraph"          # its name in brain.schema.SCHEMAS
VERSION = 1
ID_RE = re.compile(r"^docgraph/v(\d+)$")

NODE_TYPES = ("decision", "document", "milestone", "criterion", "item", "change", "test", "threat", "module",
              "owner-decision", "finding", "need")
STATUSES = ("proposed", "accepted", "superseded", "open", "closed", "done", "dropped", "planned", "stale")
EDGE_TYPES = ("decided_by", "supersedes", "complements", "depends_on", "serves", "part_of", "requires", "carries",
              "covers", "implements", "reports", "contradicts", "documented_in", "tested_by", "constrains")
SEVERITIES = ("error", "warning", "info")
DOCUMENT_KINDS = ("tutorial", "how-to", "reference", "explanation", "generated", "dated-spec")   # Diataxis, then the
# two classes kept apart (a generated view, a dated spec: history, never stale)


@dataclass(frozen=True)
class Check:
    """A named check: what it is about, its default severity, what it means and what a producer needs to run it."""
    id: str
    subject: str
    severity: str
    means: str
    needs: str


CHECKS: tuple[Check, ...] = (
    Check("criterion.no-item", "criterion", "error",
          "a criterion no item serves (no serves edge reaches it)", "items and criteria"),
    Check("item.no-criterion", "item", "warning",
          "an item of a phase that has criteria serves none of them", "items, criteria and their phases"),
    Check("test.uncarried", "test", "warning", "a test no item carries", "items and tests"),
    Check("test.carried-twice", "test", "warning", "a test two items or more carry", "items and tests"),
    Check("threat.untested", "threat", "error", "a threat no test covers", "threats and tests"),
    Check("depends.cross-phase", "item", "warning",
          "an item depends on an item of another phase that is closed or dropped, or on an id the document does not "
          "hold", "items and their phases"),
    Check("phase.review-incomplete", "milestone", "warning",
          "a phase's exit review (an item of kind review part_of it) does not depend on every item of the phase",
          "items, their phases and the review items"),
    Check("cycle", "item", "error", "a cycle of depends_on, part_of or supersedes edges", "edges"),
    Check("decision.modified-after-accept", "decision", "warning",
          "an accepted decision whose text changed after it was accepted", "decisions and their history"),
    Check("decision.number-unused-or-reused", "decision", "warning",
          "a decision number skipped, or used by two decisions", "numbered decisions"),
    Check("owner-decision.unreported", "owner-decision", "error",
          "a decision (or an owner's decision) whose reports edge reaches a node that does not cite it",
          "reports edges and the citations of their targets"),
    Check("proposed.cited-as-decided", "decision", "warning",
          "a node decided_by a decision that is still proposed", "decisions and their statuses"),
    Check("doc.stale", "document", "warning",
          "a hand-written document whose cited node or declared parent changed after the document's last change "
          "(generated documents and dated specs are exempt)", "documents, their citations and dates"),
    Check("decision.review-trigger-missing", "decision", "warning",
          "a decision with no review section, or one with no precise trigger (a phase, a measure, an event)",
          "the decisions' texts"),
    Check("decision.target-compat-missing", "decision", "warning",
          "a decision with no target compatibility section (the future needs it touches, each compatible, an "
          "extension point or to review, and what it leaves open)", "the decisions' texts"),
    Check("decision.target-unreferenced", "decision", "warning",
          "a decision that touches a need (a shared module or subject, or a declared link) without a constrains edge "
          "to it", "the register of needs (run where it is)"),
)
CHECK_IDS = tuple(c.id for c in CHECKS)


class DocgraphError(ValueError):
    """A file that is not a docgraph document this engine reads (not JSON, another contract, a newer version)."""


def load(path: Path) -> dict:
    """The document at ``path`` (a UTF-8 byte order mark allowed: a Windows PowerShell 5.1 producer writes one);
    :class:`DocgraphError` when it is not JSON or not an object (JSON nested too deep or a number too long too)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, RecursionError) as exc:   # ValueError: JSONDecodeError, UnicodeDecodeError, digits
        raise DocgraphError(f"{path}: not a JSON document ({exc})") from exc
    if not isinstance(data, dict):
        raise DocgraphError(f"{path}: not a JSON object")
    return data


def newer(doc: dict) -> str:
    """The refusal of a document written for a later version of the contract; "" otherwise."""
    if not isinstance(doc, dict):
        return ""
    m = ID_RE.match(str(doc.get("schema", "")))
    if m and int(m.group(1)) > VERSION:
        return f"schema: {doc['schema']} is a later contract than this engine's {ID}: brain update"
    return ""


def _source_names_something(src) -> bool:
    return isinstance(src, dict) and bool(src.get("path") or src.get("tracker"))


def _list(doc: dict, key: str) -> list:
    """``doc[key]`` when it is a list (the schema reports any other value), else []."""
    value = doc.get(key)
    return value if isinstance(value, list) else []


def _nodes(nodes: list, where: str, errors: list[str]) -> set[str]:
    """The ids of the document's nodes; an id used twice or not prefixed by its type, a source naming nothing: errors."""
    seen: set[str] = set()
    for i, n in enumerate(nodes):
        if not isinstance(n, dict):
            continue
        nid, ntype = str(n.get("id", "")), str(n.get("type", ""))
        if nid in seen:
            errors.append(f"{where}.nodes[{i}]: id {nid!r} used twice")
        seen.add(nid)
        if ntype and nid.partition(":")[0] != ntype:
            errors.append(f"{where}.nodes[{i}]: id {nid!r} is not prefixed by its type {ntype!r}")
        if "source" in n and not _source_names_something(n["source"]):
            errors.append(f"{where}.nodes[{i}].source: names no path and no tracker")
    return seen


def _edges(edges: list, seen: set[str], where: str, errors: list[str], notes: list[str]) -> None:
    for i, e in enumerate(edges):
        if not isinstance(e, dict):
            continue
        if "source" in e and not _source_names_something(e["source"]):
            errors.append(f"{where}.edges[{i}].source: names no path and no tracker")
        notes.extend(f"{where}.edges[{i}].{end}: {e[end]!r} is not a node of the document"
                     for end in ("from", "to") if isinstance(e.get(end), str) and e[end] not in seen)


def _findings(doc: dict, seen: set[str], where: str, errors: list[str], notes: list[str]) -> None:
    run = {c for c in _list(doc, "checks_run") if isinstance(c, str)}
    not_run = {c for c in _list(doc, "checks_not_run") if isinstance(c, str)}
    errors.extend(f"{where}: check {cid!r} is both run and not run" for cid in sorted(run & not_run))
    notes.extend(f"{where}: {cid!r} in checks_not_run is not a named check"
                 for cid in sorted(not_run - set(CHECK_IDS)))
    named_or_found = set(CHECK_IDS) | {str(f.get("id")) for f in _list(doc, "checks") if isinstance(f, dict)}
    notes.extend(f"{where}: {cid!r} in checks_run is the producer's own check (not a named one)"
                 for cid in sorted(run - named_or_found))
    for i, f in enumerate(_list(doc, "checks")):
        if not isinstance(f, dict):
            continue
        cid = str(f.get("id", ""))
        if cid in not_run:
            errors.append(f"{where}.checks[{i}]: a finding of {cid!r}, which the document says was not run")
        if cid and cid not in CHECK_IDS:
            notes.append(f"{where}.checks[{i}]: {cid!r} is the producer's own check (not a named one)")
        subjects = f.get("subjects") if isinstance(f.get("subjects"), list) else []
        notes.extend(f"{where}.checks[{i}]: subject {s!r} is not a node of the document"
                     for s in subjects if isinstance(s, str) and s not in seen)


def validate(doc: dict, where: str = "docgraph") -> tuple[list[str], list[str]]:
    """(errors, notes) of ``doc`` against docgraph/v1. Errors: the schema's, a later version (refused alone: its other
    keys may mean something else), an id used twice or not prefixed by its type, a source that names no file and no
    tracker object, a check both run and not run, a finding of a check said not run. Notes: what a reader keeps without
    judging: an edge or a finding that names an id the document does not hold (the checks report it), a finding of a
    check this engine does not name (the producer's own)."""
    if not isinstance(doc, dict):
        return [f"{where}: expected a JSON object, got {type(doc).__name__}"], []
    refused = newer(doc)
    if refused:
        return [f"{where}: {refused}"], []
    errors: list[str] = []
    contract = schema.load(KIND)   # versioned by its id: a top-level v is a producer's own key, never a refusal
    schema._validate(doc, contract, contract, where, errors)
    notes: list[str] = []
    seen = _nodes(_list(doc, "nodes"), where, errors)
    _edges(_list(doc, "edges"), seen, where, errors, notes)
    _findings(doc, seen, where, errors, notes)
    return errors, notes


def summary(doc: dict) -> dict:
    """Counts a reader shows: nodes per type, edges per type and origin, findings per severity, checks run and not."""
    def count(items, key):
        out: dict[str, int] = {}
        for x in items:
            if isinstance(x, dict):
                out[str(x.get(key))] = out.get(str(x.get(key)), 0) + 1
        return dict(sorted(out.items()))
    nodes, edges, findings = (_list(doc, k) for k in ("nodes", "edges", "checks"))
    generated = doc.get("generated") if isinstance(doc.get("generated"), dict) else {}
    return {"schema": doc.get("schema"), "by": generated.get("by"),
            "nodes": count(nodes, "type"), "edges": count(edges, "type"), "origins": count(edges, "origin"),
            "findings": count(findings, "severity"),
            "checks_run": len(_list(doc, "checks_run")), "checks_not_run": len(_list(doc, "checks_not_run"))}
