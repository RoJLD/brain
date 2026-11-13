"""``brain lot check SESSION``: whether a finished lot (a session a coordinator started) can be archived, at zero
token and read only (wi-brain-lot-close-check; packages/brain/README.md, « brain lot check »).

The desktop app's file of the session (``%LOCALAPPDATA%/Claude-Data/*/claude-code-sessions/**/<id>.json``, the newest
when several hold it, as brain.tidy reads them) names its worktree and branch, the branches it wrote
(``writtenBranches``) and its PRs (``prs``: repo, number, branch). With the branches given by ``--branch``, they are
the lot's branches, never a repo's default branch nor the branch its main checkout holds. In each repo the session
touched (its origin checkout, the git folders it was trusted in, ``--repo-dir``):

- each worktree checked out on a lot branch, and the session's own: clean (``git status --porcelain``, untracked
  files included; a status git cannot give is left too); the session's own on a detached HEAD must have its commits
  on a remote branch; a worktree whose folder is gone is pruned (``git worktree prune``) before anything else;
- each lot branch: its PRs (those of the repo whose ``origin`` is the PR's repo), their state by gh, else as the app
  last saw it (``--offline``), said with its source. It is left while a PR is open; while it holds a commit that is
  neither pushed (its upstream or ``origin/<branch>``) nor in the default branch, a PR merged by squash included;
  while it is neither merged (a PR merged, or the default branch holds its tip) nor kept (``--keep BRANCH``, on
  purpose), a PR closed unmerged included;
- the scratch folders ``--scratch GLOB`` names (``{lot}``: the lot's name, ``--lot`` else the session's name; a
  pattern with ``{lot}`` and no name is refused), to remove once ready.

The answer is « ready to archive » (exit 0) with what to remove (``git worktree prune``, ``git worktree remove``,
``git branch -d``, the scratch folders), or what is left (exit 1); 2 when the session is not found or a pattern is
refused. Nothing is removed and nothing archived: the archive stays the app's tool (the coordinator's, under the
owner's standing permission once the work is merged and verified), and a session never archives one that is running.
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import public

GH_TIMEOUT = 60


class LotError(RuntimeError):
    """The session's file is not found or not readable, or a pattern is refused."""


@dataclass
class BranchState:
    repo: str
    branch: str
    prs: list[dict] = field(default_factory=list)   # {pr, state, source}
    merged: bool = False
    pushed: bool = False
    kept: bool = False
    exists: bool = True      # the local branch is still there
    in_default: bool = False  # the default branch holds its tip: git branch -d takes it

    @property
    def states(self) -> set[str]:
        return {p["state"] for p in self.prs}

    @property
    def left(self) -> str:
        opened = [p["pr"] for p in self.prs if p["state"] == "OPEN"]
        if opened:
            return f"its PR {', '.join(opened)} is open"
        if self.exists and not self.pushed and not self.in_default:
            return "a commit neither pushed nor in the default branch"
        if not self.merged and not self.kept:
            closed = "its PR closed unmerged; " if "CLOSED" in self.states else ""
            return f"{closed}not merged (--keep it if on purpose)"
        return ""


@dataclass
class WorktreeState:
    repo: str
    path: str
    branch: str
    clean: bool
    dirty: list[str] = field(default_factory=list)
    problem: str = ""        # a status git could not give, commits on a detached HEAD no remote holds


