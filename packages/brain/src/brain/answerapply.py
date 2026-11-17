"""``brain decision apply``: the owner's answered decisions applied at zero token but the prose (the shipping
process's fourth step: what a session wrote by hand after each batch of answers).

From the answered DDRs (``records/ddr``, status ``answered``: the ids given, else every one of the project, those of
another project left out, ``--spec`` narrowing to those that name a spec):

- the ADR's skeleton, appended to the decision log: its title (``<who>'s answers of <day> to <CODE-1> to <CODE-n>``,
  the codes the DDRs' titles start with), its Context (the questions, their DDR ids, the specs they come from), its
  Decision (each answer, its option's consequences, the owner's own text); its Why and Revisit if left TODO for the
  session, the one prose a model writes;
- a ``decided_by`` edge from each item a DDR names (``links.items``, a curated node of the store) to that ADR, and the
  item's ``props.decided_<date>[_<code>]``: who, the ADR, the code and the answer;
- the answers table (Question, Answer, Applied) inserted into each spec the DDRs name, at the end of the section that
  first mentions the first code (outside a code fence), else of the last section whose heading says « question »,
  else at the end of the spec's file (a file inside the root);
- each DDR acknowledged (``brain decision ack``: applied in the ADR, its items and the spec's section it was written
  in, then archived).

The plan first; ``--write`` applies it in that order, refused before anything is written while the store has no
``decided_by`` edge type or the log already holds that ADR (a run that stopped part way: finished by hand). A DDR not
answered is refused; an item or a spec the store does not have is said and left out.
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
    """No answered DDR to apply, one that is not answered, or a plan --write refuses."""


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
    file: Path | None      # the spec's file, None when its node names none that exists inside the root
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
    problems: list[str] = field(default_factory=list)           # what refuses --write

    def applied_in(self, a: Answer) -> list[str]:
        """Where the DDR is applied: the ADR, its items, the spec sections a table is written in."""
        where = [self.adr_id, *a.items]
        where += [f"{t.spec} {t.section}".strip() for t in self.tables if t.spec in a.specs and t.file]
        return where

    def as_dict(self) -> dict:
        return {"adr": {"id": self.adr_id, "title": self.title, **self.fields},
                "ddrs": [{"id": a.id, "code": a.code, "answer": a.said, "items": a.items, "specs": a.specs}
                         for a in self.answers],
                "props_key": self.key, "items": self.item_props,
                "specs": [{"spec": t.spec, "file": str(t.file) if t.file else None, "line": t.at + 1,
                           "section": t.section, "table": t.text} for t in self.tables],
                "unknown": self.unknown, "problems": self.problems}


def _norm(text) -> str:
    return " ".join(str(text or "").split())


def _code_of(title) -> str:
    m = CODE_RE.match(str(title or ""))
    return m.group(1) if m else ""


def _linked(ddr: dict, key: str, known: set[str]) -> list[str]:
    return [x for x in (ddr.get("links") or {}).get(key) or [] if x in known]


def _answer(ddr: dict, known: set[str]) -> Answer:
    ans = ddr.get("answer") or {}
    choices = [str(c) for c in ans.get("choices") or []]
    by_label = {str(o.get("label")): _norm(o.get("consequences")) for o in ddr.get("options") or []
                if isinstance(o, dict)}
    return Answer(str(ddr["id"]), _code_of(ddr.get("title")) or str(ddr["id"]), _norm(ddr.get("title")),
                  _norm(ddr.get("question")), _norm(ddr.get("context")), choices,
                  [by_label.get(c, "") for c in choices], _norm(ans.get("other")), _norm(ans.get("notes")),
                  _norm(ans.get("by")) or "the owner", str(ans.get("at") or "")[:10], _norm(ans.get("via")),
                  _linked(ddr, "items", known), _linked(ddr, "specs", known))


def select(root: Path, ids: list[str], spec: str = "", project: str = "") -> list[dict]:
    """The DDRs to apply: those named (each must be answered), else every answered one of ``project`` (a DDR that
    names another project in links.project is left out); ``spec``: those naming it."""
    if ids:
        out = [_named(root, ref) for ref in ids]
    else:
        out = [d for _, d in decisions.load(root) if d.get("status") == "answered"
               and str((d.get("links") or {}).get("project") or project) == project]
    if spec:
        out = [d for d in out if spec in ((d.get("links") or {}).get("specs") or [])]
    if not out:
        raise ApplyError("no answered decision to apply" + (f" naming {spec}" if spec else ""))
    return sorted(out, key=lambda d: (_code_key(d), str(d.get("id"))))


def _named(root: Path, ref: str) -> dict:
    ddr = decisions.find(root, ref)[1]
    if ddr.get("status") != "answered":
        raise ApplyError(f"{ddr['id']} is {ddr.get('status')}: only an answered decision is applied")
    return ddr


def _unknown(ddrs: list[dict], known: set[str]) -> list[str]:
    """The items and specs the DDRs name that the store has not."""
    named = {x for d in ddrs for k in ("items", "specs") for x in ((d.get("links") or {}).get(k) or [])}
    return sorted(named - known)


def _code_key(ddr: dict) -> tuple:
    code = _code_of(ddr.get("title"))
    if not code:
        return ("~",)
    head, _, n = code.rpartition("-")
    return (head, int(n))


def _codes(answers: list[Answer]) -> str:
    """VIZ-1 to VIZ-4 when they share a prefix, else the list."""
    codes = [a.code for a in answers]
    if len(codes) == 1:
        return codes[0]
    if _prefix(answers):
        return f"{codes[0]} to {codes[-1]}"
    return ", ".join(codes[:-1]) + f" and {codes[-1]}"


def _prefix(answers: list[Answer]) -> str:
    """The codes' shared prefix in lower case (viz), '' when they share none."""
    if not all(CODE_RE.match(a.code) for a in answers):
        return ""
    heads = {a.code.rpartition("-")[0] for a in answers}
    return re.sub(r"[^a-z0-9]+", "_", heads.pop().lower()).strip("_") if len(heads) == 1 else ""


