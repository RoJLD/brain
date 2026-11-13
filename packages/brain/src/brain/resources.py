"""What runs for the Brain costs on this machine, at zero token (wi-brain-resources-view; the owner's answers RES-1 to
RES-4 of 2026-11-02, restated on 2026-11-04; spec cockpit-ux round 2 §4.0.3, the task manager §2-3, the scale study's
gaps 7 and 29): one sampler that serves ``brain resources`` and the cockpit's band.

The machine: its CPU (% busy since the last reading), its memory (Windows: the commit charge in % of the commit
limit, what the governor guards, beside the physical RAM and the kernel's non-paged pool; elsewhere the memory in use),
the free space of the Brain's drives (BRAIN_HOME's, the temporary folder's and the registered projects'), and the
network's throughput up and down. The network is the machine's: psutil gives system-wide counters on Windows, and a
per-process rate would need ETW, not planned until a need shows it (the task manager spec §3).

The Brain's workloads, in the full sample only (``brain resources``, the cockpit's detail):

  sessions    each Claude Code CLI process (psutil), its memory and its process tree's (the MCP servers, the test
              suites it started), tied to its session: the ``--session-id`` or ``--resume`` of its command line (a
              ``--fork-session`` resume names the session it forked from, not its own), else its working folder matched
              to one session of the desktop app (the app's session files, read through the closed list of keys,
              ``APP_KEYS``); else the session is unknown, said so. The CLI's tokens and cost today come from the token
              ledger (``<BRAIN_HOME>/usage/sessions.json``, as the last scan left it: brain usage or brain status scan).
  brain       the brain commands running (``brain tui``, a hook, a suite run by ``brain test``).
  suites      the pytest runs (an xdist worker counted with its run).
  containers  ``docker stats --no-stream`` with a bounded timeout, each container tied to the stack that declares it
              (brain.stacks: its ``index.container``, its Compose project), else said undeclared. Docker absent,
              down, slow or answering garbage is a state, never an error.
  stores      the sizes of BRAIN_HOME's stores, of the transcripts and of the temporary folder, each walk bounded in
              time (an unfinished walk says « at least »).
  projects    the sessions and containers summed per registered project (brain.queue's Placer).

The tokens today (the ledger's UTC day) and the quota (``<BRAIN_HOME>/usage/quota.json``, the last forecast of
brain.quota: the percent now, the pace as a ratio of the pace that would end the window at 100 %, the level) are read
from files, never computed here; the capacity line (scale study gap 7) is the room left in the window in
session-hours, from the same file's conversion and measured session-hour.

Thresholds: WARN at 85 %, CRITICAL at 95 % (CPU, committed memory, each drive's used space); the quota's level is
brain.quota's (its WARN, then 100 % before the reset).

The band (:meth:`Sampler.band`) reads no process list, starts no program and walks no folder: the cockpit's worker
calls it every ``BAND_S`` seconds. psutil (the ``tui`` extra) is used when installed; without it the machine's totals
come from the standard library (GetSystemTimes, GetPerformanceInfo, GetIfTable on Windows; /proc on Linux), and the
process rows are said to need psutil.

The Brain's own token overhead (rules, hooks, skills and resume packs injected into sessions, RES-2) waits on the rule
usage measure: :data:`OVERHEAD_SOURCES` is its extension point, a list of functions that each return ``{tokens,
share_pct, source}`` or None; empty, the sample says it is pending.

brain.resources_view puts the sample in words: the band's and ``brain resources``' text.

Side effects are module functions the tests replace: ``_psutil``, ``_run``, ``_which``, ``_cpu_times``,
``_net_counters``, ``_memory``, ``_disk_usage``, ``_size``, ``_now``.
"""

from __future__ import annotations

import collections
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from . import governor, paths, probe, quota, sessions, usage

V = 1
WARN, CRITICAL = 85.0, 95.0
BAND_S = 3.0                   # the cockpit's band: read every 3 s (RES-1: 2 to 5 s)
HISTORY = int(3600 / BAND_S)   # the last hour of band readings, kept in memory for the sparklines of the tab to come
PRIME_S = 0.5                  # a one-shot sample (the CLI) reads the counters twice, this far apart
DOCKER_TIMEOUT = 8.0           # docker stats --no-stream takes 1 to 3 s with a handful of containers
WALK_BUDGET = {"stores": 2.0, "transcripts": 1.0, "temp": 1.0}   # seconds each walk may take
APP_KEYS = ("sessionId", "cliSessionId", "cwd", "title", "isArchived", "lastActivityAt")   # a closed list (classes)
LOOPBACK = re.compile(r"^(lo\d*|loopback.*)$", re.I)
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
STEMS = ("claude", "node", "brain", "python", "python3", "pythonw", "py", "pytest")   # the names worth a look
DESKTOP_MARKS = ("windowsapps", "anthropicclaude", ".app/contents/macos/claude")
UNITS = {"b": 1, "kb": 1e3, "mb": 1e6, "gb": 1e9, "tb": 1e12, "kib": 2 ** 10, "mib": 2 ** 20, "gib": 2 ** 30,
         "tib": 2 ** 40}
SIZE_RE = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*([kmgt]?i?b)\s*$", re.I)
PENDING_OVERHEAD = ("the Brain's own token overhead (rules, hooks, skills, resume packs injected into sessions) waits "
                    "on the rule usage measure (wi-brain-rule-usage)")

OVERHEAD_SOURCES: list = []   # functions () -> {tokens, share_pct, source} | None: the overhead's extension point


# --- side effects, replaced by fakes in the tests -----------------------------------------------------------------

def _psutil():
    """psutil when installed (the tui extra), else None."""
    try:
        import psutil
    except ImportError:
        return None
    return psutil


