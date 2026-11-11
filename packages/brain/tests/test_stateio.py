"""brain.stateio and the truth-local files that go through it (wi-brain-state-safe-io, spec-brain-data-compat N4):
installed.json, alerts/state.json, vault/state.json, usage/sessions.json; then (wi-brain-state-safe-io-rest) tui.json,
the sessions' snapshots, states, reports and plans, Claude Code's settings.json (foreign) and the log class."""

import io
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from brain import (alerts, capture, cockpit, paths, permissions, plan, schedule, selftime, sessions, stateio,
                   usage, vault)


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


# --- wi-brain-state-safe-io-rest: the cockpit's tui.json ---

def test_tui_json_keeps_the_keys_this_engine_does_not_know(brain_home):
    f = _write(cockpit.state_path(), json.dumps({
        "v": 1, "cockpit": 1, "future": {"a": 1}, "scope": "old",
        "panels": {"newpanel": {"sort": "x"}, "queue": {"kind": "idea"}},
        "tabs": {"newtab": {"view": "grid"}}, "columns": {"newtable": {"shown": ["A"]}},
        "settings": {"theme": "dark", "newsetting": 2, "titles": {"newpanel": "Mine", "queue": "Q"}}}))
    assert cockpit.save_state({"scope": "s", "panels": {"queue": {"kind": "decision"}}, "settings": {"theme": "nord"}})
    disk = json.loads(f.read_text(encoding="utf-8"))
    assert disk["v"] == 1 and disk["cockpit"] == 1 and disk["future"] == {"a": 1} and disk["scope"] == "s"
    assert disk["panels"] == {"newpanel": {"sort": "x"}, "queue": {"kind": "decision"}}  # a newer brain's panel kept
    assert disk["tabs"] == {"newtab": {"view": "grid"}} and disk["columns"] == {"newtable": {"shown": ["A"]}}
    # a known title the save does not carry is the owner's to drop; the newer brain's own keys stay
    assert disk["settings"] == {"theme": "nord", "newsetting": 2, "titles": {"newpanel": "Mine"}}
    assert json.loads(Path(str(f) + ".bak").read_text(encoding="utf-8"))["scope"] == "old"  # backed up first
    assert cockpit.load_state()["settings"] == {"theme": "nord"}


def test_tui_json_of_a_newer_brain_is_read_but_never_written(brain_home):
    text = json.dumps({"v": 2, "scope": "theirs", "settings": {"theme": "nord"}})
    f = _write(cockpit.state_path(), text)
    assert cockpit.load_state() == {"scope": "theirs", "settings": {"theme": "nord"}}  # a tolerant reader
    assert cockpit.save_state({"scope": "mine"}) is False and f.read_text(encoding="utf-8") == text
    assert "newer brain" in cockpit.state_refusal() and "brain update" in cockpit.state_refusal()
    _write(f, "{not json")
    assert cockpit.state_refusal() == ""  # an unreadable one: the save sets it aside, then writes
    assert cockpit.load_state() == {} and f.exists() and not _asides(f)  # a read moves nothing
    assert cockpit.save_state({"scope": "mine"}) and len(_asides(f)) == 1
    assert cockpit.load_state() == {"scope": "mine"}


# --- the sessions' files: snapshot, state, report, plan ---

def _stop(t: Path, sid: str) -> None:
    capture.main(["stop"], stdin=io.StringIO(json.dumps({"session_id": sid, "transcript_path": str(t)})))


def test_the_stop_snapshot_and_its_state_go_through_stateio(brain_home, fixture_transcript, tmp_path):
    sid = "aaaabbbb-1111-2222-3333-444455556666"
    t = tmp_path / "s.jsonl"
    t.write_bytes(fixture_transcript.read_bytes())
    _stop(t, sid)
    _stop(t, sid)
    d = paths.sessions_dir()
    sr, state = (json.loads((d / f"{sid}{x}").read_text(encoding="utf-8")) for x in (".json", ".state.json"))
    assert sr["v"] == capture.SR_V == 1 and state["v"] == capture.STATS_V and state["offset"] > 0
    assert (d / f"{sid}.json.bak").is_file() and (d / f"{sid}.state.json.bak").is_file()
    assert not [p for p in d.iterdir() if p.name.endswith(".tmp")]
    assert not (brain_home / "ledger" / "errors.log").exists()


