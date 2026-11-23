"""xerj, an opt-in search backend of the code index (wi-brain-code-index-xerj-backend, the owner's answer XJ-1): a
third arm beside GitNexus and codebase-memory-mcp for the code bench's second stage, never the default. GitNexus stays
the authority for search and codebase-memory-mcp for a worktree's impact until that bench picks one (brain.codebackends
chooses xerj only when ``--backend xerj`` names it).

xerj (github.com/xerj-org/xerj, Apache-2.0) is one Rust binary: a search node behind an Elasticsearch-compatible API,
``xerj autoindex`` (a folder into indices under a prefix, code parsed by tree-sitter) and ``xerj search`` (its query
client). The owner builds it from xerj's public main at a pinned commit, never from the official binaries (built from
a private tree), and puts it at ``<BRAIN_HOME>/code-index/xerj/bin/xerj[.exe]`` (docs/code-index.md); nothing else
installs it, and neither ``xerj init`` (it wires agents and skill files) nor ``xerj feedback`` is ever run.

The node is a local service: a stack of projects.yaml whose start and stop are ``brain index --backend xerj --serve``
and ``--stop``, so ``brain up xerj`` / ``brain down xerj`` run them. :func:`serve` starts it detached (``xerj
--detach``), bound to 127.0.0.1 on :data:`PORT` (the Elasticsearch-compatible API; xerj also claims the two ports
after it), TLS and API keys off (loopback only), lexical embeddings (no model is downloaded), its data under
``<BRAIN_HOME>/code-index/xerj/data``. :func:`stop` stops the process whose pid xerj's own lock file of that data
folder names (``node.lock``), once that process is checked to run the engine's binary (by its path), never another;
a port answered by another service is left alone (:func:`running`). Every call of the binary runs
with ``XERJ_DISABLE_FEEDBACK=true`` (no field report, no corpus feedback), ``XERJ_NO_AUTOSTART=1`` (a client never
starts a node: only ``brain up`` does) and ``HF_HUB_OFFLINE=1``; its output goes to a file, never to a pipe that the
detached node could inherit.

:func:`index` reads a repo's branch head with ``git archive`` into ``<BRAIN_HOME>/code-index/xerj/snapshots/<repo>``
(tracked files at a known commit: the path the xerj trial measured, docs/code-index.md) and runs ``xerj autoindex`` on
it under the repo's prefix (:func:`prefix`), its state in ``.../state/<repo>``, ``--no-graph``, ``--max-minutes 0``
(no time gate). xerj's exit 0 and 3 (completed with junk) are a finished run when its ``xerj-done`` line is there and
says neither ``ok=false`` nor that every code file was dropped (``code_files`` > 0, ``code_files_indexed`` = 0); 4 is
a decision xerj asks (its disk budget), reported and never answered for the owner.
:func:`search` runs ``xerj search --json`` and maps its hits to the adapter's rows (:func:`rows`). What the engine
records of each index (the repo, the commit, its prefix) is ``<BRAIN_HOME>/code-index/xerj/record.json``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path

from . import paths, stacks

PORT = 9200
URL = f"http://127.0.0.1:{PORT}"
ENV = {"XERJ_DISABLE_FEEDBACK": "true", "XERJ_NO_AUTOSTART": "1", "HF_HUB_OFFLINE": "1"}
SERVE_TIMEOUT = 180.0
STOP_TIMEOUT = 30.0
INDEX_TIMEOUT = 3600.0   # 4.7 to 6.9 min a repo in the trial; finalising can take longer than indexing
SNAPSHOT_TIMEOUT = 600.0
QUERY_TIMEOUT = 120.0
PROBE_TIMEOUT = 3.0
RECORD = "record.json"
DONE = re.compile(r"\bxerj-done\b(.*)$")
PID = re.compile(r"\(pid (\d+)\)")


class XerjError(Exception):
    """xerj missing, down, slow or answering what this module cannot read: its one-line reason."""


# --- where it lives ---

def home() -> Path:
    return paths.brain_home() / "code-index" / "xerj"


def binary() -> Path:
    return home() / "bin" / ("xerj.exe" if os.name == "nt" else "xerj")


def data_dir() -> Path:
    return home() / "data"


def state_dir(repo: str) -> Path:
    return home() / "state" / repo


def snapshot_dir(repo: str) -> Path:
    return home() / "snapshots" / repo


def installed() -> bool:
    """The binary is where the owner puts it."""
    return binary().is_file()


def _argv() -> list[str]:
    """The command that runs xerj (the tests put a stand-in here)."""
    return [str(binary())]


def _env() -> dict:
    return dict(os.environ, **ENV)


def prefix(repo: str) -> str:
    """The index prefix of ``repo``: ``bx`` and its name's lowercase letters and digits. xerj searches a prefix as
    ``<prefix>-*``, so no prefix may be another's followed by a dash: none here has a dash."""
    return "bx" + re.sub(r"[^a-z0-9]", "", repo.lower())


