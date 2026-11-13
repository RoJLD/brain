"""``brain wave rename`` (wi-brain-wave-ids-decoupled, the owner's WAVES-5): a legacy wave ``wave-X.Y.Z`` renamed once
to an id that carries no version (``wave-sN``, its place), its references rewritten in the store's hand-written node
and edge files, its old id kept in ``props.renamed_from`` where :meth:`brain.waves.Plan.resolve` still finds it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import graph
from .waves import ID_RE, WaveError, _props, load

@dataclass(frozen=True)
class Renaming:
    old: str
    new: str
    files: dict[str, int]   # store-relative file -> the references rewritten
    seq: int
    release: str            # its label after the rename


def _ref_re(wid: str) -> re.Pattern:
    return re.compile(rf"(?<![\w.-]){re.escape(wid)}(?![\w.-])")


def _references(store: Path, rx: re.Pattern) -> dict[str, int]:
    """The hand-written node and edge files of ``store`` that name the wave: store-relative path -> how many times."""
    hand = [store / "edges.yaml", *sorted((store / "nodes").glob("*.yaml")), *sorted((store / "edges").glob("*.yaml"))]
    found = {f.relative_to(store).as_posix(): len(rx.findall(f.read_text(encoding="utf-8")))
             for f in hand if f.is_file() and not f.name.startswith("_generated")}
    return {k: n for k, n in found.items() if n}


def rename(store: Path, ref: str, new: str = "", *, write: bool = False, today: str | None = None) -> Renaming:
    """A wave renamed once to an id that carries no version (the owner's WAVES-5): ``new`` (default ``wave-sN``, its
    place) in every hand-written node and edge file of ``store`` (the items' part_of edges, carried_to and
    carried_via); a pending wave's props.release dropped (its label computed from then on); its old id appended to
    props.renamed_from, so it still resolves. The generated files follow at the next brain sync; the append-only
    logs keep the old id."""
    plan = load(store)
    old = plan.resolve(ref)
    if old is None:
        raise WaveError(f"{ref}: no wave of that id or release")
    seq = plan.seq(old) or plan.waves.index(old) + 1
    new = new or f"wave-s{seq}"
    if not ID_RE.match(new):
        raise WaveError(f"{new}: a wave id is wave-<letters, digits, dashes>, no dot (it carries no version)")
    if new == old or new in plan.nodes:
        raise WaveError(f"{new}: already a node of {store}")
    rx = _ref_re(old)
    files = _references(store, rx)
    pending = plan.status(old) == "pending"
    after = plan.label(old) if not pending else ""
    if write:
        for rel in files:
            f = store / rel
            raw = f.read_bytes().decode("utf-8")
            f.write_bytes(rx.sub(new, raw).encode("utf-8"))
        day = today or date.today().isoformat()
        before = str(_props(plan.nodes[old]).get("renamed_from") or "")
        said = f"{old} (brain wave rename, {day})" + (f"; before: {before}" if before else "")
        graph.set_item(store, new, [f"props.seq={seq}", f"props.renamed_from={said}"]
                       + (["props.release="] if pending else []))
        after = load(store).label(new)
    return Renaming(old, new, files, seq, after)
