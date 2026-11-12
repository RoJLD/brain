"""The Brain as an MCP server (wi-brain-mcp-server; spec-brain-plugin §2.8 and §3 step 7, spec-brain-multi-agent-
connector §1-§2, MA-1): one tool layer, two transports, so a tool behaves the same on either.

What it serves, read from the personal brain it runs in (``--root``, else brain.neutral.brain_root):

- **resources**: the rules of the neutral source (``brain://rules/<file>``, as brain.neutral reads them), the files of
  each procedure (``brain://procedures/<name>/<file>``), the decision log's index (``brain://decisions``: its dated
  headings) and one ADR through the template ``brain://decisions/{ref}`` (``brain adr show``);
- **prompts**: the procedures (each one's SKILL.md, with an optional ``task`` argument);
- **tools** (:data:`TOOLS`): the graph's reads (``brain items``, ``item show``, ``adr show``, ``spec show``,
  ``next``), ``brain check``, the memory notes read, and a proposed memory write: the note goes into this machine's
  memory folder, which the memory sync exports by a reviewed PR, never to main (brain.memory). A graph tool runs the
  ``brain`` command in a child process, its arguments validated first (an id never starts with ``-``, a text goes as
  ``--text=VALUE``), with a deadline (``BRAIN_MCP_TIMEOUT`` seconds, default 120).

Every answer (a tool's, a resource's, a prompt's) passes the secret scan (brain.secretscan.clean): a line with a key's
shape is dropped and the answer says how many. The guards of wi-brain-mcp-guards judge each call before it runs.

Transports (``brain mcp serve``):

- **stdio** (the default): newline-delimited JSON-RPC 2.0 on stdin and stdout, the process launched by the client
  (Claude Code, Cursor and others' "command" connectors). Nothing is exposed; logs go to stderr.
- **HTTP** (``--http``): Streamable HTTP's POST on ``/mcp``, each answer a JSON body (no SSE stream: the server sends
  no request of its own; GET and DELETE answer 405). It binds a loopback address only (brain.ipcauth), and refuses a
  request without the machine's token (401), from a Host or Origin that is not loopback (403), larger than 1 MB (413)
  or naming a protocol version it does not speak (400). Inside the container (``BRAIN_MCP_CONTAINER=1``, set by its
  image) it binds all of the container's addresses, and the compose file publishes the port on 127.0.0.1 only.

Nothing here starts on its own: ``brain mcp serve`` runs in the foreground of whoever launched it. A service, a
container left running or an endpoint reachable from another machine is the owner's decision (spec §6, Q1 to Q3).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import quote, unquote

from . import __version__, ipcauth, neutral, secretscan

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")   # the newest first: offered when the client asks another
DEFAULT_PORT = 8791
PATH = "/mcp"
MAX_BODY = 1_000_000
CONTAINER_ENV = "BRAIN_MCP_CONTAINER"
TIMEOUT_ENV = "BRAIN_MCP_TIMEOUT"
MAX_TEXT = 400_000          # characters of one answer; the rest is cut, and the answer says so
DECISIONS = "notes/decisions.md"
ADR_HEADING = re.compile(r"^## (\d{4}-\d{2}-\d{2}) — (.+?)\s*$", re.M)

# JSON-RPC and MCP error codes
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603
RESOURCE_NOT_FOUND = -32002

ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/#@+-]{0,199}$")        # a node id, a Doc id, a path
PROJECT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
MEMORY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,199}$")
NOTE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\.md$")
STATUSES = ("todo", "doing", "blocked", "done", "dropped")


class RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


class ToolError(Exception):
    """A tool's arguments are wrong, or it cannot run: the client gets it as a tool result with isError."""


# --- the tool layer ---------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Tool:
    """One tool: its name and schema as the client sees them, ``kind`` (read: changes nothing; write: changes a file
    or a repo), and either ``argv`` (the ``brain`` command it runs, from the validated arguments) or ``func`` (run in
    the server: ``func(server, args) -> (text, is_error)``)."""
    name: str
    title: str
    description: str
    properties: dict
    required: tuple[str, ...] = ()
    kind: str = "read"
    argv: Callable[[dict], list[str]] | None = None
    func: Callable[["Server", dict], tuple[str, bool]] | None = None

    def listing(self) -> dict:
        return {"name": self.name, "title": self.title, "description": self.description,
                "inputSchema": {"type": "object", "properties": self.properties, "required": list(self.required),
                                "additionalProperties": False},
                "annotations": {"title": self.title, "readOnlyHint": self.kind == "read",
                                "destructiveHint": False, "openWorldHint": False}}


