"""``brain spool``: the sealed local spool of the stores that leave the machine (brain.spool)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .. import config, spool

ORDER = 252   # its place in brain --help's list of commands (brain.commands): after vault
USAGE_ORDER = 292   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain spool push [STORE...] [--dry-run] [--json]   by hand: seal each store of the spool's set (config.json
                 spool.stores, else ledger, usage and sessions) whose content changed since its last push into
                 $BRAIN_HOME/spool, after a secret scan, through brain vault (refuses a store whose class never leaves
                 the machine); send what waits to spool.remote when one is set, each copy checked by sha256; keep the
                 last 3 snapshots per store (spool.keep); exit 1 when a store or a copy failed, 2 when the index
                 cannot be written (a newer brain's)
  brain spool status [--json]   the spool's folder, remote, set, last push, and each file waiting or sent
  brain spool verify   each file of the spool against its sha256 in the index; exit 1 on a missing or changed one
"""


def push_lines(res: dict) -> list[str]:
    """What ``brain spool push`` prints of its result."""
    lines = [f"to put: {p['store']}" if p.get("plan") else
             f"put: {p['file']} ({p['files']} file(s), {p['bytes']} bytes sealed)" for p in res["put"]]
    lines += [f"unchanged since its last push: {name}" for name in res["unchanged"]]
    lines += [f"nothing to put: {name}" for name in res["empty"]]
    lines += [f"sent: {r['file']}" if r.get("sent") else f"waits: {r['file']}: {r['error']}" for r in res["sent"]]
    lines += [("to prune: " if res["dry_run"] else "pruned: ") + rel for rel in res["pruned"]]
    lines += [f"error: {e}" for e in res["errors"]]
    lines += [] if res["remote"] else ["no spool.remote: the sealed files wait in the spool"]
    return lines + (["plan only: run again without --dry-run"] if res["dry_run"] else [])


def _verify() -> int:
    bad = spool.verify()
    for rel, why in bad:
        print(f"{rel}: {why}")
    print(f"spool: {len(bad)} problem(s)" if bad else "spool: every file matches its sha256")
    return 1 if bad else 0


def cmd_spool(args, root: Path) -> int:
    """``brain spool``: push, status, verify (brain.spool). Exit 2 on a refusal (the index written by a newer
    brain)."""
    cfg = config.load(root)
    try:
        if args.spool_cmd == "status":
            s = spool.status(cfg)
            print(json.dumps(s, indent=1, sort_keys=True) if args.json else "\n".join(spool.render_status(s)))
            return 0
        if args.spool_cmd == "verify":
            return _verify()
        res = spool.push(cfg, args.stores or None, dry_run=args.dry_run)
    except spool.SpoolError as exc:
        print(f"brain spool {args.spool_cmd}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(res, indent=1, sort_keys=True) if args.json else "\n".join(push_lines(res)))
    return 1 if res["errors"] or any(r.get("error") for r in res["sent"]) else 0


def register(sub, ctx) -> None:
    sp = sub.add_parser("spool", help="the sealed local spool of the stores that leave the machine, pushed by hand "
                                      "(brain.spool)").add_subparsers(dest="spool_cmd", required=True)
    pp = sp.add_parser("push", help="seal the changed stores into the spool, send what waits to spool.remote, prune")
    pp.add_argument("stores", nargs="*", metavar="STORE", help="only these stores (default: spool.stores, else "
                                                               "ledger, usage and sessions)")
    pp.add_argument("--dry-run", action="store_true", help="the plan: nothing sealed, sent or pruned")
    pp.add_argument("--json", action="store_true", help="stable keys")
    ps = sp.add_parser("status", help="the spool's folder, remote, set, last push, files waiting and sent")
    ps.add_argument("--json", action="store_true", help="stable keys")
    sp.add_parser("verify", help="each file of the spool against its sha256 in the index")


run = cmd_spool
