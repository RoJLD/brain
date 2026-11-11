"""brain spool (wi-brain-storage-split): the sealed local spool, put after a secret scan, sent checked by hash, pruned,
its last push's age in brain health."""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from brain import classes, config, keystore, secretscan, spool, vault

FAKE = Path(__file__).parent / "fixtures" / "fake_age.py"
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
STORES = {"ledger": {"class": "sealed", "paths": ["$BRAIN_HOME/ledger"], "to": ["offsite", "backup"]},
          "usage": {"class": "sealed", "paths": ["$BRAIN_HOME/usage"], "to": ["offsite", "backup"]},
          "sessions": {"class": "sealed", "paths": ["$BRAIN_HOME/sessions"]},
          "data": {"class": "resident", "paths": ["$BRAIN_HOME/data"]},
          "keys": {"class": "secret", "paths": ["$BRAIN_HOME/keys"]},
          "spool": {"class": "sealed", "paths": ["$BRAIN_HOME/spool"]},
          "repo": {"class": "private", "paths": ["**"]}}


def fake_age() -> dict:
    return {"age": vault.Age([sys.executable, str(FAKE)], [sys.executable, str(FAKE), "keygen"]),
            "gpg": vault.Gpg([])}


@pytest.fixture
def brain(tmp_path, monkeypatch, brain_home):
    """A personal brain with two age recipients (the fake age), a ledger and a usage store; ``brain(**spool)`` writes
    config.json with that spool block (none by default) and returns the config."""
    root = tmp_path / "brain"
    root.mkdir()
    monkeypatch.setenv("BRAIN_CONFIG", str(root / config.FILE))
    monkeypatch.setenv("BRAIN_KEYSTORE", "memory")
    keystore.Memory.data.clear()
    for var in vault.AGENT_ENV:
        monkeypatch.delenv(var, raising=False)
    found = fake_age()
    (a, a_pub), (b, b_pub) = (found["age"].keygen(f"test {i}") for i in range(2))
    (brain_home / "ledger").mkdir(parents=True)
    (brain_home / "ledger" / "events-2026-11.jsonl").write_bytes(b'{"e": 1}\n{"e": 2}\n')
    (brain_home / "usage").mkdir()
    # a key of the engine's own JSON that the password heuristics would take for one: not refused
    fake_hit = '{"v": 2, "mdp":[0,1.2345],"next": "x"}\n'  # gitleaks:allow
    (brain_home / "usage" / "sessions.json").write_text(fake_hit, encoding="utf-8")

    def write(spool_block: dict | None = None, **extra) -> config.Config:
        data = {"v": 1, "identity": {"owner": "Ada"}, "classes": {"stores": STORES},
                "vault": {"recipients": {"box1": {"kind": "device", "age": a_pub},
                                         "recovery": {"kind": "recovery", "age": b_pub}}}, **extra}
        if spool_block is not None:
            data["spool"] = spool_block
        (root / config.FILE).write_text(json.dumps(data), encoding="utf-8")
        return config.load(root)

    write.root, write.found, write.idents = root, found, (a, b)
    return write


def opened(cfg, brain, sealed: Path, out: Path) -> dict:
    keystore.Memory.data["device"] = brain.idents[0]
    vault.open_sealed(cfg, sealed, out, found=brain.found)
    return {p.relative_to(out).as_posix(): p.read_bytes() for p in sorted(out.rglob("*")) if p.is_file()}


# --- put and push ---
def test_push_seals_the_set_into_the_spool_and_records_its_hash(brain, brain_home, tmp_path):
    cfg = brain()
    res = spool.push(cfg, now=NOW, found=brain.found)
    assert [p["store"] for p in res["put"]] == ["ledger", "usage"] and res["empty"] == ["sessions"]
    assert not res["errors"] and res["remote"] == ""
    idx = json.loads((brain_home / "spool" / "spool.json").read_text(encoding="utf-8"))
    assert idx["v"] == 1 and idx["ok_at"] == "2026-11-11T12:00:00Z"
    rel = "ledger/ledger-20261111T120000Z.tar.gz.age"
    e = idx["files"][rel]
    sealed = brain_home / "spool" / rel
    assert e["kind"] == "snapshot" and e["sent"] == "" and e["sha256"] == vault._sha256(sealed)
    assert b'"e": 1' not in sealed.read_bytes()                       # sealed, not in clear
    assert (sealed.parent / (sealed.name + ".json")).is_file()         # brain.vault's manifest beside it
    got = opened(cfg, brain, sealed, tmp_path / "out")
    assert got == {"ledger/events-2026-11.jsonl": b'{"e": 1}\n{"e": 2}\n'}


def test_an_unchanged_store_is_not_put_again_a_changed_one_is(brain, brain_home):
    cfg = brain()
    spool.push(cfg, ["ledger"], now=NOW, found=brain.found)
    res = spool.push(cfg, ["ledger"], now=NOW + timedelta(hours=1), found=brain.found)
    assert res["unchanged"] == ["ledger"] and res["put"] == []
    f = brain_home / "ledger" / "events-2026-11.jsonl"
    f.write_text(f.read_text(encoding="utf-8") + '{"e": 3}\n', encoding="utf-8")
    res = spool.push(cfg, ["ledger"], now=NOW + timedelta(hours=2), found=brain.found)
    assert [p["file"] for p in res["put"]] == ["ledger/ledger-20261111T140000Z.tar.gz.age"]


