import hashlib
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tarfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from brain import config, keystore, rotation, stateio, vault

FAKE = Path(__file__).parent / "fixtures" / "fake_age.py"
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
STORES = {"ledger": {"class": "sealed", "paths": ["$BRAIN_HOME/ledger"], "to": ["offsite"]},
          "data": {"class": "resident", "paths": ["$BRAIN_HOME/data"]},
          "keys": {"class": "secret", "paths": ["$BRAIN_HOME/keys"]},
          "team": {"class": "tenant:team-z", "paths": ["$BRAIN_HOME/team"]},
          "repo": {"class": "private", "paths": ["**"]}}


def fake_age() -> dict:
    return {"age": vault.Age([sys.executable, str(FAKE)], [sys.executable, str(FAKE), "keygen"]),
            "gpg": vault.Gpg([])}


@pytest.fixture
def brain(tmp_path, monkeypatch, brain_home):
    """A personal brain folder whose config.json the test fills, the memory keystore, no agent session."""
    root = tmp_path / "brain"
    root.mkdir()
    monkeypatch.setenv("BRAIN_CONFIG", str(root / config.FILE))
    monkeypatch.setenv("BRAIN_KEYSTORE", "memory")
    keystore.Memory.data.clear()
    for var in vault.AGENT_ENV:
        monkeypatch.delenv(var, raising=False)
    (brain_home / "ledger").mkdir(parents=True)
    (brain_home / "ledger" / "events-2026-11.jsonl").write_text('{"e": 1}\n{"e": 2}\n', encoding="utf-8")
    (brain_home / "ledger" / "sub").mkdir()
    (brain_home / "ledger" / "sub" / "x.txt").write_text("nested", encoding="utf-8")

    def write(recipients: dict, **vault_extra) -> config.Config:
        data = {"v": 1, "identity": {"owner": "Ada"}, "classes": {"stores": STORES},
                "vault": {"recipients": recipients, **vault_extra}}
        (root / config.FILE).write_text(json.dumps(data), encoding="utf-8")
        return config.load(root)

    write.root = root
    return write


GPG_KEYGEN_S = 120   # the deadline of a test's real gpg calls (wi-brain-test-vault-gpg-hang)

# A real gpg call, run in a child Python process: the test can kill it as a process tree on its deadline (a thread
# could not stop it). It writes its outcome as JSON to the result file: the value, a VaultError's message, or any
# other error's type, arguments and traceback.
_GPG_CHILD = """
import json, sys, traceback
from brain import vault
job = json.loads(sys.argv[1])
try:
    out = {"ok": getattr(vault.Gpg(job["cmd"]), job["call"])(*job["args"], **job["kwargs"])}
except vault.VaultError as exc:
    out = {"vault_error": str(exc)}
except BaseException as exc:
    try:
        args = json.loads(json.dumps(list(exc.args)))
    except (TypeError, ValueError):
        args = [str(a) for a in exc.args]
    out = {"error": [type(exc).__module__, type(exc).__qualname__, args, traceback.format_exc()]}
with open(job["result"], "w", encoding="utf-8") as f:
    json.dump(out, f)
"""


def keygen(n: int, ad: vault.Adapter, deadline: float = GPG_KEYGEN_S, tmp: Path | None = None) -> list[tuple[str, str]]:
    """``n`` key pairs of ``ad``. A real gpg's all within ``deadline`` seconds (one end time for the ``n`` keys), each
    in a child process whose temporary folder is ``tmp`` (a folder of pytest's basetemp), else the test is skipped
    with its reason: gpg --quick-gen-key can wait forever on its agent or on entropy, and a gpg-agent the key generation
    spawned can hold the output pipe open past subprocess.run's own timeout (:func:`gpg_call`)."""
    if not isinstance(ad, vault.Gpg):
        return [ad.keygen(f"test {i}") for i in range(n)]
    end = time.monotonic() + deadline
    return [gpg_call(ad, "keygen", f"test {i}", end=end, deadline=deadline, tmp=tmp) for i in range(n)]


def gpg_call(ad: vault.Gpg, call: str, *args, end: float, deadline: float, tmp: Path | None, **kwargs):
    """``ad.<call>(*args, **kwargs)`` in a child Python process, its TEMP, TMP and TMPDIR the folder ``tmp`` (so the
    gpg home it makes lands in pytest's basetemp; a short one, tmp_path_factory.mktemp: under a test's tmp_path, the
    agent's socket path is past what gpg takes on Windows), waited on until ``end`` (time.monotonic). Past it, the child
    is killed with its whole process tree (gpg, its agent), the agents of the homes it left are stopped and the
    homes removed, and the test is skipped with its reason. A VaultError comes back as one (a timeout of gpg's own:
    skipped); any other error as itself."""
    assert tmp is not None, "a real gpg call needs a folder of pytest's basetemp"
    temp, run = Path(tmp), os.urandom(4).hex()
    result, child_log = temp / f"result-{run}.json", temp / f"child-{run}.log"
    env = {**os.environ, "TEMP": str(temp), "TMP": str(temp), "TMPDIR": str(temp),
           "PYTHONPATH": os.pathsep.join([str(Path(vault.__file__).resolve().parents[1]),
                                          *filter(None, [os.environ.get("PYTHONPATH")])])}
    job = {"cmd": ad.cmd, "call": call, "args": [_plain(a) for a in args],
           "kwargs": {k: _plain(v) for k, v in kwargs.items()}, "result": str(result)}
    with open(child_log, "wb") as log:
        child = subprocess.Popen([sys.executable, "-c", _GPG_CHILD, json.dumps(job)], stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=subprocess.STDOUT, env=env,
                                 **({} if os.name == "nt" else {"start_new_session": True}))
        try:
            child.wait(timeout=max(end - time.monotonic(), 0))
        except subprocess.TimeoutExpired:
            _kill_tree(child)
            _remove_homes(ad, temp)
            pytest.skip(f"gpg {call} did not end within {deadline:g} s (its agent or entropy): its process tree "
                        "killed, skipped, not waited on")
    if not result.is_file():
        tail = child_log.read_text(encoding="utf-8", errors="replace")[-2000:]
        raise RuntimeError(f"gpg {call}: its child process exited {child.returncode} without a result: {tail}")
    return gpg_outcome(call, json.loads(result.read_text(encoding="utf-8")))


def _plain(v):
    return str(v) if isinstance(v, Path) else v


def gpg_outcome(call: str, out: dict):
    """The child's outcome: its value (keygen's pair a tuple), a skip (gpg's own timeout), a VaultError, or the other
    error as itself (a builtin one by its type, its child traceback chained; another as a RuntimeError naming it)."""
    import builtins
    if "ok" in out:
        return tuple(out["ok"]) if call == "keygen" else out["ok"]
    if "vault_error" in out:
        if "Timeout" in out["vault_error"]:
            pytest.skip(f"gpg {call} timed out: {out['vault_error']}")
        raise vault.VaultError(out["vault_error"])
    module, name, args, tb = out["error"]
    cls = getattr(builtins, name, None) if module == "builtins" else None
    if isinstance(cls, type) and issubclass(cls, Exception):
        raise cls(*args) from RuntimeError(f"in the gpg child process:\n{tb}")
    raise RuntimeError(f"gpg {call}: {module}.{name}: {args}\n{tb}")


