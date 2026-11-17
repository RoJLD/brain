"""``brain decision apply``: the owner's answered decisions applied at zero token but the prose (the shipping
process's fourth step: what a session wrote by hand after each batch of answers).

From the answered DDRs (``records/ddr``, status ``answered``: the ids given, else every one of the project, ``--spec``
narrowing to those that name a spec):

- the ADR's skeleton, appended to the decision log: its title (``<who>'s answers of <day> to <CODE-1> to <CODE-n>``,
  the codes the DDRs' titles start with), its Context (the questions, their DDR ids, the specs they come from), its
  Decision (each answer, its option's consequences, the owner's own text); its Why and Revisit if left TODO for the
  session, the one prose a model writes;
- a ``decided_by`` edge from each item a DDR names (``links.items``, a node of the store) to that ADR, and the item's
  ``props.decided_<date>[_<code>]``: who, the ADR, the code and the answer;
- the answers table (Question, Answer, Applied) inserted into each spec the DDRs name, at the end of the section that
  first mentions the first code (else at the end of the spec's file);
- each DDR acknowledged (``brain decision ack``: applied in the ADR, its items and the spec's section, then archived).

The plan first; ``--write`` applies it in that order. A DDR not answered is refused; an item or a spec the store does
not have is said and left out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import decisions, graph, notes

CODE_RE = re.compile(r"^\s*([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d+)\b")   # VIZ-1, TOK-2, TYPO-7: a question's code
HEADING_RE = re.compile(r"^(#{1,6})\s+\S")
FENCE_RE = re.compile(r"^\s*(```|~~~)")


class ApplyError(RuntimeError):
    """No answered DDR to apply, or one that is not answered."""


@dataclass
class Answer:
    id: str
    code: str              # VIZ-1, else the DDR's id
    title: str
    question: str
    context: str
    choices: list[str]
    consequences: list[str]   # the chosen options' consequences, in the choices' order
    other: str
    notes: str
    by: str
    day: str
    via: str
    items: list[str]       # the items it names that the store has
    specs: list[str]

    @property
    def said(self) -> str:
        """The answer as the table says it: « label », and the owner's own text."""
        parts = [f"« {c} »" for c in self.choices]
        if self.other:
            parts.append(f"own text: « {self.other} »")
        return ", ".join(parts) or "no choice recorded"


@dataclass
class SpecTable:
    spec: str
    file: Path | None      # the spec's file, None when its node names none that exists
    at: int                # the line the table goes before (len(lines): the end)
    section: str           # the heading of the section it closes, '' at the end of the file
    text: str              # the table, with its lead line


@dataclass
class Plan:
    answers: list[Answer]
    adr_id: str
    title: str
    fields: dict
    key: str               # the items' props key, decided_<date>[_<code>]
    item_props: dict[str, str] = field(default_factory=dict)   # item -> its decided_ value
    tables: list[SpecTable] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)            # ids a DDR names that the store has not

    def applied_in(self, a: Answer) -> list[str]:
        where = [self.adr_id, *a.items]
        where += [f"{t.spec} {t.section}".strip() for t in self.tables if t.spec in a.specs]
        return where

    def as_dict(self) -> dict:
        return {"adr": {"id": self.adr_id, "title": self.title, **self.fields},
                "ddrs": [{"id": a.id, "code": a.code, "answer": a.said, "items": a.items, "specs": a.specs}
                         for a in self.answers],
                "props_key": self.key, "items": self.item_props,
                "specs": [{"spec": t.spec, "file": str(t.file) if t.file else None, "line": t.at + 1,
                           "section": t.section, "table": t.text} for t in self.tables],
                "unknown": self.unknown}


def _norm(text) -> str:
    return " ".join(str(text or "").split())


def _answer(ddr: dict, known: set[str]) -> Answer:
    ans = ddr.get("answer") or {}
    choices = [str(c) for c in ans.get("choices") or []]
    by_label = {str(o.get("label")): _norm(o.get("consequences")) for o in ddr.get("options") or []
                if isinstance(o, dict)}
    links = ddr.get("links") or {}
    m = CODE_RE.match(str(ddr.get("title") or ""))
    return Answer(str(ddr["id"]), m.group(1) if m else str(ddr["id"]), _norm(ddr.get("title")),
                  _norm(ddr.get("question")), _norm(ddr.get("context")), choices,
                  [by_label.get(c, "") for c in choices], _norm(ans.get("other")), _norm(ans.get("notes")),
                  _norm(ans.get("by")) or "the owner", str(ans.get("at") or "")[:10], _norm(ans.get("via")),
                  [i for i in links.get("items") or [] if i in known],
                  [s for s in links.get("specs") or [] if s in known])