def clashes(names) -> dict[str, list[str]]:
    """{prefix: the names sharing it} for the prefixes two or more of ``names`` share (``acme-data`` and
    ``acme_data``): their indices would mix, so neither is indexed nor searched."""
    by: dict[str, list[str]] = {}
    for n in names:
        by.setdefault(prefix(n), []).append(n)
    return {p: ns for p, ns in by.items() if len(ns) > 1}


# --- running it ---

def _exec(args: list[str], timeout: float) -> tuple[int | None, str]:
    """(exit code, stdout then stderr) of xerj ``args``; exit code None when it did not end in ``timeout`` (killed).
    The output goes through a file: a node started detached never holds a pipe of ours open."""
    if not installed():
        raise XerjError(f"xerj is not installed ({binary().as_posix()}; docs/code-index.md)")
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            p = subprocess.run([*_argv(), *args], stdin=subprocess.DEVNULL, stdout=out, stderr=err, env=_env(),
                               timeout=timeout, creationflags=stacks._no_window())
            code = p.returncode
        except subprocess.TimeoutExpired:
            code = None
        except OSError as exc:
            raise XerjError(f"xerj does not start: {exc}") from exc
        text = []
        for f in (out, err):
            f.seek(0)
            text.append(f.read().decode("utf-8", "replace"))
    return code, "".join(text)


def _useful(text: str) -> str:
    """The line that says why: the last ``error``-like one, else the last non-empty one."""
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    errors = [x for x in lines if re.search(r"\berror\b|failed|refused", x, re.I)]
    return (errors or lines or [""])[-1][:300]


def answers(url: str = URL, timeout: float = PROBE_TIMEOUT) -> bool:
    """True when the node answers at ``url`` (no proxy: it is local)."""
    return not stacks._probe_url(url + "/", timeout)


# --- the service: brain index --backend xerj --serve / --stop (a stack's start and stop) ---

def serve_args() -> list[str]:
    """The node's arguments: detached, loopback, TLS and keys off, lexical embeddings, feedback off, its data dir."""
    return ["--detach", "--insecure", "--bind", "127.0.0.1", "--port", str(PORT), "--no-auto-port",
            "--embed-mode", "lexical", "--disable-feedback", "--data-dir", str(data_dir())]


def serve(out) -> int:
    """Start the node unless the engine's node runs; 0 once it answers (``xerj --detach`` returns once it serves).
    Another service answering on the port is left alone, and the start refused."""
    if running():
        print(f"xerj OK (already up at {URL})", file=out)
        return 0
    if answers():
        print(f"xerj FAILED: {URL} answers but not the engine's xerj (no live xerj of {binary().as_posix()} holds "
              f"{data_dir().as_posix()}): another service has the port; left alone", file=out)
        return 1
    try:
        data_dir().mkdir(parents=True, exist_ok=True)
        code, text = _exec(serve_args(), SERVE_TIMEOUT)
    except XerjError as exc:
        print(f"xerj FAILED: {exc}", file=out)
        return 1
    if code is None:
        print(f"xerj FAILED: no answer within {SERVE_TIMEOUT:g} s (its log: {(data_dir() / 'node.log').as_posix()})",
              file=out)
        return 1
    if code:
        print(f"xerj FAILED: exited {code}: {_useful(text)}", file=out)
        return 1
    pid = PID.search(text)
    print(f"xerj started ({'pid ' + pid.group(1) + ', ' if pid else ''}{URL}, data {data_dir().as_posix()})", file=out)
    return 0


