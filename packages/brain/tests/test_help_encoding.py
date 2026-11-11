"""wi-brain-help-encoding: `brain <cmd> --help` never crashes on a cp1252 pipe (a help holds a Σ) or on a missing
stdout (pythonw.exe); wi-brain-nul-stdout-encoding: nor on NUL, a cp1252 stream that reports isatty() true."""

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

from brain import cli

SRC = str(Path(__file__).resolve().parents[1] / "src")

NO_STDOUT = """\
import sys, traceback
sys.stdout = sys.stderr = None
from brain.cli import main
try:
    main(['lesson', '--help'])
except SystemExit as e:
    sys.exit(e.code)
except BaseException:
    open(sys.argv[1], 'w').write(traceback.format_exc())
    sys.exit(3)
"""


def _run(code_or_args, *, encoding=None, inline=False, extra=()):
    env = {**os.environ, "PYTHONPATH": SRC}
    env.pop("PYTHONUTF8", None)
    if encoding:
        env["PYTHONIOENCODING"] = encoding
    cmd = [sys.executable, "-c", code_or_args, *extra] if inline else [sys.executable, "-m", "brain", *code_or_args]
    return subprocess.run(cmd, capture_output=True, env=env)


def test_help_with_sigma_survives_a_cp1252_pipe():
    for args in (["--help"], ["lesson", "--help"], ["lesson", "rules", "--help"]):
        r = _run(args, encoding="cp1252")
        assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
        assert b"UnicodeEncodeError" not in r.stderr
    assert "Σ-".encode() in _run(["--help"], encoding="cp1252").stdout


def test_help_survives_a_missing_stdout(tmp_path):
    log = tmp_path / "tb.txt"
    r = _run(NO_STDOUT, inline=True, extra=[str(log)])
    assert r.returncode == 0, log.read_text() if log.exists() else r.stderr.decode("utf-8", "replace")


class _TtyBytes(io.BytesIO):
    """NUL on Windows: a stream that says it is a terminal, opened in the ANSI code page."""

    def isatty(self):
        return True


def test_help_survives_nul_a_tty_that_is_not_utf8(monkeypatch):
    out = io.TextIOWrapper(_TtyBytes(), encoding="cp1252")
    assert out.isatty()
    monkeypatch.setattr(sys, "stdout", out)
    with pytest.raises(SystemExit) as e:
        cli.main(["--help"])
    assert e.value.code == 0
    out.flush()
    assert out.encoding == "utf-8"
    assert "Σ-".encode() in out.buffer.getvalue()


def test_a_utf8_console_is_left_alone():
    out = io.TextIOWrapper(_TtyBytes(), encoding="utf-8", errors="strict")
    cli._utf8(out)
    assert (out.encoding, out.errors) == ("utf-8", "strict")
    pipe = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", errors="strict")
    cli._utf8(pipe)  # a pipe already UTF-8 still gets errors=replace, as before
    assert pipe.errors == "replace"
