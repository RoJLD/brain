"""wi-brain-graceful-shutdown: a signal stops a command once its current write is whole, its locks released; the
cockpit and the scheduled alerts pass run one at a time per machine."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

import brain
from brain import cli, shutdown, stateio, timing
from brain.commands import alerts as alerts_cmd
from brain.commands import tui as tui_cmd

PLUGIN = Path(brain.__file__).resolve().parent / "adapters" / "claude"


def test_a_signal_outside_a_write_stops_at_once_and_the_way_out_runs():
    before = signal.getsignal(signal.SIGTERM)
    ran = []
    with pytest.raises(shutdown.Stopped) as exc:
        with shutdown.graceful():
            try:
                signal.raise_signal(signal.SIGTERM)
                time.sleep(0.2)
                ran.append("after")   # never: the handler raised
            finally:
                ran.append("finally")
    assert ran == ["finally"] and exc.value.signum == signal.SIGTERM and exc.value.exit_code == 128 + signal.SIGTERM
    assert exc.value.name == "SIGTERM" and isinstance(exc.value, KeyboardInterrupt)
    assert signal.getsignal(signal.SIGTERM) == before   # the handlers before are back


def test_a_signal_inside_a_write_waits_for_its_end():
    done = []
    with pytest.raises(shutdown.Stopped) as exc:
        with shutdown.graceful():
            with shutdown.critical():
                signal.raise_signal(signal.SIGINT)
                time.sleep(0.05)
                with shutdown.critical():   # nested: still held until the outer one ends
                    done.append("inner")
                done.append("outer")
            done.append("never")
    assert done == ["inner", "outer"] and exc.value.exit_code == 130


def test_a_signal_inside_a_write_that_raises_still_stops_the_command():
    """The write failed (a PermissionError a caller catches): the deferred signal is not lost."""
    with pytest.raises(shutdown.Stopped) as exc:
        with shutdown.graceful():
            try:
                with shutdown.critical():
                    signal.raise_signal(signal.SIGTERM)
                    raise PermissionError("the target is held")
            except OSError:
                pytest.fail("the stop was swallowed with the write's error")
    assert isinstance(exc.value.__context__, PermissionError) and not shutdown._pending


def test_the_text_cockpit_quits_on_ctrl_c_and_stops_on_sigterm(monkeypatch):
    from brain import cockpit

    class Cp:
        def refresh(self, probe):
            signal.raise_signal(self.sig)
            return False

    cp = Cp()
    with shutdown.graceful():
        cp.sig = signal.SIGINT
        assert cockpit.watch(cp, refresh_s=0.01) == 0
        cp.sig = signal.SIGTERM
        with pytest.raises(shutdown.Stopped):
            cockpit.watch(cp, refresh_s=0.01)


@pytest.mark.skipif(os.name == "nt", reason="POSIX: a signal sent to brain alone is passed to the command")
def test_brain_timed_passes_a_sigterm_to_its_command(brain_home, monkeypatch):
    sent = []

    class Proc:
        def __init__(self, *a, **kw):
            self.n = 0

        def wait(self, timeout=None):
            self.n += 1
            if self.n == 1:
                raise shutdown.Stopped(signal.SIGTERM)
            return 128 + signal.SIGTERM

        def send_signal(self, sig):
            sent.append(sig)

    monkeypatch.setattr(timing.subprocess, "Popen", Proc)
    assert timing._execute(["python", "-c", "pass"], False)[1] == "interrupted"
    assert sent == [signal.SIGTERM]


def test_critical_outside_graceful_only_counts():
    with shutdown.critical():
        pass
    assert shutdown._depth[0] == 0 and not shutdown._pending


def test_an_atomic_write_cut_by_a_signal_is_finished(tmp_path, monkeypatch):
    f = tmp_path / "state.json"
    f.write_text('{"old": 1}', encoding="utf-8")
    real = os.fsync

    def fsync(fd):
        signal.raise_signal(signal.SIGTERM)   # mid-write
        time.sleep(0.05)
        real(fd)

    monkeypatch.setattr(stateio.os, "fsync", fsync)
    with pytest.raises(shutdown.Stopped):
        with shutdown.graceful():
            stateio.write_atomic(f, '{"new": 2}')
    assert f.read_text(encoding="utf-8") == '{"new": 2}' and not list(tmp_path.glob("*.tmp"))


def test_a_ledger_line_cut_by_a_signal_is_whole(brain_home, monkeypatch):
    real = os.write
    cut = []

    def write(fd, data):
        if not cut:
            cut.append(1)
            signal.raise_signal(signal.SIGINT)
            time.sleep(0.05)
        return real(fd, data)

    monkeypatch.setattr(timing.os, "write", write)
    f = brain_home / "ledger" / "events-2026-11.jsonl"
    with pytest.raises(shutdown.Stopped):
        with shutdown.graceful():
            timing.append_lines(f, [{"id": "a"}, {"id": "b"}])
    assert f.read_text(encoding="utf-8") == '{"id":"a"}\n{"id":"b"}\n'


def test_cli_exits_128_plus_the_signal_and_says_so(brain_home, monkeypatch, capsys):
    def dispatch(args):
        signal.raise_signal(signal.SIGTERM)
        time.sleep(0.2)
        return 0

    monkeypatch.setattr(cli, "_dispatch", dispatch)
    assert cli.main(["status"]) == 128 + signal.SIGTERM
    assert "stopped by SIGTERM" in capsys.readouterr().err


CHILD = """
import sys, time
from pathlib import Path
from brain import cli
out = Path(sys.argv[1])

