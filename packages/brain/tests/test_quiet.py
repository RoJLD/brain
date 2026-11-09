"""Quiet mode (wi-brain-quiet-mode): held, summed up, critical through, nothing paused."""
import pytest
from datetime import datetime, timedelta, timezone

from brain import alerts, notify, projects, quiet
from test_notify import ENV, Fake, LEVELS, NOW, _cfg, _msg, fake  # noqa: F401 (fake: the fixture)


def _local_window(now, inside=True):
    t = now.astimezone()
    h = t.hour
    a, b = (h, (h + 2) % 24) if inside else ((h + 5) % 24, (h + 7) % 24)
    return f"{a:02d}:00-{b:02d}:00"


def test_manual_quiet_holds_below_critical_and_critical_goes_through(tmp_path, monkeypatch, fake):
    cfg = _cfg(tmp_path, monkeypatch, LEVELS)
    quiet.start(timedelta(hours=2), NOW)
    res = notify.send(cfg, _msg("error", key="k1"), now=NOW)
    assert res.status == "held" and res.code == 0 and fake.posts == []
    assert [r["key"] for r in quiet.held()] == ["k1"]
    res = notify.send(cfg, _msg("critical"), now=NOW)
    assert res.status == "delivered" and len(fake.posts) == 2   # ntfy and telegram, e-mail: all three channels
    assert len(quiet.held()) == 1


def test_the_end_sums_up_once_per_project_and_clears(tmp_path, monkeypatch, fake):
    cfg = _cfg(tmp_path, monkeypatch, LEVELS)
    reg = projects.load()
    quiet.start(timedelta(hours=2), NOW)
    for i in range(3):
        notify.send(cfg, _msg("error", key=f"k{i}", body=f"alert {i}"), now=NOW)
    notify.send(cfg, _msg("error", key="k0", body="alert 0 again"), now=NOW)   # the latest of a key only
    assert quiet.release(reg, now=NOW + timedelta(hours=1), env=ENV) == []     # still quiet: nothing sent
    assert fake.posts == []
    later = NOW + timedelta(hours=3)
    out = quiet.release(reg, now=later, env=ENV)
    assert out == ["quiet: demo: summary of 4 held: delivered"]
    assert len(fake.posts) == 1
    text = fake.posts[0][1]["message"]
    assert "4 held during the quiet" in text and "alert 1" in text and "alert 0 again" in text
    assert text.count("alert 0") == 1 and fake.posts[0][1]["title"].startswith("[demo error]")
    assert quiet.held() == [] and quiet.release(reg, now=later, env=ENV) == []


def test_a_failed_summary_stays_held(tmp_path, monkeypatch, fake):
    cfg = _cfg(tmp_path, monkeypatch, LEVELS)
    quiet.start(timedelta(minutes=30), NOW)
    notify.send(cfg, _msg("error", key="k"), now=NOW)
    fake.fail = {"ntfy", "telegram", "email"}
    out = quiet.release(projects.load(), now=NOW + timedelta(hours=1), env=ENV)
    assert out == ["quiet: demo: summary of 1 held: failed"] and len(quiet.held()) == 1


def test_off_ends_the_manual_quiet(tmp_path, monkeypatch, fake):
    cfg = _cfg(tmp_path, monkeypatch, LEVELS)
    quiet.start(timedelta(hours=2), NOW)
    assert quiet.manual_until(NOW) is not None and quiet.stop() and quiet.manual_until(NOW) is None
    assert notify.send(cfg, _msg("error"), now=NOW).status == "delivered"
    assert not quiet.stop()


def test_declared_hours(tmp_path, monkeypatch, fake):
    cfg = _cfg(tmp_path, monkeypatch, LEVELS, '    quiet_hours: "%s"\n' % _local_window(NOW))
    assert notify.send(cfg, _msg("error"), now=NOW).status == "held"
    cfg = _cfg(tmp_path, monkeypatch, LEVELS, '    quiet_hours: "%s"\n' % _local_window(NOW, inside=False))
    assert notify.send(cfg, _msg("error"), now=NOW).status == "delivered"
    assert quiet.in_hours("22:00-07:00", datetime(2026, 11, 2, 23, 30).astimezone())
    assert not quiet.in_hours("22:00-07:00", datetime(2026, 11, 2, 12, 0).astimezone())


@pytest.mark.parametrize("bad", ["25:00-07:00", "22:00", "08:00-08:00", "x"])
def test_bad_hours_are_a_configuration_error(tmp_path, monkeypatch, bad):
    with pytest.raises(notify.NotifyError, match="quiet_hours"):
        _cfg(tmp_path, monkeypatch, LEVELS, f'    quiet_hours: "{bad}"\n')


@pytest.mark.parametrize("bad", ["0h", "8d", "soon"])
def test_bad_durations(bad):
    with pytest.raises(quiet.QuietError):
        quiet.duration(bad)


def test_dry_run_is_not_held_and_does_not_write(tmp_path, monkeypatch, fake):
    cfg = _cfg(tmp_path, monkeypatch, LEVELS)
    quiet.start(timedelta(hours=2), NOW)
    assert notify.send(cfg, _msg("error"), dry_run=True, now=NOW).status == "dry-run" and quiet.held() == []


def test_the_alerts_pass_keeps_recording_while_quiet(tmp_path, monkeypatch, fake):
    """Quiet silences the notification only: the pass still opens the alert in its state (a collector's missed run
    is not forgotten), and the module touches neither the scheduler nor the alerts."""
    import inspect
    import re
    imports = " ".join(re.findall(r"^\s*from \. import (.*)$", inspect.getsource(quiet), re.M))
    assert not {"schedule", "alerts"} & set(re.findall(r"\w+", imports))
    cfg = _cfg(tmp_path, monkeypatch, LEVELS)
    p = projects.get("demo")
    quiet.start(timedelta(hours=2))
    data = {"projects": [{"project": "demo", "found": True, "alerts": [
        {"key": "task:collector", "level": "error", "message": "collector missed", "source": "task"}]}]}
    out = alerts.notify_pass(data, {"demo": p}, env=ENV)
    assert out[0] == "demo: error task:collector: held" and fake.posts == []
    assert "task:collector" in alerts.state_load()["demo"]["open"]
    assert len(quiet.held()) == 1


def test_status_line(tmp_path, monkeypatch):
    assert quiet.line({"until": "", "hours": {}, "active": False, "held": 0}) == ""
    s = {"until": _iso_in(2), "hours": {"demo": "22:00-07:00"}, "active": True, "held": 3}
    text = quiet.line(s)
    assert "quiet until" in text and "demo 22:00-07:00" in text and "3 held" in text and "no task paused" in text


def _iso_in(h):
    return (datetime.now(timezone.utc) + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")