def test_a_newer_brains_snapshot_is_left_to_it(brain_home, fixture_transcript, tmp_path):
    sid = "aaaabbbb-1111-2222-3333-444455556666"
    t = tmp_path / "s.jsonl"
    t.write_bytes(fixture_transcript.read_bytes())
    srf = _write(paths.sessions_dir() / f"{sid}.json", '{"v": 2, "id": "theirs"}')
    _stop(t, sid)
    assert srf.read_text(encoding="utf-8") == '{"v": 2, "id": "theirs"}'
    assert not (paths.sessions_dir() / f"{sid}.state.json").exists()  # nothing written beside it either
    assert not (brain_home / "ledger" / "errors.log").exists()  # not an error: each turn would log one


def test_an_unreadable_snapshot_state_is_set_aside_and_the_count_starts_over(brain_home, fixture_transcript,
                                                                              tmp_path):
    sid = "aaaabbbb-1111-2222-3333-444455556666"
    t = tmp_path / "s.jsonl"
    t.write_bytes(fixture_transcript.read_bytes())
    sf = _write(paths.sessions_dir() / f"{sid}.state.json", "[1, 2]")
    _stop(t, sid)
    assert len(_asides(sf)) == 1 and json.loads(sf.read_text(encoding="utf-8"))["offset"] > 0


def test_the_report_is_written_through_stateio_and_a_newer_one_left(brain_home):
    rep = {"v": 1, "session": "s-1", "at": "2026-11-10T10:00:00Z", "turn": "idle", "blocked": False}
    f = sessions.write_report("s-1", rep)
    assert f == sessions.report_file("s-1") and sessions.read_report("s-1") == rep
    assert sessions.write_report("s-1", {**rep, "turn": "asking"}) == f
    assert json.loads(Path(str(f) + ".bak").read_text(encoding="utf-8"))["turn"] == "idle"
    assert list(json.loads(f.read_text(encoding="utf-8")))[:2] == ["v", "session"]  # its order kept
    _write(f, '{"v": 3, "session": "s-1"}')
    assert sessions.write_report("s-1", rep) is None and sessions.read_report("s-1") == {"v": 3, "session": "s-1"}


def test_the_plan_file_of_a_newer_brain_is_left_to_it(brain_home):
    f = _write(plan.plan_file("s-1"), '{"v": 2, "steps": []}')
    call = {"session_id": "s-1", "tool_name": "TodoWrite", "tool_input": {"todos": [{"content": "x",
                                                                                      "status": "pending"}]}}
    assert plan.capture(call) is False and f.read_text(encoding="utf-8") == '{"v": 2, "steps": []}'
    _write(f, "{bad")
    assert plan.capture(call) and len(_asides(f)) == 1 and plan.read("s-1")["steps"][0]["status"] == "pending"


# --- a foreign file: Claude Code's settings.json ---

def test_read_foreign_refuses_what_it_cannot_read_and_never_moves_it(tmp_path):
    assert stateio.read_foreign(tmp_path / "none.json") == ({}, None)
    for text, why in (("{bad", "not readable JSON"), ("[1]", "not a JSON object")):
        f = _write(tmp_path / "s.json", text)
        with pytest.raises(stateio.StateError, match=f"{why}.*fix it by hand first"):
            stateio.read_foreign(f)
        assert f.read_text(encoding="utf-8") == text and not _asides(f)
    (tmp_path / "dir.json").mkdir()   # a read that fails (here a folder; a lock or a permission alike)
    with pytest.raises(stateio.StateError, match="cannot be read"):
        stateio.read_foreign(tmp_path / "dir.json")
    f = tmp_path / "bom.json"
    f.write_bytes(b'\xef\xbb\xbf{"a": 1}')
    assert stateio.read_foreign(f) == ({"a": 1}, b'\xef\xbb\xbf{"a": 1}')


