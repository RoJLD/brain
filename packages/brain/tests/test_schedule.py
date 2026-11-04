"""wi-brain-alerts-pass: the registry's schedules (the alerts pass every 15 minutes and at logon), installed by brain
schedule install as a plan then --apply (the Task Scheduler, a systemd user timer, the crontab), the installer's
schedule step, the alerts pass's dead-man (the SessionStart health hook, brain status's row) and the pass that sends
nothing without its channel's variable."""

import io
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import pytest

from brain import alerts, cli, notify, projects, schedule, stacks, status

from test_notify import ENV, Fake

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
PASS = "alerts-pass: {command: alerts --all --notify, every: 15m, at_logon: true}"
CANARY = "vault-canary: {command: [vault, canary], at: '07:30', machines: [ada-laptop]}"
PY = Path("C:/brain/venv/Scripts/pythonw.exe")


def _registry(tmp_path, monkeypatch, *entries, notify_entry="", alerts_entry=""):
    root = tmp_path / "demo"
    root.mkdir(exist_ok=True)
    text = f"demo:\n  root: {root.as_posix()}\n"
    if entries:
        text += "  schedules:\n" + "".join(f"    {e}\n" for e in entries)
    if alerts_entry:
        text += f"  alerts: {alerts_entry}\n"
    if notify_entry:
        text += "  notify:\n" + "".join(f"    {line}\n" for line in notify_entry.strip("\n").splitlines())
    reg = tmp_path / "projects.yaml"
    reg.write_text(text, encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    return projects.load()


class Runs:
    """A scheduler's commands recorded; answers by the program and its first argument."""

    def __init__(self, answers=None):
        self.calls, self.answers = [], dict(answers or {})

    def __call__(self, argv, *, input=None, timeout=None):
        self.calls.append((list(argv), input))
        for key, ans in self.answers.items():
            if " ".join(argv).startswith(key):
                code, out = ans() if callable(ans) else ans
                return subprocess.CompletedProcess(argv, code, out, "" if code == 0 else "not found")
        return subprocess.CompletedProcess(argv, 0, "", "")


# --- the declaration ---

def test_a_schedule_is_parsed_with_its_defaults(tmp_path, monkeypatch):
    reg = _registry(tmp_path, monkeypatch, PASS, CANARY)
    s, c = schedule.declared(reg)
    assert (s.name, s.project, s.command, s.every, s.at_logon, s.timeout) == \
        ("alerts-pass", "demo", ["alerts", "--all", "--notify"], 900.0, True, 600.0)
    assert s.when() == "every 15m and at logon" and s.here("anywhere") and schedule.is_alerts_pass(s)
    assert c.command == ["vault", "canary"] and c.when() == "daily at 07:30"
    assert c.here("ada-laptop") and not c.here("orbit-test") and not schedule.is_alerts_pass(c)
    assert projects.check() == [] and schedule.check(reg) == []


@pytest.mark.parametrize("entry, error", [
    ("x: {command: alerts, every: 15m, colour: red}", "unknown key(s) colour"),
    ("x: {every: 15m}", "command, the brain command's arguments, is missing"),
    ("x: {command: brain alerts, every: 15m}", "without brain itself"),
    ("x: {command: alerts, every: soon}", "'soon' is not a duration"),
    ("x: {command: alerts, every: 30s}", "every is 1m to 1d"),
    ("x: {command: alerts, at: '7h30'}", "at is a daily time HH:MM"),
    ("x: {command: alerts}", "every, at or at_logon says when it runs"),
    ("Bad_Name: {command: alerts, every: 1h}", "a name of lowercase letters"),
])
def test_a_bad_schedule_is_refused_by_brain_check(tmp_path, monkeypatch, entry, error):
    reg = _registry(tmp_path, monkeypatch, entry)
    errors = schedule.check(reg)
    assert len(errors) == 1 and error in errors[0], errors


def test_schedule_names_are_global(tmp_path, monkeypatch):
    reg = tmp_path / "projects.yaml"
    for n in ("a", "b"):
        (tmp_path / n).mkdir()
    reg.write_text(f"a:\n  root: {(tmp_path / 'a').as_posix()}\n  schedules: {{p: {{command: alerts, every: 1h}}}}\n"
                   f"b:\n  root: {(tmp_path / 'b').as_posix()}\n  schedules: {{p: {{command: digest, every: 1d}}}}\n",
                   encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    assert schedule.check(projects.load()) == ["schedule p: declared by a and b (names are global)"]


# --- the Task Scheduler ---

def _win(runs, day=datetime(2026, 11, 3, 9, 0)):
    return schedule.Windows(runs, user="DEMO\\ada", today=day)


def test_the_windows_task_runs_as_the_user_every_15_minutes_and_at_logon(tmp_path, monkeypatch):
    s = schedule.declared(_registry(tmp_path, monkeypatch, PASS))[0]
    xml = _win(Runs()).wanted(s, PY)
    assert "<LogonTrigger><Enabled>true</Enabled><UserId>DEMO\\ada</UserId></LogonTrigger>" in xml
    assert "<Interval>PT15M</Interval>" in xml and "<StopAtDurationEnd>false</StopAtDurationEnd>" in xml
    assert "<LogonType>InteractiveToken</LogonType>" in xml and "<RunLevel>LeastPrivilege</RunLevel>" in xml
    assert "<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>" in xml
    assert "<StartWhenAvailable>true</StartWhenAvailable>" in xml and "<ExecutionTimeLimit>PT10M</ExecutionTimeLimit>" in xml
    assert f"<Command>{PY}</Command>" in xml and "<Arguments>-I -m brain alerts --all --notify</Arguments>" in xml
    assert "<Description>brain schedule: alerts-pass (demo): brain alerts --all --notify, every 15m and at logon" in xml
    # the start day changes every day: it never makes an installed task look different
    assert _win(Runs()).same(xml, _win(Runs(), datetime(2027, 1, 9)).wanted(s, PY))
    canary = schedule.Schedule("c", "demo", ["vault", "canary"], at="07:30")
    cx = _win(Runs()).wanted(canary, PY)
    assert "<CalendarTrigger><StartBoundary>2026-11-03T07:30:00</StartBoundary>" in cx and "LogonTrigger" not in cx
    assert not _win(Runs()).same(cx, _win(Runs()).wanted(schedule.Schedule("c", "demo", ["vault", "canary"],
                                                                            at="08:00"), PY))


def test_the_plan_creates_then_finds_the_same_task_and_the_apply_records_it(tmp_path, monkeypatch, capsys):
    reg = _registry(tmp_path, monkeypatch, PASS)
    live = {"xml": None}

    def query():
        return (0, live["xml"]) if live["xml"] else (1, "")

    def create():
        return 0, ""
    runs = Runs({"schtasks /Query": query, "schtasks /Create": create})
    win = _win(runs)
    monkeypatch.setattr(schedule, "system", lambda run=None: win)
    monkeypatch.setattr(schedule, "interpreter", lambda: PY)
    assert schedule.install(reg, here="ada-desktop") == 0
    out = capsys.readouterr().out
    assert out.startswith("create   schedule alerts-pass: brain alerts --all --notify, every 15m and at logon "
                          "(\\Brain\\alerts-pass) (to do: --apply)")
    assert not [c for c in runs.calls if "/Create" in c[0]] and not schedule.record_file().exists()  # a plan only
    original = schedule.Windows.write

    def write(self, s, want):
        live["xml"] = want
        return original(self, s, want)
    monkeypatch.setattr(schedule.Windows, "write", write)
    assert schedule.install(reg, apply=True, here="ada-desktop") == 0
    assert "(done)" in capsys.readouterr().out
    create_call = next(c[0] for c in runs.calls if "/Create" in c[0])
    assert create_call[:4] == ["schtasks", "/Create", "/TN", "\\Brain\\alerts-pass"] and create_call[-1] == "/F"
    assert not Path(create_call[5]).exists()  # the XML file is removed after the call
    rec = schedule.installed()["alerts-pass"]
    assert rec["where"] == "\\Brain\\alerts-pass" and rec["system"] == "the Task Scheduler"
    assert schedule.install(reg, here="ada-desktop") == 0
    assert capsys.readouterr().out.startswith("same     schedule alerts-pass")


def test_a_schedule_no_longer_declared_is_removed_and_a_hand_made_task_never(tmp_path, monkeypatch, capsys):
    reg = _registry(tmp_path, monkeypatch, PASS.replace("at_logon: true", "at_logon: true, enabled: false"))
    runs = Runs({"schtasks /Query": (1, ""), "schtasks /Delete": (0, "")})
    monkeypatch.setattr(schedule, "system", lambda run=None: _win(runs))
    schedule.record_file().parent.mkdir(parents=True)
    schedule.record_file().write_text(json.dumps({"alerts-pass": {"where": "\\Brain\\alerts-pass"}}), encoding="utf-8")
    assert schedule.install(reg, apply=True, here="ada-desktop") == 0
    out = capsys.readouterr().out
    assert out.startswith("remove   schedule alerts-pass (\\Brain\\alerts-pass): no longer declared for this machine "
                          "(done)")
    assert ["schtasks", "/Delete", "/TN", "\\Brain\\alerts-pass", "/F"] in [c[0] for c in runs.calls]
    assert schedule.installed() == {}
    # a task under \Brain\ the brain never recorded (the vault canary registered by hand) is not touched
    assert schedule.install(reg, apply=True, here="ada-desktop") == 0
    assert "none declared" in capsys.readouterr().out and len([c for c in runs.calls if "/Delete" in c[0]]) == 1


def test_a_failed_apply_says_why_and_exits_1(tmp_path, monkeypatch, capsys):
    reg = _registry(tmp_path, monkeypatch, PASS)
    runs = Runs({"schtasks /Query": (1, ""), "schtasks /Create": (1, "")})
    monkeypatch.setattr(schedule, "system", lambda run=None: _win(runs))
    assert schedule.install(reg, apply=True, here="ada-desktop") == 1
    assert "(failed: not found)" in capsys.readouterr().out and "alerts-pass" not in schedule.installed()


def test_a_bad_declaration_exits_2(tmp_path, monkeypatch, capsys):
    reg = _registry(tmp_path, monkeypatch, "x: {command: alerts}")
    assert schedule.install(reg) == 2
    assert capsys.readouterr().err.startswith("brain schedule: project demo: schedules x:")


# --- Linux: a systemd user timer, else the crontab ---

def test_the_systemd_timer_runs_through_a_login_shell(tmp_path, monkeypatch):
    s = schedule.declared(_registry(tmp_path, monkeypatch, PASS))[0]
    folder = tmp_path / "units"
    runs = Runs({"systemctl --user is-enabled": (0, "enabled\n"), "loginctl": (0, "no\n")})
    sd = schedule.Systemd(runs, folder=folder, user="ada")
    want = sd.wanted(s, PurePosixPath("/opt/demo/venv/bin/python"))
    assert "ExecStart=/bin/bash -lc \"exec /opt/demo/venv/bin/python -I -m brain alerts --all --notify\"" \
        in want["service"]
    assert "Type=oneshot" in want["service"] and "TimeoutStartSec=600" in want["service"]
    assert "OnStartupSec=1min\nOnActiveSec=1min\nOnUnitActiveSec=15m\n" in want["timer"]
    assert "WantedBy=timers.target" in want["timer"] and sd.current(s.name) is None
    assert sd.write(s, want) == ""
    assert (folder / "brain-alerts-pass.timer").read_text(encoding="utf-8") == want["timer"]
    assert [c[0] for c in runs.calls][-2:] == [["systemctl", "--user", "daemon-reload"],
                                              ["systemctl", "--user", "enable", "--now", "brain-alerts-pass.timer"]]
    assert sd.same(sd.current(s.name), want)
    assert sd.notes([s]) == ["linger off for ada: the timers run only while ada is logged in; on a machine that stays "
                             "on, loginctl enable-linger ada (yours, once) keeps them running"]
    assert sd.delete(s.name) == "" and not list(folder.iterdir())
    daily = sd.wanted(schedule.Schedule("c", "demo", ["vault", "canary"], at="07:30"), PurePosixPath("/py"))
    assert "OnCalendar=*-*-* 07:30:00\nPersistent=true\n" in daily["timer"] and "OnActiveSec" not in daily["timer"]


def test_a_timer_not_enabled_is_not_the_same(tmp_path, monkeypatch):
    s = schedule.declared(_registry(tmp_path, monkeypatch, PASS))[0]
    sd = schedule.Systemd(Runs({"systemctl --user is-enabled": (1, "disabled\n")}), folder=tmp_path / "u")
    want = sd.wanted(s, PurePosixPath("/py"))
    sd.folder.mkdir()
    for k, text in want.items():
        (sd.folder / f"brain-alerts-pass.{k}").write_text(text, encoding="utf-8")
    assert not sd.same(sd.current(s.name), want)


def test_the_crontab_keeps_the_other_lines(tmp_path, monkeypatch):
    s = schedule.declared(_registry(tmp_path, monkeypatch, PASS))[0]
    tab = {"text": "0 3 * * * backup.sh\n"}

    def read():
        return 0, tab["text"]
    runs = Runs({"crontab -l": read})
    cron = schedule.Cron(runs)
    want = cron.wanted(s, PurePosixPath("/opt/demo/venv/bin/python"))
    assert want == ["*/15 * * * * /bin/bash -lc 'exec /opt/demo/venv/bin/python -I -m brain alerts --all "
                    "--notify' # brain schedule alerts-pass",
                    "@reboot /bin/bash -lc 'exec /opt/demo/venv/bin/python -I -m brain alerts --all --notify' "
                    "# brain schedule alerts-pass"]
    assert cron.current(s.name) is None and cron.write(s, want) == ""
    written = runs.calls[-1]
    assert written[0] == ["crontab", "-"] and written[1] == "0 3 * * * backup.sh\n" + "\n".join(want) + "\n"
    tab["text"] = written[1]
    assert cron.same(cron.current(s.name), want) and cron.delete(s.name) == ""
    assert runs.calls[-1][1] == "0 3 * * * backup.sh\n"
    assert schedule._cron_when(schedule.Schedule("h", "d", ["x"], every=7200.0)) == ["0 */2 * * *"]
    with pytest.raises(schedule.ScheduleError, match="no crontab form"):
        schedule._cron_when(schedule.Schedule("odd", "d", ["x"], every=420.0))


def test_the_system_is_chosen_by_what_runs_here(monkeypatch):
    monkeypatch.setattr(schedule.shutil, "which", lambda n: f"/usr/bin/{n}")
    assert isinstance(schedule.system(Runs(), "win32"), schedule.Windows)
    assert isinstance(schedule.system(Runs(), "linux"), schedule.Systemd)
    assert isinstance(schedule.system(Runs({"systemctl --user show-environment": (1, "")}), "linux"), schedule.Cron)
    assert schedule.system(Runs(), "darwin") is None
    monkeypatch.setattr(schedule.sys, "platform", "darwin")
    steps = schedule.plan([schedule.Schedule("p", "d", ["alerts"], every=900.0)], "mac", None, record={})
    assert steps[0].action == "note" and "no scheduler supported here yet (darwin)" in steps[0].line


# --- the dead-man ---

def _state(tmp_path, at=None, unset=()):
    d = tmp_path / "brain-home" / "alerts"
    d.mkdir(parents=True, exist_ok=True)
    data = {"demo": {"open": {}, "last_pass": at}}
    if at:
        data["_pass"] = {"at": at, "host": "demo-host", "unset": list(unset)}
    (d / "state.json").write_text(json.dumps(data), encoding="utf-8")


def _installed(at="2026-11-03T10:00:00+00:00"):
    schedule.record_file().parent.mkdir(parents=True, exist_ok=True)
    schedule.record_file().write_text(json.dumps({"alerts-pass": {"at": at}}), encoding="utf-8")


def test_the_dead_man_is_silent_after_two_cadences(tmp_path, monkeypatch):
    reg = _registry(tmp_path, monkeypatch, PASS)
    w = schedule.watch(reg, here="ada-desktop", now=NOW)
    assert w["line"] == "alerts-pass declared for this machine, not installed (install.ps1 -Apply)"
    assert not w["silent"] and schedule.hook_line(reg) == ""
    _installed()
    _state(tmp_path, "2026-11-03T11:40:00Z")
    w = schedule.watch(reg, here="ada-desktop", now=NOW)
    assert not w["silent"] and w["line"] == "alerts-pass every 15m, last 20 min ago"
    _state(tmp_path, "2026-11-03T11:20:00Z")   # 40 minutes: two cadences and a grace of 90 s are gone
    w = schedule.watch(reg, here="ada-desktop", now=NOW)
    assert w["silent"] and w["line"].startswith("SILENT: alerts-pass last passed 40 min ago, every 15m")
    _state(tmp_path)
    _installed("2026-11-03T11:50:00+00:00")     # installed 10 minutes ago, no pass yet: not silent yet
    assert not schedule.watch(reg, here="ada-desktop", now=NOW)["silent"]
    _installed("2026-11-03T09:00:00+00:00")
    assert schedule.watch(reg, here="ada-desktop", now=NOW)["line"].startswith("SILENT: alerts-pass never passed")
    assert schedule.watch(_registry(tmp_path, monkeypatch, CANARY), here="ada-laptop") is None  # no alerts pass


def test_the_hook_and_the_status_row_say_the_pass_is_silent(tmp_path, monkeypatch, capsys):
    reg = _registry(tmp_path, monkeypatch, PASS)
    _installed("2026-11-01T10:00:00+00:00")
    _state(tmp_path, "2026-11-01T10:00:00Z", unset=["BRAIN_NTFY_TOPIC"])
    assert schedule.hook_line(reg).startswith("The alerts pass is silent on this machine: SILENT: alerts-pass last "
                                              "passed")
    assert stacks.hook_main(["SessionStart"], stdin=io.BytesIO(b"{}")) == 0
    out = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert "The alerts pass is silent on this machine" in out["additionalContext"]
    row = status.alerts_of(reg["demo"], {}, {}, {}, alerts.state_load())
    assert row["pass"]["silent"] and row["pass"]["unset"] == ["BRAIN_NTFY_TOPIC"]
    line = alerts.status_line(row)
    assert line.startswith("SILENT: alerts-pass last passed") and "nothing sent: $BRAIN_NTFY_TOPIC not set" in line
    assert line.endswith("none open; last notify pass 2026-11-01T10:00:00Z")
    assert schedule.listing(reg) == 0
    out = capsys.readouterr().out
    assert out.startswith("alerts-pass (demo): brain alerts --all --notify, every 15m and at logon: installed ")
    assert "alerts pass: SILENT" in out


# --- the pass without its channel's variable ---

NTFY = """\
channels:
  ntfy: {type: ntfy, server: https://ntfy.sh, topic_env: T_TOPIC}
levels: {warn: [ntfy], error: [ntfy]}
"""


def test_without_the_topic_a_pass_sends_nothing_and_says_so_once(tmp_path, monkeypatch):
    fake = Fake()
    monkeypatch.setattr(notify, "_post_json", fake.post)
    monkeypatch.setattr(alerts, "_now", lambda: NOW)
    reg = _registry(tmp_path, monkeypatch, alerts_entry="{files: [a.md]}", notify_entry=NTFY)
    p = reg["demo"]
    (p.root / "a.md").write_text("## 2026-11-03 — m\nWARN  m:x  bad\nFAIL  m:y  worse\n", encoding="utf-8")
    env = {k: v for k, v in ENV.items() if k != "T_TOPIC"}
    lines = alerts.notify_pass(alerts.run([p], quick=True), reg, env=env)
    assert lines == ["demo: 2 open, 2 new, risen or retried, 0 resolved",
                     "nothing sent: $T_TOPIC not set (brain notify setup ntfy); the alerts wait for the first pass "
                     "that finds it"]
    st = alerts.state_load()
    assert {k: v["sent"] for k, v in st["demo"]["open"].items()} == {"m:x": "unset", "m:y": "unset"}
    assert {k: v for k, v in st["_pass"].items() if k not in ("host", "clock")} ==         {"at": "2026-11-03T12:00:00Z", "unset": ["T_TOPIC"]}
    assert not fake.posts and not (tmp_path / "brain-home" / "notify").exists()  # no audit line either
    lines = alerts.notify_pass(alerts.run([p], quick=True), reg, env=ENV)   # the topic is set: both go
    assert sorted(lines[:2]) == ["demo: error m:y: delivered", "demo: warn m:x: delivered"] and len(fake.posts) == 2
    assert alerts.state_load()["_pass"]["unset"] == []


def test_the_scheduler_is_skipped_off_windows(tmp_path, monkeypatch):
    reg = _registry(tmp_path, monkeypatch, alerts_entry="{scheduler: ['\\\\demo\\\\']}")
    monkeypatch.setattr(alerts, "_scheduler", lambda folders: ([], alerts.OFF_WINDOWS))
    cfg = alerts.config(reg["demo"])
    assert alerts.read_scheduler([cfg]) == {}
    assert alerts.scheduler_alerts(cfg, {}, [], NOW) == []   # no warn alert on a Linux machine


# --- the CLI and the installer's step ---

def test_cli_schedule_install_and_list(tmp_path, monkeypatch, capsys):
    _registry(tmp_path, monkeypatch, PASS)
    monkeypatch.setattr(schedule, "system", lambda run=None: _win(Runs({"schtasks /Query": (1, "")})))
    assert cli.main(["schedule", "install", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["applied"] is False and out["steps"][0]["action"] == "create"
    assert cli.main(["schedule", "list", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["schedules"][0]["name"] == "alerts-pass" and out["alerts_pass"]["installed"] is False


INSTALLER = Path(cli.__file__).parents[2] / "installer" / "install.ps1"


def _schedule_block() -> str:
    text = INSTALLER.read_text(encoding="utf-8")
    return text[text.index("# --- the schedule step"):text.index("# --- end of the schedule step")] + \
        "Set-Schedules\n"


@pytest.mark.skipif(sys.platform != "win32" or not shutil.which("powershell.exe"), reason="Windows PowerShell")
@pytest.mark.parametrize("python", ["venv", "none", "old", "bad"])
def test_installer_step(tmp_path, monkeypatch, python):
    """The plan only: an apply would register a real task on the machine that runs the tests."""
    name = f"brain-test-{tmp_path.name[-12:].lower().replace('_', '-')}"
    entry = f"{name}: {{command: alerts --all --notify, every: 15m}}" if python != "bad" else "x: {command: alerts}"
    _registry(tmp_path, monkeypatch, entry)
    old = tmp_path / "old.cmd"
    old.write_text("@echo off\r\nexit /b 2\r\n", encoding="utf-8")
    exe = {"venv": Path(sys.executable), "none": tmp_path / "absent.exe", "old": old, "bad": Path(sys.executable)}[
        python]
    script = tmp_path / "install.ps1"
    script.write_text("$ErrorActionPreference = 'Stop'\n"
                      f"$repo = '{tmp_path / 'demo'}'\n$venv_python = '{exe}'\n$Apply = $false\n"
                      + _schedule_block(), encoding="utf-8")
    res = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                         capture_output=True, text=True, timeout=120)
    assert res.returncode == 0, res.stdout + res.stderr
    if python == "none":
        assert "once the command is installed (-Apply)" in res.stdout
    elif python == "old":
        assert "no schedule subcommand yet" in res.stdout
    elif python == "bad":
        assert "brain schedule: project demo: schedules x" in res.stdout
    else:
        assert f"create   schedule {name}: brain alerts --all --notify, every 15m (\\Brain\\{name}) (to do: " \
               "--apply)" in res.stdout, res.stdout


# --- the review of #39: one regression test per high and medium finding ---

def test_a_session_cannot_apply_and_the_guard_refuses_it(tmp_path, monkeypatch, capsys):
    reg = _registry(tmp_path, monkeypatch, PASS)
    runs = Runs({"schtasks /Query": (1, ""), "schtasks /Create": (0, "")})
    monkeypatch.setattr(schedule, "system", lambda run=None: _win(runs))
    monkeypatch.setenv("CLAUDECODE", "1")
    assert schedule.install(reg, apply=True, here="ada-desktop") == 2
    out = capsys.readouterr()
    assert out.out.startswith("create   schedule alerts-pass") and "(to do: --apply)" in out.out   # the plan only
    assert out.err.startswith("brain schedule: install --apply refused: the actions are")
    assert not [c for c in runs.calls if "/Create" in c[0]] and not schedule.record_file().exists()
    monkeypatch.delenv("CLAUDECODE")
    from test_guards import bash

    from brain import guards
    monkeypatch.delenv(guards.ALLOW_ENV, raising=False)
    monkeypatch.setenv("BRAIN_PERMISSIONS", str(Path(__file__).parent / "fixtures" / "permissions.yaml"))
    for cmd in ("brain schedule install --apply", "python -I -m brain --root ~/b schedule install --apply"):
        reason = bash(tmp_path, cmd)
        assert reason and "owner:scheduled" in reason, cmd
    assert bash(tmp_path, "brain schedule install") is None and bash(tmp_path, "brain schedule list --json") is None


@pytest.mark.parametrize("entry", [
    'x: {command: [alerts, --all, --notify, "y\\n* * * * * touch /tmp/pwned #"], every: 15m}',
    "x: {command: \"alerts --notify 'y\\n*/5 * * * * id #'\", every: 15m}",
    'x: {command: [vault, "a\\tb"], at: "07:30"}',
])
def test_a_control_character_in_a_command_is_refused(tmp_path, monkeypatch, entry):
    errors = schedule.check(_registry(tmp_path, monkeypatch, entry))
    assert len(errors) == 1 and "command holds a control character" in errors[0], errors


def test_an_unbalanced_quote_is_a_bad_declaration_not_a_crash(tmp_path, monkeypatch):
    reg = _registry(tmp_path, monkeypatch, PASS, "canary: {command: notify send p info today's canary, at: '07:30'}")
    assert schedule.check(reg) == ["project demo: schedules canary: command: No closing quotation"]
    assert schedule.watch(reg, here="ada-desktop") is None and schedule.hook_line(reg) == ""
    row = status.alerts_of(reg["demo"], {}, {}, {}, {})   # brain status and the alerts pass go on
    assert "pass" not in row and row["open"] == 0
    (tmp_path / "demo" / "sched.yaml").write_text("x: [unclosed\n", encoding="utf-8")
    reg = _registry(tmp_path, monkeypatch, alerts_entry="{}")
    reg["demo"].schedules = "sched.yaml"
    assert schedule.check(reg)[0].startswith("project demo: schedules file sched.yaml: ")


def test_a_task_already_deleted_by_hand_is_removed_without_an_error(tmp_path, monkeypatch, capsys):
    reg = _registry(tmp_path, monkeypatch)
    runs = Runs({"schtasks /Delete": (1, ""), "schtasks /Query": (1, "")})
    monkeypatch.setattr(schedule, "system", lambda run=None: _win(runs))
    schedule.record_file().parent.mkdir(parents=True)
    schedule.record_file().write_text(json.dumps({"alerts-pass": {"where": "\\Brain\\alerts-pass",
                                                                  "system": "the Task Scheduler"}}), encoding="utf-8")
    assert schedule.install(reg, apply=True, here="ada-desktop") == 0
    assert "(done)" in capsys.readouterr().out and schedule.installed() == {}


def test_a_quoted_argument_and_a_dollar_read_back_the_same(tmp_path, monkeypatch):
    s = schedule.Schedule("c", "demo", ["vault", "canary", "--note", "daily check"], at="07:30")
    want = _win(Runs()).wanted(s, PY)
    assert "&quot;daily check&quot;" in want
    have = want.replace("&quot;", '"')   # the Task Scheduler writes a quote back as is
    assert _win(Runs()).same(have, want)
    unit = schedule.Systemd(Runs(), folder=tmp_path).wanted(
        schedule.Schedule("d", "demo", ["notify", "send", "p", "info", "a${HOME}b"], every=900.0), PurePosixPath("/py"))
    assert "a$${HOME}b" in unit["service"]


def test_a_schedule_recorded_under_another_scheduler_is_left_alone(tmp_path, monkeypatch):
    s = schedule.declared(_registry(tmp_path, monkeypatch, PASS))[0]
    runs = Runs({"crontab -l": (0, "")})
    record = {"alerts-pass": {"where": "~/.config/systemd/user/brain-alerts-pass.timer", "system": "systemd --user"},
              "gone": {"where": "x", "system": "systemd --user"}}
    for schedules in ([s], []):
        steps = schedule.plan(schedules, "orbit-test", schedule.Cron(runs), PurePosixPath("/py"), record)
        assert [st.action for st in steps if st.name] == ["note", "note"]   # kept, created or removed: neither
        assert "was installed with systemd --user" in steps[0].line and "nothing changed" in steps[0].line
    assert not [c for c in runs.calls if c[0] == ["crontab", "-"]]


def test_the_hook_keeps_each_report_when_the_other_fails(monkeypatch, capsys):
    monkeypatch.setattr(stacks, "load", lambda *a, **k: {})
    monkeypatch.setattr(stacks, "watched_down", lambda reg, *a: ["- web (demo): timed out"])
    monkeypatch.setattr(schedule, "hook_line", lambda reg: 1 / 0)
    stacks.hook_main(["SessionStart"], stdin=io.BytesIO(b"{}"))
    assert "1 watched stack(s) down" in json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]
    monkeypatch.setattr(stacks, "watched_down", lambda reg, *a: 1 / 0)
    monkeypatch.setattr(schedule, "hook_line", lambda reg: "The alerts pass is silent on this machine: SILENT")
    stacks.hook_main(["SessionStart"], stdin=io.BytesIO(b"{}"))
    assert "silent" in json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]


def test_downtime_is_no_silence_and_a_new_install_beats_an_old_pass(tmp_path, monkeypatch):
    reg = _registry(tmp_path, monkeypatch, PASS)
    _installed("2026-11-01T10:00:00+00:00")
    d = tmp_path / "brain-home" / "alerts"
    d.mkdir(parents=True, exist_ok=True)
    (d / "state.json").write_text(json.dumps({"_pass": {"at": "2026-11-03T03:00:00Z",   # 9 h before NOW, then sleep
                                                        "clock": {"boot": 1000, "awake": 5000}}}), encoding="utf-8")
    monkeypatch.setattr(schedule, "clock", lambda: {"boot": 1000, "awake": 5600})        # 10 min awake since
    assert not schedule.watch(reg, here="ada-desktop", now=NOW)["silent"]
    monkeypatch.setattr(schedule, "clock", lambda: {"boot": 1000, "awake": 5000 + 3000})  # 50 min awake: silent
    assert schedule.watch(reg, here="ada-desktop", now=NOW)["silent"]
    monkeypatch.setattr(schedule, "clock", lambda: {"boot": 40000, "awake": 120})         # rebooted 2 min ago
    assert not schedule.watch(reg, here="ada-desktop", now=NOW)["silent"]
    monkeypatch.setattr(schedule, "clock", lambda: {})                                    # no clock: wall time
    assert schedule.watch(reg, here="ada-desktop", now=NOW)["silent"]
    _installed("2026-11-03T11:55:00+00:00")    # armed 5 min ago, after an old pass run by hand
    assert not schedule.watch(reg, here="ada-desktop", now=NOW)["silent"]


def test_a_resolution_without_the_topic_is_not_a_failure(tmp_path, monkeypatch):
    fake = Fake()
    monkeypatch.setattr(notify, "_post_json", fake.post)
    monkeypatch.setattr(alerts, "_now", lambda: NOW)
    reg = _registry(tmp_path, monkeypatch, alerts_entry="{files: [a.md]}",
                    notify_entry=NTFY.replace("levels: {", "levels: {info: [ntfy], "))
    p = reg["demo"]
    (p.root / "a.md").write_text("## 2026-11-03 — m\nWARN  m:x  bad\n", encoding="utf-8")
    alerts.notify_pass(alerts.run([p], quick=True), reg, env=ENV)
    (p.root / "a.md").write_text("## 2026-11-03 — m\n", encoding="utf-8")
    env = {k: v for k, v in ENV.items() if k != "T_TOPIC"}
    lines = alerts.notify_pass(alerts.run([p], quick=True), reg, env=env)
    assert "demo: resolved m:x: unset" in lines and lines[-1].startswith("nothing sent: $T_TOPIC not set")
    assert len(fake.posts) == 1 and alerts.state_load()["_pass"]["unset"] == ["T_TOPIC"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows")
def test_schtasks_is_read_in_the_oem_code_page():
    assert schedule._oem().startswith("cp") and schedule.clock()["awake"] > 0
