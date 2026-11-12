"""``brain scopes``: the scope tree (brain.scopes, wi-brain-scope-tree): Global at the root, the containers of
scopes.yaml and the projects placed by their parent: key, with the projects under each node."""

from __future__ import annotations

import json
from pathlib import Path

from .. import config, projects, scopes, status

ORDER = 191   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 221   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain scopes [--scope REF] [--depth N] [--archived] [--lang en|fr] [--types] [--deny] [--json]   the scope
                 tree: Global, the containers of scopes.yaml (beside config.json; $BRAIN_SCOPES) and the projects
                 placed by their parent: in projects.yaml, each node's type label (config.json scope_types renames
                 them) and the projects under it; --scope: one node's subtree (an id, a path pro/acme, global, . or ..); --types:
                 the type catalogue; --deny: the terms public.deny_from_tree adds to public.deny.repos (the projects
                 under a class floor of private or stricter, and their repos). Without scopes.yaml or parent:, every
                 project sits under Global
"""


def here(root: Path | None) -> str:
    """The registered project of the folder acted on ('' when none): what ``.`` names."""
    found = projects.at_root(root) if root is not None else []
    return found[0].name if found else ""


def cmd_scopes(args, root: Path) -> int:
    cfg = config.load(root)
    tree = scopes.load(root, cfg)
    if args.deny:   # what public.deny_from_tree adds to public.deny.repos (brain.scopes.private_terms)
        terms = scopes.private_terms(cfg)
        on = "on" if config.deny_from_tree(cfg) else "off (config.json public.deny_from_tree)"
        if args.json:
            print(json.dumps({"deny_from_tree": config.deny_from_tree(cfg), "repos": terms}, ensure_ascii=False,
                             indent=1, sort_keys=True))
        else:
            print(f"deny from the tree: {on}; {len(terms)} term(s) for public.deny.repos"
                  + (": " + ", ".join(terms) if terms else ""))
        return 0
    if args.types:
        if args.json:
            print(json.dumps({"types": scopes.describe(tree, args.lang)["types"]}, ensure_ascii=False, indent=1,
                             sort_keys=True))
            return 0
        for tid, spec in tree.types.items():
            kids = spec.get("children")
            text = f"{spec.get('en', '')} / {spec.get('fr', '')}" + (f"; children: {', '.join(kids)}"
                                                                    if isinstance(kids, list) else "")
            print("\n".join(status._row(tid, text)))
        return 0
    try:
        nid = scopes.resolve(tree, args.scope, here(root)) if args.scope else scopes.GLOBAL
    except scopes.ScopeError as exc:
        raise SystemExit(f"brain: {exc}") from None
    if args.json:
        data = scopes.describe(tree, args.lang, args.archived, top=nid)
        data["scope"] = nid
        print(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True))
        return 0
    print("\n".join(scopes.render(tree, args.lang, args.archived, args.depth, top=nid)))
    return 0


def _depth(text: str) -> int:
    from ._common import _whole
    return _whole(text)


def register(sub, ctx) -> None:
    sc = sub.add_parser("scopes", help="the scope tree: Global, the containers of scopes.yaml and the projects "
                                       "placed by their parent: (brain.scopes)")
    sc.add_argument("--scope", help="one node's subtree: an id, a path of ids (pro/acme), global, . (the project "
                                    "here) or .. (its parent)")
    sc.add_argument("--depth", type=_depth, help="the levels shown under the node (default: all)")
    sc.add_argument("--archived", action="store_true", help="the archived nodes too")
    sc.add_argument("--lang", choices=scopes.LANGS, default="en", help="the type labels' language (default en)")
    sc.add_argument("--types", action="store_true", help="the type catalogue: ids, labels, the children a type "
                                                         "accepts")
    sc.add_argument("--deny", action="store_true", help="the terms config.json public.deny_from_tree adds to "
                                                        "public.deny.repos: the private projects and their repos")
    sc.add_argument("--json", action="store_true", help="stable keys")


run = cmd_scopes
