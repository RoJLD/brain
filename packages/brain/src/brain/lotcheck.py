"""``brain lot check SESSION``: whether a finished lot (a session a coordinator started) can be archived, at zero
token and read only (wi-brain-lot-close-check; packages/brain/README.md, « brain lot check »).

The desktop app's file of the session (``%LOCALAPPDATA%/Claude-Data/*/claude-code-sessions/**/<id>.json``, as
brain.tidy reads it) names its worktree and branch, the branches it wrote (``writtenBranches``) and its PRs (``prs``:
repo, number, branch). With the branches given by ``--branch``, they are the lot's branches. In each repo the session
touched (its origin checkout, the git folders it was trusted in, ``--repo-dir``):

- each worktree checked out on a lot branch, and the session's own: clean (``git status --porcelain``, untracked
  files included), else left;
- each lot branch: its PR's state (gh, else the state the app last saw; ``--offline``: the app's), merged when the PR
  is merged or the default branch holds its tip; pushed when its upstream (else ``origin/<branch>``) holds its tip.
  An open PR, or a branch neither merged nor kept (``--keep BRANCH``: on purpose), is left; an unpushed branch too;
- the scratch folders ``--scratch GLOB`` names (``{lot}``: the lot's name, ``--lot`` else the session's name), to
  remove once ready.

The answer is « ready to archive » (exit 0) with what to remove (``git worktree remove``, ``git branch -d``, the
scratch folders), or what is left (exit 1); 2 when the session is not found. Nothing is removed and nothing archived:
the archive stays the app's tool (the archive tool of the coordinator, the owner's standing permission once the work
is merged and verified), and a session never archives another that is running.
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

GH_TIMEOUT = 60


class LotError(RuntimeError):
    """The session's file is not found or not readable."""


@dataclass
class BranchState:
    repo: str
    branch: str
    pr: str = ""            # "owner/name#N"
    pr_state: str = ""      # OPEN, MERGED, CLOSED, or ''
    merged: bool = False
    pushed: bool = False
    kept: bool = False
    exists: bool = True     # the local branch is still there
    in_default: bool = False  # the default branch holds its tip: git branch -d takes it

    @property
    def left(self) -> str:
        if self.pr_state == "OPEN":
            return f"its PR {self.pr} is open"
        if not self.exists:
            return ""
        if not self.pushed and not self.merged:
            return "not pushed"
        if not self.merged and not self.kept:
            return "not merged (--keep it if on purpose)"
        return ""


@dataclass
class WorktreeState:
    repo: str
    path: str
    branch: str
    clean: bool
    dirty: list[str] = field(default_factory=list)


@dataclass
class Report:
    session: str
    title: str = ""
    lot: str = ""
    archived: bool = False
    repos: list[str] = field(default_factory=list)
    branches: list[BranchState] = field(default_factory=list)
    worktrees: list[WorktreeState] = field(default_factory=list)
    scratch: list[str] = field(default_factory=list)

    @property
    def left(self) -> list[str]:
        out = [f"worktree {w.path} has changes: {', '.join(w.dirty[:5])}" for w in self.worktrees if not w.clean]
        out += [f"branch {b.branch} ({b.repo}): {b.left}" for b in self.branches if b.left]
        return out

    @property
    def ready(self) -> bool:
        return not self.left

    def removals(self) -> list[str]:
        """The commands that remove what the lot leaves, once ready (never run here)."""
        kept = {b.branch for b in self.branches if b.kept}
        out = [f'git -C "{w.repo}" worktree remove "{w.path}"' for w in self.worktrees if w.branch not in kept]
        out += [f'git -C "{b.repo}" branch -d {b.branch}' + ("" if b.in_default else
                                                             "   (merged by squash: -d refuses it; the owner's -D)")
                for b in self.branches if b.exists and b.merged and not b.kept]
        out += [f"remove the folder {s}" for s in self.scratch]
        return out

    def to_json(self) -> dict:
        return {**asdict(self), "ready": self.ready, "left": self.left, "removals": self.removals()}


