"""brain session-archive: the agents' transcripts, scanned, filtered and sealed into the spool
(wi-brain-session-archive; spec-brain-vault-heirs-identity §3.2, spec-brain-session-telemetry §3.7).

Opt-in: nothing runs until config.json says ``session_archive: {enabled: true}``, and no scheduled task is created
(the owner adds one when they choose). Zero token: standard library, gitleaks and brain vault. One run::

    brain session-archive run [--dry-run] [--max N] [--json]

1. **Which transcripts.** Claude Code's (``<projects>/<project>/<session>.jsonl`` and its subagents' under
   ``<session>/subagents/``; other agents later, through their adapters), each one quiet for ``quiet_minutes``
   (default 120: a live session waits for a later run) whose size or time changed since it was last archived. The
   desktop app's session metadata is never read here: its texts never reach the archive (§3.7).
2. **The residency filter** (``session_archive.resident``: ``{name: regex}``, the owner's): a line of a transcript a
   pattern matches is a row a data source forbids from leaving the machine; it is replaced by a stub
   (``{"type": "brain-archive-dropped", "why": "residency"}``) before anything else reads it, and counted under the
   filter's name. The engine names no source: the patterns are the owner's.
3. **The secret scan**, twice and fail-closed: the engine's own patterns first (brain.secretscan: a matching line of a
   string value is dropped, a line still holding a key's shape is replaced by a stub, ``"why": "secret"``), then
   gitleaks over the staged copies (``gitleaks dir``, else ``detect --no-git``): each line it reports becomes a stub,
   and a second gitleaks pass must find nothing. gitleaks absent, failing or still finding something: **nothing is
   archived** (a transcript is never archived unscanned).
4. **Sealed**: the staged copies go into the spool through brain.spool.put (store :data:`STORE`, its class sealed:
   declared in ``classes.stores``), which scans them once more and seals them with brain vault to the store's
   recipients (two at least); ``brain spool push`` sends them to the data remote. The staged copies in clear are
   deleted in every case; nothing goes to a git repo.
5. **The index**, ``$BRAIN_HOME/session-archive/index.json`` (truth-local, ``v`` 1): by session record (the SR id,
   ``sr-<start date>-<first 8 characters of the session id>``), each session's id, project folder, machine of origin,
   its place in the tree when brain sessions knows it (``host_id``, ``parent``, ``role``), and each archived file's
   source, fingerprint, lines, what the filter and the scans dropped, and the sealed file in the spool.

``--dry-run`` lists what would be archived and what the filter and the scans would drop (gitleaks still runs, over
copies in a temporary folder deleted after); it seals nothing and writes no index. ``brain health session-archive``
gives the age of the last run that sealed something.
"""

from __future__ import annotations

import itertools
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config, paths, secretscan, spool, stateio, transcript

STORE = "session-archive"        # its home store (brain.classes.ENGINE_STORES), class sealed
CHECK = "session-archive"        # brain health session-archive
INDEX_V = 1
QUIET_MINUTES = 120              # a transcript touched more recently is a live session's: a later run takes it
MAX_FILES = 200                  # the transcripts one run seals at most; the rest wait for the next run
MAX_AGE_DAYS = 7                 # brain health warns when no run sealed anything for this long
LEAKS_EXIT = 3                   # the exit code gitleaks is told to give when it finds something
SCAN_TIMEOUT = 900
STUB_RESIDENT = json.dumps({"type": "brain-archive-dropped", "why": "residency"})
STUB_SECRET = json.dumps({"type": "brain-archive-dropped", "why": "secret"})
NO_SCANNER = ("gitleaks is not on the PATH: nothing archived (a transcript is never archived unscanned; install "
              "gitleaks, then run again)")


class ArchiveError(RuntimeError):
    """A run the archive refuses or stops: nothing is sealed (brain session-archive exits 2)."""


# --- the configuration ---
def _block(cfg: config.Config) -> dict:
    d = cfg.data.get("session_archive")
    return d if isinstance(d, dict) else {}


def enabled(cfg: config.Config) -> bool:
    return _block(cfg).get("enabled") is True


def _int(cfg: config.Config, key: str, default: int) -> int:
    v = _block(cfg).get(key)
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 1 else default


