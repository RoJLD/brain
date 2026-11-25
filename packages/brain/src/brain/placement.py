"""Placements as constraints (wi-brain-placement-grammar): where each open item may go among the waves, read at zero
token from its props, for the wave composer (``brain wave propose``) and for ``brain wave placements``.

Two sources, one result:

- ``props.place``, the structured placement (format v1, docs/placements.md): clauses separated by ``;``, each a
  keyword and its arguments: ``wave s11`` (pinned), ``wave s11 or s12`` (a choice), ``earliest s11``, ``latest s12``,
  ``before 1.0`` (before that era's exit), ``after 1.0``, ``after s10`` (the wave after it), ``after wi-a, wi-b``
  (after those items' waves), ``after wi-a past 1.0`` (an ordering that binds only after that era's exit),
  ``with wi-c`` (the same wave), ``own-lot``, ``round 2``, ``proposed`` (a soft placement), ``unplaced`` (no
  constraint: the composer places it), ``out owner|later|trigger[: why]``; an optional first clause ``v1``. A wave is
  named by its place ``sN``, its id or its release ``X.Y.Z``. It is authoritative: when an item has one, its free
  text is not read for placement (it stays as written, for people). An unknown clause is listed and the others read;
  a higher ``v`` is not read at all (listed: a newer brain wrote it).
- the free text the owner's placements were recorded in before: ``props.wave_planned``, ``props.planned_wave``,
  ``props.wave_fit`` and ``props.wave`` (in that order; ``brain wave import``'s ``props.wave`` included), then
  ``props.after_1_0`` (item ids: an ordering that binds only after the 1.0 era's exit), then the ``decided_*``
  answers (newest first, read only for their placement words: a wave ``sN``, « the wave after X.Y.Z », « before
  1.0 », « after 1.0 », « unplaced », « later »), then ``props.track`` (« owner »: out of the waves). A phrase it
  does not know is never guessed: an item whose text yields nothing is listed as unparsed, with its text.

Each open item gets one :class:`Placement`, its constraints resolved to wave places (``seq``: the N of ``wave-sN``,
a legacy wave's place in the order, a future wave's N even before it exists): ``pin``, ``choice``, ``earliest``,
``latest``, ``before`` / ``after_stage`` (an era's stage, its ``props.stage_to``), ``after`` and ``together`` (item
ids), ``own_lot``, ``round``, ``soft``, ``out`` (``owner``, ``later``, ``trigger``: the composer leaves it out, with
its reason), and its ``status``: ``composed`` (in a pending wave now: the plan's fact, the text is history), ``pinned``,
``choice``, ``constrained``, ``free``, ``out``, ``unparsed`` or ``none`` (no placement text). What cannot be honoured
is said, never dropped silently: a pin on a wave already reached or dropped (``stale``), a reference to no wave or no
item, two waves in one text (a choice, put as a question), two sources that disagree (the first one read wins),
a pin before its earliest wave.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import waves

V = 1                 # props.place's format
FORMAT = 1            # brain wave placements --json's
KEY = "place"
TEXT_KEYS = ("wave_planned", "planned_wave", "wave_fit", "wave")
SOFT_AFTER_KEY = "after_1_0"
SOFT_STAGE = "1.0"
TRACK_KEY = "track"
DECIDED = "decided_"
OUT_REASONS = ("owner", "later", "trigger")
STATUSES = ("composed", "pinned", "choice", "constrained", "free", "out", "unparsed", "none")

# a wave reference: a wave id, a place sN (or « wave sN »), a release X.Y.Z, a stage X.Y; never inside a word, a path
# or an id (« roadmap-s8-s12.md » names no wave), and case-sensitive (« S1-S3 » are slices, not waves)
_REF = r"(?:wave-[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?|(?:[Ww]ave\s+)?s\d+|v?\d+\.\d+(?:\.\d+)?)"
_B, _E = r"(?<![\w./-])", r"(?![\w-]|\.\d)"
_ID = r"[a-z][a-z0-9]*(?:-[a-z0-9]+)+"
_IDS = rf"{_ID}(?:'s)?(?:\s*(?:,\s*and|,|and|&)\s*{_ID}(?:'s)?)*"
_ORD = {"next": 1, "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}
_POSS = r"(?:'s(?:\s+release)?)?"

_CHOICE = re.compile(rf"{_B}({_REF}){_E}\s*,?\s+or\s+(?:(?:in\s+)?(the\s+next(?:\s+(?:one|wave))?)|{_B}({_REF}){_E})",
                     re.I)
_WAVE_AFTER = re.compile(rf"(?i:(?:the\s+)?(?:(next|first|second|third|fourth|fifth)\s+)?wave\s+after\s+"
                         rf"(?:release\s+)?){_B}({_REF}){_E}{_POSS}")
_AFTER_REF = re.compile(rf"(?i:\b(?:right\s+|just\s+|only\s+)?after\s+(?:release\s+)?){_B}({_REF}){_E}{_POSS}")
_BEFORE_REF = re.compile(rf"(?i:\bbefore\s+(?:the\s+)?(?:release\s+)?){_B}({_REF}){_E}{_POSS}")
_AFTER_IDS = re.compile(rf"(?i:\bafter\s+)({_IDS})")
_WITH_IDS = re.compile(rf"(?i:\b(?:beside|alongside|with|same\s+wave\s+as|together\s+with)\s+)({_IDS})")
_OWN_LOT = re.compile(r"\b(?:its|their)\s+own\s+lots?\b|\bown[- ]lot\b|\balone\s+in\s+(?:its|a)\s+lot\b", re.I)
_ROUND = re.compile(r"\bround\s+(\d+)\b", re.I)
_FREE = re.compile(r"\bunplaced\b|^\s*none\s*$|\bno\s+fixed\s+wave\b|\bplaced\s+at\s+(?:a\s+wave's|its|the\s+wave's|"
                   r"its\s+wave's)\s+composition\b|\bat\s+(?:its|the)\s+(?:wave's\s+)?composition\b", re.I)
_PIN = re.compile(rf"{_B}({_REF}){_E}")
_TRIGGER = re.compile(r"\b(?:after|once|when|until)\s+[^,;:]+", re.I)
_PROPOSED = re.compile(r"\bproposed\b", re.I)
_LATER = re.compile(r"\bkept\s+for\s+later\b|\bfor\s+later\b|(?:^|[:(])\s*later\b", re.I)
_OWNER = re.compile(r"^\s*owner\b", re.I)
_PAREN = re.compile(r"\([^()]*\)")
_VERSION = re.compile(r"v(\d+)")
_SEQ = re.compile(r"^(?:[Ww]ave\s+)?s(\d+)$")
_STAGE = re.compile(r"^\d+\.\d+$")


@dataclass(frozen=True)
class Ref:
    """A wave named by a placement: ``kind`` seq (``value`` N), wave (an id) or release (X.Y.Z); ``offset`` the waves
    after (+) or before (-) it that are meant (« the wave after 0.6.0 »: +1)."""
    kind: str
    value: str
    offset: int = 0


@dataclass
class Reading:
    """What one prop's text says, before it is resolved against the plan."""
    pins: list[Ref] = field(default_factory=list)
    choices: list[tuple[Ref, ...]] = field(default_factory=list)
    earliest: list[Ref] = field(default_factory=list)
    latest: list[Ref] = field(default_factory=list)
    before: list[str] = field(default_factory=list)       # stages
    after_stage: list[str] = field(default_factory=list)  # stages
    after: list[str] = field(default_factory=list)        # item ids
    soft_after: list[str] = field(default_factory=list)   # item ids, binding only past ``soft_stage``
    soft_stage: str = ""
    together: list[str] = field(default_factory=list)
    own_lot: bool = False
    round: int | None = None
    soft: bool = False
    out: str = ""
    why: str = ""
    triggers: list[str] = field(default_factory=list)
    free: bool = False
    notes: list[str] = field(default_factory=list)
    refused: str = ""   # props.place of a higher v: not read

    def empty(self) -> bool:
        return not (self.pins or self.choices or self.earliest or self.latest or self.before or self.after_stage
                    or self.after or self.soft_after or self.together or self.own_lot or self.round or self.out
                    or self.triggers or self.free)


