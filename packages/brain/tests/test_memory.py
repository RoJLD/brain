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

from brain import cli, memory, memorykeys

DAY = "2026-11-02"
SECRET = "token ghp_" + "a1B2c3D4e5" * 4  # a GitHub token's shape, not a token


class FakeGh:
    """gh as the sync calls it: PR list (with each head read from the origin), create, edit, comment, close."""

    def __init__(self, origin=None):
        self.calls = []
        self.open = {}  # branch -> {number, url, headRefName, body, reviews}
        self.origin = origin

    def head(self, branch):
        if self.origin is None:
            return ""
        p = subprocess.run(["git", "--git-dir", str(self.origin), "rev-parse", "-q", "--verify", f"refs/heads/{branch}"],
                           capture_output=True, text=True, timeout=30)
        return p.stdout.strip()

    def __call__(self, args, data=None):
        self.calls.append((args, data))
        if args[:2] == ["pr", "list"]:
            return json.dumps([dict(p, headRefOid=self.head(b)) for b, p in self.open.items()])
        if args[:2] == ["pr", "create"]:
            branch = args[args.index("--head") + 1]
            n = 100 + len(self.open) + len([c for c in self.calls if c[0][:2] == ["pr", "create"]])
            self.open[branch] = {"number": n, "url": f"https://github.com/o/r/pull/{n}", "headRefName": branch,
                                 "body": data, "reviews": []}
            return f"https://github.com/o/r/pull/{n}"
        if args[:2] == ["pr", "edit"]:
            for p in self.open.values():
                if str(p["number"]) == args[2]:
                    p["body"] = data
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
    w.origin, w.work, w.mem, w.gh = origin, work, claude / "projects" / "K" / "memory", FakeGh(origin)

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
    ("l", "m", {}, {"m"}, "conflict"),                     # first sync: a same-name note main never had
    ("l", "m", {"base": "l"}, set(), "import"),
    ("l", "m", {"base": "m"}, set(), "export"),
    ("l", "m", {"base": "b"}, set(), "conflict"),
    ("l", "m2", {"base": "b", "conflict": {"local": "l", "main": "m", "branch": "x"}}, set(), "resolved"),
    ("l", "m", {"base": "b", "conflict": {"local": "l", "main": "m", "branch": "x"}}, set(), "conflict"),
    ("l2", "l1", {"sent": "l1"}, set(), "export"),          # this machine's new note merged, then edited again
    ("l2", "l1", {"base": "b", "sent": "l1"}, set(), "export"),
    (None, "m", {"declined": "m"}, set(), "kept"),          # an import put back by brain memory undo stays undone
    ("l", "m", {"base": "m", "declined": "m"}, set(), "kept"),
    ("l", "m2", {"base": "m", "declined": "m"}, set(), "conflict"),   # main moved on: decided as usual
])
def test_decide(local, main, entry, history, want):
    assert memory.decide(local, main, entry, history, lambda branch: False)[0] == want


def test_a_conflict_merged_keeping_main_s_note_is_resolved():
    entry = {"base": None, "conflict": {"local": "l", "main": "m", "branch": "memory/m1/2026-11-01"}}
    closed = lambda branch: False  # noqa: E731
    assert memory.decide("l", "m", entry, set(), closed, lambda branch: True)[0] == "resolved"
    assert memory.decide("l", "m", entry, set(), closed, lambda branch: False)[0] == "conflict"   # closed unmerged


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
    world.sync()   # the bases recorded: a.md is main's
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
    world.sync()   # the same body: pushed, no PR call
    assert world.gh.verbs()[-1] == "pr close" and world.show(f"memory/m1/{DAY}", "memory/K/b.md") == "b v3\n"
    (world.mem / "c.md").write_text("c\n", encoding="utf-8")
    world.sync()   # a body of its own, unchanged since: edited
    assert world.gh.verbs()[-1] == "pr edit" and "`memory/K/c.md` (new)" in world.gh.open[f"memory/m1/{DAY}"]["body"]