def resident(cfg: config.Config) -> dict[str, re.Pattern[str]]:
    """The residency filter: {name: compiled pattern}; ArchiveError on a bad one (the run would let a row out)."""
    raw = _block(cfg).get("resident") or {}
    if not isinstance(raw, dict):
        raise ArchiveError("session_archive.resident is {name: regex}")
    out = {}
    for name, rx in raw.items():
        if not isinstance(rx, str) or not rx:
            raise ArchiveError(f"session_archive.resident.{name}: a regex (a non-empty string)")
        try:
            out[str(name)] = re.compile(rx)
        except re.error as exc:
            raise ArchiveError(f"session_archive.resident.{name}: not a regex ({exc})") from None
    return out


# --- the index ---
def archive_dir() -> Path:
    return paths.brain_home() / STORE


def index_file() -> Path:
    return archive_dir() / "index.json"


def _shape(data: dict) -> str:
    bad = sorted(k for k in ("sessions", "last") if not isinstance(data.get(k, {}), dict))
    return f"{', '.join(bad)} not an object" if bad else ""


def load_index(write: bool = False) -> tuple[stateio.State, dict]:
    """The index and its record; ``write``: ArchiveError when this engine must not write it (a newer brain's)."""
    st = stateio.load(index_file(), known=INDEX_V, check=_shape, aside=write)
    if write and not st.writable:
        raise ArchiveError(st.refusal())
    data = st.data
    for k in ("sessions", "last"):
        if not isinstance(data.get(k), dict):
            data[k] = {}
    return st, data


# --- the transcripts ---
@dataclass
class Source:
    """A transcript to archive: its path, the SR it belongs to, its name in the sealed archive."""
    path: Path
    sr: str
    session: str
    project: str
    name: str
    fingerprint: str
    agent: str = ""


