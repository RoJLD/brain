import io
import json
import urllib.error
from datetime import datetime, timedelta, timezone

import pytest

from brain import cli, notify, projects

from conftest import run_git

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
TOKEN = "123456789:" + "AAH" + "faketelegramtokenforthetests0123"  # shaped like a bot token, built so no line is one
ENV = {"T_TOPIC": "brain-topic-of-the-tests", "T_TOKEN": TOKEN, "T_CHAT": "4242", "T_USER": "ada",
       "T_PASS": "app-password-of-the-tests", "T_FROM": "brain@example.invalid", "T_TO": "a@example.invalid, b@example.invalid"}
CHANNELS = """\
      ntfy: {type: ntfy, server: https://ntfy.sh, topic_env: T_TOPIC}
      telegram: {type: telegram, token_env: T_TOKEN, chat_id_env: T_CHAT}
      email: {type: email, host: smtp.example.invalid, port: 587, user_env: T_USER, password_env: T_PASS,
              from_env: T_FROM, to_env: T_TO}
"""


class Fake:
    """Every transport recorded; none reaches the network. fail: channel types that raise."""

    def __init__(self, fail=()):
        self.posts, self.mails, self.fail = [], [], set(fail)

    def post(self, url, payload, headers, timeout):
        kind = "telegram" if "/bot" in url else "ntfy"
        if kind in self.fail:
            raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, io.BytesIO(
                json.dumps({"ok": False, "description": f"Unauthorized for {url}"}).encode()))
        self.posts.append((url, payload, headers))
        return 200, b'{"ok": true}'

    def smtp(self, host, port, security, timeout):
        fake = self

        class S:
            def login(self, user, password):
                if "email" in fake.fail:
                    raise RuntimeError(f"login refused for {user}:{password}")
                fake.mails.append(("login", user, password))

            def send_message(self, m):
                fake.mails.append(("send", m["Subject"], m["To"], m.get_content()))

            def quit(self):
                pass

        fake.mails.append(("connect", host, port, security))
        return S()


@pytest.fixture
def fake(monkeypatch):
    f = Fake()
    monkeypatch.setattr(notify, "_post_json", f.post)
    monkeypatch.setattr(notify, "_smtp", f.smtp)
    monkeypatch.setattr(notify, "_get_json", lambda url, timeout: pytest.fail("unexpected getUpdates"))
    monkeypatch.delenv("BRAIN_NOTIFY", raising=False)
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    return f


