"""The test harness of this project (a project template of the brain): a virtual clock, fault injection and the
fixtures of the old formats. The code under test takes its clock and its I/O as parameters, so that a test sets
them: no test sleeps, reads the real time or needs a real failure."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class Clock:
    """A virtual clock: it moves only when a test moves it."""

    def __init__(self, start: dt.datetime):
        self._now = start

    def now(self) -> dt.datetime:
        return self._now

    def advance(self, **delta) -> dt.datetime:
        """Move it by ``delta`` (``hours=1``, ``days=2``...), and return the new time."""
        self._now += dt.timedelta(**delta)
        return self._now


@pytest.fixture
def clock() -> Clock:
    """2026-01-01 00:00 UTC, moved by ``clock.advance(...)``."""
    return Clock(dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc))


class Faults:
    """Fault injection: a function of a module or an object fails, at once or after some calls, for one test."""

    def __init__(self, monkeypatch):
        self._mp = monkeypatch

    def fail(self, owner, attr: str, error: BaseException | None = None, after: int = 0) -> None:
        """``owner.attr`` raises ``error`` (an OSError by default) from its call number ``after + 1`` on."""
        real, calls = getattr(owner, attr), [0]
        error = error or OSError(f"injected fault: {attr}")

        def faulty(*args, **kwargs):
            calls[0] += 1
            if calls[0] > after:
                raise error
            return real(*args, **kwargs)

        self._mp.setattr(owner, attr, faulty)


@pytest.fixture
def faults(monkeypatch) -> Faults:
    return Faults(monkeypatch)


def old_formats(fmt: str) -> list[Path]:
    """The files the older writers of a format left (``fixtures/formats/<format>/v<N>/older.*``), for its reader."""
    return sorted((FIXTURES / "formats" / fmt).glob("v*/older.*"))