def _now(now: datetime | None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _fingerprint(f: Path) -> tuple[str, float] | None:
    try:
        st = f.stat()
    except OSError:
        return None
    return f"{st.st_size}:{st.st_mtime_ns}", st.st_mtime


def start_date(f: Path, fallback: float) -> str:
    """The date of a transcript's first timestamp (YYYY-MM-DD), else of ``fallback`` (its mtime)."""
    try:
        with f.open(encoding="utf-8", errors="replace") as fh:
            for line in itertools.islice(fh, 200):
                try:
                    ts = transcript.parse_ts(json.loads(line).get("timestamp"))
                except (ValueError, AttributeError):
                    continue
                if ts:
                    return ts.astimezone(timezone.utc).strftime("%Y-%m-%d")
    except OSError:
        pass
    return datetime.fromtimestamp(fallback, timezone.utc).strftime("%Y-%m-%d")


def sr_id(date: str, session: str) -> str:
    """The session record's id (brain/schemas/sr.schema.json): ``sr-<date>-<first 8 characters>``."""
    return f"sr-{date}-{re.sub(r'[^0-9a-z]', '', session.lower())[:8]:0<8}"


def candidates(index: dict, now: datetime, quiet: int) -> tuple[list[Source], int, int]:
    """(the transcripts to archive, how many wait as live, how many are unchanged since they were archived)."""
    root = paths.projects_dir()
    out: list[Source] = []
    live = unchanged = 0
    if not root.is_dir():
        return out, live, unchanged
    cutoff = now.timestamp() - quiet * 60
    for main in sorted(root.glob("*/*.jsonl")):
        fp = _fingerprint(main)
        if fp is None:
            continue
        sr = sr_id(start_date(main, fp[1]), main.stem)
        known = (index.get(sr) or {}).get("files") or {}
        subs = transcript.subagent_files(main)
        sub_root = main.with_suffix("") / "subagents"
        for f in [main, *subs]:
            got = fp if f is main else _fingerprint(f)
            if got is None:
                continue
            if got[1] > cutoff:
                live += 1
                continue
            agent = "" if f is main else f.relative_to(sub_root).with_suffix("").as_posix()
            name = f"{sr}.jsonl" if f is main else f"{sr}--{agent.replace('/', '--')}.jsonl"
            if (known.get(name) or {}).get("fingerprint") == got[0]:
                unchanged += 1
                continue
            out.append(Source(f, sr, main.stem, main.parent.name, name, got[0], agent))
    return out, live, unchanged


# --- the residency filter and the engine's scan ---
@dataclass
class Counts:
    lines: int = 0
    residency: dict[str, int] = field(default_factory=dict)
    cleaned: int = 0          # lines of string values the engine's patterns dropped
    secret: int = 0           # whole lines replaced: a key's shape left, or gitleaks reported it

    def as_dict(self) -> dict:
        return {"lines": self.lines, "residency": dict(sorted(self.residency.items())), "cleaned": self.cleaned,
                "secret": self.secret}


def _shaped(text: str) -> bool:
    return any(rx.search(text) for _, rx in secretscan.SHAPED)


def filter_file(src: Path, dst: Path, filters: dict[str, re.Pattern[str]]) -> Counts:
    """Copy one transcript to ``dst``, line by line: the residency filter, then the engine's secret patterns."""
    c = Counts()
    with src.open("rb") as fh, dst.open("w", encoding="utf-8", newline="\n") as out:
        for raw in fh:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            c.lines += 1
            hit = next((n for n, rx in filters.items() if rx.search(line)), None)
            if hit is not None:
                c.residency[hit] = c.residency.get(hit, 0) + 1
                out.write(STUB_RESIDENT + "\n")
                continue
            try:
                obj, n = secretscan.clean(json.loads(line))
                text = json.dumps(obj, ensure_ascii=False) if n else line
            except ValueError:   # not JSON (a line cut by a crash): one line still, whatever it holds
                text, n = secretscan.clean_text(line)
                text = text.replace("\n", " ").replace("\r", " ")
            c.cleaned += n
            if _shaped(text):
                c.secret += 1
                text = STUB_SECRET
            out.write(text + "\n")
    return c


# --- gitleaks ---
def scanner() -> list[str] | None:
    """The scanner's command line: gitleaks on the PATH, else None (the run archives nothing)."""
    exe = shutil.which("gitleaks")
    return [exe] if exe else None


def gitleaks(argv: list[str], folder: Path) -> dict[str, set[int]]:
    """gitleaks over a folder's files: {file name: the line numbers it reports}, {} when clean. ArchiveError when it
    fails (an old gitleaks without ``dir`` is asked through ``detect --no-git``). Its default rules, whatever the
    environment holds: a ``gitleaks:allow`` in a transcript's line is ignored (a whole tool result is one line), a
    config named by GITLEAKS_CONFIG* and a .gitleaksignore of the current folder are never read."""
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GITLEAKS_")}
    with tempfile.TemporaryDirectory(prefix="brain-gl-") as tmp:
        report = Path(tmp) / "report.json"
        why = ""
        for sub in (["dir", str(folder)], ["detect", "--no-git", "--source", str(folder)]):
            report.unlink(missing_ok=True)
            try:
                r = subprocess.run([*argv, *sub, "--no-banner", "--redact", "--ignore-gitleaks-allow",
                                    "--exit-code", str(LEAKS_EXIT), "--report-format", "json",
                                    "--report-path", str(report)],
                                   capture_output=True, timeout=SCAN_TIMEOUT, stdin=subprocess.DEVNULL, cwd=tmp,
                                   env=env)
            except (OSError, subprocess.SubprocessError) as exc:
                raise ArchiveError(f"gitleaks could not run ({exc.__class__.__name__}): nothing archived") from None
            if r.returncode == 0:
                return {}
            if r.returncode == LEAKS_EXIT and report.is_file():
                return _report_hits(report)
            why = ((r.stderr or b"").decode("utf-8", "replace").strip().splitlines() or [f"exit {r.returncode}"])[-1]
        raise ArchiveError(f"gitleaks failed ({why[:200]}): nothing archived")


def _report_hits(report: Path) -> dict[str, set[int]]:
    """gitleaks' JSON report as {file name: line numbers}; ArchiveError when it cannot be read as one."""
    try:
        found = json.loads(report.read_text(encoding="utf-8") or "[]") or []
    except ValueError:
        raise ArchiveError("gitleaks wrote a report that is not JSON: nothing archived") from None
    hits: dict[str, set[int]] = {}
    for f in found if isinstance(found, list) else []:
        if isinstance(f, dict) and isinstance(f.get("StartLine"), int):
            hits.setdefault(Path(str(f.get("File", ""))).name, set()).add(f["StartLine"])
    if not hits:
        raise ArchiveError("gitleaks reported findings without a file and line: nothing archived")
    return hits


def _stub_lines(f: Path, lines: set[int]) -> int:
    """Replace the given 1-based lines of a staged file by the secret stub; how many were replaced."""
    with f.open(encoding="utf-8", newline="") as fh:   # lines as gitleaks counts them: by \n alone
        text = fh.read().split("\n")
    n = 0
    for i in sorted(lines):
        if 1 <= i <= len(text) and text[i - 1] != STUB_SECRET:
            text[i - 1] = STUB_SECRET
            n += 1
    with f.open("w", encoding="utf-8", newline="") as fh:
        fh.write("\n".join(text))
    return n


def scan_staged(argv: list[str], folder: Path, counts: dict[str, Counts]) -> None:
    """gitleaks over the staged copies, its lines replaced by stubs, then a second pass that must be clean."""
    hits = gitleaks(argv, folder)
    for name, lines in hits.items():
        if name not in counts:
            raise ArchiveError(f"gitleaks reported a file that is not staged ({name}): nothing archived")
        counts[name].secret += _stub_lines(folder / name, lines)
    if hits and gitleaks(argv, folder):
        raise ArchiveError("gitleaks still finds a secret after its lines were dropped: nothing archived")


# --- the run ---
def _tree() -> dict[str, dict]:
    """{session id: {host_id, parent, role}} from brain sessions, {} when it cannot tell."""
    from . import sessions
    try:   # the tree is a courtesy of the index, never a reason to stop the archive
        tree = sessions.load(briefs=False)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, stateio.StateError):
        return {}
    out = {}
    for sid, key in tree.by_session.items():
        node = tree.nodes.get(key) or {}
        out[sid] = {k: v for k, v in (("host_id", node.get("host_id")), ("parent", node.get("parent")),
                                      ("role", tree.role(key))) if v}
    return out


