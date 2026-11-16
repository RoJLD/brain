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
VALUE_OPTS = ("--root", "--project", "--store")              # brain's options before the subcommand that take a value
LAUNCHERS = ("uv", "uvx", "poetry", "pipx", "pdm", "hatch", "rye")  # ... run brain
UNRESOLVED = re.compile(r"[$`%]")                            # a word the guard cannot resolve ($x, %x%, a backquote)
SPLAT = re.compile(r"@(?:[a-z_]\w*)?", re.I)   # PowerShell's splat (@args), or an array literal @(...) whose words the
                                               # guard's reader splits off: any words
PYTHON = re.compile(r"^(?:python[0-9.]*w?|pythonw|py|pypy[0-9.]*)(?:\.exe)?$")   # whose -c runs brain's modules


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
    Gesture(("vault", "open"), "keys", "it decrypts a sealed store with a key", guard="strict"),
    Gesture(("vault", "drill"), "keys", "it opens the recovery key's canary with that key", guard="strict"),
    Gesture(("vault", "device", "init"), "keys", "it creates this machine's device key", guard="strict"),
    Gesture(("vault", "device", "forget-previous"), "keys", "it deletes the previous device key from the keystore",
            guard="strict"),
    Gesture(("vault", "reseal"), "keys", "it decrypts every sealed file with the device key to seal it again",
            flags=("--apply", "--identity"), guard="strict", cli="gate"),
    Gesture(("update",), "installer", "it installs a newer engine and moves the pin", unless=("--check",),
            guard="strict"),
    Gesture(("uninstall",), "installer", "it removes the brain from this machine", flags=("--apply",),
            guard="strict"),
    Gesture(("queue", "apply"), "actions", "it runs an action the owner queued as theirs", guard="strict"),
    Gesture((), "installer", "it writes the machine's settings, hooks and scheduled tasks", flags=("-Apply",),
            program="install.ps1", cli="none"),
)


def agent_session(env=None) -> str:
    """The variable that marks an agent's session ('' in the owner's own terminal)."""
    env = os.environ if env is None else env
    return next((v for v in AGENT_ENV if env.get(v)), "")


def runs_brain(low: list[str]) -> int:
    """The index of the word that runs brain in the simple command ``low`` (lower case): the brain command or a
    launcher of it as the program, the module after an interpreter's -m (``python -X utf8 -m brain``, ``-mbrain``,
    ``-Imbrain``, ``-Im brain``), or the word after a launcher's run (``uv run brain``); -1 when it runs something
    else (``echo brain update``, ``cp -r brain x`` name it, never run it)."""
    if not low:
        return -1
    if RUNNER.match(re.split(r"[\\/]",low[0])[-1]):
        return 0
    prog = re.split(r"[\\/]",low[0])[-1].removesuffix(".exe")
    for i, w in enumerate(low[1:8], 1):
        if re.fullmatch(r"-[a-z]*m", low[i - 1]) and w in MODULES:
            return i
        m = re.fullmatch(r"-[a-z]*m(\S+)", w)
        if m and m[1] in MODULES:
            return i
        if RUNNER.match(re.split(r"[\\/]",w)[-1]) and (prog in LAUNCHERS and (low[i - 1] in ("run", "tool")
                                                                              or prog == "uvx")):
            return i
    return -1


def _flag(word: str, flag: str) -> bool:
    """Whether ``word`` gives ``flag``: as written, with a value (--apply=x), or as argparse's prefix of it (--a,
    --app=x: from three characters); a PowerShell parameter (-Apply) by any prefix, in any case."""
    if flag.startswith("--"):
        opt = word.split("=", 1)[0]
        return opt == flag or (len(opt) >= 3 and opt.startswith("--") and flag.startswith(opt))
    w, f = word.lower().lstrip("-–—"), flag.lower().lstrip("-")
    return bool(w) and word[:1] in "-–—" and f.startswith(w.split(":")[0])


def _value_opt(word: str) -> bool:
    """Whether ``word`` is one of brain's options before the subcommand that takes the next word as its value,
    spelled out or as argparse's prefix of it (--proj, --ro, --st)."""
    return any(_flag(word, o) for o in VALUE_OPTS) and "=" not in word


def _command(low: list[str], start: int) -> list[str]:
    """The words of ``low`` from its subcommand on: the options brain takes before it, and their values, skipped."""
    i = start
    while i < len(low) and low[i].startswith("-"):
        i += 2 if _value_opt(low[i]) else 1
    return low[i:]


def _unknown(word: str, wide: bool = True) -> bool:
    """Whether the guard cannot tell what ``word`` holds, under ``wide``: a variable, a command substitution, a
    backquote, a %VAR%, PowerShell's splat of a variable (``@args``) or array (``@('--apply')``, read as ``@``): it may
    be any word, a gesture's included."""
    return wide and bool(UNRESOLVED.search(word) or SPLAT.fullmatch(word))


def _fits(g: Gesture, rest: list[str], wide: bool = False) -> bool:
    """Whether ``rest`` (the words after a gesture's) gives one of its flags (under ``wide``, a word the guard cannot
    resolve counting as one: ``schedule install $f``) and none of the flags that make it a read."""
    if g.flags and not any(_flag(w, f) or _unknown(w, wide) for w in rest for f in g.flags):
        return False
    return not (g.unless and any(_flag(w, f) for w in rest for f in g.unless))


