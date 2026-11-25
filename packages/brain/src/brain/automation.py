"""The automation levels resolved (wi-brain-automation-config, spec-brain-automation-levels S2; docs/automation.md):
for each gesture of the automation catalogue (brain.gestures.CATALOGUE), the level it runs at (manual, ask or auto)
and where that level comes from, in three layers:

1. **the engine's default** (``Automation.default``): today's behaviour. A new engine never raises a level by itself;
2. **config.json's ``automation`` section**, version 1: ``{"v": 1, "levels": {gesture id: level}}``. A gesture left
   out keeps its default. Raising a level is the owner's (``automation-raise``, a floor gesture): their merge of
   config.json is the raise (AUTO-5). When ``$BRAIN_CONFIG`` names another file than the one found without it
   (brain.config.anchored), a level is the lower of the two, so a config.json a session wrote never raises one; when
   none is found without it, the cap is the engine's default (an empty anchor layer): ``$BRAIN_CONFIG`` only lowers;
3. **the machine file** ``<BRAIN_HOME>/automation.json``, of the same shape: it may only lower a level (anyone may
   lower one, a session after an incident included); a level it gives above the one it would lower is ignored.

Fail closed (AUTO-1, ``les-brain-guard-fails-open``): every level passes brain.gestures.effective, so a level that is
not one of the three, one above the gesture's ceiling and any level of a floor gesture read manual; a config.json that
cannot be read (or that this engine's version does not reach), an ``automation`` section that is not an object or
whose ``v`` this engine does not know, and a machine file that cannot be read or whose ``v`` it does not know, make
every gesture read manual. An id the catalogue does not hold is ignored (an older engine reading a newer config), a
note of ``brain config --check``; a retired id too.

The guards read it (wi-brain-automation-guard, S3: :func:`enforce`, :func:`native_rules`; the block before
:data:`CARD_MODES`). ``brain automation list`` and ``brain automation explain`` print it. Standard library only (brain.config and brain.paths imported when the
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


def _shape_error(data, label: str) -> str:
    """Why ``data`` is no layer this engine reads ('' when it is): not an object, a ``v`` other than
    :data:`SECTION_V` (absent reads 1), or ``levels`` not an object."""
    if not isinstance(data, dict):
        return f"{label} is a {type(data).__name__}, not an object"
    v = data.get("v", SECTION_V)
    if type(v) is int and v > SECTION_V:   # type(): a bool is no version
        return f"{label}: v{v} is written by a newer brain, which this one cannot read: brain update"
    if type(v) is not int or v != SECTION_V:
        return f"{label}: v is {v!r}, not {SECTION_V}"
    levels = data.get("levels", {})
    return "" if isinstance(levels, dict) else \
        f"{label}: levels is a {type(levels).__name__}, not an object of gesture id -> level"


def _issue(gid: str, level) -> tuple[str, str]:
    """(kind, what) of a level this engine does not take as written: ``('', '')`` when it does; ``floor`` a floor
    gesture above manual; ``type`` a level that is not a string (config.json's schema refuses it); ``note`` an id the
    catalogue does not hold (ignored), a level it does not know or one above the gesture's ceiling (read manual)."""
    a = gestures.automation(gid)
    if a is None:
        kind = "a retired gesture" if gid in gestures.RETIRED else "no gesture of this engine's catalogue"
        return "note", f"{kind}, ignored (brain automation list)"
    if level not in gestures.LEVELS:
        return ("note" if isinstance(level, str) else "type"), \
            f"{level!r} is no level ({', '.join(gestures.LEVELS)}): it reads manual"
    if gestures.effective(a, level) == level:
        return "", ""
    if a.floor:
        return "floor", f"{level}, but {gid} is the floor's ({a.floor}): no config lifts it, it reads manual"
    return "note", f"{level} is above its ceiling, {a.ceiling}: it reads manual"


def parse(data, name: str, where: str) -> Layer:
    """A layer from ``data``, the ``automation`` section's value or the machine file's content: an object with ``v``
    (absent reads 1) and ``levels``; another shape, or a ``v`` this engine does not know, is an error (fail closed).
    What it holds this engine ignores or reads manual is a note."""
    layer = Layer(name, where, present=True)
    label = f"{where} automation" if name != "machine" else where
    layer.error = _shape_error(data, label)
    if layer.error:
        return layer
    layer.levels = {str(k): x for k, x in data.get("levels", {}).items()}
    layer.notes += [f"{label}: unknown key {k!r}, ignored (a newer brain's?)" for k in data if k not in _KNOWN_KEYS]
    for gid, level in layer.levels.items():
        what = _issue(gid, level)[1]
        if what:
            layer.notes.append(f"{label}.levels {gid!r}: {what}")
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
    """The machine file as a layer: none (an empty layer) when it does not exist; one that cannot be read (any other
    OSError: a denied access included) or parsed is an error, so every gesture reads manual (it was there to lower).
    No ``exists()`` first: it raises outside the try on Python 3.10-3.13 and hides the error on 3.14."""
    path = path or machine_file()
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (FileNotFoundError, NotADirectoryError):
        return Layer("machine", str(path))
    except OSError as exc:
        return Layer("machine", str(path), error=f"{path}: cannot be read ({exc})", present=True)
    try:
        data = json.loads(text)
    except ValueError as exc:
        return Layer("machine", str(path), error=f"{path}: not readable JSON ({exc})", present=True)
    return parse(data, "machine", str(path))


def layers(cfg=None, anchor=None, machine: Layer | None = None) -> tuple[Layer, Layer | None, Layer]:
    """(config, anchor, machine): ``cfg`` brain.config.load() when None, ``anchor`` :func:`anchor_config` when None
    (pass False for none), ``machine`` :func:`machine_layer` when None."""
    from . import config
    cfg = cfg if cfg is not None else config.load()
    if anchor is None:
        anchor = anchor_config(cfg)
    return (config_layer(cfg), config_layer(anchor, "anchor") if anchor else None,
            machine if machine is not None else machine_layer())


def anchor_config(cfg):
    """The config.json that caps the one ``$BRAIN_CONFIG`` names: brain.config.anchored's (the one found without it,
    when that is another file); when none is found without it, an empty config (the engine's defaults), so that a file
    a session wrote only lowers; None when BRAIN_CONFIG is unset or names the file found without it."""
    from . import config
    if not os.environ.get("BRAIN_CONFIG"):
        return None
    if config.base_file() is None:
        return config.Config(None, cfg.root)
    return config.anchored(cfg)


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
            level, source = held, "config" if anchor.where else "default"
            plain = (f"the config.json found without BRAIN_CONFIG: {held}" if anchor.where else
                     f"no config.json found without BRAIN_CONFIG: the engine's default, {held}")
            steps.append(f"{astep or plain}: the lower holds")
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


def one(gesture_id: str, cfg=None) -> Resolved:
    """``gesture_id``'s :class:`Resolved` here: manual (source ``default``) for an id the catalogue does not hold, and
    manual (source ``error``) when the layers cannot be read at all (fail closed: what reads a level never raises)."""
    a = gestures.automation(gesture_id)
    if a is None:
        return Resolved(gesture_id, "manual", "default", (f"{gesture_id}: no gesture of this engine's catalogue: "
                                                          "manual (fail closed)",))
    try:
        config, held, mach = layers(cfg)
        return resolve_one(a, config, held, mach)
    except Exception as exc:   # an engine bug or a file system error: no level is a manual one
        return Resolved(a.id, "manual", "error", (f"the levels cannot be read ({type(exc).__name__}: {exc}): manual "
                                                  "(fail closed)",))


def level(gesture_id: str, cfg=None) -> str:
    """The level ``gesture_id`` runs at here: manual for an id the catalogue does not hold (fail closed)."""
    return one(gesture_id, cfg).level


# --- enforcement (wi-brain-automation-guard, spec-brain-automation-levels S3; docs/automation.md) ----------------------
# What the guards make of a level. A session's gesture with a tool of the app (archive_session, set_remote_control) is
# judged by the guard hook (brain.guards.main), which reads its level on every call:
#   manual  refused to the session, inside its conditions too: the owner does it;
#   ask     inside its conditions the guard says nothing and the native rule decides: brain permissions render writes
#           an ask rule for the tool (the app's card, which an ask rule shows in every mode but dontAsk); outside them
#           the guard's own ask (archive_session) or its refusal (set_remote_control, as before);
#   auto    inside its conditions the guard allows it (permissionDecision allow: no card); outside them as at ask.
# Where the session's permission mode shows no card for a hook's ask (CARD_MODES: the probe of 2026-11-25), ask falls
# back to manual (the safe direction); a mode the payload does not give, or one this engine does not know, shows none.
# The engine clone's pull is judged by brain.engineclone.refresh (brain refresh, brain release apply): in an agent's
# session it pulls at auto only. A gesture of the owner's terminal stays refused to a session at every level: its
# level is what their own terminal does (spec § 3.1). The harness's gestures (merge-go, workflow-launch) are its own.
CARD_MODES = ("default", "acceptEdits", "plan", "auto")   # the permission modes where a hook's ask shows the card
TOOLS = {   # the app's tools a session's gesture runs through: {tool: the gestures that use it}
    "mcp__ccd_session_mgmt__archive_session": ("session-archive",),
    "mcp__ccd_session_mgmt__set_remote_control": ("handover-remote-control", "session-archive"),
}
NATIVE = {"manual": "deny", "ask": "ask", "auto": "allow"}   # a level as the app's native permission rule


def card(mode) -> bool:
    """Whether a hook's ask shows the app's card in the permission mode ``mode`` (the payload's ``permission_mode``):
    one of :data:`CARD_MODES`; None, another value or a mode this engine does not know shows none (fail closed)."""
    return isinstance(mode, str) and mode in CARD_MODES


@dataclass(frozen=True)
class Enforced:
    """What the guard does with a gesture's call: ``decision`` the hook's permissionDecision (deny, ask or allow), ''
    when it says nothing (the native rules decide); ``level`` and ``source`` the gesture's (:func:`one`); ``why`` one
    line for the reason and the ledger."""
    gesture: str
    decision: str
    level: str
    source: str
    why: str


def enforce(gesture_id: str, inside: bool, mode, resolved: Resolved | None = None) -> Enforced:
    """What the guard does with a call of ``gesture_id``, ``inside`` its conditions or not, in the permission mode
    ``mode`` (the block above). Never raises: a level that cannot be read is manual."""
    r = resolved if resolved is not None else one(gesture_id)
    lvl = r.level if r.level in gestures.LEVELS else "manual"
    named = f"{gesture_id} is at level {lvl} ({r.source}: brain automation explain {gesture_id})"
    if lvl == "manual":
        return Enforced(gesture_id, "deny", lvl, r.source, f"{named}: its owner does it")
    if lvl == "auto" and inside:
        return Enforced(gesture_id, "allow", lvl, r.source, f"{named}, and its conditions hold: no card")
    if not card(mode):
        shown = json.dumps(mode) if isinstance(mode, str) else "none given"
        return Enforced(gesture_id, "deny", "manual", r.source,
                        f"{named}, but the permission mode ({shown[:40]}) shows no card for an ask: it reads manual "
                        "(docs/automation.md)")
    if inside:
        return Enforced(gesture_id, "", lvl, r.source, f"{named}: its conditions hold, the native rule decides")
    return Enforced(gesture_id, "ask", lvl, r.source, f"{named}: outside its conditions, the owner's card")


def native_rules(resolved: dict[str, Resolved] | None = None) -> dict[str, dict]:
    """{tool: {level, verdict, gestures}} for each app tool of :data:`TOOLS`: the highest level of the gestures that
    use it, as its native rule (:data:`NATIVE`: allow, ask or deny), since the guard judges each call apart and a
    native rule above it may only let the guard's own decision stand (an ask or a deny rule wins over a hook's allow).
    ``brain permissions render --level user`` writes it; the other two verdicts of the tool are taken out."""
    resolved = resolved if resolved is not None else resolve()
    out = {}
    for tool, ids in TOOLS.items():
        levels = [resolved[g].level if g in resolved else "manual" for g in ids]
        top = max(levels, key=_rank)
        out[tool] = {"level": top, "verdict": NATIVE[top], "gestures": list(ids)}
    return out


def enforcement(a: gestures.Automation, lvl: str) -> str:
    """One line on what enforces ``a`` at ``lvl`` (``brain automation explain``)."""
    tools = [t for t, ids in TOOLS.items() if a.id in ids]
    if a.floor:
        return "the floor: refused to a session at every level"
    if tools:
        what = {"manual": "the guard refuses it to a session, inside its conditions too",
                "ask": "inside its conditions the native ask rule shows the card (an ask reads manual in a mode with "
                       "no card); outside them the guard asks or refuses",
                "auto": "inside its conditions the guard allows it, no card; outside them it asks or refuses"}[lvl]
        return f"{what} ({', '.join(t.rsplit('__', 1)[-1] for t in tools)})"
    if a.id == "engine-clone-pull":
        return ("brain refresh and brain release apply pull it in a session" if lvl == "auto" else
                "in a session brain refresh does not pull it, and says the command")
    if a.runs in ("terminal", "elevated"):
        return "refused to a session at every level; the level is what the owner's own terminal does"
    return "the harness's own confirmation: the Brain does not change it"


def check(cfg) -> list[str]:
    """What config.json's ``automation`` section breaks that its schema cannot say (brain.config.check): a floor
    gesture set above manual (no config lifts the floor: an error in both modes). An id the catalogue does not hold, a
    level that is not one of the three and one above a gesture's ceiling are notes in read mode (an older engine
    reading a newer config; they read manual or are ignored), errors in strict mode (CI: the engine there is the pin).
    A section this engine cannot read is an error, every gesture then reading manual (its schema says why too)."""
    data = cfg.data if isinstance(cfg.data, dict) else {}
    if KEY not in data:
        return []
    from . import config, schema
    if schema.newer(config.FILE, data.get("v"), schema.known_v("config")):
        return []   # a newer brain's file: refused as a whole, its other keys not judged
    shape = _shape_error(data[KEY], f"{config.FILE}: {KEY}")
    if shape:
        return [f"{shape} (every gesture reads manual)"]
    errors: list[str] = []
    where = f"{config.FILE}: {KEY}.levels"
    for gid, asked in data[KEY].get("levels", {}).items():
        kind, what = _issue(str(gid), asked)
        if kind == "floor":
            errors.append(f"{where} {gid!r}: {what} (set it to manual or remove it)")
        elif kind == "note":
            errors += schema.tolerate(f"{where} {gid!r}: {what}")
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
                    "steps": list(r.steps), "enforced": enforcement(a, r.level)})
    lay = [x for x in (config, held, mach) if x is not None]
    return {"v": gestures.CATALOGUE_V, "section_v": SECTION_V, "levels": list(gestures.LEVELS),
            "layers": [{"name": x.name, "where": x.where or None, "present": x.present, "error": x.error or None,
                        "notes": list(x.notes)} for x in lay],
            "gestures": out}