def run(cfg: config.Config, *, dry_run: bool = False, max_files: int | None = None, now: datetime | None = None,
        argv: list[str] | None = None, found=None) -> dict:
    """One run (see the module's docstring): {off, dry_run, archived, live, unchanged, waiting, sealed, ...}."""
    res: dict = {"off": not enabled(cfg), "dry_run": dry_run, "archived": [], "live": 0, "unchanged": 0,
                 "waiting": 0, "sealed": "", "leftovers": []}
    if res["off"]:
        return res
    filters = resident(cfg)
    argv = argv or scanner()
    if not argv:
        raise ArchiveError(NO_SCANNER)
    t = _now(now)
    _, data = load_index(write=not dry_run)   # refused here when a newer brain wrote it
    if not dry_run:   # a run killed mid-way left its clear copies: removed before anything else
        res["leftovers"] = [str(p) for p in leftovers() if not _remove(p)]
    srcs, res["live"], res["unchanged"] = candidates(data["sessions"], t, _int(cfg, "quiet_minutes", QUIET_MINUTES))
    cap = max_files or _int(cfg, "max_files", MAX_FILES)
    srcs, res["waiting"] = srcs[:cap], max(0, len(srcs) - cap)
    if not srcs:
        return res
    if dry_run:
        stage_ctx = tempfile.TemporaryDirectory(prefix="brain-sarch-")
        stage = Path(stage_ctx.name)
    else:
        archive_dir().mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix="staging-", dir=archive_dir()))
    try:
        counts = {s.name: filter_file(s.path, stage / s.name, filters) for s in srcs}
        scan_staged(argv, stage, counts)
        res["archived"] = [{"sr": s.sr, "file": s.name, "source": s.path.relative_to(paths.projects_dir()).as_posix(),
                            **counts[s.name].as_dict()} for s in srcs]
        if dry_run:
            return res
        try:
            entry = spool.put(cfg, STORE, [stage / s.name for s in srcs], now=t, found=found)
        except spool.SpoolError as exc:
            raise ArchiveError(f"the spool refused the archive: {exc}") from None
        res["sealed"] = entry["file"]
        _record(srcs, counts, entry["file"], t)
        return res
    finally:
        if not _remove(stage):
            res["leftovers"].append(str(stage))


def leftovers() -> list[Path]:
    """The staged folders a run left in the store (killed, or a file locked when it tried to remove them)."""
    d = archive_dir()
    return sorted(p for p in d.glob("staging-*") if p.is_dir()) if d.is_dir() else []


def _remove(folder: Path, tries: int = 3) -> bool:
    """Remove a staged folder, again after a short wait when a file is locked (an indexer, an antivirus); whether
    it is gone."""
    for i in range(tries):
        shutil.rmtree(folder, ignore_errors=True)
        if not folder.exists():
            return True
        if i + 1 < tries:
            time.sleep(0.5)
    return False


