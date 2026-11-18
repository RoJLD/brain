"""The verdict of a long check, in three lines (brain gate): each run's logs in a folder of its own under the scratch
folder, and what a session reads: what passed, what failed, the next command.

- **The scratch folder**: ``<system temp>/brain-<kind>/``, one folder per run (``<label>-<UTC stamp>``); the oldest
  past :data:`KEEP` are removed when a run starts. A log is the step's command, its exit code, its stdout and its
  stderr, whole: the verdict names the file, the session reads it only when a step failed.
- **The three lines**: ``<kind>: PASSED|FAILED ...`` (the steps passed, and the folder of the logs), ``failed: ...``
  (each failed step and its reason, or ``none``), ``next: ...`` (the command to run next: the first failed step's,
  else the one after the gate).
- **pytest's summary**: :func:`pytest_summary` reads a pytest output's counts and the ids of its failed tests
  (``FAILED <id>`` and ``ERROR <id>`` lines of ``-rfE``, pytest's default short summary).
"""

from __future__ import annotations

import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

KEEP = 20            # the runs kept per kind
DETAIL = 160         # a reason's length in the verdict's second line
_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")
_COUNT = re.compile(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|deselected)\b")
_FAILED = re.compile(r"^(FAILED|ERROR) (\S+)")


def scratch_root(kind: str) -> Path:
    """The folder of a kind's runs, under the system's temporary folder."""
    return Path(tempfile.gettempdir()) / f"brain-{_SAFE.sub('-', kind)}"


def run_folder(kind: str, label: str, root: Path | None = None, now: datetime | None = None) -> Path:
    """A new, empty folder for one run (``root``, else :func:`scratch_root`), the oldest past :data:`KEEP` removed."""
    base = root or scratch_root(kind)
    base.mkdir(parents=True, exist_ok=True)
    olds = sorted((d for d in base.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime)
    for d in olds[:max(0, len(olds) - KEEP + 1)]:
        shutil.rmtree(d, ignore_errors=True)
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%S")
    name, n = f"{_SAFE.sub('-', label).strip('-') or kind}-{stamp}", 1
    while (base / name).exists():
        n += 1
        name = f"{_SAFE.sub('-', label).strip('-') or kind}-{stamp}-{n}"
    folder = base / name
    folder.mkdir()
    return folder


def write_log(path: Path, cmd: list[str] | str, rc: int | None, out: str = "", err: str = "") -> Path:
    """One step's log: its command, its exit code, its stdout and stderr, whole."""
    shown = cmd if isinstance(cmd, str) else " ".join(cmd)
    text = f"$ {shown}\nexit: {'-' if rc is None else rc}\n\n--- stdout ---\n{out}\n--- stderr ---\n{err}\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def last_line(*texts: str, limit: int = DETAIL) -> str:
    """The last line that says something, of the first text that has one (stderr before stdout), cut to ``limit``."""
    for text in texts:
        lines = [x.strip() for x in (text or "").splitlines() if x.strip()]
        if lines:
            line = lines[-1]
            return line if len(line) <= limit else line[:limit - 3] + "..."
    return ""


@dataclass
class PytestSummary:
    counts: dict[str, int]
    failed: list[str]   # the ids of the failed and erroring tests, in their order

    @property
    def found(self) -> bool:
        return bool(self.counts) or bool(self.failed)


def pytest_summary(text: str) -> PytestSummary:
    """A pytest output's counts (its last summary line: ``3 failed, 120 passed in 9.1s``) and the ids of its failed
    tests (the short summary's ``FAILED`` and ``ERROR`` lines; with several pytest runs, every run's)."""
    counts: dict[str, int] = {}
    failed: list[str] = []
    for line in (text or "").splitlines():
        m = _FAILED.match(line.strip())
        if m and m.group(2) not in failed:
            failed.append(m.group(2))
        if re.search(r"\b(passed|failed|errors?|no tests ran)\b.* in [\d.]+s", line):
            for n, what in _COUNT.findall(line):
                key = "error" if what.startswith("error") else what
                counts[key] = counts.get(key, 0) + int(n)
    return PytestSummary(counts, failed)


def three_lines(kind: str, passed: list[str], failed: list[tuple[str, str]], skipped: list[tuple[str, str]],
                logs: Path | None, next_cmd: str, state: str = "") -> list[str]:
    """The verdict: what passed (and the logs' folder), what failed and why, the next command; ``state`` overrides
    PASSED or FAILED (INCOMPLETE: a check skipped on purpose)."""
    total = len(passed) + len(failed)
    state = state or ("PASSED" if not failed else "FAILED")
    head = f"{kind}: {state} {len(passed)}/{total}" + (f" ({', '.join(passed)})" if passed else "")
    if skipped:
        head += f"; skipped: {', '.join(f'{n} ({why})' for n, why in skipped)}"
    if logs is not None:
        head += f"; logs: {logs.as_posix()}"
    second = "failed: " + ("; ".join(f"{n}: {why}" for n, why in failed) if failed else "none")
    return [head, second, f"next: {next_cmd}"]
