import io
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import GIT_ENV, git_init, run_git
from test_capture import PLUGIN, _bash

from brain import cli, memory

DAY = "2026-11-02"
SECRET = "token ghp_" + "a1B2c3D4e5" * 4  # a GitHub token's shape, not a token


class FakeGh:
    """gh as the sync calls it: PR list, create, edit, close."""

    def __init__(self):
        self.calls = []
        self.open = {}  # branch -> {number, url, headRefName}

    def __call__(self, args, data=None):
        self.calls.append((args, data))
        if args[:2] == ["pr", "list"]:
            return json.dumps(list(self.open.values()))
        if args[:2] == ["pr", "create"]:
            branch = args[args.index("--head") + 1]
            n = 100 + len(self.open) + len([c for c in self.calls if c[0][:2] == ["pr", "create"]])
            self.open[branch] = {"number": n, "url": f"https://github.com/o/r/pull/{n}", "headRefName": branch}
            return f"https://github.com/o/r/pull/{n}"
        if args[:2] == ["pr", "close"]:
            self.open = {b: p for b, p in self.open.items() if str(p["number"]) != args[2]}
        return ""

    def verbs(self):
        return [" ".join(a[:2]) for a, _ in self.calls if a[:2] != ["pr", "list"]]


@pytest.fixture
def world(tmp_path, monkeypatch):
    """An origin with main holding memory/K/a.md and MEMORY.md, a work clone to change main as another machine
    would, and this machine's Claude projects folder with project K."""
    if not shutil.which("git"):
        pytest.skip("git not available")
    for k, v in GIT_ENV.items():
        monkeypatch.setenv(k, v)
    origin = tmp_path / "origin.git"
    git_init(origin, bare=True)
    work = tmp_path / "work"
    run_git(tmp_path, "clone", "-q", str(origin), str(work))
    run_git(work, "config", "commit.gpgsign", "false")
    claude = tmp_path / "claude"
    (claude / "projects" / "K" / "memory").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude))
    monkeypatch.setenv("BRAIN_MEMORY_REMOTE", str(origin))
    monkeypatch.setenv("BRAIN_MACHINE", "m1")
    for k in ("BRAIN_MEMORY_SYNC", "BRAIN_MEMORY_MAP", "BRAIN_MEMORY_PULL_HOURS", "BRAIN_GH"):
        monkeypatch.delenv(k, raising=False)

    class World:
        pass

    w = World()
    w.origin, w.work, w.mem, w.gh = origin, work, claude / "projects" / "K" / "memory", FakeGh()

    def push_main(files, message="main"):
        for path, text in files.items():
            f = work / path
            if text is None:
                f.unlink()
            else:
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(text.encode("utf-8"))
        run_git(work, "add", "-A")
        run_git(work, "commit", "-q", "-m", message)
        run_git(work, "push", "-q", "origin", "HEAD:main")

    def show(ref, path):
        p = subprocess.run(["git", "--git-dir", str(origin), "show", f"{ref}:{path}"], capture_output=True)
        return p.stdout.decode("utf-8") if p.returncode == 0 else None

    def branches():
        out = run_git(tmp_path, "--git-dir", str(origin), "for-each-ref", "--format=%(refname:short)", "refs/heads")
        return sorted(out.split())

    def sync(**kw):
        state = memory.load_state()
        report = memory.sync(day=kw.pop("day", DAY), gh=w.gh, state=state, **kw)
        if not kw.get("dry_run"):
            memory.save_state(state)
        return report

    w.push_main, w.show, w.branches, w.sync = push_main, show, branches, sync
    push_main({"memory/K/a.md": "a v1\n", "memory/K/MEMORY.md": "- [A](a.md)\n"}, "init")
    (w.mem / "a.md").write_text("a v1\n", encoding="utf-8", newline="\n")
    (w.mem / "MEMORY.md").write_text("- [A](a.md)\n", encoding="utf-8", newline="\n")
    return w


