"""The owner's gestures, declared once (wi-brain-owner-only-registry): every command or flag of the engine that only
the owner runs, in their own terminal, never an agent's session. The owner guard (brain.guards.check_owner) refuses
each to a session's tool call, the command line (brain.cli) refuses the ones it gates when an agent's session runs
them past the hook (a script, a wrapper the hook does not see), and tests/test_gestures.py checks both against this
list, and guard.sh's pre-filter, which must start Python for each.

A gesture is a subcommand path of ``brain`` (``usage allow``), with the flags that make it the owner's (``--apply``;
none: the subcommand itself) and the ones that make it a read again (``update --check``). A script (``install.ps1
-Apply``) is listed for the record: the owner guard matches its PowerShell parameter prefixes itself
(brain.guards.INSTALL_APPLY), and only when permissions.yaml declares its category.

Each gesture says where it is refused:

- ``guard``: ``always``, or ``strict`` (only under config.json ``guards.owner_strict: true``, off by default: a
  refusal this release adds to what passed before);
- ``cli``: ``own`` (the command refuses itself in an agent's session already: its own message and exit), ``gate``
  (brain.cli refuses it before it runs, under ``guards.owner_strict``), or ``none`` (a helper Claude Code itself
  runs: ``brain ipc otel-headers``, which the guard alone keeps from a session's tool calls).

An agent's session is one of :data:`AGENT_ENV` set (brain.vault's and brain.answers' markers). Standard library only:
the guard hook imports it on every refusal check.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

AGENT_ENV = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "BRAIN_AGENT_SESSION")
RUNNER = re.compile(r"^brain(?:\.(?:exe|cmd|bat|ps1))?$")   # the brain command, its Windows launchers
MODULES = ("brain", "brain.cli", "brain.__main__")           # python -m brain, -mbrain, -m brain.cli
VALUE_OPTS = ("--project", "--root", "--scope")              # brain's options before the subcommand that take a value
UNRESOLVED = re.compile(r"[$`%]")                            # a word the guard cannot resolve ($x, %x%, a backquote)


@dataclass(frozen=True)
class Gesture:
    words: tuple[str, ...]            # the subcommand path after brain
    category: str                     # the owner guard's check: a never-grantable category, else its own name
    why: str                          # what it does, in the refusal
    flags: tuple[str, ...] = ()       # any one of them makes it the owner's; none: the subcommand itself
    unless: tuple[str, ...] = ()      # a flag that makes it a read (update --check)
    program: str = "brain"            # brain, or a script the guard matches itself (install.ps1)
    loose: bool = False               # matched whatever runs it, its last word unresolved too ($x after ipc)
    guard: str = "always"             # always, or strict (guards.owner_strict)
    cli: str = "own"                  # own, gate (guards.owner_strict) or none

    @property
    def name(self) -> str:
        return " ".join((self.program, *self.words, *self.flags[:1]))


GESTURES: tuple[Gesture, ...] = (
    Gesture(("usage", "allow"), "override", "it lifts the usage guard (brain.governor) for every session",
            cli="gate"),
    Gesture(("handover", "root"), "override", "it marks a coordinators' chain root, which lets a session switch "
            "Remote Control", loose=True),
    Gesture(("schedule", "install"), "scheduled", "it creates, changes or removes scheduled tasks",
            flags=("--apply",), cli="gate"),
    Gesture(("ipc", "otel-headers"), "keys", "it prints the machine's token (Claude Code's otelHeadersHelper runs "
            "it)", loose=True, cli="none"),
    Gesture(("vault", "open"), "keys", "it decrypts a sealed store with a key"),
    Gesture(("vault", "drill"), "keys", "it opens the recovery key's canary with that key"),
    Gesture(("vault", "device", "init"), "keys", "it creates this machine's device key"),
    Gesture(("vault", "device", "forget-previous"), "keys", "it deletes the previous device key from the keystore"),
    Gesture(("vault", "reseal"), "keys", "it decrypts every sealed file with the device key to seal it again",
            flags=("--apply", "--identity"), guard="strict", cli="gate"),
    Gesture(("update",), "installer", "it installs a newer engine and moves the pin", unless=("--check",)),
    Gesture(("uninstall",), "installer", "it removes the brain from this machine", flags=("--apply",)),
    Gesture(("queue", "apply"), "actions", "it runs an action the owner queued as theirs"),
    Gesture((), "installer", "it writes the machine's settings, hooks and scheduled tasks", flags=("-Apply",),
            program="install.ps1", cli="none"),
)


def agent_session(env=None) -> str:
    """The variable that marks an agent's session ('' in the owner's own terminal)."""
    env = os.environ if env is None else env
    return next((v for v in AGENT_ENV if env.get(v)), "")


def runs_brain(low: list[str]) -> int:
    """The index of the word that runs brain in the simple command ``low`` (lower case): the brain command or a
    launcher of it, or the module after an interpreter's -m (``python -X utf8 -m brain``, ``-mbrain``, ``uv run
    brain``); -1 when it runs something else."""
    for i, w in enumerate(low[:8]):
        base = re.split(r"[\\/]", w)[-1]
        if RUNNER.match(base):
            return i
        if w.startswith("-m") and w[2:] in MODULES:
            return i
        if i and low[i - 1] == "-m" and w in MODULES:
            return i
    return -1


def _flag(word: str, flag: str) -> bool:
    """Whether ``word`` gives ``flag``: as written, with a value (--apply=x), or as argparse's unique prefix of it
    (--app); a PowerShell parameter (-Apply) by any prefix, in any case."""
    if flag.startswith("--"):
        return word == flag or word.startswith(flag + "=") or (len(word) > 3 and word.startswith("--")
                                                                and flag.startswith(word))
    w, f = word.lower().lstrip("-–—"), flag.lower().lstrip("-")
    return bool(w) and word[:1] in "-–—" and f.startswith(w.split(":")[0])


def _command(low: list[str], start: int) -> list[str]:
    """The words of ``low`` from its subcommand on: the options brain takes before it, and their values, skipped."""
    i = start
    while i < len(low) and low[i].startswith("-"):
        i += 2 if low[i] in VALUE_OPTS else 1
    return low[i:]


def _fits(g: Gesture, rest: list[str]) -> bool:
    if g.flags and not any(_flag(w, f) for w in rest for f in g.flags):
        return False
    return not (g.unless and any(_flag(w, f) for w in rest for f in g.unless))


def match(words: list[str]) -> Gesture | None:
    """The gesture the simple command ``words`` runs, else None. A brain gesture's words follow brain's own options
    (``brain --project x usage allow``); a loose one is found anywhere, whatever runs it, its last word unresolved
    too (``brain ipc $x``). ``--help`` is a read."""
    low = [w.lower() for w in words]
    if not low or "--help" in low[1:] or "-h" in low[1:]:
        return None
    at = runs_brain(low)
    cmd = _command(low, at + 1) if at >= 0 else []
    for g in GESTURES:
        n = len(g.words)
        if g.program == "brain" and ((cmd[:n] == list(g.words) and _fits(g, cmd[n:])) or
                                     (g.loose and _anywhere(g, low))):
            return g
    return None


def _anywhere(g: Gesture, low: list[str]) -> bool:
    """Whether a loose gesture's words are in ``low`` after its first word, its last one unresolved too."""
    n = len(g.words)
    for i in range(1, len(low) - n + 1):
        seg = low[i:i + n]
        if seg[:-1] == list(g.words[:-1]) and (seg[-1] == g.words[-1] or UNRESOLVED.search(seg[-1])) and \
                _fits(g, low[i + n:]):
            return True
    return False


def strict(data: dict | None = None) -> bool:
    """config.json's ``guards.owner_strict``: the gestures marked strict are refused too (off by default)."""
    if data is None:
        from . import config
        data = config.load().data   # an unreadable config.json loads as no data: strict stays off
    section = data.get("guards") if isinstance(data, dict) else None
    return isinstance(section, dict) and section.get("owner_strict") is True


def cli_refusal(argv: list[str], env=None, data: dict | None = None) -> str:
    """Why brain.cli refuses ``brain ARGV`` here ('' when it runs): a gesture the CLI gates, in an agent's session,
    under ``guards.owner_strict``."""
    g = match(["brain", *argv])
    if g is None or g.cli != "gate":
        return ""
    var = agent_session(env)
    if not var or not strict(data):
        return ""
    from . import config
    return (f"{g.name} is {config.name_of()}'s, in their own terminal: {g.why}; refused in an agent's session "
            f"({var} is set; config.json guards.owner_strict)")
