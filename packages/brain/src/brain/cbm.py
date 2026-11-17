"""codebase-memory-mcp (CBM), the code index of a machine without Docker and of ``brain impact`` on a worktree: its
binary run as a stdio MCP server for the time of one command, never installed, never a service.

The owner unzips the pinned release (docs/code-index.md: its version and checksum) into
``<BRAIN_HOME>/code-index/cbm/bin``; nothing else installs it, and its own ``install`` (which wires agents and hooks)
is never run. Its store is ``<BRAIN_HOME>/code-index/cbm/cache`` (``CBM_CACHE_DIR``, always set by this module: CBM
refuses a second, empty store, so a user has one). Its daemon keeps lock files under ``%LOCALAPPDATA%``, outside
BRAIN_HOME: CBM's, not the engine's.

CBM's own settings start its HTTP UI and a file watcher with any stdio session unless they say no, and can index on
their own: before each session :func:`ensure_off` sets ``ui_enabled``, ``auto_watch``, ``watcher_enabled`` and
``auto_index`` to false (``codebase-memory-mcp config set``, kept in its store), and ``brain health code-index`` reads
them back (``config list``). A session (:class:`Session`) starts the binary with no argument (the stdio server),
speaks newline-delimited JSON-RPC, waits for each answer under a deadline (the process killed past it), and ends the
process (its daemon and index workers end with it). An answer that is not JSON-RPC, an MCP error or a tool's
``isError`` raises :class:`CbmError` with one line: CBM's own ``error`` field when it gives one.

What the engine records of CBM's indexes, the repo, its path and the commit indexed, is
``<BRAIN_HOME>/code-index/cbm/record.json`` (the code-index store: derived, rebuilt by reindexing).
"""

from __future__ import annotations

import collections
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from . import paths, stacks

VERSION = "0.12.1"   # the release the tool and argument names below are read from (docs/code-index.md)
OFF = ("ui_enabled", "auto_watch", "watcher_enabled", "auto_index")   # settings kept false
CONFIG_TIMEOUT = 30.0
START_TIMEOUT = 30.0
CALL_TIMEOUT = 120.0
INDEX_TIMEOUT = 1800.0
RECORD = "record.json"


class CbmError(Exception):
    """CBM missing, down, slow or answering what this module cannot read: its one-line reason."""


def home() -> Path:
    return paths.brain_home() / "code-index" / "cbm"


def binary() -> Path:
    return home() / "bin" / ("codebase-memory-mcp.exe" if os.name == "nt" else "codebase-memory-mcp")


def store() -> Path:
    return home() / "cache"


def installed() -> bool:
    """The binary is where the owner unzips it."""
    return binary().is_file()


def _argv() -> list[str]:
    """The command that runs CBM (the tests put a fake server here)."""
    return [str(binary())]


def _env() -> dict:
    return dict(os.environ, CBM_CACHE_DIR=str(store()))


# --- its settings, through its CLI (no server started) ---

def _cli(args: list[str], timeout: float = CONFIG_TIMEOUT) -> str:
    """The output of ``codebase-memory-mcp ARGS``; CbmError when it is not installed, cannot run, fails or does not
    end in time."""
    if not installed():
        raise CbmError(f"not installed: no {binary().as_posix()} (docs/code-index.md)")
    store().mkdir(parents=True, exist_ok=True)
    try:
        p = subprocess.run([*_argv(), *args], capture_output=True, timeout=timeout, env=_env(),
                           stdin=subprocess.DEVNULL, creationflags=stacks._no_window())
    except subprocess.TimeoutExpired as exc:
        raise CbmError(f"{' '.join(args[:2])}: no answer in {timeout:g} s") from exc
    except OSError as exc:
        raise CbmError(f"{binary().as_posix()} cannot run: {type(exc).__name__}") from exc
    out = (p.stdout + p.stderr).decode("utf-8", "replace")
    if p.returncode:
        raise CbmError(f"{' '.join(args[:2])} exited {p.returncode}: {stacks.useful_line(out)}")
    return out