def select(root: Path, ids: list[str], spec: str = "") -> list[dict]:
    """The DDRs to apply: those named (each must be answered), else every answered one (``spec``: naming it)."""
    if ids:
        out = []
        for ref in ids:
            ddr = decisions.find(root, ref)[1]
            if ddr.get("status") != "answered":
                raise ApplyError(f"{ddr['id']} is {ddr.get('status')}: only an answered decision is applied")
            out.append(ddr)
    else:
        out = [d for _, d in decisions.load(root) if d.get("status") == "answered"]
    if spec:
        out = [d for d in out if spec in ((d.get("links") or {}).get("specs") or [])]
    if not out:
        raise ApplyError("no answered decision to apply" + (f" naming {spec}" if spec else ""))
    return sorted(out, key=lambda d: (_code_key(d), str(d.get("id"))))


def _code_key(ddr: dict) -> tuple:
    m = CODE_RE.match(str(ddr.get("title") or ""))
    if not m:
        return ("~",)
    head, _, n = m.group(1).rpartition("-")
    return (head, int(n))


def _codes(answers: list[Answer]) -> str:
    """VIZ-1 to VIZ-4 when they share a prefix and run on, else the list."""
    codes = [a.code for a in answers]
    if len(codes) == 1:
        return codes[0]
    heads = {c.rpartition("-")[0] for c in codes}
    if len(heads) == 1 and all(CODE_RE.match(c) for c in codes):
        return f"{codes[0]} to {codes[-1]}"
    return ", ".join(codes[:-1]) + f" and {codes[-1]}"


def _prefix(answers: list[Answer]) -> str:
    """The codes' shared prefix in lower case (viz), '' when they share none."""
    heads = {a.code.rpartition("-")[0] for a in answers if CODE_RE.match(a.code)}
    return re.sub(r"[^a-z0-9]+", "_", heads.pop().lower()).strip("_") if len(heads) == 1 and \
        all(CODE_RE.match(a.code) for a in answers) else ""


def _who(answers: list[Answer]) -> str:
    return " and ".join(dict.fromkeys(a.by for a in answers))


def _fields(answers: list[Answer]) -> dict:
    specs = list(dict.fromkeys(s for a in answers for s in a.specs))
    via = ", ".join(dict.fromkeys(a.via for a in answers if a.via))
    lead = (f"{_who(answers)} answered {len(answers)} question(s)" + (f" ({via})" if via else "")
            + (f", asked in {', '.join(specs)}" if specs else "") + ":")
    context = [lead, ""] + [f"- {a.code} ({a.id}): {a.question or a.title}" for a in answers]
    decision = []
    for a in answers:
        line = f"- {a.code}: {a.said}"
        why = "; ".join(c for c in a.consequences if c)
        if why:
            line += f": {why}"
        if a.notes:
            line += f" (notes: {a.notes})"
        if a.items:
            line += f". Items: {', '.join(a.items)}"
        decision.append(line + ".")
    return {"context": "\n".join(context), "decision": "\n".join(decision)}


def _table(p: Plan, answers: list[Answer]) -> str:
    day = max(a.day for a in answers)
    via = ", ".join(dict.fromkeys(a.via for a in answers if a.via))
    rows = [f"**{_who(answers)}'s answers ({day}" + (f", {via}" if via else "") + "):**", "",
            "| Question | Answer | Applied |", "|---|---|---|"]
    for a in answers:
        applied = ", ".join([f"`{p.adr_id}`", *(f"`{i}`" for i in a.items)])
        rows.append(f"| {a.code} | {a.said.replace('|', '/')} | {applied} |")
    return "\n".join(rows)


def _spec_file(node: dict, root: Path) -> Path | None:
    anchor = str(node.get("anchor") or "").partition("#")[0]
    f = (root / anchor) if anchor else None
    return f if f is not None and f.is_file() else None


def _place(lines: list[str], code: str) -> tuple[int, str]:
    """(the line the table goes before, the section's heading): the end of the section that first mentions ``code``
    (outside a code fence), else the last section whose heading says « question », else the end of the file."""
    heads: list[tuple[int, int, str]] = []   # (line, level, text)
    fenced, hit = False, None
    for i, line in enumerate(lines):
        if FENCE_RE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = HEADING_RE.match(line)
        if m:
            heads.append((i, len(m.group(1)), line.strip()))
        if hit is None and code and re.search(rf"(?<![\w-]){re.escape(code)}(?![\w-])", line) and heads:
            hit = heads[-1]
    if hit is None:
        hit = next((h for h in reversed(heads) if "question" in h[2].lower()), None)
    if hit is None:
        return len(lines), ""
    start, level, text = hit
    end = next((i for i, lv, _ in heads if i > start and lv <= level), len(lines))
    return end, text.lstrip("#").strip()


