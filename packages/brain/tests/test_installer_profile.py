"""A first install.ps1 -Apply installs the profile's extras (wi-brain-install-profile-extras): the installer's own
Add-ProfileExtras, run alone with the real brain command from an empty BRAIN_HOME and no personal brain, asks pip for
the default profile's tui in the same run (on a fresh machine, the profile's render once failed for want of a graph
store and the cockpit's Textual app was never installed)."""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from brain import paths

INSTALLER = Path(__file__).resolve().parents[1] / "installer" / "install.ps1"
PS = shutil.which("powershell.exe") or shutil.which("pwsh")   # Windows PowerShell, else PowerShell 7 (Linux)
pytestmark = [pytest.mark.skipif(not PS, reason="no PowerShell to run install.ps1"),
              pytest.mark.skipif(paths.package_repo() is not None,
                                 reason="the engine sits in a brain of its own: a root is always found")]
FUNCS = ("Get-Spec", "Invoke-Brain", "Read-Tier", "Show-Tier", "Add-ProfileExtras")


def _func(text: str, name: str) -> str:
    return re.search(rf"^function {name}\b.*?^}}", text, re.S | re.M).group(0)


def extras_step(tmp_path, tier_args=(), wanted=(), apply=True) -> str:
    """Add-ProfileExtras with this Python as the venv's (the real brain command), a fresh BRAIN_HOME, no personal
    brain and a folder outside any repo; Install-Brain only says the spec it was given."""
    text = INSTALLER.read_text(encoding="utf-8-sig")
    funcs = "\n".join(_func(text, n) for n in FUNCS)

    def arr(items):
        return "@(" + ", ".join(f"'{i}'" for i in items) + ")"

    script = (f"$ErrorActionPreference = 'Stop'\n[Console]::OutputEncoding = New-Object Text.UTF8Encoding $false\n"
              f"$Apply = ${str(apply).lower()}\n$Engine = ''\n$repo = $null\n"
              f"$engine_repo = 'RoJLD/brain'\n$engine_pin = 'v9.9.9'\n$venv_python = '{sys.executable}'\n"
              f"$tier_args = {arr(tier_args)}\n$wanted = {arr(wanted)}\n"
              "function Install-Brain([string]$spec) { \"PIP $spec\" }\n"
              f"{funcs}\nAdd-ProfileExtras\n")
    home = tmp_path / "brain-home"
    home.mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("BRAIN_")}
    env["BRAIN_HOME"] = str(home)
    r = subprocess.run([PS, "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300, cwd=tmp_path, env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_a_first_install_from_an_empty_home_asks_pip_for_the_default_profiles_tui(tmp_path):
    out = extras_step(tmp_path)
    assert ": default (" in out and "built-in); extras tui;" in out, out
    assert 'install  the profile\'s extras (pip install "brain[tui] @ git+https://github.com/RoJLD/brain.git@v9.9.9' \
        in out
    assert "PIP brain[tui] @ git+https://github.com/RoJLD/brain.git@v9.9.9#subdirectory=packages/brain" in out
    assert "render failed" not in out


def test_the_plan_names_the_extras_and_installs_nothing(tmp_path):
    out = extras_step(tmp_path, apply=False)
    assert "install  the profile's extras" in out and "PIP " not in out


def test_an_extra_already_asked_is_not_installed_twice_and_lite_wants_none(tmp_path):
    out = extras_step(tmp_path, wanted=["tui"])
    assert "built-in); extras tui;" in out and "PIP " not in out
    out = extras_step(tmp_path, tier_args=["lite"], apply=False)
    assert "lite (Lite" in out and "extras none" in out and "install  the profile's extras" not in out


def test_a_render_that_fails_says_how_to_add_the_extras(tmp_path):
    out = extras_step(tmp_path, tier_args=["--with", "no-such-entry"], apply=False)
    assert "no capability or stack 'no-such-entry'" in out and "-Apply -Extras tui" in out and "PIP " not in out
    out = extras_step(tmp_path, tier_args=["--with", "no-such-entry"], wanted=["tui"], apply=False)
    assert "no capability or stack" in out and "-Extras tui" not in out   # already asked: no hint
