"""Work-item priorities: proposals that the owner validates, then ``apply``.

A proposal is ``props.priority_proposed`` (P0-P3) with a one-line ``props.priority_reason``. The owner validates them
in bulk, or changes some; ``apply`` then renames ``priority_proposed`` to ``priority`` in the node files (keeping the
reason), or sets the value the owner chose. Nothing is written without ``write=True`` (``--write``).

    research_graph priorities proposal [--markdown]
    research_graph priorities apply [--only ID,..] [--skip ID,..] [--set ID=P1 ..] [--write]

Edits are textual and touch only the item's own props mapping, so comments, layout and the other items stay as
they are; every edit is checked by parsing the file again (only the intended keys of the intended node changed).
The node files use the flow style ``- {id: ..., props: {...}}``; an item written otherwise is refused.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import networkx as nx

from . import yamlio
from .model import WORK_OPEN
from .query import PRIORITIES

_PLAIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-/]*$")


class EditError(ValueError):
    pass


def _scalar(value: Any) -> str:
    """YAML text for a value: a plain word when it is one (P1, spec-x), else a double-quoted string."""
    text = str(value)
    if _PLAIN.match(text) and text.lower() not in {"yes", "no", "true", "false", "null", "on", "off"}:
        return text
    return json.dumps(text, ensure_ascii=False)


def _close(text: str, i: int) -> int:
    """Index of the bracket closing the one at ``i``, skipping quoted scalars."""
    depth, j, quote = 0, i, None
    while j < len(text):
        c = text[j]
        if quote:
            if quote == '"' and c == "\\":
                j += 2
                continue
            if c == quote:
                if quote == "'" and text[j + 1:j + 2] == "'":
                    j += 2
                    continue
                quote = None
        elif c in "\"'" and (j == 0 or text[j - 1] in "{[,: \t\r\n"):
            quote = c
        elif c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    raise EditError("unbalanced brackets")


def _value_end(text: str, j: int, limit: int) -> int:
    if text[j] in "{[":
        return _close(text, j) + 1
    if text[j] in "\"'":
        quote, k = text[j], j + 1
        while k < limit:
            if quote == '"' and text[k] == "\\":
                k += 2
                continue
            if text[k] == quote:
                if quote == "'" and text[k + 1:k + 2] == "'":
                    k += 2
                    continue
                return k + 1
            k += 1
        raise EditError("unterminated quoted scalar")
    k = j
    while k < limit and text[k] not in ",}]":
        k += 1
    while k > j and text[k - 1] in " \t\r\n":
        k -= 1
    return k


def _entries(text: str, open_: int, close: int) -> dict[str, tuple[int, int, int]]:
    """key -> (key start, value start, value end) of a flow mapping's own entries."""
    out: dict[str, tuple[int, int, int]] = {}
    j = open_ + 1
    while j < close:
        while j < close and text[j] in " \t\r\n,":
            j += 1
        if j >= close:
            break
        colon = text.index(":", j)
        key = text[j:colon].strip()
        v = colon + 1
        while text[v] in " \t":
            v += 1
        end = _value_end(text, v, close)
        out[key] = (j, v, end)
        j = end
    return out


def _item(text: str, nid: str) -> tuple[int, int]:
    m = re.search(rf"(?m)^- \{{\s*id:\s*[\"']?{re.escape(nid)}[\"']?\s*,", text)
    if not m:
        raise EditError(f"{nid}: not found as a flow mapping (`- {{id: {nid}, ...}}`)")
    open_ = text.index("{", m.start())
    return open_, _close(text, open_)


