"""Compose bundles the engine ships, rendered and run by commands (wi-brain-sovereign-stack).

A bundle is a Compose project under ``compose/<bundle>/`` next to this module: its ``compose.yaml`` and the
configuration files its services mount. ``brain bundle apply`` renders it into ``<BRAIN_HOME>/stacks/<bundle>/`` and
starts its components. Each component is a stack of projects.yaml (brain.stacks) named after its service, with
``bundle: <bundle>``, so ``brain up / down / health`` run and check it like any other stack. The one bundle today is
``sovereign``: an OpenTelemetry collector, Prometheus, Loki, Grafana and Qdrant.

The rendering keeps the template, except, per component, where its data lives (its stack's ``placement.data``):
  volume   its Docker named volume (the default): the data stays in the container engine, safe for a database
  home     ./data/<volume>, a folder under BRAIN_HOME: files the host reads (the collector's JSONL, for DuckDB)
and each secret's ``file``, pointed at ``$BRAIN_SECRET_<NAME>`` (a path) or ``<BRAIN_HOME>/secrets/<name>`` (``_`` as
``-``), a file the owner fills. Nothing here reads, writes or generates a secret: it only checks that the file is there.
A component config.json ``ipc.require_token`` names (the collector, opt-in) also gets the machine's token file
(brain.ipcauth) as a secret, and its configuration checks it on every receiver (:func:`collector_auth`).

``brain bundle plan [BUNDLE]...`` writes nothing and starts nothing. It checks every published port (127.0.0.1 only),
every image (pinned by tag and digest), the services against the components, and ``docker compose config`` on the
rendering; then it says which files it would write (new, changed, unchanged), the folders it would create, the images
to pull, and what the apply would do with each component, from its state; a component whose secret file is missing
waits for the owner. ``brain bundle apply [BUNDLE]...`` does it: the files and folders, the dependencies outside the
bundle (Docker) started, the missing images pulled, then ``brain up`` of the components that do not wait. A second
apply writes nothing and recreates nothing. Exit code 1 when a check fails (nothing is applied) or a component does not
get healthy, 2 for a registry error.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import graph, paths, stacks

ROOT = Path(__file__).with_name("compose")
LOOPBACK = "127.0.0.1"
PINNED = re.compile(r"^[a-z0-9][a-z0-9._/-]*:(?!latest@)[A-Za-z0-9_][A-Za-z0-9._-]*@sha256:[0-9a-f]{64}$")
PULL_TIMEOUT = 1800.0  # the first pull of the sovereign bundle is about 1.5 GB
PORT_TIMEOUT = 0.3
HEADER = ("# Rendered by brain bundle apply from the engine's compose/{bundle}/compose.yaml: edit the template, then\n"
          "# brain bundle plan / apply. Data where each component's placement says; secrets read from the files named.\n")


class BundleError(Exception):
    """An unknown bundle or an unreadable template (exit code 2)."""


@dataclass
class Plan:
    bundle: str
    target: Path
    rendered: dict[str, bytes] = field(repr=False)
    files: dict[str, str] = field(default_factory=dict)    # path -> new, changed or unchanged
    folders: list[str] = field(default_factory=list)       # to create (placement data home)
    volumes: list[str] = field(default_factory=list)       # Docker named volumes in use
    images: dict[str, bool | None] = field(default_factory=dict)   # present here (None: Docker cannot tell)
    pull: list[str] = field(default_factory=list)          # the services whose image the apply pulls first
    secrets: dict[str, str] = field(default_factory=dict)  # secret -> its file
    waiting: dict[str, str] = field(default_factory=dict)  # component -> what it waits for
    rows: list[dict] = field(default_factory=list)         # component, state, why, action
    checks: list[str] = field(default_factory=list)        # what passed
    problems: list[str] = field(default_factory=list)      # what blocks the apply
    notes: list[str] = field(default_factory=list)


def names() -> list[str]:
    return sorted(d.name for d in ROOT.iterdir() if (d / stacks.BUNDLE_FILE).is_file()) if ROOT.is_dir() else []


def target(bundle: str) -> Path:
    return paths.brain_home() / "stacks" / bundle


def components(reg: dict[str, stacks.Stack], bundle: str) -> list[stacks.Stack]:
    return [s for s in reg.values() if s.bundle == bundle]


def secret_file(name: str) -> Path:
    env = os.environ.get("BRAIN_SECRET_" + re.sub(r"[^A-Z0-9]", "_", name.upper()))
    return Path(env).expanduser() if env else paths.brain_home() / "secrets" / name.replace("_", "-")


def template(bundle: str) -> dict:
    f = ROOT / bundle / stacks.BUNDLE_FILE
    if bundle not in names():
        raise BundleError(f"unknown bundle {bundle!r} (shipped: {', '.join(names()) or 'none'})")
    doc = graph.load_yaml_file(f)
    if not isinstance(doc, dict) or not isinstance(doc.get("services"), dict):
        raise BundleError(f"{f}: no services")
    return doc


def _dump(doc: dict) -> str:
    y = graph._yaml()

    class Dumper(y.SafeDumper):  # the template's anchors written out in full
        def ignore_aliases(self, data):
            return True

    return y.dump(doc, Dumper=Dumper, sort_keys=False, default_flow_style=False, allow_unicode=True, width=120)


def render(bundle: str, comps: list[stacks.Stack]) -> tuple[dict, dict[str, bytes]]:
    """(the rendered compose document, {relative path: content}) of ``bundle`` for these components."""
    doc = template(bundle)
    data = {s.name: s.data for s in comps}
    declared = doc.get("volumes") or {}
    used: set[str] = set()
    for name, svc in doc["services"].items():
        vols = []
        for v in (svc or {}).get("volumes") or []:
            vol = v.split(":", 1)[0] if isinstance(v, str) else ""
            if vol in declared and data.get(name) == "home":
                v = f"./data/{vol}{v[len(vol):]}"
            elif vol in declared:
                used.add(vol)
            vols.append(v)
        if vols:
            svc["volumes"] = vols
    if "volumes" in doc:
        doc["volumes"] = {k: v for k, v in declared.items() if k in used}
        if not doc["volumes"]:
            del doc["volumes"]
    for sname, sec in (doc.get("secrets") or {}).items():
        if isinstance(sec, dict) and "file" in sec:
            sec["file"] = secret_file(str(sname)).as_posix()
    tokened = [n for n in require_token() if n in doc["services"] and n in TOKEN_CONFIGS]
    for name in tokened:   # the machine's token mounted as a secret (brain.ipcauth); config.json ipc.require_token
        svc = doc["services"][name]
        svc["secrets"] = [*(svc.get("secrets") or []), TOKEN_SECRET]
    if tokened:
        from . import ipcauth
        doc.setdefault("secrets", {})[TOKEN_SECRET] = {"file": ipcauth.token_file().as_posix()}
    files = {stacks.BUNDLE_FILE: (HEADER.format(bundle=bundle) + _dump(doc)).encode("utf-8")}
    src = ROOT / bundle
    for f in sorted(src.rglob("*")):
        rel = f.relative_to(src).as_posix()
        if f.is_file() and rel != stacks.BUNDLE_FILE and "__pycache__" not in rel:
            files[rel] = f.read_bytes()
    for name in tokened:
        rel = TOKEN_CONFIGS[name]
        if rel in files:
            files[rel] = collector_auth(files[rel])
    return doc, files


# The machine's token for a component that requires it (wi-brain-local-ipc-auth): opt-in, config.json
# ipc.require_token, because it newly refuses a client that sends none (Claude Code's OTLP export then needs
# its headers: the owner's otelHeadersHelper setting runs brain ipc otel-headers, docs/mcp.md).
TOKEN_SECRET = "brain_ipc_token"
TOKEN_MOUNT = f"/run/secrets/{TOKEN_SECRET}"
TOKEN_CONFIGS = {"otel-collector": "otelcol.yaml"}   # the component and the configuration file that checks it
AUTH_HEADER = ("# Rendered by brain bundle apply with the machine's token required (config.json ipc.require_token):\n"
               "# every OTLP receiver checks Authorization: Bearer against the secret the compose file mounts.\n")


def _token_ok() -> bool:
    """The machine's token is usable (brain.ipcauth's own test: not merely a file that is not empty)."""
    from . import ipcauth
    return ipcauth.read() is not None


def require_token() -> list[str]:
    """config.json ``ipc.require_token``: the components that require the machine's token (none by default)."""
    from . import config, ipchealth
    return ipchealth.settings(config.load())["require_token"]


