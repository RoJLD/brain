"""brain spool: the sealed local spool of the stores that leave the machine (wi-brain-storage-split).

A store leaves the machine only sealed client-side (brain.classes.decide, brain.vault.seal). Until a data remote
exists (a NAS, object storage, a private dataset host: a config value, later), what leaves waits here, sealed and
checked by hash (the shape of a store-and-forward buffer)::

    $BRAIN_HOME/spool/
      spool.json                             the index: each sealed file's store, sha256, bytes, when put, when sent
      <store>/<store>-<stamp>.tar.gz.age     sealed by brain.vault to the store's recipients (.gpg with gpg)
      <store>/<store>-<stamp>.tar.gz.age.json   brain.vault's manifest beside it

``brain spool push`` runs by hand (no scheduled task until the owner adds one): it puts each store of the spool's set
(``spool.stores`` in config.json, else :data:`DEFAULT_STORES`) whose content changed since its last put, sends what
waits to ``spool.remote`` when one is set (a folder: a mounted share, a synced drive), each copy checked by sha256
against the index before and after it is copied, then prunes. ``brain health spool`` gives the last push's age.

The API, for a caller that writes into the spool (the session archive):

- :func:`put` ``(cfg, store, items=None)``: one store sealed into the spool, its entry returned. ``items`` (paths)
  instead of the store's declared content: an entry of kind ``items``, never pruned before it is sent. Refused
  (:class:`SpoolError`): a store whose class never lets it leave (``decide(cfg, store, "offsite")``), one
  config.json does not declare, the spool itself, a text file that holds a secret's shape (the secret scan is the
  spool's, before sealing: brain.secretscan.SHAPED); brain.vault refuses a resident or secret store and fewer than
  two recipients.
- :func:`push`, :func:`send`, :func:`prune`, :func:`verify`, :func:`status`, :func:`health`.

The index is truth-local (brain.stateio, ``v`` 1): a newer brain's is read-only here, an unreadable one set aside.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import classes, config, paths, secretscan, stateio, vault

CHECK = "spool"                                   # brain health spool
STORE = "spool"                                   # its own store (brain.classes.ENGINE_STORES)
EXIT = "offsite"                                  # the exit a store takes to leave through the spool
DEFAULT_STORES = ("ledger", "usage", "sessions")  # the spool's set when config.json names none
KEEP = 3              # the snapshots kept per store, sent or not; an items entry is pruned only once sent
MAX_AGE_DAYS = 7      # brain health spool warns past it
INDEX_V = 1
KINDS = ("snapshot", "items")


class SpoolError(RuntimeError):
    """A put or a push the spool refuses (brain spool exits 2)."""


def spool_dir() -> Path:
    return paths.brain_home() / "spool"


def index_file() -> Path:
    return spool_dir() / "spool.json"


def _block(cfg: config.Config) -> dict:
    d = cfg.data.get("spool")
    return d if isinstance(d, dict) else {}


def chosen(cfg: config.Config) -> list[str]:
    """The spool's set: config.json's ``spool.stores``, else :data:`DEFAULT_STORES`."""
    names = _block(cfg).get("stores")
    if isinstance(names, list) and names and all(isinstance(n, str) and n for n in names):
        return list(dict.fromkeys(names))
    return list(DEFAULT_STORES)


def _int(cfg: config.Config, key: str, default: int) -> int:
    v = _block(cfg).get(key)
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 1 else default


def keep(cfg: config.Config) -> int:
    return _int(cfg, "keep", KEEP)


def max_age_days(cfg: config.Config) -> int:
    return _int(cfg, "max_age_days", MAX_AGE_DAYS)


def remote(cfg: config.Config) -> Path | None:
    """``spool.remote``: the folder copies are sent to (``~`` and environment variables expanded, a relative one from
    the brain's root), None without one."""
    r = _block(cfg).get("remote")
    if not isinstance(r, str) or not r.strip():
        return None
    p = Path(os.path.expandvars(r)).expanduser()
    return p if p.is_absolute() else cfg.root / p


# --- the index ---
def _shape(data: dict) -> str:
    bad = sorted(k for k in ("files", "stores", "last") if not isinstance(data.get(k, {}), dict))
    return f"{', '.join(bad)} not an object" if bad else ""


def _index(write: bool = False) -> stateio.State:
    return stateio.load(index_file(), known=INDEX_V, check=_shape, aside=write)


def load_index(write: bool = False) -> tuple[stateio.State, dict]:
    """The index and its record; ``write``: refused here (SpoolError) when this engine must not write it."""
    st = _index(write)
    if write and not st.writable:
        raise SpoolError(st.refusal())
    data = st.data
    for k in ("files", "stores", "last"):   # a newer brain's index is not shape-checked: read what this one can
        if not isinstance(data.get(k), dict):
            data[k] = {}
    return st, data


def _save(st: stateio.State, data: dict) -> None:
    try:
        stateio.save(st, data, indent=1)
    except stateio.StateError as exc:
        raise SpoolError(str(exc)) from None


def _now(now: datetime | None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(s: object) -> datetime | None:
    try:
        return datetime.strptime(str(s), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# --- a store's content ---
def _files(pairs: list[tuple[Path, str]]) -> list[tuple[Path, str]]:
    """Every file of the items, with its name in the archive."""
    out = []
    for path, arc in pairs:
        if path.is_file():
            out.append((path, arc))
        elif path.is_dir():
            out += [(f, f"{arc}/{f.relative_to(path).as_posix()}") for f in sorted(path.rglob("*")) if f.is_file()]
    return out


def fingerprint(pairs: list[tuple[Path, str]]) -> str:
    """What a store's content looks like without reading it: its files' names, sizes and times."""
    h = hashlib.sha256()
    for f, arc in sorted(_files(pairs), key=lambda x: x[1]):
        try:
            st = f.stat()
        except OSError:
            continue
        h.update(f"{arc}\0{st.st_size}\0{st.st_mtime_ns}\n".encode("utf-8"))
    return h.hexdigest()


def scan(pairs: list[tuple[Path, str]]) -> list[str]:
    """``<name in the archive>:<line>: <pattern>`` for each secret's shape found in the items' text files (never the
    value; a binary file is not scanned: brain.secretscan.scan_file); a file that cannot be read counts, since it
    cannot be told clean."""
    hits = []
    for f, arc in _files(pairs):
        try:
            hits += [f"{arc}:{line}: {name}" for line, name in secretscan.scan_file(f)]
        except OSError as exc:
            hits.append(f"{arc}: cannot be read ({exc.__class__.__name__}), so not scanned")
    return hits


def _items(cfg: config.Config, store: str, items: list[Path]) -> list[tuple[Path, str]]:
    """The items as (path, name in the archive): refused when empty, when two share a name (one would overwrite the
    other on opening), or when one sits in a store whose class never leaves the machine (a resident or secret
    store's file cannot leave under another store's name)."""
    if not items:
        raise SpoolError(f"store {store}: no item given")
    pairs = [(Path(p), Path(p).name) for p in items]
    names = [a for _, a in pairs]
    twice = sorted({a for a in names if names.count(a) > 1})
    if twice:
        raise SpoolError(f"store {store}: items share a name in the archive: {', '.join(twice)}")
    every = classes.effective(classes.stores(cfg)[0])
    for p, _ in pairs:
        home = next((s for s in every for m in s.machine
                     if p.resolve() == classes.expand(m).resolve() or classes.expand(m).resolve() in
                     p.resolve().parents), None)
        if home is not None and home.name != store and classes.decide(cfg, home.name, EXIT) == "never":
            raise SpoolError(f"{p}: in store {home.name}, whose class never lets it leave the machine")
    return pairs


def _content(cfg: config.Config, store: str, items: list[Path] | None) -> tuple[classes.Store, list[tuple[Path, str]]]:
    if store == STORE:
        raise SpoolError("the spool does not hold itself")
    try:
        s = vault.store(cfg, store)
    except vault.VaultError as exc:
        raise SpoolError(str(exc)) from None
    if classes.decide(cfg, store, EXIT) == "never":
        raise SpoolError(f"store {store}: its class never lets it leave the machine ({EXIT}), even sealed")
    pairs = _items(cfg, store, items) if items is not None else vault.sources(cfg, s)
    return s, [(p, a) for p, a in pairs if p.exists()]


def recipients_of(cfg: config.Config, s: classes.Store) -> list[str]:
    """The fingerprints a store is sealed to now: a file sealed to others is stale (a removed or rotated key)."""
    try:
        return sorted(r.fingerprint(cfg.root) for r in vault.for_store(cfg, s))
    except vault.VaultError:
        return []


# --- put, send, prune ---
def put(cfg: config.Config, store: str, items: list[Path] | None = None, *, now: datetime | None = None,
        found: dict[str, vault.Adapter] | None = None) -> dict:
    """Seal a store (its declared content, or ``items``) into the spool after the secret scan, and record the file:
    its entry (``file`` relative to the spool, ``store``, ``kind``, ``sha256``, ``bytes``, ``recipients`` (their
    fingerprints), ``at``, ``sent`` '')."""
    load_index(write=True)   # refused before any sealing when the index cannot be written
    s, pairs = _content(cfg, store, items)
    if not pairs:
        raise SpoolError(f"store {store}: nothing to put")
    hits = scan(pairs)
    if hits:
        raise SpoolError(f"store {store}: {len(hits)} file line(s) found with a secret's shape or unreadable, nothing "
                         "sealed: " + "; ".join(hits[:5]) + (" ..." if len(hits) > 5 else "")
                         + " (clean the files, then push again)")
    kind = "items" if items is not None else "snapshot"
    fp = fingerprint(pairs) if kind == "snapshot" else ""
    t = _now(now)
    try:
        recs = vault.for_store(cfg, s)
        ad = vault.pick(cfg, recs, None, found)
        folder = spool_dir() / s.name
        stem, n = f"{s.name}-{t:%Y%m%dT%H%M%SZ}", 1
        while (folder / f"{stem}{'' if n == 1 else f'-{n}'}.tar.gz{ad.suffix}").exists():
            n += 1
        out = folder / f"{stem}{'' if n == 1 else f'-{n}'}.tar.gz{ad.suffix}"
        man = vault.seal(cfg, s.name, [p for p, _ in pairs] if kind == "items" else None, out, ad.name, t, found)
    except vault.VaultError as exc:
        raise SpoolError(str(exc)) from None
    except OSError as exc:   # a file renamed or locked while it was packed: this store fails, the others go on
        raise SpoolError(f"store {store}: {exc.__class__.__name__} while sealing: {exc}") from None
    rel = f"{s.name}/{out.name}"
    fps = sorted(r["fingerprint"] for r in man["recipients"])
    entry = {"store": s.name, "kind": kind, "seq": n, "sha256": man["sha256"], "bytes": man["bytes"],
             "files": man["files"], "recipients": fps, "at": _iso(t), "sent": ""}
    st, data = load_index(write=True)   # read again: another writer may have recorded a file meanwhile
    data["files"][rel] = entry
    if kind == "snapshot":
        data["stores"][s.name] = {"at": _iso(t), "fingerprint": fp, "recipients": fps, "file": rel}
    _save(st, data)
    return {"file": rel, **entry}


def _sha256(f: Path) -> str:
    return vault._sha256(f)


def _stale(cfg: config.Config, e: dict, current: dict[str, list[str]]) -> bool:
    """Whether a spool file is sealed to recipients that are not its store's current ones (an entry from before the
    recipients were recorded is taken as current)."""
    name = str(e.get("store", ""))
    if name not in current:
        try:
            current[name] = recipients_of(cfg, vault.store(cfg, name))
        except vault.VaultError:
            current[name] = []
    return "recipients" in e and bool(current[name]) and sorted(e["recipients"]) != current[name]


def _send_one(src: Path, target: Path, sha: str) -> str:
    """Copy one sealed file and its manifest; '' when the copy matches ``sha``, else why it was not sent."""
    if not src.is_file():
        return "missing from the spool"
    if _sha256(src) != sha:
        return "its sha256 no longer matches the index: changed in the spool, not sent"
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    shutil.copyfile(src, part)
    if _sha256(part) != sha:
        part.unlink()
        return "the copy's sha256 does not match: not sent"
    man = src.with_name(src.name + ".json")
    if man.is_file():
        shutil.copyfile(man, target.with_name(target.name + ".json"))
    os.replace(part, target)
    return ""


def _send_entry(cfg: config.Config, rel: str, e: dict, dest: Path, t: str, current: dict) -> dict:
    """One waiting file sent: its line, ``sent`` or ``error``."""
    r = {"file": rel, "store": e.get("store", "")}
    if _stale(cfg, e, current):
        r["error"] = "sealed to recipients that are no longer its store's: not sent"
        return r
    try:
        why = _send_one(spool_dir() / rel, dest / rel, str(e.get("sha256")))
    except OSError as exc:
        why = f"{exc.__class__.__name__}: {exc.strerror or exc}"
    r["error" if why else "sent"] = why or t
    return r


def send(cfg: config.Config, *, now: datetime | None = None) -> list[dict]:
    """Copy each file that waits to ``spool.remote`` (``<remote>/<store>/<file>`` and its manifest), its sha256 checked
    against the index before the copy and on the copy; marked sent only then. A file sealed to recipients that are no
    longer its store's is not sent (the next push seals the store again). [] without a remote; one line per file,
    with its ``error`` when it still waits (the remote absent, a hash that does not match, stale recipients)."""
    dest = remote(cfg)
    if dest is None:
        return []
    _, data = load_index(write=True)
    waiting = sorted(rel for rel, e in data["files"].items() if isinstance(e, dict) and not e.get("sent"))
    if not waiting:
        return []
    if not dest.is_dir():
        return [{"file": rel, "error": f"the remote {dest} is not reachable: it waits"} for rel in waiting]
    t, current = _iso(_now(now)), {}
    out = [_send_entry(cfg, rel, data["files"][rel], dest, t, current) for rel in waiting]
    st, data = load_index(write=True)   # read again before the save: a put meanwhile keeps its entry
    for r in out:
        if r.get("sent") and isinstance(data["files"].get(r["file"]), dict):
            data["files"][r["file"]]["sent"] = r["sent"]
    _save(st, data)
    return out


def prune(cfg: config.Config, *, dry_run: bool = False) -> list[str]:
    """Drop the spool's files past :func:`keep` per store and kind, the oldest first: a snapshot whether sent or not
    (a newer one holds the store), an items entry only once sent; and a snapshot that waits sealed to recipients that
    are no longer its store's, once a newer snapshot holds the store. The files removed (relative to the spool)."""
    st, data = load_index(write=not dry_run)
    gone = _past_keep(data["files"], keep(cfg))
    gone += [rel for rel in _superseded_stale(cfg, data) if rel not in gone]
    if dry_run or not gone:
        return gone
    for rel in gone:
        f = spool_dir() / rel
        _unlink(f.with_name(f.name + ".json"))
        if _unlink(f):
            data["files"].pop(rel, None)
    _save(st, data)
    return [rel for rel in gone if rel not in data["files"]]


def _past_keep(files: dict, n: int) -> list[str]:
    """The files past the newest ``n`` of their store and kind; an items entry only once sent."""
    by: dict[tuple[str, str], list[tuple[str, dict]]] = {}
    for rel, e in files.items():
        if isinstance(e, dict):
            by.setdefault((str(e.get("store", "")), str(e.get("kind", "snapshot"))), []).append((rel, e))
    gone = []
    for (_, kind), rows in by.items():
        rows.sort(key=_order, reverse=True)
        gone += [rel for rel, e in rows[n:] if kind != "items" or e.get("sent")]
    return gone


def _order(row: tuple[str, dict]) -> tuple[str, int, str]:
    """A file's place among its store's, newest last: its time, then its number within that second (``-2``, ``-10``)."""
    rel, e = row
    seq = e.get("seq")
    return str(e.get("at", "")), seq if isinstance(seq, int) and not isinstance(seq, bool) else 1, rel


def _superseded_stale(cfg: config.Config, data: dict) -> list[str]:
    """The waiting snapshots sealed to recipients no longer their store's, each store's newest snapshot left out."""
    newest: dict[str, tuple] = {}
    for rel, e in data["files"].items():
        if isinstance(e, dict) and e.get("kind", "snapshot") == "snapshot":
            k = _order((rel, e))
            if k > newest.get(str(e.get("store", "")), ("",)):
                newest[str(e.get("store", ""))] = k
    current: dict[str, list[str]] = {}
    return [rel for rel, e in data["files"].items()
            if isinstance(e, dict) and e.get("kind", "snapshot") == "snapshot" and not e.get("sent")
            and _order((rel, e)) != newest.get(str(e.get("store", ""))) and _stale(cfg, e, current)]


def _unlink(p: Path) -> bool:
    """Whether ``p`` is gone (a lock, a permission: it stays, and so does its entry)."""
    try:
        p.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        return False
    return True


def push(cfg: config.Config, stores: list[str] | None = None, *, now: datetime | None = None,
         found: dict[str, vault.Adapter] | None = None, dry_run: bool = False) -> dict:
    """``brain spool push``: put each store of the set whose content changed since its last put (a store that fails
    is an error and the others go on; a store whose recipients changed is put again), prune, send what waits, prune
    again. ``dry_run``: the plan, nothing written. Recorded in the
    index (``last``; ``ok_at`` when nothing failed): brain health spool reads it."""
    t = _now(now)
    _, data = load_index(write=not dry_run)
    res: dict = {"put": [], "unchanged": [], "empty": [], "errors": [], "sent": [], "pruned": [],
                 "remote": str(remote(cfg) or ""), "dry_run": dry_run}
    for name in stores or chosen(cfg):
        try:
            _push_store(cfg, data, name, t, found, res)
        except (SpoolError, vault.VaultError) as exc:
            res["errors"].append(f"{name}: {exc}")
    if dry_run:
        res["pruned"] = prune(cfg, dry_run=True)
        return res
    res["pruned"] = prune(cfg)       # first: a superseded stale snapshot is not sent
    res["sent"] = send(cfg, now=t)
    res["pruned"] += prune(cfg)
    _record_push(res, t)
    return res


def _push_store(cfg: config.Config, data: dict, name: str, t: datetime, found, res: dict) -> None:
    """One store of a push: empty, unchanged (its content and its recipients), planned (a dry run) or put."""
    _, pairs = _content(cfg, name, None)
    if not pairs:
        res["empty"].append(name)
        return
    last = data["stores"].get(name) or {}
    same = last.get("recipients", []) in ([], recipients_of(cfg, vault.store(cfg, name)))
    if last.get("fingerprint") == fingerprint(pairs) and same:
        res["unchanged"].append(name)
    elif res["dry_run"]:
        res["put"].append({"store": name, "plan": True})
    else:
        res["put"].append(put(cfg, name, now=t, found=found))


def _record_push(res: dict, t: datetime) -> None:
    """The push in the index: ``last``, and ``ok_at`` when nothing failed."""
    st, data = load_index(write=True)
    failed = len(res["errors"]) + sum(1 for r in res["sent"] if r.get("error"))
    data["last"] = {"at": _iso(t), "put": len(res["put"]), "sent": sum(1 for r in res["sent"] if r.get("sent")),
                    "errors": failed}
    if not failed:
        data["ok_at"] = _iso(t)
    _save(st, data)


# --- reading it ---
def verify(*, waiting_only: bool = False) -> list[tuple[str, str]]:
    """(file, problem) for each file of the index that is missing or whose sha256 is not the index's."""
    _, data = load_index()
    out = []
    for rel, e in sorted(data["files"].items()):
        if not isinstance(e, dict) or (waiting_only and e.get("sent")):
            continue
        f = spool_dir() / rel
        if not f.is_file():
            out.append((rel, "missing"))
        else:
            try:
                if _sha256(f) != e.get("sha256"):
                    out.append((rel, "sha256 does not match the index"))
            except OSError as exc:
                out.append((rel, f"cannot be read ({exc.__class__.__name__})"))
    return out


def status(cfg: config.Config) -> dict:
    """The spool as it is: its folder, remote, set, retention, last push, and the files waiting and sent."""
    st, data = load_index()
    files = {rel: e for rel, e in data["files"].items() if isinstance(e, dict)}
    waiting = {rel: e for rel, e in files.items() if not e.get("sent")}
    return {"dir": str(spool_dir()), "remote": str(remote(cfg) or ""), "stores": chosen(cfg), "keep": keep(cfg),
            "max_age_days": max_age_days(cfg), "last": data["last"], "ok_at": data.get("ok_at", ""),
            "waiting": len(waiting), "waiting_bytes": sum(int(e.get("bytes") or 0) for e in waiting.values()),
            "sent": len(files) - len(waiting), "files": files, "readonly": st.refusal()}


def _age(d: timedelta) -> str:
    return vault._age(d)


def health(cfg: config.Config, now: datetime | None = None, out=None, named: bool = True) -> int:
    """``brain health spool``: the last push's age, what waits; a warning past ``max_age_days`` (7) or after a push
    with errors, exit 1 only when a file that waits is missing or no longer matches its sha256 (it would never arrive).
    OFF (exit 0) when nothing was ever pushed and config.json declares no spool; not named (``--all``), silent then."""
    s = status(cfg)

    def say(line: str) -> None:
        print(line, file=out, flush=True)

    if not s["files"] and not s["last"] and "spool" not in cfg.data:
        if named:
            say(f"{CHECK} OFF (never pushed, config.json declares no spool: brain spool push, by hand)")
        return 0
    t = _now(now)
    ok_at = _parse(s["ok_at"])
    where = f"remote {s['remote']}" if s["remote"] else "no remote: they wait here"
    head = (f"last push without an error {_age(t - ok_at)} ago" if ok_at else "never pushed without an error") + \
           f", {s['waiting']} file(s) waiting ({s['waiting_bytes']} bytes, {where}), {s['sent']} sent"
    bad = verify(waiting_only=True)
    if bad:
        say(f"{CHECK} FAIL ({head}): " + "; ".join(f"{rel}: {why}" for rel, why in bad))
    else:
        say(f"{CHECK} OK ({head})")
    if not ok_at or t - ok_at > timedelta(days=s["max_age_days"]):
        say(f"{CHECK} warning: no push without an error for more than {s['max_age_days']} d: brain spool push")
    if s["last"].get("errors"):
        say(f"{CHECK} warning: the last push ({s['last'].get('at')}) had {s['last']['errors']} error(s): "
            "brain spool push says which")
    return 1 if bad else 0


def render_status(s: dict) -> list[str]:
    lines = [f"spool: {s['dir']}",
             f"remote: {s['remote'] or 'none (the files wait here; spool.remote in config.json)'}",
             f"stores: {', '.join(s['stores'])}; keep {s['keep']} snapshots per store",
             "last push: " + (f"{s['last'].get('at')}: {s['last'].get('put', 0)} put, {s['last'].get('sent', 0)} "
                              f"sent, {s['last'].get('errors', 0)} error(s)" if s["last"] else "never"),
             f"waiting: {s['waiting']} file(s), {s['waiting_bytes']} bytes; sent: {s['sent']}"]
    for rel, e in sorted(s["files"].items()):
        lines.append(f"  {rel}  {e.get('kind', '?')}  {e.get('bytes', 0)} bytes  put {e.get('at', '?')}  "
                     + (f"sent {e['sent']}" if e.get("sent") else "waiting"))
    if s["readonly"]:
        lines.append(f"read-only: {s['readonly']}")
    return lines
