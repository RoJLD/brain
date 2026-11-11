"""wi-brain-outbox: the sealed local outbox: what could not leave is queued under an idempotency key, replayed by the
alerts pass with exponential backoff and jitter, given up past its tries or its age; a notification whose channels
are down is no longer lost."""

import io
import json
import urllib.error
from datetime import datetime, timedelta, timezone

import pytest
from brain import alerts, net, notify, outbox, projects
from test_notify import ENV, LEVELS, _cfg, _msg

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def ceiling(monkeypatch):
    monkeypatch.setattr(net, "_random", lambda: 1.0)   # the jitter's ceiling: the waits are known
    monkeypatch.setattr(net, "_sleep", lambda s: None)
    monkeypatch.setenv(net.SWITCH, "off")              # the transports' retries stay, the breaker is not tested here


def ok(payload):
    return "done"


def down(payload):
    raise ConnectionRefusedError("refused")


def test_put_is_idempotent_and_drop_removes(tmp_path):
    k = outbox.key_of("demo", "error", "same text")
    assert k == outbox.key_of("demo", "error", "same text") != outbox.key_of("demo", "error", "other")
    assert outbox.put("notify", k, {"a": 1}, "refused", now=NOW) == ""
    assert outbox.put("notify", k, {"a": 2}, "refused", now=NOW) == ""
    rows = outbox.pending()
    assert list(rows) == [k] and rows[k]["payload"] == {"a": 1} and rows[k]["tries"] == 0
    assert outbox.path().name == "queue.json" and outbox.path().parent.name == "outbox"
    assert outbox.drop(k) and not outbox.drop(k) and outbox.pending() == {}


def test_replay_waits_with_backoff_then_sends_and_forgets(tmp_path):
    k = outbox.key_of("x")
    outbox.put("notify", k, {"n": 1}, now=NOW)
    assert outbox.replay({"notify": ok}, now=NOW) == []          # not due yet: the first wait
    t = NOW + timedelta(seconds=outbox.BASE_S)
    lines = outbox.replay({"notify": down}, now=t)
    assert "not sent (refused)" in lines[0]
    e = outbox.pending()[k]
    assert e["tries"] == 1
    assert e["next"] == (t + timedelta(seconds=outbox.BASE_S * 2)).strftime("%Y-%m-%dT%H:%M:%SZ")   # doubled
    t2 = t + timedelta(seconds=outbox.BASE_S * 2)
    assert outbox.replay({"other": ok}, now=t2) == []            # a kind without its handler waits untouched
    lines = outbox.replay({"notify": ok}, now=t2)
    assert lines[0].startswith(f"outbox: sent notify {k}") and outbox.pending() == {}


def test_wait_is_capped():
    assert outbox.wait(30) == outbox.CAP_S


def test_given_up_past_its_tries_or_its_age(tmp_path):
    outbox.put("notify", "a", {}, now=NOW)
    late = NOW + outbox.MAX_AGE + timedelta(hours=1)
    lines = outbox.replay({"notify": down}, now=late)
    assert lines[0].startswith("outbox: gave up notify a after 1 tries") and outbox.pending() == {}


def test_dry_run_changes_nothing(tmp_path):
    outbox.put("notify", "a", {}, now=NOW)
    t = NOW + timedelta(days=1)
    assert outbox.replay({"notify": down}, now=t, dry_run=True)[0].startswith("outbox: would send notify a")
    assert outbox.pending()["a"]["tries"] == 0


def test_a_newer_brains_outbox_is_left_alone(tmp_path):
    outbox.path().parent.mkdir(parents=True)
    outbox.path().write_text(json.dumps({"v": 99}), encoding="utf-8")
    assert outbox.put("notify", "a", {}, now=NOW).startswith("outbox: not kept")


class Flaky:
    """ntfy down (a refused connection) until ``up`` is set; every POST recorded."""

    def __init__(self):
        self.up, self.posts = False, []

    def post(self, url, payload, headers, timeout):
        if not self.up:
            raise urllib.error.URLError(ConnectionRefusedError("refused"))
        self.posts.append(payload)
        return 200, b"{}"


@pytest.fixture
def flaky(monkeypatch):
    f = Flaky()
    monkeypatch.setattr(notify, "_post_json", f.post)
    monkeypatch.delenv("BRAIN_NOTIFY", raising=False)
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    return f


