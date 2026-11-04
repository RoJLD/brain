"""Stacks started by commands, not prompts (spec 2026-11-01 §11, the owner's decision under it): a declarative registry
and ``brain up / down / health``, one status line per stack, at zero token for the model.

Each project of projects.yaml may declare its stacks under ``stacks:``, inline or as a YAML file relative to the
project's root. Stack names are global: ``depends_on`` may name another project's stack (the Docker engine)::

  quant:
    root: ../demo
    stacks:
      gitnexus:
        depends_on: [docker]
        cwd: ../GitNexus                  # relative to the project's root (default: the root)
        start: [docker, compose, up, -d]  # argv; a string is split like a POSIX shell would (write Windows paths
        stop: [docker, compose, stop]     # as a list)
        health: {urls: [http://localhost:4747/api/health], cmd: [docker, info]}   # every check must pass
        logs: [docker, compose, logs, --tail, '30']   # where a failure's useful line is looked for
        timeout: 120      # seconds to wait for health after the start (default 120)
        detach: false     # true: the start command keeps running (a desktop app): launched, not waited for
        watch: false      # true: the SessionStart hook reports it when it is down (on demand: false)
        placement: local  # where it runs; or {run: local, data: volume|home} (data: a bundle component's, below)
        index: {api: 'http://127.0.0.1:4747', container: gitnexus}   # the stack brain index uses (brain.codeindex)
        class: service    # its tier (brain.tiers): class, profile, provides, requires, resources, fallback and,
        profile: recommended   # for recommended, recommend_when; brain check --all refuses a stack without them
        provides: [code graph]
        requires: [docker]
        resources: {ram_mb: 300, disk_gb: 3}
        fallback: the CodeRefs checked by the AST, and git grep
        recommend_when: [memory_gb >= 7]

``brain up`` starts the named stacks (every one without names) after their dependencies, waits for each health check
(bounded by its timeout) and prints one line per stack; a healthy stack is not touched, unless it is named with
``--force``: its start command then runs again. A Compose stack (its start command is ``docker compose ... up``) runs
its start command even when healthy, since ``docker compose up -d`` recreates only the containers whose configuration
changed: a changed compose file is applied, not left to the restart policy's old containers. ``brain down`` runs the stop
commands of the named stacks (every one without names) in reverse dependency order; a stack without a stop command,
or whose dependency is down, is left alone. ``brain health`` checks the named stacks, the watched ones without names,
every one with ``--all``, and starts nothing; a healthy Compose stack whose containers differ from the compose file
(the ``com.docker.compose.config-hash`` label of each container against ``docker compose config --hash '*'``, no
network) is reported STALE; a stack outside this machine's profile (brain.tiers: brain profile) that is not up is
reported OFF, never as a failure. Exit code 1 when a stack fails, is down or is stale, 2 for a registry error.

A bundle component (``bundle: sovereign``) is a service of a Compose bundle the engine ships (brain.bundles): its
commands are ``docker compose up -d / stop / logs <its name>`` in ``<BRAIN_HOME>/stacks/<bundle>``, where ``brain bundle
apply`` renders the bundle, so it declares no cwd, start, stop or logs. Until that apply, ``brain up`` skips it and
``brain health`` reports it not applied. A bundle's name stands for its components in ``brain up / down / health``.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import graph, paths, projects

KEYS = {"depends_on", "cwd", "start", "stop", "health", "logs", "timeout", "detach", "watch", "placement", "index",
        "bundle"}
TIER_KEYS = {"class", "profile", "provides", "requires", "resources", "fallback", "recommend_when"}  # brain.tiers
PLACEMENTS = {"local"}       # where a stack runs; ssh://HOST, k8s://CONTEXT and node:NAME are planned
DATA = {"volume", "home"}    # where a bundle component's data lives: a Docker named volume, or under BRAIN_HOME
PLANNED = re.compile(r"^(ssh://|k8s://|node:|nas:)\S+$")
BUNDLE_FILE = "compose.yaml"  # what brain bundle apply renders into <BRAIN_HOME>/stacks/<bundle>
RESERVED = {"code-index"}  # brain health code-index checks the code index (brain.codeindex), not a stack
NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
USEFUL = re.compile(r"error|fail|fatal|panic|exception|refused|denied|cannot|unable", re.I)
URL_TIMEOUT, CMD_TIMEOUT, LOG_TIMEOUT = 3.0, 15.0, 15.0
HOOK_BUDGET, HOOK_URL_TIMEOUT, HOOK_CMD_TIMEOUT = 1.5, 0.5, 1.0
POLL = 1.0


class StackError(Exception):
    """A registry error: unknown stack, bad declaration, dependency cycle (exit code 2)."""


@dataclass
class Stack:
    name: str
    project: str
    start: list[str]
    health_urls: list[str] = field(default_factory=list)
    health_cmd: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    stop: list[str] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    cwd: Path | None = None
    timeout: float = 120.0
    detach: bool = False
    watch: bool = False
    placement: str = "local"
    index: dict = field(default_factory=dict)
    tier: dict = field(default_factory=dict)   # its tier keys, checked by brain.tiers (brain check --all)
    bundle: str = ""                           # the Compose bundle it is a service of (brain.bundles)
    data: str = "volume"                       # where its data lives (placement.data): volume or home


# Side effects, replaced by fakes in the tests.

def _probe_url(url: str, timeout: float) -> str:
    """'' when ``url`` answers below 400 within ``timeout``, else why not. No proxy: the stacks are local."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=timeout) as r:
            return "" if r.status < 400 else f"HTTP {r.status}"
    except urllib.error.HTTPError as exc:
        return f"HTTP {exc.code}"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        return str(reason) or type(reason).__name__


