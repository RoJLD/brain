"""This machine: one identity read everywhere, and its facts in three states with their source (wi-brain-machine-facts,
step S4 of the one-brain design).

**The identity.** :func:`name` is the machine's name for the whole engine: ``$BRAIN_MACHINE``, else the host name,
lowercase, ``[a-z0-9-]``, 40 characters at most (the memory sync's rule, now the one rule: brain.memory, brain.probe
and brain.schedule read it; brain.permissions' ``machines:`` stay host names, as they were). :func:`anchor` ties the name to the OS install: ``sha256(id || os
family)`` of ``MachineGuid`` (Windows), ``/etc/machine-id`` (Linux) or ``IOPlatformUUID`` (macOS), each readable without
admin rights and one per OS install (an MSYS or Cygwin Python reads ``MachineGuid`` through ``/proc/registry`` and
hashes it with the windows family, so it gives the native Python's anchor); the raw id is never written or printed.
:func:`identity` keeps the first sight in ``<BRAIN_HOME>/machine.json`` (``v``, the name, the anchor, a local id, its
date) and compares it, and the owner's declared machines (``config.json`` ``hosts``: ``{name: {anchor, local_id,
roles, aliases, ...}}``), with what it reads now:

  ok           the same name on the same OS install
  new          first sight on this BRAIN_HOME (machine.json written); declare it with the ``hosts`` line the plan prints
  renamed      the same OS install under another name (BRAIN_MACHINE changed)
  moved        another OS install with this BRAIN_HOME (a copied home, a cloned image)
  reused       ``hosts`` gives this name another OS install's anchor (a name taken again: name the new machine)
  duplicate    ``hosts`` gives this anchor to another name too (a cloned image)
  no-anchor    the OS install id could not be read (no machine-id file), and the owner has not confirmed this home:
               ``hosts.<name>.local_id`` naming machine.json's ``local_id`` (random, one per BRAIN_HOME) confirms it,
               for this home only, so a config.json shared by every machine vouches for no other machine that
               takes the name; with no anchor nothing is compared (never moved, reused nor duplicate), and a home
               first seen with an anchor, or a name declared with one, stays a doubt (run the Python that reads it)

Every state but ok and new is a doubt (``doubt`` holds the question, asked once: ``asked`` in machine.json dates it):
the memory sync's export (the machine's branch, a machine-level write) is held while it lasts (:func:`in_doubt`,
brain.memory.export_held), as it is below ``config.json`` ``engine.min``; the import goes on.

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
from datetime import datetime, timedelta
from pathlib import Path

from . import faults, paths

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
    "no-anchor": "the OS install id cannot be read here ({why}): if this BRAIN_HOME is {name}'s own, confirm it by "
                 "adding \"{name}\": {{\"local_id\": \"{local_id}\"}} under hosts in config.json (its declared "
                 "facts, if any, may sit in it): it vouches for this home only, not for another machine named {name}",
}
# no-anchor's other questions: an anchor known for this home or this name, or a confirmation of another home
NO_ANCHOR_SEEN = ("this home was first seen, or hosts.{name} declares it, with an OS install id that cannot be read "
                  "here ({why}): run the brain with the Python that reads it (a copied home cannot be told apart "
                  "without it)")
NO_ANCHOR_OTHER = ("hosts.{name}.local_id confirms another BRAIN_HOME, and the OS install id cannot be read here "
                   "({why}) to tell the machines apart: a second machine named {name}? give it its own name "
                   "(BRAIN_MACHINE)")
INSTALL_ID_SOURCES = {"windows": "MachineGuid", "linux": "/etc/machine-id", "darwin": "IOPlatformUUID"}
POSIX_ON_WINDOWS = ("msys", "cygwin")   # platform.system() of an MSYS2 or Cygwin Python: msys_nt-10.0-26100, ...
PROC_REGISTRY = ("/proc/registry64/HKEY_LOCAL_MACHINE/SOFTWARE/Microsoft/Cryptography/MachineGuid",
                 "/proc/registry/HKEY_LOCAL_MACHINE/SOFTWARE/Microsoft/Cryptography/MachineGuid")


# Side effects, replaced by fakes in the tests.

def _hostname() -> str:
    import socket   # here: a hook imports this module (the owner guard counts its milliseconds)
    return socket.gethostname()


def _os() -> str:
    import platform
    return platform.system().lower()


def _install_id_raw(system: str) -> str:
    """The OS install's id, raw ('' when it cannot be read)."""
    if system.startswith(POSIX_ON_WINDOWS):   # no winreg there: the registry as files, readable without admin rights
        for f in PROC_REGISTRY:
            try:
                return Path(f).read_bytes().decode("utf-8", "replace").strip("\0\r\n\t ")
            except OSError:
                continue
        return ""
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
    return faults.now()


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


def family(system: str) -> str:
    """The OS family an anchor is hashed with: an MSYS or Cygwin Python runs on Windows (the same install, the same
    anchor as the native Python's)."""
    return "windows" if system.startswith(POSIX_ON_WINDOWS) else system