ONLY_NTFY = """\
    levels:
      error: [ntfy]
"""


def test_a_failed_notification_is_queued_then_replayed_once(tmp_path, monkeypatch, flaky):
    cfg = _cfg(tmp_path, monkeypatch, ONLY_NTFY)
    res = notify.send(cfg, _msg(title="Missed pass", key="k1"), now=NOW)
    assert res.status == "failed" and res.queued
    assert any("queued in the outbox" in ln for ln in res.lines())
    [(k, e)] = outbox.pending().items()
    assert e["kind"] == "notify" and e["payload"]["project"] == "demo" and e["payload"]["title"] == "Missed pass"
    # the same notification failing again keeps one entry
    notify.send(cfg, _msg(title="Missed pass", key="k1"), now=NOW + timedelta(minutes=1))
    assert list(outbox.pending()) == [k]
    flaky.up = True
    reg = {"demo": projects.get("demo")}
    lines = notify.replay(reg, now=NOW + timedelta(hours=1))
    assert lines and lines[0].startswith("outbox: sent notify") and outbox.pending() == {}
    assert [p["title"] for p in flaky.posts] == ["[demo error] Missed pass"]
    assert notify.replay(reg, now=NOW + timedelta(hours=2)) == []


def test_a_fresh_delivery_drops_the_queued_copy(tmp_path, monkeypatch, flaky):
    cfg = _cfg(tmp_path, monkeypatch, ONLY_NTFY)
    notify.send(cfg, _msg(key="k1"), now=NOW)
    assert outbox.pending()
    flaky.up = True
    assert notify.send(cfg, _msg(key="k1"), now=NOW + timedelta(minutes=1)).status == "delivered"
    assert outbox.pending() == {}


def test_a_refusal_is_not_queued(tmp_path, monkeypatch):
    """An HTTP 401 is the service's answer (a wrong token): sending it again would not help."""
    def refuse(url, payload, headers, timeout):
        raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, io.BytesIO(b"{}"))
    monkeypatch.setattr(notify, "_post_json", refuse)
    monkeypatch.delenv("BRAIN_NOTIFY", raising=False)
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    cfg = _cfg(tmp_path, monkeypatch, ONLY_NTFY)
    res = notify.send(cfg, _msg(), now=NOW)
    assert res.status == "failed" and not res.queued and outbox.pending() == {}


def test_the_alerts_pass_replays_the_outbox(tmp_path, monkeypatch, flaky):
    cfg = _cfg(tmp_path, monkeypatch, LEVELS)
    notify.send(cfg, _msg("info", body="resolved: the pass", key="k9"), only=["ntfy"], now=NOW)
    assert outbox.pending()
    flaky.up = True
    lines = alerts.notify_pass({"projects": []}, {"demo": projects.get("demo")}, now=NOW + timedelta(hours=1))
    assert any(ln.startswith("outbox: sent notify") for ln in lines) and outbox.pending() == {}
    assert flaky.posts and flaky.posts[0]["message"].startswith("resolved: the pass")


# --- the review's findings ---

def test_given_up_past_its_tries(tmp_path):
    outbox.put("notify", "a", {}, now=NOW)
    t = NOW
    for _ in range(outbox.MAX_TRIES):
        t += timedelta(seconds=outbox.CAP_S)
        lines = outbox.replay({"notify": down}, now=t)
    assert lines[0].startswith(f"outbox: gave up notify a after {outbox.MAX_TRIES} tries") and outbox.pending() == {}


def test_what_may_have_been_delivered_is_not_queued(tmp_path, monkeypatch):
    """A timeout or a reset may have delivered the message: the outbox never sends it twice. A skipped call (its
    breaker open) surely was not."""
    def post(exc):
        def f(url, payload, headers, timeout):
            raise exc
        return f
    monkeypatch.delenv("BRAIN_NOTIFY", raising=False)
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    cfg = _cfg(tmp_path, monkeypatch, ONLY_NTFY)
    for exc in (urllib.error.URLError(TimeoutError("timed out")), ConnectionResetError("reset"),
                urllib.error.HTTPError("u", 502, "bad gateway", {}, io.BytesIO(b"{}"))):
        monkeypatch.setattr(notify, "_post_json", post(exc))
        res = notify.send(cfg, _msg(), now=NOW)
        assert res.status == "failed" and not res.queued
    assert outbox.pending() == {}
    monkeypatch.setattr(notify, "_post_json", post(net.Unavailable("http:ntfy.sh", "http:ntfy.sh unavailable")))
    assert notify.send(cfg, _msg(), now=NOW).queued


