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


def parse_layer(data, source: str = "") -> Layer:
    """A layer from a layer file's data, checked."""
    where = f"layer {source or '?'}"
    if not isinstance(data, dict):
        raise LayerError(f"{where}: a mapping")
    missing = [k for k in REQUIRED if k not in data]
    unknown = sorted(set(data) - KEYS)
    if missing or unknown:
        raise LayerError(f"{where}: " + "; ".join(([f"misses {', '.join(missing)}"] if missing else []) +
                                                  ([f"unknown key(s) {', '.join(unknown)}"] if unknown else [])))
    name, version = data["name"], data["version"]
    if not (isinstance(name, str) and NAME_RE.fullmatch(name)):
        raise LayerError(f"{where}: name is lower case letters, digits and '_'")
    where = f"layer {name}"
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise LayerError(f"{where}: version is a whole number, 1 or more")
    if data["mode"] not in MODES:
        raise LayerError(f"{where}: mode is one of {', '.join(MODES)}")
    types = data["node_types"]
    if not isinstance(types, dict) or not all(isinstance(t, str) and t for t in types):
        raise LayerError(f"{where}: node_types maps each type to a line that says what it is")
    statuses = _strs(data["statuses"], f"{where}: statuses")
    edges: dict[str, tuple[dict, ...]] = {}
    for et, spec in (data.get("edge_types") or {}).items():
        pairs = spec if isinstance(spec, list) else ([spec] if isinstance(spec, dict) and
                                                     ("from" in spec or "to" in spec) else [])
        if not isinstance(spec, (list, dict)):
            raise LayerError(f"{where}: edge_types[{et}]: a {{from, to, why}} mapping, a list of them, or {{why}}")
        out = []
        for i, p in enumerate(pairs):
            if not isinstance(p, dict) or "from" not in p or "to" not in p:
                raise LayerError(f"{where}: edge_types[{et}][{i}]: from and to")
            out.append({"from": _end(p["from"], f"{where}: edge_types[{et}][{i}].from"),
                        "to": _end(p["to"], f"{where}: edge_types[{et}][{i}].to")})
        edges[et] = tuple(out)
    sbt = {}
    for t, allowed in (data.get("status_by_type") or {}).items():
        if t not in types:
            raise LayerError(f"{where}: status_by_type: {t!r} is not one of its types")
        allowed = _strs(allowed, f"{where}: status_by_type[{t}]")
        if set(allowed) - set(statuses):
            raise LayerError(f"{where}: status_by_type[{t}]: {sorted(set(allowed) - set(statuses))} not in statuses")
        sbt[t] = allowed
    req = {}
    for t, keys in (data.get("required_props") or {}).items():
        if t not in types:
            raise LayerError(f"{where}: required_props: {t!r} is not one of its types")
        req[t] = _strs(keys, f"{where}: required_props[{t}]")
    return Layer(name, version, str(data["title"]), data["mode"], dict(types), edges, statuses,
                 _strs(data.get("requires"), f"{where}: requires"), sbt, _strs(data.get("levels"), f"{where}: levels"),
                 req, data, source)


def load_layer_file(path: str | Path) -> Layer:
    """A layer of a file of its own (a domain template's layer)."""
    try:
        data = yamlio.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise LayerError(f"layer file {path}: {exc}") from exc
    return parse_layer(data, str(path))


@lru_cache(maxsize=1)
def catalogue() -> dict[str, Layer]:
    """The engine's layers, by name: each file's name is its layer's, a node type is in one layer only, and what a
    layer requires is in the catalogue."""
    out: dict[str, Layer] = {}
    owner: dict[str, str] = {}
    for f in sorted((p for p in LAYERS.iterdir() if p.name.endswith(".yaml")), key=lambda p: p.name):
        layer = parse_layer(yamlio.loads(f.read_text(encoding="utf-8")), f"templates/layers/{f.name}")
        if f.name != f"{layer.name}.yaml":
            raise LayerError(f"templates/layers/{f.name}: holds layer {layer.name!r}")
        for t in layer.node_types:
            if t in owner:
                raise LayerError(f"the catalogue: type {t} is in layers {owner[t]} and {layer.name}")
            owner[t] = layer.name
        out[layer.name] = layer
    for layer in out.values():
        for r in layer.requires:
            if r not in out:
                raise LayerError(f"layer {layer.name}: requires {r!r}, which is not in the catalogue")
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
    seen: set[str] = set()

    def visit(name: str, path: tuple[str, ...]) -> None:
        if name in seen:
            return
        if name in path:
            raise LayerError(f"layers: a cycle of requires: {' -> '.join(path + (name,))}")
        if name not in known:
            raise LayerError(f"layer {name!r}: not in the catalogue ({', '.join(sorted(cat))})")
        for r in known[name].requires:
            visit(r, path + (name,))
        seen.add(name)
        out.append(known[name])

    for n in names:
        visit(n, ())
    return out


