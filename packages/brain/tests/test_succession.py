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
from test_guards_remote_control import E, F, G, K, R, X, Z, call, refused

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


# --- the successor's brief with ultracode, and the wait for its first turn (the owner's decision of 2026-11-12) ---

def test_write_with_a_successor_writes_its_brief_with_ultracode_first(lab, capsys):
    assert cli.main(["handover", "write", "--id", F, "--successor", "coordinator-g"]) == 0
    out = capsys.readouterr().out
    note = guards.handover_note(F)
    brief = note.with_name(note.stem + succession.BRIEF_SUFFIX)
    assert str(brief) in out and "ultracode" in out
    text = brief.read_text(encoding="utf-8")
    first = text.splitlines()[0]
    assert first.startswith("ultracode") and "coordinator-g" in first and F in first and "(coordinator-f)" in first
    assert f"archive_session {F}" in text and note.as_posix() in text
    assert "none of its children blocks" in text and f"ask {F} to detach them" in text   # before the archive
    assert not brief.name.endswith(".md") and guards.handover_note(F) == note   # the guard never reads it as a note


def test_write_without_a_successor_writes_no_brief(lab):
    note = succession.write_note("x", host=F)
    assert not list(note.parent.glob(f"*{succession.BRIEF_SUFFIX}"))


def test_wait_returns_at_once_for_a_live_successor(lab, capsys):
    assert cli.main(["handover", "wait", "--id", F, "--successor", G]) == 0
    assert f"{G} is idle after" in capsys.readouterr().out


def test_wait_polls_a_starting_successor_until_its_first_turn(lab):
    rc.starting(lab)
    t = [0.0]
    polls = []

    def sleep(s):
        polls.append(s)
        t[0] += s
        if len(polls) == 2:
            lab.turn(G, "running")   # its first turn: the transcript is written

    r = succession.wait(G, F, timeout=60, poll=3, clock=lambda: t[0], sleep=sleep)
    assert r["ok"] and r["state"] == "running" and len(polls) == 2 and r["waited_s"] == 6.0


def test_wait_is_bounded_and_says_a_starting_successor_still_passes(lab, capsys):
    rc.starting(lab)
    t = [0.0]

    def sleep(s):
        t[0] += s

    r = succession.wait(G, F, timeout=10, poll=3, clock=lambda: t[0], sleep=sleep)
    assert not r["ok"] and r["state"] == "starting" and "no first turn after 10 s" in r["why"]
    assert cli.main(["handover", "wait", "--id", F, "--successor", G, "--timeout", "0"]) == 1
    out = capsys.readouterr().out
    assert "(starting)" in out and "wait again and retry once" in out
    t[0] = 0.0
    assert succession.wait(G, F, timeout=10 ** 6, poll=100, clock=lambda: t[0], sleep=sleep)["why"].startswith(
        f"no first turn after {succession.WAIT_MAX_S} s")   # the bound is capped
    assert t[0] == succession.WAIT_MAX_S


@pytest.mark.parametrize("target, why", [(K, "is not a Brain coordinator"), (X, "was not started by this session")])
def test_wait_refuses_at_once_what_is_no_successor(lab, target, why):
    r = succession.wait(target, F, timeout=60, clock=lambda: 0.0, sleep=lambda s: pytest.fail("no wait"))
    assert not r["ok"] and why in r["why"]


def test_wait_refuses_an_archived_successor_and_a_bad_id(lab, capsys):
    lab.put(G, parent=F, name="coordinator-g", archived=True, detached=True)
    r = succession.wait(G, F, timeout=60, clock=lambda: 0.0, sleep=lambda s: pytest.fail("no wait"))
    assert not r["ok"] and r["state"] == "archived"
    assert cli.main(["handover", "wait", "--id", F, "--successor", "nope"]) == 2
    assert "is not an app id" in capsys.readouterr().err


@pytest.mark.parametrize("kw, why", [({"name": "worker-g"}, "is not a Brain coordinator"),
                                     ({"parent": X}, "was not started by this session")])
def test_wait_refuses_at_once_a_starting_session_that_is_no_successor(lab, kw, why, capsys):
    rc.starting(lab, **kw)
    r = succession.wait(G, F, timeout=60, clock=lambda: 0.0, sleep=lambda s: pytest.fail("no wait"))
    assert not r["ok"] and why in r["why"]
    assert cli.main(["handover", "wait", "--id", F, "--successor", G]) == 1
    assert "retry once" not in capsys.readouterr().out   # the guard refuses it: no hint that it would pass


def test_wait_names_an_id_the_app_does_not_know(lab):
    unknown = "local_77777777-0000-4000-8000-777777777777"
    r = succession.wait(unknown, F, timeout=0)
    assert not r["ok"] and r["state"] == "unknown" and "not in the desktop app's session files" in r["why"]


def test_wait_says_a_live_successor_not_detached(lab, capsys):
    lab.put(G, parent=F, name="coordinator-g", detached=None)
    lab.turn(G, "idle")
    assert cli.main(["handover", "wait", "--id", F, "--successor", G]) == 0
    assert "detach it" in capsys.readouterr().out
    assert succession.wait(G, F)["detached"] is False


