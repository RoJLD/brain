"""``brain ship``: a local merge queue, built on the merge gate (brain.mergeready). A session queues its PR and
stops; one merger, holding a lock, catches each PR up with main, checks it and merges it, so that no session races
main any more (before it, a median 0.8 min between a PR's last catch-up and its merge, and PRs that lost that race
twice or more).

- **The queue**: ``<BRAIN_HOME>/ship/queue.json``, one entry per PR keyed by its GitHub repo and number (queuing the
  same PR twice keeps one entry; one that failed or was refused goes back to queued). An entry names the repo's main
  checkout (a session's worktree may be gone by the time the merger runs), the remote, the PR's title and branch as
  gh last read them, and its state: ``queued``, ``running``, ``merged``, ``failed``, ``refused`` or ``culprit``,
  with the reason. Each change is a read, an edit and an atomic write under the short lock ``ship-queue``
  (brain.filelock), so two sessions queuing at once both land.
- **The merger** (``brain ship --run``): takes the lock ``ship`` (brain.filelock: one merger per machine; a second
  one is refused with the holder) and takes the queued PRs in order. For each:

  1. the merge gate (brain.mergeready.gate, the gate's own function, gh read through this module's runner): every
     check it blocks refuses the PR, but ``fresh`` (main moved under the PR's files): catching main up is the
     merger's own job, and the checks below run on the merged tree;
  2. a scratch worktree of the PR's head (no checkout hook run); main merged into it when the head lacks it, with
     the repo's merge driver (a conflict it leaves fails the PR); in a repo with a graph store the views regenerated
     once and the store checked (``brain refresh --offline``, else ``brain check`` when nothing was merged); after a
     merge, ``brain merge-check`` (nothing of main lost);
  3. the targeted tests (``brain test --changed <remote>/<base>``, the coverage map's selection);
  4. the catch-up pushed to the PR's branch when there is one, then ``gh pr merge N --merge --match-head-commit``.

  A PR that fails a step is marked failed with its reason and the merger goes on with the next. Every ``--batch``
  PRs merged in a repo (5 by default), the repo's full suite runs once on main as it is then; when it fails, a
  bisection over the batch's merges names the first one main fails from (the culprit), and the run stops: main is
  never reverted by the merger, that is its owner's call. A batch left smaller at the end of a run is tested too, so
  no merge leaves a run untested. Batches are counted per repo: two repos in one queue never mix.
- ``--dry-run`` says what the merger would do, from the queue alone: no lock taken, no external call.

Every external call (git, gh, the Python that runs brain and pytest) goes through one injectable :class:`Runner`,
with a timeout: a tool that is missing (127), that does not answer in time (124) or that answers what cannot be
read fails the PR it was for, never the queue. Starting the merger as a service is the owner's decision: this
module only provides the commands.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import filelock, paths, stateio

FOLDER = "ship"
QUEUE = "queue.json"
LOCK = "ship"               # the merger's lock (<BRAIN_HOME>/locks/ship.lock)
QUEUE_LOCK = "ship-queue"   # the queue file's short lock, around each read-edit-write
LOCK_TTL = 3600.0           # the merger's lock, renewed before each PR and each suite run
QUEUE_LOCK_TTL = 60.0
QUEUE_LOCK_WAIT = 15.0
BATCH = 5
STATES = ("queued", "running", "merged", "failed", "refused", "culprit")
OPEN_STATES = ("queued", "running")
WAIVED = ("fresh",)         # the gate's checks the merger answers itself (by catching main up)
GIT_TIMEOUT = 300
GH_TIMEOUT = 120
CHECK_TIMEOUT = 900
TEST_TIMEOUT = 1800
SUITE_TIMEOUT = 3600
SHA = re.compile(r"[0-9a-f]{40}")
PR_URL = re.compile(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/(\d+)")


class ShipError(Exception):
    pass


# --- the runner: every external call ---------------------------------------------------------------------------


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
    """The default runner: ``cmd`` run with a timeout; 127 when it does not start, 124 when it does not answer in
    time."""
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=env, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return Result(124, "", f"{cmd[0]}: no answer in {int(timeout)} s")
    except OSError as exc:
        return Result(127, "", f"{cmd[0]}: {exc}")
    return Result(r.returncode, r.stdout or "", r.stderr or "")


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
    return ""


def _key(repo: str, pr: int) -> tuple[str, int]:
    return repo.lower(), int(pr)


def entries(repo: str = "") -> list[dict]:
    """The queue's entries, in order (only ``repo``'s when given); [] when there is no queue or it cannot be read."""
    st = stateio.load(queue_path(), check=_shape, aside=False)
    rows = [e for e in st.data.get("entries", []) if isinstance(e, dict) and e.get("repo") and e.get("pr")]
    return [e for e in rows if not repo or str(e["repo"]).lower() == repo.lower()]


def _edit(change: Callable[[list[dict]], object]):
    """``change`` applied to the queue's entries under the queue lock, then written back atomically: its result."""
    lock = filelock.Lock(QUEUE_LOCK, QUEUE_LOCK_TTL, what="brain ship (the queue file)")
    with lock.acquire(wait=QUEUE_LOCK_WAIT):
        st = stateio.load(queue_path(), check=_shape)
        rows = list(st.data.get("entries", []))
        out = change(rows)
        stateio.save(st, {**st.data, "entries": rows})
        return out