def collector_auth(text: bytes) -> bytes:
    """The collector's configuration with the bearertokenauth extension on every OTLP receiver, the token read from
    the secret file (otelcol-contrib's bearertokenauth: ``filename``, scheme Bearer)."""
    y = graph._yaml()
    cfg = graph.load_yaml(text.decode("utf-8")) or {}
    cfg.setdefault("extensions", {})["bearertokenauth"] = {"filename": TOKEN_MOUNT}
    for rx in ((cfg.get("receivers") or {}).get("otlp") or {}).get("protocols", {}).values():
        if isinstance(rx, dict):
            rx["auth"] = {"authenticator": "bearertokenauth"}
    service = cfg.setdefault("service", {})
    exts = list(service.get("extensions") or [])
    service["extensions"] = exts + ([] if "bearertokenauth" in exts else ["bearertokenauth"])
    return (AUTH_HEADER + y.safe_dump(cfg, sort_keys=False, default_flow_style=False, width=120)).encode("utf-8")


# The checks.

def _loopback(port) -> bool:
    if isinstance(port, dict):
        return str(port.get("host_ip") or "") == LOOPBACK and bool(port.get("published"))
    parts = str(port).split(":")
    return len(parts) == 3 and parts[0] == LOOPBACK


def host_ports(svc: dict) -> list[int]:
    out = []
    for p in svc.get("ports") or []:
        pub = str(p.get("published") or "") if isinstance(p, dict) else (str(p).split(":") + [""])[1]
        if pub.split("-")[0].isdigit():
            out.append(int(pub.split("-")[0]))
    return out