@dataclass
class Report:
    session: str
    title: str = ""
    lot: str = ""
    archived: bool = False
    repos: list[str] = field(default_factory=list)
    branches: list[BranchState] = field(default_factory=list)
    worktrees: list[WorktreeState] = field(default_factory=list)
    prunable: list[str] = field(default_factory=list)   # repos whose worktree folder is gone
    scratch: list[str] = field(default_factory=list)

    @property
    def left(self) -> list[str]:
        out = [f"worktree {w.path}: {w.problem}" for w in self.worktrees if w.problem]
        out += [f"worktree {w.path} has changes: {', '.join(w.dirty[:5])}" for w in self.worktrees
                if not w.clean and not w.problem]
        out += [f"branch {b.branch} ({b.repo}): {b.left}" for b in self.branches if b.left]
        return out

    @property
    def ready(self) -> bool:
        return not self.left

    def removals(self) -> list[str]:
        """The commands that remove what the lot leaves, once ready (never run here); none while it is not."""
        if not self.ready:
            return []
        kept = {b.branch for b in self.branches if b.kept}
        out = [f'git -C "{r}" worktree prune' for r in self.prunable]
        out += [f'git -C "{w.repo}" worktree remove "{w.path}"' for w in self.worktrees if w.branch not in kept]
        out += [f'git -C "{b.repo}" branch -d "{b.branch}"' + ("" if b.in_default else
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
    try:
        r = _git(repo, *args)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def session_file(session: str) -> dict:
    """The app's record of ``session`` (a ``local_...`` id): the newest file that holds it."""
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        raise LotError("LOCALAPPDATA is not set: no desktop app here")
    pattern = f"Claude-Data/*/claude-code-sessions/**/{glob.escape(session)}.json"
    hits = sorted(Path(base).glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True)
    if not hits:
        raise LotError(f"{session}: no session file of the desktop app")
    try:
        data = json.loads(hits[0].read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LotError(f"{hits[0]}: {exc}") from exc
    if not isinstance(data, dict):
        raise LotError(f"{hits[0]}: not a session record")
    return data


def _main_checkout(path: str) -> str | None:
    """The main worktree of the repo ``path`` is in: the first entry of ``git worktree list``."""
    out = _ok(path, "worktree", "list", "--porcelain")
    first = next((x[9:] for x in (out or "").splitlines() if x.startswith("worktree ")), "")
    return str(Path(first)) if first else None


def _same(a: str, b: str) -> bool:
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def repos_of(data: dict, extra: list[str]) -> list[str]:
    """The repos the session touched: its origin checkout and worktree, the git folders it was trusted in, extra."""
    seeds = [data.get("originCwd"), data.get("worktreePath"), data.get("cwd"), *extra]
    seeds += [a.get("gitRoot") for a in data.get("gitAnchors") or [] if isinstance(a, dict)]
    seeds += [str(w).split("\0")[0] for w in data.get("writtenBranches") or []]
    out: list[str] = []
    for s in seeds:
        top = _main_checkout(str(s)) if s and Path(str(s)).is_dir() else None
        if top and not any(_same(top, x) for x in out):
            out.append(top)
    return out


def lot_branches(data: dict, extra: list[str]) -> dict[str, list[dict]]:
    """branch -> its PRs ({pr, slug, number, state, source}) from the session's PRs, branches written, own branch
    and ``extra``."""
    out: dict[str, list[dict]] = {}
    for b in [data.get("branch"), *(str(w).split("\0")[-1] for w in data.get("writtenBranches") or []), *extra]:
        if b:
            out.setdefault(str(b), [])
    for pr in data.get("prs") or []:
        if not isinstance(pr, dict) or not pr.get("branch"):
            continue
        try:
            number = int(pr.get("prNumber") or 0)
        except (TypeError, ValueError):
            continue
        slug = str(pr.get("repo") or "")
        out.setdefault(str(pr["branch"]), []).append({"pr": f"{slug}#{number}", "slug": slug, "number": number,
                                                      "state": str(pr.get("state") or "").upper(), "source": "app"})
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
        if _ok(repo, "rev-parse", "--verify", "--quiet", ref) is not None:
            return ref
    return ""


def _holds(repo: str, ref: str | None, tip: str) -> bool:
    return bool(ref) and _git(repo, "merge-base", "--is-ancestor", tip, ref).returncode == 0


def branch_state(repo: str, branch: str, prs: list[dict], keep: set[str], slug: str) -> BranchState | None:
    """The branch in ``repo`` (None when the repo has neither it nor a PR of its own on it)."""
    mine = [{k: p[k] for k in ("pr", "state", "source")} for p in prs if p["slug"].lower() == slug.lower()]
    tip = _ok(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
    if tip is None and not mine:
        return None
    b = BranchState(repo, branch, mine, kept=branch in keep, exists=tip is not None)
    if tip:
        b.in_default = _holds(repo, _default(repo), tip)
        b.pushed = any(_holds(repo, _ok(repo, "rev-parse", "--verify", "--quiet", ref), tip)
                       for ref in (f"{branch}@{{upstream}}", f"refs/remotes/origin/{branch}"))
    b.merged = "MERGED" in b.states or b.in_default
    return b


def _worktree(repo: str, path: str, branch: str) -> WorktreeState:
    status = _ok(path, "status", "--porcelain")
    if status is None:
        return WorktreeState(repo, path, branch, False, problem="git cannot read its status")
    dirty = [x[3:] for x in status.splitlines()]
    w = WorktreeState(repo, path, branch, not dirty, dirty)
    if not branch and not _ok(path, "branch", "-r", "--contains", "HEAD"):
        w.problem = "a detached HEAD whose commits no remote branch holds"
    return w


def worktrees_of(repo: str, branches: set[str], own: str) -> tuple[list[WorktreeState], bool]:
    """(the linked worktrees of ``repo`` on a lot branch and the session's own, whether one's folder is gone)."""
    listing = _ok(repo, "worktree", "list", "--porcelain")
    if listing is None:
        return [WorktreeState(repo, repo, "", False, problem="git cannot list its worktrees")], False
    out, gone = [], False
    entries = [e for e in listing.split("\n\n") if e.strip()]
    for e in entries[1:]:   # the first is the main checkout: never the lot's to remove
        fields = dict((x.split(" ", 1) + [""])[:2] for x in e.splitlines())
        path, branch = fields.get("worktree", ""), fields.get("branch", "").removeprefix("refs/heads/")
        if "prunable" in fields or not Path(path).is_dir():
            gone = gone or branch in branches
            continue
        if branch in branches or (own and _same(path, own)):
            out.append(_worktree(repo, str(Path(path)), branch))
    return out, gone


def _not_lot(repo: str) -> set[str]:
    """The branches a lot never owns in ``repo``: its default branch and the one its main checkout holds."""
    out = {"main", "master"}
    default = _default(repo)
    if default:
        out.add(default.removeprefix("refs/remotes/origin/").removeprefix("refs/heads/"))
    head = _ok(repo, "symbolic-ref", "--quiet", "--short", "HEAD")
    if head:
        out.add(head)
    return out


def _slug(repo: str) -> str:
    """``owner/name`` of the repo's origin as configured (an insteadOf rewrite aside), '' when not GitHub."""
    return public.repo_slug(_ok(repo, "config", "--get", "remote.origin.url") or "")


def check(session: str, *, branches: list[str] | None = None, keep: list[str] | None = None,
          repo_dirs: list[str] | None = None, scratch: list[str] | None = None, lot: str = "",
          offline: bool = False) -> Report:
    """The lot of ``session``: its repos, branches, worktrees and scratch folders (module docstring)."""
    data = session_file(session)
    spawned = data.get("spawnedFrom") if isinstance(data.get("spawnedFrom"), dict) else {}
    name = lot or str(spawned.get("name") or "")
    rep = Report(session, str(data.get("title") or ""), name, bool(data.get("isArchived")))
    rep.scratch = _scratch(scratch or [], name)
    rep.repos = repos_of(data, repo_dirs or [])
    infos = lot_branches(data, branches or [])
    if not offline:
        _refresh(infos)
    for repo in rep.repos:
        _read_repo(rep, repo, infos, set(keep or []), str(data.get("worktreePath") or ""))
    return rep


def _read_repo(rep: Report, repo: str, infos: dict[str, list[dict]], kept: set[str], own: str) -> None:
    """The lot's branches and worktrees in ``repo`` into ``rep``."""
    mine = {b: prs for b, prs in infos.items() if b not in _not_lot(repo)}
    slug = _slug(repo)
    found = (branch_state(repo, b, prs, kept, slug) for b, prs in mine.items())
    rep.branches += [st for st in found if st is not None]
    trees, gone = worktrees_of(repo, set(mine), own)
    rep.worktrees += trees
    if gone:
        rep.prunable.append(repo)


def _refresh(infos: dict[str, list[dict]]) -> None:
    """Each PR's state by gh, the app's last seen state kept when gh does not answer."""
    for prs in infos.values():
        for p in prs:
            state = gh_state(p["slug"], p["number"])
            if state:
                p["state"], p["source"] = state, "gh"


def _scratch(patterns: list[str], name: str) -> list[str]:
    if not name and any("{lot}" in p for p in patterns):
        raise LotError("--scratch names {lot} and the lot has no name (--lot NAME)")
    return [str(Path(p)) for pattern in patterns for p in sorted(glob.glob(pattern.replace("{lot}", glob.escape(name))))
            if Path(p).exists()]


def _branch_line(b: BranchState) -> str:
    state = "merged" if b.merged else "kept" if b.kept else "pushed" if b.pushed else "local only"
    prs = "".join(f", PR {p['pr']} {p['state'].lower() or '?'} ({p['source']})" for p in b.prs)
    return f"  branch   {b.branch}: {state}{prs}" + ("" if b.exists else " (local branch gone)")


def lines(rep: Report) -> list[str]:
    out = [f"lot {rep.lot or '?'} ({rep.session}): {rep.title}" + (" [archived already]" if rep.archived else "")]
    out += [f"  repo     {r}" for r in rep.repos]
    out += [_branch_line(b) for b in rep.branches]
    for w in rep.worktrees:
        out.append(f"  worktree {w.path} [{w.branch or 'detached'}]: {'clean' if w.clean else 'changes'}")
    out += [f"  prune    {r}: a worktree's folder is gone" for r in rep.prunable]
    if rep.ready:
        out.append("ready to archive: nothing left; then remove (none of it is run here):")
        out += [f"  {x}" for x in rep.removals()] or ["  nothing"]
        out.append("the archive is the app's (the coordinator's archive tool, the owner's standing permission once "
                   "merged and verified); never a session that is running")
    else:
        out.append(f"not ready: {len(rep.left)} thing(s) left")
        out += [f"  {x}" for x in rep.left]
    return out
