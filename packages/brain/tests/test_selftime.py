"""The engine times itself (wi-brain-self-timing): every brain command and every hook writes its exec event to
<BRAIN_HOME>/ledger/engine/, every error it catches an error event (class and module:function, never the message);
brain perf --engine and brain alerts read them back."""

import io
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from test_capture import PLUGIN, _bash

import brain
from brain import alerts, capture, cli, perf, projects, schema, selftime

HOOKS = PLUGIN / "hooks"


@pytest.fixture
def on(monkeypatch, brain_home):
    monkeypatch.delenv("BRAIN_SELFTIME", raising=False)
    monkeypatch.delenv("BRAIN_HOOK_T0", raising=False)
    return brain_home / "ledger" / "engine"


def _lines(d: Path, pattern: str) -> list[dict]:
    return [json.loads(x) for f in sorted(d.glob(pattern)) for x in f.read_text(encoding="utf-8").splitlines()]


def _valid(ev: dict) -> dict:
    errors, _ = schema.check("event", ev)
    assert not errors, errors
    return ev


# --- the Python writer ---

def test_a_run_writes_its_exec_event(on):
    with selftime.run("hook guard shell", from_import=False) as r:
        pass
    (ev,) = _lines(on, "exec-2*.jsonl")
    assert _valid(ev) == r.event
    assert ev["project"] == selftime.ENGINE == "brain" and ev["task"] == "hook guard shell"
    assert ev["version"] == brain.__version__ and ev["exit"] == 0 and "error" not in ev
    assert 0 <= ev["duration_s"] < 5


def test_the_end_is_never_before_the_start(on, monkeypatch):
    """A clock read that rounds the start up across a millisecond (or a wall clock stepped back) put the end 1 ms
    before the start (wi-brain-selftime-end-before-start): both come from time.time(), the end clamped to the start."""
    clock = iter([1762700000.1239995, 1762700000.1239991])   # enter, then exit a hair earlier
    monkeypatch.setattr(selftime.time, "time", lambda: next(clock))
    with selftime.run("hook guard shell", from_import=False):
        pass
    (ev,) = _lines(on, "exec-2*.jsonl")
    assert _valid(ev)["end"] == ev["start"] == "2025-11-09T14:53:20.124Z"   # clamped, from the same clock


def test_an_uncaught_error_is_an_exec_failure_and_an_error_event_without_its_message(on):
    with pytest.raises(perf.PerfError):
        with selftime.run("brain perf", from_import=False):
            perf.parse_since("D:/work/secret-folder", datetime.now(timezone.utc))
    (ex,) = _lines(on, "exec-2*.jsonl")
    (er,) = _lines(on, "error-*.jsonl")
    assert ex["exit"] == 1 and ex["error"] == "brain.perf.PerfError"
    assert _valid(er)["code"] == "brain.perf.PerfError" and er["severity"] == "error" and er["task"] == "brain perf"
    assert er["details"] == {"where": "brain.perf:parse_since"}  # the engine's frame, not this test's
    assert "secret-folder" not in json.dumps(er)


def test_an_exit_code_and_a_message_exit_are_not_errors(on):
    for code, want in ((3, 3), ("brain: no such item", 1), (None, 0)):
        with pytest.raises(SystemExit):
            with selftime.run("brain item", from_import=False):
                raise SystemExit(code)
    assert [e["exit"] for e in _lines(on, "exec-2*.jsonl")] == [3, 1, 0]
    assert not list(on.glob("error-*.jsonl"))


def test_the_error_sink_writes_the_text_line_and_the_event_and_marks_the_run(on, brain_home):
    def broken():
        return {}["missing-key"]

    with selftime.run("hook guard edit", from_import=False):
        try:
            broken()
        except KeyError as exc:
            capture._log_error("guard production", exc)
    (er,) = _lines(on, "error-*.jsonl")
    assert er["task"] == "hook guard edit" and er["code"] == "KeyError"
    assert er["details"]["where"].endswith(":broken")  # no brain frame: the innermost one
    assert "missing-key" not in json.dumps(er)
    assert "guard production: KeyError" in (brain_home / "ledger" / "errors.log").read_text(encoding="utf-8")
    (ex,) = _lines(on, "exec-2*.jsonl")
    assert ex["exit"] == 0 and ex["error"] == "KeyError"  # caught: the hook went on, its run says so


def test_a_hook_entry_never_raises(on):
    def main(argv):
        raise TypeError("expected string, got list")

    assert selftime.hook("hook capture post-tool-use", main, []) == 0
    assert _lines(on, "error-*.jsonl")[0]["code"] == "TypeError"
    assert _lines(on, "exec-2*.jsonl")[0]["error"] == "TypeError"


