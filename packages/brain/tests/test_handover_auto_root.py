"""wi-brain-handover-auto-root (HANDOVER-1): a coordinators' chain root marked by its first prompt. The
UserPromptSubmit hook (midsession) marks a session the owner started (no parent in the app's files) when its first
prompt asks for a coordinator; a later prompt, a session another session started, or a prompt that asks for none,
marks nothing; the guard refuses a session that runs the hook's entry by hand. On the invented sessions of
test_guards_remote_control's lab."""

import io
import json

import pytest
import test_guards_remote_control as rc
from test_guards import bash
from test_guards_remote_control import CLI, F

from brain import guards, midsession, sessions, succession

lab = rc.lab   # the lab's fixture: invented sessions in the desktop app's files
O = "local_77777777-0000-4000-8000-777777777777"   # a session the owner started
ASK = "Tu es le coordinateur du Brain : reprends la vague 0.4.1."


@pytest.fixture
def owner(lab, monkeypatch):
    monkeypatch.setitem(CLI, O, "77777777-cli0-4000-8000-000000000000")
    lab.put(O, title="Brain coordination")
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


@pytest.mark.parametrize("prompt", ["Fix the flaky test in the queue.", "coordinates of the map"])
def test_a_prompt_that_asks_for_no_coordinator_marks_nothing(owner, prompt):
    assert succession.auto_root(_payload(prompt)) is None and O not in succession.roots()


def test_a_session_another_session_started_is_never_marked(owner, monkeypatch):
    monkeypatch.setenv(sessions.HOST_ENV, F)   # coordinator F, started by E
    assert succession.auto_root(_payload(sid=CLI[F])) is None and F not in succession.roots()


def test_a_later_prompt_marks_nothing(owner, tmp_path):
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps({"type": "user", "message": {"content": "hello"}}) + "\n", encoding="utf-8")
    assert succession.first_prompt(t) and succession.first_prompt(tmp_path / "none.jsonl")
    with t.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}}) + "\n")
    assert not succession.first_prompt(t)
    assert succession.auto_root(_payload(transcript=str(t))) is None and O not in succession.roots()
    two = tmp_path / "two.jsonl"
    two.write_text("".join(json.dumps({"type": "user", "message": {"content": p}}) + "\n" for p in "ab"),
                   encoding="utf-8")
    assert not succession.first_prompt(two)


def test_an_id_the_app_does_not_know_or_another_transcripts_is_not_marked(owner, monkeypatch):
    assert succession.auto_root(_payload(sid="other-transcript")) is None   # the app's file names another session
    monkeypatch.setenv(sessions.HOST_ENV, "local_66666666-0000-4000-8000-666666666666")
    assert succession.auto_root(_payload(sid="x")) is None
    monkeypatch.delenv(sessions.HOST_ENV)
    assert succession.auto_root(_payload()) is None and succession.roots() == {}


def test_the_userpromptsubmit_hook_marks_it_and_never_fails(owner, monkeypatch):
    stdin = io.StringIO(json.dumps(_payload()))
    assert midsession.hook_main(["UserPromptSubmit"], stdin) == 0 and O in succession.roots()

    def boom(data):
        raise RuntimeError("boom")
    monkeypatch.setattr(succession, "auto_root", boom)
    assert midsession.hook_main(["UserPromptSubmit"], io.StringIO(json.dumps(_payload()))) == 0


@pytest.mark.parametrize("command", [
    "python hooks/midsession.py UserPromptSubmit", "python -X utf8 -I /x/hooks/midsession.py UserPromptSubmit",
    "python -m brain.midsession", 'python -c "from brain.succession import auto_root; auto_root({})"',
    "bash hooks/midsession.sh", "CLAUDECODE= python3 midsession.py"])
def test_the_guard_refuses_the_hook_entry_run_by_hand(tmp_path, brain_home, command):
    reason = bash(tmp_path, command)
    assert reason and "the chain root's hook entry (midsession.py) run by hand refused" in reason, command


def test_reading_the_hook_is_not_refused(tmp_path, brain_home):
    assert not guards._root_hook(["grep", "auto_root", "midsession.py"])
    assert not guards._root_hook(["cat", "hooks/midsession.sh"])
    assert guards._root_hook(["uv", "run", "python", "midsession.py"])
