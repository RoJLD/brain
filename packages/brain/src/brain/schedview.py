"""One view of every scheduled task of every project, and a change routed to the file that declares it
(wi-brain-schedule-settings; the owner's answers of 2026-11-09: one view in the Brain, each value in its project's
file, a plan then an apply).

**The view** (``brain schedule list``, the cockpit's Schedules settings page): each row a task, with its cadence,
its window (hidden or visible), enabled or not, its project's quiet hours (they hold notifications below critical,
never a run: brain.quiet), its floor when it is a collector, where its value lives and how it changes. Two kinds:

- **declared**: a ``schedules:`` entry (brain.schedule): its value lives in the registry (projects.yaml, inline) or
  in the project's schedules file; ``brain schedule set`` changes it;
- **found**: a task under a Task Scheduler folder the project's ``alerts: scheduler:`` names, that no ``schedules:``
  entry declares (a project's own installer registered it): read from the scheduler (Windows), shown with its
  cadence, its window and its last run, and changed where its project registers it, not here.

**The change** (``brain schedule set NAME [--every D|none] [--at HH:MM|none] [--days D,D|none] [--visible|--hidden]
[--enable|--disable] [--apply]``): the entry's line rewritten in its file, its comments and the other lines kept, as
a plan (the line before and after), then written by ``--apply``; the result must read back as the same file with
that one entry changed and pass the schedule's checks, else nothing is written. A collector's floor holds: an every
slower than it, or a ``--disable``, is refused (its data cannot be recovered). Only a one-line entry (a flow mapping,
as the registry writes them) is rewritten; a block entry is shown with the change to make by hand. Writing the file
installs nothing: ``brain schedule install --apply`` (the owner's) applies it to the scheduler, on each machine the
schedule runs on.
"""

from __future__ import annotations

import copy
import json
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml

from . import graph, projects, schedule

HIDDEN_EXES = {"pythonw.exe", "wscript.exe"}
HIDDEN_ARGS = re.compile(r"-w(indowstyle)?\s+hidden\b|--headless\b", re.I)
SET_HINT = "brain schedule set {name} --every|--at|--days|--visible|--hidden|--enable|--disable"
INSTALL_HINT = "then brain schedule install --apply on its machines (the owner's)"


class SetError(ValueError):
    """A change that cannot be made (brain schedule set exits 2)."""


# --- the view ---

def _quiet(p: projects.Project) -> str:
    from . import notify
    try:
        return notify.config(p).quiet_hours or ""
    except notify.NotifyError:
        return ""


def source_of(p: projects.Project, root: Path | None = None) -> Path | None:
    """The file that holds the project's schedules: its schedules file, else the registry."""
    value = getattr(p, "schedules", None)
    if isinstance(value, str):
        return p.root / value
    return projects.registry_file(root)


def window_of(row: dict) -> str:
    """A found task's window from its action: hidden (pythonw.exe, wscript.exe, -WindowStyle Hidden, a headless
    console), visible otherwise, '?' when the scheduler gave no action."""
    exe = str(row.get("exe") or "").strip().strip('"')
    if not exe:
        return "?"
    if Path(exe.replace("\\", "/")).name.lower() in HIDDEN_EXES or HIDDEN_ARGS.search(str(row.get("args") or "")):
        return "hidden"
    return "visible"


def _found_when(row: dict) -> str:
    from . import alerts
    every = alerts.cadence(row)
    kinds = {str(g.get("type") or "") for g in row.get("triggers") or [] if isinstance(g, dict)}
    parts = [f"every {schedule.duration_text(every)}"] if every else []
    parts += ["at logon"] if any("Logon" in k for k in kinds) else []
    parts += ["at boot"] if any("Boot" in k for k in kinds) else []
    return " and ".join(parts) or "on an event"