@dataclass(frozen=True)
class Placement:
    """An open item's placement, resolved to wave places (see the module's docstring)."""
    item: str
    status: str
    wave: str = ""                       # composed: the pending wave it is in now
    pin: int | None = None
    choice: tuple[int, ...] = ()
    earliest: int | None = None
    latest: int | None = None
    before: str = ""                     # a stage: due before that era's exit
    after_stage: str = ""                # a stage: not before that era's exit
    era: str = ""                        # the era whose props.stage_to is ``before`` or ``after_stage``
    after: tuple[str, ...] = ()
    soft_after: tuple[str, ...] = ()
    soft_stage: str = ""
    together: tuple[str, ...] = ()
    own_lot: bool = False
    round: int | None = None
    soft: bool = False
    out: str = ""
    why: str = ""
    source: str = ""                     # ``place``, or the free-text keys read, comma-separated
    texts: tuple[tuple[str, str], ...] = ()
    stale: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()

    def questions(self) -> list[str]:
        """What the composer cannot decide alone: a choice, a conflict, a reference to nothing."""
        out = [f"{self.item}: {c}" for c in self.conflicts]
        if self.choice and not self.conflicts:
            out.append(f"{self.item}: a choice of waves, {' or '.join(f's{n}' for n in self.choice)} (the earlier one "
                       "by default)")
        out += [f"{self.item}: {n}" for n in self.notes if "names no " in n]
        return out

    def canonical(self) -> str:
        """The placement as a props.place v1 value (``brain item set ID place=...``); '' when it says nothing."""
        cl: list[str] = []
        if self.choice:
            cl.append("wave " + " or ".join(f"s{n}" for n in self.choice))
        elif self.pin is not None:
            cl.append(f"wave s{self.pin}")
        if self.earliest is not None:
            cl.append(f"earliest s{self.earliest}")
        if self.latest is not None:
            cl.append(f"latest s{self.latest}")
        if self.before:
            cl.append(f"before {self.before}")
        if self.after_stage:
            cl.append(f"after {self.after_stage}")
        if self.after:
            cl.append("after " + ", ".join(self.after))
        if self.soft_after:
            cl.append("after " + ", ".join(self.soft_after) + f" past {self.soft_stage or SOFT_STAGE}")
        if self.together:
            cl.append("with " + ", ".join(self.together))
        if self.own_lot:
            cl.append("own-lot")
        if self.round is not None:
            cl.append(f"round {self.round}")
        if self.soft:
            cl.append("proposed")
        if self.out:
            cl.append(f"out {self.out}" + (f": {self.why}" if self.why else ""))
        if not cl and self.status == "free":
            cl.append("unplaced")
        return "; ".join(cl)

    def constraints(self) -> list[tuple]:
        """The composer's rules (spec Part 2, step 4): pin, choice, earliest, latest, before_era, after_era, after,
        together, own_lot, out."""
        i = self.item
        out: list[tuple] = []
        if self.pin is not None:
            out.append(("pin", i, self.pin))
        if self.choice:
            out.append(("choice", i, self.choice))
        if self.earliest is not None:
            out.append(("earliest", i, self.earliest))
        if self.latest is not None:
            out.append(("latest", i, self.latest))
        if self.before:
            out.append(("before_era", i, self.era or self.before))
        if self.after_stage:
            out.append(("after_era", i, self.era or self.after_stage))
        out += [("after", i, d) for d in self.after] + [("together", i, t) for t in self.together]
        if self.own_lot:
            out.append(("own_lot", i))
        if self.out:
            out.append(("out", i, self.out))
        return out

    def as_dict(self) -> dict:
        return {"id": self.item, "status": self.status, "wave": self.wave, "pin": self.pin, "choice": list(self.choice),
                "earliest": self.earliest, "latest": self.latest, "before": self.before,
                "after_stage": self.after_stage, "era": self.era, "after": list(self.after),
                "soft_after": list(self.soft_after), "soft_stage": self.soft_stage, "together": list(self.together),
                "own_lot": self.own_lot, "round": self.round, "soft": self.soft, "out": self.out, "why": self.why,
                "source": self.source, "texts": [{"key": k, "text": t} for k, t in self.texts],
                "stale": list(self.stale), "notes": list(self.notes), "conflicts": list(self.conflicts),
                "canonical": self.canonical()}


