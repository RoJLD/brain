"""``brain wave rename`` (wi-brain-wave-ids-decoupled, the owner's WAVES-5): a legacy wave ``wave-X.Y.Z`` renamed once
to an id that carries no version (``wave-sN``, its place), its references rewritten in the store's node and edge files
(the generated ones too, so the store loads before the next brain sync), its old id kept in ``props.renamed_from``
where :meth:`brain.waves.Plan.resolve` still finds it.

Only YAML values are rewritten: an ``id``, an edge's ``from`` and ``to``, an item's ``carried_to`` and each id of its
``carried_via``; a comment or a free text that names the old id is left as written. A default title
(« Wave <old release> ») becomes « Wave sN ».
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import graph
from .waves import ID_RE, WaveError, _props, load


@dataclass(frozen=True)
class Renaming:
    old: str
    new: str
    files: dict[str, int]   # store-relative hand-written file -> the references rewritten
    seq: int
    release: str            # its label after the rename
    generated: dict[str, int] = field(default_factory=dict)   # the generated files (brain sync's) rewritten too
    title: str = ""         # the default title it gets, '' when its title is kept


def _value_res(wid: str) -> tuple[re.Pattern, re.Pattern]:
    """(an id, from, to or carried_to whose value is ``wid``; a carried_via value that holds it)."""
    old = re.escape(wid)
    key = r"(?:^[ \t]*(?:-[ \t]+)?|[{,][ \t]*)"   # a key at a line's start (a list item's too), or in a flow mapping
    single = re.compile(rf"({key}(?:id|from|to|carried_to)[ \t]*:[ \t]*)([\"']?){old}\2(?=[ \t]*(?:[,}}\]#]|$))",
                        re.M)
    via = re.compile(rf"({key}carried_via[ \t]*:[ \t]*)([\"'])([^\"'\n]*)\2"   # quoted: the whole value
                     rf"|(^[ \t]*(?:-[ \t]+)?carried_via[ \t]*:[ \t]*)([^\"'\s#{{}}][^\n#]*)"   # block: to its end
                     rf"|([{{,][ \t]*carried_via[ \t]*:[ \t]*)([^\"'\s#{{}},][^\n#,}}]*)", re.M)   # flow: to , or }}
    return single, via


def _rewrite(text: str, old: str, new: str) -> tuple[str, int]:
    """``text`` with the YAML values naming ``old`` rewritten to ``new``, and how many."""
    single, via = _value_res(old)
    text, n = single.subn(lambda m: f"{m.group(1)}{m.group(2)}{new}{m.group(2)}", text)
    token = re.compile(rf"(?<![\w.-]){re.escape(old)}(?![\w.-])")
    count = [n]

    def one(m: re.Match) -> str:
        if m.group(1) is not None:
            value, k = token.subn(new, m.group(3))
            count[0] += k
            return f"{m.group(1)}{m.group(2)}{value}{m.group(2)}"
        lead, raw = (m.group(4), m.group(5)) if m.group(4) is not None else (m.group(6), m.group(7))
        value, k = token.subn(new, raw)
        count[0] += k
        return f"{lead}{value}"
    text = via.sub(one, text)
    return text, count[0]


def _files(store: Path) -> list[Path]:
    """The store's node and edge files, the generated ones included."""
    return [f for f in [store / "edges.yaml", *sorted((store / "nodes").glob("*.yaml")),
                        *sorted((store / "edges").glob("*.yaml"))] if f.is_file()]


def _references(store: Path, old: str, new: str) -> dict[str, int]:
    """Each node or edge file of ``store`` whose values name the wave: store-relative path -> how many."""
    found = {f.relative_to(store).as_posix(): _rewrite(f.read_text(encoding="utf-8"), old, new)[1]
             for f in _files(store)}
    return {k: n for k, n in found.items() if n}


def _generated(rel: str) -> bool:
    return rel.rsplit("/", 1)[-1].startswith("_generated")


def _check_new(plan, old: str, new: str, store: Path) -> None:
    if not ID_RE.match(new):
        raise WaveError(f"{new}: a wave id is wave-<letters, digits, dashes>, no dot (it carries no version)")
    if new == old or new in plan.nodes:
        raise WaveError(f"{new}: already a node of {store}")
    taken = next((w for w in plan.waves if w != old and new in plan.former(w)), None)
    if taken:
        raise WaveError(f"{new}: a former id of {taken} (props.renamed_from), which it still resolves to")


def rename(store: Path, ref: str, new: str = "", *, write: bool = False, today: str | None = None) -> Renaming:
    """A wave renamed once to an id that carries no version (the owner's WAVES-5): ``new`` (default ``wave-sN``, its
    place) in the YAML values of every node and edge file of ``store`` (its id, the edges' from and to, the items'
    carried_to and carried_via; the generated files too, so the store loads before brain sync rebuilds them); a
    pending wave's props.release dropped (its label computed from then on); a default title « Wave <old release> »
    made « Wave sN »; its old id appended to props.renamed_from, so it still resolves. The append-only logs keep the
    old id."""
    plan = load(store)
    old = plan.resolve(ref)
    if old is None:
        raise WaveError(f"{ref}: no wave of that id or release")
    seq = plan.seq(old) or plan.waves.index(old) + 1
    new = new or f"wave-s{seq}"
    _check_new(plan, old, new, store)
    refs = _references(store, old, new)
    files = {k: n for k, n in refs.items() if not _generated(k)}
    generated = {k: n for k, n in refs.items() if _generated(k)}
    pending = plan.status(old) == "pending"
    title = str(plan.nodes[old].get("title") or "")
    retitle = f"Wave s{seq}" if title in (f"Wave {old.removeprefix('wave-')}", f"Wave {plan.label(old)}") else ""
    after = plan.label(old) if not pending else ""
    if write:
        _write(store, plan, refs, (old, new, seq), pending, retitle, today)
        after = load(store).label(new)
    return Renaming(old, new, files, seq, after, generated, retitle)


def _write(store: Path, plan, refs: dict[str, int], names: tuple[str, str, int], pending: bool, retitle: str,
           today: str | None) -> None:
    """The rename written: each file's values, then the wave's props (seq, renamed_from; a pending wave's release
    dropped) and its default title. ``names``: (the old id, the new one, its place)."""
    old, new, seq = names
    for rel in refs:
        f = store / rel
        f.write_bytes(_rewrite(f.read_bytes().decode("utf-8"), old, new)[0].encode("utf-8"))
    day = today or date.today().isoformat()
    before = str(_props(plan.nodes[old]).get("renamed_from") or "")
    said = f"{old} (brain wave rename, {day})" + (f"; before: {before}" if before else "")
    graph.set_item(store, new, [f"props.seq={seq}", f"props.renamed_from={said}"]
                   + (["props.release="] if pending else []) + ([f"title={retitle}"] if retitle else []))
