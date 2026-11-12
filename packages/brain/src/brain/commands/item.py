"""``brain item``: show, add, set or close a backlog node."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from .. import crossstore, graph, milestones, reads
from ._common import _kv, _print_json, _read_stores, _store

ORDER = 20   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 20   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain item show ID [--history] [--json]   one node and all that bears on it, instead of reading the store's YAML:
                 its props in full, its edges both ways, the ids its props name, its blockers, the ADRs that decide it
                 (direct and inherited) and its specs, the DDRs that name it; --history: its changes from git (a
                 replay of the store's history: a minute on a store of thousands of nodes and commits)
  brain item add ID --title T [--priority P1 [--reason R]] [--size S|M|L|XL --size-reason R] [--spec S]
                 [--after ID]... [--milestone M] [--adr A] [--prop k=v]...   without --milestone, prints the
                 milestone the signals suggest; a WorkItem is stamped props.created (today) and should carry a size,
                 the writing session's judgement (S under ~0.3 h of active time, M ~0.8 h, L ~2 h, XL beyond: to
                 split); brain check warns on an open item written without one (brain.sizing)
  brain item set ID key=value...   size=S|M|L|XL size_reason=... sizes an item (any case)
  brain item close ID --pr "repo #N" [--outcome TEXT]
  brain item link FROM TYPE TO [--prop k=v]...   an edge (with props: enforced_by's scope); one end may be another
                 store's id (a store of the registry: research_graph shows it with its store's label)
  brain item unlink FROM TO   remove the curated edge between two nodes (re-typing one: unlink, then link)
"""


def cmd_item(args, root: Path) -> int:
    store = _store(args, root)
    try:
        if args.item_cmd == "add":
            props = {k: v for k, v in {"priority": args.priority, "priority_reason": args.reason, "theme": args.theme,
                                       "idea": args.idea}.items() if v}
            if args.size_reason and not args.size:
                raise graph.GraphError("--size-reason without --size")
            if args.size:
                if not args.size_reason:
                    raise graph.GraphError("--size needs its --size-reason (one line: why this size)")
                props.update(size=args.size.upper(), size_reason=args.size_reason)
            if args.type == "WorkItem":
                props["created"] = date.today().isoformat()   # since the size rule (brain.sizing)
            props.update(_kv(args.prop))
            node = graph.add_item(store, args.id, args.title, node_type=args.type, status=args.status, props=props,
                                  spec=args.spec, after=args.after, milestone=args.milestone, adr=args.adr,
                                  anchor=args.anchor, file=args.file, edges_file=args.edges_file,
                                  foreign=_foreign(root, store, [args.spec, *(args.after or []), args.milestone,
                                                                 args.adr]))
        elif args.item_cmd == "set":
            node = graph.set_item(store, args.id, args.assign)
        elif args.item_cmd == "unlink":
            edge, f = graph.unlink(store, args.id, args.to)
            print(f"unlink: {edge['from']} -{edge['type']}-> {edge['to']} removed from {f.name}; then brain sync and "
                  "brain check")
            return 0
        elif args.item_cmd == "link":
            edge = graph.link(store, args.id, args.type, args.to, args.edges_file, props=_kv(args.prop),
                              foreign=_foreign(root, store, [args.id, args.to]))
            print(f"link: {edge['from']} -{edge['type']}-> {edge['to']}; then brain sync and brain check")
            return 0
        else:
            node = graph.close_item(store, args.id, args.pr, args.outcome or "", status=args.status)
    except graph.GraphError as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 1
    print(f"{args.item_cmd}: {node['id']} [{node['status']}]; then brain sync and brain check")
    if args.item_cmd == "add" and args.type == "WorkItem" and not (node.get("props") or {}).get("size"):
        print(f"size: none; give one (brain item set {node['id']} size=S|M|L|XL size_reason=...): S under ~0.3 h of "
              "active time, M ~0.8 h, L ~2 h, XL beyond (to split)")
    if args.item_cmd == "add" and args.type == "WorkItem" and not args.milestone \
            and milestones.PROPOSED not in (node.get("props") or {}):
        _print_suggestion(store, node["id"])
    return 0