def _value(cmd: list[str], i: int, wide: bool) -> bool:
    """Whether ``cmd[i]`` is an option's value (the word after an option without =)."""
    return i > 0 and cmd[i - 1].startswith("-") and "=" not in cmd[i - 1] and not _unknown(cmd[i - 1], wide)


def _words_at(g: Gesture, cmd: list[str], wide: bool = False) -> int:
    """Where a gesture's words end in ``cmd`` (its subcommand first), options and their values allowed between them
    (``usage --hours 2 allow``, ``queue --kind action apply``), a positional word not (``queue add ... apply``); under
    ``wide``, a word the guard cannot resolve stands for any of them (``schedule $(echo install)``), but an option's
    value; -1 when they are not there."""
    if not g.words or not cmd or not (cmd[0] == g.words[0] or _unknown(cmd[0], wide)):
        return -1
    i = 1
    for word in g.words[1:]:
        while i < len(cmd) and not (cmd[i] == word or (_unknown(cmd[i], wide) and not _value(cmd, i, wide))):
            if not (cmd[i].startswith("-") or _value(cmd, i, wide)):
                return -1
            i += 1
        if i >= len(cmd):
            return -1
        i += 1
    return i


def _starts(cmd: list[str], wide: bool) -> list[list[str]]:
    """``cmd``, and under ``wide`` ``cmd`` from each later word that may be the subcommand: past leading words the
    guard cannot resolve (``brain $opts schedule install --apply``: $opts may be options)."""
    out = [cmd]
    i = 0
    while wide and i < len(cmd) - 1 and _unknown(cmd[i]):
        i += 1
        out.append(cmd[i:])
    return out


def _code(low: list[str]) -> str:
    """Python's inline code in the simple command ``low`` (``python -c CODE``, ``python -Ic CODE``), else ''."""
    if not PYTHON.match(re.split(r"[\\/]", low[0])[-1]):
        return ""
    for i, w in enumerate(low[1:], 1):
        m = re.fullmatch(r"-[a-z]*c(.*)", w, re.S)
        if m:
            return m.group(1) or (low[i + 1] if i + 1 < len(low) else "")
        if not w.startswith("-"):
            return ""   # a script or a module: not inline code
    return ""


def _inline(low: list[str]) -> Gesture | None:
    """The gesture Python's inline code runs through brain's own modules: the code names brain and, as words, each of
    the gesture's words and one of its flags (``main(['schedule', 'install', '--apply'])``,
    ``schedule.install(reg, apply=True)``), none of its read flags; underscores read as hyphens (otel_headers)."""
    code = _code(low)
    if not code or not re.search(r"(?<![\w.])brain\b", code):
        return None
    tokens = set(re.findall(r"[a-z][a-z0-9-]*", code.replace("_", "-")))
    for g in GESTURES:
        if g.program != "brain" or not g.words or not set(g.words) <= tokens:
            continue
        if g.flags and not any(f.lstrip("-").lower() in tokens for f in g.flags):
            continue
        if any(f.lstrip("-").lower() in tokens for f in g.unless):
            continue
        return g
    return None


def _help(low: list[str]) -> bool:
    """Whether brain is asked for its help (--help or -h before any --): a read."""
    words = low[1:low.index("--")] if "--" in low else low[1:]
    return "--help" in words or "-h" in words


def match(words: list[str], wide: bool | None = None) -> Gesture | None:
    """The gesture the simple command ``words`` runs, else None. A brain gesture's words follow brain's own options
    (``brain --project x usage allow``, their prefixes too), options allowed between them; a loose one is found
    anywhere, whatever runs it, its last word unresolved too (``brain ipc $x``), even with --help. ``--help`` or
    ``-h`` before any ``--`` makes any other one a read. ``wide`` (None: config.json ``guards.gestures_wide``, read
    only when the call has a word the guard cannot resolve or Python's inline code): a word the guard cannot resolve
    may be any of a gesture's words or flags, and Python's inline code that drives brain's modules counts (_inline)."""
    low = [w.lower() for w in words]
    if not low:
        return None
    at = runs_brain(low)
    cmd = _command(low, at + 1) if at >= 0 else []
    helped = _help(low)
    found = _find(low, cmd, at, helped, False)
    if found or wide is False:
        return found
    if wide is None:
        if not (any(_unknown(w) for w in low) or _code(low)):
            return None
        wide = wide_matching()
    if not wide:
        return None
    if at < 0 and _unknown(low[0]):   # & $exe schedule install --apply: the program may be brain
        at, cmd = 0, _command(low, 1)
    return _find(low, cmd, at, helped, True) or _inline(low)


def _find(low: list[str], cmd: list[str], at: int, helped: bool, wide: bool) -> Gesture | None:
    for g in GESTURES:
        if g.program != "brain":
            continue
        if g.loose and _anywhere(g, low):
            return g
        for start in ([] if helped or at < 0 else _starts(cmd, wide)):
            end = _words_at(g, start, wide)
            if end >= 0 and _fits(g, start[end:], wide):
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


def wide_matching(data: dict | None = None) -> bool:
    """config.json's ``guards.gestures_wide``: a gesture is matched through words the guard cannot resolve and
    Python's inline code too (off by default: refusals 0.5.2 adds; the MCP server matches wide always)."""
    if data is None:
        from . import config
        data = config.load().data
    section = data.get("guards") if isinstance(data, dict) else None
    return isinstance(section, dict) and section.get("gestures_wide") is True


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
