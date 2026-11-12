"""This machine: one identity read everywhere, and its facts in three states with their source (wi-brain-machine-facts,
step S4 of the one-brain design).

**The identity.** :func:`name` is the machine's name for the whole engine: ``$BRAIN_MACHINE``, else the host name,
lowercase, ``[a-z0-9-]``, 40 characters at most (the memory sync's rule, now the one rule: brain.memory, brain.probe,
brain.permissions and brain.schedule read it). :func:`anchor` ties the name to the OS install: ``sha256(id || os
family)`` of ``MachineGuid`` (Windows), ``/etc/machine-id`` (Linux) or ``IOPlatformUUID`` (macOS), each readable without
admin rights and one per OS install; the raw id is never written or printed. :func:`identity` keeps the first sight in
``<BRAIN_HOME>/machine.json`` (``v``, the name, the anchor, a local id, its date) and compares it, and the owner's
declared machines (``config.json`` ``hosts``: ``{name: {anchor, roles, aliases, ...}}``), with what it reads now:

  ok           the same name on the same OS install
  new          first sight on this BRAIN_HOME (machine.json written); declare it with the ``hosts`` line the plan prints
  renamed      the same OS install under another name (BRAIN_MACHINE changed)
  moved        another OS install with this BRAIN_HOME (a copied home, a cloned image)
  reused       ``hosts`` gives this name another OS install's anchor (a name taken again: name the new machine)
  duplicate    ``hosts`` gives this anchor to another name too (a cloned image)
  no-anchor    the OS install id could not be read

Every state but ok and new is a doubt (``doubt`` holds the question, asked once: ``asked`` in machine.json dates it):
a writer of the machine level writes nothing while it lasts (:func:`in_doubt`).

**The facts.** Each fact is true, false or unknown (None): an unknown fact never satisfies ``FACT`` nor ``not FACT``
(brain.tiers.truth). :func:`facts` gives each fact's value and its source, in this order of trust:

  1. the agent report (``inventory.agent_json``: a ``brain.status/v1`` document of an infra agent, read only when the
     ``infra-node`` capability is on and the report is less than 24 h old);
  2. the local probe (``brain doctor``: always on, a probe that could not say stays unknown and falls through);
  3. the nodes file (``inventory.nodes_file``: a YAML read at a git ref of a local checkout, ``git show REF:FILE``,
     never the working copy, through a declarative table of field paths; a ``version`` outside the accepted ones is
     refused loudly);
  4. declared in ``config.json`` ``hosts.<name>`` (ecc, battery, encrypted, gpu, type, cluster, roles);
  5. unknown.

``<BRAIN_HOME>/facts.json`` caches the last facts, each with its source and date (brain doctor writes it).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import paths

FILE = "machine.json"
FACTS_FILE = "facts.json"
V = 1
AGENT_MAX_AGE = timedelta(hours=24)
DECLARED = ("ecc", "battery", "encrypted", "gpu", "type", "cluster", "roles")   # what hosts.<name> may declare
DOUBTS = {
    "renamed": "this OS install was first seen as {first}: is {name} the same machine (keep {first}, or rename it)?",
    "moved": "this BRAIN_HOME was made on another OS install ({first}): a copied home or a cloned image; a new "
             "machine needs its own name (BRAIN_MACHINE) and home",
    "reused": "hosts.{name}.anchor is another OS install's: {name} was reused; give this machine a new name "
              "(BRAIN_MACHINE)",
    "duplicate": "hosts gives this OS install to {other} as well: a cloned image? one name per install",
    "no-anchor": "the OS install id cannot be read here ({why}): confirm the name {name} by hand in hosts",
}
INSTALL_ID_SOURCES = {"windows": "MachineGuid", "linux": "/etc/machine-id", "darwin": "IOPlatformUUID"}


# Side effects, replaced by fakes in the tests.

def _hostname() -> str:
    import socket   # here: a hook imports this module (the owner guard counts its milliseconds)
    return socket.gethostname()


def _os() -> str:
    import platform
    return platform.system().lower()


def _install_id_raw(system: str) -> str:
    """The OS install's id, raw ('' when it cannot be read)."""
    if system == "windows":
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                            winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)) as k:
            return str(winreg.QueryValueEx(k, "MachineGuid")[0])
    if system == "linux":
        for f in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            try:
                return Path(f).read_text(encoding="utf-8").strip()
            except OSError:
                continue
        return ""
    if system == "darwin":
        out = subprocess.run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"], capture_output=True, text=True,
                             timeout=5).stdout
        m = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', out)
        return m.group(1) if m else ""
    return ""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _git_show(checkout: str, ref: str, file: str) -> str:
    p = subprocess.run(["git", "-C", checkout, "show", f"{ref}:{file}"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=10, stdin=subprocess.DEVNULL,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if p.returncode != 0:
        raise ValueError(f"git show {ref}:{file} in {checkout} failed: {(p.stderr or '').strip()[:200]}")
    return p.stdout


# The identity.

def normalize(raw: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", (raw or "").lower()).strip("-")[:40]


def name() -> str:
    """This machine's name for the brain: $BRAIN_MACHINE, else the host name; lowercase, [a-z0-9-], 40 at most."""
    return normalize(os.environ.get("BRAIN_MACHINE") or _hostname() or "machine") or "machine"


def anchor() -> tuple[str | None, str]:
    """(sha256 of the OS install's id and the OS family, its source); (None, why) when the id cannot be read."""
    system = _os()
    try:
        raw = _install_id_raw(system)
    except Exception as exc:  # noqa: BLE001 - an unreadable id is a state (no-anchor), never an error
        return None, f"{INSTALL_ID_SOURCES.get(system, system)}: {type(exc).__name__}"
    if not raw:
        return None, f"{INSTALL_ID_SOURCES.get(system, system)} not found"
    return hashlib.sha256(f"{raw.strip().lower()}\0{system}".encode("utf-8")).hexdigest(), \
        INSTALL_ID_SOURCES.get(system, system)


def machine_file() -> Path:
    return paths.brain_home() / FILE


def _load(f: Path) -> dict:
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def hosts(cfg_data: dict | None) -> dict:
    h = (cfg_data or {}).get("hosts")
    return h if isinstance(h, dict) else {}


def identity(cfg_data: dict | None = None, write: bool = True) -> dict:
    """This machine's identity and its state (see the module's docstring); machine.json is written at first sight
    (``write``), and its ``asked`` stamped the first time a doubt is shown."""
    from . import stateio

    nm = (name())
    anc, src = anchor()
    f = machine_file()
    first = _load(f)
    declared = hosts(cfg_data)
    out = {"v": V, "name": nm, "anchor": anc, "anchor_source": src, "local_id": first.get("local_id"),
           "since": first.get("since"), "file": f.as_posix(), "state": "ok", "doubt": "",
           "declared": nm in declared}
    other = next((k for k, v in declared.items() if k != nm and isinstance(v, dict) and anc
                  and v.get("anchor") == anc), None)
    mine = declared.get(nm) if isinstance(declared.get(nm), dict) else {}
    if anc is None:
        out["state"] = "no-anchor"
    elif mine.get("anchor") and mine["anchor"] != anc:
        out["state"] = "reused"
    elif other:
        out["state"] = "duplicate"
    elif not first:
        out["state"] = "new"
    elif first.get("anchor") and first["anchor"] != anc:
        out["state"] = "moved"
    elif first.get("name") and first["name"] != nm:
        out["state"] = "renamed"
    if out["state"] in DOUBTS:
        out["doubt"] = DOUBTS[out["state"]].format(name=nm, first=first.get("name") or "?", other=other, why=src)
    if write and not first and out["state"] in ("new", "no-anchor"):
        rec = {"v": V, "name": nm, "anchor": anc, "local_id": uuid.uuid4().hex,
               "since": _now().strftime("%Y-%m-%dT%H:%M:%SZ")}
        try:
            stateio.write_atomic(f, json.dumps(rec, indent=1) + "\n")
            out.update(local_id=rec["local_id"], since=rec["since"])
        except OSError:
            pass
    elif write and out["doubt"] and first and out["state"] not in (first.get("asked") or {}):
        first.setdefault("asked", {})[out["state"]] = _now().strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            stateio.write_atomic(f, json.dumps(first, indent=1) + "\n")
        except OSError:
            pass
    out["asked"] = (first.get("asked") or {}).get(out["state"])
    if anc and not mine.get("anchor") and out["state"] in ("ok", "new"):
        out["declare"] = f'"hosts": {{"{nm}": {{"anchor": "{anc}"}}}}'   # the line the owner's config.json lacks
    return out


def in_doubt(cfg_data: dict | None = None) -> str:
    """The doubt on this machine's identity, '' when there is none: a writer of the machine level writes nothing while
    it lasts."""
    return identity(cfg_data, write=False)["doubt"]


# The facts and their sources.

def _dotted(data, path: str):
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


def nodes_file(spec: dict, me: str, aliases: list[str]) -> tuple[dict, dict]:
    """The facts of ``me`` (or one of its aliases, or ``spec.node``) in a nodes file read at a git ref through its
    field table: ({fact: value}, {fingerprint, ref, node}). ValueError for an unknown version or an unreadable file."""
    from .graph import load_yaml

    text = _git_show(str(spec["checkout"]), spec.get("ref") or "origin/main", spec["file"])
    data = load_yaml(text) or {}
    vpath = spec.get("version_path", "version")
    accept = [str(v) for v in spec.get("versions") or []]
    got = _dotted(data, vpath)
    if accept and str(got) not in accept:
        raise ValueError(f"{spec['file']}: {vpath} {got!r} is not one this brain reads ({', '.join(accept)})")
    nodes = _dotted(data, spec.get("nodes", "nodes")) or {}
    wanted = [spec["node"]] if spec.get("node") else [me, *aliases]
    node = None
    if isinstance(nodes, dict):
        node = next((nodes[w] for w in wanted if isinstance(nodes.get(w), dict)), None)
    elif isinstance(nodes, list):
        key = spec.get("key", "name")
        node = next((n for w in wanted for n in nodes if isinstance(n, dict) and n.get(key) == w), None)
    meta = {"fingerprint": hashlib.sha256(text.encode("utf-8")).hexdigest()[:12], "ref": spec.get("ref") or
            "origin/main", "node": next((w for w in wanted if node is not None), None), "version": got}
    if node is None:
        return {}, meta
    out = {}
    for fact, path in (spec.get("fields") or {}).items():
        v = _dotted(node, str(path))
        if v is not None:
            out[fact] = v
    return out, meta


def agent_report(spec: dict, me: str, now: datetime | None = None) -> tuple[dict, dict]:
    """The flat facts of a recent agent report (``spec.path``, ``{machine}`` replaced by the name): a brain.status/v1
    document, read when it is younger than AGENT_MAX_AGE; ({}, why) otherwise."""
    from . import probe

    f = Path(str(spec["path"]).replace("{machine}", me))
    doc = _load(f)
    at = str((doc.get("brain") or {}).get("at") or doc.get("at") or "")
    try:
        when = datetime.fromisoformat(at.replace("Z", "+00:00"))
    except ValueError:
        return {}, {"path": f.as_posix(), "note": "no report, or no date in it"}
    if (now or _now()) - when > AGENT_MAX_AGE:
        return {}, {"path": f.as_posix(), "at": at, "note": "older than 24 h: the local probe stands"}
    try:
        flat = probe.facts(doc)
    except (KeyError, TypeError):
        return {}, {"path": f.as_posix(), "at": at, "note": "not a brain.status/v1 document"}
    return flat, {"path": f.as_posix(), "at": at}


def facts(probed: dict, cfg_data: dict | None = None, infra_node: bool = False,
          now: datetime | None = None) -> tuple[dict, dict, list[str]]:
    """(the flat facts, {fact: {value, source}}, the providers' errors): each fact from the first source that knows
    it (see the module's docstring)."""
    me = name()
    declared = hosts(cfg_data).get(me) if isinstance(hosts(cfg_data).get(me), dict) else {}
    inv = (cfg_data or {}).get("inventory") or {}
    layers, errors = [], []
    if infra_node and isinstance(inv.get("agent_json"), dict):
        agent, meta = agent_report(inv["agent_json"], me, now)
        layers.append(("agent", agent))
        if meta.get("note"):
            errors.append(f"agent report {meta['path']}: {meta['note']}")
    layers.append(("probed", probed))
    if isinstance(inv.get("nodes_file"), dict):
        try:
            nodes, meta = nodes_file(inv["nodes_file"], me, list(declared.get("aliases") or []))
            layers.append((f"nodes-file@{meta['ref']}:{meta['fingerprint']}", nodes))
        except (ValueError, KeyError, OSError, subprocess.SubprocessError) as exc:
            errors.append(f"nodes file: {exc}")
    layers.append(("declared", {k: v for k, v in declared.items() if k in DECLARED}))
    flat, sources = {}, {}
    for _, values in layers:
        for k in values:
            flat.setdefault(k, None)
    for k in list(flat):
        for src, values in layers:
            if values.get(k) is not None:
                flat[k], sources[k] = values[k], src
                break
        else:
            sources[k] = "unknown"
    return flat, {k: {"value": flat[k], "source": sources[k]} for k in sorted(flat)}, errors


def save_facts(sourced: dict, now: datetime | None = None) -> None:
    """``<BRAIN_HOME>/facts.json``: the last facts with their source, dated."""
    from . import stateio

    at = (now or _now()).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        stateio.write_atomic(paths.brain_home() / FACTS_FILE, json.dumps(
            {"v": V, "machine": name(), "at": at, "facts": sourced}, ensure_ascii=False, indent=1) + "\n")
    except OSError:
        pass