# --- reading one text ---------------------------------------------------------------------------------------------

def _ref(text: str) -> Ref | str:
    """A wave reference's Ref, or its stage (X.Y) as a str."""
    t = text.strip()
    m = _SEQ.match(t) or waves.SEQ_RE.match(t)
    if m:
        return Ref("seq", m.group(1))
    if t.startswith("wave-"):
        return Ref("wave", t)
    t = t.removeprefix("v")
    if _STAGE.match(t):
        return t
    return Ref("release", t)


def _shift(r: Ref | str, by: int) -> Ref | str:
    return r if isinstance(r, str) else Ref(r.kind, r.value, r.offset + by)


def _ids(raw: str, items: frozenset[str], rd: Reading) -> list[str]:
    """The known item ids of a list (« wi-a, wi-b and wi-c's »); an unknown one is a note."""
    out = []
    for tok in re.split(r"\s*(?:,\s*and|,|and|&)\s*", raw):
        tok = tok.strip().removesuffix("'s")
        if not tok:
            continue
        if tok in items:
            out.append(tok)
        else:
            rd.notes.append(f"names no item: {tok}")
    return out


def _strip_parens(text: str) -> str:
    prev = None
    while prev != text:
        prev, text = text, _PAREN.sub(" ", text)
    return text


def read_text(text: str, items: frozenset[str] = frozenset(), mode: str = "text", self_id: str = "") -> Reading:
    """One free-text prop read for its placement words. ``mode``: ``text`` (wave_planned and the like: everything),
    ``decided`` (a decided_* answer: waves sN, « the wave after X.Y.Z », before or after a stage, unplaced, later),
    ``track`` (« owner »: out), ``soft`` (after_1_0: item ids past the 1.0 exit). The parentheses are provenance:
    only their « proposed » and « later » are read. A clause (between ``;``) that still names another item once its
    « after » and « with » are read speaks of that item: the waves it names are not this item's (a note)."""
    rd = Reading()
    raw = " ".join(str(text or "").split())
    if mode == "track":
        if _OWNER.match(raw):
            rd.out = "owner"
        return rd
    core = _strip_parens(raw)
    if mode == "soft":
        found = [i for i in re.findall(_ID, core) if i in items and i != self_id]
        rd.soft_after, rd.soft_stage = list(dict.fromkeys(found)), SOFT_STAGE
        return rd
    full = mode == "text"
    for clause in core.split(";"):
        _read_clause(rd, clause, items, full, self_id)
    if full:
        rd.soft = bool(_PROPOSED.search(raw))
    if _LATER.search(raw):
        rd.out = "later"
    return rd