def edit_props(text: str, nid: str, *, set_: Mapping[str, Any] | None = None,
               rename: Mapping[str, str] | None = None) -> str:
    """Rename props keys (old -> new, keeping the value unless ``set_`` gives the new key one), then set keys:
    replace the value of a key present, add the others at the end of the props mapping, on a new line aligned with
    its first key (or add a ``props`` mapping on a new line)."""
    set_ = dict(set_ or {})
    open_, close = _item(text, nid)
    entries = _entries(text, open_, close)
    if "props" not in entries:
        if not set_:
            raise EditError(f"{nid}: no props to rename")
        body = ", ".join(f"{k}: {_scalar(v)}" for k, v in set_.items())
        return text[:close] + f",\n   props: {{{body}}}" + text[close:]
    _, p_open, p_end = entries["props"]
    if text[p_open] != "{":
        raise EditError(f"{nid}: props is not a flow mapping")
    p_close = p_end - 1
    props = _entries(text, p_open, p_close)
    edits: list[tuple[int, int, str]] = []
    for old, new in (rename or {}).items():
        if old not in props:
            raise EditError(f"{nid}: no props.{old} to rename")
        if new in props:
            raise EditError(f"{nid}: props.{new} already set")
        k_start, v_start, v_end = props[old]
        edits.append((k_start, k_start + len(old), new))
        if new in set_:
            edits.append((v_start, v_end, _scalar(set_.pop(new))))
    for key in list(set_):
        if key in props:
            _, v_start, v_end = props[key]
            edits.append((v_start, v_end, _scalar(set_.pop(key))))
    if set_:
        body = ", ".join(f"{k}: {_scalar(v)}" for k, v in set_.items())
        if props:
            first = min(k for k, _, _ in props.values())
            indent = first - (text.rfind("\n", 0, first) + 1)
            last_end = max(e for _, _, e in props.values())
            edits.append((last_end, last_end, ",\n" + " " * indent + body))
        else:
            edits.append((p_open + 1, p_close, body))
    for start, end, new_text in sorted(edits, reverse=True):
        text = text[:start] + new_text + text[end:]
    return text


def _nodes(text: str) -> dict[str, dict]:
    data = yamlio.loads(text) or []
    return {n["id"]: n for n in data if isinstance(n, dict) and "id" in n}


def _check(before: str, after: str, nid: str, keys: Iterable[str]) -> None:
    """Only ``keys`` of ``nid``'s props changed; anything else is a bug in the textual edit."""
    old, new = _nodes(before), _nodes(after)
    keys = set(keys)
    if set(old) != set(new):
        raise EditError(f"{nid}: the edit changed which nodes the file holds")
    for n in old:
        a, b = dict(old[n]), dict(new[n])
        pa, pb = a.pop("props", {}) or {}, b.pop("props", {}) or {}
        if a != b:
            raise EditError(f"{n}: the edit changed more than its props")
        if n != nid and pa != pb:
            raise EditError(f"{n}: the edit of {nid} changed another node")
        if n == nid and {k: v for k, v in pa.items() if k not in keys} != \
                {k: v for k, v in pb.items() if k not in keys}:
            raise EditError(f"{nid}: the edit changed other props")


