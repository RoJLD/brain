"""Presets and personas (brain.presets): the sets of modules and distributions a module registry's installer offers,
and the two checks of each one against the map of realisations (brain.modulemap). Zero token.

A store that keeps a registry (``modules.yaml``, brain.modules) may keep beside it ``personas.yaml``
(``schemas/personas.schema.json``, ``v: 1``): its presets, each a set of ``bricks`` (a brick gives every module of the
registry with that brick, except the statuses and placements ``expand`` skips: ``proposed`` by default),
``modules`` (each taken alone), ``distributions`` (what it downloads, as the map's ``ships_in`` names them),
``optional`` bricks and modules (a second variant, checked too) and ``ai`` (whether it uses AI). A persona is a
preset the platform's documents describe: an import session reads them (the engine never does) and writes the file
with its ``source`` and the day ``imported``; a correction goes through the documents and a new import.

``brain modules --check`` validates the file (exit 1; brain check warns): its version (a higher ``v`` refused alone),
its shape (an unknown key a note in read mode, an error in strict mode), ids unique, every brick and module it names
known to the registry, no source dated after the import. ``brain modules --personas`` runs the two checks on each
preset's set (its variant with ``optional`` apart):

1. **closed under hard dependencies**: every ``depends_on`` of its modules, direct or not, is in the set; ``open``
   names each one missing and who needs it. A module whose dependencies the map has not classified (an entry without
   the map, or a ``declared`` dependency in neither ``depends_on`` nor ``uses``) is shown, and the set is
   ``incomplete`` rather than ``closed``: the check never passes on what it cannot see.
2. **no AI without AI**: a preset whose ``ai`` is false pulls no AI module (``ai: true`` in the map), lists no
   distribution that ships one (an *AI distribution*: a live realisation of an AI module ``ships_in`` it), and none of
   its modules is shipped by AI distributions only; ``violated`` names each. A module no realisation ships is shown,
   never counted. A preset that uses AI, or does not say, is not checked (``-``).

Its exit is 1 when a preset is open or violated; brain check warns of them (never fails).
"""

from __future__ import annotations

from pathlib import Path

from . import graph, modulemap, modules, schema

FILE = "personas.yaml"
KIND = "personas"   # the schema: schemas/personas.schema.json
SKIP_STATUS = ("proposed",)   # a brick gives no proposed module unless expand says otherwise
CLOSED, INCOMPLETE, OPEN = "closed", "incomplete", "open"
OK, VIOLATED, UNCHECKED = "ok", "violated", "-"


def path(store: Path, root: Path | None = None) -> Path | None:
    """``personas.yaml`` beside the registry ``store`` reads (its own, or the one config.json modules.store names);
    None when the store reads no registry."""
    reg = modules.registry_file(store, root)
    return None if reg is None else reg.parent / FILE


def _own(store: Path, root: Path | None) -> Path | None:
    """The file, on the store that keeps the registry only (a store that reads another's: that store's check says
    it, once); None when there is none."""
    f = path(store, root)
    return f if (store / modules.REGISTRY).is_file() and f is not None and f.is_file() else None


def load(f: Path) -> tuple[dict | None, list[str]]:
    """(the document, []) or (None, [why it is no document of this format])."""
    try:
        data = graph._yaml().safe_load(f.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, graph._yaml().YAMLError) as exc:
        return None, [f"{FILE}: not a YAML document ({type(exc).__name__})"]
    if not isinstance(data, dict):
        return None, [f"{FILE}: expected a mapping (v, personas), got {type(data).__name__}"]
    return data, []


def _ids(value) -> list[str]:
    return [str(x) for x in value] if isinstance(value, list) else []


def _presets(doc: dict) -> list[dict]:
    found = doc.get("personas")
    return [p for p in found if isinstance(p, dict) and isinstance(p.get("id"), str)] if isinstance(found, list) else []


def _shape(doc: dict) -> list[str]:
    s = schema.load(KIND)
    errors: list[str] = []
    unknown: list[tuple[str, str]] = []
    schema._validate(doc, s, s, FILE, errors, unknown)
    for where, key in unknown:
        errors += schema.tolerate(f"{where}: unknown field {key!r}")
    return errors


def _provenance(doc: dict) -> list[str]:
    day, out = modules._day(doc.get("imported")), []
    if "imported" in doc and day is None:
        out.append(f"{FILE}.imported: {doc['imported']!r} is not a day (YYYY-MM-DD)")
    for i, s in enumerate(doc.get("source") if isinstance(doc.get("source"), list) else []):
        when = modules._day(s.get("date")) if isinstance(s, dict) else None
        if isinstance(s, dict) and "date" in s and when is None:
            out.append(f"{FILE}.source[{i}].date: {s['date']!r} is not a day (YYYY-MM-DD)")
        elif when is not None and day is not None and when > day:
            out.append(f"{FILE}.source[{i}]: dated {when}, after the import of {day}")
    return out


