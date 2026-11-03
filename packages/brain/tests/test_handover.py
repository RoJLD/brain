"""wi-brain-tui-apply-reload (ADR INST-1 to INST-3): the cockpit hands an engine install over to a window that waits
for its exit, runs the steps, then relaunches brain tui with the same arguments. No installer ever runs here: the
scripts are read, and the window's start is faked."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from brain import detail, handover

ARGV = ["brain", "tui", "--project", "demo", "--refresh", "2"]  # how the cockpit was started


@pytest.fixture
def brain(tmp_path, monkeypatch):
    """Ada's brain, whose config.json declares its installer; a folder name with an apostrophe and an accent."""
    root = tmp_path / "Ada's brain é"
    root.mkdir()
    cfg = {"v": 1, "identity": {"owner": "Ada", "kind": "person"},
           "engine": {"repo": "ada/engine", "pin": "v0.2.3", "installer": "install.ps1"}}
    (root / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    (root / "install.ps1").write_text("'the plan'\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(root / "config.json"))
    monkeypatch.delenv("CLAUDECODE", raising=False)
    return root


def _install(root):
    return detail.Action(kind="apply", label="Install", project="brain", ref="pin v0.2.3", cwd=root,
                         steps=[["install.ps1", "-Apply"]], preview=["install.ps1"], handover=True)


def test_the_relaunch_keeps_the_cockpits_arguments():
    assert handover.relaunch(ARGV) == [sys.executable, "-m", "brain", "tui", "--project", "demo", "--refresh", "2"]


def test_the_windows_script_waits_installs_then_relaunches(brain, tmp_path):
    procs = [("install.ps1 -Apply", detail.argv(["install.ps1", "-Apply"], brain))]
    text = handover.script(procs, brain, handover.relaunch(ARGV), tmp_path, 4242, "Install pin v0.2.3", windows=True)
    lines = text.split("\r\n")
    wait = next(i for i, x in enumerate(lines) if "WaitForExit(60000)" in x)
    run = next(i for i, x in enumerate(lines) if "'-File'" in x)
    failed = next(i for i, x in enumerate(lines) if x.strip().startswith('"FAILED: '))
    again = next(i for i, x in enumerate(lines) if "'-m' 'brain' 'tui'" in x)
    assert "Get-Process -Id 4242" in text and wait < run < failed < again  # wait, install, a failure said, relaunch
    assert f"'{str(brain / 'install.ps1').replace(chr(39), chr(39) * 2)}' '-Apply'" in lines[run]  # quoted whole
    assert lines[again].endswith("'tui' '--project' 'demo' '--refresh' '2'")
    assert "Read-Host 'Enter relaunches brain tui'" in text  # a failure waits for the owner before the relaunch
    assert "nothing installed" in text and "exit 1" in text  # the cockpit still there: no install at all
    assert f"Set-Location -LiteralPath '{str(brain).replace(chr(39), chr(39) * 2)}'" in text


def test_the_posix_script_runs_in_the_cockpits_place(brain, tmp_path):
    procs = [("brain update --yes", ["/venv/bin/python", "-m", "brain", "update", "--yes"])]
    text = handover.script(procs, brain, ["/venv/bin/python", "-m", "brain", "tui"], tmp_path, 4242, "Update",
                           windows=False)
    assert text.startswith("#!/bin/sh\n") and "4242" not in text  # exec'd in place: nothing to wait for
    assert "'/venv/bin/python' '-m' 'brain' 'update' '--yes' || { code=$?; failed='brain update --yes'" in text
    assert text.rstrip().endswith("exec '/venv/bin/python' '-m' 'brain' 'tui'")
    assert "'\\''" in text  # the apostrophe of the brain's folder, quoted for sh
    assert text.index("FAILED: ") < text.index("exec ")


def test_prepare_writes_the_script_and_logs_the_owners_action(brain, brain_home, tmp_path):
    h = handover.prepare(_install(brain), [["install.ps1", "-Apply"]], argv=ARGV, pid=4242, here=tmp_path,
                         env={}, windows=True)
    f = Path(h["script"])
    assert f == brain_home / "handover" / "cockpit-4242.ps1" and f.read_bytes().startswith(b"\xef\xbb\xbf")
    assert h["window"] == ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit", "-File", str(f)]
    assert h["steps"] == [detail.argv(["install.ps1", "-Apply"], brain)] and h["steps"][0][-1] == "-Apply"
    assert h["relaunch"][-5:] == ["tui", "--project", "demo", "--refresh", "2"]
    rows = [json.loads(x) for f in (brain_home / "ledger").glob("cockpit-*.jsonl") for x in f.read_text("utf-8").split("\n") if x]
    assert len(rows) == 1 and rows[0]["command"] == "install.ps1 -Apply" and rows[0]["exit"] is None
    assert rows[0]["by"] == "Ada" and "handed over to" in rows[0]["output"]


def test_refused_in_a_claude_code_sessions_shell(brain, brain_home, tmp_path):
    with pytest.raises(PermissionError):
        handover.prepare(_install(brain), [["install.ps1", "-Apply"]], argv=ARGV, here=tmp_path,
                         env={"CLAUDECODE": "1"})
    assert not (brain_home / "handover").exists()
    started = []
    with pytest.raises(PermissionError):
        handover.start({"windows": True, "window": ["powershell"], "script": "x"}, popen=started.append,
                       env={"CLAUDECODE": "1"})
    assert started == []


def test_start_opens_a_new_console_on_windows_and_execs_elsewhere(capsys):
    seen = []
    h = {"windows": True, "window": ["powershell", "-NoExit", "-File", "h.ps1"], "script": "h.ps1"}
    assert handover.start(h, popen=lambda argv, **kw: seen.append((argv, kw)), env={}) == 0
    argv, kw = seen[0]
    assert argv == h["window"] and kw["creationflags"] == getattr(subprocess, "CREATE_NEW_CONSOLE", 0x10)
    assert "stdin" not in kw and "stdout" not in kw  # the window's own console: Read-Host and the relaunched cockpit
    assert "new window" in capsys.readouterr().out
    execs = []
    h = {"windows": False, "window": ["sh", "h.sh"], "script": "h.sh"}
    assert handover.start(h, execvp=lambda f, a: execs.append((f, a)), env={}) == 0 and execs == [("sh", ["sh", "h.sh"])]


def test_old_scripts_are_tidied(brain, brain_home, tmp_path):
    import os
    d = brain_home / "handover"
    d.mkdir(parents=True)
    old = d / "cockpit-1.ps1"
    old.write_text("x", encoding="utf-8")
    os.utime(old, (0, 0))
    handover.prepare(_install(brain), [["install.ps1", "-Apply"]], argv=ARGV, pid=2, here=tmp_path, env={},
                     windows=False)
    assert not old.exists() and (d / "cockpit-2.sh").is_file()


def test_the_scripts_parse(brain, tmp_path):
    """Parsed only, never run: PowerShell's own parser on the Windows script, sh -n on the other."""
    import os
    import shutil
    procs = [("install.ps1 -Apply", detail.argv(["install.ps1", "-Apply"], brain))]
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if ps:
        f = tmp_path / "h.ps1"
        f.write_text(handover.script(procs, brain, handover.relaunch(ARGV), tmp_path, 1, "Install", windows=True),
                     encoding="utf-8-sig", newline="")
        check = ("$e = $null; [void][System.Management.Automation.Language.Parser]::ParseFile($env:HANDOVER_PS1, [ref]$null, "
                 "[ref]$e); if ($e) { $e | ForEach-Object { $_.Message }; exit 1 }")
        proc = subprocess.run([ps, "-NoProfile", "-Command", check], capture_output=True, text=True,
                              env={**os.environ, "HANDOVER_PS1": str(f)})
        assert proc.returncode == 0, proc.stdout + proc.stderr
    sh = shutil.which("sh")
    if sh:
        f = tmp_path / "h.sh"
        f.write_text(handover.script(procs, brain, handover.relaunch(ARGV), tmp_path, 1, "Install", windows=False),
                     encoding="utf-8", newline="")
        proc = subprocess.run([sh, "-n", str(f)], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
    if not (ps or sh):
        pytest.skip("neither PowerShell nor sh here")
