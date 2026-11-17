import subprocess
import sys
import time

from proc_tree import Tree, all_gone, holder

# a parent that starts its child again the moment it ends: a kill one process after another (taskkill /T, leaf
# first) leaves the parent the time to start one that the kill never saw
_RESTARTER = "import subprocess, sys\nwhile True:\n    subprocess.run([sys.executable, '-c', sys.argv[1]])\n"


def _wait_for(pidfile, bound=60.0):
    end = time.monotonic() + bound
    while not (pidfile.exists() and pidfile.read_text(encoding="utf-8").strip()) and time.monotonic() < end:
        time.sleep(0.05)
    assert pidfile.read_text(encoding="utf-8").strip(), "the child never started"


def test_kill_ends_the_tree_and_a_child_its_parent_starts_again(tmp_path):
    """kill() alone, its job still open (its close would kill on its own on Windows): the parent, its child and any
    child it started again are gone."""
    pidfile = tmp_path / "held.pid"
    with Tree([sys.executable, "-c", _RESTARTER, holder(pidfile)], stdin=subprocess.DEVNULL) as tree:
        _wait_for(pidfile)
        tree.kill()
        assert tree.child.poll() is not None
        gone = time.monotonic() + 10
        while not all_gone(pidfile) and time.monotonic() < gone:
            time.sleep(0.2)
        assert all_gone(pidfile)
        time.sleep(1)   # a child started again during the kill would have written its pid by now
        assert all_gone(pidfile)


def test_a_tree_whose_child_ends_by_itself_is_closed_quietly(tmp_path):
    with Tree([sys.executable, "-c", "pass"], stdin=subprocess.DEVNULL) as tree:
        assert tree.child.wait(timeout=60) == 0
