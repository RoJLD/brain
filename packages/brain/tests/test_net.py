"""wi-brain-net-resilience: one helper for external calls (brain.net): a quick failure retried with backoff and
jitter, a timeout never retried, a circuit breaker remembered across runs so that a down service costs one timeout
per window, said in one line; and the call sites moved onto it (GitNexus, docker, ntfy, ls-remote, gh)."""

import json
import socket
import subprocess
import urllib.error

import pytest
from brain import codeindex, net, notify, update

REMOTE_TAGS = update.remote_tags   # the real one: conftest keeps the tests offline


class Clock:
    def __init__(self, t=1_700_000_000.0):
        self.t = t
        self.slept = []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(net, "_clock", c)
    monkeypatch.setattr(net, "_sleep", c.sleep)
    monkeypatch.setattr(net, "_random", lambda: 1.0)   # the jitter's ceiling, so the waits are known
    monkeypatch.delenv(net.SWITCH, raising=False)
    return c


def calls(*outcomes):
    """A fake call returning or raising each outcome in turn, counting the calls."""
    seen = []

    def fn():
        seen.append(1)
        o = outcomes[min(len(seen), len(outcomes)) - 1]
        if isinstance(o, BaseException):
            raise o
        return o
    fn.seen = seen
    return fn


def test_success_is_unchanged_and_writes_nothing(clock):
    fn = calls("ok")
    assert net.call("svc", fn) == "ok"
    assert len(fn.seen) == 1
    assert not net.path().exists()


def test_a_quick_failure_is_retried_with_backoff_and_jitter(clock):
    fn = calls(ConnectionRefusedError("refused"), urllib.error.HTTPError("u", 503, "busy", {}, None), "ok")
    assert net.call("svc", fn) == "ok"
    assert len(fn.seen) == 3
    assert clock.slept == [net.BACKOFF_S, net.BACKOFF_S * 2]   # exponential, at the jitter's ceiling
    assert net.status() == {}


def test_backoff_is_capped_and_jittered(monkeypatch):
    monkeypatch.setattr(net, "_random", lambda: 0.25)
    assert net.backoff(1) == 0.25 * net.BACKOFF_S
    assert net.backoff(20) == 0.25 * net.CAP_S


def test_a_timeout_is_not_retried_and_opens_the_breaker_for_a_window(clock):
    fn = calls(socket.timeout("timed out"))
    with pytest.raises(socket.timeout):
        net.call("svc", fn)
    assert len(fn.seen) == 1 and clock.slept == []
    # the next calls inside the window cost nothing and say so in one line
    with pytest.raises(net.Unavailable) as e:
        net.call("svc", fn)
    assert len(fn.seen) == 1
    line = str(e.value)
    assert line.startswith("svc unavailable since ") and "(timed out)" in line and "skipped until" in line
    assert "\n" not in line and net.SWITCH in line
    assert net.status()["svc"]["open"] is True
    # another service is not concerned
    assert net.call("other", calls("ok")) == "ok"


def test_the_breaker_half_opens_after_the_window_and_closes_on_success(clock):
    with pytest.raises(subprocess.TimeoutExpired):
        net.call("svc", calls(subprocess.TimeoutExpired("x", 1)))
    clock.t += net.WINDOW_S + 1
    fn = calls("back")
    assert net.call("svc", fn) == "back"
    assert net.status() == {}


def test_a_failure_after_the_window_opens_it_again(clock):
    with pytest.raises(subprocess.TimeoutExpired):
        net.call("svc", calls(subprocess.TimeoutExpired("x", 1)))
    since = net.status()["svc"]["since"]
    clock.t += net.WINDOW_S + 1
    with pytest.raises(subprocess.TimeoutExpired):
        net.call("svc", calls(subprocess.TimeoutExpired("x", 1)))
    s = net.status()["svc"]
    assert s["open"] and s["failures"] == 2 and s["since"] == since


def test_quick_failures_past_their_retries_open_the_breaker(clock):
    fn = calls(ConnectionResetError("reset"))
    with pytest.raises(ConnectionResetError):
        net.call("svc", fn)
    assert len(fn.seen) == 1 + net.RETRIES
    assert net.status()["svc"]["open"]


