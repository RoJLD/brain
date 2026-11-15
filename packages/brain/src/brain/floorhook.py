"""The locked guard's entry points (wi-brain-unadopted-floor, review rounds 7-8): what the managed settings' hooks and
the owner's elevated step run from the guard's system copy (brain.floor.guard_dir()), never from the user's profile.

<copy>/hook.py and <copy>/floor.py, written by brain floor lock --apply, put the copy's own folders first on the path
(``python -I``: no environment, no user site) and call :func:`hook` or :func:`cli`. Both take the guard's selectors
from the lock file, not from the environment a session sets: BRAIN_CONFIG is the config.json the lock holds, BRAIN_HOME
its <BRAIN_HOME>, BRAIN_PYTHON, CLAUDE_PLUGIN_ROOT, CLAUDE_BRAIN_DIR and BRAIN_PERSONAL are dropped, and
NoDefaultCurrentDirectoryInExePath is set (a program is never taken from the working directory; brain.guards.allowed
drops BRAIN_GUARD_ALLOW's floor names wherever a lock exists).

Round 8: the managed settings set allowManagedHooksOnly, which blocks the plugin's hooks, so the lock re-declares the
plugin's PreToolUse hooks here (:data:`HOOKS`: the guard, the governor, the read and wait hints), each in exec form;
the judging ones (the guard, the governor) carry a deadline (``--deadline=S``, well under their hook's timeout) past
which they refuse the call, so that a slow argument (a network path, a long command) cannot outrun the hook.
"""

from __future__ import annotations

import importlib
import os
import sys
import threading

DROPPED = ("BRAIN_PYTHON", "CLAUDE_PLUGIN_ROOT", "CLAUDE_BRAIN_DIR", "BRAIN_PERSONAL")
# name: (module, entry, whether the entry takes the arguments left)
HOOKS = {"guard": ("brain.guards", "main", False), "governor": ("brain.governor", "main", False),
         "readhint": ("brain.readhint", "hook_main", True), "waithint": ("brain.waithint", "hook_main", True)}


def pin(environ=None) -> None:
    """Set the guard's selectors from the lock file (module docstring); a missing or unreadable lock leaves BRAIN_CONFIG
    unset, and the guard then refuses every call (brain.floor.unlocked)."""
    from . import floor
    env = os.environ if environ is None else environ
    for name in (*DROPPED, "BRAIN_CONFIG"):
        env.pop(name, None)
    env["NoDefaultCurrentDirectoryInExePath"] = "1"
    lock = floor.read_lock()
    if lock and not lock.get("error"):
        for name, key in (("BRAIN_CONFIG", "config"), ("BRAIN_HOME", "brain_home")):
            if isinstance(lock.get(key), str) and lock[key]:
                env[name] = lock[key]


def refuse_after(seconds: float, what: str, exit=os._exit) -> threading.Timer:
    """A timer that refuses the call (exit code 2, the reason on stderr: Claude Code blocks it) when the hook has not
    answered within ``seconds``; started, daemon, cancelled by the caller when it answers."""
    def expire() -> None:
        sys.stderr.write(f"brain guard: {what} refused: the guard did not decide within {seconds:g} s (a network path "
                         "or a very long command); split the call or name local paths\n")
        sys.stderr.flush()
        exit(2)
    timer = threading.Timer(seconds, expire)
    timer.daemon = True
    timer.start()
    return timer


def hook(argv: list[str]) -> int:
    """A PreToolUse hook from the locked copy: ``[--deadline=S] <name> [args]`` (:data:`HOOKS`; shell, edit and tool
    are the guard's kinds, as the plugin's guard.py takes them). An unknown name refuses."""
    pin()
    deadline = 0.0
    if argv and argv[0].startswith("--deadline="):
        deadline, argv = float(argv[0].split("=", 1)[1]), argv[1:]
    name, rest = (argv[0], argv[1:]) if argv else ("", [])
    if name in ("shell", "edit", "tool"):
        name, rest = "guard", [name, *rest]
    if name not in HOOKS:
        sys.stderr.write(f"brain guard: the locked hook {name or '(none)'} is unknown: refused\n")
        return 2
    module, entry, takes = HOOKS[name]
    fn = getattr(importlib.import_module(module), entry)
    timer = refuse_after(deadline, name) if deadline > 0 else None
    try:
        call = (lambda: fn(rest)) if takes else fn
        try:
            from .selftime import hook as timed
        except ImportError:   # pragma: no cover - the copy carries the engine it was taken from
            return call()
        return timed(" ".join([f"hook {name}", *rest[:1], "[locked]"]), call)
    finally:
        if timer:
            timer.cancel()


def cli(argv: list[str]) -> int:
    """brain floor, run from the locked copy (the owner's elevated step: lock again, unlock, status)."""
    pin()
    from .cli import main
    return main(["floor", *argv])
