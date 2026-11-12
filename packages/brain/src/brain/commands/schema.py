"""``brain schema diff``: what a change of the formats' schemas narrows since a tag (brain.schemadiff,
wi-brain-schema-diff): a removed property, a new required field, a narrowed enum or type, and how the PR's Compat:
line resolves it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .. import schemadiff, scout, structure
from ..inventory import AuditError, git, git_tree, work_tree
from ._common import root_of

ORDER = 535   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 535   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain schema diff --against TAG [--repo-dir D] [--pr-body FILE|-] [--strict] [--json]   what the schemas a
                 change touches since TAG narrow (the JSON Schemas *.schema.json and the graph stores' and templates'
                 schema.yaml): a property removed, a field newly required, an enum or a type narrowed, a const, a
                 bound, a pattern, additionalProperties closed; a node type, an edge type or a status removed. A
                 narrowing is resolved by the PR's Compat: line (in --pr-body or a commit message since TAG):
                 'Compat: migration <id>' with the format's v bumped and its fixtures/formats/<format>/v<N>/, or
                 'Compat: breaking <adr-id>'. Exit 1 on an unresolved narrowing under --strict or config.json
                 audit.schema_diff_strict (the scout's schema.narrowed lines are NEW then, info otherwise), 2 when
                 TAG or the repo cannot be read (docs/formats.md, « The schema diff »)
"""


def _top(args) -> Path:
    d = Path(args.repo_dir).resolve() if args.repo_dir else Path.cwd()
    return Path(git(d, "rev-parse", "--show-toplevel").strip()).resolve()


def _text(args, found: list, body: str, tree, strict: bool) -> None:
    lines = schemadiff.compat(body)
    for d in found:
        bump = f"  (v{d.v[0]} -> v{d.v[1]})" if d.v[0] != d.v[1] else ""
        print(f"{'resolved' if d.resolved else 'narrows':<9}{d.path}{bump}")
        for line in d.narrowed:
            print(f"           {line}")
        print(f"           -> {d.resolved or schemadiff.why_not(d, lines, tree)}")
    unresolved = sum(1 for d in found if not d.resolved)
    verdict = (f"{unresolved} unresolved" if unresolved else "none unresolved") + (", strict" if strict else "")
    print(f"schema diff {args.against}..worktree: {len(found)} schema(s) narrowed, {verdict}")


def cmd_schema(args, root: Path | None) -> int:
    try:
        top = _top(args)
        base_rev = git(top, "rev-parse", "--verify", f"{args.against}^{{commit}}").strip()
        body = structure.body_of(top, base_rev, "", scout._pr_body(args.pr_body or ""))
        tree = work_tree(top)
        found = schemadiff.diffs(scout.changed(top, base_rev), git_tree(top, base_rev), tree, body)
    except AuditError as exc:
        print(f"brain schema diff: {exc}", file=sys.stderr)
        return 2
    strict = args.strict or schemadiff.strict(root)
    if args.json:
        print(json.dumps({"against": args.against, "base": base_rev, "strict": strict,
                          "compat": [f"{k} {i}".strip() for k, i in schemadiff.compat(body)],
                          "schemas": [{"path": d.path, "narrowed": d.narrowed, "v": list(d.v), "resolved": d.resolved}
                                      for d in found]}, ensure_ascii=False, indent=1, sort_keys=True))
    else:
        _text(args, found, body, tree, strict)
    return 1 if strict and any(not d.resolved for d in found) else 0


def early(args) -> int:
    """Any repo, a brain or not (CI's checkout of the engine holds no graph store): before find_root, the owner's
    opt-in read from --root when given, else from the config discovery (brain.config)."""
    return cmd_schema(args, root_of(args))


def register(sub, ctx) -> None:
    sc = sub.add_parser("schema", help="the formats' schemas: diff, what a change narrows since a tag "
                                       "(brain.schemadiff)")
    ss = sc.add_subparsers(dest="schema_cmd", required=True)
    di = ss.add_parser("diff", help="what the schemas a change touches since --against narrow, and how its Compat: "
                                    "line resolves it")
    di.add_argument("--against", required=True, metavar="TAG", help="the tag (or any commit) compared with")
    di.add_argument("--repo-dir", help="the repo (default: the current folder's)")
    di.add_argument("--pr-body", metavar="FILE", help="the PR body ('-' for stdin), where the Compat: line is read "
                                                      "(the commit messages since TAG are read too)")
    di.add_argument("--strict", action="store_true", help="exit 1 on an unresolved narrowing (default: the "
                                                          "owner's config.json audit.schema_diff_strict)")
    di.add_argument("--json", action="store_true", help="stable keys")