def test_the_services_own_answer_is_raised_unchanged_and_closes_the_breaker(clock):
    with pytest.raises(socket.timeout):
        net.call("svc", calls(socket.timeout()))
    clock.t += net.WINDOW_S + 1
    fn = calls(urllib.error.HTTPError("u", 404, "no such", {}, None))
    with pytest.raises(urllib.error.HTTPError):
        net.call("svc", fn)
    assert len(fn.seen) == 1          # a 404 is an answer: not retried
    assert net.status() == {}         # and the service answered: closed
    with pytest.raises(FileNotFoundError):   # a missing program is not a down service
        net.call("svc", calls(FileNotFoundError("gh")))
    assert net.status() == {}


def test_the_switch_turns_the_breaker_off(clock, monkeypatch):
    with pytest.raises(socket.timeout):
        net.call("svc", calls(socket.timeout()))
    monkeypatch.setenv(net.SWITCH, "off")
    assert net.call("svc", calls("tried anyway")) == "tried anyway"


def test_an_unwritable_breaker_file_never_fails_a_call(clock):
    net.path().parent.mkdir(parents=True)
    net.path().write_text(json.dumps({"v": 99}), encoding="utf-8")   # a newer brain's: read-only here
    with pytest.raises(socket.timeout):
        net.call("svc", calls(socket.timeout()))
    assert net.call("svc", calls("ok")) == "ok"


def test_run_opens_on_a_timeout_and_keeps_the_exit_code_as_the_answer(clock, monkeypatch):
    seen = []

    def fake(argv, timeout, **kw):
        seen.append(argv)
        if argv[0] == "slow":
            raise subprocess.TimeoutExpired(argv, timeout)
        return subprocess.CompletedProcess(argv, 1, "", "no")
    monkeypatch.setattr(net.subprocess, "run", fake)
    assert net.run("tool", ["fails"], timeout=5).returncode == 1
    assert net.status() == {}
    with pytest.raises(subprocess.TimeoutExpired):
        net.run("tool", ["slow"], timeout=5)
    with pytest.raises(net.Unavailable):
        net.run("tool", ["fails"], timeout=5)
    assert seen == [["fails"], ["slow"]]


# --- the call sites ---

def test_gitnexus_http_down_costs_one_timeout_per_window(clock, monkeypatch):
    tries = []

    class Opener:
        def open(self, req, timeout):
            tries.append(req.full_url)
            raise urllib.error.URLError(socket.timeout("timed out"))
    monkeypatch.setattr(codeindex.urllib.request, "build_opener", lambda *a: Opener())
    status, why = codeindex._http("GET", "http://127.0.0.1:1/api/repos")
    assert status == 0
    status, why = codeindex._http("GET", "http://127.0.0.1:1/api/repos")
    assert status == 0 and why.startswith("gitnexus unavailable")
    text, why = codeindex._mcp_tool("http://127.0.0.1:1/api/mcp", "cypher", {})
    assert text == "" and why.startswith("gitnexus unavailable")
    assert len(tries) == 1


def test_docker_timeout_skips_the_next_docker_calls(clock, monkeypatch):
    runs = []
    monkeypatch.setattr(codeindex.stacks, "_resolve", lambda argv: argv)

    def exec_(argv, timeout, stdin=None):
        runs.append(argv)
        return None, ""
    monkeypatch.setattr(codeindex, "_exec", exec_)
    assert codeindex._docker(["docker", "exec", "c", "du"], 60) == (None, "")
    code, why = codeindex._docker(["docker", "exec", "c", "du"], 60)
    assert code == 127 and why.startswith("docker unavailable")
    assert len(runs) == 1


def test_ntfy_post_retries_a_refused_connection_then_says_the_host_is_down(clock, monkeypatch):
    tries = []

    def urlopen(req, timeout):
        tries.append(req.full_url)
        raise urllib.error.URLError(ConnectionRefusedError("refused"))
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    with pytest.raises(urllib.error.URLError):
        notify._post_json("https://ntfy.example/", {}, {}, 5)
    assert len(tries) == 1 + net.RETRIES
    with pytest.raises(net.Unavailable) as e:
        notify._post_json("https://ntfy.example/", {}, {}, 5)
    assert str(e.value).startswith("http:ntfy.example unavailable")
    assert len(tries) == 1 + net.RETRIES


