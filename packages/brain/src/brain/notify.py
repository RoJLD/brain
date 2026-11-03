"""Notification channels, a Brain feature for every project (wi-brain-notify-channels; the owner, 2026-10-30): ``brain
notify send | status | setup``. ntfy first, then Telegram (``brain notify setup telegram`` walks through it: the steps
the TUI wizard will show), then e-mail; each channel is optional, declared once and routed per project and per level.

Each project of projects.yaml may declare ``notify:``, inline or as a YAML file relative to its root. Channel names are
global, like stack names: a project may route to a channel another project declares (the Brain's, usually)::

  brain:
    notify:
      channels:
        ntfy: {type: ntfy, server: https://ntfy.sh, topic_env: BRAIN_NTFY_TOPIC}   # token_env: an access token
        telegram: {type: telegram, token_env: BRAIN_TELEGRAM_TOKEN, chat_id_env: BRAIN_TELEGRAM_CHAT_ID}
        email: {type: email, host: smtp.example.org, port: 587, security: starttls, user_env: BRAIN_SMTP_USER,
                password_env: BRAIN_SMTP_PASSWORD, from_env: BRAIN_MAIL_FROM, to_env: BRAIN_MAIL_TO}
      levels:                     # info, warn, error, critical: the channels to try, in order
        critical: {channels: [ntfy, telegram, email], mode: all}   # all: every one of them
        error: [ntfy, telegram, email]                             # a list: the first that delivers (a fallback)
      decisions: error            # the level a blocking DDR is sent at (brain decision ask --blocking; default error)
      throttle: 60                # minutes before the same --key is sent again at its level (0: never held back)
  quant:
    notify: {levels: {critical: [ntfy, telegram]}}

A secret is never in a file: a key that holds one ends in ``_env`` and names the environment variable the owner
sets themselves (a literal ``token`` or ``password`` is refused, and so is a literal topic on the public ntfy.sh,
where the topic is the password). A level without channels sends nothing; a project without ``notify:`` neither.

``send`` tries the route's channels and records one line per channel tried in ``<BRAIN_HOME>/notify/<YYYY-MM>.jsonl``
(time, host, project, level, source, key, channel, outcome, title; never the message, a secret or a URL that carries
one). A failure is reported by its HTTP or SMTP status or its exception class, with every configured secret masked.
``--dry-run`` prints what would be sent and sends nothing; ``$BRAIN_NOTIFY=off`` sends nothing at all (the tests run
so), ``dry-run`` turns every send into a dry run. Exit code 0 when a channel delivered or nothing was due (no route,
held back by the throttle, off, dry run); 1 when every channel of the route failed or is not set up; 2 for a
configuration error. The transports use the standard library only (urllib, smtplib), imported when they send.

The watchdog's interface (a project's ``wi-ops-watchdog-alerts``, then ``wi-brain-project-alerts``) is ``brain notify
send --project P --level L --source watchdog --key ALERT-ID``, or ``notify()`` from Python: the key holds back a
repeat of an open alert, and the threshold (2 missed passes for a 15-minute task) stays the watchdog's.
"""

from __future__ import annotations

import json
import os
import re
import socket
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from . import graph, paths, projects, secretscan
from .config import owner_of   # brain.config's: this module's own config() reads the notify configuration

LEVELS = ("info", "warn", "error", "critical")
MODES = ("first", "all")
SWITCH = "BRAIN_NOTIFY"
NTFY_SERVER = "https://ntfy.sh"
PUBLIC_NTFY = {"ntfy.sh"}
TELEGRAM_API = "https://api.telegram.org"
TIMEOUT = 10.0
THROTTLE = 60
MAX_TEXT = 3800  # ntfy keeps 4,096 bytes as a message, Telegram 4,096 characters
PRIORITY = {"info": 2, "warn": 3, "error": 4, "critical": 5}
TAG = {"info": "information_source", "warn": "warning", "error": "x", "critical": "rotating_light"}
TOP_KEYS = {"channels", "levels", "decisions", "throttle"}
KEYS = {
    "ntfy": {"type", "server", "topic", "topic_env", "token_env", "timeout"},
    "telegram": {"type", "api", "token_env", "chat_id", "chat_id_env", "timeout"},
    "email": {"type", "host", "port", "security", "user_env", "password_env", "from", "from_env", "to", "to_env",
              "timeout"},
}
SECRET_ENV = {"topic_env", "token_env", "user_env", "password_env"}  # their values are masked in every output
SECURITY = ("starttls", "tls", "none")
NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class NotifyError(Exception):
    """A configuration error (exit code 2)."""


