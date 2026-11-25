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

An agent's session is one of :data:`AGENT_ENV` set (brain.vault's and brain.answers' markers), or under config.json
``guards.gestures_session_markers: true`` (off by default) one of :data:`MARKER_NAMES`. Standard library only:
the guard hook imports it on every refusal check.

The automation catalogue (:data:`CATALOGUE`, wi-brain-automation-catalogue) lists every recurring owner gesture, the
ones a session runs too (the engine clone's pull, a session's archive, Remote Control at a hand-over, the merge go, a
workflow's launch), each with its stable id, its ceiling (manual, ask or auto: the highest level the engine allows),
its default (its level today), its conditions, where it runs and its floor category (AUTO-1: :data:`FLOOR`); a level
above the ceiling, unknown or unreadable, and any level of a floor gesture, reads manual (:func:`effective`).
brain.automation resolves each gesture's level from its default, config.json's ``automation`` section and the machine
file that may only lower (wi-brain-automation-config); the guards read it (wi-brain-automation-guard:
brain.automation.enforce, the guard hook on archive_session and set_remote_control, brain.engineclone.refresh;
``brain automation list`` and ``explain`` print them; docs/automation.md « Enforcement »).
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
PYTHON = re.compile(r"^(?:python[0-9.]*[tw]?(?:-dbg)?|pythonw|py|pypy[0-9.]*)(?:\.exe)?$")   # whose -c runs brain's modules


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
    Gesture(("release", "tag"), "release", "it signs a release tag with the owner's key and pushes it"),
    Gesture(("release", "apply"), "release", "it runs the brain's installer with -Apply: the machine's settings, "
            "hooks and engine"),
    Gesture((), "installer", "it writes the machine's settings, hooks and scheduled tasks", flags=("-Apply",),
            program="install.ps1", cli="none"),
)


# The automation catalogue (wi-brain-automation-catalogue, spec-brain-automation-levels S1): every recurring owner
# gesture, the ones a session runs as well as the owner-only commands above, with the highest level the engine allows
# it (its ceiling), its level today (the engine's default), its conditions, where it runs and its floor category
# (AUTO-1). The ids are a public contract: config.json's automation section keys its levels by them
# (wi-brain-automation-config), so an id is never renamed or reused; one that leaves the catalogue goes to RETIRED.
CATALOGUE_V = 1
LEVELS = ("manual", "ask", "auto")   # in order: a level above another confirms less
RUNS = {
    "session": "an agent's session",
    "terminal": "the owner's terminal",
    "elevated": "the owner's elevated terminal",
    "harness": "Claude Code's own confirmation (the app)",
}
# The owner's never-grantable categories (brain.permissions.NEVER, its first words; tests/test_gestures.py checks the
# copy), then the three the floor adds (AUTO-1): the owner's elevated terminal, the rules' text, raising a level.
NEVER_GRANTABLE = ("keys", "money", "arming", "visibility", "accounts", "scheduled", "legal", "security-settings")
FLOOR = (*NEVER_GRANTABLE, "elevated", "rules", "raise")
RETIRED: tuple[str, ...] = ()   # ids that left the catalogue, never reused


@dataclass(frozen=True)
class Automation:
    id: str                            # the stable key (config.json automation.levels)
    label: str                         # what it is, for a reader: may change, the id does not
    runs: str                          # where it runs: a key of RUNS
    ceiling: str                       # the highest level the engine allows, whatever the config says
    default: str                       # its level today, the engine's default: a new engine never raises it
    conditions: tuple[str, ...] = ()   # what must hold at any level: a level changes who confirms, never these
    floor: str = ""                    # its floor category (a FLOOR name), '' when none: its ceiling is manual
    commands: tuple[str, ...] = ()     # the owner's gestures above it covers (Gesture.name), or the commands it runs
    note: str = ""                     # why its ceiling is what it is