def _kill_tree(child: subprocess.Popen) -> None:
    """The child and every process it started: taskkill /T on Windows, its process group (its own session) on
    POSIX."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], capture_output=True, timeout=30, check=False)
    else:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def _remove_homes(ad: vault.Gpg, temp: Path) -> None:
    """The gpg homes a killed child left under ``temp``: their agent stopped (one that left the process tree: a
    daemon in its own session), then removed."""
    gpgconf = shutil.which("gpgconf")
    for home in temp.glob("bv-*"):
        if gpgconf:
            try:
                subprocess.run([gpgconf, "--homedir", ad.home(home), "--kill", "gpg-agent"], capture_output=True,
                               timeout=10, stdin=subprocess.DEVNULL, check=False)
            except (OSError, subprocess.SubprocessError):
                pass
        shutil.rmtree(home, ignore_errors=True)


def tree(d: Path) -> dict:
    return {p.relative_to(d).as_posix(): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


def _sleeping_gpg(pidfile: Path) -> vault.Gpg:
    """A gpg that never answers (an agent that never does): its command a Python that writes its pid, then sleeps."""
    ad = vault.Gpg([sys.executable, "-c", f"import os, time; open({str(pidfile)!r}, 'w').write(str(os.getpid())); "
                                          "time.sleep(60)"])
    ad._msys = False   # the test's own process never asks it its version: it would sleep too
    return ad


def _alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"], capture_output=True,
                             text=True, check=False).stdout
        return f'"{pid}"' in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_a_gpg_call_that_hangs_is_killed_as_a_tree_and_skipped_with_its_reason(tmp_path):
    """On the deadline the child, and the 'gpg' it started, are killed; no gpg home is left; the skip says why."""
    pidfile = tmp_path / "gpg.pid"
    start = time.monotonic()
    with pytest.raises(pytest.skip.Exception, match=r"did not end within 4 s \(its agent or entropy\): its process"):
        keygen(1, _sleeping_gpg(pidfile), deadline=4, tmp=tmp_path)
    assert time.monotonic() - start < 30
    pid = int(pidfile.read_text(encoding="utf-8"))   # the sleeping 'gpg' had started: the kill reached it
    gone = time.monotonic() + 10
    while _alive(pid) and time.monotonic() < gone:
        time.sleep(0.2)
    assert not _alive(pid)
    assert not list(tmp_path.rglob("bv-*"))   # no temporary gpg home left behind


def test_a_gpg_childs_outcome_is_its_value_a_skip_or_its_own_error(tmp_path):
    assert gpg_outcome("keygen", {"ok": ["key", "pub"]}) == ("key", "pub")
    with pytest.raises(pytest.skip.Exception, match="gpg keygen timed out"):
        gpg_outcome("keygen", {"vault_error": "gpg: TimeoutExpired: Command timed out after 300 seconds"})
    with pytest.raises(vault.VaultError, match="gpg: key generation: bad"):   # any other failure is a failure
        gpg_outcome("keygen", {"vault_error": "gpg: key generation: bad"})
    with pytest.raises(PermissionError, match="denied"):   # an error other than VaultError: itself
        gpg_outcome("keygen", {"error": ["builtins", "PermissionError", [13, "denied"], "Traceback ..."]})
    with pytest.raises(AttributeError, match="no_such_call"):   # through a real child process
        gpg_call(vault.Gpg([sys.executable]), "no_such_call", end=time.monotonic() + 60, deadline=60, tmp=tmp_path)


# --- the round trips ---
def test_gpg_seal_then_open_with_each_of_two_recipients(brain, brain_home, tmp_path, tmp_path_factory):
    """Real cryptography: a store sealed to two gpg recipients opens with either key, and not with a third."""
    ad = vault.Gpg()
    if not ad.found():
        pytest.skip("gpg not available")
    g = tmp_path_factory.mktemp("g")   # the gpg calls' temporary folder: short, in pytest's basetemp
    (a, a_pub), (b, b_pub), (c, _) = keygen(3, ad, tmp=g)
    keys = brain.root / "vault" / "keys"
    keys.mkdir(parents=True)
    (keys / "box1.asc").write_text(a_pub, encoding="utf-8")
    (keys / "recovery.asc").write_text(b_pub, encoding="utf-8")
    cfg = brain({"box1": {"kind": "device", "gpg": "vault/keys/box1.asc"},
                 "recovery": {"kind": "recovery", "gpg": "vault/keys/recovery.asc"}})
    assert vault.check(cfg=cfg) == []
    man = vault.seal(cfg, "ledger", now=NOW)
    assert man["adapter"] == "gpg" and [r["name"] for r in man["recipients"]] == ["box1", "recovery"]
    sealed = brain_home / "vault" / "sealed" / "ledger" / man["file"]
    assert sealed.is_file() and b'"e": 1' not in sealed.read_bytes()
    assert json.loads(sealed.with_name(sealed.name + ".json").read_text())["files"] == 2
    end = time.monotonic() + GPG_KEYGEN_S   # each open imports a secret key into a fresh home: an agent, bounded too
    for i, ident in enumerate((a, b)):
        out = tmp_path / f"opened{i}"
        gpg_call(ad, "open", sealed, tmp_path / f"plain{i}", ident=ident, end=end, deadline=GPG_KEYGEN_S, tmp=g)
        vault._safe_extract(tmp_path / f"plain{i}", out)
        assert tree(out / "ledger") == tree(brain_home / "ledger")
    with pytest.raises(vault.VaultError):
        gpg_call(ad, "open", sealed, tmp_path / "nope", ident=c, end=end, deadline=GPG_KEYGEN_S, tmp=g)


def test_age_wiring_seal_then_open_with_each_of_two_recipients(brain, brain_home, tmp_path):
    found = fake_age()
    (a, a_pub), (b, b_pub), (c, _) = keygen(3, found["age"])
    cfg = brain({"box1": {"kind": "device", "age": a_pub}, "recovery": {"kind": "recovery", "age": b_pub}})
    man = vault.seal(cfg, "ledger", now=NOW, found=found)
    sealed = brain_home / "vault" / "sealed" / "ledger" / man["file"]
    assert sealed.name == "ledger-20261102T120000Z.tar.gz.age"
    for ident in (a, b):
        keystore.Memory.data["device"] = ident
        out = tmp_path / ident[-6:]
        vault.open_sealed(cfg, sealed, out, found=found)
        assert tree(out / "ledger") == tree(brain_home / "ledger")
    keystore.Memory.data["device"] = c
    with pytest.raises(vault.VaultError, match="no identity matched"):
        vault.open_sealed(cfg, sealed, tmp_path / "nope", found=found)
    key_file = tmp_path / "recovery.txt"
    key_file.write_text(f"# public key: {b_pub}\n{b}\n", encoding="utf-8")
    vault.open_sealed(cfg, sealed, tmp_path / "from-file", identity=str(key_file), found=found)
    assert (tmp_path / "from-file" / "ledger" / "sub" / "x.txt").read_text() == "nested"


def test_age_real_round_trip(brain, brain_home, tmp_path, monkeypatch):
    ad = vault.Age()
    if not ad.found() or not ad.keygen_cmd:
        pytest.skip("age not installed")
    (a, a_pub), (b, b_pub) = keygen(2, ad)
    cfg = brain({"box1": {"kind": "device", "age": a_pub}, "recovery": {"kind": "recovery", "age": b_pub}})
    man = vault.seal(cfg, "ledger", now=NOW)
    sealed = brain_home / "vault" / "sealed" / "ledger" / man["file"]
    for ident in (a, b):
        keystore.Memory.data["device"] = ident
        out = tmp_path / ident[-6:]
        vault.open_sealed(cfg, sealed, out)
        assert tree(out / "ledger") == tree(brain_home / "ledger")
    vault.canary(cfg, now=NOW)  # the drill with the real age: the key typed hidden, then Enter, and nothing else
    monkeypatch.setattr(vault.sys, "stdin", Tty())
    monkeypatch.setattr(vault.getpass, "getpass", lambda prompt: b)
    assert vault.drill(cfg, "recovery", "-", now=NOW)["recipient"] == "recovery"
    (c, c_pub), = keygen(1, ad)   # a new machine joins: the real age seals the store again for it
    keystore.Memory.data["device"] = a
    cfg = brain({"box1": {"kind": "device", "age": a_pub}, "recovery": {"kind": "recovery", "age": b_pub},
                 "box2": {"kind": "device", "age": c_pub}})
    (done,) = rotation.reseal(cfg, apply=True)
    assert done["done"]
    keystore.Memory.data["device"] = c
    vault.open_sealed(cfg, sealed, tmp_path / "resealed")
    assert tree(tmp_path / "resealed" / "ledger") == tree(brain_home / "ledger")


# --- refusals ---
def test_seal_refuses_what_never_leaves_and_too_few_recipients(brain):
    found = fake_age()
    (_, a_pub), (_, b_pub) = keygen(2, found["age"])
    cfg = brain({"box1": {"kind": "device", "age": a_pub}, "recovery": {"kind": "recovery", "age": b_pub}})
    for name, why in (("data", "resident"), ("keys", "secret")):
        with pytest.raises(vault.VaultError, match=f"{why}: it never leaves the machine"):
            vault.seal(cfg, name, found=found)
    with pytest.raises(vault.VaultError, match="no store nope"):
        vault.seal(cfg, "nope", found=found)
    one = brain({"box1": {"kind": "device", "age": a_pub}})
    with pytest.raises(vault.VaultError, match="1 recipient.*2 at least"):
        vault.seal(one, "ledger", found=found)
    with pytest.raises(vault.VaultError, match="0 recipient"):  # the tenant declares none
        vault.seal(cfg, "team", found=found)


def test_only_public_keys_enter_config(brain, tmp_path):
    found = fake_age()
    (_, a_pub), = keygen(1, found["age"])
    cfg = brain({"box1": {"kind": "device", "age": a_pub}})
    age_private = "AGE-SECRET-" + "KEY-1" + "Q" * 58
    with pytest.raises(vault.VaultError, match="private key"):
        vault.recipient_add(cfg, "oops", "recovery", age=age_private, write=True)
    pgp = tmp_path / "k.asc"
    pgp.write_text("-----BEGIN PGP " + "PRIVATE KEY BLOCK-----\nxx\n", encoding="utf-8")
    with pytest.raises(vault.VaultError, match="private key"):
        vault.recipient_add(cfg, "oops", "device", gpg=str(pgp), write=True)
    assert "oops" not in json.loads(cfg.file.read_text())["vault"]["recipients"]
    leaked = brain({"box1": {"kind": "device", "age": a_pub}, "bad": {"kind": "recovery", "age": age_private}})
    errors = vault.check(cfg=leaked)
    assert any("private key material" in e for e in errors) and any("bad: age is an age1" in e for e in errors)


def test_recipient_add_plans_then_writes(brain, tmp_path):
    found = fake_age()
    (_, a_pub), (_, b_pub) = keygen(2, found["age"])
    cfg = brain({"box1": {"kind": "device", "age": a_pub}})
    entry, written = vault.recipient_add(cfg, "recovery", "recovery", age=b_pub)
    assert entry == {"kind": "recovery", "age": b_pub} and not written
    assert "recovery" not in json.loads(cfg.file.read_text())["vault"]["recipients"]
    vault.recipient_add(cfg, "recovery", "recovery", age=b_pub, write=True)
    assert json.loads(cfg.file.read_text())["vault"]["recipients"]["recovery"]["age"] == b_pub
    with pytest.raises(vault.VaultError, match="kind is one of"):
        vault.recipient_add(cfg, "x", "friend", age=b_pub)
    with pytest.raises(vault.VaultError, match="age1"):
        vault.recipient_add(cfg, "x", "device", age="not-a-key")
    pub = tmp_path / "pub.asc"
    pub.write_text("-----BEGIN PGP PUBLIC KEY BLOCK-----\nxx\n-----END PGP PUBLIC KEY BLOCK-----\n", encoding="utf-8")
    entry, _ = vault.recipient_add(config.load(), "box2", "device", gpg=str(pub), write=True)
    assert entry["gpg"] == "vault/keys/box2.asc" and (brain.root / "vault" / "keys" / "box2.asc").is_file()


def test_recipient_remove_plans_refuses_then_writes(brain, brain_home):
    """A recipient leaves config.json only by a plan then --write, never below two, never the only recovery key, never
    while a tenant names it; the plan lists the sealed files its key still opens."""
    found = fake_age()
    (a, a_pub), (_, b_pub), (_, c_pub) = keygen(3, found["age"])
    cfg = brain({"box1": {"kind": "device", "age": a_pub}, "recovery": {"kind": "recovery", "age": b_pub}})
    with pytest.raises(vault.VaultError, match="1 recipient.*would be left"):
        rotation.recipient_remove(cfg, "box1")
    with pytest.raises(vault.VaultError, match="no recipient nope"):
        rotation.recipient_remove(cfg, "nope")
    with pytest.raises(vault.VaultError, match="declared already: --replace"):
        vault.recipient_add(cfg, "box1", "device", age=c_pub, write=True)
    cfg = brain({"box1": {"kind": "device", "age": a_pub}, "box2": {"kind": "device", "age": c_pub},
                 "recovery": {"kind": "recovery", "age": b_pub}})
    with pytest.raises(vault.VaultError, match="only recovery key"):
        rotation.recipient_remove(cfg, "recovery")
    vault.seal(cfg, "ledger", now=NOW, found=found)
    plan, written = rotation.recipient_remove(cfg, "box2")
    assert not written and plan["left"] == ["box1", "recovery"] and len(plan["reseal"]) == 1
    assert "box2" in json.loads(cfg.file.read_text())["vault"]["recipients"]
    rotation.recipient_remove(cfg, "box2", write=True)
    assert "box2" not in json.loads(cfg.file.read_text())["vault"]["recipients"]
    cfg = brain({"box1": {"kind": "device", "age": a_pub}, "box2": {"kind": "device", "age": c_pub},
                 "recovery": {"kind": "recovery", "age": b_pub}}, tenants={"team-z": ["box2"]})
    with pytest.raises(vault.VaultError, match="still named in vault.tenants.team-z"):
        rotation.recipient_remove(cfg, "box2")


def test_reseal_follows_a_new_and_a_replaced_recipient(brain, brain_home, tmp_path, capsys):
    """A sealed file whose recipients changed is listed (health fails while a replaced key still opens it), sealed
    again by the plan's --apply with the device key, and the old key then opens nothing."""
    found = fake_age()
    (a, a_pub), (b, b_pub), (c, c_pub), (d, d_pub) = keygen(4, found["age"])
    keystore.Memory.data["device"] = a
    cfg = brain({"box1": {"kind": "device", "age": a_pub}, "recovery": {"kind": "recovery", "age": b_pub}})
    man = vault.seal(cfg, "ledger", now=NOW, found=found)
    sealed = brain_home / "vault" / "sealed" / "ledger" / man["file"]
    assert rotation.stale_seals(cfg) == [] and rotation.reseal(cfg, apply=True, found=found) == []

    cfg = brain({"box1": {"kind": "device", "age": a_pub}, "recovery": {"kind": "recovery", "age": b_pub},
                 "box2": {"kind": "device", "age": c_pub}})
    (p,) = rotation.stale_seals(cfg)
    assert p["new"] == ["box2"] and p["gone"] == []
    vault.health(cfg, now=NOW, found=found)
    assert "1 sealed file(s) a new recipient cannot open yet" in capsys.readouterr().out
    (plan,) = rotation.reseal(cfg, found=found)
    assert not plan.get("done") and rotation.stale_seals(cfg)  # a plan changes nothing
    (done,) = rotation.reseal(cfg, apply=True, now=NOW, found=found)
    assert done["done"] and rotation.stale_seals(cfg) == []
    keystore.Memory.data["device"] = c
    vault.open_sealed(cfg, sealed, tmp_path / "by-box2", found=found)
    assert tree(tmp_path / "by-box2" / "ledger") == tree(brain_home / "ledger")
    assert json.loads(sealed.with_name(sealed.name + ".json").read_text())["resealed"] == "2026-11-02T12:00:00Z"

    keystore.Memory.data["device"] = a
    cfg = brain({"box1": {"kind": "device", "age": a_pub}, "recovery": {"kind": "recovery", "age": d_pub},
                 "box2": {"kind": "device", "age": c_pub}})   # the recovery key replaced
    (p,) = rotation.stale_seals(cfg)
    assert p["gone"] == ["recovery"] and p["new"] == ["recovery"] and p["gone_recovery"] == ["recovery"]
    assert vault.health(cfg, now=NOW, found=found) == 1
    assert "still open with a key no longer declared" in capsys.readouterr().out
    (kept,) = rotation.reseal(cfg, apply=True, found=found)   # the new paper key is not proven yet: the old stays
    assert "never drilled" in kept["error"] and not kept.get("done")
    keystore.Memory.data["device"] = b
    vault.open_sealed(cfg, sealed, tmp_path / "still-old", found=found)
    keystore.Memory.data["device"] = a
    vault.canary(cfg, now=NOW, found=found)
    paper = tmp_path / "paper-d.txt"
    paper.write_text(d + "\n", encoding="utf-8")
    vault.drill(cfg, "recovery", str(paper), now=NOW, found=found)
    (done,) = rotation.reseal(cfg, apply=True, found=found)
    assert done["done"]
    keystore.Memory.data["device"] = b
    with pytest.raises(vault.VaultError, match="no identity matched"):
        vault.open_sealed(cfg, sealed, tmp_path / "by-old", found=found)


