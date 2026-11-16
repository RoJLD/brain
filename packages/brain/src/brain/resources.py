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
              to one live session of the desktop app (the app's session files, read through the closed list of keys,
              ``APP_KEYS``) when it is the only CLI without a session flag in that folder and no command line already
              names that session (:func:`tie_all`); else the session is unknown, said so. A nested CLI (a hook's
              ``claude -p``) is its own row, outside its parent's tree; a session's tokens count once per project. The CLI's tokens and cost today come from the token
              ledger (``<BRAIN_HOME>/usage/sessions.json``, as the last scan left it: brain usage or brain status scan).
  brain       the brain commands running (``brain tui``, a hook, a suite run by ``brain test``), each once: the
              launcher and the venv's Python under it are one row, the top one holding the tree.
  suites      the pytest runs (an xdist worker counted with its run).
  containers  ``docker stats --no-stream`` with a bounded timeout, each container tied to the stack that declares it
              (brain.stacks: its ``index.container``; the Compose project of a stack whose start runs ``docker compose``,
              from ``-p``, its ``-f`` files' ``name:`` or its folder), else said undeclared. Docker absent,
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
calls it every ``BAND_S`` seconds; its drives are BRAIN_HOME's, Temp's and the registered projects' (the registry read
once per sampler). The band's and the detail's workers share one sampler: the counters are read and swapped under a
lock, and a counter that went down counts as a wrap only from its modulus' top quarter. The detail's read is asked
to stop between its steps (:class:`Cancelled`), its docker stats bounded to ``TUI_DOCKER_TIMEOUT``. psutil
(the ``tui`` extra) is used when installed; without it the machine's totals
come from the standard library (GetSystemTimes, GetPerformanceInfo, GetIfTable on Windows; /proc on Linux), and the
process rows are said to need psutil.

The Brain's own token overhead (rules, hooks, skills and resume packs injected into sessions, RES-2) waits on the rule
usage measure: :data:`OVERHEAD_SOURCES` is its extension point, a list of functions that each return ``{tokens,
share_pct, source}`` or None; empty, the sample says it is pending.

brain.resources_view puts the sample in words: the band's and ``brain resources``' text.