def _registry(tmp_path, monkeypatch, root, demo="", other=""):
    reg = tmp_path / "brain" / "projects.yaml"
    reg.parent.mkdir(exist_ok=True)
    reg.write_text(f"demo:\n  root: {root.as_posix()}\n{demo}other:\n  root: ../other\n{other}", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    return reg


def _cfg(tmp_path, monkeypatch, levels="", extra="", other=""):
    root = tmp_path / "demo"
    root.mkdir(exist_ok=True)
    _registry(tmp_path, monkeypatch, root, f"  notify:\n    channels:\n{CHANNELS}{levels}{extra}", other)
    return notify.config(projects.get("demo"))


LEVELS = """\
    levels:
      critical: {channels: [ntfy, telegram, email], mode: all}
      error: [ntfy, telegram, email]
"""


def _msg(level="error", **kw):
    return notify.Message("demo", level, kw.pop("body", "the pass of 12:00 was missed"), host="pc", **kw)


def test_first_delivers_then_stops_and_all_sends_everywhere(tmp_path, monkeypatch, fake):
    cfg = _cfg(tmp_path, monkeypatch, LEVELS)
    res = notify.send(cfg, _msg(title="Missed pass", source="watchdog", link="https://example.invalid/log"), now=NOW)
    assert res.status == "delivered" and res.code == 0 and [a.channel for a in res.attempts] == ["ntfy"]
    url, payload, headers = fake.posts[0]
    assert url == "https://ntfy.sh/" and headers == {}
    assert payload == {"topic": ENV["T_TOPIC"], "title": "[demo error] Missed pass", "priority": 4,
                       "tags": ["x", "demo"], "click": "https://example.invalid/log",
                       "message": "the pass of 12:00 was missed\nhttps://example.invalid/log\n— pc · watchdog"}
    res = notify.send(cfg, _msg("critical"), now=NOW)
    assert [(a.channel, a.outcome) for a in res.attempts] == [("ntfy", "sent"), ("telegram", "sent"), ("email", "sent")]
    url, payload, _ = fake.posts[-1]
    assert url == f"https://api.telegram.org/bot{TOKEN}/sendMessage" and payload["chat_id"] == "4242"
    assert payload["text"].startswith("[demo critical] the pass of 12:00 was missed\n\n")
    assert fake.mails[0] == ("connect", "smtp.example.invalid", 587, "starttls")
    assert fake.mails[1] == ("login", "ada", ENV["T_PASS"])
    assert fake.mails[2][:3] == ("send", "[demo critical] the pass of 12:00 was missed",
                                 "a@example.invalid, b@example.invalid")
    assert notify.send(cfg, _msg("warn"), now=NOW).status == "no-route"


def test_fallback_on_failure_and_unset_variable_and_masked_errors(tmp_path, monkeypatch, fake):
    cfg = _cfg(tmp_path, monkeypatch, LEVELS)
    fake.fail = {"telegram"}
    monkeypatch.delenv("T_TOPIC")
    res = notify.send(cfg, _msg(), now=NOW)
    assert [(a.channel, a.outcome) for a in res.attempts] == [("ntfy", "unset"), ("telegram", "failed"),
                                                               ("email", "sent")]
    assert res.attempts[0].detail == "not set up: $T_TOPIC not set"
    assert res.attempts[1].detail.startswith("HTTP 401: Unauthorized for ") and TOKEN not in res.attempts[1].detail
    assert "***" in res.attempts[1].detail
    fake.fail = {"telegram", "email"}
    res = notify.send(cfg, _msg(), now=NOW)
    assert res.status == "failed" and res.code == 1
    assert ENV["T_PASS"] not in res.attempts[2].detail and res.attempts[2].detail.startswith("RuntimeError")
    audit = (notify.audit_dir() / "2026-11.jsonl").read_text(encoding="utf-8")
    assert TOKEN not in audit and ENV["T_PASS"] not in audit and "— pc" not in audit  # no secret, no message text
    lines = [json.loads(x) for x in audit.splitlines()]
    assert [(x["channel"], x["outcome"]) for x in lines][-3:] == [("ntfy", "unset"), ("telegram", "failed"),
                                                                  ("email", "failed")]
    assert lines[0]["host"] == "pc" and lines[0]["title"] == "[demo error] the pass of 12:00 was missed"


def test_dry_run_switch_and_only_send_nothing(tmp_path, monkeypatch, fake):
    cfg = _cfg(tmp_path, monkeypatch, LEVELS)
    res = notify.send(cfg, _msg(), dry_run=True, now=NOW)
    assert res.status == "dry-run" and fake.posts == [] and fake.mails == []
    assert res.attempts[0].detail == f"would send through ntfy https://ntfy.sh, topic $T_TOPIC (set)"
    assert res.attempts[1].detail.endswith(", if the ones before fail") and TOKEN not in res.attempts[1].detail
    assert not notify.audit_dir().exists()
    monkeypatch.setenv("BRAIN_NOTIFY", "off")
    assert notify.send(cfg, _msg(), now=NOW).status == "off" and fake.posts == []
    monkeypatch.setenv("BRAIN_NOTIFY", "dry-run")
    assert notify.send(cfg, _msg(), now=NOW).status == "dry-run" and fake.posts == []
    monkeypatch.delenv("BRAIN_NOTIFY")
    res = notify.send(cfg, _msg("info"), only=["telegram"], now=NOW)  # a test send: a level without a route
    assert [a.channel for a in res.attempts] == ["telegram"] and res.status == "delivered"
    with pytest.raises(notify.NotifyError, match="unknown channel 'pigeon'"):
        notify.send(cfg, _msg(), only=["pigeon"], now=NOW)
    with pytest.raises(notify.NotifyError, match="unknown level"):
        notify.send(cfg, _msg("fatal"), now=NOW)


def test_key_is_held_back_within_the_throttle(tmp_path, monkeypatch, fake):
    cfg = _cfg(tmp_path, monkeypatch, LEVELS, "    throttle: 30\n")
    assert notify.send(cfg, _msg(key="missed-qmd"), now=NOW).status == "delivered"
    assert notify.send(cfg, _msg(key="missed-qmd"), now=NOW + timedelta(minutes=29)).status == "throttled"
    assert notify.send(cfg, _msg(key="missed-qmd"), force=True, now=NOW + timedelta(minutes=29)).status == "delivered"
    assert notify.send(cfg, _msg("critical", key="missed-qmd"), now=NOW + timedelta(minutes=29)).status == "delivered"
    assert notify.send(cfg, _msg(key="missed-qmd"), now=NOW + timedelta(minutes=60)).status == "delivered"
    assert notify.send(cfg, _msg(key="other"), now=NOW + timedelta(minutes=61)).status == "delivered"
    assert len(fake.posts) == 6  # four error sends to ntfy, the critical one to ntfy and telegram (and e-mail)
    cfg.throttle = 0
    assert notify.send(cfg, _msg(key="other"), now=NOW + timedelta(minutes=62)).status == "delivered"


@pytest.mark.parametrize("conf, error", [
    ("{type: telegram, token: abc, chat_id_env: X}", "a secret is never written in a file; name its environment "
                                                     "variable with token_env"),
    ("{type: email, host: h, password: p, from: a, to: b}", "password_env"),
    ("{type: ntfy, topic: public-topic}", "on the public ntfy.sh the topic is the password"),
    ("{type: ntfy, topic_env: 'not a name'}", "names an environment variable"),
    ("{type: ntfy, topic_env: A, topic: b, server: 'http://127.0.0.1:8090'}", "give topic or topic_env"),
    ("{type: pigeon}", "type must be one of"),
    ("{type: telegram, chat_id: '1'}", "token_env is required"),
    ("{type: email, host: h, security: none, user_env: U, password_env: P, from: a, to: b}", "never sent in clear"),
    ("{type: email, host: h, from: a, to: b, user_env: U}", "together"),
    ("{type: email, host: h, from: a, to_env: B, colour: red}", "unknown key 'colour'"),
    (f"{{type: telegram, token_env: T, chat_id: '{TOKEN}'}}",
     "looks like a secret"),
])
def test_configuration_errors(tmp_path, monkeypatch, conf, error):
    root = tmp_path / "demo"
    root.mkdir()
    _registry(tmp_path, monkeypatch, root, f"  notify:\n    channels:\n      c: {conf}\n")
    with pytest.raises(notify.NotifyError, match=error):
        notify.config(projects.get("demo"))


def test_routes_are_checked_and_channels_are_global(tmp_path, monkeypatch, fake):
    with pytest.raises(notify.NotifyError, match="unknown channel 'sms'"):
        _cfg(tmp_path, monkeypatch, "    levels: {error: [ntfy, sms]}\n")
    with pytest.raises(notify.NotifyError, match="unknown level 'fatal'"):
        _cfg(tmp_path, monkeypatch, "    levels: {fatal: [ntfy]}\n")
    with pytest.raises(notify.NotifyError, match="mode is first"):
        _cfg(tmp_path, monkeypatch, "    levels: {error: {channels: [ntfy], mode: some}}\n")
    with pytest.raises(notify.NotifyError, match="decisions is a level"):
        _cfg(tmp_path, monkeypatch, LEVELS, "    decisions: urgent\n")
    with pytest.raises(notify.NotifyError, match="unknown key"):
        _cfg(tmp_path, monkeypatch, LEVELS, "    colour: red\n")
    with pytest.raises(notify.NotifyError, match="declared by demo and other"):
        _cfg(tmp_path, monkeypatch, LEVELS, other="  notify: {channels: {ntfy: {type: ntfy, topic_env: X}}}\n")
    _cfg(tmp_path, monkeypatch, LEVELS, other="  notify: {levels: {critical: [telegram]}}\n")
    other = notify.config(projects.get("other"))  # routes to a channel the demo project declares
    assert other.levels["critical"].channels == ["telegram"] and other.channels["telegram"].project == "demo"
    assert notify.send(other, notify.Message("other", "critical", "down", host="pc"), now=NOW).status == "delivered"
    plain = notify.config(projects.Project("alone", tmp_path / "alone"), registry={})
    assert not plain.declared and plain.channels == {} and plain.levels == {}


def test_notify_file_relative_to_the_root(tmp_path, monkeypatch, fake):
    root = tmp_path / "demo"
    (root / "ops").mkdir(parents=True)
    (root / "ops" / "notify.yaml").write_text(f"channels:\n{CHANNELS.replace('      ', '  ')}levels: "
                                              "{warn: [email]}\ndecisions: warn\n", encoding="utf-8")
    _registry(tmp_path, monkeypatch, root, "  notify: ops/notify.yaml\n")
    cfg = notify.config(projects.get("demo"))
    assert cfg.decisions == "warn" and cfg.levels["warn"].channels == ["email"]
    _registry(tmp_path, monkeypatch, root, "  notify: ops/missing.yaml\n")
    with pytest.raises(notify.NotifyError, match="not found"):
        notify.config(projects.get("demo"))


def test_a_notification_leaves_scrubbed(tmp_path, monkeypatch, fake):
    """wi-brain-privacy-scrub: the free text of what leaves is scrubbed; the sending host's own field is kept."""
    cfg = _cfg(tmp_path, monkeypatch, LEVELS)
    monkeypatch.setenv("BRAIN_MACHINE", "orchard-01")
    res = notify.send(cfg, _msg(body="disk full on orchard-01 at " + "/home/" + "bob/data", title="for ada" + "@corp.io"), now=NOW)
    assert res.status == "delivered"
    payload = fake.posts[0][1]
    assert payload["title"] == "[demo error] for <email>"
    assert payload["message"].startswith("disk full on <host> at ~/data") and payload["message"].endswith("— pc")


def test_blocking_decision_is_sent_and_never_fails_the_ask(tmp_path, monkeypatch, fake):
    cfg = _cfg(tmp_path, monkeypatch, LEVELS)
    ddr = {"id": "ddr-2026-11-02-ntfy-server", "title": "Which server", "question": "Which ntfy server?",
           "options": [{"label": "ntfy.sh"}, {"label": "Self-hosted"}]}
    title, body = notify.decision_message("demo", ddr)
    assert title == "Decision needed: Which server"
    assert body == ("Which ntfy server?\n\n1. ntfy.sh (recommended)\n2. Self-hosted\n\n"
                    "brain decision answer ddr-2026-11-02-ntfy-server <n>  (--project demo)")
    lines = notify.decision(projects.get("demo"), ddr)
    assert lines == ["notify demo error: delivered", "  ntfy: sent (HTTP 200)"]
    assert fake.posts[0][1]["title"] == "[demo error] Decision needed: Which server"
    lines = notify.decision(projects.get("demo"), ddr, dry_run=True)
    assert lines[0] == "notify demo error: dry run: nothing sent" and len(fake.posts) == 1
    monkeypatch.setattr(notify, "config", lambda *a, **k: (_ for _ in ()).throw(ValueError(f"boom {TOKEN}")))
    lines = notify.decision(projects.get("demo"), ddr)
    assert lines[0].startswith("notify: not sent: ") and TOKEN not in lines[0]


def test_a_worktree_gets_its_project_routes(tmp_path, monkeypatch, fake, git_repo, capsys):
    _registry(tmp_path, monkeypatch, git_repo, f"  notify:\n    channels:\n{CHANNELS}{LEVELS}")
    wt = tmp_path / "wt"
    run_git(git_repo, "worktree", "add", "-q", "-b", "side", str(wt))
    assert cli.main(["--root", str(wt), "notify", "status"]) == 0
    assert "demo error: ntfy, telegram, email (the first that delivers)" in capsys.readouterr().out
    assert cli.main(["--root", str(wt), "notify", "send", "--level", "error", "x"]) == 0
    assert fake.posts[0][1]["title"] == "[demo error] x"


def test_cli_send_status_setup_and_the_blocking_ask(tmp_path, monkeypatch, fake, store, capsys):
    root = store.parents[1]
    _registry(tmp_path, monkeypatch, root, f"  notify:\n    channels:\n{CHANNELS}{LEVELS}")
    assert cli.main(["--project", "demo", "notify", "send", "--level", "error", "--dry-run", "--title", "T",
                     "line one"]) == 0
    out = capsys.readouterr().out
    assert "notify demo error: dry run: nothing sent" in out and "title: [demo error] T" in out
    assert "  line one" in out and fake.posts == []
    assert cli.main(["notify", "send", "--project", "demo", "--level", "error", "--key", "k", "--json", "x"]) == 0
    assert json.loads(capsys.readouterr().out)["delivered"] is True
    fake.fail = {"ntfy", "telegram", "email"}
    assert cli.main(["--project", "demo", "notify", "send", "--level", "error", "--force", "x"]) == 1
    assert "NOT delivered" in capsys.readouterr().out
    assert cli.main(["--project", "demo", "notify", "send", "--level", "error", ""]) == 2
    assert cli.main(["--project", "demo", "notify", "send", "--level", "error", "--channel", "sms", "x"]) == 2
    monkeypatch.delenv("T_CHAT")
    assert cli.main(["--project", "demo", "notify", "status"]) == 0
    out = capsys.readouterr().out
    assert "$T_TOKEN (set)" in out and "$T_CHAT (NOT SET)" in out and TOKEN not in out
    assert "demo critical: ntfy, telegram, email (every one)" in out
    assert "demo error: ntfy, telegram, email (the first that delivers)" in out and "demo warn: nothing" in out
    assert "last sends:" in out
    assert cli.main(["--project", "demo", "notify", "setup", "telegram"]) == 0
    out = capsys.readouterr().out
    assert "@BotFather" in out and "missing: $T_CHAT" in out and TOKEN not in out
    monkeypatch.setattr(notify, "_get_json", lambda url, timeout: {"result": [
        {"message": {"chat": {"id": 4242, "first_name": "Ada", "type": "private"}}}]})
    assert cli.main(["--project", "demo", "notify", "setup", "telegram", "--find-chat"]) == 0
    assert "find-chat: chat 4242 (Ada)" in capsys.readouterr().out
    assert cli.main(["--project", "demo", "notify", "setup", "pigeon"]) == 2
    fake.fail = set()
    assert cli.main(["--project", "demo", "decision", "ask", "--title", "Pick", "--question", "Which?", "--option",
                     "A: a", "--option", "B: b", "--why", "w", "--blocking", "--at", "2026-11-02T10:00:00Z"]) == 0
    out = capsys.readouterr().out
    assert "asked ddr-2026-11-02-pick" in out and "notify demo error: delivered" in out
    assert fake.posts[-1][1]["title"] == "[demo error] Decision needed: Pick"
    n = len(fake.posts)
    assert cli.main(["--project", "demo", "decision", "ask", "--title", "Quiet", "--question", "Q", "--option", "A: a",
                     "--option", "B: b", "--why", "w", "--blocking", "--no-notify"]) == 0
    assert cli.main(["--project", "demo", "decision", "ask", "--title", "Free", "--question", "Q", "--option", "A: a",
                     "--option", "B: b", "--why", "w"]) == 0
    assert "notify" not in capsys.readouterr().out and len(fake.posts) == n


def test_the_audit_keeps_six_months(tmp_path, monkeypatch, fake):
    """wi-brain-logs-unclassified: a month's first audit line prunes the months past the retention; the state files
    beside the audit stay."""
    cfg = _cfg(tmp_path, monkeypatch, LEVELS)
    d = notify.audit_dir()
    d.mkdir(parents=True, exist_ok=True)
    for name in ("2026-04.jsonl", "2026-05.jsonl", "2026-06.jsonl", "state.json"):
        (d / name).write_text("{}\n", encoding="utf-8")
    notify.send(cfg, _msg(), now=NOW)
    # exec.lock: the audit is appended under its folder's lock (wi-brain-ledger-append-lock)
    assert sorted(p.name for p in d.iterdir()) == ["2026-06.jsonl", "2026-11.jsonl", "exec.lock", "state.json"]
    (d / "2026-05.jsonl").write_text("{}\n", encoding="utf-8")
    notify.send(cfg, _msg(), now=NOW)                       # not the month's first line: nothing pruned
    assert (d / "2026-05.jsonl").exists()
    assert len(notify.history(NOW)) >= 2
