"""A brain's identity, standalone (wi-brain-identity; spec-brain-vault-heirs-identity 3.8, the owner's answers of
2026-11-02 and 2026-11-04, the 0.3.1 scope of 2026-11-10): who belongs to the brain (``members.yaml``) and which
answers the owner signed.

- ``members.yaml``, at the brain's root next to config.json (``schemas/members.schema.json``): the people with their
  public signing keys (SSH ed25519) and encryption recipients (age), their accounts, the organizations and tenants,
  and the memberships with their roles; ``decider`` is the role whose key verifies an owner-decides answer.
- **The owner-decides class**: a decision whose text touches money, keys, accounts, visibility, heirs or scheduled
  tasks (:data:`OWNER_CLASS`, the words of brain.defaults plus heirs). Its answer may carry a **detached signature**,
  ``records/ddr/<id>.sig``, next to the record: an SSH signature (namespace ``brain-decision``) over
  :func:`payload`, the answer as the owner read it. The record's format does not move: an older engine reads the
  record and ignores the file.
- **Unsigned**: such an answer without its signature, relayed by a session (the question tool) or typed in a
  terminal; ``brain decision view`` marks it, ``brain identity unsigned`` lists it, ``brain check`` reports it.
- :func:`check` (``brain check``, ``brain identity check``): members.yaml's schema and references, then each
  owner-decides answer recorded from the deciders' earliest ``since``: unsigned, or a signature that does not verify.
  **Warnings by default**; errors under config.json ``identity.require_signed: true``, the owner's opt-in (the merge
  lock of 2026-11-04). Without members.yaml nothing is checked.
- ``releaser`` is the role whose keys verify a signed engine release tag: brain.tagsig generates ``allowed_signers``
  from it (``brain identity allowed-signers``).

The engine only verifies, with public keys (brain.sshsig): no session generates, reads, stores or prints a private key.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from . import config, defaults, graph, records, schema, secretscan, sshsig

FILE = "members.yaml"
SIG = ".sig"
DECIDER = "decider"
OWNER_CLASS = ("money", "keys", "accounts", "visibility", "heirs", "scheduled tasks")
_HEIRS = re.compile(r"(?<![^\W_])(?:heirs?|inherit\w*|succession|héritiers?|héritières?|testament|dead[ _-]man)"
                    r"(?![^\W_])", re.I)
RELAYED = ("ask-tool", "chat")   # answer.via of an answer a session carried from the owner


class IdentityError(ValueError):
    """A refusal of brain identity (exit 1)."""


@dataclass
class Members:
    file: Path
    data: dict
    errors: list[str]


# --- members.yaml ---

def members_file(root: Path) -> Path:
    """members.yaml beside the brain's config.json, else at ``root``."""
    cfg = config.load(root)
    return (cfg.file.parent if cfg.file else Path(root)) / FILE


def load(root: Path) -> Members | None:
    """The brain's members.yaml with its errors (schema, references, secrets), None when there is none."""
    f = members_file(root)
    if not f.is_file():
        return None
    try:
        data = graph.load_yaml_file(f)
    except Exception as exc:   # a YAML error, a conflict marker
        return Members(f, {}, [f"{FILE}: not readable YAML ({type(exc).__name__})"])
    if not isinstance(data, dict):
        return Members(f, {}, [f"{FILE}: a mapping, got {type(data).__name__}"])
    data = plain(data)
    errors = [f"{FILE}: {e}" for e in schema.check("members", data, schema.mode())[0]]
    errors += [f"{FILE}: {e}" for e in _references(data)]
    text = f.read_text(encoding="utf-8", errors="replace")
    errors += [f"{FILE}:{line}: matches secret pattern {name} (public keys only)"
               for line, name in secretscan.scan_lines(text)]
    return Members(f, data, errors)


def plain(value):
    """``value`` with its YAML dates as the ISO text the owner wrote (``since: 2026-11-10`` unquoted)."""
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [plain(v) for v in value]
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def _list(data: dict, key: str) -> list[dict]:
    items = data.get(key)
    return [x for x in items if isinstance(x, dict)] if isinstance(items, list) else []


def _id(x: dict, key: str = "person_id") -> str | None:
    """``x[key]`` when it is text, else None: a wrong type is the schema's error, never a crash here."""
    v = x.get(key)
    return v if isinstance(v, str) else None


def _references(data: dict) -> list[str]:
    """What the schema cannot say: unique ids, and every person, organization and tenant named exists."""
    people = [_id(p) for p in _list(data, "people")]
    dupes = {p for p in people if p is not None and people.count(p) > 1}
    errors = [f"people: person_id {p!r} is declared twice" for p in sorted(dupes)]
    errors += [f"{key}[{i}]: person_id {x.get('person_id')!r} is not in people"
               for key in ("accounts", "memberships") for i, x in enumerate(_list(data, key))
               if _id(x) is None or _id(x) not in people]
    return errors + _org_references(data)


