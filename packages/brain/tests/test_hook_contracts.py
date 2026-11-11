"""wi-brain-hook-contracts: the formats the bash hooks read from Python (the .mark files, node-clis.txt, the rendered
hooks/contract.txt) against their fixtures (tests/fixtures/hooks/), read by today's bash and by a line 1 reader (bash
before 0.3.2, which a plugin cache copy keeps running); the hook's brain_version passed to Python and the health line
on a mismatch; one spelling of <BRAIN_HOME> in bash and Python, and the health line on two .brain folders."""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_capture import PLUGIN, _bash

import brain
from brain import budget, guards, midsession, paths, render, stacks

FIX = Path(__file__).parent / "fixtures" / "hooks"
HOOKS = PLUGIN / "hooks"


def fixture(name: str, **values) -> str:
    text = (FIX / name).read_text(encoding="utf-8")
    for k, v in values.items():
        text = text.replace("{" + k + "}", v)
    return text


def _sh():
    sh = _bash()
    if not sh:
        pytest.skip("no bash")
    return sh


def _fake_python(tmp_path: Path) -> tuple[str, Path]:
    ran = tmp_path / "python-ran"
    fake = tmp_path / "fake-python"
    fake.write_text(f"#!/usr/bin/env bash\necho ran >> '{ran.as_posix()}'\n", encoding="utf-8", newline="\n")
    fake.chmod(0o755)
    return fake.as_posix(), ran


def _hook(script: str, payload: dict, python: str, brain_home: Path) -> None:
    env = dict(os.environ, BRAIN_HOME=str(brain_home), BRAIN_PYTHON=python, CLAUDE_PLUGIN_ROOT=str(PLUGIN))
    out = subprocess.run([_sh(), str(HOOKS / script)], input=json.dumps(payload), capture_output=True, text=True,
                         env=env, timeout=60)
    assert out.returncode == 0 and out.stderr == "", out.stderr


# --- the writers write the fixtures' formats ---------------------------------------------------------------------

def test_the_writers_write_the_fixtures(tmp_path, brain_home, monkeypatch):
    t = tmp_path / "t.jsonl"
    budget._mark("s-1", str(t), 60)
    assert (budget.state_dir() / "s-1.mark").read_text(encoding="utf-8") == fixture("budget.mark",
                                                                                     transcript=t.as_posix())
    q = tmp_path / "queue"
    midsession._save("s-1", "D:/w", q, {}, {"ddr-2026-01-01-pending.md": "pending", "ddr-x.md": "answered"},
                     time.time())
    assert (midsession.state_dir() / "s-1.mark").read_text(encoding="utf-8") == \
        fixture("announce.mark", cwd="D:/w", queue=q.as_posix())
    monkeypatch.setattr(guards.config, "load", lambda *a, **k: SimpleNamespace(
        data={"power": {"node_clis": ["acme-cli", "acme"]}}))
    guards.node_tools()
    assert (brain_home / "cache" / guards.NODE_CLI_CACHE).read_text(encoding="utf-8") == fixture("node-clis.txt")
    monkeypatch.setattr(render, "_own_config", lambda src: {"rules": ["rules/a.md", 3, "x\ny", "rules/b.md"]})
    assert render.hook_contract(None) == fixture("contract.txt", version=brain.__version__)


def test_the_formats_named_in_bash_are_pythons():
    """Each format line a bash hook trusts is the one its Python writer writes."""
    for script, form in (("budget.sh", budget.MARK_FORMAT), ("midsession.sh", midsession.MARK_FORMAT),
                         ("guard.sh", guards.NODE_CLI_FORMAT), ("inject-rules.sh", render.HOOK_CONTRACT_FORMAT)):
        assert f"'{form}'" in (HOOKS / script).read_text(encoding="utf-8") or \
            f'"{form}"' in (HOOKS / script).read_text(encoding="utf-8"), script
    assert f"/hooks/{render.HOOK_CONTRACT}" in (HOOKS / "inject-rules.sh").read_text(encoding="utf-8")


def test_line_one_keeps_what_bash_before_0_3_2_reads():
    """A plugin cache copy runs old bash against the new engine: line 1 is still the transcript (budget.sh), the
    session's folder (midsession.sh) and the alternation (guard.sh); the format line comes last."""
    assert fixture("budget.mark").splitlines()[0] == "{transcript}"
    assert fixture("announce.mark").splitlines()[:2] == ["{cwd}", "{queue}"]
    assert fixture("node-clis.txt").splitlines()[0] == "acme|acme-cli"
    for name in ("budget.mark", "announce.mark", "node-clis.txt"):
        assert fixture(name).splitlines()[-1].startswith("#brain.")


