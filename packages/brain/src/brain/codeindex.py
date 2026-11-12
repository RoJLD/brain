"""The code index (wi-brain-code-index, spec 2026-11-02 §3.17, answer Q8): the platform's repos and the Brain
indexed in the local GitNexus, on demand, and ``brain health`` saying when an index is older than its branch.

projects.yaml declares the repos to index under each project's ``code_index:``, relative to the project's root, and
the stack that indexes them under its ``index:``::

  acme:
    root: ../demo
    code_index: [., ../acme-data, {path: ../trade-desk, branch: master}]   # branch: default origin/HEAD's
    stacks:
      gitnexus:
        ...
        index: {api: 'http://127.0.0.1:4747', container: gitnexus}   # store, timeout, embeddings: the defaults

GitNexus names a repo after its folder (a worktree counts as its main checkout) and keeps the index next to the
source, as ``<repo>/.gitnexus`` plus a line in ``.git/info/exclude``: indexing a checkout in place would write into
it. So ``brain index REPO...`` (``--all``: every declared repo) reads the repo's branch on the host with ``git bundle
create`` (the repo is only read), streams the bundle into the GitNexus container, where a clone in GitNexus's own
store (``/data/gitnexus/repos/<name>``, where its URL clones go) is reset to it, then asks GitNexus to analyze that
clone (``POST /api/analyze``, force and embeddings, as the fork's reindex.ps1 does) and waits for the job. The
indexed commit, the time it took, GitNexus's counts (per node label and edge type, by Cypher through its MCP tool,
which also checks that MCP answers) and the size of the index are recorded in ``<BRAIN_HOME>/code-index.json``. ``--stale`` keeps only the repos that are not indexed at
their branch head. ``brain index`` alone prints each repo's state and changes nothing.

``brain health code-index`` (and ``brain health --all``) reports STALE when a repo's branch moved past its indexed
commit, it was never indexed, or GitNexus no longer lists it; exit code 1 then. No hook and no schedule (the owner,
2026-11-02): a repo is reindexed after a merge, or when brain health says so.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import net, paths, projects, stacks

CHECK = "code-index"
NAME = re.compile(r"^[A-Za-z0-9._-]+$")  # GitNexus's REPO_NAME_PATTERN, for the clone's folder
INDEX_KEYS = {"api", "container", "store", "timeout", "embeddings"}
STORE = "/data/gitnexus/repos"
TIMEOUT = 2400.0  # GitNexus fails an analyze job after 30 min
SNAPSHOT_TIMEOUT, GIT_TIMEOUT, URL_TIMEOUT, QUERY_TIMEOUT = 600.0, 30.0, 10.0, 120.0
POLL = 2.0
RECORD = "code-index.json"
SERVICE = "gitnexus"   # its breaker in brain.net (the REST API and the MCP endpoint)
SHORT_TIMEOUT = 120.0  # a docker command that times out within this opens the docker breaker (a longer one: a job)
# Reset GitNexus's clone $2/$1 to branch $3 of the bundle read on stdin; prints the clone's HEAD. One line: the
# argument goes through the Windows command line.
SNAPSHOT = ("set -e; b=/tmp/brain-index-$1.bundle; trap 'rm -f \"$b\"' EXIT; cat > \"$b\"; d=$2/$1; mkdir -p \"$2\"; "
            "[ -d \"$d/.git\" ] || git init -q -b \"$3\" \"$d\"; "
            "git -C \"$d\" fetch -q --no-tags \"$b\" \"+refs/heads/$3:refs/brain/snapshot\"; "
            "git -C \"$d\" checkout -q --force -B \"$3\" refs/brain/snapshot; "
            "git -C \"$d\" clean -qfdx -e .gitnexus; git -C \"$d\" rev-parse HEAD")
COUNTS = {"labels": "MATCH (n) RETURN label(n) AS k, count(*) AS n",
          "edge_types": "MATCH ()-[r:CodeRelation]->() RETURN r.type AS k, count(*) AS n"}


class CodeIndexError(Exception):
    """A declaration error: unknown repo, bad code_index or index key (exit code 2)."""


@dataclass
class Indexer:
    stack: stacks.Stack
    api: str
    container: str
    store: str = STORE
    timeout: float = TIMEOUT
    embeddings: bool = True

    def target(self, name: str) -> str:
        return f"{self.store}/{name}"


@dataclass
class Repo:
    name: str
    project: str
    path: Path
    branch: str = ""  # '' = the branch origin/HEAD names, else the checked-out one


@dataclass
class State:
    repo: Repo
    branch: str
    head: str
    state: str  # OK, STALE, NOT INDEXED, MISSING (GitNexus lost it), ERROR (the repo cannot be read)
    why: str = ""


# Side effects, replaced by fakes in the tests (git runs for real on the tests' repos).

def _exec(argv: list[str], timeout: float, stdin: Path | None = None) -> tuple[int | None, str]:
    """(exit code, stdout and stderr) of ``argv``, ``stdin`` read from a file; None when it did not finish."""
    try:
        with (open(stdin, "rb") if stdin else contextlib.nullcontext(subprocess.DEVNULL)) as f:
            p = subprocess.run(argv, stdin=f, capture_output=True, timeout=timeout, creationflags=stacks._no_window())
    except subprocess.TimeoutExpired:
        return None, ""
    except OSError as exc:
        return 127, str(exc)
    return p.returncode, (p.stdout + p.stderr).decode("utf-8", "replace")


def _git(path: Path, *args: str, timeout: float = GIT_TIMEOUT) -> tuple[int | None, str]:
    return _exec(["git", "-C", str(path), *args], timeout)


def _docker(argv: list[str], timeout: float, stdin: Path | None = None) -> tuple[int | None, str]:
    """``_exec`` of a docker command under the docker breaker (brain.net): a short command that times out opens it
    (a long job past its time is the job's, not a daemon down), and while it is open the call is skipped as (127,
    the line that says so)."""
    why = net.blocked("docker")
    if why:
        return 127, why
    resolved = stacks._resolve(argv)
    if not resolved:
        return 127, f"{argv[0]} not found"
    code, out = _exec(resolved, timeout, stdin)
    if code is None and timeout <= SHORT_TIMEOUT:
        net.failed("docker", "timed out")
    else:
        net.ok("docker")
    return code, out


def _http(method: str, url: str, body: dict | None = None, timeout: float = URL_TIMEOUT) -> tuple[int, object]:
    """(HTTP status, the JSON body, else its text); status 0 when the server did not answer. No proxy: local."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def go() -> tuple[int, object]:
        with opener.open(req, timeout=timeout) as r:
            return r.status, _json(r.read())
    # under GitNexus's breaker: a refused connection retried (a POST only when surely not handled), a timeout or a
    # skip said as status 0; a job's poll is retried but never opens it (one slow answer while it analyzes)
    poll = method == "GET" and "/api/analyze/" in url
    try:
        return net.call(SERVICE, go, idempotent=method == "GET", breaker=not poll)
    except urllib.error.HTTPError as exc:
        return exc.code, _json(exc.read())
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return 0, str(getattr(exc, "reason", exc)) or type(exc).__name__


