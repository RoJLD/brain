"""wi-brain-fault-injection: a virtual clock ($BRAIN_NOW) and injected faults ($BRAIN_FAULT=<point>[@<glob>]:<kind>)
honoured by the shared helpers (brain.stateio's writes and reads, brain.net's calls, the engine's « now »), so that the
command line and the suite play a failure end to end: a full disk, a process killed mid-write, a corrupt file, a
timeout, a date moved."""

import errno
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from brain import cli, faults, governor, net, paths, plugins, quiet, stateio, usage

SRC = str(Path(__file__).resolve().parents[1] / "src")
T = "2030-01-31T22:00:00Z"
AT = datetime(2030, 1, 31, 22, 0, tzinfo=timezone.utc)


@pytest.fixture
def env(monkeypatch):
    for k in (faults.NOW_ENV, faults.FAULT_ENV, net.SWITCH):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


# --- the clock ---

@pytest.mark.parametrize("text, want", [
    ("2030-01-31", datetime(2030, 1, 31, tzinfo=timezone.utc)),
    ("2030-01-31T22:00", AT),
    (T, AT),
    ("2030-01-31T23:00:00+01:00", AT),
])
def test_a_point_in_time_freezes_the_clock_in_utc(env, text, want):
    env.setenv(faults.NOW_ENV, text)
    assert faults.now() == want and faults.now().tzinfo == timezone.utc
    assert faults.time() == want.timestamp()
    assert faults.virtual()


def test_a_shift_moves_the_real_clock_and_keeps_it_running(env):
    env.setenv(faults.NOW_ENV, "+3d")
    real = datetime.now(timezone.utc)
    assert abs((faults.now() - real) - timedelta(days=3)) < timedelta(seconds=5)
    env.setenv(faults.NOW_ENV, "-90m")
    assert abs((faults.now() - datetime.now(timezone.utc)) + timedelta(minutes=90)) < timedelta(seconds=5)


def test_unset_it_is_the_real_clock(env):
    assert not faults.virtual()
    assert abs(faults.now() - datetime.now(timezone.utc)) < timedelta(seconds=5)


@pytest.mark.parametrize("text", ["tomorrow", "+3", "3d", "2030-13-01"])
def test_a_clock_that_is_not_a_date_is_refused(env, text):
    env.setenv(faults.NOW_ENV, text)
    with pytest.raises(faults.FaultError, match=faults.NOW_ENV):
        faults.now()


def test_the_shared_helpers_read_the_virtual_clock(env, tmp_path):
    env.setenv(faults.NOW_ENV, T)
    assert usage.now_utc() == AT and governor._now() == AT
    assert net._clock() == AT.timestamp()
    f = tmp_path / "state.json"
    f.write_text("not json", encoding="utf-8")
    st = stateio.load(f)
    assert st.status == "aside" and st.aside.name == "state.json.unreadable-20300131T220000Z"
    copy = stateio.backup_home(tmp_path / "state.json.unreadable-20300131T220000Z", tmp_path / "bk")
    assert copy.name.startswith("state.json.unreadable-20300131T220000Z.20300131T220000")


def test_a_month_later_the_log_rotates(env, tmp_path):
    log = tmp_path / "errors.log"
    log.write_text("a line\n", encoding="utf-8")
    mtime = datetime.now(timezone.utc)
    env.setenv(faults.NOW_ENV, (mtime + timedelta(days=40)).strftime("%Y-%m-%d"))
    moved = stateio.rotate_log(log)
    assert moved is not None and moved.name == f"errors-{mtime:%Y-%m}.log" and not log.exists()


def test_the_breaker_window_runs_on_the_virtual_clock(env):
    env.setenv(faults.NOW_ENV, T)
    net.failed("svc", "timed out")
    assert net.blocked("svc")                              # open at T
    env.setenv(faults.NOW_ENV, "2030-01-31T22:06:00Z")     # past its 5 minutes
    assert net.blocked("svc") == ""


# --- the faults: parsing ---

@pytest.mark.parametrize("text", ["write", "write:full", "disk:disk-full", "net@x", "read:timeout"])
def test_a_fault_not_understood_is_refused(env, text):
    env.setenv(faults.FAULT_ENV, text)
    with pytest.raises(faults.FaultError, match="<point>"):
        faults.fault("write", "x.json")


