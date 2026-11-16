"""The merge queue's lease lock (brain.filelock): an O_EXCL file under BRAIN_HOME/locks
naming its holder (pid, session, host, started, expires): of two takers one wins, a stale lock (its pid gone, its TTL
passed, an empty file past its grace) is broken, the holder renews it and releases it in a finally, and never on a
network share."""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


