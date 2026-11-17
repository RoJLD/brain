"""A child process that a test can kill with every process it started, at once.

On Windows the child is created suspended, put in a job object of its own, then resumed: every process it starts
joins that job, and ``TerminateJobObject`` ends them all in one call. A tree walk by parent pid (``taskkill /T``)
kills one process after another from a snapshot, so a parent killed after its child can start a new one first, and
that one, out of the snapshot, survives. On POSIX the child gets a session of its own, killed as a process group.
"""
from __future__ import annotations

import ctypes
import os
import signal
import subprocess
from pathlib import Path

CREATE_SUSPENDED = 0x4
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
PROCESS_TERMINATE, PROCESS_SET_QUOTA, PROCESS_SUSPEND_RESUME = 0x0001, 0x0100, 0x0800


def _win():
    from ctypes import wintypes as w

    class IoCounters(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOps", "WriteOps", "OtherOps", "Read", "Write", "Other")]

    class BasicLimits(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", w.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", w.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", w.DWORD), ("SchedulingClass", w.DWORD)]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    k32.CreateJobObjectW.restype, k32.CreateJobObjectW.argtypes = w.HANDLE, [ctypes.c_void_p, w.LPCWSTR]
    k32.SetInformationJobObject.restype = w.BOOL
    k32.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    k32.OpenProcess.restype, k32.OpenProcess.argtypes = w.HANDLE, [w.DWORD, w.BOOL, w.DWORD]
    k32.AssignProcessToJobObject.restype, k32.AssignProcessToJobObject.argtypes = w.BOOL, [w.HANDLE, w.HANDLE]
    k32.TerminateJobObject.restype, k32.TerminateJobObject.argtypes = w.BOOL, [w.HANDLE, w.UINT]
    k32.CloseHandle.restype, k32.CloseHandle.argtypes = w.BOOL, [w.HANDLE]
    ntdll.NtResumeProcess.restype, ntdll.NtResumeProcess.argtypes = ctypes.c_long, [w.HANDLE]   # as psutil resumes
    return k32, ntdll, ExtendedLimits


class Tree:
    """``subprocess.Popen(argv, **kw)`` as ``.child``; :meth:`kill` ends it and every process it started (on Windows
    also any left when :meth:`close` runs: the job kills on its last handle's close)."""

    def __init__(self, argv: list[str], **kw):
        self.job = None
        if os.name != "nt":
            self.child = subprocess.Popen(argv, start_new_session=True, **kw)
            return
        k32, ntdll, limits = _win()
        job = k32.CreateJobObjectW(None, None)
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            info = limits()
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not k32.SetInformationJobObject(job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info),
                                               ctypes.sizeof(info)):
                raise ctypes.WinError(ctypes.get_last_error())
            # suspended: it starts nothing before it is in the job
            self.child = subprocess.Popen(argv, creationflags=CREATE_SUSPENDED, **kw)
            h = k32.OpenProcess(PROCESS_TERMINATE | PROCESS_SET_QUOTA | PROCESS_SUSPEND_RESUME, False, self.child.pid)
            try:
                if not h or not k32.AssignProcessToJobObject(job, h):
                    err = ctypes.WinError(ctypes.get_last_error())
                    self._reap()
                    raise err
                status = ntdll.NtResumeProcess(h)
                if status != 0:
                    self._reap()
                    raise OSError(f"NtResumeProcess: NTSTATUS {status & 0xFFFFFFFF:#010x}")
            finally:
                if h:
                    k32.CloseHandle(h)
        except BaseException:
            k32.CloseHandle(job)
            raise
        self.job, self._k32 = job, k32

    def _reap(self) -> None:
        self.child.kill()
        self.child.wait(timeout=10)

    def kill(self) -> None:
        """The child and every process it started, then the child waited on (bounded)."""
        if os.name == "nt":
            if self.job is None:
                raise RuntimeError("the tree's job is closed: its processes ended with it")
            if not self._k32.TerminateJobObject(self.job, 1):
                raise ctypes.WinError(ctypes.get_last_error())
        else:
            try:
                os.killpg(self.child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            self.child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass

    def close(self) -> None:
        if self.job is not None:
            self._k32.CloseHandle(self.job)
            self.job = None

    def __enter__(self) -> Tree:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def holder(pidfile: Path) -> str:
    """The code of a Python that appends its pid to ``pidfile``, keeps it open, then sleeps (60 s)."""
    return (f"import os, time; f = open({str(pidfile)!r}, 'a'); f.write(f'{{os.getpid()}}\\n'); f.flush(); "
            "time.sleep(60)")


def all_gone(pidfile: Path) -> bool:
    """Every :func:`holder` of ``pidfile`` that wrote its pid has ended. On Windows, ``pidfile`` can be deleted once
    none holds it open (a pid can be reused within seconds there, by any process); on POSIX, no pid in it answers."""
    if os.name == "nt":
        try:
            pidfile.unlink(missing_ok=True)
        except PermissionError:
            return False
        return True
    for pid in (int(p) for p in pidfile.read_text(encoding="utf-8").split()):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        except PermissionError:
            pass
        return False
    return True