_which = shutil.which
_disk_usage = shutil.disk_usage
_size = probe._size


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _run(argv: list[str], timeout: float) -> tuple[str, int | None, str]:
    """(state, exit code, output): state ``ok`` (it ran, whatever its code), ``slow`` (killed at ``timeout``) or
    ``absent`` (it could not start)."""
    try:
        p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return "slow", None, ""
    except (OSError, subprocess.SubprocessError):
        return "absent", None, ""
    return "ok", p.returncode, (p.stdout or "") + (p.stderr or "")


def _cpu_times(ps=None) -> tuple[float, float] | None:
    """(idle, total) CPU seconds since boot, every core summed; None when not readable."""
    if ps is not None:
        t = ps.cpu_times()
        idle = getattr(t, "idle", 0.0) + getattr(t, "iowait", 0.0)
        fields = getattr(t, "_fields", ())
        total = sum(v for k, v in zip(fields, t, strict=False) if k not in ("guest", "guest_nice")) if fields else sum(t)
        return float(idle), float(total)   # Linux's guest times are in user's already
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
            if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
                return None
        except (OSError, AttributeError, ValueError):
            return None

        def secs(ft):
            return ((ft.dwHighDateTime << 32) | ft.dwLowDateTime) / 1e7
        return secs(idle), secs(kernel) + secs(user)   # the kernel's time holds the idle time
    try:
        first = Path("/proc/stat").read_text(encoding="ascii").splitlines()[0].split()
    except (OSError, IndexError):
        return None
    if first[:1] != ["cpu"]:
        return None
    vals = [float(x) for x in first[1:9]]
    return vals[3] + (vals[4] if len(vals) > 4 else 0.0), sum(vals)


def _net_counters(ps=None) -> tuple[dict[str, tuple[int, int]], int | None] | None:
    """({interface: (bytes received, bytes sent)}, the counters' modulus or None), loopback left out; None when not
    readable. Windows without psutil: GetIfTable's 32-bit counters, one row per adapter's hardware address (a filter
    driver repeats its adapter's row)."""
    if ps is not None:
        return ({n: (int(c.bytes_recv), int(c.bytes_sent)) for n, c in ps.net_io_counters(pernic=True).items()
                 if not LOOPBACK.match(n)}, None)
    if os.name == "nt":
        rows = _win_if_table()
        return (rows, 2 ** 32) if rows is not None else None
    try:
        text = Path("/proc/net/dev").read_text(encoding="ascii")
    except OSError:
        return None
    return parse_net_dev(text), None


def parse_net_dev(text: str) -> dict[str, tuple[int, int]]:
    """/proc/net/dev's interfaces: {name: (received, sent)}, loopback left out."""
    out = {}
    for line in text.splitlines():
        name, sep, rest = line.partition(":")
        f = rest.split()
        if not sep or len(f) < 9 or not f[0].isdigit() or LOOPBACK.match(name.strip()):
            continue
        out[name.strip()] = (int(f[0]), int(f[8]))
    return out


def _win_if_table() -> dict[str, tuple[int, int]] | None:
    """GetIfTable's adapters that are up, keyed by hardware address, loopback (type 24) and tunnels without one left
    out; the largest counters of the rows that share an address."""
    try:
        import ctypes
        from ctypes import wintypes
        dw = wintypes.DWORD

        class Row(ctypes.Structure):
            _fields_ = [("name", ctypes.c_wchar * 256), ("index", dw), ("type", dw), ("mtu", dw), ("speed", dw),
                        ("addr_len", dw), ("addr", ctypes.c_ubyte * 8), ("admin", dw), ("oper", dw),
                        ("changed", dw), ("in_octets", dw), ("in_ucast", dw), ("in_nucast", dw),
                        ("in_discards", dw), ("in_errors", dw), ("in_unknown", dw), ("out_octets", dw),
                        ("out_ucast", dw), ("out_nucast", dw), ("out_discards", dw), ("out_errors", dw),
                        ("out_qlen", dw), ("descr_len", dw), ("descr", ctypes.c_ubyte * 256)]
        size = dw(0)
        get = ctypes.windll.iphlpapi.GetIfTable
        get(None, ctypes.byref(size), False)
        buf = ctypes.create_string_buffer(size.value)
        if get(buf, ctypes.byref(size), False) != 0:
            return None
        n = dw.from_buffer(buf).value
        rows = (Row * n).from_buffer(buf, ctypes.sizeof(dw))
    except (OSError, AttributeError, ValueError):
        return None
    out: dict[str, tuple[int, int]] = {}
    for r in rows:
        if r.type == 24 or not r.addr_len or r.oper < 4:   # loopback, no address, not connected or operational
            continue
        key = bytes(r.addr[:r.addr_len]).hex()
        old = out.get(key, (0, 0))
        out[key] = (max(old[0], int(r.in_octets)), max(old[1], int(r.out_octets)))
    return out


def _memory() -> dict:
    """{committed_pct, commit_total, commit_limit, total, available, nonpaged}: Windows' GetPerformanceInfo (the
    governor's reader), else /proc/meminfo; a measure not readable is None."""
    perf = governor.performance_info()
    if perf:
        return {"committed_pct": round(100.0 * perf["commit_total"] / perf["commit_limit"], 1)
                if perf["commit_limit"] else None, "commit_total": perf["commit_total"],
                "commit_limit": perf["commit_limit"], "total": perf["physical_total"],
                "available": perf["physical_available"], "nonpaged": perf["kernel_nonpaged"]}
    info = governor.memory_info()
    try:
        m = probe.probe_memory()
    except (OSError, ValueError):
        m = {}
    return {"committed_pct": info.get("committed"), "commit_total": None, "commit_limit": None,
            "total": m.get("total_bytes") or None, "available": m.get("free_bytes"), "nonpaged": None}


