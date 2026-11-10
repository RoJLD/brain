"""``brain features``: the feature matrix: Feature nodes, FEATURES.md and a SQLite index with full-text search
(brain.features).
"""

from __future__ import annotations

import sys
from pathlib import Path

from .. import features, graph, skew
from ._common import _kv, _on_main, _project, _repos, _root_repo, _store, _whole

ORDER = 40   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 30   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain features list [--status S] [--domain D] [--repo R] [--module M] [--value V] [--json]
  brain features search TEXT... [--limit N] [--json] | show ID [--json]   the feature matrix through its SQLite
                 index (full-text search, FTS5), a cache in <BRAIN_HOME>/features rebuilt when the store changes
  brain features add ID --title T --domain D [--status planned] [--value medium] [--repo R] [--module M]
                 [--code PATH[::SYMBOL]]... [--test T]... [--doc D]... [--spec S]... [--adr A]... [--parent F]
                 [--item WI]... [--prop k=v]...   | link ID [the same edges] | set ID key=value...
  brain features render [--write [--force]] [--repo R --out PATH]   FEATURES.md, the matrix by domain (no
                 --write: exit 1 when the file is not the render; another engine than config.json engine.pin writes
                 nothing); sync [--offline]: statuses named by merged PRs
                 ("feat-brain-x: have"), then FEATURES.md
