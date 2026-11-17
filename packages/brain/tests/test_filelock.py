"""The merge queue's lease lock (brain.filelock): an O_EXCL file under BRAIN_HOME/locks
naming its holder (pid, session, host, started, expires): of two takers one wins, a stale lock (its pid gone, its TTL
passed, an empty file past its grace) is broken, the holder renews it and releases it in a finally, and never on a
network share."""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

import pytest
from brain import filelock

# --- the lock ---------------------------------------------------------------------------------------------------


def test_a_second_merger_is_refused_with_the_holder(tmp_path):
    a = filelock.Lock("ship", 60, tmp_path).acquire()
    with pytest.raises(filelock.Held) as held:
        filelock.Lock("ship", 60, tmp_path).acquire(wait=0.3)
    assert held.value.holder["pid"] == os.getpid() and held.value.holder["host"] == filelock.host()
    assert {"session", "started", "expires", "token"} <= set(held.value.holder)
    a.release()
    assert not (tmp_path / "ship.lock").exists()
    filelock.Lock("ship", 60, tmp_path).acquire().release()


_RACE = """
import sys, time
from pathlib import Path
from brain import filelock
try:
    filelock.Lock("ship", 60, Path(sys.argv[1])).acquire()
except filelock.Held:
    print("held"); sys.exit(0)
print("won"); sys.stdout.flush(); time.sleep(2)
"""


def test_two_mergers_started_together_one_wins(tmp_path):
    procs = [subprocess.Popen([sys.executable, "-c", _RACE, str(tmp_path)], stdout=subprocess.PIPE, text=True)
             for _ in range(2)]
    outs = sorted(p.communicate(timeout=60)[0].strip() for p in procs)
    assert outs == ["held", "won"]


def _dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait(timeout=60)
    return p.pid


def _write_lock(folder: Path, **rec) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    base = {"pid": os.getpid(), "session": "", "host": filelock.host(), "what": "x", "token": "theirs",
            "started": now.isoformat(), "expires": (now + timedelta(hours=1)).isoformat()}
    f = folder / "ship.lock"
    f.write_text(json.dumps({**base, **rec}), encoding="utf-8")
    return f


def test_a_stale_lock_is_broken_when_its_pid_is_gone_or_its_ttl_passed(tmp_path):
    _write_lock(tmp_path, pid=_dead_pid())
    lk = filelock.Lock("ship", 60, tmp_path).acquire()
    assert lk.owned() and lk.broken["token"] == "theirs"
    lk.release()
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    _write_lock(tmp_path, host="another-machine", pid=1, expires=past.isoformat())   # its pid cannot be checked
    lk = filelock.Lock("ship", 60, tmp_path).acquire()
    assert lk.owned() and lk.broken["host"] == "another-machine"
    lk.release()
    _write_lock(tmp_path, host="another-machine", pid=1)   # another machine's, not expired: held
    with pytest.raises(filelock.Held):
        filelock.Lock("ship", 60, tmp_path).acquire()


def test_an_empty_lock_file_is_stale_only_after_its_grace(tmp_path):
    f = tmp_path / "ship.lock"
    f.write_text("", encoding="utf-8")
    with pytest.raises(filelock.Held):
        filelock.Lock("ship", 60, tmp_path).acquire()
    old = datetime.now().timestamp() - filelock.GRACE - 5
    os.utime(f, (old, old))
    filelock.Lock("ship", 60, tmp_path).acquire().release()


def test_renew_pushes_the_ttl_and_release_leaves_a_lock_taken_by_another(tmp_path):
    lk = filelock.Lock("ship", 1, tmp_path).acquire()
    first = lk.holder()["expires"]
    lk.ttl = 600
    started = lk.holder()["started"]
    assert lk.renew() and lk.holder()["expires"] > first and lk.holder()["started"] == started
    _write_lock(tmp_path)   # broken and taken by another since
    assert not lk.renew()
    lk.release()
    assert (tmp_path / "ship.lock").exists()


def test_the_lock_is_released_on_an_exception(tmp_path):
    with pytest.raises(RuntimeError):
        with filelock.Lock("ship", 60, tmp_path):
            assert (tmp_path / "ship.lock").exists()
            raise RuntimeError("boom")
    assert not (tmp_path / "ship.lock").exists()


def test_never_a_lock_on_a_network_share(tmp_path, monkeypatch):
    assert filelock.on_network(Path("\\\\server\\share\\brain")) and filelock.on_network(Path("//server/share"))
    assert not filelock.on_network(tmp_path)
    with pytest.raises(filelock.LockError, match="network share"):
        filelock.Lock("ship", 60, Path("//server/share/locks")).acquire()
    monkeypatch.setattr(filelock, "_mount_fs", lambda p: "nfs4")
    if sys.platform.startswith("linux"):
        assert filelock.on_network(tmp_path)


def test_pid_alive():
    assert filelock.pid_alive(os.getpid()) and not filelock.pid_alive(_dead_pid()) and not filelock.pid_alive(0)


