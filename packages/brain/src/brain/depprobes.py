"""Dependency probes: loud fallbacks (wi-brain-dependency-probes). Every external dependency a capability relies on (a
CLI's login, a tool's last output, an index's freshness, a channel's last delivery, a collector's last data, the
last backup) declares a token-free probe in the personal brain's ``config.json`` (``probes``); the mechanism is the
engine's, the list is the owner's, and no code is written per dependency.

A probe is one of the kinds of :data:`KINDS`, each a neutral check:

  file-age   the newest file matching ``path`` (a glob) was modified within ``max_age``;
  json-age   a timestamp field (``field``, dotted) of a JSON file, or of the last line of a JSON Lines file that
             matches ``where`` ({field: value}; the newest of up to three files that hold one, so a monthly ledger's
             new month is not a failure), is within ``max_age``: an ISO time, or seconds (milliseconds) since the
             epoch;
  command    a program (``argv``, never through a shell; no shell or interpreter as the program) exits with one of
             ``ok_exit`` (default 0) within ``timeout``, and its output matches ``expect`` when given. Its output is
             read for ``expect`` only: never shown, never stored, never sent;
  http       a GET of ``url`` answers one of ``ok_status`` (default any 2xx or 3xx) within ``timeout``; no header is
             sent, a URL carrying a user or a password is refused, and the URL is never shown.

Every probe may say ``about`` (the capability that relies on it), ``level`` (the alert's: info, warn, the default,
error, critical), ``timeout`` (default :data:`TIMEOUT`, at most :data:`TIMEOUT_MAX`) and ``machines`` (the hosts it
runs on, case-insensitive; none: every machine). Durations are written ``90s``, ``15m``, ``26h``, ``7d``, ``2w``. In
a path, ``~``, the environment's variables and ``$BRAIN_HOME`` (this machine's brain home, even unset) are expanded::

  "probes": {
    "cli-login": {"kind": "command", "argv": ["tool", "auth", "status"], "expect": "logged in", "timeout": "20s",
                  "level": "error", "about": "the summaries of the session archive"},
    "notify-delivery": {"kind": "json-age", "path": "$BRAIN_HOME/notify/*.jsonl", "field": "at",
                        "where": {"outcome": "sent"}, "max_age": "7d"},
    "backup": {"kind": "file-age", "path": "D:/backups/*.zip", "max_age": "26h", "machines": ["host-a"]}
  }

A result is OK, STALE (older than ``max_age``), FAIL (missing, unreadable, a wrong exit, status or output) or TIMEOUT.
:func:`run` runs this machine's probes, each in its own thread with its own timeout (a file read, a stat and a
subprocess each have theirs), and records them in ``$BRAIN_HOME/probes/state.json`` (brain.stateio's policy): each
probe's state, why, when it last ran, its last OK and since when it is in its state. :func:`last` reads that record
back (``brain status --quick``, the alerts of a project that did not run them). The alerts pass (brain.alerts, the
brain's own project) turns each probe that is not OK into an alert ``probe:<name>`` at its level, so the pass's
notify path and its dedup send it once when it opens, again when its level rises, and ``resolved`` when it closes;
``brain status``'s probes row and the cockpit's health panel show them; ``brain probes`` runs them on demand.
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime, timezone
from pathlib import Path

from . import alerts, config, paths, stateio, timing

FILE = "probes"                      # config.json's key
STATES = ("OK", "STALE", "FAIL", "TIMEOUT")
TIMEOUT = 10.0                       # seconds, a probe that names none
TIMEOUT_MAX = 120.0
GRACE = 2.0                          # seconds a probe's thread is waited for beyond its own timeout
WORKERS = 8
READ_MAX = 4 * 2 ** 20               # bytes of a JSON file read at most
TAIL = 256 * 2 ** 10                 # bytes read from the end of a JSON Lines file
JSONL_FILES = 3                      # JSON Lines files read back, newest first, for a line that matches
NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
COMMON = {"kind", "about", "level", "timeout", "machines"}
# kind -> (required keys, optional keys)
KINDS = {
    "file-age": ({"path", "max_age"}, set()),
    "json-age": ({"path", "field", "max_age"}, {"where"}),
    "command": ({"argv"}, {"ok_exit", "expect"}),
    "http": ({"url"}, {"ok_status"}),
}
KIND_HELP = {
    "file-age": "the newest file matching path (a glob) modified within max_age",
    "json-age": "a timestamp field (dotted) of a JSON file, or of the last JSON Lines line matching where, within "
                "max_age",
    "command": "argv (no shell) exits with ok_exit (default 0) within timeout, its output matching expect; the output "
               "is never shown",
    "http": "a GET of url answers ok_status (default 2xx or 3xx) within timeout; no header, the URL never shown",
}
# programs a command probe may not start: a shell or an interpreter would run any code the declaration holds
REFUSED = {"cmd", "powershell", "pwsh", "bash", "sh", "zsh", "dash", "fish", "wsl", "python", "python3", "py",
           "pythonw", "node", "deno", "perl", "ruby", "wscript", "cscript", "mshta", "rundll32", "regsvr32"}
STATE_V = 1


class ProbeError(ValueError):
    """A bad probe declaration."""


# --- the declarations ---

def _duration(value, where: str) -> float:
    if not isinstance(value, str):
        raise ProbeError(f"{where}: a duration such as 90s, 15m, 26h, 7d (a string)")
    try:
        return alerts.seconds(value)
    except ValueError as exc:
        raise ProbeError(f"{where}: {exc}") from None


def _ints(value, where: str) -> list[int]:
    if not isinstance(value, list) or not value or not all(isinstance(v, int) and not isinstance(v, bool)
                                                            for v in value):
        raise ProbeError(f"{where}: a list of whole numbers")
    return list(value)


def _program(argv0: str) -> str:
    return Path(argv0.replace("\\", "/")).name.lower().removesuffix(".exe").removesuffix(".cmd").removesuffix(".bat")


def parse(name: str, conf) -> dict:
    """One declaration checked and normalised: {name, kind, about, level, timeout, machines, ...its kind's keys};
    raises ProbeError."""
    where = f"config.json probes.{name}"
    if not isinstance(name, str) or not NAME.match(name):
        raise ProbeError(f"{where}: a name of lowercase letters, digits, dots, dashes and underscores")
    if not isinstance(conf, dict):
        raise ProbeError(f"{where}: an object")
    kind = conf.get("kind")
    if kind not in KINDS:
        raise ProbeError(f"{where}: kind {kind!r}: one of {', '.join(KINDS)}")
    need, opt = KINDS[kind]
    unknown = set(map(str, conf)) - COMMON - need - opt
    if unknown:
        raise ProbeError(f"{where}: unknown key(s) {', '.join(sorted(unknown))} for kind {kind} "
                         f"(known: {', '.join(sorted(COMMON | need | opt))})")
    missing = need - set(conf)
    if missing:
        raise ProbeError(f"{where}: kind {kind} needs {', '.join(sorted(missing))}")
    level = conf.get("level", "warn")
    if level not in alerts.LEVELS:
        raise ProbeError(f"{where}: level {level!r}: one of {', '.join(alerts.LEVELS)}")
    machines = conf.get("machines") or []
    if not isinstance(machines, list) or not all(isinstance(m, str) and m for m in machines):
        raise ProbeError(f"{where}: machines: a list of host names")
    timeout = _duration(conf["timeout"], f"{where}: timeout") if "timeout" in conf else TIMEOUT
    if timeout > TIMEOUT_MAX:
        raise ProbeError(f"{where}: timeout {conf['timeout']}: at most {int(TIMEOUT_MAX)}s")
    p = {"name": name, "kind": kind, "about": str(conf.get("about") or ""), "level": level, "timeout": timeout,
         "machines": list(machines)}
    if "max_age" in need:
        p["max_age"] = _duration(conf["max_age"], f"{where}: max_age")
    if "path" in need:
        if not isinstance(conf["path"], str) or not conf["path"].strip():
            raise ProbeError(f"{where}: path: a file or a glob")
        p["path"] = conf["path"]
    if kind == "json-age":
        if not isinstance(conf["field"], str) or not conf["field"]:
            raise ProbeError(f"{where}: field: a key, dotted for a nested one (meta.updated_at)")
        p["field"] = conf["field"]
        w = conf.get("where") or {}
        if not isinstance(w, dict) or not all(isinstance(v, (str, int, float, bool)) for v in w.values()):
            raise ProbeError(f"{where}: where: an object of field -> a string, number or boolean")
        p["where"] = dict(w)
    if kind == "command":
        argv = conf["argv"]
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) and a for a in argv):
            raise ProbeError(f"{where}: argv: the program and its arguments, a list of strings")
        if _program(argv[0]) in REFUSED:
            raise ProbeError(f"{where}: argv: {argv[0]!r} is a shell or an interpreter: name the program itself "
                             "(a command probe runs no script)")
        p["argv"] = list(argv)
        p["ok_exit"] = _ints(conf["ok_exit"], f"{where}: ok_exit") if "ok_exit" in conf else [0]
        if "expect" in conf:
            if not isinstance(conf["expect"], str) or not conf["expect"]:
                raise ProbeError(f"{where}: expect: a regular expression")
            try:
                re.compile(conf["expect"])
            except re.error as exc:
                raise ProbeError(f"{where}: expect: {exc}") from None
            p["expect"] = conf["expect"]
    if kind == "http":
        from urllib.parse import urlsplit
        url = conf["url"]
        parts = urlsplit(url) if isinstance(url, str) else None
        if not parts or parts.scheme not in ("http", "https") or not parts.hostname:
            raise ProbeError(f"{where}: url: an http or https URL")
        if parts.username or parts.password:
            raise ProbeError(f"{where}: url: no user or password in the URL (a probe carries no secret)")
        p["url"] = url
        p["ok_status"] = _ints(conf["ok_status"], f"{where}: ok_status") if "ok_status" in conf else []
    return p


def declared(cfg: config.Config | None = None) -> tuple[list[dict], list[str]]:
    """(the probes config.json declares, parsed; the errors of the bad ones, which are left out)."""
    cfg = cfg or config.load()
    raw = cfg.data.get(FILE)
    if raw is None:
        return [], []
    if not isinstance(raw, dict):
        return [], [f"config.json {FILE}: an object of name -> probe"]
    out, errors = [], []
    for name, conf in raw.items():
        try:
            out.append(parse(name, conf))
        except ProbeError as exc:
            errors.append(str(exc))
    return out, errors


def check(cfg: config.Config | None = None) -> list[str]:
    """What is wrong in config.json's probes (brain config --check, brain check --all)."""
    return declared(cfg)[1]


def mine(probes: list[dict], host: str | None = None) -> list[dict]:
    """The probes that run on ``host`` (this machine): those naming it, and those naming no machine."""
    host = (host or timing.host()).lower()
    return [p for p in probes if not p["machines"] or host in {m.lower() for m in p["machines"]}]


# --- the kinds ---

def _expand(text: str) -> str:
    home = paths.brain_home().as_posix()
    text = text.replace("${BRAIN_HOME}", home).replace("$BRAIN_HOME", home)
    return os.path.expandvars(os.path.expanduser(text))


def _newest(pattern: str, n: int = 1) -> list[Path]:
    """The ``n`` newest files matching ``pattern`` (a path or a glob), newest first; [] when none does."""
    pattern = _expand(pattern)
    found = glob.glob(pattern, recursive=True) if glob.has_magic(pattern) else [pattern]
    timed = []
    for f in found:
        try:
            if os.path.isfile(f):
                timed.append((os.stat(f).st_mtime, Path(f)))
        except OSError:
            continue
    return [f for _, f in sorted(timed, key=lambda x: x[0], reverse=True)[:n]]


def _age_text(seconds: float) -> str:
    for unit, n in (("d", 86400), ("h", 3600), ("min", 60)):
        if seconds >= n:
            return f"{seconds / n:.1f} {unit}" if seconds < 10 * n else f"{seconds // n:.0f} {unit}"
    return f"{max(seconds, 0):.0f} s"


def _aged(age: float, max_age: float, what: str) -> tuple[str, str, float]:
    if age > max_age:
        return "STALE", f"{what} {_age_text(age)} old > {alerts.every_text(max_age)}", age
    return "OK", f"{what} {_age_text(age)} old", age


def probe_file_age(p: dict, now: datetime) -> tuple[str, str, float | None]:
    found = _newest(p["path"])
    if not found:
        return "FAIL", "no file matches its path", None
    try:
        mtime = found[0].stat().st_mtime
    except OSError as exc:
        return "FAIL", f"unreadable ({type(exc).__name__})", None
    return _aged(now.timestamp() - mtime, p["max_age"], "newest file")


def _field(doc, dotted: str):
    for part in dotted.split("."):
        if not isinstance(doc, dict) or part not in doc:
            return None
        doc = doc[part]
    return doc


def _when(value) -> datetime | None:
    """An ISO time, or seconds (milliseconds above 1e12) since the epoch."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        v = value / 1000 if value > 1e12 else value
        try:
            return datetime.fromtimestamp(v, timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    return alerts._ts(value)


def _matches(doc, where: dict) -> bool:
    return isinstance(doc, dict) and all(_field(doc, k) == v for k, v in where.items())


def _read_json(f: Path) -> tuple[object, str]:
    """(the document, '') of a JSON file, or of the last line of a JSON Lines file (None, the line list); (None, why)."""
    try:
        size = f.stat().st_size
        with open(f, "rb") as fh:
            if f.suffix.lower() == ".jsonl":
                fh.seek(max(0, size - TAIL))
                lines = fh.read(TAIL).decode("utf-8", errors="replace").splitlines()
                return lines[1:] if size > TAIL else lines, "lines"
            if size > READ_MAX:
                return None, f"larger than {READ_MAX // 2 ** 20} MB"
            return json.loads(fh.read().decode("utf-8-sig", errors="replace")), ""
    except OSError as exc:
        return None, f"unreadable ({type(exc).__name__})"
    except ValueError:
        return None, "not JSON"


def _last_line(files: list[Path], p: dict) -> dict | None:
    """The last line with a time in ``field`` that matches ``where``, from the newest JSON Lines file back."""
    for f in files:
        lines, how = _read_json(f)
        if how != "lines":
            continue
        for line in reversed(lines):
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if _matches(row, p["where"]) and _when(_field(row, p["field"])):
                return row
    return None


def probe_json_age(p: dict, now: datetime) -> tuple[str, str, float | None]:
    files = _newest(p["path"], JSONL_FILES)
    if not files:
        return "FAIL", "no file matches its path", None
    if files[0].suffix.lower() == ".jsonl":   # a monthly ledger: last month's when this one has no such line yet
        doc = _last_line([f for f in files if f.suffix.lower() == ".jsonl"], p)
        if doc is None:
            return "FAIL", f"no line with {p['field']}" + (" matching where" if p["where"] else ""), None
    else:
        doc, how = _read_json(files[0])
        if doc is None:
            return "FAIL", how, None
        if p["where"] and not _matches(doc, p["where"]):
            return "FAIL", "the file does not match where", None
    at = _when(_field(doc, p["field"]))
    if at is None:
        return "FAIL", f"{p['field']} is not a time", None
    return _aged((now - at).total_seconds(), p["max_age"], p["field"])


def probe_command(p: dict, now: datetime) -> tuple[str, str, float | None]:
    exe = shutil.which(p["argv"][0])
    if exe is None:
        return "FAIL", f"{_program(p['argv'][0])} not found", None
    try:
        proc = subprocess.run([exe, *p["argv"][1:]], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=p["timeout"], stdin=subprocess.DEVNULL,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return "TIMEOUT", f"no exit within {alerts.every_text(p['timeout'])}", None
    except (OSError, subprocess.SubprocessError) as exc:
        return "FAIL", f"could not start ({type(exc).__name__})", None
    if proc.returncode not in p["ok_exit"]:
        return "FAIL", f"exit {proc.returncode}", None
    if "expect" in p and not re.search(p["expect"], (proc.stdout or "") + (proc.stderr or "")):
        return "FAIL", f"exit {proc.returncode}, its output does not match expect", None
    return "OK", f"exit {proc.returncode}", None


def probe_http(p: dict, now: datetime) -> tuple[str, str, float | None]:
    import urllib.error
    import urllib.request

    req = urllib.request.Request(p["url"], method="GET", headers={"User-Agent": "brain-probe"})
    try:
        with urllib.request.urlopen(req, timeout=p["timeout"]) as resp:   # noqa: S310 (the owner's URL, http(s))
            code = resp.status
    except urllib.error.HTTPError as exc:
        code = exc.code
    except TimeoutError:
        return "TIMEOUT", f"no answer within {alerts.every_text(p['timeout'])}", None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, TimeoutError):
            return "TIMEOUT", f"no answer within {alerts.every_text(p['timeout'])}", None
        return "FAIL", f"no answer ({type(reason).__name__})", None
    ok = code in p["ok_status"] if p["ok_status"] else 200 <= code < 400
    return ("OK" if ok else "FAIL"), f"HTTP {code}", None


RUNNERS = {"file-age": probe_file_age, "json-age": probe_json_age, "command": probe_command, "http": probe_http}


# --- a run ---

def _one(p: dict, now: datetime) -> tuple[str, str, float | None]:
    try:
        return RUNNERS[p["kind"]](p, now)
    except Exception as exc:  # a probe never stops the pass: its failure is its result
        return "FAIL", f"the probe failed ({type(exc).__name__})", None


def measure(probes: list[dict], now: datetime | None = None) -> list[dict]:
    """Each probe run in its own thread, waited for its timeout plus :data:`GRACE`: [{name, kind, about, level,
    state, why, age_s}] in the order given."""
    now = now or alerts._now()
    if not probes:
        return []
    pool = ThreadPoolExecutor(max_workers=min(WORKERS, len(probes)), thread_name_prefix="brain-depprobe")
    futures = [(p, pool.submit(_one, p, now)) for p in probes]
    out = []
    for p, fut in futures:
        try:
            state, why, age = fut.result(timeout=p["timeout"] + GRACE)
        except FutureTimeout:
            state, why, age = "TIMEOUT", f"no result within {alerts.every_text(p['timeout'])}", None
        row = {"name": p["name"], "kind": p["kind"], "about": p["about"], "level": p["level"], "state": state,
               "why": why}
        if age is not None:
            row["age_s"] = round(age, 1)
        out.append(row)
    pool.shutdown(wait=False, cancel_futures=True)
    return out


def state_file() -> Path:
    return paths.brain_home() / FILE / "state.json"


def _shape(data: dict) -> str:
    bad = sorted(k for k, r in data.items() if not isinstance(r, dict))
    return f"{', '.join(bad[:3])} not an object" if bad else ""


_LATEST: dict = {}   # the last run of this process, by state file: read back even when it could not be saved


def run(cfg: config.Config | None = None, *, host: str | None = None, now: datetime | None = None,
        save: bool = True) -> dict:
    """This machine's probes run now and recorded: {host, at, probes: [rows with last_ok and since], errors,
    saved}. Nothing is written when no probe runs here and none was recorded."""
    now = now or alerts._now()
    host = host or timing.host()
    probes, errors = declared(cfg)
    here = mine(probes, host)
    loaded = stateio.load(state_file(), known=STATE_V, check=_shape, aside=save)
    prev = {k: v for k, v in loaded.data.items() if not k.startswith("_")}
    at = alerts._iso(now)
    rows = []
    for r in measure(here, now):
        p = prev.get(r["name"]) or {}
        r["at"] = at
        r["last_ok"] = at if r["state"] == "OK" else p.get("last_ok") or ""
        r["since"] = p.get("since") if p.get("state") == r["state"] and p.get("since") else at
        rows.append(r)
    data = {"host": host, "at": at, "probes": rows, "errors": errors, "saved": False}
    if save and (rows or prev):
        record = {r["name"]: {k: v for k, v in r.items() if k != "name"} for r in rows}
        record["_run"] = {"at": at, "host": host}
        try:
            stateio.save(loaded, record)
            data["saved"] = True
        except (stateio.StateError, OSError) as exc:
            data["errors"] = [*errors, f"not recorded: {exc}"]
    _LATEST[str(state_file())] = data
    return data


def last() -> dict:
    """The last run's results on this machine (this process's own run first, else $BRAIN_HOME/probes/state.json):
    {host, at, probes, errors}; probes [] when none ever ran here."""
    mem = _LATEST.get(str(state_file()))
    if mem is not None:
        return mem
    st = stateio.load(state_file(), known=STATE_V, check=_shape, aside=False)
    meta = st.data.get("_run") if isinstance(st.data.get("_run"), dict) else {}
    rows = [{"name": k, **v} for k, v in sorted(st.data.items()) if not k.startswith("_") and isinstance(v, dict)
            and v.get("state") in STATES]
    return {"host": meta.get("host") or "", "at": meta.get("at") or "", "probes": rows, "errors": [], "saved": True}


# --- the views ---

def _bad(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r.get("state") != "OK"]


def _since_text(r: dict) -> str:
    last_ok = r.get("last_ok")
    return f"last OK {alerts._short(alerts._ts(last_ok))}" if alerts._ts(last_ok) else "never OK here"


def message(r: dict) -> str:
    """An alert's message: the probe, its state and why, what relies on it, its last OK."""
    return (f"dependency {r['name']} {r['state']}: {r.get('why') or ''}" + (f" ({r['about']})" if r.get("about")
                                                                           else "")
            + f"; {_since_text(r)}; brain probes")