def test_a_note_written_again_without_a_successor_drops_the_old_brief(lab, capsys):
    assert cli.main(["handover", "write", "--id", F, "--successor", "coordinator-g"]) == 0
    note = guards.handover_note(F)
    brief = note.with_name(note.stem + succession.BRIEF_SUFFIX)
    assert brief.exists()
    assert cli.main(["handover", "write", "--id", F]) == 0
    assert not brief.exists() and "brief beside it removed" in capsys.readouterr().out


# --- the children line: each session it started, archived, detached or blocking (wi-brain-handover-detach-children) ---

def test_children_line_says_which_child_blocks_and_what_it_needs(lab, capsys):
    succession.write_note("body", host=F)
    assert cli.main(["handover", "check", "--id", F]) == 0   # a blocking child changes no exit code
    out = capsys.readouterr().out
    assert "children     2 of 3 blocking: detach each live one" in out and "only the session that started it" in out
    assert f"- {G} (coordinator-g): detached" in out
    assert f"- {K} (rc-guard): blocking (idle): archive it once its work is merged and verified, else detach it" in out
    assert f"- {R} (busy): blocking (running): detach it" in out
    assert cli.main(["handover", "check", "--id", F, "--json"]) == 0
    r = json.loads(capsys.readouterr().out)
    assert r["blocking"] == [K, R] and [c["verdict"] for c in r["children"]] == ["detached", "blocking", "blocking"]
    assert r["ok"] and r["on"] and r["off"]   # the guard's conditions are unchanged
    assert decide(call(lab, G, True)) is None   # and the guard lets on through with children blocking


def test_children_archived_or_detached_do_not_block(lab):
    lab.put(K, parent=F, name="rc-guard", archived=True)
    lab.put(R, parent=F, name="busy", detached=True)
    r = succession.check(F)
    assert r["blocking"] == []
    assert {c["id"]: c["verdict"] for c in r["children"]} == {G: "detached", K: "archived", R: "detached"}
    assert "children     none of 3 blocking (archived or detached)" in succession.lines(r)


def test_a_child_with_no_transcript_blocks_as_unknown_or_starting(lab):
    old, new = (f"local_{c * 8}-0000-4000-8000-{c * 12}" for c in "45")
    cli = "-cli0-4000-8000-000000000000"
    lab.put(old, parent=F, name="gone", created=1_000, cli=old[6:14] + cli)   # created long ago, no transcript here
    lab.put(new, parent=F, name="fresh", cli=new[6:14] + cli,
            created=int(datetime.now(timezone.utc).timestamp() * 1000))
    kids = {c["id"]: c for c in succession.check(F)["children"]}
    assert kids[old]["verdict"] == "blocking" and kids[old]["state"] == "unknown" and "check it" in kids[old]["advice"]
    assert kids[new]["verdict"] == "blocking" and kids[new]["state"] == "starting"
    assert kids[new]["advice"] == "detach it"


def test_a_child_whose_app_file_cannot_be_read_again_blocks():
    h = "local_66666666-0000-4000-8000-666666666666"
    kids = succession.children(F, {h: {"parent": F, "name": "twice"}, G: {"parent": E}}, lambda _: {})
    assert [(c["id"], c["name"], c["state"], c["verdict"]) for c in kids] == [(h, "twice", "unknown", "blocking")]
    assert "check it" in kids[0]["advice"]


def test_no_predecessor_line_for_a_root_and_none_without_children(lab, chain):
    o, c1, c2 = chain
    succession.mark_root(o, "a chain", env={})
    out = "\n".join(succession.lines(succession.check(o)))
    assert "predecessor" not in out and "children     none of 1 blocking" in out   # c1, detached
    lone = "local_77777777-0000-4000-8000-777777777777"
    lab.put(lone, title="A session on its own", cli=lone[6:14] + "-cli0-4000-8000-000000000000")
    assert "children     none (no session it started)" in succession.lines(succession.check(lone))


def test_predecessor_line_archive_only_once_none_of_its_children_blocks(lab):
    assert f"predecessor  {E}: archived already" in succession.lines(succession.check(F))
    lab.put(E, name="coordinator-e", parent=Z, title="Coordination du Brain — coordinateur E")   # live again
    r = succession.check(F)
    assert r["parent_blocking"] == [X, F] and not r["parent_archived"]
    out = "\n".join(succession.lines(r))
    assert f"predecessor  {E}: archive it only once none of its children blocks: 2 blocking" in out
    assert "detach_session works only for the session that started the child" in out
    assert f"- {F} (coordinator-f, this session): blocking (running): detach it" in out
    assert f"- {X} (cousin): blocking (idle)" in out
    lab.put(F, parent=E, name="coordinator-f", detached=True)
    lab.put(X, parent=E, name="cousin", detached=True)
    out = "\n".join(succession.lines(succession.check(F)))
    assert f"predecessor  {E}: none of its children blocks: an incoming coordinator archives it first" in out
