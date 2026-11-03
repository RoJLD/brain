"""hooks/announce.sh: at SessionStart, the decisions the owner answered that the project has not integrated yet."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import brain
from brain import decisions

SCRIPT = Path(brain.__file__).resolve().parents[1] / "hooks" / "announce.sh"
AT = "2026-11-01T10:00:00Z"


def _run(cwd: Path, text: str = "") -> subprocess.CompletedProcess:
    """announce.sh with ``text`` on stdin (default: the payload naming ``cwd``), run from ``cwd``."""
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash not available")
    import os
    env = dict(os.environ, BRAIN_PYTHON=sys.executable)
    return subprocess.run([bash, SCRIPT.as_posix(), "SessionStart"], input=text or json.dumps({"cwd": str(cwd)}),
                          capture_output=True, text=True, encoding="utf-8", env=env, timeout=60, cwd=cwd)


def test_announces_the_answers_to_integrate(store):
    root = store.parents[1]
    assert _run(root).stdout == ""  # nothing answered: silent
    decisions.ask(root, title="Alert channel", question="Which channel for the alerts?",
                  options=["Telegram: a bot", "Email: the SMTP relay"], why="already set up", at=AT)
    decisions.answer(root, "alert-channel", ["Email"], at=AT)
    out = _run(root)
    assert out.returncode == 0
    hook = json.loads(out.stdout)["hookSpecificOutput"]
    assert hook["hookEventName"] == "SessionStart"
    # the owner the tests run as (config.json, via BRAIN_CONFIG), never a name the script chose
    assert hook["additionalContext"].startswith("Ada answered 1 decision(s) that root has not integrated yet.")
    assert "- ddr-2026-11-01-alert-channel: Email (Alert channel)" in hook["additionalContext"]


def test_never_breaks_a_session(tmp_path):
    out = _run(tmp_path, "not json")  # run from a folder with no records: nothing to announce, whatever the payload
    assert out.returncode == 0 and out.stdout == ""
