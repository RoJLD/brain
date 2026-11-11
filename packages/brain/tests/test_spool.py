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
    assert "spool OK (last push without an error 3 h ago, 2 file(s) waiting" in out and "warning" not in out
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
    heuristic = 'password = "hunter2hunter2"\n'  # gitleaks:allow
    t.write_text("one\n" + "x hf_" + "a1B2" * 9 + "\n" + heuristic, encoding="utf-8")
    assert secretscan.scan_file(t) == [(2, "huggingface-token")]       # the heuristics are not the spool's
    assert (3, "password-quoted") in secretscan.scan_file(t, secretscan.PATTERNS)
    b = tmp_path / "b.db"
    b.write_bytes(b"SQLite\0" + b"hf_" + b"a1B2" * 9)
    assert secretscan.scan_file(b) == []


# --- what the review found (wi-brain-storage-split) ---
def test_a_change_of_recipients_seals_again_and_the_stale_file_is_never_sent(brain, brain_home, tmp_path):
    cfg = brain()
    spool.push(cfg, ["ledger"], now=NOW, found=brain.found)
    _, c_pub = brain.found["age"].keygen("test 2")
    data = json.loads((brain.root / config.FILE).read_text(encoding="utf-8"))
    data["vault"]["recipients"]["box2"] = {"kind": "device", "age": c_pub}
    remote = tmp_path / "remote"
    remote.mkdir()
    data["spool"] = {"remote": str(remote)}
    (brain.root / config.FILE).write_text(json.dumps(data), encoding="utf-8")
    cfg = config.load(brain.root)
    stale = "ledger/ledger-20261111T120000Z.tar.gz.age"
    (r,) = spool.send(cfg, now=NOW)
    assert r["file"] == stale and "no longer its store" in r["error"] and not (remote / stale).exists()
    res = spool.push(cfg, ["ledger"], now=NOW + timedelta(hours=1), found=brain.found)
    assert [p["file"] for p in res["put"]] == ["ledger/ledger-20261111T130000Z.tar.gz.age"]   # content unchanged
    assert len(res["put"][0]["recipients"]) == 3 and stale in res["pruned"]                  # superseded, not sent
    assert [x["file"] for x in res["sent"]] == ["ledger/ledger-20261111T130000Z.tar.gz.age"] and not res["errors"]


def test_send_keeps_an_entry_put_while_it_copied(brain, brain_home, tmp_path, monkeypatch):
    remote = tmp_path / "remote"
    remote.mkdir()
    cfg = brain({"remote": str(remote)})
    spool.push(cfg, ["ledger"], now=NOW, found=brain.found)
    spool.put(cfg, "usage", now=NOW, found=brain.found)
    t = tmp_path / "t.jsonl"
    t.write_bytes(b"{}\n")
    real = spool._send_one

    def slow(src, target, sha):   # another writer puts a file while the copy runs
        if not slow.done:
            slow.done = True
            spool.put(cfg, "ledger", [t], now=NOW + timedelta(minutes=1), found=brain.found)
        return real(src, target, sha)
    slow.done = False
    monkeypatch.setattr(spool, "_send_one", slow)
    spool.send(cfg, now=NOW)
    files = json.loads(spool.index_file().read_text(encoding="utf-8"))["files"]
    assert "ledger/ledger-20261111T120100Z.tar.gz.age" in files and len(files) == 3


def test_a_copy_that_does_not_match_or_a_missing_file_is_not_sent(brain, brain_home, tmp_path, monkeypatch):
    remote = tmp_path / "remote"
    remote.mkdir()
    cfg = brain({"remote": str(remote)})
    spool.push(cfg, now=NOW, found=brain.found)       # both sent
    spool.put(cfg, "ledger", [brain_home / "ledger" / "events-2026-11.jsonl"], now=NOW, found=brain.found)
    real = spool.shutil.copyfile

    def bad_copy(src, dst):
        real(src, dst)
        if str(dst).endswith(".part"):
            with open(dst, "ab") as fh:
                fh.write(b"x")
    monkeypatch.setattr(spool.shutil, "copyfile", bad_copy)
    (r,) = spool.send(cfg, now=NOW)
    assert "copy's sha256 does not match" in r["error"] and not list(remote.rglob("*.part"))
    monkeypatch.setattr(spool.shutil, "copyfile", real)
    (brain_home / "spool" / r["file"]).unlink()
    (r2,) = spool.send(cfg, now=NOW)
    assert r2["error"] == "missing from the spool"
    assert spool.health(cfg, now=NOW) == 1                 # a waiting file is gone: it would never arrive


def test_items_are_checked(brain, brain_home, tmp_path):
    cfg = brain()
    with pytest.raises(spool.SpoolError, match="no item given"):
        spool.put(cfg, "ledger", [], now=NOW, found=brain.found)
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    for d in ("a", "b"):
        (tmp_path / d / "x.txt").write_bytes(d.encode())
    with pytest.raises(spool.SpoolError, match="share a name in the archive: x.txt"):
        spool.put(cfg, "ledger", [tmp_path / "a" / "x.txt", tmp_path / "b" / "x.txt"], now=NOW, found=brain.found)
    (brain_home / "keys").mkdir()
    (brain_home / "keys" / "k.txt").write_bytes(b"not a shaped secret")
    with pytest.raises(spool.SpoolError, match="in store keys, whose class never lets it leave"):
        spool.put(cfg, "ledger", [brain_home / "keys" / "k.txt"], now=NOW, found=brain.found)


