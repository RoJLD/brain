"""wi-brain-handover-auto-root (HANDOVER-1): the first prompt marks the root of a coordinators' chain. The
UserPromptSubmit hook (midsession) marks a session the owner started (no parent in the app's files, no completed turn)
when its first prompt asks for a coordinator, judged on the session's own transcript (found from its id, never the
payload's path); a later prompt, a session another session started, or a prompt that asks for none marks nothing; the
owner is told; the guard refuses a session that runs the hook's entry by hand. On the invented sessions of
test_guards_remote_control's lab."""

import io
import json
import os
import subprocess

import pytest
import test_guards_remote_control as rc
from test_capture import PLUGIN, _bash
from test_guards import bash, pwsh
from test_guards_remote_control import CLI, F

from brain import guards, midsession, paths, sessions, succession

lab = rc.lab   # the lab's fixture: invented sessions in the desktop app's files
O = "local_77777777-0000-4000-8000-777777777777"   # a session the owner started
ASK = "Tu es le coordinateur du Brain : reprends la vague 0.4.1."
FIRST = json.dumps({"type": "queue-operation"}) + "\n" + json.dumps({"type": "user", "message": {"content": ASK}})


def _transcript(host: str, text: str = FIRST):
    """The session's own transcript, where Claude Code writes it (the lab's CLAUDE_CONFIG_DIR)."""
    f = paths.projects_dir() / "E--lab" / f"{CLI[host]}.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text + "\n", encoding="utf-8")
    return f


@pytest.fixture
def owner(lab, monkeypatch):
    monkeypatch.setitem(CLI, O, "77777777-cli0-4000-8000-000000000000")
    lab.put(O, title="Brain coordination")
    _transcript(O)
    monkeypatch.setenv(sessions.HOST_ENV, O)
    return lab


def _payload(prompt=ASK, transcript="", sid=None):
    return {"session_id": sid or CLI[O], "prompt": prompt, "transcript_path": transcript,
            "hook_event_name": "UserPromptSubmit"}


def test_the_first_prompt_of_an_owner_session_asking_for_a_coordinator_marks_it(owner):
    row = succession.auto_root(_payload())
    assert row["reason"] == succession.AUTO_REASON and row["title"] == "Brain coordination"
    assert O in succession.roots() and guards.chain_root(O, sessions.app_meta(O))
    assert succession.auto_root(_payload()) is None   # marked once; the row is left as it is


@pytest.mark.parametrize("prompt", ["Fix the flaky test in the queue.", "coordinates of the map",
                                    "fix the coordination between the alerts"])
def test_a_prompt_that_asks_for_no_coordinator_marks_nothing(owner, prompt):
    assert succession.auto_root(_payload(prompt)) is None and O not in succession.roots()


def test_a_session_another_session_started_is_never_marked(owner, monkeypatch):
    monkeypatch.setenv(sessions.HOST_ENV, F)   # coordinator F, started by E
    assert succession.auto_root(_payload(sid=CLI[F])) is None and F not in succession.roots()


def test_a_later_prompt_marks_nothing_whatever_path_the_payload_names(owner, tmp_path):
    """Review finding 1: a hand run on a session with turns, with an empty or invented transcript_path, is judged on
    the session's own transcript."""
    _transcript(O, FIRST + "\n" + json.dumps({"type": "assistant", "message": {"content": []}}))
    for path in ("", str(tmp_path / "none.jsonl"), str(tmp_path)):
        assert succession.auto_root(_payload(transcript=path)) is None
    assert O not in succession.roots()


def test_no_transcript_or_a_completed_turn_fails_closed(owner):
    (paths.projects_dir() / "E--lab" / f"{CLI[O]}.jsonl").unlink()
    assert succession.auto_root(_payload()) is None
    _transcript(O)
    f = sessions.app_file(O)
    data = json.loads(f.read_text(encoding="utf-8"))
    f.write_text(json.dumps({**data, "completedTurns": 1}), encoding="utf-8")
    assert succession.auto_root(_payload()) is None and succession.roots() == {}


def test_first_prompt_reads_the_transcript(tmp_path):
    t = tmp_path / "t.jsonl"
    meta = json.dumps({"type": "user", "isMeta": True, "message": {"content": "<command-message>x"}})
    t.write_text(FIRST + "\n" + meta + "\n", encoding="utf-8")
    assert succession.first_prompt(t)   # a skill's expansion is no second prompt (finding 7)
    with t.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "user", "message": {"content": "again"}}) + "\n")
    assert not succession.first_prompt(t) and not succession.first_prompt(tmp_path / "none.jsonl")


