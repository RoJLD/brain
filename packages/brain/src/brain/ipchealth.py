"""``brain health ipc`` (wi-brain-local-ipc-auth): every local service the Brain starts binds loopback and requires the
machine's token (brain.ipcauth), and its container runs as a user that is not root. It reads; it starts nothing.

What it checks, each on its own line (``ipc OK``, ``ipc OFF``, ``ipc warning``, ``ipc FAIL``):

- **the token**: ``<BRAIN_HOME>/ipc/token`` holds a usable token, not readable by every user (on POSIX: no "other"
  bit; a group bit or an ACL is how a container's user may read it). No token: OFF, unless a service is declared to need it (config.json ``ipc.require_token``), then FAIL.
- **the MCP server** (brain mcp serve --http, 127.0.0.1:8791 unless ``ipc.mcp_port``): when something answers there,
  a request without the token must get 401; one that is served is a FAIL. Nothing answering: OFF (a connection
  bounded to 0.3 s first); another program answering while the machine has no token: OFF, no MCP server can run.
- **the containers** of the Brain's Compose projects (``brain-sovereign``, ``brain-mcp``) and of the code index
  (each stack's ``index.container``), when Docker answers: a port published on an address that is not loopback is a
  FAIL; a container that runs as root is a warning (an image the Brain does not build may need it: Qdrant's does).
- **the token per service**: the MCP server always requires it; the collector when config.json ``ipc.require_token``
  names ``otel-collector`` (opt-in: it would newly refuse Claude Code's export until its headers carry the token,
  brain.bundles); GitNexus has no authentication of its own: a warning that says so, its port on loopback.
- **Claude Code's export**, when the collector requires the token: its user settings (``$CLAUDE_CONFIG_DIR`` or
  ``~/.claude``, ``settings.json``) with the export on and no ``otelHeadersHelper`` is a FAIL (the collector refuses
  the export); the grpc protocol with the helper too (Claude Code does not send it then); the token in clear in
  ``OTEL_EXPORTER_OTLP_HEADERS`` a warning. :func:`export_settings` renders what those settings need from config.json
  ``adapters.claude.telemetry`` (``brain ipc claude-settings``, which the installer adds to them).

Exit 1 on a FAIL, else 0. ``brain health --all`` runs it with the machine's other checks, silent on a machine that
never made the token and requires none (nothing probed, Docker not asked): what ``--all`` said before stays the same.
Each container is inspected on its own: one that stopped meanwhile is a warning and hides no other.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import socket
import stat
import urllib.error
import urllib.request
from pathlib import Path

from . import ipcauth

CHECK = "ipc"
PROJECTS = ("brain-sovereign", "brain-mcp")      # the Compose projects of the Brain's own services
DEFAULT_MCP_PORT = 8791
TOKEN_SERVICES = ("otel-collector",)              # what config.json ipc.require_token may name (brain.bundles)
DOCKER_TIMEOUT = 15.0
PROBE_TIMEOUT = 2.0
CONNECT_TIMEOUT = 0.3


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
    """(OK|OFF|FAIL, what) of the machine's token file. On POSIX a token readable by every user (an "other" bit) is a
    FAIL; a group bit or an ACL entry may be how a container's user reads it (docs/mcp.md), so it passes."""
    f = ipcauth.token_file()
    if ipcauth.read() is None:
        return "OFF", f"no usable token in {f} (brain ipc token --init)"
    if os.name != "nt":
        try:
            mode = f.stat().st_mode
        except OSError as exc:
            return "FAIL", f"{f}: {exc}"
        if mode & stat.S_IRWXO:
            return "FAIL", f"{f} is readable by every user (chmod o-rwx)"
    return "OK", f"token {f}"


def _listening(port: int) -> bool:
    """Something accepts a connection on 127.0.0.1:port within CONNECT_TIMEOUT (a closed port on Windows is not
    refused at once: this bounds the wait)."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=CONNECT_TIMEOUT):
            return True
    except OSError:
        return False


def probe_mcp(port: int, token: bool = True) -> tuple[str, str]:
    """(OK|OFF|FAIL, what) of a request without the token to the MCP server's port. ``token``: the machine has one;
    without it no MCP server can run, so whatever answers there is another program: OFF, never a FAIL."""
    url = f"http://127.0.0.1:{port}/mcp"
    if not _listening(port):
        return "OFF", f"mcp: nothing answers on {url}"
    req = urllib.request.Request(url, data=b'{"jsonrpc":"2.0","id":1,"method":"ping"}', method="POST",
                                 headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    other = ("OFF", f"mcp: another program answers on {url} (no token on this machine: no MCP server can run)")
    try:
        with opener.open(req, timeout=PROBE_TIMEOUT) as r:
            return ("FAIL", f"mcp {url} served a request without the token (HTTP {r.status})") if token else other
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return "OK", f"mcp {url} refuses a request without the token"
        return ("FAIL", f"mcp {url} answered HTTP {exc.code} without the token, not 401") if token else other
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException):
        return ("FAIL", f"mcp: what answers on {url} is not the MCP server") if token else other


def _docker(argv: list[str]) -> tuple[int | None, str]:
    """(exit code, output) of ``docker ARGV`` through brain.stacks' runner (None: no answer, or no docker)."""
    from . import stacks
    try:
        return stacks._run(["docker", *argv], None, DOCKER_TIMEOUT)
    except OSError:
        return None, ""