def test_a_replaced_key_is_not_proven_by_its_name(brain, brain_home, tmp_path, capsys):
    """Review of #36, findings 1, 7, 12: the drill and the canary prove a key, not a name. A recovery key replaced
    under the same name is « never drilled » and its canary « never sealed » until they run again; a drill recorded
    by name only (before) is tied once to the key its canary held."""
    found = fake_age()
    (a, a_pub), (r0, r0_pub), (_, r1_pub) = keygen(3, found["age"])
    keystore.Memory.data["device"] = a
    vault.device_file().parent.mkdir(parents=True, exist_ok=True)
    vault.device_file().write_text(json.dumps({"name": "box1", "adapter": "age", "public": a_pub,
                                               "keystore": "memory"}), encoding="utf-8")
    cfg = brain({"box1": {"kind": "device", "age": a_pub}, "recovery": {"kind": "recovery", "age": r0_pub}})
    vault.canary(cfg, now=NOW, found=found)
    paper = tmp_path / "r0.txt"
    paper.write_text(r0 + "\n", encoding="utf-8")
    vault.drill(cfg, "recovery", str(paper), now=NOW, found=found)
    assert vault.health(cfg, now=NOW, found=found) == 0 and "never drilled" not in capsys.readouterr().out

    vault.recipient_add(cfg, "recovery", "recovery", age=r1_pub, write=True, replace=True)
    cfg = config.load()
    s = vault.status(cfg, found)
    rec = next(r for r in s["recipients"] if r["name"] == "recovery")
    assert rec["drilled_at"] == "" and rec["canary"] == {}
    assert vault.health(cfg, now=NOW, found=found) == 1
    out = capsys.readouterr().out
    assert "canary recovery: never sealed" in out and "recovery: never drilled" in out
    assert any("drill the recovery key" in step for step in vault.next_steps(s))

    st = json.loads(vault.state_file().read_text())   # a drill recorded by name only, by an older brain
    st["drill"]["recovery"] = "2026-11-01T00:00:00Z"
    vault.state_file().write_text(json.dumps(st), encoding="utf-8")
    assert vault.load_state()["drill"]["recovery"] == {"at": "2026-11-01T00:00:00Z",
                                                       "fingerprint": st["canary"]["recovery"]["fingerprint"]}
    assert json.loads(vault.state_file().read_text())["drill"]["recovery"]["fingerprint"]   # persisted once


