"""``brain vault``: seal stores to public recipients; the device key, the canaries, the drill (brain.vault)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .. import config, keystore, rotation, vault

ORDER = 250   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 290   # its usage lines' place in brain --help's epilog
RUNS_VIA = {   # brain perf --usage: how a subcommand that may never run from the CLI is reached (brain.adoption)
    "vault device": "on demand: an owner's gesture of the vault's setup, rotation or recovery (docs/vault.md)",
    "vault drill": "on demand: an owner's gesture of the vault's setup, rotation or recovery (docs/vault.md)",
    "vault open": "on demand: an owner's gesture of the vault's setup, rotation or recovery (docs/vault.md)",
    "vault reseal": "on demand: an owner's gesture of the vault's setup, rotation or recovery (docs/vault.md)",
    "vault seal": "on demand: an owner's gesture of the vault's setup, rotation or recovery (docs/vault.md)",
}
USAGE = """\
  brain vault status [--json]   adapters (age, gpg), the keystore, this machine's device key (public facts), every
                 recipient with its fingerprint and last canary, the last seal per store, and the steps left to the
                 owner with their exact commands
  brain vault seal STORE [PATH...] [--out FILE] [--adapter age|gpg]   seal a store (its declared content, or the
                 paths) client-side to its recipients, public keys only, unattended; refuses a resident or secret
                 store and fewer than two recipients; a manifest beside the sealed file
  brain vault canary   seal a fresh nonce to each recipient alone, open the one this machine's device key opens,
                 compare the digests ($BRAIN_HOME/vault/state.json): the daily proof, the scheduled task's command
  brain vault recipient add NAME --kind device|recovery|hardware|person (--age KEY | --gpg FILE) [--host H]
                 [--replace] [--write]   declare a public recipient in config.json (a plan without --write); refuses
                 a private key, and a declared name unless --replace (a rotation)
  brain vault recipient remove NAME [--write]   take a recipient out (a lost machine, a revoked heir, a suspect key);
                 refused below two recipients, for the only recovery key, or while a tenant or a scope names it
  brain vault reseal [STORE...] [--apply] [--identity FILE|-]   seal again, to their store's current recipients, the
                 sealed files that are not (a removed or replaced key, a new recipient): the plan, or --apply; opened
                 with this machine's device key (then its previous one) or the key given (the owner's terminal only)
  brain vault device init [--name N] [--adapter age|gpg] [--rotate]   this machine's device key, created straight
                 into the OS keystore; prints its public half only; --rotate replaces it and keeps the previous one
                 until forget-previous (the owner's terminal only)
  brain vault device forget-previous   end a rotation once config.json declares the new key and nothing waits on a
                 re-seal: the previous key is deleted from the keystore (the owner's terminal only)
  brain vault open FILE [--out DIR] [--identity FILE|-]   open a sealed file with the device key, a key file or a
                 key typed hidden (-) (the owner's terminal only: refused in an agent session)
  brain vault drill RECIPIENT [--identity FILE|-]   open that recipient's canary with its key and record the proof:
                 the recovery key's yearly drill (the owner's terminal only)
"""


def cmd_vault(args, root: Path) -> int:
    """``brain vault``: status, seal, canary, recipient add and remove, reseal, device init and forget-previous, open,
    drill (brain.vault). Open, drill, device init and forget-previous, and a reseal with a key given are the owner's
    acts: refused in an agent session. Exit 2 on a refusal."""
    cfg = config.load(root)
    try:
        if args.vault_cmd == "status":
            s = vault.status(cfg)
            print(json.dumps(s, indent=1, sort_keys=True) if args.json else "\n".join(vault.render_status(s)))
            return 1 if s["errors"] else 0
        if args.vault_cmd == "seal":
            man = vault.seal(cfg, args.store, [Path(p) for p in args.paths] or None,
                             Path(args.out) if args.out else None, args.adapter)
            print(f"sealed {man['store']} ({man['class']}, {man['files']} file(s)) to "
                  f"{', '.join(r['name'] for r in man['recipients'])} with {man['adapter']}: "
                  f"{vault.vault_dir() / 'sealed' / man['store'] / man['file'] if not args.out else args.out}")
            return 0
        if args.vault_cmd == "canary":
            res = vault.canary(cfg)
            for name, e in res.items():
                print(f"{name}: " + (f"error: {e['error']}" if e["error"] else
                                     f"sealed ({e['adapter']})" + (", opened by this machine's key"
                                                                   if e.get("opened_at") else "")))
            return 1 if any(e["error"] for e in res.values()) else 0
        if args.vault_cmd == "recipient" and args.recipient_cmd == "remove":
            plan, written = rotation.recipient_remove(cfg, args.name, args.write)
            print(f"remove {plan['remove']}; left: {', '.join(plan['left'])}")
            for f in plan["reseal"]:
                print(f"  still opens with its key: {f}")
            print(f"written to {cfg.file}; then brain vault reseal --apply" if written
                  else "plan only: run again with --write to remove it")
            return 0
        if args.vault_cmd == "recipient":
            entry, written = vault.recipient_add(cfg, args.name, args.kind, args.age or "", args.gpg or "",
                                                 args.host or "", args.write, args.replace)
            print(json.dumps({args.name: entry}))
            print(f"written to {cfg.file}" if written else "plan only: run again with --write to add it")
            return 0
        if args.vault_cmd == "reseal":
            if args.identity:
                vault.human_only("brain vault reseal --identity")
            plan = rotation.reseal(cfg, args.apply, args.stores or None, args.identity or "device")
            for p in plan:
                state = ("done" if p.get("done") else f"error: {p['error']}" if p.get("error") else "to re-seal")
                why = p["why"] or ", ".join(x for x in (f"gone: {' '.join(p['gone'])}" if p["gone"] else "",
                                                         f"new: {' '.join(p['new'])}" if p["new"] else "") if x)
                print(f"{state}: {p['file']} ({p['store']}; {why})")
            print("nothing to re-seal" if not plan else "" if args.apply else "plan only: run again with --apply")
            return 1 if any(p.get("error") for p in plan) else 0
        if args.vault_cmd == "device" and args.device_cmd == "forget-previous":
            vault.human_only("brain vault device forget-previous")
            res = rotation.forget_previous(cfg)
            print(f"{res['name']}: the previous device key is deleted from the keystore")
            return 0
        if args.vault_cmd == "device":
            vault.human_only("brain vault device init")
            facts = vault.device_init(cfg, args.name, args.adapter, rotate=args.rotate)
            print(f"device key {facts['name']} ({facts['adapter']}) created in the keystore ({facts['keystore']})"
                  + ("; the previous one is kept until brain vault device forget-previous" if args.rotate else ""))
            print(f"public: {facts['public']}")
            print(f"declare it (a PR): {facts['declare']}")
            if args.rotate:
                print("then: brain vault reseal --apply, brain vault canary, brain vault device forget-previous")
            return 0
        if args.vault_cmd == "open":
            vault.human_only("brain vault open")
            sealed = Path(args.file)
            out = Path(args.out) if args.out else sealed.with_name(sealed.name.split(".")[0] + ".opened")
            res = vault.open_sealed(cfg, sealed, out, args.identity or "device")
            print(f"opened {sealed.name} into {res['out']} ({res['entries']} entries)")
            return 0
        if args.vault_cmd == "drill":
            vault.human_only("brain vault drill")
            res = vault.drill(cfg, args.recipient, args.identity or "-")
            print(f"{res['recipient']}: its canary opened and matched, drilled at {res['drilled_at']}")
            return 0
    except (vault.VaultError, keystore.KeystoreError) as exc:
        print(f"brain vault {args.vault_cmd}: {exc}", file=sys.stderr)
        return 2
    return 2


def register(sub, ctx) -> None:
    va = sub.add_parser("vault", help="seal stores to public recipients; the device key, the canaries, the drill "
                                      "(brain.vault)").add_subparsers(dest="vault_cmd", required=True)
    vs = va.add_parser("status", help="adapters, keystore, device key, recipients, last canaries and seals, the "
                                      "steps left to the owner")
    vs.add_argument("--json", action="store_true", help="stable keys")
    vl = va.add_parser("seal", help="seal a store to its recipients (public keys only, unattended)")
    vl.add_argument("store", help="a store of config.json classes.stores")
    vl.add_argument("paths", nargs="*", metavar="PATH", help="what to seal instead of the store's declared content")
    vl.add_argument("--out", help="the sealed file (default $BRAIN_HOME/vault/sealed/<store>/)")
    vl.add_argument("--adapter", choices=vault.ADAPTERS, help="age or gpg (default: config's, else age, else gpg)")
    va.add_parser("canary", help="the daily proof: a nonce sealed to each recipient alone, opened by this machine's "
                                 "device key")
    vr = va.add_parser("recipient", help="declare a public recipient").add_subparsers(dest="recipient_cmd",
                                                                                       required=True)
    vra = vr.add_parser("add", help="a plan, or --write into config.json; refuses a private key")
    vra.add_argument("name", help="kebab-case: the machine for a device key, recovery for the recovery key")
    vra.add_argument("--kind", required=True, choices=vault.KINDS)
    key = vra.add_mutually_exclusive_group(required=True)
    key.add_argument("--age", help="an age1... recipient or an ssh-ed25519 public key")
    key.add_argument("--gpg", help="an armored gpg public key file (copied into vault/keys/)")
    vra.add_argument("--host", help="the machine a device key belongs to")
    vra.add_argument("--replace", action="store_true", help="give a declared name this key (a rotation)")
    vra.add_argument("--write", action="store_true", help="write config.json")
    vrr = vr.add_parser("remove", help="a plan, or --write: take a recipient out of config.json (a lost machine, a "
                                       "revoked heir, a suspect key); then brain vault reseal")
    vrr.add_argument("name")
    vrr.add_argument("--write", action="store_true", help="write config.json")
    vre = va.add_parser("reseal", help="seal again, to their store's current recipients, the sealed files that are "
                                       "not (a plan, or --apply)")
    vre.add_argument("stores", nargs="*", metavar="STORE", help="only these stores")
    vre.add_argument("--apply", action="store_true", help="re-seal them")
    vre.add_argument("--identity", help="a key file, or - to type or paste it, hidden (default: this machine's "
                                        "device key, then its previous one; the owner's terminal only)")
    vd = va.add_parser("device", help="this machine's device key").add_subparsers(dest="device_cmd", required=True)
    vdi = vd.add_parser("init", help="create it straight into the OS keystore, print its public half (the "
                                     "owner's terminal only)")
    vdi.add_argument("--name", help="kebab-case (default: this machine's name)")
    vdi.add_argument("--adapter", choices=vault.ADAPTERS, help="age or gpg (default: age when found)")
    vdi.add_argument("--rotate", action="store_true", help="replace the existing key; the previous one is kept "
                                                           "until forget-previous")
    vd.add_parser("forget-previous", help="end a rotation: delete the previous key, once config.json declares the "
                                          "new one and nothing waits on a re-seal (the owner's terminal only)")
    vo = va.add_parser("open", help="open a sealed file (the owner's terminal only)")
    vo.add_argument("file")
    vo.add_argument("--out", help="the folder to open into (default: <name>.opened beside the file)")
    vo.add_argument("--identity", help="a key file, or - to type or paste it, hidden (default: the device key)")
    vi = va.add_parser("drill", help="open a recipient's canary with its key and record the proof (the owner's "
                                     "terminal only)")
    vi.add_argument("recipient")
    vi.add_argument("--identity", help="a key file, or - to type or paste it, hidden (default -)")


run = cmd_vault
