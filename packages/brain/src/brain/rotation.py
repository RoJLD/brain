"""The vault's recipients when they change (wi-brain-vault-rotation): a recipient taken out, the sealed files sealed
again to their store's current recipients, the end of a device key's rotation.

A sealed file opens with the keys it was sealed to, and with no other. So when ``config.json`` loses a recipient (a
lost machine, a revoked heir, a suspect key) or gains one (a new machine), or a name gets a new key (a rotation:
``brain vault device init --rotate``, then ``recipient add --replace``), the copies this machine keeps under
``$BRAIN_HOME/vault/sealed`` are stale: ``stale_seals`` lists them, from each manifest's recipients' fingerprints, and
``reseal`` seals them again (a plan, then ``apply``), opened with this machine's device key, its previous one during a
rotation (``vault.previous_key``), or the owner's key. ``forget_previous`` ends a rotation once nothing waits on it.
A copy already sent elsewhere stays readable by the keys it was sealed to: it is sealed again where it lives.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from . import classes, config, keystore, vault
from .vault import VaultError


def sealed_files() -> list[tuple[Path, dict]]:
    """Every sealed file this machine keeps under $BRAIN_HOME/vault/sealed, with its manifest ({} without one)."""
    base = vault.vault_dir() / "sealed"
    out = []
    for f in sorted(base.glob("*/*")) if base.is_dir() else []:
        if f.name.endswith((".age", ".gpg")):
            try:
                man = json.loads(f.with_name(f.name + ".json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                man = {}
            out.append((f, man if isinstance(man, dict) else {}))
    return out


def stale_seals(cfg: config.Config) -> list[dict]:
    """The sealed files whose recipients are not their store's current ones: ``gone`` still open them (a removed or
    replaced key; ``gone_recovery`` those of kind recovery), ``new`` cannot yet; ``why`` when the store is no longer
    one to seal. What ``reseal`` seals again."""
    out = []
    for f, man in sealed_files():
        name = man.get("store") or f.parent.name
        entry = {"file": str(f), "store": name, "gone": [], "gone_recovery": [], "new": [], "why": ""}
        try:
            want = {r.fingerprint(cfg.root): r.name for r in vault.for_store(cfg, vault.store(cfg, name))}
        except VaultError as exc:
            out.append({**entry, "why": str(exc)})
            continue
        have = {r.get("fingerprint", ""): r for r in man.get("recipients") or []}
        if set(have) != set(want):
            gone = [r for fp, r in have.items() if fp not in want]
            out.append({**entry, "gone": sorted(r.get("name", "?") for r in gone),
                        "gone_recovery": sorted(r.get("name", "?") for r in gone if r.get("kind") == "recovery"),
                        "new": sorted(n for fp, n in want.items() if fp not in have)})
    return out


def reseal(cfg: config.Config, apply: bool = False, only: list[str] | None = None, identity: str = "device",
           now: datetime | None = None, found: dict[str, vault.Adapter] | None = None) -> list[dict]:
    """Seal again, to its store's current recipients, each sealed file ``stale_seals`` lists (a plan unless
    ``apply``): opened with this machine's device key (its previous one mid-rotation) or the key given (``-``, a
    file), sealed again with the same adapter, the old copy replaced only once the new one is written; its manifest
    gains ``resealed``. A file is left as it is when its store would fall under its floors (``floors``) or would
    leave a recovery key for one never drilled. Each entry of the plan gains ``done`` or ``error``."""
    plan = [p for p in stale_seals(cfg) if not only or p["store"] in only]
    if not apply:
        return plan
    vault.load_state(write=True)   # refused before any file is sealed again when the record cannot be written
    found = found if found is not None else vault.adapters()
    t = vault._iso(vault._now(now))
    keys: dict[str, list] = {}
    sealed: dict[str, list[str]] = {}
    for p in plan:
        try:
            sealed[p["file"]] = _reseal_one(cfg, p, found, keys, identity, t)
            p["done"] = True
        except VaultError as exc:
            p["error"] = str(exc)
    st = vault.load_state()   # read again: a canary or a drill may have run meanwhile
    for name, seal in st["seals"].items():
        if seal.get("file") in sealed:
            seal["recipients"] = sealed[seal["file"]]
    vault.save_state(st)
    return plan


def _reseal_one(cfg: config.Config, p: dict, found: dict, keys: dict, identity: str, t: str) -> list[str]:
    """Seal one file again; the names it is now sealed to."""
    if p["why"]:
        raise VaultError(p["why"])
    f = Path(p["file"])
    ad = vault.adapter_of(f, found)
    s = vault.store(cfg, p["store"])
    recs = vault.for_store(cfg, s)
    problems = [msg for msg, _ in floors(cfg, [s])] + _unproven_recovery(cfg, p, recs)
    if problems:
        raise VaultError("; ".join(problems))
    lacking = [r.name for r in recs if not r.key(ad.name, cfg.root)]
    if lacking:
        raise VaultError(f"no {ad.name} key for {', '.join(lacking)}")
    mf = f.with_name(f.name + ".json")
    try:
        man = json.loads(mf.read_text(encoding="utf-8")) if mf.is_file() else {"v": 1, "store": p["store"]}
    except (OSError, ValueError):
        raise VaultError(f"{mf.name}: unreadable (remove it, then brain vault reseal again)") from None
    if ad.name not in keys:
        keys[ad.name] = vault._keys(cfg, ad, identity)
    with vault._private_dir("r") as tmp:
        vault._open_with(ad, f, tmp / "plain", keys[ad.name])
        part = f.with_name(f.name + ".part")
        ad.seal(tmp / "plain", part, [r.key(ad.name, cfg.root) for r in recs])
        os.replace(part, f)
    man.update(recipients=[{"name": r.name, "kind": r.kind, "fingerprint": r.fingerprint(cfg.root)} for r in recs],
               resealed=t, bytes=f.stat().st_size, sha256=vault._sha256(f))
    vault._write_atomic(mf, json.dumps(man, indent=2) + "\n")
    return [r.name for r in recs]


def _unproven_recovery(cfg: config.Config, p: dict, recs: list) -> list[str]:
    """A file that would leave a recovery key: kept until one of the store's recovery keys was drilled (a mistyped
    paper key would otherwise be the only way back)."""
    if not p.get("gone_recovery"):
        return []
    st = vault.load_state()
    if any(r.kind == "recovery" and vault.drilled_at(st, r.name, r.fingerprint(cfg.root)) for r in recs):
        return []
    return [f"{Path(p['file']).name} would leave its recovery key for one never drilled: brain vault canary, then "
            "brain vault drill <recovery> in your own terminal, then reseal"]


def sealable(cfg: config.Config) -> list[classes.Store]:
    """The declared stores whose class seals them when they leave (private, confidential, sealed, a tenant's)."""
    declared, _ = classes.stores(cfg)
    return [s for s in declared if "sealed" in classes.POLICY.get(s.kind, {}).values()]


def floors(cfg: config.Config, stores: list[classes.Store] | None = None) -> list[tuple[str, bool]]:
    """Each store under its floors, as (problem, fatal): fewer distinct keys than ``min_recipients`` (fatal: it can
    no longer be sealed), or a root store sealed to no recovery key (a lost machine would lock it)."""
    need = vault.min_recipients(cfg)
    out = []
    for s in stores if stores is not None else sealable(cfg):
        try:
            recs = vault.for_store(cfg, s)
        except VaultError:
            continue
        if not recs:   # none declared for it (a tenant not set up yet): nothing it could be sealed to
            continue
        keys = {r.fingerprint(cfg.root) for r in recs}
        if len(keys) < need:
            out.append((f"store {s.name} has {len(keys)} distinct key(s): {need} at least", True))
        elif s.kind != "tenant" and not any(r.kind == "recovery" for r in recs):
            out.append((f"store {s.name} is sealed to no recovery key", False))
    return out


def recipient_remove(cfg: config.Config, name: str, write: bool = False) -> tuple[dict, bool]:
    """Take a recipient out of config.json (a plan, or --write): a lost machine, a revoked heir, a suspect key. Refused
    when fewer than ``min_recipients`` would be left, for the only recovery key, or while a tenant or a scope still
    names it. The plan lists this machine's sealed files that still open with its key: ``reseal`` is next."""
    if not cfg.file:
        raise VaultError("no config.json to remove a recipient from")
    recs, _ = vault.recipients(cfg)
    _removable(cfg, recs, name)
    sealed_to = [str(f) for f, man in sealed_files() if any(r.get("name") == name for r in man.get("recipients") or [])]
    plan = {"remove": name, "left": sorted(n for n in recs if n != name), "reseal": sealed_to}
    if not write:
        return plan, False
    data = json.loads(cfg.file.read_text(encoding="utf-8"))
    del data["vault"]["recipients"][name]
    cfg.file.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return plan, True


def _removable(cfg: config.Config, recs: dict, name: str) -> None:
    if name not in recs:
        raise VaultError(f"no recipient {name} in config.json")
    rest = [r for n, r in recs.items() if n != name]
    need = vault.min_recipients(cfg)
    if len(rest) < need:
        raise VaultError(f"{len(rest)} recipient(s) would be left: a sealed store needs {need} at least; declare its "
                         "successor first (brain vault recipient add)")
    if recs[name].kind == "recovery" and not any(r.kind == "recovery" for r in rest):
        raise VaultError(f"{name} is the only recovery key: declare the new one first")
    users = named_in(cfg, name)
    if users:
        raise VaultError(f"{name} is still named in {', '.join(users)}: take it out there first")
    data = json.loads(json.dumps(cfg.data))
    del data["vault"]["recipients"][name]
    before = {msg for msg, _ in floors(cfg)}
    worse = [msg for msg, _ in floors(config.Config(cfg.file, cfg.root, data)) if msg not in before]
    if worse:   # each store on its own: a tenant's or a scope's key does not stand for the owner's stores
        raise VaultError(f"without {name}, " + "; ".join(worse) + ": declare its successor first")


def named_in(cfg: config.Config, name: str) -> list[str]:
    """Where a recipient is named besides its own entry: ``vault.tenants`` and the scope nodes' ``vault.recipients``."""
    users = [f"vault.tenants.{t}" for t, ns in (vault._block(cfg).get("tenants") or {}).items() if name in (ns or [])]
    for node, d in classes.scope_nodes(cfg).items():
        v = d.get("vault") if isinstance(d.get("vault"), dict) else {}
        if name in (v.get("recipients") or []):
            users.append(f"scopes {node}")
    return users


def forget_previous(cfg: config.Config, found: dict[str, vault.Adapter] | None = None) -> dict:
    """End a rotation: delete the previous device key from the keystore, once config.json declares the new one and
    no sealed file of this machine still waits on a re-seal."""
    ks = keystore.backend()
    dev = vault.device()
    prev = dev.get("previous")
    if ks is None or not prev or not ks.get(vault.previous_key(cfg)):
        raise VaultError("no previous device key on this machine: nothing to forget")
    recs, _ = vault.recipients(cfg)
    ad = (found if found is not None else vault.adapters()).get(dev.get("adapter", ""))
    mine = recs.get(dev.get("name", ""))
    if ad is None or mine is None or ad.public_id(mine.key(ad.name, cfg.root)) != dev.get("public"):
        raise VaultError(f"config.json does not declare the new key of {dev.get('name')} yet: "
                         f"{dev.get('declare', 'brain vault recipient add ... --replace --write')} (a PR), then pull")
    still = [n for n, r in recs.items() if r.key(ad.name, cfg.root) and ad.public_id(r.key(ad.name, cfg.root))
             == prev.get("public")]
    if still:
        raise VaultError(f"config.json still declares the previous key (as {', '.join(still)}): take it out first, "
                         "or it stays a recipient nobody holds")
    stale = stale_seals(cfg)
    if stale:
        raise VaultError(f"{len(stale)} sealed file(s) are not sealed to the current recipients yet: brain vault "
                         "reseal --apply first")
    ks.delete(vault.previous_key(cfg))
    dev.pop("previous")
    vault._write_atomic(vault.device_file(), json.dumps(dev, indent=2) + "\n")
    return {"name": dev.get("name"), "forgot": prev.get("public", "")}