def _org_references(data: dict) -> list[str]:
    """Each membership's organization or tenant is declared with that kind."""
    orgs = {_id(o, "id"): o.get("kind") or "organization" for o in _list(data, "organizations")}
    return [f"memberships[{i}]: {key} {m[key]!r} is not in organizations with kind {key}"
            for i, m in enumerate(_list(data, "memberships")) for key in ("organization", "tenant")
            if m.get(key) and (_id(m, key) is None or orgs.get(m[key]) != key)]


def deciders(data: dict, project: str = "") -> dict[str, list[dict]]:
    """{person_id: their signing keys not revoked} for the people with the decider role on the whole brain or on
    ``project``."""
    who = {_id(m) for m in _list(data, "memberships") if _decides(m, project)} - {None}
    return {p["person_id"]: _signing(p) for p in _list(data, "people") if _id(p) in who}


def _decides(membership: dict, project: str) -> bool:
    """Whether a membership gives the decider role on the whole brain or on ``project`` (not an organization's or a
    tenant's: another identity domain)."""
    roles = membership.get("roles")
    if not isinstance(roles, list) or DECIDER not in roles:
        return False
    if membership.get("organization") or membership.get("tenant"):
        return False
    return membership.get("project") in (None, "", project)


def _signing(person: dict) -> list[dict]:
    """A person's signing keys that still count (a key, not revoked)."""
    keys = person.get("keys")
    keys = keys.get("signing") if isinstance(keys, dict) else None
    return [k for k in keys if isinstance(k, dict) and _id(k, "key") and not k.get("revoked")] \
        if isinstance(keys, list) else []


def since(keys: dict[str, list[dict]]) -> str | None:
    """The day signatures start to count: the earliest ``since`` of the deciders' keys, '' (every answer) when a key
    has none; None when no decider has a key (then no answer is checked)."""
    days = [str(k.get("since") or "") for ks in keys.values() for k in ks]
    return None if not days else "" if "" in days else min(days)


# --- the owner-decides class and the payload ---

def owner_class(ddr: dict) -> list[str]:
    """The owner-decides topics the DDR's text touches (brain.defaults' words, plus heirs)."""
    hits = [t for t, _ in defaults.topics(ddr) if t in OWNER_CLASS]
    if _HEIRS.search(defaults._text(ddr)):
        hits.append("heirs")
    return hits


def payload(ddr: dict) -> bytes:
    """What a signature covers: the question as asked and the answer as recorded, in a stable JSON text the owner
    reads before signing. Any later change of them (an answer --again) voids the signature."""
    a = ddr.get("answer") or {}
    body = {"namespace": sshsig.NAMESPACE, "id": ddr.get("id"), "title": ddr.get("title"),
            "question": ddr.get("question"),
            "options": [o.get("label") for o in ddr.get("options") or [] if isinstance(o, dict)],
            "answer": {k: a[k] for k in ("at", "by", "choices", "other", "notes") if k in a}}
    return (json.dumps(body, sort_keys=True, ensure_ascii=False, indent=1, default=str) + "\n").encode("utf-8")


def sig_file(ddr_file: Path) -> Path:
    return ddr_file.with_suffix(SIG)


def _answered(ddr: dict) -> bool:
    a = ddr.get("answer")
    return (isinstance(a, dict) and ddr.get("status") in ("answered", "integrated", "archived")
            and (ddr.get("kind") or "decision") == "decision" and a.get("via") != defaults.VIA)


def needs_signature(ddr: dict, start: str | None) -> list[str]:
    """The owner-decides topics of an answered decision recorded from ``start`` on ([] when it needs none, and
    always when ``start`` is None: no decider's key to sign with)."""
    if start is None or not _answered(ddr) or str(ddr["answer"].get("at", ""))[:10] < start:
        return []
    return owner_class(ddr)


def relayed(ddr: dict) -> str:
    """How an unsigned answer came: 'relayed by session S (ask-tool)', or 'recorded via cli'."""
    a = ddr.get("answer") or {}
    via = a.get("via") or "cli"
    if via in RELAYED or a.get("session"):
        return f"relayed by session {a.get('session') or (ddr.get('asked') or {}).get('by') or '?'} ({via})"
    return f"recorded via {via}"


def marks(root: Path, project: str = "") -> dict[str, str]:
    """{DDR id: 'signed', 'unverified' or 'unsigned'} for the owner-decides answers the board marks, {} without
    members.yaml: 'signed' only when the signature file verifies (a decider's public key, ssh-keygen), 'unverified'
    when it is there but does not (an answer changed after it, another key, a revoked key, no ssh-keygen here)."""
    m = load(root)
    if m is None:
        return {}
    keys = deciders(m.data, project)
    start, exe = since(keys), sshsig.tool()
    return {d["id"]: _mark(f, d, keys, exe) for f, d in records.load(root)["ddr"] if needs_signature(d, start)}


