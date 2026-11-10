"""brain.stateio and the truth-local files that go through it (wi-brain-state-safe-io, spec-brain-data-compat N4):
installed.json, alerts/state.json, vault/state.json, usage/sessions.json."""

import json
from pathlib import Path

import pytest

from brain import alerts, paths, schedule, stateio, usage, vault


def _asides(f: Path) -> list[Path]:
    return sorted(f.parent.glob(f.name + stateio.ASIDE + "*"))


def _write(f: Path, text: str) -> Path:
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")
    return f


# --- the helper ---

def test_a_missing_file_is_an_empty_writable_record(tmp_path):
    st = stateio.load(tmp_path / "s.json")
    assert (st.status, st.data, st.writable) == ("missing", {}, True)
    stateio.save(st, {"a": 1})
    assert json.loads((tmp_path / "s.json").read_text(encoding="utf-8")) == {"a": 1, "v": 1}
    assert not (tmp_path / "s.json.bak").exists()  # nothing to back up the first time


@pytest.mark.parametrize("text, why", [("{not json", "is not JSON"), ("[1, 2]", "is not an object (a list)"),
                                       ('"x"', "is not an object (a str)"), ("", "is not JSON")])
def test_an_unreadable_or_non_object_file_is_set_aside_never_saved_over(tmp_path, capsys, text, why):
    f = _write(tmp_path / "s.json", text)
    st = stateio.load(f)
    assert (st.status, st.data, st.writable) == ("aside", {}, True) and why in st.why
    assert not f.exists() and _asides(f) == [st.aside] and st.aside.read_text(encoding="utf-8") == text
    assert f"set aside as {st.aside.name}" in capsys.readouterr().err
    stateio.save(st, {"a": 1})
    assert st.aside.read_text(encoding="utf-8") == text  # the copy is kept: the new record never overwrites it


def test_a_file_that_is_not_utf8_is_set_aside_never_a_crash(tmp_path, brain_home):
    f = tmp_path / "s.json"
    f.write_bytes(b'{"a": "caf\xe9"}')   # cp1252, as a Windows editor may save it
    assert stateio.load(f, aside=False).status == "unreadable" and f.exists()
    st = stateio.load(f)
    assert st.status == "aside" and "not JSON" in st.why and st.aside.read_bytes() == b'{"a": "caf\xe9"}'
    _write(alerts.state_dir() / "state.json", "").write_bytes(b"\xe9")
    assert alerts.state_load() == {}  # brain status reads it without a traceback


def test_a_file_a_writer_replaced_meanwhile_is_read_again_not_set_aside(tmp_path, monkeypatch):
    f = _write(tmp_path / "s.json", "{bad")
    real = stateio.set_aside

    def racing(path, why, seen=None):
        path.write_text('{"a": 1}', encoding="utf-8")   # a writer's os.replace lands between the read and the move
        return real(path, why, seen)
    monkeypatch.setattr(stateio, "set_aside", racing)
    st = stateio.load(f)
    assert st.status == "ok" and st.data == {"a": 1} and not _asides(f)


def test_a_backup_that_fails_does_not_stop_the_write(tmp_path, monkeypatch, capsys):
    f = _write(tmp_path / "s.json", '{"a": 1}')

    def locked(src, dst):
        raise PermissionError("locked by a scanner")
    monkeypatch.setattr(stateio.shutil, "copyfile", locked)
    stateio.save(stateio.load(f), {"a": 2})
    assert json.loads(f.read_text(encoding="utf-8"))["a"] == 2 and "no backup (PermissionError)" in capsys.readouterr().err
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


def test_a_shape_the_owner_refuses_is_set_aside(tmp_path):
    f = _write(tmp_path / "s.json", '{"a": 1}')
    st = stateio.load(f, check=lambda d: "a is not an object" if not isinstance(d.get("a"), dict) else "")
    assert st.status == "aside" and "a is not an object" in st.why and len(_asides(f)) == 1


def test_aside_false_reads_without_moving_and_refuses_to_write(tmp_path):
    f = _write(tmp_path / "s.json", "[]")
    st = stateio.load(f, aside=False)
    assert st.status == "unreadable" and not st.writable and f.exists() and not _asides(f)
    with pytest.raises(stateio.StateError, match="cannot be read"):
        stateio.save(st, {})