def cmd_show(args, root: Path) -> int:
    """``brain item show``: research_graph's item, its decisions and DDRs, its history (brain.reads)."""
    try:
        detail, events = reads.item(root, _read_stores(args, root), args.id, git=args.history)
    except reads.ReadError as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 1
    if args.json:
        _print_json({**detail, "history": None if events is None else [e.to_json() for e in events]})
    else:
        print("\n".join(reads.render_item(detail, events)))
    return 0


def _foreign(root: Path, store: Path, ends: list) -> dict[str, str]:
    """{id: its store's label} of the ends the store does not hold that another store of the registry does
    (brain.crossstore); the registry is read only when an end is not the store's."""
    index = graph.node_index(store)
    if all(not e or e in index for e in ends):
        return {}
    return crossstore.registry_ids(root, store)


def _print_suggestion(store: Path, nid: str) -> None:
    """The milestone the signals suggest for a new item (ADR 2026-11-01: proposed, never attached alone)."""
    ix = milestones.index(store)
    if not ix.milestones:
        return
    s = ix.suggest(nid)
    if s:
        print(f"milestone: none; suggested {s.milestone}? ({s.reason}); keep it as a proposal: brain milestone "
              f"suggest --write --only {nid}")
    else:
        print("milestone: none, and no signal suggests one; brain milestone add when no milestone fits")


def register(sub, ctx) -> None:
    it = sub.add_parser("item", help="show, add, set or close a backlog node").add_subparsers(dest="item_cmd",
                                                                                            required=True)
    sh = it.add_parser("show", help="one node and all that bears on it: props in full, edges both ways, the ADRs and "
                                    "specs behind it, the DDRs that name it (--history: its changes from git)")
    sh.add_argument("id")
    sh.add_argument("--history", action="store_true", help="its changes from git, replayed from the store's history "
                                                           "(slow on a large store)")
    sh.add_argument("--json", action="store_true", help="research_graph's item with decisions, ddrs and history")
    add = it.add_parser("add")
    add.add_argument("id")
    add.add_argument("--title", required=True)
    add.add_argument("--type", default="WorkItem")
    add.add_argument("--status", default="todo")
    add.add_argument("--priority")
    add.add_argument("--reason", help="props.priority_reason: why this priority")
    add.add_argument("--size", type=str.upper, choices=graph.SIZES,
                     help="props.size, the writing session's judgement: S under ~0.3 h of active time, M ~0.8 h, "
                          "L ~2 h, XL beyond (to split)")
    add.add_argument("--size-reason", help="props.size_reason: one line, why this size (required with --size)")
    add.add_argument("--theme")
    add.add_argument("--idea")
    add.add_argument("--spec", help="specified_by edge")
    add.add_argument("--after", action="append", help="depends_on edge (repeatable)")
    add.add_argument("--milestone", help="part_of edge")
    add.add_argument("--adr", help="decided_by edge")
    add.add_argument("--prop", action="append", help="key=value prop (repeatable)")
    add.add_argument("--anchor", default="", help="file#fragment the node points to")
    add.add_argument("--file", default="nodes/work.yaml")
    add.add_argument("--edges-file", default="edges/work.yaml")
    st = it.add_parser("set")
    st.add_argument("id")
    st.add_argument("assign", nargs="+", help="status=doing, title=..., props.<k>=... or <k>=... (empty removes)")
    ln = it.add_parser("link", help="append an edge: brain item link FROM TYPE TO")
    ln.add_argument("id", metavar="from")
    ln.add_argument("type", help="edge type: depends_on, part_of, specified_by, decided_by, delivers...")
    ln.add_argument("to")
    ln.add_argument("--edges-file", default="edges/work.yaml")
    ln.add_argument("--prop", action="append", help="key=value edge prop, e.g. scope=... on enforced_by (repeatable)")
    un = it.add_parser("unlink", help="remove the curated edge between two nodes: brain item unlink FROM TO")
    un.add_argument("id", metavar="from")
    un.add_argument("to")
    cl = it.add_parser("close")
    cl.add_argument("id")
    cl.add_argument("--pr", required=True, help='e.g. "brain #13"')
    cl.add_argument("--outcome", help="one line: what was done and checked")
    cl.add_argument("--status", default="done", choices=["done", "dropped"])


def run(args, root: Path) -> int:
    return (cmd_show if args.item_cmd == "show" else cmd_item)(args, root)