def index_containers(root=None) -> list[str]:
    """The code index's containers the registry names (each stack's index.container)."""
    try:
        from . import stacks
        return [str(s.index["container"]) for s in stacks.load(root).values()
                if isinstance(s.index, dict) and s.index.get("container")]
    except Exception:
        return []


def _inspect(name: str) -> dict:
    """``docker inspect`` of one container; {"Name", "_error"} when it cannot be read (stopped meanwhile, a warning
    on stderr around the JSON): one container that fails hides no other."""
    rc, out = _docker(["inspect", "--format", "{{json .}}", name])
    line = next((x for x in out.splitlines() if x.startswith("{")), "")
    try:
        data = json.loads(line) if rc == 0 and line else None
    except ValueError:
        data = None
    return data if isinstance(data, dict) else {"Name": name, "_error": f"docker inspect exited {rc}"}


def containers(root=None) -> list[dict] | None:
    """``docker inspect`` of the running containers of the Brain's Compose projects and code index, one by one;
    None when Docker does not answer."""
    rc, out = _docker(["ps", "--format", "{{.Names}}\t{{.Label \"com.docker.compose.project\"}}"])
    if rc != 0:
        return None
    wanted = set(index_containers(root))
    names = [n for n, _, proj in (line.partition("\t") for line in out.splitlines() if line.strip())
             if proj in PROJECTS or n in wanted]
    return [_inspect(n) for n in names]


def _wide(ports: dict) -> list[str]:
    """The bindings of ``docker inspect``'s NetworkSettings.Ports on an address that is not loopback."""
    return sorted(f"{b.get('HostIp') or '0.0.0.0'}:{b.get('HostPort')}->{p}"
                  for p, binds in ports.items() for b in (binds or [])
                  if not ipcauth.is_loopback(b.get("HostIp") or ""))


def judge_container(c: dict) -> list[tuple[str, str]]:
    """(FAIL|warning|OK, what) of one inspected container: its published ports, its user."""
    name = str(c.get("Name") or "?").lstrip("/")
    if c.get("_error"):
        return [("warning", f"container {name} could not be inspected ({c['_error']}): run brain health ipc again")]
    wide = _wide((c.get("NetworkSettings") or {}).get("Ports") or {})
    user = str((c.get("Config") or {}).get("User") or "")
    out = [("FAIL", f"container {name} publishes beyond loopback: {', '.join(wide)}")] if wide else []
    if user.split(":")[0] in ("", "0", "root"):
        out.append(("warning", f"container {name} runs as root (user {user or 'unset'})"))
    return out or [("OK", f"container {name}: ports on loopback only, user {user}")]


def service_lines(s: dict, root=None) -> list[tuple[str, str]]:
    """The containers' lines, then what takes requests without the token."""
    found = containers(root)
    lines = [] if found is not None else [("warning", "docker does not answer: the containers are not checked")]
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
    return lines


# --- Claude Code's OTLP export (wi-brain-install-claude-telemetry) ----------------------------------------------------
# config.json adapters.claude.telemetry says what Claude Code's user settings need for its export to the collector;
# the installer adds it to ~/.claude/settings.json (additions only, plan then -Apply), and brain health ipc says when
# the collector requires the token while those settings carry no otelHeadersHelper.
EXPORT_PROTOCOLS = ("http/protobuf", "http/json", "grpc")
EXPORTERS = {"metrics": "OTEL_METRICS_EXPORTER", "logs": "OTEL_LOGS_EXPORTER"}
HELPER_MODES = ("auto", "always", "never")
EXPORT_DEFAULTS = {"enabled": False, "endpoint": "http://127.0.0.1:4318", "protocol": "http/protobuf",
                   "exporters": ["metrics", "logs"], "env": {}, "headers_helper": "auto"}
