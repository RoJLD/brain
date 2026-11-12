"""One privacy scrub for what leaves the machine (wi-brain-privacy-scrub; spec-brain-client-standards §2 6.2 and §3):
every line of ``errors.log`` and of a crash report, and every outbound record (a notification, its outbox copy, the
telemetry the engine writes for later sending) passes :func:`text` (a string) or :func:`obj` (dicts and lists) first.
Zero token, standard library only.

What it replaces, in this order, each by a placeholder that says what was there:

- a secret, by brain.secretscan's shaped patterns (keys, tokens, a PEM block's first line, URL credentials): the
  match, ``<secret>``; a password after its word (``password=...``), ``<secret>`` too;
- an e-mail address, ``<email>`` (a no-reply or ``example`` address is kept);
- a home folder with its user name (``C:\\Users\\name``, ``/Users/name``, ``/home/name``): ``~``, the rest of the path
  kept (``~\\project\\file.py``), so a stack trace still names its file;
- the machine's own name and the names of the fleet (config.json ``hosts`` and their ``aliases``, ``$BRAIN_MACHINE``,
  the host name): ``<host>``;
- the user's own login (``$USERNAME``, ``$USER``): ``<user>``.

A secretscan line drop (brain.secretscan.clean_text) loses the whole line; the scrub keeps the line and takes out the
private parts, so a crash line stays useful. Both run where a record is written: the drop first for the ledgers, the
scrub for what leaves. The corpus ``tests/fixtures/scrub/corpus.json`` holds each case, input and expected output.
"""

from __future__ import annotations

import getpass
import os
import re

from . import secretscan

SECRET, EMAIL, HOME, HOST, USER = "<secret>", "<email>", "~", "<host>", "<user>"
_EMAIL = re.compile(r"(?<![\w.%+-])([A-Za-z0-9._%+-]+)@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})(?![\w-])")
_EMAIL_KEEP = re.compile(r"(?i)^(?:no-?reply|git)$|(?:^|\.)(?:example\.(?:com|org|net)|invalid|test|localhost|"
                         r"noreply\.github\.com)$")
_HOME = re.compile(r"(?i)(?:\b[A-Z]:(?:\\\\|\\|/)+Users|(?<![\w.-])/Users|(?<![\w.-])/home)(?:\\\\|\\|/)+[^\\/\s:\"'`<>|]+")
_PASSWORD = re.compile(r"(?i)((?:pass(?:word|wd|phrase)|pwd|mot[ _-]?de[ _-]?passe|mdp)\w*\s*[:=]\s*)(['\"]?)[^\s'\"]+\2")
_SHAPED = [rx for name, rx in secretscan.SHAPED if name != "url-credentials"]
_URL_CREDENTIALS = re.compile(r"([a-z][a-z0-9+.\-]*://)[^/\s:@]+:[^/\s@]+@")


def hosts() -> list[str]:
    """The names to hide: this machine's (``$BRAIN_MACHINE``, the host name), the fleet's (config.json ``hosts`` and
    their aliases); 3 characters or more, longest first."""
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
    return sorted((n for n in names if len(n) >= 3), key=len, reverse=True)


def users() -> list[str]:
    names = {os.environ.get("USERNAME", ""), os.environ.get("USER", "")}
    try:
        names.add(getpass.getuser())
    except Exception:   # noqa: BLE001 - no login name readable: nothing more to hide
        pass
    return sorted((n for n in names if len(n) >= 3), key=len, reverse=True)


def _words(names: list[str]) -> re.Pattern | None:
    names = sorted(names, key=len, reverse=True)   # the longest first: kestrel-wsl before kestrel
    return re.compile(r"(?i)(?<![A-Za-z0-9])(?:" + "|".join(re.escape(n) for n in names) + r")(?![A-Za-z0-9])") \
        if names else None


def text(value: str, *, host_names: list[str] | None = None, user_names: list[str] | None = None) -> str:
    """``value`` with its secrets, e-mail addresses, home folders, host names and login replaced (the module's
    order). ``host_names`` and ``user_names`` default to :func:`hosts` and :func:`users`."""
    if not value:
        return value
    out = value
    out = _URL_CREDENTIALS.sub(lambda m: m.group(1) + SECRET + "@", out)
    for rx in _SHAPED:
        out = rx.sub(SECRET, out)
    out = _PASSWORD.sub(lambda m: m.group(1) + SECRET, out)
    out = _EMAIL.sub(lambda m: m.group(0) if _EMAIL_KEEP.search(m.group(1)) or _EMAIL_KEEP.search(m.group(2))
                     else EMAIL, out)
    out = _HOME.sub(HOME, out)
    rx = _words(hosts() if host_names is None else host_names)
    out = rx.sub(HOST, out) if rx else out
    rx = _words(users() if user_names is None else user_names)
    return rx.sub(USER, out) if rx else out


def obj(value, **names):
    """A copy of ``value`` (dicts, lists, strings) with every string scrubbed (:func:`text`); keys are kept."""
    if isinstance(value, str):
        return text(value, **names)
    if isinstance(value, dict):
        return {k: obj(v, **names) for k, v in value.items()}
    if isinstance(value, list):
        return [obj(v, **names) for v in value]
    return value