# --- pure parts ---

@pytest.mark.parametrize("local, main, entry, history, want", [
    ("x", "x", {}, set(), "same"),
    (None, "m", {}, set(), "import"),
    ("l", None, {}, set(), "export"),
    ("l", None, {"base": "l"}, set(), "kept"),             # deleted on main, unchanged here
    ("l", None, {"base": "b"}, set(), "export"),           # deleted on main, changed here
    ("l", "m", {}, {"l", "m"}, "import"),                  # first sync: the local copy is an old one of main's
    ("l", "m", {}, {"m"}, "export"),                       # first sync: a local copy main never had
    ("l", "m", {"base": "l"}, set(), "import"),
    ("l", "m", {"base": "m"}, set(), "export"),
    ("l", "m", {"base": "b"}, set(), "conflict"),
    ("l", "m2", {"base": "b", "conflict": {"local": "l", "main": "m", "branch": "x"}}, set(), "resolved"),
    ("l", "m", {"base": "b", "conflict": {"local": "l", "main": "m", "branch": "x"}}, set(), "conflict"),
])
def test_decide(local, main, entry, history, want):
    assert memory.decide(local, main, entry, history, lambda branch: False)[0] == want


def test_flagged_conflict_stays_while_its_pr_is_open():
    entry = {"base": "b", "conflict": {"local": "l", "main": "m", "branch": "memory/m1/2026-11-01"}}
    assert memory.decide("l", "m2", entry, set(), lambda branch: True)[0] == "conflict"


def test_blob_id_is_git_s(tmp_path):
    if not shutil.which("git"):
        pytest.skip("git not available")
    data = "é note\n".encode("utf-8")
    f = tmp_path / "n.md"
    f.write_bytes(data)
    assert memory.blob_id(data) == subprocess.run(["git", "hash-object", "--no-filters", str(f)], capture_output=True,
                                                  text=True).stdout.strip()
    assert memory.normalize(b"a\r\nb\r\n") == b"a\nb\n"


def test_union_keeps_both_sides_lines():
    assert memory.union_lines(b"- a\n- b\n", b"- a\n- c\n\n- c\n") == b"- a\n- b\n- c\n"


