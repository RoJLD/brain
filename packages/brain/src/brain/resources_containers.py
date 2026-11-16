"""The Brain's containers for brain.resources (wi-brain-resources-view): ``docker stats --no-stream`` with a bounded
timeout, each container tied to the stack that declares it (brain.stacks), its sizes parsed. Docker absent, down, slow
or answering garbage is a state, never an error. Side effects are module functions the tests replace: ``_run``,
``_which``.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

DOCKER_TIMEOUT = 8.0           # docker stats --no-stream takes 1 to 3 s with a handful of containers
TUI_DOCKER_TIMEOUT = 4.0       # the cockpit's detail: a quit never waits longer on docker
UNITS = {"b": 1, "kb": 1e3, "mb": 1e6, "gb": 1e9, "tb": 1e12, "kib": 2 ** 10, "mib": 2 ** 20, "gib": 2 ** 30,
         "tib": 2 ** 40}
SIZE_RE = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*([kmgt]?i?b)\s*$", re.I)

_which = shutil.which


def _run(argv: list[str], timeout: float) -> tuple[str, int | None, str]:
    """(state, exit code, output): state ``ok`` (it ran, whatever its code), ``slow`` (killed at ``timeout``) or
    ``absent`` (it could not start)."""
    try:
        p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return "slow", None, ""
    except (OSError, subprocess.SubprocessError):
        return "absent", None, ""
    return "ok", p.returncode, (p.stdout or "") + (p.stderr or "")


def parse_size(text: str) -> int | None:
    """docker stats' sizes: ``75.63MiB``, ``1.06MB``, ``0B``; None for ``--`` or garbage."""
    m = SIZE_RE.match(text or "")
    return int(float(m.group(1)) * UNITS[m.group(2).lower()]) if m else None


def _pair(text: str) -> tuple[int | None, int | None]:
    a, _, b = (text or "").partition("/")
    return parse_size(a), parse_size(b)


def _pct(text: str) -> float | None:
    try:
        return round(float((text or "").strip().rstrip("%")), 2)
    except ValueError:
        return None


# --- the containers ------------------------------------------------------------------------------------------------

COMPOSE_FILES = ("compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml")


def _option(argv: list[str], names: tuple[str, ...]) -> list[str]:
    """The values of an option given as ``-x V``, ``--long V`` or ``--long=V``."""
    out = []
    for i, a in enumerate(argv):
        if a in names and i + 1 < len(argv):
            out.append(argv[i + 1])
        elif any(a.startswith(n + "=") for n in names if n.startswith("--")):
            out.append(a.split("=", 1)[1])
    return out


def _compose_project(s) -> str:
    """The Compose project of a stack whose start runs ``docker compose ... up`` (brain.stacks): its ``-p``, its
    compose files' ``name:`` (``-f``, else the default names, in its folder), else its folder's name; '' for a stack
    that does not run Compose, or one without a folder and a ``-p``."""
    from . import stacks
    argv = stacks._compose(s)
    if argv is None:
        return ""
    named = _option(argv, ("-p", "--project-name"))
    if named:
        return named[-1].lower()
    if s.cwd is None:
        return ""
    for name in _option(argv, ("-f", "--file")) or COMPOSE_FILES:
        try:
            m = re.search(r"^name:\s*['\"]?([A-Za-z0-9_.-]+)", (s.cwd / name).read_text(encoding="utf-8"), re.M)
        except OSError:
            continue
        if m:
            return m.group(1).lower()
    return re.sub(r"[^a-z0-9_-]", "", s.cwd.name.lower())


def owner_of(name: str, stacks_: list) -> tuple[str, str]:
    """(stack, project) that declares the container ``name``: its ``index.container``, a bundle component's
    ``<project>-<service>-N``, a Compose stack's ``<project>-...``; ('', '') when none does."""
    low = name.lower()
    for s in stacks_:
        if str((s.index or {}).get("container") or "").lower() == low:
            return s.name, s.project
    projects_ = [(s, _compose_project(s)) for s in stacks_]
    for s, p in projects_:
        if s.bundle and p and re.fullmatch(rf"{re.escape(p)}[-_]{re.escape(s.name)}[-_]\d+", low):
            return s.name, s.project
    for s, p in projects_:
        if not s.bundle and p and (low == p or low.startswith((p + "-", p + "_"))):
            return s.name, s.project
    return "", ""


def parse_stats(text: str, stacks_: list | None = None) -> tuple[list[dict], int]:
    """docker stats' ``{{json .}}`` lines: (rows, lines that were not a container's)."""
    rows, bad = [], 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if not isinstance(d, dict) or not isinstance(d.get("Name"), str) or not d.get("Name"):
            bad += 1
            continue
        mem, limit = _pair(str(d.get("MemUsage") or ""))
        rx, tx = _pair(str(d.get("NetIO") or ""))
        rd, wr = _pair(str(d.get("BlockIO") or ""))
        stack, project = owner_of(d["Name"], stacks_ or [])
        pids = str(d.get("PIDs") or "")
        rows.append({"name": d["Name"], "id": str(d.get("ID") or "")[:12], "cpu_pct": _pct(str(d.get("CPUPerc"))),
                     "mem_bytes": mem, "mem_limit_bytes": limit, "mem_pct": _pct(str(d.get("MemPerc"))),
                     "net_rx_bytes": rx, "net_tx_bytes": tx, "block_read_bytes": rd, "block_write_bytes": wr,
                     "pids": int(pids) if pids.isdigit() else None, "stack": stack, "project": project})
    return rows, bad


def containers(stacks_: list | None = None, timeout: float = DOCKER_TIMEOUT) -> dict:
    """{state, why, rows}: ``ok``; ``absent`` (no docker client); ``down`` (the client answers, the engine does
    not); ``slow`` (no answer in ``timeout`` s); ``garbage`` (an answer that holds no container). Never raises."""
    exe = _which("docker")
    if not exe:
        return {"state": "absent", "why": "no docker client on the PATH", "rows": []}
    state, code, out = _run([exe, "stats", "--no-stream", "--format", "{{json .}}"], timeout)
    if state == "slow":
        return {"state": "slow", "why": f"docker stats gave no answer in {timeout:g} s", "rows": []}
    if state == "absent":
        return {"state": "absent", "why": "the docker client could not start", "rows": []}
    if code != 0:
        first = next((ln.strip() for ln in out.splitlines() if ln.strip()), f"exit {code}")
        return {"state": "down", "why": f"the Docker engine does not answer: {first[:200]}", "rows": []}
    rows, bad = parse_stats(out, stacks_)
    if bad and not rows:
        return {"state": "garbage", "why": f"docker stats answered {bad} line(s) that are no container's", "rows": []}
    return {"state": "ok", "why": f"{bad} line(s) skipped" if bad else "", "rows": rows}