"""


def _features_view(args, root: Path, store: Path, write: bool, repo: str = "", out: str = "") -> int:
    """FEATURES.md of ``repo`` (default: the root's), written to the root (or ``out``) with ``write``, else checked:
    exit 1 when the file is not the render."""
    repo = (repo or _root_repo(args, root)).lower()
    if repo != _root_repo(args, root) and not out:
        print(f"brain: {repo} is not the repo at {root}: give --out <a worktree of {repo}>/{features.VIEW}",
              file=sys.stderr)
        return 1
    target = Path(out).resolve() if out else root / features.VIEW
    label = store.relative_to(root).as_posix() if store.is_relative_to(root) else store.as_posix()
    text = features.render(features.load_store(store, _root_repo(args, root)), repo, label)
    old = target.read_text(encoding="utf-8") if target.is_file() else None
    if not write:
        why = features.check_view(old, text)
        print(f"{features.VIEW} of {repo}: " + (f"{why}: brain features render --write" if why else "up to date"))
        return 1 if why else 0
    if old is not None and old.replace("\r\n", "\n") == text:
        print(f"view: {features.VIEW} unchanged")
        return 0
    if old is not None and features.MARKER not in old:
        print(f"brain: {target} exists and is not generated (no '{features.MARKER}'): not overwritten",
              file=sys.stderr)
        return 1
    target.write_text(text, encoding="utf-8", newline="\n")
    print(f"view: {features.VIEW} written ({repo})")
    return 0


def _features_sync(args, root: Path, store: Path) -> int:
    """brain sync's feature step: the merged PRs' statuses (unless --offline), then FEATURES.md."""
    if not getattr(args, "offline", False):
        features.sync_prs(store, [(c.name, c.path) for c in _repos(args, root) if c.path.is_dir()])
    return _features_view(args, root, store, write=True)


def cmd_features(args, root: Path) -> int:
    store = _store(args, root)
    sub = args.features_cmd
    try:
        if sub in ("list", "search", "show"):
            db = features.open_index(store, _project(args, root).name, _root_repo(args, root))
            try:
                if sub == "list":
                    features.print_list(features.query_list(db, args.status or "", args.domain or "", args.repo or "",
                                                            args.module or "", args.value or ""), args.json)
                elif sub == "search":
                    rows = features.query_search(db, " ".join(args.text), args.limit)
                    features.print_list(rows, args.json) if rows or args.json else print("no feature matches")
                else:
                    f = features.query_show(db, args.id)
                    if f is None:
                        print(f"brain: {args.id}: unknown feature", file=sys.stderr)
                        return 1
                    features.print_show(f, args.json)
            finally:
                db.close()
            return 0
        if sub == "render":
            if args.write and not args.out and _on_main(root):
                raise SystemExit(f"brain: {root} is a main checkout on {_on_main(root)}: render from a worktree")
            if args.write and skew.refuse(root, "features render --write", args.force,
                                          f"the committed {features.VIEW}"):
                return 1
            return _features_view(args, root, store, args.write, args.repo or "", args.out or "")
        if sub == "sync":
            return _features_sync(args, root, store)
        if sub == "set":
            node = features.set_feature(store, args.id, args.assign)
        else:
            links = {"code": args.code or [], "tests": args.test or [], "docs": args.doc or [],
                     "specs": args.spec or [], "adrs": args.adr or [], "parent": args.parent or "",
                     "items": args.item or []}
            if sub == "link":
                new = features.link(store, args.id, **links)
                print(f"link: {args.id}: {len(new)} edge(s) added; then brain sync")
                return 0
            node = features.add(store, args.id, args.title, args.domain, args.repo or _root_repo(args, root),
                                status=args.status, value=args.value, module=args.module or "",
                                props=_kv(args.prop), **links)
    except (features.FeatureError, graph.GraphError, ValueError) as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 1
    print(f"{sub}: {node['id']} [{node['status']}]; then brain sync (FEATURES.md) and brain check")
    return 0


def register(sub, ctx) -> None:
    fe = sub.add_parser("features", help="the feature matrix: Feature nodes, FEATURES.md and a SQLite index with "
                                         "full-text search (brain.features)").add_subparsers(dest="features_cmd",
                                                                                            required=True)
    fl = fe.add_parser("list", help="the features, by domain (filters combine)")
    fl.add_argument("--status", choices=list(features.STATUSES))
    fl.add_argument("--domain")
    fl.add_argument("--repo")
    fl.add_argument("--module", help="a module of the owner's platform (props.module)")
    fl.add_argument("--value", choices=list(features.VALUES))
    fl.add_argument("--json", action="store_true")
    fs = fe.add_parser("search", help="full-text search: every word (a prefix each), best first")
    fs.add_argument("text", nargs="+")
    fs.add_argument("--limit", type=_whole, default=20)
    fs.add_argument("--json", action="store_true")
    fw = fe.add_parser("show", help="one feature: its props and links both ways")
    fw.add_argument("id")
    fw.add_argument("--json", action="store_true")
    fr = fe.add_parser("render", help=f"{features.VIEW}, the matrix by domain: checked, or --write")
    fr.add_argument("--write", action="store_true", help=f"write {features.VIEW} at the root (from a worktree)")
    fr.add_argument("--repo", help="the repo whose features (default: the root's)")
    fr.add_argument("--out", help=f"where to write another repo's {features.VIEW} (its worktree)")
    fr.add_argument("--force", action="store_true", help="--write even when the running engine is not config.json "
                                                         "engine.pin")
    fy = fe.add_parser("sync", help=f"the statuses named by merged PRs (feat-brain-x: have), then {features.VIEW}")
    fy.add_argument("--offline", action="store_true", help="no gh call: only the render")
    for name in ("add", "link"):
        fp = fe.add_parser(name, help="a new feature and its edges" if name == "add" else
                           "append edges to a feature (an existing pair is skipped)")
        fp.add_argument("id", help="feat-<words>, e.g. feat-brain-records" if name == "add" else "the feature")
        if name == "add":
            fp.add_argument("--title", required=True)
            fp.add_argument("--domain", required=True, help=f"its section of {features.VIEW}")
            fp.add_argument("--status", default="planned", choices=list(features.STATUSES))
            fp.add_argument("--value", default="medium", choices=list(features.VALUES), help="strategic value")
            fp.add_argument("--repo", help="the owner repo (default: the root's)")
            fp.add_argument("--module", help="the platform's module, when known")
            fp.add_argument("--prop", action="append", help="key=value prop (repeatable)")
        fp.add_argument("--code", action="append", help="implemented_by: <path>[::<symbol>] in the feature's repo, "
                                                        "or code:<repo>:<path>[::<symbol>] (CodeRef made if missing)")
        fp.add_argument("--test", action="append", help="tested_by: a Test node")
        fp.add_argument("--doc", action="append", help="documented_in: a Doc node")
        fp.add_argument("--spec", action="append", help="specified_by: a Spec node")
        fp.add_argument("--adr", action="append", help="decided_by: an ADR node")
        fp.add_argument("--parent", help="part_of: the parent Feature")
        fp.add_argument("--item", action="append", help="a WorkItem that delivers it")
    fx = fe.add_parser("set", help="key=value, as brain item set (status have|partial|planned|no checked)")
    fx.add_argument("id")
    fx.add_argument("assign", nargs="+")


run = cmd_features
