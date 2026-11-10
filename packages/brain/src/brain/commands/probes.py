"""``brain probes``: this machine's dependency probes (brain.depprobes), run now and recorded; --last: their last run;
--list: every declared probe and the machines it runs on; --kinds: the probe kinds and their keys.
"""

from __future__ import annotations

import json

from .. import depprobes

ORDER = 465   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 375   # its usage lines' place in brain --help's epilog
NO_PROJECT = ("probes",)   # machine-wide: no root, no project
USAGE = """\
  brain probes [--last | --list | --kinds] [--json]
                 this machine's dependency probes (config.json probes: a CLI's login, a tool's last output, an
                 index's or a backup's age, a channel's last delivery), at zero token: each one OK, STALE, FAIL or
                 TIMEOUT, run now in its own thread with its own timeout and recorded in $BRAIN_HOME/probes (the
                 alerts pass runs them too and raises probe:<name> for one that is not OK; brain status and the
                 cockpit's health show them); a command's output and a URL are never shown; --last: the last run,
                 nothing run; --list: every declared probe and its machines; --kinds: file-age, json-age, command,
                 http and their keys; exit 1 when one is not OK, 2 for a bad declaration
"""


def register(sub, ctx) -> None:
    sp = sub.add_parser("probes", help="this machine's dependency probes (config.json probes), run now and recorded; "
                                       "exit 1 when one is not OK")
    mode = sp.add_mutually_exclusive_group()
    mode.add_argument("--last", action="store_true", help="the last run's results, nothing run")
    mode.add_argument("--list", action="store_true", help="every declared probe, the machines it runs on and "
                                                          "whether it runs here; nothing run")
    mode.add_argument("--kinds", action="store_true", help="the probe kinds and the keys of each")
    sp.add_argument("--json", action="store_true", help="stable keys")


def _kinds() -> dict:
    return {k: {"what": depprobes.KIND_HELP[k], "required": sorted(need), "optional": sorted(opt | depprobes.COMMON
                                                                                             - {"kind"})}
            for k, (need, opt) in depprobes.KINDS.items()}


def early(args) -> int:
    """Machine-wide: run before any root is resolved (no graph store needed)."""
    if args.kinds:
        data = _kinds()
        if args.json:
            print(json.dumps(data, indent=1, sort_keys=True))
        else:
            for k, v in data.items():
                print(f"{k:<9} {v['what']}\n          needs {', '.join(v['required'])}; may say "
                      f"{', '.join(v['optional'])}")
        return 0
    if args.list:
        data = depprobes.listing()
        if args.json:
            print(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True))
        else:
            print(f"dependency probes declared (this machine: {data['host']})")
            for p in data["probes"]:
                print(f"  {'here' if p['here'] else '    '} {p['name']:<24} {p['kind']:<9} {p['level']:<8} "
                      f"{', '.join(p['machines']) or 'every machine'}" + (f"  ({p['about']})" if p["about"] else ""))
            if not data["probes"]:
                print("  none (config.json probes; brain probes --kinds)")
            for e in data["errors"]:
                print(f"  bad declaration: {e}")
        return 2 if data["errors"] else 0
    data = depprobes.last() if args.last else depprobes.run()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True))
    else:
        print("\n".join(depprobes.render(data)))
    if data.get("errors") and any(not e.startswith("not recorded") for e in data["errors"]):
        return 2
    return 1 if any(r.get("state") != "OK" for r in data.get("probes") or []) else 0
