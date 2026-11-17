"""A lease lock on one machine: an O_EXCL file under ``<BRAIN_HOME>/locks`` that names its holder and expires
(the merge queue's lock, ``brain ship --run``).

The general lock primitive of the agent locks (an owner session, a TTL, a release, a lock break) is not built yet;
this is the small lock the merge queue needs, shaped so that item can generalize it (the same file, the same holder
record, the same break rules) instead of writing a second one:

- **take**: ``<BRAIN_HOME>/locks/<name>.lock`` created with ``O_CREAT | O_EXCL``, so of two takers exactly one wins;
  it holds the holder as JSON: ``pid``, ``pstart`` (when that process started, so that a pid the OS gave to another
  process since is told apart), ``session`` (the agent session's id, when one runs it), ``host``, ``started``,
  ``expires`` (now plus the TTL) and a random ``token`` that says which taker it is;
- **held**: a second taker gets :class:`Held` with the holder's record, after waiting ``wait`` seconds at most;
- **stale**: a holder on this host is judged by its process alone: the lock is broken when its pid is gone or is now
  another process (its start differs), and never on its TTL while it runs (a long step does not lose the lock); a
  holder on another host is judged by its TTL alone, its pid being out of reach. A file left empty or unreadable by
  a taker killed between its create and its write is stale after :data:`GRACE` seconds. The break renames the file
  aside first and checks it moved the stale record it read; one that moved a fresh lock puts it back without ever
  overwriting a lock taken since (a hard link on POSIX, a rename that refuses an existing name on Windows), and keeps
  it aside when it cannot;
- **renew**: the holder pushes ``expires`` forward; :meth:`Lock.heartbeat` renews from a thread every quarter of the
  TTL until the release, so a step longer than the TTL keeps the lock on another host's clock too;
- **release**: in a ``finally`` (the context manager), and only the holder's own file (its token): a lock broken and
  taken by another since is left alone. A release that cannot remove the file (Windows refuses to delete a file
  another process holds open) is retried, then said; the same process then reads that file as released.

Windows: a file another process holds open cannot be deleted nor replaced (a sharing violation, PermissionError);
each unlink, rename and replace here is retried for a second before it counts as failed.

Never on a file system where the lock cannot be trusted: the O_EXCL create is not atomic on every network file
system, and another machine's pid cannot be checked. A BRAIN_HOME on a UNC path, a Windows remote drive or a
network, WSL or FUSE share mount (Linux's /proc/mounts) is refused (:class:`LockError`); macOS's mounts are not read.

Standard library only.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

GRACE = 30.0          # seconds an empty or unreadable lock file is given before it is stale (a taker mid-write)
POLL = 0.2            # seconds between two tries while waiting
RETRIES = 20          # tries of an unlink, rename or replace that Windows refuses for a sharing violation
RETRY_PAUSE = 0.05
SESSION_ENV = ("CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID")   # the agent session's id (as brain.answers reads it)
_UNTRUSTED_FS = {"nfs", "nfs4", "cifs", "smb3", "smbfs", "sshfs", "fuse.sshfs", "afs", "9p", "davfs", "fuse.rclone",
                 "drvfs", "v9fs", "fuse"}
_RELEASED: set[str] = set()   # the tokens this process released whose file could not be removed


class LockError(Exception):
    """The lock cannot be taken here at all (an untrusted file system, a folder that cannot be written)."""


class Held(Exception):
    """Another holder has the lock; ``holder`` is its record (maybe empty)."""

    def __init__(self, name: str, holder: dict):
        self.name, self.holder = name, holder
        super().__init__(f"the lock {name} is held by {describe(holder)}")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse(s: object) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def host() -> str:
    from . import timing  # BRAIN_HOST, else the machine's name
    return timing.host()


def session() -> str:
    return next((os.environ[v] for v in SESSION_ENV if os.environ.get(v)), "")


def describe(holder: dict) -> str:
    if not holder:
        return "an unknown holder (the lock file is empty or unreadable)"
    parts = [f"pid {holder.get('pid', '?')} on {holder.get('host') or '?'}"]
    if holder.get("session"):
        parts.append(f"session {holder['session']}")
    if holder.get("started"):
        parts.append(f"since {holder['started']}")
    if holder.get("expires"):
        parts.append(f"until {holder['expires']}")
    return ", ".join(parts)


def retry(fn, *args):
    """``fn(*args)``, tried again for about a second while Windows refuses it for a sharing violation."""
    for i in range(RETRIES):
        try:
            return fn(*args)
        except PermissionError:
            if i == RETRIES - 1:
                raise
            time.sleep(RETRY_PAUSE)
    return None


def _win_process(pid: int):
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    return ctypes, wintypes, k32, k32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION


def proc_start(pid: int) -> str:
    """When the process ``pid`` started, as the OS counts it ('' when it cannot be read): Windows' creation time,
    Linux's start in clock ticks since boot."""
    if pid <= 0:
        return ""
    if os.name == "nt":
        try:
            ctypes, wintypes, k32, h = _win_process(pid)
        except (AttributeError, OSError):
            return ""
        if not h:
            return ""
        try:
            times = [wintypes.FILETIME() for _ in range(4)]
            if not k32.GetProcessTimes(h, *(ctypes.byref(t) for t in times)):
                return ""
            return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
        finally:
            k32.CloseHandle(h)
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    fields = stat.rsplit(")", 1)[-1].split()
    return fields[19] if len(fields) > 19 else ""   # field 22 of the whole line: starttime