def _str(args: dict, key: str, rx: re.Pattern | None = None, required: bool = False, limit: int = 300) -> str | None:
    v = args.get(key)
    if v is None or v == "":
        if required:
            raise ToolError(f"{key} is required")
        return None
    if not isinstance(v, str):
        raise ToolError(f"{key} must be a string")
    if len(v) > limit or any(ord(c) < 32 and c not in "\t" for c in v):
        raise ToolError(f"{key} is too long or holds a control character")
    if rx is not None and not rx.match(v):
        raise ToolError(f"{key} {v!r} is not a valid value")
    return v


def _ref(args: dict, key: str) -> str:
    """A free reference (an id or a title): never an option."""
    v = _str(args, key, required=True)
    if v.lstrip().startswith("-"):
        raise ToolError(f"{key} must not start with -")
    return v


def _project(args: dict) -> list[str]:
    p = _str(args, "project", PROJECT)
    return [f"--project={p}"] if p else []


def _limit(args: dict, default: int = 50) -> int:
    v = args.get("limit", default)
    if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 1000:
        raise ToolError("limit must be an integer from 0 to 1000")
    return v


def _items_argv(a: dict) -> list[str]:
    argv = _project(a) + ["items", f"--limit={_limit(a)}"]
    statuses = a.get("status") or []
    if not isinstance(statuses, list) or any(s not in STATUSES for s in statuses):
        raise ToolError(f"status must be a list of {', '.join(STATUSES)}")
    argv += [f"--status={s}" for s in statuses]
    for key in ("text", "wave", "priority", "type", "milestone"):
        v = _str(a, key)
        if v is not None:
            argv.append(f"--{key}={v}")
    return argv


def _spec_argv(a: dict) -> list[str]:
    argv = _project(a) + ["spec", "show", _ref(a, "ref")]
    section = _str(a, "section")
    if section is not None:
        argv.append(f"--section={section}")
    elif a.get("toc") is True:
        argv.append("--toc")
    return argv


_P = {"project": {"type": "string", "description": "a registered project (default: the brain's own)"}}

TOOLS: tuple[Tool, ...] = (
    Tool("brain_items", "Backlog items",
         "The backlog filtered (brain items): the open work items by default; filters by status, words, wave, "
         "priority, node type or milestone.",
         {**_P, "status": {"type": "array", "items": {"enum": list(STATUSES)}},
          "text": {"type": "string", "description": "every word in the id, title, anchor or props"},
          "wave": {"type": "string"}, "priority": {"type": "string", "description": "P0-P3, P1? or none"},
          "type": {"type": "string", "description": "node type (default WorkItem)"},
          "milestone": {"type": "string"}, "limit": {"type": "integer", "minimum": 0, "maximum": 1000}},
         argv=_items_argv),
    Tool("brain_item_show", "One graph node",
         "A node of the graph (brain item show): its props, edges, the ADRs that decide it and its specs.",
         {**_P, "id": {"type": "string"}}, ("id",),
         argv=lambda a: _project(a) + ["item", "show", _str(a, "id", ID, required=True)]),
    Tool("brain_adr_show", "An ADR",
         "An ADR's text by its id, title or the start of its id, else the ADRs that decide a node (brain adr show).",
         {**_P, "ref": {"type": "string"}, "titles": {"type": "boolean", "description": "headings only"}}, ("ref",),
         argv=lambda a: _project(a) + ["adr", "show", _ref(a, "ref")] + (["--titles"] if a.get("titles") is True
                                                                          else [])),
    Tool("brain_spec_show", "A spec",
         "A spec, one of its sections, or its table of contents (brain spec show).",
         {**_P, "ref": {"type": "string", "description": "a Spec id, a Doc id or the spec's path"},
          "section": {"type": "string", "description": "its number (2.1), key or the start of its title"},
          "toc": {"type": "boolean"}}, ("ref",), argv=_spec_argv),
    Tool("brain_next", "What to do next",
         "The frontier of the backlog: the open items whose dependencies are done (brain next).",
         dict(_P), argv=lambda a: _project(a) + ["next"]),
    Tool("brain_check", "Check the records",
         "The records, journals, decision logs and graph checked (brain check): what is wrong, at zero token.",
         dict(_P), argv=lambda a: _project(a) + ["check"]),
)


