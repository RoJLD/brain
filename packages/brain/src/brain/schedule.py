"""The brain commands a machine's scheduler runs (wi-brain-alerts-pass): declared in the registry, installed by one
idempotent command (``brain schedule install``, a plan, then ``--apply``; the installer's schedule step runs it), and
the alerts pass's own silence watched (a dead-man).

A project's ``schedules:`` entry, inline or a YAML file relative to its root, one entry per scheduled command::

  brain:
    schedules:
      alerts-pass: {command: alerts --all --notify, every: 15m, at_logon: true}
      vault-canary: {command: vault canary, at: '07:30', machines: [ada-desktop]}

  command   the brain command's arguments (a string or a list): the task runs the interpreter of the brain command
            that installed it, ``python -I -m brain <command>``
  every     a cadence (1m to 1d: 15m, 1h, 1d); at   a daily time HH:MM; at_logon  true: also at logon (one of the
            three at least)
  machines  the machines it runs on ($BRAIN_MACHINE, else the host name, lowercase; default every machine)
  timeout   how long a run may last before the scheduler stops it (default 10m)
  enabled   false: removed from this machine (and never installed)

Schedule names are global, like stack names. Where it goes, per system:

  windows  the Task Scheduler, ``\\Brain\\<name>``: schtasks /Create /XML, as the user who applies it, in their session
           (the interactive token: their environment, their keystore), never two runs at once, started when a run was
           missed; the venv's pythonw.exe, so no console window opens
  linux    a systemd user timer, ``~/.config/systemd/user/brain-<name>.timer`` and its ``.service``, enabled with
           systemctl --user (the timers run while the user is logged in, or always once ``loginctl enable-linger``,
           the owner's gesture); without a user systemd, the user's crontab (a line tagged ``# brain schedule <name>``,
           at_logon as @reboot). Both run through ``bash -lc``, so the login profile's variables reach the command
           (BRAIN_NTFY_TOPIC, BRAIN_MACHINE)
  other    not supported yet: the plan says so

What this machine installed is recorded in ``$BRAIN_HOME/schedules/installed.json``: a schedule no longer declared
for this machine, or declared ``enabled: false``, is removed by the next apply; a task the brain did not install (one
registered by hand under ``\\Brain\\``) is never touched, and one recorded under another scheduler than the one this
run finds (systemd --user out of a login session) is left as it is, said in a note. A command is the brain command's
arguments: a control character (a newline) or an unbalanced quote is refused. Creating a scheduled task is the
owner's decision: ``--apply`` is refused from a Claude Code session (CLAUDECODE set) after printing the plan, and the
guards refuse ``brain schedule install --apply`` (owner, scheduled); the owner runs the apply (install.ps1 -Apply).

The dead-man (:func:`watch`): the alerts pass is the schedule whose command is ``alerts ... --notify``; once installed
here, it is silent when the later of its last pass (``$BRAIN_HOME/alerts/state.json``, written by every pass) and its
install is older than two cadences, plus a grace, counted in the machine's awake time (:func:`clock`: a machine off
or asleep misses no pass, so the first session after a boot or a wake is not told SILENT). The SessionStart health
hook says so in one line and brain status's alerts row shows it.
"""

from __future__ import annotations

import html
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from . import graph, paths, projects

KEYS = {"command", "every", "at", "at_logon", "machines", "timeout", "enabled"}
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
DURATION = re.compile(r"(\d+)\s*([smhd])")
UNIT = {"s": 1, "m": 60, "h": 3600, "d": 86400}
TIME = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")
DEFAULT_TIMEOUT = 600.0
WIN_FOLDER = "\\Brain\\"
MARK = "brain schedule:"          # the Windows task's description and the unit's Description start with it
CRON_TAG = "# brain schedule "    # a crontab line's tag, then the name
RUN_TIMEOUT = 30.0


class ScheduleError(ValueError):
    """A bad schedules: entry (brain check --all reports it; brain schedule exits 2)."""


@dataclass
class Schedule:
    name: str
    project: str
    command: list[str]
    every: float | None = None     # seconds
    at: str = ""                   # HH:MM, daily
    at_logon: bool = False
    machines: list[str] = field(default_factory=list)
    timeout: float = DEFAULT_TIMEOUT
    enabled: bool = True

    def here(self, machine: str) -> bool:
        return self.enabled and (not self.machines or machine in self.machines)

    def when(self) -> str:
        parts = ([f"every {duration_text(self.every)}"] if self.every else []) + (
            [f"daily at {self.at}"] if self.at else []) + (["at logon"] if self.at_logon else [])
        return " and ".join(parts)

    def cadence(self) -> float:
        """The longest wait between two runs: the every, else a day."""
        return self.every or 86400.0

    def describe(self) -> str:
        return f"{MARK} {self.name} ({self.project}): brain {shlex.join(self.command)}, {self.when()}"