def test_replace_keeps_the_kind_and_the_limits_and_refuses_a_shared_key(brain, tmp_path):
    """Review of #36, findings 2, 3, 6, 8, 11: --replace changes the key only. Its kind stays and its classes and why
    are kept; a key another name holds is refused (one key counted twice); a name not declared has nothing to
    replace; a gpg key's file is copied anew even where the old one lies."""
    found = fake_age()
    (_, a_pub), (_, r_pub), (_, h_pub), (_, h2_pub) = keygen(4, found["age"])
    cfg = brain({"box1": {"kind": "device", "age": a_pub}, "recovery": {"kind": "recovery", "age": r_pub},
                 "heir": {"kind": "person", "age": h_pub, "classes": ["private"], "why": "Ada's heir, private only"}})
    with pytest.raises(vault.VaultError, match="box1 already holds this key"):
        vault.recipient_add(cfg, "recovery", "recovery", age=a_pub, replace=True)
    with pytest.raises(vault.VaultError, match="box1 already holds this key"):
        vault.recipient_add(cfg, "box2", "device", age=a_pub)
    with pytest.raises(vault.VaultError, match="a rotation keeps its kind"):
        vault.recipient_add(cfg, "recovery", "device", age=h2_pub, replace=True)
    with pytest.raises(vault.VaultError, match="not declared: nothing to replace"):
        vault.recipient_add(cfg, "box9", "device", age=h2_pub, replace=True)
    entry, _ = vault.recipient_add(cfg, "heir", "person", age=h2_pub, replace=True, write=True)
    assert entry == {"kind": "person", "classes": ["private"], "why": "Ada's heir, private only", "age": h2_pub}

    old, new = tmp_path / "old.asc", tmp_path / "new.asc"
    old.write_text("-----BEGIN PGP PUBLIC KEY BLOCK-----\nOLD\n-----END PGP PUBLIC KEY BLOCK-----\n", encoding="utf-8")
    new.write_text("-----BEGIN PGP PUBLIC KEY BLOCK-----\nNEW\n-----END PGP PUBLIC KEY BLOCK-----\n", encoding="utf-8")
    vault.recipient_add(config.load(), "box2", "device", gpg=str(old), write=True)
    before = vault.recipients(config.load())[0]["box2"].fingerprint(brain.root)
    vault.recipient_add(config.load(), "box2", "device", gpg=str(new), write=True, replace=True)
    assert "NEW" in (brain.root / "vault" / "keys" / "box2.asc").read_text()
    assert vault.recipients(config.load())[0]["box2"].fingerprint(brain.root) != before