def status_line(d: dict) -> str:
    """brain status's probes row (and the cockpit's health line)."""
    rows = d.get("probes") or []
    errs = d.get("errors") or []
    if not rows:
        return "none run on this machine" + (f"; {len(errs)} bad declaration(s): brain config --check" if errs else "")
    bad = _bad(rows)
    line = f"{len(rows) - len(bad)} of {len(rows)} OK" + "".join(
        f"; {r['name']} {r['state']} ({r.get('why')}; {_since_text(r)})" for r in bad)
    return line + (f"; run {alerts._short(alerts._ts(d['at']))}" if alerts._ts(d.get("at")) else "") + (
        f"; {len(errs)} bad declaration(s): brain config --check" if errs else "")


def render(d: dict) -> list[str]:
    """brain probes's text."""
    rows = d.get("probes") or []
    head = f"dependency probes on {d.get('host') or timing.host()}"
    lines = [head + (f", run {alerts._short(alerts._ts(d['at']))}" if alerts._ts(d.get("at")) else "")]
    if not rows:
        lines.append("  none declared for this machine (config.json probes; brain probes --kinds)")
    for r in rows:
        lines.append(f"  {r['state']:<8} {r['name']:<24} {r['kind']:<9} {r.get('why') or ''}"
                     + ("" if r["state"] == "OK" else f"; {_since_text(r)}")
                     + (f"  ({r['about']})" if r.get("about") else ""))
    lines += [f"  bad declaration: {e}" for e in d.get("errors") or []]
    return lines


def listing(cfg: config.Config | None = None) -> dict:
    """Every declared probe, whichever machine runs it: what brain probes --list prints (no target: a path, a URL or
    an argv stays in config.json)."""
    probes, errors = declared(cfg)
    here = {p["name"] for p in mine(probes)}
    return {"host": timing.host(), "probes": [{"name": p["name"], "kind": p["kind"], "level": p["level"],
                                               "machines": p["machines"], "about": p["about"],
                                               "here": p["name"] in here} for p in probes], "errors": errors}
