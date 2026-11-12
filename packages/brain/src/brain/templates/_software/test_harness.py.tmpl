"""The harness's own tests (tests/conftest.py): they show how to use it, and keep the CI green from the first
commit. Replace them with the project's tests as it grows; keep the harness."""

import datetime as dt
import os

import pytest
from conftest import old_formats


def test_the_clock_moves_only_when_told(clock):
    start = clock.now()
    assert clock.now() == start
    assert clock.advance(hours=2) - start == dt.timedelta(hours=2)


def test_a_fault_comes_after_the_calls_that_pass(faults, tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.write_text("1", encoding="utf-8")
    second.write_text("2", encoding="utf-8")
    faults.fail(os, "replace", after=1)
    os.replace(first, tmp_path / "first.done")   # the first call passes
    with pytest.raises(OSError, match="injected fault: replace"):
        os.replace(second, tmp_path / "second.done")
    assert second.exists()


def test_a_format_without_fixtures_has_none():
    assert old_formats("a-format-not-written-yet") == []