def _named(p: dict) -> tuple[list[str], list[str]]:
    """(bricks, modules) a preset names, its optional ones included."""
    opt = p.get("optional") if isinstance(p.get("optional"), dict) else {}
    return _ids(p.get("bricks")) + _ids(opt.get("bricks")), _ids(p.get("modules")) + _ids(opt.get("modules"))


def _references(doc: dict, reg: list[dict]) -> list[str]:
    known, bricks, seen, out = {str(m["id"]) for m in reg}, {str(m.get("brick")) for m in reg}, set(), []
    for p in _presets(doc):
        pid = p["id"]
        if pid in seen:
            out.append(f"{FILE}: preset {pid} given twice")
        seen.add(pid)
        named_bricks, named_mods = _named(p)
        out += [f"{pid}: brick {b} is the brick of no module of {modules.REGISTRY}" for b in named_bricks
                if b not in bricks]
        out += [f"{pid}: module {m} is not in {modules.REGISTRY}" for m in named_mods if m not in known]
    return out


def problems(store: Path, root: Path | None = None) -> list[str]:
    """What ``brain modules --check`` refuses in ``personas.yaml`` (exit 1), on the store that keeps the registry;
    [] without the file."""
    f = _own(store, root)
    if f is None:
        return []
    doc, why = load(f)
    if doc is None:
        return why
    refused = schema.newer(FILE, doc.get("v"), schema.known_v(KIND))
    if refused:
        return [refused]   # its other keys may mean something else
    return list(dict.fromkeys(_shape(doc) + _provenance(doc) + _references(doc, modules.registry(store, root) or [])))


# --- the two checks ---

def _rules(doc: dict) -> tuple[set[str], set[str]]:
    e = doc.get("expand") if isinstance(doc.get("expand"), dict) else {}
    status = e.get("skip_status")
    return (set(_ids(status)) if isinstance(status, list) else set(SKIP_STATUS)), set(_ids(e.get("skip_placement")))


def expand(bricks: list[str], mods: list[str], reg: dict[str, dict], rules: tuple[set[str], set[str]]) -> list[str]:
    """The modules of a set: each brick's (by the registry's order, its skipped statuses and placements left out),
    then each module named (once)."""
    skip_status, skip_placement = rules
    out = [mid for b in bricks for mid, m in reg.items() if str(m.get("brick")) == b
           and str(m.get("status")) not in skip_status and str(m.get("placement")) not in skip_placement]
    return list(dict.fromkeys(out + [m for m in mods if m in reg]))


def _classified(m: dict) -> bool:
    """The map has classified the module's dependencies: it carries the map, and each declared one is hard or soft."""
    classified = _ids(m.get("depends_on")) + _ids(m.get("uses"))
    return modulemap.has_map(m) and all(d in classified for d in _ids(m.get("declared")))


def closure(held: list[str], reg: dict[str, dict]) -> dict[str, list[str]]:
    """{a module the set misses: the modules of the set, or pulled, that need it}: the hard dependencies of the map,
    direct or not. Iterative: a long chain is no recursion error."""
    missing: dict[str, list[str]] = {}
    todo, seen = list(held), set(held)
    while todo:
        x = todo.pop(0)
        for d in _ids(reg.get(x, {}).get("depends_on")):
            if d not in reg or d in held:
                continue   # an unknown id is brain modules --check's to report
            missing.setdefault(d, []).append(x)
            if d not in seen:
                seen.add(d)
                todo.append(d)
    return missing


def shipping(reg: dict[str, dict]) -> dict[str, list[str]]:
    """{module: the distributions its live realisations ship in}, from the map's ``ships_in``."""
    return {mid: list(dict.fromkeys(str(r["ships_in"]) for r in modulemap._live(m) if r.get("ships_in")))
            for mid, m in reg.items()}


def ai_distributions(reg: dict[str, dict], ships: dict[str, list[str]]) -> dict[str, list[str]]:
    """{a distribution that ships an AI module: those modules}."""
    out: dict[str, list[str]] = {}
    for mid, dists in ships.items():
        if reg[mid].get("ai") is True:
            for d in dists:
                out.setdefault(d, []).append(mid)
    return out


def _no_ai(p: dict, full: list[str], reg: dict[str, dict], ships: dict[str, list[str]],
           ai_dists: dict[str, list[str]]) -> dict:
    if p.get("ai") is not False:
        return {"no_ai": UNCHECKED}
    found = {"ai_modules": [m for m in full if reg[m].get("ai") is True],
             "ai_distributions": [d for d in _ids(p.get("distributions")) if d in ai_dists],
             "only_ai": {m: ships[m] for m in full if ships[m] and all(d in ai_dists for d in ships[m])},
             "unshipped": [m for m in full if not ships[m]]}
    bad = found["ai_modules"] or found["ai_distributions"] or found["only_ai"]
    return {"no_ai": VIOLATED if bad else OK, **found}