def test_an_id_the_app_does_not_know_or_another_transcripts_is_not_marked(owner, monkeypatch):
    assert succession.auto_root(_payload(sid="other-transcript")) is None   # the app's file names another session
    monkeypatch.setenv(sessions.HOST_ENV, "local_66666666-0000-4000-8000-666666666666")
    assert succession.auto_root(_payload(sid="x")) is None
    monkeypatch.delenv(sessions.HOST_ENV)
    assert succession.auto_root(_payload()) is None and succession.roots() == {}


def test_the_hook_marks_it_tells_the_owner_and_never_fails(owner, monkeypatch, capsys):
    assert midsession.hook_main(["UserPromptSubmit"], io.StringIO(json.dumps(_payload()))) == 0
    assert O in succession.roots()
    out = json.loads(capsys.readouterr().out)
    assert "marked a coordinators' chain root" in out["systemMessage"] and "--clear" in out["systemMessage"]
    assert (owner.home / "announce" / f"{CLI[O]}.root").is_file()   # judged: the fast path holds from now on

    def boom(data):
        raise RuntimeError("boom")
    monkeypatch.setattr(succession, "auto_root", boom)
    assert midsession.hook_main(["UserPromptSubmit"], io.StringIO(json.dumps(_payload()))) == 0


def test_the_bash_hook_starts_python_for_a_coordinator_prompt_until_judged(tmp_path, brain_home):
    """Review finding 4: SessionStart writes the mark, so without the bypass the first prompt never reached Python."""
    sh = _bash()
    if not sh:
        pytest.skip("no bash")
    root = tmp_path / "proj"
    (root / "records" / "ddr").mkdir(parents=True)
    payload = {"session_id": "s-1", "cwd": str(root), "hook_event_name": "UserPromptSubmit", "prompt": "hello"}
    midsession.baseline(payload)
    ran = tmp_path / "python-ran"
    fake = tmp_path / "fake-python"
    fake.write_text(f"#!/usr/bin/env bash\necho ran >> '{ran.as_posix()}'\n", encoding="utf-8", newline="\n")
    fake.chmod(0o755)

    def run(prompt):
        env = dict(os.environ, BRAIN_HOME=str(brain_home), BRAIN_PYTHON=str(fake), CLAUDE_PLUGIN_ROOT=str(PLUGIN))
        subprocess.run([sh, str(PLUGIN / "hooks" / "midsession.sh")], input=json.dumps({**payload, "prompt": prompt}),
                       capture_output=True, text=True, env=env, timeout=60, check=True)
        return ran.read_text().count("ran") if ran.exists() else 0

    assert run("hello") == 0                      # the fast path: no Python
    assert run("Tu es le Coordinateur") == 1      # a coordinator named: Python judges it
    (brain_home / "announce" / "s-1.root").write_text("judged\n", encoding="utf-8")
    assert run("Coordinateur again") == 1         # judged once: the fast path again


@pytest.mark.parametrize("command", [
    "python hooks/midsession.py UserPromptSubmit", "python -X utf8 -I /x/hooks/midsession.py UserPromptSubmit",
    "python -m brain.midsession", "python -mbrain.midsession",
    'python -c "from brain.succession import auto_root; auto_root({})"',
    'python -c "from brain.midsession import hook_main; hook_main([])"',
    'python -c "import brain.midsession as m; m.hook_main([])"',
    "bash hooks/midsession.sh", "CLAUDECODE= python3 midsession.py", "cmd /c python 'hooks\\midsession.py'",
    "pypy3 midsession.py"])
def test_the_guard_refuses_the_hook_entry_run_by_hand(tmp_path, brain_home, command):
    reason = bash(tmp_path, command)
    assert reason and "the chain root's hook entry (midsession.py) run by hand refused" in reason, command


@pytest.mark.parametrize("command", [
    "python -m pytest tests/test_handover_auto_root.py", "python -m pytest -q -k auto_root",
    'bash -c "cat hooks/midsession.sh"', "grep -rn auto_root src", "cat hooks/midsession.py",
    "uv run pytest tests/test_handover_auto_root.py"])
def test_reading_or_testing_the_hook_is_not_refused(tmp_path, brain_home, command):
    """Review finding 3: the module's own tests and a read through a shell pass."""
    assert "chain root" not in (bash(tmp_path, command) or ""), command


def test_powershell_forms(tmp_path, brain_home):
    assert "hook entry" in (pwsh(tmp_path, 'python -c "from brain.midsession import hook_main"') or "")
    assert "chain root" not in (pwsh(tmp_path, "python -m pytest tests/test_handover_auto_root.py") or "")
