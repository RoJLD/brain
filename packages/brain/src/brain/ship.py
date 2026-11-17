"""``brain ship``: a local merge queue, built on the merge gate (brain.mergeready). A session queues its PR and
stops; one merger, holding a lock, catches each PR up with main, checks it and merges it, so that no session races
main any more (before it, a median 0.8 min between a PR's last catch-up and its merge, and PRs that lost that race
twice or more).

- **The queue**: ``<BRAIN_HOME>/ship/queue.json``, one entry per PR keyed by its GitHub repo and number (queuing the
  same PR twice keeps one entry; one that failed or was refused goes back to queued). An entry names the repo's main
  checkout (a session's worktree may be gone by the time the merger runs), the remote, the PR's title and branch as
  gh last read them, and its state: ``queued``, ``running``, ``merged``, ``failed``, ``refused`` or ``culprit``,
  with the reason. Each change is a read, an edit and an atomic write under the short lock ``ship-queue``
  (brain.filelock), so two sessions queuing at once both land; the finished entries past the last
  :data:`KEEP_FINISHED` of a repo are dropped. The file also keeps, per repo and base, a main whose last full suite
  was red (``red``): its PRs wait until a run with ``--force`` (or a green suite) clears it.
- **The merger** (``brain ship --run``): takes the lock ``ship`` (brain.filelock: one merger per machine; a second
  one is refused with the holder; the lock renewed by a heartbeat), sweeps the scratch worktrees a killed merger left,
  and takes the queued PRs in order (never a ``running`` entry a live merger holds). For each:

  1. the merge gate (brain.mergeready.gate, the gate's own function, gh read through this module's runner): every
     check it blocks refuses the PR, but ``fresh`` (main moved under the PR's files): catching main up is the
     merger's job. A PR from a fork, or whose branch is the base or the default branch, is refused: the merger
     pushes to the base repo's PR branch only;
  2. a scratch worktree of the PR's head (no checkout hook run); main merged into it when the head lacks it, with
     the repo's merge driver (a conflict it leaves fails the PR); in a repo with a graph store the views regenerated
     once and the store checked (``brain refresh --offline``, else ``brain check`` when nothing was merged); after a
     merge, ``brain merge-check`` (nothing of main lost);
  3. the targeted tests, ``brain test --changed <remote>/<base> --strict`` (a selection the evidence cannot answer
     runs the whole suite);
  4. after a catch-up, the new head is gated like any head: for a public repo the public check stamps it before the
     push (``brain check --public --history``), it is pushed to the PR's branch, its CI is awaited (green, or the PR
     fails), and the merge gate runs on it with no check waived (its review stamp carried only when it is git's own
     merge of the base into the reviewed head, brain.mergeready.carried_review); then the gate's stamp is written
     and ``gh pr merge N --match-head-commit <head>`` runs with the repo's allowed merge method, and the PR is read
     back: merged at that head, or failed while still open; any other answer stops the run.

  A PR that fails a step, or whose step raises, is marked failed with its reason and the merger goes on with the
  next. Every ``--batch`` PRs merged in a repo onto one base (5 by default), the full suite runs once on that base
  as it is then; when it fails, a bisection over the batch's merges finds the first one it fails from, confirmed
  (it fails again there and passes on its parent): that PR is the culprit; a failure that does not reproduce is
  flaky, one already there before the PR is main's own. Then the base is marked red and the run stops: main is
  never reverted by the merger, that is its owner's call. Every other pending batch is tested before the run ends
  (a smaller one too), and one that cannot be is marked ``untested``. Batches are counted per repo and base.
- ``--dry-run`` says what the merger would do, from the queue alone: no lock taken, no external call.

The merger's own external calls (git, gh, the Python that runs brain and pytest) go through one injectable
:class:`Runner`, with a timeout that stops the whole process tree, and never a credential prompt: a tool that is
missing (127), that does not answer in time (124) or that answers what cannot be read fails the PR it was for,
never the queue. The merge gate's own git calls are its own (brain.inventory.git). Starting the merger as a service
is the owner's decision: this module only provides the commands.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import filelock, paths, stateio

FOLDER = "ship"
QUEUE = "queue.json"
LOCK = "ship"               # the merger's lock (<BRAIN_HOME>/locks/ship.lock)
QUEUE_LOCK = "ship-queue"   # the queue file's short lock, around each read-edit-write
LOCK_TTL = 3600.0           # the merger's lock, renewed by a heartbeat every quarter of it
QUEUE_LOCK_TTL = 60.0
QUEUE_LOCK_WAIT = 15.0
BATCH = 5
KEEP_FINISHED = 50          # merged, failed or refused entries kept per repo, the newest
STATES = ("queued", "running", "merged", "failed", "refused", "culprit")
OPEN_STATES = ("queued", "running")
WAIVED = ("fresh",)         # the gate's checks the merger answers itself (by catching main up), on the PR's own head
GIT_TIMEOUT = 300
GH_TIMEOUT = 120
CHECK_TIMEOUT = 900
TEST_TIMEOUT = 3600
SUITE_TIMEOUT = 3600
CI_WAIT = 3600              # the caught-up head's CI awaited this long at most
CI_POLL = 30
SCRATCH = "brain-ship-"
NO_PROMPT = {"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never", "GIT_ASKPASS": "", "SSH_ASKPASS": "",
             "GH_PROMPT_DISABLED": "1"}
SHA = re.compile(r"[0-9a-f]{40}")
PR_URL = re.compile(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/(\d+)")
VIEW_FIELDS = "isCrossRepository,headRepositoryOwner"   # beside the gate's own (mergeready.FIELDS)
MERGE_METHODS = (("mergeCommitAllowed", "--merge"), ("squashMergeAllowed", "--squash"), ("rebaseMergeAllowed",
                                                                                         "--rebase"))


class ShipError(Exception):
    pass


class Stop(Exception):
    """An answer the merger cannot go on after (a merge whose outcome cannot be read): the run stops."""


# --- the runner: every external call of the merger --------------------------------------------------------------


@dataclass
class Result:
    rc: int
    out: str = ""
    err: str = ""

    @property
    def ok(self) -> bool:
        return self.rc == 0

    def why(self) -> str:
        text = (self.err or self.out).strip().splitlines()
        return " / ".join(text[-3:])[:400] if text else f"exit {self.rc}"


Runner = Callable[..., Result]   # (cmd, cwd, timeout, env=None) -> Result


def run(cmd: list[str], cwd: Path | None = None, timeout: float = GIT_TIMEOUT, env: dict | None = None) -> Result:
    """The default runner: ``cmd`` run in a process group of its own, with no credential prompt; at the timeout the
    whole tree is stopped (its grandchildren too: a test worker, a credential helper). 127 when it does not start,
    124 when it does not answer in time."""
    from .formats import _kill_tree
    group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                                env={**(os.environ if env is None else env), **NO_PROMPT}, **group)
    except (OSError, ValueError) as exc:
        return Result(127, "", f"{cmd[0]}: {exc}")
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        with contextlib.suppress(subprocess.TimeoutExpired, OSError, ValueError):
            proc.communicate(timeout=10)
        return Result(124, "", f"{Path(str(cmd[0])).name}: no answer in {int(timeout)} s (its process tree stopped)")
    return Result(proc.returncode, out or "", err or "")


def _gh() -> str:
    return shutil.which("gh") or "gh"


def _git() -> str:
    return shutil.which("git") or "git"


# --- the queue file ----------------------------------------------------------------------------------------------


def queue_path() -> Path:
    return paths.brain_home() / FOLDER / QUEUE


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _shape(data: dict) -> str:
    e = data.get("entries", [])
    if not isinstance(e, list) or not all(isinstance(x, dict) for x in e):
        return "entries is not a list of objects"
    if not isinstance(data.get("red", {}), dict):
        return "red is not an object"
    return ""


def _key(repo: str, pr: int) -> tuple[str, int]:
    return repo.lower(), int(pr)


def _base_key(repo: str, base: str) -> str:
    return f"{repo.lower()}@{base}"


def _load(aside: bool = False) -> stateio.State:
    return stateio.load(queue_path(), check=_shape, aside=aside)


def entries(repo: str = "") -> list[dict]:
    """The queue's entries, in order (only ``repo``'s when given); [] when there is no queue or it cannot be read."""
    rows = [e for e in _load().data.get("entries", []) if isinstance(e, dict) and e.get("repo") and e.get("pr")]
    return [e for e in rows if not repo or str(e["repo"]).lower() == repo.lower()]


def red() -> dict:
    """{repo@base: why its main's last full suite is red} as the queue file keeps it."""
    r = _load().data.get("red", {})
    return r if isinstance(r, dict) else {}


def _trim(rows: list[dict]) -> None:
    """Each repo's finished entries past its newest :data:`KEEP_FINISHED` dropped (a culprit is kept)."""
    seen: dict[str, int] = {}
    drop = set()
    for i in range(len(rows) - 1, -1, -1):
        e = rows[i]
        if e.get("status") in ("merged", "failed", "refused"):
            r = str(e.get("repo", "")).lower()
            seen[r] = seen.get(r, 0) + 1
            if seen[r] > KEEP_FINISHED:
                drop.add(i)
    rows[:] = [e for i, e in enumerate(rows) if i not in drop]


def _edit(change: Callable[[list[dict], dict], object]):
    """``change(entries, top)`` applied under the queue lock (``top``: the file's other keys), then written back
    atomically: its result."""
    lock = filelock.Lock(QUEUE_LOCK, QUEUE_LOCK_TTL, what="brain ship (the queue file)")
    lock.acquire(wait=QUEUE_LOCK_WAIT)
    try:
        st = _load(aside=True)
        top = {k: v for k, v in st.data.items() if k != "entries"}
        rows = list(st.data.get("entries", []))
        out = change(rows, top)
        _trim(rows)
        stateio.save(st, {**top, "entries": rows})
        return out
    finally:
        left = lock.release()
        if left:
            print(f"brain ship: warning: {left}", file=sys.stderr)


def place(rows: list[dict], repo: str, pr: int) -> tuple[int, int]:
    """(the PR's place among its repo's open entries, how many there are); place 0 when it is not open."""
    open_ = [_key(e["repo"], e["pr"]) for e in rows if str(e.get("repo", "")).lower() == repo.lower()
             and e.get("status") in OPEN_STATES]
    k = _key(repo, pr)
    return (open_.index(k) + 1 if k in open_ else 0), len(open_)


def enqueue(repo: str, pr: int, checkout: str, remote: str = "origin", title: str = "", branch: str = "",
            by: str = "") -> tuple[dict, bool, tuple[int, int]]:
    """(the entry, whether it was added or put back to queued, its place): the PR queued once."""
    def change(rows: list[dict], top: dict):
        k = _key(repo, pr)
        for e in rows:
            if _key(e["repo"], e["pr"]) == k:
                back = e.get("status") not in (*OPEN_STATES, "merged")
                e.update({"dir": checkout, "remote": remote, "updated": _now()}, **({"title": title} if title else {}),
                         **({"branch": branch} if branch else {}))
                if back:
                    e.update(status="queued", reason="", queued=_now())
                    e.pop("merger", None)
                return e, back, place(rows, repo, pr)
        e = {"repo": repo, "pr": int(pr), "dir": checkout, "remote": remote, "title": title, "branch": branch,
             "by": by, "queued": _now(), "updated": _now(), "status": "queued", "reason": ""}
        rows.append(e)
        return e, True, place(rows, repo, pr)
    return _edit(change)


def update(repo: str, pr: int, **fields) -> None:
    def change(rows: list[dict], top: dict):
        for e in rows:
            if _key(e["repo"], e["pr"]) == _key(repo, pr):
                e.update(fields, updated=_now())
    _edit(change)


def set_red(repo: str, base: str, why: dict | None) -> None:
    """The base of ``repo`` marked red (``why``: sha, detail, culprit) or cleared (None)."""
    def change(rows: list[dict], top: dict):
        reds = dict(top.get("red") or {})
        if why is None:
            reds.pop(_base_key(repo, base), None)
        else:
            reds[_base_key(repo, base)] = {**why, "at": _now()}
        top["red"] = reds
    _edit(change)


def _held_by_live(e: dict, token: str) -> bool:
    """Whether a ``running`` entry is held by another merger still alive on this host."""
    m = e.get("merger") if isinstance(e.get("merger"), dict) else {}
    if not m or m.get("token") == token or m.get("host") != filelock.host() or not isinstance(m.get("pid"), int):
        return False
    return filelock.pid_alive(m["pid"], str(m.get("pstart") or ""))


def next_open(skip: set, token: str = "") -> dict | None:
    """The first open entry not in ``skip`` (keys already taken this run) and not running under a live merger."""
    for e in entries():
        if e.get("status") not in OPEN_STATES or _key(e["repo"], e["pr"]) in skip:
            continue
        if e.get("status") == "running" and _held_by_live(e, token):
            continue
        return e
    return None


# --- the text views --------------------------------------------------------------------------------------------


def cell(text: object) -> str:
    """A Markdown table cell: one line, its pipes, backticks and HTML escaped (a title is someone's text)."""
    s = " ".join(str(text if text is not None else "").split())
    s = s.replace("\\", "\\\\").replace("|", "\\|").replace("`", "\\`").replace("<", "&lt;").replace(">", "&gt;")
    return s[:160] + "..." if len(s) > 160 else s


def table(rows: list[dict]) -> list[str]:
    out = ["| # | repo | PR | status | title | queued | reason |", "|---|---|---|---|---|---|---|"]
    for i, e in enumerate(rows, 1):
        out.append(f"| {i} | {cell(e.get('repo'))} | #{cell(e.get('pr'))} | {cell(e.get('status'))} | "
                   f"{cell(e.get('title'))} | {cell(e.get('queued'))} | {cell(e.get('reason'))} |")
    return out


def lock_holder() -> dict:
    """The merger's lock record when the lock file is there, else {}."""
    return filelock.Lock(LOCK, LOCK_TTL).holder()


# --- queuing a PR ----------------------------------------------------------------------------------------------


def parse_pr(text: str) -> tuple[str, int]:
    """(the slug a PR URL names or '', its number) of ``text``: a number, ``#N`` or a PR URL."""
    m = PR_URL.search(text or "")
    if m:
        return f"{m.group(1)}/{m.group(2)}", int(m.group(3))
    s = str(text or "").strip().lstrip("#")
    if not s.isdigit() or int(s) <= 0:
        raise ShipError(f"not a PR number or URL: {text!r}")
    return "", int(s)


def gh_json(runner: Runner, cmd: list[str], what: str, cwd: Path | None = None) -> dict:
    """A gh command's JSON answer through the runner: an object, else :class:`ShipError`."""
    r = runner([_gh(), *cmd], cwd, GH_TIMEOUT)
    if not r.ok:
        raise ShipError(f"{what}: {r.why()}")
    try:
        data = json.loads(r.out)
    except ValueError:
        raise ShipError(f"{what}: not JSON: {r.out.strip()[:120]!r}") from None
    if not isinstance(data, dict):
        raise ShipError(f"{what}: not an object")
    return data


def gh_pr(runner: Runner, pr: int, slug: str, fields: str, cwd: Path | None = None) -> dict:
    """``gh pr view --json`` through the runner: the PR as an object, else :class:`ShipError`."""
    return gh_json(runner, ["pr", "view", str(pr), *(["--repo", slug] if slug else []), "--json", fields],
                   f"gh pr view {pr}", cwd)


def locate(runner: Runner, repo_dir: Path, remote: str) -> tuple[Path, str]:
    """(the repo's main checkout, the remote's GitHub slug or '') of a folder in a checkout or one of its
    worktrees."""
    from . import public
    r = runner([_git(), "-C", str(repo_dir), "rev-parse", "--path-format=absolute", "--git-common-dir"], None,
               GIT_TIMEOUT)
    common = r.out.strip().splitlines()[-1] if r.ok and r.out.strip() else ""
    if not common:
        raise ShipError(f"{repo_dir} is not in a git checkout: {r.why()}")
    top = Path(common)
    top = top.parent if top.name == ".git" else top
    url = runner([_git(), "-C", str(top), "remote", "get-url", remote], None, GIT_TIMEOUT)
    return top, public.repo_slug(url.out.strip()) if url.ok else ""


def queue_pr(pr_text: str, repo_dir: Path, slug: str = "", remote: str = "origin",
             runner: Runner = run) -> tuple[dict, bool, tuple[int, int], list[str]]:
    """``brain ship PR``: (the entry, added, its place, warnings). gh is read for the title and the branch; when it
    cannot be (down, slow, garbage), the PR is queued all the same and the merger reads it at its run. A PR of
    another repo than the checkout's remote is refused: the merger works in that checkout."""
    url_slug, pr = parse_pr(pr_text)
    top, remote_slug = locate(runner, repo_dir, remote)
    for named in (slug, url_slug):
        if named and remote_slug and named.lower() != remote_slug.lower():
            raise ShipError(f"{named}#{pr} is not a PR of this checkout's repo ({remote_slug}, its remote "
                            f"{remote}): queue it from a checkout of {named} (--repo-dir D)")
    slug = slug or url_slug or remote_slug
    warnings: list[str] = []
    data: dict = {}
    try:
        data = gh_pr(runner, pr, slug, "number,state,title,headRefName,url", top)
    except ShipError as exc:
        warnings.append(f"{exc}; queued without its title (the merger reads the PR at its run)")
    if not slug:
        from . import mergeready
        slug = mergeready.slug_of_url(str(data.get("url") or ""))
    if not slug:
        raise ShipError(f"the GitHub repo of PR {pr} is unknown (--slug OWNER/NAME)")
    state = str(data.get("state") or "")
    if state and state != "OPEN":
        raise ShipError(f"{slug}#{pr} is {state.lower()}: only an open PR is queued")
    entry, added, at = enqueue(slug, pr, str(top), remote, str(data.get("title") or ""),
                               str(data.get("headRefName") or ""), filelock.session())
    return entry, added, at, warnings


# --- the merger ------------------------------------------------------------------------------------------------


class StepFailed(Exception):
    pass


@dataclass
class Merged:
    entry: dict
    before: str   # the base's tip before its merge (the merge commit's first parent; '' when unknown)
    after: str    # the merge commit on the base ('' when it could not be read)


@dataclass
class Report:
    done: list[dict] = field(default_factory=list)       # {"repo", "pr", "status", "reason"}
    suites: list[dict] = field(default_factory=list)     # {"repo", "base", "sha", "prs", "result", "detail", "culprit"}
    untested: list[dict] = field(default_factory=list)   # {"repo", "base", "prs", "why"}
    waiting: list[dict] = field(default_factory=list)    # {"repo", "pr", "why"}: a red base's PRs left queued
    stopped: str = ""
    lines: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.stopped and not self.untested and not self.waiting and \
            all(d["status"] == "merged" for d in self.done) and all(s["result"] == "pass" for s in self.suites)

    def to_json(self) -> dict:
        return {"ok": self.ok, "done": self.done, "suites": self.suites, "untested": self.untested,
                "waiting": self.waiting, "stopped": self.stopped}


def scratch_root() -> Path:
    """The folder of the merger's scratch worktrees: one per BRAIN_HOME under the system's temporary folder, so that
    a sweep never touches another queue's merger."""
    import hashlib
    tag = hashlib.sha1(os.path.normcase(str(paths.brain_home())).encode("utf-8")).hexdigest()[:10]
    return Path(tempfile.gettempdir()) / f"{SCRATCH}{tag}"


def default_gate(top: Path, pr: int, slug: str, remote: str, view):
    from . import mergeready
    return mergeready.gate(top, str(pr), slug, remote, fetch=True, view=view)


def default_suite(top: Path, python: str) -> list[tuple[Path, list[str]]]:
    """The repo's whole suite, as brain test would run it: (folder, command) per pytest configuration."""
    from . import inventory, targeted
    suite = targeted.suite_of(inventory.work_tree(top))
    return targeted.commands(top, suite, python, extra=["-q", "-p", "no:cacheprovider"]) if suite else []


def default_public(repo: str) -> bool:
    from . import config, public
    return public.is_public(repo, config.load())


class Merger:
    """The merger's run over the queue. ``runner``, ``gate``, ``suite``, ``is_public`` and ``sleep`` are injectable
    (the tests fake git, gh and pytest); ``say`` takes each progress line."""

    def __init__(self, runner: Runner = run, gate=default_gate, suite=default_suite, batch: int = BATCH,
                 python: str = "", say: Callable[[str], None] = print, force: bool = False,
                 is_public: Callable[[str], bool] = default_public, sleep: Callable[[float], None] = time.sleep,
                 ci_wait: float = CI_WAIT):
        self.runner, self.gate, self.suite = runner, gate, suite
        self.batch = max(1, int(batch))
        self.python = python or sys.executable
        self.say, self.force, self.is_public, self.sleep, self.ci_wait = say, force, is_public, sleep, ci_wait
        self.report = Report()
        self.batches: dict[tuple[str, str], list[Merged]] = {}
        self.lock: filelock.Lock | None = None
        self._pr_data: dict[tuple[str, int], dict] = {}
        self._methods: dict[str, str] = {}

    # --- helpers ---

    def _log(self, line: str) -> None:
        self.report.lines.append(line)
        self.say(line)

    def _git(self, cwd: Path, *args: str, timeout: float = GIT_TIMEOUT) -> Result:
        return self.runner([_git(), *args], cwd, timeout)

    def _must(self, step: str, r: Result) -> Result:
        if not r.ok:
            raise StepFailed(f"{step}: {r.why()}")
        return r

    def _sha(self, cwd: Path, ref: str) -> str:
        r = self._git(cwd, "rev-parse", "--verify", f"{ref}^{{commit}}")
        sha = r.out.strip().splitlines()[-1] if r.ok and r.out.strip() else ""
        return sha if SHA.fullmatch(sha) else ""

    def _brain(self, *args: str) -> list[str]:
        return [self.python, "-m", "brain", *args]

    def _env(self, scratch: Path) -> dict:
        from .mergetogether import _src_path  # the scratch's own sources first: its tests test its code
        return {**os.environ, "PYTHONPATH": os.pathsep.join(x for x in (_src_path(scratch),
                                                                         os.environ.get("PYTHONPATH", "")) if x)}

    def _token(self) -> str:
        return self.lock.token if self.lock is not None else ""

    def view(self, pr, slug, cwd=None) -> dict:
        """The gate's ``gh pr view``, through the runner; kept for the branch, the title and the fork's fields."""
        from . import mergeready
        try:
            data = gh_pr(self.runner, int(pr), slug, f"{mergeready.FIELDS},{VIEW_FIELDS}", cwd)
        except ShipError as exc:
            raise mergeready.GateError(str(exc)) from None
        self._pr_data[_key(slug, int(pr))] = data
        return data

    def _worktree(self, top: Path, commit: str) -> Path:
        root = scratch_root()
        root.mkdir(parents=True, exist_ok=True)
        scratch = Path(tempfile.mkdtemp(prefix="wt-", dir=root))
        shutil.rmtree(scratch, ignore_errors=True)
        hooks = tempfile.mkdtemp(prefix=f"{SCRATCH}hooks-")   # no post-checkout hook runs in the scratch
        try:
            self._must("git worktree add", self._git(top, "-c", f"core.hooksPath={Path(hooks).as_posix()}",
                                                     "worktree", "add", "--detach", "--quiet", str(scratch), commit))
        finally:
            shutil.rmtree(hooks, ignore_errors=True)
        return scratch

    def _remove(self, top: Path, scratch: Path) -> None:
        self._git(top, "worktree", "remove", "--force", str(scratch))
        if scratch.exists():
            shutil.rmtree(scratch, ignore_errors=True)
            self._git(top, "worktree", "prune")

    def sweep(self) -> None:
        """The scratch worktrees a killed merger left: their folders removed, each queued repo's worktrees pruned
        (one merger per machine: under the lock, none is in use)."""
        root = scratch_root()
        for d in (root.iterdir() if root.is_dir() else ()):
            if d.is_dir():
                shutil.rmtree(d, ignore_errors=True)
        for top in sorted({str(e.get("dir")) for e in entries() if e.get("dir")}):
            if Path(top).is_dir():
                self._git(Path(top), "worktree", "prune")

    def _done(self, e: dict, status: str, reason: str = "", **more) -> str:
        update(e["repo"], e["pr"], status=status, reason=reason, **more)
        self.report.done.append({"repo": e["repo"], "pr": int(e["pr"]), "status": status, "reason": reason})
        self._log(f"{e['repo']}#{e['pr']}: {status.upper()}" + (f": {reason}" if reason else ""))
        return status

    def _renew(self) -> None:
        if self.lock is not None and self.lock.lost:
            raise filelock.LockError(f"the merger's lock was lost ({self.lock.lost}): this run stops")

    # --- one PR ---

    def _catch_up(self, scratch: Path, base_ref: str, branch: str) -> bool:
        """main merged into the scratch when the head lacks it, with the views regenerated: whether it merged."""
        r = self._git(scratch, "merge-base", "--is-ancestor", base_ref, "HEAD")
        if r.rc == 0:
            return False
        if r.rc != 1:
            raise StepFailed(f"git merge-base: {r.why()}")
        m = self._git(scratch, "merge", "--no-ff", "--no-commit", base_ref)
        if not m.ok:
            u = self._git(scratch, "diff", "--name-only", "--diff-filter=U")
            files = [f for f in u.out.split("\n") if f.strip()] if u.ok else []
            self._git(scratch, "merge", "--abort")
            what = f" the merge driver left on {', '.join(files[:8])}" if files else f": {m.why()}"
            raise StepFailed(f"merging {base_ref} into the PR: a conflict{what}; merge it by hand, push, queue again")
        if (scratch / "notes" / "graph" / "schema.yaml").is_file():
            r = self.runner(self._brain("--root", str(scratch), "refresh", "--offline"), scratch, CHECK_TIMEOUT)
            if not r.ok:
                pin = " (the merged tree pins another engine: config.json engine.pin; run the merger with that " \
                      "engine)" if "engine.pin" in (r.err + r.out) else ""
                raise StepFailed(f"brain refresh (the views regenerated once): {r.why()}{pin}")
        self._must("git add", self._git(scratch, "add", "-A"))
        self._must("git commit (the catch-up)", self._git(
            scratch, "commit", "--no-edit", "-m", f"Merge {base_ref} into {branch or 'the PR'} (brain ship)"))
        return True

    def _checks(self, scratch: Path, base_ref: str, merged: bool) -> None:
        if not merged and (scratch / "notes" / "graph" / "schema.yaml").is_file():
            self._must("brain check", self.runner(self._brain("--root", str(scratch), "check"), scratch,
                                                  CHECK_TIMEOUT))
        if merged:
            self._must("brain merge-check (nothing of main lost)", self.runner(
                self._brain("merge-check", "--repo", str(scratch), "--base", base_ref, "--no-fetch"), scratch,
                CHECK_TIMEOUT))
        self._must("the targeted tests (brain test --changed --strict)", self.runner(
            self._brain("test", "--changed", base_ref, "--repo-dir", str(scratch), "--strict"), scratch,
            TEST_TIMEOUT, env=self._env(scratch)))

    def _default_branch(self, top: Path, remote: str) -> str:
        r = self._git(top, "symbolic-ref", "--short", f"refs/remotes/{remote}/HEAD")
        name = r.out.strip().splitlines()[-1] if r.ok and r.out.strip() else ""
        return name[len(remote) + 1:] if name.startswith(f"{remote}/") else ""

    def _gated(self, e: dict, top: Path, remote: str):
        """The gate's answer for the entry: the Gate when the merger may go on, else the entry's final state."""
        from . import mergeready
        from .inventory import AuditError
        try:
            g = self.gate(top, int(e["pr"]), str(e["repo"]), remote, self.view)
        except (mergeready.GateError, AuditError, OSError, ValueError) as exc:
            return self._done(e, "failed", f"the merge gate could not run: {exc}")
        blocks = [c for c in g.blocks if c["check"] not in WAIVED]
        if blocks or not g.checks:
            why = "; ".join(f"{c['check']}: {c['detail']}" for c in blocks) or "the gate ran no check"
            return self._done(e, "refused", f"the merge gate: {why}")
        data = self._pr_data.get(_key(str(e["repo"]), int(e["pr"])), {})
        if data.get("isCrossRepository") is not False:
            owner = (data.get("headRepositoryOwner") or {}).get("login", "") if isinstance(
                data.get("headRepositoryOwner"), dict) else ""
            return self._done(e, "refused", "a PR from a fork" + (f" ({owner})" if owner else "") + " or one gh does "
                              "not say is not: the merger pushes to the base repo's PR branch only; merge it by hand")
        branch = str(data.get("headRefName") or "")
        guarded = {b.lower() for b in (g.base, self._default_branch(top, remote)) if b}
        if not branch or branch.lower() in guarded:
            return self._done(e, "refused", f"its branch {branch or '(unknown)'} is the base or the default branch: "
                              "the merger never pushes there")
        return g

    def _wait_ci(self, pr: int, repo: str, head: str) -> None:
        """The checks GitHub reports on ``head`` awaited: all green, else :class:`StepFailed` (one failed, or still
        running or not started at the deadline)."""
        from . import mergeready
        deadline = time.monotonic() + self.ci_wait
        last = "no answer yet"
        while True:
            try:
                data = gh_pr(self.runner, pr, repo, "headRefOid,statusCheckRollup")
            except ShipError as exc:
                last = str(exc)
            else:
                rollup = data.get("statusCheckRollup") or []
                if data.get("headRefOid") != head:
                    last = f"GitHub reads the head {str(data.get('headRefOid'))[:8]} still"
                elif not isinstance(rollup, list) or not all(isinstance(c, dict) for c in rollup):
                    raise StepFailed(f"the caught-up head's checks cannot be read: {str(rollup)[:120]}")
                else:
                    states = [mergeready._check_state(c) for c in rollup]
                    green, detail = mergeready.ci(rollup)
                    if "failed" in states:
                        raise StepFailed(f"the CI of the caught-up head {head[:8]}: {detail}")
                    if green:
                        return
                    last = detail
            if time.monotonic() >= deadline:
                raise StepFailed(f"the CI of the caught-up head {head[:8]} not green in {int(self.ci_wait)} s: {last}")
            self.sleep(CI_POLL)

    def _regate(self, e: dict, top: Path, remote: str, head: str):
        """The merge gate on the caught-up head, nothing waived."""
        from . import mergeready
        from .inventory import AuditError
        try:
            g = self.gate(top, int(e["pr"]), str(e["repo"]), remote, self.view)
        except (mergeready.GateError, AuditError, OSError, ValueError) as exc:
            raise StepFailed(f"the merge gate on the caught-up head could not run: {exc}") from None
        if g.head != head:
            raise StepFailed(f"the PR's head moved to {g.head[:8]} after the catch-up {head[:8]} was pushed")
        if not g.ready:
            why = "; ".join(f"{c['check']}: {c['detail']}" for c in g.blocks) or "the gate ran no check"
            hint = f" (a new review stamp for {head}: brain review stamp)" if any(
                c["check"] == "review" for c in g.blocks) else ""
            raise StepFailed(f"the merge gate on the caught-up head {head[:8]}: {why}{hint}")
        return g

    def _method(self, repo: str) -> str:
        if repo not in self._methods:
            try:
                data = gh_json(self.runner, ["repo", "view", repo, "--json",
                                             ",".join(k for k, _ in MERGE_METHODS)], f"gh repo view {repo}")
            except ShipError:
                data = {}
            self._methods[repo] = next((flag for k, flag in MERGE_METHODS if data.get(k) is True), "--merge")
        return self._methods[repo]

    def _merge(self, top: Path, repo: str, pr: int, head: str) -> str:
        """gh pr merge at ``head``, then the PR read back: the merge commit when it merged at that head;
        :class:`StepFailed` when it is still open; :class:`Stop` on any other answer."""
        r = self.runner([_gh(), "pr", "merge", str(pr), "--repo", repo, self._method(repo), "--match-head-commit",
                         head], top, GH_TIMEOUT)
        try:
            data = gh_pr(self.runner, pr, repo, "state,mergeCommit,headRefOid")
        except ShipError as exc:
            raise Stop(f"{repo}#{pr}: gh pr merge answered {r.why() if not r.ok else 'done'}, and the PR cannot be "
                       f"read back ({exc}): check it by hand") from None
        state = str(data.get("state") or "")
        if state == "OPEN":
            raise StepFailed(f"gh pr merge: {r.why()}" if not r.ok else
                             "gh pr merge said done, but the PR is still open (a merge queue or auto-merge on GitHub?)")
        commit = data.get("mergeCommit") if isinstance(data.get("mergeCommit"), dict) else {}
        oid = str(commit.get("oid") or "")
        if state == "MERGED" and data.get("headRefOid") == head and SHA.fullmatch(oid):
            return oid
        raise Stop(f"{repo}#{pr}: after gh pr merge the PR reads {state or '?'} at {str(data.get('headRefOid'))[:8]} "
                   f"(merged at {head[:8]} expected): check it by hand")

    def _ship(self, e: dict, top: Path, scratch: Path, g, remote: str, base_ref: str) -> tuple[bool, str, str]:
        """The catch-up, the checks, the gated push and gh pr merge: (whether main was merged in, the head merged,
        the merge commit); :class:`StepFailed` on a step that fails."""
        from . import mergeready
        repo, pr = str(e["repo"]), int(e["pr"])
        branch = str(self._pr_data.get(_key(repo, pr), {}).get("headRefName") or "")
        merged = self._catch_up(scratch, base_ref, branch)
        self._checks(scratch, base_ref, merged)
        head = self._sha(scratch, "HEAD") if merged else g.head
        if merged:
            if not head:
                raise StepFailed("the catch-up's head is unknown: nothing pushed")
            if self.is_public(repo):
                self._must("brain check --public --history (the caught-up head, before its push)", self.runner(
                    self._brain("check", "--public", "--history"), scratch, CHECK_TIMEOUT))
            self._must("git push (the catch-up)", self._git(scratch, "push", remote, f"HEAD:refs/heads/{branch}"))
            self._wait_ci(pr, repo, head)
            g = self._regate(e, top, remote, head)
        if g.ready:
            with contextlib.suppress(OSError):
                mergeready.stamp(g)
        return merged, head, self._merge(top, repo, pr, head)

    def process(self, e: dict) -> str:
        repo, pr, remote = str(e["repo"]), int(e["pr"]), str(e.get("remote") or "origin")
        top = Path(str(e.get("dir") or ""))
        holder = self.lock.holder() if self.lock is not None else {}
        update(repo, pr, status="running", reason="", merger={k: holder.get(k) for k in ("pid", "pstart", "host",
                                                                                         "token")})
        if not e.get("dir") or not top.is_dir():
            return self._done(e, "failed", f"its checkout {top} is gone: queue it again from a checkout")
        g = self._gated(e, top, remote)
        if isinstance(g, str):
            return g
        base = g.base or "main"
        bad = red().get(_base_key(repo, base))
        if bad and not self.force:
            why = f"{base}'s last full suite was red ({bad.get('detail', '?')}): it waits (--force ships anyway)"
            update(repo, pr, status="queued", reason=f"waiting: {why}")
            self.report.waiting.append({"repo": repo, "pr": pr, "why": why})
            self._log(f"{repo}#{pr}: WAITING: {why}")
            return "waiting"
        base_ref = f"{remote}/{base}"
        try:
            scratch = self._worktree(top, g.head)
        except StepFailed as exc:
            return self._done(e, "failed", str(exc))
        try:
            merged, head, after = self._ship(e, top, scratch, g, remote, base_ref)
        except StepFailed as exc:
            return self._done(e, "failed", str(exc))
        except Stop as exc:
            self._done(e, "failed", f"{exc}")
            raise
        finally:
            self._remove(top, scratch)
        self._done(e, "merged", ("caught up with main, gated again and merged" if merged else "checked and merged"),
                   head=head, merged=after)
        self._git(top, "fetch", "--quiet", remote, f"+refs/heads/{base}:refs/remotes/{remote}/{base}")
        self.batches.setdefault((repo.lower(), base), []).append(Merged(e, self._sha(top, f"{after}^1"), after))
        return "merged"

    # --- the batch's full suite, and the bisection ---

    def run_suite(self, top: Path, sha: str) -> tuple[str, str]:
        """('pass' | 'fail' | 'error', a detail): the full suite on ``sha`` in a scratch worktree."""
        self._renew()
        if not sha:
            return "error", "the commit is unknown"
        try:
            scratch = self._worktree(top, sha)
        except StepFailed as exc:
            return "error", str(exc)
        try:
            try:
                cmds = self.suite(scratch, self.python)
            except Exception as exc:   # an unreadable tree: the suite cannot say
                return "error", f"the suite could not be listed: {exc}"
            if not cmds:
                return "pass", "no test suite"
            for cwd, cmd in cmds:
                r = self.runner(cmd, cwd, SUITE_TIMEOUT, env=self._env(scratch))
                if r.rc in (124, 127):
                    return "error", r.why()
                if r.rc not in (0, 5):
                    return "fail", r.why()
            return "pass", f"{len(cmds)} pytest run(s) green"
        finally:
            self._remove(top, scratch)

    def _bisect(self, name: str, top: Path, items: list[Merged]) -> tuple[int, str]:
        """(the index of the first merge the suite fails from, '') or (-1, why the bisection stopped)."""
        lo, hi = -1, len(items) - 1   # the suite fails after items[hi]; nothing is known of before items[0]
        while hi - lo > 1:
            mid = (lo + hi) // 2
            res, det = self.run_suite(top, items[mid].after)
            self._log(f"{name}: bisection: the full suite after #{items[mid].entry['pr']}: {res.upper()}")
            if res == "error":
                among = ", ".join("#" + str(m.entry["pr"]) for m in items[lo + 1:hi + 1])
                return -1, f"the bisection stopped ({det}): the failure is among {among}"
            hi, lo = (mid, lo) if res == "fail" else (hi, mid)
        return hi, ""

    def _confirm(self, name: str, top: Path, m: Merged) -> str:
        """'' when the suite fails again after ``m`` and passes on its parent; else why there is no culprit."""
        res, det = self.run_suite(top, m.after)
        self._log(f"{name}: the full suite again after #{m.entry['pr']}: {res.upper()}")
        if res == "pass":
            return f"flaky: the full suite passed again after #{m.entry['pr']}: no culprit"
        if res == "error":
            return f"the culprit cannot be confirmed ({det})"
        res, det = self.run_suite(top, m.before)
        self._log(f"{name}: the full suite before #{m.entry['pr']}: {res.upper()}")
        if res == "fail":
            return f"main was red before #{m.entry['pr']}'s merge already: no culprit"
        return "" if res == "pass" else f"the culprit cannot be confirmed ({det})"

    def verify(self, key: tuple[str, str]) -> bool:
        """The batch's full suite once, on its last merge; on a failure, the bisection and its confirmation; a red
        base recorded. True when the batch is green."""
        items = self.batches.pop(key, [])
        if not items:
            return True
        top = Path(str(items[-1].entry["dir"]))
        prs = [int(m.entry["pr"]) for m in items]
        name, base = items[-1].entry["repo"], key[1]
        rec = {"repo": name, "base": base, "sha": items[-1].after, "prs": prs, "result": "", "detail": "",
               "culprit": None}
        self.report.suites.append(rec)
        result, detail = self.run_suite(top, items[-1].after)
        rec.update(result=result, detail=detail)
        self._log(f"{name}: the full suite on {base} {items[-1].after[:8]} after {', '.join(f'#{p}' for p in prs)}: "
                  f"{result.upper()} ({detail})")
        if result == "pass":
            if red().get(_base_key(name, base)):
                set_red(name, base, None)
            return True
        why = detail
        if result == "fail":
            hi, stop = self._bisect(name, top, items)
            why = stop or self._confirm(name, top, items[hi])
            if not why:
                culprit = items[hi].entry
                rec["culprit"] = int(culprit["pr"])
                why = f"the full suite fails from #{culprit['pr']}'s merge ({items[hi].after[:8]}) on: {detail}"
                update(culprit["repo"], culprit["pr"], status="culprit",
                       reason=f"{why}; main is not reverted (its owner decides)")
                self._log(f"{name}: CULPRIT #{culprit['pr']}: the full suite fails from its merge on")
            else:
                rec["detail"] += f"; {why}"
                self._log(f"{name}: {why}")
        set_red(name, base, {"sha": items[-1].after, "detail": why[:300], "culprit": rec["culprit"]})
        return False

    def _untested(self, key: tuple[str, str], why: str) -> None:
        items = self.batches.pop(key, [])
        if not items:
            return
        self.report.untested.append({"repo": items[0].entry["repo"], "base": key[1],
                                     "prs": [int(m.entry["pr"]) for m in items], "why": why})
        for m in items:
            with contextlib.suppress(Exception):
                update(m.entry["repo"], m.entry["pr"], suite=f"untested: {why}")
        self._log(f"{items[0].entry['repo']}: UNTESTED {', '.join('#' + str(m.entry['pr']) for m in items)}: {why}")

    def _finish(self, failing: BaseException | None) -> None:
        """Every pending batch tested (each repo's on its own), or marked untested when the run cannot test it."""
        for key in list(self.batches):
            if failing is not None:
                self._untested(key, f"the run stopped on {type(failing).__name__}: {failing}")
                continue
            try:
                ok = self.verify(key)
            except Exception as exc:
                self._untested(key, f"{type(exc).__name__}: {exc}")
                continue
            if not ok and not self.report.stopped:
                self.report.stopped = f"the full suite is not green on {key[0]} {key[1]}: the run stops"

    # --- the run ---

    def run(self) -> Report:
        """Every open entry, in order, under the merger's lock (the caller takes it: :func:`merge_queue`)."""
        seen: set = set()
        failing: BaseException | None = None
        try:
            while True:
                self._renew()
                e = next_open(seen, self._token())
                if e is None:
                    break
                seen.add(_key(e["repo"], e["pr"]))
                try:
                    status = self.process(e)
                except Stop as exc:
                    self.report.stopped = str(exc)
                    break
                except filelock.LockError:
                    raise
                except Exception as exc:   # one PR's surprise fails that PR, never the queue
                    try:
                        self._done(e, "failed", f"an unexpected {type(exc).__name__}: {exc}")
                    except Exception as again:
                        self._log(f"{e['repo']}#{e['pr']}: FAILED ({type(exc).__name__}: {exc}), and its entry "
                                  f"could not be written ({type(again).__name__}: {again})")
                    continue
                if status != "merged":
                    continue
                key = next(k for k, v in self.batches.items() if v and v[-1].entry is e)
                if len(self.batches[key]) >= self.batch and not self.verify(key):
                    self.report.stopped = f"the full suite is not green on {e['repo']} {key[1]}: the run stops"
                    break
        except BaseException as exc:
            failing = exc
            raise
        finally:
            self._finish(failing)
        return self.report


def plan(batch: int = BATCH) -> list[str]:
    """--dry-run: what the merger would do, from the queue alone (no lock, no external call)."""
    rows = [e for e in entries() if e.get("status") in OPEN_STATES]
    held = lock_holder()
    out = [f"brain ship --run --dry-run: {len(rows)} PR(s) open in {queue_path()}"]
    if held:
        out.append(f"the merger's lock is held by {filelock.describe(held)}: a run now would be refused unless it "
                   "is stale")
    for k, why in red().items():
        out.append(f"  red: {k}: {why.get('detail', '?')}: its PRs wait (--force ships them)")
    counts: dict[str, int] = {}
    for e in rows:
        repo = str(e["repo"])
        counts[repo.lower()] = counts.get(repo.lower(), 0) + 1
        out.append(f"  would ship {repo}#{e['pr']} {cell(e.get('title'))!s}: the merge gate (fresh answered by the "
                   f"catch-up), main merged in when the head lacks it, the views and brain check, merge-check, the "
                   f"targeted tests (--strict); a caught-up head: the public check, the push, its CI, the gate again; "
                   f"gh pr merge --match-head-commit, the PR read back")
        if counts[repo.lower()] % batch == 0:
            out.append(f"  then the full suite of {repo} once on its base (a batch of {batch}), a bisection if it "
                       "fails")
    for repo, n in counts.items():
        if n % batch:
            out.append(f"  at the end: the full suite of {repo} once for its last {n % batch} merge(s)")
    return out


def merge_queue(batch: int = BATCH, runner: Runner = run, gate=default_gate, suite=default_suite,
                say: Callable[[str], None] = print, force: bool = False, **kw) -> Report:
    """``brain ship --run``: the lock taken (:class:`filelock.Held` when another merger runs) and kept by a heartbeat,
    the scratch worktrees a killed merger left swept, the queue merged, the lock released whatever happens."""
    m = Merger(runner, gate, suite, batch, say=say, force=force, **kw)
    lock = filelock.Lock(LOCK, LOCK_TTL, what="brain ship --run (the merger)")
    lock.acquire()
    m.lock = lock
    try:
        lock.heartbeat()
        if lock.broken is not None:
            say(f"brain ship: a stale lock broken ({filelock.describe(lock.broken)})")
        m.sweep()
        return m.run()
    finally:
        left = lock.release()
        if left:
            say(f"brain ship: warning: {left}")
