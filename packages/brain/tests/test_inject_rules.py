"""hooks/inject-rules.sh: the owner's rules from config.json, else the plugin's rules/global.md."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import brain

PLUGIN = Path(brain.__file__).resolve().parent / "adapters" / "claude"  # its hooks/ folder is a plugin's
SCRIPT = PLUGIN / "hooks" / "inject-rules.sh"


def _run(env_extra: dict, event: str = "SessionStart", root: Path = PLUGIN) -> dict:
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash not available")
    env = {k: v for k, v in __import__("os").environ.items() if k not in ("BRAIN_CONFIG", "CLAUDE_BRAIN_DIR")}
    env.update({"CLAUDE_PLUGIN_ROOT": root.as_posix(), **env_extra})
    out = subprocess.run([bash, SCRIPT.as_posix(), event], capture_output=True, text=True, env=env, check=True,
                         encoding="utf-8").stdout
    return json.loads(out)["hookSpecificOutput"]


def test_the_rules_of_config_json_in_order(tmp_path):
    (tmp_path / "a.md").write_text('A "quoted"\trule \\ here\r\n', encoding="utf-8", newline="")
    (tmp_path / "b.md").write_text("B rule\n", encoding="utf-8")
    (tmp_path / "config.json").write_text(
        '{"v": 1,\r\n "identity": {"owner": "Ada"},\r\n "rules": ["a.md", "missing.md", "b.md"]}\r\n', encoding="utf-8")
    out = _run({"BRAIN_CONFIG": str(tmp_path / "config.json")}, "SubagentStart")
    assert out == {"hookEventName": "SubagentStart", "additionalContext": 'A "quoted" rule \\ here\n\nB rule\n'}


def test_claude_brain_dir_then_the_plugin_copy(tmp_path):
    (tmp_path / "r.md").write_text("from the brain dir\n", encoding="utf-8")
    (tmp_path / "config.json").write_text('{"v": 1, "identity": {"owner": "Ada"}, "rules": ["r.md"]}',
                                          encoding="utf-8")
    assert _run({"CLAUDE_BRAIN_DIR": str(tmp_path)})["additionalContext"] == "from the brain dir\n"
    plugin = tmp_path / "plugins" / "cache" / "core"  # a cached copy of the plugin: no config.json two folders up
    (plugin / "rules").mkdir(parents=True)
    (plugin / "rules" / "global.md").write_text("the plugin's own\n", encoding="utf-8")
    assert _run({}, root=plugin)["additionalContext"] == "the plugin's own\n"
    (tmp_path / "config.json").write_text('{"v": 1, "identity": {"owner": "Ada"}, "rules": []}', encoding="utf-8")
    assert _run({"BRAIN_CONFIG": str(tmp_path / "config.json")}, root=plugin)["additionalContext"] == \
        "the plugin's own\n"


def test_the_personal_brain_the_installer_points_to(tmp_path, brain_home):
    """A cached plugin finds its owner's rules from anywhere: $BRAIN_PERSONAL, else <BRAIN_HOME>/personal.json (its
    root JSON-escaped as the installer may write it), before the plugin's own copy."""
    me = tmp_path / "me"
    (me / "rules").mkdir(parents=True)
    (me / "rules" / "global.md").write_text("Ada's rules\n", encoding="utf-8")
    (me / "config.json").write_text('{"v": 1, "identity": {"owner": "Ada"}, "rules": ["rules/global.md"]}',
                                    encoding="utf-8")
    plugin = tmp_path / "cache" / "core"
    (plugin / "rules").mkdir(parents=True)
    (plugin / "rules" / "global.md").write_text("the plugin's own\n", encoding="utf-8")
    assert _run({}, root=plugin)["additionalContext"] == "the plugin's own\n"
    assert _run({"BRAIN_PERSONAL": str(me)}, root=plugin)["additionalContext"] == "Ada's rules\n"
    brain_home.mkdir(parents=True, exist_ok=True)
    (brain_home / "personal.json").write_text(json.dumps({"root": str(me)}), encoding="utf-8")
    assert _run({}, root=plugin)["additionalContext"] == "Ada's rules\n"