def place(rows: list[dict], repo: str, pr: int) -> tuple[int, int]:
    """(the PR's place among its repo's open entries, how many there are); place 0 when it is not open."""
    open_ = [_key(e["repo"], e["pr"]) for e in rows if str(e.get("repo", "")).lower() == repo.lower()
             and e.get("status") in OPEN_STATES]
    k = _key(repo, pr)
    return (open_.index(k) + 1 if k in open_ else 0), len(open_)


def enqueue(repo: str, pr: int, checkout: str, remote: str = "origin", title: str = "", branch: str = "",
            by: str = "") -> tuple[dict, bool, tuple[int, int]]:
    """(the entry, whether it was added or put back to queued, its place): the PR queued once."""
    def change(rows: list[dict]):
        k = _key(repo, pr)
        for e in rows:
            if _key(e["repo"], e["pr"]) == k:
                back = e.get("status") not in (*OPEN_STATES, "merged")
                e.update({"dir": checkout, "remote": remote, "updated": _now()}, **({"title": title} if title else {}),
                         **({"branch": branch} if branch else {}))
                if back:
                    e.update(status="queued", reason="", queued=_now())
                return e, back, place(rows, repo, pr)
        e = {"repo": repo, "pr": int(pr), "dir": checkout, "remote": remote, "title": title, "branch": branch,
             "by": by, "queued": _now(), "updated": _now(), "status": "queued", "reason": ""}
        rows.append(e)
        return e, True, place(rows, repo, pr)
    return _edit(change)


def update(repo: str, pr: int, **fields) -> None:
    def change(rows: list[dict]):
        for e in rows:
            if _key(e["repo"], e["pr"]) == _key(repo, pr):
                e.update(fields, updated=_now())
    _edit(change)


def next_open(skip: set) -> dict | None:
    """The first open entry not in ``skip`` (keys already taken this run)."""
    return next((e for e in entries() if e.get("status") in OPEN_STATES and _key(e["repo"], e["pr"]) not in skip),
                None)


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


