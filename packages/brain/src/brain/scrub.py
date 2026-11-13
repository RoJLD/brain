"""One privacy scrub for what leaves the machine (wi-brain-privacy-scrub; spec-brain-client-standards §2 6.2 and §3):
every line of ``errors.log`` and of a crash report, and every outbound record (a notification, its outbox copy, the
telemetry the engine writes for later sending) passes :func:`text` (a string) or :func:`obj` (dicts and lists) first.
Zero token, standard library only; every pattern is linear on a long line.

What it replaces, in this order, each by a placeholder that says what was there:

- a secret, by brain.secretscan's shaped patterns (keys, tokens, a PEM block's first line): the match, ``<secret>``;
  URL credentials keep their scheme and host (``https://<secret>@host``); a password after its word (``password=x``,
  ``"password": "x"``, ``password='two words'``), ``<secret>`` too;
- an e-mail address, ``<email>`` (a no-reply or ``example`` address is kept);
- the user's home folder: its exact path first (a name with a space included), then any home folder with its user
  name (``C:\\Users\\name``, ``/Users/name``, ``/home/name``, WSL's ``/mnt/c/Users/name``, a share's
  ``\\\\host\\c$\\Users\\name``): ``~``, the rest of the path kept, so a stack trace still names its file;
- the machine's own name and the names of the fleet (config.json ``hosts`` and their ``aliases``, ``$BRAIN_MACHINE``,
  the host name): ``<host>``, whatever the case;
- the user's own login (``$USERNAME``, ``$USER``): ``<user>``, its case kept.

A name of 3 characters or fewer, and a common word (:data:`COMMON`: ``root``, ``admin``, ``runner``, ``dev``...),
is never replaced: it would blank ordinary words. A secretscan line drop (brain.secretscan.clean_text) loses the
whole line; the scrub keeps the line and takes out the private parts, so a crash line stays useful. Both run where a
record is written: the drop first for the ledgers, the scrub for what leaves. The corpus
``tests/fixtures/scrub/corpus.json`` holds each case, input and expected output.
"""

from __future__ import annotations

import getpass
import os
import re
from pathlib import Path

from . import secretscan

SECRET, EMAIL, HOME, HOST, USER = "<secret>", "<email>", "~", "<host>", "<user>"
MIN_NAME = 4
COMMON = {"root", "admin", "administrator", "runner", "user", "users", "guest", "default", "public", "dev", "test",
          "build", "home", "local", "localhost", "server", "main", "master", "node", "ubuntu", "debian", "docker",
          "brain", "desktop", "laptop", "machine", "computer", "worker"}
_EMAIL = re.compile(r"(?<![\w.%+-])([A-Za-z0-9._%+-]+)@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})(?![\w-])")
_EMAIL_KEEP = re.compile(r"(?i)^(?:no-?reply|git)$|(?:^|\.)(?:example\.(?:com|org|net)|invalid|test|localhost|"
                         r"noreply\.github\.com)$")
_HOME = re.compile(r"(?i)(?:(?:\b[A-Z]:|\b[A-Z]\$|/mnt/[a-z])[\\/]+Users|(?<![\w.-])/Users|(?<![\w.-])/home)"
                   r"[\\/]+[^\\/\s:\"'`<>|]+")
_PASSWORD = re.compile(r"(?i)((?<![A-Za-z])(?:pass(?:word|wd|phrase)|pwd|mot[ _-]?de[ _-]?passe|mdp)['\"]?\s*[:=]\s*)"
                       r"(?:'[^'\n]*'|\"[^\"\n]*\"|[^\s'\",}]+)")
_SHAPED = [rx for name, rx in secretscan.SHAPED if name != "url-credentials"]
_URL_CREDENTIALS = re.compile(r"(?i)(?<![A-Za-z0-9+.\-])([a-z][a-z0-9+.\-]*://)[^/\s:@]+:[^/\s@]+@")
_TEXT_KEYS = ("body", "title", "link", "message", "text", "why")   # the free text of an outbound record


def _keep(name: str) -> bool:
    return len(name) >= MIN_NAME and name.lower() not in COMMON


