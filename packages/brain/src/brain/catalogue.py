"""catalogue/v1, the module catalogue's neutral contract (wi-brain-catalogue-contract; docs/catalogue.md).

A catalogue of modules: its bricks (groups of modules), its modules with their hard and soft dependencies, what a
machine needs to run each one and its estimated cost (RAM, disk, VRAM), its fallback and its licence; the
distributions that ship them; and the presets an installer offers (the base presets, then the personas when a
catalogue declares them). Any program may emit it; the Brain emits its own (:func:`emit`, ``brain catalogue emit``),
and an installer (``brain init``'s screens) or a settings tab reads one.

The JSON schema (``schemas/catalogue.schema.json``) holds the shape; :func:`validate` adds what a schema cannot say:
ids unique in their list, every reference to a module, a brick, a distribution or a base preset resolved in the
document (a soft dependency on a module another catalogue holds is a note), no cycle of hard dependencies, a planned
module in no preset. Evolution (the status contract's rule): an optional key may be added in v1 and a reader ignores
the ones it does not know; a new enum value, a new required key or a change of a key's meaning is ``catalogue/v2``.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

from . import schema

ID = "catalogue/v1"
KIND = "catalogue"          # its name in brain.schema.SCHEMAS
VERSION = 1
ID_RE = re.compile(r"^catalogue/v([0-9]{1,6})\Z")   # bounded: a 5,000-digit version is no crash
LISTS = ("bricks", "modules", "distributions", "presets")
CLASSES = ("core", "extra", "service")
PRESET_KINDS = ("base", "persona")
COST = ("ram_mb", "disk_mb", "vram_gb", "download_mb")
BASE = "base"                # the distribution of the Brain's own catalogue that the engine's install is


class CatalogueError(ValueError):
    """A file that is not a catalogue document this engine reads (not JSON, not an object)."""


def load(path: Path) -> dict:
    """The document at ``path`` (a UTF-8 byte order mark allowed); :class:`CatalogueError` when it is not JSON or not
    an object."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, RecursionError) as exc:
        raise CatalogueError(f"{path}: not a JSON document ({exc})") from exc
    if not isinstance(data, dict):
        raise CatalogueError(f"{path}: not a JSON object")
    return data


def newer(doc: dict) -> str:
    """The refusal of a document written for a later version of the contract; "" otherwise."""
    if not isinstance(doc, dict):
        return ""
    m = ID_RE.match(str(doc.get("schema", "")))
    if m and int(m.group(1)) > VERSION:
        return f"schema: {doc['schema']} is a later contract than this engine's {ID}: brain update"
    return ""


def _list(doc: dict, key: str) -> list[dict]:
    """``doc[key]``'s objects when it is a list (the schema reports any other value), else []."""
    value = doc.get(key)
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def _strs(v) -> list[str]:
    return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []


def _ids(doc: dict, key: str, where: str, errors: list[str]) -> dict[str, dict]:
    """{id: entry} of one list; an id given twice is an error."""
    out: dict[str, dict] = {}
    for i, e in enumerate(_list(doc, key)):
        eid = e.get("id")
        if not isinstance(eid, str):
            continue
        if eid in out:
            errors.append(f"{where}.{key}[{i}]: id {eid!r} used twice")
        out.setdefault(eid, e)
    return out


def _cycle(edges: dict[str, list[str]]) -> list[str]:
    """One cycle of ``edges`` (its ids, the first repeated last), [] when there is none. Iterative: a chain of
    thousands of modules is no recursion error."""
    state: dict[str, int] = {}
    for start in sorted(edges):
        if state.get(start):
            continue
        path, its = [start], [iter(edges.get(start, ()))]
        state[start] = 1
        while path:
            d = next(its[-1], None)
            if d is None:
                state[path.pop()] = 2
                its.pop()
            elif state.get(d) == 1:
                return path[path.index(d):] + [d]
            elif d in edges and not state.get(d):
                state[d] = 1
                path.append(d)
                its.append(iter(edges.get(d, ())))
    return []


def _finite(value, path: str, errors: list[str]) -> None:
    """A number that is not finite (NaN, Infinity: JSON parsers accept them) is an error wherever it is."""
    todo = [(value, path)]
    while todo:
        v, at = todo.pop()
        if isinstance(v, float) and not math.isfinite(v):
            errors.append(f"{at}: {v} is not a finite number")
        elif isinstance(v, dict):
            todo += [(x, f"{at}.{k}") for k, x in v.items()]
        elif isinstance(v, list):
            todo += [(x, f"{at}[{i}]") for i, x in enumerate(v)]