def gh_pr(runner: Runner, pr: int, slug: str, fields: str, cwd: Path | None = None) -> dict:
    """``gh pr view --json`` through the runner: the PR as an object, else :class:`ShipError`."""
    r = runner([_gh(), "pr", "view", str(pr), *(["--repo", slug] if slug else []), "--json", fields], cwd,
               GH_TIMEOUT)
    if not r.ok:
        raise ShipError(f"gh pr view {pr}: {r.why()}")
    try:
        data = json.loads(r.out)
    except ValueError:
        raise ShipError(f"gh pr view {pr}: not JSON: {r.out.strip()[:120]!r}") from None
    if not isinstance(data, dict):
        raise ShipError(f"gh pr view {pr}: not an object")
    return data


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
    cannot be (down, slow, garbage), the PR is queued all the same and the merger reads it at its run."""
    url_slug, pr = parse_pr(pr_text)
    top, remote_slug = locate(runner, repo_dir, remote)
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
    before: str   # the base's tip before its merge
    after: str    # the base's tip after it ('' when it could not be read)


@dataclass
class Report:
    done: list[dict] = field(default_factory=list)     # {"repo", "pr", "status", "reason"}
    suites: list[dict] = field(default_factory=list)   # {"repo", "sha", "prs", "result", "detail", "culprit"}
    stopped: str = ""
    lines: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.stopped and all(d["status"] == "merged" for d in self.done) and \
            all(s["result"] == "pass" for s in self.suites)

    def to_json(self) -> dict:
        return {"ok": self.ok, "done": self.done, "suites": self.suites, "stopped": self.stopped}


def default_gate(top: Path, pr: int, slug: str, remote: str, view):
    from . import mergeready
    return mergeready.gate(top, str(pr), slug, remote, fetch=True, view=view)


def default_suite(top: Path, python: str) -> list[tuple[Path, list[str]]]:
    """The repo's whole suite, as brain test would run it: (folder, command) per pytest configuration."""
    from . import inventory, targeted
    suite = targeted.suite_of(inventory.work_tree(top))
    return targeted.commands(top, suite, python, extra=["-q", "-p", "no:cacheprovider"]) if suite else []