def anchor() -> tuple[str | None, str]:
    """(sha256 of the OS install's id and the OS family, its source); (None, why) when the id cannot be read."""
    system = _os()
    fam = family(system)
    src = INSTALL_ID_SOURCES.get(fam, system) + (" (/proc/registry)" if fam != system else "")
    try:
        raw = _install_id_raw(system)
    except (OSError, ValueError, ImportError, subprocess.SubprocessError) as exc:   # unreadable: a state, no error
        return None, f"{src}: {type(exc).__name__}"
    if not raw:
        return None, f"{src} not found"
    return hashlib.sha256(f"{raw.strip().lower()}\0{fam}".encode("utf-8")).hexdigest(), src


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


def _stamp() -> str:
    return _now().strftime("%Y-%m-%dT%H:%M:%SZ")


def _unanchored(nm: str, first: dict, mine: dict) -> str:
    """The state of an identity whose install id cannot be read: no-anchor until hosts.<name>.local_id names this
    home's local_id, while neither this home nor this name has a known anchor; then renamed or ok."""
    confirmed = (not first.get("anchor") and not mine.get("anchor") and bool(first.get("local_id"))
                 and mine.get("local_id") == first.get("local_id"))
    if not confirmed:
        return "no-anchor"
    return "renamed" if first.get("name") and first.get("name") != nm else "ok"


def _state(nm: str, anc: str | None, first: dict, declared: dict) -> tuple[str, str | None]:
    """(the identity's state, the other name that holds this anchor in hosts) from what is read and recorded.

    An unreadable anchor compares nothing (never moved, reused nor duplicate: review of the item, finding 1); it is a
    doubt until ``hosts.<name>.local_id`` names this home's machine.json ``local_id`` (the owner's confirmation, bound
    to this home: wi-brain-machine-no-anchor-doubt), and stays one when this home or this name has a known anchor."""
    mine = declared.get(nm) if isinstance(declared.get(nm), dict) else {}
    if anc is None:
        return _unanchored(nm, first, mine), None
    other = next((k for k, v in declared.items() if k != nm and isinstance(v, dict)
                  and v.get("anchor") == anc), None)
    checks = (("reused", bool(mine.get("anchor")) and mine.get("anchor") != anc),
              ("duplicate", bool(other)), ("new", not first),
              ("moved", bool(first.get("anchor")) and first.get("anchor") != anc),
              ("renamed", bool(first.get("name")) and first.get("name") != nm))
    return next((state for state, hit in checks if hit), "ok"), other


def _write(f: Path, rec: dict) -> bool:
    from . import stateio

    try:
        stateio.write_atomic(f, json.dumps(rec, indent=1) + "\n")
    except OSError:
        return False
    return True


def _first_sight(f: Path, first: dict, out: dict) -> None:
    """machine.json written at first sight (before the doubt is said: no-anchor's names this home's ``local_id``)."""
    if not first and out["state"] in ("new", "no-anchor"):
        rec = {"v": V, "name": out["name"], "anchor": out["anchor"], "local_id": uuid.uuid4().hex, "since": _stamp()}
        if _write(f, rec):
            out.update(local_id=rec["local_id"], since=rec["since"])


def _remember(f: Path, first: dict, out: dict) -> None:
    """A doubt's first showing stamped in machine.json's ``asked`` (``first`` updated)."""
    if out["doubt"] and first and out["state"] not in (first.get("asked") or {}):
        first.setdefault("asked", {})[out["state"]] = _stamp()
        _write(f, first)


def _doubt(state: str, nm: str, first: dict, mine: dict, other: str | None, why: str, local_id: str | None) -> str:
    """The doubt's question, '' for ok and new."""
    if state not in DOUBTS:
        return ""
    text = DOUBTS[state]
    if state == "no-anchor" and (first.get("anchor") or mine.get("anchor")):
        text = NO_ANCHOR_SEEN
    elif state == "no-anchor" and mine.get("local_id") and first.get("local_id") != mine.get("local_id"):
        text = NO_ANCHOR_OTHER
    return text.format(name=nm, first=first.get("name") or "?", other=other, why=why,
                       local_id=local_id or "<the local_id of BRAIN_HOME/machine.json>")


def identity(cfg_data: dict | None = None, write: bool = True) -> dict:
    """This machine's identity and its state (see the module's docstring); machine.json is written at first sight
    (``write``), and its ``asked`` stamped the first time a doubt is shown."""
    nm, (anc, src), f = name(), anchor(), machine_file()
    first, declared = _load(f), hosts(cfg_data)
    state, other = _state(nm, anc, first, declared)
    mine = declared.get(nm) if isinstance(declared.get(nm), dict) else {}
    out = {"v": V, "name": nm, "anchor": anc, "anchor_source": src, "local_id": first.get("local_id"),
           "since": first.get("since"), "file": f.as_posix(), "state": state, "declared": nm in declared}
    if write:
        _first_sight(f, first, out)
    out["doubt"] = _doubt(state, nm, first, mine, other, src, out["local_id"])
    if write:
        _remember(f, first, out)
    out["asked"] = (first.get("asked") or {}).get(state)
    if anc and not mine.get("anchor") and state in ("ok", "new"):
        out["declare"] = f'"hosts": {{"{nm}": {{"anchor": "{anc}"}}}}'   # the line the owner's config.json lacks
    return out