def test_a_note_with_a_secret_stays_here_alone_and_the_others_go_on(world, brain_home):
    (world.mem / "b.md").write_text("fine\n", encoding="utf-8")
    (world.mem / "c.md").write_text(f"line one\n{SECRET}\n", encoding="utf-8")
    report = world.sync()
    assert report.hits == ["K/c.md:2 github-token"] and report.actions["K/c.md"] == "secret"
    assert report.pushed and report.exported == ["memory/K/b.md"]
    assert world.show(f"memory/m1/{DAY}", "memory/K/c.md") is None
    assert "K/c.md" not in memory.load_state()["notes"]   # no base: exported once the secret is gone
    alert = " ".join(memory.alert_lines(report))
    assert "K/c.md:2 github-token" in alert and "ghp_" not in alert and "kept on this machine" in alert
    (world.mem / "c.md").write_text("line one\n", encoding="utf-8")
    assert world.sync().actions["K/c.md"] == "export"


def test_import_brings_main_s_notes_and_backs_up_the_old_copy(world, brain_home, tmp_path):
    world.push_main({"memory/K/n.md": "from m2\n", "memory/Absent/x.md": "x\n"})
    world.sync()  # the first sync records the bases
    world.push_main({"memory/K/a.md": "a v2 from m2\n"})
    report = world.sync()
    assert report.actions["K/a.md"] == "import" and "Absent/x.md" not in report.actions
    assert (world.mem / "a.md").read_text(encoding="utf-8") == "a v2 from m2\n"
    assert (world.mem / "n.md").read_text(encoding="utf-8") == "from m2\n"
    backup = brain_home / "memory-sync" / "backup"
    saved = list(backup.rglob("a.*.md"))
    assert [p.read_text(encoding="utf-8") for p in saved] == ["a v1\n"]
    assert saved[0].name == f"a.{memory.blob_id(b'a v1' + bytes([10]))[:12]}.md"   # named by its content's hash
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


def test_an_index_conflict_is_a_conflict_copy_never_a_union(world):
    world.sync()
    (world.mem / "MEMORY.md").write_text("# Mine\n\n- [L](l.md) the agent's own sentence\n- [A](a.md)\n",
                                         encoding="utf-8")
    (world.mem / "l.md").write_text("l\n", encoding="utf-8")
    world.push_main({"memory/K/MEMORY.md": "- [A](a.md)\n- [R](r.md)\n", "memory/K/r.md": "r\n"})
    report = world.sync()
    assert report.actions["K/MEMORY.md"] == "conflict" and report.actions["K/r.md"] == "import"
    branch = f"memory/m1/{DAY}"
    assert world.show(branch, "memory/K/MEMORY.md") == "- [A](a.md)\n- [R](r.md)\n"   # main's, untouched
    assert world.show(branch, "memory/K/MEMORY.conflict-m1.md") == (   # this machine's, as the agent wrote it
        "# Mine\n\n- [L](l.md) the agent's own sentence\n- [A](a.md)\n")
    assert (world.mem / "MEMORY.md").read_text(encoding="utf-8").startswith("# Mine")   # never regenerated here


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


# --- the sync's safety rules (wi-brain-memory-sync-safety, spec-brain-one-brain 4.5 and 4.9) ---

def test_a_same_name_note_without_base_is_a_conflict_never_a_replacement(world):
    world.push_main({"memory/K/n.md": "n written on m2\n"})
    (world.mem / "n.md").write_text("n written here\n", encoding="utf-8")
    report = world.sync()   # no state: n.md here was never main's
    assert report.actions["K/n.md"] == "conflict"
    branch = f"memory/m1/{DAY}"
    assert world.show(branch, "memory/K/n.md") == "n written on m2\n"
    assert world.show(branch, "memory/K/n.conflict-m1.md") == "n written here\n"
    assert (world.mem / "n.md").read_text(encoding="utf-8") == "n written here\n"


