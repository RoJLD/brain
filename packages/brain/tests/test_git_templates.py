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