def problems(bundle: str, doc: dict, comps: list[stacks.Stack]) -> tuple[list[str], list[str]]:
    """(what passed, what blocks the apply) in the rendered document: images pinned, ports on loopback only,
    services and components matching."""
    bad: list[str] = []
    services = doc.get("services") or {}
    images = [str((svc or {}).get("image") or "") for svc in services.values()]
    ports = [p for svc in services.values() for p in (svc or {}).get("ports") or []]
    for name, svc in services.items():
        svc = svc or {}
        img = str(svc.get("image") or "")
        if not PINNED.match(img):
            bad.append(f"{name}: image {img or '(none)'} is not pinned by tag and digest (name:tag@sha256:...)")
        if svc.get("build"):
            bad.append(f"{name}: a bundle runs pinned images, it builds none")
        if str(svc.get("network_mode") or "") == "host":
            bad.append(f"{name}: network_mode host bypasses the loopback binding")
        bad += [f"{name}: port {p} is published beyond {LOOPBACK}" for p in svc.get("ports") or [] if not _loopback(p)]
    have = {s.name for s in comps}
    bad += [f"service {n} has no component: declare the stack {n} with bundle: {bundle} in projects.yaml"
            for n in services if n not in have]
    bad += [f"component {n} has no service {n} in compose/{bundle}/compose.yaml" for n in sorted(have - set(services))]
    ok = [f"{len(images)} images pinned by tag and digest", f"{len(ports)} ports published on {LOOPBACK} only",
          f"{len(services)} services, each a component of projects.yaml"]
    return ([] if bad else ok), bad


def _compose_config(files: dict[str, bytes]) -> tuple[str, str]:
    """(passed, problem) of ``docker compose config --quiet`` on the rendering, in a scratch folder."""
    argv = stacks._resolve(["docker", "compose"])
    if not argv:
        return "", ""
    # docker compose runs from elsewhere (the file given with -f), and the folder goes by shutil.rmtree, errors
    # ignored: a docker compose killed at its timeout may leave a child holding it on Windows, and 3.10's
    # TemporaryDirectory then recursed until RecursionError, ignore_cleanup_errors or not (left to the temp cleaner)
    tmp = Path(tempfile.mkdtemp(prefix="brain-bundle-"))
    try:
        for rel, data in files.items():
            f = tmp / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(data)
        code, out = stacks._run([*argv, "-f", str(tmp / stacks.BUNDLE_FILE), "config", "--quiet"], None,
                                stacks.CMD_TIMEOUT)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if code == 0:
        return "docker compose config OK", ""
    why = "no answer" if code is None else f"exited {code}: {stacks.useful_line(out)}"
    return "", f"docker compose config {why}"


def _image_present(image: str, docker_up: bool) -> bool | None:
    argv = stacks._resolve(["docker", "image", "inspect", "--format", "{{.Id}}", image]) if docker_up else None
    if not argv:
        return None
    code, _ = stacks._run(argv, None, stacks.CMD_TIMEOUT)
    return code == 0


def _listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(PORT_TIMEOUT)
        return s.connect_ex((LOOPBACK, port)) == 0


def _secret_ok(f: Path) -> bool:
    try:
        return f.is_file() and f.stat().st_size > 0
    except OSError:
        return False