CATALOGUE: tuple[Automation, ...] = (
    # What a session runs, under the guard's conditions (spec § 1, G3 to G7)
    Automation("engine-clone-pull", "pull the engine's clone", "session", "auto", "auto",
               ("fast-forward only (git merge --ff-only), never a switch, a reset or a stash",
                "on its remote's default branch, no tracked change, no merge, rebase, cherry-pick or revert in "
                "progress, no file the remote brings that it ignores"),
               commands=("brain refresh",),
               note="brain refresh fast-forwards it since 0.6.1 (engine.clone; --no-clone skips it once); brain "
                    "release apply (release-apply's gesture) does too, after an install"),
    Automation("session-archive", "archive a finished session", "session", "auto", "ask",
               ("Remote Control off first, under the guard's archive case (wi-brain-guard-rc-archive): a session "
                "the caller started, its turn finished, or the caller's predecessor at a hand-over",
                "its PRs merged and its worktree clean (the definition of done), none of its children blocking"),
               note="brain.guards.archive checks the family, the turn, the children, the PRs and the folder (the "
                    "Remote Control off is set_remote_control's own case, and the app refuses an archive while it is "
                    "on): inside them its level decides (brain.automation.enforce: ask the guard's card, whatever "
                    "an owner's allow rule; auto no card; manual refused), outside them or on an error the guard "
                    "asks; the engine's default stays ask"),
    Automation("handover-remote-control", "Remote Control at a coordinators' hand-over", "session", "auto", "ask",
               ("on for the coordinator the caller started to succeed it, live or starting, detached",
                "off on the caller itself once its hand-over note is written and its successor detached"),
               note="outside a hand-over Remote Control is the floor's (remote-control)"),
    Automation("merge-go", "merge a PR on the owner's word", "harness", "ask", "ask",
               ("the owner's words in the session that merges; a relayed go is refused",),
               note="the harness's: its auto-mode classifier asks, the Brain cannot raise it"),
    Automation("workflow-launch", "launch a workflow of agents", "harness", "ask", "ask",
               ("the owner's explicit opt-in, in the session that launches it",),
               note="the harness's: the Workflow tool's opt-in, the Brain cannot raise it"),
    # What the owner's terminal runs (G1, G2, G8 and the other owner-only commands)
    Automation("release-tag", "sign and push a release tag", "terminal", "ask", "ask",
               ("on main, pulled fast-forward, HEAD the version PR's merge commit, the public stamp valid",
                "the owner's key: their passphrase where the key asks"),
               commands=("brain release tag",), note="its plan, then one y"),
    Automation("release-apply", "install a release (the installer's -Apply)", "terminal", "ask", "ask",
               ("the pin PR merged and pulled", "the installer's plan shown first"),
               commands=("brain release apply",),
               note="auto would be an unattended patch install (wi-brain-engine-auto-update), not declared yet"),
    Automation("installer-apply", "apply the installer by hand", "terminal", "ask", "manual",
               ("its plan read first (install.ps1 without -Apply)",),
               commands=("install.ps1 -Apply",), note="brain release apply runs it as one gesture"),
    Automation("engine-update", "install a newer engine and move the pin", "terminal", "ask", "ask",
               ("its plan, then one y",), commands=("brain update",)),
    Automation("usage-allow", "lift the usage guard (governor override)", "terminal", "ask", "manual",
               ("for a bounded time (--hours)",), commands=("brain usage allow",)),
    Automation("queue-apply", "run an action the owner queued", "terminal", "ask", "ask",
               ("the action's exact command, shown, confirmed by the owner",), commands=("brain queue apply",)),
    Automation("uninstall", "remove the brain from this machine", "terminal", "manual", "manual",
               commands=("brain uninstall --apply",), note="not recurring: always typed"),
    # The floor (AUTO-1): shown locked, refused above manual whatever config.json says
    Automation("handover-root", "mark a coordinators' chain root", "terminal", "manual", "manual",
               floor="security-settings", commands=("brain handover root",),
               note="it lets a session switch Remote Control, so the catalogue locks it as security-settings; the "
                    "owner guard's category for it is override (a lift by BRAIN_GUARD_ALLOW still passes it)"),
    Automation("remote-control", "Remote Control outside a hand-over", "harness", "manual", "manual",
               floor="security-settings"),
    Automation("permission-mode", "a session's permission mode", "harness", "manual", "manual",
               floor="security-settings"),
    Automation("schedule-install", "create, change or remove scheduled tasks", "terminal", "manual", "manual",
               floor="scheduled", commands=("brain schedule install --apply",)),
    Automation("otel-headers", "print the machine's token for Claude Code's telemetry", "harness", "manual",
               "manual", floor="keys", commands=("brain ipc otel-headers",),
               note="Claude Code's otelHeadersHelper runs it, never a session"),
    Automation("vault-open", "decrypt a sealed store", "terminal", "manual", "manual", floor="keys",
               commands=("brain vault open",)),
    Automation("vault-drill", "open the recovery key's canary", "terminal", "manual", "manual", floor="keys",
               commands=("brain vault drill",)),
    Automation("vault-device-init", "create this machine's device key", "terminal", "manual", "manual",
               floor="keys", commands=("brain vault device init",)),
    Automation("vault-device-forget-previous", "delete the previous device key", "terminal", "manual", "manual",
               floor="keys", commands=("brain vault device forget-previous",)),
    Automation("vault-reseal", "seal every sealed file again", "terminal", "manual", "manual", floor="keys",
               commands=("brain vault reseal --apply",)),
    Automation("elevated", "a gesture of the owner's elevated terminal (ACLs, takeown, the locked floor)",
               "elevated", "manual", "manual", floor="elevated",
               commands=("brain floor lock --apply", "brain floor unlock --apply")),
    Automation("rules-text", "change the rules' text (global and project rules)", "terminal", "manual", "manual",
               floor="rules", note="a session proposes, the owner merges"),
    Automation("automation-raise", "raise an automation level", "terminal", "manual", "manual", floor="raise",
               note="the owner's merge of config.json is the raise; lowering a level is anyone's"),
    Automation("money", "anything touching money", "terminal", "manual", "manual", floor="money"),
    Automation("arming", "arm a live system (live orders)", "terminal", "manual", "manual", floor="arming"),
    Automation("visibility", "a repository's visibility", "terminal", "manual", "manual", floor="visibility"),
    Automation("accounts", "create or change an account", "terminal", "manual", "manual", floor="accounts"),
    Automation("legal", "accept terms, a licence, a legal act", "terminal", "manual", "manual", floor="legal"),
)