def test_two_files_one_without_its_last_newline(tmp_path):
    """The text as the tr, sed and awk pipeline built it: a blank line between two files, the last line ended."""
    (tmp_path / "a.md").write_text("A\r\n\r\n", encoding="utf-8", newline="")
    (tmp_path / "b.md").write_text("B\tend", encoding="utf-8", newline="")
    (tmp_path / "config.json").write_text('{"v": 1, "rules": ["a.md", "b.md"]}', encoding="utf-8")
    assert _run({"BRAIN_CONFIG": str(tmp_path / "config.json")})["additionalContext"] == "A\n\n\nB end\n"


def test_the_hook_starts_no_process():
    """wi-brain-hook-timeout-trace: each fork cost 35 to 90 ms on Windows at rest, seconds under load (10.5 s against
    the 10 s timeout on 2026-11-27); the one subshell left reads a floor section that names "only"."""
    code = "\n".join(line.split("  #")[0] for line in SCRIPT.read_text(encoding="utf-8").splitlines()
                     if not line.lstrip().startswith("#"))
    assert code.count("$(") == 1 and '[[ $json == *\'"floor"\'* && $json == *\'"only"\'* ]]' in code
    for word in ("tr ", "sed ", "awk ", "grep ", "dirname", "cat ", "`"):
        assert word not in code, word


def test_a_printed_injection_marks_its_session(tmp_path, brain_home):
    """The mark the budget watch reads at the session's first tool call (budget.sh): only after the rules are out."""
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash not available")
    (tmp_path / "r.md").write_text("R\n", encoding="utf-8")
    (tmp_path / "config.json").write_text('{"v": 1, "rules": ["r.md"]}', encoding="utf-8")
    env = dict(__import__("os").environ, BRAIN_CONFIG=str(tmp_path / "config.json"), BRAIN_HOME=str(brain_home),
               CLAUDE_PLUGIN_ROOT=PLUGIN.as_posix())
    out = subprocess.run([bash, SCRIPT.as_posix(), "SessionStart"], input='{"session_id": "s-1", "source": "startup"}',
                         capture_output=True, text=True, env=env, check=True, encoding="utf-8", timeout=60)
    assert json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"] == "R\n"
    assert (brain_home / "session-rules" / "s-1.ok").is_file()
    subprocess.run([bash, SCRIPT.as_posix(), "SessionStart"], input='{"session_id": "../x"}', capture_output=True,
                   text=True, env=env, check=True, encoding="utf-8", timeout=60)
    assert sorted(p.name for p in (brain_home / "session-rules").iterdir()) == ["s-1.ok"]  # no path from the JSON


def _budget(sid: str, brain_home, **env) -> str:
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash not available")
    full = dict(__import__("os").environ, BRAIN_HOME=str(brain_home), CLAUDE_PLUGIN_ROOT=PLUGIN.as_posix(),
                BRAIN_PYTHON=str(brain_home / "no-python"), **env)
    return subprocess.run([bash, (PLUGIN / "hooks" / "budget.sh").as_posix()],
                          input=json.dumps({"session_id": sid, "tool_name": "Read"}), capture_output=True, text=True,
                          env=full, check=True, encoding="utf-8", timeout=60).stdout


def test_the_first_tool_call_of_a_session_the_injection_missed_says_so(brain_home):
    """wi-brain-hook-timeout-trace: a start that left no mark (inject-rules killed by its timeout) is said at the
    session's first tool call, once; a marked session and a machine with no marks at all hear nothing."""
    assert _budget("s-2", brain_home) == ""                       # no session-rules folder: not checked
    (brain_home / "session-rules").mkdir(parents=True)
    (brain_home / "session-rules" / "s-1.ok").write_text("", encoding="utf-8")
    assert _budget("s-1", brain_home) == ""                       # injected
    out = json.loads(_budget("s-3", brain_home, BRAIN_BUDGET_WATCH="0"))["hookSpecificOutput"]
    assert out["hookEventName"] == "PostToolUse" and "No trace that this session's start injected" in \
        out["additionalContext"] and out["additionalContext"].endswith("/rules/global.md) and follow them.")
    assert _budget("s-3", brain_home) == ""                       # once
    assert (brain_home / "session-rules" / "s-3.seen").is_file()