ENABLE_VAR = "CLAUDE_CODE_ENABLE_TELEMETRY"
HELPER_KEY = "otelHeadersHelper"
HELPER = "brain ipc otel-headers"   # the launcher's folder is on the user PATH (install.ps1)
OTEL_NAME = re.compile(r"^OTEL_[A-Z0-9_]+$")
URL = re.compile(r"^https?://[^/@\s\\]+(/[^@\s\\]*)?$")
LOOPBACK_URL = re.compile(r"^https?://(127(\.\d{1,3}){3}|localhost|\[::1\])(:\d{1,5})?(/[^@\s\\]*)?$", re.I)
ENDPOINT_VAR = re.compile(r"^OTEL_EXPORTER_OTLP(_[A-Z]+)?_ENDPOINT$")   # the export's, or one signal's
PROTOCOL_VAR = re.compile(r"^OTEL_EXPORTER_OTLP(_[A-Z]+)?_PROTOCOL$")


def telemetry(cfg) -> dict:
    """config.json ``adapters.claude.telemetry`` over its defaults: {enabled, endpoint, protocol, exporters, env,
    headers_helper}. A value of the wrong type keeps its default here; brain config --check refuses it."""
    data = cfg.data if isinstance(getattr(cfg, "data", None), dict) else {}
    adapters = data.get("adapters") if isinstance(data.get("adapters"), dict) else {}
    claude = adapters.get("claude") if isinstance(adapters.get("claude"), dict) else {}
    raw = claude.get("telemetry") if isinstance(claude.get("telemetry"), dict) else {}
    out = {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v)
           for k, v in EXPORT_DEFAULTS.items()}
    for key, default in EXPORT_DEFAULTS.items():
        v = raw.get(key)
        if v is not None and type(v) is type(default):
            out[key] = v
    return out


def export_settings(cfg, current: dict | None = None) -> dict:
    """What Claude Code's user settings need for its OTLP export, from config.json ``adapters.claude.telemetry``:
    ``{"enabled", "env": {name: value}, "otelHeadersHelper": command or None, "errors": [...]}``. The helper is
    wanted when ``headers_helper`` is always, or auto while ``ipc.require_token`` names otel-collector. Refused (an
    error, nothing to write): an endpoint with a user part, a backslash or a space; a helper with the grpc protocol
    (Claude Code then sends only the static headers) or an endpoint off loopback (the machine's token would leave
    it); an extra variable that is not OTEL_*, that names the headers (the token goes through the helper, never in
    clear in settings.json) or that a key of the section already sets. ``current``: the user settings as they are;
    since the installer only adds, the helper is judged against the export they would then make (a value already
    there wins over the section's: an endpoint off loopback or grpc kept there refuses the helper too)."""
    t = telemetry(cfg)
    res = {"enabled": bool(t["enabled"]), "env": {}, HELPER_KEY: None, "errors": []}
    if not res["enabled"]:
        return res
    errors = res["errors"]
    protocol, endpoint, mode = str(t["protocol"]), str(t["endpoint"]), str(t["headers_helper"])
    for key, value, allowed in (("protocol", protocol, EXPORT_PROTOCOLS), ("headers_helper", mode, HELPER_MODES),
                                *(("exporters", x, tuple(EXPORTERS)) for x in t["exporters"])):
        if value not in allowed:
            errors.append(f"adapters.claude.telemetry.{key} {value!r}: one of {', '.join(allowed)}")
    if not URL.match(endpoint):
        errors.append(f"adapters.claude.telemetry.endpoint {endpoint!r}: an http:// or https:// URL, with no user "
                      "part, backslash or space")
    env = {ENABLE_VAR: "1", **{EXPORTERS[x]: "otlp" for x in t["exporters"] if x in EXPORTERS},
           "OTEL_EXPORTER_OTLP_PROTOCOL": protocol, "OTEL_EXPORTER_OTLP_ENDPOINT": endpoint}
    _extra_env(t["env"], env, errors)
    if mode == "always" or (mode == "auto" and "otel-collector" in settings(cfg)["require_token"]):
        have = (current or {}).get("env") if isinstance((current or {}).get("env"), dict) else {}
        errors += helper_errors({**env, **{k: str(v) for k, v in have.items()}})
        res[HELPER_KEY] = HELPER
    res["env"] = env
    return res


def _extra_env(extra: dict, env: dict, errors: list[str]) -> None:
    """The section's ``env`` added to ``env``: only OTEL_* string values, never a headers variable (the token goes
    through the helper), never one the section's own keys set; each refusal in ``errors``."""
    for name, value in extra.items():
        why = ("only OTEL_* variables" if not OTEL_NAME.match(str(name))
               else "the token goes through otelHeadersHelper, never in clear in settings.json" if "HEADERS" in name
               else "set by the section's own keys" if name in env
               else "a string" if not isinstance(value, str) else "")
        if why:
            errors.append(f"adapters.claude.telemetry.env {name}: {why}")
        else:
            env[name] = value