# --- small helpers -------------------------------------------------------------------------------------------------

def level(pct) -> str:
    """``critical`` from CRITICAL %, ``warn`` from WARN %, ``ok`` under, ``unknown`` without a measure."""
    if not isinstance(pct, (int, float)):
        return "unknown"
    return "critical" if pct >= CRITICAL else "warn" if pct >= WARN else "ok"


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def size_text(n) -> str:
    """Bytes in words: ``512 B``, ``1.2 MB``, ``31.3 GB`` (1024-based, as the system's tools show them)."""
    if not isinstance(n, (int, float)):
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return "-"


def rate_text(n) -> str:
    return f"{size_text(n)}/s" if isinstance(n, (int, float)) else "-"


def pct_text(p) -> str:
    return f"{p:.0f} %" if isinstance(p, (int, float)) else "-"


def parse_size(text: str) -> int | None:
    """docker stats' sizes: ``75.63MiB``, ``1.06MB``, ``0B``; None for ``--`` or garbage."""
    m = SIZE_RE.match(text or "")
    return int(float(m.group(1)) * UNITS[m.group(2).lower()]) if m else None


def _pair(text: str) -> tuple[int | None, int | None]:
    a, _, b = (text or "").partition("/")
    return parse_size(a), parse_size(b)


def _pct(text: str) -> float | None:
    try:
        return round(float((text or "").strip().rstrip("%")), 2)
    except ValueError:
        return None


# --- the machine ---------------------------------------------------------------------------------------------------