def test_key_map_renames_and_leaves_out(tmp_path, monkeypatch):
    claude = tmp_path / "c"
    for key in ("-home-a-work", "tmp-probe", "Other"):
        (claude / "projects" / key / "memory").mkdir(parents=True)
        (claude / "projects" / key / "memory" / "n.md").write_text("n\n", encoding="utf-8")
    (claude / "projects" / "Other" / "memory" / "n.conflict-m2.md").write_text("x\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude))
    monkeypatch.setenv("BRAIN_MEMORY_MAP", "-home-a-work=D--work; tmp-probe=")
    assert sorted(memory.local_notes()) == ["D--work/n.md", "Other/n.md"]
    assert memory.local_dir("D--work") == claude / "projects" / "-home-a-work" / "memory"
    assert memory.local_dir("tmp-probe") is None and memory.local_dir("Absent") is None


# --- the sync against a local origin ---

def test_export_pushes_the_branch_of_the_day_and_opens_one_pr(world):
    (world.mem / "a.md").write_text("a v2\n", encoding="utf-8")
    (world.mem / "b.md").write_bytes(b"b\r\nnew\r\n")
    report = world.sync()
    assert report.actions == {"K/MEMORY.md": "same", "K/a.md": "export", "K/b.md": "export"}
    assert report.pushed and report.pr == "https://github.com/o/r/pull/101"
    assert world.branches() == ["main", f"memory/m1/{DAY}"]
    assert world.show("main", "memory/K/a.md") == "a v1\n"  # never main
    assert world.show(f"memory/m1/{DAY}", "memory/K/a.md") == "a v2\n"
    assert world.show(f"memory/m1/{DAY}", "memory/K/b.md") == "b\nnew\n"  # LF in the repo
    (args, body), = [c for c in world.gh.calls if c[0][:2] == ["pr", "create"]]
    assert args[args.index("--title") + 1] == f"Memory from m1, {DAY}"
    assert "`memory/K/b.md` (new)" in body and "`memory/K/a.md` (edited)" in body
    log = run_git(world.work, "--git-dir", str(world.origin), "log", "--format=%P %s", f"memory/m1/{DAY}", "-1")
    assert log.split()[0] == run_git(world.work, "--git-dir", str(world.origin), "rev-parse", "main").strip()

    again = world.sync()  # idempotent: nothing pushed, no PR call
    assert not again.pushed and again.pr == report.pr
    assert world.gh.verbs() == ["pr create"]
    assert memory.load_state()["snapshot"] == memory.snapshot(memory.local_notes())
    assert not memory.needs_run(memory.load_state())


def test_a_later_change_updates_the_same_pr_and_supersedes_an_older_one(world):
    (world.mem / "b.md").write_text("b\n", encoding="utf-8")
    world.sync(day="2026-11-01")
    (world.mem / "b.md").write_text("b v2\n", encoding="utf-8")
    report = world.sync()
    assert world.gh.verbs() == ["pr create", "pr create", "pr close"]
    close = [a for a, _ in world.gh.calls if a[:2] == ["pr", "close"]][0]
    assert "--delete-branch" in close and report.pr in close[close.index("--comment") + 1]
    (world.mem / "b.md").write_text("b v3\n", encoding="utf-8")
    world.sync()
    assert world.gh.verbs()[-1] == "pr edit" and world.show(f"memory/m1/{DAY}", "memory/K/b.md") == "b v3\n"


def test_a_secret_refuses_the_whole_export(world):
    (world.mem / "b.md").write_text("fine\n", encoding="utf-8")
    (world.mem / "c.md").write_text(f"line one\n{SECRET}\n", encoding="utf-8")
    report = world.sync()
    assert report.hits == ["K/c.md:2 github-token"] and not report.pushed
    assert world.branches() == ["main"] and world.gh.verbs() == []
    alert = " ".join(memory.alert_lines(report))
    assert "K/c.md:2 github-token" in alert and "ghp_" not in alert


def test_import_brings_main_s_notes_and_backs_up_the_old_copy(world, brain_home, tmp_path):
    world.push_main({"memory/K/n.md": "from m2\n", "memory/Absent/x.md": "x\n"})
    world.sync()  # the first sync records the bases
    world.push_main({"memory/K/a.md": "a v2 from m2\n"})
    report = world.sync()
    assert report.actions["K/a.md"] == "import" and "Absent/x.md" not in report.actions
    assert (world.mem / "a.md").read_text(encoding="utf-8") == "a v2 from m2\n"
    assert (world.mem / "n.md").read_text(encoding="utf-8") == "from m2\n"
    backup = brain_home / "memory-sync" / "backup"
    assert [p.read_text(encoding="utf-8") for p in backup.rglob("a.md")] == ["a v1\n"]
    assert not (tmp_path / "claude" / "projects" / "Absent").exists()  # no project folder is created
    assert world.branches() == ["main"]


def test_first_sync_treats_a_copy_main_once_had_as_old(world):
    world.push_main({"memory/K/a.md": "a v2\n"})
    report = world.sync()  # no state: a.md here is main's v1
    assert report.actions["K/a.md"] == "import" and (world.mem / "a.md").read_text(encoding="utf-8") == "a v2\n"


def test_export_only_leaves_main_s_changes(world, monkeypatch):
    world.sync()
    world.push_main({"memory/K/a.md": "a v2\n"})
    monkeypatch.setenv("BRAIN_MEMORY_SYNC", "export")
    assert memory.job_main(force=True, gh=world.gh, day=DAY) == 0
    assert (world.mem / "a.md").read_text(encoding="utf-8") == "a v1\n"


def test_conflict_keeps_both_then_imports_once_resolved(world, brain_home):
    world.sync()
    (world.mem / "a.md").write_text("a by m1\n", encoding="utf-8")
    world.push_main({"memory/K/a.md": "a by m2\n"})
    report = world.sync()
    assert report.actions["K/a.md"] == "conflict" and report.conflicts == ["K/a.md"]
    branch = f"memory/m1/{DAY}"
    assert world.show(branch, "memory/K/a.md") == "a by m2\n"
    assert world.show(branch, "memory/K/a.conflict-m1.md") == "a by m1\n"
    (args, body), = [c for c in world.gh.calls if c[0][:2] == ["pr", "create"]]
    assert "conflict" in args[args.index("--title") + 1] and "a.conflict-m1.md" in body
    assert "conflicting note" in " ".join(memory.alert_lines(report))
    assert (world.mem / "a.md").read_text(encoding="utf-8") == "a by m1\n"  # nothing lost here

    world.sync()  # still flagged: the same branch, nothing pushed
    assert memory.load_state()["notes"]["K/a.md"]["conflict"]["local"]

    world.push_main({"memory/K/a.md": "a by m1 and m2\n"})  # the reviewer merged both and closed the PR
    world.gh.open.clear()
    report = world.sync(day="2026-11-03")
    assert report.actions["K/a.md"] == "resolved"
    assert (world.mem / "a.md").read_text(encoding="utf-8") == "a by m1 and m2\n"
    assert "conflict" not in memory.load_state()["notes"]["K/a.md"]


def test_index_conflict_is_the_union_of_lines(world):
    world.sync()
    (world.mem / "MEMORY.md").write_text("- [A](a.md)\n- [L](l.md)\n", encoding="utf-8")
    (world.mem / "l.md").write_text("l\n", encoding="utf-8")
    world.push_main({"memory/K/MEMORY.md": "- [A](a.md)\n- [R](r.md)\n", "memory/K/r.md": "r\n"})
    report = world.sync()
    assert report.actions["K/MEMORY.md"] == "conflict" and report.actions["K/r.md"] == "import"
    assert world.show(f"memory/m1/{DAY}", "memory/K/MEMORY.md") == "- [A](a.md)\n- [R](r.md)\n- [L](l.md)\n"


def test_a_note_deleted_on_main_is_kept_here_and_not_exported_again(world):
    world.sync()
    world.push_main({"memory/K/a.md": None})
    report = world.sync()
    assert report.actions["K/a.md"] == "kept" and (world.mem / "a.md").exists() and world.branches() == ["main"]


def test_status_writes_nothing(world, capsys):
    (world.mem / "b.md").write_text("b\n", encoding="utf-8")
    assert cli.main(["memory", "status"]) == 0
    out = capsys.readouterr().out
    assert "export    K/b.md" in out and "same      2 note(s)" in out and "nothing written" in out
    assert world.branches() == ["main"] and memory.load_state() == {}
    assert cli.main(["memory", "status", "--offline"]) == 0


def test_no_remote_is_a_failure_in_the_alert(world, monkeypatch, brain_home):
    monkeypatch.delenv("BRAIN_MEMORY_REMOTE")
    monkeypatch.setattr(memory.paths, "installed_checkout", lambda: None)
    monkeypatch.setattr(memory.paths, "package_repo", lambda: None)
    lock = brain_home / "memory-sync" / "run.json"  # and the last job died holding the lock
    lock.parent.mkdir(parents=True)
    lock.write_text(json.dumps({"pid": 1, "at": "2026-11-01T00:00:00Z"}), encoding="utf-8")
    os.utime(lock, (time.time() - 3600, time.time() - 3600))
    assert memory.job_main(force=True, gh=world.gh) == 1
    alert = (brain_home / "memory-sync" / "alert.txt").read_text(encoding="utf-8").splitlines()
    assert "never finished" in alert[0] and "no remote" in alert[1]
    assert json.loads((brain_home / "memory-sync" / "last.json").read_text(encoding="utf-8"))["result"] == "failed"


def test_a_clean_run_clears_the_alert(world, brain_home):
    memory.write_alert(["old trouble"])
    (world.mem / "b.md").write_text("b\n", encoding="utf-8")
    assert memory.job_main(force=True, gh=world.gh, day=DAY) == 0
    assert not (brain_home / "memory-sync" / "alert.txt").exists()
    assert json.loads((brain_home / "memory-sync" / "last.json").read_text(encoding="utf-8"))["exported"] == [
        "memory/K/b.md"]


# --- the hook ---

def test_session_end_spawns_only_when_needed(world, monkeypatch, brain_home):
    spawned = []
    monkeypatch.setattr(memory, "_spawn", spawned.append)

    def no_process(*args, **kwargs):
        raise AssertionError(f"the SessionEnd decision started a process: {args[:1]}")
    with monkeypatch.context() as m:   # the hook returns at once: its decision starts no process but the job
        m.setattr(subprocess, "Popen", no_process)
        assert memory.hook_main(["session-end"], stdin=io.StringIO("{}")) == 0 and len(spawned) == 1
    assert spawned[0][:3] == [sys.executable, "-I", "-c"]
    assert memory.session_end() is False  # one queued job is enough: it rescans when it starts
    (brain_home / "memory-sync" / "queued.json").unlink()
    world.sync()
    assert memory.session_end() is False  # nothing changed, pulled just now
    (world.mem / "a.md").write_text("a v2\n", encoding="utf-8")
    assert memory.session_end() is True
    monkeypatch.setenv("BRAIN_MEMORY_SYNC", "0")
    (brain_home / "memory-sync" / "queued.json").unlink()
    assert memory.session_end() is False


def test_pull_is_due_after_the_interval(world, monkeypatch):
    world.sync()
    state = memory.load_state()
    assert not memory.needs_run(state)
    assert memory.needs_run(state, now=time.time() + 13 * 3600)
    monkeypatch.setenv("BRAIN_MEMORY_PULL_HOURS", "0")
    assert not memory.needs_run(state, now=time.time() + 13 * 3600)


def test_a_dead_job_s_lock_is_alerted_and_broken(world, brain_home, monkeypatch):
    monkeypatch.setenv("BRAIN_MEMORY_TIMEOUT", "1")
    lock = brain_home / "memory-sync" / "run.json"
    lock.parent.mkdir(parents=True)
    lock.write_text(json.dumps({"pid": 1, "at": "2026-11-01T00:00:00Z"}), encoding="utf-8")
    old = time.time() - 60
    os.utime(lock, (old, old))
    assert memory._acquire(wait=1, stale=2)
    assert "never finished" in (brain_home / "memory-sync" / "alert.txt").read_text(encoding="utf-8")
    assert not memory._acquire(wait=0, stale=2)  # held now


def test_hook_scripts_end_to_end(world, brain_home, tmp_path):
    """The real detached job: memory.sh SessionEnd returns at once, the job pushes the branch afterwards; then the
    SessionStart hook prints the alert as JSON.

    The job's gh waits for a gate the test opens only once the hook has returned: the hook returning while the job
    still waits proves it detached, with no bound on seconds that a loaded machine overran (it once took more than
    the 10 s it allowed, wi-brain-test-speed-2). A hook that ran the job itself would block on the gate past its 60 s
    timeout; that the decision itself starts no process is test_session_end_spawns_only_when_needed's."""
    bash = _bash()
    if not bash:
        pytest.skip("no bash")
    gate = tmp_path / "gate"
    fake = tmp_path / "fake_gh.py"
    fake.write_text("import pathlib, sys, time\nargs = sys.argv[1:]\n"
                    f"gate, end = pathlib.Path({str(gate)!r}), time.monotonic() + 120\n"
                    "while not gate.exists() and time.monotonic() < end:\n    time.sleep(0.05)\n"
                    "if args[:2] == ['pr', 'list']: print('[]')\n"
                    "elif args[:2] == ['pr', 'create']: print('https://github.com/o/r/pull/7')\n", encoding="utf-8")
    (world.mem / "b.md").write_text("b\n", encoding="utf-8")
    env = dict(os.environ, BRAIN_HOME=str(brain_home), BRAIN_PYTHON=sys.executable,
               BRAIN_GH=json.dumps([sys.executable, str(fake)]), BRAIN_MEMORY_REPO="o/r",
               CLAUDE_PLUGIN_ROOT=str(PLUGIN))
    last = brain_home / "memory-sync" / "last.json"
    try:   # the gate opens whatever fails here: no job left waiting on gh past the test
        out = subprocess.run([bash, str(PLUGIN / "hooks" / "memory.sh"), "SessionEnd"], input="{}",
                             capture_output=True, text=True, env=env, timeout=60)
        assert out.returncode == 0 and out.stdout == ""
        assert not last.exists(), last.read_text(encoding="utf-8")   # the job waits on gh: it has not finished
    finally:
        gate.write_text("", encoding="utf-8")
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if last.exists() and not (brain_home / "memory-sync" / "run.json").exists():
            break
        time.sleep(0.05)
    result = json.loads(last.read_text(encoding="utf-8"))
    assert result["result"] == "ok" and result["pr"] == "https://github.com/o/r/pull/7", result
    assert world.show(result["branch"], "memory/K/b.md") == "b\n"

    out = subprocess.run([bash, str(PLUGIN / "hooks" / "memory.sh"), "SessionStart"], capture_output=True, text=True,
                         env=env, timeout=30)
    assert out.stdout == ""  # no alert
    memory.write_alert(['refused "x" in K\\c.md:2\tgithub-token', "second line"])
    out = subprocess.run([bash, str(PLUGIN / "hooks" / "memory.sh"), "SessionStart"], capture_output=True, text=True,
                         env=env, timeout=30)
    ctx = json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]
    assert ctx == 'refused "x" in K\\c.md:2 github-token\nsecond line\n'