def test_write_foreign_refuses_a_file_its_owner_changed_meanwhile(tmp_path):
    f = _write(tmp_path / "s.json", '{"a": 1}')
    data, seen = stateio.read_foreign(f)
    f.write_text('{"a": 2}', encoding="utf-8")   # the owner wrote it meanwhile
    with pytest.raises(stateio.StateError, match="changed while it was being edited"):
        stateio.write_foreign(f, '{"a": 3}\n', seen)
    assert f.read_text(encoding="utf-8") == '{"a": 2}'
    with pytest.raises(stateio.StateError, match="changed"):
        stateio.write_foreign(tmp_path / "new.json", "{}\n", b"{}")  # it was there, now it is gone
    assert stateio.write_foreign(tmp_path / "new.json", "{}\n", None) is None  # nothing to back up
    data, seen = stateio.read_foreign(f)
    assert stateio.write_foreign(f, '{"a": 3}\n', seen, keep_backup=False) is None and not Path(str(f) + ".bak").exists()


def test_claude_settings_are_backed_up_kept_and_written_atomically(tmp_path):
    home = permissions.claude_home()
    assert str(home).startswith(str(tmp_path))   # never the owner's real ~/.claude
    f = _write(home / "settings.json", json.dumps({"theme": "dark", "permissions": {"allow": ["A"], "x": 1}}))
    before = f.read_text(encoding="utf-8")
    permissions.ClaudeCode().write(f, {"allow": ["B"], "deny": ["C"]}, {"allow": ["A"]})
    data = json.loads(f.read_text(encoding="utf-8"))
    assert data == {"theme": "dark", "permissions": {"allow": ["B"], "x": 1, "deny": ["C"]}}  # other keys kept
    assert Path(str(f) + ".bak").read_text(encoding="utf-8") == before
    assert not [p for p in home.iterdir() if p.name.endswith(".tmp")]


def test_claude_settings_unreadable_or_changed_meanwhile_are_refused_untouched(tmp_path, monkeypatch):
    f = _write(permissions.claude_home() / "settings.json", "{bad")
    with pytest.raises(permissions.PermissionsError, match="fix it by hand first"):
        permissions.ClaudeCode().write(f, {"allow": ["B"]})
    assert f.read_text(encoding="utf-8") == "{bad" and not Path(str(f) + ".bak").exists() and not _asides(f)
    _write(f, '{"permissions": {}}')
    real = stateio.read_foreign

    def racing(path):
        got = real(path)
        path.write_text('{"permissions": {"allow": ["Z"]}}', encoding="utf-8")   # Claude Code writes meanwhile
        return got
    monkeypatch.setattr(stateio, "read_foreign", racing)
    with pytest.raises(permissions.PermissionsError, match="run the command again"):
        permissions.ClaudeCode().write(f, {"allow": ["B"]})
    assert json.loads(f.read_text(encoding="utf-8")) == {"permissions": {"allow": ["Z"]}}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                    "-c", "commit.gpgsign=false", *args], check=True, capture_output=True)


def _status(repo: Path) -> str:
    return subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True,
                          check=True).stdout


def _repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q")
    _write(path / "README", "x")
    _git(path, "add", ".")
    _git(path, "commit", "-q", "-m", "c")
    return path