def _union(seqs) -> list[str]:
    out: list[str] = []
    for seq in seqs:
        out += [x for x in seq if x not in out]
    return out


def _endpoints(layers: list[Layer]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for layer in layers:
        for et, pairs in layer.edges.items():
            for p in pairs:
                if p not in out.setdefault(et, []):
                    out[et].append(dict(p))
    return {et: ps for et, ps in out.items() if ps}


def compose_layers(layers: list[Layer], owner: str | None = None) -> dict:
    """The schema data of ``layers`` (resolved), in :data:`SCHEMA_KEYS` order, ``owner`` first when given."""
    where: dict[str, str] = {}
    for layer in layers:
        for t in layer.node_types:
            if t in where:
                raise LayerError(f"type {t} is in layers {where[t]} and {layer.name}: a type belongs to one layer")
            where[t] = layer.name
    data: dict = {"owner": owner} if owner else {}
    data["templates"] = [{"layer": la.name, "version": la.version} for la in layers]
    data["node_types"] = [t for la in layers for t in la.node_types]
    data["edge_types"] = _union(la.edges for la in layers)
    data["statuses"] = _union(la.statuses for la in layers)
    levels = _union(la.levels for la in layers)
    if levels:
        data["levels"] = levels
    data["layers"] = {la.name: list(la.node_types) for la in layers}
    data["status_by_type"] = {t: list(s) for la in layers for t, s in la.status_by_type.items()}
    req = {t: list(k) for la in layers for t, k in la.required_props.items()}
    if req:
        data["required_props"] = req
    ends = _endpoints(layers)
    if ends:
        data["endpoints"] = ends
    parse_schema(data)   # the composition is a schema the loader accepts
    return data


def compose(names, owner: str | None = None, extra: dict[str, Layer] | None = None) -> dict:
    return compose_layers(resolve(names, extra), owner)


# --- the text ----------------------------------------------------------------------------------------------------

def flow(value) -> str:
    """One value in YAML flow style (a list, a mapping, a scalar), as a schema.yaml line holds it."""
    return yaml.safe_dump(value, default_flow_style=True, width=10**6, sort_keys=False,
                          allow_unicode=True).strip().removesuffix("...").strip()


def _wrapped(head: str, items: list[str], indent: int) -> list[str]:
    """``head [a, b, ...]`` wrapped at :data:`WIDTH`, the continuation lines under the first item."""
    lines, line = [], head + "["
    pad = " " * (indent or len(head) + 1)
    for i, item in enumerate(items):
        piece = item + (", " if i < len(items) - 1 else "]")
        if len(line) + len(piece.rstrip()) > WIDTH and line.strip() not in (head.strip() + "[", ""):
            lines.append(line.rstrip())
            line = pad
        line += piece
    lines.append(line if items else head + "[]")
    return lines


def _continuation(items: list[str], col: int) -> list[str]:
    """``items`` on lines indented by ``col``, wrapped at :data:`WIDTH`, the last one closing the list."""
    pad, lines = " " * col, []
    line = pad
    for i, item in enumerate(items):
        piece = item + (", " if i < len(items) - 1 else "]")
        if len(line) + len(piece.rstrip()) > WIDTH and line.strip():
            lines.append(line.rstrip())
            line = pad
        line += piece
    return lines + [line]


def render(data: dict, header: str = "") -> str:
    """A schema.yaml text for a composition (:func:`compose`)."""
    out = [f"# {ln}".rstrip() for ln in header.splitlines()] if header else []
    if data.get("owner"):
        out.append(f"owner: {flow(data['owner'])}")
    for key in SCHEMA_KEYS:
        if key not in data:
            continue
        value = data[key]
        if key == "templates":
            out.append("templates:   # the catalogue's layers that composed this schema (research_graph layers)")
            out += [f"  - {flow(t)}" for t in value]
        elif isinstance(value, list):
            out += _wrapped(f"{key}: ", [flow(v) for v in value], 0)
        else:
            out.append(f"{key}:")
            for k, v in value.items():
                out += _entry("  ", k, v)
    return "\n".join(out) + "\n"


def _entry(pad: str, key: str, value) -> list[str]:
    """One entry of a mapping: a list of names wrapped, another value on its line, or as a block list when that line
    would pass :data:`WIDTH`."""
    if isinstance(value, list) and all(isinstance(x, str) for x in value):
        return _wrapped(f"{pad}{key}: ", [flow(x) for x in value], 0)
    line = f"{pad}{key}: {flow(value)}"
    if len(line) <= WIDTH or not isinstance(value, list):
        return [line]
    return [f"{pad}{key}:"] + [f"{pad}  - {flow(x)}" for x in value]


def header_for(layers: list[Layer]) -> str:
    text = ("The vocabulary of this graph store, composed from the catalogue's layers (research_graph layers): "
            f"{', '.join(la.name for la in layers)}. research_graph check validates every node and edge against it, "
            "endpoints included. Add a layer with research_graph layers add NAME (a plan, then --write); your own "
            "types go in a layer of your own (local), which no command of the catalogue touches.")
    return "\n".join(textwrap.wrap(text, WIDTH - 2))


# --- a store's layers --------------------------------------------------------------------------------------------

def store_layers(data: dict) -> dict:
    """What a schema's data holds of the catalogue: ``recorded`` (its ``templates:``), ``present`` (the catalogue's
    layers whose name and types it has: recorded or matched), ``other`` (its layers that are not the catalogue's)."""
    cat = catalogue()
    layers = data.get("layers") or {}
    recorded = [(t["layer"], t["version"]) for t in data.get("templates") or [] if isinstance(t, dict)]
    present, exact = [], []
    for name, types in layers.items():
        if name in cat and set(cat[name].node_types) <= set(types or []):
            present.append(name)
            if set(cat[name].node_types) == set(types or []):
                exact.append(name)
    present += [n for n, _ in recorded if n not in present and n in cat]
    return {"recorded": recorded, "present": present, "exact": exact, "other": [n for n in layers if n not in cat]}


def proposed(typology: str, stage: str) -> list[Layer]:
    """The catalogue's layers a typology may take and a stage proposes (each layer's ``lifecycle``)."""
    out = []
    for layer in catalogue().values():
        lc = layer.lifecycle()
        typ, at = lc.get("typologies") or [], lc.get("proposed_at") or []
        if (ANY in typ or typology in typ) and (ANY in at or stage in at):
            out.append(layer)
    return out


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


_TOP = re.compile(r"^[^\s#]")


def _block(lines: list[str], key: str) -> tuple[int, int] | None:
    """(the line of top-level ``key:``, the end of its block: the next top-level line) or None."""
    pat = re.compile(rf"^{re.escape(key)}\s*:")
    for i, ln in enumerate(lines):
        if pat.match(ln):
            j = i + 1
            while j < len(lines) and not _TOP.match(lines[j]):
                j += 1
            return i, j
    return None


def _last_content(lines: list[str], start: int, end: int) -> int:
    last = start
    for k in range(start + 1, end):
        if lines[k].strip() and not lines[k].startswith("#"):
            last = k
    return last


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


def _append_list(lines: list[str], key: str, items: list[str], block: bool = False) -> None:
    """Append ``items`` (flow texts) to the top-level list ``key``, flow or block, or add the key at the end."""
    if not items:
        return
    found = _block(lines, key)
    if found is None:
        lines +=([f"{key}:"] + [f"  - {x}" for x in items]) if block else _wrapped(f"{key}: ", items, 0)
        return
    i, end = found
    if "[" in _strip_comment(lines[i]).split(":", 1)[1]:
        depth, k = 0, i
        while k < end:
            code = _strip_comment(lines[k])
            depth += code.count("[") - code.count("]")
            if depth <= 0:
                break
            k += 1
        code = _strip_comment(lines[k])
        at = code.rfind("]")
        rest = lines[k][len(code):]
        inner = code[:at].rstrip()
        sep = "" if inner.endswith("[") else ", "
        added = inner + sep + ", ".join(items) + "]"
        if len(added) <= WIDTH:
            lines[k] = added + rest
        else:   # the items on lines of their own, under the list's first item
            lines[k] = inner + ("," if sep else "") + rest
            lines[k + 1:k + 1] = _continuation(items, lines[i].index("[") + 1)
        return
    last = _last_content(lines, i, end)
    item_lines = [lines[k] for k in range(i + 1, end) if lines[k].lstrip().startswith("- ")]
    pad = item_lines[0][:len(item_lines[0]) - len(item_lines[0].lstrip())] if item_lines else "  "
    lines[last + 1:last + 1] = [f"{pad}- {x}" for x in items]


def _append_map(lines: list[str], key: str, entries: list[tuple[str, object]]) -> None:
    """Append ``entries`` ((key, value)) to the top-level mapping ``key``, or add the key at the end."""
    if not entries:
        return
    found = _block(lines, key)
    if found is None:
        lines += [f"{key}:"] + [ln for k, v in entries for ln in _entry("  ", k, v)]
        return
    i, end = found
    if _strip_comment(lines[i]).split(":", 1)[1].strip() not in ("", "{}"):
        raise LayerError(f"schema.yaml: {key} is not a block mapping")
    if _strip_comment(lines[i]).split(":", 1)[1].strip() == "{}":
        lines[i] = f"{key}:"
    last = _last_content(lines, i, end)
    firsts = [lines[k] for k in range(i + 1, end) if lines[k].strip() and not lines[k].lstrip().startswith("#")]
    pad = firsts[0][:len(firsts[0]) - len(firsts[0].lstrip())] if firsts else "  "
    lines[last + 1:last + 1] = [ln for k, v in entries for ln in _entry(pad, k, v)]


def _expected(data: dict, new: list[Layer], ends_for: set[str]) -> dict:
    """The schema data once ``new`` is added: what :func:`add_plan` must read back from its text."""
    out = {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v) for k, v in data.items()}
    out["node_types"] = list(data.get("node_types") or []) + [t for la in new for t in la.node_types]
    out["edge_types"] = _union([data.get("edge_types") or []] + [list(la.edges) for la in new])
    out["statuses"] = _union([data.get("statuses") or []] + [list(la.statuses) for la in new])
    levels = _union([data.get("levels") or []] + [list(la.levels) for la in new])
    if levels:
        out["levels"] = levels
    out["layers"] = {**(data.get("layers") or {}), **{la.name: list(la.node_types) for la in new}}
    sbt = {**(data.get("status_by_type") or {}), **{t: list(s) for la in new for t, s in la.status_by_type.items()}}
    if sbt:
        out["status_by_type"] = sbt
    req = {**(data.get("required_props") or {}), **{t: list(k) for la in new for t, k in la.required_props.items()}}
    if req:
        out["required_props"] = req
    ends = {et: list(ps) for et, ps in (data.get("endpoints") or {}).items()}
    for et, ps in _endpoints(new).items():
        if et in ends_for:
            ends.setdefault(et, [])
            ends[et] = (ends[et] if isinstance(ends[et], list) else [ends[et]]) + \
                [p for p in ps if p not in ends[et]]
    if ends:
        out["endpoints"] = ends
    recorded = list(data.get("templates") or [])
    out["templates"] = recorded + [{"layer": la.name, "version": la.version} for la in new]
    return out