def _who(answers: list[Answer]) -> str:
    return " and ".join(dict.fromkeys(a.by for a in answers))


def _via(answers: list[Answer]) -> str:
    return ", ".join(dict.fromkeys(a.via for a in answers if a.via))


def _decision_line(a: Answer) -> str:
    line = f"- {a.code}: {a.said}"
    why = "; ".join(c for c in a.consequences if c)
    line += f": {why}" if why else ""
    line += f" (notes: {a.notes})" if a.notes else ""
    line += f". Items: {', '.join(a.items)}" if a.items else ""
    return line + "."


def _fields(answers: list[Answer]) -> dict:
    specs = list(dict.fromkeys(s for a in answers for s in a.specs))
    via = _via(answers)
    lead = (f"{_who(answers)} answered {len(answers)} question(s)" + (f" ({via})" if via else "")
            + (f", asked in {', '.join(specs)}" if specs else "") + ":")
    context = [lead, ""] + [f"- {a.code} ({a.id}): {a.question or a.title}" for a in answers]
    return {"context": "\n".join(context), "decision": "\n".join(_decision_line(a) for a in answers)}


def _table(p: Plan, answers: list[Answer]) -> str:
    day = max(a.day for a in answers)
    via = _via(answers)
    rows = [f"**{_who(answers)}'s answers ({day}" + (f", {via}" if via else "") + "):**", "",
            "| Question | Answer | Applied |", "|---|---|---|"]
    for a in answers:
        applied = ", ".join([f"`{p.adr_id}`", *(f"`{i}`" for i in a.items)])
        rows.append(f"| {a.code} | {a.said.replace('|', '/')} | {applied} |")
    return "\n".join(rows)


def _spec_file(node: dict, root: Path) -> Path | None:
    """The spec's file from its anchor: a file inside ``root``, else None."""
    anchor = str(node.get("anchor") or "").partition("#")[0]
    if not anchor:
        return None
    f = (root / anchor).resolve()
    return f if f.is_file() and f.is_relative_to(root.resolve()) else None


def _unfenced(lines: list[str]):
    """(index, line) of each line outside a code fence."""
    fenced = False
    for i, line in enumerate(lines):
        if FENCE_RE.match(line):
            fenced = not fenced
        elif not fenced:
            yield i, line


def _place(lines: list[str], code: str) -> tuple[int, str]:
    """(the line the table goes before, the section's heading): the end of the section that first mentions ``code``
    (outside a code fence), else the last section whose heading says « question », else the end of the file."""
    mention = re.compile(rf"(?<![\w-]){re.escape(code)}(?![\w-])") if code else None
    heads: list[tuple[int, int, str]] = []   # (line, level, text)
    hit = None
    for i, line in _unfenced(lines):
        m = HEADING_RE.match(line)
        if m:
            heads.append((i, len(m.group(1)), line.strip()))
        if hit is None and heads and mention and mention.search(line):
            hit = heads[-1]
    hit = hit or next((h for h in reversed(heads) if "question" in h[2].lower()), None)
    if hit is None:
        return len(lines), ""
    start, level, text = hit
    end = next((i for i, lv, _ in heads if i > start and lv <= level), len(lines))
    return end, text.lstrip("#").strip()


def _item_props(p: Plan, curated: dict) -> None:
    for a in p.answers:
        for item in a.items:
            have = str((curated[item][1].get("props") or {}).get(p.key) or "")
            text = f"{a.by}, {a.day} ({p.adr_id}, {a.code}): {a.said}"
            p.item_props[item] = "; ".join(x for x in (p.item_props.get(item) or have, text) if x)


def _tables(p: Plan, index: dict, root: Path) -> None:
    for spec in dict.fromkeys(s for a in p.answers for s in a.specs):
        mine = [a for a in p.answers if spec in a.specs]
        f = _spec_file(index[spec][1], root)
        at, section = _place(notes.read(f)[0].split("\n"), mine[0].code) if f else (0, "")
        p.tables.append(SpecTable(spec, f, at, section, ""))
        p.tables[-1].text = _table(p, mine)


