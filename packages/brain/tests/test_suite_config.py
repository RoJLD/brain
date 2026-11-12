"""How the suite itself runs (conftest's own hooks, wi-brain-test-speed-2)."""

import os
from pathlib import Path
from types import SimpleNamespace

import conftest
import pytest


class _Config:
    def __init__(self, dist, numprocesses, xdist=True, maxschedchunk=None):
        self.option = SimpleNamespace(dist=dist, numprocesses=numprocesses, maxschedchunk=maxschedchunk)
        self.pluginmanager = SimpleNamespace(hasplugin=lambda name: xdist and name == "xdist")

    def getoption(self, name, default=None):
        return getattr(self.option, name, default)


def _dist(dist, numprocesses, xdist=True, maxschedchunk=None):
    config = _Config(dist, numprocesses, xdist, maxschedchunk)
    conftest.pytest_cmdline_main(config)
    return config.option.dist


def test_parallel_runs_steal_work_unless_told_otherwise():
    """-n N or -n auto with no --dist: worksteal; an explicit --dist is kept, and load when --maxschedchunk asks for
    it; no -n, -n 0 or no xdist: one process."""
    assert _dist("no", 16) == "worksteal"
    assert _dist("no", "auto") == "worksteal"
    assert _dist("load", 16) == "load" and _dist("loadfile", "auto") == "loadfile"
    assert _dist("no", 4, maxschedchunk=1) == "no"   # xdist then makes it load, with that chunk
    assert _dist("no", None) == "no" and _dist("no", 0) == "no"
    assert _dist("no", 16, xdist=False) == "no"


def test_the_hook_runs_before_xdist_turns_no_dist_into_load(pytestconfig):
    """The hook only works ahead of xdist's own pytest_cmdline_main, which turns dist "no" into "load": were it to run
    after (its tryfirst dropped, xdist's hooks reordered), every -n run would silently go back to load."""
    xdist = pytestconfig.pluginmanager.get_plugin("xdist")
    if xdist is None:
        return   # no xdist: nothing to order against
    order = [impl.plugin for impl in reversed(pytestconfig.hook.pytest_cmdline_main.get_hookimpls())]
    ours = next(i for i, p in enumerate(order)
                if Path(getattr(p, "__file__", "") or ".").resolve() == Path(conftest.__file__).resolve())
    assert ours < order.index(xdist)


def test_brain_test_workers_sets_what_n_auto_means(monkeypatch):
    """BRAIN_TEST_WORKERS: the count -n auto starts; unset or blank: xdist's own (None); anything but a whole number
    is a usage error, not a silent default."""
    monkeypatch.delenv("BRAIN_TEST_WORKERS", raising=False)
    assert conftest.pytest_xdist_auto_num_workers(None) is None
    for raw, workers in (("24", 24), (" 8 ", 8), ("0", 0), ("", None)):
        monkeypatch.setenv("BRAIN_TEST_WORKERS", raw)
        assert conftest.pytest_xdist_auto_num_workers(None) == workers
    for raw in ("many", "-2", "1.5"):
        monkeypatch.setenv("BRAIN_TEST_WORKERS", raw)
        with pytest.raises(pytest.UsageError, match="a whole number of workers"):
            conftest.pytest_xdist_auto_num_workers(None)


def _temp(monkeypatch, root=None, basetemp=None, temproot=None):
    for var, value in (("BRAIN_TEST_ROOT", root), ("PYTEST_DEBUG_TEMPROOT", temproot)):
        if value is None:
            monkeypatch.delenv(var, raising=False)
        else:
            monkeypatch.setenv(var, str(value))
    config = SimpleNamespace(getoption=lambda name, default=None: basetemp if name == "basetemp" else default)
    conftest.temp_under_test_root(config)
    return os.environ.get("PYTEST_DEBUG_TEMPROOT")


def test_brain_test_root_holds_pytests_temp_folders(tmp_path, monkeypatch):
    """BRAIN_TEST_ROOT: pytest's temp root is <root>/tmp (made); unset or blank: the system's, untouched; an explicit
    --basetemp or PYTEST_DEBUG_TEMPROOT wins."""
    root = tmp_path / "brain-tests"
    assert _temp(monkeypatch) is None
    assert _temp(monkeypatch, root="  ") is None
    assert _temp(monkeypatch, root=root) == str(root / "tmp") and (root / "tmp").is_dir()
    assert _temp(monkeypatch, root=root, basetemp=str(tmp_path / "bt")) is None
    assert _temp(monkeypatch, root=root, temproot=tmp_path / "mine") == str(tmp_path / "mine")
    monkeypatch.setenv("BRAIN_TEST_ROOT", str(root))
    assert conftest.test_root_dir("venvs") == root / "venvs" and (root / "venvs").is_dir()
    monkeypatch.delenv("BRAIN_TEST_ROOT")
    assert conftest.test_root_dir("venvs") is None