def dispatch(args):
    try:
        out.with_suffix(".ready").write_text("ready")
        for _ in range(600):   # short sleeps: on Windows only SIGINT wakes a sleep; another signal runs after it
            time.sleep(0.1)
    finally:
        out.write_text("cleaned up")
    return 0

cli._dispatch = dispatch
sys.argv = ["brain", "status"]   # a real run (argv None), as the brain command
sys.exit(cli.main())
"""


def _no_console() -> bool:
    if os.name != "nt":
        return False
    import ctypes
    return not ctypes.windll.kernel32.GetConsoleWindow()


@pytest.mark.skipif(_no_console(), reason="Ctrl+Break needs a console (a detached or scheduled run has none)")
def test_a_real_signal_from_outside_runs_the_way_out(brain_home, tmp_path):
    """Ctrl+Break on Windows (SIGBREAK, which ends a process at once by default), SIGTERM elsewhere."""
    script, out = tmp_path / "child.py", tmp_path / "out.txt"
    script.write_text(CHILD, encoding="utf-8")
    env = dict(os.environ, BRAIN_HOME=str(brain_home), PYTHONPATH=str(PLUGIN))
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    child = subprocess.Popen([sys.executable, str(script), str(out)], env=env, creationflags=flags,
                             stderr=subprocess.PIPE)
    deadline = time.monotonic() + 60
    while not out.with_suffix(".ready").exists() and child.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    sig = signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM
    try:
        os.kill(child.pid, sig)
        _, err = child.communicate(timeout=60)
    finally:
        if child.poll() is None:
            child.kill()
    # Windows: exit 128 + SIGBREAK; POSIX: a death by the signal itself (brain.shutdown.die), as a shell expects
    expected = 128 + signal.SIGBREAK if os.name == "nt" else -signal.SIGTERM
    assert child.returncode == expected, err
    assert out.read_text(encoding="utf-8") == "cleaned up"


HOLDER = """
import sys, time
from pathlib import Path
from brain import shutdown
ready = Path(sys.argv[2])
with shutdown.single_instance(sys.argv[1], "a holder"):
    ready.write_text("held")
    for _ in range(600):   # until the test lets it go (a venv's python.exe may be a launcher: killing it may leave
        if ready.with_suffix(".go").exists():   # the interpreter that holds the lock running)
            break
        time.sleep(0.1)
"""


@pytest.fixture
def held(brain_home, tmp_path):
    """A child process holding the lock ``name`` until the test ends."""
    procs = []

    def hold(name):
        script, ready = tmp_path / "holder.py", tmp_path / f"{name}.ready"
        script.write_text(HOLDER, encoding="utf-8")
        env = dict(os.environ, BRAIN_HOME=str(brain_home), PYTHONPATH=str(PLUGIN))
        p = subprocess.Popen([sys.executable, str(script), name, str(ready)], env=env)
        procs.append(p)
        deadline = time.monotonic() + 60
        while not ready.exists() and p.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists()
        return p

    yield hold
    for f in tmp_path.glob("*.ready"):
        f.with_suffix(".go").write_text("go")
    for p in procs:
        p.wait(timeout=60)


def test_single_instance_refuses_a_second_holder_and_frees_on_exit(held, tmp_path):
    p = held("cockpit")
    with pytest.raises(shutdown.Busy) as exc:
        with shutdown.single_instance("cockpit"):
            pass
    # the holder's pid (a venv's python.exe may be a launcher whose child holds it: not compared with p.pid)
    assert "another a holder runs on this machine (pid " in str(exc.value)
    assert shutdown.holder("cockpit")["pid"] != os.getpid()
    (tmp_path / "cockpit.go").write_text("go")
    assert p.wait(timeout=60) == 0
    with shutdown.single_instance("cockpit", "brain tui"):   # the holder's exit dropped its lock
        assert shutdown.holder("cockpit")["pid"] == os.getpid()
    with shutdown.single_instance("cockpit"):   # released at the block's end, taken again
        pass


def test_a_second_scheduled_alerts_pass_is_skipped(held, monkeypatch, capsys):
    held("alerts-pass")
    monkeypatch.setattr(alerts_cmd, "_scope", lambda args, root: [])
    monkeypatch.setattr(alerts_cmd, "_report", lambda *a: pytest.fail("the pass ran beside another"))
    args = type("A", (), {"alerts_cmd": None, "dry_run": False, "notify": True})()
    assert alerts_cmd.cmd_alerts(args, Path(".")) == 0
    assert "this pass is skipped" in capsys.readouterr().err


def test_a_second_interactive_cockpit_is_refused(held, monkeypatch, capsys):
    held("cockpit")
    monkeypatch.setattr(tui_cmd, "_interactive", lambda *a: pytest.fail("a second cockpit started"))
    monkeypatch.setattr(tui_cmd, "_projects", lambda args, root: [])

    class Cockpit:
        scope, choices = "demo", []

        def __init__(self, *a, **kw):
            pass

    monkeypatch.setattr(tui_cmd.cockpit, "Cockpit", Cockpit)
    args = cli.build_parser().parse_args(["tui", "--plain"])
    assert tui_cmd.cmd_tui(args, Path(".")) == 1
    assert "another a holder runs" in capsys.readouterr().err
