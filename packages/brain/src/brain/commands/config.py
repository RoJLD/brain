"""``brain config``: the personal brain's config.json resolved: owner, registry, rules, memory, records, engine pin,
public repos, denied terms, secrets by name.
"""

from __future__ import annotations

import json
from pathlib import Path

from .. import config, status

ORDER = 210   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 240   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain config [--json] [--keys] [--check]   the personal brain's config.json resolved (owner, registry, rules,
                 memory, records, engine pin, public repos and how many denied terms, secrets by name, the machine's
                 pointer); --keys: every key it may hold (from schemas/config.schema.json); --check: exit 1 when it
                 breaks the contract
"""


def cmd_config(args, root: Path) -> int:
    """The personal brain's config.json resolved; --keys: what it may hold; --check: exit 1 when it breaks the
    contract (brain.config)."""
    if args.keys:
        for k, text in config.keys():
            print("\n".join(status._row(k, text)))
        return 0
    errors = config.check(root)
    data = config.describe(config.load(root))
    if args.json:
        print(json.dumps({"config": data, "errors": errors}, ensure_ascii=False, indent=1, sort_keys=True))
    else:
        print(f"{data['file'] or 'no ' + config.FILE + ' (the defaults)'}: owner {data['owner']} ({data['kind']}"
              + (f", tenant {data['tenant']}" if data["tenant"] else "") + ")")
        engine = data["engine"]
        deny = ", ".join(f"{k} {n}" for k, n in data["deny"].items() if n)
        for label, text in (("registry", data["registry"]), ("rules", ", ".join(data["rules"])),
                            ("memory", data["memory"]), ("records", data["records"]), ("source", data["source"]),
                            ("claude", "{plugin}@{marketplace}".format(**data["claude"])
                             + (f" from {data['claude']['source']}" if data["claude"]["source"] else "")),
                            ("engine", f"{engine['repo']}@{engine['pin']}" if engine else
                             "not pinned (config.json engine: {repo, pin}, the tag the installer installs)"),
                            ("personal", data["personal"] or "no pointer ($BRAIN_PERSONAL, <BRAIN_HOME>/personal.json)"),
                            ("public", ", ".join(data["public_repos"])), ("denied", deny),
                            ("allowed", ", ".join(data["allow"])), ("secrets", ", ".join(data["secrets"]))):
            print("\n".join(status._row(label, text or "-")))
        for e in errors:
            print(f"error: {e}")
    return 1 if args.check and errors else 0


def register(sub, ctx) -> None:
    cf = sub.add_parser("config", help="the personal brain's config.json resolved: owner, registry, rules, memory, "
                                       "records, engine pin, public repos, denied terms, secrets by name")
    cf.add_argument("--keys", action="store_true", help="every key config.json may hold, and what it holds")
    cf.add_argument("--check", action="store_true", help="exit 1 when config.json breaks the contract")
    cf.add_argument("--json", action="store_true", help="stable keys")


run = cmd_config
