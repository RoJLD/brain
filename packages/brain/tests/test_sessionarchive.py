"""brain session-archive (wi-brain-session-archive): opt-in, the residency filter, the engine's scan then gitleaks
(fail-closed), sealed into the spool, indexed by session record."""

import io
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from brain import cli, config, keystore, schema, spool, vault
from brain import sessionarchive as sa
from brain.commands import session_archive as cmd

FIXTURES = Path(__file__).parent / "fixtures"
FAKE_AGE = FIXTURES / "fake_age.py"
GITLEAKS = [sys.executable, str(FIXTURES / "fake_gitleaks.py")]
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
SID = "0a1b2c3d-1111-2222-3333-444455556666"
SR = "sr-2026-11-10-0a1b2c3d"
TOKEN = "gh" + "p_" + "A1b2C3d4" * 5          # a key's shape, built here so that no file holds one
STORES = {"session-archive": {"class": "sealed", "paths": ["$BRAIN_HOME/session-archive"], "to": ["offsite"]},
          "spool": {"class": "sealed", "paths": ["$BRAIN_HOME/spool"]},
          "repo": {"class": "private", "paths": ["**"]}}


def line(text: str, ts: str = "2026-11-10T09:00:00Z") -> str:
    return json.dumps({"type": "user", "timestamp": ts, "message": {"content": text}})


@pytest.fixture
def brain(tmp_path, monkeypatch):
    """A personal brain with two age recipients (the fake age) and a projects folder with one session and one
    subagent, untouched for a day; ``brain(**block)`` writes config.json with that session_archive block."""
    root = tmp_path / "brain"
    root.mkdir()
    monkeypatch.setenv("BRAIN_CONFIG", str(root / config.FILE))
    monkeypatch.setenv("BRAIN_KEYSTORE", "memory")
    monkeypatch.delenv("FAKE_GITLEAKS", raising=False)
    keystore.Memory.data.clear()
    found = {"age": vault.Age([sys.executable, str(FAKE_AGE)], [sys.executable, str(FAKE_AGE), "keygen"]),
             "gpg": vault.Gpg([])}
    (a, a_pub), (b, b_pub) = (found["age"].keygen(f"test {i}") for i in range(2))
    proj = tmp_path / "claude-config" / "projects" / "E--work-demo"
    sub = proj / SID / "subagents"
    sub.mkdir(parents=True)
    main = proj / f"{SID}.jsonl"
    main.write_text("\n".join([line("hello"), line("rows from the vendor-feed: 1,2,3"),
                               line(f"the key is {TOKEN}"), line("a FAKELEAK value"), line("bye")]) + "\n",
                    encoding="utf-8")
    (sub / "agent-abc.jsonl").write_text(line("subagent work") + "\n", encoding="utf-8")
    old = (NOW - timedelta(days=1)).timestamp()
    for f in (main, sub / "agent-abc.jsonl"):
        os.utime(f, (old, old))

    def write(block: dict | None = None, stores: dict | None = None) -> config.Config:
        data = {"v": 1, "identity": {"owner": "Ada"}, "classes": {"stores": stores or STORES},
                "vault": {"recipients": {"box1": {"kind": "device", "age": a_pub},
                                         "recovery": {"kind": "recovery", "age": b_pub}}}}
        if block is not None:
            data["session_archive"] = block
        (root / config.FILE).write_text(json.dumps(data), encoding="utf-8")
        return config.load(root)

    write.root, write.found, write.ident, write.main, write.proj = root, found, a, main, proj
    return write


ON = {"enabled": True, "resident": {"vendor": r"\bvendor-feed\b"}}


def staged_left(home: Path) -> list[Path]:
    d = home / "session-archive"
    return [p for p in d.iterdir() if p.name.startswith("staging-")] if d.is_dir() else []


def test_off_by_default_does_nothing(brain, brain_home, capsys):
    cfg = brain()
    assert sa.run(cfg, argv=GITLEAKS, now=NOW)["off"] is True
    assert not (brain_home / "session-archive").exists() and not (brain_home / "spool").exists()
    assert cli.main(["--root", str(brain.root), "session-archive", "run"]) == 0
    assert "off" in capsys.readouterr().out


