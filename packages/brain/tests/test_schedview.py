"""wi-brain-schedule-settings: one view of every scheduled task of every project (brain schedule list, the cockpit's
Schedules page), a declared schedule's change routed to the file that declares it as a plan then --apply (brain
schedule set), the window (hidden or visible) and a collector's floor."""

import json
from pathlib import Path

import pytest

from brain import alerts, cli, projects, schedule, schedview, settings

PY = Path("C:/brain/venv/Scripts/pythonw.exe")
REGISTRY = """\
# the registry's own comment
demo:
  root: {root}
  schedules:
    alerts-pass: {{command: alerts --all --notify, every: 15m, at_logon: true}}  # keep me
    collect: {{command: timed collect, every: 15m, floor: 1h}}
    block:
      command: vault canary
      at: '07:30'
  alerts:
    scheduler: ['\\\\demo\\\\']
  notify:
    quiet_hours: "22:00-07:00"
"""
ROWS = [
    {"name": "demo-scan", "folder": "\\demo\\", "state": "Ready", "exe": "powershell.exe",
     "args": "-NoProfile -WindowStyle Hidden -File scan.ps1", "last_run": "2026-11-13T08:00:00Z", "last_result": 0,
     "triggers": [{"type": "MSFT_TaskTimeTrigger", "enabled": True, "interval": "PT15M", "duration": None}]},
    {"name": "demo-report", "folder": "\\demo\\", "state": "Disabled", "exe": "C:\\Python\\python.exe", "args": "r.py",
     "triggers": [{"type": "MSFT_TaskDailyTrigger", "enabled": True, "days": 1}]},
    {"name": "alerts-pass", "folder": "\\Brain\\", "state": "Ready", "exe": str(PY), "args": "-I -m brain alerts",
     "last_run": "2026-11-13T12:00:00Z", "last_result": 0, "triggers": []},
    # the project's own task named as a declared schedule: listed as found, its run never shown on the declared row
    {"name": "collect", "folder": "\\demo\\", "state": "Ready", "exe": "cmd.exe", "args": "/c c.bat",
     "last_run": "2026-11-01T00:00:00Z", "last_result": 1, "triggers": []},
]


@pytest.fixture
def reg(tmp_path, monkeypatch):
    root = tmp_path / "demo"
    root.mkdir()
    f = tmp_path / "projects.yaml"
    f.write_bytes(REGISTRY.format(root=root.as_posix()).replace("\n", "\r\n").encode("utf-8"))   # CRLF, kept
    monkeypatch.setenv("BRAIN_PROJECTS", str(f))
    monkeypatch.setattr(alerts, "_scheduler", lambda folders: (ROWS, ""))
    return f


def _text(f: Path) -> str:
    return f.read_bytes().decode("utf-8")


# --- the window and the floor ---

def test_visible_runs_the_console_interpreter_and_a_change_of_window_updates_the_task(tmp_path):
    hidden = schedule._entry("demo", "x", {"command": "alerts", "every": "15m"})
    visible = schedule._entry("demo", "x", {"command": "alerts", "every": "15m", "visible": True})
    assert (hidden.window(), visible.window()) == ("hidden", "visible")
    assert schedule._argv(hidden, PY)[0].endswith("pythonw.exe") and schedule._argv(visible, PY)[0].endswith(
        "python.exe") and not schedule._argv(visible, PY)[0].endswith("pythonw.exe")
    assert schedule._argv(visible, Path("/usr/bin/python3"))[0] == str(Path("/usr/bin/python3"))   # no window there
    win = schedule.Windows(lambda argv, **k: None, user="BOX\\ada")
    assert not win.same(win.wanted(hidden, PY), win.wanted(visible, PY))   # the next install updates it


@pytest.mark.parametrize("conf, error", [
    ({"command": "c", "every": "2h", "floor": "1h"}, "every 2h is slower than its floor 1h"),
    ({"command": "c", "at": "07:30", "floor": "1h"}, "no every is slower than its floor 1h"),
    ({"command": "c", "every": "15m", "floor": "2d"}, "floor is 1m to 1d"),
    ({"command": "c", "every": "15m", "visible": "yes"}, "visible is true or false"),
])
def test_a_collector_slower_than_its_floor_and_a_bad_window_are_refused(conf, error):
    with pytest.raises(schedule.ScheduleError, match=error):
        schedule._entry("demo", "x", conf)


def test_a_collector_at_or_under_its_floor_passes():
    s = schedule._entry("demo", "x", {"command": "c", "every": "1h", "floor": "1h"})
    assert s.floor == 3600 and schedule._entry("demo", "y", {"command": "c", "every": "5m", "floor": "1h"}).floor