def in_doubt(cfg_data: dict | None = None) -> str:
    """The doubt on this machine's identity, '' when there is none: the memory export is held while it lasts."""
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


def _find_node(nodes, wanted: list[str], key: str) -> tuple[str | None, dict | None]:
    """(the name found, its node) among ``nodes``, a mapping by name or a list whose ``key`` holds the name."""
    for w in wanted:
        if isinstance(nodes, dict) and isinstance(nodes.get(w), dict):
            return w, nodes[w]
        if isinstance(nodes, list):
            hit = next((n for n in nodes if isinstance(n, dict) and n.get(key) == w), None)
            if hit is not None:
                return w, hit
    return None, None


def nodes_file(spec: dict, me: str, aliases: list[str]) -> tuple[dict, dict]:
    """The facts of ``me`` (or one of its aliases, or ``spec.node``) in a nodes file read at a git ref through its
    field table: ({fact: value}, {fingerprint, ref, node, version}). ValueError for an unknown version or a file git
    cannot show."""
    from .graph import load_yaml

    ref = spec.get("ref") or "origin/main"
    if str(ref).startswith("-") or str(spec["file"]).startswith("-"):   # never read as a git option
        raise ValueError(f"{ref}:{spec['file']} is not a ref and a path (it starts with -)")
    text = _git_show(str(spec["checkout"]), ref, str(spec["file"]))
    data = load_yaml(text) or {}
    vpath, accept = spec.get("version_path", "version"), [str(v) for v in spec.get("versions") or []]
    got = _dotted(data, vpath)
    if accept and str(got) not in accept:
        raise ValueError(f"{spec['file']}: {vpath} {got!r} is not one this brain reads ({', '.join(accept)})")
    wanted = [spec["node"]] if spec.get("node") else [me, *aliases]
    found, node = _find_node(_dotted(data, spec.get("nodes", "nodes")), wanted, spec.get("key", "name"))
    meta = {"fingerprint": hashlib.sha256(text.encode("utf-8")).hexdigest()[:12], "ref": ref, "node": found,
            "version": got}
    fields = (spec.get("fields") or {}).items() if node is not None else ()
    return {fact: v for fact, path in fields if (v := _dotted(node, str(path))) is not None}, meta


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


def _layers(probed: dict, cfg_data: dict | None, infra_node: bool, now: datetime | None) -> tuple[list, list[str]]:
    """[(source, {fact: value})] in their order of trust, and the providers' errors."""
    me = name()
    declared = hosts(cfg_data).get(me) if isinstance(hosts(cfg_data).get(me), dict) else {}
    inv = (cfg_data or {}).get("inventory") or {}
    layers, errors = [], []
    if infra_node and isinstance(inv.get("agent_json"), dict):
        agent, meta = agent_report(inv["agent_json"], me, now)
        layers.append(("agent", agent))
        errors += [f"agent report {meta['path']}: {meta['note']}"] if meta.get("note") else []
    layers.append(("probed", probed))
    if isinstance(inv.get("nodes_file"), dict):
        try:
            nodes, meta = nodes_file(inv["nodes_file"], me, list(declared.get("aliases") or []))
            layers.append((f"nodes-file@{meta['ref']}:{meta['fingerprint']}", nodes))
        except (ValueError, KeyError, OSError, subprocess.SubprocessError) as exc:
            errors.append(f"nodes file: {exc}")
    layers.append(("declared", {k: v for k, v in declared.items() if k in DECLARED}))
    return layers, errors


def facts(probed: dict, cfg_data: dict | None = None, infra_node: bool = False,
          now: datetime | None = None) -> tuple[dict, dict, list[str]]:
    """(the flat facts, {fact: {value, source}}, the providers' errors): each fact from the first source that knows
    it (see the module's docstring)."""
    layers, errors = _layers(probed, cfg_data, infra_node, now)
    keys = sorted({k for _, values in layers for k in values})
    sourced = {}
    for k in keys:
        src, value = next(((s, v[k]) for s, v in layers if v.get(k) is not None), ("unknown", None))
        sourced[k] = {"value": value, "source": src}
    return {k: s["value"] for k, s in sourced.items()}, sourced, errors


def save_facts(sourced: dict, now: datetime | None = None) -> None:
    """``<BRAIN_HOME>/facts.json``: the last facts with their source, dated."""
    from . import stateio

    at = (now or _now()).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        stateio.write_atomic(paths.brain_home() / FACTS_FILE, json.dumps(
            {"v": V, "machine": name(), "at": at, "facts": sourced}, ensure_ascii=False, indent=1) + "\n")
    except OSError:
        pass
