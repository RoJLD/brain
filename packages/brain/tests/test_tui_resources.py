"""wi-brain-resources-view in the cockpit: the band at the header's right, read by a worker from brain.resources'
sampler, its levels in colour, narrowed under 120 columns, and its detail opened by 9 or a click (Textual only)."""

import time

import pytest

pytest.importorskip("textual")

from textual.widgets import Static  # noqa: E402

from brain import resources, tui_screens  # noqa: E402
from test_tui import _run  # noqa: E402

BAND = {"at": "2026-11-13T10:00:00Z", "cpu_pct": 97.0, "mem_pct": 50.0, "disk_pct": 60.0, "disk": "C:\\",
        "up_bps": 2048, "down_bps": 4096, "tokens": 1_500_000, "usd": 12.0, "quota_pct": 42.0, "pace_x": 0.8,
        "quota_level": "ok", "source": "stdlib", "levels": [{"what": "cpu", "level": "critical", "pct": 97.0,
                                                              "text": "CPU 97 %"}], "cost_ms": 1.0}


class FakeSampler:
    def __init__(self, fail=False):
        self.bands = self.samples = 0
        self.fail = fail

    def band(self):
        self.bands += 1
        if self.fail:
            raise OSError("no counters")
        return dict(BAND)

    def sample(self, stop=None, docker_timeout=None):
        assert stop is not None and stop() is False and docker_timeout == 4.0
        self.samples += 1
        return {"v": 1, "at": "2026-11-13T10:00:00Z", "levels": [],
                "containers": {"state": "down", "why": "the Docker engine does not answer", "rows": []}}


def _band(app):
    return app.query_one("#band", Static).render()


def test_the_band_shows_the_sampler_with_its_levels_and_9_opens_the_detail():
    sampler = FakeSampler()

    async def check(app, pilot, fake):
        await app.workers.wait_for_complete()
        await pilot.pause(0.1)
        text = _band(app)
        assert sampler.bands >= 1
        assert str(text).startswith("CPU 97 % \u00b7 RAM 50 % \u00b7 C: 60 %") and "1.5M tok" in str(text)
        assert "quota 42 % 0.8x" in str(text)
        red = [str(text)[s.start:s.end] for s in text.spans if "red" in str(s.style)]
        assert red == ["CPU 97 %"]   # CRITICAL in red, the rest plain
        await pilot.press("9")
        await pilot.pause(0.1)
        await app.screen.workers.wait_for_complete()
        await pilot.pause(0.1)
        assert isinstance(app.screen, tui_screens.ResourcesScreen) and sampler.samples == 1
        body = str(app.screen.query_one("#resources-body", Static).render())
        assert "containers (down: the Docker engine does not answer)" in body
        await pilot.press("r")
        await pilot.pause(0.1)
        await app.screen.workers.wait_for_complete()
        assert sampler.samples == 2
        await pilot.press("escape")
        await pilot.pause(0.1)
        assert not isinstance(app.screen, tui_screens.ResourcesScreen)
        await pilot.click("#band")
        await pilot.pause(0.1)
        assert isinstance(app.screen, tui_screens.ResourcesScreen)
    _run(check, sampler=sampler)


def test_under_120_columns_the_band_keeps_cpu_ram_and_the_quota():
    async def check(app, pilot, fake):
        await app.workers.wait_for_complete()
        await pilot.pause(0.1)
        assert str(_band(app)) == "CPU 97 % \u00b7 RAM 50 % \u00b7 quota 42 % 0.8x"
    _run(check, size=(110, 40), sampler=FakeSampler())


def test_a_failing_sampler_is_said_in_the_band_and_the_cockpit_goes_on():
    async def check(app, pilot, fake):
        await app.workers.wait_for_complete()
        await pilot.pause(0.1)
        assert str(_band(app)) == "resources: OSError: no counters"
        assert fake.calls   # the panels were read all the same
    _run(check, sampler=FakeSampler(fail=True))


class SlowSampler(FakeSampler):
    """A read that takes 10 s unless it is stopped: closing the detail ends it at its next step."""

    def sample(self, stop=None, docker_timeout=None):
        end = time.monotonic() + 10
        while time.monotonic() < end:
            if stop():
                self.stopped = True
                raise resources.Cancelled()
            time.sleep(0.05)
        return super().sample(stop, docker_timeout)


def test_closing_the_detail_stops_its_read_at_the_next_step():
    sampler = SlowSampler()
    sampler.stopped = False

    async def check(app, pilot, fake):
        await pilot.press("9")
        await pilot.pause(0.2)
        screen = app.screen
        assert isinstance(screen, tui_screens.ResourcesScreen)
        t0 = time.monotonic()
        await pilot.press("escape")
        await screen.workers.wait_for_complete()
        assert time.monotonic() - t0 < 3 and sampler.stopped
    _run(check, sampler=sampler)