def automation(gesture_id: str) -> Automation | None:
    """The catalogue's gesture ``gesture_id``, None when it has none (an unknown id: config.json's automation section
    ignores it with a note, brain.automation, so that an older engine reads a newer config)."""
    return next((a for a in CATALOGUE if a.id == gesture_id), None)


def effective(a: Automation | None, level) -> str:
    """The level ``a`` runs at when ``level`` is asked (AUTO-1, fail closed): ``manual`` for an unknown gesture, a
    level that is not one of :data:`LEVELS` (unknown or unreadable), one above the gesture's ceiling, and any level of a
    floor gesture; else ``level``. ``a`` is an :class:`Automation` (:func:`automation`'s); anything else (an id, None)
    reads manual too."""
    if not isinstance(a, Automation) or a.floor or level not in LEVELS:
        return "manual"
    if LEVELS.index(level) > LEVELS.index(a.ceiling):
        return "manual"
    return level


def catalogue() -> dict:
    """The catalogue as data: its version, the levels, where a gesture runs, the floor's categories, the retired ids
    and each gesture with its level at the engine's default (source ``default``) and whether it is locked.
    ``brain automation list --json`` prints brain.automation.catalogue, this with each level resolved."""
    return {"v": CATALOGUE_V, "levels": list(LEVELS), "runs": dict(RUNS), "floor": list(FLOOR),
            "retired": list(RETIRED),
            "gestures": [{"id": a.id, "label": a.label, "level": effective(a, a.default), "source": "default",
                          "ceiling": a.ceiling, "runs": a.runs, "floor": a.floor or None, "locked": bool(a.floor),
                          "conditions": list(a.conditions), "commands": list(a.commands), "note": a.note}
                         for a in CATALOGUE]}


