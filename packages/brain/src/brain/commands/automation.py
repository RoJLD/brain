"""``brain automation``: the automation catalogue (brain.gestures.CATALOGUE, wi-brain-automation-catalogue;
docs/automation.md): ``list`` prints every recurring owner gesture with its level, the level's source, its ceiling,
where it runs, its floor category and its conditions; ``explain [GESTURE]`` says why each one runs at its level, layer
by layer (brain.automation, wi-brain-automation-config: the engine's default, config.json's automation section, the
machine file that may only lower). Read only, zero token, machine-wide: no root (the config.json the guard reads)."""

from __future__ import annotations

import sys

from .. import automation, gestures
from ._common import _print_json

ORDER = 489   # its place in brain --help's list of commands (brain.commands): after floor
PHASE = "early"   # its handlers: early only, before any root is resolved (brain.commands)
NO_PROJECT = {"automation"}   # its parsers that take no --project after them
USAGE_ORDER = 369   # its usage lines' place in brain --help's epilog, after brain floor's
USAGE = """\
  brain automation list [--json]   the automation catalogue (docs/automation.md): every recurring owner gesture, the
                 ones a session runs too, with its id (the key of config.json's automation.levels), its level and
                 where that level comes from (default, config or machine), its ceiling (manual, ask or auto: the
                 highest level the engine allows), where it runs (a session, the owner's terminal, their elevated
                 terminal, the harness), its floor category (locked at manual: the never-grantable categories, the
                 elevated terminal, the rules' text, raising a level) and its conditions. Read only
  brain automation explain [GESTURE] [--json]   why each gesture (or GESTURE alone) runs at its level: the engine's
                 default, config.json's automation section (the lower of it and the config.json found without
                 $BRAIN_CONFIG, when that names another), then <BRAIN_HOME>/automation.json, which may only lower; a
                 level above the ceiling, unknown or unreadable, and any floor gesture's, reads manual. Exit 1 for an
                 id the catalogue does not hold. Read only
"""


def early(args) -> int:
    if args.automation_cmd == "explain":
        return _explain(args)
    data = automation.catalogue()
    if args.json:
        _print_json(data)
        return 0
    print("\n".join(_text(data)))
    return 0


def _explain(args) -> int:
    try:
        data = automation.explain(args.gesture)
    except KeyError:
        kind = "a retired gesture" if args.gesture in gestures.RETIRED else "no gesture of the catalogue"
        print(f"brain automation explain: {args.gesture!r} is {kind} (brain automation list prints the ids)",
              file=sys.stderr)
        return 1
    if args.json:
        _print_json(data)
        return 0
    print("\n".join(_explain_text(data)))
    return 0


LAYER_NAMES = {"config": "config.json", "anchor": "the config.json found without BRAIN_CONFIG",
               "machine": "the machine file"}


def _explain_text(data: dict) -> list[str]:
    """The layers read (each file, or none; its error and notes), then one block per gesture: its id, level and
    source, its ceiling and floor category, then each step."""
    out = []
    for layer in data["layers"]:
        where = layer["where"]
        if layer["present"]:
            state = where
        elif layer["name"] == "machine":
            state = f"none ({where})"
        else:
            state = f"{where}, no automation section" if where else "none (the defaults)"
        error = f"; cannot be read: {layer['error']} (every gesture reads manual)" if layer["error"] else ""
        out.append(f"{LAYER_NAMES[layer['name']]}: {state}{error}")
        out += [f"  note: {n}" for n in layer["notes"]]
    for g in data["gestures"]:
        lock = f"  locked: {g['floor']}" if g["locked"] else ""
        out.append(f"{g['id']}: {g['level']} ({g['source']})  ceiling {g['ceiling']}  runs: {g['runs']}{lock}")
        out += [f"    {i}. {s}" for i, s in enumerate(g["steps"], 1)]
    out.append("Raising a level is the owner's (automation-raise): their merge of config.json's automation section; "
               "lowering one is anyone's, there or in the machine file (docs/automation.md).")
    return out


def _text(data: dict) -> list[str]:
    """One block per gesture: its id, level (source), ceiling and where it runs, then its label, floor, commands,
    conditions and note, indented."""
    rows = data["gestures"]
    width = max(len(g["id"]) for g in rows)
    out = [f"automation catalogue v{data['v']}: {len(rows)} gestures, levels {' < '.join(data['levels'])}; "
           f"{sum(g['locked'] for g in rows)} locked by the floor"]
    for g in rows:
        lock = f"  locked: {g['floor']}" if g["locked"] else ""
        out.append(f"{g['id']:<{width}}  {g['level']:<6} ({g['source']})  ceiling {g['ceiling']:<6}  "
                   f"runs: {g['runs']}{lock}")
        out.append(f"    {g['label']}")
        if g["commands"]:
            out.append(f"    commands: {', '.join(g['commands'])}")
        out += [f"    if: {c}" for c in g["conditions"]]
        if g["note"]:
            out.append(f"    note: {g['note']}")
    out.append("A level above its ceiling, unknown or unreadable reads manual; the floor stays manual whatever "
               "config.json says (AUTO-1). runs: " + "; ".join(f"{k}, {v}" for k, v in data["runs"].items()))
    return out


def register(sub, ctx) -> None:
    a = sub.add_parser("automation", help="the automation catalogue: every recurring owner gesture, its level, "
                                          "ceiling, conditions and where it runs")
    asub = a.add_subparsers(dest="automation_cmd", required=True)
    lst = asub.add_parser("list", help="print the catalogue (read only)")
    lst.add_argument("--json", action="store_true", help="the catalogue as JSON (its v, levels, floor, gestures)")
    ex = asub.add_parser("explain", help="why each gesture runs at its level, layer by layer (read only)")
    ex.add_argument("gesture", nargs="?", help="one gesture id (brain automation list); default every gesture")
    ex.add_argument("--json", action="store_true", help="the layers read and each gesture's level, source and steps")
