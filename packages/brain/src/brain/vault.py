"""brain vault: seal stores to public recipients (wi-brain-vault; spec-brain-vault-heirs-identity §3.3, §3.4).

Sealing needs no secret, only opening does. A store leaves the machine sealed client-side to the **public** keys of
its recipients (age, gpg as the fallback, both adapters around their command), unattended, with no private key in a
hook, a scheduled task's command line or the repo. Opening is a human act in the owner's own terminal: ``brain vault
open``, ``drill`` and ``device init`` refuse to run in an agent session (:func:`agent_session`).

The keys, from config.json's ``vault`` (public keys only; ``brain vault recipient add`` refuses anything private)::

    "vault": {"adapter": "age", "min_recipients": 2,
              "recipients": {"box1": {"kind": "device", "age": "age1...", "host": "box1"},
                             "recovery": {"kind": "recovery", "age": "age1..."},
                             "box1-gpg": {"kind": "device", "gpg": "vault/keys/box1-gpg.asc"}},
              "tenants": {"team-z": ["z-ada", "z-bob"]}}

- **device**: one per machine, created by ``brain vault device init`` straight into the OS keystore
  (brain.keystore), its public half printed to declare; the canary opens with it, unattended.
- **recovery**: offline, on paper, created by the owner in their own terminal (``age-keygen``), later split for the
  heirs (wi-brain-heirs); a recipient of everything sealed, proven by the yearly drill (``brain vault drill``).
- **hardware**, **person**: a YubiKey (age-plugin-yubikey), a member's key.

A store (brain.classes) is sealed to the union of the root's recipients (those no scope node and no tenant names,
filtered by their optional ``classes``) and the recipients the nodes of its scope chain add (``vault: {recipients}``
in scopes.yaml, spec-brain-scope-tree §3.9); a ``tenant:<id>`` store to its tenant's recipients only. Every seal
needs ``min_recipients`` (two at least: a device key and the recovery key); a ``resident`` or ``secret`` store never
leaves, even sealed.

The proof (the lesson of a backup that failed four times unseen): ``brain vault canary``, daily, seals a fresh
random nonce to each recipient alone, then opens what this machine can open (its device key) and compares the
digests; ``brain health vault`` fails when a canary is missing, failing or older than ``canary_hours`` (26), and
warns when the recovery key was never drilled or not for a year. Everything lives in ``$BRAIN_HOME/vault``:
``state.json``, ``device.json`` (public facts), ``canary/``, ``sealed/<store>/`` (each with a manifest).
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import classes, config, keystore, paths

CHECK = "vault"                          # brain health vault
KINDS = ("device", "recovery", "hardware", "person")
ADAPTERS = ("age", "gpg")
MIN_RECIPIENTS = 2
CANARY_HOURS = 26
DRILL_DAYS = 400
NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
AGE_KEY = re.compile(r"^age1[0-9a-z]{20,}$")                      # X25519 and plugin recipients, bech32 lower case
SSH_KEY = re.compile(r"^(ssh-ed25519|ssh-rsa) [A-Za-z0-9+/]+={0,3}( \S.*)?$")
PRIVATE = re.compile(r"AGE-SECRET-KEY-|AGE-PLUGIN-[A-Z0-9-]+-1|PRIVATE KEY")   # what never enters the repo
PGP_PUBLIC = "BEGIN PGP PUBLIC KEY BLOCK"
VAULT_KEYS = {"adapter", "min_recipients", "canary_hours", "recipients", "tenants"}
RECIPIENT_KEYS = {"kind", "age", "gpg", "host", "classes", "why"}
AGENT_ENV = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "BRAIN_AGENT_SESSION")
AGE_SECRET = re.compile(r"^AGE-(SECRET-KEY|PLUGIN-[A-Z0-9-]+)-1[0-9A-Z]+$")   # an identity line, never stored
KEY_PROMPT = "the key, AGE-SECRET-KEY-1... (hidden as you paste or type it), then Enter: "
NOT_ON_PATH ="not found on this terminal's PATH (a terminal opened before the install misses it: open a new one)"
RUNBOOK = "https://github.com/RoJLD/brain/blob/main/packages/brain/docs/vault.md"   # the owner's steps, generic


class VaultError(RuntimeError):
    """A refusal or a failure of the vault: its message never holds a key."""


def agent_session() -> str:
    """The variable that marks an agent's session ('' in the owner's own terminal): opening, drilling and creating a
    key refuse to run there. Decrypting is a human act (spec §3.4)."""
    return next((v for v in AGENT_ENV if os.environ.get(v)), "")


def human_only(what: str) -> None:
    var = agent_session()
    if var:
        raise VaultError(f"{what} is a human act: run it in your own terminal, not in an agent session ({var} is set)")


def ask_key(read=None) -> str:
    """The owner's age key, typed or pasted in their terminal and hidden (no echo, nothing in the scrollback, Enter
    ends it, the same in every terminal); checked for its shape, then handed to age on its stdin and never written. A
    stdin that is not a terminal (a pipe, a terminal Python cannot hide input in) gives its first line."""
    if read is None:
        read = getpass.getpass if sys.stdin is not None and sys.stdin.isatty() else _read_line
    try:
        key = read(KEY_PROMPT).strip()
    except (EOFError, KeyboardInterrupt):
        raise VaultError("no key given: nothing opened") from None
    if not AGE_SECRET.match(key):
        raise VaultError("that is not an age secret key (a line that starts with AGE-SECRET-KEY-1): nothing opened")
    return key


def _read_line(prompt: str) -> str:
    print(prompt, end="", flush=True)
    line = sys.stdin.readline() if sys.stdin is not None else ""
    if not line:
        raise EOFError
    return line


def paste_prompt(windows: bool | None = None) -> str:
    """How to end a key block pasted for gpg, which reads it from the terminal itself: the console's end of input."""
    if os.name == "nt" if windows is None else windows:
        return "paste the key block and press Enter, then Ctrl+Z alone on the new line and Enter: it ends the input"
    return "paste the key block and press Enter, then Ctrl+D: it ends the input"