def _memory_read(server: "Server", a: dict) -> tuple[str, bool]:
    from . import memory
    key, note = _str(a, "project", MEMORY_KEY), _str(a, "note", NOTE)
    notes = memory.local_notes()
    if key is None:
        keys = sorted({k.split("/", 1)[0] for k in notes})
        return ("The memory folders of this machine (pass one as project):\n" + "\n".join(keys)
                if keys else "No memory note on this machine."), False
    if note is None:
        names = [k.split("/", 1)[1] for k in notes if k.split("/", 1)[0] == key]
        return (f"The notes of {key}:\n" + "\n".join(names)) if names else f"No memory note under {key}.", not names
    f = notes.get(f"{key}/{note}")
    if f is None:
        return f"No note {note} under {key}.", True
    return f.read_text(encoding="utf-8", errors="replace"), False


def _memory_propose(server: "Server", a: dict) -> tuple[str, bool]:
    from . import memory
    key, note = _str(a, "project", MEMORY_KEY, required=True), _str(a, "note", NOTE, required=True)
    content = a.get("content")
    if not isinstance(content, str) or not content.strip() or len(content) > 100_000:
        raise ToolError("content must be a non-empty string of at most 100000 characters")
    hits = secretscan.scan_lines(content)
    if hits:
        raise ToolError(f"refused: line {hits[0][0]} matches a secret pattern ({hits[0][1]}); nothing written")
    folder = memory.local_dir(key)
    if folder is None:
        raise ToolError(f"no project folder {key} on this machine: a note is only written where the project is")
    folder.mkdir(exist_ok=True)
    target = folder / note
    existed = target.is_file()
    tmp = target.with_name(target.name + ".mcp-new")
    tmp.write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, target)
    return (f"{'Updated' if existed else 'Wrote'} {key}/{note} in this machine's memory. The memory sync exports it "
            "by a reviewed PR (brain memory status shows it; never to main)."), False


TOOLS += (
    Tool("memory_read", "Read memory notes",
         "The shared memory notes on this machine: no project lists the memory folders, a project lists its notes, "
         "a project and a note give the note's text.",
         {"project": {"type": "string", "description": "a memory folder's key"}, "note": {"type": "string"}},
         func=_memory_read),
    Tool("memory_propose", "Propose a memory note",
         "Write a memory note into this machine's memory folder of a project; the memory sync carries it to the "
         "brain repo by a reviewed PR, never to main. Refused when the text matches a secret pattern.",
         {"project": {"type": "string", "description": "a memory folder's key (memory_read lists them)"},
          "note": {"type": "string", "description": "the file name, ending in .md"},
          "content": {"type": "string", "description": "the note's Markdown text"}},
         ("project", "note", "content"), kind="write", func=_memory_propose),
)


# --- the server -------------------------------------------------------------------------------------------------------

def _timeout() -> float:
    try:
        return max(1.0, float(os.environ.get(TIMEOUT_ENV, "120")))
    except ValueError:
        return 120.0


def clean(text: str) -> str:
    """``text`` cut to MAX_TEXT and passed through the secret scan; a note says what was dropped or cut."""
    cut = len(text) > MAX_TEXT
    text = text[:MAX_TEXT]
    text, dropped = secretscan.clean_text(text)
    if dropped:
        text += f"\n[{dropped} line(s) dropped by the secret scan]"
    if cut:
        text += f"\n[cut at {MAX_TEXT} characters]"
    return text


