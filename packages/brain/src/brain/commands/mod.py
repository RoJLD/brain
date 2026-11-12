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


def cmd_mod(args, root: Path) -> int:
    sub = args.mod_cmd
    try:
        if sub == "list":
            rows = mod.rows(root)
            if args.json:
                print(json.dumps(rows, ensure_ascii=False, indent=1))
                return 0
            w = max([len(r["id"]) for r in rows] + [6])
            print(f"{'module':<{w}}  {'state':<16}  {'from':<12}  capabilities (fallback)")
            for r in rows:
                fb = f" ({r['fallback']})" if r["fallback"] and r["state"] != "on" else ""
                print(f"{r['id']:<{w}}  {r['state']:<16}  {r['source']:<12}  {', '.join(r['capabilities'])}{fb}")
            return 0
        if sub == "show":
            data = mod.show(root, args.id)
            if args.json:
                print(json.dumps(data, ensure_ascii=False, indent=1))
                return 0
            print(f"{data['id']} ({data['name']}): {data['state']}")
            for c in data["capabilities"]:
                print(f"  {c['id']}: {c['class']}, {c['profile']}, {'on' if c['on'] else 'off'}"
                      + (f", requires {', '.join(c['requires'])}" if c["requires"] else "")
                      + (f", fallback: {c['fallback']}" if c["fallback"] else ""))
            print(f"  depends on: {', '.join(data['depends_on']) or 'nothing'}; "
                  f"uses: {', '.join(data['uses']) or 'nothing'}")
            for r in data["realized_by"]:
                print(f"  realised by {r.get('project')} ({r.get('kind')}, {r.get('state')})")
            return 0
        if sub == "explain":
            print("\n".join(mod.explain(root, args.id)))
            return 0
        new, lines = mod.plan(root, args.id, sub == "enable", getattr(args, "cascade", False))
    except mod.ModError as exc:
        print(f"brain mod {sub}: {exc}", file=sys.stderr)
        return 2
    print("\n".join(lines))
    if not args.apply:
        print("plan only: --apply writes $BRAIN_HOME/profile.json for this machine")
        return 0
    path, written = tiers.write(new)
    print(f"{path}: {'written' if written else 'already so, nothing written'}")
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