def lock_pid() -> int | None:
    """The pid xerj's lock of the data dir names (``node.lock``, else ``node.lock.pid`` while the lock is held)."""
    for name in ("node.lock", "node.lock.pid"):
        try:
            text = (data_dir() / name).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if text.isdigit():
            return int(text)
    return None


def _exe_nt(pid: int) -> str:
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                               ctypes.POINTER(wintypes.DWORD)]
    h = k32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        code = wintypes.DWORD()
        if not k32.GetExitCodeProcess(h, ctypes.byref(code)) or code.value != 259:   # STILL_ACTIVE
            return ""
        buf, size = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
        return buf.value if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)) else ""
    finally:
        k32.CloseHandle(h)


def _exe(pid: int) -> str:
    """The program file of the live process ``pid`` ('' when there is none): its full path (Windows, Linux), else
    its name (``ps``)."""
    if os.name == "nt":
        return _exe_nt(pid)
    try:
        return os.readlink(f"/proc/{pid}/exe")
    except OSError:
        pass
    try:
        p = subprocess.run(["ps", "-p", str(pid), "-o", "comm="], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return p.stdout.strip()


def _ours(exe: str) -> bool:
    """``exe`` is the engine's xerj binary (by its path; by its name where only a name is known)."""
    if not exe:
        return False
    if not os.path.isabs(exe):
        return Path(exe).name == binary().name
    return os.path.normcase(os.path.realpath(exe)) == os.path.normcase(os.path.realpath(binary()))


def running() -> bool:
    """The engine's node runs: the lock of its data dir names a live process of its binary, and the port answers
    (not another service on it)."""
    pid = lock_pid()
    return pid is not None and _ours(_exe(pid)) and answers()


def _kill(pid: int, force: bool) -> None:
    if os.name == "nt":   # a detached node has no console: only a forced stop ends it (xerj's own hub stop too)
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=30,
                       creationflags=stacks._no_window())
    else:
        os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)


_clock = time.monotonic
_sleep = time.sleep


def stop(out) -> int:
    """Stop the node of the engine's data dir: its lock's pid, checked to be a live process of the engine's binary
    before each signal. POSIX: SIGTERM (its graceful stop), SIGKILL after STOP_TIMEOUT; Windows: forced at once."""
    pid = lock_pid()
    if pid is None:
        if answers():
            print(f"xerj left alone: a node answers at {URL} but {data_dir().as_posix()} holds no lock (not the "
                  "engine's node)", file=out)
            return 1
        print("xerj is not running", file=out)
        return 0
    exe = _exe(pid)
    if not exe:
        print(f"xerj is not running (pid {pid} of its lock is gone)", file=out)
        return 0
    if not _ours(exe):
        print(f"xerj left alone: pid {pid} of its lock is {exe}, not {binary().as_posix()}", file=out)
        return 1
    t0 = _clock()
    for force in ((True,) if os.name == "nt" else (False, True)):
        if not _ours(_exe(pid)):   # ended, or its pid now another program's: never signalled
            break
        try:
            _kill(pid, force)
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"xerj FAILED: cannot stop pid {pid}: {exc}", file=out)
            return 1
        deadline = _clock() + STOP_TIMEOUT
        while _ours(_exe(pid)) and _clock() < deadline:
            _sleep(0.5)
        if not _ours(_exe(pid)):
            print(f"xerj stopped (pid {pid}, {round(_clock() - t0)} s{', forced' if force else ''})", file=out)
            return 0
    if not _ours(_exe(pid)):
        print(f"xerj stopped (pid {pid}, {round(_clock() - t0)} s)", file=out)
        return 0
    print(f"xerj FAILED: pid {pid} still runs after a forced stop", file=out)
    return 1


