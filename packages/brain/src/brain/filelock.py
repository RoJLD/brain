"""A lease lock on one machine: an O_EXCL file under ``<BRAIN_HOME>/locks`` that names its holder and expires
(the merge queue's lock, ``brain ship --run``).

The general lock primitive of the agent locks (an owner session, a TTL, a release, a lock break) is not built yet;
this is the small lock the merge queue needs, shaped so that item can generalize it (the same file, the same holder
record, the same break rules) instead of writing a second one:

- **take**: ``<BRAIN_HOME>/locks/<name>.lock`` created with ``O_CREAT | O_EXCL``, so of two takers exactly one wins;
  it holds the holder as JSON: ``pid``, ``session`` (the agent session's id, when one runs it), ``host``,
  ``started``, ``expires`` (started plus the TTL) and a random ``token`` that says which taker it is;
- **held**: a second taker gets :class:`Held` with the holder's record, after waiting ``wait`` seconds at most;
- **stale**: the lock is broken when its TTL passed, or when its holder ran on this host and its pid is gone (a crash,
  a kill); a file left empty or unreadable by a taker killed between its create and its write is stale after
  :data:`GRACE` seconds. The break renames the file aside first and checks it moved the stale record it read, so
  two breakers never both take the lock (one that moved a fresh lock puts it back);
- **renew**: the holder pushes ``expires`` forward (a long run renews between its steps, so the TTL is the longest
  step, not the whole run);
- **release**: in a ``finally`` (the context manager), and only the holder's own file (its token): a lock broken and
  taken by another since is left alone.

Never on a network share: the O_EXCL create is not atomic on every network file system, and another machine's pid
cannot be checked; a BRAIN_HOME on a UNC path or a remote drive is refused (:class:`LockError`).

Standard library only.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

GRACE = 30.0          # seconds an empty or unreadable lock file is given before it is stale (a taker mid-write)
POLL = 0.2            # seconds between two tries while waiting
SESSION_ENV = ("CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID")   # the agent session's id (as brain.answers reads it)
_NETWORK_FS = {"nfs", "nfs4", "cifs", "smb3", "smbfs", "sshfs", "fuse.sshfs", "afs", "9p", "davfs", "fuse.rclone"}


class LockError(Exception):
    """The lock cannot be taken here at all (a network share, a folder that cannot be written)."""


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


def pid_alive(pid: int) -> bool:
    """Whether the process ``pid`` runs on this machine (True when it cannot be told: a lock is never broken on a
    doubt about its pid, only on its TTL)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        h = k32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ctypes.get_last_error() == 5   # access denied: it runs, as another user
        try:
            code = wintypes.DWORD()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return True
            return code.value == 259   # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


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
        if len(f) >= 3 and (p == f[1] or p.startswith(f[1].rstrip("/") + "/")) and len(f[1]) >= len(best):
            best, fs = f[1], f[2]
    return fs


def on_network(path: Path) -> bool:
    """Whether ``path`` is on a network share: a UNC path, a Windows remote drive, a network file system mount."""
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
        return _mount_fs(Path(os.path.abspath(s))) in _NETWORK_FS
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
        exp = _parse(holder.get("expires"))
        if exp is None or now > exp:
            return f"its TTL passed ({holder.get('expires') or 'no expiry'})"
        pid = holder.get("pid")
        if holder.get("host") == host() and isinstance(pid, int) and not pid_alive(pid):
            return f"its pid {pid} is gone"
        return ""

    # --- taking, renewing, releasing ---

    def _record(self, started: datetime | None = None) -> dict:
        start = started or _now()
        return {"pid": os.getpid(), "session": session(), "host": host(), "what": self.what,
                "started": _iso(start), "expires": _iso(_now() + timedelta(seconds=self.ttl)), "token": self.token}

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

    def _break(self, seen: dict) -> bool:
        """The stale lock moved aside, then checked: True when the record moved is the stale one read."""
        aside = self.path.with_name(f"{self.path.name}.broken-{os.getpid()}-{secrets.token_hex(4)}")
        try:
            os.rename(self.path, aside)
        except FileNotFoundError:
            return True    # broken by another meanwhile: try to take it
        except OSError:
            return False
        try:
            moved = json.loads(aside.read_text(encoding="utf-8")) if aside.stat().st_size else {}
        except (OSError, ValueError):
            moved = {}
        if moved != seen and not self.stale(moved if isinstance(moved, dict) else {}, file=aside):
            try:   # a fresh lock taken since the read: put back, unless yet another taker holds the name now
                if not self.path.exists():
                    os.rename(aside, self.path)
                    return False
            except OSError:
                pass
        with contextlib.suppress(OSError):
            aside.unlink()
        self.broken = seen
        return True

    def acquire(self, wait: float = 0.0) -> Lock:
        """Take the lock, breaking a stale one; :class:`Held` once ``wait`` seconds passed with a live holder."""
        if on_network(self.folder):
            raise LockError(f"{self.folder} is on a network share: the lock {self.name} is taken on a local disk "
                            "only (set BRAIN_HOME to a local folder)")
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise LockError(f"{self.folder}: {exc}") from None
        self.token = secrets.token_hex(8)
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
        """``expires`` pushed to now plus the TTL; False when the lock is no longer this holder's (broken)."""
        rec = self.holder()
        if not self.token or rec.get("token") != self.token:
            return False
        new = {**rec, **self._record(_parse(rec.get("started")))}
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        try:
            tmp.write_text(json.dumps(new) + "\n", encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            with contextlib.suppress(OSError):
                tmp.unlink()
            return False
        return True

    def release(self) -> None:
        """The lock file removed when it is still this holder's."""
        if self.owned():
            with contextlib.suppress(OSError):
                self.path.unlink()
        self.token = ""

    def __enter__(self) -> Lock:
        return self if self.token else self.acquire()

    def __exit__(self, *exc) -> None:
        self.release()