def _scheduler_rows(registry: Mapping[str, projects.Project]) -> tuple[dict[str, list[dict]], str]:
    """{project: its scheduler folders' rows} and why the scheduler could not be read ('' when it was, or when no
    project names a folder)."""
    from . import alerts
    cfgs = []
    for p in registry.values():
        try:
            cfgs.append(alerts.config(p))
        except (alerts.AlertsError, ValueError):   # a bad alerts entry: brain check's to report, not the view's
            continue
    sched = alerts.read_scheduler(cfgs)
    if "error" in sched:
        return {}, sched["error"]
    out: dict[str, list[dict]] = {}
    for c in cfgs:
        folders = {alerts._norm_folder(f) for f in c.scheduler}
        out[c.project] = [r for r in sched.get("rows") or []
                          if alerts._norm_folder(str(r.get("folder") or "")) in folders]
    return out, ""


def rows(registry: Mapping[str, projects.Project], *, here: str | None = None, root: Path | None = None,
         live: bool = True) -> tuple[list[dict], str]:
    """Every scheduled task of every project: (rows, why the scheduler could not be read). ``live``: the Task
    Scheduler is read for the found tasks and the declared tasks' last runs (a PowerShell call on Windows)."""
    declared = schedule.declared(registry)
    here = here or schedule.machine()
    rec = schedule.installed()
    found, why = _scheduler_rows(registry) if live else ({}, "")
    seen = {(r.get("name") or "").lower(): r for rs in found.values() for r in rs}
    out = [_declared_row(s, registry[s.project], here, rec, seen.get(s.name.lower(), {}), root) for s in declared]
    names = {s.name.lower() for s in declared}
    out += [_found_row(r, project, registry[project]) for project, rs in found.items() for r in rs
            if str(r.get("name") or "").lower() not in names]
    return out, why


def _declared_row(s: schedule.Schedule, p: projects.Project, here: str, rec: dict, task: dict,
                  root: Path | None) -> dict:
    src = source_of(p, root)
    key = s.name if isinstance(getattr(p, "schedules", None), str) else f"{s.project}.schedules.{s.name}"
    return {"kind": "declared", "name": s.name, "project": s.project, "command": s.command, "when": s.when(),
            "window": s.window(), "enabled": s.enabled, "here": s.here(here), "machines": s.machines,
            "quiet": _quiet(p), "floor": s.floor, "installed": rec.get(s.name), "last_run": task.get("last_run"),
            "last_result": task.get("last_result"),
            "source": f"{src.as_posix() if src else 'projects.yaml'}: {key}",
            "change": f"{SET_HINT.format(name=s.name)}, {INSTALL_HINT}"}


def _found_row(r: dict, project: str, p: projects.Project) -> dict:
    return {"kind": "found", "name": r.get("name"), "project": project, "command": None, "when": _found_when(r),
            "window": window_of(r), "enabled": r.get("state") != "Disabled", "here": True, "machines": [],
            "quiet": _quiet(p), "floor": None, "installed": None, "last_run": r.get("last_run"),
            "last_result": r.get("last_result"),
            "source": f"the Task Scheduler {r.get('folder') or ''}{r.get('name') or ''}",
            "change": f"where {project} registers it (its own setup, not brain schedule)"}


def settings_line(r: dict) -> str:
    """The row's settings in one line: window, enabled, quiet hours, floor."""
    parts = [r["window"], "enabled" if r["enabled"] else "disabled"]
    if r["quiet"]:
        parts.append(f"quiet {r['quiet']} (notifications held, the task runs)")
    if r["floor"]:
        parts.append(f"collector, floor {schedule.duration_text(r['floor'])}")
    if r["last_run"]:
        parts.append(f"last run {r['last_run']} (result {r['last_result']})")
    return ", ".join(parts)


# --- the change ---

@dataclass
class Change:
    schedule: str
    project: str
    file: Path
    line_no: int                 # 1-based
    before: str
    after: str
    text: str                    # the file's new text ('' when it is to change by hand)
    by_hand: str = ""            # why the line cannot be rewritten, with the change to make


def _split_flow(inner: str) -> list[str]:
    """A flow mapping's items, split on the commas outside quotes and brackets."""
    parts, cur, depth, quote = [], "", 0, ""
    for ch in inner:
        if quote:
            cur += ch
            quote = "" if ch == quote else quote
            continue
        if ch in "'\"":
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
            continue
        cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