def _record(srcs: list[Source], counts: dict[str, Counts], sealed: str, t: datetime) -> None:
    """The index updated with what was sealed, read again first: another run may have written it meanwhile."""
    from .timing import host
    st, data = load_index(write=True)
    tree = _tree()
    for s in srcs:
        sess = data["sessions"].setdefault(s.sr, {})
        sess.update({"session": s.session, "project": s.project, "machine": host(), **tree.get(s.session, {})})
        sess.setdefault("files", {})[s.name] = {"source": s.path.relative_to(paths.projects_dir()).as_posix(),
                                                "agent": s.agent, "fingerprint": s.fingerprint,
                                                "sealed": sealed, "at": _iso(t), **counts[s.name].as_dict()}
    data["last"] = {"at": _iso(t), "sealed": sealed, "files": len(srcs)}
    try:
        stateio.save(st, data, indent=1)
    except stateio.StateError as exc:
        raise ArchiveError(f"sealed into the spool ({sealed}) but the index could not be written: {exc}") from None


# --- status and health ---
def status(cfg: config.Config) -> dict:
    _, data = load_index()
    files = sum(len((s or {}).get("files") or {}) for s in data["sessions"].values())
    return {"enabled": enabled(cfg), "scanner": bool(scanner()), "index": str(index_file()),
            "sessions": len(data["sessions"]), "files": files, "last": data["last"],
            "leftovers": [str(p) for p in leftovers()],
            "resident": sorted((_block(cfg).get("resident") or {}) if isinstance(_block(cfg).get("resident"), dict)
                               else [])}


def render_status(s: dict) -> list[str]:
    last = s["last"]
    return [f"session archive: {'on' if s['enabled'] else 'off (config.json session_archive.enabled)'}",
            f"scanner: {'gitleaks' if s['scanner'] else 'gitleaks not on the PATH: a run archives nothing'}",
            f"index: {s['index']}: {s['sessions']} session(s), {s['files']} file(s)",
            f"residency filters: {', '.join(s['resident']) or 'none'}",
            "last run that sealed: " + (f"{last.get('at')} ({last.get('files')} file(s), {last.get('sealed')})"
                                        if last.get("at") else "never")] + \
        [f"WARN staged copies in clear left by a run (the next run removes them): {p}" for p in s["leftovers"]]


def health(cfg: config.Config, now: datetime | None = None, out=None, named: bool = True) -> int:
    """``brain health session-archive``: OFF while it is not enabled (silent with --all), a warning when a run left
    staged copies, gitleaks is missing or no run sealed anything for ``max_age_days``; never a failure (exit 0)."""
    import sys
    out = out or sys.stdout
    if not enabled(cfg):
        if named:
            print(f"{CHECK}: OFF (config.json session_archive.enabled)", file=out)
        return 0
    _, data = load_index()
    at = data["last"].get("at")
    limit = _int(cfg, "max_age_days", MAX_AGE_DAYS)
    when = None
    if isinstance(at, str):
        try:
            when = datetime.strptime(at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            when = None
    age = _now(now) - when if when else None
    left = leftovers()
    if left:
        print(f"{CHECK}: WARN {len(left)} staged folder(s) in clear left by a run (the next run removes them)",
              file=out)
    elif not scanner():
        print(f"{CHECK}: WARN gitleaks is not on the PATH: a run archives nothing", file=out)
    elif age is None:
        print(f"{CHECK}: WARN no run has sealed anything yet (brain session-archive run)", file=out)
    elif age > timedelta(days=limit):
        print(f"{CHECK}: WARN the last archive is {age.days} days old (over {limit})", file=out)
    else:
        hours = int(age.total_seconds() // 3600)
        print(f"{CHECK}: OK the last archive is {hours // 24}d {hours % 24}h old", file=out)
    return 0


def run_lines(res: dict) -> list[str]:
    """What ``brain session-archive run`` prints of its result."""
    if res["off"]:
        return ["session archive: off (config.json session_archive.enabled is not true): nothing done"]
    lines = []
    for a in res["archived"]:
        res_n = sum(a["residency"].values())
        lines.append(f"{'would archive' if res['dry_run'] else 'archived'}: {a['source']} as {a['file']} "
                     f"({a['lines']} line(s); residency dropped {res_n}, secret lines dropped {a['secret']}, "
                     f"string lines cleaned {a['cleaned']})")
    lines.append(f"{res['live']} live transcript(s) wait, {res['unchanged']} unchanged since archived"
                 + (f", {res['waiting']} left for the next run" if res["waiting"] else ""))
    lines += [f"WARN could not remove staged copies in clear (a file locked): {p}" for p in res["leftovers"]]
    if res["sealed"]:
        lines.append(f"sealed into the spool: {res['sealed']} (brain spool push sends it)")
    if res["dry_run"]:
        lines.append("plan only: nothing sealed, no index written")
    return lines
