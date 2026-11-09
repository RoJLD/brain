"""No console window for a child of a brain that has no console (Windows).

A scheduled task runs the brain through ``pythonw.exe``, so that no console opens for it (brain.schedule). But a console
program started from a process with no console gets a console of its own: every ``git``, ``gh`` or ``docker`` of an
alerts pass then opens a window, in Windows Terminal where it is the default terminal, and takes the focus.
:func:`install`, called first by the command's ``main``, gives each child ``CREATE_NO_WINDOW`` in that case, in one
place, so that no call site can forget it. A brain run from a console keeps its children in that console, and a child
started with its own console or detached keeps what its caller asked for.
"""

from __future__ import annotations

import os
import subprocess
from typing import Callable

CREATE_NO_WINDOW = 0x08000000
OWN_CONSOLE = 0x00000010 | 0x00000008   # CREATE_NEW_CONSOLE, DETACHED_PROCESS: neither goes with CREATE_NO_WINDOW
FLAGS_AT = 13   # creationflags' index among Popen's positional parameters after self (args 0 ... startupinfo 12)


def has_console() -> bool:
    """Whether this process has a console window; True off Windows, where the question does not arise."""
    if os.name != "nt":
        return True
    import ctypes
    return bool(ctypes.windll.kernel32.GetConsoleWindow())


def flags(creationflags: int | None) -> int:
    """A child's creation flags once it is sure to open no window (None, a wrapper's default, is Popen's 0)."""
    creationflags = creationflags or 0
    return creationflags if creationflags & OWN_CONSOLE else creationflags | CREATE_NO_WINDOW


def install(console: Callable[[], bool] = has_console) -> bool:
    """Make every later subprocess of this process windowless, when it has no console; True when it did. Idempotent."""
    original = subprocess.Popen.__init__
    if getattr(original, "_brain_no_window", False) or console():
        return False

    def __init__(self, *args, **kwargs):
        if len(args) > FLAGS_AT:   # passed positionally: that one is the child's flags
            args = (*args[:FLAGS_AT], flags(args[FLAGS_AT]), *args[FLAGS_AT + 1:])
        else:
            kwargs["creationflags"] = flags(kwargs.get("creationflags", 0))
        original(self, *args, **kwargs)

    __init__._brain_no_window = True
    subprocess.Popen.__init__ = __init__
    return True