def test_without_gitleaks_nothing_is_archived(brain, brain_home, monkeypatch, capsys):
    cfg = brain(ON)
    monkeypatch.setattr(sa.shutil, "which", lambda name: None)
    with pytest.raises(sa.ArchiveError, match="gitleaks is not on the PATH: nothing archived"):
        sa.run(cfg, now=NOW)
    assert cli.main(["--root", str(brain.root), "session-archive", "run"]) == 2
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "never archived unscanned" in err
    assert not (brain_home / "spool").exists() and not staged_left(brain_home)


def test_dry_run_lists_what_would_be_archived_and_dropped(brain, brain_home):
    cfg = brain(ON)
    res = sa.run(cfg, dry_run=True, argv=GITLEAKS, now=NOW, found=brain.found)
    by = {a["file"]: a for a in res["archived"]}
    assert set(by) == {f"{SR}.jsonl", f"{SR}--agent-abc.jsonl"}
    main = by[f"{SR}.jsonl"]
    assert main["source"] == f"E--work-demo/{SID}.jsonl" and main["lines"] == 5
    assert main["residency"] == {"vendor": 1} and main["cleaned"] == 1 and main["secret"] == 1   # gitleaks' line
    assert res["sealed"] == "" and not (brain_home / "spool").exists()
    assert not (brain_home / "session-archive").exists()     # no index, no staging
    assert "plan only" in sa.run_lines(res)[-1]


def test_run_seals_filtered_copies_into_the_spool_and_indexes_them_by_sr(brain, brain_home, tmp_path):
    cfg = brain(ON)
    res = sa.run(cfg, argv=GITLEAKS, now=NOW, found=brain.found)
    assert res["sealed"].startswith("session-archive/session-archive-20261111T120000Z")
    assert not staged_left(brain_home)                       # the clear copies are gone
    idx = json.loads((brain_home / "session-archive" / "index.json").read_text(encoding="utf-8"))
    assert idx["v"] == 1 and idx["last"]["files"] == 2
    sess = idx["sessions"][SR]
    assert sess["session"] == SID and sess["project"] == "E--work-demo" and sess["machine"]
    assert sess["files"][f"{SR}.jsonl"]["sealed"] == res["sealed"]
    assert sess["files"][f"{SR}--agent-abc.jsonl"]["agent"] == "agent-abc"
    entry = json.loads((brain_home / "spool" / "spool.json").read_text(encoding="utf-8"))["files"][res["sealed"]]
    assert entry["kind"] == "items" and entry["store"] == "session-archive"
    # opened, the copy holds stubs where the resident row, the key and gitleaks' line were
    keystore.Memory.data["device"] = brain.ident
    out = tmp_path / "opened"
    vault.open_sealed(cfg, brain_home / "spool" / res["sealed"], out, found=brain.found)
    text = (out / f"{SR}.jsonl").read_text(encoding="utf-8")
    assert "vendor-feed" not in text and TOKEN not in text and "FAKELEAK" not in text
    assert text.count('"why": "residency"') == 1 and text.count('"why": "secret"') == 1
    assert '"hello"' in text and len(text.splitlines()) == 5
    # nothing changed: the next run takes nothing
    again = sa.run(cfg, argv=GITLEAKS, now=NOW, found=brain.found)
    assert again["archived"] == [] and again["unchanged"] == 2


def test_a_live_transcript_waits(brain):
    cfg = brain(ON)
    recent = (NOW - timedelta(minutes=5)).timestamp()
    os.utime(brain.main, (recent, recent))
    res = sa.run(cfg, dry_run=True, argv=GITLEAKS, now=NOW)
    assert [a["file"] for a in res["archived"]] == [f"{SR}--agent-abc.jsonl"] and res["live"] == 1


@pytest.mark.parametrize("mode, why", [("fail", "gitleaks failed"), ("sticky", "still finds a secret")])
def test_gitleaks_failing_or_still_finding_archives_nothing(brain, brain_home, monkeypatch, mode, why):
    cfg = brain(ON)
    monkeypatch.setenv("FAKE_GITLEAKS", mode)
    with pytest.raises(sa.ArchiveError, match=why):
        sa.run(cfg, argv=GITLEAKS, now=NOW, found=brain.found)
    assert not (brain_home / "spool").exists() and not staged_left(brain_home)
    assert not (brain_home / "session-archive" / "index.json").exists()