def _read_clause(rd: Reading, clause: str, items: frozenset[str], full: bool, self_id: str) -> None:
    """One ``;`` clause of a free text into ``rd``."""
    found = Reading()

    def take(rx: re.Pattern, fn) -> None:
        nonlocal clause
        clause = rx.sub(lambda m: " " if fn(m) is not False else m.group(0), clause)

    def choice(m: re.Match) -> None:
        a = _ref(m.group(1))
        b = _shift(a, 1) if m.group(2) else _ref(m.group(3))
        if isinstance(a, Ref) and isinstance(b, Ref):
            found.choices.append((a, b))

    def wave_after(m: re.Match) -> None:
        r = _ref(m.group(2))
        if isinstance(r, str):
            found.after_stage.append(r)
        else:
            found.pins.append(_shift(r, _ORD.get((m.group(1) or "next").lower(), 1)))

    def after_ref(m: re.Match) -> None:
        r = _ref(m.group(1))
        (found.after_stage.append(r) if isinstance(r, str) else found.earliest.append(_shift(r, 1)))

    def before_ref(m: re.Match) -> None:
        r = _ref(m.group(1))
        (found.before.append(r) if isinstance(r, str) else found.latest.append(_shift(r, -1)))

    def ids_into(target: list[str]):
        def fn(m: re.Match) -> bool:
            if not _known(m.group(1), items):
                return False
            target.extend(_ids(m.group(1), items, rd))
            return True
        return fn

    def pin(m: re.Match) -> None:
        r = _ref(m.group(1))
        if isinstance(r, Ref) and (full or r.kind != "release"):
            found.pins.append(r)

    def free(_m: re.Match) -> None:
        found.free = True

    if full:
        take(_CHOICE, choice)
    take(_WAVE_AFTER, wave_after)
    take(_AFTER_REF, after_ref)
    take(_BEFORE_REF, before_ref)
    if full:
        take(_AFTER_IDS, ids_into(found.after))
        take(_WITH_IDS, ids_into(found.together))
        take(_OWN_LOT, lambda m: setattr(found, "own_lot", True))
        take(_ROUND, lambda m: setattr(found, "round", found.round if found.round is not None else int(m.group(1))))
    take(_FREE, free)
    take(_PIN, pin)
    if full:
        take(_TRIGGER, lambda m: found.triggers.append(m.group(0).strip(" .")))
    others = [i for i in re.findall(_ID, clause) if i in items and i != self_id]
    if others and (found.pins or found.choices):
        rd.notes.append(f"a wave named beside {', '.join(dict.fromkeys(others))}: not read as this item's")
        found.pins, found.choices = [], []
    for name in ("pins", "choices", "earliest", "latest", "before", "after_stage", "after", "together", "triggers"):
        getattr(rd, name).extend(getattr(found, name))
    rd.own_lot = rd.own_lot or found.own_lot
    rd.round = rd.round if rd.round is not None else found.round
    rd.free = rd.free or found.free


