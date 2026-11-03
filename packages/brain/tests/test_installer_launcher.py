"""install.ps1's Set-Launcher: brain.exe is replaced even while a brain runs (Windows refuses to overwrite a running
image; sessions' hooks run it many times a minute, so -Apply failed on its last step on 2026-11-02 and 03)."""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

INSTALLER = Path(__file__).resolve().parents[1] / "installer" / "install.ps1"
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="the launcher is copied on Windows only")


def set_launcher(src, dst):
    """Run the installer's own Set-Launcher function on two files; its result: same, copied or swapped."""
    text = INSTALLER.read_text(encoding="utf-8")
    func = re.search(r"^function Set-Launcher\b.*?^}", text, re.S | re.M).group(0)
    script = f"$ErrorActionPreference = 'Stop'\n{func}\nSet-Launcher '{src}' '{dst}'\n"
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_identical_launcher_is_left_alone(tmp_path):
    src, dst = tmp_path / "venv-brain.exe", tmp_path / "brain.exe"
    src.write_bytes(b"launcher v1")
    dst.write_bytes(b"launcher v1")
    assert set_launcher(src, dst) == "same"
    assert not (tmp_path / "brain.exe.new").exists()


def test_new_launcher_is_copied(tmp_path):
    src, dst = tmp_path / "venv-brain.exe", tmp_path / "brain.exe"
    src.write_bytes(b"launcher v2")
    assert set_launcher(src, dst) == "copied"
    dst.write_bytes(b"launcher v1")
    assert set_launcher(src, dst) == "copied"
    assert dst.read_bytes() == b"launcher v2" and not (tmp_path / "brain.exe.new").exists()


def test_running_launcher_is_swapped_then_cleaned(tmp_path):
    src, dst = tmp_path / "venv-brain.exe", tmp_path / "brain.exe"
    src.write_bytes(b"launcher v2")
    shutil.copy(Path(r"C:\Windows\System32\PING.EXE"), dst)  # a real image, locked while it runs
    running = subprocess.Popen([str(dst), "-n", "30", "127.0.0.1"], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    try:
        assert set_launcher(src, dst) == "swapped"
        assert dst.read_bytes() == b"launcher v2"
        assert len(list(tmp_path.glob("brain.exe.old-*"))) == 1
    finally:
        running.kill()
        running.wait()
    assert set_launcher(src, dst) == "same"  # the next run removes the old launcher once nothing runs it
    assert not list(tmp_path.glob("brain.exe.old-*"))