def agent_session(env=None, data: dict | None = None) -> str:
    """The variable that marks an agent's session ('' in the owner's own terminal): one of :data:`AGENT_ENV`; under
    config.json ``guards.gestures_session_markers`` (:func:`session_markers`, off by default), one of
    :data:`MARKER_NAMES`, the variables Claude Code sets for each session (its id, its host's, its child flag, its
    executable, its messaging socket, its process) besides :data:`AGENT_ENV`; never a configuration variable an owner
    may export in their own terminal (``CLAUDE_CODE_USE_BEDROCK``, the IDE's ``CLAUDE_CODE_SSE_PORT``)."""
    env = os.environ if env is None else env
    names = MARKER_NAMES if session_markers(data) else AGENT_ENV
    return next((v for v in names if env.get(v)), "")


def lock_marker(env=None, data: dict | None = None, present: bool = False) -> str:
    """The marker the acting gestures' own lock reads (brain.detail.refused: schedule install --apply, update,
    uninstall --apply, queue apply, tidy's remote apply, the cockpit's actions; brain.succession: handover root), ''
    when there is none: ``CLAUDECODE`` alone, set and not empty (``present``: set, even empty), as 0.5.1 read it;
    under config.json ``guards.gestures_session_markers``, any of :data:`MARKER_NAMES` (:func:`agent_session`), so
    that clearing one is not enough."""
    env = os.environ if env is None else env
    if session_markers(data):
        var = agent_session(env, data)
        return var or ("CLAUDECODE" if present and "CLAUDECODE" in env else "")
    return "CLAUDECODE" if ("CLAUDECODE" in env if present else env.get("CLAUDECODE")) else ""


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


HOLDS = -2   # _words_at: a word the guard cannot resolve may hold the gesture's remaining words and its flag


def _words_at(g: Gesture, cmd: list[str], wide: bool = False) -> int:
    """Where a gesture's words end in ``cmd`` (its subcommand first), options and their values allowed between them
    (``usage --hours 2 allow``, ``queue --kind action apply``), a positional word not (``queue add ... apply``); -1
    when they are not there. Under ``wide``, :data:`HOLDS` when a word the guard cannot resolve stands where the
    gesture's next word would (``schedule $x``, ``$x``, ``schedule @rest``): it may split into the remaining words and
    the flag; an option's value is no such word."""
    if not g.words or not cmd:
        return -1
    if _unknown(cmd[0], wide):
        return HOLDS
    if cmd[0] != g.words[0]:
        return -1
    i = 1
    for word in g.words[1:]:
        while i < len(cmd) and cmd[i] != word:
            if _unknown(cmd[i], wide) and not _value(cmd, i, wide):
                return HOLDS
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
    """Python's inline code in the simple command ``low`` (``python -c CODE``, ``python -X utf8 -Ic CODE``, ``$PY -c
    CODE``), with the arguments it gets after it (its sys.argv), else ''."""
    if not (PYTHON.match(re.split(r"[\\/]", low[0])[-1]) or _unknown(low[0])):
        return ""
    skip = False
    for i, w in enumerate(low[1:], 1):
        if skip:
            skip = False
            continue
        if w[:2] in ("-x", "-w"):   # -X utf8, -W ignore: an option with its value (or -Xutf8)
            skip = len(w) == 2
            continue
        m = re.fullmatch(r"-[a-z]*c(.*)", w, re.S)
        if m:
            code = m.group(1) or (low[i + 1] if i + 1 < len(low) else "")
            return " ".join([code, *low[i + (1 if m.group(1) else 2):]])
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
    """The gesture ``cmd`` runs: one its words spell out first, else (under ``wide``) the first one a word the guard
    cannot resolve may hold."""
    held = None
    for g in GESTURES:
        if g.program != "brain":
            continue
        if g.loose and _anywhere(g, low):
            return g
        for start in ([] if helped or at < 0 else _starts(cmd, wide)):
            end = _words_at(g, start, wide)
            if end >= 0 and _fits(g, start[end:], wide):
                return g
            held = held or (g if end == HOLDS else None)
    return held


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


