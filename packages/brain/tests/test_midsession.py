import contextlib
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import run_git
from test_capture import PLUGIN, _bash

from brain import decisions, midsession

AT = "2026-11-02T09:00:00Z"
OPTS = ["Telegram: one bot, already set up", "Email: SMTP"]


def _project(base: Path) -> Path:
    (base / "notes" / "graph").mkdir(parents=True, exist_ok=True)
    (base / "notes" / "graph" / "schema.yaml").write_text("node_types: [DDR]\n", encoding="utf-8")
    (base / "records" / "ddr").mkdir(parents=True)
    return base


def _ask(root, slug, session="ada-tui"):
    decisions.ask(root, title=f"Question {slug}", question="Which?", options=OPTS, why="set up", at=AT, slug=slug,
                  session=session)


def _check(root, sid="s-1"):
    return midsession.check({"session_id": sid, "cwd": str(root)})


def _age(*paths: Path) -> None:
    """Put mtimes well before the mark: the mark is a whole second before its scan, so a file written within a second
    of a scan reads as newer and starts Python once more (harmless, but not what a fast-path test checks)."""
    t = time.time() - 100
    for f in paths:
        os.utime(f, (t, t))


def test_queue_is_the_main_checkouts(git_repo):
    main = _project(git_repo)
    run_git(main, "add", "-A")
    run_git(main, "commit", "-q", "-m", "queue")
    wt = main / ".claude" / "worktrees" / "wt"
    run_git(main, "worktree", "add", "-q", "-b", "wt", str(wt))
    queue = (main / "records" / "ddr").resolve()
    assert midsession.queue_dir(wt / "notes") == queue
    assert midsession.queue_dir(main) == queue
    assert midsession.queue_dir(main.parent) is None


def test_answered_and_newly_asked_are_announced_once(tmp_path):
    root = _project(tmp_path / "proj")
    _ask(root, "before")
    assert _check(root) == ""  # no mark yet: set silently
    assert (midsession.state_dir() / "s-1.json").is_file()
    assert _check(root) == ""
    decisions.answer(root, "before", ["Email"], at=AT)
    _ask(root, "new")
    _ask(root, "mine", session="s-1")
    text = _check(root)
    assert text.startswith("Ada's decision queue in proj changed during this session: 1 answered, 1 newly asked.")
    assert "`brain decision ack <id> --applied <where>`" in text
    assert "- answered ddr-2026-11-02-before: Email (Question before)" in text
    assert "- asked ddr-2026-11-02-new: Question new (waits on Ada)" in text
    assert "mine" not in text  # this session asked it: not news
    assert _check(root) == ""  # the mark moved
    decisions.answer(root, "mine", ["Telegram"], other="", at=AT)
    assert "- answered ddr-2026-11-02-mine: Telegram" in _check(root)  # its answer is news
    decisions.ack(root, "before", ["adr-x"], at=AT)
    assert _check(root) == ""  # integrated, archived: not announced
    decisions.answer(root, "before", [], other="redo it", at=AT, again=True)
    assert "- answered ddr-2026-11-02-before: other: redo it" in _check(root)
    assert _check(root, sid="s-2") == ""  # another session has its own mark


def test_session_start_sets_the_mark_after_announcing(tmp_path):
    root = _project(tmp_path / "proj")
    _ask(root, "old")
    decisions.answer(root, "old", ["Email"], at=AT)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        decisions.hook_main(["SessionStart"], stdin=io.StringIO(json.dumps({"session_id": "s-1", "cwd": str(root)})))
    assert "ddr-2026-11-02-old: Email" in json.loads(out.getvalue())["hookSpecificOutput"]["additionalContext"]
    assert _check(root) == ""  # announced at the start: not again
    _ask(root, "late")
    assert "- asked ddr-2026-11-02-late" in _check(root)


def test_moving_to_another_project_resets_the_mark_silently(tmp_path):
    a, b = _project(tmp_path / "a"), _project(tmp_path / "b")
    assert _check(a) == ""
    _ask(b, "elsewhere")
    assert _check(b) == ""
    assert json.loads((midsession.state_dir() / "s-1.json").read_text(encoding="utf-8"))["queue"] == str(
        (b / "records" / "ddr").resolve())
    assert _check(tmp_path) == ""  # outside a project: a mark with no queue


def test_rows_are_capped(tmp_path):
    root = _project(tmp_path / "proj")
    assert _check(root) == ""
    for i in range(12):
        _ask(root, f"q{i:02d}")
    text = _check(root)
    rows = text.splitlines()[1:]
    assert len(rows) == midsession.MAX_ROWS and rows[-1] == "- and 5 more: `brain decision pending`"
    assert len(text) <= midsession.CAP


def test_old_marks_are_pruned(tmp_path):
    root = _project(tmp_path / "proj")
    assert _check(root, sid="old") == ""
    old = time.time() - 30 * 86400
    for f in midsession.state_dir().glob("old.*"):
        os.utime(f, (old, old))
    midsession.baseline({"session_id": "s-1", "cwd": str(root)})
    assert sorted(f.name for f in midsession.state_dir().iterdir()) == ["s-1.json", "s-1.mark"]


