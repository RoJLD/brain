"""``brain mod``: the modules of the registry that list the engine's capabilities, turned on and off for this machine
with a plan, then an apply (brain.mod; wi-brain-mod-command)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .. import mod, tiers

ORDER = 251   # its place in brain --help's list of commands (brain.commands): after profile
USAGE_ORDER = 251   # its usage lines' place in brain --help's epilog, after brain profile's
USAGE = """\
  brain mod list [--json]   the modules of the registry that list capabilities (else each capability): their state
                 (on, off, partly on), where it comes from (preset, config.json, profile.json, pulled) and their
                 fallback
  brain mod show ID [--json]   one module: its capabilities (class, requirements, cost, fallback, state), its hard
                 and soft dependencies, its realisations
  brain mod enable ID [--apply] | disable ID [--cascade] [--apply]   the plan for this machine: the hard dependencies
                 pulled, what turns on and off and its cost; --apply writes $BRAIN_HOME/profile.json (a second apply
                 changes nothing); disable is refused while a module that is on needs it, unless --cascade (which
                 turns it off too). Every machine's default is config.json tier.components, by a PR; both accept module
                 ids, expanded to their capabilities (a capability named directly wins)
  brain mod explain ID   each layer: the engine's preset, config.json, profile.json, the dependencies pulled,
                 the scopes' capabilities
"""


def _list(args, root: Path) -> list[str]:
    rows = mod.rows(root)
    if args.json:
        return [json.dumps(rows, ensure_ascii=False, indent=1)]
    w = max([len(r["id"]) for r in rows] + [6])
    return [f"{'module':<{w}}  {'state':<16}  {'from':<12}  capabilities (fallback)"] + [
        f"{r['id']:<{w}}  {r['state']:<16}  {r['source']:<12}  {', '.join(r['capabilities'])}"
        + (f" ({r['fallback']})" if r["fallback"] and r["state"] != "on" else "") for r in rows]


def _show(args, root: Path) -> list[str]:
    data = mod.show(root, args.id)
    if args.json:
        return [json.dumps(data, ensure_ascii=False, indent=1)]
    return ([f"{data['id']} ({data['name']}): {data['state']}"]
            + [f"  {c['id']}: {c['class']}, {c['profile']}, {'on' if c['on'] else 'off'}"
               + (f", requires {', '.join(c['requires'])}" if c["requires"] else "")
               + (f", fallback: {c['fallback']}" if c["fallback"] else "") for c in data["capabilities"]]
            + [f"  depends on: {', '.join(data['depends_on']) or 'nothing'}; "
               f"uses: {', '.join(data['uses']) or 'nothing'}"]
            + [f"  realised by {r.get('project')} ({r.get('kind')}, {r.get('state')})" for r in data["realized_by"]])


def _change(args, root: Path) -> list[str]:
    new, lines = mod.plan(root, args.id, args.mod_cmd == "enable", getattr(args, "cascade", False))
    if not args.apply:
        return lines + ["plan only: --apply writes $BRAIN_HOME/profile.json for this machine"]
    path, written = tiers.write(new)
    return lines + [f"{path}: {'written' if written else 'already so, nothing written'}"]


def cmd_mod(args, root: Path) -> int:
    act = {"list": _list, "show": _show, "explain": lambda a, r: mod.explain(r, a.id)}.get(args.mod_cmd, _change)
    try:
        print("\n".join(act(args, root)))
    except mod.ModError as exc:
        print(f"brain mod {args.mod_cmd}: {exc}", file=sys.stderr)
        return 2
    return 0


def register(sub, ctx) -> None:
    md = sub.add_parser("mod", help="the modules of the registry that list capabilities: list, show, enable, disable, "
                                    "explain (this machine's profile.json, a plan then --apply)")
    ms = md.add_subparsers(dest="mod_cmd", required=True)
    for name, text in (("list", "each module's state, its source and its fallback"),
                       ("show", "one module's capabilities, dependencies and realisations"),
                       ("enable", "the plan to turn a module on here, its hard dependencies pulled"),
                       ("disable", "the plan to turn a module off here"),
                       ("explain", "each layer that decides a module's state")):
        sp = ms.add_parser(name, help=text)
        if name != "list":
            sp.add_argument("id", help="a module id or name (a capability without a registry)")
        if name in ("list", "show"):
            sp.add_argument("--json", action="store_true")
        if name in ("enable", "disable"):
            sp.add_argument("--apply", action="store_true", help="write $BRAIN_HOME/profile.json")
        if name == "disable":
            sp.add_argument("--cascade", action="store_true", help="turn off what needs it too")


def run(args, root: Path) -> int:
    return cmd_mod(args, root)