def settings() -> dict[str, str]:
    """CBM's settings as ``config list`` prints them (``  key = value`` lines), lower-cased values."""
    out = {}
    for line in _cli(["config", "list"]).splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() and " " not in key.strip():
            out[key.strip()] = value.strip().lower()
    return out


def not_off(found: dict[str, str]) -> list[str]:
    """The settings of :data:`OFF` that ``found`` does not hold false (a missing one counts: CBM's default is on)."""
    return [k for k in OFF if found.get(k) != "false"]


def ensure_off() -> list[str]:
    """Set every setting of :data:`OFF` that is not false to false; the names set. CbmError when one stays on."""
    changed = not_off(settings())
    for key in changed:
        _cli(["config", "set", key, "false"])
    left = not_off(settings()) if changed else []
    if left:
        raise CbmError(f"its settings {', '.join(left)} stay on after config set")
    return changed


# --- a stdio MCP session ---

class Session:
    """One stdio server for the time of a command: ``with Session() as s: s.call(tool, args)``. A call past its
    deadline ends the server (its process tree); every later call then fails at once, said in one line."""

    def __init__(self, start_timeout: float = START_TIMEOUT):
        ensure_off()   # not installed: CbmError before anything runs
        self._id = 0
        self._closed = ""
        self._lines: queue.Queue = queue.Queue()
        self._err: collections.deque = collections.deque(maxlen=20)   # the server's last stderr lines, for a reason
        try:
            self._p = subprocess.Popen(_argv(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, env=_env(), creationflags=stacks._no_window())
        except OSError as exc:
            raise CbmError(f"{binary().as_posix()} cannot run: {type(exc).__name__}") from exc
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._drain, daemon=True).start()
        try:
            self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                     "clientInfo": {"name": "brain", "version": "1"}}, start_timeout)
            self._send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        except CbmError:
            self.close()
            raise

    def __enter__(self) -> Session:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _read(self) -> None:
        for line in self._p.stdout:
            self._lines.put(line)
        self._lines.put(None)

    def _drain(self) -> None:
        for line in self._p.stderr:
            text = line.decode("utf-8", "replace").strip()
            if text:
                self._err.append(text)

    def _why_ended(self) -> str:
        try:
            code = self._p.wait(timeout=2)
        except subprocess.TimeoutExpired:
            code = None
        last = stacks.useful_line("\n".join(self._err)) if self._err else ""
        return f"the server ended (exit {code})" + (f": {last[:160]}" if last else "")

    def _send(self, msg: dict) -> None:
        if self._closed:
            raise CbmError(self._closed)
        try:
            self._p.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
            self._p.stdin.flush()
        except (OSError, ValueError) as exc:   # ValueError: a pipe already closed
            raise CbmError(f"the server's input is closed: {type(exc).__name__}") from exc

    def _rpc(self, method: str, params: dict, timeout: float, label: str = "") -> dict:
        self._id += 1
        what = label or method   # a tool call is said by its tool's name
        self._send({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params})
        deadline = time.monotonic() + timeout   # one deadline for the call, whatever the server sends meanwhile
        while True:
            try:
                line = self._lines.get(timeout=max(deadline - time.monotonic(), 0))
            except queue.Empty:
                self.close(f"{what} gave no answer in {timeout:g} s: the server was ended")
                raise CbmError(f"{what}: no answer in {timeout:g} s") from None
            if line is None:
                self._lines.put(None)   # the end stays seen by every later read
                self._closed = self._closed or self._why_ended()
                raise CbmError(f"{what}: {self._closed}")
            try:
                msg = json.loads(line)
            except ValueError:
                raise CbmError(f"{what}: an answer that is not JSON: "
                               f"{stacks.useful_line(line.decode('utf-8', 'replace'))[:120]}") from None
            if not isinstance(msg, dict):
                raise CbmError(f"{what}: an answer that is not a JSON-RPC message")
            if msg.get("id") != self._id:
                continue   # a notification, or an answer to a call given up
            if msg.get("error"):
                err = msg["error"]
                raise CbmError(f"{what}: {err.get('message') if isinstance(err, dict) else err}")
            res = msg.get("result")
            if not isinstance(res, dict):
                raise CbmError(f"{what}: an answer without a result")
            return res

    def call(self, tool: str, arguments: dict, timeout: float = CALL_TIMEOUT) -> dict:
        """The structured answer of ``tool`` (its JSON text when it gives no structuredContent)."""
        res = self._rpc("tools/call", {"name": tool, "arguments": arguments}, timeout, tool)
        data = res.get("structuredContent")
        if not isinstance(data, dict):
            text = "".join(c.get("text", "") for c in res.get("content") or [] if isinstance(c, dict))
            try:
                data = json.loads(text)
            except ValueError:
                data = {"error": stacks.useful_line(text) or "an empty answer"} if res.get("isError") else None
            if not isinstance(data, dict):
                raise CbmError(f"{tool}: an answer that is not a JSON object: {stacks.useful_line(text)[:120]}")
        if res.get("isError") or data.get("error"):
            raise CbmError(f"{tool}: {stacks.useful_line(str(data.get('error') or 'failed'))}")
        return data

    def close(self, why: str = "the session is closed") -> None:
        """End the server: its input closed (it ends with its daemon and workers), else its process tree killed."""
        self._closed = self._closed or why
        p = getattr(self, "_p", None)
        if p is None or p.poll() is not None:
            return
        try:
            p.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _kill_tree(p)