# --- indexing ---

def snapshot(path: Path, sha: str, dest: Path) -> None:
    """``dest`` replaced by the files of commit ``sha`` of the checkout ``path`` (``git archive``; the repo is only
    read). XerjError on any failure (git, the disk, a path too long), never a traceback."""
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
            tar = Path(tmp) / "snapshot.tar"
            try:
                p = subprocess.run(["git", "-C", str(path), "archive", "--format=tar", "-o", str(tar), sha],
                                   capture_output=True, text=True, timeout=SNAPSHOT_TIMEOUT,
                                   creationflags=stacks._no_window())
            except subprocess.TimeoutExpired as exc:
                raise XerjError(f"git archive of {path.as_posix()}: no end within {SNAPSHOT_TIMEOUT:g} s") from exc
            if p.returncode:
                raise XerjError(f"git archive of {path.as_posix()} exited {p.returncode}: {_useful(p.stderr)}")
            new = Path(tmp) / "tree"
            new.mkdir()
            extract(tar, new)
            if dest.exists():
                shutil.rmtree(dest)
            new.rename(dest)
    except (OSError, tarfile.TarError) as exc:
        raise XerjError(f"snapshot of {path.as_posix()} into {dest.as_posix()}: {exc}") from exc


def extract(tar: Path, into: Path) -> list[str]:
    """Extract the regular files and folders of ``tar`` into ``into``; a link, an absolute or drive path, or a name
    with ``..`` is skipped (the names skipped)."""
    safe = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
    skipped = []
    with tarfile.open(tar) as t:
        for m in t.getmembers():
            name = Path(m.name)
            if (m.isfile() or m.isdir()) and not name.is_absolute() and ".." not in name.parts and ":" not in m.name:
                t.extract(m, into, **safe)
            elif m.type != tarfile.XGLTYPE:   # git archive's pax header holds the commit, not a file
                skipped.append(m.name)
    return skipped


def done_line(text: str) -> dict:
    """The ``key=value`` fields of the last ``xerj-done`` line ({} when there is none)."""
    found = {}
    for line in text.splitlines():
        m = DONE.search(line)
        if m:
            found = dict(kv.split("=", 1) for kv in m.group(1).split() if "=" in kv)
    return found


def outcome(code: int | None, text: str, timeout: float = INDEX_TIMEOUT) -> tuple[dict, str]:
    """(the done line's fields, '') for a finished ``xerj autoindex``, else (.., why not)."""
    done = done_line(text)
    if code is None:
        return done, f"no end within {timeout:g} s (killed)"
    if code == 4:
        return done, ("xerj asks a decision (exit 4: its disk budget or a reduced plan); run its xerj autoindex by "
                      "hand to read it")
    if code not in (0, 3):
        return done, f"exited {code}: {_useful(text)}"
    if not done:
        return done, f"exited {code} without its xerj-done line (not xerj's answer): {_useful(text) or 'no output'}"
    if done.get("ok") == "false":
        return done, f"not ok ({done.get('reason', 'no reason given')})"
    if done.get("code_files", "0") != "0" and done.get("code_files_indexed") == "0":
        return done, f"no code file indexed of {done['code_files']}"
    return done, ""


def index(path: Path, repo: str, sha: str) -> dict:
    """Index commit ``sha`` of the checkout ``path`` as ``repo``: its snapshot, then ``xerj autoindex`` under its
    prefix. ``--no-graph``: such a journal reconciles added, changed, deleted and renamed files on every run, where a
    graph-enabled one answers ``stale-resume-plan`` once a file needs a new dataset (xerj's resume policy); ``xerj
    search`` does not read the link layer. The done line's fields; XerjError on any failure."""
    snap = snapshot_dir(repo)
    snapshot(path, sha, snap)
    try:
        state_dir(repo).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise XerjError(f"state folder {state_dir(repo).as_posix()}: {exc}") from exc
    code, text = _exec(["autoindex", str(snap), "--url", URL, "--prefix", prefix(repo), "--state-dir",
                        str(state_dir(repo)), "--no-graph", "--max-minutes", "0", "--progress", "plain"],
                       INDEX_TIMEOUT)
    done, why = outcome(code, text, INDEX_TIMEOUT)
    if why:
        raise XerjError(why)
    return done