brain.resources_containers reads docker stats. Side effects are module functions the tests replace: ``_psutil``, ``_cpu_times``,
``_net_counters``, ``_memory``, ``_disk_usage``, ``_size``, ``_now``.
"""

from __future__ import annotations

import collections
import json
import os
import re
import shutil
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath

from . import classes, governor, paths, probe, quota, sessions, usage
from .resources_containers import DOCKER_TIMEOUT, containers

V = 1
WARN, CRITICAL = 85.0, 95.0
BAND_S = 3.0                   # the cockpit's band: read every 3 s (RES-1: 2 to 5 s)
HISTORY = int(3600 / BAND_S)   # the last hour of band readings, kept in memory for the sparklines of the tab to come
PRIME_S = 0.5                  # a one-shot sample (the CLI) reads the counters twice, this far apart
WRAP_TOP = 0.75                # a counter that went down wrapped only when its old value was in its modulus' top quarter
WALK_BUDGET = {"stores": 2.0, "transcripts": 1.0, "temp": 1.0}   # seconds each walk may take
APP_KEYS = ("sessionId", "cliSessionId", "cwd", "title", "isArchived", "lastActivityAt")   # a closed list (classes)
LOOPBACK = re.compile(r"^(lo\d*|loopback.*)$", re.I)
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
STEMS = ("claude", "node", "brain", "python", "python3", "pythonw", "py", "pytest")   # the names worth a look
DESKTOP_MARKS = ("windowsapps", "anthropicclaude", ".app/contents/macos/claude")
PENDING_OVERHEAD = ("the Brain's own token overhead (rules, hooks, skills, resume packs injected into sessions) waits "
                    "on the rule usage measure (wi-brain-rule-usage)")

OVERHEAD_SOURCES: list = []   # functions () -> {tokens, share_pct, source} | None: the overhead's extension point
_MEMORY_TOTAL: dict = {}      # macOS without psutil: the total read once (sysctl), never on each band


class Cancelled(Exception):
    """A sample stopped between two steps (the cockpit's detail closed, the cockpit quit)."""


# --- side effects, replaced by fakes in the tests -----------------------------------------------------------------

def _psutil():
    """psutil when installed (the tui extra), else None."""
    try:
        import psutil
    except ImportError:
        return None
    return psutil


_disk_usage = shutil.disk_usage
_size = probe._size


def _now() -> datetime:
    return datetime.now(timezone.utc)


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


def _memory(ps=None) -> dict:
    """{committed_pct, commit_total, commit_limit, total, available, nonpaged}: Windows' GetPerformanceInfo (the
    governor's reader), else psutil's virtual_memory, else /proc/meminfo (macOS without psutil: the total read once,
    never a program per band); a measure not readable is None."""
    perf = governor.performance_info()
    if perf:
        return {"committed_pct": round(100.0 * perf["commit_total"] / perf["commit_limit"], 1)
                if perf["commit_limit"] else None, "commit_total": perf["commit_total"],
                "commit_limit": perf["commit_limit"], "total": perf["physical_total"],
                "available": perf["physical_available"], "nonpaged": perf["kernel_nonpaged"]}
    none = {"commit_total": None, "commit_limit": None, "nonpaged": None}
    if ps is not None:
        vm = ps.virtual_memory()
        return {"committed_pct": round(float(vm.percent), 1), "total": int(vm.total),
                "available": int(vm.available), **none}
    info = governor.memory_info()
    if probe._os() == "darwin":
        if "total" not in _MEMORY_TOTAL:
            try:
                _MEMORY_TOTAL["total"] = probe.probe_memory().get("total_bytes") or None
            except (OSError, ValueError):
                _MEMORY_TOTAL["total"] = None
        return {"committed_pct": info.get("committed"), "total": _MEMORY_TOTAL["total"], "available": None, **none}
    try:
        m = probe.probe_memory()   # /proc/meminfo: a file, no program
    except (OSError, ValueError):
        m = {}
    return {"committed_pct": info.get("committed"), "total": m.get("total_bytes") or None,
            "available": m.get("free_bytes"), **none}


# --- small helpers -------------------------------------------------------------------------------------------------

def _delta(old: int, new: int, modulus: int | None) -> int:
    """A counter's growth between two readings: a fall is a wrap only for a counter with a modulus whose old value
    was in its top quarter (``WRAP_TOP``); any other fall (an adapter reset, readings out of order) counts 0."""
    d = new - old
    if d >= 0:
        return d
    return d + modulus if modulus and old >= modulus * WRAP_TOP else 0


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
        self._drives: list | None = None     # the registered projects' roots, read once (the band's drives)
        self._lock = threading.Lock()        # the band's worker and the detail's share the counters
        self.history: collections.deque = collections.deque(maxlen=HISTORY)

    # the counters: a rate needs two readings

    def cpu(self) -> float | None:
        with self._lock:   # read and swap together: two workers never pair a reading with a later one's
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
        with self._lock:   # read and swap together, as cpu()
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
            if old:
                down += _delta(old[0], rx, modulus)
                up += _delta(old[1], tx, modulus)
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
            st = usage.ledger()   # read only: a broken file is not set aside from here
            why = (f"written by a newer brain (v {st.v}, this engine reads v {st.known}): brain update"
                   if st.status == "newer" else st.why if st.status == "unreadable" else "")
            if why:
                return {"day": day, "tokens": None, "usd": None, "sessions": 0, "by_session": {}, "ledger_at": None,
                        "why": f"token ledger not read: {why}"}
            self._ledger = (sig, today_of(st.data.get("rows") or {}, day), day)
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
        mem = _memory(self.ps)
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

    def drives(self, projs: list | None = None) -> list[tuple[str, Path]]:
        """The registered projects' roots on this machine, labelled; read from the registry once per sampler."""
        if self._drives is None or projs is not None:
            self._drives = [(f"project:{p.name}", p.root) for p in (_projects(self.root) if projs is None else projs)
                            if p.root.is_dir()]
        return self._drives

    def band(self) -> dict:
        """The cockpit's band: no process list, no program started, no folder walked. Its cost in ms is in it."""
        t0 = time.perf_counter()
        m = self.machine(self.drives())
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

    def sample(self, docker: bool = True, walks: bool = True, prime: bool = True, stop=None,
               docker_timeout: float = DOCKER_TIMEOUT) -> dict:
        """The full sample: the machine, the sessions, the brain processes, the suites, the containers, the stores,
        the projects, the tokens and the quota. ``prime``: read the counters twice, ``PRIME_S`` apart, when this
        sampler has no earlier reading (a one-shot command); ``docker`` and ``walks`` off: what --quick leaves out;
        ``stop``: a function asked between the steps, :class:`Cancelled` raised when it says true."""
        def step():
            if stop and stop():
                raise Cancelled()
        t0 = time.perf_counter()
        projs = _projects(self.root)
        if prime:
            self._prime_if_new()
        step()
        m = self.machine(self.drives(projs))
        tok = self.tokens_today()
        q = self.quota()
        procs = self.processes()
        step()
        sess = self.sessions(procs, tok, _placer(projs))
        step()
        skipped = {"state": "skipped", "why": "--quick", "rows": []}
        cont = containers(_stacks(self.root), docker_timeout) if docker else skipped
        step()
        stores_ = stores(stop) if walks else dict(skipped)
        step()
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
        kinds = {pid: k for pid, t in table.items() if (k := self._kind(t))}
        if prime_only:
            return {}
        clis = {pid for pid, (kind, _) in kinds.items() if kind == "cli"}
        found: dict[str, list[dict]] = {"cli": [], "brain": [], "suite": []}
        for pid, (kind, detail) in kinds.items():
            found[kind].append(self._row(pid, kind, detail, table, children, clis))
        rows = found["cli"]
        brain_, suites = (_tops(found[k]) for k in ("brain", "suite"))
        live = {r["pid"] for r in rows + brain_ + suites}
        self._proc = {k: v for k, v in self._proc.items() if k[0] in live}
        return {"available": True, "why": "", "rows": rows, "brain": brain_, "suites": suites,
                "counted": len(table)}

    def _kind(self, t: dict) -> tuple[str, dict] | None:
        """(kind, detail) of a process of the Brain's (a CLI, a brain command, a suite), else None."""
        stem = _stem(t["name"])
        detail = self._detail(t["p"]) if stem in STEMS else None
        kind = kind_of(stem, detail["exe"], detail["cmdline"]) if detail else ""
        return (kind, detail) if kind else None

    def _row(self, pid: int, kind: str, detail: dict, table: dict, children: dict, clis: set) -> dict:
        """A process's row with its tree's memory: a nested CLI (a hook's ``claude -p``) is its own row, never in its
        parent's tree."""
        t = table[pid]
        row = {"pid": pid, "ppid": t["ppid"], "kind": kind, **{k: detail[k] for k in ("rss", "private", "cpu_pct")}}
        tree = list(_descendants(pid, children, clis))
        row["tree_bytes"] = (detail["rss"] or 0) + sum(self._rss(table[c]["p"]) for c in tree)
        if kind == "brain":
            row["what"] = brain_what(detail["cmdline"])
        elif kind == "cli":
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
        clis = procs.get("rows", [])
        rows = [live_row(r, tied, by_cli, tok["by_session"], place) for r, tied in zip(
            clis, tie_all(clis, by_cli, by_cwd), strict=True)]
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


def live_row(r: dict, tied: tuple[str, str], by_cli: dict, spent_by: dict, place) -> dict:
    """A live CLI's row: tied to its session (:func:`tie_all`), its memory and CPU, its tokens today."""
    cli, how = tied
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


def _descendants(pid: int, children: dict[int, list[int]], stop: set | None = None):
    """The processes under ``pid``; one in ``stop`` (a nested CLI) is left out with its own tree."""
    stack, seen = list(children.get(pid, [])), {pid}
    while stack:
        c = stack.pop()
        if c in seen or (stop and c in stop):
            continue
        seen.add(c)
        yield c
        stack.extend(children.get(c, []))


def _tops(rows: list[dict]) -> list[dict]:
    """The rows whose parent is not a row of the same list: a brain command's launcher and the venv's python under it
    (Windows), a pytest run and a worker that is pytest too, counted once, the top holding the tree."""
    pids = {r["pid"] for r in rows}
    return [r for r in rows if r["ppid"] not in pids]


def _cwd(p, ps) -> str:
    try:
        return str(p.cwd() or "")
    except (ps.Error, OSError):
        return ""


def _stem(path: str) -> str:
    """A program's name without its folder and suffix, lowercase, whatever the separator: a Windows path
    (``C:\\v\\brain.exe``) reads the same on Linux as on Windows (PureWindowsPath splits on both)."""
    return PureWindowsPath(str(path)).stem.lower()


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
    if any(_stem(a) == "pytest" for a in head) or ("-m" in low[:3] and "pytest" in head):
        return "suite"
    if ("-m" in low[:3] and "brain" in head) or (len(low) > 1 and _stem(low[1]) == "brain"):
        return "brain"
    return ""


def brain_what(cmd: list[str]) -> str:
    """The brain subcommand a process runs (``tui``, ``usage``...), else ''."""
    from .commands import _names
    known = {n.replace("_", "-") for n in _names()} | {"doctor", "lessons"}
    low = [a.lower() for a in cmd]
    for i, a in enumerate(low):
        if _stem(a) == "brain" or (a == "brain" and i and low[i - 1] == "-m"):
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


def tie_all(rows: list[dict], by_cli: dict, by_cwd: dict) -> list[tuple[str, str]]:
    """Each live CLI's (session id, how): its command line first; a CLI without one by its folder only when it is the
    one such CLI in that folder and no command line already names that folder's session; else ('', why not)."""
    def flags(r):
        return r.get("cmd_session") or {}
    taken = {flags(r)["id"] for r in rows if flags(r).get("id")}
    flagless = collections.Counter(_norm(r["cwd"]) for r in rows if r.get("cwd") and not flags(r).get("id"))
    out = []
    for r in rows:
        n = flagless[_norm(r.get("cwd") or "")] if r.get("cwd") and not flags(r).get("id") else 0
        cli, how = ("", f"folder held by {n} CLIs") if n > 1 else tie(flags(r), r.get("cwd"), by_cli, by_cwd)
        if how == "folder" and cli in taken:
            cli, how = "", "folder's session already tied by another CLI's command line"
        out.append((cli, how))
    return out


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


# --- the stores ----------------------------------------------------------------------------------------------------

def stores(stop=None) -> dict:
    """{state, rows: [{name, path, bytes, complete}], left_out: [name]}: each top-level entry of BRAIN_HOME the read
    gate lets the engine walk (:func:`brain.classes.home_sizes`: a secret store is never entered nor a link followed,
    so it has no row), the transcripts and the temporary folder, each walk bounded in time (:data:`WALK_BUDGET`): when
    the stores' budget runs out, the entry being walked is said incomplete and the later ones are named in
    ``left_out``; ``stop`` asked between two entries (:class:`Cancelled`)."""
    home = paths.brain_home()

    def between():
        if stop and stop():
            raise Cancelled()
    between()
    sizes, cut, left = (classes.home_sizes(time.monotonic() + WALK_BUDGET["stores"], between) if home.is_dir()
                        else ({}, None, []))
    rows = sorted(({"name": n, "path": str(home / n), "bytes": b, "complete": n != cut} for n, b in sizes.items()),
                  key=lambda r: -r["bytes"])
    for name, root in (("transcripts", paths.projects_dir()), ("temp", Path(tempfile.gettempdir()))):
        if stop and stop():
            raise Cancelled()
        if root.is_dir():
            n, done = _size(root, WALK_BUDGET[name])
            rows.append({"name": name, "path": str(root), "bytes": n, "complete": done})
    return {"state": "ok", "home": str(home), "rows": rows, "left_out": left}


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
    counted: set[str] = set()   # a session's tokens once, however many rows name it
    for s in sess:
        r = row(s["project"])
        r["sessions_live"] += 1 if s["live"] else 0
        r["tree_bytes"] += s.get("tree_bytes") or 0
        r["cpu_pct"] = round(r["cpu_pct"] + (s.get("cpu_pct") or 0.0), 1)
        if s.get("cli") and s["cli"] in counted:
            continue
        counted.add(s.get("cli") or "")
        r["sessions_today"] += 1 if s.get("tokens_today") else 0
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