def vault_dir() -> Path:
    return paths.brain_home() / "vault"


def _now(now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(s: str) -> datetime | None:
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _run(argv: list[str], *, stdin: bytes | str | None = None, inherit: bool = False,
         timeout: int = 300) -> subprocess.CompletedProcess:
    """Run an adapter's command: stdin given (bytes or text), or inherited from the terminal (the owner types or
    pastes a key the brain never reads), else closed. stderr is kept for the error message, never a key."""
    data = stdin.encode("utf-8") if isinstance(stdin, str) else stdin
    try:
        r = subprocess.run(argv, input=data, capture_output=True, timeout=timeout,
                           stdin=None if (data is not None or inherit) else subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        raise VaultError(f"{Path(argv[0]).name}: {type(exc).__name__}: {exc}") from None
    return r


def _fail(r: subprocess.CompletedProcess, what: str) -> None:
    if r.returncode:
        err = r.stderr.decode("utf-8", "replace").strip().splitlines() if r.stderr else []
        tail = next((ln for ln in reversed(err) if ln.strip()), "")
        raise VaultError(f"{what} failed (exit {r.returncode})" + (f": {tail}" if tail and not PRIVATE.search(tail)
                                                                    else ""))


@contextmanager
def _private_dir(prefix: str, short: bool = False):
    """A temporary folder under $BRAIN_HOME/vault/tmp (``short``: under the system's temporary folder, for gpg's
    agent sockets, whose path is limited to about 100 characters), its owner's only, removed whatever happens."""
    base = None if short else vault_dir() / "tmp"
    if base is not None:
        base.mkdir(parents=True, exist_ok=True)
    d = Path(tempfile.mkdtemp(prefix=prefix, dir=base))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


# --- adapters ---
def _which(*names: str) -> list[str]:
    for n in names:
        p = shutil.which(n)
        if p:
            return [p]
    return []


class Adapter:
    name = ""
    suffix = ""

    def found(self) -> bool:
        raise NotImplementedError

    def seal(self, src: Path, dst: Path, keys: list[str]) -> None:
        raise NotImplementedError

    def open(self, src: Path, dst: Path, ident: str | None = None, ident_file: Path | None = None) -> None:
        """Open with the keystore's value (``ident``), a key file the owner points at, or neither: the owner gives
        the key in the terminal (age: ``ask_key``, hidden; gpg reads its key block itself, ``paste_prompt``)."""
        raise NotImplementedError

    def keygen(self, label: str) -> tuple[str, str]:
        """(the keystore value, the public key: an age recipient or an armored gpg key)."""
        raise NotImplementedError

    def public_id(self, key: str) -> str:
        """What device.json compares: the age recipient, or the gpg key file's fingerprint."""
        raise NotImplementedError


class Age(Adapter):
    """age (or rage): ``-r`` per recipient, the identity on standard input (``-i -``), never on a command line."""
    name, suffix = "age", ".age"

    def __init__(self, cmd: list[str] | None = None, keygen_cmd: list[str] | None = None):
        self.cmd = cmd if cmd is not None else _which("age", "rage")
        self.keygen_cmd = keygen_cmd if keygen_cmd is not None else _which("age-keygen", "rage-keygen")

    def found(self):
        return bool(self.cmd)

    def seal(self, src, dst, keys):
        argv = [*self.cmd, "-e"]
        for k in keys:
            argv += ["-r", k]
        _fail(_run([*argv, "-o", str(dst), str(src)]), "age: seal")

    def open(self, src, dst, ident=None, ident_file=None):
        if ident_file is not None:
            r = _run([*self.cmd, "-d", "-i", str(ident_file), "-o", str(dst), str(src)])
        else:
            key = ident if ident is not None else ask_key()
            r = _run([*self.cmd, "-d", "-i", "-", "-o", str(dst), str(src)], stdin=key + "\n")
        _fail(r, "age: open")

    def keygen(self, label):
        if not self.keygen_cmd:
            raise VaultError("age-keygen not found")
        r = _run(list(self.keygen_cmd))
        _fail(r, "age-keygen")
        lines = r.stdout.decode("utf-8", "replace").splitlines()
        ident = next((ln.strip() for ln in lines if ln.startswith("AGE-SECRET-KEY-")), "")
        pub = next((ln.split(":", 1)[1].strip() for ln in lines if ln.lower().startswith("# public key:")), "")
        if not ident:
            raise VaultError("age-keygen printed no identity")
        return ident, pub or self.derive(ident)

    def derive(self, ident: str) -> str:
        r = _run([*self.keygen_cmd, "-y"], stdin=ident + "\n")
        _fail(r, "age-keygen -y")
        return r.stdout.decode().strip()

    def public_id(self, key):
        return key


class Gpg(Adapter):
    """gpg, keyring-free: a fresh home per call, ``--recipient-file`` per public key, the device key imported from the
    keystore into that home for one decryption, the home and its agent removed after. Git for Windows' gpg (MSYS)
    takes its home as /c/... (a ':' is refused in its socket names)."""
    name, suffix = "gpg", ".gpg"

    def __init__(self, cmd: list[str] | None = None):
        self.cmd = cmd if cmd is not None else _which("gpg")
        self._msys: bool | None = None

    def found(self):
        return bool(self.cmd)

    def msys(self) -> bool:
        if self._msys is None:
            r = _run([*self.cmd, "--version"], timeout=30)
            home = next((ln for ln in r.stdout.decode("utf-8", "replace").splitlines() if ln.startswith("Home:")), "")
            self._msys = home.split(":", 1)[1].strip().startswith("/") if home else False
        return self._msys

    def home(self, d: Path) -> str:
        s = str(d)
        if self.msys() and re.match(r"^[A-Za-z]:[\\/]", s):
            return "/" + s[0].lower() + s[2:].replace("\\", "/")
        return s

    @contextmanager
    def _home(self):
        with _private_dir("bv-", short=True) as d:
            try:
                yield d
            finally:
                gpgconf = shutil.which("gpgconf")
                if gpgconf:
                    _run([gpgconf, "--homedir", self.home(d), "--kill", "gpg-agent"], timeout=30)

    def _gpg(self, home: Path, *args: str, **kw) -> subprocess.CompletedProcess:
        return _run([*self.cmd, "--batch", "--no-tty", "--homedir", self.home(home), *args], **kw)

    def seal(self, src, dst, keys):
        argv = ["--yes", "--trust-model", "always"]
        for k in keys:
            argv += ["--recipient-file", k]
        with self._home() as h:
            _fail(self._gpg(h, *argv, "--output", str(dst), "--encrypt", str(src)), "gpg: seal")

    def open(self, src, dst, ident=None, ident_file=None):
        with self._home() as h:
            if ident is not None:
                _fail(self._gpg(h, "--import", stdin=base64.b64decode(ident)), "gpg: import the device key")
                r = self._gpg(h, "--yes", "--pinentry-mode", "loopback", "--passphrase", "", "--output", str(dst),
                              "--decrypt", str(src))
            else:
                if ident_file is not None:
                    _fail(self._gpg(h, "--import", str(ident_file)), "gpg: import the key")
                else:
                    print(paste_prompt())
                    _fail(self._gpg(h, "--import", inherit=True), "gpg: import the key")
                r = _run([*self.cmd, "--no-tty", "--homedir", self.home(h), "--yes", "--output", str(dst),
                          "--decrypt", str(src)], inherit=True)
            _fail(r, "gpg: open")

    def keygen(self, label):
        with self._home() as h:
            _fail(self._gpg(h, "--passphrase", "", "--pinentry-mode", "loopback", "--quick-gen-key",
                            f"brain vault {label}", "default", "default", "never"), "gpg: key generation")
            sk = self._gpg(h, "--export-secret-keys")
            _fail(sk, "gpg: export the device key")
            pub = self._gpg(h, "--armor", "--export")
            _fail(pub, "gpg: export the public key")
        return base64.b64encode(sk.stdout).decode("ascii"), pub.stdout.decode("ascii")

    def public_id(self, key):
        """The fingerprint of the primary key in an armored public key file."""
        with self._home() as h:
            r = self._gpg(h, "--with-colons", "--show-keys", key)
            _fail(r, "gpg: read a public key")
        for ln in r.stdout.decode("utf-8", "replace").splitlines():
            if ln.startswith("fpr:"):
                return ln.split(":")[9]
        raise VaultError(f"gpg: no fingerprint in {Path(key).name}")


def adapters() -> dict[str, Adapter]:
    """The adapters, found or not (brain vault status says which)."""
    return {"age": Age(), "gpg": Gpg()}


# --- recipients ---
@dataclass
class Recipient:
    name: str
    kind: str
    age: str = ""
    gpg: str = ""                       # an armored public key file, relative to the brain's root
    host: str = ""
    classes: list[str] = field(default_factory=list)
    why: str = ""

    def key(self, adapter: str, root: Path) -> str:
        if adapter == "age":
            return self.age
        return str((root / self.gpg).resolve()) if self.gpg else ""

    def fingerprint(self, root: Path) -> str:
        """A short public digest of the recipient's keys, to compare sets without printing them."""
        h = hashlib.sha256(self.age.encode())
        if self.gpg and (root / self.gpg).is_file():
            h.update((root / self.gpg).read_bytes())
        return h.hexdigest()[:16]


def _block(cfg: config.Config) -> dict:
    b = cfg.data.get("vault")
    return b if isinstance(b, dict) else {}


def private_material(text: str) -> bool:
    return bool(PRIVATE.search(text or ""))


def recipients(cfg: config.Config) -> tuple[dict[str, Recipient], list[str]]:
    """The declared recipients, and what is wrong with them (a private key among them first of all)."""
    block = _block(cfg)
    errors: list[str] = []
    if private_material(json.dumps(block)):
        errors.append("vault: holds private key material: only public keys enter config.json (remove it, and treat "
                      "that key as exposed)")
    unknown = set(block) - VAULT_KEYS
    if unknown:
        errors.append(f"vault: unknown key(s) {', '.join(sorted(unknown))} (known: {', '.join(sorted(VAULT_KEYS))})")
    out: dict[str, Recipient] = {}
    for name, d in (block.get("recipients") or {}).items():
        where = f"vault.recipients.{name}"
        if not NAME.match(str(name)) or not isinstance(d, dict):
            errors.append(f"{where}: a kebab-case name and a mapping")
            continue
        if set(d) - RECIPIENT_KEYS:
            errors.append(f"{where}: unknown key(s) {', '.join(sorted(set(d) - RECIPIENT_KEYS))}")
        r = Recipient(name, str(d.get("kind") or ""), str(d.get("age") or ""), str(d.get("gpg") or ""),
                      str(d.get("host") or ""), list(d.get("classes") or []), str(d.get("why") or ""))
        errors += [f"{where}: {e}" for e in _recipient_errors(r, cfg.root)]
        out[name] = r
    if (block.get("min_recipients") or MIN_RECIPIENTS) < MIN_RECIPIENTS:
        errors.append(f"vault.min_recipients: {MIN_RECIPIENTS} at least (a device key and the recovery key)")
    for tid, names in (block.get("tenants") or {}).items():
        if not classes.TENANT_ID.match(str(tid)):
            errors.append(f"vault.tenants.{tid}: a kebab-case tenant id")
        for n in names or []:
            if n not in out:
                errors.append(f"vault.tenants.{tid}: unknown recipient {n}")
    return out, errors


def _recipient_errors(r: Recipient, root: Path) -> list[str]:
    errs = []
    if r.kind not in KINDS:
        errs.append(f"kind is one of {', '.join(KINDS)}")
    if not r.age and not r.gpg:
        errs.append("an age recipient or a gpg public key file")
    if r.age and not (AGE_KEY.match(r.age) or SSH_KEY.match(r.age)):
        errs.append("age is an age1... or ssh-ed25519/ssh-rsa public recipient")
    if r.gpg:
        f = root / r.gpg
        if not f.is_file():
            errs.append(f"gpg: {r.gpg} not found")
        else:
            text = f.read_text(encoding="utf-8", errors="replace")
            if private_material(text):
                errs.append(f"gpg: {r.gpg} holds a private key: remove it, and treat that key as exposed")
            elif PGP_PUBLIC not in text:
                errs.append(f"gpg: {r.gpg} is not an armored public key")
    bad = [c for c in r.classes if not classes.class_ok(c)]
    if bad:
        errs.append(f"classes: unknown {', '.join(map(str, bad))}")
    return errs


def check(root: Path | None = None, cfg: config.Config | None = None) -> list[str]:
    """What brain check --all refuses in the vault block: a private key, a malformed recipient, an unknown name."""
    cfg = cfg or config.load(root)
    if "vault" not in cfg.data:
        return []
    if not isinstance(cfg.data["vault"], dict):
        return ["vault: a mapping (adapter, min_recipients, recipients, tenants)"]
    _, errors = recipients(cfg)
    nodes = classes.scope_nodes(cfg)
    recs = (_block(cfg).get("recipients") or {})
    for node, d in nodes.items():
        for n in ((d.get("vault") or {}) if isinstance(d.get("vault"), dict) else {}).get("recipients") or []:
            if n not in recs:
                errors.append(f"scopes {node}: vault.recipients names an unknown recipient {n}")
    return errors


def min_recipients(cfg: config.Config) -> int:
    return max(MIN_RECIPIENTS, int(_block(cfg).get("min_recipients") or MIN_RECIPIENTS))


def for_store(cfg: config.Config, store: classes.Store) -> list[Recipient]:
    """The recipients a store is sealed to: its tenant's, or the root's plus those of its scope chain."""
    if store.kind in ("resident", "secret"):
        raise VaultError(f"store {store.name} is {store.kind}: it never leaves the machine, even sealed")
    recs, _ = recipients(cfg)
    tenants = _block(cfg).get("tenants") or {}
    if store.kind == "tenant":
        return [recs[n] for n in tenants.get(store.cls[len(classes.TENANT):]) or [] if n in recs]
    nodes = classes.scope_nodes(cfg)

    def node_recipients(d: dict) -> list[str]:
        v = d.get("vault") if isinstance(d.get("vault"), dict) else {}
        return [str(n) for n in v.get("recipients") or []]

    scoped = {n for d in nodes.values() for n in node_recipients(d)}
    tenant_only = {n for ns in tenants.values() for n in ns or []}
    names = [n for n, r in recs.items() if n not in scoped and n not in tenant_only
             and (not r.classes or store.cls in r.classes)]
    for node in classes.scope_chain(cfg, store.project or classes.own_project(cfg), nodes):
        names += [n for n in node_recipients(nodes.get(node) or {}) if n in recs and n not in names]
    return [recs[n] for n in names]


def pick(cfg: config.Config, recs: list[Recipient], name: str | None = None,
         found: dict[str, Adapter] | None = None) -> Adapter:
    """The adapter that can seal to every recipient: the one asked, else config's, else age, else gpg."""
    found = found if found is not None else adapters()
    pref = _block(cfg).get("adapter")
    order = [name] if name else ([pref] if pref in ADAPTERS else []) + [a for a in ADAPTERS if a != pref]
    why = []
    for a in order:
        ad = found.get(a)
        if ad is None or not ad.found():
            why.append(f"{a} not found")
            continue
        lacking = [r.name for r in recs if not r.key(a, cfg.root)]
        if lacking:
            why.append(f"{a}: no {a} key for {', '.join(lacking)}")
            continue
        return ad
    raise VaultError("no adapter can seal to every recipient (" + "; ".join(why) + ")")


# --- state ---
def state_file() -> Path:
    return vault_dir() / "state.json"


def load_state() -> dict:
    try:
        data = json.loads(state_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    for k in ("canary", "drill", "seals"):
        data.setdefault(k, {})
    return data


def save_state(st: dict) -> None:
    f = state_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, f)


def device_file() -> Path:
    return vault_dir() / "device.json"


def device() -> dict:
    """This machine's device key, public facts only ({} without one): name, adapter, public, keystore, created."""
    try:
        d = json.loads(device_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def keystore_key(cfg: config.Config) -> str:
    """The keystore entry of this machine's device key: device, or device-<tenant> for a hosted team's brain."""
    ident = cfg.data.get("identity") if isinstance(cfg.data.get("identity"), dict) else {}
    return f"device-{ident['tenant']}" if ident.get("tenant") else "device"


def host_name() -> str:
    return re.sub(r"[^a-z0-9-]+", "-", socket.gethostname().lower()).strip("-") or "device"


# --- seal and open ---
def store(cfg: config.Config, name: str) -> classes.Store:
    declared, _ = classes.stores(cfg)
    for s in declared:
        if s.name == name:
            return s
    raise VaultError(f"no store {name} in config.json's classes.stores (brain classes lists them)")


def sources(cfg: config.Config, s: classes.Store) -> list[tuple[Path, str]]:
    """(path, name in the archive) of a store's content: its machine folders and files, and its tracked files."""
    out = []
    for m in s.machine:
        p = classes.expand(m)
        if p.exists():
            out.append((p, p.name))
    if s.globs:
        by, _ = classes.classify(classes.stores(cfg)[0], classes.tracked(cfg.root))
        out += [(cfg.root / f, f) for f in by.get(s.name, [])]
    return out


def _reset(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = info.gid = 0
    info.uname = info.gname = ""      # no user name in what leaves the machine
    return info


def pack(items: list[tuple[Path, str]], dst: Path) -> tuple[int, int]:
    """A tar.gz of the items in a stable order: (files, bytes before compression)."""
    count = size = 0
    with tarfile.open(dst, "w:gz") as tar:
        for path, arc in sorted(items, key=lambda x: x[1]):
            walk = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
            for f in walk:
                name = arc if f == path else f"{arc}/{f.relative_to(path).as_posix()}"
                tar.add(f, arcname=name, recursive=False, filter=_reset)
                count, size = count + 1, size + f.stat().st_size
    return count, size


def _sha256(f: Path) -> str:
    h = hashlib.sha256()
    with f.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def seal(cfg: config.Config, name: str, items: list[Path] | None = None, out: Path | None = None,
         adapter: str | None = None, now: datetime | None = None, found: dict[str, Adapter] | None = None) -> dict:
    """Seal a store (its declared content, or the given paths) to its recipients; the manifest written beside the
    sealed file. Unattended: public keys only."""
    s = store(cfg, name)
    recs = for_store(cfg, s)
    need = min_recipients(cfg)
    if len(recs) < need:
        raise VaultError(f"store {s.name} would be sealed to {len(recs)} recipient(s): every sealed store needs "
                         f"{need} at least, a device key and the recovery key (brain vault status)")
    ad = pick(cfg, recs, adapter, found)
    pairs = [(p, p.name) for p in items] if items else sources(cfg, s)
    pairs = [(p, a) for p, a in pairs if p.exists()]
    if not pairs:
        raise VaultError(f"store {s.name}: nothing to seal")
    t = _now(now)
    out = out or vault_dir() / "sealed" / s.name / f"{s.name}-{t:%Y%m%dT%H%M%SZ}.tar.gz{ad.suffix}"
    out.parent.mkdir(parents=True, exist_ok=True)
    with _private_dir("s") as tmp:
        payload = tmp / "payload.tar.gz"
        files, size = pack(pairs, payload)
        part = out.with_name(out.name + ".part")
        ad.seal(payload, part, [r.key(ad.name, cfg.root) for r in recs])
        os.replace(part, out)
    manifest = {"v": 1, "store": s.name, "class": s.cls, "adapter": ad.name, "created": _iso(t),
                "recipients": [{"name": r.name, "kind": r.kind, "fingerprint": r.fingerprint(cfg.root)} for r in recs],
                "files": files, "bytes_in": size, "bytes": out.stat().st_size, "sha256": _sha256(out),
                "file": out.name}
    out.with_name(out.name + ".json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    st = load_state()
    st["seals"][s.name] = {"at": _iso(t), "file": str(out), "recipients": [r.name for r in recs]}
    save_state(st)
    return manifest


def adapter_of(path: Path, found: dict[str, Adapter] | None = None) -> Adapter:
    found = found if found is not None else adapters()
    for ad in found.values():
        if path.name.endswith(ad.suffix):
            if not ad.found():
                raise VaultError(f"{ad.name} {NOT_ON_PATH}; it opens {path.name}")
            return ad
    raise VaultError(f"{path.name}: neither .age nor .gpg")


def device_value(cfg: config.Config) -> str:
    ks = keystore.backend()
    if ks is None:
        raise VaultError("no keystore on this machine")
    value = ks.get(keystore_key(cfg))
    if not value:
        raise VaultError(f"no device key in the keystore ({ks.name}): brain vault device init, in your own terminal")
    return value


def _safe_extract(archive: Path, dst: Path) -> int:
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        base = dst.resolve()
        for m in members:
            target = (dst / m.name).resolve()
            if m.issym() or m.islnk() or not (target == base or base in target.parents):
                raise VaultError(f"refused: {m.name} would land outside {dst}")
        if hasattr(tarfile, "data_filter"):
            tar.extractall(dst, filter="data")
        else:  # Python before the extraction filters
            tar.extractall(dst)
    return len(members)


def open_sealed(cfg: config.Config, sealed: Path, out: Path, identity: str = "device",
                found: dict[str, Adapter] | None = None) -> dict:
    """Open a sealed file into ``out`` (a folder for an archive): with the device key, a key file, or ``-`` (the key
    typed or pasted, hidden: ``ask_key``). The CLI refuses it in an agent session."""
    ad = adapter_of(sealed, found)
    out.mkdir(parents=True, exist_ok=True)
    with _private_dir("o") as tmp:
        plain = tmp / "plain"
        if identity == "device":
            ad.open(sealed, plain, ident=device_value(cfg))
        elif identity == "-":
            ad.open(sealed, plain)
        else:
            ad.open(sealed, plain, ident_file=Path(identity))
        stem = sealed.name[:-len(ad.suffix)]
        if stem.endswith(".tar.gz"):
            n = _safe_extract(plain, out)
        else:
            shutil.copyfile(plain, out / stem)
            n = 1
    return {"file": str(sealed), "out": str(out), "entries": n}


# --- the device key, the recipients ---
def device_init(cfg: config.Config, name: str | None = None, adapter: str | None = None, now: datetime | None = None,
                found: dict[str, Adapter] | None = None) -> dict:
    """Create this machine's device key straight into the keystore; return its public facts only."""
    ks = keystore.backend()
    if ks is None:
        raise VaultError("no keystore on this machine (Credential Manager, keychain, secret-tool or keyring)")
    key = keystore_key(cfg)
    if ks.get(key):
        raise VaultError(f"this machine already has a device key ({ks.name}: {keystore.SERVICE}/{key}); rotation "
                         "is not built yet")
    name = name or host_name()
    if not NAME.match(name):
        raise VaultError(f"{name!r}: a kebab-case name")
    found = found if found is not None else adapters()
    order = [adapter] if adapter else list(ADAPTERS)
    ad = next((found[a] for a in order if a in found and found[a].found()), None)
    if ad is None:
        raise VaultError(f"{' or '.join(order)} not found: install age (or use gpg) first")
    value, public = ad.keygen(f"device {name}")
    ks.set(key, value)
    if ks.get(key) != value:
        raise VaultError(f"the keystore ({ks.name}) did not keep the device key")
    del value
    facts = {"name": name, "adapter": ad.name, "keystore": ks.name, "created": _iso(_now(now))}
    if ad.name == "age":
        facts["public"] = public
        facts["declare"] = f"brain vault recipient add {name} --kind device --age {public} --host {name} --write"
    else:
        kf = vault_dir() / "keys" / f"{name}.asc"
        kf.parent.mkdir(parents=True, exist_ok=True)
        kf.write_text(public, encoding="utf-8")
        facts["public"] = ad.public_id(str(kf))
        facts["key_file"] = str(kf)
        facts["declare"] = f"brain vault recipient add {name} --kind device --gpg {kf} --host {name} --write"
    device_file().parent.mkdir(parents=True, exist_ok=True)
    device_file().write_text(json.dumps(facts, indent=2) + "\n", encoding="utf-8")
    return facts


def recipient_add(cfg: config.Config, name: str, kind: str, age: str = "", gpg: str = "", host: str = "",
                  write: bool = False) -> tuple[dict, bool]:
    """Declare a public recipient in config.json (a plan, or --write); refuses any private key."""
    if not cfg.file:
        raise VaultError("no config.json to declare a recipient in")
    if private_material(age) or (gpg and Path(gpg).is_file() and private_material(
            Path(gpg).read_text(encoding="utf-8", errors="replace"))):
        raise VaultError("that is a private key: only a public recipient is declared (treat the key as exposed if it "
                         "was copied anywhere)")
    if not NAME.match(name):
        raise VaultError(f"{name!r}: a kebab-case name")
    entry: dict = {"kind": kind}
    if age:
        entry["age"] = age.strip()
    if gpg:
        src = Path(gpg).expanduser()
        try:
            rel = src.resolve().relative_to(cfg.root.resolve()).as_posix()
        except ValueError:
            rel = f"vault/keys/{name}.asc"
        entry["gpg"] = rel
    if host:
        entry["host"] = host
    probe = Recipient(name, kind, entry.get("age", ""), "", host)
    errs = [e for e in _recipient_errors(probe, cfg.root) if not (gpg and e.startswith("an age recipient"))]
    if gpg:
        src = Path(gpg).expanduser()
        text = src.read_text(encoding="utf-8", errors="replace") if src.is_file() else ""
        if PGP_PUBLIC not in text:
            errs.append(f"gpg: {gpg} is not an armored public key")
    if errs:
        raise VaultError(f"recipient {name}: " + "; ".join(errs))
    if not write:
        return entry, False
    if gpg and not (cfg.root / entry["gpg"]).is_file():
        (cfg.root / entry["gpg"]).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(gpg).expanduser(), cfg.root / entry["gpg"])
    data = json.loads(cfg.file.read_text(encoding="utf-8"))
    data.setdefault("vault", {}).setdefault("recipients", {})[name] = entry
    cfg.file.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return entry, True


# --- the canary and the drill ---
def canary(cfg: config.Config, now: datetime | None = None, found: dict[str, Adapter] | None = None) -> dict:
    """Seal a fresh nonce to each recipient alone, then open what this machine's device key opens; the results in
    state.json. Unattended (the scheduled task's command)."""
    t = _iso(_now(now))
    recs, errors = recipients(cfg)
    if errors:
        raise VaultError("; ".join(errors))
    found = found if found is not None else adapters()
    dev = device()
    st = load_state()
    cdir = vault_dir() / "canary"
    cdir.mkdir(parents=True, exist_ok=True)
    ident: str | None = None
    results = {}
    for r in recs.values():
        avail = [a for a in ADAPTERS if r.key(a, cfg.root) and a in found and found[a].found()]
        entry: dict = {"sealed_at": "", "opened_at": "", "error": "", "adapter": avail[0] if avail else "",
                       "fingerprint": r.fingerprint(cfg.root)}
        if not avail:
            entry["error"] = "no adapter found for its keys"
        else:
            ad = found[avail[0]]
            target = cdir / f"{r.name}{ad.suffix}"
            nonce = os.urandom(32)
            try:
                with _private_dir("c") as tmp:
                    (tmp / "nonce").write_bytes(nonce)
                    ad.seal(tmp / "nonce", tmp / "sealed", [r.key(ad.name, cfg.root)])
                    os.replace(tmp / "sealed", target)
                entry.update(sealed_at=t, digest=hashlib.sha256(nonce).hexdigest())
                if dev.get("adapter") == ad.name and dev.get("public") and dev["public"] == ad.public_id(
                        r.key(ad.name, cfg.root)):
                    ident = ident or device_value(cfg)
                    with _private_dir("c") as tmp:
                        ad.open(target, tmp / "plain", ident=ident)
                        got = hashlib.sha256((tmp / "plain").read_bytes()).hexdigest()
                    if got != entry["digest"]:
                        raise VaultError("the opened canary does not match its digest")
                    entry.update(opened_at=t, opened_by="device")
            except VaultError as exc:
                entry["error"] = str(exc)
        st["canary"][r.name] = entry
        results[r.name] = entry
    for gone in set(st["canary"]) - set(recs):
        del st["canary"][gone]
    save_state(st)
    return results


def drill(cfg: config.Config, name: str, identity: str = "-", now: datetime | None = None,
          found: dict[str, Adapter] | None = None) -> dict:
    """Open a recipient's canary with its key (a key file, or ``-``: typed into the tool) and record the proof: the
    recovery key's yearly drill. The CLI refuses it in an agent session."""
    st = load_state()
    entry = st["canary"].get(name)
    if not entry or not entry.get("digest"):
        raise VaultError(f"no canary for {name}: brain vault canary first")
    ad = (found if found is not None else adapters()).get(entry["adapter"])
    if ad is None or not ad.found():
        raise VaultError(f"{entry['adapter']} {NOT_ON_PATH}")
    target = vault_dir() / "canary" / f"{name}{ad.suffix}"
    with _private_dir("d") as tmp:
        if identity == "-":
            ad.open(target, tmp / "plain")
        else:
            ad.open(target, tmp / "plain", ident_file=Path(identity))
        got = hashlib.sha256((tmp / "plain").read_bytes()).hexdigest()
    if got != entry["digest"]:
        raise VaultError(f"the canary of {name} opened, but does not match its digest")
    t = _iso(_now(now))
    st["drill"][name] = t
    save_state(st)
    return {"recipient": name, "drilled_at": t}


# --- status and health ---
def status(cfg: config.Config, found: dict[str, Adapter] | None = None) -> dict:
    found = found if found is not None else adapters()
    recs, errors = recipients(cfg)
    ks = keystore.backend()
    dev = device()
    st = load_state()
    has_key = False
    if ks is not None and dev:
        try:
            has_key = bool(ks.get(keystore_key(cfg)))
        except keystore.KeystoreError:
            has_key = False
    return {"declared": "vault" in cfg.data, "adapters": {a: found[a].found() for a in ADAPTERS},
            "keystore": ks.name if ks else None, "device": {**dev, "in_keystore": has_key} if dev else None,
            "min_recipients": min_recipients(cfg),
            "recipients": [{"name": r.name, "kind": r.kind, "keys": [a for a in ADAPTERS if r.key(a, cfg.root)],
                            "host": r.host, "fingerprint": r.fingerprint(cfg.root),
                            "canary": st["canary"].get(r.name) or {}, "drilled_at": st["drill"].get(r.name, "")}
                           for r in recs.values()],
            "seals": st["seals"], "errors": errors}


def next_steps(s: dict) -> list[str]:
    """What waits on the owner, in order, with the exact commands (none of them run by an agent)."""
    steps = []
    if not s["adapters"]["age"]:
        steps.append("install age (winget install FiloSottile.age, brew install age, apt install age), or use gpg")
    if not s["device"]:
        steps.append("create this machine's device key, in your own terminal: brain vault device init")
    elif not any(r["kind"] == "device" and r["name"] == s["device"].get("name") for r in s["recipients"]):
        steps.append(f"declare it: {s['device'].get('declare', 'brain vault recipient add ...')}")
    if not any(r["kind"] == "recovery" for r in s["recipients"]):
        steps.append("create the offline recovery key, in your own terminal, ideally offline: age-keygen ; copy the "
                     "AGE-SECRET-KEY-1... line on paper (two copies, two places), note the age1... public key, then "
                     "Clear-Host (clear) and close the terminal; declare it: brain vault recipient add recovery "
                     "--kind recovery --age age1... --write")
    if s["recipients"] and not any(r["canary"].get("sealed_at") for r in s["recipients"]):
        steps.append("run the canary once, then schedule it daily (your decision; the runbook gives the task for "
                     "Windows, macOS and Linux): brain vault canary")
    if any(r["kind"] == "recovery" and not r["drilled_at"] for r in s["recipients"]):
        steps.append("drill the recovery key once a year, in your own terminal: brain vault drill recovery")
    return steps


def health(cfg: config.Config, now: datetime | None = None, out=None,
           found: dict[str, Adapter] | None = None, named: bool = True) -> int:
    """``brain health vault``: exit 1 when a sealed store could not be opened by two recipients, as far as this
    machine can tell; OFF (exit 0) without a vault block or without any adapter (Lite). Not named (``--all``), a
    brain without a vault block says nothing."""
    if not named and "vault" not in cfg.data:
        return 0
    s = status(cfg, found)
    t = _now(now)
    say = (lambda line: print(line, file=out, flush=True))
    if not s["declared"]:
        say(f"{CHECK} OFF (config.json declares no vault: nothing is sealed yet)")
        return 0
    fails, warns = list(s["errors"]), []
    hours = int(_block(cfg).get("canary_hours") or CANARY_HOURS)
    recs = s["recipients"]
    if len(recs) < s["min_recipients"]:
        fails.append(f"{len(recs)} recipient(s): a sealed store needs {s['min_recipients']} at least")
    if not any(r["kind"] == "recovery" for r in recs):
        warns.append("no recovery recipient")
    if not any(s["adapters"].values()):
        say(f"{CHECK} OFF on this machine (neither age nor gpg found: available, off)"
            + (f"; {len(fails)} problem(s): " + "; ".join(fails) if fails else ""))
        return 1 if fails else 0
    dev = s["device"]
    if not dev:
        warns.append("no device key on this machine (brain vault device init)")
    elif not dev["in_keystore"]:
        fails.append(f"the device key {dev.get('name')} is missing from the keystore")
    for r in recs:
        c = r["canary"]
        sealed, opened = _parse(c.get("sealed_at", "")), _parse(c.get("opened_at", ""))
        if c.get("error"):
            fails.append(f"canary {r['name']}: {c['error']}")
        elif not sealed:
            fails.append(f"canary {r['name']}: never sealed (brain vault canary)")
        elif t - sealed > timedelta(hours=hours):
            fails.append(f"canary {r['name']}: sealed {_age(t - sealed)} ago (more than {hours} h)")
        mine = dev and r["kind"] == "device" and r["name"] == dev.get("name")
        if mine and sealed and not c.get("error") and (not opened or t - opened > timedelta(hours=hours)):
            fails.append(f"canary {r['name']}: this machine's key has not opened it in {hours} h")
        if r["kind"] == "recovery":
            d = _parse(r["drilled_at"])
            if not d:
                warns.append(f"{r['name']}: never drilled (brain vault drill {r['name']})")
            elif t - d > timedelta(days=DRILL_DAYS):
                warns.append(f"{r['name']}: drilled {_age(t - d)} ago")
    seals = [f"{k} {_age(t - (_parse(v.get('at', '')) or t))} ago" for k, v in sorted(s["seals"].items())]
    head = f"{len(recs)} recipient(s)" + (f", device {dev['name']} ({dev['adapter']}, {dev['keystore']})" if dev
                                          else "") + (f", last sealed: {', '.join(seals)}" if seals else "")
    if fails:
        say(f"{CHECK} FAIL ({head}): " + "; ".join(fails))
    else:
        say(f"{CHECK} OK ({head})")
    for w in warns:
        say(f"{CHECK} warning: {w}")
    return 1 if fails else 0


def _age(d: timedelta) -> str:
    secs = int(d.total_seconds())
    if secs < 3600:
        return f"{secs // 60} min"
    if secs < 172800:
        return f"{secs // 3600} h"
    return f"{secs // 86400} d"


def render_status(s: dict) -> list[str]:
    lines = [f"adapters: " + ", ".join(f"{a} {'found' if ok else 'missing'}" for a, ok in s["adapters"].items()),
             f"keystore: {s['keystore'] or 'none'}"]
    dev = s["device"]
    lines.append("device: " + (f"{dev['name']} ({dev['adapter']}, {'in' if dev['in_keystore'] else 'NOT in'} the "
                               f"keystore, created {dev.get('created', '?')})" if dev else "none on this machine"))
    lines.append(f"recipients ({len(s['recipients'])}, {s['min_recipients']} at least per sealed store):")
    for r in s["recipients"]:
        c = r["canary"]
        proof = (f"canary sealed {c.get('sealed_at') or 'never'}" + (f", opened {c['opened_at']}" if c.get(
            "opened_at") else "") + (f", error: {c['error']}" if c.get("error") else ""))
        lines.append(f"  {r['name']:<16} {r['kind']:<9} {'+'.join(r['keys']):<8} {r['fingerprint']}  {proof}"
                     + (f"; drilled {r['drilled_at']}" if r["drilled_at"] else ""))
    for name, v in sorted(s["seals"].items()):
        lines.append(f"sealed: {name} at {v.get('at')} to {', '.join(v.get('recipients') or [])}")
    lines += [f"error: {e}" for e in s["errors"]]
    steps = next_steps(s)
    if steps:
        lines.append("next (yours):")
        lines += [f"  {i}. {x}" for i, x in enumerate(steps, 1)]
        lines.append(f"the runbook: {RUNBOOK}")
    return lines
