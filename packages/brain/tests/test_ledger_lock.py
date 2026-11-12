"""wi-brain-ledger-append-lock: every append-only ledger of the brain is written under the exec ledger's lock
(brain.timing.append_text), so that sessions' hooks and commands writing at once neither lose nor mix a line."""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import brain
from brain import answers, capture, detail, governor, guards, notify, queue, quiet, quota, timing, usage

PLUGIN = Path(brain.__file__).resolve().parent / "adapters" / "claude"

WRITER = """
import sys
from brain import capture, guards
n, k = int(sys.argv[1]), sys.argv[2]
pad = "x" * 600
for i in range(n):
    capture._append("events", {"at": "2026-11-12T10:00:00.000Z", "id": f"e{k}-{i}", "pad": pad})
    guards._record({"tool_name": "Bash", "session_id": f"s{k}", "tool_use_id": f"g{k}-{i}", "cwd": pad},
                   "owner", "installer", "deny", "test", request={"what": pad})
"""


def _lines(f: Path) -> list[dict]:
    return [json.loads(line) for line in f.read_bytes().decode("utf-8").splitlines()]  # every line whole JSON


def test_concurrent_hooks_lose_and_mix_no_capture_or_guard_line(brain_home, tmp_path):
    procs, n = 6, 80
    script = tmp_path / "writer.py"
    script.write_text(WRITER, encoding="utf-8")
    env = dict(os.environ, BRAIN_HOME=str(brain_home), PYTHONPATH=str(PLUGIN))
    children = [subprocess.Popen([sys.executable, str(script), str(n), str(k)], env=env) for k in range(procs)]
    assert all(c.wait(timeout=180) == 0 for c in children)
    d = brain_home / "ledger"
    events = [r["id"] for r in _lines(d / "events-2026-11.jsonl")]
    guard_rows = [r["tool_use_id"] for f in d.glob("guards-*.jsonl") for r in _lines(f)]
    assert len(events) == procs * n == len(set(events))
    assert len(guard_rows) == procs * n == len(set(guard_rows))
    assert not (d / "errors.log").exists()


@pytest.fixture
def spy(monkeypatch):
    """The files written through the locked append, with their lines."""
    seen: list[tuple[str, int]] = []
    real = timing.append_text

    def append_text(f, text):
        seen.append((Path(f).name, text.count("\n")))
        return real(f, text)

    monkeypatch.setattr(timing, "append_text", append_text)
    return seen


AT = "2026-11-12T10:00:00Z"


def test_every_ledger_writer_goes_through_the_lock(brain_home, spy):
    (brain_home / "ledger").mkdir(parents=True)
    payload = {"tool_name": "Bash", "session_id": "s1", "tool_use_id": "t1", "cwd": "."}
    capture._append("ar", {"at": AT, "id": "ar-x"})
    guards._record(payload, "owner", "installer", "deny", "test")
    governor._record(payload, "budget", "deny", "test")
    answers._append("answers", [{"at": AT, "a": 1}, {"at": "2026-12-01T00:00:00Z", "a": 2}])
    queue.order("ddr-x", at=AT, position=1, by="owner")
    queue.done(brain_home, "perm-x", at=AT, by="owner")
    detail.log({"at": AT, "argv": ["brain", "status"]})
    notify._audit([{"at": AT, "n": 1}, {"at": AT, "n": 2}], datetime(2026, 11, 12, tzinfo=timezone.utc))
    governor._note_start({"tool_input": {"title": "t"}, "session_id": "s1"},
                         {"brainstorm": True, "now": AT, "project": "p"})
    quiet.hold(notify.Message("demo", "error", "body", host="pc"), datetime(2026, 11, 12, tzinfo=timezone.utc))
    names = [name for name, _ in spy]
    assert names == ["ar-2026-11.jsonl", "guards-2026-11.jsonl", "guards-2026-11.jsonl", "answers-2026-11.jsonl",
                     "answers-2026-12.jsonl", "queue-2026-11.jsonl", "queue-2026-11.jsonl",
                     f"{detail.LOG}-2026-11.jsonl", "2026-11.jsonl", "starts.jsonl",
                     quiet.HELD]
    assert dict(spy)["2026-11.jsonl"] == 2   # the notify audit's lines in one write
    assert (brain_home / "ledger" / "exec.lock").exists() and (brain_home / "notify" / "exec.lock").exists()


def test_the_quota_readings_go_through_the_lock(brain_home, spy):
    at = usage.now_utc() - timedelta(hours=1)
    quota.observe(42.0, window="week", at=at, resets=at + timedelta(days=2))
    assert [name for name, _ in spy] == [quota.readings_file().name]


def test_append_text_closes_a_torn_line_and_writes_nothing_for_nothing(brain_home):
    f = brain_home / "ledger" / "events-2026-11.jsonl"
    f.parent.mkdir(parents=True)
    f.write_bytes(b'{"id":"torn')
    assert timing.append_text(f, "")
    assert timing.append_lines(f, [{"id": "a"}, {"id": "b"}])
    assert f.read_bytes().decode("utf-8").splitlines()[1:] == ['{"id":"a"}', '{"id":"b"}']
