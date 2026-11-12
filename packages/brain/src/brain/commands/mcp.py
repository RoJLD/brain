"""``brain mcp``: the Brain as an MCP server (brain.mcpserver): serve over stdio or loopback HTTP, list its tools."""

from __future__ import annotations

import sys

from .. import ipcauth, mcpserver, neutral
from ._common import root_of

ORDER = 445   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 405   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain mcp serve [--http [--host H] [--port N]]   the Brain as an MCP server, in the foreground (brain.mcpserver):
                                  resources (the neutral source's rules, the procedures' files, the decision log),
                                  prompts (the procedures), tools (the graph's reads, brain check, memory read and a
                                  proposed memory note the memory sync carries by PR); stdio by default (a client
                                  launches it); --http: Streamable HTTP on a loopback address only (default
                                  127.0.0.1:8791, path /mcp), each request with the machine's token (brain ipc
                                  token); starts no service
  brain mcp tools                 the server's tools, their kind (read, write) and what they do
"""
NO_PROJECT = {"mcp"}   # its parsers that take no --project after them


def register(sub, ctx) -> None:
    me = sub.add_parser("mcp", help="the Brain as an MCP server: serve (stdio, or loopback HTTP with the machine's "
                                    "token), tools").add_subparsers(dest="mcp_cmd", required=True)
    sv = me.add_parser("serve", help="serve in the foreground: stdio by default, --http on a loopback address")
    sv.add_argument("--http", action="store_true", help="Streamable HTTP (POST /mcp, JSON answers) instead of stdio")
    sv.add_argument("--host", default="127.0.0.1", help="--http: the loopback address to bind (default 127.0.0.1)")
    sv.add_argument("--port", type=int, default=mcpserver.DEFAULT_PORT,
                    help=f"--http: the port (default {mcpserver.DEFAULT_PORT}; 0: any free one)")
    me.add_parser("tools", help="the server's tools, their kind and what they do")


def early(args) -> int:
    """Machine-wide: the brain served is --root's, else the personal brain (brain.neutral.brain_root)."""
    if args.mcp_cmd == "tools":
        print("\n".join(mcpserver.tools_table()))
        return 0
    if args.http and not mcpserver.bindable(args.host):   # before anything is read
        print(f"brain mcp: binds a loopback address only, not {args.host}", file=sys.stderr)
        return 2
    server = mcpserver.Server(root=neutral.brain_root(root_of(args)))
    if not args.http:
        return mcpserver.serve_stdio(server)
    try:
        return mcpserver.serve_http(server, args.host, args.port)
    except (ValueError, ipcauth.TokenError, OSError) as exc:
        print(f"brain mcp: {exc}", file=sys.stderr)
        return 2