# The plan and the apply.

def plan(reg: dict[str, stacks.Stack], bundle: str, root: Path | None = None) -> Plan:
    comps = components(reg, bundle)
    doc, rendered = render(bundle, comps)
    p = Plan(bundle, target(bundle), rendered)
    p.checks, p.problems = problems(bundle, doc, comps)
    passed, bad = _compose_config(rendered)
    p.checks += [passed] if passed else []
    p.problems += [bad] if bad else []
    if not passed and not bad:
        p.notes.append("docker not found: the compose file is not checked")
    for rel, data in rendered.items():
        f = p.target / rel
        p.files[rel] = "unchanged" if f.is_file() and f.read_bytes() == data else "changed" if f.exists() else "new"
    services = doc.get("services") or {}
    for name, svc in services.items():
        for v in (svc or {}).get("volumes") or []:
            if isinstance(v, str) and v.startswith("./data/"):
                rel = v.split(":", 1)[0][2:]
                if not (p.target / rel).is_dir():
                    p.folders.append(rel)
    p.volumes = [f"{doc.get('name') or bundle}_{v}" for v in doc.get("volumes") or {}]
    p.secrets = {str(n): str(s["file"]) for n, s in (doc.get("secrets") or {}).items() if isinstance(s, dict)
                 and "file" in s}
    for s in stacks.plan(reg, [c.name for c in comps]):  # dependencies first
        if s.bundle != bundle:
            continue
        named = [n for n in (services.get(s.name) or {}).get("secrets") or [] if n in p.secrets]
        missing = [p.secrets[n] for n in named if n != TOKEN_SECRET and not _secret_ok(Path(p.secrets[n]))]
        waits = [d for d in s.depends_on if d in p.waiting]
        if TOKEN_SECRET in named and not _token_ok():
            p.waiting[s.name] = f"the machine's token {p.secrets[TOKEN_SECRET]} (brain ipc token --init)"
        elif missing:
            p.waiting[s.name] = f"its secret file {', '.join(missing)} (the owner fills it)"
        elif waits:
            p.waiting[s.name] = f"{', '.join(waits)}"
    off = stacks.profile_off(reg, root)
    outside = []
    for s in stacks.plan(reg, [c.name for c in comps]):
        st, why = stacks.state(s, off.get(s.name, ""))
        if s.bundle != bundle:
            p.rows.append({"component": s.name, "state": st, "why": why,
                           "action": "a dependency: up" if st == "OK" else "a dependency: started first"})
            continue
        if not stacks.applied(s):
            why = "not applied"
        if s.name in off:
            outside.append(s.name)
        if s.name in p.waiting:
            action = f"waits for {p.waiting[s.name]}"
        elif st == "OK":
            action = "up; docker compose up -d recreates it only if its configuration changed"
        elif st == "STALE":
            action = "recreated (its containers differ from the compose file)"
        else:
            action = "started"
            busy = [port for port in host_ports(services.get(s.name) or {}) if _listening(port)]
            if busy:
                p.notes.append(f"{s.name} is not up but {', '.join(f'{LOOPBACK}:{n}' for n in busy)} answers: another "
                               "program holds it, or the container is still starting")
        p.rows.append({"component": s.name, "state": st, "why": why, "action": action})
    docker_up = all(r["state"] == "OK" for r in p.rows if r["component"] not in {c.name for c in comps})
    for name, svc in services.items():
        image = str((svc or {}).get("image") or "")
        if image and image not in p.images:
            p.images[image] = _image_present(image, docker_up)
        if image and p.images[image] is not True and name not in p.waiting:
            p.pull.append(name)
    if outside:
        p.notes.append(f"outside this machine's profile (brain health says OFF when stopped, no alert): "
                       f"{', '.join(outside)}; brain profile set " + " ".join(f"--with {n}" for n in outside)
                       + " --apply keeps them in it")
    return p