def test_floors_hold_for_each_store(brain, brain_home, capsys):
    """Review of #36, findings 4, 5, 10: a tenant's recovery key does not stand for the owner's stores. remove refuses
    to leave a store without its recovery key or under two keys; reseal refuses to seal a store to no recovery key;
    health names the store."""
    found = fake_age()
    (a, a_pub), (_, b_pub), (_, r_pub), (_, z_pub), (_, zr_pub) = keygen(5, found["age"])
    keystore.Memory.data["device"] = a
    team = {"team-z": ["z-ada", "z-rec"]}
    cfg = brain({"box1": {"kind": "device", "age": a_pub}, "box2": {"kind": "device", "age": b_pub},
                 "recovery": {"kind": "recovery", "age": r_pub}, "z-ada": {"kind": "person", "age": z_pub},
                 "z-rec": {"kind": "recovery", "age": zr_pub}}, tenants=team)
    vault.seal(cfg, "ledger", now=NOW, found=found)
    with pytest.raises(vault.VaultError, match="store ledger is sealed to no recovery key"):
        rotation.recipient_remove(cfg, "recovery")
    cfg = brain({"box1": {"kind": "device", "age": a_pub}, "recovery": {"kind": "recovery", "age": r_pub},
                 "z-ada": {"kind": "person", "age": z_pub}, "z-rec": {"kind": "recovery", "age": zr_pub}}, tenants=team)
    with pytest.raises(vault.VaultError, match="store ledger has 1 distinct key"):
        rotation.recipient_remove(cfg, "box1")

    cfg = brain({"box1": {"kind": "device", "age": a_pub}, "box2": {"kind": "device", "age": b_pub},
                 "z-ada": {"kind": "person", "age": z_pub}, "z-rec": {"kind": "recovery", "age": zr_pub}}, tenants=team)
    vault.health(cfg, now=NOW, found=found)
    assert "store ledger is sealed to no recovery key" in capsys.readouterr().out
    (p,) = rotation.reseal(cfg, apply=True, found=found)
    assert "sealed to no recovery key" in p["error"] and not p.get("done")


def test_a_cut_rotation_leaves_the_keystore_as_it_was(brain, brain_home, monkeypatch):
    """Review of #36, findings 9, 13, 14, 17: a rotation that fails after the keystore write puts the old key back;
    a rotation keeps its name; forget-previous refuses while the previous key is still declared."""
    found = fake_age()
    cfg = brain({})
    old = vault.device_init(cfg, "box1", now=NOW, found=found)
    (_, r_pub), = keygen(1, found["age"])
    cfg = brain({"box1": {"kind": "device", "age": old["public"]}, "recovery": {"kind": "recovery", "age": r_pub}})
    before, facts = keystore.Memory.data["device"], vault.device_file().read_text()
    with pytest.raises(vault.VaultError, match="keeps the name box1"):
        vault.device_init(cfg, "box1b", found=found, rotate=True)

    def full(path, text):
        raise OSError(28, "No space left on device")
    with monkeypatch.context() as m:   # never monkeypatch.undo(): it would drop the fixtures' BRAIN_HOME and keystore
        m.setattr(stateio, "write_atomic", full)   # device.json goes through brain.stateio
        with pytest.raises(vault.VaultError, match="stopped.*as it was"):
            vault.device_init(cfg, found=found, rotate=True)
    assert keystore.Memory.data == {"device": before} and vault.device_file().read_text() == facts
    assert keystore.backend().name == "memory" and str(vault.vault_dir()).startswith(str(brain_home))

    new = vault.device_init(cfg, found=found, rotate=True)
    vault.recipient_add(cfg, "box1", "device", age=new["public"], write=True, replace=True)
    vault.recipient_add(config.load(), "box1-old", "device", age=old["public"], write=True)   # the old key kept
    with pytest.raises(vault.VaultError, match="still declares the previous key \\(as box1-old\\)"):
        rotation.forget_previous(config.load(), found=found)