def test_the_glob_narrows_to_a_name_a_path_or_a_service(env, tmp_path):
    env.setenv(faults.FAULT_ENV, "write@?uota.json:disk-full, read@*/usage/*:corrupt,net@http:*:timeout")
    assert faults.fault("write", tmp_path / "usage" / "quota.json") == "disk-full"
    assert faults.fault("write", tmp_path / "usage" / "quota.json.sha256") == ""
    assert faults.fault("read", tmp_path / "usage" / "sessions.json") == "corrupt"
    assert faults.fault("read", tmp_path / "alerts" / "state.json") == ""
    assert faults.fault("net", "http:ntfy.sh") == "timeout"
    assert faults.fault("net", "github") == ""
    env.setenv(faults.FAULT_ENV, "net:refused")
    assert faults.fault("net", "anything") == "refused" and faults.fault("write", "x") == ""


def test_a_glob_written_with_backslashes_matches(env, tmp_path):
    env.setenv(faults.FAULT_ENV, r"write@*\usage\quota.json:disk-full")
    assert faults.fault("write", tmp_path / "usage" / "quota.json") == "disk-full"


def test_never_played_on_the_real_home(env, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)          # the default home, here: tmp_path/.brain
    env.setenv("BRAIN_HOME", str(tmp_path / ".brain"))
    env.setenv(faults.NOW_ENV, T)
    env.setenv(faults.FAULT_ENV, "write:disk-full")
    assert not faults.scratch() and not faults.virtual()
    assert abs(faults.now() - datetime.now(timezone.utc)) < timedelta(seconds=5)   # the real clock
    assert faults.fault("write", tmp_path / "x.json") == ""                        # nothing injected
    with pytest.raises(faults.FaultError, match="scratch home"):
        faults.check()
    assert cli.main(["quiet"]) == 2 and "scratch home" in capsys.readouterr().err
    assert not (tmp_path / ".brain").exists()


def test_a_plugin_command_is_refused_too(env, monkeypatch, capsys):
    ran = []
    monkeypatch.setattr(plugins, "target", lambda argv, commands: ([], "demo", "x", ["go"]))
    monkeypatch.setattr(plugins, "run", lambda *a: ran.append(a) or 0)
    env.setenv(faults.FAULT_ENV, "disk:full")
    assert cli.main(["demo", "go"]) == 2 and ran == [] and faults.FAULT_ENV in capsys.readouterr().err
    env.delenv(faults.FAULT_ENV)
    assert cli.main(["demo", "go"]) == 0 and len(ran) == 1


def test_off_by_default(env, tmp_path):
    assert faults.fault("write", tmp_path / "x.json") == ""
    stateio.write_atomic(tmp_path / "x.json", "{}\n")
    assert (tmp_path / "x.json").read_text(encoding="utf-8") == "{}\n"


# --- write ---

def test_disk_full_leaves_the_file_as_it_was_and_no_temporary_file(env, tmp_path, capsys):
    f = tmp_path / "state.json"
    st = stateio.load(f)
    stateio.save(st, {"a": 1})
    before = f.read_bytes()
    env.setenv(faults.FAULT_ENV, "write@*/state.json:disk-full")
    with pytest.raises(OSError) as exc:
        stateio.save(stateio.load(f), {"a": 2})
    assert exc.value.errno == errno.ENOSPC
    assert f.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["state.json", "state.json.bak"]
    assert "BRAIN_FAULT write:disk-full" in capsys.readouterr().err


KILL = """\
import sys
from pathlib import Path
from brain import stateio
stateio.write_atomic(Path(sys.argv[1]), "new\\n")
print("not reached")
"""


def _py(code, *args, **env):
    e = {**os.environ, "PYTHONPATH": SRC, **env}
    return subprocess.run([sys.executable, "-c", code, *args], capture_output=True, text=True, env=e, timeout=120)


