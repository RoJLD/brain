"""The automation levels resolved (wi-brain-automation-config, spec-brain-automation-levels S2; docs/automation.md):
for each gesture of the automation catalogue (brain.gestures.CATALOGUE), the level it runs at (manual, ask or auto)
and where that level comes from, in three layers:

1. **the engine's default** (``Automation.default``): today's behaviour. A new engine never raises a level by itself;
2. **config.json's ``automation`` section**, version 1: ``{"v": 1, "levels": {gesture id: level}}``. A gesture left
   out keeps its default. Raising a level is the owner's (``automation-raise``, a floor gesture): their merge of
   config.json is the raise (AUTO-5). When ``$BRAIN_CONFIG`` names another file than the one found without it
   (brain.config.anchored), a level is the lower of the two, so a config.json a session wrote never raises one;
3. **the machine file** ``<BRAIN_HOME>/automation.json``, of the same shape: it may only lower a level (anyone may
   lower one, a session after an incident included); a level it gives above the one it would lower is ignored.

Fail closed (AUTO-1, ``les-brain-guard-fails-open``): every level passes brain.gestures.effective, so a level that is
not one of the three, one above the gesture's ceiling and any level of a floor gesture read manual; a config.json that
cannot be read (or that this engine's version does not reach), an ``automation`` section that is not an object or
whose ``v`` this engine does not know, and a machine file that cannot be read or whose ``v`` it does not know, make
every gesture read manual. An id the catalogue does not hold is ignored (an older engine reading a newer config), a
note of ``brain config --check``; a retired id too.

Nothing enforces a level yet: the guards that read it are wi-brain-automation-guard (S3). ``brain automation list``
and ``brain automation explain`` print it. Standard library only (brain.config and brain.paths imported when the
caller gives no data), so that the guard hook may import it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from . import gestures

KEY = "automation"            # config.json's section
SECTION_V = 1                 # the section's version, and the machine file's: one shape for both
MACHINE_FILE = "automation.json"   # <BRAIN_HOME>/automation.json: this machine's lowering
SOURCES = ("default", "config", "machine")   # where a level comes from (brain automation list's source)
_KNOWN_KEYS = ("v", "levels")


@dataclass
class Layer:
    """One layer's levels as read: ``levels`` {gesture id: level as written}, ``error`` why the layer cannot be read
    ('' when it can: every gesture then reads manual), ``notes`` what it holds this engine ignores."""
    name: str                       # config, anchor or machine
    where: str                      # the file it was read from, '' when there is none
    levels: dict = field(default_factory=dict)
    error: str = ""
    notes: list[str] = field(default_factory=list)
    present: bool = False           # the file or section exists


@dataclass(frozen=True)
class Resolved:
    """A gesture's level: ``level`` what it runs at, ``source`` the layer that set it (:data:`SOURCES`), ``steps`` why,
    one line per layer, in order."""
    id: str
    level: str
    source: str
    steps: tuple[str, ...]


def _rank(level: str) -> int:
    return gestures.LEVELS.index(level)


def parse(data, name: str, where: str) -> Layer:
    """A layer from ``data``, the ``automation`` section's value or the machine file's content: an object with ``v``
    (absent reads 1) and ``levels``; another shape, or a ``v`` this engine does not know, is an error (fail closed)."""
    layer = Layer(name, where, present=True)
    label = f"{where} automation" if name != "machine" else where
    if not isinstance(data, dict):
        layer.error = f"{label} is a {type(data).__name__}, not an object"
        return layer
    v = data.get("v", SECTION_V)
    if isinstance(v, bool) or not isinstance(v, int) or v != SECTION_V:
        layer.error = (f"{label}: v{v} is written by a newer brain, which this one cannot read: brain update"
                       if isinstance(v, int) and not isinstance(v, bool) and v > SECTION_V
                       else f"{label}: v is {v!r}, not {SECTION_V}")
        return layer
    levels = data.get("levels", {})
    if not isinstance(levels, dict):
        layer.error = f"{label}: levels is a {type(levels).__name__}, not an object of gesture id -> level"
        return layer
    layer.levels = {str(k): x for k, x in levels.items()}
    layer.notes += [f"{label}: unknown key {k!r}, ignored (a newer brain's?)" for k in data if k not in _KNOWN_KEYS]
    for gid, level in layer.levels.items():
        a = gestures.automation(gid)
        if a is None:
            kind = "a retired gesture" if gid in gestures.RETIRED else "no gesture of this engine's catalogue"
            layer.notes.append(f"{label}.levels {gid!r}: {kind}, ignored (brain automation list)")
        elif level not in gestures.LEVELS:
            layer.notes.append(f"{label}.levels {gid!r}: {level!r} is no level ({', '.join(gestures.LEVELS)}): "
                               "it reads manual")
        elif gestures.effective(a, level) != level:
            why = f"{gid} is the floor's ({a.floor})" if a.floor else f"above its ceiling, {a.ceiling}"
            layer.notes.append(f"{label}.levels {gid!r}: {level} is {why}: it reads manual")
    return layer


def config_layer(cfg, name: str = "config") -> Layer:
    """config.json's ``automation`` section as a layer (``cfg`` a brain.config.Config). A file that exists but
    cannot be read, one whose ``v`` this engine does not reach, or a ``$BRAIN_CONFIG`` naming no file, is an error;
    no config.json at all, or one without the section, an empty layer (the defaults)."""
    where = str(cfg.file) if cfg.file is not None else ""
    if cfg.error and (cfg.file is not None or os.environ.get("BRAIN_CONFIG")):
        return Layer(name, where or os.environ.get("BRAIN_CONFIG", ""), error=cfg.error, present=True)
    data = cfg.data if isinstance(cfg.data, dict) else {}
    v = data.get("v")
    from . import schema
    try:
        newer = schema.newer("config.json", v, schema.known_v("config"))
    except (OSError, ValueError, KeyError) as exc:   # the engine's own schema is broken: fail closed
        newer = f"the engine's config.schema.json cannot be read ({exc}): brain update"
    if newer:
        return Layer(name, where, error=newer, present=True)
    if KEY not in data:
        return Layer(name, where)
    return parse(data[KEY], name, where or "config.json")


def machine_file() -> Path:
    from . import paths
    return paths.brain_home() / MACHINE_FILE


def machine_layer(path: Path | None = None) -> Layer:
    """The machine file as a layer: none (an empty layer) when it does not exist; one that cannot be read or parsed is
    an error, so every gesture reads manual (it was there to lower)."""
    path = path or machine_file()
    if not path.exists():
        return Layer("machine", str(path))
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return Layer("machine", str(path), error=f"{path}: not readable JSON ({exc})", present=True)
    return parse(data, "machine", str(path))


def layers(cfg=None, anchor=None, machine: Layer | None = None) -> tuple[Layer, Layer | None, Layer]:
    """(config, anchor, machine): ``cfg`` brain.config.load() when None, ``anchor`` brain.config.anchored(cfg) when
    None (pass False for none), ``machine`` :func:`machine_layer` when None."""
    from . import config
    cfg = cfg if cfg is not None else config.load()
    if anchor is None:
        anchor = config.anchored(cfg)
    return (config_layer(cfg), config_layer(anchor, "anchor") if anchor else None,
            machine if machine is not None else machine_layer())


def _config_step(a: gestures.Automation, layer: Layer, label: str) -> tuple[str, str | None]:
    """(the level the layer gives ``a``, its step), the step None when the layer leaves it at the default."""
    if layer.error:
        return "manual", f"{label} cannot be read ({layer.error}): manual (fail closed)"
    if a.id not in layer.levels:
        return gestures.effective(a, a.default), None
    asked = layer.levels[a.id]
    got = gestures.effective(a, asked)
    return got, f"{label}: {asked}" + ("" if got == asked else f", read as {got} ({_why_manual(a, asked)})")


def _why_manual(a: gestures.Automation, asked) -> str:
    if asked not in gestures.LEVELS:
        return "no level"
    if a.floor:
        return f"the floor's: {a.floor}"
    return f"above its ceiling, {a.ceiling}"


def resolve_one(a: gestures.Automation, config: Layer, anchor: Layer | None, machine: Layer) -> Resolved:
    """``a``'s level through the three layers (the module's docstring)."""
    level = gestures.effective(a, a.default)
    source = "default"
    steps = [f"the engine's default: {a.default}" + ("" if level == a.default else f", read as {level}")]
    got, step = _config_step(a, config, f"config.json ({config.where})" if config.where else "config.json")
    if step:
        level, source = got, "config"
        steps.append(step)
    if anchor is not None:
        held, astep = _config_step(a, anchor, f"the config.json found without BRAIN_CONFIG ({anchor.where})")
        if _rank(held) < _rank(level):
            level, source = held, "config"
            steps.append(f"{astep or f'the config.json found without BRAIN_CONFIG: {held}'}: the lower holds")
    if machine.error:
        level, source = "manual", "machine"
        steps.append(f"the machine file cannot be read ({machine.error}): manual (fail closed)")
    elif a.id in machine.levels:
        asked = machine.levels[a.id]
        low = asked if asked in gestures.LEVELS else "manual"
        if _rank(low) < _rank(level):
            level, source = low, "machine"
            steps.append(f"the machine file ({machine.where}): {asked}" +
                         ("" if low == asked else ", no level: read as manual") + ", lowers it")
        elif _rank(low) > _rank(level):
            steps.append(f"the machine file ({machine.where}): {asked}, above {level}: ignored (it may only lower)")
        else:
            steps.append(f"the machine file ({machine.where}): {asked}, the same")
    final = gestures.effective(a, level)
    return Resolved(a.id, final, source, tuple(steps))


def resolve(cfg=None, anchor=None, machine: Layer | None = None) -> dict[str, Resolved]:
    """{gesture id: :class:`Resolved`} for every gesture of the catalogue, in its order (:func:`layers`' arguments)."""
    config, held, mach = layers(cfg, anchor, machine)
    return {a.id: resolve_one(a, config, held, mach) for a in gestures.CATALOGUE}


def level(gesture_id: str, cfg=None) -> str:
    """The level ``gesture_id`` runs at here: manual for an id the catalogue does not hold (fail closed)."""
    a = gestures.automation(gesture_id)
    if a is None:
        return "manual"
    config, held, mach = layers(cfg)
    return resolve_one(a, config, held, mach).level


def check(cfg) -> list[str]:
    """What config.json's ``automation`` section breaks that its schema cannot say (brain.config.check): a floor
    gesture set above manual (no config lifts the floor: an error in both modes). An id the catalogue does not hold, a
    level that is not one of the three and one above a gesture's ceiling are notes in read mode (an older engine
    reading a newer config; they read manual or are ignored), errors in strict mode (CI: the engine there is the pin)."""
    data = cfg.data if isinstance(cfg.data, dict) else {}
    if KEY not in data or not isinstance(data[KEY], dict) or not isinstance(data[KEY].get("levels"), dict):
        return []   # absent, or a shape the schema refuses already
    from . import config, schema
    if schema.newer(config.FILE, data.get("v"), schema.known_v("config")) or data[KEY].get("v", SECTION_V) != SECTION_V:
        return []   # a newer brain's file or section: refused as a whole, its other keys not judged
    errors: list[str] = []
    where = f"{config.FILE}: {KEY}.levels"
    for gid, asked in data[KEY]["levels"].items():
        a = gestures.automation(str(gid))
        if a is not None and a.floor and asked in gestures.LEVELS and asked != "manual":
            errors.append(f"{where} {gid!r}: {asked}, but {gid} is the floor's ({a.floor}): no config lifts it, it "
                          "reads manual (set it to manual or remove it)")
            continue
        if a is None:
            kind = "a retired gesture" if gid in gestures.RETIRED else "no gesture of this engine's catalogue"
            errors += schema.tolerate(f"{where} {gid!r}: {kind}, ignored (brain automation list)")
        elif not isinstance(asked, str):
            continue   # the schema's
        elif asked not in gestures.LEVELS:
            errors += schema.tolerate(f"{where} {gid!r}: {asked!r} is no level ({', '.join(gestures.LEVELS)}): it "
                                      "reads manual")
        elif gestures.effective(a, asked) != asked:
            errors += schema.tolerate(f"{where} {gid!r}: {asked} is above its ceiling, {a.ceiling}: it reads manual")
    return errors


def catalogue(resolved: dict[str, Resolved] | None = None) -> dict:
    """brain.gestures.catalogue with each gesture's level and source resolved (``brain automation list --json``)."""
    resolved = resolved if resolved is not None else resolve()
    data = gestures.catalogue()
    for g in data["gestures"]:
        r = resolved.get(g["id"])
        if r is not None:
            g["level"], g["source"] = r.level, r.source
    return data


def explain(gesture_id: str | None = None, cfg=None, anchor=None, machine: Layer | None = None) -> dict:
    """Why each gesture (or ``gesture_id`` alone) runs at its level: the layers read (each file, its errors and
    notes) and, per gesture, its default, ceiling, floor, what each layer asks and the steps. A ``KeyError`` for an id
    the catalogue does not hold."""
    config, held, mach = layers(cfg, anchor, machine)
    picked = gestures.CATALOGUE
    if gesture_id is not None:
        a = gestures.automation(gesture_id)
        if a is None:
            raise KeyError(gesture_id)
        picked = (a,)
    out = []
    for a in picked:
        r = resolve_one(a, config, held, mach)
        out.append({"id": a.id, "label": a.label, "level": r.level, "source": r.source, "default": a.default,
                    "ceiling": a.ceiling, "floor": a.floor or None, "locked": bool(a.floor), "runs": a.runs,
                    "config": config.levels.get(a.id), "machine": mach.levels.get(a.id),
                    "steps": list(r.steps)})
    lay = [x for x in (config, held, mach) if x is not None]
    return {"v": gestures.CATALOGUE_V, "section_v": SECTION_V, "levels": list(gestures.LEVELS),
            "layers": [{"name": x.name, "where": x.where or None, "present": x.present, "error": x.error or None,
                        "notes": list(x.notes)} for x in lay],
            "gestures": out}