def session_markers(data: dict | None = None) -> bool:
    """config.json's ``guards.gestures_session_markers``: an agent's session is read from every name of
    :data:`MARKER_NAMES` (off by default: :data:`AGENT_ENV`, and ``CLAUDECODE`` alone for the acting gestures' own
    lock, as 0.5.1 read them); an unreadable config.json loads as no data, so it stays off."""
    if data is None:
        from . import config
        data = config.load().data
    section = data.get("guards") if isinstance(data, dict) else None
    return isinstance(section, dict) and section.get("gestures_session_markers") is True


# What marks a session: the variables Claude Code sets for each session it runs (and the brain's own agents'), never
# the configuration ones an owner may export in their own terminal (CLAUDE_CODE_USE_BEDROCK, CLAUDE_CODE_SSE_PORT...)
SESSION_ENV = ("CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_HOST_SESSION_ID", "CLAUDE_CODE_CHILD_SESSION",
               "CLAUDE_CODE_EXECPATH", "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_PID")
MARKER_NAMES = (*AGENT_ENV, *SESSION_ENV)
_MARKER = re.compile(r"(?i)^(?:CLAUDE\w*|BRAIN_AGENT_SESSION)\*?$")
CLEARING = {"unset": "", "export": "-n", "declare": "+x", "typeset": "+x"}   # the shell's, with the flag that clears
PS_REMOVE = {"remove-item", "ri", "rm", "del", "erase", "clear-item", "cli", "rmdir", "rd"}
CODE_CLEARS = re.compile(
    r"(?i)SetEnvironmentVariable\s*\(\s*(?:['\"]?(?:CLAUDE|BRAIN_AGENT)|\$)|-UseNewEnvironment\b|"
    r"\.Environment\.(?:Clear|Remove)\s*\(|\bdel\s+os\.environ\b|\benviron\.(?:pop|clear)\s*\(|\b(?:unsetenv|putenv)\b")


def _names_marker(word: str, named: bool) -> bool:
    """Whether ``word`` (an operand) is a marker, a pattern of them, or (``named``: the call names CLAUDE) a word the
    guard cannot resolve, which may be one ($v, $(compgen ...))."""
    w = word.strip("'\"")
    return bool(_MARKER.match(w)) or "${!CLAUDE" in w.upper() or (named and _unknown(w))


_EMPTY_VALUES = ("", "$null")
_ENV_CLEARS_ALL = re.compile(r"-[a-z]*i")


def _empty_assignment(words: list[str]) -> str:
    """A leading assignment of a marker to nothing (``CLAUDECODE= cmd``), or PowerShell's ``$env:CLAUDECODE = ''``."""
    for w in words:
        m = re.match(r"^(?:\$env:)?([A-Za-z_]\w*)=(.*)$", w, re.I)
        if not m:
            break
        if _MARKER.match(m.group(1)) and m.group(2).strip("'\"") in _EMPTY_VALUES:
            return w
    ps = len(words) >= 3 and words[1] == "=" and words[0].lower().startswith("$env:")
    if ps and _MARKER.match(words[0][5:]) and words[2].strip("'\"") in _EMPTY_VALUES:
        return " ".join(words[:3])
    return ""


def _env_value(args: list[str], k: int) -> str | None:
    """The variable ``env``'s option at ``args[k]`` unsets (``-u X``, ``-uX``, ``--unset=X``), else None."""
    a = args[k]
    if a in ("-u", "--unset"):
        return args[k + 1] if k + 1 < len(args) else None
    if a.startswith("--unset="):
        return a.split("=", 1)[1]
    return a[2:] if a.startswith("-u") and len(a) > 2 else None