def _missing(at: str, ids: list[str], known: dict, what: str) -> list[str]:
    """``<at>: 'x' is not a <what> of the catalogue`` for each id of ``ids`` the document does not hold."""
    return [f"{at}: {i!r} is not a {what} of the catalogue" for i in ids if i not in known]


def _module_refs(mid: str, m: dict, lists: dict, at: str, errors: list[str], notes: list[str]) -> None:
    """One module's references: its hard and soft dependencies, its brick, its distributions."""
    deps, uses = _strs(m.get("depends_on")), _strs(m.get("uses"))
    errors += _missing(f"{at}.depends_on", deps, lists["modules"], "module")
    notes += [f"{n} (another catalogue's?)" for n in _missing(f"{at}.uses", uses, lists["modules"], "module")]
    if mid in deps or mid in uses:
        errors.append(f"{at}: depends on or uses itself")
    errors += [f"{at}: {d!r} is both a hard (depends_on) and a soft (uses) dependency"
               for d in sorted({*deps} & {*uses})]
    brick = m.get("brick")
    errors += _missing(f"{at}.brick", [brick] if isinstance(brick, str) else [], lists["bricks"], "brick")
    errors += _missing(f"{at}.distributions", _strs(m.get("distributions")), lists["distributions"], "distribution")


def _modules(lists: dict, where: str, errors: list[str], notes: list[str]) -> None:
    mods = lists["modules"]
    for mid, m in mods.items():
        _module_refs(mid, m, lists, f"{where}.modules[{mid}]", errors, notes)
    cycle = _cycle({mid: [d for d in _strs(m.get("depends_on")) if d in mods] for mid, m in mods.items()})
    if cycle:
        errors.append(f"{where}: a cycle of hard dependencies: {' -> '.join(cycle)}")


def _preset_modules(p: dict, mods: dict, at: str) -> list[str]:
    """A preset's modules and when_fits: each a built module of the catalogue, never in both."""
    listed, fits = _strs(p.get("modules")), _strs(p.get("when_fits"))
    out = []
    for key, ids in (("modules", listed), ("when_fits", fits)):
        out += _missing(f"{at}.{key}", ids, mods, "module")
        out += [f"{at}.{key}: {m!r} is planned, not installable" for m in ids
                if mods.get(m, {}).get("status") == "planned"]
    return out + [f"{at}: {m!r} is both in modules and in when_fits" for m in sorted({*listed} & {*fits})]


def _is_base(p: dict | None) -> bool:
    """A preset of the document whose kind is base (a preset that says no kind is one)."""
    return p is not None and p.get("kind", "base") == "base"


def _presets(presets: dict, mods: dict, where: str, errors: list[str], notes: list[str]) -> None:
    for pid, p in presets.items():
        at = f"{where}.presets[{pid}]"
        errors += _preset_modules(p, mods, at)
        base = p.get("base")
        if isinstance(base, str) and not _is_base(presets.get(base)):
            errors.append(f"{at}.base: {base!r} is not a base preset of the catalogue")
        if p.get("kind") == "persona" and not isinstance(base, str):
            notes.append(f"{at}: a persona with no base preset (an installer starts it from nothing)")
        listed = _strs(p.get("modules"))
        held = set(listed) | (set(_strs(presets[base].get("modules"))) if _is_base(presets.get(base)) else set())
        pulled = sorted({d for m in listed if m in mods for d in _closure(m, mods)} - held)
        if pulled:
            notes.append(f"{at}: pulls {', '.join(pulled)} (hard dependencies its modules need)")


def _closure(start: str, mods: dict) -> list[str]:
    """The modules ``start`` needs, directly or not (its hard dependencies of the catalogue)."""
    seen: list[str] = []
    todo = [d for d in _strs(mods[start].get("depends_on")) if d in mods]
    while todo:
        d = todo.pop(0)
        if d not in seen and d != start:
            seen.append(d)
            todo += [x for x in _strs(mods[d].get("depends_on")) if x in mods]
    return seen