class Merger:
    """The merger's run over the queue. ``runner``, ``gate`` and ``suite`` are injectable (the tests fake git, gh
    and pytest); ``say`` takes each progress line."""

    def __init__(self, runner: Runner = run, gate=default_gate, suite=default_suite, batch: int = BATCH,
                 python: str = "", say: Callable[[str], None] = print):
        self.runner, self.gate, self.suite = runner, gate, suite
        self.batch = max(1, int(batch))
        self.python = python or sys.executable
        self.say = say
        self.report = Report()
        self.batches: dict[str, list[Merged]] = {}
        self.lock: filelock.Lock | None = None
        self._pr_data: dict[tuple[str, int], dict] = {}

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

    def view(self, pr, slug, cwd=None) -> dict:
        """The gate's ``gh pr view``, through the runner; kept for the branch and the title."""
        from . import mergeready
        try:
            data = gh_pr(self.runner, int(pr), slug, mergeready.FIELDS, cwd)
        except ShipError as exc:
            raise mergeready.GateError(str(exc)) from None
        self._pr_data[_key(slug, int(pr))] = data
        return data

    def _worktree(self, top: Path, commit: str) -> Path:
        scratch = Path(tempfile.mkdtemp(prefix="brain-ship-"))
        shutil.rmtree(scratch, ignore_errors=True)
        hooks = tempfile.mkdtemp(prefix="brain-ship-hooks-")   # no post-checkout hook runs in the scratch
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

    def _done(self, e: dict, status: str, reason: str = "", **more) -> str:
        update(e["repo"], e["pr"], status=status, reason=reason, **more)
        self.report.done.append({"repo": e["repo"], "pr": int(e["pr"]), "status": status, "reason": reason})
        self._log(f"{e['repo']}#{e['pr']}: {status.upper()}" + (f": {reason}" if reason else ""))
        return status

    def _renew(self) -> None:
        if self.lock is not None and not self.lock.renew():
            raise filelock.LockError("the merger's lock was broken by another merger: this run stops")

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
            self._must("brain refresh (the views regenerated once)",
                       self.runner(self._brain("--root", str(scratch), "refresh", "--offline"), scratch,
                                   CHECK_TIMEOUT))
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
        self._must("the targeted tests (brain test --changed)", self.runner(
            self._brain("test", "--changed", base_ref, "--repo-dir", str(scratch)), scratch, TEST_TIMEOUT,
            env=self._env(scratch)))

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
        return g

    def _ship(self, e: dict, top: Path, scratch: Path, g, remote: str, base_ref: str) -> tuple[bool, str]:
        """The catch-up, the checks, the push and gh pr merge in the scratch: (whether main was merged in, the head
        merged); :class:`StepFailed` on a step that fails."""
        repo, pr = str(e["repo"]), int(e["pr"])
        branch = str(self._pr_data.get(_key(repo, pr), {}).get("headRefName") or e.get("branch") or "")
        merged = self._catch_up(scratch, base_ref, branch)
        self._checks(scratch, base_ref, merged)
        head = self._sha(scratch, "HEAD") if merged else g.head
        if merged:
            if not head or not branch:
                raise StepFailed("the catch-up's head or the PR's branch is unknown: nothing pushed")
            self._must("git push (the catch-up)", self._git(scratch, "push", remote, f"HEAD:refs/heads/{branch}"))
        self._must("gh pr merge", self.runner([_gh(), "pr", "merge", str(pr), "--repo", repo, "--merge",
                                               "--match-head-commit", head], top, GH_TIMEOUT))
        return merged, head

    def process(self, e: dict) -> str:
        repo, pr, remote = str(e["repo"]), int(e["pr"]), str(e.get("remote") or "origin")
        top = Path(str(e.get("dir") or ""))
        update(repo, pr, status="running", reason="")
        if not e.get("dir") or not top.is_dir():
            return self._done(e, "failed", f"its checkout {top} is gone: queue it again from a checkout")
        g = self._gated(e, top, remote)
        if isinstance(g, str):
            return g
        base = g.base or "main"
        base_ref = f"{remote}/{base}"
        before = self._sha(top, base_ref)
        try:
            scratch = self._worktree(top, g.head)
        except StepFailed as exc:
            return self._done(e, "failed", str(exc))
        try:
            merged, head = self._ship(e, top, scratch, g, remote, base_ref)
        except StepFailed as exc:
            return self._done(e, "failed", str(exc))
        finally:
            self._remove(top, scratch)
        fetched = self._git(top, "fetch", "--quiet", remote, f"+refs/heads/{base}:refs/remotes/{remote}/{base}")
        after = self._sha(top, base_ref) if fetched.ok else ""
        self.batches.setdefault(repo.lower(), []).append(Merged(e, before, after))
        return self._done(e, "merged", "caught up with main, checked and merged" if merged else "checked and merged",
                          head=head, merged=after)

    # --- the batch's full suite, and the bisection ---

    def run_suite(self, top: Path, sha: str) -> tuple[str, str]:
        """('pass' | 'fail' | 'error', a detail): the full suite on ``sha`` in a scratch worktree."""
        self._renew()
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

    def verify(self, repo: str) -> bool:
        """The repo's batch's full suite once, on the last merge; on a failure, the bisection names the culprit.
        True when the batch is green."""
        items = self.batches.pop(repo, [])
        if not items:
            return True
        top = Path(str(items[-1].entry["dir"]))
        prs = [int(m.entry["pr"]) for m in items]
        name = items[-1].entry["repo"]
        rec = {"repo": name, "sha": items[-1].after, "prs": prs, "result": "", "detail": "", "culprit": None}
        self.report.suites.append(rec)
        if not items[-1].after:
            rec.update(result="error", detail="main's tip after the merges could not be read: the batch is "
                                               "untested")
            self._log(f"{name}: the full suite NOT RUN for {', '.join(f'#{p}' for p in prs)}: {rec['detail']}")
            return False
        result, detail = self.run_suite(top, items[-1].after)
        rec.update(result=result, detail=detail)
        self._log(f"{name}: the full suite on {items[-1].after[:8]} after {', '.join(f'#{p}' for p in prs)}: "
                  f"{result.upper()} ({detail})")
        if result != "fail":
            return result == "pass"
        lo, hi = -1, len(items) - 1   # main before the batch passes (assumed), main after items[hi] fails
        while hi - lo > 1:
            mid = (lo + hi) // 2
            res, det = self.run_suite(top, items[mid].after) if items[mid].after else ("error", "its tip unknown")
            self._log(f"{name}: bisection: the full suite after #{items[mid].entry['pr']}: {res.upper()}")
            if res == "error":
                rec["detail"] += f"; the bisection stopped: {det}"
                among = ", ".join("#" + str(m.entry["pr"]) for m in items[lo + 1:hi + 1])
                self._log(f"{name}: the bisection stopped ({det}): the culprit is among {among}")
                return False
            if res == "fail":
                hi = mid
            else:
                lo = mid
        culprit = items[hi].entry
        rec["culprit"] = int(culprit["pr"])
        update(culprit["repo"], culprit["pr"], status="culprit",
               reason=f"the full suite fails on main from its merge ({items[hi].after[:8]}) on: {detail}; main is "
                      "not reverted (its owner decides)")
        self._log(f"{name}: CULPRIT #{culprit['pr']}: the full suite fails from its merge on")
        return False

    # --- the run ---

    def run(self) -> Report:
        """Every open entry, in order, under the merger's lock (the caller takes it: :func:`merge_queue`)."""
        seen: set = set()
        while True:
            e = next_open(seen)
            if e is None:
                break
            seen.add(_key(e["repo"], e["pr"]))
            self._renew()
            if self.process(e) == "merged":
                repo = str(e["repo"]).lower()
                if len(self.batches.get(repo, [])) >= self.batch and not self.verify(repo):
                    self.report.stopped = f"the full suite failed on {e['repo']}: the run stops"
                    break
        if not self.report.stopped:
            for repo in list(self.batches):
                if not self.verify(repo):
                    self.report.stopped = f"the full suite failed on {repo}: the run stops"
                    break
        return self.report


