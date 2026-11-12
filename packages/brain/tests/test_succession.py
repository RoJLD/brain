"""brain handover write|check|root (wi-brain-handover-command, brain.succession): the coordinator's hand-over note,
its own app id first; the guard's conditions read before the Remote Control calls, and the predecessor to archive;
the chain root, the owner's mark in their own terminal, refused to a session. On the invented sessions of
test_guards_remote_control's lab (coordinator F started by coordinator E; G its detached successor)."""

import json
import os
from datetime import datetime, timezone

import pytest
import test_guards_remote_control as rc
from test_guards import bash, decide, payload, pwsh
from test_guards_remote_control import E, F, G, K, call, refused

from brain import cli, guards, sessions, succession

lab, chain = rc.lab, rc.chain   # the lab's fixtures: invented sessions in the desktop app's files


def test_write_puts_the_sessions_own_id_first_and_the_guard_reads_it(lab, monkeypatch):
    monkeypatch.setenv(sessions.HOST_ENV, F)
    f = succession.write_note(f"# Hand-over\nThe successor G is `{G}`, its predecessor `{E}`.\n",
                              successor="coordinator-g")
    text = f.read_text(encoding="utf-8")
    assert f.name.startswith("coordinator-") and f.name.endswith("-f.md")
    assert text.startswith(f"From {F} (coordinator-f), ") and "Successor: coordinator-g" in text
    assert guards.LOCAL_ID.search(text).group(0) == F and guards.handover_note(F) == f
    monkeypatch.delenv(sessions.HOST_ENV)
    assert decide(call(lab, G, True)) is None   # the guard takes it


def test_write_needs_an_app_id(lab, monkeypatch, capsys):
    monkeypatch.delenv(sessions.HOST_ENV, raising=False)
    with pytest.raises(succession.SuccessionError, match="no app id"):
        succession.write_note("x")
    assert cli.main(["handover", "write"]) == 2 and "no app id" in capsys.readouterr().err


def test_write_takes_its_body_from_a_file(lab, tmp_path, capsys):
    body = tmp_path / "note.md"
    body.write_text("# What is open\n- PR 1\n", encoding="utf-8")
    assert cli.main(["handover", "write", "--id", F, "--from", str(body), "--successor", "coordinator-g"]) == 0
    f = guards.handover_note(F)
    assert f and "# What is open\n- PR 1\n" in f.read_text(encoding="utf-8") and str(f) in capsys.readouterr().out


def test_check_says_each_condition_and_the_predecessor(lab, monkeypatch, capsys):
    monkeypatch.setenv(sessions.HOST_ENV, F)
    assert cli.main(["handover", "check"]) == 1
    out = capsys.readouterr().out
    assert "a coordinator by name" in out and f"started by   {E} (coordinator-e): ok" in out
    assert "note         NONE" in out and f"predecessor  {E}" in out
    succession.write_note("body")
    assert cli.main(["handover", "check"]) == 0
    out = capsys.readouterr().out
    assert f"successors   {G}" in out and "on           ok" in out and "off          ok" in out
    assert cli.main(["handover", "check", "--json", "--successor", K]) == 1   # on would be refused for K
    r = json.loads(capsys.readouterr().out)
    assert r["ok"] and r["successor"] == K and not r["on"] and "is not a Brain coordinator" in r["on_why"]


def test_check_of_an_unknown_session_is_an_error(lab, capsys):
    assert cli.main(["handover", "check", "--id", "local_77777777-0000-4000-8000-777777777777"]) == 2
    assert "not in the desktop app's session files" in capsys.readouterr().err


def test_check_agrees_with_the_guard_on_a_root(lab, chain):
    o, c1, _ = chain
    succession.write_note("x", host=o)
    r = succession.check(o)
    assert not r["ok"] and "nor a chain root" in r["why"]
    refused(lab, call(lab, c1, True, caller=o), "this session is not a Brain coordinator")
    succession.mark_root(o, "the chain of a new wave", env={})
    r = succession.check(o)
    assert r["ok"] and r["root"] and r["on"] and r["off"] and not r["parent"]
    assert decide(call(lab, c1, True, caller=o)) is None
    assert "chain root" in "\n".join(succession.lines(r))


def test_root_is_the_owners_alone(lab, chain, monkeypatch, capsys):
    o, _, _ = chain
    monkeypatch.setenv("CLAUDECODE", "1")
    assert cli.main(["handover", "root", o]) == 2 and "owner's mark" in capsys.readouterr().err
    assert not guards.roots_file().exists()
    monkeypatch.delenv("CLAUDECODE")
    assert cli.main(["handover", "root", o, "--reason", "a new wave"]) == 0
    assert o in succession.roots() and cli.main(["handover", "root"]) == 0 and o in capsys.readouterr().out
    assert cli.main(["handover", "root", F]) == 2   # a session started F
    assert cli.main(["handover", "root", o, "--clear"]) == 0 and succession.roots() == {}
    assert cli.main(["handover", "root", "local_x"]) == 2
    assert cli.main(["handover", "root", "--clear"]) == 2 and "--clear needs" in capsys.readouterr().err
    assert cli.main(["handover", "root", "local_77777777-0000-4000-8000-777777777777"]) == 2   # unknown to the app
    monkeypatch.setenv("CLAUDECODE", "")   # set, even empty: a Claude Code shell
    assert cli.main(["handover", "root", o]) == 2 and o not in succession.roots()