def test_a_hook_is_timed_from_its_bash_start(on, monkeypatch):
    monkeypatch.setenv(selftime.T0_ENV, f"{time.time() - 0.4:.6f}".replace(".", ","))  # a French locale's comma
    with selftime.run("hook budget", hook=True, from_import=False):
        pass
    monkeypatch.setenv(selftime.T0_ENV, f"{time.time() - 4000:.6f}")  # not this run's: ignored
    with selftime.run("hook budget", hook=True, from_import=False):
        pass
    first, second = _lines(on, "exec-2*.jsonl")
    assert 0.4 <= first["duration_s"] < 5 and second["duration_s"] < 5
    assert first["start"] < first["end"]


def test_a_command_is_timed_from_the_engine_import(on, monkeypatch):
    monkeypatch.setattr(selftime, "_started", (time.time() - 0.3, time.perf_counter() - 0.3))
    with selftime.run("brain sync"):
        pass
    assert _lines(on, "exec-2*.jsonl")[0]["duration_s"] >= 0.3


def test_off_writes_nothing(on, monkeypatch):
    monkeypatch.setenv("BRAIN_SELFTIME", "0")
    with selftime.run("brain sync", from_import=False):
        selftime.error(ValueError("x"))
    assert not on.exists()


def test_a_new_month_prunes_the_old_ones(on):
    on.mkdir(parents=True)
    now = datetime.now(timezone.utc)
    old = (now.replace(day=1) - timedelta(days=100)).strftime("%Y-%m")
    keep = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    for name in (f"exec-{old}.jsonl", f"exec-bash-{old}.jsonl", f"error-{old}.jsonl", f"exec-{keep}.jsonl"):
        (on / name).write_text("{}\n", encoding="utf-8")
    with selftime.run("brain status", from_import=False):
        pass
    assert sorted(f.name for f in on.glob("*.jsonl")) == sorted([f"exec-{keep}.jsonl", f"exec-{now:%Y-%m}.jsonl"])


def test_the_command_line_writes_one_event_per_command(on, monkeypatch, capsys):
    assert cli.main(["perf", "--engine", "--json"]) == 0
    capsys.readouterr()
    (ev,) = _lines(on, "exec-2*.jsonl")
    assert ev["task"] == "brain perf" and ev["exit"] == 0


def test_the_task_names_the_command_and_its_subcommand():
    p = cli.build_parser()
    assert selftime.command_task(p.parse_args(["sync"])) == "brain sync"
    assert selftime.command_task(p.parse_args(["decision", "pending"])) == "brain decision pending"
    assert selftime.command_task(p.parse_args(["record", "check"])) == "brain record check"


def test_the_light_import_of_timing():
    """A hook imports brain.selftime, so brain.timing: secretscan, schema and socket wait until used."""
    code = ("import sys, brain.selftime; bad = {'brain.secretscan', 'brain.schema', 'socket'} & set(sys.modules); "
            "print(sorted(bad))")
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=60,
                         env=dict(os.environ, PYTHONPATH=str(Path(brain.__file__).parents[1])))
    assert out.stdout.strip() == "[]", out.stderr


# --- the hooks ---

def test_every_hook_is_timed():
    """Each launcher sources common.sh and passes its start to Python; each Python entry runs through selftime."""
    for sh in HOOKS.glob("*.sh"):
        if sh.name == "common.sh":
            continue
        text = sh.read_text(encoding="utf-8")
        assert '. "${BASH_SOURCE[0]%[!A-Za-z0-9._-]*}/common.sh"' in text, sh.name
        for line in text.splitlines():
            if '-X utf8 -I "$root/hooks/' in line:
                assert "BRAIN_HOOK_T0=$brain_t0 " in line, (sh.name, line)
    for py in HOOKS.glob("*.py"):
        assert "from brain.selftime import hook" in py.read_text(encoding="utf-8"), py.name


def test_the_bash_side_knows_the_engine_version():
    text = (HOOKS / "common.sh").read_text(encoding="utf-8")
    assert re.search(r"^brain_version=(\S+)$", text, re.M).group(1) == brain.__version__


def _hook(script: str, payload: dict, *args, **env):
    bash = _bash()
    if not bash:
        pytest.skip("no bash")
    full = {k: v for k, v in os.environ.items() if k != "BRAIN_SELFTIME"}
    full.update(env)
    return subprocess.run([bash, str(HOOKS / script), *args], input=json.dumps(payload), capture_output=True,
                          text=True, env=full, timeout=60)