def test_a_newer_v_is_read_but_never_written(tmp_path):
    f = _write(tmp_path / "s.json", '{"v": 3, "a": {"x": 1}, "new": true}')
    st = stateio.load(f, known=2)
    assert (st.status, st.v, st.data) == ("newer", 3, {"a": {"x": 1}, "new": True}) and not st.writable
    with pytest.raises(stateio.StateError, match=r"newer brain \(v 3, this engine knows v 2\): brain update"):
        stateio.save(st, {"a": {}})
    assert json.loads(f.read_text(encoding="utf-8"))["v"] == 3 and not _asides(f)


@pytest.mark.parametrize("v", ['"2"', "true", "1.5", "[1]"])
def test_a_v_that_is_not_an_integer_is_read_only(tmp_path, v):
    f = _write(tmp_path / "s.json", f'{{"v": {v}, "a": 1}}')
    st = stateio.load(f)
    assert st.status == "newer" and not st.writable and f.exists()


def test_a_v_holding_an_object_is_a_record_named_v(tmp_path):
    f = _write(tmp_path / "s.json", '{"v": {"at": "x"}, "w": {}}')
    st = stateio.load(f)
    assert st.status == "ok" and st.v is None and st.data == {"v": {"at": "x"}, "w": {}}
    stateio.save(st, write_v=False)
    assert json.loads(f.read_text(encoding="utf-8")) == {"v": {"at": "x"}, "w": {}}


def test_an_older_or_absent_v_is_read_and_unknown_keys_survive_the_round_trip(tmp_path):
    f = _write(tmp_path / "s.json", '{"a": 1, "later": {"kept": true}}')
    st = stateio.load(f, known=2)
    assert st.status == "ok" and st.v is None
    st.data["a"] = 2
    stateio.save(st)
    assert json.loads(f.read_text(encoding="utf-8")) == {"v": 2, "a": 2, "later": {"kept": True}}


def test_an_os_error_other_than_missing_is_read_only_and_moves_nothing(tmp_path):
    f = tmp_path / "s.json"
    f.mkdir()   # reading a folder raises an OSError (IsADirectory, or PermissionError on Windows)
    st = stateio.load(f)
    assert st.status == "unreadable" and not st.writable and f.is_dir()