@pytest.mark.skipif(not shutil.which("git"), reason="git")
def test_a_work_trees_settings_are_backed_up_under_brain_home(tmp_path, brain_home):
    """wi-brain-settings-backup-home: a project's settings.json (tracked) and its settings.local.json (gitignored, as
    Claude Code does) are backed up under $BRAIN_HOME/backup/<project>-<key>/.claude before each write, never beside
    themselves: git status stays clean. An untracked .bak an older engine left beside one moves there first."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    shared = _write(repo / ".claude" / "settings.json", '{"permissions": {}}')
    _write(repo / ".gitignore", ".claude/settings.local.json\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "c")
    local = _write(repo / ".claude" / "settings.local.json", '{"permissions": {"allow": ["mine"]}}')
    old = _write(Path(str(local) + ".bak"), '{"permissions": {"allow": ["older"]}}')   # left by an older engine
    os.utime(old, (1_700_000_000, 1_700_000_000))
    home = permissions.home_backup_dir(local)
    assert home.parent.parent == brain_home / "backup" and home.parent.name.startswith("repo-")
    assert home.name == ".claude"
    assert permissions.in_work_tree(local) and permissions.home_backup_dir(permissions.claude_home() / "x") is None

    permissions.ClaudeCode().write(shared, {"allow": ["B"]})
    permissions.ClaudeCode().write(local, {"allow": ["B"]})
    assert not list((repo / ".claude").glob("*.bak"))
    assert _status(repo) == " M .claude/settings.json\n"          # only the change itself: no .bak shows
    copies = sorted(p.name for p in home.iterdir())
    assert [n.split(".2")[0] for n in copies] == ["settings.json", "settings.local.json", "settings.local.json"]
    olds = [json.loads((home / n).read_text(encoding="utf-8"))["permissions"].get("allow") for n in copies]
    assert olds == [None, ["older"], ["mine"]]                      # the adopted .bak, older, sorts first
    permissions.ClaudeCode().write(shared, {"allow": ["C"]})
    newest = sorted(home.glob("settings.json.*.bak"))[-1]
    assert json.loads(newest.read_text(encoding="utf-8"))["permissions"]["allow"] == ["B"]


@pytest.mark.skipif(not shutil.which("git"), reason="git")
def test_two_repos_of_one_name_and_a_linked_worktree_keep_their_own_copies(tmp_path, brain_home):
    a, b = _repo(tmp_path / "a" / "api"), _repo(tmp_path / "b" / "api")
    fa = _write(a / ".claude" / "settings.local.json", "{}")
    fb = _write(b / ".claude" / "settings.local.json", "{}")
    da, db = permissions.home_backup_dir(fa), permissions.home_backup_dir(fb)
    assert da != db and da.parent.name.startswith("api-") and db.parent.name.startswith("api-")
    _git(a, "worktree", "add", "-q", str(tmp_path / "wt-one"))
    fw = _write(tmp_path / "wt-one" / ".claude" / "settings.local.json", "{}")
    dw = permissions.home_backup_dir(fw)
    assert dw.parent.parent.name == "worktrees" and dw.parent.name.startswith("wt-one-")
    assert dw.parent.parent.parent == da.parent                     # under its repo's folder


def test_backup_home_keeps_the_last_copies_and_skips_the_same_bytes(tmp_path):
    f = _write(tmp_path / "settings.json", "0")
    folder = tmp_path / "home"
    _write(folder / "settings.json.notes", "kept")                     # not a copy: never pruned
    _write(folder / "settings.local.json.20260101T000000000000Z.bak", "another file's copy")
    first = stateio.backup_home(f, folder, keep=3)
    assert stateio.backup_home(f, folder, keep=3) == first           # the same bytes: no new copy
    for i in range(1, 5):
        _write(f, str(i))
        stateio.backup_home(f, folder, keep=3)
    names = sorted(p.name for p in folder.glob("settings.json.*.bak"))
    assert [(folder / n).read_text(encoding="utf-8") for n in names] == ["2", "3", "4"]
    assert (folder / "settings.json.notes").exists() and len(list(folder.glob("settings.local.json.*"))) == 1
    assert stateio.backup_home(tmp_path / "none", folder) is None


def test_two_copies_in_one_clock_tick_are_both_kept(tmp_path, monkeypatch):
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(stateio, "datetime", Frozen)
    f = _write(tmp_path / "settings.json", "a")
    folder = tmp_path / "home"
    stateio.backup_home(f, folder)
    _write(f, "b")
    stateio.backup_home(f, folder)
    assert sorted(p.read_text(encoding="utf-8") for p in folder.iterdir()) == ["a", "b"]


def test_a_write_with_no_change_takes_no_new_copy_and_a_failed_copy_never_stops_it(tmp_path, capsys):
    f = _write(tmp_path / "s.json", '{"a": 0}')
    folder = tmp_path / "home"
    for _ in range(3):
        _, seen = stateio.read_foreign(f)
        stateio.write_foreign(f, '{"a": 1}\n', seen, backup_dir=folder)
    assert sorted(p.read_text(encoding="utf-8") for p in folder.iterdir()) == ['{"a": 0}', '{"a": 1}\n']
    blocked = _write(tmp_path / "blocked", "a file where the folder should be")
    _, seen = stateio.read_foreign(f)
    assert stateio.write_foreign(f, '{"a": 2}\n', seen, backup_dir=blocked) is None
    assert f.read_text(encoding="utf-8") == '{"a": 2}\n' and "no backup in" in capsys.readouterr().err


@pytest.mark.skipif(not shutil.which("git"), reason="git")
def test_an_old_bak_is_adopted_only_when_git_says_it_is_untracked(tmp_path, brain_home, monkeypatch):
    repo = _repo(tmp_path / "repo")
    f = _write(repo / ".claude" / "settings.json", "{}")
    bak = _write(Path(str(f) + ".bak"), "{}")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "a tracked .bak")
    home = tmp_path / "home"
    assert permissions.adopt_old_backup(f, home) is None and bak.exists()          # tracked: stays
    _git(repo, "rm", "-q", "--cached", ".claude/settings.json.bak")
    real = subprocess.run

    def no_git(*a, **kw):
        raise FileNotFoundError("git")
    monkeypatch.setattr(subprocess, "run", no_git)
    assert permissions.adopt_old_backup(f, home) is None and bak.exists()          # git cannot say: stays
    monkeypatch.setattr(subprocess, "run", real)
    moved = permissions.adopt_old_backup(f, home)
    assert moved is not None and moved.parent == home and not bak.exists()
    _write(bak, "{}")
    stamp = datetime.fromtimestamp(bak.stat().st_mtime, timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    _write(home / f"settings.json.{stamp}.bak", "{}")                               # its copy is already there
    assert permissions.adopt_old_backup(f, home) is None and not bak.exists()       # so the .bak goes


def test_a_symlinked_settings_file_is_written_through_its_link(tmp_path):
    """A settings.json linked into a dotfiles repo: the file it points to is written, the link stays a link."""
    real = _write(tmp_path / "dotfiles" / "settings.json", '{"theme": "dark"}')
    home = _write(tmp_path / "home" / "x", "").parent
    link = home / "settings.json"
    try:
        os.symlink(real, link)
    except OSError:
        pytest.skip("no symlinks here")
    permissions.ClaudeCode().write(link, {"allow": ["B"]})
    assert link.is_symlink() and Path(os.path.realpath(link)) == Path(os.path.realpath(real))
    assert json.loads(real.read_text(encoding="utf-8")) == {"theme": "dark", "permissions": {"allow": ["B"]}}
    assert Path(str(link) + ".bak").read_text(encoding="utf-8") == '{"theme": "dark"}'
    assert not [p for p in (home, real.parent) for q in p.iterdir() if q.name.endswith(".tmp")]
    stateio.write_atomic(link, "{}\n")   # every writer of the module goes through the link the same way
    assert link.is_symlink() and real.read_text(encoding="utf-8") == "{}\n"


# --- the log class ---

NOV = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


def _aged(f: Path, when: datetime) -> Path:
    os.utime(f, (when.timestamp(), when.timestamp()))
    return f


def test_month_of_and_the_retention_window():
    assert [stateio.month_of(n) for n in ("errors-2026-10.log", "errors-2026-10-2.log", "exec-bash-2026-09.jsonl",
                                          "errors.log")] == ["2026-10", "2026-10", "2026-09", ""]
    assert stateio.oldest_kept(NOV, 6) == "2026-06" and stateio.oldest_kept(datetime(2026, 2, 1), 3) == "2025-12"
    assert selftime.KEEP_MONTHS == stateio.LOG_RETENTION["timing"]  # the engine's timing is a log class
    assert stateio.LOG_RETENTION["ledger"] is None  # the records' ledgers are kept


def test_prune_months_drops_only_the_months_past_the_retention(tmp_path):
    files = [_write(tmp_path / n, "x") for n in ("e-2026-04.log", "e-2026-05.log", "e-2026-11.log", "notes.log")]
    assert stateio.prune_months(files, None, NOV) == [] and all(f.exists() for f in files)  # kept: a record
    assert stateio.prune_months(files, 6, NOV) == [files[0], files[1]]
    assert [f.exists() for f in files] == [False, False, True, True]  # a name without a month is never pruned


def test_rotate_log_moves_an_earlier_months_log_aside(tmp_path):
    f = _aged(_write(tmp_path / "errors.log", "old\n"), datetime(2026, 10, 30, tzinfo=timezone.utc))
    assert stateio.rotate_log(f, NOV) == tmp_path / "errors-2026-10.log" and not f.exists()
    assert stateio.rotate_log(f, NOV) is None  # nothing to move
    _write(f, "this month\n")
    assert stateio.rotate_log(f, NOV) is None and f.exists()  # this month's: appended to
    _write(f, "x" * 50)
    assert stateio.rotate_log(f, NOV, max_bytes=10) == tmp_path / "errors-2026-11.log"  # past its size
    _write(f, "x" * 50)
    assert stateio.rotate_log(f, NOV, max_bytes=10) == tmp_path / "errors-2026-11-2.log"  # the name is taken
    old = _write(tmp_path / "errors-2026-01.log", "x")
    _aged(_write(f, "y"), datetime(2026, 10, 1, tzinfo=timezone.utc))
    stateio.rotate_log(f, NOV, keep=6)
    assert not old.exists() and (tmp_path / "errors-2026-10-2.log").exists()  # past six months: gone


def test_rotate_log_never_writes_over_a_month_another_hook_rotated(tmp_path, monkeypatch):
    """Two hooks rotate at once: the name one checked as free is taken when it moves; the rotated month is kept."""
    f = _aged(_write(tmp_path / "errors.log", "late october\n"), datetime(2026, 10, 31, tzinfo=timezone.utc))
    archive = _write(tmp_path / "errors-2026-10.log", "october\n")   # the other hook's move, after this one looked
    with monkeypatch.context() as m:
        m.setattr(Path, "exists", lambda self: False)   # it looked before the other hook moved
        assert stateio.rotate_log(f, NOV) == tmp_path / "errors-2026-10-2.log"
    assert archive.read_text(encoding="utf-8") == "october\n" and not f.exists()
    assert (tmp_path / "errors-2026-10-2.log").read_text(encoding="utf-8") == "late october\n"


def test_rotate_log_looks_again_when_another_hook_rotated_meanwhile(tmp_path, monkeypatch):
    """Hook B decided to rotate; A rotated first and C started a fresh log: B leaves the fresh one where it is."""
    f = _aged(_write(tmp_path / "errors.log", "october\n"), datetime(2026, 10, 31, tzinfo=timezone.utc))
    real, calls = stateio._move_new, []

    def raced(src, dst):
        if not calls:
            os.replace(src, dst)   # hook A rotates
            _aged(_write(src, "november\n"), NOV)   # hook C appends a line: a fresh errors.log
        calls.append(dst)
        return real(src, dst)
    monkeypatch.setattr(stateio, "_move_new", raced)
    assert stateio.rotate_log(f, NOV) is None and len(calls) == 1
    assert (tmp_path / "errors-2026-10.log").read_text(encoding="utf-8") == "october\n"
    assert f.read_text(encoding="utf-8") == "november\n" and not (tmp_path / "errors-2026-10-2.log").exists()


def test_rotate_log_looks_again_when_the_log_changed_while_it_chose_a_name(tmp_path, monkeypatch):
    """Hook A rotated and C started a fresh log between B's look at the log and B's choice of a free name: B sees the
    log changed and leaves the fresh one where it is, never filing it under the old month's -2 name."""
    f = _aged(_write(tmp_path / "starts.jsonl", "october\n"), datetime(2026, 10, 31, tzinfo=timezone.utc))
    real, done = Path.exists, []

    def raced(self, *a, **kw):
        if self.name == "starts-2026-10.jsonl" and not done:
            done.append(1)
            os.replace(f, self)                              # hook A rotates
            _aged(_write(f, "a fresh line\n"), NOV)          # hook C starts this month's log
        return real(self, *a, **kw)
    monkeypatch.setattr(Path, "exists", raced)
    assert stateio.rotate_log(f, NOV) is None and done
    assert f.read_text(encoding="utf-8") == "a fresh line\n" and not (tmp_path / "starts-2026-10-2.jsonl").exists()