# --- the view ---

@pytest.mark.parametrize("exe, args, window", [
    ("C:\\venv\\Scripts\\pythonw.exe", "-m x", "hidden"), ("powershell.exe", "-WindowStyle Hidden -File a.ps1",
                                                          "hidden"),
    ("powershell.exe", "-w hidden -File a.ps1", "hidden"), ("conhost.exe", "--headless cmd", "hidden"),
    ("powershell.exe", "-Win Hidden -File a.ps1", "hidden"),
    ("powershell.exe", "-File a.ps1", "visible"), ("", "", "?")])
def test_a_found_tasks_window_is_read_from_its_action(exe, args, window):
    assert schedview.window_of({"exe": exe, "args": args}) == window


def test_the_view_holds_declared_and_found_tasks_with_their_settings(reg):
    rows, why = schedview.rows(projects.load(), here="box1")
    assert why == ""
    assert [(r["kind"], r["name"]) for r in rows] == [
        ("declared", "alerts-pass"), ("declared", "collect"), ("declared", "block"), ("found", "demo-scan"),
        ("found", "demo-report"), ("found", "collect")]   # alerts-pass once: \Brain\ holds the declared ones
    by = {(r["kind"], r["name"]): r for r in rows}
    assert by[("declared", "collect")]["last_run"] is None and by[("found", "collect")]["last_result"] == 1


def test_each_row_carries_its_settings(reg):
    rows, _ = schedview.rows(projects.load(), here="box1")
    by = {r["name"]: r for r in rows if r["kind"] == "declared" or r["name"] != "collect"}
    a = by["alerts-pass"]
    assert a["kind"] == "declared" and a["window"] == "hidden" and a["enabled"] and a["quiet"] == "22:00-07:00"
    assert a["last_run"] == "2026-11-13T12:00:00Z" and a["source"].endswith("projects.yaml: demo.schedules.alerts-pass")
    assert by["collect"]["floor"] == 3600 and "collector, floor 1h" in schedview.settings_line(by["collect"])
    scan, report = by["demo-scan"], by["demo-report"]
    assert scan["kind"] == "found" and scan["when"] == "every 15m" and scan["window"] == "hidden"
    assert report["enabled"] is False and report["window"] == "visible" and report["when"] == "every 1d"
    assert "where demo registers it" in scan["change"]
    assert "quiet 22:00-07:00 (notifications held, the task runs)" in schedview.settings_line(a)


