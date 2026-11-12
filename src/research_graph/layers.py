"""``research_graph layers``: graph templates as layers (spec-brain-graph-templates, GT-1 and GT-5).

A layer is a fragment of a store's schema.yaml kept as data in the package (``templates/layers/<name>.yaml``): its node
types, its edge types with the endpoints each allows, its statuses and levels, its mode (``written`` by commands,
``generated`` by a sync, ``projected`` to a tool), the commands and views it feeds, the checks it gets, its GitNexus
projection and fictitious examples (ids ``example-*``, or a fictitious repo ``example`` where the engine fixes the id's
shape). The catalogue holds the layers real stores have proven; a domain template composes them and adds its own
layer file; the owner's own types go in a layer of their own (``local`` by convention), which nothing here touches.

A store's schema.yaml is the union of its layers (:func:`compose`): a node type belongs to one layer only (two layers
may share an edge name: an edge is a name), ``templates:`` records each layer's version and ``endpoints:`` the edge
endpoints research_graph check verifies (validate.endpoint_errors). Adding a layer to a store is a plan, then its
write (:func:`add_plan`): the schema's own text is kept, the new types, edges, statuses and layer appended, and the
result checked by parsing it back and loading the store with it. Nothing is ever removed or renamed here: a type
renamed or retired is a migration (brain template upgrade, a later item).

    research_graph layers [--json]                          the catalogue, and the store's layers
    research_graph layers show NAME [--json]                one layer
    research_graph layers compose NAME... [--owner X]       the schema.yaml those layers make
    research_graph layers add NAME... [--write]             add them to --store: the plan, then --write
    research_graph layers propose --typology T --stage S    the layers that stage proposes that the store lacks
"""

from __future__ import annotations

import difflib
import re
import textwrap
from dataclasses import dataclass, field
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

import yaml

from . import yamlio
from .loader import ValidationError, load_store
from .schema import ANY, parse_schema
from .validate import endpoint_errors

LAYERS = files(__package__) / "templates" / "layers"
MODES = ("written", "generated", "projected")
REQUIRED = ("name", "version", "title", "mode", "node_types", "statuses")
KEYS = set(REQUIRED) | {"requires", "generator", "edge_types", "status_by_type", "levels", "required_props", "ids",
                        "commands", "views", "checks", "projection", "lifecycle", "examples"}
NAME_RE = re.compile(r"[a-z][a-z0-9_]*")
# the schema.yaml keys a composition writes, in order
SCHEMA_KEYS = ("templates", "node_types", "edge_types", "statuses", "levels", "layers", "status_by_type",
               "required_props", "endpoints")
LIST_KEYS = ("templates", "node_types", "edge_types", "statuses", "levels")
MAP_KEYS = ("layers", "status_by_type", "required_props", "endpoints")
WIDTH = 120


class LayerError(ValueError):
    """A layer file, a name or a composition that does not hold: nothing is composed or written."""


@dataclass(frozen=True)
class Layer:
    name: str
    version: int
    title: str
    mode: str
    node_types: dict[str, str]
    edges: dict[str, tuple[dict, ...]]          # edge -> its {from, to} pairs as written ("*" or a list), maybe none
    statuses: tuple[str, ...]
    requires: tuple[str, ...] = ()
    status_by_type: dict[str, tuple[str, ...]] = field(default_factory=dict)
    levels: tuple[str, ...] = ()
    required_props: dict[str, tuple[str, ...]] = field(default_factory=dict)
    data: dict = field(default_factory=dict, compare=False)   # the file as read: commands, views, examples...
    source: str = ""

    def lifecycle(self) -> dict:
        return self.data.get("lifecycle") or {}

    def ref(self) -> dict:
        """Its entry in a schema's ``templates:``."""
        return {"layer": self.name, "version": self.version}


# --- reading a layer -----------------------------------------------------------------------------------------------

