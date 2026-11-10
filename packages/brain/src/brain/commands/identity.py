"""``brain identity``: members.yaml and the owner's signed answers (brain.identity, docs/identity.md)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .. import identity, records, sshsig
from ._common import _project

ORDER = 255   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 295   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain identity check   members.yaml (people, public keys, accounts, organizations, memberships: its schema and
                 references) and the owner-decides answers (money, keys, accounts, visibility, heirs, scheduled
                 tasks) unsigned or whose signature (records/ddr/<id>.sig) does not verify; warnings, errors under
                 config.json identity.require_signed (brain check runs it too); nothing without members.yaml
  brain identity unsigned [--write DIR] [--json]   the owner-decides answers without a signature; --write: each
                 one's payload as DIR/<id>.txt and the one command that signs them all in the owner's terminal
  brain identity payload ID   what a signature covers: the question and the answer as recorded (stdout)
  brain identity attach SIG|DIR...   the owner's signatures (DIR/<id>.txt.sig), verified with the deciders' public keys,
                 then kept beside their records (records/ddr/<id>.sig); nothing kept when one fails. The engine never
                 signs and never reads a private key (docs/identity.md)
"""


def _check(args, root: Path) -> int:
    errors, warnings = identity.check(root, _project(args, root).name)
    for line in errors:
        print(f"error: {line}")
    for line in warnings:
        print(f"warning: {line}")
    if identity.load(root) is None:
        print(f"identity: no {identity.FILE}: nothing checked")
    elif not errors and not warnings:
        print("identity: members.yaml valid, every owner-decides answer signed")
    return 1 if errors else 0


def _unsigned(args, root: Path) -> int:
    entries = identity.unsigned(root, _project(args, root).name)
    if args.json:
        print(json.dumps([{"id": d["id"], "title": d.get("title"), "topics": t, "how": identity.relayed(d)}
                          for _, d, t in entries], indent=1, ensure_ascii=False))
        return 0
    for _, d, t in entries:
        print(f"{d['id']}  {d.get('title')}  [{', '.join(t)}]  {identity.relayed(d)}")
    if not entries:
        print("no owner-decides answer waits on a signature")
        return 0
    if args.write:
        out = Path(args.write).resolve()
        identity.write_payloads(entries, out)
        print(f"\n{len(entries)} payload(s) in {out}: read them, then sign them all at once in your own terminal "
              f"(your passphrase, asked once):\n"
              f"  ssh-keygen -Y sign -f <your signing key> -n {sshsig.NAMESPACE} {out / '*.txt'}\n"
              f"  (PowerShell: ssh-keygen -Y sign -f <your signing key> -n {sshsig.NAMESPACE} "
              f"(Get-ChildItem '{out / '*.txt'}').FullName)\n"
              f"then: brain identity attach {out}")
    else:
        print(f"\n{len(entries)} unsigned: brain identity unsigned --write DIR writes their payloads to sign")
    return 0


def _payload(args, root: Path) -> int:
    for _, d in records.load(root)["ddr"]:
        if d.get("id") == args.id:
            sys.stdout.buffer.write(identity.payload(d))
            return 0
    raise identity.IdentityError(f"{args.id}: no DDR in {records.RECORDS_DIR}/ddr")


def _sig_files(names: list[str]) -> list[Path]:
    """The signature files named: a folder gives its *.sig, a pattern (PowerShell does not expand one) its matches."""
    out: list[Path] = []
    for name in names:
        p = Path(name)
        if p.is_dir():
            out += sorted(p.glob(f"*{identity.SIG}"))
        elif any(c in p.name for c in "*?["):
            out += sorted(p.parent.glob(p.name))
        else:
            out.append(p)
    return out


def _attach(args, root: Path) -> int:
    files = _sig_files(args.sig)
    if not files:
        raise identity.IdentityError(f"no signature file in {' '.join(args.sig)}")
    missing = [str(p) for p in files if not p.is_file()]
    if missing:
        raise identity.IdentityError(f"not found: {', '.join(missing)}")
    for line in identity.attach(root, files, _project(args, root).name):
        print(line)
    return 0


SUBS = {"check": _check, "unsigned": _unsigned, "payload": _payload, "attach": _attach}


def cmd_identity(args, root: Path) -> int:
    try:
        return SUBS[args.identity_cmd](args, root)
    except identity.IdentityError as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 1


def register(sub, ctx) -> None:
    ident = sub.add_parser("identity", help="members.yaml and the owner's signed answers: check, unsigned, payload, "
                                            "attach (brain.identity)")
    isub = ident.add_subparsers(dest="identity_cmd", required=True)
    isub.add_parser("check", help="members.yaml and the owner-decides answers' signatures (warnings; errors under "
                                  "config.json identity.require_signed)")
    un = isub.add_parser("unsigned", help="the owner-decides answers without a signature")
    un.add_argument("--write", metavar="DIR", help="write each one's payload as DIR/<id>.txt, to read and sign")
    un.add_argument("--json", action="store_true", help="stable keys: id, title, topics, how")
    pa = isub.add_parser("payload", help="what a signature of the answer covers, on stdout")
    pa.add_argument("id", help="a DDR id")
    at = isub.add_parser("attach", help="verify the owner's signatures and keep them beside their records")
    at.add_argument("sig", nargs="+", metavar="SIG", help="DIR/<id>.txt.sig as ssh-keygen -Y sign wrote it, or DIR "
                                                         "(its *.sig)")


run = cmd_identity