def _known(raw: str, items: frozenset[str]) -> bool:
    """A list of ids worth taking: its first one is an item (« after the schema » is not)."""
    first = re.split(r"\s*(?:,\s*and|,|and|&)\s*", raw)[0].strip().removesuffix("'s")
    return first in items


def read_place(text: str, items: frozenset[str] = frozenset()) -> Reading:
    """props.place (format v1, strict): its clauses; an unknown one is a note and the others are read; a higher v
    leaves it unread (``refused``)."""
    rd = Reading()
    clauses = [c.strip() for c in str(text or "").split(";") if c.strip()]
    for n, c in enumerate(clauses):
        m = _VERSION.fullmatch(c)
        if m and n == 0:
            if int(m.group(1)) > V:
                rd.refused = f"v{m.group(1)}"
                return rd
            continue
        word, _, rest = c.partition(" ")
        word, rest = word.lower(), rest.strip()
        if not _clause(rd, word, rest, items):
            rd.notes.append(f"unknown clause {c!r}")
    return rd


def _strict_ref(text: str) -> Ref | str | None:
    t = text.strip()
    return _ref(t) if re.fullmatch(_REF, t) else None


def _clause(rd: Reading, word: str, rest: str, items: frozenset[str]) -> bool:
    """One props.place clause into ``rd``; False when it is not one of v1's."""
    if word == "wave":
        refs = [_strict_ref(p) for p in re.split(r"\s+or\s+", rest)]
        if not refs or any(not isinstance(r, Ref) for r in refs):
            return False
        (rd.pins.append(refs[0]) if len(refs) == 1 else rd.choices.append(tuple(refs)))
        return True
    if word in ("earliest", "latest"):
        r = _strict_ref(rest)
        if not isinstance(r, Ref):
            return False
        (rd.earliest if word == "earliest" else rd.latest).append(r)
        return True
    if word == "before":
        r = _strict_ref(rest)
        if r is None:
            return False
        (rd.before.append(r) if isinstance(r, str) else rd.latest.append(_shift(r, -1)))
        return True
    if word == "after":
        return _after_clause(rd, rest, items)
    if word == "with":
        ids = [i.strip() for i in rest.split(",") if i.strip()]
        rd.together += _known_ids(ids, items, rd)
        return bool(ids)
    if word in ("own-lot", "own_lot") and not rest:
        rd.own_lot = True
        return True
    if word == "round" and rest.isdigit():
        rd.round = int(rest)
        return True
    if word in ("proposed", "unplaced") and not rest:
        setattr(rd, "soft" if word == "proposed" else "free", True)
        return True
    if word == "out":
        reason, _, why = rest.partition(":")
        if reason.strip() not in OUT_REASONS:
            return False
        rd.out, rd.why = reason.strip(), why.strip()
        return True
    return False


def _after_clause(rd: Reading, rest: str, items: frozenset[str]) -> bool:
    head, sep, stage = rest.partition(" past ")
    if sep:
        if not _STAGE.match(stage.strip()):
            return False
        ids = [i.strip() for i in head.split(",") if i.strip()]
        rd.soft_after += _known_ids(ids, items, rd)
        rd.soft_stage = stage.strip()
        return bool(ids)
    r = _strict_ref(rest)
    if r is not None:
        (rd.after_stage.append(r) if isinstance(r, str) else rd.earliest.append(_shift(r, 1)))
        return True
    ids = [i.strip() for i in rest.split(",") if i.strip()]
    if not ids or not all(re.fullmatch(_ID, i) or i in items for i in ids):
        return False
    rd.after += _known_ids(ids, items, rd)
    return True