def hosts() -> list[str]:
    """The names to hide: this machine's (``$BRAIN_MACHINE``, the host name), the fleet's (config.json ``hosts`` and
    their aliases); common words and short names left out, longest first."""
    names = {os.environ.get("BRAIN_MACHINE", ""), os.environ.get("COMPUTERNAME", "")}
    try:
        import socket
        names.add(socket.gethostname().split(".")[0])
    except OSError:
        pass
    try:
        from . import config
        declared = config.load().data.get("hosts")
        for name, facts in (declared.items() if isinstance(declared, dict) else []):
            names.add(str(name))
            aliases = facts.get("aliases") if isinstance(facts, dict) else None
            names.update(a for a in aliases or [] if isinstance(a, str))
    except Exception:   # noqa: BLE001 - a scrub never fails: the machine's own names are still hidden
        pass
    return sorted((n for n in names if _keep(n)), key=len, reverse=True)


def users() -> list[str]:
    """The login names to hide (``$USERNAME``, ``$USER``, getpass); common words and short names left out."""
    names = {os.environ.get("USERNAME", ""), os.environ.get("USER", "")}
    try:
        names.add(getpass.getuser())
    except Exception:   # noqa: BLE001 - no login name readable: nothing more to hide
        pass
    return sorted((n for n in names if _keep(n)), key=len, reverse=True)


def homes() -> list[str]:
    """The user's own home folder, in both slash forms (a name with a space is caught whole here)."""
    try:
        home = str(Path.home())
    except (RuntimeError, OSError):
        return []
    return list(dict.fromkeys(h for h in (home, home.replace("\\", "/")) if len(h) > 3))


def _words(names: list[str], case: bool) -> re.Pattern | None:
    names = sorted((n for n in names if _keep(n)), key=len, reverse=True)   # the longest first: kestrel-wsl first
    if not names:
        return None
    return re.compile(("" if case else "(?i)") + r"(?<![A-Za-z0-9])(?:" + "|".join(re.escape(n) for n in names)
                      + r")(?![A-Za-z0-9])")


def names() -> dict:
    """The names :func:`text` hides, read once for a batch of strings (:func:`obj`)."""
    return {"host_names": hosts(), "user_names": users(), "home_paths": homes()}


def text(value: str, *, host_names: list[str] | None = None, user_names: list[str] | None = None,
         home_paths: list[str] | None = None) -> str:
    """``value`` with its secrets, e-mail addresses, home folders, host names and login replaced (the module's
    order). The names default to :func:`hosts`, :func:`users` and :func:`homes`."""
    if not value:
        return value
    out = _URL_CREDENTIALS.sub(lambda m: m.group(1) + SECRET + "@", value)
    for rx in _SHAPED:
        out = rx.sub(SECRET, out)
    out = _PASSWORD.sub(lambda m: m.group(1) + SECRET, out)
    out = _EMAIL.sub(lambda m: m.group(0) if _EMAIL_KEEP.search(m.group(1)) or _EMAIL_KEEP.search(m.group(2))
                     else EMAIL, out)
    for home in sorted(homes() if home_paths is None else home_paths, key=len, reverse=True):
        out = re.sub(re.escape(home) + r"(?![^\\/\s:\"'`<>|])", HOME, out, flags=re.I)
    out = _HOME.sub(HOME, out)
    rx = _words(hosts() if host_names is None else host_names, case=False)
    out = rx.sub(HOST, out) if rx else out
    rx = _words(users() if user_names is None else user_names, case=True)
    return rx.sub(USER, out) if rx else out


def obj(value, **given):
    """A copy of ``value`` (dicts, lists, strings) with every string scrubbed (:func:`text`); keys are kept. The
    names are read once for the whole value."""
    given = given or names()
    if isinstance(value, str):
        return text(value, **given)
    if isinstance(value, dict):
        return {k: obj(v, **given) for k, v in value.items()}
    if isinstance(value, list):
        return [obj(v, **given) for v in value]
    return value


def record(payload: dict) -> dict:
    """An outbound record with its free text scrubbed (:data:`_TEXT_KEYS`), its other fields as they are: a project,
    a key, a channel name or a level is what routes it, never text to hide."""
    given = names()
    return {k: (obj(v, **given) if k in _TEXT_KEYS else v) for k, v in payload.items()}