def seconds(text) -> float:
    m = DURATION.fullmatch(str(text).strip().lower())
    if not m:
        raise ValueError(f"{text!r} is not a duration (15m, 1h, 1d)")
    return float(int(m.group(1)) * UNIT[m.group(2)])


def duration_text(s: float) -> str:
    for unit, n in (("d", 86400), ("h", 3600), ("m", 60)):
        if s >= n and s % n == 0:
            return f"{int(s // n)}{unit}"
    return f"{int(s)}s"


def machine() -> str:
    from .memory import machine as name
    return name()


# --- the declaration ---

def _entries(p: projects.Project) -> dict:
    value = getattr(p, "schedules", None)
    if isinstance(value, str):
        f = p.root / value
        if not f.is_file():
            raise ScheduleError(f"project {p.name}: schedules file {value} not found")
        try:
            value = graph.load_yaml(f.read_text(encoding="utf-8")) or {}
        except Exception as exc:  # noqa: BLE001 (a YAML or decode error: a bad declaration, never a crash)
            raise ScheduleError(f"project {p.name}: schedules file {value}: {type(exc).__name__}") from None
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ScheduleError(f"project {p.name}: schedules is a mapping of name -> entry, or a file name")
    return value


CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _command(conf: dict, where: str) -> list[str]:
    cmd = conf.get("command")
    try:
        command = shlex.split(cmd) if isinstance(cmd, str) else [str(c) for c in cmd] if isinstance(cmd, list) else []
    except ValueError as exc:  # an unbalanced quote
        raise ScheduleError(f"{where}: command: {exc}") from None
    if any(CONTROL.search(c) for c in command):
        # a newline would split a crontab line or a unit file: the command is the brain command's arguments, nothing more
        raise ScheduleError(f"{where}: command holds a control character (a newline, a tab)")
    if not command:
        raise ScheduleError(f"{where}: command, the brain command's arguments, is missing")
    if command[0] == "brain":
        raise ScheduleError(f"{where}: command holds the brain command's arguments, without brain itself")
    return command


def _duration(conf: dict, key: str, where: str, default: float | None) -> float | None:
    if conf.get(key) in (None, ""):
        return default
    try:
        return seconds(conf[key])
    except ValueError as exc:
        raise ScheduleError(f"{where}: {exc}") from None


def _when(conf: dict, where: str) -> tuple[float | None, str]:
    every = _duration(conf, "every", where, None)
    if every is not None and not 60 <= every <= 86400:
        raise ScheduleError(f"{where}: every is 1m to 1d")
    at = str(conf.get("at") or "")
    if at and not TIME.fullmatch(at):
        raise ScheduleError(f"{where}: at is a daily time HH:MM")
    if not (every or at or conf.get("at_logon")):
        raise ScheduleError(f"{where}: every, at or at_logon says when it runs")
    return every, at


def _entry(project: str, name: str, conf) -> Schedule:
    where = f"project {project}: schedules {name}"
    if not NAME.fullmatch(name):
        raise ScheduleError(f"{where}: a name of lowercase letters, digits and dashes")
    if not isinstance(conf, dict):
        raise ScheduleError(f"{where}: an entry is a mapping ({', '.join(sorted(KEYS))})")
    unknown = sorted(set(map(str, conf)) - KEYS)
    if unknown:
        raise ScheduleError(f"{where}: unknown key(s) {', '.join(unknown)} (known: {', '.join(sorted(KEYS))})")
    command = _command(conf, where)
    every, at = _when(conf, where)
    machines = conf.get("machines") or []
    machines = [machines] if isinstance(machines, str) else machines
    if not isinstance(machines, list):
        raise ScheduleError(f"{where}: machines is a list of machine names")
    return Schedule(name, project, command, every, at, bool(conf.get("at_logon")), [str(m).lower() for m in machines],
                    _duration(conf, "timeout", where, DEFAULT_TIMEOUT), conf.get("enabled", True) is not False)


def parse(p: projects.Project) -> list[Schedule]:
    """The project's schedules; ScheduleError on a bad entry."""
    return [_entry(p.name, str(name), conf) for name, conf in _entries(p).items()]