def test_a_bash_fast_path_appends_its_event(on, tmp_path):
    out = _hook("guard.sh", {"tool_name": "Bash", "tool_input": {"command": "ls -la"}, "cwd": str(tmp_path)},
                "shell", BRAIN_PYTHON=str(tmp_path / "no-python"))
    assert out.returncode == 0 and out.stdout == ""
    (ev,) = _lines(on, "exec-bash-*.jsonl")
    assert _valid(ev)["task"] == "hook guard shell [bash]" and ev["version"] == brain.__version__
    assert ev["exit"] == 0 and 0 <= ev["duration_s"] < 30 and ev["start"] <= ev["end"]
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", ev["at"])
    assert abs(datetime.fromisoformat(ev["at"].replace("Z", "+00:00")) - datetime.now(timezone.utc)) < \
        timedelta(minutes=5)  # UTC, not the machine's local time


def test_a_python_hook_counts_its_bash_start(on, tmp_path):
    out = _hook("guard.sh", {"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}, "cwd": str(tmp_path)},
                "shell", BRAIN_PYTHON=sys.executable)
    assert out.returncode == 0
    (ev,) = _lines(on, "exec-2*.jsonl")
    assert _valid(ev)["task"] == "hook guard shell" and ev["exit"] == 0
    assert not list(on.glob("exec-bash-*.jsonl"))  # one event per run: Python's


def test_the_budget_watch_fast_path_and_off(on, monkeypatch):
    assert _hook("budget.sh", {"tool_name": "Read"}).returncode == 0  # no session id: the fast path
    assert [e["task"] for e in _lines(on, "exec-bash-*.jsonl")] == ["hook budget [bash]"]
    assert _hook("budget.sh", {"tool_name": "Read"}, BRAIN_SELFTIME="0").returncode == 0
    assert len(_lines(on, "exec-bash-*.jsonl")) == 1


# --- brain perf --engine ---

def _write(d: Path, kind: str, events: list[dict]) -> None:
    d.mkdir(parents=True, exist_ok=True)
    with open(d / f"{kind}-{events[0]['at'][:7]}.jsonl", "a", encoding="utf-8") as fh:
        fh.writelines(json.dumps(e) + "\n" for e in events)


def _exec(task, at, d, version="0.2.2", error=""):
    end = at.isoformat().replace("+00:00", "Z")
    ev = {"v": 1, "kind": "exec", "at": end, "host": "h", "project": "brain", "task": task, "version": version,
          "start": end, "end": end, "duration_s": d, "exit": 0}
    return {**ev, **({"error": error} if error else {})}


def _err(task, at, code="TypeError", where="brain.guards:check_owner"):
    return {"v": 1, "kind": "error", "at": at.isoformat().replace("+00:00", "Z"), "host": "h", "project": "brain",
            "task": task, "version": "0.2.2", "code": code, "severity": "error", "details": {"where": where}}


def test_perf_engine_reads_the_engine_folder_only(on, brain_home, capsys):
    now = datetime.now(timezone.utc)
    _write(on, "exec", [_exec("hook guard shell", now - timedelta(minutes=i), 0.7, error="TypeError" if i < 2 else "")
                        for i in range(5)] + [_exec("hook capture stop", now, 2.0)])
    _write(on, "exec-bash", [_exec("hook budget [bash]", now, 0.1)])
    _write(on, "error", [_err("hook guard shell", now - timedelta(minutes=i)) for i in range(2)])
    _write(brain_home / "ledger", "exec", [{**_exec("cycle L4", now, 9.0), "project": "acme"}])
    assert perf.main(engine=True, as_json=True) == 0
    rep = json.loads(capsys.readouterr().out)
    rows = {r["task"]: r for r in rep["slowest"]}
    assert set(rows) == {"hook guard shell", "hook capture stop", "hook budget [bash]"}  # not acme's cycle
    assert rows["hook guard shell"]["errors"] == 2 and rows["hook guard shell"]["median_s"] == 0.7
    (week,) = rep["hook_weeks"]
    assert week["runs"] == 7 and week["blocking_s"] == pytest.approx(3.6)  # capture stop is async
    assert rep["errors"] == [{"task": "hook guard shell", "code": "TypeError", "where": "brain.guards:check_owner",
                              "count": 2, "first": rep["errors"][0]["first"], "last": rep["errors"][0]["last"]}]
    assert perf.main(engine=True) == 0
    text = capsys.readouterr().out
    assert "the engine's own runs" in text and "700 ms" in text and "errors the engine caught" in text
    assert "brain.guards:check_owner" in text and "hooks per week" in text


def test_perf_engine_regressions_by_engine_version(on, capsys):
    now = datetime.now(timezone.utc)
    _write(on, "exec", [_exec("brain sync", now - timedelta(hours=3, minutes=i), 6.0, "0.2.2") for i in range(3)]
           + [_exec("brain sync", now - timedelta(minutes=i), 25.0, "0.2.3") for i in range(3)])
    assert perf.main(engine=True, as_json=True) == 0
    (reg,) = json.loads(capsys.readouterr().out)["regressions"]
    assert (reg["task"], reg["from"], reg["to"]) == ("brain sync", "0.2.2", "0.2.3")


def test_perf_engine_refuses_from_and_project(on):
    assert perf.main(engine=True, sources=["x.jsonl"]) == 2
    assert perf.main(engine=True, project="acme") == 2


def test_perf_engine_says_where_when_empty(on, capsys):
    assert perf.main(engine=True) == 0
    assert "every brain command and hook writes them" in capsys.readouterr().out


# --- brain alerts ---

def _project(tmp_path, name="brain") -> projects.Project:
    root = tmp_path / name
    root.mkdir(exist_ok=True)
    return projects.Project(name=name, root=root)


def test_a_hook_failing_three_times_a_day_raises_an_alert(on, tmp_path):
    now = datetime.now(timezone.utc)
    _write(on, "error", [_err("hook guard shell", now - timedelta(hours=i)) for i in range(3)]
           + [_err("brain sync", now - timedelta(hours=i), code="OSError", where="brain.graph:load") for i in range(3)]
           + [_err("hook budget", now - timedelta(hours=i)) for i in range(2)]               # twice: not yet
           + [_err("hook midsession", now - timedelta(hours=30 + i)) for i in range(5)])     # yesterday's
    found = {a.key: a for a in alerts.engine_alerts(alerts.config(_project(tmp_path)), now)}
    assert set(found) == {"engine:hook-guard-shell:TypeError", "engine:brain-sync:OSError"}
    guard = found["engine:hook-guard-shell:TypeError"]
    assert guard.level == "error" and guard.source == "engine" and "3 times in 24 h" in guard.message
    assert "brain.guards:check_owner" in guard.message
    assert found["engine:brain-sync:OSError"].level == "warn"


def test_the_brain_project_carries_the_engine_alerts(on, tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    _write(on, "error", [_err("hook guard edit", now - timedelta(minutes=i)) for i in range(4)])
    brain_p, other = _project(tmp_path), _project(tmp_path, "acme")
    assert alerts.carries_engine(brain_p) and not alerts.carries_engine(other)
    keys = [a.key for a in alerts.of_project(brain_p)]
    assert "engine:hook-guard-edit:TypeError" in keys
    assert not [a for a in alerts.of_project(other) if a.source == "engine"]
    monkeypatch.setenv("BRAIN_PERSONAL", str(other.root))  # a brain of another name: its personal root carries them
    assert alerts.carries_engine(other)


def test_the_sink_feeds_the_alert_end_to_end(on, tmp_path):
    for _ in range(3):
        with selftime.run("hook guard shell", from_import=False):
            try:
                "".join([1])
            except TypeError as exc:
                capture._log_error("guard", exc)
    (a,) = [a for a in alerts.of_project(_project(tmp_path)) if a.source == "engine"]
    assert a.key == "engine:hook-guard-shell:TypeError" and a.level == "error"


def test_capture_main_keeps_going_and_reports(on, monkeypatch):
    def boom(payload):
        raise RuntimeError("no")

    monkeypatch.setitem(capture.HANDLERS, "stop", boom)
    assert capture.main(["stop"], stdin=io.StringIO("{}")) == 0
    assert _lines(on, "error-*.jsonl")[0]["code"] == "RuntimeError"



@pytest.mark.skipif(sys.platform != "win32", reason="nowindow wraps Popen on Windows")
def test_an_error_passing_through_nowindow_is_its_callers(monkeypatch):
    """brain.nowindow wraps every child a console-less engine starts: a child's own error (a cwd that is a file) is
    located at its caller, never at the wrapper (it read brain.nowindow:__init__ on 2026-11-09)."""
    from brain import nowindow
    monkeypatch.setattr(subprocess.Popen, "__init__", subprocess.Popen.__init__)   # restored after the test
    assert nowindow.install(console=lambda: False)
    with pytest.raises(OSError) as info:
        subprocess.Popen(["git", "--version"], cwd=str(Path(__file__)))
    assert not selftime.where(info.value).startswith("brain.nowindow")