def test_a_dry_run_writes_nothing(brain, brain_home):
    cfg = brain()
    res = spool.push(cfg, now=NOW, found=brain.found, dry_run=True)
    assert [p["store"] for p in res["put"]] == ["ledger", "usage"] and all(p["plan"] for p in res["put"])
    assert not (brain_home / "spool").exists()


@pytest.mark.parametrize("store, why", [("data", "never lets it leave"), ("keys", "never lets it leave"),
                                         ("spool", "does not hold itself"), ("nope", "no store nope")])
def test_a_store_that_must_not_leave_is_refused(brain, brain_home, store, why):
    cfg = brain()
    (brain_home / "data").mkdir()
    (brain_home / "data" / "x.csv").write_text("1\n", encoding="utf-8")
    with pytest.raises(spool.SpoolError, match=why):
        spool.put(cfg, store, now=NOW, found=brain.found)
    res = spool.push(cfg, [store, "ledger"], now=NOW, found=brain.found)
    assert res["errors"][0].startswith(f"{store}: ") and [p["store"] for p in res["put"]] == ["ledger"]
    assert json.loads((brain_home / "spool" / "spool.json").read_text(encoding="utf-8"))["last"]["errors"] == 1


def test_a_secret_in_a_store_stops_its_put_and_names_no_value(brain, brain_home):
    cfg = brain()
    token = "ghp_" + "A1b2C3d4" * 5
    (brain_home / "ledger" / "leak.log").write_text(f"ok\nthe token {token} here\n", encoding="utf-8")
    with pytest.raises(spool.SpoolError) as exc:
        spool.put(cfg, "ledger", now=NOW, found=brain.found)
    assert "ledger/leak.log:2: github-token" in str(exc.value) and token not in str(exc.value)
    assert not (brain_home / "spool" / "ledger").exists()


def test_items_are_put_as_their_own_entry(brain, brain_home, tmp_path):
    """The session archive's way in: given paths, an items entry; the store's snapshot record is not touched."""
    cfg = brain()
    t = tmp_path / "t1.jsonl"
    t.write_bytes(b'{"turn": 1}\n')
    e = spool.put(cfg, "ledger", [t], now=NOW, found=brain.found)
    assert e["kind"] == "items" and e["file"] == "ledger/ledger-20261111T120000Z.tar.gz.age"
    e2 = spool.put(cfg, "ledger", [t], now=NOW, found=brain.found)      # the same second: a name of its own
    assert e2["file"] == "ledger/ledger-20261111T120000Z-2.tar.gz.age"
    idx = json.loads((brain_home / "spool" / "spool.json").read_text(encoding="utf-8"))
    assert idx["stores"] == {} and set(idx["files"]) == {e["file"], e2["file"]}
    assert opened(cfg, brain, brain_home / "spool" / e["file"], tmp_path / "o") == {"t1.jsonl": b'{"turn": 1}\n'}


def test_an_index_a_newer_brain_wrote_is_read_only(brain, brain_home):
    cfg = brain()
    (brain_home / "spool").mkdir()
    (brain_home / "spool" / "spool.json").write_text('{"v": 9, "files": {}}', encoding="utf-8")
    with pytest.raises(spool.SpoolError, match="newer brain"):
        spool.push(cfg, now=NOW, found=brain.found)
    assert sorted(p.name for p in (brain_home / "spool").iterdir()) == ["spool.json"]
    assert spool.status(cfg)["readonly"]


# --- send ---
def test_without_a_remote_the_files_wait(brain):
    cfg = brain()
    res = spool.push(cfg, now=NOW, found=brain.found)
    assert res["sent"] == [] and spool.status(cfg)["waiting"] == 2


def test_an_absent_remote_leaves_them_waiting(brain, tmp_path):
    cfg = brain({"remote": str(tmp_path / "nas-offline")})
    res = spool.push(cfg, now=NOW, found=brain.found)
    assert len(res["sent"]) == 2 and all("not reachable" in r["error"] for r in res["sent"])
    assert not (tmp_path / "nas-offline").exists() and spool.status(cfg)["waiting"] == 2
    idx = json.loads(spool.index_file().read_text(encoding="utf-8"))
    assert idx["last"]["errors"] == 2 and "ok_at" not in idx


def test_send_copies_and_checks_each_file_by_hash(brain, brain_home, tmp_path):
    remote = tmp_path / "remote"
    remote.mkdir()
    cfg = brain({"remote": str(remote)})
    res = spool.push(cfg, now=NOW, found=brain.found)
    assert [r["file"] for r in res["sent"] if r.get("sent")] == ["ledger/ledger-20261111T120000Z.tar.gz.age",
                                                                 "usage/usage-20261111T120000Z.tar.gz.age"]
    for r in res["sent"]:
        assert vault._sha256(remote / r["file"]) == vault._sha256(brain_home / "spool" / r["file"])
        assert (remote / (r["file"] + ".json")).is_file()
    assert spool.status(cfg)["waiting"] == 0 and spool.send(cfg, now=NOW) == []