def test_the_write_backs_up_first_and_is_atomic(tmp_path, monkeypatch):
    f = _write(tmp_path / "s.json", '{"v": 1, "a": 1}')
    st = stateio.load(f)
    stateio.save(st, {"a": 2})
    assert json.loads((tmp_path / "s.json.bak").read_text(encoding="utf-8")) == {"v": 1, "a": 1}
    assert json.loads(f.read_text(encoding="utf-8")) == {"v": 1, "a": 2}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["s.json", "s.json.bak"]  # no temporary file left

    def crash(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(stateio.os, "replace", crash)
    with pytest.raises(OSError):
        stateio.save(stateio.load(f), {"a": 3})
    monkeypatch.undo()
    assert json.loads(f.read_text(encoding="utf-8")) == {"v": 1, "a": 2}  # a failed write leaves the file whole
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


def test_a_newer_brain_that_wrote_since_the_load_wins(tmp_path):
    f = _write(tmp_path / "s.json", '{"v": 1, "a": 1}')
    st = stateio.load(f)
    f.write_text('{"v": 2, "a": 9}', encoding="utf-8")
    with pytest.raises(stateio.StateError, match="newer brain"):
        stateio.save(st, {"a": 2})
    assert json.loads(f.read_text(encoding="utf-8")) == {"v": 2, "a": 9}


def test_a_secret_is_never_copied(brain_home):
    f = _write(paths.brain_home() / "secrets" / "s.json", '{"a": 1}')
    stateio.save(stateio.load(f), {"a": 2})
    assert not (f.parent / "s.json.bak").exists() and stateio.backup(f) is None


# --- schedules/installed.json ---

def test_installed_json_corrupt_or_wrong_shape_is_set_aside_by_a_write_only(brain_home):
    f = _write(schedule.record_file(), '{"alerts-pass": "not a record"}')
    assert schedule.installed() == {} and f.exists() and not _asides(f)  # a plan or a listing moves nothing
    schedule._record({"alerts-pass": {"system": "schtasks"}})
    assert len(_asides(f)) == 1 and json.loads(f.read_text(encoding="utf-8")) == {"alerts-pass": {"system": "schtasks"}}
    _write(f, "{broken")
    assert schedule.installed() == {} and len(_asides(f)) == 1
    schedule._record({})
    assert len(_asides(f)) == 2


def test_installed_json_keeps_v1_unwritten_and_a_newer_one_refuses_the_apply(brain_home, capsys):
    schedule._record({"alerts-pass": {"system": "schtasks"}})
    f = schedule.record_file()
    assert json.loads(f.read_text(encoding="utf-8")) == {"alerts-pass": {"system": "schtasks"}}  # 0.2.5 reads it
    schedule._record({"alerts-pass": {"system": "schtasks", "at": "x"}})
    assert json.loads(Path(str(f) + ".bak").read_text(encoding="utf-8")) == {"alerts-pass": {"system": "schtasks"}}
    _write(f, '{"v": 2, "alerts-pass": {"system": "schtasks"}}')
    assert schedule.installed() == {"alerts-pass": {"system": "schtasks"}}  # read, the v left out of the names
    assert schedule.install({}, apply=True, here="ada-desktop") == 2
    assert "install --apply refused" in capsys.readouterr().err and "brain update" in str(schedule.record_state().refusal())
    with pytest.raises(stateio.StateError):
        schedule._record({})
    assert json.loads(f.read_text(encoding="utf-8"))["v"] == 2


# --- alerts/state.json ---

def _alerts_file() -> Path:
    return alerts.state_dir() / "state.json"


def test_alerts_state_corrupt_or_wrong_shape_is_set_aside_and_the_pass_records_afresh(brain_home):
    f = _write(_alerts_file(), "[]")
    assert alerts.state_load() == {} and not _asides(f)  # brain status, the cockpit: read only
    assert alerts.notify_pass({"projects": []}, {}, dry_run=True) == [] and not _asides(f)
    _write(f, '{"demo": 3}')
    alerts.notify_pass({"projects": []}, {})
    assert len(_asides(f)) == 1 and "_pass" in json.loads(f.read_text(encoding="utf-8"))
    assert schedule.last_pass()["host"]


def test_alerts_state_newer_v_sends_nothing_and_keeps_the_file(brain_home):
    f = _write(_alerts_file(), '{"v": 2, "demo": {"open": {}}}')
    assert alerts.state_load() == {"demo": {"open": {}}}
    assert alerts.notify_pass({"projects": []}, {})[0].startswith("nothing sent: ")
    assert json.loads(f.read_text(encoding="utf-8")) == {"v": 2, "demo": {"open": {}}}
    assert alerts.notify_pass({"projects": []}, {}, dry_run=True) == []  # a dry run writes nothing anyway


def test_alerts_state_is_written_atomically_with_a_backup(brain_home):
    alerts.notify_pass({"projects": []}, {})
    alerts.notify_pass({"projects": []}, {})
    f = _alerts_file()
    assert "v" not in json.loads(f.read_text(encoding="utf-8"))  # v 1 unwritten: 0.2.5 reads every key as a project
    assert Path(str(f) + ".bak").is_file() and not list(f.parent.glob("*.tmp"))


# --- vault/state.json ---

def test_vault_state_that_is_not_an_object_no_longer_crashes(brain_home):
    f = _write(vault.state_file(), "[1, 2]")
    assert vault.load_state() == {"canary": {}, "drill": {}, "seals": {}} and not _asides(f)  # status: read only
    assert vault.load_state(write=True) == {"canary": {}, "drill": {}, "seals": {}} and len(_asides(f)) == 1
    _write(f, '{"drill": ["x"]}')
    assert vault.load_state(write=True)["drill"] == {} and len(_asides(f)) == 2
    _write(f, "{oops")
    assert vault.load_state(write=True)["seals"] == {} and len(_asides(f)) == 3


def test_vault_state_gains_a_v_and_its_legacy_migration_backs_up_first(brain_home):
    f = _write(vault.state_file(), json.dumps({"canary": {"r": {"fingerprint": "fp"}}, "drill": {"r": "2026-01-01"}}))
    st = vault.load_state()
    assert st["drill"]["r"] == {"at": "2026-01-01", "fingerprint": "fp"}
    assert json.loads(f.read_text(encoding="utf-8"))["v"] == vault.STATE_V
    assert json.loads(Path(str(f) + ".bak").read_text(encoding="utf-8"))["drill"] == {"r": "2026-01-01"}


def test_vault_state_newer_v_is_read_and_every_write_is_refused(brain_home, monkeypatch):
    f = _write(vault.state_file(), json.dumps({"v": 2, "drill": {"r": "2026-01-01"}, "seals": {}, "canary": {}}))
    assert vault.load_state()["drill"]["r"]["at"] == "2026-01-01"  # migrated in memory, never written over it
    with pytest.raises(vault.VaultError, match="newer brain"):
        vault.load_state(write=True)
    with pytest.raises(vault.VaultError, match="newer brain"):
        vault.drill(None, "r")  # refused before any key is asked
    with pytest.raises(vault.VaultError, match="newer brain"):
        vault.save_state({"canary": {}, "drill": {}, "seals": {}})
    from brain import rotation
    monkeypatch.setattr(rotation, "stale_seals", lambda cfg: [{"store": "s", "file": "f"}])
    with pytest.raises(vault.VaultError, match="newer brain"):
        rotation.reseal(None, apply=True)  # refused before any file is sealed again
    assert json.loads(f.read_text(encoding="utf-8"))["v"] == 2 and not Path(str(f) + ".bak").exists()


# --- usage/sessions.json ---

def _fake_scan(monkeypatch, tmp_path):
    t = tmp_path / "p" / "s.jsonl"
    _write(t, "")
    monkeypatch.setattr(usage, "main_transcripts", lambda: [t])
    monkeypatch.setattr(paths, "relative_transcript", lambda f: "p/s.jsonl")
    monkeypatch.setattr(usage, "scan", lambda f, prices=None: {"v": usage.SCAN_V, "sig": [], "cost": 1.0})


def test_usage_ledger_corrupt_or_wrong_shape_is_set_aside_not_lost(brain_home):
    f = _write(usage.ledger_file(), '{"v": 2, "rows": []}')
    assert usage.load() == {} and not _asides(f)  # brain cost, the budget: read only
    assert usage.ledger(write=True).status == "aside" and len(_asides(f)) == 1
    _write(f, '{"v": 2, "rows": {"gone.jsonl": 3}}')
    assert usage.ledger(write=True).data == {} and len(_asides(f)) == 2


def test_usage_ledger_v_is_its_format_not_the_scanner(brain_home, monkeypatch):
    f = _write(usage.ledger_file(), json.dumps({"v": usage.LEDGER_V, "rows": {"a": {"v": 1}}}))
    monkeypatch.setattr(usage, "SCAN_V", usage.SCAN_V + 1)  # a better scanner rescans rows, the file stays writable
    assert usage.ledger(write=True).writable and usage.load() == {"a": {"v": 1}}


def test_usage_ledger_newer_v_is_brought_up_to_date_in_memory_only(brain_home, tmp_path, monkeypatch, capsys):
    _fake_scan(monkeypatch, tmp_path)
    f = _write(usage.ledger_file(), json.dumps({"v": usage.LEDGER_V + 1, "rows": {"gone.jsonl": {"cost": 2}}}))
    rows, scanned = usage.update()
    assert scanned == 1 and set(rows) == {"gone.jsonl", "p/s.jsonl"}
    assert "newer brain" in capsys.readouterr().err
    assert json.loads(f.read_text(encoding="utf-8"))["rows"] == {"gone.jsonl": {"cost": 2}}


def test_usage_ledger_is_saved_with_its_v_atomically_and_backed_up(brain_home, tmp_path, monkeypatch):
    _fake_scan(monkeypatch, tmp_path)
    f = _write(usage.ledger_file(), json.dumps({"v": usage.LEDGER_V, "rows": {"gone.jsonl": {"cost": 2}}}))
    usage.update()
    data = json.loads(f.read_text(encoding="utf-8"))
    assert data["v"] == usage.LEDGER_V and set(data["rows"]) == {"gone.jsonl", "p/s.jsonl"}
    assert json.loads(Path(str(f) + ".bak").read_text(encoding="utf-8"))["rows"] == {"gone.jsonl": {"cost": 2}}
    assert not [p for p in f.parent.iterdir() if p.name.endswith(".tmp")]