def _render_value(key: str, value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(str(v) for v in value) + "]"
    if key == "at":
        return f"'{value}'"   # 07:30 unquoted is a number in YAML 1.1
    return str(value)


def wanted_changes(args_every=None, args_at=None, args_days=None, visible=None, enabled=None) -> dict:
    """{key: value or None (removed)} from the options; a value equal to the default is removed."""
    ch: dict = {}
    for key, v in (("every", args_every), ("at", args_at)):
        if v is not None:
            ch[key] = None if v.lower() == "none" else v
    if args_days is not None:
        days = [d.strip().lower() for d in args_days.split(",") if d.strip()]
        ch["days"] = None if args_days.lower() == "none" or not days else days
    if visible is not None:
        ch["visible"] = True if visible else None
    if enabled is not None:
        ch["enabled"] = None if enabled else False
    return ch


def _entry_lines(lines: list[str], name: str) -> list[int]:
    pat = re.compile(rf"^(\s*){re.escape(name)}\s*:\s*(\{{.*\}})\s*(#.*)?$")
    return [i for i, line in enumerate(lines) if pat.match(line.rstrip("\r\n"))]


def _rewrite(line: str, name: str, changes: dict) -> str:
    body = line.rstrip("\r\n")
    end = line[len(body):]
    m = re.match(rf"^(\s*{re.escape(name)}\s*:\s*)\{{(.*)\}}(\s*(#.*)?)$", body)
    items = _split_flow(m.group(2))
    keyed = [(it.split(":", 1)[0].strip(), it) for it in items]
    out, done = [], set()
    for key, it in keyed:
        if key in changes:
            done.add(key)
            if changes[key] is not None:
                out.append(f"{key}: {_render_value(key, changes[key])}")
        else:
            out.append(it)
    out += [f"{k}: {_render_value(k, v)}" for k, v in changes.items() if k not in done and v is not None]
    return f"{m.group(1)}{{{', '.join(out)}}}{m.group(3)}{end}"


def _path_of(p: projects.Project, name: str) -> list[str]:
    return [name] if isinstance(getattr(p, "schedules", None), str) else [p.name, "schedules", name]


def _get(doc, path: list[str]):
    for k in path:
        doc = doc[k]
    return doc


def plan_change(registry: Mapping[str, projects.Project], name: str, changes: dict,
                root: Path | None = None) -> Change:
    """The change of one declared schedule, checked: SetError when it is unknown, refused or does not read back."""
    if not changes:
        raise SetError("nothing to change: --every, --at, --days, --visible, --hidden, --enable or --disable")
    declared = {s.name: s for s in schedule.declared(registry)}
    s = declared.get(name)
    if s is None:
        raise SetError(f"no declared schedule {name!r} (brain schedule list shows every one; a task found in a "
                       "project's scheduler folder changes where the project registers it)")
    if s.floor and changes.get("enabled") is False:
        raise SetError(f"{name} is a collector (floor {schedule.duration_text(s.floor)}): its data cannot be "
                       "recovered, so it is never disabled from here; remove its floor in its file first")
    p = registry[s.project]
    f = source_of(p, root)
    if f is None or not f.is_file():
        raise SetError(f"{name}: the file that declares it is not found ({f})")
    with f.open(encoding="utf-8", newline="") as fh:
        text = fh.read()
    want = _wanted_doc(text, _path_of(p, name), changes, s.project, name)
    found = _rewritten(text, name, changes, want)
    if found:
        i, before, after, new_text = found
        return Change(name, s.project, f, i + 1, before, after, new_text)
    by_hand = ", ".join(f"{k}: {_render_value(k, v)}" if v is not None else f"{k} removed" for k, v in changes.items())
    return Change(name, s.project, f, 0, "", "", "", by_hand=f"{name} is not a one-line entry of {f.name}: change it "
                  f"by hand ({by_hand})")


def _wanted_doc(text: str, path: list[str], changes: dict, project: str, name: str):
    """The file's data as it must read once changed; SetError when the changed entry fails the schedule's checks."""
    want = copy.deepcopy(graph.load_yaml(text) or {})
    entry = _get(want, path)
    for k, v in changes.items():
        if v is None:
            entry.pop(k, None)
        else:
            entry[k] = v
    try:
        schedule._entry(project, name, entry)   # the schedule's own checks, the floor's included
    except schedule.ScheduleError as exc:
        raise SetError(str(exc)) from None
    return want


def _rewritten(text: str, name: str, changes: dict, want) -> tuple[int, str, str, str] | None:
    """(line index, before, after, new text) for the one line whose rewrite reads back as ``want``; None."""
    lines = text.splitlines(keepends=True)
    for i in _entry_lines(lines, name):
        new_line = _rewrite(lines[i], name, changes)
        new_text = "".join(lines[:i]) + new_line + "".join(lines[i + 1:])
        try:
            back = graph.load_yaml(new_text)
        except (yaml.YAMLError, ValueError):   # a candidate that does not parse is not the line
            continue
        if back == want:
            return i, lines[i].rstrip("\r\n"), new_line.rstrip("\r\n"), new_text
    return None


def set_main(registry: Mapping[str, projects.Project], name: str, changes: dict, apply: bool,
             root: Path | None = None, as_json: bool = False) -> int:
    """brain schedule set: the plan, written with --apply; 0, 1 when it must be made by hand, 2 when refused."""
    try:
        ch = plan_change(registry, name, changes, root)
    except (SetError, schedule.ScheduleError) as exc:
        print(f"brain schedule set: {exc}", file=sys.stderr)
        return 2
    written = False
    if apply and ch.text:
        with ch.file.open("w", encoding="utf-8", newline="") as fh:   # its line endings kept
            fh.write(ch.text)
        written = True
    if as_json:
        print(json.dumps({"schedule": ch.schedule, "project": ch.project, "file": str(ch.file), "line": ch.line_no,
                          "before": ch.before, "after": ch.after, "by_hand": ch.by_hand, "written": written},
                         indent=2))
        return 1 if ch.by_hand else 0
    if ch.by_hand:
        print(f"by hand  {ch.by_hand}")
        return 1
    print(f"schedule {ch.schedule} ({ch.project}): {ch.file} line {ch.line_no}")
    print(f"  - {ch.before.strip()}")
    print(f"  + {ch.after.strip()}")
    print("written  (commit it by a PR; " + INSTALL_HINT + ")" if written else "plan only: --apply writes the file")
    return 0


def _row_lines(r: dict) -> list[str]:
    if r["kind"] == "declared":
        state = ("installed " + str(r["installed"].get("at", ""))) if r["installed"] else (
            "not installed (brain schedule install --apply, or install.ps1 -Apply)" if r["here"]
            else "not for this machine")
        head = f"{r['name']} ({r['project']}): brain {shlex.join(r['command'])}, {r['when']}: {state}"
    else:
        head = f"{r['name']} ({r['project']}, found in the scheduler): {r['when']}"
    return [head, f"  {settings_line(r)}", f"  value: {r['source']}; change: {r['change']}"]


def list_main(registry: Mapping[str, projects.Project], *, here: str | None = None, root: Path | None = None,
              as_json: bool = False) -> int:
    """brain schedule list: every task of every project, then the alerts pass's dead-man."""
    try:
        rs, why = rows(registry, here=here, root=root)
    except schedule.ScheduleError as exc:
        print(f"brain schedule: {exc}", file=sys.stderr)
        return 2
    here = here or schedule.machine()
    w = schedule.watch(registry, here=here)
    if as_json:
        print(json.dumps({"machine": here, "schedules": [r for r in rs if r["kind"] == "declared"],
                          "found": [r for r in rs if r["kind"] == "found"], "scheduler": why or "read",
                          "alerts_pass": w}, indent=2, default=str))
        return 0
    if not any(r["kind"] == "declared" for r in rs):
        print("schedule none declared (projects.yaml schedules:)")
    for r in rs:
        print("\n".join(_row_lines(r)))
    if why:
        print(f"note     the scheduler's own tasks are not shown: {why}")
    if w:
        print(f"alerts pass: {w['line']}")
    return 0
