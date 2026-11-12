"""wi-brain-stuck-waiters (lesson les-brain-unbounded-background-waiter): a background until or while loop with no
deadline, no process check and no check that its file is still there gets one line of hook context (waithint.sh,
brain.waithint); never a refusal. The wave 0.3.2 loops that spun after their logs were deleted are the first cases."""

import io
import json
import os
import subprocess
import sys

import pytest
from test_capture import PLUGIN, _bash

from brain import waithint

# the two loops of wave 0.3.2 (lots 6 and 8), which spun until the owner stopped them
LOT6 = "until grep -qE '(passed|failed|error).* in [0-9]' v-lot6-plugins.log; do sleep 10; done"
LOT8 = "until grep -qE '[0-9]+ (passed|failed)' resil-full.log; do sleep 15; done"


@pytest.mark.parametrize("command", [
    LOT6, LOT8,
    "while true; do sleep 1; done",
    "until [ -f done.flag ]; do sleep 1; done",                         # waits for a file to appear: no bound
    "while ! grep -q ready app.log; do sleep 1; done",
    "while (-not (Select-String -Path run.log -Pattern passed -Quiet)) { Start-Sleep 5 }",
    "do { Start-Sleep 5 } until (Select-String -Path run.log -Pattern passed -Quiet)",
])
def test_an_unbounded_wait_is_named(command):
    assert waithint.unbounded(command), command


@pytest.mark.parametrize("command", [
    f"timeout 1800 bash -c \"{LOT6}\"",
    "for i in $(seq 360); do grep -q passed run.log && break; sleep 5; done",
    "until grep -q passed run.log; do [ -e run.log ] || exit 1; sleep 5; done",
    "until grep -q passed run.log; do test -f run.log || break; sleep 5; done",
    "until grep -q passed run.log; do kill -0 $pid || exit 1; sleep 5; done",
    "while [ ! -e out.txt ] && [ $SECONDS -lt 600 ]; do sleep 1; done",
    "end=$(( $(date +%s) + 600 )); until grep -q x f; do sleep 1; done",
    "while IFS= read -r line; do echo \"$line\"; done < list.txt",
    "while read -r f; do rm \"$f\"; done",
    "$sw = [Diagnostics.Stopwatch]::StartNew(); while ($sw.Elapsed.TotalMinutes -lt 30) { Start-Sleep 5 }",
    "while (-not (Select-String run.log passed -Quiet)) { if (-not (Test-Path run.log)) { break }; Start-Sleep 5 }",
    "Wait-Process -Id 42 -Timeout 600",
    "git log --oneline | head; echo meanwhile",                        # no loop at all
    "grep -n untilDone src/x.py",                                       # a word that only holds until
])
def test_a_bounded_wait_or_no_wait_is_left_alone(command):
    assert not waithint.unbounded(command), command


def _payload(tool="Bash", background=True, command=LOT8):
    inp = {"command": command, "description": "wait for the suite"}
    if background is not None:
        inp["run_in_background"] = background
    return {"session_id": "s-1", "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": inp}


def test_only_a_background_shell_call_gets_the_hint():
    hint = waithint.hint(_payload())
    assert "no deadline" in hint and "TaskStop" in hint and waithint.LESSON in hint
    assert waithint.hint(_payload("PowerShell", command="while ($true) { Start-Sleep 1 }"))
    assert waithint.hint(_payload(background=False)) == "" and waithint.hint(_payload(background=None)) == ""
    assert waithint.hint(_payload(background="true")) == ""   # the tool's own boolean only
    assert waithint.hint(_payload("Monitor")) == ""            # a Monitor has its own timeout
    assert waithint.hint({"tool_name": "Bash", "tool_input": "x"}) == ""


def test_hook_main_prints_context_never_a_decision(capsys):
    assert waithint.hook_main([], io.BytesIO(json.dumps(_payload()).encode("utf-8"))) == 0
    out = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse" and "no deadline" in out["additionalContext"]
    assert "permissionDecision" not in out
    for raw in (b"not json", b"[]", json.dumps(_payload(command="sleep 1")).encode("utf-8")):
        assert waithint.hook_main([], io.BytesIO(raw)) == 0 and capsys.readouterr().out == ""


def test_waithint_sh_fast_path_and_python_path(tmp_path):
    bash = _bash()
    if not bash:
        pytest.skip("no bash")
    env = dict(os.environ, BRAIN_PYTHON=sys.executable, BRAIN_HOME=str(tmp_path / "home"))

    def run(data: dict, **more) -> subprocess.CompletedProcess:
        return subprocess.run([bash, str(PLUGIN / "hooks" / "waithint.sh")], input=json.dumps(data),
                              capture_output=True, text=True, encoding="utf-8", env=dict(env, **more), timeout=60)

    assert run(_payload(background=False)).stdout == ""                 # fast path: not in the background
    assert run(_payload(command="sleep 30")).stdout == ""               # fast path: no loop word
    hit = run(_payload())
    assert hit.returncode == 0 and "no deadline" in json.loads(hit.stdout)["hookSpecificOutput"]["additionalContext"]
    assert run(_payload(), BRAIN_WAIT_HINT="0").stdout == ""


def test_hooks_json_starts_it_only_on_a_loop_word():
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    ifs = sorted(h["if"] for g in hooks for h in g["hooks"] if "waithint.sh" in h["command"])
    assert ifs == ["Bash(*until*)", "Bash(*while*)", "PowerShell(*until*)", "PowerShell(*while*)"]