def declared(registry: Mapping[str, projects.Project]) -> list[Schedule]:
    """Every project's schedules, names unique across them; ScheduleError on the first bad entry."""
    out, seen = [], {}
    for p in registry.values():
        for s in parse(p):
            if s.name in seen:
                raise ScheduleError(f"schedule {s.name}: declared by {seen[s.name]} and {s.project} (names are "
                                    "global)")
            seen[s.name] = s.project
            out.append(s)
    return out


def check(registry: Mapping[str, projects.Project]) -> list[str]:
    """brain check --all: every schedules: entry."""
    try:
        declared(registry)
    except ScheduleError as exc:
        return [str(exc)]
    return []


# --- what this machine installed ---

def record_file() -> Path:
    return paths.brain_home() / "schedules" / "installed.json"


def installed() -> dict:
    try:
        data = json.loads(record_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _record(data: dict) -> None:
    f = record_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, f)


# --- the systems ---

Runner = Callable[..., subprocess.CompletedProcess]


def _oem() -> str:
    """The console code page a windowless child writes in (schtasks: cp850 on a French Windows), utf-8 elsewhere."""
    try:
        import ctypes
        return f"cp{ctypes.windll.kernel32.GetOEMCP()}"
    except (ImportError, AttributeError, OSError):
        return "utf-8"