def test_ls_remote_timeout_is_said_as_the_oserror_it_was(clock):
    tries = []

    def slow(*a, **kw):
        tries.append(1)
        raise subprocess.TimeoutExpired("git", update.TIMEOUT_S)
    with pytest.raises(OSError, match="timed out"):
        REMOTE_TAGS("x/y", runner=slow)
    with pytest.raises(OSError, match="git-remote:github.com unavailable"):
        REMOTE_TAGS("x/y", runner=slow)
    assert len(tries) == 1


def test_brain_update_reads_the_tags_even_with_the_breaker_open(clock):
    """An explicit refresh (brain update) closes the breaker a background check opened a minute ago."""
    def slow(*a, **kw):
        raise subprocess.TimeoutExpired("git", update.TIMEOUT_S)

    def fine(*a, **kw):
        return subprocess.CompletedProcess(a, 0, "abc\trefs/tags/v9.0.0\n", "")
    with pytest.raises(OSError):
        REMOTE_TAGS("x/y", runner=slow)
    assert update.check(refresh=False, fetch=lambda r: REMOTE_TAGS(r, runner=fine))["source"] in ("offline", "cache")
    got = update.check(refresh=True, fetch=lambda r: REMOTE_TAGS(r, runner=fine))
    assert got["source"] == "remote" and got["latest"] == "9.0.0"


def test_a_rate_limit_or_a_busy_gateway_never_opens_the_breaker(clock):
    """An HTTP 429 or 5xx is the service answering: retried, then raised, and its other calls still go."""
    fn = calls(urllib.error.HTTPError("u", 429, "slow down", {}, None))
    with pytest.raises(urllib.error.HTTPError):
        net.call("svc", fn)
    assert len(fn.seen) == 1 + net.RETRIES
    assert net.status() == {} and net.call("svc", calls("ok")) == "ok"


def test_a_post_is_retried_only_when_surely_not_handled(clock):
    reset = calls(ConnectionResetError("reset"), "ok")
    with pytest.raises(ConnectionResetError):          # the server may have acted: never sent twice
        net.call("svc", reset, idempotent=False)
    assert len(reset.seen) == 1
    clock.t += net.WINDOW_S + 1
    for first in (urllib.error.URLError(ConnectionRefusedError("refused")),
                  urllib.error.HTTPError("u", 503, "busy", {}, None)):
        fn = calls(first, "ok")
        assert net.call("svc", fn, idempotent=False) == "ok" and len(fn.seen) == 2
    fn = calls(urllib.error.HTTPError("u", 502, "bad gateway", {}, None))
    with pytest.raises(urllib.error.HTTPError):
        net.call("svc", fn, idempotent=False)
    assert len(fn.seen) == 1


def test_a_refused_certificate_is_an_answer(clock):
    import ssl
    fn = calls(urllib.error.URLError(ssl.SSLCertVerificationError("bad cert")))
    with pytest.raises(urllib.error.URLError):
        net.call("svc", fn)
    assert len(fn.seen) == 1 and net.status() == {}


def test_gitnexus_http_status_passes_through_and_a_poll_never_opens(clock, monkeypatch):
    import io
    tries = []

    class Opener:
        def open(self, req, timeout):
            tries.append((req.get_method(), req.full_url))
            if req.full_url.endswith("/api/repos"):
                raise urllib.error.HTTPError(req.full_url, 404, "no", {}, io.BytesIO(b'{"error": "none"}'))
            raise urllib.error.URLError(socket.timeout("timed out"))
    monkeypatch.setattr(codeindex.urllib.request, "build_opener", lambda *a: Opener())
    assert codeindex._http("GET", "http://127.0.0.1:1/api/repos") == (404, {"error": "none"})
    assert codeindex._http("GET", "http://127.0.0.1:1/api/analyze/7")[0] == 0     # a poll that timed out
    assert net.status() == {}                                                     # opened nothing
    assert codeindex._http("GET", "http://127.0.0.1:1/api/analyze/7")[0] == 0
    assert len(tries) == 3


def test_a_long_docker_job_past_its_time_does_not_shut_docker(clock, monkeypatch):
    monkeypatch.setattr(codeindex.stacks, "_resolve", lambda argv: argv)
    monkeypatch.setattr(codeindex, "_exec", lambda argv, timeout, stdin=None: (None, ""))
    assert codeindex._docker(["docker", "exec", "-i", "c", "sh"], codeindex.SNAPSHOT_TIMEOUT) == (None, "")
    assert net.status() == {}