def _mark(f: Path, ddr: dict, keys: dict[str, list[dict]], exe: str) -> str:
    if not sig_file(f).is_file():
        return "unsigned"
    return "unverified" if _verify_lines(f, ddr, keys, exe) else "signed"


# --- the check ---

def require_signed(root: Path) -> bool:
    """config.json identity.require_signed: the owner's opt-in that turns this check's warnings into errors."""
    ident = config.load(root).data.get("identity")
    return isinstance(ident, dict) and ident.get("require_signed") is True


def _verify_lines(f: Path, ddr: dict, keys: dict[str, list[dict]], exe: str) -> list[str]:
    rel = f"{records.RECORDS_DIR}/ddr/{sig_file(f).name}"
    if not _answered(ddr):
        return [f"{rel}: a signature of a decision with no answer ({ddr.get('status')})"]
    person, why = sshsig.verify(payload(ddr), sig_file(f).read_bytes(), _public(keys), exe=exe)
    return [] if person else [f"{rel}: {why}"]


def _public(keys: dict[str, list[dict]]) -> dict[str, list[str]]:
    return {p: [k["key"] for k in ks] for p, ks in keys.items() if ks}


def problems(root: Path, project: str = "") -> list[str]:
    """members.yaml's errors, then each owner-decides answer unsigned or whose signature does not verify, and each
    signature file that verifies nothing; [] without members.yaml."""
    m = load(root)
    if m is None:
        return []
    out = list(m.errors)
    keys = deciders(m.data, project)
    if not m.errors and not any(keys.values()):
        out.append(f"{FILE}: no person has the {DECIDER} role with a signing key: no answer can be verified")
    start, exe = since(keys), sshsig.tool()
    for f, d in records.load(root)["ddr"]:
        rel = f"{records.RECORDS_DIR}/ddr/{f.name}"
        if sig_file(f).is_file():
            out += _verify_lines(f, d, keys, exe)
            continue
        topics = needs_signature(d, start)
        if topics:
            out.append(f"{rel}: an owner-decides answer ({', '.join(topics)}) is unsigned, {relayed(d)}: the owner "
                       f"signs it (brain identity unsigned)")
    return out


def check(root: Path, project: str = "") -> tuple[list[str], list[str]]:
    """(errors, warnings): :func:`problems` are errors under identity.require_signed, warnings otherwise; the release
    signers' file (brain.tagsig: stale, or missing under engine.verify_tags) is always a warning."""
    from . import tagsig

    found = problems(root, project)
    errors, warnings = (found, []) if require_signed(root) else ([], found)
    return errors, warnings + tagsig.problems(root)


# --- the owner's signing: the payloads out, the signatures in ---

def unsigned(root: Path, project: str = "") -> list[tuple[Path, dict, list[str]]]:
    """(record file, DDR, topics) of each owner-decides answer without its signature file."""
    m = load(root)
    if m is None:
        raise IdentityError(f"no {FILE} at {members_file(root).parent}: declare the deciders first (docs/identity.md)")
    start = since(deciders(m.data, project))
    return [(f, d, t) for f, d in records.load(root)["ddr"] if not sig_file(f).is_file()
            for t in [needs_signature(d, start)] if t]


def write_payloads(entries: list[tuple[Path, dict, list[str]]], out: Path) -> list[Path]:
    """Each answer's payload as ``out/<id>.txt``, for the owner to read, then sign in one go."""
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for _, d, _ in entries:
        f = out / f"{d['id']}.txt"
        f.write_bytes(payload(d))
        written.append(f)
    return written


def attach(root: Path, files: list[Path], project: str = "") -> list[str]:
    """Each ``<id>.txt.sig`` (or ``<id>.sig``) the owner made, verified against the answer as recorded and the
    deciders' keys, then copied beside its record as ``records/ddr/<id>.sig``. Refused, with nothing copied, when one
    does not verify or its decision has no answer yet."""
    m = load(root)
    if m is None or m.errors:
        raise IdentityError("; ".join(m.errors) if m else f"no {FILE}: declare the deciders first")
    keys = _public(deciders(m.data, project))
    by_id = {d.get("id"): (f, d) for f, d in records.load(root)["ddr"]}
    plan = []
    for s in files:
        ddr_id = s.name.removesuffix(SIG).removesuffix(".txt")
        if ddr_id not in by_id:
            raise IdentityError(f"{s.name}: no DDR {ddr_id} in {records.RECORDS_DIR}/ddr")
        f, d = by_id[ddr_id]
        if not _answered(d):   # a payload of a pending question: an answer recorded later voids it
            raise IdentityError(f"{s.name}: {ddr_id} has no answer to sign ({d.get('status')})")
        person, why = sshsig.verify(payload(d), s.read_bytes(), keys)
        if not person:
            raise IdentityError(f"{s.name}: {why}")
        plan.append((s, sig_file(f), person))
    for s, dest, _ in plan:
        shutil.copyfile(s, dest)
    return [f"{dest.stem}: signed by {person}" for _, dest, person in plan]