def _env_clears(args: list[str], named: bool) -> bool:
    """Whether ``env ARGS`` starts its program without the markers (``-i``, ``-``, or ``-u`` of one)."""
    for k, a in enumerate(args):
        if a in ("-", "--ignore-environment") or _ENV_CLEARS_ALL.fullmatch(a):
            return True
        val = _env_value(args, k)
        if val is not None and _names_marker(val, named):
            return True
    return False


def _ps_removes(args: list[str], command: str) -> bool:
    """Whether PowerShell's Remove-Item (and its kin) removes Env: items, by path or from an Env: listing piped."""
    paths = [a for a in args if not a.startswith("-")]
    if any(re.match(r"(?i)^env:[\\/]?", a.strip("'\"")) for a in paths):
        return True
    return not paths and bool(re.search(r"(?i)\benv:[\\/]?claude", command))


def _clears(words: list[str], named: bool, command: str) -> str:
    """What the simple command ``words`` clears of the markers, else ''."""
    hit = _empty_assignment(words)
    if hit:
        return hit
    prog = re.split(r"[\\/]", words[0])[-1].lower().removesuffix(".exe")
    args = words[1:]
    flag = CLEARING.get(prog)
    if flag is not None and (not flag or flag in args) and \
            any(_names_marker(a, named) for a in args if not a.startswith(("-", "+"))):
        return " ".join(words)[:120]
    if (prog == "env" and _env_clears(args, named)) or (prog in PS_REMOVE and _ps_removes(args, command)):
        return " ".join(words)[:120]
    return ""


def clears_marker(command: str) -> str:
    """What in ``command`` clears an agent session's markers, else '': read from its simple commands' words (a
    message or a search that only names the forms passes), and only when the call names CLAUDE, BRAIN_AGENT_SESSION or
    a way to clear a whole environment: an empty assignment (``CLAUDECODE= cmd``, ``$env:CLAUDECODE = ''``), ``unset``,
    ``export -n``, ``declare +x`` of a marker, a pattern or an operand it cannot resolve; ``env -u`` likewise,
    ``env -i``; PowerShell's removal of ``Env:`` items (or of what an ``Env:`` listing pipes to it); .NET's and inline
    code's environment calls."""
    low = (command or "").lower()
    if not any(w in low for w in ("claude", "brain_agent_session", "env -i", "env --ignore", "env -", "usenewenv",
                                  "environment.clear")):
        return ""
    named = "claude" in low or "brain_agent_session" in low
    from . import guards
    for ps in (False, True):
        for words in guards.segments(command, ps):
            if words and not words[0].startswith(guards.REDIRECT):
                hit = _clears(words, named, command)
                if hit:
                    return hit
    m = CODE_CLEARS.search(command or "")
    return m.group(0) if m else ""


def wide_matching(data: dict | None = None) -> bool:
    """config.json's ``guards.gestures_wide``: a gesture is matched through words the guard cannot resolve and
    Python's inline code too (off by default: refusals 0.6.0 adds; the MCP server follows it too)."""
    if data is None:
        from . import config
        data = config.load().data
    section = data.get("guards") if isinstance(data, dict) else None
    return isinstance(section, dict) and section.get("gestures_wide") is True


def cli_refusal(argv: list[str], env=None, data: dict | None = None) -> str:
    """Why brain.cli refuses ``brain ARGV`` here ('' when it runs): a gesture the CLI gates, in an agent's session,
    under ``guards.owner_strict`` or ``guards.gestures_wide`` (the command's own lock under the wide guard)."""
    g = match(["brain", *argv])
    if g is None or g.cli != "gate":
        return ""
    var = agent_session(env, data)
    if not var or not (strict(data) or wide_matching(data)):
        return ""
    from . import config
    return (f"{g.name} is {config.name_of()}'s, in their own terminal: {g.why}; refused in an agent's session "
            f"({var} is set; config.json guards.owner_strict or guards.gestures_wide)")