def _files(store: str | Path) -> list[Path]:
    return sorted((Path(store) / "nodes").glob("*.yaml"))


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def _write(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


def _locate(store: str | Path) -> dict[str, Path]:
    where: dict[str, Path] = {}
    for f in _files(store):
        for nid in _nodes(_read(f)):
            where.setdefault(nid, f)
    return where


@dataclass(frozen=True)
class Change:
    id: str
    file: str
    proposed: str | None
    priority: str
    reason: str | None

    def line(self) -> str:
        how = (f"{self.proposed}? -> {self.priority}" if self.proposed == self.priority
               else f"{self.proposed or '-'}? -> {self.priority} (the owner's value)")
        return f"{self.id}: {how}"


def _check_priority(value: str, what: str) -> str:
    value = value.upper()
    if value not in PRIORITIES:
        raise EditError(f"{what}: {value!r} is not one of {', '.join(PRIORITIES)}")
    return value


def apply_priorities(store: str | Path, *, only: Iterable[str] | None = None, skip: Iterable[str] = (),
                     overrides: Mapping[str, str] | None = None, write: bool = False) -> list[Change]:
    """Turn proposals into ``props.priority``. Every item with ``priority_proposed`` and no ``priority`` is
    validated as proposed, except those in ``skip`` (and, with ``only``, those not in it); ``overrides`` (id ->
    P0-P3) validates an item with the owner's value instead, and may set an item that has no proposal. Returns the
    changes; writes the node files only with ``write``."""
    overrides = {k: _check_priority(v, k) for k, v in (overrides or {}).items()}
    only = set(only) if only is not None else None
    skip = set(skip)
    where = _locate(store)
    unknown = sorted((set(overrides) | (only or set()) | skip) - set(where))
    if unknown:
        raise EditError(f"unknown ids: {', '.join(unknown)}")
    texts: dict[Path, str] = {}
    changes: list[Change] = []
    for nid, path in sorted(where.items()):
        if nid in skip or (only is not None and nid not in only and nid not in overrides):
            continue
        text = texts.get(path, _read(path))
        props = _nodes(text)[nid].get("props") or {}
        proposed = props.get("priority_proposed")
        if props.get("priority") or (not proposed and nid not in overrides):
            continue
        value = overrides.get(nid, _check_priority(str(proposed), nid) if proposed else None)
        if proposed:
            new = edit_props(text, nid, rename={"priority_proposed": "priority"}, set_={"priority": value})
        else:
            new = edit_props(text, nid, set_={"priority": value})
        _check(text, new, nid, {"priority", "priority_proposed"})
        texts[path] = new
        changes.append(Change(nid, path.name, proposed, value, props.get("priority_reason")))
    if write:
        for path, text in texts.items():
            _write(path, text)
    return changes


def propose(store: str | Path, proposals: Mapping[str, tuple[str, str]], *, write: bool = False) -> list[str]:
    """Add ``priority_proposed`` and ``priority_reason`` (id -> (P0-P3, reason)) to items; returns the ids. An item
    that already has ``priority`` is refused: a proposal never hides a validated priority."""
    where = _locate(store)
    unknown = sorted(set(proposals) - set(where))
    if unknown:
        raise EditError(f"unknown ids: {', '.join(unknown)}")
    texts: dict[Path, str] = {}
    for nid, (value, reason) in sorted(proposals.items()):
        path = where[nid]
        text = texts.get(path, _read(path))
        if (_nodes(text)[nid].get("props") or {}).get("priority"):
            raise EditError(f"{nid}: already has a priority")
        new = edit_props(text, nid, set_={"priority_proposed": _check_priority(value, nid),
                                          "priority_reason": reason})
        _check(text, new, nid, {"priority_proposed", "priority_reason"})
        texts[path] = new
    if write:
        for path, text in texts.items():
            _write(path, text)
    return sorted(proposals)


def proposal_rows(g: nx.DiGraph) -> list[dict]:
    """Open items with a proposal and no validated priority, by proposed priority then id."""
    rows = []
    for n, a in g.nodes(data=True):
        p = a.get("props") or {}
        if a.get("type") == "WorkItem" and a.get("status") in WORK_OPEN and p.get("priority_proposed") \
                and not p.get("priority"):
            rows.append({"id": n, "status": a.get("status"), "title": a.get("title") or "",
                         "priority_proposed": str(p["priority_proposed"]), "reason": p.get("priority_reason") or ""})
    order = {p: i for i, p in enumerate(PRIORITIES)}
    return sorted(rows, key=lambda r: (order.get(r["priority_proposed"], 9), r["id"]))


def _short(text: str, n: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def render_proposal(g: nx.DiGraph, *, title_width: int = 110) -> str:
    """Markdown tables of the proposals, one per proposed priority."""
    rows = proposal_rows(g)
    out = []
    for p in PRIORITIES:
        group = [r for r in rows if r["priority_proposed"] == p]
        if not group:
            continue
        out += ["", f"## {p} ({len(group)})", "", "| Item | Status | Title | Why |", "|---|---|---|---|"]
        for r in group:
            title = _short(r["title"], title_width).replace("|", "\\|")
            out.append(f"| `{r['id']}` | {r['status']} | {title} | {r['reason'].replace('|', '/')} |")
    return "\n".join(out).lstrip("\n") + "\n" if out else "(no proposal)\n"