def loopback_url(url: str) -> bool:
    """An http(s) URL whose host is this machine's loopback, read strictly: 127.x.x.x, localhost or [::1], an
    optional port and path, no user part, backslash or space (where two URL parsers may disagree on the host, the
    token could go to the other one's)."""
    return bool(LOOPBACK_URL.match(url))


def helper_errors(env: dict) -> list[str]:
    """Why otelHeadersHelper cannot go with the export ``env`` makes (Claude Code's settings env, with what the
    installer would add): grpc for any signal (Claude Code then sends only the static headers), an endpoint off
    loopback for any signal (the helper sends the machine's token there). Unset, Claude Code's own defaults are
    loopback and http."""
    errors = []
    for name in sorted(k for k in env if PROTOCOL_VAR.match(k) and str(env[k]).strip() == "grpc"):
        errors.append(f"{name} grpc: otelHeadersHelper works with http/protobuf and http/json only (with grpc Claude "
                      "Code sends only the static headers)")
    for name in sorted(k for k in env if ENDPOINT_VAR.match(k) and not loopback_url(str(env[k]).strip())):
        errors.append(f"{name} off loopback: the machine's token would leave it (otelHeadersHelper sends it)")
    return errors


def claude_settings_file() -> Path:
    """Claude Code's user settings: $CLAUDE_CONFIG_DIR/settings.json, default ~/.claude/settings.json."""
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(env).expanduser() if env else Path.home() / ".claude") / "settings.json"


def export_lines(s: dict, path: Path | None = None) -> list[tuple[str, str]]:
    """Whether Claude Code's export carries the token the collector requires (ipc.require_token names
    otel-collector), read from its user settings: none of a collector that does not require it."""
    if "otel-collector" not in s["require_token"]:
        return []
    f = path or claude_settings_file()
    try:
        data = json.loads(f.read_text(encoding="utf-8-sig")) if f.is_file() else {}
    except (OSError, ValueError) as exc:
        return [("warning", f"Claude Code's settings {f} could not be read ({exc}): its export is not checked")]
    data = data if isinstance(data, dict) else {}
    env = data.get("env") if isinstance(data.get("env"), dict) else {}
    if str(env.get(ENABLE_VAR, "")).strip().lower() not in ("1", "true"):
        return [("OK", f"Claude Code's export is off in {f}: nothing for the collector to refuse")]
    helper = data.get(HELPER_KEY)
    if isinstance(helper, str) and helper.strip():
        return [_helper_line(f, helper, env)]
    endpoint = str(env.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")).strip()
    if endpoint and not loopback_url(endpoint):
        return [("OK", f"Claude Code's export goes off loopback in {f}, not to the collector: nothing for it to "
                       "refuse")]
    if "authorization" in str(env.get("OTEL_EXPORTER_OTLP_HEADERS", "")).lower():
        return [("warning", f"Claude Code's export carries the token in clear in {f} (OTEL_EXPORTER_OTLP_HEADERS): "
                            f"{HELPER_KEY} keeps it in the token file")]
    return [("FAIL", f"the collector requires the token and Claude Code's settings {f} carry no {HELPER_KEY}: its "
                     "export is refused (config.json adapters.claude.telemetry, then install.ps1 -Apply)")]


def _helper_line(f: Path, helper: str, env: dict) -> tuple[str, str]:
    """The line of an export that has an otelHeadersHelper: FAIL when the export cannot take it (grpc, an endpoint
    off loopback), a warning when it runs another command, else OK."""
    errors = helper_errors({k: str(v) for k, v in env.items()})
    if errors:
        return ("FAIL", f"Claude Code's {HELPER_KEY} in {f} goes with an export that cannot take it: "
                        f"{'; '.join(errors)} (config.json adapters.claude.telemetry)")
    if "otel-headers" not in helper:
        return ("warning", f"Claude Code's otelHeadersHelper in {f} runs {helper!r}, not {HELPER}")
    return ("OK", f"Claude Code's export carries the token ({HELPER_KEY} in {f})")


def health(cfg, named: bool = True, out=None, root=None) -> int:
    """``brain health ipc``: the lines above; exit 1 on a FAIL."""
    s = settings(cfg)
    state, what = token_state()
    if state == "OFF" and s["require_token"]:
        state, what = "FAIL", f"{what}; config.json ipc.require_token names {', '.join(s['require_token'])}"
    if not named and state == "OFF":
        return 0   # --all on a machine that never made the token nor asked for it: silent, nothing probed
    mcp = probe_mcp(s["mcp_port"], token=state == "OK")
    lines = [(state, what), mcp, *service_lines(s, root), *export_lines(s)]
    for st, line in lines:
        print(f"{CHECK} {st} {line}" if st != "warning" else f"{CHECK} warning: {line}", file=out, flush=True)
    return 1 if any(st == "FAIL" for st, _ in lines) else 0