def _kill_tree(p: subprocess.Popen) -> None:
    """Kill ``p`` and its children (CBM's daemon and index workers): taskkill /T on Windows, else the process."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True, timeout=30,
                       creationflags=stacks._no_window())
    else:
        p.kill()
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        print(f"brain: codebase-memory-mcp (pid {p.pid}) did not end", file=sys.stderr)


# --- the tools the engine uses (v0.12.1's names) ---

def index(s: Session, path: Path, name: str, mode: str = "full") -> dict:
    """Index the checkout at ``path`` in place as CBM's project ``name`` (no file written into it)."""
    out = s.call("index_repository", {"repo_path": path.as_posix(), "name": name, "mode": mode}, INDEX_TIMEOUT)
    if out.get("status") != "indexed":
        raise CbmError(f"index_repository: {stacks.useful_line(str(out.get('error') or out.get('status')))}")
    return out


def status(s: Session, name: str) -> dict:
    return s.call("index_status", {"project": name, "format": "json"})


def projects(s: Session) -> list[dict]:
    rows = s.call("list_projects", {"format": "json", "limit": 500}).get("projects")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def delete(s: Session, name: str) -> None:
    s.call("delete_project", {"project": name})


def changes(s: Session, name: str, base: str, depth: int) -> dict:
    """``detect_changes`` of the project's checkout against ``base``: the changed symbols (seeds) and the symbols
    that call them, ``depth`` levels up, each with the one it reaches (via)."""
    return s.call("detect_changes", {"project": name, "base_branch": base, "format": "json", "scope": "impact",
                                     "depth": max(depth, 1), "seeds": "list", "seed_limit": 1000, "limit": 5000,
                                     "changed_limit": 5000, "via": True, "max_output_tokens": 1000000})


# --- the record ---

def record_file() -> Path:
    return home() / RECORD


def read_record() -> dict:
    try:
        data = json.loads(record_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(name: str, entry: dict) -> None:
    f = record_file()
    data = read_record()
    data[name] = entry
    f.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=f.parent, prefix=".record-", suffix=".tmp")   # one per writer
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    os.replace(tmp, f)