def _strs(value, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise LayerError(f"{where}: a list of names")
    return tuple(value)


def _end(value, where: str):
    if value == ANY or (isinstance(value, list) and value and all(isinstance(v, str) and v for v in value)):
        return value
    raise LayerError(f"{where}: a list of node types or \"*\"")


def _keys(data, where: str) -> None:
    if not isinstance(data, dict):
        raise LayerError(f"{where}: a mapping")
    said = [f"misses {', '.join(k for k in REQUIRED if k not in data)}"] if set(REQUIRED) - set(data) else []
    said += [f"unknown key(s) {', '.join(sorted(set(data) - KEYS))}"] if set(data) - KEYS else []
    if said:
        raise LayerError(f"{where}: " + "; ".join(said))


def _whole(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 1


# a layer's head: (the key, what it must be, what it is said to be)
_HEAD = (("name", lambda v: isinstance(v, str) and bool(NAME_RE.fullmatch(v)), "name is lower case letters, digits "
                                                                                "and '_'"),
         ("version", _whole, "version is a whole number, 1 or more"),
         ("mode", lambda v: v in MODES, f"mode is one of {', '.join(MODES)}"),
         ("node_types", lambda v: isinstance(v, dict) and all(isinstance(t, str) and t for t in v),
          "node_types maps each type to a line that says what it is"))


def _head(data, source: str) -> str:
    """The layer's name, once its keys, name, version, mode and types hold."""
    _keys(data, f"layer {source or '?'}")
    for key, ok, said in _HEAD:
        if not ok(data[key]):
            raise LayerError(f"layer {data['name'] if key != 'name' else source or '?'}: {said}")
    return data["name"]


def _pairs(et: str, spec, where: str) -> tuple[dict, ...]:
    """An edge type's {from, to} pairs: a mapping with from and to, a list of them, or a mapping without (none)."""
    if not isinstance(spec, (list, dict)):
        raise LayerError(f"{where}: edge_types[{et}]: a {{from, to, why}} mapping, a list of them, or {{why}}")
    pairs = spec if isinstance(spec, list) else ([spec] if "from" in spec or "to" in spec else [])
    out = []
    for i, p in enumerate(pairs):
        if not isinstance(p, dict) or "from" not in p or "to" not in p:
            raise LayerError(f"{where}: edge_types[{et}][{i}]: from and to")
        out.append({"from": _end(p["from"], f"{where}: edge_types[{et}][{i}].from"),
                    "to": _end(p["to"], f"{where}: edge_types[{et}][{i}].to")})
    return tuple(out)


def _per_type(raw, types, key: str, where: str, allowed=None) -> dict[str, tuple[str, ...]]:
    """``status_by_type`` or ``required_props``: {one of its types: names}, a status among ``allowed``."""
    out = {}
    for t, names in (raw or {}).items():
        if t not in types:
            raise LayerError(f"{where}: {key}: {t!r} is not one of its types")
        out[t] = _strs(names, f"{where}: {key}[{t}]")
        stray = sorted(set(out[t]) - set(allowed)) if allowed is not None else []
        if stray:
            raise LayerError(f"{where}: {key}[{t}]: {stray} not in statuses")
    return out


def parse_layer(data, source: str = "") -> Layer:
    """A layer from a layer file's data, checked."""
    name = _head(data, source)
    where = f"layer {name}"
    types = data["node_types"]
    statuses = _strs(data["statuses"], f"{where}: statuses")
    edges = {et: _pairs(et, spec, where) for et, spec in (data.get("edge_types") or {}).items()}
    return Layer(name, data["version"], str(data["title"]), data["mode"], dict(types), edges, statuses,
                 _strs(data.get("requires"), f"{where}: requires"),
                 _per_type(data.get("status_by_type"), types, "status_by_type", where, statuses),
                 _strs(data.get("levels"), f"{where}: levels"),
                 _per_type(data.get("required_props"), types, "required_props", where), data, source)


def load_layer_file(path: str | Path) -> Layer:
    """A layer of a file of its own (a domain template's layer)."""
    try:
        data = yamlio.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise LayerError(f"layer file {path}: {exc}") from exc
    return parse_layer(data, str(path))


def _one_layer_each(layers, where: str) -> None:
    """A node type belongs to one layer only."""
    owner: dict[str, str] = {}
    for layer in layers:
        for t in layer.node_types:
            if t in owner:
                raise LayerError(f"{where}type {t} is in layers {owner[t]} and {layer.name}: a type belongs to one "
                                 "layer")
            owner[t] = layer.name


@lru_cache(maxsize=1)
def catalogue() -> dict[str, Layer]:
    """The engine's layers, by name: each file's name is its layer's, a node type is in one layer only, and what a
    layer requires is in the catalogue."""
    out: dict[str, Layer] = {}
    for f in sorted((p for p in LAYERS.iterdir() if p.name.endswith(".yaml")), key=lambda p: p.name):
        layer = parse_layer(yamlio.loads(f.read_text(encoding="utf-8")), f"templates/layers/{f.name}")
        if f.name != f"{layer.name}.yaml":
            raise LayerError(f"templates/layers/{f.name}: holds layer {layer.name!r}")
        out[layer.name] = layer
    _one_layer_each(out.values(), "the catalogue: ")
    unknown = [(la.name, r) for la in out.values() for r in la.requires if r not in out]
    if unknown:
        raise LayerError(f"layer {unknown[0][0]}: requires {unknown[0][1]!r}, which is not in the catalogue")
    return out


def resolve(names, extra: dict[str, Layer] | None = None) -> list[Layer]:
    """The layers ``names`` names with what they require, each once, a layer after those it requires; ``extra``:
    layers of files of their own (a domain template's), by name, never one of the catalogue's names."""
    cat, extra = catalogue(), dict(extra or {})
    clash = sorted(set(extra) & set(cat))
    if clash:
        raise LayerError(f"layer {', '.join(clash)}: a name of the catalogue's; a template's own layer has its own")
    known = {**cat, **extra}
    out: list[Layer] = []

    def visit(name: str, path: tuple[str, ...]) -> None:
        if any(la.name == name for la in out):
            return
        if name in path:
            raise LayerError(f"layers: a cycle of requires: {' -> '.join(path + (name,))}")
        if name not in known:
            raise LayerError(f"layer {name!r}: not in the catalogue ({', '.join(sorted(cat))})")
        for r in known[name].requires:
            visit(r, path + (name,))
        out.append(known[name])

    for n in names:
        visit(n, ())
    return out


# --- composing ----------------------------------------------------------------------------------------------------

def _union(seqs) -> list:
    out: list = []
    for seq in seqs:
        out += [x for x in seq if x not in out]
    return out


# what each layer gives to a schema's list and mapping keys
_LISTS = {"node_types": lambda la: list(la.node_types), "edge_types": lambda la: list(la.edges),
          "statuses": lambda la: list(la.statuses), "levels": lambda la: list(la.levels)}
_MAPS = {"layers": lambda la: {la.name: list(la.node_types)},
         "status_by_type": lambda la: {t: list(s) for t, s in la.status_by_type.items()},
         "required_props": lambda la: {t: list(k) for t, k in la.required_props.items()}}


def _grown_endpoints(ends: dict, new: list[Layer], ends_for: set[str] | None) -> dict:
    """``ends`` with the pairs of ``new``'s edges (those in ``ends_for``; None: every edge), each pair once."""
    out = dict(ends)   # an edge the layers leave alone keeps its text's form (a mapping or a list)
    for la in new:
        for et, pairs in la.edges.items():
            if pairs and (ends_for is None or et in ends_for):
                have = _listed(out.get(et))
                out[et] = have + [dict(p) for p in pairs if p not in have]
    return out


def _listed(value) -> list:
    return [] if value is None else list(value) if isinstance(value, list) else [value]


def merged(data: dict, new: list[Layer], ends_for: set[str] | None = None) -> dict:
    """The schema data ``data`` becomes with the layers ``new`` added (``data`` empty: their composition). An empty
    optional key stays out."""
    out = dict(data)
    for key, of in _LISTS.items():
        value = _union([data.get(key) or []] + [of(la) for la in new])
        if value or key in data:
            out[key] = value
    for key, of in _MAPS.items():
        value = dict(data.get(key) or {})
        for la in new:
            value.update(of(la))
        if value or key in data:
            out[key] = value
    ends = _grown_endpoints(data.get("endpoints") or {}, new, ends_for)
    if ends:
        out["endpoints"] = ends
    out["templates"] = list(data.get("templates") or []) + [la.ref() for la in new]
    return out


def compose_layers(layers: list[Layer], owner: str | None = None) -> dict:
    """The schema data of ``layers`` (resolved), ``owner`` first when given; refused unless the loader accepts it."""
    _one_layer_each(layers, "")
    data = {**({"owner": owner} if owner else {}), **merged({}, layers)}
    parse_schema(data)
    return data


def compose(names, owner: str | None = None, extra: dict[str, Layer] | None = None) -> dict:
    return compose_layers(resolve(names, extra), owner)


# --- the text ----------------------------------------------------------------------------------------------------

def flow(value) -> str:
    """One value in YAML flow style (a list, a mapping, a scalar), as a schema.yaml line holds it."""
    return yaml.safe_dump(value, default_flow_style=True, width=10**6, sort_keys=False,
                          allow_unicode=True).strip().removesuffix("...").strip()


def _continuation(items: list[str], col: int, first: str = "") -> list[str]:
    """``first`` then ``items``, the lines after the first indented by ``col``, wrapped at :data:`WIDTH`, the last
    one closing the list."""
    lines, line = [], first or " " * col
    for i, item in enumerate(items):
        piece = item + (", " if i < len(items) - 1 else "]")
        if len(line) + len(piece.rstrip()) > WIDTH and line.strip() and not line.endswith("["):
            lines.append(line.rstrip())
            line = " " * col
        line += piece
    return lines + [line]


def _wrapped(head: str, items: list[str]) -> list[str]:
    """``head [a, b, ...]`` wrapped at :data:`WIDTH`, the continuation lines under the first item."""
    return _continuation(items, len(head) + 1, head + "[") if items else [head + "[]"]


def _entry(pad: str, key: str, value) -> list[str]:
    """One entry of a mapping: a list of names wrapped, another value on its line, or as a block list when that line
    would pass :data:`WIDTH`."""
    if isinstance(value, list) and all(isinstance(x, str) for x in value):
        return _wrapped(f"{pad}{key}: ", [flow(x) for x in value])
    line = f"{pad}{key}: {flow(value)}"
    if len(line) <= WIDTH or not isinstance(value, list):
        return [line]
    return [f"{pad}{key}:"] + [f"{pad}  - {flow(x)}" for x in value]


def _key_lines(key: str, value) -> list[str]:
    if key == "templates":
        return ["templates:   # the catalogue's layers that composed this schema (research_graph layers)"] + \
            [f"  - {flow(t)}" for t in value]
    if isinstance(value, list):
        return _wrapped(f"{key}: ", [flow(v) for v in value])
    return [f"{key}:"] + [ln for k, v in value.items() for ln in _entry("  ", k, v)]


def render(data: dict, header: str = "") -> str:
    """A schema.yaml text for a composition (:func:`compose`)."""
    out = [f"# {ln}".rstrip() for ln in header.splitlines()] if header else []
    if data.get("owner"):
        out.append(f"owner: {flow(data['owner'])}")
    for key in SCHEMA_KEYS:
        if key in data:
            out += _key_lines(key, data[key])
    return "\n".join(out) + "\n"


def header_for(layers: list[Layer]) -> str:
    text = ("The vocabulary of this graph store, composed from the catalogue's layers (research_graph layers): "
            f"{', '.join(la.name for la in layers)}. research_graph check validates every node and edge against it, "
            "endpoints included. Add a layer with research_graph layers add NAME (a plan, then --write); your own "
            "types go in a layer of your own (local), which no command of the catalogue touches.")
    return "\n".join(textwrap.wrap(text, WIDTH - 2))


# --- a store's layers --------------------------------------------------------------------------------------------

def store_layers(data: dict) -> dict:
    """What a schema's data holds of the catalogue: ``recorded`` (its ``templates:``), ``present`` (the catalogue's
    layers whose name and types it has, or recorded), ``exact`` (those whose types are the catalogue's, no more),
    ``other`` (its layers that are not the catalogue's)."""
    cat = catalogue()
    layers = {n: set(ts or []) for n, ts in (data.get("layers") or {}).items()}
    recorded = _recorded(data)
    present = [n for n in layers if set(getattr(cat.get(n), "node_types", {None})) <= layers[n]]
    exact = [n for n in present if set(cat[n].node_types) == layers[n]]
    present += [n for n, _ in recorded if n in cat and n not in present]
    return {"recorded": recorded, "present": present, "exact": exact, "other": [n for n in layers if n not in cat]}


def _recorded(data: dict) -> list[tuple[str, int]]:
    return [(t.get("layer"), t.get("version")) for t in data.get("templates") or [] if isinstance(t, dict)]


def proposed(typology: str, stage: str) -> list[Layer]:
    """The catalogue's layers a typology may take and a stage proposes (each layer's ``lifecycle``)."""
    def takes(lc: dict) -> bool:
        typ, at = lc.get("typologies") or [], lc.get("proposed_at") or []
        return (ANY in typ or typology in typ) and (ANY in at or stage in at)
    return [la for la in catalogue().values() if takes(la.lifecycle())]


# --- editing a schema's text ---------------------------------------------------------------------------------------

_TOP = re.compile(r"^(?!-\s|-$)[^\s#]")   # a top-level key: not a comment, nor a list item at the margin


def _block(lines: list[str], key: str) -> tuple[int, int] | None:
    """(the line of top-level ``key:``, the end of its block: the next top-level line) or None."""
    pat = re.compile(rf"^{re.escape(key)}\s*:")
    start = next((i for i, ln in enumerate(lines) if pat.match(ln)), None)
    if start is None:
        return None
    end = next((j for j in range(start + 1, len(lines)) if _TOP.match(lines[j])), len(lines))
    return start, end


def _last_content(lines: list[str], start: int, end: int) -> int:
    """The block's last line that is neither blank nor a comment at the margin (one that heads the next key)."""
    return max([k for k in range(start + 1, end) if lines[k].strip() and not lines[k].startswith("#")],
               default=start)


def _strip_comment(line: str) -> str:
    """The line without a trailing comment (not inside quotes)."""
    quote = None
    for i, ch in enumerate(line):
        if quote:
            quote = None if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i].rstrip()
    return line.rstrip()


def _value(line: str) -> str:
    return _strip_comment(line).split(":", 1)[1].strip()


def _pad(lines: list[str], start: int, end: int, default: str = "  ") -> str:
    """The indentation of the block's first entry."""
    first = next((lines[k] for k in range(start + 1, end) if lines[k].strip() and
                  not lines[k].lstrip().startswith("#")), None)
    return first[:len(first) - len(first.lstrip())] if first else default


def _close_of(lines: list[str], start: int, end: int) -> int:
    """The line that closes the flow list opened on ``start``."""
    depth = 0
    for k in range(start, end):
        code = _strip_comment(lines[k])
        depth += code.count("[") - code.count("]")
        if depth <= 0:
            return k
    raise LayerError(f"schema.yaml: the list at line {start + 1} is not closed")


def _append_flow(lines: list[str], start: int, end: int, items: list[str]) -> None:
    k = _close_of(lines, start, end)
    code = _strip_comment(lines[k])
    rest, inner = lines[k][len(code):], code[:code.rfind("]")].rstrip()
    sep = "" if inner.endswith("[") else ", "
    if len(inner + sep + ", ".join(items) + "]") <= WIDTH:
        lines[k] = inner + sep + ", ".join(items) + "]" + rest
    else:   # the items on lines of their own, under the list's first item
        lines[k] = inner + ("," if sep else "") + rest
        lines[k + 1:k + 1] = _continuation(items, lines[start].index("[") + 1)


def _append_list(lines: list[str], key: str, items: list[str], block: bool = False) -> None:
    """Append ``items`` (flow texts) to the top-level list ``key``, flow or block, or add the key at the end."""
    if not items:
        return
    found = _block(lines, key)
    if found is None:
        lines += ([f"{key}:"] + [f"  - {x}" for x in items]) if block else _wrapped(f"{key}: ", items)
        return
    start, end = found
    if "[" in _value(lines[start]):
        _append_flow(lines, start, end, items)
        return
    pad = _pad(lines, start, end)
    last = _last_content(lines, start, end)
    lines[last + 1:last + 1] = [f"{pad}- {x}" for x in items]


def _append_map(lines: list[str], key: str, entries: list[tuple[str, object]]) -> None:
    """Append ``entries`` ((key, value)) to the top-level mapping ``key``, or add the key at the end."""
    if not entries:
        return
    found = _block(lines, key)
    if found is None:
        lines += [f"{key}:"] + [ln for k, v in entries for ln in _entry("  ", k, v)]
        return
    start, end = found
    if _value(lines[start]) not in ("", "{}"):
        raise LayerError(f"schema.yaml: {key} is not a block mapping")
    if _value(lines[start]) == "{}":
        lines[start] = f"{key}:"
    pad, last = _pad(lines, start, end), _last_content(lines, start, end)
    lines[last + 1:last + 1] = [ln for k, v in entries for ln in _entry(pad, k, v)]


def _grow_entry(lines: list[str], key: str, entry: str, value: list) -> None:
    """The entry ``entry`` of the top-level mapping ``key`` now holds ``value`` (its old items first): a value on the
    entry's line is written again, a block list gets the new items after its own."""
    start, end = _block(lines, key) or (None, None)
    pat = re.compile(rf"^(\s+){re.escape(entry)}\s*:")
    i = next((k for k in range(start + 1, end) if pat.match(lines[k])), None) if start is not None else None
    if i is None:
        raise LayerError(f"schema.yaml: {key}: no entry {entry}")
    pad = pat.match(lines[i]).group(1)
    stop = next((k for k in range(i + 1, end) if lines[k].strip() and not lines[k].lstrip().startswith("#")
                 and len(lines[k]) - len(lines[k].lstrip()) <= len(pad)), end)
    if _value(lines[i]):
        lines[i:stop] = _entry(pad, entry, value)
        return
    items = [k for k in range(i + 1, stop) if lines[k].lstrip().startswith("- ")]
    if not items:
        raise LayerError(f"schema.yaml: {key}: {entry} is not a list")
    item_pad = lines[items[0]][:len(lines[items[0]]) - len(lines[items[0]].lstrip())]
    lines[items[-1] + 1:items[-1] + 1] = [f"{item_pad}- {flow(x)}" for x in value[len(items):]]


def _grow_endpoints_text(lines: list[str], old: dict, new: dict) -> None:
    """The endpoints the store declares that gain pairs (an edge type two layers share), grown in the text."""
    for et in [et for et, value in new.items() if et in old and _listed(value) != _listed(old[et])]:
        _grow_entry(lines, "endpoints", et, _listed(new[et]))


def edited(text: str, data: dict, want: dict) -> str:
    """``text`` with what ``want`` adds to ``data`` appended, key by key, in the text's own style (its line ends
    kept)."""
    lines = text.splitlines()
    for key in LIST_KEYS:
        _append_list(lines, key, [flow(x) for x in _new_items(data, want, key)], block=key == "templates")
    for key in MAP_KEYS:
        _append_map(lines, key, [(k, want[key][k]) for k in _new_items(data, want, key)])
    _grow_endpoints_text(lines, data.get("endpoints") or {}, want.get("endpoints") or {})
    nl = "\r\n" if "\r\n" in text else "\n"
    return nl.join(lines) + (nl if text.endswith("\n") or not text else "")


def _new_items(data: dict, want: dict, key: str) -> list:
    """What ``want`` holds under ``key`` that ``data`` does not: list items, or a mapping's keys."""
    have = data.get(key) or ()
    return [x for x in want.get(key) or () if x not in have]


# --- adding a layer: a plan, then its write --------------------------------------------------------------------

@dataclass
class Plan:
    store: Path
    before: str
    after: str = ""
    added: list[str] = field(default_factory=list)      # the layers added, in order
    lines: list[str] = field(default_factory=list)      # what it adds, said
    problems: list[str] = field(default_factory=list)   # why it cannot be written

    def diff(self) -> str:
        return "".join(difflib.unified_diff(self.before.splitlines(keepends=True), self.after.splitlines(keepends=True),
                                            "schema.yaml", "schema.yaml (planned)"))


def _clashes(data: dict, new: list[Layer]) -> list[str]:
    """A type of a layer to add that the store already has (under another layer): refused, nothing moves."""
    where = {t: layer for layer, ts in (data.get("layers") or {}).items() for t in ts or []}
    known = set(data.get("node_types") or [])
    out = []
    for la in new:
        clash = [t for t in la.node_types if t in known]
        if clash:
            under = sorted({where[t] for t in clash if t in where})
            out.append(f"layer {la.name}: type(s) {', '.join(clash)} already in the store"
                       + (f" (layer {', '.join(under)})" if under else "")
                       + ": rename that layer to the catalogue's by hand first (no node moves), or keep your own")
    return out


def _edge_split(data: dict, new: list[Layer]) -> tuple[set[str], list[str]]:
    """The edge types whose endpoints the layers declare (new to the store, or checked there already), and those left
    unchecked (in the store without endpoints)."""
    old, checked = set(data.get("edge_types") or []), set(data.get("endpoints") or {})
    edges = {et for la in new for et, ps in la.edges.items() if ps}
    return {et for et in edges if et not in old or et in checked}, sorted(edges & old - checked)


def _wanted(data: dict, have: dict, new: list[Layer]) -> tuple[dict, list[str]]:
    """The schema data once ``new`` is added, and the edge types left unchecked (in the store without endpoints: a
    layer never starts checking old edges). An edge type the store checks already gets the new pairs: more pairs only
    allow more, so no edge that passed is refused."""
    ends_for, left = _edge_split(data, new)
    base = data if "templates" in data else {**data, "templates": [catalogue()[n].ref() for n in have["exact"]]}
    return merged(base, new, ends_for), left


def _rehearse(store: Path, after: str, want: dict) -> list[str]:
    """The planned text read back and the store loaded with it: what would break."""
    try:
        got = yamlio.loads(after) or {}
    except yaml.YAMLError:
        got = None
    if not isinstance(got, dict) or {k: got.get(k) for k in want} != want:
        return ["the additions could not be placed in schema.yaml's text: edit it by hand; the composition is:\n"
                + render(want)]
    try:
        schema = parse_schema(got)
        return endpoint_errors(load_store(store, schema=schema), schema)
    except (ValueError, ValidationError) as exc:
        return [f"the store does not load with the planned schema: {exc}"]


def _to_add(data: dict, have: dict, names, extra) -> tuple[list[Layer], list[str], list[str]]:
    """The layers ``names`` adds (with what they require) that the store lacks, a line for each one named that it
    holds already, and the problems: a layer of the store's with a catalogue layer's name but not its types."""
    present, own = set(have["present"]), set(data.get("layers") or {})
    wanted = resolve(names, extra)
    return ([la for la in wanted if la.name not in present | own],
            [f"layer {n}: already in the store" for n in names if n in present],
            [f"layer {la.name}: the store has a layer of that name without the catalogue's types "
             f"({', '.join(la.node_types)}): rename the store's layer first" for la in wanted
             if la.name in own - present])


def add_plan(store: str | Path, names, extra: dict[str, Layer] | None = None) -> Plan:
    """What adding the layers ``names`` (and what they require) to ``store`` writes in its schema.yaml: the text with
    the additions appended, read back and the store loaded with it; ``problems`` say why it cannot be written."""
    store = Path(store)
    try:
        before = (store / "schema.yaml").read_bytes().decode("utf-8")   # its line ends as they are (CRLF kept)
    except (OSError, UnicodeDecodeError) as exc:
        raise LayerError(f"{store / 'schema.yaml'}: {exc}") from exc
    plan = Plan(store, before, after=before)
    data = yamlio.loads(before) or {}
    have = store_layers(data)
    new, plan.lines, plan.problems = _to_add(data, have, names, extra)
    plan.problems += _clashes(data, new)
    if not new or plan.problems:
        return plan
    want, left = _wanted(data, have, new)
    try:
        plan.after = edited(before, data, want)
    except LayerError as exc:
        plan.problems.append(f"{exc}: edit schema.yaml by hand; the composition is:\n" + render(want))
    plan.added = [la.name for la in new]
    plan.lines += [f"add layer {la.name} v{la.version} ({la.mode}): {', '.join(la.node_types)}" for la in new]
    plan.lines += [f"edge type(s) {', '.join(left)} already in the store without endpoints: left unchecked"] if left \
        else []
    plan.problems += [] if plan.problems else _rehearse(store, plan.after, want)
    return plan


def write(plan: Plan) -> Path:
    if plan.problems:
        raise LayerError("; ".join(plan.problems))
    path = plan.store / "schema.yaml"
    path.write_text(plan.after, encoding="utf-8", newline="\n")
    yamlio.clear()
    return path
