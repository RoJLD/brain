"""The guards on the desktop app's Terminal panel (wi-brain-guard-terminal-tool): a command that run_in_terminal types
into the owner's shell is judged as a shell call, PowerShell on Windows, else bash, in its cwd, else the session's.
The tests run as owner Ada (fixtures/brain) on the invented platform of test_guards (demo-lab, demo-data)."""

import json
import os
import subprocess
import sys

import pytest
from test_guards import CLAUDE, PLUGIN, decide, payload, plat  # noqa: F401 (plat is a fixture)

from brain import guards

TOOL = "mcp__terminal__run_in_terminal"


@pytest.fixture(params=["PowerShell", "Bash"])
def shell(request, monkeypatch):
    monkeypatch.setattr(guards, "terminal_shell", lambda: request.param)
    return request.param


def term(folder, command, **inp):
    """The refusal for ``command`` typed into the Terminal panel by a session working in ``folder``."""
    p = payload(TOOL, folder, command=command, title="build")
    p["tool_input"].update(inp)
    return decide(p)


def test_a_terminal_command_meets_the_shell_guards(plat, shell, brain_home):
    lab = (plat / "demo-lab").as_posix()
    assert "refused" in term(plat / "demo-lab", "git commit -m x")                                    # production
    assert "refused" in term(plat, f"git -C {lab} reset --hard")
    assert "brain usage allow refused: it lifts the usage guard" in term(plat, "brain usage allow --hours 8")
    assert "visibility is Ada's alone" in term(plat, "gh repo edit acme/x --visibility public")      # owner
    assert "attribution" in term(plat, f'git commit -m "x" -m "{CLAUDE}"')
    assert "refused" in term(plat, "shutdown /s /t 0")                                               # power
    assert term(plat, "git status") is None and term(plat, "npm run dev") is None
    assert term(plat, "python -m http.server 8000") is None and term(plat, "git log --oneline") is None


def test_its_cwd_is_the_folder_it_runs_in(plat, shell):
    assert term(plat, "git commit -m x", cwd=str(plat / "demo-lab"))                                 # a new tab there
    assert term(plat / "demo-lab", "git commit -m x", cwd=str(plat / "demo-lab2")) is None          # not production


def test_the_shell_on_this_machine():
    assert guards.terminal_shell() == ("PowerShell" if os.name == "nt" else "Bash")


def test_the_powershell_queue_hint(plat, monkeypatch, brain_home):
    monkeypatch.setattr(guards, "terminal_shell", lambda: "PowerShell")
    monkeypatch.setenv("BRAIN_CAPTURE", "0")   # no ledger: the hint carries the command, quoted for PowerShell
    reason = term(plat, "gh secret set KEY --body x")
    assert "brain queue add --kind action --title" in reason and "--what 'gh secret set KEY --body x'" in reason


def test_guard_script_end_to_end(plat):
    from test_capture import _bash
    sh = _bash()
    if not sh:
        pytest.skip("no bash")
    env = dict(os.environ, BRAIN_PYTHON=sys.executable)

    def run(p):
        out = subprocess.run([sh, str(PLUGIN / "hooks" / "guard.sh"), "shell"], input=json.dumps(p),
                             capture_output=True, text=True, env=env, timeout=60)
        assert out.returncode == 0
        return out.stdout

    refused = json.loads(run(payload(TOOL, plat / "demo-lab", command="git commit -m x", title="t")))
    assert refused["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "lifts the usage guard" in run(payload(TOOL, plat, command="brain usage allow", title="t"))
    assert run(payload(TOOL, plat, command="dir", title="t")) == ""
