"""hooks/inject-rules.sh: the owner's rules from config.json, else the plugin's rules/global.md."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import brain

PLUGIN = Path(brain.__file__).resolve().parents[1]
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