# --- today's bash reads them ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("form,starts", [(None, False), ("#brain.budget-mark/v1", False),
                                         ("#brain.budget-mark/v2", True)])
def test_budget_sh_trusts_its_format_only(tmp_path, brain_home, form, starts):
    t = tmp_path / "t.jsonl"
    t.write_text("{}\n", encoding="utf-8")
    mark = brain_home / "budget" / "s-1.mark"
    mark.parent.mkdir(parents=True)
    text = fixture("budget.mark", transcript=t.as_posix())
    text = text.splitlines()[0] + "\n" + (f"{form}\n" if form else "")
    mark.write_text(text, encoding="utf-8", newline="\n")
    ahead = time.time() + 600
    os.utime(mark, (ahead, ahead))
    python, ran = _fake_python(tmp_path)
    _hook("budget.sh", {"session_id": "s-1", "transcript_path": str(t)}, python, brain_home)
    assert ran.exists() is starts


@pytest.mark.parametrize("form,starts", [(None, False), ("#brain.announce-mark/v1", False),
                                         ("#brain.announce-mark/v2", True)])
def test_midsession_sh_trusts_its_format_only(tmp_path, brain_home, form, starts):
    q = tmp_path / "queue"
    q.mkdir()
    (q / "ddr-2026-01-01-pending.md").write_text("x\n", encoding="utf-8")
    old = time.time() - 600
    for p in (q / "ddr-2026-01-01-pending.md", q):
        os.utime(p, (old, old))
    lines = fixture("announce.mark", cwd="D:/w", queue=q.as_posix()).splitlines()
    mark = brain_home / "announce" / "s-1.mark"
    mark.parent.mkdir(parents=True)
    mark.write_text("\n".join(lines[:-1] + ([form] if form else [])) + "\n", encoding="utf-8", newline="\n")
    python, ran = _fake_python(tmp_path)
    _hook("midsession.sh", {"session_id": "s-1", "cwd": "D:/w", "prompt": "hi"}, python, brain_home)
    assert ran.exists() is starts


def _needs_python(commands, brain_home):
    lines = "\n".join(json.dumps({"tool_name": "Bash", "tool_input": {"command": c}}) for c in commands) + "\n"
    script = (f'source "{(HOOKS / "guard.sh").as_posix()}"; '
              'while IFS= read -r l; do needs_python shell "$l" && echo 1 || echo 0; done')
    out = subprocess.run([_sh(), "-c", script], input=lines.encode(), capture_output=True, timeout=60,
                         env=dict(os.environ, BRAIN_HOME=str(brain_home)))
    assert out.returncode == 0, out.stderr
    return [x == b"1" for x in out.stdout.split()]


def test_guard_sh_reads_the_node_clis_fixture(brain_home):
    cache = brain_home / "cache" / guards.NODE_CLI_CACHE
    cache.parent.mkdir(parents=True)
    cache.write_text(fixture("node-clis.txt"), encoding="utf-8", newline="\n")
    assert _needs_python(["acme-cli wake box1", "ls -la"], brain_home) == [True, False]
    cache.write_text("acme|acme-cli\n", encoding="utf-8", newline="\n")   # written before 0.3.2
    assert _needs_python(["acme-cli wake box1", "ls -la"], brain_home) == [True, False]
    cache.write_text("acme|acme-cli\n#brain.node-clis/v2\n", encoding="utf-8", newline="\n")   # a newer engine's
    assert _needs_python(["ls -la"], brain_home) == [True]


def _inject(plugin: Path, config: Path) -> str:
    env = {k: v for k, v in os.environ.items() if k not in ("BRAIN_CONFIG", "CLAUDE_BRAIN_DIR")}
    env.update(CLAUDE_PLUGIN_ROOT=plugin.as_posix(), BRAIN_CONFIG=str(config))
    out = subprocess.run([_sh(), (HOOKS / "inject-rules.sh").as_posix(), "SessionStart"], capture_output=True,
                         text=True, env=env, check=True, encoding="utf-8").stdout
    return json.loads(out)["hookSpecificOutput"]["additionalContext"]


