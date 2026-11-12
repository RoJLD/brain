"""``brain ipc``: the machine's token for the Brain's local services (brain.ipcauth): where it is, made once."""

from __future__ import annotations

from .. import ipcauth

ORDER = 446   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 406   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain ipc token [--init]        the machine's token for the Brain's local services (brain.ipcauth): its file and
                                  whether it holds a usable token; --init makes it when there is none (32 random
                                  bytes, the file readable by its owner only); never prints the token: a client reads
                                  the file ($BRAIN_IPC_TOKEN_FILE names another); exit 1 without a usable token
"""
NO_PROJECT = {"ipc"}   # its parsers that take no --project after them


def register(sub, ctx) -> None:
    ip = sub.add_parser("ipc", help="the machine's token for the Brain's local services: where it is, --init makes "
                                    "it").add_subparsers(dest="ipc_cmd", required=True)
    tk = ip.add_parser("token", help="the token's file and whether it is usable; never prints the token")
    tk.add_argument("--init", action="store_true", help="make the token when there is none (an existing one is kept)")


def early(args) -> int:
    if args.init:
        f, made = ipcauth.init()
        print(f"{f}: {'made' if made else 'kept (a usable token was already there)'}")
        return 0
    ok = ipcauth.read() is not None
    print(f"{ipcauth.token_file()}: {'a usable token' if ok else 'no usable token (brain ipc token --init)'}")
    return 0 if ok else 1