def add_plan(store: str | Path, names, extra: dict[str, Layer] | None = None) -> Plan:
    """What adding the layers ``names`` (and what they require) to ``store`` writes in its schema.yaml: the text with
    the additions appended, read back and the store loaded with it; ``problems`` say why it cannot be written."""
    store = Path(store)
    path = store / "schema.yaml"
    try:
        before = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LayerError(f"{path}: {exc}") from exc
    plan = Plan(store, before)
    data = yamlio.loads(before) or {}
    have = store_layers(data)
    present = set(have["present"]) | set((data.get("layers") or {}))
    wanted = resolve(names, extra)
    new = [la for la in wanted if la.name not in present]
    for la in wanted:
        if la.name in present and la.name in names:
            plan.lines.append(f"layer {la.name}: already in the store")
    if not new:
        plan.after = before
        return plan
    types = {t: layer for layer, ts in (data.get("layers") or {}).items() for t in ts or []}
    known = set(data.get("node_types") or [])
    for la in new:
        clash = [t for t in la.node_types if t in known]
        if clash:
            plan.problems.append(
                f"layer {la.name}: type(s) {', '.join(clash)} already in the store"
                + (f" (layer {', '.join(sorted({types[t] for t in clash if t in types}))})" if types else "")
                + ": rename that layer to the catalogue's by hand first (no node moves), or keep your own")
    if plan.problems:
        plan.after = before
        return plan
    old_edges = set(data.get("edge_types") or [])
    checked = set((data.get("endpoints") or {}))
    ends_for = {et for la in new for et in la.edges if et not in old_edges or et in checked}
    left = sorted({et for la in new for et, ps in la.edges.items() if ps and et in old_edges and et not in checked})
    want = _expected(data, new, ends_for)
    lines = before.splitlines()
    try:
        if "templates" not in data:   # the catalogue's layers it holds as they are, recorded with the ones added
            recorded = [{"layer": n, "version": catalogue()[n].version} for n in have["exact"]]
            want["templates"] = recorded + [{"layer": la.name, "version": la.version} for la in new]
            _append_list(lines, "templates", [flow(t) for t in want["templates"]], block=True)
        else:
            _append_list(lines, "templates", [flow({"layer": la.name, "version": la.version}) for la in new],
                         block=True)
        for key in ("node_types", "edge_types", "statuses", "levels"):
            _append_list(lines, key, [flow(x) for x in want.get(key, []) if x not in (data.get(key) or [])])
        for key in ("layers", "status_by_type", "required_props", "endpoints"):
            entries = [(k, v) for k, v in (want.get(key) or {}).items() if k not in (data.get(key) or {})]
            if key == "endpoints":
                grown = [(k, v) for k, v in (want.get(key) or {}).items()
                         if k in (data.get(key) or {}) and v != data[key][k]]
                if grown:
                    plan.problems.append(f"endpoints of {', '.join(k for k, _ in grown)}: already declared, the "
                                         "layer adds pairs to them: add them by hand (" +
                                         "; ".join(f"{k}: {flow(v)}" for k, v in grown) + ")")
            _append_map(lines, key, entries)
    except LayerError as exc:
        plan.problems.append(f"{exc}: edit schema.yaml by hand; the composition is:\n" + render(want))
    after = "\n".join(lines) + ("\n" if before.endswith("\n") or not before else "")
    got = yamlio.loads(after) or {}
    if not plan.problems and {k: got.get(k) for k in want} != want:
        plan.problems.append("the additions could not be placed in schema.yaml's text: edit it by hand; the composition "
                             "is:\n" + render(want))
    plan.after = after
    plan.added = [la.name for la in new]
    plan.lines += [f"add layer {la.name} v{la.version} ({la.mode}): {', '.join(la.node_types)}" for la in new]
    if left:
        plan.lines.append(f"edge type(s) {', '.join(left)} already in the store without endpoints: left unchecked")
    if not plan.problems:
        try:
            schema = parse_schema(got)
            graph = load_store(store, schema=schema)
            plan.problems += endpoint_errors(graph, schema)
        except (ValueError, ValidationError) as exc:
            plan.problems.append(f"the store does not load with the planned schema: {exc}")
    return plan


def write(plan: Plan) -> Path:
    if plan.problems:
        raise LayerError("; ".join(plan.problems))
    path = plan.store / "schema.yaml"
    path.write_text(plan.after, encoding="utf-8", newline="\n")
    yamlio.clear()
    return path