def test_a_key_no_project_claims_is_not_exported_nor_watched(world, tmp_path, monkeypatch):
    for key in ("Stray", "Mapped", "E--work-proj", "E--work-proj--claude-worktrees-x", "E--work-proj-old"):
        (tmp_path / "claude" / "projects" / key / "memory").mkdir(parents=True)
        (tmp_path / "claude" / "projects" / key / "memory" / "n.md").write_text(f"{key}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_MEMORY_MAP", "Mapped=Mapped")
    monkeypatch.setattr(memorykeys, "registered_keys", lambda: {memorykeys.path_key("E:/work/proj").lower()})
    report = world.sync()
    assert report.actions["Stray/n.md"] == "unmapped" and "Stray" in " ".join(report.lines())
    assert report.actions["E--work-proj-old/n.md"] == "unmapped"   # a sibling folder is not the project
    assert {"Mapped/n.md", "E--work-proj/n.md", "E--work-proj--claude-worktrees-x/n.md"} <= {
        p[len("memory/"):] for p in report.exported}
    assert world.show(f"memory/m1/{DAY}", "memory/Stray/n.md") is None
    state = memory.load_state()
    assert "Stray" in state["unmapped"] and not memory.needs_run(state)
    (tmp_path / "claude" / "projects" / "Stray" / "memory" / "n.md").write_text("changed\n", encoding="utf-8")
    assert not memory.needs_run(memory.load_state())   # a key left out starts no run
    (world.mem / "a.md").write_text("a v2\n", encoding="utf-8")
    assert memory.needs_run(memory.load_state())
    world.sync()
    new = tmp_path / "claude" / "projects" / "E--work-proj--claude-worktrees-y" / "memory"
    new.mkdir(parents=True)
    (new / "n.md").write_text("from a new worktree\n", encoding="utf-8")
    assert memory.needs_run(memory.load_state())   # a key never seen starts the run that classes it


def test_registered_keys_reads_the_personal_brain_s_registry(tmp_path, monkeypatch):
    personal = tmp_path / "personal"
    (personal / "proj").mkdir(parents=True)
    (personal / "projects.yaml").write_text("p:\n  root: proj\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PERSONAL", str(personal))
    monkeypatch.setenv("BRAIN_PROJECTS", str(personal / "projects.yaml"))
    assert memorykeys.path_key((personal / "proj").resolve()).lower() in memorykeys.registered_keys()
    monkeypatch.delenv("BRAIN_PERSONAL")
    monkeypatch.setattr(memory.paths, "pointer_root", lambda: None)
    assert memorykeys.registered_keys() == set()


def test_a_branch_someone_else_pushed_to_is_left_and_the_notes_go_to_the_next(world, brain_home):
    (world.mem / "b.md").write_text("b\n", encoding="utf-8")
    first = world.sync()
    branch = f"memory/m1/{DAY}"
    run_git(world.work, "fetch", "-q", "origin", f"{branch}:{branch}")   # the owner resolves on the PR branch
    run_git(world.work, "checkout", "-q", branch)
    (world.work / "memory" / "K" / "b.md").write_text("b merged by the owner\n", encoding="utf-8")
    run_git(world.work, "commit", "-qam", "owner's merge")
    run_git(world.work, "push", "-q", "origin", branch)
    run_git(world.work, "checkout", "-q", "main")
    owner_head = run_git(world.work, "rev-parse", branch).strip()
    (world.mem / "c.md").write_text("c\n", encoding="utf-8")
    report = world.sync()
    assert report.left == [branch] and report.branch == f"{branch}-2" and report.pushed
    assert run_git(world.work, "--git-dir", str(world.origin), "rev-parse", branch).strip() == owner_head
    assert world.show(f"{branch}-2", "memory/K/c.md") == "c\n"
    assert report.kept_open == [branch] and first.pr in [p["url"] for p in world.gh.open.values()]
    assert "pr close" not in world.gh.verbs()
    assert "left as it is" in " ".join(memory.alert_lines(report))


def test_a_lease_lost_between_fetch_and_push_overwrites_nothing(world, monkeypatch):
    branch = f"memory/m1/{DAY}"
    real = memory.Sync.push

    def race(self, commit, state):
        if self.branch == branch:   # someone pushes the branch after this run fetched
            run_git(world.work, "push", "-q", "origin", f"main:refs/heads/{branch}")
        return real(self, commit, state)

    monkeypatch.setattr(memory.Sync, "push", race)
    (world.mem / "b.md").write_text("b\n", encoding="utf-8")
    report = world.sync()
    main = run_git(world.work, "rev-parse", "main").strip()
    assert run_git(world.work, "--git-dir", str(world.origin), "rev-parse", branch).strip() == main
    assert report.branch == f"{branch}-2" and report.left == [branch]
    assert world.show(f"{branch}-2", "memory/K/b.md") == "b\n"