def test_a_file_changed_in_the_spool_is_not_sent_and_fails_the_health(brain, brain_home, tmp_path, capsys):
    cfg = brain()
    spool.push(cfg, ["ledger"], now=NOW, found=brain.found)
    rel = "ledger/ledger-20261111T120000Z.tar.gz.age"
    with open(brain_home / "spool" / rel, "ab") as fh:
        fh.write(b"rot")
    assert spool.verify() == [(rel, "sha256 does not match the index")]
    remote = tmp_path / "remote"
    remote.mkdir()
    cfg = brain({"remote": str(remote)})
    (r,) = spool.send(cfg, now=NOW)
    assert "no longer matches" in r["error"] and not (remote / rel).exists()
    assert spool.health(cfg, now=NOW) == 1
    assert "spool FAIL" in capsys.readouterr().out


# --- prune ---
def test_prune_keeps_the_newest_snapshots_and_unsent_items(brain, brain_home, tmp_path):
    cfg = brain({"keep": 2})
    f = brain_home / "ledger" / "events-2026-11.jsonl"
    for h in range(4):
        f.write_text(f'{{"e": {h}}}\n', encoding="utf-8")
        os.utime(f, (1_800_000_000 + h, 1_800_000_000 + h))
        spool.push(cfg, ["ledger"], now=NOW + timedelta(hours=h), found=brain.found)
    t = tmp_path / "t.jsonl"
    t.write_text("{}\n", encoding="utf-8")
    items = [spool.put(cfg, "ledger", [t], now=NOW + timedelta(minutes=m), found=brain.found)["file"]
             for m in range(3)]
    assert spool.prune(cfg) == []                       # unsent items are never pruned; the snapshots already were
    left = sorted(p.name for p in (brain_home / "spool" / "ledger").glob("*.age"))
    assert left == sorted([Path(i).name for i in items] + ["ledger-20261111T140000Z.tar.gz.age",
                                                           "ledger-20261111T150000Z.tar.gz.age"])
    remote = tmp_path / "remote"
    remote.mkdir()
    cfg = brain({"keep": 2, "remote": str(remote)})
    spool.send(cfg, now=NOW)
    assert spool.prune(cfg) == [items[0]]
    assert not (brain_home / "spool" / (items[0] + ".json")).exists()


# --- the health ---
def test_health_is_off_until_a_first_push(brain, capsys):
    cfg = brain()
    assert spool.health(cfg, now=NOW) == 0
    assert "spool OFF" in capsys.readouterr().out
    assert spool.health(cfg, now=NOW, named=False) == 0
    assert capsys.readouterr().out == ""


def test_health_gives_the_last_push_age_and_warns_when_old(brain, capsys):
    cfg = brain()
    spool.push(cfg, now=NOW, found=brain.found)
    assert spool.health(cfg, now=NOW + timedelta(hours=3)) == 0
    out = capsys.readouterr().out
    assert "spool OK (last push 3 h ago, 2 file(s) waiting" in out and "warning" not in out
    assert spool.health(cfg, now=NOW + timedelta(days=8)) == 0
    assert "spool warning: no push without an error for more than 7 d" in capsys.readouterr().out


def test_brain_health_spool_and_the_cli(brain, brain_home, capsys):
    from brain import cli
    cfg = brain()
    root = str(brain.root)
    assert cli.main(["--root", root, "spool", "push", "--dry-run"]) == 0
    assert "to put: ledger" in capsys.readouterr().out
    spool.push(cfg, now=NOW, found=brain.found)
    assert cli.main(["--root", root, "spool", "status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["waiting"] == 2
    assert cli.main(["--root", root, "spool", "verify"]) == 0
    assert cli.main(["--root", root, "health", "spool"]) == 0
    assert "spool OK" in capsys.readouterr().out
    assert cli.main(["--root", root, "spool", "push", "data"]) == 1
    assert "error: data: store data: its class never lets it leave" in capsys.readouterr().out


# --- the pieces it stands on ---
def test_the_spool_is_an_engine_store_sealed():
    k = classes.ENGINE_STORES["spool"]
    assert (k.path, k.cls, k.format) == ("$BRAIN_HOME/spool", "sealed", "truth-local")


def test_scan_file_finds_shaped_secrets_by_line_and_skips_binaries(tmp_path):
    t = tmp_path / "a.log"
    t.write_text("one\n" + "x hf_" + "a1B2" * 9 + "\n" + 'password = "hunter2hunter2"\n', encoding="utf-8")  # gitleaks:allow
    assert secretscan.scan_file(t) == [(2, "huggingface-token")]       # the heuristics are not the spool's
    assert (3, "password-quoted") in secretscan.scan_file(t, secretscan.PATTERNS)
    b = tmp_path / "b.db"
    b.write_bytes(b"SQLite\0" + b"hf_" + b"a1B2" * 9)
    assert secretscan.scan_file(b) == []