def render_plan(p: Plan, applied: bool = False) -> list[str]:
    head = "the apply" if applied else "the plan (nothing written, nothing started)"
    lines = [f"bundle {p.bundle}: {head}", f"target    {p.target}"]
    by = {}
    for rel, st in p.files.items():
        by.setdefault(st, []).append(rel)
    lines.append("files     " + "; ".join(f"{st} {', '.join(by[st])}" for st in ("new", "changed", "unchanged")
                                          if st in by))
    if p.folders:
        lines.append(f"folders   new {', '.join(p.folders)} (placement data home)")
    if p.volumes:
        lines.append(f"volumes   {', '.join(p.volumes)} (Docker named volumes: placement data volume)")
    for name, f in p.secrets.items():
        lines.append(f"secret    {name}: {f} ({'present' if _secret_ok(Path(f)) else 'missing'})")
    pull = [i for i, here in p.images.items() if here is False]
    unknown = [i for i, here in p.images.items() if here is None]
    if pull:
        lines.append(f"images    to pull: {', '.join(i.split('@')[0] for i in pull)}")
    if unknown:
        lines.append(f"images    not checked (Docker is down): {len(unknown)}, pulled by the apply where missing")
    if not pull and not unknown and p.images:
        lines.append(f"images    {len(p.images)} present")
    width = max([len(r["component"]) for r in p.rows] + [9])
    for r in p.rows:
        lines.append(f"{r['component']:<{width}} {r['state']:<5} -> {r['action']}")
    lines += [f"check     ok: {c}" for c in p.checks]
    lines += [f"PROBLEM   {b}" for b in p.problems]
    lines += [f"note      {n}" for n in p.notes]
    if not applied:
        lines.append(f"next      fix the problems above, then brain bundle plan {p.bundle}" if p.problems else
                     f"next      brain bundle apply {p.bundle}")
    return lines


def _write(f: Path, data: bytes) -> None:
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, f)


def apply(reg: dict[str, stacks.Stack], bundle: str, root: Path | None = None, start: bool = True,
          out=None) -> int:
    out = out or sys.stdout
    p = plan(reg, bundle, root)
    if p.problems:
        for line in render_plan(p):
            print(line, file=out)
        print(f"brain bundle apply {bundle}: nothing applied ({len(p.problems)} problem(s))", file=out)
        return 1
    for rel, st in p.files.items():
        if st != "unchanged":
            _write(p.target / rel, p.rendered[rel])
    for rel in p.folders:
        (p.target / rel).mkdir(parents=True, exist_ok=True)
    for line in render_plan(p, applied=True):
        print(line, file=out)
    written = [rel for rel, st in p.files.items() if st != "unchanged"]
    print(f"wrote     {', '.join(written) if written else 'nothing (every file unchanged)'}", file=out, flush=True)
    if not start:
        print(f"not started (--no-start): brain up {bundle} starts it", file=out)
        return 0
    comps = [s.name for s in components(reg, bundle)]
    deps = [s.name for s in stacks.plan(reg, comps) if s.bundle != bundle]
    rc = stacks.up(reg, deps, out=out) if deps else 0
    if rc:
        return rc
    go = [n for n in comps if n not in p.waiting]
    if p.pull:
        rc = _pull(p.target, p.pull, out)
        if rc:
            return rc
    rc = stacks.up(reg, go, out=out) if go else 0
    for n, why in p.waiting.items():
        print(f"{n} WAITS for {why}; brain bundle apply {bundle} starts it once it is there", file=out)
    return rc


def _pull(where: Path, services: list[str], out) -> int:
    argv = stacks._resolve(["docker", "compose", "pull", "--quiet", *services])
    if not argv:
        print("pull FAILED: docker not found", file=out)
        return 1
    t0 = stacks._clock()
    code, text = stacks._run(argv, where, PULL_TIMEOUT)
    if code == 0:
        print(f"pulled    {', '.join(services)} ({stacks._secs(t0)})", file=out, flush=True)
        return 0
    why = f"did not finish in {PULL_TIMEOUT:g} s" if code is None else f"exited {code}: {stacks.useful_line(text)}"
    print(f"pull FAILED: {why}", file=out, flush=True)
    return 1


def main(cmd: str, bundles: list[str], root: Path | None = None, start: bool = True, as_json: bool = False) -> int:
    """``brain bundle plan / apply``: every shipped bundle when none is named."""
    try:
        reg = stacks.load(root)
        rc = 0
        for i, b in enumerate(bundles or names()):
            if cmd == "apply":
                rc = max(rc, apply(reg, b, root, start))
                continue
            p = plan(reg, b, root)
            if as_json:
                d = {k: v for k, v in asdict(p).items() if k != "rendered"}
                print(json.dumps({**d, "target": str(p.target)}, indent=2, ensure_ascii=False))
            else:
                print(("\n" if i else "") + "\n".join(render_plan(p)))
            rc = max(rc, 1 if p.problems else 0)
        return rc
    except (stacks.StackError, BundleError) as exc:
        print(f"brain bundle {cmd}: {exc}", file=sys.stderr)
        return 2