class DeliveryError(Exception):
    """A channel failed; the text is already masked."""


@dataclass
class Channel:
    name: str
    type: str
    conf: dict
    project: str

    def get(self, key: str, default=None):
        return self.conf.get(key, default)

    def env_names(self) -> list[str]:
        return [v for k, v in self.conf.items() if k.endswith("_env")]

    def missing(self, env: Mapping[str, str]) -> list[str]:
        return [n for n in self.env_names() if not env.get(n)]

    def secrets(self, env: Mapping[str, str]) -> list[str]:
        return [env[v] for k, v in self.conf.items() if k in SECRET_ENV and env.get(v)]


@dataclass
class Route:
    channels: list[str] = field(default_factory=list)
    mode: str = "first"


@dataclass
class Config:
    project: str
    channels: dict[str, Channel]
    levels: dict[str, Route]
    decisions: str = "error"
    throttle: int = THROTTLE
    declared: bool = False


@dataclass
class Message:
    project: str
    level: str
    body: str
    title: str = ""
    source: str = ""
    key: str = ""
    link: str = ""
    host: str = field(default_factory=socket.gethostname)

    def heading(self) -> str:
        title = self.title or (self.body.strip().splitlines() or [""])[0]
        return _cut(f"[{self.project} {self.level}] {title}", 200)

    def text(self) -> str:
        tail = " · ".join(x for x in (self.host, self.source) if x)
        parts = [self.body.strip(), self.link, f"— {tail}" if tail else ""]
        return _cut("\n".join(p for p in parts if p), MAX_TEXT)


@dataclass
class Attempt:
    channel: str
    outcome: str  # sent, failed, unset, dry-run
    detail: str = ""


@dataclass
class Result:
    project: str
    level: str
    status: str  # delivered, failed, no-route, throttled, off, dry-run
    mode: str = "first"
    route: list[str] = field(default_factory=list)
    attempts: list[Attempt] = field(default_factory=list)

    @property
    def code(self) -> int:
        return 1 if self.status == "failed" else 0

    def lines(self) -> list[str]:
        head = {"delivered": "delivered", "failed": "NOT delivered", "no-route": "nothing to send (no channel at "
                "this level)", "throttled": "held back (sent less than the throttle ago; --force sends it)",
                "off": f"off (${SWITCH}=off): nothing sent", "dry-run": "dry run: nothing sent"}[self.status]
        out = [f"notify {self.project} {self.level}: {head}"]
        for a in self.attempts:
            out.append(f"  {a.channel}: {a.outcome}" + (f" ({a.detail})" if a.detail else ""))
        return out

    def to_json(self) -> dict:
        return {**asdict(self), "delivered": self.status == "delivered"}