def test_reseal_survives_a_bad_manifest_and_keeps_what_ran_meanwhile(brain, brain_home, monkeypatch):
    """Review of #36, findings 15, 18: an unreadable manifest is that file's error, not a crash; the state saved at
    the end keeps a canary that ran during the reseal."""
    found = fake_age()
    (a, a_pub), (_, r_pub), (_, c_pub) = keygen(3, found["age"])
    keystore.Memory.data["device"] = a
    cfg = brain({"box1": {"kind": "device", "age": a_pub}, "recovery": {"kind": "recovery", "age": r_pub}})
    man = vault.seal(cfg, "ledger", now=NOW, found=found)
    mf = brain_home / "vault" / "sealed" / "ledger" / (man["file"] + ".json")
    cfg = brain({"box1": {"kind": "device", "age": a_pub}, "recovery": {"kind": "recovery", "age": r_pub},
                 "box2": {"kind": "device", "age": c_pub}})
    good = mf.read_text()
    mf.write_text(good[:40], encoding="utf-8")       # a manifest cut short
    (p,) = rotation.reseal(cfg, apply=True, found=found)
    assert "unreadable" in p["error"]
    mf.write_text(good, encoding="utf-8")
    real = rotation._reseal_one

    def with_a_canary(*args, **kwargs):
        st = vault.load_state()
        st["canary"]["box2"] = {"sealed_at": "meanwhile"}
        vault.save_state(st)
        return real(*args, **kwargs)
    monkeypatch.setattr(rotation, "_reseal_one", with_a_canary)
    (p,) = rotation.reseal(cfg, apply=True, found=found)
    assert p["done"] and vault.load_state()["canary"]["box2"] == {"sealed_at": "meanwhile"}


def test_device_rotation_keeps_the_previous_key_until_it_is_forgotten(brain, brain_home, tmp_path):
    """--rotate keeps the old key beside the new one; the sealed files open with it until reseal; forget-previous
    waits on config.json declaring the new key and on the re-seal, then deletes it."""
    found = fake_age()
    cfg = brain({})
    old = vault.device_init(cfg, "box1", now=NOW, found=found)
    (_, r_pub), = keygen(1, found["age"])
    cfg = brain({"box1": {"kind": "device", "age": old["public"]}, "recovery": {"kind": "recovery", "age": r_pub}})
    man = vault.seal(cfg, "ledger", now=NOW, found=found)
    sealed = brain_home / "vault" / "sealed" / "ledger" / man["file"]
    with pytest.raises(vault.VaultError, match="already has a device key.*--rotate"):
        vault.device_init(cfg, found=found)
    with pytest.raises(vault.VaultError, match="no previous device key"):
        rotation.forget_previous(cfg, found=found)
    old_value = keystore.Memory.data["device"]

    new = vault.device_init(cfg, found=found, rotate=True, now=NOW + timedelta(days=1))
    assert new["name"] == "box1" and new["public"] != old["public"] and new["previous"]["public"] == old["public"]
    assert keystore.Memory.data["device-previous"] == old_value != keystore.Memory.data["device"]
    assert "--replace --write" in new["declare"] and "AGE-SECRET" not in vault.device_file().read_text()
    with pytest.raises(vault.VaultError, match="last rotation is not finished"):
        vault.device_init(cfg, found=found, rotate=True)
    vault.open_sealed(cfg, sealed, tmp_path / "mid", found=found)          # the previous key still opens it
    with pytest.raises(vault.VaultError, match="does not declare the new key"):
        rotation.forget_previous(cfg, found=found)

    vault.recipient_add(cfg, "box1", "device", age=new["public"], host="box1", write=True, replace=True)
    cfg = config.load()
    assert any("rotation of box1" in s for s in vault.next_steps(vault.status(cfg, found)))
    with pytest.raises(vault.VaultError, match="1 sealed file.*reseal --apply first"):
        rotation.forget_previous(cfg, found=found)
    (done,) = rotation.reseal(cfg, apply=True, found=found)
    assert done["done"]
    assert rotation.forget_previous(cfg, found=found)["forgot"] == old["public"]
    assert "device-previous" not in keystore.Memory.data and "previous" not in vault.device()
    vault.open_sealed(cfg, sealed, tmp_path / "after", found=found)        # the new key alone opens it now
    assert tree(tmp_path / "after" / "ledger") == tree(brain_home / "ledger")


def test_open_drill_and_device_init_are_human_acts(monkeypatch):
    for var in vault.AGENT_ENV:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CLAUDECODE", "1")
    with pytest.raises(vault.VaultError, match="human act.*CLAUDECODE"):
        vault.human_only("brain vault open")
    monkeypatch.delenv("CLAUDECODE")
    vault.human_only("brain vault open")


def test_extraction_refuses_a_path_outside(tmp_path):
    bad = tmp_path / "bad.tar.gz"
    with tarfile.open(bad, "w:gz") as tar:
        info = tarfile.TarInfo("../escape.txt")
        info.size = 2
        tar.addfile(info, io.BytesIO(b"hi"))
    with pytest.raises(vault.VaultError, match="outside"):
        vault._safe_extract(bad, tmp_path / "out")
    assert not (tmp_path / "escape.txt").exists()


