"""wi-brain-help-encoding: `brain <cmd> --help` never crashes on a cp1252 pipe (a help holds a Σ) or on a missing
stdout (pythonw.exe)."""

import os
import subprocess
import sys
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")


def _run(code_or_args, *, encoding=None, inline=False):
    env = {**os.environ, "PYTHONPATH": SRC}
    env.pop("PYTHONUTF8", None)
    if encoding:
        env["PYTHONIOENCODING"] = encoding
    cmd = [sys.executable, "-c", code_or_args] if inline else [sys.executable, "-m", "brain", *code_or_args]
    return subprocess.run(cmd, capture_output=True, env=env)


def test_help_with_sigma_survives_a_cp1252_pipe():
    for args in (["--help"], ["lesson", "--help"], ["lesson", "rules", "--help"]):
        r = _run(args, encoding="cp1252")
        assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
        assert b"UnicodeEncodeError" not in r.stderr
    assert "Σ-".encode() in _run(["--help"], encoding="cp1252").stdout


def test_help_survives_a_missing_stdout(tmp_path):
    log = tmp_path / "tb.txt"
    code = (
        "import sys, traceback
"
        "sys.stdout = sys.stderr = None
"
        "from brain.cli import main
"
        "try:
"
        "    main(['lesson', '--help'])
"
        "except SystemExit as e:
"
        "    sys.exit(e.code)
"
        "except BaseException:
"
        f"    open({str(log)!r}, 'w').write(traceback.format_exc())
"
        "    sys.exit(3)
"
    )
    r = _run(code, inline=True)
    assert r.returncode == 0, log.read_text() if log.exists() else r.stderr.decode("utf-8", "replace")