def _variant(p: dict, label: str, bricks: list[str], mods: list[str], ctx: tuple) -> dict:
    reg, rules, ships, ai_dists = ctx
    held = expand(bricks, mods, reg, rules)
    missing = closure(held, reg)
    full = held + [m for m in missing if m not in held]
    unclassified = [m for m in full if not _classified(reg[m])]
    state = OPEN if missing else INCOMPLETE if unclassified else CLOSED
    known = {d for ds in ships.values() for d in ds}
    return {"id": p["id"], "variant": label, "name": str(p.get("name") or ""), "modules": held,
            "closure": state, "missing": missing, "unclassified": unclassified,
            "distributions": _ids(p.get("distributions")),
            "unknown_distributions": [d for d in _ids(p.get("distributions")) if d not in known],
            **_no_ai(p, full, reg, ships, ai_dists)}


def report(store: Path, root: Path | None = None) -> list[dict]:
    """The two checks on each preset of the file (and its variant with ``optional``); [] without the file, or when
    it is refused (a newer v, not a document: brain modules --check says why)."""
    f = _own(store, root)
    doc = load(f)[0] if f is not None else None
    if doc is None or schema.newer(FILE, doc.get("v"), schema.known_v(KIND)):
        return []
    reg = {str(m["id"]): m for m in modules.registry(store, root) or []}
    ships = shipping(reg)
    ctx = (reg, _rules(doc), ships, ai_distributions(reg, ships))
    out = []
    for p in _presets(doc):
        bricks, mods = _ids(p.get("bricks")), _ids(p.get("modules"))
        out.append(_variant(p, "", bricks, mods, ctx))
        opt = p.get("optional") if isinstance(p.get("optional"), dict) else {}
        extra_bricks, extra_mods = _ids(opt.get("bricks")), _ids(opt.get("modules"))
        if extra_bricks or extra_mods:
            label = "+" + "+".join(extra_bricks + extra_mods)
            out.append(_variant(p, label, bricks + extra_bricks, mods + extra_mods, ctx))
    return out


def failed(r: dict) -> bool:
    return r["closure"] == OPEN or r["no_ai"] == VIOLATED


def _who(r: dict) -> str:
    return r["id"] + (f" {r['variant']}" if r["variant"] else "")


def _faults(r: dict) -> list[str]:
    """One line per fault of a variant: a hard dependency missing, an AI module, an AI distribution listed, a module
    shipped by AI distributions only."""
    who = _who(r)
    out = [f"{who}: misses {d}, a hard dependency of {', '.join(by)}" for d, by in r["missing"].items()]
    out += [f"{who}: without AI, pulls the AI module {m}" for m in r.get("ai_modules", [])]
    out += [f"{who}: without AI, lists {d}, a distribution that ships AI modules" for d in r.get("ai_distributions", [])]
    out += [f"{who}: without AI, {m} is shipped only by {', '.join(ds)}, which ship AI modules"
            for m, ds in r.get("only_ai", {}).items()]
    return out


def warnings(store: Path, root: Path | None = None) -> list[str]:
    """What brain check warns of, never a failure: each fault of an open or violated preset."""
    return [line for r in report(store, root) if failed(r) for line in _faults(r)]


def lines(found: list[dict]) -> list[str]:
    """``brain modules --personas``' text: a line per variant (its closure and its AI check), then its faults and what
    it shows without judging (the modules to classify, those no realisation ships, distributions the map does not
    know)."""
    if not found:
        return [f"no {FILE} beside the registry (or none this engine reads: brain modules --check)"]
    out = []
    for r in found:
        out.append(f"{_who(r)} ({r['name']}): {len(r['modules'])} module(s), closure {r['closure']}, "
                   f"no AI {r['no_ai']}")
        out += [f"  {line}" for line in _faults(r)]
        if r["unclassified"]:
            out.append(f"  to classify ({len(r['unclassified'])}): {', '.join(r['unclassified'])}")
        if r.get("unshipped"):
            out.append(f"  shipped by no realisation: {', '.join(r['unshipped'])}")
        if r["unknown_distributions"]:
            out.append(f"  distributions no realisation ships in: {', '.join(r['unknown_distributions'])}")
    bad = sum(failed(r) for r in found)
    out.append(f"{len(found)} preset variant(s): {bad} open or violated, "
               f"{sum(r['closure'] == INCOMPLETE for r in found)} incomplete")
    return out
