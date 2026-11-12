"""The tests' template repositories (conftest.git_init, git_repo): copied, never a lock git holds a moment."""

import subprocess

import conftest
from conftest import git_init


def test_the_template_runs_no_background_maintenance(tmp_path):
    """git commit may start `git maintenance run --auto` in the background: its objects/maintenance.lock, made and
    removed while a test copied the template, failed shutil.copytree in CI. The templates turn it off."""
    repo = git_init(tmp_path / "r")
    def get(key):
        return subprocess.run(["git", "-C", str(repo), "config", "--get", key], capture_output=True, text=True,
                              timeout=30).stdout.strip()
    assert get("maintenance.auto") == "false" and get("gc.auto") == "0"


def test_a_lock_in_the_template_is_not_copied(tmp_path):
    template = conftest._template("work")
    lock = template / ".git" / "objects" / "maintenance.lock"
    lock.write_text("", encoding="utf-8")
    try:
        repo = git_init(tmp_path / "r")
        assert not (repo / ".git" / "objects" / "maintenance.lock").exists()
        assert (repo / ".git" / "HEAD").is_file()
    finally:
        lock.unlink()


def test_head_sha_reads_the_loose_ref_and_falls_back_to_git(make_repo, monkeypatch):
    """make_repo.commit returns HEAD's sha without a git process when the branch's ref is a loose file; a packed ref,
    a detached HEAD and another branch give the same answer as git rev-parse (wi-brain-test-speed-2)."""
    repo = make_repo("r", {"a.txt": "a\n"})
    git = conftest.run_git

    def rev_parse():
        return git(repo, "rev-parse", "HEAD").strip()

    def no_git(*args):
        raise AssertionError(f"head_sha ran git {args[1:]}")
    with monkeypatch.context() as m:   # a loose ref (and a detached HEAD below): no git process
        m.setattr(conftest, "run_git", no_git)
        first = make_repo.commit(repo, {"a.txt": "b\n"})
    assert first == rev_parse()
    git(repo, "pack-refs", "--all")   # the loose ref is gone: rev-parse answers
    assert not (repo / ".git" / "refs" / "heads" / "main").exists() and conftest.head_sha(repo) == first
    git(repo, "checkout", "-q", "-b", "feat")
    assert make_repo.commit(repo, {"a.txt": "c\n"}) == rev_parse() != first
    git(repo, "checkout", "-q", "--detach", first)
    with monkeypatch.context() as m:
        m.setattr(conftest, "run_git", no_git)
        assert conftest.head_sha(repo) == first
