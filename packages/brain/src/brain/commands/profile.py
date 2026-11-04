"""``brain profile`` (alias: brain doctor): this machine's facts, its profile (Lite, Défaut, Recommandé,
Personnalisable), each capability's and stack's state, and the Recommended profile, at zero token.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import probe, tiers

ORDER = 270   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 250   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain profile [--json] [--quick]   (alias brain doctor) this machine's facts at zero token, each probe with its
                 own timeout (CPU, memory, GPUs and their VRAM, the inference backend, disks and BRAIN_HOME's size,
                 tools, container runtime, Kubernetes context, disk encryption), the active profile and its overrides,
                 each capability's and stack's state (on, to install, fallback, missing, off, unavailable, planned),
                 the Recommended profile computed for this machine and what it would add; --json: the machines
                 brick's inventory fields and a brain block, for the cockpit; --quick: no probe that starts a program
  brain profile list | show lite|default|recommended|custom [--json]   each profile's entries (Lite, Défaut,
                 Recommandé computed for this machine, Personnalisable: this machine's overrides); show: one profile's
                 entries with their class, requirements, cost, fallback and state (brain.tiers, tiers.yaml)
  brain profile set [lite|default|recommended] [--with ID]... [--without ID]... [--apply]   the plan of this
                 machine's profile (recommended: the set this machine allows, frozen into the overrides); --apply
                 writes it to $BRAIN_HOME/profile.json, and a second apply changes nothing; no base: the current one
                 with these overrides; --with all: every built entry; install.ps1 -Tier / -With / -Without runs it
  brain profile render [the same]   what install.ps1 reads, as JSON: the pip extras the profile wants, those
                 installed outside it, the stacks on and off
"""


def cmd_profile(args, root: Path) -> int:
    """``brain profile`` (alias ``brain doctor``): this machine's facts, profile, each entry's state and Recommended;
    ``list``, ``show``, ``set`` (the plan; --apply writes $BRAIN_HOME/profile.json) and ``render`` (what install.ps1
    reads) (brain.tiers, brain.probe)."""
    sub = getattr(args, "profile_cmd", None)
    as_json = getattr(args, "json", False)
    if not sub:
        doc = tiers.doctor(root, quick=args.quick)
        print(json.dumps(doc, ensure_ascii=False, indent=1) if as_json else "\n".join(tiers.render_doctor(doc)))
        return 1 if doc["brain"]["profile"]["errors"] else 0
    reg, errors = tiers.registry(root)
    for e in errors:
        print(f"brain profile: {e}", file=sys.stderr)
    ch = tiers.choice(root)
    base = getattr(args, "base", None)
    facts = (probe.facts(probe.collect(quick=True, roots=[root]))
             if sub in ("list", "show") or base == "recommended" else None)
    if sub == "list":
        data = tiers.profiles(reg, ch, facts)
        print(json.dumps(data, ensure_ascii=False, indent=1) if as_json else "\n".join(tiers.render_list(data)))
        return 0
    if sub == "show":
        rows = tiers.show(reg, args.name, ch, facts)
        print(json.dumps(rows, ensure_ascii=False, indent=1) if as_json else
              "\n".join(tiers.render_show(args.name, rows)))
        return 0
    try:
        new = (tiers.plan(reg, ch, base, args.with_ or [], args.without or [], facts)
               if base or args.with_ or args.without else ch)
    except tiers.TierError as exc:
        print(f"brain profile {sub}: {exc}", file=sys.stderr)
        return 2
    if sub == "render":
        print(json.dumps(tiers.render(reg, new), ensure_ascii=False, indent=1))
        return 0
    path, written = (tiers.write(new) if args.apply else (tiers.machine_file(), False))
    print("\n".join(tiers.render_plan(reg, ch, new, args.apply, written, path)))
    return 0


def register(sub, ctx) -> None:
    pf = sub.add_parser("profile", aliases=["doctor"],
                        help="this machine's facts, its profile (Lite, Défaut, Recommandé, Personnalisable), each "
                             "capability's and stack's state, and the Recommended profile, at zero token")
    pf.add_argument("--json", action="store_true", help="the report as JSON: the machines brick's inventory fields, "
                                                        "then a brain block")
    pf.add_argument("--quick", action="store_true", help=f"no probe that starts a program ({', '.join(probe.SLOW)})")
    pfs = pf.add_subparsers(dest="profile_cmd")
    pfl = pfs.add_parser("list", help="each profile's entries, Recommandé computed for this machine")
    pfw = pfs.add_parser("show", help="one profile's entries: class, requirements, cost, fallback and state")
    pfw.add_argument("name", choices=tiers.PROFILES)
    for sp in (pfl, pfw):
        sp.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    for name, text in (("set", "the plan of this machine's profile; --apply writes $BRAIN_HOME/profile.json"),
                       ("render", "what install.ps1 reads, as JSON: the pip extras and the stacks on and off")):
        sp = pfs.add_parser(name, help=text)
        sp.add_argument("base", nargs="?", choices=tiers.BASES,
                        help="the base (recommended: the set this machine allows, frozen into the overrides); none: "
                             "the current one")
        sp.add_argument("--with", dest="with_", action="append", metavar="ID",
                        help="turn a capability or stack on (repeatable; all: every built entry)")
        sp.add_argument("--without", action="append", metavar="ID", help="turn a capability or stack off (repeatable)")
        if name == "set":
            sp.add_argument("--apply", action="store_true", help="write the choice (a second apply changes nothing)")


def run(args, root: Path) -> int:
    args.cmd = "profile"   # brain doctor is its alias
    return cmd_profile(args, root)