def test_hook_never_fails(tmp_path, brain_home):
    root = _project(tmp_path / "proj")
    for raw in ("", "not json", "[1]", json.dumps({"cwd": str(root)}), json.dumps({"session_id": "../x"})):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert midsession.hook_main(["UserPromptSubmit"], stdin=io.StringIO(raw)) == 0
        assert out.getvalue() == ""
    brain_home.mkdir(parents=True, exist_ok=True)
    (brain_home / "announce").write_text("a file where the folder goes", encoding="utf-8")
    with contextlib.redirect_stdout(io.StringIO()):
        assert midsession.hook_main([], stdin=io.StringIO(json.dumps({"session_id": "s-1", "cwd": str(root)}))) == 0
    assert "midsession-announce" in (brain_home / "ledger" / "errors.log").read_text(encoding="utf-8")


def test_hook_entry_reads_utf8_bytes(tmp_path, brain_home):
    """midsession.py runs with python -I (standard library only) and reads its stdin as UTF-8, a BOM dropped."""
    root = _project(tmp_path / "projé")
    payload = {"session_id": "s-1", "cwd": str(root)}
    script = PLUGIN / "hooks" / "midsession.py"
    env = dict(os.environ, BRAIN_HOME=str(brain_home))

    def run():
        out = subprocess.run([sys.executable, "-I", str(script), "UserPromptSubmit"], env=env, timeout=30,
                             input=b"\xef\xbb\xbf" + json.dumps(payload, ensure_ascii=False).encode(),
                             capture_output=True)
        assert out.returncode == 0 and out.stderr == b""
        return out.stdout.decode()

    assert run() == ""
    _ask(root, "q")
    assert "- asked ddr-2026-11-02-q" in json.loads(run())["hookSpecificOutput"]["additionalContext"]


def test_hook_script_fast_path_and_announce(tmp_path, brain_home):
    """midsession.sh starts no Python while nothing is newer than the mark; then midsession.py announces."""
    bash = _bash()
    if not bash:
        pytest.skip("no bash")
    root = _project(tmp_path / "proj")
    _ask(root, "q")
    queue, ddr = root / "records" / "ddr", root / "records" / "ddr" / "ddr-2026-11-02-q.yaml"
    _age(ddr, queue)
    payload = json.dumps({"session_id": "s-1", "cwd": str(root), "hook_event_name": "UserPromptSubmit"})
    midsession.baseline(json.loads(payload))
    ran = tmp_path / "python-ran"
    fake = tmp_path / "fake-python"
    fake.write_text(f"#!/usr/bin/env bash\necho ran >> '{ran.as_posix()}'\n", encoding="utf-8", newline="\n")
    fake.chmod(0o755)

    def run(python, data=payload):
        env = dict(os.environ, BRAIN_HOME=str(brain_home), BRAIN_PYTHON=python, CLAUDE_PLUGIN_ROOT=str(PLUGIN))
        out = subprocess.run([bash, str(PLUGIN / "hooks" / "midsession.sh")], input=data, capture_output=True,
                             text=True, env=env, timeout=60)
        assert out.returncode == 0 and out.stderr == ""
        return out.stdout

    def runs():
        return ran.read_text().count("ran") if ran.exists() else 0

    assert run(fake.as_posix()) == "" and runs() == 0  # fast path: nothing newer than the mark
    decisions.answer(root, "q", ["Email"], at=AT)  # rewritten in place: only the file's mtime moves
    assert run(fake.as_posix()) == "" and runs() == 1  # a DDR changed: Python runs
    out = json.loads(run(sys.executable))
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "- answered ddr-2026-11-02-q: Email (Question q)" in out["hookSpecificOutput"]["additionalContext"]
    _age(ddr, queue)
    assert run(fake.as_posix()) == "" and runs() == 1  # the mark moved: fast path again
    assert "ddr-2026-11-02-q" not in (brain_home / "announce" / "s-1.mark").read_text(encoding="utf-8")
    decisions.ack(root, "q", ["adr-x"], at=AT)
    assert run(fake.as_posix()) == "" and runs() == 1  # only the pending DDRs are watched: an ack is not news
    (queue / "ddr-2026-11-02-new.yaml").write_text("id: ddr-2026-11-02-new\nstatus: pending\n", encoding="utf-8")
    assert run(fake.as_posix()) == "" and runs() == 2  # a new DDR file
    other = json.dumps({"session_id": "s-1", "cwd": str(tmp_path), "hook_event_name": "UserPromptSubmit"})
    _age(ddr, queue, queue / "ddr-2026-11-02-new.yaml")
    assert run(fake.as_posix(), other) == "" and runs() == 3  # another folder: Python decides


def test_hooks_json_runs_midsession_at_each_prompt():
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    (entry,) = [h for m in hooks["UserPromptSubmit"] for h in m["hooks"]]
    assert entry["command"].endswith('hooks/midsession.sh"') and not entry.get("async") and entry["timeout"] <= 5