def _cut(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


# --- configuration ---

def _entry(p: projects.Project) -> dict:
    raw = p.notify
    if raw is None:
        return {}
    if isinstance(raw, str):
        f = p.root / raw
        if not f.is_file():
            raise NotifyError(f"{p.name}: notify file {raw} not found under {p.root}")
        raw = graph.load_yaml_file(f) or {}
    if not isinstance(raw, dict):
        raise NotifyError(f"{p.name}: notify: must be a mapping or a YAML file")
    unknown = set(raw) - TOP_KEYS
    if unknown:
        raise NotifyError(f"{p.name}: notify: unknown key(s) {', '.join(sorted(unknown))} "
                          f"(known: {', '.join(sorted(TOP_KEYS))})")
    return raw


def _channel(project: str, name: str, conf) -> Channel:
    where = f"{project}: notify channel {name!r}"
    if not NAME.match(str(name)):
        raise NotifyError(f"{where}: a name is lower case letters, digits, '.', '_' or '-'")
    if not isinstance(conf, dict) or conf.get("type") not in KEYS:
        raise NotifyError(f"{where}: type must be one of {', '.join(KEYS)}")
    kind = conf["type"]
    for k, v in conf.items():
        if k not in KEYS[kind]:
            if f"{k}_env" in KEYS[kind]:
                raise NotifyError(f"{where}: {k}: a secret is never written in a file; name its environment variable "
                                  f"with {k}_env (only {owner_of()} sets it)")
            raise NotifyError(f"{where}: unknown key {k!r} (known for {kind}: {', '.join(sorted(KEYS[kind]))})")
        if k.endswith("_env") and not (isinstance(v, str) and ENV_NAME.match(v)):
            raise NotifyError(f"{where}: {k} names an environment variable (letters, digits, '_'), got {v!r}")
        if not k.endswith("_env") and isinstance(v, str) and secretscan.find(v):
            raise NotifyError(f"{where}: {k} looks like a secret; name its environment variable instead")
    if "timeout" in conf and not (isinstance(conf["timeout"], (int, float)) and conf["timeout"] > 0):
        raise NotifyError(f"{where}: timeout is a number of seconds")
    one_of = {"ntfy": ("topic",), "telegram": ("chat_id",), "email": ("from", "to")}[kind]
    for k in one_of:
        if (k in conf) == (f"{k}_env" in conf):
            raise NotifyError(f"{where}: give {k} or {k}_env (one of them)")
    if kind == "ntfy":
        host = re.sub(r"^\w+://", "", str(conf.get("server", NTFY_SERVER))).split("/")[0].split(":")[0].lower()
        if "topic" in conf and host in PUBLIC_NTFY:
            raise NotifyError(f"{where}: on the public {host} the topic is the password: name it with topic_env")
    if kind == "telegram" and "token_env" not in conf:
        raise NotifyError(f"{where}: token_env is required (the bot's token, from @BotFather)")
    if kind == "email":
        if "host" not in conf:
            raise NotifyError(f"{where}: host is required (the SMTP server)")
        if conf.get("security", "starttls") not in SECURITY:
            raise NotifyError(f"{where}: security is one of {', '.join(SECURITY)}")
        if ("user_env" in conf) != ("password_env" in conf):
            raise NotifyError(f"{where}: give user_env and password_env together")
        if conf.get("security") == "none" and "password_env" in conf:
            raise NotifyError(f"{where}: a password is never sent in clear (security: starttls or tls)")
    return Channel(str(name), kind, dict(conf), project)


def _route(project: str, level: str, value, channels: dict[str, Channel]) -> Route:
    where = f"{project}: notify level {level!r}"
    if level not in LEVELS:
        raise NotifyError(f"{project}: notify: unknown level {level!r} (levels: {', '.join(LEVELS)})")
    if isinstance(value, dict):
        unknown = set(value) - {"channels", "mode"}
        if unknown:
            raise NotifyError(f"{where}: unknown key(s) {', '.join(sorted(unknown))} (channels, mode)")
        names, mode = value.get("channels") or [], value.get("mode", "first")
    else:
        names, mode = value or [], "first"
    if mode not in MODES:
        raise NotifyError(f"{where}: mode is first (the first that delivers) or all")
    if not isinstance(names, list):
        raise NotifyError(f"{where}: a list of channel names")
    for n in names:
        if n not in channels:
            raise NotifyError(f"{where}: unknown channel {n!r} (declared: {', '.join(channels) or 'none'})")
    return Route([str(n) for n in names], mode)


def channels(registry: Mapping[str, projects.Project]) -> dict[str, Channel]:
    """Every project's channels; a name declared twice is an error."""
    out: dict[str, Channel] = {}
    for p in registry.values():
        for name, conf in (_entry(p).get("channels") or {}).items():
            if name in out:
                raise NotifyError(f"notify channel {name!r} is declared by {out[name].project} and {p.name}")
            out[name] = _channel(p.name, name, conf)
    return out


def config(project: projects.Project, registry: Mapping[str, projects.Project] | None = None) -> Config:
    """The project's routes, over the channels of every registered project (``project`` replaces its own entry, so a
    worktree's projects.yaml is read at that root)."""
    reg = dict(projects.load(project.root) if registry is None else registry)
    reg[project.name] = project
    chans = channels(reg)
    e = _entry(project)
    levels = {str(lvl): _route(project.name, str(lvl), v, chans) for lvl, v in (e.get("levels") or {}).items()}
    decisions = e.get("decisions", "error")
    if decisions not in LEVELS:
        raise NotifyError(f"{project.name}: notify: decisions is a level ({', '.join(LEVELS)})")
    throttle = e.get("throttle", THROTTLE)
    if not isinstance(throttle, int) or throttle < 0:
        raise NotifyError(f"{project.name}: notify: throttle is a number of minutes (0: never held back)")
    return Config(project.name, chans, levels, decisions, throttle, declared=bool(e))


# --- transports (standard library, imported when they send) ---

def _post_json(url: str, payload: dict, headers: dict, timeout: float) -> tuple[int, bytes]:
    import urllib.request
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (http and https only, from the config)
        return r.status, r.read()


def _get_json(url: str, timeout: float) -> dict:
    import urllib.request
    with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310
        return json.loads(r.read() or b"{}")


def _smtp(host: str, port: int, security: str, timeout: float):
    import smtplib
    import ssl
    if security == "tls":
        return smtplib.SMTP_SSL(host, port, timeout=timeout, context=ssl.create_default_context())
    s = smtplib.SMTP(host, port, timeout=timeout)
    if security == "starttls":
        s.starttls(context=ssl.create_default_context())
    return s


def _mask(text: str, secrets: list[str]) -> str:
    for s in sorted(secrets, key=len, reverse=True):
        if len(s) >= 4:
            text = text.replace(s, "***")
    return secretscan.DROPPED if secretscan.find(text) else text


def _why(exc: BaseException, secrets: list[str]) -> str:
    """A failure in a few words, never the URL (a Telegram URL carries the token) nor a secret."""
    code = getattr(exc, "code", None) if hasattr(exc, "read") else None
    if code is not None:  # urllib's HTTPError: its status and the service's own short reason
        detail = ""
        try:
            data = json.loads(exc.read() or b"{}")
            detail = str(data.get("description") or data.get("error") or "") if isinstance(data, dict) else ""
        except Exception:  # noqa: BLE001 (a body that is not JSON: the status alone)
            pass
        text = f"HTTP {code}" + (f": {detail}" if detail else "")
    elif hasattr(exc, "smtp_code"):
        text = f"SMTP {exc.smtp_code}"
    elif hasattr(exc, "reason") and not isinstance(exc, DeliveryError):  # URLError: the reason, without the URL
        text = f"{type(exc).__name__}: {exc.reason}"
    else:
        text = f"{type(exc).__name__}: {exc}"
    return _cut(_mask(text, secrets), 200)


def _value(ch: Channel, key: str, env: Mapping[str, str]) -> str:
    return str(ch.get(key)) if key in ch.conf else env.get(ch.get(f"{key}_env"), "")


def _ntfy(ch: Channel, msg: Message, env: Mapping[str, str]) -> str:
    payload = {"topic": _value(ch, "topic", env), "title": msg.heading(), "message": msg.text(),
               "priority": PRIORITY[msg.level], "tags": [TAG[msg.level], msg.project]}
    if msg.link:
        payload["click"] = msg.link
    token = env.get(ch.get("token_env") or "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    status, _ = _post_json(str(ch.get("server", NTFY_SERVER)).rstrip("/") + "/", payload, headers,
                           float(ch.get("timeout", TIMEOUT)))
    return f"HTTP {status}"


def _telegram(ch: Channel, msg: Message, env: Mapping[str, str]) -> str:
    url = f"{str(ch.get('api', TELEGRAM_API)).rstrip('/')}/bot{env[ch.get('token_env')]}/sendMessage"
    payload = {"chat_id": _value(ch, "chat_id", env), "text": _cut(f"{msg.heading()}\n\n{msg.text()}", 4000),
               "disable_web_page_preview": True}
    status, body = _post_json(url, payload, {}, float(ch.get("timeout", TIMEOUT)))
    try:
        ok = json.loads(body or b"{}").get("ok", True)
    except ValueError:
        ok = True
    if not ok:
        raise DeliveryError(f"HTTP {status}: Telegram answered ok: false")
    return f"HTTP {status}"


def _addresses(text: str) -> list[str]:
    return [a.strip() for a in re.split(r"[,;]", text) if a.strip()]


def _email(ch: Channel, msg: Message, env: Mapping[str, str]) -> str:
    from email.message import EmailMessage
    to = ch.get("to")
    to = [str(a) for a in to] if isinstance(to, list) else _addresses(to or env.get(ch.get("to_env"), ""))
    m = EmailMessage()
    m["Subject"], m["From"], m["To"] = msg.heading(), _value(ch, "from", env), ", ".join(to)
    m.set_content(msg.text())
    s = _smtp(str(ch.get("host")), int(ch.get("port", 465 if ch.get("security") == "tls" else 587)),
              ch.get("security", "starttls"), float(ch.get("timeout", TIMEOUT)))
    try:
        if ch.get("user_env"):
            s.login(env[ch.get("user_env")], env[ch.get("password_env")])
        s.send_message(m)
    finally:
        try:
            s.quit()
        except Exception:  # noqa: BLE001 (the message is sent; a failed goodbye changes nothing)
            pass
    return f"SMTP to {len(to)} address(es)"


TRANSPORTS = {"ntfy": _ntfy, "telegram": _telegram, "email": _email}


def describe(ch: Channel, env: Mapping[str, str]) -> str:
    """Where a channel sends, with each environment variable set or missing (never its value)."""
    def var(key: str) -> str:
        if key in ch.conf:
            return str(ch.get(key))
        name = ch.get(f"{key}_env")
        return f"${name} ({'set' if env.get(name) else 'NOT SET'})" if name else ""

    if ch.type == "ntfy":
        out = f"ntfy {ch.get('server', NTFY_SERVER)}, topic {var('topic')}"
        return out + (f", token {var('token')}" if ch.get("token_env") else "")
    if ch.type == "telegram":
        return f"telegram {ch.get('api', TELEGRAM_API)}, bot token {var('token')}, chat {var('chat_id')}"
    sec = ch.get("security", "starttls")
    out = f"e-mail {ch.get('host')}:{ch.get('port', 465 if sec == 'tls' else 587)} ({sec}), from {var('from')}, " \
          f"to {var('to')}"
    return out + (f", login {var('user')} / {var('password')}" if ch.get("user_env") else "")


# --- the audit and the throttle ---

def audit_dir() -> Path:
    return paths.brain_home() / "notify"


def _audit(lines: list[dict], now: datetime) -> None:
    if not lines:
        return
    d = audit_dir()
    d.mkdir(parents=True, exist_ok=True)
    with open(d / f"{now:%Y-%m}.jsonl", "a", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")


def history(now: datetime | None = None, months: int = 2) -> list[dict]:
    """The audit lines of this month and the ones before, oldest first."""
    now = now or datetime.now(timezone.utc)
    out, y, m = [], now.year, now.month
    files = []
    for _ in range(months):
        files.append(audit_dir() / f"{y:04d}-{m:02d}.jsonl")
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    for f in reversed(files):
        if f.is_file():
            for line in f.read_text(encoding="utf-8").splitlines():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    return out


def _held(cfg: Config, msg: Message, now: datetime) -> bool:
    if not msg.key or not cfg.throttle:
        return False
    since = now - timedelta(minutes=cfg.throttle)
    for line in history(now):
        if (line.get("project"), line.get("level"), line.get("key"), line.get("outcome")) == \
                (msg.project, msg.level, msg.key, "sent"):
            try:
                if datetime.fromisoformat(str(line["at"]).replace("Z", "+00:00")) >= since:
                    return True
            except (KeyError, ValueError):
                continue
    return False


# --- send ---

def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def send(cfg: Config, msg: Message, *, only: list[str] | None = None, dry_run: bool = False, force: bool = False,
         env: Mapping[str, str] | None = None, now: datetime | None = None) -> Result:
    """Send ``msg`` through the route of its level (``only``: these channels, every one of them), the first channel
    that delivers in mode first, every one in mode all. Raises NotifyError for a bad level or channel name only."""
    env = os.environ if env is None else env
    now = now or datetime.now(timezone.utc)
    if msg.level not in LEVELS:
        raise NotifyError(f"unknown level {msg.level!r} (levels: {', '.join(LEVELS)})")
    switch = (env.get(SWITCH) or "").strip().lower()
    dry_run = dry_run or switch == "dry-run"
    if only:
        for n in only:
            if n not in cfg.channels:
                raise NotifyError(f"unknown channel {n!r} (declared: {', '.join(cfg.channels) or 'none'})")
        route = Route(list(only), "all")
    else:
        route = cfg.levels.get(msg.level) or Route()
    res = Result(msg.project, msg.level, "no-route", route.mode, list(route.channels))
    if not route.channels:
        return res
    if switch == "off":
        res.status = "off"
        return res
    base = {"at": _iso(now), "host": msg.host, "project": msg.project, "level": msg.level, "source": msg.source,
            "key": msg.key, "title": _mask(msg.heading(), [])}
    if not dry_run and not force and _held(cfg, msg, now):
        res.status = "throttled"
        _audit([{**base, "channel": "", "outcome": "throttled"}], now)
        return res
    lines = []
    for name in route.channels:
        ch = cfg.channels[name]
        missing = ch.missing(env)
        if dry_run:
            note = f"would send through {describe(ch, env)}"
            if route.mode == "first" and len(res.attempts):
                note += ", if the ones before fail"
            res.attempts.append(Attempt(name, "dry-run", note))
            continue
        if missing:
            a = Attempt(name, "unset", f"not set up: {', '.join('$' + m for m in missing)} not set")
        else:
            try:
                a = Attempt(name, "sent", TRANSPORTS[ch.type](ch, msg, env))
            except Exception as exc:  # noqa: BLE001 (a channel never fails the caller: the next one is tried)
                a = Attempt(name, "failed", _why(exc, ch.secrets(env)))
        res.attempts.append(a)
        lines.append({**base, "channel": name, "outcome": a.outcome, "detail": a.detail})
        if a.outcome == "sent" and route.mode == "first":
            break
    _audit(lines, now)
    if dry_run:
        res.status = "dry-run"
    else:
        res.status = "delivered" if any(a.outcome == "sent" for a in res.attempts) else "failed"
    return res


def notify(project: str | projects.Project, level: str, body: str, *, title: str = "", source: str = "",
           key: str = "", link: str = "", only: list[str] | None = None, dry_run: bool = False, force: bool = False,
           root: Path | None = None) -> Result:
    """The Python entry for a watchdog or a hook: a registered project's name (or a Project), a level, a message."""
    p = project if isinstance(project, projects.Project) else projects.get(project, root)
    cfg = config(p)
    return send(cfg, Message(p.name, level, body, title, source, key, link), only=only, dry_run=dry_run, force=force)


def decision_message(project: str, ddr: dict) -> tuple[str, str]:
    """The title and text of a blocking DDR's notification: the question, the options, the command that answers."""
    lines = [_cut(" ".join(str(ddr.get("question", "")).split()), 400), ""]
    for i, o in enumerate(ddr.get("options") or [], 1):
        lines.append(f"{i}. {o.get('label', '')}" + (" (recommended)" if i == 1 else ""))
    lines += ["", f"brain decision answer {ddr.get('id', '')} <n>" +
              (f"  (--project {project})" if project and project != "brain" else "")]
    return _cut(f"Decision needed: {ddr.get('title', '')}", 150), "\n".join(lines)


def decision(project: projects.Project, ddr: dict, *, dry_run: bool = False,
             registry: Mapping[str, projects.Project] | None = None, env: Mapping[str, str] | None = None) -> list[str]:
    """``brain decision ask --blocking``: the DDR sent at the project's decisions level; the lines to print. Never
    raises: the question is asked even when the notification fails."""
    try:
        cfg = config(project, registry)
        title, body = decision_message(project.name, ddr)
        msg = Message(project.name, cfg.decisions, body, title, "decision", str(ddr.get("id", "")))
        return send(cfg, msg, dry_run=dry_run, env=env).lines()
    except NotifyError as exc:
        return [f"notify: not sent: {exc}"]
    except Exception as exc:  # noqa: BLE001
        return [f"notify: not sent: {_why(exc, [])}"]


# --- status and setup (the steps the TUI wizard will show) ---

def status(cfg: Config, env: Mapping[str, str] | None = None, last: int = 5) -> list[str]:
    env = os.environ if env is None else env
    switch = (env.get(SWITCH) or "").strip().lower()
    out = [f"notify: {'off' if switch == 'off' else 'dry run' if switch == 'dry-run' else 'on'} (${SWITCH}="
           f"{switch or 'unset'})"]
    if cfg.channels:
        out.append("channels:")
        width = max(len(n) for n in cfg.channels)
        for n, ch in cfg.channels.items():
            out.append(f"  {n:<{width}}  {describe(ch, env)}  [{ch.project}]")
    else:
        out.append("channels: none declared (projects.yaml, notify: channels:)")
    if not cfg.declared:
        out.append(f"{cfg.project}: no notify: in projects.yaml: nothing is sent for this project")
    else:
        for lvl in reversed(LEVELS):
            r = cfg.levels.get(lvl)
            how = "nothing" if not r or not r.channels else \
                ", ".join(r.channels) + (" (every one)" if r.mode == "all" else
                                         " (the first that delivers)" if len(r.channels) > 1 else "")
            out.append(f"{cfg.project} {lvl}: {how}")
        out.append(f"{cfg.project}: blocking decisions at {cfg.decisions}; throttle {cfg.throttle} min")
    mine = [h for h in history() if h.get("project") == cfg.project][-last:]
    if mine:
        out.append("last sends:")
        out += [f"  {h.get('at')} {h.get('level')} {h.get('channel') or '-'} {h.get('outcome')}: {h.get('title')}"
                for h in mine]
    return out


def _set_env_hint(name: str) -> str:
    if os.name == "nt":
        return f"[Environment]::SetEnvironmentVariable('{name}', '<value>', 'User')   (PowerShell; then a new terminal)"
    return f"export {name}='<value>'   (in your shell profile; then a new terminal)"


SNIPPETS = {
    "ntfy": "ntfy: {type: ntfy, server: https://ntfy.sh, topic_env: BRAIN_NTFY_TOPIC}",
    "telegram": "telegram: {type: telegram, token_env: BRAIN_TELEGRAM_TOKEN, chat_id_env: BRAIN_TELEGRAM_CHAT_ID}",
    "email": "email: {type: email, host: smtp.example.org, port: 587, security: starttls, user_env: BRAIN_SMTP_USER, "
             "password_env: BRAIN_SMTP_PASSWORD, from_env: BRAIN_MAIL_FROM, to_env: BRAIN_MAIL_TO}",
}


def setup(cfg: Config, target: str, *, find_chat: bool = False, env: Mapping[str, str] | None = None) -> list[str]:
    """The setup steps of a channel (its name, or a type when none is declared), with what is set and what is
    missing; ``find_chat`` asks the Telegram bot for the chats that wrote to it (getUpdates: it sends nothing)."""
    env = os.environ if env is None else env
    ch = cfg.channels.get(target) or next((c for c in cfg.channels.values() if c.type == target), None)
    kind = ch.type if ch else target
    if kind not in KEYS:
        raise NotifyError(f"setup: {target!r} is neither a declared channel ({', '.join(cfg.channels) or 'none'}) "
                          f"nor a type ({', '.join(KEYS)})")
    out = []
    if not ch:
        out += [f"No {kind} channel is declared. Add it under a project's notify: channels: in projects.yaml (by PR):",
                f"  {SNIPPETS[kind]}", "then route levels to it (notify: levels:) and run this again."]
        return out
    out.append(f"{ch.name}: {describe(ch, env)}")
    if kind == "ntfy":
        out += ["1. Install the ntfy app (Android, iOS) or open the server's web app.",
                "2. Pick a long random topic, e.g. python -c \"import secrets; print('brain-' + "
                "secrets.token_urlsafe(18))\"; on a public server anyone who knows it reads your messages.",
                f"3. Set it yourself: {_set_env_hint(ch.get('topic_env') or 'BRAIN_NTFY_TOPIC')}"
                if ch.get("topic_env") else "3. The topic is in the configuration (a private server).",
                f"4. Subscribe to it in the app (server {ch.get('server', NTFY_SERVER)}).",
                f"5. Test: brain notify send --project {cfg.project} --channel {ch.name} --level info \"test\""]
    elif kind == "telegram":
        token = env.get(ch.get("token_env"))
        out += ["1. In Telegram, talk to @BotFather: /newbot, a name, a username ending in 'bot'; it gives a token.",
                f"2. Set it yourself: {_set_env_hint(ch.get('token_env'))}"
                + ("  [done]" if token else ""),
                "3. Open your bot in Telegram and send it any message (it can only write to who wrote first).",
                f"4. brain notify setup {ch.name} --find-chat   lists the chats that wrote to the bot (sends nothing)",
                f"5. Set the chat id yourself: {_set_env_hint(ch.get('chat_id_env') or 'BRAIN_TELEGRAM_CHAT_ID')}"
                if ch.get("chat_id_env") else "5. The chat id is in the configuration.",
                f"6. Test: brain notify send --project {cfg.project} --channel {ch.name} --level info \"test\""]
        if find_chat:
            if not token:
                out.append(f"find-chat: ${ch.get('token_env')} is not set (step 2 first)")
            else:
                url = f"{str(ch.get('api', TELEGRAM_API)).rstrip('/')}/bot{token}/getUpdates"
                try:
                    data = _get_json(url, float(ch.get("timeout", TIMEOUT)))
                except Exception as exc:  # noqa: BLE001
                    out.append(f"find-chat: failed: {_why(exc, ch.secrets(env))}")
                else:
                    chats = {}
                    for u in data.get("result") or []:
                        c = (u.get("message") or u.get("channel_post") or u.get("my_chat_member") or {}).get("chat")
                        if c and "id" in c:
                            chats[c["id"]] = c.get("username") or c.get("title") or c.get("first_name") or c.get("type")
                    out += [f"find-chat: chat {i} ({who})" for i, who in chats.items()] or \
                           ["find-chat: no chat yet: send your bot a message (step 3), then run this again"]
    else:
        out += ["1. Pick the SMTP server: host, port, security (starttls on 587, tls on 465); with Gmail, an app "
                "password (Google account, Security, App passwords), never the account's own.",
                *[f"{i}. Set it yourself: {_set_env_hint(ch.get(k))}" + ("  [done]" if env.get(ch.get(k)) else "")
                  for i, k in enumerate([k for k in ("user_env", "password_env", "from_env", "to_env")
                                         if ch.get(k)], 2)],
                f"Test: brain notify send --project {cfg.project} --channel {ch.name} --level info \"test\""]
    missing = ch.missing(env)
    out.append(f"missing: {', '.join('$' + m for m in missing)}" if missing else "every variable is set")
    return out