def validate(doc: dict, where: str = "catalogue") -> tuple[list[str], list[str]]:
    """(errors, notes) of ``doc`` against catalogue/v1. Errors: the schema's, a later version (refused alone: its other
    keys may mean something else), an id used twice in a list, a hard dependency, brick, distribution or preset module
    the document does not hold, a module both a hard and a soft dependency of another (or of itself), a cycle of hard
    dependencies, a planned module in a preset, a persona's base that is no base preset. Notes: what a reader keeps
    without judging: a soft dependency on a module another catalogue holds, the hard dependencies a preset pulls."""
    if not isinstance(doc, dict):
        return [f"{where}: expected a JSON object, got {type(doc).__name__}"], []
    refused = newer(doc)
    if refused:
        return [f"{where}: {refused}"], []
    errors: list[str] = []
    contract = schema.load(KIND)   # versioned by its id: a top-level v is a producer's own key, never a refusal
    schema._validate(doc, contract, contract, where, errors)
    _finite(doc, where, errors)
    notes: list[str] = []
    lists = {k: _ids(doc, k, where, errors) for k in LISTS}
    _modules(lists, where, errors, notes)
    _presets(lists["presets"], lists["modules"], where, errors, notes)
    return errors, notes


def summary(doc: dict) -> dict:
    """Counts a reader shows: modules per class and status, the bricks, distributions and presets."""
    def count(items, key, default):
        out: dict[str, int] = {}
        for x in items:
            out[str(x.get(key, default))] = out.get(str(x.get(key, default)), 0) + 1
        return dict(sorted(out.items()))
    mods = _list(doc, "modules")
    generated = doc.get("generated") if isinstance(doc.get("generated"), dict) else {}
    return {"schema": doc.get("schema"), "by": generated.get("by"), "modules": len(mods),
            "classes": count(mods, "class", "-"), "statuses": count(mods, "status", "built"),
            "bricks": len(_list(doc, "bricks")), "distributions": len(_list(doc, "distributions")),
            "presets": [str(p.get("id")) for p in _list(doc, "presets")]}


# The Brain's own catalogue.

def _licence() -> str:
    """The engine's licence, from its installed metadata ("" when the distribution is not installed)."""
    from importlib import metadata
    try:
        meta = metadata.metadata("brain")
    except metadata.PackageNotFoundError:
        return ""
    return str(meta.get("License-Expression") or meta.get("License") or "")


def _cost(entries: list) -> dict:
    """The capabilities' resources summed, in the contract's units (disk_gb counted in disk_mb)."""
    out: dict[str, float] = {}
    for e in entries:
        for k, v in (e.resources or {}).items():
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not v > 0:
                continue   # a stack's tier is only shape-checked by brain check --all: never a crash, never below 0
            key, val = ("disk_mb", v * 1024) if k == "disk_gb" else (k, v)
            if key in COST:
                out[key] = out.get(key, 0) + val
    return {k: (int(v) if float(v).is_integer() else v) for k, v in sorted(out.items()) if v}


def _union(lists) -> list[str]:
    return list(dict.fromkeys(x for xs in lists for x in xs))


def _kind(caps: list) -> dict:
    """class (the most costly of the capabilities'), status (planned when one is), auto (when all are)."""
    cls = max((e.cls for e in caps if e.cls in CLASSES), key=CLASSES.index, default="")
    return {"class": cls, "status": "planned" if any(e.status == "planned" for e in caps) else "built",
            "auto": bool(caps) and all(e.auto for e in caps)}


def _kept(d: dict) -> dict:
    """``d`` without its empty values ("", None, False, [], {}); an explicit ``ai: false`` is kept."""
    return {k: v for k, v in d.items() if v or (k == "ai" and v is False)}


def _said(m, entry: dict, caps: list) -> dict:
    """What the registry entry says (its definition, brick, ai), else a capability's title as the description."""
    titles = "; ".join(e.title for e in caps if e.title)
    ai = entry.get("ai")
    return {"description": str(entry.get("definition") or ("" if m.from_registry else titles)),
            "brick": str(entry.get("brick") or ""), "ai": ai if isinstance(ai, bool) else None}


def _needs(caps: list, licence: str) -> dict:
    """What the machine needs and pays: requirements, the clauses that recommend it, the cost, the fallback."""
    from . import probe
    brought = [[r for r in e.requires if not (e.pip and r in probe.MODULES)] for e in caps]   # its extra installs it
    return {"requires": _union(brought), "recommend_when": _union(e.recommend_when for e in caps),
            "cost": _cost(caps), "fallback": "; ".join(sorted({e.fallback for e in caps if e.fallback})),
            "licence": licence}