def _known_ids(ids: list[str], items: frozenset[str], rd: Reading) -> list[str]:
    for i in ids:
        if i not in items:
            rd.notes.append(f"names no item: {i}")
    return [i for i in ids if i in items]


# --- resolving and merging -----------------------------------------------------------------------------------------

@dataclass(frozen=True)
class _Ctx:
    plan: waves.Plan
    pos: dict[str, int]          # wave id -> its place
    by_pos: dict[int, str]       # place -> wave id
    eras: dict[str, str]         # stage -> era id
    items: frozenset[str]

    @classmethod
    def of(cls, plan: waves.Plan) -> _Ctx:
        pos = {w: plan.seq(w) or i + 1 for i, w in enumerate(plan.waves)}
        eras = {}
        for e in plan.eras:
            st = str(waves._props(plan.nodes[e]).get("stage_to") or "").strip()
            if st:
                eras[_stage(st)] = e
        return cls(plan, pos, {n: w for w, n in pos.items()}, eras,
                   frozenset(k for k in plan.nodes if plan.is_item(k)))

    def seq(self, r: Ref) -> tuple[int | None, str]:
        """A Ref's place, or None and why."""
        if r.kind == "seq":
            return int(r.value) + r.offset, ""
        w = self.plan.resolve(r.value)
        if w is None or w not in self.pos:
            return None, f"names no wave: {r.value}"
        return self.pos[w] + r.offset, ""

    def closed(self, n: int) -> str:
        """The status of the wave at place ``n`` when it is reached or dropped, else ''."""
        w = self.by_pos.get(n)
        st = self.plan.status(w) if w else ""
        return st if st in ("reached", "dropped") else ""


def _stage(text: str) -> str:
    """A stage's key: « 1.0 », « 1.0.0 » and « v1.0 » are one."""
    parts = text.strip().removeprefix("v").split(".")
    while len(parts) > 2 and parts[-1] == "0":
        parts.pop()
    return ".".join(parts)


def _sources(node: dict) -> list[tuple[str, str]]:
    """The (key, mode) of an item's placement props, in the order they are read."""
    p = waves._props(node)
    keys = [(k, "text") for k in TEXT_KEYS if str(p.get(k) or "").strip()]
    if str(p.get(SOFT_AFTER_KEY) or "").strip():
        keys.append((SOFT_AFTER_KEY, "soft"))
    keys += [(k, "decided") for k in sorted((k for k in p if k.startswith(DECIDED) and str(p.get(k) or "").strip()),
                                            reverse=True)]
    if str(p.get(TRACK_KEY) or "").strip():
        keys.append((TRACK_KEY, "track"))
    return keys


def place_of(plan: waves.Plan, nid: str, ctx: _Ctx | None = None) -> Placement:
    """The item's placement: props.place when it has one, else its free text, resolved against the plan."""
    ctx = ctx or _Ctx.of(plan)
    node = plan.nodes.get(nid) or {}
    p = waves._props(node)
    now = plan.wave_of(nid)
    composed = now if now and plan.status(now) == "pending" else ""
    raw_place = str(p.get(KEY) or "").strip()
    if raw_place:
        rd = read_place(raw_place, ctx.items)
        if rd.refused:
            return Placement(nid, "composed" if composed else "unparsed", composed, source=KEY,
                             texts=((KEY, raw_place),),
                             notes=(f"props.place {rd.refused} is written by a newer brain, which this engine "
                                    f"(v{V}) does not read: brain update",))
        return _merge(ctx, nid, composed, [(KEY, raw_place, rd)])
    readings = [(k, str(p[k]), read_text(p[k], ctx.items, mode, nid)) for k, mode in _sources(node)]
    # a decided_* answer or a track that says nothing of a placement is not a placement text (most answers are not)
    readings = [r for r in readings if r[0] in TEXT_KEYS or not r[2].empty()]
    return _merge(ctx, nid, composed, readings)