def test_a_pr_body_someone_edited_or_a_reviewed_pr_gets_a_comment(world):
    (world.mem / "b.md").write_text("b\n", encoding="utf-8")
    world.sync()
    pr = world.gh.open[f"memory/m1/{DAY}"]
    pr["body"] = "The owner's own notes on this PR.\n"
    (world.mem / "c.md").write_text("c\n", encoding="utf-8")
    report = world.sync()
    assert world.gh.verbs()[-1] == "pr comment" and pr["body"] == "The owner's own notes on this PR.\n"
    assert report.commented == pr["url"]
    pr["body"] = next(d for a, d in world.gh.calls if a[:2] == ["pr", "create"])   # this machine's body, back:
    pr["reviews"] = [{"state": "COMMENTED"}]
    (world.mem / "d.md").write_text("d\n", encoding="utf-8")
    world.sync()
    assert world.gh.verbs()[-1] == "pr comment" and "pr edit" not in world.gh.verbs()


def test_an_older_pr_is_closed_only_while_its_head_is_this_machine_s_push(world):
    (world.mem / "b.md").write_text("b\n", encoding="utf-8")
    world.sync(day="2026-11-01")
    old = "memory/m1/2026-11-01"
    run_git(world.work, "push", "-q", "--force", "origin", f"main:refs/heads/{old}")   # someone else's commit
    (world.mem / "b.md").write_text("b v2\n", encoding="utf-8")
    report = world.sync()
    assert "pr close" not in world.gh.verbs() and report.kept_open == [old]


def test_a_backup_is_named_by_its_hash_and_never_overwritten(brain_home):
    one = memory.backup("K", "a.md", b"first\n")
    assert memory.backup("K", "a.md", b"first\n") == one   # the same content: the same file
    two = memory.backup("K", "a.md", b"second\n")
    assert one != two and one.read_bytes() == b"first\n" and two.read_bytes() == b"second\n"
    one.write_bytes(b"tampered\n")
    memory.backup("K", "a.md", b"first\n")
    assert one.read_bytes() == b"tampered\n"   # an existing backup is never written again


def test_undo_restores_only_while_the_note_holds_what_was_imported(world, brain_home, capsys):
    world.sync()
    world.push_main({"memory/K/a.md": "a v2 from m2\n"})
    world.sync()
    assert (world.mem / "a.md").read_text(encoding="utf-8") == "a v2 from m2\n"
    assert cli.main(["memory", "undo", "K/a.md"]) == 0
    assert (world.mem / "a.md").read_text(encoding="utf-8") == "a v1\n"
    assert "K/a.md" not in memory.load_state().get("imports", {})
    assert cli.main(["memory", "undo", "K/a.md"]) == 1   # nothing recorded any more
    report = world.sync()   # the undo sticks: main's v2 neither imported again nor reverted by an export
    assert report.actions["K/a.md"] == "kept" and not report.pushed
    assert (world.mem / "a.md").read_text(encoding="utf-8") == "a v1\n"

    (world.mem / "a.md").write_text("a v2 from m2\n", encoding="utf-8")   # back to main's, then main moves on
    world.sync()
    world.push_main({"memory/K/a.md": "a v3 from m2\n"})
    world.sync()
    assert (world.mem / "a.md").read_text(encoding="utf-8") == "a v3 from m2\n"
    (world.mem / "a.md").write_text("edited after the import\n", encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["memory", "undo", "K/a.md"]) == 1
    assert (world.mem / "a.md").read_text(encoding="utf-8") == "edited after the import\n"
    assert (world.mem / "a.md.undo-conflict").read_text(encoding="utf-8") == "a v2 from m2\n"
    assert "changed since the import" in capsys.readouterr().out
    assert not [n for n in memory.local_notes() if "undo-conflict" in n]   # never taken for a note
    assert cli.main(["memory", "undo", "no-slash"]) == 1