# --- its record ---

def record_file() -> Path:
    return home() / RECORD


def read_record() -> dict:
    try:
        data = json.loads(record_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(repo: str, entry: dict) -> None:
    f = record_file()
    data = read_record()
    data[repo] = entry
    f.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=f.parent, prefix=".record-", suffix=".tmp")   # one per writer
    with os.fdopen(fd, "w", encoding="utf-8") as w:
        w.write(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    os.replace(tmp, f)


# --- searching ---

def _rel(path: str, root: Path | None) -> str:
    p = path.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    if root is not None:
        base = root.as_posix().rstrip("/") + "/"
        if p.lower().startswith(base.lower()):
            p = p[len(base):]
    return p


def _int(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def rows(answer, root: Path | None = None) -> list[dict]:
    """The adapter's search rows of ``xerj search --json``'s answer, in its order: rank, path (relative to the
    indexed folder, '/'-separated), line (the matched line, else the passage's or symbol's first; None when none),
    name and kind (a symbol's, '' for a file), score. XerjError when it is not the answer xerj writes."""
    hits = answer.get("hits", {}).get("hits") if isinstance(answer, dict) and isinstance(answer.get("hits"), dict) \
        else None
    if not isinstance(hits, list):
        raise XerjError("xerj search answered what this module cannot read (no hits.hits list)")
    out = []
    for h in hits:
        row = _row(h, root)
        if row:
            out.append({"rank": len(out) + 1, **row})
    return out


def _row(hit, root: Path | None) -> dict | None:
    """One hit's row without its rank; None for a hit without a path."""
    src = hit.get("_source") if isinstance(hit, dict) else None
    if not isinstance(src, dict):
        return None
    path = src.get("ax_path") or src.get("path")
    if not isinstance(path, str) or not path:
        return None
    score = hit.get("_score")
    return {"path": _rel(path, root),
            "line": _int(hit.get("match_line")) or _int(src.get("line")) or _int(src.get("start_line")),
            "name": str(src.get("name") or ""), "kind": str(src.get("kind") or ""),
            "score": float(score) if isinstance(score, (int, float)) else 0.0, "backend": "xerj"}


def search(query: str, repo: str, k: int = 5, root: Path | None = None) -> list[dict]:
    """The ``k`` first rows of ``xerj search`` for ``query`` in ``repo``'s indices (:func:`rows`)."""
    if not query.strip() or query.lstrip().startswith("-"):
        raise XerjError("a query is words, and does not start with '-'")
    if not running():
        raise XerjError(f"the engine's xerj does not answer at {URL}; brain up xerj starts it")
    code, text = _exec(["search", "--url", URL, "--prefix", prefix(repo), "-k", str(int(k)), "--json",
                        "--disable-feedback", query.strip()], QUERY_TIMEOUT)
    if code is None:
        raise XerjError(f"xerj search: no answer within {QUERY_TIMEOUT:g} s (killed)")
    if code:
        raise XerjError(f"xerj search exited {code}: {_useful(text)}")
    start = text.find("{")   # stdout's JSON first; anything after it is stderr
    try:
        answer = json.JSONDecoder().raw_decode(text[start:])[0] if start >= 0 else None
    except ValueError:
        answer = None
    if not isinstance(answer, dict):
        raise XerjError("xerj search answered what this module cannot read (no JSON)")
    return rows(answer, snapshot_dir(repo) if root is None else root)[:k]


def files(found: list[dict]) -> list[str]:
    """The distinct paths of ``found``, in rank order (what a file recall reads)."""
    seen: list[str] = []
    for r in found:
        if r["path"] not in seen:
            seen.append(r["path"])
    return seen
