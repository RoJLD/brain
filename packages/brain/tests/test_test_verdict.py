"""brain test --changed --verdict: pytest's whole output in a log file, a run that blocks until its deadline (its
process tree stopped there, exit 124), and three lines out: PASSED, FAILED or TIMEOUT with the counts and the log, the
failed tests' ids, the next command. pytest runs for real on a small repo."""

import json
import time
from pathlib import Path

import pytest
from brain import cli, verdict
from brain.commands import test as test_cmd
from test_targeted import FILES, _head, _map

PASS = "def test_other():\n    assert True\n"
FAIL = "def test_other():\n    assert 1 == 2\n\n\ndef test_fine():\n    assert True\n"
SLOW = "import time\n\n\ndef test_other():\n    time.sleep(60)\n"


@pytest.fixture
def lab(make_repo, tmp_path, monkeypatch):
    """The targeted tests' small repo and its map; the runs' logs under the test's temporary folder."""
    monkeypatch.setattr(verdict.tempfile, "tempdir", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    repo = make_repo("lab", FILES)
    m = tmp_path / "map.json"
    m.write_text(json.dumps(_map(_head(repo))), encoding="utf-8")

    def run(test_text, *more):
        make_repo.write(repo, {"tests/test_other.py": test_text})
        return cli.main(["test", "--changed", "--repo-dir", str(repo), "--map", str(m), "--verdict", *more])
    return run


def _out(capsys) -> list[str]:
    return capsys.readouterr().out.splitlines()


def test_a_green_run_says_three_lines_and_keeps_the_whole_log(lab, capsys):
    assert lab(PASS) == 0
    lines = _out(capsys)
    assert len(lines) == 3
    assert lines[0].startswith("test: PASSED 1 passed (1 test module(s)); log: ")
    assert lines[1] == "failed: none" and lines[2] == "next: brain gate (or git push)"
    log = Path(lines[0].rsplit("log: ", 1)[1])
    text = log.read_text(encoding="utf-8")
    assert log.name == "pytest.log" and log.parent.parent == verdict.scratch_root("test")
    assert "1 of 4 test module(s) selected" in text and "1 passed" in text and "recorded in" in text


def test_a_red_run_names_the_failed_tests_and_how_to_rerun_them(lab, capsys):
    assert lab(FAIL) == 1
    lines = _out(capsys)
    assert lines[0].startswith("test: FAILED 1 failed, 1 passed (1 test module(s)); log: ")
    assert lines[1] == "failed: tests/test_other.py::test_other"
    assert lines[2].startswith("next: python -m pytest tests/test_other.py::test_other (in .), fix, then brain test "
                               "--changed --verdict")


def test_the_deadline_stops_the_run_and_its_tree(lab, capsys, tmp_path):
    log = tmp_path / "own.log"
    t0 = time.monotonic()
    assert lab(SLOW, "--deadline", "3", "--log", str(log)) == 124
    assert time.monotonic() - t0 < 50   # not the test's 60 s
    lines = _out(capsys)
    assert lines[0].startswith("test: TIMEOUT stopped at the deadline (3 s) (1 test module(s)); log: ")
    assert lines[0].endswith(log.as_posix()) and lines[1] == "failed: none so far"
    assert lines[2] == "next: brain test --changed --verdict with a later --deadline (never a background run polled)"
    assert "stopped at the deadline (3 s)" in log.read_text(encoding="utf-8")


def test_json_carries_the_verdict(lab, capsys):
    assert lab(FAIL, "--json") == 1
    data = json.loads(capsys.readouterr().out)
    assert data["failed"] == ["tests/test_other.py::test_other"] and data["counts"] == {"failed": 1, "passed": 1}
    assert data["stopped"] is False and len(data["verdict"]) == 3 and Path(data["log"]).is_file()


def test_the_verdict_flags_go_together(lab, capsys):
    with pytest.raises(SystemExit, match="--deadline goes with --verdict"):
        cli.main(["test", "--changed", "--deadline", "5"])
    with pytest.raises(SystemExit, match="--log goes with --verdict"):
        cli.main(["test", "--changed", "--log", "x.log"])
    with pytest.raises(SystemExit, match="--list runs nothing"):
        cli.main(["test", "--changed", "--verdict", "--list"])
    for bad in ("0", "-3", "nan", "soon"):
        with pytest.raises(SystemExit):
            cli.main(["test", "--changed", "--verdict", "--deadline", bad])
    assert test_cmd.DEADLINE < 600   # under a shell tool's ten minutes


def test_the_lines_of_an_empty_selection_and_of_a_run_with_no_ids(tmp_path):
    none = verdict.pytest_summary("")
    lines = verdict.test_lines(0, False, 540, none, tmp_path / "l.log", 0, "r", "a")
    assert lines[0].startswith("test: PASSED no test module to run (0 test module(s)); log: ")
    lines = verdict.test_lines(2, False, 540, none, tmp_path / "l.log", 3, "r", "a")
    assert lines[0].startswith("test: FAILED pytest exit 2 (3 test module(s))")
    assert lines[1] == "failed: no test id in pytest's summary (exit 2): read the log" and lines[2] == "next: r"
    many = verdict.PytestSummary({"failed": 12}, [f"t.py::t{i}" for i in range(12)])
    assert verdict.test_lines(1, False, 540, many, tmp_path / "l.log", 1, "r", "a")[1].endswith(
        "t.py::t9 and 2 more (the log)")