def test_two_machines_share_one_remote_without_overwriting_each_other(world, tmp_path, monkeypatch):
    """The two-machine harness (spec-brain-one-brain 4.10): two BRAIN_HOMEs, two Claude folders, one bare remote; run
    by the CI on Windows and on Ubuntu."""
    homes = {"m1": Path(os.environ["BRAIN_HOME"]), "m2": tmp_path / "home-m2"}
    claudes = {"m1": tmp_path / "claude", "m2": tmp_path / "claude-m2"}
    (claudes["m2"] / "projects" / "K" / "memory").mkdir(parents=True)

    def on(m):
        monkeypatch.setenv("BRAIN_HOME", str(homes[m]))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claudes[m]))
        monkeypatch.setenv("BRAIN_MACHINE", m)
        return claudes[m] / "projects" / "K" / "memory"

    def merge(branch):   # the owner merges a machine's PR
        run_git(world.work, "fetch", "-q", "origin", f"{branch}:{branch}")
        run_git(world.work, "merge", "-q", "--no-edit", branch)
        run_git(world.work, "push", "-q", "origin", "HEAD:main")
        world.gh.open.pop(branch, None)

    m1 = on("m1")
    world.sync()
    m2 = on("m2")   # a fresh machine: imports main's notes
    assert world.sync().imported == ["K/MEMORY.md", "K/a.md"]
    assert (m2 / "a.md").read_text(encoding="utf-8") == "a v1\n"

    (m2 / "idea.md").write_text("idea from m2\n", encoding="utf-8")   # both write a note of the same name
    m2_report = world.sync()
    on("m1")
    (m1 / "idea.md").write_text("idea from m1\n", encoding="utf-8")
    world.sync()
    merge(m2_report.branch)   # m2's note reaches main first
    report = world.sync()
    assert report.actions["K/idea.md"] == "conflict"
    assert world.show(report.branch, "memory/K/idea.md") == "idea from m2\n"
    assert world.show(report.branch, "memory/K/idea.conflict-m1.md") == "idea from m1\n"
    assert (m1 / "idea.md").read_text(encoding="utf-8") == "idea from m1\n"

    on("m2")   # m2 edits a.md; m1 imports it once merged, with a backup
    (m2 / "a.md").write_text("a v2 from m2\n", encoding="utf-8")
    merge(world.sync(day="2026-11-03").branch)
    on("m1")
    report = world.sync(day="2026-11-03")
    assert report.actions["K/a.md"] == "import" and (m1 / "a.md").read_text(encoding="utf-8") == "a v2 from m2\n"
    assert list((homes["m1"] / "memory-sync" / "backup").rglob("a.*.md"))
    assert (m2 / "idea.md").read_text(encoding="utf-8") == "idea from m2\n"   # m2 never got m1's copy


def test_a_push_is_recorded_even_when_the_pr_step_fails(world, brain_home):
    class Down(FakeGh):
        def __call__(self, args, data=None):
            if args[:2] == ["pr", "create"]:
                raise memory.SyncError("gh: not logged in")
            return super().__call__(args, data)

    (world.mem / "b.md").write_text("b\n", encoding="utf-8")
    assert memory.job_main(force=True, gh=Down(world.origin), day=DAY) == 1
    assert world.branches() == ["main", f"memory/m1/{DAY}"]
    report = world.sync()   # the branch is this machine's own push: no -2, the PR opened now
    assert report.left == [] and report.branch == f"memory/m1/{DAY}" and report.pr


def test_a_held_export_flags_no_conflict(world, monkeypatch):
    world.sync()
    (world.mem / "a.md").write_text("a by m1\n", encoding="utf-8")
    world.push_main({"memory/K/a.md": "a by m2\n"})
    monkeypatch.setattr(memory, "export_held", lambda: "the engine is below engine.min")
    report = world.sync()
    assert report.actions["K/a.md"] == "conflict" and not report.pushed
    assert "conflict" not in memory.load_state()["notes"]["K/a.md"]   # nothing carries it: not flagged
    world.push_main({"memory/K/a.md": "a by m2, again\n"})
    assert world.sync().actions["K/a.md"] == "conflict"   # never "resolved" over a copy no PR carried
    assert (world.mem / "a.md").read_text(encoding="utf-8") == "a by m1\n"


def test_a_refused_push_is_a_failure_not_a_lost_lease(world, monkeypatch):
    real = memory.Runner.__call__

    def refuse(self, argv, data=None, env=None, check=True):
        if "push" in argv:
            return subprocess.CompletedProcess(argv, 1, b"", b" ! [remote rejected] x (pre-receive hook declined)\n")
        return real(self, argv, data, env, check)

    monkeypatch.setattr(memory.Runner, "__call__", refuse)
    (world.mem / "b.md").write_text("b\n", encoding="utf-8")
    with pytest.raises(memory.SyncError, match="pre-receive hook declined"):
        world.sync()