def test_the_error_sink_rotates_errors_log_monthly(brain_home):
    d = brain_home / "ledger"
    f = _write(d / "errors.log", "2026-01-01T00:00:00Z old: x\n")
    then = time.time() - 40 * 86400   # last month or the one before: an earlier month in any case
    os.utime(f, (then, then))
    month = time.strftime("%Y-%m", time.gmtime(then))
    capture._log_error("test", ValueError("boom"))
    assert (d / f"errors-{month}.log").read_text(encoding="utf-8") == "2026-01-01T00:00:00Z old: x\n"
    now = f.read_text(encoding="utf-8")
    assert now.endswith("test: ValueError: boom\n") and "old" not in now and not (d / "errors.log.1").exists()


def test_refused_tells_a_writers_refusal_from_a_file_it_will_set_aside(tmp_path):
    assert not stateio.load(tmp_path / "none.json", aside=False).refused
    assert not stateio.load(_write(tmp_path / "bad.json", "{bad"), aside=False).refused  # set aside by its writer
    assert stateio.load(_write(tmp_path / "new.json", '{"v": 9}'), aside=False).refused
    (tmp_path / "dir.json").mkdir()   # a read that fails: a lock, a permission
    assert stateio.load(tmp_path / "dir.json", aside=False).refused


def test_log_files_gives_a_rotated_logs_files_in_order(tmp_path):
    """wi-brain-logs-unclassified: the monthly files by month, then n (-10 after -2), then the live file."""
    for name in ("quota-2026-10-10.jsonl", "quota-2026-10.jsonl", "quota-2026-10-2.jsonl", "quota-2026-09.jsonl",
                 "quota.jsonl", "quota.json", "quotas-2026-10.jsonl", "quota-2026-10.jsonl.bak"):
        _write(tmp_path / name, "x")
    assert [p.name for p in stateio.log_files(tmp_path / "quota.jsonl")] == [
        "quota-2026-09.jsonl", "quota-2026-10.jsonl", "quota-2026-10-2.jsonl", "quota-2026-10-10.jsonl",
        "quota.jsonl"]
    (tmp_path / "quota.jsonl").unlink()
    assert stateio.log_files(tmp_path / "quota.jsonl")[-1].name == "quota-2026-10-10.jsonl"
    assert stateio.log_files(tmp_path / "nowhere" / "x.jsonl") == []


def test_the_unclassified_logs_have_a_retention():
    assert {k: stateio.LOG_RETENTION[k] for k in ("starts", "quota", "notify")} == {"starts": 2, "quota": 12,
                                                                                 "notify": 6}
