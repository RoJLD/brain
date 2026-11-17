"""The registry of the engine's format migrations (wi-brain-migrate): which formats, which steps, and the chain from a
file's version to the one this engine reads and writes. Both sides read it from here:

- the readers, so a file is never saved at a version its data does not have: :func:`brain.stateio.load` and
  :func:`brain.config.load` run a file's pending steps in memory (:func:`upcast`), so a writer that loaded it saves
  it in the shape its ``v`` names; a file the chain does not reach is ``behind``, read-only;
- ``brain migrate`` (brain.migrate), the eager, backed-up and logged version of the same steps.

**Every step lives in this module**, defined below with :func:`step` (never beside its reader, nor in a module of its
own: a step registered only when an unrelated module happens to be imported would be missed by a command that does
not import it). ``tests/test_migrate.py`` refuses a ``step(`` or ``register(`` call anywhere else in the engine.

A format's ``reads`` names the older versions its reader still reads in place (an upcast in its own code, as
``usage/sessions.json`` v1 under ``LEDGER_V`` 2): every version below the format's own has a step or is named there,
else a file at it is ``behind`` (a test holds the registry to that).

Standard library only, and no import of the engine's other modules at load time: brain.stateio and brain.config
import it.
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable

VKEY = "v"


@dataclass(frozen=True)
class Format:
    """A format the migrations cover: its id, its file (``config.json``: the brain's, found as brain.config finds it;
    any other: relative to ``$BRAIN_HOME``), the store it lives in, the version this engine reads and writes (None:
    the schema's, ``config.schema.json``), the module that owns it (the reader the test holds it to) and the older
    versions that reader reads in place."""
    id: str
    path: str
    store: str
    known_v: int | None
    owner: str
    reads: frozenset = frozenset()

    @property
    def repo(self) -> bool:
        """Whether the file lives in the brain's repo (git holds its history) rather than in ``$BRAIN_HOME``."""
        return self.id == "config"

    def known(self) -> int:
        return self.known_v if self.known_v is not None else config_known()

    def where(self) -> str:
        return self.path if self.repo else f"$BRAIN_HOME/{self.path}"

    def file(self, root: Path | None = None) -> Path | None:
        """The file of this format on this machine, None when there is none."""
        from . import config, paths
        f = config.config_file(root) if self.repo else paths.brain_home() / self.path
        return f if f is not None and f.is_file() else None


@lru_cache(maxsize=1)
def config_known() -> int:
    from . import schema
    return schema.known_v("config")


# The formats the migrations cover, in the order brain migrate --apply takes them: the brain's config.json, then the
# truth-local files of $BRAIN_HOME that carry a v (docs/formats.md, « Machine-local state »). Left out, each for its
# reason (tests/test_migrate.py holds every stateio.load caller to this list or to EXCLUDED): a session's own files
# live as long as their session; a derived file is rebuilt; a log is upcast on read.
FORMATS: tuple[Format, ...] = (
    Format("config", "config.json", "config", None, "brain.config"),
    Format("schedules", "schedules/installed.json", "schedules", 1, "brain.schedule.record_file"),
    Format("alerts", "alerts/state.json", "alerts", 1, "brain.alerts.state_dir"),
    Format("vault", "vault/state.json", "vault", 1, "brain.vault.state_file"),
    Format("vault-device", "vault/device.json", "vault", 1, "brain.vault.device_file"),
    Format("usage", "usage/sessions.json", "usage", 2, "brain.usage.ledger_file", frozenset({1})),
    Format("cockpit", "tui.json", "cockpit", 1, "brain.cockpit.state_path"),
    Format("memory-sync", "memory-sync/state.json", "memory-sync", 1, "brain.memory.sync_dir"),
    Format("machine", "machine.json", "machine.json", 1, "brain.machine.machine_file"),
    Format("spool", "spool/spool.json", "spool", 1, "brain.spool.index_file"),
    Format("session-archive", "session-archive/index.json", "session-archive", 1, "brain.sessionarchive.index_file"),
    Format("net", "net/breakers.json", "net", 1, "brain.net.path"),
    Format("outbox", "outbox/queue.json", "outbox", 1, "brain.outbox.path"),
    Format("ship", "ship/queue.json", "ship", 1, "brain.ship.queue_path"),
)
BY_ID = {f.id: f for f in FORMATS}
# The stateio.load callers whose files are not migrated, and why (tests/test_migrate.py).
EXCLUDED = {
    "brain.budget": "a session's own file (budget/<session>.json): it lives as long as its session",
    "brain.capture": "a session's own files (sessions/<id>.json, <id>.state.json): written by its Stop hook",
    "brain.sessions": "a session's own report (sessions/<id>.report.json)",
    "brain.plan": "a session's own plan file (sessions/<id>.plan.json)",
    "brain.formats": "derived: the format checks' cached results, rebuilt by brain formats check",
    "brain.depprobes": "derived: the dependency probes' last run, rebuilt by the next probe",
}


@dataclass(frozen=True)
class Step:
    """One version of one format: ``fn`` takes the record at ``frm`` (a copy, without its ``v``) and returns the
    record at ``to`` (``frm + 1``), without its ``v`` either: the caller writes it."""
    format: str
    frm: int
    to: int
    fn: Callable[[dict], dict]
    about: str

    @property
    def id(self) -> str:
        return f"{self.format}-v{self.frm}-v{self.to}"

    def row(self) -> dict:
        return {"id": self.id, "from": self.frm, "to": self.to, "about": self.about}


STEPS: dict[tuple[str, int], Step] = {}   # (format, from v) -> its step


def register(s: Step) -> Step:
    """Add ``s`` to :data:`STEPS`: a known format, one version up, the only step from its version."""
    if s.format not in BY_ID:
        raise ValueError(f"brain migrate: {s.format!r} is not a format of brain.migrations.FORMATS")
    if not isinstance(s.frm, int) or s.frm < 1 or s.to != s.frm + 1:
        raise ValueError(f"brain migrate: a step goes one version up from v1 or later, not v{s.frm} -> v{s.to}")
    if (s.format, s.frm) in STEPS:
        raise ValueError(f"brain migrate: {s.format} already has a step from v{s.frm}")
    STEPS[(s.format, s.frm)] = s
    return s


def step(fmt: str, frm: int, about: str):
    """A decorator: the function becomes the step of ``fmt`` from ``frm`` to ``frm + 1``."""
    def add(fn: Callable[[dict], dict]) -> Callable[[dict], dict]:
        register(Step(fmt, frm, frm + 1, fn, about))
        return fn
    return add


# --- the steps: every one of the engine's, here (none yet: no format has broken since its v was written) ---


# --- the chain ---

def chain(fmt: Format, v: int, known: int | None = None) -> list[Step]:
    """The steps from ``v``, in order, as far as they are registered and never past ``known`` (the format's own)."""
    out: list[Step] = []
    known = fmt.known() if known is None else known
    while (fmt.id, v) in STEPS and STEPS[(fmt.id, v)].to <= known:
        out.append(STEPS[(fmt.id, v)])
        v = out[-1].to
    return out


def reach(fmt: Format, v: int, known: int | None = None) -> tuple[list[Step], bool]:
    """(the steps from ``v``, whether the file is then read as this engine reads it): the chain ends at ``known`` or
    at a version its reader reads in place; False is a file ``behind``, its migration missing."""
    known = fmt.known() if known is None else known
    steps = chain(fmt, v, known)
    end = steps[-1].to if steps else v
    return steps, end >= known or end in fmt.reads


class StepFailed(RuntimeError):
    """A step that raised, or returned no record."""


def run(steps: list[Step], data: dict) -> dict:
    """``data`` (without its ``v``) carried along ``steps``, in memory; :class:`StepFailed` on a step that fails."""
    for s in steps:
        try:
            out = s.fn(copy.deepcopy(data))
        except Exception as exc:   # a step is code: any failure is the step's, said as one
            raise StepFailed(f"step {s.id} failed ({exc.__class__.__name__}: {exc})") from None
        if not isinstance(out, dict):
            raise StepFailed(f"step {s.id} returned a {type(out).__name__}, not a record")
        data = {k: val for k, val in out.items() if not (k == VKEY and not isinstance(val, dict))}
    return data


def home_format(path: Path) -> Format | None:
    """The format of a ``$BRAIN_HOME`` file (None: not one of :data:`FORMATS`)."""
    from . import paths
    try:
        rel = os.path.normcase(os.path.relpath(Path(path).resolve(), paths.brain_home().resolve()))
    except (OSError, ValueError):   # another drive (Windows): not under the home
        return None
    for fmt in FORMATS:
        if not fmt.repo and rel == os.path.normcase(os.path.normpath(fmt.path)):
            return fmt
    return None


def upcast(fmt: Format, data: dict, v: int, known: int | None = None) -> tuple[dict, int, str]:
    """A reader's view of a file at ``v``: (its data carried along the chain, the version reached, '' or why it is
    behind: a step missing or failing). The file itself is never touched."""
    steps, ok = reach(fmt, v, known)
    if not ok:
        return data, v, (f"is at v {v}, and no migration of this engine reaches v "
                         f"{fmt.known() if known is None else known} ({fmt.id}): brain migrate --plan")
    if not steps:
        return data, v, ""
    try:
        return run(steps, data), steps[-1].to, ""
    except StepFailed as exc:
        return data, v, f"is at v {v}: {exc}: brain migrate --plan"