def test_prune_keeps_the_newest_of_one_second(brain, brain_home, tmp_path):
    cfg = brain({"keep": 1})
    t = tmp_path / "t.jsonl"
    t.write_bytes(b"{}\n")
    puts = [spool.put(cfg, "ledger", [t], now=NOW, found=brain.found)["file"] for _ in range(3)]
    idx_st, idx = spool.load_index(write=True)
    for rel in puts:
        idx["files"][rel]["sent"] = "2026-11-11T12:00:00Z"
    spool._save(idx_st, idx)
    assert sorted(spool.prune(cfg)) == sorted(puts[:2])     # -3 is the newest, kept
    assert puts[2].endswith("-3.tar.gz.age")


def test_a_file_that_cannot_be_removed_keeps_its_entry(brain, brain_home, monkeypatch):
    cfg = brain({"keep": 1})
    f = brain_home / "ledger" / "events-2026-11.jsonl"
    spool.push(cfg, ["ledger"], now=NOW, found=brain.found)
    f.write_bytes(b'{"e": 9}\n')
    os.utime(f, (1_900_000_000, 1_900_000_000))
    monkeypatch.setattr(spool, "_unlink", lambda p: not p.name.endswith(".age"))
    spool.push(cfg, ["ledger"], now=NOW + timedelta(hours=1), found=brain.found)
    assert "ledger/ledger-20261111T120000Z.tar.gz.age" in spool.status(cfg)["files"]


def test_a_store_that_fails_while_packed_lets_the_others_go_on(brain, monkeypatch):
    cfg = brain()
    real = vault.pack

    def locked(items, dst):
        if any(a == "ledger" for _, a in items):
            raise PermissionError(13, "locked")
        return real(items, dst)
    monkeypatch.setattr(vault, "pack", locked)
    res = spool.push(cfg, now=NOW, found=brain.found)
    assert res["errors"][0].startswith("ledger: store ledger: PermissionError while sealing")
    assert [p["store"] for p in res["put"]] == ["usage"]


def test_a_newer_index_of_another_shape_is_still_read(brain, brain_home, capsys):
    from brain import cli
    cfg = brain({})
    (brain_home / "spool").mkdir()
    (brain_home / "spool" / "spool.json").write_text('{"v": 2, "files": [{"file": "x"}], "last": []}',
                                                     encoding="utf-8")
    assert spool.status(cfg)["files"] == {} and spool.health(cfg, now=NOW) == 0
    assert cli.main(["--root", str(brain.root), "spool", "push"]) == 2
    assert "newer brain" in capsys.readouterr().err


def test_an_unreadable_index_is_set_aside(brain, brain_home):
    cfg = brain()
    (brain_home / "spool").mkdir()
    (brain_home / "spool" / "spool.json").write_text("not json", encoding="utf-8")
    spool.push(cfg, ["ledger"], now=NOW, found=brain.found)
    names = sorted(p.name for p in (brain_home / "spool").iterdir())
    assert any(n.startswith("spool.json.unreadable-") for n in names)
    assert len(spool.status(cfg)["files"]) == 1


def test_the_config_readers(brain, monkeypatch):
    cfg = brain({"stores": ["usage", "usage", "ledger"], "keep": 0, "max_age_days": True, "remote": "rel/dir"})
    assert spool.chosen(cfg) == ["usage", "ledger"]
    assert (spool.keep(cfg), spool.max_age_days(cfg)) == (spool.KEEP, spool.MAX_AGE_DAYS)
    assert spool.remote(cfg) == brain.root / "rel" / "dir"
    monkeypatch.setenv("SPOOL_TEST_DIR", str(brain.root / "abs"))
    assert spool.remote(brain({"remote": "$SPOOL_TEST_DIR"})) == brain.root / "abs"
    assert spool.chosen(brain({"stores": []})) == list(spool.DEFAULT_STORES)


def test_health_warns_after_a_push_with_errors_and_verify_exits_1(brain, brain_home, tmp_path, capsys):
    from brain import cli
    cfg = brain({"remote": str(tmp_path / "offline")})
    spool.push(cfg, ["ledger"], now=NOW, found=brain.found)
    assert spool.health(cfg, now=NOW) == 0
    out = capsys.readouterr().out
    assert "never pushed without an error" in out and "the last push (2026-11-11T12:00:00Z) had 1 error(s)" in out
    with open(brain_home / "spool" / "ledger" / "ledger-20261111T120000Z.tar.gz.age", "ab") as fh:
        fh.write(b"rot")
    assert cli.main(["--root", str(brain.root), "spool", "verify"]) == 1