def pid_alive(pid: int, start: str = "") -> bool:
    """Whether the process ``pid`` runs on this machine and, when ``start`` is given and the OS tells it, is the one
    that started then (a pid reused since is gone). True when it cannot be told: a lock is never broken on a doubt."""
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            ctypes, wintypes, k32, h = _win_process(pid)
        except (AttributeError, OSError):
            return True
        if not h:
            return ctypes.get_last_error() == 5   # access denied: it runs, as another user
        try:
            code = wintypes.DWORD()
            if k32.GetExitCodeProcess(h, ctypes.byref(code)) and code.value != 259:   # STILL_ACTIVE
                return False
        finally:
            k32.CloseHandle(h)
    else:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except (PermissionError, OSError):
            pass
    now = proc_start(pid) if start else ""
    return not (start and now and now != str(start))


def _unescape(field: str) -> str:
    """A /proc/mounts field with its octal escapes (``\\040`` for a space) decoded."""
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), field)


def _mount_fs(path: Path) -> str:
    """The file system type of the mount that holds ``path`` (Linux's /proc/mounts), '' when unknown."""
    try:
        rows = Path("/proc/mounts").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    best, fs = "", ""
    p = str(path)
    for row in rows:
        f = row.split()
        if len(f) < 3:
            continue
        point = _unescape(f[1])
        if (p == point or p.startswith(point.rstrip("/") + "/")) and len(point) >= len(best):
            best, fs = point, f[2]
    return fs


def on_network(path: Path) -> bool:
    """Whether ``path`` is on a file system where the lock cannot be trusted: a UNC path, a Windows remote drive, a
    network, WSL or FUSE share mount."""
    s = str(path)
    if s.startswith(("\\\\", "//")):
        return True
    if os.name == "nt":
        drive = os.path.splitdrive(os.path.abspath(s))[0]
        if not drive:
            return False
        try:
            import ctypes
            return ctypes.windll.kernel32.GetDriveTypeW(drive + "\\") == 4   # DRIVE_REMOTE
        except (AttributeError, OSError):
            return False
    if sys.platform.startswith("linux"):
        fs = _mount_fs(Path(os.path.abspath(s)))
        return fs in _UNTRUSTED_FS or fs.startswith("fuse.")
    return False