def _git(repo, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=120, stdin=subprocess.DEVNULL)


def _ok(repo, *args: str) -> str | None:
    r = _git(repo, *args)
    return r.stdout.strip() if r.returncode == 0 else None


def session_file(session: str) -> dict:
    """The app's record of ``session`` (a ``local_...`` id)."""
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        raise LotError("LOCALAPPDATA is not set: no desktop app here")
    hits = sorted(Path(base).glob(f"Claude-Data/*/claude-code-sessions/**/{session}.json"))
    if not hits:
        raise LotError(f"{session}: no session file of the desktop app")
    try:
        data = json.loads(hits[0].read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LotError(f"{hits[0]}: {exc}") from exc
    if not isinstance(data, dict):
        raise LotError(f"{hits[0]}: not a session record")
    return data


def _top(path: str) -> str | None:
    """The main checkout of the repo ``path`` is in (its common git folder's parent), or None."""
    common = _ok(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return str(Path(common).parent) if common else None


def repos_of(data: dict, extra: list[str]) -> list[str]:
    """The repos the session touched: its origin checkout and worktree, the git folders it was trusted in, extra."""
    seeds = [data.get("originCwd"), data.get("worktreePath"), data.get("cwd"), *extra]
    seeds += [a.get("gitRoot") for a in data.get("gitAnchors") or [] if isinstance(a, dict)]
    seeds += [str(w).split("\0")[0] for w in data.get("writtenBranches") or []]
    out: list[str] = []
    for s in seeds:
        top = _top(s) if s and Path(s).is_dir() else None
        if top and os.path.normcase(top) not in {os.path.normcase(x) for x in out}:
            out.append(top)
    return out


def lot_branches(data: dict, extra: list[str]) -> dict[str, dict]:
    """branch -> {pr, pr_state} from the session's PRs, branches written, own branch and ``extra``."""
    out: dict[str, dict] = {}
    for b in [data.get("branch"), *(str(w).split("\0")[-1] for w in data.get("writtenBranches") or []), *extra]:
        if b:
            out.setdefault(str(b), {"pr": "", "pr_state": "", "slug": "", "number": 0})
    for pr in data.get("prs") or []:
        if isinstance(pr, dict) and pr.get("branch"):
            out[str(pr["branch"])] = {"pr": f"{pr.get('repo')}#{pr.get('prNumber')}", "slug": str(pr.get("repo") or ""),
                                      "number": int(pr.get("prNumber") or 0),
                                      "pr_state": str(pr.get("state") or "").upper()}
    return out


def gh_state(slug: str, number: int) -> str:
    """The PR's state by gh (OPEN, MERGED, CLOSED), '' when gh does not answer."""
    exe = shutil.which("gh")
    if not exe or not slug or not number:
        return ""
    try:
        r = subprocess.run([exe, "pr", "view", str(number), "--repo", slug, "--json", "state", "-q", ".state"],
                           capture_output=True, text=True, timeout=GH_TIMEOUT, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout.strip().upper() if r.returncode == 0 else ""


def _default(repo: str) -> str:
    head = _ok(repo, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    for ref in ([head] if head else []) + ["refs/remotes/origin/main", "refs/remotes/origin/master", "main",
                                           "master"]:
        if _ok(repo, "rev-parse", "--verify", "--quiet", ref):
            return ref
    return ""


def branch_state(repo: str, branch: str, info: dict, keep: set[str]) -> BranchState | None:
    """The branch in ``repo`` (None when the repo has neither it nor its PR)."""
    tip = _ok(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
    if tip is None and not info.get("pr"):
        return None
    b = BranchState(repo, branch, info.get("pr", ""), info.get("pr_state", ""), kept=branch in keep,
                    exists=tip is not None)
    default = _default(repo)
    in_default = bool(tip and default and _git(repo, "merge-base", "--is-ancestor", tip, default).returncode == 0)
    b.merged, b.in_default = b.pr_state == "MERGED" or in_default, in_default
    upstream = _ok(repo, "rev-parse", "--verify", "--quiet", f"{branch}@{{upstream}}") or \
        _ok(repo, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}")
    b.pushed = bool(tip and upstream and _git(repo, "merge-base", "--is-ancestor", tip, upstream).returncode == 0)
    return b


def worktrees_of(repo: str, branches: set[str], own: str) -> list[WorktreeState]:
    """The linked worktrees of ``repo`` checked out on a lot branch, and the session's own worktree."""
    out = []
    path, branch = "", ""
    for line in [*(_ok(repo, "worktree", "list", "--porcelain") or "").splitlines(), ""]:
        if line.startswith("worktree "):
            path, branch = line[9:], ""
        elif line.startswith("branch "):
            branch = line[7:].removeprefix("refs/heads/")
        elif not line and path:
            mine = own and os.path.normcase(os.path.normpath(path)) == os.path.normcase(os.path.normpath(own))
            linked = os.path.normcase(path) != os.path.normcase(repo)   # never the main checkout
            if (branch in branches or mine) and linked and Path(path).is_dir():
                status = (_ok(path, "status", "--porcelain") or "").splitlines()
                out.append(WorktreeState(repo, str(Path(path)), branch, not status, [x[3:] for x in status]))
            path = ""
    return out


def check(session: str, *, branches: list[str] | None = None, keep: list[str] | None = None,
          repo_dirs: list[str] | None = None, scratch: list[str] | None = None, lot: str = "",
          offline: bool = False) -> Report:
    """The lot of ``session``: its repos, branches, worktrees and scratch folders (module docstring)."""
    data = session_file(session)
    name = lot or str((data.get("spawnedFrom") or {}).get("name") or "")
    rep = Report(session, str(data.get("title") or ""), name, bool(data.get("isArchived")))
    rep.repos = repos_of(data, repo_dirs or [])
    infos = lot_branches(data, branches or [])
    if not offline:
        _refresh(infos)
    kept = set(keep or [])
    for repo in rep.repos:
        found = (branch_state(repo, b, info, kept) for b, info in infos.items())
        rep.branches += [st for st in found if st is not None]
        rep.worktrees += worktrees_of(repo, set(infos), str(data.get("worktreePath") or ""))
    rep.scratch = _scratch(scratch or [], name)
    return rep


def _refresh(infos: dict[str, dict]) -> None:
    """Each PR's state by gh, the app's last seen state kept when gh does not answer."""
    for info in infos.values():
        info["pr_state"] = gh_state(info["slug"], info["number"]) or info["pr_state"]


def _scratch(patterns: list[str], name: str) -> list[str]:
    return [str(Path(p)) for pattern in patterns for p in sorted(glob.glob(pattern.replace("{lot}", name)))
            if Path(p).exists()]


def _branch_line(b: BranchState) -> str:
    state = "merged" if b.merged else "kept" if b.kept else "pushed" if b.pushed else "local only"
    pr = f", PR {b.pr} {b.pr_state.lower() or '?'}" if b.pr else ""
    return f"  branch   {b.branch}: {state}{pr}" + ("" if b.exists else " (local branch gone)")


def lines(rep: Report) -> list[str]:
    out = [f"lot {rep.lot or '?'} ({rep.session}): {rep.title}" + (" [archived already]" if rep.archived else "")]
    out += [f"  repo     {r}" for r in rep.repos]
    out += [_branch_line(b) for b in rep.branches]
    for w in rep.worktrees:
        out.append(f"  worktree {w.path} [{w.branch or 'detached'}]: {'clean' if w.clean else 'changes'}")
    if rep.ready:
        out.append("ready to archive: nothing left; then remove (none of it is run here):")
        out += [f"  {x}" for x in rep.removals()] or ["  nothing"]
        out.append("the archive is the app's (the coordinator's archive tool, the owner's standing permission once "
                   "merged and verified); never a session that is running")
    else:
        out.append(f"not ready: {len(rep.left)} thing(s) left")
        out += [f"  {x}" for x in rep.left]
    return out