def test_an_older_gitleaks_is_asked_through_detect(brain, monkeypatch, tmp_path):
    cfg = brain(ON)
    log = tmp_path / "calls.log"
    monkeypatch.setenv("FAKE_GITLEAKS", f"log={log}")
    sa.run(cfg, dry_run=True, argv=GITLEAKS, now=NOW)
    assert log.read_text(encoding="utf-8").split() == ["dir", "dir"]   # a finding, then the clean second pass
    folder = tmp_path / "f"
    folder.mkdir()
    (folder / "x.jsonl").write_text("a FAKELEAK\n", encoding="utf-8")
    monkeypatch.setenv("FAKE_GITLEAKS", "old")
    assert sa.gitleaks(GITLEAKS, folder) == {"x.jsonl": {1}}


def test_a_bad_residency_pattern_refuses_the_run(brain):
    cfg = brain({"enabled": True, "resident": {"broken": "(unclosed"}})
    with pytest.raises(sa.ArchiveError, match="resident.broken: not a regex"):
        sa.run(cfg, argv=GITLEAKS, now=NOW)


def test_an_undeclared_store_is_refused_by_the_spool(brain, brain_home):
    cfg = brain(ON, stores={k: v for k, v in STORES.items() if k != "session-archive"})
    with pytest.raises(sa.ArchiveError, match="the spool refused the archive"):
        sa.run(cfg, argv=GITLEAKS, now=NOW, found=brain.found)
    assert not staged_left(brain_home) and not (brain_home / "session-archive" / "index.json").exists()


def test_max_files_leaves_the_rest_for_the_next_run(brain):
    res = sa.run(brain(ON), dry_run=True, max_files=1, argv=GITLEAKS, now=NOW)
    assert len(res["archived"]) == 1 and res["waiting"] == 1


def test_the_sr_id_is_the_schemas():
    pattern = schema.load("sr")["properties"]["id"]["pattern"]
    assert re.match(pattern, sa.sr_id("2026-11-10", SID)) and sa.sr_id("2026-11-10", SID) == SR


def test_health(brain, monkeypatch):
    out = io.StringIO()
    assert sa.health(brain(), out=out) == 0 and "OFF" in out.getvalue()
    out = io.StringIO()
    sa.health(brain(), out=out, named=False)
    assert out.getvalue() == ""
    cfg = brain(ON)
    monkeypatch.setattr(sa, "scanner", lambda: GITLEAKS)
    out = io.StringIO()
    sa.health(cfg, now=NOW, out=out)
    assert "no run has sealed anything yet" in out.getvalue()
    sa.run(cfg, now=NOW, found=brain.found)
    out = io.StringIO()
    sa.health(cfg, now=NOW + timedelta(hours=3), out=out)
    assert "OK the last archive is 0d 3h old" in out.getvalue()
    out = io.StringIO()
    sa.health(cfg, now=NOW + timedelta(days=9), out=out)
    assert "WARN the last archive is 9 days old" in out.getvalue()


def test_status_lines(brain):
    s = sa.status(brain(ON))
    assert s["enabled"] and s["resident"] == ["vendor"] and s["sessions"] == 0
    assert sa.render_status(s)[0] == "session archive: on"


def test_the_spool_keeps_its_own_refusals(brain):
    """The archive goes through brain.spool.put: a store whose class never leaves is refused there too."""
    cfg = brain(ON, stores={**STORES, "session-archive": {"class": "resident",
                                                          "paths": ["$BRAIN_HOME/session-archive"]}})
    with pytest.raises(sa.ArchiveError, match="never lets it leave"):
        sa.run(cfg, argv=GITLEAKS, now=NOW, found=brain.found)
    assert spool.load_index()[1]["files"] == {}