def _problems(store: Path, old: str, day: str, title: str) -> list[str]:
    out = []
    if "decided_by" not in (graph.load_schema(store).get("edge_types") or []):
        out.append(f"decided_by: not an edge type of {store / 'schema.yaml'}")
    if (day, title) in notes.headings(old):
        out.append(f"the decision log already holds « {day} — {title} »: a run stopped part way? finish it by hand "
                   "(brain decision ack), or give another --title")
    return out


def plan(root: Path, store: Path, decision_log: Path, ddrs: list[dict], *, title: str = "",
         day: str | None = None) -> Plan:
    index = graph.node_index(store)
    curated = graph.node_index(store, generated=False)   # the items set_item can write
    known = set(curated) | {i for i, (_, n) in index.items() if n.get("type") == "Spec"}
    answers = [_answer(d, known) for d in ddrs]
    unknown = _unknown(ddrs, known)
    day = day or date.today().isoformat()
    when = max(a.day for a in answers) or day
    title = _norm(title) or f"{_who(answers)}'s answers of {when} to {_codes(answers)}"
    old = notes.read(decision_log)[0] if decision_log.is_file() else ""
    key = "decided_" + when.replace("-", "_") + (f"_{_prefix(answers)}" if _prefix(answers) else "")
    p = Plan(answers, notes.adr_id(day, title, notes.headings(old)), title, _fields(answers), key,
             unknown=unknown, problems=_problems(store, old, day, title))
    _item_props(p, curated)
    _tables(p, index, root)
    return p


def _write_table(t: SpecTable) -> None:
    text, nl = notes.read(t.file)
    rows = text.split("\n")
    before = rows[:t.at]
    while before and not before[-1].strip():
        before.pop()
    after = rows[t.at:]
    new = before + ["", *t.text.split("\n"), ""] + (after if any(x.strip() for x in after) else [""])
    notes.write(t.file, "\n".join(new).rstrip("\n") + "\n", nl)


def write(root: Path, store: Path, decision_log: Path, p: Plan, *, at: str, session: str = "",
          day: str | None = None, edges_file: str = "edges/work.yaml") -> list[str]:
    """Apply the plan: the ADR, its edges, the items' props, the spec tables, then the acks. One line each."""
    if p.problems:
        raise ApplyError("; ".join(p.problems))
    out = notes.adr_new(decision_log, p.title, p.fields, day=day)
    if out["id"] != p.adr_id:
        raise ApplyError(f"the ADR was written as {out['id']}, not {p.adr_id}: the decision log moved meanwhile")
    lines = [f"adr: {p.adr_id} appended to {decision_log.name}; fill its Why and Revisit if (left TODO)"]
    for item in dict.fromkeys(i for a in p.answers for i in a.items):
        graph.link(store, item, "decided_by", p.adr_id, edges_file, pending={p.adr_id}, via="brain decision apply")
        graph.set_item(store, item, [f"{p.key}={p.item_props[item]}"])
        lines.append(f"item: {item} decided_by {p.adr_id}, props.{p.key}")
    # bottom up: a table inserted lower in a file leaves the planned lines of the ones above it where they were
    for t in sorted(p.tables, key=lambda t: (str(t.file), -t.at)):
        if t.file is None:
            lines.append(f"spec: {t.spec} has no file in the root: its table is not written")
            continue
        _write_table(t)
        lines.append(f"spec: {t.spec}: the answers table in {t.file.name}" + (f" (« {t.section} »)" if t.section
                                                                              else " (at its end)"))
    for a in p.answers:
        decisions.ack(root, a.id, p.applied_in(a), session=session, at=at, store=store)
        lines.append(f"ack: {a.id} applied in {', '.join(p.applied_in(a))}, archived")
    return lines


def _plan_lines(p: Plan) -> list[str]:
    lines = [f"adr: {p.adr_id}", f"  ## {p.title}", *(f"  {x}" for x in p.fields["context"].split("\n")),
             *(f"  {x}" for x in p.fields["decision"].split("\n")), "  Why, Revisit if: TODO (the session's)"]
    lines += [f"item: {i} decided_by {p.adr_id}; props.{p.key}={v}" for i, v in p.item_props.items()]
    for t in p.tables:
        where = f"{t.file.name} line {t.at + 1}, " if t.file else "no file in the root: not written"
        where += (f"the end of « {t.section} »" if t.section else "its end") if t.file else ""
        lines.append(f"spec: {t.spec}: the answers table ({where})")
    lines += [f"ack: {a.id} --applied {', '.join(p.applied_in(a))}" for a in p.answers]
    return lines


def render(p: Plan, written: list[str] | None = None) -> list[str]:
    lines = [f"apply {len(p.answers)} answered decision(s): {', '.join(a.id for a in p.answers)}"]
    lines += [f"refused: {x}" for x in p.problems]
    lines += written if written is not None else _plan_lines(p)
    lines += [f"not in the store: {x} (left out)" for x in p.unknown]
    lines.append(f"apply: written; then fill {p.adr_id}'s Why and Revisit if, brain sync and brain check"
                 if written is not None else "apply: not written: --write" if not p.problems else
                 "apply: nothing written")
    return lines