class Sampler:
    """The machine's counters between two readings, the caches of the files it reads, and the last hour of band
    readings. One per process: the cockpit keeps one for its worker, brain resources makes one."""

    def __init__(self, root: Path | None = None, project: str | None = None, ps=...) -> None:
        self.root, self.project = root, project
        self.ps = _psutil() if ps is ... else ps
        self.cores = (self.ps.cpu_count() if self.ps else None) or os.cpu_count() or 1
        self._cpu: tuple[float, float] | None = None
        self._net: tuple[float, dict, int | None] | None = None
        self._proc: dict[tuple, tuple[float, float]] = {}   # (pid, create_time) -> (wall, cpu seconds)
        self._ledger: tuple | None = None    # (stat, {cli: today's row}, day)
        self._app: dict[str, tuple] = {}     # app session file -> (stat, picked keys)
        self.history: collections.deque = collections.deque(maxlen=HISTORY)

    # the counters: a rate needs two readings

    def cpu(self) -> float | None:
        try:
            now = _cpu_times(self.ps)
        except (OSError, ValueError, AttributeError):
            now = None
        before, self._cpu = self._cpu, now
        if not (now and before) or now[1] <= before[1]:
            return None
        busy = 1.0 - (now[0] - before[0]) / (now[1] - before[1])
        return round(min(max(busy, 0.0), 1.0) * 100, 1)

    def network(self) -> dict:
        """{up_bps, down_bps, source}: the machine's throughput since the last reading (None on the first)."""
        try:
            got = _net_counters(self.ps)
        except (OSError, ValueError, AttributeError):
            got = None
        source = "psutil" if self.ps else "stdlib"
        if got is None:
            self._net = None
            return {"up_bps": None, "down_bps": None, "source": source, "why": "not readable on this system"}
        counters, modulus = got
        t = time.monotonic()
        before, self._net = self._net, (t, counters, modulus)
        if not before or t <= before[0]:
            return {"up_bps": None, "down_bps": None, "source": source}
        down = up = 0
        for name, (rx, tx) in counters.items():
            old = before[1].get(name)
            if not old:
                continue
            for i, new in ((0, rx), (1, tx)):
                d = new - old[i]
                if d < 0:
                    d = d + modulus if modulus else 0   # a 32-bit counter wrapped; else an adapter reset
                if i == 0:
                    down += d
                else:
                    up += d
        dt = t - before[0]
        return {"up_bps": round(up / dt), "down_bps": round(down / dt), "source": source}

    def prime(self) -> None:
        """A first reading of the counters, so the next one gives a rate."""
        self.cpu()
        self.network()

    def _prime_if_new(self) -> None:
        """A one-shot sample's first reading of the machine's and the processes' counters, ``PRIME_S`` before the
        one it gives: a rate needs two (the cockpit's sampler has them from its band)."""
        if self._cpu is None or (self.ps and not self._proc):
            self.prime()
            self.processes(prime_only=True)
            time.sleep(PRIME_S)   # the interval the rates are measured over, not a wait on anything

    # the files: the token ledger and the quota's last forecast

    def tokens_today(self) -> dict:
        """{day, tokens, usd, sessions, by_session: {cli id: {tokens, usd, folder, title}}, ledger_at}: the UTC day's
        tokens and cost in the token ledger as its last scan left it (parsed again only when the file changed)."""
        f = usage.ledger_file()
        day = _now().strftime("%Y-%m-%d")
        try:
            st = f.stat()
            sig = (st.st_size, st.st_mtime_ns)
        except OSError:
            return {"day": day, "tokens": None, "usd": None, "sessions": 0, "by_session": {}, "ledger_at": None,
                    "why": "no token ledger yet (brain usage scans the transcripts)"}
        if not self._ledger or self._ledger[0] != sig or self._ledger[2] != day:
            try:
                rows = usage.load()
            except Exception as exc:   # brain.stateio refuses a newer or broken ledger: said, never raised
                return {"day": day, "tokens": None, "usd": None, "sessions": 0, "by_session": {}, "ledger_at": None,
                        "why": f"token ledger not read: {exc}"}
            self._ledger = (sig, today_of(rows, day), day)
        by = self._ledger[1]
        return {"day": day, "tokens": sum(x["tokens"] for x in by.values()),
                "usd": round(sum(x["usd"] for x in by.values()), 2), "sessions": len(by), "by_session": by,
                "ledger_at": _iso(datetime.fromtimestamp(sig[1] / 1e9, timezone.utc))}

    def quota(self) -> dict:
        """The last forecast brain.quota wrote: {window, pct_now, pace_x, at_reset, level, at, capacity}; ``pace_x``:
        the last 24 h's pace over the pace that would end the window at exactly 100 % (1.0: on the line);
        ``capacity``: the room left in session-hours, and for 20 sessions in hours (scale study gap 7)."""
        fc = quota.load_status()
        if not fc:
            return {"level": "unknown", "why": "no quota forecast yet (brain usage quota)"}
        pct, pace = fc.get("pct_now"), fc.get("pace") or {}
        at_reset = pace.get("at_reset")
        pace_x = None
        if isinstance(pct, (int, float)) and isinstance(at_reset, (int, float)) and pct < 100:
            pace_x = round((at_reset - pct) / (100 - pct), 2)
        lvl = {"room": "ok", "p0p1": "warn", "none": "critical"}.get(str(fc.get("level")), "unknown")
        out = {"window": fc.get("window"), "pct_now": pct, "at_reset": at_reset, "pace_x": pace_x,
               "pct_h": pace.get("pct_h"), "resets": fc.get("resets"), "level": lvl, "at": fc.get("now"),
               "advice": fc.get("advice")}
        conv = fc.get("conversion") if isinstance(fc.get("conversion"), dict) else {}
        sh = fc.get("session_hour") if isinstance(fc.get("session_hour"), dict) else {}
        per_pct, hour = conv.get("usd_per_pct"), sh.get("usd")
        if isinstance(pct, (int, float)) and isinstance(per_pct, (int, float)) and isinstance(hour, (int, float)) \
                and hour > 0:
            room = max(0.0, 100 - pct) * per_pct / hour
            out["capacity"] = {"session_hours": round(room, 1), "for_20": round(room / 20, 1),
                               "session_hour_usd": hour}
        return out

    # the band and the full sample

    def machine(self, drives: list[tuple[str, Path]] | None = None) -> dict:
        mem = _memory()
        disks = self.disks(drives)
        return {"name": probe.machine(), "os": probe._os(), "cores": self.cores, "cpu_pct": self.cpu(),
                "memory": mem, "disks": disks, "network": self.network(),
                "source": "psutil" if self.ps else "stdlib"}

    def disks(self, drives: list[tuple[str, Path]] | None = None) -> list[dict]:
        """The Brain's drives, one row per device: BRAIN_HOME's, the temporary folder's, and ``drives``'."""
        out, seen = [], {}
        for label, p in [("brain_home", paths.brain_home()), ("temp", Path(tempfile.gettempdir())),
                         *(drives or [])]:
            d = probe._existing(Path(p))
            try:
                dev = os.stat(d).st_dev
                if dev in seen:
                    seen[dev]["for"].append(label)
                    continue
                u = _disk_usage(d)
            except OSError:
                continue
            used = round(100.0 * (u.total - u.free) / u.total, 1) if u.total else None
            row = {"for": [label], "path": Path(d).anchor or str(d), "free_bytes": u.free, "total_bytes": u.total,
                   "used_pct": used, "level": level(used)}
            seen[dev] = row
            out.append(row)
        return out

    def band(self) -> dict:
        """The cockpit's band: no process list, no program started, no folder walked. Its cost in ms is in it."""
        t0 = time.perf_counter()
        m = self.machine()
        tok = self.tokens_today()
        q = self.quota()
        worst = max(m["disks"], key=lambda d: d["used_pct"] or 0.0, default=None)
        b = {"at": _iso(_now()), "cpu_pct": m["cpu_pct"], "mem_pct": m["memory"]["committed_pct"],
             "disk_pct": worst["used_pct"] if worst else None, "disk": worst["path"] if worst else None,
             "up_bps": m["network"]["up_bps"], "down_bps": m["network"]["down_bps"],
             "tokens": tok["tokens"], "usd": tok["usd"], "quota_pct": q.get("pct_now"), "pace_x": q.get("pace_x"),
             "quota_level": q["level"], "source": m["source"]}
        b["levels"] = levels(b)
        b["cost_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        self.history.append({k: b[k] for k in ("at", "cpu_pct", "mem_pct", "up_bps", "down_bps")})
        return b

    def sample(self, docker: bool = True, walks: bool = True, prime: bool = True) -> dict:
        """The full sample: the machine, the sessions, the brain processes, the suites, the containers, the stores,
        the projects, the tokens and the quota. ``prime``: read the counters twice, ``PRIME_S`` apart, when this
        sampler has no earlier reading (a one-shot command); ``docker`` and ``walks`` off: what --quick leaves out."""
        t0 = time.perf_counter()
        projs = _projects(self.root)
        if prime:
            self._prime_if_new()
        m = self.machine([(f"project:{p.name}", p.root) for p in projs if p.root.is_dir()])
        tok = self.tokens_today()
        q = self.quota()
        procs = self.processes()
        place = _placer(projs)
        sess = self.sessions(procs, tok, place)
        skipped = {"state": "skipped", "why": "--quick", "rows": []}
        cont = containers(_stacks(self.root)) if docker else skipped
        stores_ = stores() if walks else dict(skipped)
        doc = {"v": V, "at": _iso(_now()), "machine": m, "processes": {k: procs[k] for k in procs if k != "rows"},
               "sessions": sess, "containers": cont, "stores": stores_,
               "tokens": {k: v for k, v in tok.items() if k != "by_session"}, "quota": q, "overhead": overhead()}
        doc["projects"] = by_project(sess, cont)
        doc = scoped(doc, self.project) if self.project else doc
        doc["levels"] = machine_levels(m, q)
        doc["one_more_session_bytes"] = _median([s["tree_bytes"] for s in sess if s.get("tree_bytes")])
        doc["cost_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return doc

    # the processes (psutil)

    def processes(self, prime_only: bool = False) -> dict:
        """{available, why, rows: [{pid, ppid, kind, ...}], brain: [...], suites: [...], counted}: the Claude Code
        CLIs, the brain commands and the pytest runs, with each CLI's process tree (psutil only)."""
        if not self.ps:
            return {"available": False, "why": "the process rows need psutil (pip install brain[tui])", "rows": [],
                    "brain": [], "suites": []}
        table, children = _table(self.ps)
        found: dict[str, list[dict]] = {"cli": [], "brain": [], "suite": []}
        for pid, t in table.items():
            row = self._row(pid, t, table, children)
            if row:
                found[row["kind"]].append(row)
        if prime_only:
            return {}
        rows, brain_, suites = found["cli"], found["brain"], found["suite"]
        runs = {s["pid"] for s in suites}
        suites = [s for s in suites if s["ppid"] not in runs]   # an xdist worker is counted with its run
        live = {r["pid"] for r in rows + brain_ + suites}
        self._proc = {k: v for k, v in self._proc.items() if k[0] in live}
        return {"available": True, "why": "", "rows": rows, "brain": brain_, "suites": suites,
                "counted": len(table)}

    def _row(self, pid: int, t: dict, table: dict, children: dict) -> dict | None:
        """A process of the Brain's (a CLI with its tree, a brain command, a suite with its workers), else None."""
        stem = Path(t["name"]).stem.lower()
        detail = self._detail(t["p"]) if stem in STEMS else None
        kind = kind_of(stem, detail["exe"], detail["cmdline"]) if detail else ""
        if not kind:
            return None
        row = {"pid": pid, "ppid": t["ppid"], "kind": kind, **{k: detail[k] for k in ("rss", "private", "cpu_pct")}}
        if kind == "brain":
            return {**row, "what": brain_what(detail["cmdline"])}
        tree = list(_descendants(pid, children))
        row["tree_bytes"] = (detail["rss"] or 0) + sum(self._rss(table[c]["p"]) for c in tree)
        if kind == "cli":
            row.update(children=len(tree), cwd=_cwd(t["p"], self.ps), cmd_session=session_flags(detail["cmdline"]))
        return row

    def _detail(self, p) -> dict | None:
        ps = self.ps
        try:
            with p.oneshot():
                cmd = p.cmdline() or []
                exe = ""
                try:
                    exe = p.exe() or ""
                except (ps.Error, OSError):
                    pass
                mi = p.memory_info()
                ct = p.cpu_times()
                created = p.create_time()
        except (ps.Error, OSError):
            return None
        key, now, used = (p.pid, created), time.monotonic(), float(ct.user + ct.system)
        before = self._proc.get(key)
        self._proc[key] = (now, used)
        cpu = (round(100.0 * (used - before[1]) / ((now - before[0]) * self.cores), 1)
               if before and now > before[0] else None)
        return {"cmdline": [str(a) for a in cmd], "exe": str(exe), "rss": int(mi.rss),
                "private": int(getattr(mi, "private", 0)) or None, "cpu_pct": cpu}

    def _rss(self, p) -> int:
        try:
            return int(p.memory_info().rss)
        except (self.ps.Error, OSError):
            return 0

    # the sessions: each CLI tied to its session, joined to the ledger's day

    def app_sessions(self) -> list[dict]:
        """The desktop app's sessions on this machine (the closed list ``APP_KEYS``), each file parsed again only when
        it changed."""
        out, fresh = [], {}
        for d in sessions.app_dirs():
            for f in d.glob("local_*.json"):
                try:
                    st = f.stat()
                except OSError:
                    continue
                sig = (st.st_size, st.st_mtime_ns)
                hit = self._app.get(str(f))
                if not hit or hit[0] != sig:
                    try:
                        data = json.loads(f.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        continue
                    if not isinstance(data, dict) or not data.get("sessionId"):
                        continue
                    hit = (sig, {k: data.get(k) for k in APP_KEYS})
                fresh[str(f)] = hit
                out.append(hit[1])
        self._app = fresh
        return out

    def sessions(self, procs: dict, tok: dict, place) -> list[dict]:
        """One row per live CLI, then one per session that spent tokens today without a live CLI here."""
        by_cli, by_cwd = app_index(self.app_sessions())
        rows = [live_row(r, by_cli, by_cwd, tok["by_session"], place) for r in procs.get("rows", [])]
        seen = {r["cli"] for r in rows if r["cli"]}
        rows += [ledger_row(cli, spent, by_cli.get(cli) or {}, place) for cli, spent in tok["by_session"].items()
                 if cli not in seen]
        return sorted(rows, key=lambda r: (not r["live"], -(r["tokens_today"] or 0)))


def app_index(app: list[dict]) -> tuple[dict[str, dict], dict[str, list[dict]]]:
    """The app's sessions by CLI id, and the live ones by folder."""
    by_cli = {str(a.get("cliSessionId") or ""): a for a in app if a.get("cliSessionId")}
    by_cwd: dict[str, list[dict]] = collections.defaultdict(list)
    for a in app:
        if a.get("cwd") and not a.get("isArchived"):
            by_cwd[_norm(a["cwd"])].append(a)
    return by_cli, by_cwd


def live_row(r: dict, by_cli: dict, by_cwd: dict, spent_by: dict, place) -> dict:
    """A live CLI's row: tied to its session (:func:`tie`), its memory and CPU, its tokens today."""
    cli, how = tie(r.get("cmd_session") or {}, r.get("cwd"), by_cli, by_cwd)
    meta = by_cli.get(cli) or {}
    spent = (spent_by.get(cli) or {}) if cli else {}
    folder = r.get("cwd") or meta.get("cwd") or spent.get("folder") or ""
    return {"session": str(meta.get("sessionId") or ""), "cli": cli, "how": how,
            "title": str(meta.get("title") or spent.get("title") or ""), "project": place(folder) if folder else "",
            "pid": r["pid"], "rss": r["rss"], "private": r["private"], "tree_bytes": r["tree_bytes"],
            "children": r["children"], "cpu_pct": r["cpu_pct"], "tokens_today": spent.get("tokens"),
            "usd_today": spent.get("usd"), "live": True}


def ledger_row(cli: str, spent: dict, meta: dict, place) -> dict:
    """A session that spent tokens today without a live CLI on this machine."""
    return {"session": str(meta.get("sessionId") or ""), "cli": cli, "how": "ledger",
            "title": spent.get("title") or str(meta.get("title") or ""),
            "project": place(spent["folder"]) if spent.get("folder") else "", "pid": None, "rss": None,
            "private": None, "tree_bytes": None, "children": None, "cpu_pct": None,
            "tokens_today": spent.get("tokens"), "usd_today": spent.get("usd"), "live": False}


def today_of(rows: dict, day: str) -> dict[str, dict]:
    """{session id: {tokens, usd, folder, title}} of the ledger's rows that spent on ``day``."""
    by = {}
    for r in rows.values():
        b = (r.get("days") or {}).get(day) if isinstance(r, dict) else None
        if isinstance(b, dict):
            by[str(r.get("session_id") or "")] = {"tokens": int(b.get("tokens") or 0),
                                                  "usd": round(float(b.get("cost") or 0.0), 4),
                                                  "folder": str(r.get("folder") or ""), "title": str(r.get("title") or "")}
    return by


def scoped(doc: dict, project: str) -> dict:
    """``--project``: the document's sessions, projects and containers of that project only."""
    cont = doc["containers"]
    return {**doc, "sessions": [s for s in doc["sessions"] if s["project"] == project],
            "projects": [p for p in doc["projects"] if p["project"] == project],
            "containers": {**cont, "rows": [c for c in cont.get("rows", []) if c.get("project") == project]}}


def _table(ps) -> tuple[dict[int, dict], dict[int, list[int]]]:
    """Every process ({pid: {p, ppid, name}}) and each one's children, from one process_iter."""
    table: dict[int, dict] = {}
    for p in ps.process_iter(["pid", "ppid", "name"]):
        info = p.info
        if info.get("pid") is not None:
            table[info["pid"]] = {"p": p, "ppid": info.get("ppid"), "name": str(info.get("name") or "")}
    children: dict[int, list[int]] = collections.defaultdict(list)
    for pid, t in table.items():
        if t["ppid"] in table and t["ppid"] != pid:
            children[t["ppid"]].append(pid)
    return table, children


def _descendants(pid: int, children: dict[int, list[int]]):
    stack, seen = list(children.get(pid, [])), {pid}
    while stack:
        c = stack.pop()
        if c in seen:
            continue
        seen.add(c)
        yield c
        stack.extend(children.get(c, []))


def _cwd(p, ps) -> str:
    try:
        return str(p.cwd() or "")
    except (ps.Error, OSError):
        return ""


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(str(path))) if path else ""


def _median(xs: list) -> int | None:
    xs = sorted(xs)
    return int(xs[len(xs) // 2]) if xs else None


def kind_of(stem: str, exe: str, cmd: list[str]) -> str:
    """``cli`` (a Claude Code CLI: the claude binary, not the desktop app's own processes, or node running
    claude-code), ``brain`` (a brain command), ``suite`` (a pytest run), else ''."""
    low = [a.lower() for a in cmd]
    if stem == "claude":
        where = (exe or (cmd[0] if cmd else "")).replace("\\", "/").lower()
        desktop = any(m in where for m in DESKTOP_MARKS) or any(a.startswith("--type=") for a in low)
        return "" if desktop else "cli"
    if stem == "node":
        return "cli" if any("claude-code" in a.replace("\\", "/") for a in low[1:]) else ""
    return "brain" if stem == "brain" else _python_kind(low)


def _python_kind(low: list[str]) -> str:
    """A Python process: a pytest run (``pytest``, ``-m pytest``) or a brain command (``-m brain``, a brain script),
    else ''."""
    head = low[:4]
    if any(Path(a).stem == "pytest" for a in head) or ("-m" in low[:3] and "pytest" in head):
        return "suite"
    if ("-m" in low[:3] and "brain" in head) or (len(low) > 1 and Path(low[1]).stem == "brain"):
        return "brain"
    return ""


def brain_what(cmd: list[str]) -> str:
    """The brain subcommand a process runs (``tui``, ``usage``...), else ''."""
    from .commands import _names
    known = {n.replace("_", "-") for n in _names()} | {"doctor", "lessons"}
    low = [a.lower() for a in cmd]
    for i, a in enumerate(low):
        if Path(a).stem == "brain" or (a == "brain" and i and low[i - 1] == "-m"):
            return next((x for x in low[i + 1:] if x in known), "")
    return ""


def session_flags(cmd: list[str]) -> dict:
    """The session ids a CLI's command line names: ``{id}`` (--session-id, or --resume without --fork-session) or
    ``{forked_from}`` (--resume with --fork-session)."""
    found: dict[str, str] = {}
    fork = "--fork-session" in cmd
    for i, a in enumerate(cmd):
        name, eq, value = a.partition("=")
        if name in ("--session-id", "--resume", "-r"):
            value = value if eq else (cmd[i + 1] if i + 1 < len(cmd) else "")
            if UUID.match(value):
                key = "id" if name == "--session-id" or not fork else "forked_from"
                found.setdefault(key, value.lower())
    return found


def tie(flags: dict, cwd: str | None, by_cli: dict, by_cwd: dict) -> tuple[str, str]:
    """(the CLI's session id, how it was found): its command line, else its folder when one live app session holds
    it, else ('', why not)."""
    if flags.get("id"):
        return flags["id"], "command line"
    cands = by_cwd.get(_norm(cwd or "")) or []
    if len(cands) == 1 and cands[0].get("cliSessionId"):
        return str(cands[0]["cliSessionId"]), "folder"
    if len(cands) > 1:
        return "", f"folder held by {len(cands)} sessions"
    if flags.get("forked_from"):
        return "", f"forked from {flags['forked_from'][:8]}"
    return "", "unknown" if cwd else "unknown (no folder readable)"


# --- the containers ------------------------------------------------------------------------------------------------

def _compose_project(s) -> str:
    """The Compose project of a stack: its ``-p``, its compose file's ``name:``, else its folder's name."""
    argv = s.start
    for i, a in enumerate(argv):
        if a in ("-p", "--project-name") and i + 1 < len(argv):
            return argv[i + 1].lower()
        if a.startswith("--project-name="):
            return a.split("=", 1)[1].lower()
    for name in ("compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml"):
        f = (s.cwd or Path(".")) / name
        try:
            m = re.search(r"^name:\s*['\"]?([A-Za-z0-9_.-]+)", f.read_text(encoding="utf-8"), re.M)
        except OSError:
            continue
        if m:
            return m.group(1).lower()
    return re.sub(r"[^a-z0-9_-]", "", (s.cwd.name if s.cwd else "").lower())


def owner_of(name: str, stacks_: list) -> tuple[str, str]:
    """(stack, project) that declares the container ``name``: its ``index.container``, a bundle component's
    ``<project>-<service>-N``, a Compose stack's ``<project>-...``; ('', '') when none does."""
    low = name.lower()
    for s in stacks_:
        if str((s.index or {}).get("container") or "").lower() == low:
            return s.name, s.project
    for s in stacks_:
        p = _compose_project(s)
        if s.bundle and re.fullmatch(rf"{re.escape(p)}[-_]{re.escape(s.name)}[-_]\d+", low):
            return s.name, s.project
    for s in stacks_:
        p = _compose_project(s)
        if not s.bundle and p and (low == p or low.startswith((p + "-", p + "_"))):
            return s.name, s.project
    return "", ""


def parse_stats(text: str, stacks_: list | None = None) -> tuple[list[dict], int]:
    """docker stats' ``{{json .}}`` lines: (rows, lines that were not a container's)."""
    rows, bad = [], 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if not isinstance(d, dict) or not isinstance(d.get("Name"), str) or not d.get("Name"):
            bad += 1
            continue
        mem, limit = _pair(str(d.get("MemUsage") or ""))
        rx, tx = _pair(str(d.get("NetIO") or ""))
        rd, wr = _pair(str(d.get("BlockIO") or ""))
        stack, project = owner_of(d["Name"], stacks_ or [])
        pids = str(d.get("PIDs") or "")
        rows.append({"name": d["Name"], "id": str(d.get("ID") or "")[:12], "cpu_pct": _pct(str(d.get("CPUPerc"))),
                     "mem_bytes": mem, "mem_limit_bytes": limit, "mem_pct": _pct(str(d.get("MemPerc"))),
                     "net_rx_bytes": rx, "net_tx_bytes": tx, "block_read_bytes": rd, "block_write_bytes": wr,
                     "pids": int(pids) if pids.isdigit() else None, "stack": stack, "project": project})
    return rows, bad


def containers(stacks_: list | None = None, timeout: float = DOCKER_TIMEOUT) -> dict:
    """{state, why, rows}: ``ok``; ``absent`` (no docker client); ``down`` (the client answers, the engine does
    not); ``slow`` (no answer in ``timeout`` s); ``garbage`` (an answer that holds no container). Never raises."""
    exe = _which("docker")
    if not exe:
        return {"state": "absent", "why": "no docker client on the PATH", "rows": []}
    state, code, out = _run([exe, "stats", "--no-stream", "--format", "{{json .}}"], timeout)
    if state == "slow":
        return {"state": "slow", "why": f"docker stats gave no answer in {timeout:g} s", "rows": []}
    if state == "absent":
        return {"state": "absent", "why": "the docker client could not start", "rows": []}
    if code != 0:
        first = next((ln.strip() for ln in out.splitlines() if ln.strip()), f"exit {code}")
        return {"state": "down", "why": f"the Docker engine does not answer: {first[:200]}", "rows": []}
    rows, bad = parse_stats(out, stacks_)
    if bad and not rows:
        return {"state": "garbage", "why": f"docker stats answered {bad} line(s) that are no container's", "rows": []}
    return {"state": "ok", "why": f"{bad} line(s) skipped" if bad else "", "rows": rows}


# --- the stores ----------------------------------------------------------------------------------------------------

def stores() -> dict:
    """{state, rows: [{name, path, bytes, complete}]}: each top-level entry of BRAIN_HOME (a store), the transcripts
    and the temporary folder, each walk bounded in time (:data:`WALK_BUDGET`)."""
    home = paths.brain_home()
    rows = []
    end = time.monotonic() + WALK_BUDGET["stores"]
    try:
        entries = sorted(home.iterdir()) if home.is_dir() else []
    except OSError:
        entries = []
    for e in entries:
        left = end - time.monotonic()
        try:
            if e.is_dir():
                n, done = _size(e, max(left, 0.0)) if left > 0 else (0, False)
            else:
                n, done = e.stat().st_size, True
        except OSError:
            continue
        rows.append({"name": e.name, "path": str(e), "bytes": n, "complete": done})
    rows.sort(key=lambda r: -r["bytes"])
    for name, root in (("transcripts", paths.projects_dir()), ("temp", Path(tempfile.gettempdir()))):
        if root.is_dir():
            n, done = _size(root, WALK_BUDGET[name])
            rows.append({"name": name, "path": str(root), "bytes": n, "complete": done})
    return {"state": "ok", "home": str(home), "rows": rows}


# --- the projects, the overhead, the levels ------------------------------------------------------------------------

def _projects(root: Path | None) -> list:
    from . import projects
    try:
        return list(projects.load(root).values())
    except Exception:   # a registry error is brain check's to report: the resources go on without projects
        return []


def _placer(projs: list):
    from . import queue
    if not projs:
        return lambda folder: ""
    place = queue.Placer(projs)

    def at(folder: str) -> str:
        try:
            name = place(folder)
        except OSError:
            return ""
        return name or ""
    return at


def _stacks(root: Path | None) -> list:
    from . import stacks
    try:
        return list(stacks.load(root).values())
    except Exception:   # a stacks registry error is brain health's to report
        return []


def by_project(sess: list[dict], cont: dict) -> list[dict]:
    """The sessions and containers summed per project ('' for a folder no project holds)."""
    out: dict[str, dict] = {}

    def row(name: str) -> dict:
        return out.setdefault(name, {"project": name, "sessions_live": 0, "sessions_today": 0, "tree_bytes": 0,
                                     "cpu_pct": 0.0, "tokens_today": 0, "usd_today": 0.0, "containers": 0,
                                     "container_bytes": 0, "container_cpu_pct": 0.0})
    for s in sess:
        r = row(s["project"])
        r["sessions_live"] += 1 if s["live"] else 0
        r["sessions_today"] += 1 if s.get("tokens_today") else 0
        r["tree_bytes"] += s.get("tree_bytes") or 0
        r["cpu_pct"] = round(r["cpu_pct"] + (s.get("cpu_pct") or 0.0), 1)
        r["tokens_today"] += s.get("tokens_today") or 0
        r["usd_today"] = round(r["usd_today"] + (s.get("usd_today") or 0.0), 2)
    for c in cont.get("rows", []):
        r = row(c.get("project") or "")
        r["containers"] += 1
        r["container_bytes"] += c.get("mem_bytes") or 0
        r["container_cpu_pct"] = round(r["container_cpu_pct"] + (c.get("cpu_pct") or 0.0), 2)
    return sorted(out.values(), key=lambda r: (r["project"] == "", -(r["tree_bytes"] + r["container_bytes"])))


def overhead() -> dict:
    """The Brain's own token overhead (RES-2), from :data:`OVERHEAD_SOURCES`; pending while none is plugged."""
    got = []
    for fn in OVERHEAD_SOURCES:
        try:
            r = fn()
        except Exception:   # a source's failure leaves the others
            continue
        if isinstance(r, dict):
            got.append(r)
    if not got:
        return {"state": "pending", "why": PENDING_OVERHEAD}
    return {"state": "ok", "tokens": sum(int(r.get("tokens") or 0) for r in got),
            "share_pct": round(sum(float(r.get("share_pct") or 0.0) for r in got), 1),
            "sources": [str(r.get("source") or "") for r in got]}


def levels(b: dict) -> list[dict]:
    """The band's measures at WARN or CRITICAL, the worst first."""
    out = []
    for what, key, text in (("cpu", "cpu_pct", "CPU"), ("memory", "mem_pct", "committed memory"),
                            ("disk", "disk_pct", f"disk {b.get('disk') or ''}".strip())):
        lv = level(b.get(key))
        if lv in ("warn", "critical"):
            out.append({"what": what, "level": lv, "pct": b[key], "text": f"{text} {pct_text(b[key])}"})
    if b.get("quota_level") in ("warn", "critical"):
        out.append({"what": "quota", "level": b["quota_level"], "pct": b.get("quota_pct"),
                    "text": f"quota {pct_text(b.get('quota_pct'))}, pace {b.get('pace_x')}x"})
    return sorted(out, key=lambda x: x["level"] != "critical")


def machine_levels(m: dict, q: dict) -> list[dict]:
    """The full sample's levels: the CPU, the committed memory, each drive, the quota."""
    out = levels({"cpu_pct": m["cpu_pct"], "mem_pct": m["memory"]["committed_pct"], "disk_pct": None,
                  "quota_level": q.get("level"), "quota_pct": q.get("pct_now"), "pace_x": q.get("pace_x")})
    for d in m["disks"]:
        if d["level"] in ("warn", "critical"):
            out.append({"what": "disk", "level": d["level"], "pct": d["used_pct"],
                        "text": f"disk {d['path']} {pct_text(d['used_pct'])} used"})
    return sorted(out, key=lambda x: x["level"] != "critical")


def worst(b: dict) -> str:
    lv = {x["level"] for x in b.get("levels") or []}
    return "critical" if "critical" in lv else "warn" if "warn" in lv else "ok"