class Lock:
    """The lock ``name`` under ``folder`` (default ``<BRAIN_HOME>/locks``), held ``ttl`` seconds unless renewed."""

    def __init__(self, name: str, ttl: float, folder: Path | None = None, what: str = ""):
        if folder is None:
            from . import shutdown
            folder = shutdown.locks_dir()
        self.name, self.ttl, self.what = name, float(ttl), what or name
        self.folder = Path(folder)
        self.path = self.folder / f"{name}.lock"
        self.token = ""
        self.broken: dict | None = None   # the stale holder this taker broke, if it broke one
        self.lost = ""                    # why a renewal found the lock no longer this holder's
        self._beat: tuple[threading.Thread, threading.Event] | None = None

    # --- reading ---

    def holder(self) -> dict:
        """The record in the lock file; {} when there is none or it cannot be read."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def stale(self, holder: dict, now: datetime | None = None, file: Path | None = None) -> str:
        """Why the lock held by ``holder`` (read from ``file``, default the lock file) may be broken ('' when it may
        not)."""
        now = now or _now()
        if not holder:
            try:
                age = time.time() - (file or self.path).stat().st_mtime
            except OSError:
                return "gone"
            return f"empty or unreadable for {int(age)} s" if age > GRACE else ""
        if holder.get("token") and holder.get("token") in _RELEASED:
            return "released by this process (its file could not be removed then)"
        pid = holder.get("pid")
        if holder.get("host") == host() and isinstance(pid, int):
            if not pid_alive(pid, str(holder.get("pstart") or "")):
                return f"its pid {pid} is gone"
            return ""   # a live holder here keeps its lock whatever its TTL says
        exp = _parse(holder.get("expires"))
        if exp is None or now > exp:
            return f"its TTL passed ({holder.get('expires') or 'no expiry'})"
        return ""

    # --- taking, renewing, releasing ---

    def _record(self, started: datetime | None = None) -> dict:
        start = started or _now()
        return {"pid": os.getpid(), "pstart": proc_start(os.getpid()), "session": session(), "host": host(),
                "what": self.what, "started": _iso(start), "expires": _iso(_now() + timedelta(seconds=self.ttl)),
                "token": self.token}

    def _create(self) -> bool:
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o644)
        except FileExistsError:
            return False
        except PermissionError:
            if self.path.exists():   # Windows: a file being deleted reads as access denied
                return False
            raise
        try:
            os.write(fd, (json.dumps(self._record()) + "\n").encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        return True

    def _put_back(self, aside: Path) -> bool:
        """The record moved aside put back at the lock's name, never over a lock taken since."""
        try:
            if os.name == "nt":
                retry(os.rename, aside, self.path)   # refuses an existing name
            else:
                os.link(aside, self.path)            # refuses an existing name
                aside.unlink()
        except OSError:
            return False
        return True

    def _break(self, seen: dict) -> bool:
        """The stale lock moved aside, then checked: True when the record moved is the stale one read."""
        aside = self.path.with_name(f"{self.path.name}.broken-{os.getpid()}-{secrets.token_hex(4)}")
        try:
            retry(os.rename, self.path, aside)
        except FileNotFoundError:
            return True    # broken by another meanwhile: try to take it
        except OSError:
            return False
        try:
            moved = json.loads(aside.read_text(encoding="utf-8")) if aside.stat().st_size else {}
        except (OSError, ValueError):
            moved = {}
        if moved != seen and not self.stale(moved if isinstance(moved, dict) else {}, file=aside):
            self._put_back(aside)   # a fresh lock taken since the read; kept aside when it cannot go back
            return False
        with contextlib.suppress(OSError):
            retry(aside.unlink)
        self.broken = seen
        return True

    def acquire(self, wait: float = 0.0) -> Lock:
        """Take the lock, breaking a stale one; :class:`Held` once ``wait`` seconds passed with a live holder."""
        if on_network(self.folder):
            raise LockError(f"{self.folder} is on a file system where the lock {self.name} cannot be trusted (a "
                            "network share, a WSL or FUSE mount): set BRAIN_HOME to a folder on a local disk")
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise LockError(f"{self.folder}: {exc}") from None
        self.token, self.lost = secrets.token_hex(8), ""
        deadline = time.monotonic() + max(0.0, wait)
        while True:
            if self._create():
                return self
            seen = self.holder()
            if self.stale(seen) and self._break(seen):
                continue
            if time.monotonic() >= deadline:
                raise Held(self.name, seen)
            time.sleep(POLL)

    def owned(self) -> bool:
        return bool(self.token) and self.holder().get("token") == self.token

    def renew(self) -> bool:
        """``expires`` pushed to now plus the TTL; False when the lock is no longer this holder's (``lost`` says
        why) or the file could not be replaced."""
        rec = self.holder()
        if not self.token or rec.get("token") != self.token:
            self.lost = self.lost or "the lock file is no longer this holder's (broken and taken by another)"
            return False
        new = {**rec, **self._record(_parse(rec.get("started")))}
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            tmp.write_text(json.dumps(new) + "\n", encoding="utf-8")
            retry(os.replace, tmp, self.path)
        except OSError:
            with contextlib.suppress(OSError):
                tmp.unlink()
            return False
        return True

    def heartbeat(self, interval: float | None = None) -> None:
        """Renew from a thread every ``interval`` seconds (a quarter of the TTL by default) until :meth:`release`."""
        if self._beat is not None:
            return
        stop = threading.Event()
        every = max(0.05, interval if interval is not None else self.ttl / 4)

        def beat():
            while not stop.wait(every):
                if not self.renew() and self.lost:
                    return
        t = threading.Thread(target=beat, name=f"lock-{self.name}", daemon=True)
        self._beat = (t, stop)
        t.start()

    def release(self) -> str:
        """The lock file removed when it is still this holder's: '' when done, else what was left (said)."""
        if self._beat is not None:
            t, stop = self._beat
            stop.set()
            t.join(timeout=5)
            self._beat = None
        left = ""
        if self.owned():
            try:
                retry(self.path.unlink)
            except FileNotFoundError:
                pass
            except OSError as exc:
                _RELEASED.add(self.token)
                left = f"the lock file {self.path} could not be removed ({exc}); this process reads it as released"
        self.token = ""
        return left

    def __enter__(self) -> Lock:
        return self if self.token else self.acquire()

    def __exit__(self, *exc) -> None:
        left = self.release()
        if left:
            print(f"warning: {left}", file=sys.stderr)