def _merge(ctx: _Ctx, nid: str, composed: str, readings: list[tuple[str, str, Reading]]) -> Placement:
    """The readings of one item, in the order read, into its placement: the first source that names a wave holds the
    pin (a later one that names another is a conflict, listed), the bounds the tightest, the lists their union."""
    notes: list[str] = []
    conflicts: list[str] = []
    stale: list[str] = []
    cpos = ctx.pos.get(composed) if composed else None

    def resolve(refs, key: str, pins: bool = False) -> list[int]:
        """The places of ``refs``; a reference to no wave is a note; a pin on a wave reached or dropped is stale
        (left out), unless the item is composed in a later wave (its history)."""
        found: list[int] = []
        for r in refs:
            n, why_ = ctx.seq(r)
            if n is None:
                notes.append(f"{key}: {why_}")
            elif pins and ctx.closed(n):
                if cpos is None or n > cpos:
                    stale.append(f"{key}: s{n} ({ctx.closed(n)})")
            elif n not in found:
                found.append(n)
        return found

    pin: int | None = None
    choice: tuple[int, ...] = ()
    pin_src = ""
    soft = False
    earliest: list[int] = []
    latest: list[int] = []
    before = after_stage = soft_stage = out = why = ""
    after: list[str] = []
    soft_after: list[str] = []
    together: list[str] = []
    own_lot = free = False
    rnd: int | None = None
    triggers: list[str] = []
    read: list[str] = []
    pin_conflicts: list[str] = []   # dropped when the item is composed: its wave is the plan's fact
    text_read = False
    for key, _text, rd in readings:
        notes += [f"{key}: {n}" for n in rd.notes]
        if rd.empty():
            continue
        read.append(key)
        if key.startswith(DECIDED) and text_read:   # an answer's waves are prose beside a placement text: its
            pins, chs = [], []                       # bounds and its « later » are read, not its waves
        else:
            pins = resolve(rd.pins, key, pins=True)
            chs = [c for c in (resolve(c, key, pins=True) for c in rd.choices) if c]
        text_read = text_read or key in TEXT_KEYS
        named = sorted(set(pins) | {n for c in chs for n in c})
        if not pin_src and named:
            pin_src, soft = key, rd.soft
            if len(pins) > 1 or (pins and chs):
                choice = tuple(named)
                pin_conflicts.append(f"{key} names several waves ({', '.join(f's{n}' for n in named)}): one wave, "
                                     "or the item split")
            elif pins:
                pin = pins[0]
            elif len(chs[0]) > 1:
                choice = tuple(sorted(chs[0]))
            else:
                pin = chs[0][0]
        elif named:
            mine = sorted(set(choice) | ({pin} if pin is not None else set()))
            if named != mine:
                pin_conflicts.append(f"{key} names {', '.join(f's{n}' for n in named)}, {pin_src} "
                                     f"{', '.join(f's{n}' for n in mine)}: {pin_src} is read")
        earliest += resolve(rd.earliest, key)
        latest += resolve(rd.latest, key)
        before = before or (rd.before[0] if rd.before else "")
        after_stage = after_stage or (rd.after_stage[0] if rd.after_stage else "")
        after += rd.after
        soft_after += rd.soft_after
        soft_stage = soft_stage or rd.soft_stage
        together += rd.together
        own_lot = own_lot or rd.own_lot
        rnd = rnd if rnd is not None else rd.round
        free = free or rd.free
        triggers += rd.triggers
        if rd.out and not out:
            out, why = rd.out, rd.why
    if not pin_src:
        soft = any(rd.soft for _, _, rd in readings)
    if before and after_stage and _stage(before) == _stage(after_stage):
        conflicts.append(f"both before and after {before}")
    stage = before or after_stage
    era = ctx.eras.get(_stage(stage), "") if stage else ""
    e = max(earliest) if earliest else None
    lt = min(latest) if latest else None
    if cpos is not None:   # composed: the wave it is in, whatever its text named when it was planned
        pin, choice = cpos, ()
    else:
        conflicts += pin_conflicts
    if pin is not None and e is not None and pin < e:
        conflicts.append(f"{'composed in' if cpos is not None else 'pinned to'} s{pin}, before its earliest wave "
                         f"s{e}")
    if pin is not None and lt is not None and pin > lt:
        conflicts.append(f"{'composed in' if cpos is not None else 'pinned to'} s{pin}, after its latest wave s{lt}")
    hard = pin is not None or bool(choice)
    if out == "later" and hard:
        out, why = "", ""   # a wave named beats a « later »
    bound = e is not None or lt is not None or bool(before or after_stage or after)
    triggers = list(dict.fromkeys(triggers))
    if not out and triggers and not hard and not bound:
        out, why = "trigger", "; ".join(triggers)
    else:
        notes += [f"not read as a constraint: {t}" for t in triggers]
    after = [i for i in dict.fromkeys(after) if i != nid]
    together = [i for i in dict.fromkeys(together) if i != nid]
    soft_after = [i for i in dict.fromkeys(soft_after) if i != nid]
    texts = tuple((k, " ".join(t.split())) for k, t, _ in readings)
    if composed:
        status = "composed"
    elif not texts:
        status = "none"
    elif choice:
        status = "choice"
    elif pin is not None:
        status = "pinned"
    elif out:
        status = "out"
    elif bound or together or own_lot:
        status = "constrained"
    elif free or soft_after or rnd is not None or stale:
        status = "free"
    else:
        status = "unparsed"
    return Placement(nid, status, composed, pin, choice, e, lt, before, after_stage, era, tuple(after),
                     tuple(soft_after), soft_stage, tuple(together), own_lot, rnd, soft, out, why,
                     ", ".join(read), texts, tuple(stale), tuple(dict.fromkeys(notes)), tuple(conflicts))