def plan(batch: int = BATCH) -> list[str]:
    """--dry-run: what the merger would do, from the queue alone (no lock, no external call)."""
    rows = [e for e in entries() if e.get("status") in OPEN_STATES]
    held = lock_holder()
    out = [f"brain ship --run --dry-run: {len(rows)} PR(s) open in {queue_path()}"]
    if held:
        out.append(f"the merger's lock is held by {filelock.describe(held)}: a run now would be refused unless it "
                   "is stale")
    counts: dict[str, int] = {}
    for e in rows:
        repo = str(e["repo"])
        counts[repo.lower()] = counts.get(repo.lower(), 0) + 1
        out.append(f"  would ship {repo}#{e['pr']} {cell(e.get('title'))!s}: the merge gate (fresh answered by the "
                   f"catch-up), main merged in when the head lacks it, the views and brain check, merge-check, the "
                   f"targeted tests, gh pr merge --match-head-commit")
        if counts[repo.lower()] % batch == 0:
            out.append(f"  then the full suite of {repo} once on main (a batch of {batch}), a bisection if it fails")
    for repo, n in counts.items():
        if n % batch:
            out.append(f"  at the end: the full suite of {repo} once for its last {n % batch} merge(s)")
    return out


def merge_queue(batch: int = BATCH, runner: Runner = run, gate=default_gate, suite=default_suite,
                say: Callable[[str], None] = print) -> Report:
    """``brain ship --run``: the lock taken (:class:`filelock.Held` when another merger runs), the queue merged,
    the lock released whatever happens."""
    m = Merger(runner, gate, suite, batch, say=say)
    lock = filelock.Lock(LOCK, LOCK_TTL, what="brain ship --run (the merger)")
    lock.acquire()
    m.lock = lock
    try:
        if lock.broken is not None:
            say(f"brain ship: a stale lock broken ({filelock.describe(lock.broken)})")
        return m.run()
    finally:
        lock.release()
