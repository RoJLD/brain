"""The cockpit hands over to a window that installs, then relaunches it (wi-brain-tui-apply-reload, ADR INST-1 to
INST-3). The standard library and brain only.

An install cannot run from the open cockpit: on Windows pip cannot replace a file a running process holds, such as
PyYAML's ``_yaml.pyd`` that ``brain tui`` loaded, so an install from it fails or leaves the engine half replaced. On
the owner's Run, the cockpit calls :func:`prepare`, which writes a script to ``<BRAIN_HOME>/handover/`` and logs the
handover as the owner's action, then exits; ``brain.tui.run`` calls :func:`start` once the app is gone:

  Windows   a new console window (PowerShell, ``-NoExit``) runs the script: it waits for the cockpit's process to
            exit (60 s at most, else it installs nothing and says so), runs each step in the brain's folder (the
            brain's installer with ``-Apply``, or ``brain update --yes``), the next one only when the last exited 0,
            then relaunches ``brain tui`` with the cockpit's own arguments in the cockpit's folder;
  elsewhere the script (sh) replaces the cockpit's process in its own terminal, so nothing holds a file.

The steps' output stays in the window: a failure says so, with its exit code, and waits for Enter before the
relaunch, which then runs the engine as the failure left it; a success relaunches after 2 s. Refused in a Claude
Code session's shell (``CLAUDECODE``), like the cockpit's other actions.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import config, detail, paths, transcript

WINDOWS = os.name == "nt"
DIR = "handover"            # <BRAIN_HOME>/handover/cockpit-<pid>.ps1 (or .sh)
WAIT_S = 60                 # how long the window waits for the cockpit to exit before giving up
KEEP_S = 24 * 3600.0        # older scripts are removed by the next handover


def relaunch(argv: list[str] | None = None) -> list[str]:
    """``brain tui`` again, with the cockpit's own arguments, from this interpreter (the brain's venv: the install
    replaces the package in it, not the interpreter)."""
    argv = sys.argv if argv is None else argv
    return [sys.executable, "-m", "brain", *argv[1:]]


def _ps(word: str) -> str:
    return "'" + str(word).replace("'", "''") + "'"


def _sh(word: str) -> str:
    return "'" + str(word).replace("'", "'\\''") + "'"


def script(steps: list[tuple[str, list[str]]], cwd: Path, again: list[str], here: Path, pid: int, title: str,
           windows: bool = WINDOWS) -> str:
    """The window's script: ``steps`` are (as shown, the process's argv), run in ``cwd`` once process ``pid`` is
    gone, then ``again`` in ``here``. PowerShell on Windows, sh elsewhere."""
    if windows:
        out = ["# brain tui's handover (brain.handover, INST-2): written by the cockpit, run once in its own window",
               "$ErrorActionPreference = 'Continue'",
               f"try {{ $Host.UI.RawUI.WindowTitle = {_ps('brain: ' + title)} }} catch {{}}",
               f"$cockpit = Get-Process -Id {pid} -ErrorAction SilentlyContinue",
               "if ($cockpit) {",
               f"    'waiting for the cockpit (pid {pid}) to exit...'",
               f"    if (-not $cockpit.WaitForExit({WAIT_S * 1000})) {{",
               f"        {_ps(f'the cockpit (pid {pid}) still runs after {WAIT_S} s: nothing installed; close it, then run:')}",
               *(f"        {_ps('  ' + shown)}" for shown, _ in steps),
               "        Read-Host 'Enter closes'",
               "        exit 1",
               "    }",
               "}",
               "$failed = $null",
               f"Set-Location -LiteralPath {_ps(cwd)}"]
        for shown, argv in steps:
            out += ["if (-not $failed) {",
                    f"    {_ps('$ ' + shown)}",
                    "    $global:LASTEXITCODE = $null",
                    f"    & {' '.join(_ps(w) for w in argv)}",
                    f"    if ($LASTEXITCODE -ne 0) {{ $failed = {_ps(shown)} + \" failed with exit code $LASTEXITCODE\" }}",
                    "}"]
        out += ["''",
                "if ($failed) {",
                "    \"FAILED: $failed. The engine is as the output above leaves it.\"",
                "    Read-Host 'Enter relaunches brain tui'",
                "} else {",
                "    'done: brain tui again in 2 s'",
                "    Start-Sleep -Seconds 2",
                "}",
                f"Set-Location -LiteralPath {_ps(here)}",
                f"& {' '.join(_ps(w) for w in again)}"]
        return "\r\n".join(out) + "\r\n"
    out = ["#!/bin/sh", "# brain tui's handover (brain.handover, INST-2): written by the cockpit, run once in its place",
           "failed=", f"cd {_sh(cwd)} || failed={_sh('cd ' + str(cwd))}"]
    for shown, argv in steps:
        out += ["if [ -z \"$failed\" ]; then",
                f"    printf '%s\\n' {_sh('$ ' + shown)}",
                f"    {' '.join(_sh(w) for w in argv)} || {{ code=$?; failed={_sh(shown)}\" failed with exit code $code\"; }}",
                "fi"]
    out += ["echo",
            "if [ -n \"$failed\" ]; then",
            "    printf 'FAILED: %s. The engine is as the output above leaves it.\\n' \"$failed\"",
            "    printf 'Enter relaunches brain tui '; read _",
            "else",
            "    echo 'done: brain tui again in 2 s'; sleep 2",
            "fi",
            f"cd {_sh(here)} && exec {' '.join(_sh(w) for w in again)}"]
    return "\n".join(out) + "\n"


def window(f: Path, windows: bool = WINDOWS) -> list[str]:
    """The process that runs the script: a PowerShell that stays open after it (Windows), else sh."""
    if windows:
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit", "-File", str(f)]
    return ["sh", str(f)]


def _tidy(d: Path, now: float) -> None:
    for old in d.glob("cockpit-*"):
        try:
            if now - old.stat().st_mtime > KEEP_S:
                old.unlink()
        except OSError:
            pass


def prepare(a: detail.Action, steps: list[list[str]], *, argv: list[str] | None = None, pid: int | None = None,
            here: Path | None = None, env: dict | None = None, windows: bool = WINDOWS) -> dict:
    """Write the handover of action ``a``'s ``steps`` (words, as the confirmation showed them) and log it as the
    owner's action: {script, window, steps, relaunch, windows}. Refused in a Claude Code session's shell."""
    why = detail.refused(env)
    if why:
        raise PermissionError(why)
    pid = os.getpid() if pid is None else pid
    here = Path.cwd() if here is None else here
    procs = [(detail.shown(w), detail.argv(w, a.cwd)) for w in steps]
    again = relaunch(argv)
    d = paths.brain_home() / DIR
    d.mkdir(parents=True, exist_ok=True)
    _tidy(d, time.time())
    f = d / f"cockpit-{pid}.{'ps1' if windows else 'sh'}"
    text = script(procs, Path(a.cwd or here), again, here, pid, f"{a.label} {a.ref}, then brain tui", windows)
    # Windows PowerShell 5.1 reads a script without a BOM in the ANSI codepage: the BOM keeps a non-ASCII path whole
    f.write_text(text, encoding="utf-8-sig" if windows else "utf-8", newline="")
    detail.log({"at": transcript.iso(datetime.now(timezone.utc)), "event": "tui-action", "action": a.kind,
                "by": config.owner_of(), "via": "tui", "project": a.project, "id": a.ref,
                "command": "; ".join(shown for shown, _ in procs), "cwd": str(a.cwd or ""), "exit": None,
                "seconds": 0, "output": f"handed over to {f} (then {detail.shown(again)})"})
    return {"script": str(f), "window": window(f, windows), "steps": [p for _, p in procs], "relaunch": again,
            "windows": windows}


def start(h: dict, *, popen=subprocess.Popen, execvp=os.execvp, env: dict | None = None) -> int:
    """Start a prepared handover once the cockpit's app is gone: a new console window on Windows (this process then
    exits, which the window waits for), else the script in this process's place. Refused in a Claude Code session's
    shell."""
    why = detail.refused(env)
    if why:
        raise PermissionError(why)
    if h["windows"]:
        # no redirection: the window's own console is its input (Read-Host, the relaunched cockpit) and its output
        popen(h["window"], creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0x10), close_fds=True)
        print(f"brain tui: the install runs in a new window, which relaunches brain tui ({h['script']})")
        return 0
    sys.stdout.flush()
    execvp(h["window"][0], h["window"])
    return 0  # execvp returns only when faked
