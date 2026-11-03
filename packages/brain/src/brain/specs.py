"""Specs turn active by themselves (wi-brain-spec-auto-activate): ``brain spec activate [--write]``, the step of
``brain sync`` (so of ``brain refresh``) that flips the ready specs, and the line ``brain check`` prints for each
ready one it finds (a main checkout is only checked).

A Spec node still ``proposed`` in a curated nodes file turns ``active`` when all of these hold:

- a decision is recorded: a DDR names it (``links.specs`` of ``records/ddr/*.yaml``, a section after its id is
  ignored: ``spec-x 4.2``), or its props carry ``validated`` or ``decided`` (a spec settled outside the queue);
- every DDR that names it is answered and applied (``integrated`` or ``archived``: ``brain decision ack``);
- it has no ``props.open``;
- its document (the anchor's file) has no unanswered question, as ``research_graph pending`` reads them (what
  ``brain decision pending`` lists);
- its document has no section flagged open for thinking: a line ``<!-- thinking: open -->`` outside code, with an
  optional note (``<!-- thinking: open: the distance function -->``). Prose such as « à réfléchir » is not read: it
  quotes the owner's words in most specs. The section closes when the marker goes (``<!-- thinking: closed -->`` is not
  read, so it may stay as history).

``props.keep_proposed`` (its value: the reason) keeps a spec proposed whatever holds. A flip writes ``status:
active``, ``props.activated`` (the day and the command) and ``props.activated_by`` (the DDRs that closed it, else the
prop that recorded the decision) through brain.graph's checked editor: the node's block changes, nothing else.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import config, decisions, graph, records

APPLIED = ("integrated", "archived")
THINKING_RE = re.compile(r"<!--\s*thinking\s*:\s*open\b\s*:?\s*(.*?)\s*-->", re.IGNORECASE)
_HEADING_RE = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$")
_INLINE_CODE_RE = re.compile(r"`[^`]*`")


@dataclass
class Readiness:
    """One proposed spec: the DDRs that name it, what keeps it proposed (none: ready), its opt-out."""
    id: str
    ddrs: list[str] = field(default_factory=list)
    waits: list[str] = field(default_factory=list)
    kept: str = ""
    settled_by: str = ""  # the prop that records a decision when no DDR names it (validated, decided)

    @property
    def ready(self) -> bool:
        return not self.waits and not self.kept

    def closed_by(self) -> str:
        return ", ".join(self.ddrs) or f"props.{self.settled_by}"

    def line(self) -> str:
        if self.kept:
            return f"{self.id}: kept proposed (props.keep_proposed: {self.kept})"
        if self.ready:
            return f"{self.id}: ready, turns active (closed by {self.closed_by()})"
        return f"{self.id}: stays proposed: {'; '.join(self.waits)}"

    def as_dict(self) -> dict:
        return {"id": self.id, "ready": self.ready, "ddrs": self.ddrs, "waits": self.waits, "kept": self.kept,
                "settled_by": self.settled_by}


def thinking_marks(text: str) -> list[dict]:
    """The open-thinking markers of a Markdown document, outside fenced and inline code: each one's line (1-based),
    the heading it sits under and its note."""
    out, section, fence = [], "", False
    for i, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if line.startswith(("```", "~~~")):
            fence = not fence
            continue
        if fence:
            continue
        h = _HEADING_RE.match(line)
        if h:
            section = h.group(1)
        m = THINKING_RE.search(_INLINE_CODE_RE.sub("", raw))
        if m:
            out.append({"line": i, "section": section, "note": m.group(1)})
    return out


def doc_path(root: Path, node: dict) -> Path | None:
    anchor = str(node.get("anchor") or "").split("#")[0]
    if not anchor:
        return None
    path = Path(anchor)
    return path if path.is_absolute() else root / path


def ddrs_by_spec(root: Path) -> dict[str, list[dict]]:
    """The DDRs of ``records/ddr`` per spec id they name in ``links.specs``."""
    out: dict[str, list[dict]] = {}
    if not (root / records.RECORDS_DIR / "ddr").is_dir():
        return out
    for _, d in decisions.load(root):
        for ref in (d.get("links") or {}).get("specs") or []:
            words = str(ref).split("#")[0].split()
            if words and d not in out.setdefault(words[0], []):
                out[words[0]].append(d)
    return out


def unanswered(root: Path, store: Path) -> dict[str, list[str]] | None:
    """The labels of each spec's unanswered questions, from research_graph pending (a spec with props.validated and
    no props.open is settled: the engine reads none); None when the engine did not run."""
    data = graph.research_graph_json(root, store, "pending")
    if not isinstance(data, dict):
        return None
    return {s["id"]: [str(q.get("label")) for q in s.get("questions") or []] for s in data.get("spec_questions") or []}


def proposed(store: Path) -> dict[str, dict]:
    """The Spec nodes still proposed in the curated nodes files (a generated file is never edited)."""
    return {nid: n for nid, (_, n) in graph.node_index(store, generated=False).items()
            if n.get("type") == "Spec" and n.get("status") == "proposed"}


def readiness(root: Path, store: Path, full: bool = False) -> list[Readiness]:
    """Every proposed spec of the store with what keeps it proposed (none: ready). The questions come from
    research_graph pending (a few seconds: it loads the graph), run only when a spec passes every other check, or
    for every spec not kept with ``full`` (the plan of brain spec activate)."""
    specs = proposed(store)
    if not specs:
        return []
    by_spec = ddrs_by_spec(root)
    out = []
    for nid in sorted(specs):
        node, props = specs[nid], specs[nid].get("props") or {}
        r = Readiness(nid, kept=str(props.get("keep_proposed") or ""))
        ddrs = by_spec.get(nid, [])
        r.ddrs = sorted(d["id"] for d in ddrs if d.get("status") in APPLIED)
        r.settled_by = next((k for k in ("validated", "decided") if props.get(k)), "")
        if not ddrs and not r.settled_by:
            r.waits.append("no decision recorded (no DDR names it in links.specs, no props.validated or decided)")
        asked = sorted(d["id"] for d in ddrs if d.get("status") == "pending")
        unapplied = sorted(d["id"] for d in ddrs if d.get("status") not in APPLIED + ("pending",))
        if asked:
            r.waits.append(f"{len(asked)} DDR(s) waiting on {config.name_of()} ({', '.join(asked)})")
        if unapplied:
            r.waits.append(f"{len(unapplied)} DDR(s) answered, not applied: brain decision ack ({', '.join(unapplied)})")
        if props.get("open"):
            r.waits.append(f"props.open: {decisions._short(props['open'], 80)}")
        path = doc_path(root, node)
        if path is not None and path.is_file():
            for m in thinking_marks(path.read_text(encoding="utf-8")):
                where = f"under '{decisions._short(m['section'], 60)}'" if m["section"] else "before any heading"
                r.waits.append(f"open for thinking {where} (line {m['line']}"
                               + (f": {decisions._short(m['note'], 60)})" if m["note"] else ")"))
        out.append(r)
    asking = [r for r in out if not r.kept and (full or not r.waits)]
    questions = unanswered(root, store) if asking else {}
    for r in asking:
        if questions is None:
            r.waits.append("its questions were not read (research_graph pending did not run)")
        elif questions.get(r.id):
            labels = questions[r.id]
            r.waits.append(f"{len(labels)} unanswered question(s) in its document "
                           f"({', '.join(labels[:6])}{', ...' if len(labels) > 6 else ''})")
    return out


def activate(store: Path, rows: list[Readiness], *, via: str, today: str | None = None) -> list[dict]:
    """Flip the ready specs to active, with props.activated and props.activated_by; the nodes written."""
    day = today or date.today().isoformat()
    done = []
    for r in rows:
        if not r.ready:
            continue

        def change(node: dict, r: Readiness = r) -> None:
            node["status"] = "active"
            props = node.setdefault("props", {})
            props["activated"] = f"{day} by {via} (every decision taken and applied, no thinking phase left)"
            props["activated_by"] = r.closed_by()
        done.append(graph._edit(store, r.id, change))
    return done


def render(rows: list[Readiness], written: bool) -> list[str]:
    lines = [r.line() for r in rows]
    ready = sum(1 for r in rows if r.ready)
    tail = (" turned active" if written else " ready (not written: --write)") if ready else ""
    lines.append(f"specs: {len(rows)} proposed, {ready}{tail or ' ready'}")
    return lines
