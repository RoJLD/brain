import hashlib
import io
import json
import shutil
import sys
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from brain import config, keystore, vault

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


def keygen(n: int, ad: vault.Adapter) -> list[tuple[str, str]]:
    return [ad.keygen(f"test {i}") for i in range(n)]


def tree(d: Path) -> dict:
    return {p.relative_to(d).as_posix(): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


# --- the round trips ---
def test_gpg_seal_then_open_with_each_of_two_recipients(brain, brain_home, tmp_path):
    """Real cryptography: a store sealed to two gpg recipients opens with either key, and not with a third."""
    ad = vault.Gpg()
    if not ad.found():
        pytest.skip("gpg not available")
    (a, a_pub), (b, b_pub), (c, _) = keygen(3, ad)
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
    for i, ident in enumerate((a, b)):
        out = tmp_path / f"opened{i}"
        ad.open(sealed, tmp_path / f"plain{i}", ident=ident)
        vault._safe_extract(tmp_path / f"plain{i}", out)
        assert tree(out / "ledger") == tree(brain_home / "ledger")
    with pytest.raises(vault.VaultError):
        ad.open(sealed, tmp_path / "nope", ident=c)


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
    for given in (rec_pub, "# created: 2026-11-03", ""):
        monkeypatch.setattr(vault.getpass, "getpass", lambda prompt, g=given: g)
        with pytest.raises(vault.VaultError, match="not an age secret key") as exc:
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
                 ["vault", "device", "init"]):
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