def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run(argv: list[str], cwd: Path | None, timeout: float) -> tuple[int | None, str]:
    """(exit code, stdout and stderr) of ``argv``; exit code None when it did not finish within ``timeout``."""
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, stdin=subprocess.DEVNULL, creationflags=_no_window())
    except subprocess.TimeoutExpired:
        return None, ""
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _spawn(argv: list[str], cwd: Path | None) -> None:
    """Launch ``argv`` detached from this process (a desktop app that keeps running), its output discarded."""
    kw: dict = {"start_new_session": True}
    if os.name == "nt":
        kw = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
    subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     close_fds=True, **kw)


_clock = time.monotonic
_sleep = time.sleep


# The registry.

def _argv(value, where: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return shlex.split(value)
    if isinstance(value, list) and value and all(isinstance(v, (str, int, float)) for v in value):
        return [str(v) for v in value]
    raise StackError(f"{where}: a command is a list of arguments or a string")


def _stack(name: str, project: projects.Project, decl) -> Stack:
    where = f"stack {name!r} ({project.name})"
    if not NAME.match(name):
        raise StackError(f"{where}: a name is lowercase letters, digits, '.', '_' and '-'")
    if name in RESERVED:
        raise StackError(f"{where}: the name is reserved (brain health {name})")
    if not isinstance(decl, dict):
        raise StackError(f"{where}: a stack is a mapping")
    if not isinstance(decl.get("index") or {}, dict):
        raise StackError(f"{where}: index is a mapping (api, container...)")
    unknown = set(decl) - KEYS - TIER_KEYS
    if unknown:
        raise StackError(f"{where}: unknown key(s) {', '.join(sorted(unknown))} "
                         f"(known: {', '.join(sorted(KEYS | TIER_KEYS))})")
    health = decl.get("health") or {}
    if not isinstance(health, dict) or set(health) - {"urls", "cmd"}:
        raise StackError(f"{where}: health is a mapping of urls and/or cmd")
    urls = health.get("urls") or []
    urls = [urls] if isinstance(urls, str) else [str(u) for u in urls]
    bundle = str(decl.get("bundle") or "")
    if bundle:  # a service of a rendered Compose bundle: its commands are the bundle's
        own = sorted({"cwd", "start", "stop", "logs", "detach"} & set(decl))
        if own or not NAME.match(bundle):
            raise StackError(f"{where}: a bundle component takes its commands from its bundle ("
                             + (f"no {', '.join(own)})" if own else f"bad bundle name {bundle!r})"))
        compose = ["docker", "compose"]
        decl = {**decl, "start": [*compose, "up", "-d", name], "stop": [*compose, "stop", name],
                "logs": [*compose, "logs", "--tail", "30", name]}
    run, data = _placement(decl.get("placement"), where)
    s = Stack(name, project.name, _argv(decl.get("start"), f"{where} start"), urls,
              _argv(health.get("cmd"), f"{where} health.cmd"), [str(d) for d in decl.get("depends_on") or []],
              _argv(decl.get("stop"), f"{where} stop"), _argv(decl.get("logs"), f"{where} logs"),
              paths.brain_home() / "stacks" / bundle if bundle else
              Path(os.path.normpath(project.root / decl["cwd"])) if decl.get("cwd") else project.root,
              float(decl.get("timeout", 120)), bool(decl.get("detach", False)), bool(decl.get("watch", False)),
              run, dict(decl.get("index") or {}), {k: v for k, v in decl.items() if k in TIER_KEYS}, bundle, data)
    if not s.start:
        raise StackError(f"{where}: no start command")
    if not (s.health_urls or s.health_cmd):
        raise StackError(f"{where}: no health check (health.urls or health.cmd)")
    return s


def _placement(value, where: str) -> tuple[str, str]:
    """(run, data) of a placement: a string says where the stack runs, {run, data} also where its data lives."""
    if isinstance(value, dict):
        if set(value) - {"run", "data"}:
            raise StackError(f"{where}: placement is a string or a mapping of run and data")
        run, data = str(value.get("run", "local")), str(value.get("data", "volume"))
    else:
        run, data = str(value or "local"), "volume"
    for key, v, known in (("placement", run, PLACEMENTS), ("placement data", data, DATA)):
        if v not in known:
            planned = " (planned: wi-brain-stack-placement)" if PLANNED.match(v) else ""
            raise StackError(f"{where}: {key} {v!r} is not supported (only: {', '.join(sorted(known))}){planned}")
    return run, data


def applied(s: Stack) -> bool:
    """False for a bundle component whose bundle brain bundle apply has not rendered yet."""
    return not s.bundle or (s.cwd / BUNDLE_FILE).is_file()


def not_applied(s: Stack) -> str:
    return f"bundle {s.bundle} not applied (brain bundle plan {s.bundle}, then brain bundle apply {s.bundle})"


def load(root: Path | None = None) -> dict[str, Stack]:
    """Every stack of the registry's projects, in declaration order; a project whose stacks file is in a root not on
    this machine is left out (:func:`uncloned`)."""
    out: dict[str, Stack] = {}
    for p in projects.load(root).values():
        decl = p.stacks
        if isinstance(decl, str) and not p.root.is_dir():   # a project cloned elsewhere: its stacks are not run here
            continue
        if isinstance(decl, str):
            f = p.root / decl
            if not f.is_file():
                raise StackError(f"project {p.name}: stacks file {f} not found")
            decl = graph.load_yaml_file(f) or {}
        if not isinstance(decl or {}, dict):
            raise StackError(f"project {p.name}: stacks is a mapping or a file name")
        for name, d in (decl or {}).items():
            if str(name) in out:
                raise StackError(f"stack {name!r} is declared by {out[str(name)].project} and {p.name}")
            out[str(name)] = _stack(str(name), p, d)
    return out


def uncloned(root: Path | None = None) -> list[str]:
    """The projects whose stacks file sits in a root this machine does not hold: :func:`load` leaves them out."""
    return [p.name for p in projects.load(root).values() if isinstance(p.stacks, str) and not p.root.is_dir()]


def plan(reg: dict[str, Stack], names: list[str]) -> list[Stack]:
    """``names`` (every stack when empty) and their dependencies, dependencies first."""
    unknown = [n for n in names if n not in reg]
    if unknown:
        raise StackError(f"unknown stack(s) {', '.join(unknown)} (declared: {', '.join(reg) or 'none'})")
    order: list[Stack] = []
    state: dict[str, int] = {}

    def visit(n: str, path: list[str]) -> None:
        if state.get(n) == 2:
            return
        if state.get(n) == 1:
            raise StackError(f"dependency cycle: {' -> '.join(path + [n])}")
        if n not in reg:
            raise StackError(f"stack {path[-1]!r} depends on unknown stack {n!r}")
        state[n] = 1
        for d in reg[n].depends_on:
            visit(d, path + [n])
        state[n] = 2
        order.append(reg[n])

    for n in names or list(reg):
        visit(n, [])
    return order


# Checks and commands.

def useful_line(text: str) -> str:
    """The line of a command's output worth reading: the last that looks like an error, else the last one."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    hits = [ln for ln in lines if USEFUL.search(ln)]
    line = (hits or lines or [""])[-1]
    return line if len(line) <= 200 else line[:197] + "..."


def _resolve(argv: list[str]) -> list[str] | None:
    exe = shutil.which(argv[0])
    return [exe, *argv[1:]] if exe else None


def check(s: Stack, url_timeout: float = URL_TIMEOUT, cmd_timeout: float = CMD_TIMEOUT) -> str:
    """'' when every health check of ``s`` passes, else the first failure."""
    if not applied(s):
        return not_applied(s)
    for url in s.health_urls:
        why = _probe_url(url, url_timeout)
        if why:
            return f"{url}: {why}"
    if s.health_cmd:
        argv = _resolve(s.health_cmd)
        if not argv:
            return f"{s.health_cmd[0]} not found"
        code, out = _run(argv, s.cwd, cmd_timeout)
        if code is None:
            return f"{' '.join(s.health_cmd)}: no answer in {cmd_timeout:g} s"
        if code:
            return f"{' '.join(s.health_cmd)} exited {code}" + (f": {useful_line(out)}" if out.strip() else "")
    return ""


def _log_line(s: Stack) -> str:
    if not s.logs:
        return ""
    argv = _resolve(s.logs)
    if not argv:
        return ""
    _, out = _run(argv, s.cwd, LOG_TIMEOUT)
    line = useful_line(out)
    return f" | log: {line}" if line else ""


def _start(s: Stack, deadline: float) -> str:
    """Run the start command: '' when it ran, else why not."""
    argv = _resolve(s.start)
    if not argv:
        return f"start command not found: {s.start[0]}"
    if s.detach:
        try:
            _spawn(argv, s.cwd)
        except OSError as exc:
            return f"start failed: {exc}"
        return ""
    code, out = _run(argv, s.cwd, max(deadline - _clock(), 1.0))
    if code is None:
        return f"start did not finish in {s.timeout:g} s"
    if code:
        line = useful_line(out)
        return f"start exited {code}" + (f": {line}" if line else "")
    return ""


def _compose(s: Stack) -> list[str] | None:
    """The ``docker compose`` argv with its global options (``-f``, ``-p``...) when ``s`` starts with ``docker compose
    ... up``, else None."""
    a = s.start
    if len(a) >= 3 and Path(a[0]).stem.lower() == "docker" and a[1] == "compose" and "up" in a[2:]:
        return a[:a.index("up", 2)]
    return None


def _hashes(text: str) -> dict[str, str]:
    return dict(ln.split(None, 1) for ln in text.splitlines() if len(ln.split()) == 2)


def drift(s: Stack, cmd_timeout: float = CMD_TIMEOUT) -> str:
    """Why the containers of a Compose stack differ from its compose file, else '' (also when it is not a Compose
    stack or Compose cannot tell)."""
    base = _compose(s)
    argv = _resolve(base) if base else None
    if not argv:
        return ""
    code, out = _run([*argv, "config", "--hash", "*"], s.cwd, cmd_timeout)
    want = _hashes(out) if code == 0 else {}
    mine = [a for a in s.start[s.start.index("up", 2) + 1:] if not a.startswith("-")]
    if mine:  # a stack that names its services (a bundle component): the others are other stacks'
        want = {n: h for n, h in want.items() if n in mine}
    code, out = _run([*argv, "ps", "-a", "--format", '{{.Service}} {{.Label "com.docker.compose.config-hash"}}'],
                     s.cwd, cmd_timeout)
    if not want or code != 0:
        return ""
    have = _hashes(out)
    changed = sorted(n for n in want if have.get(n) != want[n])
    return (f"{', '.join(changed)} differ{'s' if len(changed) == 1 else ''} from the compose file; "
            f"brain up {s.name} applies it") if changed else ""


def _secs(t0: float) -> str:
    return f"{round(_clock() - t0)} s"


def up(reg: dict[str, Stack], names: list[str], out=None, force: bool = False) -> int:
    out = out or sys.stdout
    failed: set[str] = set()
    unapplied: set[str] = set()  # skipped, a failure only when named
    for s in plan(reg, names):
        if not applied(s):
            print(f"{s.name} SKIPPED ({not_applied(s)})", file=out, flush=True)
            (failed if s.name in names else unapplied).add(s.name)
            continue
        blocked = [d for d in s.depends_on if d in failed or d in unapplied]
        if blocked:
            print(f"{s.name} SKIPPED ({', '.join(blocked)} failed)", file=out, flush=True)
            failed.add(s.name)
            continue
        healthy = not check(s)
        if healthy and not (force and s.name in names) and not _compose(s):
            print(f"{s.name} OK (already up)", file=out, flush=True)
            continue
        t0 = _clock()
        deadline = t0 + s.timeout
        why = _start(s, deadline)
        if not why:
            why = check(s)
            while why and _clock() < deadline:
                _sleep(POLL)
                why = check(s)
            if why:
                why = f"not healthy after {s.timeout:g} s: {why}{_log_line(s)}"
        if why:
            print(f"{s.name} FAILED ({_secs(t0)}): {why}", file=out, flush=True)
            failed.add(s.name)
        else:
            print(f"{s.name} OK ({_secs(t0)}{', compose file applied' if healthy and _compose(s) else ''})", file=out, flush=True)
    return 1 if failed else 0


def down(reg: dict[str, Stack], names: list[str], out=None) -> int:
    out = out or sys.stdout
    chosen = set(names or reg)
    rc = 0
    for s in reversed([s for s in plan(reg, names) if s.name in chosen]):
        if not s.stop or not applied(s):
            print(f"{s.name} left alone ({not_applied(s) if s.stop else 'no stop command'})", file=out, flush=True)
            continue
        dead = [d for d in s.depends_on if d in reg and check(reg[d])]
        if dead:
            print(f"{s.name} down ({', '.join(dead)} is down)", file=out, flush=True)
            continue
        t0 = _clock()
        argv = _resolve(s.stop)
        code, text = _run(argv, s.cwd, s.timeout) if argv else (127, f"{s.stop[0]} not found")
        if code == 0:
            print(f"{s.name} stopped ({_secs(t0)})", file=out, flush=True)
            continue
        why = f"stop did not finish in {s.timeout:g} s" if code is None else f"stop exited {code}"
        line = useful_line(text)
        print(f"{s.name} FAILED ({_secs(t0)}): {why}" + (f": {line}" if line else ""), file=out, flush=True)
        rc = 1
    return rc


def profile_off(reg: dict[str, Stack], root: Path | None = None) -> dict[str, str]:
    """{stack: why} for the stacks outside this machine's profile (brain.tiers); {} when it cannot tell."""
    from . import tiers
    return tiers.outside(root, reg)


def health(reg: dict[str, Stack], names: list[str], every: bool = False, out=None, root: Path | None = None) -> int:
    out = out or sys.stdout
    if names:
        plan(reg, names)  # unknown names are an error
        chosen = [reg[n] for n in names]
    else:
        chosen = [s for s in reg.values() if every or s.watch]
    if not chosen:
        print(f"no watched stack; brain health --all checks the {len(reg)} declared"
              + (f" ({', '.join(reg)})" if reg else ""), file=out)
        return 0
    rc = 0
    off = profile_off(reg, root)
    for s in chosen:
        st, why = state(s, off.get(s.name, ""))
        print(f"{s.name} {st}: {why}" if why else f"{s.name} {st}", file=out, flush=True)
        rc = rc or (0 if st in ("OK", "OFF") else 1)
    return rc


def state(s: Stack, off: str = "") -> tuple[str, str]:
    """OK, DOWN, STALE (a Compose stack whose containers differ from its compose file) or OFF (not up, and outside
    this machine's profile: ``off`` says why), and why: the line brain health prints, which brain status reads too."""
    why = check(s)
    if why:
        return ("OFF", off) if off else ("DOWN", why)
    stale = drift(s)
    return ("STALE", stale) if stale else ("OK", "")


def expand(reg: dict[str, Stack], names: list[str]) -> list[str]:
    """``names`` with each bundle's name replaced by its components (a stack's own name wins)."""
    out: list[str] = []
    for n in names:
        mine = [] if n in reg else [c for c, s in reg.items() if s.bundle == n]
        out += [c for c in mine or [n] if c not in out]
    return out


def of_project(reg: dict[str, Stack], project: str, names: list[str]) -> list[str]:
    """``names``, each one ``project``'s, or every stack ``project`` declares when none is named (``--project``)."""
    mine = [n for n, s in reg.items() if s.project == project]
    other = [n for n in names if n not in mine]
    if other:
        raise StackError(f"{', '.join(other)}: not a stack of {project} (it declares {', '.join(mine) or 'none'})")
    return list(names) or mine


def main(cmd: str, names: list[str], every: bool = False, root: Path | None = None, force: bool = False,
         project: str | None = None) -> int:
    """``brain up / down / health``; ``project`` (``--project``) narrows them to its stacks, every one of them when
    none is named (their dependencies still start first)."""
    try:
        reg = load(root)
        names = expand(reg, names)
        if project:
            names = of_project(reg, project, names)
            if not names:
                print(f"no stack declared by {project}")
                return 0
        if cmd == "up":
            return up(reg, names, force=force)
        if cmd == "down":
            return down(reg, names)
        return health(reg, names, every, root=root)
    except StackError as exc:
        print(f"brain {cmd}: {exc}", file=sys.stderr)
        return 2


# The SessionStart hook: the watched stacks that are down, within a fixed budget, and a silent alerts pass (the
# dead-man of brain.schedule); silent when all is well.

def watched_down(reg: dict[str, Stack], budget: float = HOOK_BUDGET) -> list[str]:
    end = _clock() + budget
    rows = []
    off = profile_off(reg) if any(s.watch for s in reg.values()) else {}
    for s in (s for s in reg.values() if s.watch and s.name not in off):
        left = end - _clock()
        if left <= 0:
            break
        why = check(s, min(HOOK_URL_TIMEOUT, left), min(HOOK_CMD_TIMEOUT, left))
        if why:
            rows.append(f"- {s.name} ({s.project}): {why}")
    return rows


def hook_main(argv: list[str], stdin=None) -> int:
    """SessionStart hook: the down watched stacks as additionalContext; nothing when all is well. Never fails: an
    error goes to <BRAIN_HOME>/ledger/errors.log."""
    try:
        # the hook's JSON, as bytes (a codepage decode can fail): nothing in it is needed
        stdin.read() if stdin is not None else getattr(sys.stdin, "buffer", sys.stdin).read()
        from .capture import _log_error
        parts = []
        try:
            rows = watched_down(load())
            if rows:
                names = " ".join(r[2:].split(" ", 1)[0] for r in rows)
                parts.append(f"{len(rows)} watched stack(s) down. `brain up {names}` starts them (allowed without a "
                             "prompt); `brain health --all` shows every stack.\n" + "\n".join(rows))
        except Exception as exc:  # noqa: BLE001 - one report's error never drops the other
            _log_error("stacks-health", exc)
        try:
            from . import projects, schedule
            silent = schedule.hook_line(projects.load())
            if silent:
                parts.append(silent)
        except Exception as exc:  # noqa: BLE001
            _log_error("alerts-dead-man", exc)
        if parts:
            text = "\n".join(parts)
            event = argv[0] if argv else "SessionStart"
            print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}},
                             ensure_ascii=True))
    except BaseException as exc:  # noqa: BLE001 - a hook never breaks a session start, SystemExit included
        from .capture import _log_error
        _log_error("stacks-health", exc)
    return 0