def test_the_command_runs_the_archive_and_prints_its_status(brain, brain_home, monkeypatch, capsys):
    brain(ON)
    monkeypatch.setattr(sa, "scanner", lambda: GITLEAKS)
    args = type("Args", (), {"sarch_cmd": "run", "dry_run": True, "max": None, "json": True})()
    assert cmd.run(args, brain.root) == 0
    res = json.loads(capsys.readouterr().out)
    assert res["dry_run"] and {a["file"] for a in res["archived"]} == {f"{SR}.jsonl", f"{SR}--agent-abc.jsonl"}
    args.sarch_cmd, args.json = "status", False
    assert cmd.run(args, brain.root) == 0
    out = capsys.readouterr().out
    assert "session archive: on" in out and "scanner: gitleaks" in out and "residency filters: vendor" in out
    assert cli.main(["--root", str(brain.root), "health", "session-archive"]) == 0
    assert "WARN no run has sealed anything yet" in capsys.readouterr().out


def test_gitleaks_reads_with_its_own_rules_whatever_the_line_or_the_environment_says(brain, monkeypatch, tmp_path):
    """A whole tool result is one line: a gitleaks:allow in it must not hide a secret, nor an inherited config."""
    folder = tmp_path / "f"
    folder.mkdir()
    (folder / "x.jsonl").write_text('{"m": "a FAKELEAK in a file that says gitleaks:allow"}\n', encoding="utf-8")
    monkeypatch.setenv("GITLEAKS_CONFIG", str(tmp_path / "narrow.toml"))
    assert sa.gitleaks(GITLEAKS, folder) == {"x.jsonl": {1}}


def test_a_lone_carriage_return_does_not_shift_the_dropped_line(tmp_path):
    src = tmp_path / "t.jsonl"
    src.write_bytes(b'{"a": 1}\npartial\rwith a CR\n{"m": "a FAKELEAK"}\n{"z": 2}\n')
    stage = tmp_path / "stage"
    stage.mkdir()
    counts = {"t.jsonl": sa.filter_file(src, stage / "t.jsonl", {})}
    sa.scan_staged(GITLEAKS, stage, counts)
    with open(stage / "t.jsonl", encoding="utf-8", newline="") as fh:
        lines = fh.read().split("\n")
    assert lines[:4] == ['{"a": 1}', "partial with a CR", sa.STUB_SECRET, '{"z": 2}'] and counts["t.jsonl"].secret == 1


def test_staged_copies_left_by_a_killed_run_are_removed_and_warned_about(brain, brain_home, monkeypatch):
    cfg = brain(ON)
    left = brain_home / "session-archive" / "staging-killed"
    left.mkdir(parents=True)
    (left / "x.jsonl").write_text("clear\n", encoding="utf-8")
    assert any("staged copies in clear" in ln for ln in sa.render_status(sa.status(cfg)))
    monkeypatch.setattr(sa, "scanner", lambda: GITLEAKS)
    out = io.StringIO()
    sa.health(cfg, now=NOW, out=out)
    assert "1 staged folder(s) in clear" in out.getvalue()
    res = sa.run(cfg, now=NOW, found=brain.found)
    assert not left.exists() and res["leftovers"] == [] and res["sealed"]


def test_a_grown_transcript_is_archived_again(brain):
    cfg = brain(ON)
    sa.run(cfg, argv=GITLEAKS, now=NOW, found=brain.found)
    with brain.main.open("a", encoding="utf-8") as fh:
        fh.write(line("resumed") + "\n")
    old = (NOW - timedelta(hours=3)).timestamp()
    os.utime(brain.main, (old, old))
    res = sa.run(cfg, argv=GITLEAKS, now=NOW, found=brain.found)
    assert [a["file"] for a in res["archived"]] == [f"{SR}.jsonl"] and res["unchanged"] == 1


def test_a_newer_index_refuses_the_run_but_not_the_plan(brain, brain_home):
    cfg = brain(ON)
    (brain_home / "session-archive").mkdir(parents=True)
    (brain_home / "session-archive" / "index.json").write_text('{"v": 99, "sessions": {}, "last": {}}',
                                                               encoding="utf-8")
    with pytest.raises(sa.ArchiveError):
        sa.run(cfg, argv=GITLEAKS, now=NOW, found=brain.found)
    assert sa.run(cfg, dry_run=True, argv=GITLEAKS, now=NOW)["archived"]


@pytest.mark.parametrize("n", ["0", "-1"])
def test_max_is_one_or_more(brain, n):
    with pytest.raises(SystemExit):
        cli.main(["--root", str(brain.root), "session-archive", "run", "--max", n])