def _run(argv: list[str], *, input: str | None = None, timeout: float = RUN_TIMEOUT) -> subprocess.CompletedProcess:
    """A scheduler's command, its output captured (replaced by a fake in the tests). schtasks writes the OEM code
    page, whatever its XML header says."""
    try:
        return subprocess.run(argv, input=input, capture_output=True, text=True, timeout=timeout,
                              encoding=_oem() if os.name == "nt" and argv[:1] == ["schtasks"] else "utf-8",
                              errors="replace", stdin=None if input is not None else subprocess.DEVNULL,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(argv, 127, "", f"{type(exc).__name__}: {exc}")


def interpreter() -> Path:
    """The Python the tasks run: the brain command's own (its venv), pythonw.exe beside it on Windows."""
    exe = Path(sys.executable)
    if os.name == "nt":
        w = exe.with_name("pythonw.exe")
        if w.is_file():
            return w
    return exe


def _argv(s: Schedule, python: Path) -> list[str]:
    return [str(python), "-I", "-m", "brain", *s.command]


@dataclass
class Step:
    action: str        # same, create, update, remove, note
    name: str
    line: str
    apply: Callable[[], str] | None = None   # returns '' when it worked, else why not


class System:
    """One machine scheduler: what a schedule looks like there, and how it is read, written and removed."""
    label = ""

    def where(self, name: str) -> str:
        raise NotImplementedError

    def wanted(self, s: Schedule, python: Path) -> object:
        raise NotImplementedError

    def current(self, name: str) -> object | None:
        raise NotImplementedError

    def write(self, s: Schedule, want) -> str:
        raise NotImplementedError

    def delete(self, name: str) -> str:
        raise NotImplementedError

    def notes(self, live: list[Schedule]) -> list[str]:
        return []


def _iso_local(dt: datetime) -> str:
    return dt.replace(microsecond=0, tzinfo=None).isoformat()


def _xml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _xs_duration(s: float) -> str:
    s = int(s)
    h, rest = divmod(s, 3600)
    m, sec = divmod(rest, 60)
    return "PT" + (f"{h}H" if h else "") + (f"{m}M" if m else "") + (f"{sec}S" if sec or not (h or m) else "")


class Windows(System):
    """The Task Scheduler, through schtasks (its XML: every setting, no locale)."""
    label = "the Task Scheduler"

    def __init__(self, run: Runner = _run, user: str | None = None, today: datetime | None = None):
        self.run = run
        self.user = user or "\\".join(x for x in (os.environ.get("USERDOMAIN"), os.environ.get("USERNAME")) if x)
        self.today = today or datetime.now()

    def where(self, name: str) -> str:
        return WIN_FOLDER + name

    def wanted(self, s: Schedule, python: Path) -> str:
        start = self.today.replace(hour=0, minute=0, second=0, microsecond=0)
        triggers = []
        if s.at_logon:
            triggers.append(f"<LogonTrigger><Enabled>true</Enabled><UserId>{_xml(self.user)}</UserId></LogonTrigger>")
        if s.every:
            triggers.append(f"<TimeTrigger><StartBoundary>{_iso_local(start)}</StartBoundary><Enabled>true</Enabled>"
                            f"<Repetition><Interval>{_xs_duration(s.every)}</Interval>"
                            "<StopAtDurationEnd>false</StopAtDurationEnd></Repetition></TimeTrigger>")
        if s.at:
            hh, mm = map(int, s.at.split(":"))
            triggers.append(f"<CalendarTrigger><StartBoundary>{_iso_local(start.replace(hour=hh, minute=mm))}"
                            "</StartBoundary><Enabled>true</Enabled><ScheduleByDay><DaysInterval>1</DaysInterval>"
                            "</ScheduleByDay></CalendarTrigger>")
        argv = _argv(s, python)
        args = subprocess.list2cmdline(argv[1:])
        return ('<?xml version="1.0" encoding="UTF-16"?>\n'
                '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
                f"<RegistrationInfo><Description>{_xml(s.describe())}</Description></RegistrationInfo>"
                f"<Triggers>{''.join(triggers)}</Triggers>"
                f'<Principals><Principal id="Author"><UserId>{_xml(self.user)}</UserId>'
                "<LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>"
                "<Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>"
                "<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>"
                "<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><StartWhenAvailable>true</StartWhenAvailable>"
                f"<ExecutionTimeLimit>{_xs_duration(s.timeout)}</ExecutionTimeLimit><Enabled>true</Enabled>"
                "</Settings>"
                f'<Actions Context="Author"><Exec><Command>{_xml(argv[0])}</Command>'
                f"<Arguments>{_xml(args)}</Arguments></Exec></Actions></Task>\n")

    @staticmethod
    def summary(xml: str) -> dict:
        """What decides same or update: the description, the action, the triggers' kinds and cadences, the limit."""
        def tag(name: str) -> list[str]:   # entities decoded: the Task Scheduler writes a quote back as is
            return [html.unescape(m.strip()) for m in re.findall(rf"<{name}>(.*?)</{name}>", xml, re.S)]
        kinds = sorted(set(re.findall(r"<(LogonTrigger|TimeTrigger|CalendarTrigger)\b", xml)))
        times = sorted(b[11:16] for b in re.findall(r"<CalendarTrigger>.*?<StartBoundary>(.*?)</StartBoundary>",
                                                     xml, re.S))
        return {"description": tag("Description"), "command": tag("Command"), "arguments": tag("Arguments"),
                "kinds": kinds, "interval": tag("Interval"), "at": times, "limit": tag("ExecutionTimeLimit")}

    def current(self, name: str) -> str | None:
        r = self.run(["schtasks", "/Query", "/TN", self.where(name), "/XML", "ONE"])
        return r.stdout if r.returncode == 0 and "<Task" in (r.stdout or "") else None

    def same(self, have: str, want: str) -> bool:
        return self.summary(have) == self.summary(want)

    def write(self, s: Schedule, want: str) -> str:
        fd, tmp = tempfile.mkstemp(suffix=".xml", prefix=f"brain-{s.name}-")
        os.close(fd)
        try:
            Path(tmp).write_text(want, encoding="utf-16")
            r = self.run(["schtasks", "/Create", "/TN", self.where(s.name), "/XML", tmp, "/F"])
        finally:
            Path(tmp).unlink(missing_ok=True)
        return "" if r.returncode == 0 else _why(r)

    def delete(self, name: str) -> str:
        r = self.run(["schtasks", "/Delete", "/TN", self.where(name), "/F"])
        if r.returncode == 0 or self.current(name) is None:   # already gone (deleted by hand): removed all the same
            return ""
        return _why(r)


def _why(r: subprocess.CompletedProcess) -> str:
    text = ((r.stderr or "").strip() or (r.stdout or "").strip()).splitlines()
    return (text[0] if text else f"exit {r.returncode}")[:200]


def _bash_lc(argv: list[str]) -> str:
    """The command as a login shell runs it: the profile's variables (BRAIN_NTFY_TOPIC, BRAIN_MACHINE) reach it."""
    return "exec " + shlex.join(argv)


def _unit_quote(text: str) -> str:
    """One ExecStart argument: systemd expands %, $VAR and ${VAR} even inside quotes, so each is doubled."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$") + '"'


class Systemd(System):
    """A systemd user timer and its service, in ~/.config/systemd/user (XDG_CONFIG_HOME)."""
    label = "systemd --user"

    def __init__(self, run: Runner = _run, folder: Path | None = None, user: str | None = None):
        self.run = run
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        self.folder = folder or base / "systemd" / "user"
        self.user = user or os.environ.get("USER") or os.environ.get("LOGNAME") or ""

    def unit(self, name: str) -> str:
        return f"brain-{name}"

    def where(self, name: str) -> str:
        return str(self.folder / f"{self.unit(name)}.timer")

    def wanted(self, s: Schedule, python: Path) -> dict[str, str]:
        timer = ["OnStartupSec=1min" if s.at_logon else "", "OnActiveSec=1min" if s.every else "",
                 f"OnUnitActiveSec={duration_text(s.every)}" if s.every else "",
                 f"OnCalendar=*-*-* {s.at}:00" if s.at else "", "Persistent=true" if s.at else ""]
        return {
            "service": (f"[Unit]\nDescription={s.describe()}\n\n[Service]\nType=oneshot\n"
                        f"ExecStart=/bin/bash -lc {_unit_quote(_bash_lc(_argv(s, python)))}\n"
                        f"TimeoutStartSec={int(s.timeout)}\n"),
            "timer": (f"[Unit]\nDescription={s.describe()}\n\n[Timer]\n"
                      + "".join(f"{t}\n" for t in timer if t) + "AccuracySec=1min\n\n[Install]\n"
                      "WantedBy=timers.target\n")}

    def current(self, name: str) -> dict | None:
        files = {k: self.folder / f"{self.unit(name)}.{k}" for k in ("service", "timer")}
        if not any(f.is_file() for f in files.values()):
            return None
        out = {k: f.read_text(encoding="utf-8") if f.is_file() else "" for k, f in files.items()}
        r = self.run(["systemctl", "--user", "is-enabled", f"{self.unit(name)}.timer"])
        out["enabled"] = (r.stdout or "").strip() == "enabled"
        return out

    def same(self, have: dict, want: dict) -> bool:
        return have.get("enabled") is True and all(have.get(k) == v for k, v in want.items())

    def write(self, s: Schedule, want: dict) -> str:
        self.folder.mkdir(parents=True, exist_ok=True)
        for k, text in want.items():
            (self.folder / f"{self.unit(s.name)}.{k}").write_text(text, encoding="utf-8")
        for argv in (["systemctl", "--user", "daemon-reload"],
                     ["systemctl", "--user", "enable", "--now", f"{self.unit(s.name)}.timer"]):
            r = self.run(argv)
            if r.returncode != 0:
                return _why(r)
        return ""

    def delete(self, name: str) -> str:
        r = self.run(["systemctl", "--user", "disable", "--now", f"{self.unit(name)}.timer"])
        for k in ("service", "timer"):
            (self.folder / f"{self.unit(name)}.{k}").unlink(missing_ok=True)
        self.run(["systemctl", "--user", "daemon-reload"])
        return "" if r.returncode == 0 or "not loaded" in (r.stderr or "") or "does not exist" in (r.stderr or "") \
            else _why(r)

    def notes(self, live: list[Schedule]) -> list[str]:
        if not live or not self.user:
            return []
        r = self.run(["loginctl", "show-user", self.user, "-p", "Linger", "--value"])
        if r.returncode == 0 and (r.stdout or "").strip() == "no":
            return [f"linger off for {self.user}: the timers run only while {self.user} is logged in; on a machine "
                    f"that stays on, loginctl enable-linger {self.user} (yours, once) keeps them running"]
        return []


def _cron_when(s: Schedule) -> list[str]:
    out = []
    if s.every:
        m = int(s.every // 60)
        if s.every % 60 or not (m < 60 and 60 % m == 0 or m % 60 == 0 and (m // 60 <= 24 and 24 % (m // 60) == 0)):
            raise ScheduleError(f"schedule {s.name}: every {duration_text(s.every)} has no crontab form (a divisor "
                                "of an hour or of a day)")
        out.append(f"*/{m} * * * *" if m < 60 else "0 * * * *" if m == 60 else "0 0 * * *" if m == 1440
                   else f"0 */{m // 60} * * *")
    if s.at:
        hh, mm = s.at.split(":")
        out.append(f"{int(mm)} {int(hh)} * * *")
    if s.at_logon:
        out.append("@reboot")
    return out


class Cron(System):
    """The user's crontab, where no user systemd runs (a container, WSL, a minimal server)."""
    label = "the user's crontab"

    def __init__(self, run: Runner = _run):
        self.run = run

    def where(self, name: str) -> str:
        return f"crontab, {CRON_TAG}{name}"

    def _lines(self) -> list[str] | None:
        r = self.run(["crontab", "-l"])
        if r.returncode != 0:
            return [] if "no crontab" in (r.stderr or "").lower() else None
        return (r.stdout or "").splitlines()

    def wanted(self, s: Schedule, python: Path) -> list[str]:
        cmd = shlex.quote(_bash_lc(_argv(s, python))).replace("%", "\\%")
        return [f"{when} /bin/bash -lc {cmd} {CRON_TAG}{s.name}" for when in _cron_when(s)]

    def current(self, name: str) -> list[str] | None:
        mine = [ln for ln in self._lines() or [] if ln.endswith(f"{CRON_TAG}{name}")]
        return mine or None

    def same(self, have: list[str], want: list[str]) -> bool:
        return have == want

    def _replace(self, name: str, new: list[str]) -> str:
        lines = self._lines()
        if lines is None:
            return "crontab -l failed"
        kept = [ln for ln in lines if not ln.endswith(f"{CRON_TAG}{name}")]
        r = self.run(["crontab", "-"], input="\n".join(kept + new) + "\n")
        return "" if r.returncode == 0 else _why(r)

    def write(self, s: Schedule, want: list[str]) -> str:
        return self._replace(s.name, want)

    def delete(self, name: str) -> str:
        return self._replace(name, [])


def system(run: Runner = _run, platform: str | None = None) -> System | None:
    """This machine's scheduler: the Task Scheduler on Windows; a user systemd on Linux, else cron; None elsewhere."""
    platform = platform or sys.platform
    if platform == "win32":
        return Windows(run)
    if platform.startswith("linux"):
        if shutil.which("systemctl") and run(["systemctl", "--user", "show-environment"]).returncode == 0:
            return Systemd(run)
        if shutil.which("crontab"):
            return Cron(run)
    return None


# --- the plan, then the apply ---

def _step(s: Schedule, sys_: System, python: Path) -> Step:
    try:
        want = sys_.wanted(s, python)
    except ScheduleError as exc:
        return Step("note", s.name, f"schedule {s.name}: {exc}")
    have = sys_.current(s.name)
    what = f"{s.name}: brain {shlex.join(s.command)}, {s.when()} ({sys_.where(s.name)})"
    if have is not None and sys_.same(have, want):
        return Step("same", s.name, f"same     schedule {what}")
    action = "update" if have is not None else "create"
    return Step(action, s.name, f"{action:<8} schedule {what}", lambda: sys_.write(s, want))


def plan(schedules: list[Schedule], here: str, sys_: System | None, python: Path | None = None,
         record: dict | None = None) -> list[Step]:
    """What brain schedule install would do on this machine: a step per schedule declared here, enabled: false or
    recorded as installed and no longer declared."""
    record = installed() if record is None else record
    live = [s for s in schedules if s.here(here)]
    if sys_ is None:
        return [Step("note", s.name, f"schedule {s.name}: {s.when()}: no scheduler supported here yet "
                     f"({sys.platform}): run brain {shlex.join(s.command)} by hand") for s in live]
    elsewhere = {n: r for n, r in record.items() if r.get("system") and r["system"] != sys_.label}
    steps = [_moved(s.name, elsewhere[s.name], sys_) if s.name in elsewhere else _step(s, sys_, python or interpreter())
             for s in live]
    steps += _removals(record, {s.name for s in live}, elsewhere, sys_)
    return steps + [Step("note", "", f"note     {n}") for n in sys_.notes(live)]


def _removals(record: dict, live: set[str], elsewhere: dict, sys_: System) -> list[Step]:
    """A step for each schedule this machine installed and no longer declares."""
    return [_moved(name, rec, sys_) if name in elsewhere else
            Step("remove", name, f"remove   schedule {name} ({rec.get('where') or sys_.where(name)}): no longer "
                 "declared for this machine", lambda name=name: sys_.delete(name))
            for name, rec in sorted(record.items()) if name not in live]


def _moved(name: str, rec: dict, sys_: System) -> Step:
    """A schedule installed with another scheduler than the one this run finds (systemd --user out of a login
    session, say): left as it is, so that no task is orphaned or doubled."""
    return Step("note", name, f"note     schedule {name} was installed with {rec['system']} ({rec.get('where', '')}); "
                f"this run finds {sys_.label}: nothing changed (apply where {rec['system']} answers, a login session)")


def _stamp(sys_: System, name: str) -> dict:
    return {"where": sys_.where(name), "system": sys_.label,
            "at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "clock": clock()}


def _apply(st: Step, sys_: System, record: dict) -> str:
    """One step applied, its outcome; the record of what this machine installed kept with it."""
    why = st.apply() if st.apply is not None else ""
    if why:
        return f"failed: {why}"
    if st.action == "remove":
        record.pop(st.name, None)
    elif st.action in ("create", "update") or (st.action == "same" and st.name not in record):
        record[st.name] = _stamp(sys_, st.name)   # a same task found here unrecorded is adopted
    return "done" if st.apply is not None else ""


def install(registry: Mapping[str, projects.Project], apply: bool = False, *, run: Runner = _run,
            here: str | None = None, as_json: bool = False) -> int:
    """brain schedule install [--apply]: the plan, then each step applied; 0, 1 when a step failed, 2 on a bad
    declaration."""
    try:
        schedules = declared(registry)
    except ScheduleError as exc:
        print(f"brain schedule: {exc}", file=sys.stderr)
        return 2
    if apply:
        from .detail import refused
        why = refused()
        if why:   # the owner's decision: a session prints the plan, the owner runs the apply (install.ps1 -Apply)
            install(registry, False, run=run, here=here, as_json=as_json)
            print(f"brain schedule: install --apply refused: {why}", file=sys.stderr)
            return 2
    here = here or machine()
    sys_ = system(run)
    record = installed()
    steps = plan(schedules, here, sys_, record=record)
    rows = [{"action": st.action, "name": st.name, "line": st.line,
             "outcome": _apply(st, sys_, record) if apply and st.action != "note" else ""} for st in steps]
    if apply and sys_ is not None:
        _record(record)
    if as_json:
        print(json.dumps({"machine": here, "system": sys_.label if sys_ else None, "steps": rows,
                          "applied": apply}, indent=2))
    else:
        print("\n".join(_render(rows, apply)))
    return 1 if any(r["outcome"].startswith("failed") for r in rows) else 0


def _render(rows: list[dict], apply: bool) -> list[str]:
    if not rows:
        return ["schedule none declared for this machine (projects.yaml schedules:)"]
    todo = " (to do: --apply)" if not apply else ""
    return [r["line"] + (f" ({r['outcome']})" if r["outcome"] else
                         todo if r["action"] in ("create", "update", "remove") else "") for r in rows]


def listing(registry: Mapping[str, projects.Project], *, here: str | None = None, as_json: bool = False) -> int:
    """brain schedule list: every declared schedule, whether it runs here, whether this machine installed it, and
    the alerts pass's dead-man."""
    try:
        schedules = declared(registry)
    except ScheduleError as exc:
        print(f"brain schedule: {exc}", file=sys.stderr)
        return 2
    here = here or machine()
    rec = installed()
    rows = [{"name": s.name, "project": s.project, "command": s.command, "when": s.when(),
             "here": s.here(here), "installed": rec.get(s.name)} for s in schedules]
    w = watch(registry, here=here)
    if as_json:
        print(json.dumps({"machine": here, "schedules": rows, "alerts_pass": w}, indent=2))
        return 0
    if not rows:
        print("schedule none declared (projects.yaml schedules:)")
    for r in rows:
        state = ("installed " + str(r["installed"].get("at", ""))) if r["installed"] else (
            "not installed (brain schedule install --apply, or install.ps1 -Apply)" if r["here"]
            else "not for this machine")
        print(f"{r['name']} ({r['project']}): brain {shlex.join(r['command'])}, {r['when']}: {state}")
    if w:
        print(f"alerts pass: {w['line']}")
    return 0


# --- the dead-man of the alerts pass ---

def is_alerts_pass(s: Schedule) -> bool:
    return bool(s.command) and s.command[0] == "alerts" and "--notify" in s.command


def _ts(text) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def last_pass() -> dict:
    """The last notify pass on this machine ({at, host, unset}), from $BRAIN_HOME/alerts/state.json; {} before one."""
    try:
        data = json.loads((paths.brain_home() / "alerts" / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    p = data.get("_pass") if isinstance(data, dict) else None
    return p if isinstance(p, dict) else {}


def clock() -> dict:
    """{boot, awake}: when this machine booted (epoch seconds) and how long it has been awake since, sleep left out
    (Windows' unbiased interrupt time, Linux's monotonic clock); {} elsewhere. The dead-man counts awake time only."""
    import time
    try:
        if os.name == "nt":
            import ctypes
            k32 = ctypes.windll.kernel32
            k32.GetTickCount64.restype = ctypes.c_ulonglong
            unbiased = ctypes.c_ulonglong()
            if not k32.QueryUnbiasedInterruptTime(ctypes.byref(unbiased)):
                return {}
            return {"boot": round(time.time() - k32.GetTickCount64() / 1000), "awake": round(unbiased.value / 1e7)}
        if sys.platform.startswith("linux"):
            btime = next(int(ln.split()[1]) for ln in Path("/proc/stat").read_text().splitlines()
                         if ln.startswith("btime "))
            return {"boot": btime, "awake": round(time.monotonic())}
    except (OSError, AttributeError, ValueError, StopIteration):
        pass
    return {}


def _awake_since(ref) -> float | None:
    """The awake seconds since a recorded clock: across a reboot, the time awake since the boot; None unknown."""
    cur = clock()
    if not cur or not isinstance(ref, dict) or "boot" not in ref or "awake" not in ref:
        return None
    return cur["awake"] - ref["awake"] if abs(cur["boot"] - ref["boot"]) < 300 else cur["awake"]


def _ago(seconds_: float) -> str:
    m = int(seconds_ // 60)
    return f"{m} min" if m < 120 else f"{m // 60} h" if m < 2880 else f"{m // 1440} d"


def _pass_line(s: Schedule, rec: dict | None, last: datetime | None, silent: bool, now: datetime) -> str:
    every = duration_text(s.cadence())
    if not rec:
        return f"{s.name} declared for this machine, not installed (install.ps1 -Apply)"
    ago = f"{_ago((now - last).total_seconds())} ago" if last else ""
    if silent:
        return (f"SILENT: {s.name} " + (f"last passed {ago}" if last else "never passed") + f", every {every} "
                "(brain schedule list; brain alerts --all --notify runs one)")
    return f"{s.name} every {every}, last {ago or 'not yet'}"


def _alerts_pass(registry, here: str, project: str | None) -> Schedule | None:
    try:
        schedules = registry if isinstance(registry, list) else declared(registry)
    except ScheduleError:
        return None
    return next((s for s in schedules if is_alerts_pass(s) and s.here(here)
                 and (project is None or s.project == project)), None)


def limit_of(s: Schedule) -> float:
    """How long the pass may stay silent: two cadences and a grace (a tenth of one, 1 to 15 minutes)."""
    return 2 * s.cadence() + min(max(s.cadence() / 10, 60), 900)


def _silent(s: Schedule, rec: dict, lp: dict, last: datetime | None, now: datetime) -> bool:
    """Whether the installed pass missed two cadences of awake time since the later of its last pass and its install
    (an old pass run by hand never makes a new install SILENT; a machine asleep or off misses no pass)."""
    armed = _ts(rec.get("at"))
    since, ref = max(((t, c) for t, c in ((last, lp.get("clock")), (armed, rec.get("clock"))) if t),
                     key=lambda tc: tc[0], default=(None, None))
    if since is None:
        return True
    if (now - since).total_seconds() <= limit_of(s):
        return False
    awake = _awake_since(ref)
    return awake is None or awake > limit_of(s)


def watch(registry: Mapping[str, projects.Project] | list, *, here: str | None = None,
          now: datetime | None = None, project: str | None = None) -> dict | None:
    """The alerts pass declared for this machine (``project``: only that project's): {schedule, project, every,
    installed, last, silent, unset, line}; None when none is declared here or the declaration is bad."""
    s = _alerts_pass(registry, here or machine(), project)
    if s is None:
        return None
    now = now or datetime.now(timezone.utc)
    rec = installed().get(s.name)
    lp = last_pass()
    last = _ts(lp["at"]) if lp.get("at") else None
    silent = bool(rec) and _silent(s, rec, lp, last, now)
    unset = [str(v) for v in lp.get("unset") or []] if rec else []
    line = _pass_line(s, rec, last, silent, now)
    if unset:
        line += f"; nothing sent: ${', $'.join(unset)} not set (brain notify setup ntfy)"
    return {"schedule": s.name, "project": s.project, "every": s.cadence(), "installed": bool(rec),
            "last": lp.get("at"), "silent": silent, "unset": unset, "line": line}


def hook_line(registry: Mapping[str, projects.Project]) -> str:
    """The SessionStart health hook's line: only when the installed alerts pass is silent."""
    w = watch(registry)
    return f"The alerts pass is silent on this machine: {w['line']}" if w and w["silent"] else ""


def main(cmd: str, apply: bool, root: Path | None, as_json: bool = False) -> int:
    registry = projects.load(root)
    if cmd == "list":
        return listing(registry, as_json=as_json)
    return install(registry, apply, as_json=as_json)