def _module(m, reg: dict, entry: dict, deps: list[str], uses: list[str], licence: str) -> dict:
    """One module of brain.mod's catalogue as the contract's module; an empty optional key is left out (the lists
    always given)."""
    caps = [reg[c] for c in m.capabilities if c in reg]
    out: dict = {"id": m.id, "name": m.name if m.from_registry else m.id}   # a capability's title is its description
    out.update(_kept({**_said(m, entry, caps), **_kind(caps)}))
    out.update(components=list(m.capabilities), depends_on=deps, uses=uses, requires=[], recommend_when=[])
    out.update(_kept(_needs(caps, licence)))
    out["distributions"] = [BASE] + [f"extra-{x}" for x in sorted({e.pip for e in caps if e.pip})]
    return out


def _presets_of(cat: dict, reg: dict) -> list[dict]:
    """The engine's three bases as presets: the modules each turns on (all their switched capabilities in the base),
    and for recommended the modules it adds when the machine fits (a capability of profile recommended)."""
    from . import mod, tiers

    def modules_of(keep: set[str]) -> list[str]:
        return [m.id for m in cat.values()
                if (sw := mod.switched(m, reg)) and all(c in keep for c in sw)]

    keep = tiers.preset(reg, "default")
    eligible = {e.id for e in reg.values() if e.profile == "recommended" and e.status == "built" and not e.auto}
    eligible = {c for c in eligible if all(d in keep or d in eligible for d in reg[c].depends_on)}   # recommend's rule

    def fits(m) -> bool:
        """As tiers.recommend: every switched capability in Default or recommendable, one of them recommendable."""
        sw = mod.switched(m, reg)
        return bool(sw) and all(c in keep or c in eligible for c in sw) and any(c in eligible for c in sw)

    default = modules_of(keep)
    out = [{"id": base, "name": tiers.NAMES[base], "kind": "base", "modules": modules_of(tiers.preset(reg, base))}
           for base in tiers.BASES]
    out[-1]["when_fits"] = [m.id for m in cat.values() if m.id not in default and fits(m)]   # recommended
    return out


def _soft(m, cat: dict, reg: dict, owner: dict, deps: list[str]) -> list[str]:
    """A module's soft dependencies of the catalogue: its registry entry's, then its capabilities' (by their
    module), never itself nor a hard one."""
    soft = [u for u in m.uses if u in cat] if m.from_registry else []
    soft += [owner[u] for c in m.capabilities for u in getattr(reg.get(c), "uses", []) if u in owner]
    return [u for u in dict.fromkeys(soft) if u != m.id and u not in deps]


def _distributions(mods: list[dict], licence: str, version: str) -> list[dict]:
    """The engine (bundled) and each pip extra a module needs (downloaded when it is added)."""
    extras = sorted({d for m in mods for d in m["distributions"] if d != BASE})
    base = {"id": BASE, "name": "the brain engine", "kind": "base", "version": version, "bundled": True}
    return [{**base, **({"licence": licence} if licence else {})}] + [
        {"id": x, "name": f"the engine's {x.removeprefix('extra-')} extra", "kind": "extra", "bundled": False}
        for x in extras]


def emit(root: Path | None, by: str, at: str | None = None) -> dict:
    """The Brain's catalogue as a catalogue/v1 document: its modules (the registry's that list capabilities, else one
    per capability of the engine: brain.mod.catalogue), their bricks, dependencies, requirements, costs, fallbacks
    and licence, the engine and its extras as distributions, and the engine's three bases as presets."""
    from . import __version__, mod, modules, tiers

    reg, _ = tiers.registry(root)
    store = mod._store(root)
    registry = (modules.registry(store, root) or []) if store is not None else []
    entries = {str(e["id"]): e for e in registry}
    cat = mod.catalogue(root, reg, store)
    edges = mod.needs(cat, reg)
    owner = {c: m.id for m in cat.values() for c in m.capabilities}
    licence = _licence()
    out_mods = []
    for m in cat.values():
        deps = sorted(edges.get(m.id, ()))
        out_mods.append(_module(m, reg, entries.get(m.id, {}) if m.from_registry else {}, deps,
                                _soft(m, cat, reg, owner, deps), licence))
    sources = [f"{tiers.FILE.name} (brain {__version__})"] + ([str(modules.REGISTRY)] if registry else [])
    return {"schema": ID,
            "generated": {"at": at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "by": by,
                          "from": sources},
            "bricks": [{"id": b} for b in sorted({m["brick"] for m in out_mods if "brick" in m})],
            "modules": out_mods, "distributions": _distributions(out_mods, licence, __version__),
            "presets": _presets_of(cat, reg)}
