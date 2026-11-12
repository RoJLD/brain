"""``brain health ipc`` (wi-brain-local-ipc-auth): every local service the Brain starts binds loopback and requires the
machine's token (brain.ipcauth), and its container runs as a user that is not root. It reads; it starts nothing.

What it checks, each on its own line (``ipc OK``, ``ipc OFF``, ``ipc warning``, ``ipc FAIL``):

- **the token**: ``<BRAIN_HOME>/ipc/token`` holds a usable token, readable by its owner only (on POSIX: no group or
  other bit). No token: OFF, unless a service is declared to need it (config.json ``ipc.require_token``), then FAIL.
- **the MCP server** (brain mcp serve --http, 127.0.0.1:8791 unless ``ipc.mcp_port``): when something answers there,
  a request without the token must get 401; one that is served is a FAIL. Nothing answering: OFF.
- **the containers** of the Brain's Compose projects (``brain-sovereign``, ``brain-mcp``) and of the code index
  (each stack's ``index.container``), when Docker answers: a port published on an address that is not loopback is a
  FAIL; a container that runs as root is a warning (an image the Brain does not build may need it: Qdrant's does).
- **the token per service**: the MCP server always requires it; the collector when config.json ``ipc.require_token``
  names ``otel-collector`` (opt-in: it would newly refuse Claude Code's export until its headers carry the token,
  brain.bundles); GitNexus has no authentication of its own: a warning that says so, its port on loopback.

Exit 1 on a FAIL, else 0. ``brain health --all`` runs it with the machine's other checks.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import urllib.error
import urllib.request

from . import ipcauth

CHECK = "ipc"
PROJECTS = ("brain-sovereign", "brain-mcp")      # the Compose projects of the Brain's own services
DEFAULT_MCP_PORT = 8791
TOKEN_SERVICES = ("otel-collector",)              # what config.json ipc.require_token may name (brain.bundles)
DOCKER_TIMEOUT = 15.0
PROBE_TIMEOUT = 2.0


def settings(cfg) -> dict:
    """config.json ``ipc``: {require_token: [component...], mcp_port: N}, with the defaults."""
    raw = cfg.data.get("ipc") if isinstance(getattr(cfg, "data", None), dict) else None
    raw = raw if isinstance(raw, dict) else {}
    req = raw.get("require_token")
    port = raw.get("mcp_port")
    return {"require_token": [str(x) for x in req] if isinstance(req, list) else [],
            "mcp_port": port if isinstance(port, int) and not isinstance(port, bool) and 0 < port < 65536
            else DEFAULT_MCP_PORT}


def token_state() -> tuple[str, str]:
    """(OK|OFF|FAIL, what) of the machine's token file."""
    f = ipcauth.token_file()
    if ipcauth.read() is None:
        return "OFF", f"no usable token in {f} (brain ipc token --init)"
    if os.name != "nt":
        try:
            mode = f.stat().st_mode
        except OSError as exc:
            return "FAIL", f"{f}: {exc}"
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            return "FAIL", f"{f} is readable beyond its owner (chmod 600)"
    return "OK", f"token {f}"


def probe_mcp(port: int) -> tuple[str, str]:
    """(OK|OFF|FAIL, what) of a request without the token to the MCP server's port."""
    url = f"http://127.0.0.1:{port}/mcp"
    req = urllib.request.Request(url, data=b'{"jsonrpc":"2.0","id":1,"method":"ping"}', method="POST",
                                 headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=PROBE_TIMEOUT) as r:
            return "FAIL", f"mcp {url} served a request without the token (HTTP {r.status})"
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return "OK", f"mcp {url} refuses a request without the token"
        return "FAIL", f"mcp {url} answered HTTP {exc.code} without the token, not 401"
    except (urllib.error.URLError, OSError, ValueError):
        return "OFF", f"mcp: nothing answers on {url}"


def _docker(argv: list[str]) -> tuple[int | None, str]:
    try:
        p = subprocess.run(["docker", *argv], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=DOCKER_TIMEOUT, stdin=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return None, ""
    return p.returncode, p.stdout or ""


def index_containers(root=None) -> list[str]:
    """The code index's containers the registry names (each stack's index.container)."""
    try:
        from . import stacks
        return [str(s.index["container"]) for s in stacks.load(root).values()
                if isinstance(s.index, dict) and s.index.get("container")]
    except Exception:
        return []


def containers(root=None) -> list[dict] | None:
    """``docker inspect`` of the running containers of the Brain's Compose projects and code index; None when Docker
    does not answer."""
    rc, out = _docker(["ps", "--format", "{{.Names}}\t{{.Label \"com.docker.compose.project\"}}"])
    if rc != 0:
        return None
    wanted = set(index_containers(root))
    names = [n for n, _, proj in (line.partition("\t") for line in out.splitlines() if line.strip())
             if proj in PROJECTS or n in wanted]
    if not names:
        return []
    rc, out = _docker(["inspect", *names])
    try:
        data = json.loads(out) if rc == 0 else None
    except ValueError:
        data = None
    return data if isinstance(data, list) else None


def judge_container(c: dict) -> list[tuple[str, str]]:
    """(FAIL|warning|OK, what) of one inspected container: its published ports, its user."""
    name = str(c.get("Name") or "?").lstrip("/")
    ports = ((c.get("NetworkSettings") or {}).get("Ports") or {})
    wide = sorted(f"{b.get('HostIp') or '0.0.0.0'}:{b.get('HostPort')}->{p}"
                  for p, binds in ports.items() for b in (binds or [])
                  if not ipcauth.is_loopback(b.get("HostIp") or ""))
    out = []
    if wide:
        out.append(("FAIL", f"container {name} publishes beyond loopback: {', '.join(wide)}"))
    user = str((c.get("Config") or {}).get("User") or "")
    if user.split(":")[0] in ("", "0", "root"):
        out.append(("warning", f"container {name} runs as root (user {user or 'unset'})"))
    if not out:
        out.append(("OK", f"container {name}: ports on loopback only, user {user}"))
    return out


def health(cfg, named: bool = True, out=None, root=None) -> int:
    """``brain health ipc``: the lines above; exit 1 on a FAIL."""
    s = settings(cfg)
    lines: list[tuple[str, str]] = []
    state, what = token_state()
    if state == "OFF" and s["require_token"]:
        state, what = "FAIL", f"{what}; config.json ipc.require_token names {', '.join(s['require_token'])}"
    lines.append((state, what))
    mcp = probe_mcp(s["mcp_port"])
    lines.append(mcp)
    found = containers(root)
    if not named and state == "OFF" and mcp[0] == "OFF" and not found:
        return 0   # --all on a machine that runs none of these services: silent
    if found is None:
        lines.append(("warning", "docker does not answer: the containers are not checked"))
    for c in found or []:
        lines += judge_container(c)
    unknown = [n for n in s["require_token"] if n not in TOKEN_SERVICES]
    if unknown:
        lines.append(("FAIL", f"config.json ipc.require_token names {', '.join(unknown)}: only "
                              f"{', '.join(TOKEN_SERVICES)} can require the token"))
    if "otel-collector" not in s["require_token"]:
        lines.append(("warning", "the collector takes OTLP without the token (opt in: config.json ipc.require_token "
                                 "[otel-collector], then brain bundle apply)"))
    if index_containers(root):
        lines.append(("warning", "GitNexus has no authentication of its own: its port stays on loopback"))
    for st, what in lines:
        print(f"{CHECK} {st} {what}" if st != "warning" else f"{CHECK} warning: {what}", file=out, flush=True)
    return 1 if any(st == "FAIL" for st, _ in lines) else 0