def test_a_live_holder_here_keeps_its_lock_past_its_ttl_and_a_reused_pid_does_not(tmp_path):
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    me = filelock.proc_start(os.getpid())
    _write_lock(tmp_path, expires=past, pstart=me)   # this host, a live pid, its TTL long passed: still held
    with pytest.raises(filelock.Held):
        filelock.Lock("ship", 60, tmp_path).acquire()
    if me:   # the OS tells a process's start: a pid now another process's is gone
        _write_lock(tmp_path, pstart=str(int(me) - 1))
        lk = filelock.Lock("ship", 60, tmp_path).acquire()
        assert lk.owned() and lk.broken["pstart"] == str(int(me) - 1)
        lk.release()


def test_the_record_holds_the_process_start(tmp_path):
    lk = filelock.Lock("ship", 60, tmp_path).acquire()
    try:
        assert lk.holder()["pstart"] == filelock.proc_start(os.getpid())
        assert filelock.pid_alive(os.getpid(), lk.holder()["pstart"])
    finally:
        lk.release()


def test_the_heartbeat_renews_until_the_release(tmp_path):
    lk = filelock.Lock("ship", 0.4, tmp_path).acquire()
    first = lk.holder()["expires"]
    lk.heartbeat(0.05)
    deadline = time.monotonic() + 10
    while lk.holder().get("expires") == first and time.monotonic() < deadline:
        time.sleep(0.05)
    assert lk.holder()["expires"] != first
    assert lk.release() == "" and not (tmp_path / "ship.lock").exists() and lk._beat is None


def test_a_release_windows_refuses_is_retried_then_said_and_read_as_released(tmp_path, monkeypatch):
    lk = filelock.Lock("ship", 60, tmp_path).acquire()
    real = Path.unlink
    refused = [2]

    def unlink(self, *a, **k):
        if self.name == "ship.lock" and refused[0]:
            refused[0] -= 1
            raise PermissionError(32, "in use by another process")
        return real(self, *a, **k)
    monkeypatch.setattr(Path, "unlink", unlink)
    monkeypatch.setattr(filelock, "RETRY_PAUSE", 0.001)
    assert lk.release() == "" and not (tmp_path / "ship.lock").exists()   # retried past two refusals
    lk = filelock.Lock("ship", 60, tmp_path).acquire()
    refused[0] = 10 ** 6
    left = lk.release()
    assert "could not be removed" in left and (tmp_path / "ship.lock").exists()
    refused[0] = 0
    again = filelock.Lock("ship", 60, tmp_path).acquire()   # its own leftover: read as released, taken at once
    assert again.owned()
    again.release()


def test_a_renewal_windows_refuses_once_is_retried(tmp_path, monkeypatch):
    lk = filelock.Lock("ship", 60, tmp_path).acquire()
    real = os.replace
    refused = [1]

    def replace(a, b):
        if refused[0]:
            refused[0] -= 1
            raise PermissionError(32, "in use")
        return real(a, b)
    monkeypatch.setattr(filelock.os, "replace", replace)
    monkeypatch.setattr(filelock, "RETRY_PAUSE", 0.001)
    assert lk.renew() and not lk.lost
    lk.release()


def test_a_breaker_that_moved_a_fresh_lock_puts_it_back_and_never_over_a_newer_one(tmp_path):
    seen = {"pid": _dead_pid(), "host": filelock.host(), "token": "stale"}
    _write_lock(tmp_path, token="fresh")   # taken since the stale record was read
    lk = filelock.Lock("ship", 60, tmp_path)
    lk.token = "mine"
    assert not lk._break(seen) and lk.broken is None
    assert json.loads((tmp_path / "ship.lock").read_text(encoding="utf-8"))["token"] == "fresh"
    aside = tmp_path / "ship.lock.aside"
    aside.write_text(json.dumps({"token": "fresh"}), encoding="utf-8")
    _write_lock(tmp_path, token="newer")
    assert not lk._put_back(aside) and aside.exists()   # a newer lock stands; the moved record stays aside
    assert json.loads((tmp_path / "ship.lock").read_text(encoding="utf-8"))["token"] == "newer"


def test_the_mounts_table_is_decoded_and_wsl_and_fuse_mounts_are_refused(tmp_path, monkeypatch):
    rows = "C:\\134 /mnt/c 9p rw 0 0\n//nas/share /mnt/my\\040share cifs rw 0 0\ndrvfs /mnt/d drvfs rw 0 0\n"
    real = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: rows if self.as_posix() == "/proc/mounts" else
                        real(self, *a, **k))
    assert filelock._mount_fs(PurePosixPath("/mnt/my share/brain")) == "cifs"
    assert filelock._mount_fs(PurePosixPath("/mnt/d/x")) == "drvfs" and filelock._mount_fs(PurePosixPath("/srv/lab")) == ""
    for fs in ("drvfs", "9p", "fuse.sshfs", "fuse.gcsfuse"):
        monkeypatch.setattr(filelock, "_mount_fs", lambda p, fs=fs: fs)
        if sys.platform.startswith("linux"):
            assert filelock.on_network(tmp_path)
    with pytest.raises(filelock.LockError, match="cannot be trusted"):
        filelock.Lock("ship", 60, Path("//server/share/locks")).acquire()