def placements(plan: waves.Plan, ids=None) -> dict[str, Placement]:
    """The open items' placements (``ids``: those alone), by id."""
    ctx = _Ctx.of(plan)
    want = sorted(ids) if ids else sorted(k for k in plan.nodes if plan.is_item(k) and plan.status(k) in waves.OPEN)
    return {k: place_of(plan, k, ctx) for k in want}


def warnings(plan: waves.Plan) -> list[str]:
    """brain check's warnings on props.place: an unknown clause, an item or a wave it names that is not there, a
    higher v (a newer brain wrote it)."""
    ctx = _Ctx.of(plan)
    out = []
    for k in sorted(k for k in plan.nodes if plan.is_item(k) and plan.status(k) in waves.OPEN
                    and str(waves._props(plan.nodes[k]).get(KEY) or "").strip()):
        pl = place_of(plan, k, ctx)
        out += [f"{k}: {n}" for n in pl.notes if n.startswith("props.place") or n.startswith(f"{KEY}: ")]
    return out


def report(plan: waves.Plan, ids=None) -> dict:
    """``brain wave placements --json`` (``format`` 1, keys only added): the open items' placements, their counts by
    status and the questions they leave."""
    pls = placements(plan, ids)
    counts = {s: 0 for s in STATUSES}
    for p in pls.values():
        counts[p.status] += 1
    return {"format": FORMAT, "place_v": V, "counts": counts, "items": [p.as_dict() for p in pls.values()],
            "questions": [q for p in pls.values() for q in p.questions()]}


def render(rep: dict, every: bool = False) -> list[str]:
    """``brain wave placements``'s text: the items by status (composed ones by wave; those with no placement text
    counted, ``every``: named), then the questions."""
    items = rep["items"]
    with_text = sum(1 for i in items if i["status"] != "none")
    lines = [f"placements of {len(items)} open item(s): {with_text} with a placement, {rep['counts']['none']} "
             f"without (props.place, else {', '.join(TEXT_KEYS)}, {SOFT_AFTER_KEY}, {DECIDED}*, {TRACK_KEY}; zero "
             "token)"]
    for status in STATUSES:
        group = [i for i in items if i["status"] == status]
        if not group:
            continue
        lines.append(f"{status} ({len(group)}):")
        if status == "composed":
            by: dict[str, list[str]] = {}
            for i in group:
                by.setdefault(i["wave"], []).append(i["id"])
            lines += [f"  {w}: {', '.join(ids)}" for w, ids in by.items()]
            continue
        if status == "none" and not every:
            lines.append("  (--all names them)")
            continue
        for i in group:
            head = f"  {i['id']}"
            if i["canonical"]:
                head += f": {i['canonical']}"
            if i["source"]:
                head += f"  ({i['source']})"
            lines.append(head)
            if status == "unparsed":
                lines += [f"    {t['key']}: {t['text']}" for t in i["texts"]]
            lines += [f"    ! {n}" for n in i["stale"] + i["notes"] + i["conflicts"]
                      if status != "none"]
    if rep["questions"]:
        lines.append(f"questions ({len(rep['questions'])}):")
        lines += [f"  {q}" for q in rep["questions"]]
    lines.append("a placement is written as props.place: brain item set ID place=\"wave s11; after ID; own-lot\" "
                 "(docs/placements.md)")
    return lines
