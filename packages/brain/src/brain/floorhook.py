"""The locked guard's entry points (wi-brain-unadopted-floor, review round 7): what the managed settings' hooks and the
owner's elevated step run from the guard's system copy (brain.floor.guard_dir()), never from the user's profile.

guard_dir()/guard.py and guard_dir()/floor.py, written by brain floor lock --apply, put the copy's own folders first on
the path (``python -I``: no environment, no user site) and call :func:`hook` or :func:`cli`. Both take the guard's
selectors from the lock file, not from the environment a session sets: BRAIN_CONFIG is the config.json the lock holds,
BRAIN_HOME its <BRAIN_HOME>, and BRAIN_PYTHON, CLAUDE_PLUGIN_ROOT, CLAUDE_BRAIN_DIR and BRAIN_PERSONAL are dropped
(brain.guards.allowed drops BRAIN_GUARD_ALLOW's floor names wherever a lock exists).
"""

from __future__ import annotations

import os

DROPPED = ("BRAIN_PYTHON", "CLAUDE_PLUGIN_ROOT", "CLAUDE_BRAIN_DIR", "BRAIN_PERSONAL")


def pin(environ=None) -> None:
    """Set the guard's selectors from the lock file (module docstring); a missing or unreadable lock leaves BRAIN_CONFIG
    unset, and the guard then refuses every call (brain.floor.unlocked)."""
    from . import floor
    env = os.environ if environ is None else environ
    for name in (*DROPPED, "BRAIN_CONFIG"):
        env.pop(name, None)
    lock = floor.read_lock()
    if lock and not lock.get("error"):
        for name, key in (("BRAIN_CONFIG", "config"), ("BRAIN_HOME", "brain_home")):
            if isinstance(lock.get(key), str) and lock[key]:
                env[name] = lock[key]


def hook(argv: list[str]) -> int:
    """The PreToolUse hook (as the plugin's hooks/guard.py, from the locked copy)."""
    pin()
    from .guards import main
    try:
        from .selftime import hook as timed
    except ImportError:   # pragma: no cover - the copy carries the engine it was taken from
        return main()
    return timed(" ".join(["hook guard", *argv[:1], "[locked]"]), main)


def cli(argv: list[str]) -> int:
    """brain floor, run from the locked copy (the owner's elevated step: lock again, unlock, status)."""
    pin()
    from .cli import main
    return main(["floor", *argv])