def _mcp_tool(url: str, name: str, arguments: dict, timeout: float = QUERY_TIMEOUT) -> tuple[str, str]:
    """(the text of MCP tool ``name``'s answer, '') from the StreamableHTTP endpoint ``url``, else ('', why not). One
    session per call, ended with DELETE."""
    why = net.blocked(SERVICE)
    if why:
        return "", why
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    session = ""

    def post(body: dict, method: str = "POST") -> dict:
        nonlocal session
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if session:
            headers["mcp-session-id"] = session
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8") if body else None, headers=headers,
                                     method=method)
        with opener.open(req, timeout=timeout) as r:
            session = r.headers.get("mcp-session-id") or session
            raw = r.read().decode("utf-8", "replace").strip()
        if raw and not raw.startswith("{"):  # an event stream: the last data line holds the answer
            raw = ([ln[5:].strip() for ln in raw.splitlines() if ln.startswith("data:")] or [""])[-1]
        return json.loads(raw) if raw else {}

    try:
        post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                         "clientInfo": {"name": "brain-index", "version": "1"}}})
        post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        res = post({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
    except urllib.error.HTTPError as exc:
        net.ok(SERVICE)
        return "", f"HTTP {exc.code}"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        if net.down(exc):
            net.failed(SERVICE, exc)
        return "", str(getattr(exc, "reason", exc)) or type(exc).__name__
    finally:
        if session:
            with contextlib.suppress(urllib.error.URLError, OSError, ValueError):
                post({}, "DELETE")
    net.ok(SERVICE)
    result = res.get("result") or {}
    text = "".join(c.get("text", "") for c in result.get("content") or [] if isinstance(c, dict))
    if res.get("error") or result.get("isError"):
        return "", stacks.useful_line(text or json.dumps(res.get("error")))
    return text, ""


def _json(raw: bytes) -> object:
    text = raw.decode("utf-8", "replace")
    try:
        return json.loads(text)
    except ValueError:
        return text


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_clock = time.monotonic
_sleep = time.sleep


# The declarations and the record.

def _indexer(s: stacks.Stack) -> Indexer:
    d, where = s.index, f"stack {s.name!r} ({s.project}) index"
    unknown = set(d) - INDEX_KEYS
    if unknown:
        raise CodeIndexError(f"{where}: unknown key(s) {', '.join(sorted(unknown))} "
                             f"(known: {', '.join(sorted(INDEX_KEYS))})")
    if not d.get("api") or not d.get("container"):
        raise CodeIndexError(f"{where}: api and container are required")
    return Indexer(s, str(d["api"]).rstrip("/"), str(d["container"]), str(d.get("store", STORE)).rstrip("/"),
                   float(d.get("timeout", TIMEOUT)), bool(d.get("embeddings", True)))


def _repo_path(path: Path) -> Path:
    """A worktree's main checkout (GitNexus names the repo after the folder), else ``path``."""
    main = paths.main_checkout(path) if path.is_dir() else None
    return main.resolve() if main else path


def load(root: Path | None = None) -> tuple[Indexer | None, dict[str, Repo]]:
    """The indexing stack (None when no stack declares index:) and the declared repos, in declaration order."""
    try:
        reg = stacks.load(root)
    except stacks.StackError as exc:
        raise CodeIndexError(str(exc)) from exc
    found = [s for s in reg.values() if s.index]
    if len(found) > 1:
        raise CodeIndexError(f"index: is declared by several stacks ({', '.join(s.name for s in found)}); one indexes")
    ix = _indexer(found[0]) if found else None
    repos: dict[str, Repo] = {}
    for p in projects.load(root).values():
        for entry in p.code_index:
            if isinstance(entry, str):
                rel, branch = entry, ""
            elif isinstance(entry, dict) and entry.get("path") and set(entry) <= {"path", "branch"}:
                rel, branch = str(entry["path"]), str(entry.get("branch") or "")
            else:
                raise CodeIndexError(f"project {p.name}: a code_index entry is a path or {{path, branch}}")
            path = _repo_path(projects._resolve_root(rel, p.root))   # from the root, else its main checkout
            if not NAME.match(path.name):
                raise CodeIndexError(f"project {p.name}: {path.name!r}: GitNexus names a repo after its folder, "
                                     "letters, digits, '.', '_' and '-'")
            if path.name in repos:
                raise CodeIndexError(f"code_index: {path.name} is declared by {repos[path.name].project} and {p.name} "
                                     "(GitNexus names a repo after its folder)")
            repos[path.name] = Repo(path.name, p.name, path, branch)
    if repos and ix is None:
        raise CodeIndexError("code_index: is declared but no stack declares index: (the GitNexus stack)")
    return ix, repos


def record_file() -> Path:
    return paths.brain_home() / RECORD


def read_record() -> dict:
    try:
        data = json.loads(record_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(name: str, entry: dict) -> None:
    f = record_file()
    data = read_record()
    data[name] = entry
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, f)


# State.

def _default_branch(path: Path) -> str:
    code, out = _git(path, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if code == 0 and "/" in out.strip():
        return out.strip().split("/", 1)[1]
    code, out = _git(path, "rev-parse", "--abbrev-ref", "HEAD")
    return out.strip() if code == 0 and out.strip() != "HEAD" else ""


def head(r: Repo) -> tuple[str, str, str]:
    """(branch, its commit, '') for ``r`` on the host, else (branch, '', why it cannot be read)."""
    if not (r.path / ".git").exists():
        return r.branch, "", f"{r.path.as_posix()} is not a git checkout"
    branch = r.branch or _default_branch(r.path)
    if not branch:
        return "", "", "no origin/HEAD and a detached HEAD: declare its branch in code_index"
    code, out = _git(r.path, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}^{{commit}}")
    sha = out.strip() if code == 0 else ""
    return branch, sha, "" if sha else f"no branch {branch} in {r.path.as_posix()}"


def registry(ix: Indexer) -> list | None:
    """GitNexus's indexed repos (``/api/repos``), None when it does not answer."""
    status, body = _http("GET", f"{ix.api}/api/repos")
    return body if status == 200 and isinstance(body, list) else None


def _entry(entries: list | None, ix: Indexer, name: str) -> dict | None:
    return next((e for e in entries or [] if isinstance(e, dict) and e.get("path") == ix.target(name)), None)


def state(ix: Indexer, r: Repo, rec: dict | None, entries: list | None) -> State:
    """The state of ``r``'s index; GitNexus's registry is checked when ``entries`` is not None."""
    branch, sha, why = head(r)
    if why:
        return State(r, branch, sha, "ERROR", why)
    if not rec or not rec.get("sha"):
        return State(r, branch, sha, "NOT INDEXED", f"{branch}@{sha[:7]}")
    if rec["sha"] != sha:
        code, out = _git(r.path, "rev-list", "--count", f"{rec['sha']}..{sha}")
        n = out.strip() if code == 0 else ""
        moved = f"{n} commit{'' if n == '1' else 's'} past" if n.isdigit() and n != "0" else "moved off"
        return State(r, branch, sha, "STALE", f"{branch} is {moved} the index ({rec['sha'][:7]})")
    if entries is not None:
        e = _entry(entries, ix, r.name)
        if e is None:
            return State(r, branch, sha, "MISSING", "GitNexus no longer lists it (its volume reset?)")
        if e.get("lastCommit") and e["lastCommit"] != sha:
            return State(r, branch, sha, "STALE", f"GitNexus's index is at {str(e['lastCommit'])[:7]}")
    return State(r, branch, sha, "OK", f"{branch}@{sha[:7]}, indexed {str(rec.get('indexed_at', '?'))[:16]}")


def _line(s: State) -> str:
    if s.state == "OK":
        return f"{s.repo.name} OK ({s.why})"
    hint = "" if s.state == "ERROR" else f"; brain index {s.repo.name}"
    return f"{s.repo.name} {s.state}: {s.why}{hint}"


# Indexing.

def _secs(t0: float) -> str:
    return f"{round(_clock() - t0)} s"


def _error(status: int, body: object) -> str:
    text = body.get("error") if isinstance(body, dict) else body
    return (f"HTTP {status}: " if status else "") + (stacks.useful_line(str(text or "")) or "no answer")


def snapshot(ix: Indexer, r: Repo, branch: str, sha: str) -> str:
    """Reset GitNexus's clone of ``r`` to ``branch`` at ``sha``: '' when done, else why not."""
    bundle = paths.brain_home() / "code-index" / f"{r.name}.bundle"
    bundle.parent.mkdir(parents=True, exist_ok=True)
    try:
        code, out = _git(r.path, "bundle", "create", str(bundle), f"refs/heads/{branch}", timeout=SNAPSHOT_TIMEOUT)
        if code != 0:
            return f"git bundle create {'did not finish' if code is None else f'exited {code}'}: " \
                   f"{stacks.useful_line(out)}"
        code, out = _docker(["docker", "exec", "-i", ix.container, "sh", "-c", SNAPSHOT, "sh", r.name, ix.store,
                             branch], SNAPSHOT_TIMEOUT, stdin=bundle)
        if code is None:
            return f"snapshot: no answer in {SNAPSHOT_TIMEOUT:g} s"
        if code:
            return f"snapshot exited {code}: {stacks.useful_line(out)}"
        got = (out.strip().splitlines() or [""])[-1].strip()
        return "" if got == sha else f"snapshot: GitNexus's clone is at {got[:7] or '?'}, not {sha[:7]}"
    finally:
        with contextlib.suppress(OSError):
            bundle.unlink()


def analyze(ix: Indexer, r: Repo) -> str:
    """Have GitNexus analyze its clone of ``r`` and wait for the job: '' when complete, else why not."""
    status, body = _http("POST", f"{ix.api}/api/analyze",
                         {"path": ix.target(r.name), "force": True, "embeddings": ix.embeddings})
    if status != 202 or not isinstance(body, dict) or not body.get("jobId"):
        return f"POST /api/analyze: {_error(status, body)}"
    job_id, deadline = body["jobId"], _clock() + ix.timeout
    while True:
        status, job = _http("GET", f"{ix.api}/api/analyze/{job_id}")
        if status == 200 and isinstance(job, dict):
            if job.get("status") == "complete":
                return ""
            if job.get("status") == "failed":
                return f"analyze failed: {stacks.useful_line(str(job.get('error') or 'no reason given'))}"
        elif status:  # an answer other than the job: it is gone (the server restarted?)
            return f"GET /api/analyze/{job_id}: {_error(status, job)}"
        if _clock() >= deadline:
            return f"analyze not complete after {ix.timeout:g} s (job {job_id} left running)"
        _sleep(POLL)


def _table(text: str) -> dict:
    """{first column: second column} of the markdown table in the MCP cypher tool's answer, largest first."""
    try:
        md = json.loads(text.split("\n\n---", 1)[0]).get("markdown") or ""
    except (ValueError, AttributeError):
        return {}
    out = {}
    for ln in md.splitlines()[2:]:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) == 2 and cells[1].isdigit():
            out[cells[0]] = int(cells[1])
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def measure(ix: Indexer, name: str) -> dict:
    """GitNexus's counts per node label and edge type, and the index's size: what can be read, best effort. The
    counts go through the MCP cypher tool, which opens the index read-only: a REST /api/query read leaves an
    unreplayed lbug.wal and lbug.shadow when the server evicts its connection, and MCP then cannot open the index."""
    out: dict = {}
    for key, cypher in COUNTS.items():
        text, why = _mcp_tool(f"{ix.api}/api/mcp", "cypher", {"repo": name, "query": cypher})
        if why:
            out["mcp_error"] = why
            break
        if _table(text):
            out[key] = _table(text)
    code, text = _docker(["docker", "exec", ix.container, "du", "-sk", f"{ix.target(name)}/.gitnexus"], 60)
    first = (text.split() or [""])[0]
    if code == 0 and first.isdigit():
        out["size_kb"] = int(first)
    return out


def index_one(ix: Indexer, r: Repo) -> tuple[bool, str]:
    t0 = _clock()
    branch, sha, why = head(r)
    why = why or snapshot(ix, r, branch, sha) or analyze(ix, r)
    if not why:
        e = _entry(registry(ix), ix, r.name)
        if e is None:
            why = f"analyze complete but GitNexus does not list {ix.target(r.name)}"
        elif e.get("lastCommit") and e["lastCommit"] != sha:
            why = f"GitNexus indexed {str(e['lastCommit'])[:7]}, not {sha[:7]}"
    if why:
        return False, f"{r.name} FAILED ({_secs(t0)}): {why}"
    secs = round(_clock() - t0)
    stats = e.get("stats") or {}
    extra = measure(ix, r.name)
    _save(r.name, {"project": r.project, "path": r.path.as_posix(), "branch": branch, "sha": sha,
                   "indexed_at": _now(), "seconds": secs, "embeddings": ix.embeddings,
                   "gitnexus": {"name": e.get("name"), "path": ix.target(r.name), "indexed_at": e.get("indexedAt")},
                   "stats": stats, **extra})
    parts = [f"{secs} s", f"{branch}@{sha[:7]}"] + [f"{stats[k]} {k}" for k in ("files", "nodes", "edges",
                                                                                 "embeddings") if k in stats]
    if "size_kb" in extra:
        parts.append(f"{extra['size_kb'] / 1024:.1f} MB")
    mcp = f"; MCP does not answer: {extra['mcp_error']}" if "mcp_error" in extra else ""
    return True, f"{r.name} OK ({', '.join(parts)}){mcp}"


# Commands.

def of_project(repos: dict[str, Repo], project: str | None) -> dict[str, Repo]:
    """The repos ``project`` declares under code_index: (every one when ``project`` is None)."""
    return {k: r for k, r in repos.items() if project is None or r.project == project}


def run(names: list[str], every: bool = False, stale: bool = False, root: Path | None = None, out=None,
        project: str | None = None) -> int:
    """``brain index``: the state of each repo (no name, no flag), else index the named, every or stale ones; only
    ``project``'s with ``--project``."""
    out = out or sys.stdout
    ix, repos = load(root)
    repos = of_project(repos, project)
    unknown = [n for n in names if n not in repos]
    if unknown:
        raise CodeIndexError(f"unknown repo(s) {', '.join(unknown)} (declared under code_index"
                             f"{' of ' + project if project else ''}: {', '.join(repos) or 'none'})")
    if not repos:
        print(f"no repo declared under code_index: {'of ' + project if project else 'in projects.yaml'}", file=out)
        return 0
    rec = read_record()
    if not (names or every or stale):
        entries = registry(ix)
        for r in repos.values():
            print(_line(state(ix, r, rec.get(r.name), entries)), file=out, flush=True)
        if entries is None:
            print(f"({ix.stack.name} does not answer at {ix.api}: its registry was not checked)", file=out)
        return 0
    why = stacks.check(ix.stack)
    if why:
        print(f"brain index: {ix.stack.name} is down ({why}); brain up {ix.stack.name} starts it", file=out)
        return 1
    chosen = [repos[n] for n in names] if names else list(repos.values())
    if stale:
        entries = registry(ix)
        chosen = [r for r in chosen if state(ix, r, rec.get(r.name), entries).state != "OK"]
        if not chosen:
            print("every repo is indexed at its branch head", file=out)
            return 0
    rc = 0
    for r in chosen:
        ok, line = index_one(ix, r)
        print(line, file=out, flush=True)
        rc = rc or (0 if ok else 1)
    return rc


def health(root: Path | None = None, out=None, named: bool = True, project: str | None = None) -> int:
    """``brain health code-index``: one line; exit 1 when a repo is not indexed at its branch head. Silent when no
    repo is declared and the check was not ``named`` (``brain health --all``). Only ``project``'s repos with
    ``--project``."""
    out = out or sys.stdout
    ix, repos = load(root)
    repos = of_project(repos, project)
    if not repos:
        if named:
            print(f"{CHECK} OK (no repo declared under code_index:)", file=out)
        return 0
    rec, entries = read_record(), registry(ix)
    states = [state(ix, r, rec.get(r.name), entries) for r in repos.values()]
    bad = [s for s in states if s.state != "OK"]
    note = "" if entries is not None else f"; {ix.stack.name} does not answer: its registry was not checked"
    if not bad:
        print(f"{CHECK} OK ({len(states)} repo(s) indexed at their branch head{note})", file=out, flush=True)
        return 0
    short = {"NOT INDEXED": "not indexed", "MISSING": "lost by GitNexus"}
    print(f"{CHECK} STALE: " + ", ".join(f"{s.repo.name} ({short.get(s.state, s.why)})" for s in bad)
          + f"; brain index --stale reindexes {'it' if len(bad) == 1 else 'them'}{note}", file=out, flush=True)
    return 1


def main(names: list[str], every: bool = False, stale: bool = False, root: Path | None = None,
         project: str | None = None) -> int:
    try:
        return run(names, every, stale, root, project=project)
    except CodeIndexError as exc:
        print(f"brain index: {exc}", file=sys.stderr)
        return 2