def test_the_guard_refuses_the_mark_to_a_session(tmp_path, brain_home):
    for command in ("brain handover root local_x", "python -m brain handover root", "brain --project x handover root"):
        reason = bash(tmp_path, command)
        assert reason and "brain handover root refused: it marks a coordinators' chain root" in reason, command
    assert "marks a coordinators' chain root" in pwsh(tmp_path, "brain.exe handover root local_x")
    roots = guards.roots_file().as_posix()
    assert "marks a coordinators' chain root" in bash(tmp_path, f"echo '{{}}' > {roots}")
    assert "marks the coordinators' chain roots" in decide(payload("Write", tmp_path, file_path=roots, content="{}"))
    assert bash(tmp_path, "brain handover check") is None and bash(tmp_path, "brain handover write --from n.md") is None


@pytest.mark.parametrize("command", [
    'brain handover "root" local_x', "brain handover ro''ot local_x", "r=root; brain handover $r local_x",
    "python -I -m brain handover root local_x", "python -X utf8 -m brain handover root local_x",
    "CLAUDECODE= python -I -m brain handover root local_x"])
def test_the_mark_is_refused_whatever_runs_it_or_however_it_is_spelled(tmp_path, brain_home, command):
    from test_guards import _needs_python
    assert _needs_python([command]) == [True], command
    reason = bash(tmp_path, command)
    assert reason and "marks a coordinators' chain root" in reason, command


def test_the_marks_file_and_folder_are_refused_in_any_spelling(tmp_path, brain_home):
    roots = guards.roots_file()
    roots.parent.mkdir(parents=True, exist_ok=True)
    for command in (f"cp /x/roots.json {roots.parent.as_posix()}/", f"rm -rf {roots.parent.as_posix()}",
                    f"mv /x {roots.parent.as_posix()}"):
        assert "marks a coordinators' chain root" in (bash(tmp_path, command) or ""), command
    if os.name == "nt":
        stream = f"{roots.as_posix()}::$DATA"
        assert "marks a coordinators' chain root" in (bash(tmp_path, f"echo x > '{stream}'") or "")
        assert "chain roots" in (decide(payload("Write", tmp_path, file_path=stream, content="{}")) or "")


@pytest.mark.skipif(os.name == "nt", reason="symbolic links need a privilege on Windows")
def test_a_linked_marks_file_marks_nothing(lab, chain, tmp_path):
    o, _, _ = chain
    real = tmp_path / "elsewhere.json"
    real.write_text(json.dumps({"v": 1, "roots": {o: {}}}), encoding="utf-8")
    guards.roots_file().parent.mkdir(parents=True, exist_ok=True)
    guards.roots_file().symlink_to(real)
    assert guards.chain_roots() == {}


def test_the_prefilter_starts_python_for_the_mark():
    from test_guards import _needs_python
    # any handover word starts Python, which reads it
    assert _needs_python(["brain handover root local_x", "brain handover  root", "brain handover check"]) == [
        True, True, True]


def test_a_note_too_big_for_the_guard_is_refused(lab):
    with pytest.raises(succession.SuccessionError, match="over"):
        succession.write_note("x" * guards.HANDOVER_MAX, host=F)


def test_note_names_are_safe_and_never_shared():
    t = datetime(2026, 11, 12, 12, tzinfo=timezone.utc).timestamp()
    assert succession.note_name("coordinator-033", t) == "coordinator-2026-11-12-033.md"
    assert succession.note_name("", t, "local_1234abcd-0000") == "coordinator-2026-11-12-root-1234abcd.md"
    assert succession.note_name("", t, "local_99998888-0000") != succession.note_name("", t, "local_1234abcd-0000")
    assert succession.note_name("../x y", t) == "coordinator-2026-11-12-x-y.md"
    assert succession.note_name("coordinateur-033", t) != succession.note_name("coordinator-033", t)


def test_a_note_of_another_session_is_never_overwritten(lab):
    f = succession.write_note("F's", host=F)
    with pytest.raises(succession.SuccessionError, match=f"{F}'s note"):
        succession.write_note("G's", host=G, name="coordinator-f")
    assert guards.handover_note(F) == f


def test_write_reads_a_utf16_body(lab, tmp_path, capsys):
    body = tmp_path / "note.md"
    body.write_bytes("\ufeffÉtat: ok\n".encode("utf-16-le"))   # PowerShell 5.1's >: UTF-16 LE with a BOM
    assert cli.main(["handover", "write", "--id", F, "--from", str(body)]) == 0
    assert "État: ok" in guards.handover_note(F).read_text(encoding="utf-8")
    body.write_bytes(b"\x93\xff\x00bad")
    assert cli.main(["handover", "write", "--id", F, "--from", str(body)]) == 2
