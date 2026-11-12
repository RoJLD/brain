"""How the suite itself runs (conftest's own hooks, wi-brain-test-speed-2)."""

from types import SimpleNamespace

import conftest


class _Config:
    def __init__(self, dist, numprocesses, xdist=True):
        self.option = SimpleNamespace(dist=dist, numprocesses=numprocesses)
        self.pluginmanager = SimpleNamespace(hasplugin=lambda name: xdist and name == "xdist")

    def getoption(self, name, default=None):
        return getattr(self.option, name, default)


def _dist(dist, numprocesses, xdist=True):
    config = _Config(dist, numprocesses, xdist)
    conftest.pytest_cmdline_main(config)
    return config.option.dist


def test_parallel_runs_steal_work_unless_told_otherwise():
    """-n N or -n auto with no --dist: worksteal; an explicit --dist is kept; no -n, -n 0 or no xdist: one process."""
    assert _dist("no", 16) == "worksteal"
    assert _dist("no", "auto") == "worksteal"
    assert _dist("load", 16) == "load" and _dist("loadfile", "auto") == "loadfile"
    assert _dist("no", None) == "no" and _dist("no", 0) == "no"
    assert _dist("no", 16, xdist=False) == "no"