# --- the sync's record through brain.stateio (wi-brain-state-safe-io-rest) ---

def test_a_newer_brains_sync_state_is_refused_before_any_fetch(world, brain_home):
    f = brain_home / "memory-sync" / "state.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text('{"v": 2, "notes": {}}', encoding="utf-8")
    assert memory.job_main(force=True, gh=world.gh) == 1
    assert f.read_text(encoding="utf-8") == '{"v": 2, "notes": {}}' and world.branches() == ["main"]
    last = json.loads((brain_home / "memory-sync" / "last.json").read_text(encoding="utf-8"))
    assert last["result"] == "failed" and "newer brain" in last["error"]
    assert "brain update" in (brain_home / "memory-sync" / "alert.txt").read_text(encoding="utf-8")
    assert memory.load_state() == {"notes": {}}  # still read, as it is: brain memory status


def test_the_sync_state_is_saved_with_its_v_backed_up_and_set_aside_when_unreadable(brain_home):
    memory.save_state({"notes": {"K/a.md": "x"}})
    memory.save_state({"notes": {}})
    f = memory.sync_dir() / "state.json"
    assert json.loads(f.read_text(encoding="utf-8")) == {"v": memory.STATE_V, "notes": {}}
    assert json.loads((f.parent / "state.json.bak").read_text(encoding="utf-8"))["notes"] == {"K/a.md": "x"}
    f.write_text("[1]", encoding="utf-8")
    assert memory.load_state() == {} and f.exists()  # a read moves nothing
    assert memory.load_state(write=True) == {} and not f.exists()
    assert len(list(f.parent.glob("state.json.unreadable-*"))) == 1
