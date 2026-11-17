"""``brain projects``: the project registry resolved (every project, or --project's)."""

from __future__ import annotations

import json
from pathlib import Path

from .. import projects, status

ORDER = 190   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 220   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain projects [--keys] [--json]   the registry resolved: each project's stores, journals, decision logs, ledgers,
                 repos, stacks, code index and plugin, the project whose root it shares, then the projects the brain
                 reads and never writes (access: read), then the tombstones (a project that ended: status merged,
                 split, became-process or archived); each one's aliases and label; --keys: every key an entry may
                 hold
"""


def cmd_projects(args, root: Path) -> int:
    """The registry resolved: every project, or --project's; --keys: what an entry may hold."""
    if args.keys:
        for k, text in projects.KEYS.items():
            print("\n".join(status._row(k, text)))
        return 0
    one = getattr(args, "project_obj", None)
    projs = [one] if one else list(projects.load(root).values())
    read_only = [] if one else list(projects.readonly(root).values())
    ended = [] if one else projects.describe_tombstones(root)
    if not projs and not read_only and not ended:
        raise SystemExit(f"brain: no project registry ({projects.REGISTRY}; $BRAIN_PROJECTS or $CLAUDE_BRAIN_DIR)")
    data = [projects.describe(p) for p in projs] + [projects.describe_read_only(r, root) for r in read_only] + ended
    if args.json:
        print(json.dumps({"projects": data}, ensure_ascii=False, indent=1, sort_keys=True))
        return 0
    for d in data:
        if d["access"] in ("read", "none"):
            what = ("read only: the brain reads it and never writes it" if d["access"] == "read"
                    else f"tombstone, {d['status']}: the project ended, no command loads it")
            print(f"{d['name']} ({what})" + (f": {d['title']}" if d["title"] else ""))
            _names(d)
            continue
        print(f"{d['name']} ({d['root']}" + ("" if d["found"] else ", not found on this machine") + ")"
              + (f": {d['title']}" if d["title"] else ""))
        rows = [("shares_root_with", "shares root")] if d["shares_root_with"] else []
        for key, label in rows + [("stores", "stores"), ("overlays", "overlays"), ("journals", "journals"), ("decisions", "decisions"),
                                  ("ledgers", "ledgers"), ("repos", "repos"), ("production", "production"),
                                  ("code_index", "code index"), ("stacks", "stacks"), ("shared_ids", "shared ids"),
                                  ("plugin", "plugin")]:
            value = d[key]
            text = (", ".join(f"{k}: {v}" for k, v in value.items()) if isinstance(value, dict)
                    else ", ".join(map(str, value)) if isinstance(value, list) else str(value or ""))
            print("\n".join(status._row(label, text or "-")))
        _names(d)
    return 0


def _names(d: dict) -> None:
    """Its label and aliases, when it declares any (brain.projectids)."""
    for key in ("label", "aliases"):
        value = ", ".join(d[key]) if isinstance(d[key], list) else d[key]
        if value:
            print("\n".join(status._row(key, value)))


def register(sub, ctx) -> None:
    pj = sub.add_parser("projects", help="the project registry resolved (every project, or --project's)")
    pj.add_argument("--keys", action="store_true", help="every key a project's entry may hold, and what it holds")
    pj.add_argument("--json", action="store_true", help="stable keys")


run = cmd_projects
