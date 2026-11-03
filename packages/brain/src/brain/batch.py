"""The owner's morning decisions: ``brain decision batch [--project P | --all] [--size 4] [--zen [--minutes N]]
[--json]``
and ``brain decision answer --batch FILE|-|JSON`` (wi-brain-batch-decisions; governance spec section 3.2, zen mode).

The pending DDRs of kind decision are gathered into batches ready for Claude Code's question tool (AskUserQuestion: 1
to 4 questions per call, each with a header of 12 characters at most and 2 to 4 options, "Other" added by the tool):

- **ranked as the queue ranks them**: by band (now, this week, when you can), then the score of what each holds up
  (``brain.queue``: priority, count, slip, milestone, deadline, effort, age; the owner's order first), the blocking
  DDRs first in their band, in their own group and flagged (``[BLOQUANT]`` in the question: they were notified when
  asked, ``brain decision ask --blocking``);
- **grouped**: the questions of one brainstorm together (a numbered series of one spec: ``Q1``..``Q8``, ``BRIQUE-1``..,
  ``PB-1``.., in their numbered order, since a later question may lean on an earlier one), else the DDRs of one
  item, else of one spec; a group is placed by its best-ranked DDR, cut in batches of ``size``, and its last batch
  takes the next groups that fit whole;
- **ready for the ask tool**: each batch's ``questions`` is the tool's ``questions`` input as is, its ``ids`` the DDRs
  in the same order; the recommended option first, its label marked ``(Recommandé)`` and its description carrying the
  reason.

``--zen`` is the readable digest of one morning session: the batches that fit in ``--minutes`` (default 5, by an
estimate of reading time; blocking ones always), the options cut to one line, then one line per batch left for later
and what else waits on the owner (``brain queue``). Zero token: the records and the graph, read by script.

``answer_batch`` takes the session's answers back in one call: a JSON object ``{key: value}`` (or
``{"answers": {...}}``, or a list of ``{"id": ..., "choices"|"choice": ..., "other": ..., "notes": ...}``). A key is a
DDR id (or a part only one DDR has) or the question's text as the tool keys its answers (the ``[BLOQUANT]`` flag
ignored). A value is the tool's answer: an option's label (``(Recommandé)`` ignored, any case), several labels joined
by ", " for a multi_select DDR, anything else the owner's own text (``other``); a number is an option's (1-based); a
list holds labels or numbers (anything else in it is the owner's text); an object gives ``choices``, ``other`` and
``notes``
explicitly; an empty value leaves the DDR pending. Every key is resolved before any DDR is written: one bad key writes
nothing.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date
from pathlib import Path

from . import config, decisions, queue

SIZE = 4  # the question tool's maximum per call
HEADER = 12  # the question tool's chip
WIDTH = 118
MINUTES = 5
RECOMMENDED = "(Recommandé)"
BLOCKING = "[BLOQUANT]"
WHY = "Pourquoi : "
READ_WPM = 200  # words read per minute, then CHOOSE_S seconds to choose
CHOOSE_S = 10

_SERIES_RE = re.compile(r"^\s*([A-Za-z]+-?(\d+))\s*(?:[—–:]|-\s)\s*(.*)$")
_HEAD_SEP_RE = re.compile(r"\s*(?::\s|\s[—–-]\s)")
_MARK_RE = re.compile(r"\s*\((?:recommandée?|recommended)\)\s*$", re.I)
_FLAG_RE = re.compile(r"^\s*\[(?:bloquant|blocking)\]\s*", re.I)
_STOP = {
    "a", "an", "the", "of", "to", "for", "in", "on", "at", "by", "and", "or", "is", "are", "be", "it", "its", "do",
    "does", "what", "which", "how", "where", "when", "who", "why", "should", "can", "new", "into", "with",
    "le", "la", "les", "l", "un", "une", "des", "du", "de", "d", "et", "ou", "que", "quoi", "quel", "quelle", "quels",
    "quelles", "comment", "où", "quand", "qui", "pour", "à", "au", "aux", "faut-il", "est-ce", "ce", "se", "sur"}
_PUNCT = "'\"«»“”‘’?!.,;:()[]{}"
_ELISION_RE = re.compile(r"^(?:[lLdD]|[qQ]u)['’]")
_ID_SUFFIX_RE = re.compile(r"\((ddr-[a-z0-9-]+)\)\s*$")


class BatchError(Exception):
    pass


# --- headers and groups ---

def _words(text: str) -> list[str]:
    """The significant words of a title: punctuation, stop words and French elisions (l', d', qu') dropped."""
    out = []
    for w in str(text or "").split():
        w = _ELISION_RE.sub("", w.strip(_PUNCT)).strip(_PUNCT)
        if w and w.lower() not in _STOP:
            out.append(w)
    return out


def header(title: str, n: int = HEADER) -> str:
    """The question tool's chip from a DDR title: a numbered prefix (Q6, BRIQUE-10, PB-3) or the first words,
    then the next significant words while they fit whole in ``n`` characters."""
    title = title or ""
    m = _SERIES_RE.match(title)
    if m:
        head, rest = m.group(1), m.group(3)
    else:  # "Rules lint: a guard for..." -> Rules lint, unless the part before the separator is too long
        parts = _HEAD_SEP_RE.split(title, maxsplit=1)
        head, rest = parts[0].strip(), parts[1] if len(parts) > 1 else ""
        if len(head) > n:
            head, rest = "", title
    words = _words(rest)
    if not head:
        if not words:
            return title[:n].strip() or "?"
        head, words = words[0][:n], words[1:]
    for w in words:
        if len(head) + 1 + len(w) > n:
            break
        head = f"{head} {w}"
    return head[:n]


def _unique(heads: list[str], n: int = HEADER) -> list[str]:
    """Distinct chips within one call: a repeated one gets ' 2', ' 3'..., its text cut to fit."""
    out, seen = [], {}
    for h in heads:
        seen[h] = seen.get(h, 0) + 1
        k = f" {seen[h]}"
        out.append(h if seen[h] == 1 else h[: n - len(k)].rstrip() + k)
    return out


def _series(ddr: dict) -> tuple[str, int] | None:
    m = _SERIES_RE.match(ddr.get("title") or "")
    if not m:
        return None
    return m.group(1)[: -len(m.group(2))].rstrip("-"), int(m.group(2))


def group_of(ddr: dict) -> tuple[str, str]:
    """(key, label) of a DDR's group: a numbered series of one spec (one brainstorm), else its first item, else its
    first spec, else itself."""
    links = ddr.get("links") or {}
    specs, items = links.get("specs") or [], links.get("items") or []
    s = _series(ddr)
    if s:
        where = specs[0] if specs else _day(ddr)
        return f"series:{s[0]}:{where}", f"{s[0]}* ({where})"
    if items:
        return f"item:{items[0]}", items[0]
    if specs:
        return f"spec:{specs[0]}", specs[0]
    return f"ddr:{ddr['id']}", ddr["id"]


def _day(ddr: dict) -> str:
    return str((ddr.get("asked") or {}).get("at", ""))[:10]


# --- the question tool's input ---

def question(ddr: dict) -> dict:
    """One question of AskUserQuestion's input (question, header, options, multiSelect: no other key, the tool
    refuses them): the recommended option first and marked, its description ending with the reason."""
    rec = ddr.get("recommendation") or {}
    opts = []
    for i, o in enumerate(ddr.get("options") or []):
        label, desc = o["label"], " ".join(str(o.get("consequences") or "").split())
        if o.get("risks"):
            desc = f"{desc} Risques : {' '.join(str(o['risks']).split())}".strip()
        if i == 0 and rec.get("option") == label:
            label = f"{label} {RECOMMENDED}"
            if rec.get("why"):
                desc = f"{desc} {WHY}{' '.join(str(rec['why']).split())}".strip()
        opts.append({"label": label, "description": desc or "-"})
    text = " ".join(str(ddr.get("question") or ddr.get("title") or "").split())
    if ddr.get("blocking"):
        text = f"{BLOCKING} {text}"
    return {"question": text, "header": header(ddr.get("title", "")), "options": opts,
            "multiSelect": bool(ddr.get("multi_select"))}


def check_questions(questions: list[dict]) -> list[str]:
    """What the question tool would refuse in one call's input ([] when none)."""
    errs = []
    if not 1 <= len(questions) <= SIZE:
        errs.append(f"{len(questions)} questions (1 to {SIZE} per call)")
    texts = [q["question"] for q in questions]
    if len(set(texts)) != len(texts):
        errs.append("two questions have the same text (the tool keys its answers by it)")
    for q in questions:
        if set(q) != {"question", "header", "options", "multiSelect"}:
            errs.append(f"{q.get('header')}: keys {sorted(q)}")
        if not 1 <= len(q["header"]) <= HEADER:
            errs.append(f"header {q['header']!r}: 1 to {HEADER} characters")
        if not 2 <= len(q["options"]) <= 4:
            errs.append(f"{q['header']}: {len(q['options'])} options (2 to 4)")
        labels = [o["label"] for o in q["options"]]
        if len(set(labels)) != len(labels):
            errs.append(f"{q['header']}: two options have the same label")
        if any(set(o) != {"label", "description"} or not o["description"] for o in q["options"]):
            errs.append(f"{q['header']}: an option needs a label and a description, nothing else")
    return errs


def _seconds(lines: list[str]) -> int:
    """Reading and choosing time of one question, from the lines the zen view shows."""
    return round(sum(len(x.split()) for x in lines) * 60 / READ_WPM) + CHOOSE_S


# --- batches ---

def build(project, *, size: int = SIZE, today: date | None = None, named: bool = False) -> dict:
    """The project's pending decisions in batches for the question tool, in rank order (band, then score), the
    blocking ones before all; and the counts of what else waits on the owner (``brain queue``: actions, permissions, items' open
    questions). The data function of the zen view and of the TUI's Decisions panel. ``named``: each batch's answer
    command names the project (``--all``)."""
    if not 1 <= size <= SIZE:
        raise BatchError(f"--size takes 1 to {SIZE} (the question tool's maximum per call)")
    today = today or date.today()
    data = queue.build(project, today=today, with_graph=False, transcripts=False)
    by_id = {e["id"]: e for e in data["entries"] if e["source"] == "ddr"}
    ddrs = [d for _, d in decisions.load(project.root) if d.get("status") == "pending"
            and decisions.kind_of(d) == "decision" and d.get("id") in by_id] if by_id else []
    groups: dict[str, dict] = {}
    for d in ddrs:
        key, label = ("blocking", "blocking") if d.get("blocking") else group_of(d)
        g = groups.setdefault(key, {"key": key, "label": label, "ddrs": []})
        g["ddrs"].append(d)
    def band(d):
        return queue.BANDS.index(by_id[d["id"]].get("band") or "later")
    for g in groups.values():
        series = g["key"].startswith("series:")
        g["ddrs"].sort(key=lambda d: (_series(d)[1] if series else 0, band(d), -by_id[d["id"]].get("score", 0),
                                      -by_id[d["id"]]["unblocks"], _day(d), d["id"]))
        g["band"] = min(band(d) for d in g["ddrs"])
        g["max"] = max(by_id[d["id"]].get("score", 0) for d in g["ddrs"])
        g["asked"] = min(_day(d) for d in g["ddrs"])
    ordered = sorted(groups.values(), key=lambda g: (g["band"], g["key"] != "blocking", -g["max"], g["asked"],
                                                     g["key"]))
    raw: list[list[tuple[dict, str]]] = []
    for g in ordered:
        chunks = [g["ddrs"][i:i + size] for i in range(0, len(g["ddrs"]), size)]
        for i, chunk in enumerate(chunks):
            fits = raw and i == 0 and len(raw[-1]) + len(chunk) <= size and g["key"] != "blocking" and \
                not raw[-1][0][0].get("blocking") and band(raw[-1][0][0]) == g["band"]
            if fits:
                raw[-1] += [(d, g["label"]) for d in chunk]
            else:
                raw.append([(d, g["label"]) for d in chunk])
    owner = data.get("owner") or config.owner_of()
    batches = [_batch(project.name, i + 1, len(raw), rows, by_id, named, owner) for i, rows in enumerate(raw)]
    rest = [e for e in data["entries"] if e["id"] not in by_id or e["kind"] != "decision"]
    return {"project": project.name, "root": str(project.root), "today": today.isoformat(), "size": size,
            "owner": owner,
            "decisions": len(ddrs), "blocking": sum(1 for d in ddrs if d.get("blocking")), "batches": batches,
            "rest": {"decision": sum(1 for e in rest if e["kind"] == "decision"),
                     "action": sum(1 for e in rest if e["kind"] == "action"),
                     "permission": sum(1 for e in rest if e["kind"] == "permission")}}


def _batch(project: str, n: int, of: int, rows: list[tuple[dict, str]], by_id: dict, named: bool,
           owner: str) -> dict:
    questions = [question(d) for d, _ in rows]
    for q, h in zip(questions, _unique([q["header"] for q in questions])):
        q["header"] = h
    texts = [q["question"] for q in questions]
    for q, (d, _) in zip(questions, rows):
        if texts.count(q["question"]) > 1:
            q["question"] = f"{q['question']} ({d['id']})"
    unblocked = sorted({x for d, _ in rows for x in by_id[d["id"]]["unblocked"]})
    labels = list(dict.fromkeys(label for _, label in rows))
    entries = []
    for (d, label), q in zip(rows, questions):
        e = by_id[d["id"]]
        entries.append({k: v for k, v in {
            "id": d["id"], "header": q["header"], "title": d.get("title", ""), "group": label,
            "blocking": bool(d.get("blocking")), "unblocks": e["unblocks"], "unblocked": e["unblocked"],
            "asked": _day(d), "age_days": e["age_days"], "due": d.get("due"), "band": e.get("band"),
            "score": e.get("score"),
            "recommended": (d.get("recommendation") or {}).get("option"),
            "why": (d.get("recommendation") or {}).get("why"), "context": d.get("context"),
            "blocks": d.get("blocks"), "options": d.get("options"), "multi_select": bool(d.get("multi_select"))
        }.items() if v not in (None, "")})
        entries[-1]["seconds"] = _seconds(_question_lines(0, entries[-1], q))
    bands = [e.get("band") or "later" for e in entries]
    return {"project": project, "n": n, "of": of, "title": " + ".join(labels),
            "band": min(bands, key=queue.BANDS.index) if bands else "later",
            "blocking": any(e["blocking"] for e in entries), "unblocks": len(unblocked), "unblocked": unblocked,
            "seconds": sum(e["seconds"] for e in entries), "ids": [d["id"] for d, _ in rows], "questions": questions,
            "entries": entries,
            "answer": f"brain decision answer --batch @answers.json --via ask-tool --by {owner}"
                      + (f" --project {project}" if named else "")}


def session(data: dict, minutes: int = MINUTES) -> int:
    """How many batches one morning session holds: the blocking ones and those of the band now (they reach the owner
    live), then the next while the reading time stays within ``minutes`` (always one; 0: every batch)."""
    batches = data["batches"]
    if not minutes:
        return len(batches)
    n, spent = 0, 0
    for b in batches:
        if n and not b["blocking"] and b.get("band") != "now" and spent + b["seconds"] > minutes * 60:
            break
        n, spent = n + 1, spent + b["seconds"]
    return n


# --- views ---

def _cut(line, n: int) -> str:
    """A line cut to ``n`` characters, its indentation kept."""
    return queue._cut(str(line), n)


def _mins(seconds: int) -> int:
    return max(1, math.ceil(seconds / 60))


def render(data: dict, width: int = WIDTH) -> list[str]:
    """One line per question, batch by batch."""
    b = data["batches"]
    lines = [f"{data['project']}: {data['decisions']} decision(s) in {len(b)} batch(es) of up to {data['size']}, "
             f"{data['blocking']} blocking (brain decision batch --zen: the morning digest; --json: the question "
             "tool's input)"]
    for x in b:
        lines.append(_cut(f"  batch {x['n']}/{x['of']}{' [blocking]' if x['blocking'] else ''} · {x['title']} · "
                          f"unblocks {x['unblocks']} · ~{_mins(x['seconds'])} min", width))
        for e in x["entries"]:
            rec = f" -> recommended: {e['recommended']}" if e.get("recommended") else ""
            lines.append(_cut(f"    {e['header']:<12} {e['unblocks']:>3}  {e['id']}: {e['title']}{rec}", width))
    lines += _footer(data)
    return lines


def _footer(data: dict) -> list[str]:
    r = data["rest"]
    if not sum(r.values()):
        return []
    return [f"  also waiting on {data.get('owner') or config.NO_OWNER}: {r['decision']} item question(s) without "
            f"options, {r['action']} action(s), {r['permission']} permission(s); with the spec questions and the "
            "denied tool calls: brain queue"]


def _question_lines(i: int, e: dict, q: dict, width: int = WIDTH) -> list[str]:
    """One question of the zen view: the question, its id, a line of context, an option a line, the reason."""
    lines = [f"  {i}. [{e['header']}] {q['question']}",
             f"     {e['id']} · unblocks {e['unblocks']}" + (f" · due {e['due']}" if e.get("due") else "")
             + (" · several choices" if e["multi_select"] else "")]
    if e.get("context"):
        lines.append(f"     {' '.join(e['context'].split())}")
    for letter, o, raw in zip("abcd", q["options"], e["options"]):
        cons = " ".join(str(raw.get("consequences") or "").split())
        lines.append(f"     {letter}) {o['label']}" + (f": {cons}" if cons else ""))
    if e.get("why"):
        lines.append(f"     {WHY}{' '.join(e['why'].split())}")
    return [_cut(x, width) for x in lines]


def zen(data: dict, minutes: int = MINUTES, width: int = WIDTH) -> list[str]:
    """The morning digest: this session's batches in full (options cut to one line), then the later ones in a
    line each."""
    b = data["batches"]
    if not b:
        return [f"{data['project']}: no decision waiting on {config.name_of()}."] + _footer(data)
    n = session(data, minutes)
    now = b[:n]
    lines = [f"Morning decisions — {data['project']}, {data['today']}: {data['decisions']} decision(s) in {len(b)} "
             f"batch(es) of up to {data['size']}, {data['blocking']} blocking.",
             f"This session: {n} batch(es), {sum(len(x['ids']) for x in now)} question(s), about "
             f"{_mins(sum(x['seconds'] for x in now))} min. The full text: notes/decision_queue.md.", ""]
    for x in now:
        lines.append(_cut(f"Batch {x['n']}/{x['of']}{' [BLOQUANT]' if x['blocking'] else ''} · "
                          f"{queue.BAND_NAMES.get(x.get('band'), x.get('band'))} · {x['title']} · "
                          f"unblocks {x['unblocks']} · ~{_mins(x['seconds'])} min", width))
        for i, (e, q) in enumerate(zip(x["entries"], x["questions"]), 1):
            lines += _question_lines(i, e, q, width)
        lines += ["", f"  then: {x['answer']}", ""]
    if b[n:]:
        lines.append(f"Later ({len(b) - n} batch(es), {sum(len(x['ids']) for x in b[n:])} question(s); "
                     "brain decision batch --zen --minutes 0 shows them all):")
        for x in b[n:]:
            lines.append(_cut(f"  {x['n']}/{x['of']} · {queue.BAND_NAMES.get(x.get('band'), x.get('band'))} · "
                              f"{x['title']} · unblocks {x['unblocks']}: "
                              + ", ".join(e["header"] for e in x["entries"]), width))
    lines += _footer(data)
    return lines


# --- the session's answers, in one call ---

def parse(text: str) -> list[tuple[str, object]]:
    """(key, value) pairs from the answers' JSON: an object, {"answers": object}, or a list of objects with an id."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise BatchError(f"the answers are not JSON: {exc}") from exc
    if isinstance(data, dict) and isinstance(data.get("answers"), (dict, list)):
        data = data["answers"]
    if isinstance(data, dict):
        return [(str(k), v) for k, v in data.items()]
    if isinstance(data, list) and all(isinstance(x, dict) and (x.get("id") or x.get("question")) for x in data):
        return [(str(x.get("id") or x.get("question")), {k: v for k, v in x.items() if k not in ("id", "question")})
                for x in data]
    raise BatchError('the answers: {"<DDR id or question>": "<label>", ...}, {"answers": {...}}, or a list of '
                     '{"id": ..., "choices": [...], "other": ..., "notes": ...}')


def _norm(text) -> str:
    return " ".join(_FLAG_RE.sub("", str(text or "")).split()).casefold()


def _ddr_for(entries: list[dict], key: str) -> dict:
    """The DDR a key names: its id, the id a repeated question carries at its end, its question's text (the pending one
    first), else a part of its id only one DDR has."""
    m = _ID_SUFFIX_RE.search(key)
    ref = m.group(1) if m else key
    for d in entries:
        if d.get("id") == ref:
            return d
    by_q = [d for d in entries if decisions.kind_of(d) == "decision" and _norm(d.get("question")) == _norm(key)]
    hits = [d for d in by_q if d.get("status") == "pending"] or by_q or \
        [d for d in entries if key and key in str(d.get("id", ""))]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise BatchError(f"{_cut(key, 80)!r}: no DDR has this id or this question")
    raise BatchError(f"{_cut(key, 80)!r}: several DDRs match ({', '.join(d['id'] for d in hits)})")


def _label(ddr: dict, text) -> str | None:
    """An option's label from the tool's text (marker ignored, any case) or its number; None when it is neither."""
    labels = [o["label"] for o in ddr.get("options") or []]
    if isinstance(text, int) and not isinstance(text, bool):
        return labels[text - 1] if 1 <= text <= len(labels) else None
    t = _MARK_RE.sub("", str(text)).strip().casefold()
    return next((lab for lab in labels if lab.casefold() == t), None)


def _split(ddr: dict, text: str) -> tuple[list[str], str]:
    """A multi_select answer joined by ', ' (labels may hold ', ' themselves): the labels found, the rest as other."""
    tokens = str(text).split(", ")
    picked, other, i = [], [], 0
    while i < len(tokens):
        for j in range(len(tokens), i, -1):
            lab = _label(ddr, ", ".join(tokens[i:j]))
            if lab:
                picked.append(lab)
                i = j
                break
        else:
            other.append(tokens[i])
            i += 1
    return picked, ", ".join(other).strip()


def _value(ddr: dict, value) -> tuple[list[str], str, str] | None:
    """(choices, other, notes) from one answer, None when it is empty (the DDR stays pending)."""
    if value is None or value == "" or value == []:
        return None
    notes = ""
    if isinstance(value, dict):
        notes = str(value.get("notes") or "")
        other = str(value.get("other") or "")
        raw = value.get("choices", value.get("choice"))
        raw = [] if raw is None else raw if isinstance(raw, list) else [raw]
        picked = []
        for r in raw:
            lab = _label(ddr, r)
            if lab is None:
                labels = "; ".join(o["label"] for o in ddr["options"])
                raise BatchError(f"{ddr['id']}: {r!r} is not one of the options ({labels}); free text goes in other")
            picked.append(lab)
        if not picked and not other:
            return None
        return picked, other, notes
    if isinstance(value, list):
        picked, other = [], []
        for v in value:
            lab = _label(ddr, v)
            (picked if lab else other).append(lab or str(v))
        return picked, ", ".join(other), notes
    lab = _label(ddr, value)
    if lab:
        return [lab], "", notes
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        raise BatchError(f"{ddr['id']}: option {value} does not exist ({len(ddr.get('options') or [])} options)")
    if ddr.get("multi_select"):
        picked, other = _split(ddr, str(value))
        return picked, other, notes
    return [], str(value).strip(), notes


def answer_batch(root: Path, text: str, *, by: str = "", via: str = "ask-tool", at: str,
                 again: bool = False) -> dict:
    """Record a session's answers (``by``: config.json's owner by default): every key resolved and checked first,
    then each DDR answered (``decisions.answer``). Returns the DDRs answered and the ids left pending (an empty
    answer)."""
    by = by or config.owner_of()
    pairs = parse(text)
    if not pairs:
        raise BatchError("no answer given")
    entries = [d for _, d in decisions.load(root)]
    plan, skipped, errors, seen = [], [], [], {}
    for key, value in pairs:
        try:
            ddr = _ddr_for(entries, key)
            if ddr["id"] in seen:
                raise BatchError(f"{ddr['id']} is answered twice ({_cut(seen[ddr['id']], 40)!r} and "
                                 f"{_cut(key, 40)!r})")
            seen[ddr["id"]] = key
            if decisions.kind_of(ddr) != "decision":
                raise BatchError(f"{ddr['id']} is of kind {decisions.kind_of(ddr)}: brain queue done {ddr['id']}")
            if ddr.get("status") != "pending" and not again:
                raise BatchError(f"{ddr['id']} is {ddr.get('status')}, not pending (--again replaces the answer)")
            got = _value(ddr, value)
            if got is None or not (got[0] or got[1]):
                skipped.append(ddr["id"])
                continue
            if len(got[0]) > 1 and not ddr.get("multi_select"):
                raise BatchError(f"{ddr['id']} takes one choice (it is not multi_select): {got[0]}")
            plan.append((ddr["id"], *got))
        except BatchError as exc:
            errors.append(str(exc))
    if errors:
        raise BatchError("nothing written:\n  " + "\n  ".join(errors))
    answered = [decisions.answer(root, ddr_id, choices, other=other, notes=notes, by=by, via=via, at=at,
                                 again=again) for ddr_id, choices, other, notes in plan]
    return {"answered": answered, "skipped": skipped}