def test_killed_mid_write_ends_the_process_before_the_move(env, tmp_path):
    f = tmp_path / "state.json"
    f.write_text("old\n", encoding="utf-8")
    r = _py(KILL, str(f), BRAIN_FAULT="write:killed")
    assert r.returncode == faults.KILLED_EXIT and "not reached" not in r.stdout
    assert "BRAIN_FAULT write:killed" in r.stderr
    assert f.read_text(encoding="utf-8") == "old\n"                       # the file as it was
    left = [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert len(left) == 1 and left[0].read_text(encoding="utf-8") == "new\n"   # what a kill leaves


# --- read ---

def test_a_corrupt_read_sets_the_file_aside_and_keeps_its_real_bytes(env, tmp_path):
    f = tmp_path / "state.json"
    f.write_text('{"a": 1}\n', encoding="utf-8")
    env.setenv(faults.FAULT_ENV, "read@*/state.json:corrupt")
    ro = stateio.load(f, aside=False)
    assert ro.status == "unreadable" and "not JSON" in ro.why and f.exists()   # a read-only command moves nothing
    st = stateio.load(f)
    assert st.status == "aside" and st.data == {} and not f.exists()
    assert st.aside.read_text(encoding="utf-8") == '{"a": 1}\n'   # the disk was never changed
    stateio.save(st, {"b": 2})
    env.delenv(faults.FAULT_ENV)
    assert stateio.load(f).data == {"b": 2}


def test_a_corrupt_foreign_file_is_refused_not_replaced(env, tmp_path):
    f = tmp_path / "settings.json"
    f.write_text('{"a": 1}\n', encoding="utf-8")
    env.setenv(faults.FAULT_ENV, "read:corrupt")
    with pytest.raises(stateio.StateError, match="fix it by hand"):
        stateio.read_foreign(f)
    assert f.read_text(encoding="utf-8") == '{"a": 1}\n'


# --- net ---

def test_a_timeout_is_not_called_not_retried_and_opens_the_breaker(env):
    env.setenv(faults.FAULT_ENV, "net@gitnexus:timeout")
    called = []
    with pytest.raises(TimeoutError):
        net.call("gitnexus", lambda: called.append(1))
    assert called == [] and net.status()["gitnexus"]["open"]
    with pytest.raises(net.Unavailable, match="gitnexus unavailable"):
        net.call("gitnexus", lambda: called.append(1))
    assert net.call("github", lambda: "answered") == "answered"   # another service: called


def test_a_command_times_out_as_a_command(env):
    env.setenv(faults.FAULT_ENV, "net:timeout")
    with pytest.raises(subprocess.TimeoutExpired):
        net.run("docker", [sys.executable, "-c", "print(1)"], timeout=5)
    assert net.status()["docker"]["why"] == "timed out"


def test_refused_is_retried_then_opens_the_breaker(env, monkeypatch):
    slept = []
    monkeypatch.setattr(net, "_sleep", slept.append)
    env.setenv(faults.FAULT_ENV, "net:refused")
    with pytest.raises(ConnectionRefusedError):
        net.call("svc", lambda: "never")
    assert len(slept) == net.RETRIES and net.status()["svc"]["open"]


# --- the command line, end to end ---

def _brain(*args, **env):
    e = {**os.environ, "PYTHONPATH": SRC, **env}
    return subprocess.run([sys.executable, "-m", "brain", *args], capture_output=True, text=True, env=e,
                          timeout=120)


def test_the_cli_travels_in_time(env):
    r = _brain("quiet", "--for", "2h", BRAIN_NOW="2030-01-01T00:00:00Z")
    assert r.returncode == 0, r.stderr
    state = json.loads((paths.brain_home() / "notify" / quiet.STATE).read_text(encoding="utf-8"))
    assert state == {"since": "2030-01-01T00:00:00Z", "until": "2030-01-01T02:00:00Z"}
    r = _brain("quiet", BRAIN_NOW="2030-01-01T01:00:00Z")
    assert r.returncode == 0 and r.stdout.startswith("quiet until"), r.stdout + r.stderr
    r = _brain("quiet", BRAIN_NOW="2030-01-01T03:00:00Z")
    assert r.returncode == 0 and r.stdout.startswith("not quiet"), r.stdout + r.stderr


def test_the_cli_plays_a_full_disk_and_a_kill(env):
    f = paths.brain_home() / "notify" / quiet.STATE
    assert _brain("quiet", "--for", "2h", BRAIN_NOW="2030-01-01T00:00:00Z").returncode == 0
    before = f.read_bytes()
    r = _brain("quiet", "--for", "5h", BRAIN_FAULT="write@*/quiet.json:disk-full")
    assert r.returncode == 1 and "nothing changed" in r.stderr and "Traceback" not in r.stderr, r.stderr
    assert f.read_bytes() == before and not list(f.parent.glob("*.tmp"))
    r = _brain("quiet", "--for", "5h", BRAIN_FAULT="write@*/quiet.json:killed")
    assert r.returncode == faults.KILLED_EXIT and f.read_bytes() == before


@pytest.mark.parametrize("var, value", [("BRAIN_NOW", "yesterday"), ("BRAIN_FAULT", "disk:full")])
def test_the_cli_refuses_a_value_it_cannot_read(env, var, value):
    r = _brain("quiet", **{var: value})
    assert r.returncode == 2 and var in r.stderr and "Traceback" not in r.stderr