def test_inject_rules_reads_the_contract_not_the_json(tmp_path):
    """The contract's rule lines win over config.json's text, whose first "rules" array may be another section's;
    a contract of another format, or none, falls back to config.json."""
    me = tmp_path / "me"
    (me / "rules").mkdir(parents=True)
    for n in ("a", "b", "wrong"):
        (me / "rules" / f"{n}.md").write_text(f"{n} rule\n", encoding="utf-8")
    config = me / "config.json"
    config.write_text('{"v": 1, "standards": {"rules": ["rules/wrong.md"]}, "rules": ["rules/a.md"]}',
                      encoding="utf-8")
    plugin = tmp_path / "plugin"
    (plugin / "hooks").mkdir(parents=True)
    contract = plugin / "hooks" / "contract.txt"
    contract.write_text(fixture("contract.txt", version="9.9.9").replace("\n", "\r\n"), encoding="utf-8",
                        newline="")
    assert _inject(plugin, config) == "a rule\n\nb rule\n"
    contract.write_text("#brain.hook-contract/v2\nrule rules/b.md\n", encoding="utf-8")
    assert _inject(plugin, config) == "wrong rule\n"
    contract.unlink()
    assert _inject(plugin, config) == "wrong rule\n"


# --- the version and the home ------------------------------------------------------------------------------------

def test_common_sh_exports_its_version_to_the_python_it_starts():
    script = f'source "{(HOOKS / "common.sh").as_posix()}"; "$0" -c "import os; print(os.environ[\'BRAIN_HOOK_VERSION\'])"'
    out = subprocess.run([_sh(), "-c", script, sys.executable], capture_output=True, text=True, timeout=60,
                         env={k: v for k, v in os.environ.items() if k != "BRAIN_HOOK_VERSION"})
    assert out.stdout.strip() == brain.__version__, out.stderr


def test_the_health_reports_a_hook_of_another_version(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "home_folders", lambda: [])
    monkeypatch.delenv("BRAIN_HOOK_VERSION", raising=False)
    assert stacks.hook_contract_notes() == []   # a hook before 0.3.2 passes none
    monkeypatch.setenv("BRAIN_HOOK_VERSION", brain.__version__)
    assert stacks.hook_contract_notes() == []
    monkeypatch.setenv("BRAIN_HOOK_VERSION", "0.0.1")
    (line,) = stacks.hook_contract_notes()
    assert f"hooks are 0.0.1 while the engine is {brain.__version__}" in line and "Restart the session" in line


def test_two_brain_folders_are_reported(monkeypatch, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for h in (a, b):
        (h / ".brain").mkdir(parents=True)
    monkeypatch.delenv("BRAIN_HOOK_VERSION", raising=False)
    monkeypatch.setenv("USERPROFILE", str(a))
    monkeypatch.setenv("HOME", str(a))
    monkeypatch.delenv("BRAIN_HOME")
    assert paths.home_folders() == [a / ".brain"] and stacks.hook_contract_notes() == []
    monkeypatch.setenv("HOME", str(b) if os.name == "nt" else str(a))
    monkeypatch.setenv("USERPROFILE", str(a) if os.name == "nt" else str(b))
    assert paths.home_folders() == [a / ".brain", b / ".brain"]
    (line,) = stacks.hook_contract_notes()
    assert line.startswith("Two .brain folders: ") and str(b / ".brain") in line
    if os.name == "nt":   # Git Bash's spelling of the same home
        monkeypatch.setenv("HOME", "/" + str(a)[0].lower() + str(a)[2:].replace("\\", "/"))
        assert paths.home_folders() == [a / ".brain"]
    monkeypatch.setenv("BRAIN_HOME", str(tmp_path / "set"))
    assert paths.home_folders() == []


def test_every_hook_spells_brain_home_as_python_does():
    """bash names <BRAIN_HOME> as Python's Path.home() does on Windows (%USERPROFILE%), never $HOME alone."""
    spelling = "${BRAIN_HOME:-${USERPROFILE:-$HOME}/.brain}"
    for sh in HOOKS.glob("*.sh"):
        code = "\n".join(re.sub(r"(^|\s)#.*", "", line) for line in sh.read_text(encoding="utf-8").splitlines())
        assert code.count("/.brain") == code.count(spelling), sh.name