def test_pack_keeps_no_user_name(tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    (d / "a.txt").write_text("a", encoding="utf-8")
    assert vault.pack([(d, "d")], tmp_path / "x.tar.gz") == (1, 1)
    with tarfile.open(tmp_path / "x.tar.gz") as tar:
        assert [(m.name, m.uname, m.uid) for m in tar.getmembers()] == [("d/a.txt", "", 0)]


# --- recipients along the scope chain, tenants ---
def test_store_recipients_union_along_the_scope_chain(brain, monkeypatch):
    found = fake_age()
    pubs = [p for _, p in keygen(5, found["age"])]
    cfg = brain({"box1": {"kind": "device", "age": pubs[0]}, "recovery": {"kind": "recovery", "age": pubs[1]},
                 "colleague": {"kind": "person", "age": pubs[2]}, "z-ada": {"kind": "person", "age": pubs[3]},
                 "z-bob": {"kind": "person", "age": pubs[4]}},
                tenants={"team-z": ["z-ada", "z-bob"]})
    root = brain.root
    (root / "projects.yaml").write_text("brain:\n  root: .\nwork:\n  root: work\n  parent: finance\n",
                                        encoding="utf-8")
    (root / "scopes.yaml").write_text("v: 1\nscopes:\n  pro: {type: sphere}\n"
                                      "  acme: {type: company, parent: pro, vault: {recipients: [colleague]}}\n"
                                      "  finance: {type: unit, parent: acme}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(root / "projects.yaml"))
    cfg = config.load(root)
    assert vault.check(cfg=cfg) == []
    ledger = vault.store(cfg, "ledger")
    assert [r.name for r in vault.for_store(cfg, ledger)] == ["box1", "recovery"]
    ledger.project = "work"
    assert [r.name for r in vault.for_store(cfg, ledger)] == ["box1", "recovery", "colleague"]
    assert [r.name for r in vault.for_store(cfg, vault.store(cfg, "team"))] == ["z-ada", "z-bob"]


# --- the device key, the canary, health, the drill ---
def test_device_init_canary_health_and_drill(brain, brain_home, tmp_path, capsys):
    found = fake_age()
    cfg = brain({})
    facts = vault.device_init(cfg, "box1", now=NOW, found=found)
    assert facts["adapter"] == "age" and facts["keystore"] == "memory" and facts["public"].startswith("age1fake")
    assert "AGE-SECRET" not in json.dumps(facts) and "AGE-SECRET" not in vault.device_file().read_text()
    assert keystore.Memory.data["device"].startswith("AGE-SECRET-KEY-")
    assert "--kind device --age " + facts["public"] in facts["declare"]
    with pytest.raises(vault.VaultError, match="already has a device key"):
        vault.device_init(cfg, "box1", found=found)

    (rec, rec_pub), = keygen(1, found["age"])
    cfg = brain({"box1": {"kind": "device", "age": facts["public"]}, "recovery": {"kind": "recovery", "age": rec_pub}})
    assert vault.health(cfg, now=NOW, found=found) == 1  # no canary yet
    assert "never sealed" in capsys.readouterr().out

    res = vault.canary(cfg, now=NOW, found=found)
    assert res["box1"]["opened_by"] == "device" and res["box1"]["error"] == ""
    assert res["recovery"]["sealed_at"] and not res["recovery"]["opened_at"]
    assert vault.health(cfg, now=NOW + timedelta(hours=1), found=found) == 0
    out = capsys.readouterr().out
    assert "vault OK (2 recipient(s), device box1 (age, memory)" in out and "recovery: never drilled" in out

    assert vault.health(cfg, now=NOW + timedelta(hours=30), found=found) == 1
    assert "sealed 30 h ago (more than 26 h)" in capsys.readouterr().out

    key_file = tmp_path / "paper.txt"
    key_file.write_text(rec + "\n", encoding="utf-8")
    assert vault.drill(cfg, "recovery", str(key_file), now=NOW, found=found)["drilled_at"] == "2026-11-02T12:00:00Z"
    vault.health(cfg, now=NOW + timedelta(hours=1), found=found)
    assert "never drilled" not in capsys.readouterr().out
    with pytest.raises(vault.VaultError):
        vault.drill(cfg, "box1", str(key_file), found=found)  # the paper key is not box1's

    keystore.Memory.data.clear()  # the keystore lost the device key: the canary cannot open, health fails
    vault.canary(cfg, now=NOW, found=found)
    assert vault.health(cfg, now=NOW, found=found) == 1
    assert "missing from the keystore" in capsys.readouterr().out


class Tty(io.StringIO):
    def isatty(self):
        return True


def test_drill_asks_the_key_hidden_and_hands_it_to_age(brain, monkeypatch, capsys):
    """The recovery key is typed hidden (getpass: no echo, Enter ends it, no end-of-input key to find), checked for its
    shape and handed to age on its stdin; a wrong line, nothing or Ctrl+C opens nothing and never echoes the line."""
    found = fake_age()
    (dev, dev_pub), (rec, rec_pub) = keygen(2, found["age"])
    keystore.Memory.data["device"] = dev
    cfg = brain({"box1": {"kind": "device", "age": dev_pub}, "recovery": {"kind": "recovery", "age": rec_pub}})
    vault.canary(cfg, now=NOW, found=found)
    asked = []
    monkeypatch.setattr(vault.sys, "stdin", Tty())
    monkeypatch.setattr(vault.getpass, "getpass", lambda prompt: asked.append(prompt) or f"  {rec}  ")
    assert vault.drill(cfg, "recovery", "-", now=NOW, found=found)["drilled_at"] == "2026-11-02T12:00:00Z"
    assert asked == [vault.KEY_PROMPT] and rec not in capsys.readouterr().out
    assert "SECRET key" in vault.KEY_PROMPT and "not the public age1" in vault.KEY_PROMPT
    for given, why in ((rec_pub, "that is the public key"), ("# created: 2026-11-03", "not an age secret key"),
                       ("", "not an age secret key")):
        monkeypatch.setattr(vault.getpass, "getpass", lambda prompt, g=given: g)
        with pytest.raises(vault.VaultError, match=why) as exc:
            vault.drill(cfg, "recovery", "-", found=found)
        assert not given or given not in str(exc.value)

    def interrupted(prompt):
        raise KeyboardInterrupt
    monkeypatch.setattr(vault.getpass, "getpass", interrupted)
    with pytest.raises(vault.VaultError, match="no key given"):
        vault.drill(cfg, "recovery", "-", found=found)
    with pytest.raises(vault.VaultError):
        monkeypatch.setattr(vault.getpass, "getpass", lambda prompt: dev)
        vault.drill(cfg, "recovery", "-", found=found)  # the device key is not the recovery key

    monkeypatch.setattr(vault.sys, "stdin", io.StringIO(rec + "\n"))  # not a terminal: its first line
    assert vault.drill(cfg, "recovery", "-", now=NOW, found=found)["recipient"] == "recovery"
    monkeypatch.setattr(vault.sys, "stdin", io.StringIO(""))
    with pytest.raises(vault.VaultError, match="no key given"):
        vault.drill(cfg, "recovery", "-", found=found)


def test_a_failure_names_ages_error_not_its_report_line():
    err = (b"age: error: no identity matched any of the recipients\n"
           b"age: report unexpected or unhelpful errors at https://filippo.io/age/report\n")
    with pytest.raises(vault.VaultError) as exc:
        vault._fail(vault.subprocess.CompletedProcess([], 1, b"", err), "age: open")
    assert str(exc.value) == "age: open failed (exit 1): age: error: no identity matched any of the recipients"


def test_the_owner_prompts_name_what_to_do(brain, monkeypatch):
    """gpg reads its key block itself: the prompt says how the console ends the input; age missing from a terminal
    opened before the install says to open a new one."""
    assert "Ctrl+Z alone on the new line" in vault.paste_prompt(windows=True)
    assert "Ctrl+D" in vault.paste_prompt(windows=False) and "Ctrl+Z" not in vault.paste_prompt(windows=False)
    found = fake_age()
    (dev, dev_pub), (rec, rec_pub) = keygen(2, found["age"])
    keystore.Memory.data["device"] = dev
    cfg = brain({"box1": {"kind": "device", "age": dev_pub}, "recovery": {"kind": "recovery", "age": rec_pub}})
    vault.canary(cfg, now=NOW, found=found)
    with pytest.raises(vault.VaultError, match="age not found on this terminal's PATH .*open a new one"):
        vault.drill(cfg, "recovery", "-", found={"age": vault.Age([], []), "gpg": vault.Gpg([])})


def test_health_off_and_next_steps(brain, capsys):
    (brain.root / config.FILE).write_text(json.dumps({"v": 1, "identity": {"owner": "Ada"}}), encoding="utf-8")
    assert vault.health(config.load(brain.root)) == 0
    assert "vault OFF (config.json declares no vault" in capsys.readouterr().out
    found = {"age": vault.Age([], []), "gpg": vault.Gpg([])}
    (_, a_pub), (_, b_pub) = keygen(2, fake_age()["age"])
    cfg = brain({"box1": {"kind": "device", "age": a_pub}, "recovery": {"kind": "recovery", "age": b_pub}})
    assert vault.health(cfg, found=found) == 0
    assert "OFF on this machine (neither age nor gpg found" in capsys.readouterr().out
    steps = vault.next_steps(vault.status(cfg, found))
    assert steps[0].startswith("install age") and "brain vault device init" in steps[1]
    assert any("brain vault canary" in s for s in steps) and any("drill" in s for s in steps)
    one = brain({"box1": {"kind": "device", "age": a_pub}})
    assert any("age-keygen" in s and "on paper" in s for s in vault.next_steps(vault.status(one, found)))
    assert vault.render_status(vault.status(one, found))[-1] == f"the runbook: {vault.RUNBOOK}"
    assert (Path(vault.__file__).parents[2] / "docs" / "vault.md").is_file()  # the page RUNBOOK names, in this repo


def test_gpg_home_is_msys_shaped_for_git_for_windows():
    ad = vault.Gpg(["gpg"])
    ad._msys = True
    assert ad.home(Path("D:\\work\\demo\\x")) == "/d/work/demo/x"
    ad._msys = False
    assert ad.home(Path("D:\\work\\demo\\x")) == str(Path("D:\\work\\demo\\x"))


def test_canary_leaves_no_plaintext_behind(brain, brain_home):
    found = fake_age()
    (_, a_pub), (_, b_pub) = keygen(2, found["age"])
    cfg = brain({"box1": {"kind": "device", "age": a_pub}, "recovery": {"kind": "recovery", "age": b_pub}})
    vault.canary(cfg, now=NOW, found=found)
    st = vault.load_state()
    assert set(st["canary"]) == {"box1", "recovery"}
    blob = (brain_home / "vault" / "canary" / "recovery.age").read_bytes()
    assert hashlib.sha256(blob).hexdigest() != st["canary"]["recovery"]["digest"]
    assert (brain_home / "vault" / "tmp").is_dir() and not any((brain_home / "vault" / "tmp").iterdir())


# --- the command line ---
def test_cli_refuses_the_human_acts_in_an_agent_session(brain, monkeypatch, capsys, tmp_path):
    from brain import cli
    found = fake_age()
    (_, a_pub), (_, b_pub) = keygen(2, found["age"])
    brain({"box1": {"kind": "device", "age": a_pub}, "recovery": {"kind": "recovery", "age": b_pub}})
    monkeypatch.setenv("CLAUDECODE", "1")
    for argv in (["vault", "open", str(tmp_path / "x.tar.gz.age")], ["vault", "drill", "recovery"],
                 ["vault", "device", "init"], ["vault", "device", "init", "--rotate"],
                 ["vault", "device", "forget-previous"], ["vault", "reseal", "--apply", "--identity", "-"]):
        assert cli.main(["--root", str(brain.root), *argv]) == 2
        assert "is a human act: run it in your own terminal" in capsys.readouterr().err
    assert keystore.Memory.data == {}


def test_cli_status_health_and_classes(brain, capsys):
    from brain import cli
    (brain.root / config.FILE).write_text(json.dumps({"v": 1, "identity": {"owner": "Ada"}}), encoding="utf-8")
    assert cli.main(["health", "vault"]) == 0
    assert "vault OFF" in capsys.readouterr().out
    assert vault.health(config.load(brain.root), named=False) == 0  # health --all: silent without a vault block
    assert capsys.readouterr().out == ""
    assert cli.main(["--root", str(brain.root), "classes", "--matrix"]) == 0
    assert capsys.readouterr().out.splitlines()[1].startswith("public")
    found = fake_age()
    (_, a_pub), = keygen(1, found["age"])
    brain({"box1": {"kind": "device", "age": a_pub}})
    assert cli.main(["--root", str(brain.root), "vault", "status"]) == 0
    out = capsys.readouterr().out
    assert "recipients (1, 2 at least per sealed store):" in out and "next (yours):" in out
    assert cli.main(["--root", str(brain.root), "vault", "recipient", "add", "recovery", "--kind", "recovery",
                     "--age", "AGE-SECRET-" + "KEY-1" + "Q" * 58]) == 2
    assert "private key" in capsys.readouterr().err


def test_an_age_identity_is_a_secret_to_the_scan():
    from brain import secretscan
    ident = "AGE-SECRET-" + "KEY-1" + "QPZRY9X8GF2TVDW0S3JN54KHCE6MUA7L" + "Q" * 26
    assert secretscan.find(f"key: {ident}") == ["age-secret-key"]
    assert secretscan.find("age1" + "q" * 58) == []  # a public recipient is not a secret


def test_device_json_goes_through_stateio_and_a_newer_one_stops_device_init(brain, brain_home):
    """wi-brain-state-safe-io-rest: device.json is truth-local; a newer brain's stops device init before the keystore
    is touched, an unreadable one is read as none and set aside by the next write."""
    found = fake_age()
    cfg = brain({})
    f = vault.device_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text('{"v": 2, "name": "box9"}', encoding="utf-8")
    with pytest.raises(vault.VaultError, match="newer brain.*brain update"):
        vault.device_init(cfg, "box1", now=NOW, found=found)
    assert keystore.Memory.data == {} and f.read_text(encoding="utf-8") == '{"v": 2, "name": "box9"}'
    assert vault.device() == {"name": "box9"}  # read as it is
    f.write_text("{bad", encoding="utf-8")
    assert vault.device() == {} and f.exists()  # a read moves nothing
    vault.device_init(cfg, "box1", now=NOW, found=found)
    disk = json.loads(f.read_text(encoding="utf-8"))
    assert list(disk)[:2] == ["v", "name"] and disk["v"] == vault.DEVICE_V and disk["name"] == "box1"
    assert len(list(f.parent.glob("device.json.unreadable-*"))) == 1


def test_device_rotation_keeps_the_keys_a_newer_brain_added(brain, brain_home):
    """wi-brain-state-safe-io-rest: a newer minor brain's key in device.json (still v 1) survives --rotate; the keys
    this engine writes are new."""
    found = fake_age()
    cfg = brain({})
    old = vault.device_init(cfg, "box1", now=NOW, found=found)
    f = vault.device_file()
    disk = json.loads(f.read_text(encoding="utf-8"))
    disk["later"] = {"kept": True}
    f.write_text(json.dumps(disk), encoding="utf-8")
    new = vault.device_init(cfg, found=found, rotate=True, now=NOW + timedelta(days=1))
    disk = json.loads(f.read_text(encoding="utf-8"))
    assert disk["later"] == {"kept": True} and new["later"] == {"kept": True}
    assert disk["public"] == new["public"] != old["public"] and disk["previous"]["public"] == old["public"]
    assert list(disk)[:2] == ["v", "name"]
