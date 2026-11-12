"""``brain ipc``: the machine's token for the Brain's local services (brain.ipcauth): where it is, made once, and the
headers Claude Code's OTLP export sends with it."""

from __future__ import annotations

import json
import sys

from .. import config, ipcauth, ipchealth
from ._common import root_of

ORDER = 446   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 406   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain ipc token [--init]        the machine's token for the Brain's local services (brain.ipcauth): its file and
                                  whether it holds a usable token; --init makes it when there is none (32 random
                                  bytes, the file readable by its owner only); never prints the token: a client reads
                                  the file ($BRAIN_IPC_TOKEN_FILE names another); exit 1 without a usable token
  brain ipc otel-headers          the OTLP export's headers for Claude Code's otelHeadersHelper setting, one JSON
                                  object {"Authorization": "Bearer <token>"} on stdout, for the collector that
                                  requires the token (config.json ipc.require_token); the helper's only output: a
                                  session never runs it (the owner guard, keys); exit 1, nothing on stdout, without a
                                  usable token
  brain ipc claude-settings [--json]
                                  what Claude Code's user settings need for its OTLP export, from config.json
                                  adapters.claude.telemetry: env CLAUDE_CODE_ENABLE_TELEMETRY and OTEL_*, and
                                  otelHeadersHelper (brain ipc otel-headers) when the collector requires the token
                                  (ipc.require_token); install.ps1 adds them (additions only); prints no secret; exit 1
                                  on an error of the section (the helper off loopback or with grpc, a headers variable)
"""
NO_PROJECT = {"ipc"}   # its parsers that take no --project after them


def register(sub, ctx) -> None:
    ip = sub.add_parser("ipc", help="the machine's token for the Brain's local services: where it is, --init makes "
                                    "it").add_subparsers(dest="ipc_cmd", required=True)
    tk = ip.add_parser("token", help="the token's file and whether it is usable; never prints the token")
    tk.add_argument("--init", action="store_true", help="make the token when there is none (an existing one is kept)")
    ip.add_parser("otel-headers", help="the OTLP export's headers (Authorization: Bearer) as JSON, for Claude Code's "
                                       "otelHeadersHelper; exit 1 without a usable token")
    cs = ip.add_parser("claude-settings", help="what Claude Code's user settings need for its OTLP export, from "
                                               "config.json adapters.claude.telemetry (install.ps1 adds them)")
    cs.add_argument("--json", action="store_true", help="one JSON object: enabled, env, otelHeadersHelper, errors")


def otel_headers() -> int:
    """Claude Code's otelHeadersHelper contract: a JSON object of string headers on stdout, nothing else. Without a
    usable token: nothing on stdout (the export fails visibly rather than going out unauthenticated), the fix on
    stderr, exit 1."""
    tok = ipcauth.read()
    if tok is None:
        print(f"brain ipc otel-headers: no usable token in {ipcauth.token_file()} (the owner makes it with brain ipc "
              "token --init)", file=sys.stderr)
        return 1
    sys.stdout.write(json.dumps({"Authorization": f"Bearer {tok}"}) + "\n")
    return 0


def claude_settings(args) -> int:
    """The settings of Claude Code's OTLP export (brain.ipchealth.export_settings), as JSON for the installer or as
    lines; exit 1 on an error of config.json adapters.claude.telemetry."""
    res = ipchealth.export_settings(config.load(root_of(args)))
    if args.json:
        print(json.dumps(res, ensure_ascii=False))
        return 1 if res["errors"] else 0
    if not res["enabled"]:
        print("Claude Code's telemetry: off (config.json adapters.claude.telemetry.enabled)")
    for name, value in res["env"].items():
        print(f"env      {name}={value}")
    if res[ipchealth.HELPER_KEY]:
        print(f"helper   {ipchealth.HELPER_KEY}: {res[ipchealth.HELPER_KEY]}")
    for e in res["errors"]:
        print(f"error    {e}", file=sys.stderr)
    return 1 if res["errors"] else 0


def early(args) -> int:
    if args.ipc_cmd == "otel-headers":
        return otel_headers()
    if args.ipc_cmd == "claude-settings":
        return claude_settings(args)
    if args.init:
        f, made = ipcauth.init()
        print(f"{f}: {'made' if made else 'kept (a usable token was already there)'}")
        return 0
    ok = ipcauth.read() is not None
    print(f"{ipcauth.token_file()}: {'a usable token' if ok else 'no usable token (brain ipc token --init)'}")
    return 0 if ok else 1
