"""The machine's token for the Brain's local services (wi-brain-mcp-server, wi-brain-local-ipc-auth): a service the
Brain starts binds a loopback address and answers only a request that carries this token.

One token per machine, in ``<BRAIN_HOME>/ipc/token`` (``BRAIN_IPC_TOKEN_FILE`` names another file: a container reads
the copy its compose file mounts as a secret). It is made once, by ``brain ipc token --init`` (the owner's gesture:
nothing makes it on its own, and a service refuses to start without it), from 32 random bytes, and it is printed
only by ``brain ipc otel-headers``, for Claude Code's otelHeadersHelper: a client reads the file, or takes it from
an environment variable its own configuration fills from the file. A request carries it as ``Authorization: Bearer <token>``; the comparison takes constant time.

Loopback: 127.0.0.0/8, ::1 and the name ``localhost``. A service refuses to bind any other address, and refuses a
request whose ``Host`` or ``Origin`` names another host (a page in a browser cannot reach it through DNS rebinding).
"""

from __future__ import annotations

import hmac
import ipaddress
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from . import paths

ENV = "BRAIN_IPC_TOKEN_FILE"
MIN_LENGTH = 32          # characters: a shorter file is no token (a truncated copy, a placeholder)
LOOPBACK_NAMES = {"localhost"}


class TokenError(Exception):
    """The token is missing or unusable; the message names the fix."""


def token_file() -> Path:
    """Where the machine's token is: $BRAIN_IPC_TOKEN_FILE, else <BRAIN_HOME>/ipc/token."""
    env = os.environ.get(ENV, "").strip()
    return Path(env).expanduser() if env else paths.brain_home() / "ipc" / "token"


def read() -> str | None:
    """The token, or None when the file is missing or holds no usable token."""
    try:
        text = token_file().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text if len(text) >= MIN_LENGTH and text.isascii() and " " not in text else None


def require() -> str:
    """The token, else TokenError naming the command that makes it: a service never starts unauthenticated."""
    tok = read()
    if tok is None:
        raise TokenError(f"no usable token in {token_file()}: the owner makes it with brain ipc token --init")
    return tok


def init() -> tuple[Path, bool]:
    """Make the token when there is none: (its file, True when made now). An existing usable token is kept (a
    rotation is a deletion then --init, so that every client is updated knowingly)."""
    f = token_file()
    if read() is not None:
        return f, False
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + ".new")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(secrets.token_urlsafe(32) + "\n")
    os.replace(tmp, f)
    return f, True


def authorized(header: str | None, token: str) -> bool:
    """Whether an Authorization header carries ``token`` as a bearer token (constant-time comparison)."""
    if not header or not token:
        return False
    scheme, _, value = header.strip().partition(" ")
    if scheme.lower() != "bearer":
        return False
    return hmac.compare_digest(value.strip().encode("utf-8"), token.encode("utf-8"))


def is_loopback(host: str | None) -> bool:
    """Whether a host name or address is this machine's loopback (127.0.0.0/8, ::1, localhost)."""
    if not host:
        return False
    h = host.strip().strip("[]").lower()
    if h in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def host_of(header: str | None) -> str:
    """The host of a Host header (``name``, ``name:port``, ``[::1]:port``)."""
    h = (header or "").strip()
    if h.startswith("["):
        return h[1:h.find("]")] if "]" in h else h
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


def origin_ok(origin: str | None) -> bool:
    """A request's Origin passes when absent (a program, not a page) or naming a loopback host."""
    if origin is None:
        return True
    try:
        return is_loopback(urlsplit(origin.strip()).hostname)
    except ValueError:
        return False
