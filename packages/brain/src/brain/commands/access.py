"""``brain access``: who may do what, where (brain.access, spec-brain-access slice 1): read only, zero token."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .. import access, config, identity, scopes

ORDER = 256   # its place in brain --help's list of commands (brain.commands): after identity
USAGE_ORDER = 296   # its usage lines' place in brain --help's epilog
RUNS_VIA = {   # brain perf --usage: how a subcommand that may never run from the CLI is reached (brain.adoption)
    "access explain": "on demand: a shared brain's owner or a member reads who may do what, where (docs/identity.md)",
}
USAGE = """\
  brain access explain PERSON [--scope REF] [--client C] [--lang fr] [--json]   PERSON's effective right on a node of
                 the scope tree (default: Global and each node a grant of theirs names): the grade, the highest along
                 the node's chain by union of their own grants and their groups', the verbs it gives (read, propose,
                 write, administer; decide from the decider role) with the grant behind each, the capability roles;
                 --client: an agent of that client acting for them (read and propose at most, never administer or
                 decide). members.yaml's groups and grants (docs/identity.md); read only: nothing is refused yet
"""


def _explain(args, root: Path) -> int:
    cfg = config.load(root)
    m = identity.load(root)
    tree = scopes.load(root, cfg)
    owner = config.owner_of()
    if m is None:   # a solo brain: nothing changes
        if args.person != owner:
            print(f"brain: no {identity.FILE}: {args.person!r} is no member (a solo brain: its owner is "
                  f"{owner or 'config.json identity.owner'})", file=sys.stderr)
            return 1
        line = (f"{owner}: no {identity.FILE}, a solo brain: the owner's terminal has every verb on every node; an "
                "agent's session is held by the owner's gestures as before (nothing changes)")
        print(json.dumps({"person": owner, "solo": True}) if args.json else line)
        return 0
    if args.person not in access.people(m.data):
        print(f"brain: {args.person!r} is not in {identity.FILE} people", file=sys.stderr)
        return 1
    try:
        nodes = [scopes.resolve(tree, args.scope)] if args.scope else access.nodes_with_grants(m.data, args.person,
                                                                                                  tree)
    except scopes.ScopeError as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 1
    rows = [access.explain(m.data, args.person, tree, n, args.client or "") for n in nodes]
    if args.json:
        print(json.dumps({"person": args.person, "solo": False, "nodes": rows, "problems": m.errors},
                         ensure_ascii=False, indent=1))
        return 0
    labels = access.labels(cfg.data)
    for r in rows:
        _print(r, tree, labels, args.lang)
    if m.errors:
        print(f"note: {identity.FILE} has {len(m.errors)} problem(s): brain identity check")
    return 0


def _print(r: dict, tree, labels: dict, lang: str) -> None:
    where = tree.path(r["node"]) if r["node"] in tree.nodes else r["node"]
    grade = r["grade"]
    shown = f"{grade} ({labels[grade].get(lang) or labels[grade]['en']})" if grade else "none"
    print(f"{r['person']} on {where}: grade {shown}")
    if r["groups"]:
        print("  groups: " + ", ".join(" -> ".join(p) for p in r["groups"].values()))
    for verb in access.VERBS:
        if verb in r["verbs"]:
            print(f"  {verb:<10} " + "; ".join(r["verbs"][verb]))
    for role, src in r["roles"].items():
        print(f"  role {role}: " + "; ".join(src) + ("" if role in access.ROLES else " (a role this engine does not "
                                                     "know: kept, gives nothing)"))
    for u in r["unknown_grades"]:
        print(f"  unknown grade {u}: read as none, never above")
    for n in r["not_counted"]:
        print(f"  not counted today: {n}")
    if "client" in r:
        c = r["client"]
        print(f"  an agent of {c['name']} for them: {', '.join(c['verbs']) or 'nothing'} (ceiling "
              f"{', '.join(c['ceiling'])}; never {', '.join(c['never'])})")
    if not r["verbs"] and not r["roles"]:
        print("  no verb here")


def cmd_access(args, root: Path) -> int:
    return {"explain": _explain}[args.access_cmd](args, root)


def register(sub, ctx) -> None:
    ac = sub.add_parser("access", help="who may do what, where: members.yaml's grades and roles on the scope tree, "
                                       "read only (brain.access)")
    asub = ac.add_subparsers(dest="access_cmd", required=True)
    ex = asub.add_parser("explain", help="a person's effective right on a node, with the grant behind each verb")
    ex.add_argument("person", help="a person_id of members.yaml")
    ex.add_argument("--scope", help="a node of the scope tree: an id, an alias, a path of ids, global (default: Global "
                                    "and each node a grant of theirs names)")
    ex.add_argument("--client", help="an agent's client acting for them (claude, cursor...): its reach")
    ex.add_argument("--lang", default="en", choices=("en", "fr"), help="the grades' labels (config.json grades)")
    ex.add_argument("--json", action="store_true", help="stable keys: person, solo, nodes, problems")


run = cmd_access