def test_sends_switched_off_leave_the_outbox_as_it_is(tmp_path, monkeypatch, flaky):
    cfg = _cfg(tmp_path, monkeypatch, ONLY_NTFY)
    notify.send(cfg, _msg(key="k1"), now=NOW)
    flaky.up = True
    reg = {"demo": projects.get("demo")}
    for switch in ("dry-run", "off"):
        monkeypatch.setenv("BRAIN_NOTIFY", switch)
        assert notify.replay(reg, now=NOW + timedelta(hours=1)) == []
        [e] = outbox.pending().values()
        assert e["tries"] == 0
    assert flaky.posts == []


def test_a_newer_brains_outbox_is_not_replayed(tmp_path):
    outbox.path().parent.mkdir(parents=True)
    outbox.path().write_text(json.dumps({"v": 99, "a": {"kind": "notify", "payload": {}, "at": "2026-11-01T00:00:00Z",
                                                         "tries": 0, "next": "2026-11-01T00:00:00Z"}}),
                             encoding="utf-8")
    sent = []
    lines = outbox.replay({"notify": lambda p: sent.append(p) or "ok"}, now=NOW)
    assert sent == [] and lines[0].startswith("outbox: not replayed")


def test_another_projects_entry_waits_for_its_own_pass(tmp_path, monkeypatch, flaky):
    cfg = _cfg(tmp_path, monkeypatch, ONLY_NTFY)
    notify.send(cfg, _msg(key="k1"), now=NOW)
    for i in range(outbox.MAX_TRIES + 2):
        assert notify.replay({}, now=NOW + timedelta(days=1, hours=i)) == []
    [e] = outbox.pending().values()
    assert e["tries"] == 0


def test_a_forced_send_stays_forced_when_replayed(tmp_path, monkeypatch, flaky):
    cfg = _cfg(tmp_path, monkeypatch, ONLY_NTFY)
    flaky.up = True
    assert notify.send(cfg, _msg(key="k1"), now=NOW).status == "delivered"
    flaky.up = False
    assert notify.send(cfg, _msg(key="k1", body="again"), force=True, now=NOW + timedelta(minutes=1)).queued
    flaky.up = True
    lines = notify.replay({"demo": projects.get("demo")}, now=NOW + timedelta(minutes=10))
    assert lines[0].startswith("outbox: sent notify") and lines[0].endswith("(delivered)")
    assert [p["message"].split("\n")[0] for p in flaky.posts] == ["the pass of 12:00 was missed", "again"]


def test_a_newer_message_of_the_same_key_replaces_the_queued_one(tmp_path, monkeypatch, flaky):
    """A resolved message queued while ntfy was down is not sent after its alert reopened."""
    cfg = _cfg(tmp_path, monkeypatch, LEVELS)
    notify.send(cfg, _msg("info", body="resolved: the pass", key="k9"), only=["ntfy"], now=NOW)
    assert outbox.pending()
    flaky.up = True
    notify.send(cfg, _msg("error", body="the pass again", key="k9"), queue=False, now=NOW + timedelta(hours=1))
    assert outbox.pending() == {}


def test_a_call_queued_during_a_replay_is_kept(tmp_path):
    outbox.put("notify", "a", {}, now=NOW)

    def meanwhile(payload):
        outbox.put("notify", "b", {}, now=NOW)   # another command queues while this pass sends
        return "ok"
    outbox.replay({"notify": meanwhile}, now=NOW + timedelta(days=1))
    assert list(outbox.pending()) == ["b"]


def test_the_alerts_pass_does_not_queue_an_open_alert(tmp_path, monkeypatch, flaky):
    """The pass sends a failed open alert again itself: the outbox would send it twice."""
    _cfg(tmp_path, monkeypatch, LEVELS)
    data = {"projects": [{"project": "demo", "found": True, "alerts": [
        {"key": "a1", "level": "error", "message": "the pass of 12:00 was missed", "source": "watchdog"}]}]}
    lines = alerts.notify_pass(data, {"demo": projects.get("demo")}, now=NOW)
    assert any("a1" in ln for ln in lines) and outbox.pending() == {}