def test_an_unreadable_scheduler_is_said_and_the_declared_rows_stay(reg, monkeypatch, capsys):
    monkeypatch.setattr(alerts, "_scheduler", lambda folders: ([], "the scheduler could not be read: denied"))
    assert cli.main(["schedule", "list"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("alerts-pass (demo): brain alerts --all --notify, every 15m and at logon: ")
    assert "note     the scheduler's own tasks are not shown: the scheduler could not be read: denied" in out
    assert "demo-scan" not in out


def test_cli_list_json_gives_the_declared_and_the_found(reg, capsys):
    assert cli.main(["schedule", "list", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert [s["name"] for s in out["schedules"]] == ["alerts-pass", "collect", "block"]
    assert {r["name"] for r in out["found"]} == {"demo-scan", "demo-report", "collect"} and out["scheduler"] == "read"


def test_a_folder_two_projects_name_lists_its_tasks_once(reg, monkeypatch):
    text = reg.read_bytes().decode("utf-8") + "other:\r\n  root: .\r\n  alerts:\r\n    scheduler: ['\\\\demo\\\\']\r\n"
    reg.write_bytes(text.encode("utf-8"))
    rows, _ = schedview.rows(projects.load(), here="box1")
    found = [(r["project"], r["name"]) for r in rows if r["kind"] == "found"]
    assert sorted(n for _, n in found) == ["collect", "demo-report", "demo-scan"]
    assert {p for p, _ in found} == {"demo"}


def test_the_cockpit_page_lists_the_declared_and_reads_no_scheduler(reg, monkeypatch):
    monkeypatch.setattr(alerts, "_scheduler", lambda folders: pytest.fail("the page read the scheduler"))
    rows = settings.collect(pages=("schedules",))["schedules"]
    keys = [r.key for r in rows]
    assert keys == ["alerts-pass", "collect", "block", "found tasks"]
    assert rows[0].change.startswith("brain schedule set alerts-pass ") and "install --apply" in rows[0].change
    assert settings.page_label("schedules") in ("Schedules", "Tâches planifiées")


# --- the change ---

def test_set_plans_then_writes_the_one_line_keeping_comments_and_line_endings(reg, capsys):
    before = _text(reg)
    assert cli.main(["schedule", "set", "alerts-pass", "--every", "30m", "--visible"]) == 0
    out = capsys.readouterr().out
    assert "  - alerts-pass: {command: alerts --all --notify, every: 15m, at_logon: true}  # keep me" in out
    assert "  + alerts-pass: {command: alerts --all --notify, every: 30m, at_logon: true, visible: true}  # keep me" \
        in out and "plan only" in out
    assert _text(reg) == before
    assert cli.main(["schedule", "set", "alerts-pass", "--every", "30m", "--visible", "--apply"]) == 0
    assert "written" in capsys.readouterr().out
    after = _text(reg)
    assert after.count("\r\n") == before.count("\r\n") and "# the registry's own comment" in after
    s = {x.name: x for x in schedule.declared(projects.load())}["alerts-pass"]
    assert s.every == 1800 and s.visible and s.at_logon
    assert cli.main(["schedule", "set", "alerts-pass", "--hidden", "--every", "15m", "--apply"]) == 0   # back
    assert _text(reg) == before


def test_set_at_days_and_none_render_as_yaml_reads_them(reg, capsys):
    assert cli.main(["schedule", "set", "alerts-pass", "--at", "07:05", "--days", "mon,fri", "--every", "none",
                     "--apply"]) == 0
    s = {x.name: x for x in schedule.declared(projects.load())}["alerts-pass"]
    assert (s.every, s.at, s.days) == (None, "07:05", ["mon", "fri"])
    assert "at: '07:05', days: [mon, fri]" in _text(reg)


def test_a_collectors_floor_refuses_a_slower_every_and_a_disable(reg, capsys):
    before = _text(reg)
    assert cli.main(["schedule", "set", "collect", "--every", "2h", "--apply"]) == 2
    assert "slower than its floor 1h" in capsys.readouterr().err
    assert cli.main(["schedule", "set", "collect", "--disable", "--apply"]) == 2
    assert "its data cannot be recovered" in capsys.readouterr().err
    assert _text(reg) == before
    assert cli.main(["schedule", "set", "collect", "--every", "30m", "--apply"]) == 0   # faster: fine


def test_a_block_entry_an_unknown_or_found_name_and_no_change_write_nothing(reg, capsys):
    before = _text(reg)
    assert cli.main(["schedule", "set", "block", "--at", "08:00", "--apply"]) == 1
    assert "not a one-line entry of projects.yaml: change it by hand (at: '08:00')" in capsys.readouterr().out
    assert cli.main(["schedule", "set", "demo-scan", "--every", "1h"]) == 2
    assert "no declared schedule 'demo-scan'" in capsys.readouterr().err
    assert cli.main(["schedule", "set", "alerts-pass"]) == 2
    assert "nothing to change" in capsys.readouterr().err
    assert cli.main(["schedule", "set", "alerts-pass", "--every", "2d"]) == 2   # the schedule's own checks
    assert "every is 1m to 1d" in capsys.readouterr().err
    assert _text(reg) == before


def test_a_project_schedules_file_is_the_one_written(tmp_path, monkeypatch, capsys):
    root = tmp_path / "app"
    root.mkdir()
    (root / "schedules.yaml").write_text("# app's schedules\nnightly: {command: refresh --all, at: '02:00'}\n",
                                         encoding="utf-8")
    f = tmp_path / "projects.yaml"
    f.write_text(f"app:\n  root: {root.as_posix()}\n  schedules: schedules.yaml\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(f))
    monkeypatch.setattr(alerts, "_scheduler", lambda folders: ([], ""))
    assert cli.main(["schedule", "set", "nightly", "--disable", "--apply", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["written"] and Path(out["file"]) == root / "schedules.yaml" and out["line"] == 2
    assert (root / "schedules.yaml").read_text(encoding="utf-8") == (
        "# app's schedules\nnightly: {command: refresh --all, at: '02:00', enabled: false}\n")
    assert f.read_text(encoding="utf-8").endswith("schedules: schedules.yaml\n")
    rows, _ = schedview.rows(projects.load(), here="box1", live=False)
    assert rows[0]["source"].endswith("schedules.yaml: nightly") and rows[0]["enabled"] is False


def test_a_name_that_appears_in_another_block_is_not_the_line_rewritten(tmp_path, monkeypatch, capsys):
    root = tmp_path / "demo"
    root.mkdir()
    f = tmp_path / "projects.yaml"
    f.write_text(f"demo:\n  root: {root.as_posix()}\n  alerts:\n    tasks:\n      pass: {{missed: 1}}\n"
                 "  schedules:\n    pass: {command: alerts --all, every: 15m}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(f))
    monkeypatch.setattr(alerts, "_scheduler", lambda folders: ([], ""))
    assert cli.main(["schedule", "set", "pass", "--every", "5m", "--apply"]) == 0
    text = f.read_text(encoding="utf-8")
    assert "pass: {missed: 1}" in text and "pass: {command: alerts --all, every: 5m}" in text


# --- review of wi-brain-schedule-settings ---

def _one(tmp_path, monkeypatch, entries: str) -> Path:
    root = tmp_path / "demo"
    root.mkdir(exist_ok=True)
    f = tmp_path / "projects.yaml"
    f.write_text(f"demo:\n  root: {root.as_posix()}\n{entries}", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(f))
    monkeypatch.setattr(alerts, "_scheduler", lambda folders: ([], ""))
    return f


def test_a_brace_in_the_comment_stays_the_comment(tmp_path, monkeypatch):
    f = _one(tmp_path, monkeypatch, "  schedules:\n    x: {command: alerts, every: 15m}  # see {y}\n")
    assert cli.main(["schedule", "set", "x", "--every", "1h", "--apply"]) == 0
    assert f.read_text(encoding="utf-8").endswith("    x: {command: alerts, every: 1h}  # see {y}\n")


@pytest.mark.parametrize("line, after", [
    ("x: {command: alerts, machines: [o'brien-pc], every: 15m}",
     "x: {command: alerts, machines: [o'brien-pc], every: 1h}"),   # an apostrophe inside a word opens no quote
    ('x: {command: alerts, "every": 15m}', "x: {command: alerts, every: 1h}"),   # a quoted key is the same key
    ("x: {command: 'a, b', every: 15m}", "x: {command: 'a, b', every: 1h}")])
def test_quotes_and_quoted_keys_are_read_as_yaml_reads_them(tmp_path, monkeypatch, line, after):
    f = _one(tmp_path, monkeypatch, f"  schedules:\n    {line}\n")
    assert cli.main(["schedule", "set", "x", "--every", "1h", "--apply"]) == 0
    assert f.read_text(encoding="utf-8").endswith(f"    {after}\n")


def test_a_key_twice_once_rewritten_is_changed_by_hand(monkeypatch):
    monkeypatch.setattr(schedview, "_split_flow", lambda inner: ["command: alerts", "every: 15m", "'every': 5m"])
    assert schedview._rewrite("    x: {command: alerts, every: 15m}\n", "x", {"every": "1h"}) is None


def test_a_change_to_the_same_values_writes_nothing_and_touches_no_other_line(tmp_path, monkeypatch, capsys):
    f = _one(tmp_path, monkeypatch, "  alerts:\n    tasks:\n      x: {every: 1h,ledger: a}\n"
                                    "  schedules:\n    x: {command: alerts, every: 15m}\n")
    before = f.read_text(encoding="utf-8")
    assert cli.main(["schedule", "set", "x", "--enable", "--hidden", "--apply"]) == 0
    assert "already has these values: nothing to write" in capsys.readouterr().out
    assert f.read_text(encoding="utf-8") == before


def test_a_name_of_digits_is_found(tmp_path, monkeypatch):
    f = _one(tmp_path, monkeypatch, "  schedules:\n    2024: {command: alerts, every: 15m}\n")
    assert cli.main(["schedule", "set", "2024", "--every", "1h", "--apply"]) == 0
    assert "2024: {command: alerts, every: 1h}" in f.read_text(encoding="utf-8")


def test_a_refusal_in_json_is_json_and_an_empty_value_is_refused(tmp_path, monkeypatch, capsys):
    _one(tmp_path, monkeypatch, "  schedules:\n    x: {command: alerts, every: 15m}\n")
    assert cli.main(["schedule", "set", "nope", "--every", "1h", "--json"]) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["written"] is False and "no declared schedule 'nope'" in out["error"]
    assert cli.main(["schedule", "set", "x", "--every", ""]) == 2
    assert "--every: a value, or none to remove it" in capsys.readouterr().err


def test_the_newer_keys_are_said_to_need_every_machine_on_0_5_1(tmp_path, monkeypatch, capsys):
    f = _one(tmp_path, monkeypatch, "  schedules:\n    x: {command: alerts, every: 15m}\n")
    assert cli.main(["schedule", "set", "x", "--visible", "--apply"]) == 0
    out = capsys.readouterr().out
    assert "note     every machine that reads this file must run brain 0.5.1 or later" in out
    assert not list(tmp_path.glob(".projects.yaml.*"))   # the temporary file renamed over it
    assert cli.main(["schedule", "set", "x", "--hidden", "--every", "30m"]) == 0
    assert "note" not in capsys.readouterr().out   # no newer key left in the entry
    assert "visible: true" in f.read_text(encoding="utf-8")