@dataclass
class Server:
    """The transport-free MCP server: :meth:`handle` takes one JSON-RPC message, returns the answer or None."""
    root: Path
    tools: tuple[Tool, ...] = TOOLS
    client: dict = field(default_factory=dict)       # clientInfo, as initialize gave it
    protocol: str = PROTOCOLS[0]
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # JSON-RPC
    def handle(self, msg) -> dict | None:
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return _error(msg.get("id") if isinstance(msg, dict) else None, INVALID_REQUEST, "not a JSON-RPC 2.0 message")
        method = msg.get("method")
        if not isinstance(method, str):
            return None   # a response or an error from the client: this server sends no request
        if "id" not in msg:
            return None   # a notification (initialized, cancelled): nothing to answer
        mid = msg.get("id")
        params = msg.get("params") or {}
        if not isinstance(params, dict):
            return _error(mid, INVALID_PARAMS, "params must be an object")
        handler = METHODS.get(method)
        if handler is None:
            return _error(mid, METHOD_NOT_FOUND, f"method not found: {method}")
        try:
            return {"jsonrpc": "2.0", "id": mid, "result": handler(self, params)}
        except RpcError as exc:
            return _error(mid, exc.code, str(exc))
        except Exception as exc:   # never a traceback to the client: its type only, the rest on stderr
            print(f"brain mcp: {method} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return _error(mid, INTERNAL_ERROR, f"internal error ({type(exc).__name__})")

    def initialize(self, params: dict) -> dict:
        asked = params.get("protocolVersion")
        self.protocol = asked if asked in PROTOCOLS else PROTOCOLS[0]
        info = params.get("clientInfo")
        self.client = {k: str(info[k])[:100] for k in ("name", "version") if isinstance(info, dict) and k in info}
        return {"protocolVersion": self.protocol,
                "capabilities": {"tools": {"listChanged": False},
                                 "resources": {"listChanged": False, "subscribe": False},
                                 "prompts": {"listChanged": False}},
                "serverInfo": {"name": "brain", "title": "Brain", "version": __version__},
                "instructions": "The Brain's rules (resources brain://rules/...), decisions (brain://decisions), "
                                "procedures (prompts) and tools over its graph and memory. Read the rules before "
                                "acting; a write goes through a reviewed PR."}

    # tools
    def tool(self, name) -> Tool:
        t = next((t for t in self.tools if t.name == name), None)
        if t is None:
            raise RpcError(INVALID_PARAMS, f"unknown tool: {name}")
        return t

    def call_tool(self, params: dict) -> dict:
        tool = self.tool(params.get("name"))
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            raise RpcError(INVALID_PARAMS, "arguments must be an object")
        unknown = sorted(set(args) - set(tool.properties))
        try:
            if unknown:
                raise ToolError(f"unknown argument(s): {', '.join(unknown)}")
            text, is_error = self.run(tool, args)
        except ToolError as exc:
            text, is_error = str(exc), True
        return {"content": [{"type": "text", "text": clean(text)}], "isError": bool(is_error)}

    def run(self, tool: Tool, args: dict) -> tuple[str, bool]:
        """Run a tool whose arguments passed (ToolError when they do not)."""
        if tool.func is not None:
            with self.lock:
                return tool.func(self, args)
        return self.brain(tool.argv(args))

    def brain(self, argv: list[str]) -> tuple[str, bool]:
        """``brain --root ROOT ARGV`` in a child process: (its stdout then stderr, failed)."""
        cmd = [sys.executable, "-m", "brain", f"--root={self.root}", *argv]
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        try:
            p = subprocess.run(cmd, cwd=self.root, env=env, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=_timeout(), stdin=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            return f"brain {argv[0] if argv else ''}: no answer within {_timeout():.0f} s", True
        out = (p.stdout or "") + (("\n" if p.stdout else "") + p.stderr if p.stderr else "")
        return out.strip() or f"(exit {p.returncode}, no output)", p.returncode != 0

    # resources and prompts
    def source(self) -> neutral.Source:
        return neutral.load(self.root)

    def resources(self) -> list[dict]:
        src = self.source()
        out = [{"uri": f"brain://rules/{quote(rel)}", "name": rel, "title": rf.heading()[0] or rel,
                "description": f"rules of scope {rf.scope or neutral.GLOBAL}", "mimeType": "text/markdown"}
               for rel, rf in sorted(src.rule_files.items())]
        for name, proc in sorted(src.procedures.items()):
            out += [{"uri": f"brain://procedures/{quote(name)}/{quote(rel)}", "name": f"{name}/{rel}",
                     "mimeType": "text/markdown" if rel.endswith(".md") else "text/plain"}
                    for rel in sorted(proc.files)]
        if (self.root / DECISIONS).is_file():
            out.append({"uri": "brain://decisions", "name": "decisions", "title": "The decision log's index",
                        "description": "every ADR's date and title; brain://decisions/{ref} reads one",
                        "mimeType": "text/markdown"})
        return out

    def read_resource(self, uri: str) -> str:
        """A resource's text; RpcError RESOURCE_NOT_FOUND for a URI that names nothing this server serves (only
        what resources() lists, or an ADR: never a path outside them)."""
        kind, _, rest = uri[len("brain://"):].partition("/") if isinstance(uri, str) and uri.startswith("brain://") \
            else ("", "", "")
        reader = {"rules": self._rules, "procedures": self._procedure, "decisions": self._decisions}.get(kind)
        text = reader(rest) if reader else None
        if text is None:
            raise RpcError(RESOURCE_NOT_FOUND, f"resource not found: {uri}")
        return text

    def _rules(self, rest: str) -> str | None:
        rf = self.source().rule_files.get(unquote(rest))
        return rf.render() if rf is not None else None

    def _procedure(self, rest: str) -> str | None:
        name, _, rel = rest.partition("/")
        proc = self.source().procedures.get(unquote(name))
        f = proc.files.get(unquote(rel)) if proc else None
        return f.read_text(encoding="utf-8", errors="replace") if f is not None else None

    def _decisions(self, rest: str) -> str | None:
        if rest:   # one ADR, through brain adr show
            ref = unquote(rest)
            if ref.lstrip().startswith("-") or len(ref) > 300:
                raise RpcError(INVALID_PARAMS, "not a valid ADR reference")
            text, failed = self.brain(["adr", "show", ref])
            return None if failed else text
        f = self.root / DECISIONS
        if not f.is_file():
            return None
        rows = [f"- {d} — {t}" for d, t in ADR_HEADING.findall(f.read_text(encoding="utf-8"))]
        return "# The decision log\n\n" + "\n".join(rows) + "\n"

    def prompts(self) -> list[dict]:
        return [{"name": name, "title": str(p.meta.get("name") or name),
                 "description": str(p.meta.get("description") or ""),
                 "arguments": [{"name": "task", "description": "what to apply it to", "required": False}]}
                for name, p in sorted(self.source().procedures.items()) if neutral.SKILL in p.files]

    def get_prompt(self, params: dict) -> dict:
        name = params.get("name")
        proc = self.source().procedures.get(name) if isinstance(name, str) else None
        if proc is None or neutral.SKILL not in proc.files:
            raise RpcError(INVALID_PARAMS, f"unknown prompt: {name}")
        meta, body = neutral.front_matter(proc.files[neutral.SKILL].read_text(encoding="utf-8"))
        others = sorted(set(proc.files) - {neutral.SKILL})
        if others:
            body += "\n\nIts other files (resources brain://procedures/" + name + "/...): " + ", ".join(others) + "\n"
        task = (params.get("arguments") or {}).get("task") if isinstance(params.get("arguments"), dict) else None
        if isinstance(task, str) and task.strip():
            body += f"\n\nApply this procedure to: {task.strip()}\n"
        return {"description": str(meta.get("description") or ""),
                "messages": [{"role": "user", "content": {"type": "text", "text": clean(body)}}]}


def _error(mid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


METHODS: dict[str, Callable[[Server, dict], dict]] = {
    "initialize": Server.initialize,
    "ping": lambda s, p: {},
    "tools/list": lambda s, p: {"tools": [t.listing() for t in s.tools]},
    "tools/call": Server.call_tool,
    "resources/list": lambda s, p: {"resources": s.resources()},
    "resources/templates/list": lambda s, p: {"resourceTemplates": [
        {"uriTemplate": "brain://decisions/{ref}", "name": "adr", "title": "An ADR",
         "description": "an ADR by its id, title or the start of its id", "mimeType": "text/markdown"}]},
    "resources/read": lambda s, p: {"contents": [{"uri": p.get("uri"), "mimeType": "text/markdown",
                                                  "text": clean(s.read_resource(p.get("uri")))}]},
    "prompts/list": lambda s, p: {"prompts": s.prompts()},
    "prompts/get": Server.get_prompt,
}


def handle_body(server: Server, body) -> object | None:
    """One parsed body (a message, or a batch of them): the answer, or None when nothing is to be answered."""
    if isinstance(body, list):
        if not body:
            return _error(None, INVALID_REQUEST, "empty batch")
        answers = [a for a in (server.handle(m) for m in body) if a is not None]
        return answers or None
    return server.handle(body)


# --- stdio ------------------------------------------------------------------------------------------------------------

def serve_stdio(server: Server, stdin=None, stdout=None) -> int:
    """Newline-delimited JSON-RPC on stdin and stdout until stdin closes."""
    inp, out = stdin or sys.stdin, stdout or sys.stdout
    for stream in (s for s, given in ((inp, stdin), (out, stdout)) if given is None):
        if hasattr(stream, "reconfigure"):   # UTF-8 and bare newlines whatever the console's codepage
            stream.reconfigure(encoding="utf-8", errors="replace", newline="\n")
    for line in inp:
        line = line.strip()
        if not line:
            continue
        try:
            body = json.loads(line)
        except ValueError:
            answer = _error(None, PARSE_ERROR, "not JSON")
        else:
            answer = handle_body(server, body)
        if answer is not None:
            out.write(json.dumps(answer, ensure_ascii=False, separators=(",", ":")) + "\n")
            out.flush()
    return 0


# --- HTTP -------------------------------------------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    server_version = "brain-mcp"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):   # the request line and status only, never a header
        print(f"brain mcp: {self.address_string()} {fmt % args}", file=sys.stderr)

    def _send(self, code: int, body: object | None = None, headers: dict | None = None) -> None:
        data = b"" if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        if body is not None:
            self.send_header("Content-Type", "application/json")
        if code >= 400:   # a refused request's body may be unread: never reuse the connection after it
            self.send_header("Connection", "close")
            self.close_connection = True
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if data:
            self.wfile.write(data)

    def _refused(self) -> bool:
        """Answer and True when the request may not reach the server: path, Host, Origin, token, version."""
        if self.path.split("?", 1)[0] != PATH:
            self._send(404, {"error": "not found"})
        elif not ipcauth.is_loopback(ipcauth.host_of(self.headers.get("Host"))) or \
                not ipcauth.origin_ok(self.headers.get("Origin")):
            self._send(403, {"error": "only a loopback Host and Origin are served"})
        elif not ipcauth.authorized(self.headers.get("Authorization"), self.server.token):
            self._send(401, {"error": "the machine's token is required (brain ipc token)"},
                       {"WWW-Authenticate": 'Bearer realm="brain"'})
        elif self.headers.get("MCP-Protocol-Version") not in (None, *PROTOCOLS):
            self._send(400, {"error": f"unsupported protocol version; this server speaks {', '.join(PROTOCOLS)}"})
        else:
            return False
        return True

    def do_POST(self):
        if self._refused():
            return
        try:
            length = int(self.headers.get("Content-Length") or -1)
        except ValueError:
            length = -1
        if length < 0:
            self._send(411, {"error": "Content-Length is required"})
            return
        if length > MAX_BODY:
            self._send(413, {"error": f"a body is at most {MAX_BODY} bytes"})
            return
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._send(400, _error(None, PARSE_ERROR, "not JSON"))
            return
        answer = handle_body(self.server.mcp, body)
        if answer is None:
            self._send(202)
        else:
            self._send(200, answer)

    def _not_allowed(self):
        if not self._refused():
            self._send(405, {"error": "POST only: this server opens no stream"}, {"Allow": "POST"})

    do_GET = do_DELETE = do_PUT = _not_allowed


class HTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, mcp: Server, token: str, host: str, port: int):
        self.mcp = mcp
        self.token = token
        family_v6 = ":" in host
        if family_v6:
            import socket
            self.address_family = socket.AF_INET6
        super().__init__((host, port), _Handler)


def bindable(host: str) -> bool:
    """A loopback address; any address inside the container, whose compose file publishes on 127.0.0.1 only."""
    return ipcauth.is_loopback(host) or os.environ.get(CONTAINER_ENV) == "1"


def make_http(server: Server, host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> HTTPServer:
    """The HTTP transport, bound but not serving yet; ValueError for an address it may not bind, TokenError when the
    machine has no token."""
    if not bindable(host):
        raise ValueError(f"brain mcp binds a loopback address only, not {host}: an endpoint reachable from another "
                         "machine is the owner's decision (a tunnel, spec-brain-multi-agent-connector §6)")
    return HTTPServer(server, ipcauth.require(), host, port)


def serve_http(server: Server, host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> int:
    httpd = make_http(server, host, port)
    print(f"brain mcp: serving http://{host}:{httpd.server_address[1]}{PATH} (token: {ipcauth.token_file()})",
          file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


def tools_table() -> list[str]:
    """``brain mcp tools``: each tool, its kind and what it does."""
    return [f"{t.name:<17} {t.kind:<5} {t.description}" for t in TOOLS]