def plan(root: Path, store: Path, decision_log: Path, ddrs: list[dict], *, title: str = "",
         day: str | None = None) -> Plan:
    index = graph.node_index(store)
    known = set(index)
    answers = [_answer(d, known) for d in ddrs]
    unknown = sorted({x for d in ddrs for k in ("items", "specs") for x in ((d.get("links") or {}).get(k) or [])
                      if x not in known})
    when = max(a.day for a in answers) or (day or date.today().isoformat())
    title = _norm(title) or f"{_who(answers)}'s answers of {when} to {_codes(answers)}"
    day = day or date.today().isoformat()
    old = notes.read(decision_log)[0] if decision_log.is_file() else ""
    adr = notes.adr_id(day, title, notes.headings(old))
    key = "decided_" + when.replace("-", "_") + (f"_{_prefix(answers)}" if _prefix(answers) else "")
    p = Plan(answers, adr, title, _fields(answers), key, unknown=unknown)
    for a in answers:
        for item in a.items:
            have = str(((index[item][1].get("props") or {}).get(key)) or "")
            text = f"{a.by}, {a.day} ({adr}, {a.code}): {a.said}"
            p.item_props[item] = "; ".join(x for x in (p.item_props.get(item) or have, text) if x)
    for spec in dict.fromkeys(s for a in answers for s in a.specs):
        f = _spec_file(index[spec][1], root)
        mine = [a for a in answers if spec in a.specs]
        at, section = _place(notes.read(f)[0].split("\n"), mine[0].code) if f else (0, "")
        p.tables.append(SpecTable(spec, f, at, section, ""))
    for t in p.tables:
        t.text = _table(p, [a for a in answers if t.spec in a.specs])
    return p


def write(root: Path, store: Path, decision_log: Path, p: Plan, *, at: str, session: str = "",
          day: str | None = None, edges_file: str = "edges/work.yaml") -> list[str]:
    """Apply the plan: the ADR, its edges, the items' props, the spec tables, then the acks. One line each."""
    out = notes.adr_new(decision_log, p.title, p.fields, day=day)
    if out["id"] != p.adr_id:
        raise ApplyError(f"the ADR was written as {out['id']}, not {p.adr_id}: the decision log moved meanwhile")
    lines = [f"adr: {p.adr_id} appended to {decision_log.name}; fill its Why and Revisit if (left TODO)"]
    for item in dict.fromkeys(i for a in p.answers for i in a.items):
        graph.link(store, item, "decided_by", p.adr_id, edges_file, pending={p.adr_id}, via="brain decision apply")
        graph.set_item(store, item, [f"{p.key}={p.item_props[item]}"])
        lines.append(f"item: {item} decided_by {p.adr_id}, props.{p.key}")
    for t in p.tables:
        if t.file is None:
            lines.append(f"spec: {t.spec} has no file: its table is not written")
            continue
        text, nl = notes.read(t.file)
        rows = text.split("\n")
        before = rows[:t.at]
        while before and not before[-1].strip():
            before.pop()
        after = rows[t.at:]
        new = before + ["", *t.text.split("\n"), ""] + (after if any(x.strip() for x in after) else [""])
        notes.write(t.file, "\n".join(new).rstrip("\n") + "\n", nl)
        lines.append(f"spec: {t.spec}: the answers table in {t.file.name}" + (f" (« {t.section} »)" if t.section
                                                                              else " (at its end)"))
    for a in p.answers:
        decisions.ack(root, a.id, p.applied_in(a), session=session, at=at, store=store)
        lines.append(f"ack: {a.id} applied in {', '.join(p.applied_in(a))}, archived")
    return lines


def render(p: Plan, written: list[str] | None = None) -> list[str]:
    lines = [f"apply {len(p.answers)} answered decision(s): {', '.join(a.id for a in p.answers)}"]
    if written is not None:
        lines += written
        lines.append(f"apply: written; then fill {p.adr_id}'s Why and Revisit if, brain sync and brain check")
        return lines
    lines += [f"adr: {p.adr_id}", f"  ## {p.title}", *(f"  {x}" for x in p.fields["context"].split("\n")),
              *(f"  {x}" for x in p.fields["decision"].split("\n")), "  Why, Revisit if: TODO (the session's)"]
    lines += [f"item: {i} decided_by {p.adr_id}; props.{p.key}={v}" for i, v in p.item_props.items()]
    for t in p.tables:
        where = (f"{t.file.name} line {t.at + 1}" + (f", the end of « {t.section} »" if t.section else ", its end")
                 if t.file else "no file")
        lines.append(f"spec: {t.spec}: the answers table ({where})")
    lines += [f"ack: {a.id} --applied {', '.join(p.applied_in(a))}" for a in p.answers]
    lines += [f"not in the store: {x} (left out)" for x in p.unknown]
    lines.append("apply: not written: --write")
    return lines
