"""``brain automation``: the automation catalogue (brain.gestures.CATALOGUE, wi-brain-automation-catalogue;
docs/automation.md): ``list`` prints every recurring owner gesture with its level, the level's source, its ceiling,
where it runs, its floor category and its conditions. Read only, zero token, machine-wide: no root."""

from __future__ import annotations

from .. import gestures
from ._common import _print_json

ORDER = 489   # its place in brain --help's list of commands (brain.commands): after floor
PHASE = "early"   # its handlers: early only, before any root is resolved (brain.commands)
NO_PROJECT = {"automation"}   # its parsers that take no --project after them
USAGE_ORDER = 369   # its usage lines' place in brain --help's epilog, after brain floor's
USAGE = """\
  brain automation list [--json]   the automation catalogue (docs/automation.md): every recurring owner gesture, the
                 ones a session runs too, with its id (the key config.json's automation section will use), its level
                 and where that level comes from (the engine's default until that section), its ceiling (manual, ask
                 or auto: the highest level the engine allows), where it runs (a session, the owner's terminal, their
                 elevated terminal, the harness), its floor category (locked at manual: the never-grantable
                 categories, the elevated terminal, the rules' text, raising a level) and its conditions. Read only
"""


def early(args) -> int:
    data = gestures.catalogue()
    if args.json:
        _print_json(data)
        return 0
    print("\n".join(_text(data)))
    return 0


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
