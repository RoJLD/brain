"""A brain with no console opens no window for its children (an alerts pass under pythonw.exe opened one per git)."""

from __future__ import annotations

import subprocess
import sys

import pytest

from brain import cli, nowindow

NEW_CONSOLE, DETACHED = 0x10, 0x08


@pytest.fixture
def seen(monkeypatch):
    """Popen's constructor replaced, so that nothing runs: the keyword arguments each child would have had."""
    calls = []

    def fake(self, *args, **kwargs):
        calls.append(kwargs)
    monkeypatch.setattr(subprocess.Popen, "__init__", fake)
    monkeypatch.setattr(subprocess.Popen, "__del__", lambda self: None)
    return calls


def test_a_child_of_a_brain_with_no_console_gets_no_window(seen):
    assert nowindow.install(console=lambda: False) is True
    subprocess.Popen(["git", "status"])
    subprocess.Popen(["git", "status"], creationflags=0x200)
    assert [c["creationflags"] for c in seen] == [nowindow.CREATE_NO_WINDOW, nowindow.CREATE_NO_WINDOW | 0x200]


def test_a_brain_in_a_console_leaves_its_children_there(seen):
    assert nowindow.install(console=lambda: True) is False
    subprocess.Popen(["git", "status"])
    assert seen == [{}]


@pytest.mark.parametrize("own", [NEW_CONSOLE, DETACHED])
def test_a_child_asked_with_its_own_console_or_detached_keeps_it(seen, own):
    nowindow.install(console=lambda: False)
    subprocess.Popen(["git", "status"], creationflags=own)
    assert seen[0]["creationflags"] == own


def test_creationflags_passed_positionally_or_as_none_still_get_no_window(seen, monkeypatch):
    """Popen's parameters after self: args (0) ... startupinfo (12), creationflags (13). The wrapper sees its own
    arguments, so a fake that records them replaces Popen first."""
    positional = []
    monkeypatch.setattr(subprocess.Popen, "__init__", lambda self, *a, **k: positional.append((a, k)))
    nowindow.install(console=lambda: False)
    thirteen = ["git"] + [None] * 12                       # up to startupinfo: creationflags not given
    subprocess.Popen(*thirteen)
    subprocess.Popen(*thirteen, 0x200)                     # creationflags given positionally
    subprocess.Popen(*thirteen, NEW_CONSOLE)               # its own console: kept
    subprocess.Popen(["git"], creationflags=None)          # a wrapper's default
    assert positional[0] == (tuple(thirteen), {"creationflags": nowindow.CREATE_NO_WINDOW})
    assert positional[1][0][13] == nowindow.CREATE_NO_WINDOW | 0x200 and positional[1][1] == {}
    assert positional[2][0][13] == NEW_CONSOLE
    assert positional[3][1] == {"creationflags": nowindow.CREATE_NO_WINDOW}


def test_popen_is_restored_after_each_test():
    """conftest undoes a wrap that cli.main left in a process with no console (a CI runner): no test sees another's."""
    assert not getattr(subprocess.Popen.__init__, "_brain_no_window", False)


def test_install_is_idempotent(seen):
    assert nowindow.install(console=lambda: False) is True
    assert nowindow.install(console=lambda: False) is False


def test_the_command_installs_it_first(monkeypatch):
    calls = []
    monkeypatch.setattr(nowindow, "install", lambda: calls.append("install"))
    monkeypatch.setattr(cli, "build_parser", lambda: calls.append("parser") or (_ for _ in ()).throw(SystemExit(0)))
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert calls == ["install", "parser"]


@pytest.mark.skipif(sys.platform != "win32", reason="a console is a Windows question here")
def test_this_flag_really_runs_a_child():
    assert nowindow.flags(0) == subprocess.CREATE_NO_WINDOW
    done = subprocess.run([sys.executable, "-c", "print('ok')"], capture_output=True, text=True,
                          creationflags=nowindow.flags(0))
    assert done.returncode == 0 and done.stdout.strip() == "ok"
