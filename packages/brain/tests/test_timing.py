import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import run_git

import brain
from brain import cli, schema, timing

PLUGIN = Path(brain.__file__).resolve().parent / "adapters" / "claude"  # its hooks/ folder is a plugin's
T0 = datetime(2026, 11, 2, 10, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def labels(monkeypatch):
    """Fixed project and version (no registry, no git call) unless a test removes them; fresh caches."""
    monkeypatch.setenv("BRAIN_PROJECT", "proj")
    monkeypatch.setenv("BRAIN_VERSION", "v1")
    monkeypatch.delenv("BRAIN_TIMED", raising=False)
    timing._project_of.cache_clear()
    timing._head.cache_clear()
    yield
    timing._project_of.cache_clear()
    timing._head.cache_clear()


def _events(home, kind="exec"):
    return [json.loads(line) for f in sorted((home / "ledger").glob(f"{kind}-*.jsonl"))
            for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]


def _child_env(home):
    return dict(os.environ, BRAIN_HOME=str(home), PYTHONPATH=str(PLUGIN), BRAIN_PROJECT="proj", BRAIN_VERSION="v1")


# --- events ---

def test_make_event_follows_the_schema(brain_home):
    ev = timing.make_event("cycle L4", T0, T0 + timedelta(seconds=2.5), 2.5004, 0, details={"rows": 3},
                           log="logs/l4.log")
    assert schema.check("event", ev) == ([], [])
    assert ev["v"] == 1 and ev["kind"] == "exec" and ev["at"] == ev["end"] == "2026-11-02T10:00:02.500Z"
    assert ev["start"] == "2026-11-02T10:00:00.000Z" and ev["duration_s"] == 2.5 and ev["exit"] == 0
    assert ev["project"] == "proj" and ev["version"] == "v1" and ev["host"] and ev["pid"] == os.getpid()
    assert ev["details"] == {"rows": 3} and ev["log"] == "logs/l4.log"
    with pytest.raises(TypeError, match="unknown event field"):
        timing.make_event("x", T0, T0, 0, 0, colour="red")


def test_exit_none_is_kept_and_secrets_are_dropped(brain_home):
    fake = "curl -H 'Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123'"  # gitleaks:allow (a fake key)
    ev = timing.make_event("deploy", T0, T0, 0.1, None, command=fake)
    assert ev["exit"] is None and "abcdefghij" not in ev["command"] and "dropped" in ev["command"]
    assert schema.check("event", ev)[0] == []


def test_the_schema_rejects_bad_events():
    good = timing.make_event("x", T0, T0 + timedelta(seconds=1), 1, 0)
    assert schema.check("event", {**good, "end": "2026-11-02T09:00:00.000Z"})[0] == ["event.end: before start"]
    errors = schema.check("event", {k: v for k, v in good.items() if k != "duration_s"})[0]
    assert any("duration_s" in e for e in errors)
    assert schema.check("event", {**good, "colour": "red"})[0]
    error_event = {"v": 1, "kind": "error", "at": good["at"], "host": "h", "task": "cycle", "code": "0x41306",
                   "severity": "error", "details": "killed by its time limit", "log": "x.log"}
    assert schema.check("event", error_event) == ([], [])
    assert schema.check("event", {**error_event, "severity": "fatal"})[0]


def test_write_event_appends_to_the_month_file(brain_home):
    ev = timing.make_event("a", T0, T0 + timedelta(seconds=1), 1, 0)
    f = timing.write_event(ev)
    assert f == brain_home / "ledger" / "exec-2026-11.jsonl"
    timing.write_event(timing.make_event("b", T0, T0 + timedelta(seconds=1), 1, 0))
    assert [e["task"] for e in _events(brain_home)] == ["a", "b"]
    with pytest.raises(ValueError, match="invalid event"):
        timing.write_event({**ev, "duration_s": -1})


def test_a_torn_last_line_is_closed_before_the_next_event(brain_home):
    d = brain_home / "ledger"
    d.mkdir(parents=True)
    (d / "exec-2026-11.jsonl").write_bytes(b'{"v":1,"kind":"exec","task":"kil')  # a writer died mid-line
    timing.write_event(timing.make_event("next", T0, T0, 0, 0))
    lines = (d / "exec-2026-11.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and json.loads(lines[1])["task"] == "next"


# --- concurrency ---

WRITER = """
import sys
from datetime import datetime, timezone
from brain import timing
n = int(sys.argv[1])
for i in range(n):
    now = datetime.now(timezone.utc)
    timing.record(f"w{sys.argv[2]}-{i}", now, now, 0.001, 0, details={"pad": "x" * 600})
"""


def test_concurrent_processes_and_threads_lose_and_mix_no_line(brain_home, tmp_path):
    procs, n = 6, 120
    script = tmp_path / "writer.py"
    script.write_text(WRITER, encoding="utf-8")
    children = [subprocess.Popen([sys.executable, str(script), str(n), str(k)], env=_child_env(brain_home))
                for k in range(procs)]

    def threaded(k):
        for i in range(n):
            now = datetime.now(timezone.utc)
            timing.record(f"t{k}-{i}", now, now, 0.001, 0, details={"pad": "y" * 600})

    threads = [threading.Thread(target=threaded, args=(k,)) for k in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(c.wait(timeout=120) == 0 for c in children)
    raw = b"".join(f.read_bytes() for f in (brain_home / "ledger").glob("exec-*.jsonl"))
    lines = raw.decode("utf-8").splitlines()
    tasks = [json.loads(line)["task"] for line in lines]  # every line is whole JSON
    assert len(tasks) == (procs + 4) * n == len(set(tasks))
    assert not (brain_home / "ledger" / "errors.log").exists()


HOLDER_CHILD = """
import sys
from datetime import datetime, timezone
from pathlib import Path
from brain import timing
now = datetime.now(timezone.utc)
ev = timing.make_event("waited", now, now, 0.0, 0)
Path(sys.argv[1]).write_text("ready")
timing.write_event(ev)
"""


def test_a_writer_waits_for_the_lock_another_process_holds(brain_home, tmp_path):
    d = brain_home / "ledger"
    d.mkdir(parents=True)
    script, ready = tmp_path / "child.py", tmp_path / "ready"
    script.write_text(HOLDER_CHILD, encoding="utf-8")
    with timing.locked(d) as got:
        assert got
        child = subprocess.Popen([sys.executable, str(script), str(ready)], env=_child_env(brain_home))
        deadline = time.monotonic() + 60
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        time.sleep(0.5)  # the child is now polling the lock (LOCK_TIMEOUT is 5 s)
        assert child.poll() is None and _events(brain_home) == []
    assert child.wait(timeout=60) == 0
    assert [e["task"] for e in _events(brain_home)] == ["waited"]


def test_without_the_lock_the_event_is_still_written_and_logged(brain_home, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(timing, "_try_lock", lambda fd: False)
    monkeypatch.setattr(timing, "_clock", lambda: clock[0])
    monkeypatch.setattr(timing, "_sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    timing.write_event(timing.make_event("stuck", T0, T0, 0, 0))
    assert [e["task"] for e in _events(brain_home)] == ["stuck"]
    assert clock[0] >= timing.LOCK_TIMEOUT
    assert "not had in" in (brain_home / "ledger" / "errors.log").read_text(encoding="utf-8")


# --- the decorator and the context manager ---

def test_context_manager_and_decorator(brain_home):
    with timing.timed("block", details={"n": 1}) as t:
        time.sleep(0.01)
    assert t.event["task"] == "block" and t.event["exit"] == 0 and t.event["duration_s"] >= 0.005

    @timing.timed()
    def step(x):
        return x * 2

    @timing.timed("named step", project="other", version="v2")
    def fact(n):
        return 1 if n <= 1 else n * fact(n - 1)  # nested calls: each its own timer

    assert step(21) == 42 and fact(3) == 6
    evs = _events(brain_home)
    assert evs[1]["task"] == f"{__name__}.test_context_manager_and_decorator.<locals>.step"
    assert [e["task"] for e in evs[2:]] == ["named step"] * 3
    assert {e["project"] for e in evs[2:]} == {"other"} and {e["version"] for e in evs[2:]} == {"v2"}
    assert all(schema.check("event", e)[0] == [] for e in evs)


def test_exceptions_set_the_exit_and_go_on(brain_home):
    @timing.timed("boom")
    def boom():
        raise ValueError("no")

    with pytest.raises(ValueError):
        boom()
    with pytest.raises(SystemExit):
        with timing.timed("exit 3"):
            sys.exit(3)
    with pytest.raises(SystemExit):
        with timing.timed("exit text"):
            sys.exit("bad")
    with pytest.raises(KeyboardInterrupt):
        with timing.timed("ctrl c"):
            raise KeyboardInterrupt
    got = {e["task"]: (e["exit"], e.get("error")) for e in _events(brain_home)}
    assert got == {"boom": (1, "ValueError"), "exit 3": (3, None), "exit text": (1, None),
                   "ctrl c": (130, "KeyboardInterrupt")}


def test_the_ledger_never_breaks_the_timed_work(brain_home, monkeypatch):
    def broken(event, ledger=None):
        raise OSError("disk full")

    monkeypatch.setattr(timing, "write_event", broken)
    with timing.timed("still runs") as t:
        pass
    assert t.event is None
    assert "disk full" in (brain_home / "ledger" / "errors.log").read_text(encoding="utf-8")
    with pytest.raises(TypeError):
        timing.timed("x", colour="red")
    with pytest.raises(TypeError):
        with timing.timed():
            pass


def test_brain_timed_off(brain_home, monkeypatch):
    monkeypatch.setenv("BRAIN_TIMED", "0")
    with timing.timed("quiet") as t:
        pass
    assert t.event["task"] == "quiet" and not (brain_home / "ledger").exists()


# --- defaults: project, version, host ---

def test_project_from_the_registry_a_worktree_or_the_folder(brain_home, git_repo, tmp_path, monkeypatch):
    monkeypatch.delenv("BRAIN_PROJECT")
    reg = tmp_path / "projects.yaml"
    reg.write_text(f"alpha: {{root: '{git_repo.as_posix()}'}}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    sub = git_repo / "notes"
    assert timing.project_for(sub) == "alpha"
    wt = tmp_path / "wt"
    run_git(git_repo, "worktree", "add", "-q", "-b", "side", str(wt))
    assert timing.project_for(wt) == "alpha"  # a worktree outside the root: its main checkout's project
    elsewhere = tmp_path / "plain" / "folder"
    elsewhere.mkdir(parents=True)
    assert timing.project_for(elsewhere) == "folder"
    reg.write_text("{}\n", encoding="utf-8")
    timing._project_of.cache_clear()
    assert timing.project_for(wt) == git_repo.name  # unregistered: the main checkout's name
    monkeypatch.setenv("BRAIN_PROJECT", "forced")
    assert timing.project_for(wt) == "forced"


def test_version_is_the_short_head_sha(brain_home, git_repo, tmp_path, monkeypatch):
    monkeypatch.delenv("BRAIN_VERSION")
    head = run_git(git_repo, "rev-parse", "--short=10", "HEAD").strip()
    assert timing.version_for(git_repo) == head
    outside = tmp_path / "no-repo"
    outside.mkdir()
    assert "version" not in timing.make_event("x", T0, T0, 0, 0, cwd=outside)
    monkeypatch.setenv("BRAIN_HOST", "forge")
    assert timing.make_event("x", T0, T0, 0, 0)["host"] == "forge"


def test_fmt_duration():
    assert [timing.fmt_duration(s) for s in (0.04, 4.25, 42.4, 185, 3569, 3575, 7380)] == [
        "0.0 s", "4.2 s", "42 s", "3 min 05 s", "59 min 29 s", "1 h 00 min", "2 h 03 min"]


# --- brain timed ---

def test_run_passes_the_exit_code_through_and_records(brain_home, capsys):
    code = timing.run(["--", sys.executable, "-c", "import sys; print('out'); sys.exit(3)"], task="three")
    assert code == 3
    captured = capsys.readouterr()
    assert captured.err.startswith("timed: three ") and captured.err.rstrip().endswith("exit 3")
    ev = _events(brain_home)[-1]
    assert ev["task"] == "three" and ev["exit"] == 3 and "sys.exit(3)" in ev["command"]


def test_run_not_found_shell_and_default_task(brain_home, capsys):
    assert timing.run(["no-such-program-xyz", "arg"], quiet=True) == 127
    assert timing.run([f'"{sys.executable}" -c "import sys; sys.exit(4)"'], shell=True, quiet=True) == 4
    assert timing.run([sys.executable, "-c", "pass"], quiet=True) == 0
    assert capsys.readouterr().err == ""
    evs = _events(brain_home)
    assert (evs[0]["exit"], evs[0]["error"], evs[0]["task"]) == (127, "not found", "no-such-program-xyz arg")
    assert evs[1]["exit"] == 4
    assert evs[2]["task"] == "python -c pass" or evs[2]["task"].endswith(" -c pass")
    assert timing.run([]) == 2


def test_run_waits_for_an_interrupted_command(brain_home, monkeypatch):
    class Proc:
        def __init__(self, argv, shell=False):
            self.calls = 0

        def wait(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise KeyboardInterrupt
            return -2  # POSIX: ended by SIGINT

        def kill(self):
            raise AssertionError("not needed: it ended within the grace period")

    monkeypatch.setattr(timing.subprocess, "Popen", Proc)
    assert timing.run([sys.executable, "-c", "pass"], quiet=True) == 130
    ev = _events(brain_home)[-1]
    assert (ev["exit"], ev["error"]) == (-2, "interrupted")


def test_cli_timed_options_and_both_project_forms(brain_home):
    prog = [sys.executable, "-c", "pass"]
    assert cli.main(["timed", "--task", "t1", "--project", "p1", "--version", "abc", "--quiet", "--", *prog]) == 0
    assert cli.main(["--project", "p2", "timed", "--quiet", "--task", "t2", "--", *prog]) == 0
    assert cli.main(["timed", "--quiet", *prog]) == 0  # no --: the command still goes whole to the child
    evs = _events(brain_home)
    assert [(e["task"], e["project"], e["version"]) for e in evs[:2]] == [("t1", "p1", "abc"), ("t2", "p2", "v1")]
    assert evs[2]["command"].endswith("-c pass")
