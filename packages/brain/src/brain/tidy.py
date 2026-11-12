"""``brain tidy``: the local branches, worktrees and, with --remote, remote branches a project's repos no longer need,
listed, then removed with --apply, at zero token (wi-brain-tidy, the owner's decision of 2026-11-03).

For each repo of the project (its ``repos:``, root and production checkouts, each git repository once):

- the default branch is origin/HEAD's target, else main, else master; a commit is merged when origin/<default> or the
  local <default> holds it;
- a linked worktree is stale when it is clean (``git status --porcelain``: nothing, untracked files included), not
  locked, not the current folder, detached on a commit some branch holds or on a merged branch, and no session works
  in it. The desktop app's state says so when it knows the worktree (``Claude-Data/*/git-worktrees.json``'s lease, the
  session files of ``claude-code-sessions`` whose cwd is in it): live while one of them is not archived, stale once
  every one is archived or gone (a lease to a session without a file). A worktree it does not know is live while its
  HEAD moved or committed in the last RECENT_HOURS. A stale worktree is removed by ``git worktree remove`` (never
  --force), after the junctions and links to folders it holds that git does not track (one into a production checkout
  is named): git's recursive removal never follows them;
- a local branch merged into the default branch, other than it, main or master, is removed by ``git branch -d``
  (never -D), unless a worktree that stays has it checked out;
- a worktree whose folder is gone is pruned (``git worktree prune``) outside production checkouts, which tidy touches
  with ``git worktree remove`` and ``git branch -d`` only (it is listed there);
- with --remote, origin's branches (``git ls-remote --heads``, read only) whose commit origin/<default> holds, other
  than the default, main, master and the head of an open PR (gh, when it answers). Deleting them (``git push origin
  --delete``) is the owner's: ``--remote --apply`` runs it only outside a Claude Code session's shell (CLAUDECODE
  unset: their terminal, their Apply); in a session it prints the ``brain queue add`` that puts the exact command to
  them.

Never an unmerged branch, a dirty or locked worktree, the main worktree, --force or -D. :func:`hygiene` is the line
brain check and brain refresh print (local only, no network).
"""

from __future__ import annotations

import json
import os
import shlex
import stat
import subprocess
import textwrap
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import config, detail, guards, net, paths, projects

RECENT_HOURS = 24
KEEP = ("main", "master")
PUSH_CHUNK = 50
JUNCTION = getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)


def _git(repo, *args: str, timeout: float = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)


def _out(repo, *args: str) -> str:
    try:
        r = _git(repo, *args)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout if r.returncode == 0 else ""


def _norm(path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _inside(path, folder) -> bool:
    p, f = _norm(path), _norm(folder)
    return p == f or p.startswith(f.rstrip("\\/") + os.sep)


# --- what git says -----------------------------------------------------------------------------------------------

@dataclass
class Worktree:
    path: str
    head: str = ""
    branch: str = ""          # the branch it has checked out, '' when detached
    locked: bool = False
    prunable: bool = False
    main: bool = False


def worktrees(repo) -> list[Worktree]:
    """``git worktree list --porcelain``: the main worktree first."""
    out: list[Worktree] = []
    for line in _out(repo, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            out.append(Worktree(str(Path(line[9:])), main=not out))
        elif not out:
            continue
        elif line.startswith("HEAD "):
            out[-1].head = line[5:]
        elif line.startswith("branch "):
            out[-1].branch = line[7:].removeprefix("refs/heads/")
        elif line.startswith("locked"):
            out[-1].locked = True
        elif line.startswith("prunable"):
            out[-1].prunable = True
    return out


def _exists(repo, ref: str) -> bool:
    return bool(_out(repo, "rev-parse", "--verify", "--quiet", ref).strip())


def default_branch(repo) -> tuple[str, list[str]]:
    """(name, the refs that hold the merged commits): origin/HEAD's target, else main, else master; its refs are
    origin/<name> and the local <name>, those that exist. ('', []) when there is none."""
    head = _out(repo, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD").strip()
    name = head.removeprefix("refs/remotes/origin/") if head.startswith("refs/remotes/origin/") else ""
    if not name:
        name = next((n for n in KEEP if _exists(repo, f"refs/remotes/origin/{n}") or _exists(repo, f"refs/heads/{n}")),
                    "")
    refs = [r for r in (f"refs/remotes/origin/{name}", f"refs/heads/{name}") if name and _exists(repo, r)]
    return (name, refs) if refs else ("", [])


def merged_branches(repo, refs: list[str]) -> set[str]:
    """The local branches whose tip one of ``refs`` holds."""
    out: set[str] = set()
    for ref in refs:
        out |= {r.removeprefix("refs/heads/") for r in
                _out(repo, "for-each-ref", f"--merged={ref}", "--format=%(refname)", "refs/heads").split()}
    return out


def held(repo, sha: str) -> bool:
    """Whether a branch, local or remote, holds the commit ``sha`` (a detached worktree's HEAD)."""
    return bool(_out(repo, "for-each-ref", "--count=1", f"--contains={sha}", "--format=%(refname)", "refs/heads",
                     "refs/remotes").strip())


def clean(path: str) -> tuple[bool, str]:
    """(clean, why not): nothing to commit, untracked files included."""
    try:
        r = _git(path, "status", "--porcelain", "--ignore-submodules=none")
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"git status failed ({exc})"
    if r.returncode:
        return False, f"git status failed ({r.stderr.strip().splitlines()[-1] if r.stderr.strip() else r.returncode})"
    n = len(r.stdout.splitlines())
    return (True, "") if not n else (False, f"{n} change(s) not committed")


def last_activity(path: str) -> float:
    """When the worktree's HEAD last moved (its reflog, its HEAD file) or committed, as a timestamp; 0 when unknown."""
    times = []
    gitdir = _out(path, "rev-parse", "--absolute-git-dir").strip()
    for name in ("logs/HEAD", "HEAD"):
        try:
            times.append(os.path.getmtime(os.path.join(gitdir, name)) if gitdir else 0)
        except OSError:
            pass
    ct = _out(path, "log", "-1", "--format=%ct").strip()
    if ct.isdigit():
        times.append(float(ct))
    return max(times, default=0.0)


# --- the desktop app's sessions ----------------------------------------------------------------------------------

@dataclass
class AppState:
    seen: bool = False
    leases: dict[str, str] = field(default_factory=dict)      # worktree folder -> the session leasing it
    sessions: dict[str, dict] = field(default_factory=dict)   # session id -> {cwd, archived}
    cli: dict[str, str] = field(default_factory=dict)        # Claude Code session id (a transcript's) -> session id


def app_state() -> AppState:
    """What the Claude desktop app knows of its worktrees and sessions (``%LOCALAPPDATA%/Claude-Data/*``), read only;
    an empty state when it is not on this machine."""
    st = AppState()
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        return st
    for f in sorted(Path(base).glob("Claude-Data/*/git-worktrees.json")):
        st.seen = True
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for w in ((data.get("worktrees") or {}) if isinstance(data, dict) else {}).values():
            if isinstance(w, dict) and w.get("path") and w.get("leasedBy"):
                st.leases[_norm(w["path"])] = str(w["leasedBy"])
    for f in Path(base).glob("Claude-Data/*/claude-code-sessions/**/local_*.json"):
        st.seen = True
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("sessionId"):
            st.sessions[str(data["sessionId"])] = {"cwd": _norm(data.get("cwd") or ""),
                                                   "archived": bool(data.get("isArchived"))}
            if data.get("cliSessionId"):
                st.cli[str(data["cliSessionId"])] = str(data["sessionId"])
    return st


def session_state(path: str, st: AppState) -> tuple[str, str]:
    """(state, the session it names) of a worktree in the app's eyes: live, archived, gone, or unknown when the app
    knows no session of it."""
    ids = {st.leases[_norm(path)]} if _norm(path) in st.leases else set()
    ids |= {sid for sid, s in st.sessions.items() if s["cwd"] and _inside(s["cwd"], path)}
    if not ids:
        return "unknown", ""
    live = sorted(sid for sid in ids if sid in st.sessions and not st.sessions[sid]["archived"])
    if live:
        return "live", live[0]
    archived = sorted(sid for sid in ids if sid in st.sessions)
    return ("archived", archived[0]) if archived else ("gone", sorted(ids)[0])


# --- links a worktree holds --------------------------------------------------------------------------------------

def _is_dir_link(entry: os.DirEntry) -> bool:
    """A junction, or a symbolic link to a folder."""
    try:
        if entry.is_symlink():
            return os.path.isdir(entry.path)
        return getattr(entry.stat(follow_symlinks=False), "st_reparse_tag", 0) == JUNCTION
    except OSError:
        return False


def dir_links(root: str) -> list[str]:
    """The junctions and links to folders under ``root``, not followed, its .git skipped."""
    out, stack = [], [root]
    while stack:
        d = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            if d == root and e.name == ".git":
                continue
            if _is_dir_link(e):
                out.append(e.path)
            else:
                try:
                    if e.is_dir(follow_symlinks=False):
                        stack.append(e.path)
                except OSError:
                    pass
    return sorted(out)


def untracked_links(path: str) -> list[str]:
    """The folder links of the worktree ``path`` that git does not track (git places none: a junction is local)."""
    return [p for p in dir_links(path)
            if _git(path, "ls-files", "--error-unmatch", "--", os.path.relpath(p, path)).returncode]


def _unlink(path: str) -> None:
    """Remove the link itself, never what it points to: rmdir for a junction or a folder link on Windows."""
    try:
        os.unlink(path)
    except OSError:
        os.rmdir(path)


# --- the plan ----------------------------------------------------------------------------------------------------

@dataclass
class Step:
    kind: str      # worktree, branch, prune, remote
    target: str
    remove: bool
    why: str
    links: list[str] = field(default_factory=list)   # a worktree's folder links to remove first
    into_production: list[str] = field(default_factory=list)
    after: str = ""   # a branch's worktree, removed first


@dataclass
class RepoPlan:
    project: str
    name: str
    path: str
    production: bool
    default: str = ""
    error: str = ""
    steps: list[Step] = field(default_factory=list)
    remote: list[str] | None = None    # merged remote branches (--remote), None when not asked
    remote_note: str = ""

    def of(self, kind: str, remove: bool | None = None) -> list[Step]:
        return [s for s in self.steps if s.kind == kind and (remove is None or s.remove == remove)]


def _repos(p: projects.Project) -> list[tuple[str, Path, bool]]:
    """(name, folder, production) of each git repository of ``p``, once each (by their common git folder)."""
    try:
        repos = [(r.name, r.path, r.production) for r in projects.repos_of(p)]
    except projects.RepoError:
        prod = {_norm(x) for x in p.production}
        repos = [(Path(x).name.lower(), Path(x), _norm(x) in prod) for x in [p.root, *p.production]]
    out, seen = [], set()
    for name, path, prod in repos:
        common = _out(path, "rev-parse", "--path-format=absolute", "--git-common-dir").strip() if path.is_dir() else ""
        if not common or _norm(common) in seen:
            continue
        seen.add(_norm(common))
        out.append((name, path, prod))
    return out


def _ago(ts: float, now: float) -> str:
    h = (now - ts) / 3600
    return f"{h:.0f} h" if h < 48 else f"{h / 24:.0f} days"


def plan_repo(project: str, name: str, repo: Path, production: bool, *, remote: bool = False,
              state: list | None = None, now: float | None = None, cwd: str | None = None,
              prod_roots: list[str] | None = None) -> RepoPlan:
    """What tidy would do in one repo. ``state`` is a one-slot cache of the app's state, read when a linked worktree
    needs it."""
    now = time.time() if now is None else now
    cwd = cwd or os.getcwd()
    rp = RepoPlan(project, name, str(paths.main_checkout(repo) or repo), production)
    rp.default, refs = default_branch(repo)
    if not refs:
        rp.error = "no default branch (origin/HEAD, main or master)"
        return rp
    merged = merged_branches(repo, refs)
    staying: dict[str, str] = {}   # branch -> the worktree that keeps it checked out
    leaving: dict[str, str] = {}   # branch -> its stale worktree
    for wt in worktrees(repo):
        if wt.main:
            if wt.branch:
                staying[wt.branch] = wt.path
            continue
        if wt.prunable or not os.path.isdir(wt.path):
            rp.steps.append(Step("prune", wt.path, not production,
                                 "its folder is gone" + ("; a production checkout's: git worktree prune is the "
                                                         "owner's" if production else "")))
            continue
        why, remove = _stale(wt, repo, merged, state, now, cwd)
        step = Step("worktree", wt.path, remove, why)
        if remove:
            step.links = untracked_links(wt.path)
            roots = guards.production_roots() if prod_roots is None else prod_roots
            step.into_production = [lk for lk in step.links
                                    if guards.in_production(os.path.realpath(lk), roots)]
            if wt.branch:
                leaving[wt.branch] = wt.path
        elif wt.branch:
            staying[wt.branch] = wt.path
        rp.steps.append(step)
    for b in sorted(merged):
        if b == rp.default or b in KEEP:
            continue
        if b in staying:
            rp.steps.append(Step("branch", b, False, f"checked out in {staying[b]}"))
        else:
            rp.steps.append(Step("branch", b, True, "after its worktree" if b in leaving else "merged",
                                 after=leaving.get(b, "")))
    if remote:
        rp.remote, rp.remote_note = remote_merged(repo, rp.default, staying)
    return rp


def _stale(wt: Worktree, repo: Path, merged: set[str], state: list | None, now: float,
           cwd: str) -> tuple[str, bool]:
    """(why, stale) for a linked worktree."""
    if wt.locked:
        return "locked", False
    if _inside(cwd, wt.path):
        return "the current folder", False
    if wt.branch and wt.branch not in merged:
        return f"{wt.branch} is not merged", False
    if not wt.branch and not held(repo, wt.head):
        return "detached on a commit no branch holds", False
    if state is not None and not state:
        state.append(app_state())
    known, sid = session_state(wt.path, state[0] if state else app_state())
    if known == "live":
        return f"session {sid} is open", False
    if known in ("archived", "gone"):
        idle = f"session {sid} {known}"
    else:
        last = last_activity(wt.path)
        if last and now - last < RECENT_HOURS * 3600:
            return f"no session known, active {_ago(last, now)} ago", False
        idle = f"no session known, idle {_ago(last, now) if last else 'for long'}"
    ok, why = clean(wt.path)
    if not ok:
        return why, False
    return f"{f'on {wt.branch} (merged)' if wt.branch else 'detached'}, clean, {idle}", True


def remote_merged(repo: Path, default: str, staying: dict[str, str] | None = None) -> tuple[list[str], str]:
    """(origin's branches merged into origin/<default>, a note): read with git ls-remote (no fetch); a branch whose
    commit is not here yet is not listed; kept: one a worktree that stays has checked out (``staying``: its session
    may push again), and the heads of open PRs when gh answers."""
    ref = f"refs/remotes/origin/{default}"
    if not _exists(repo, ref):
        return [], f"no {ref}"
    try:
        r = net.call(f"git-remote:{Path(repo).name}", lambda: _git(repo, "ls-remote", "--heads", "origin", timeout=60),
                     retries=0)   # its breaker (brain.net): a remote that timed out is skipped for a window
    except (OSError, subprocess.SubprocessError) as exc:
        return [], f"git ls-remote failed ({exc})"
    if r.returncode:
        return [], f"git ls-remote failed ({r.stderr.strip().splitlines()[-1] if r.stderr.strip() else r.returncode})"
    held_by = set(_out(repo, "rev-list", ref).split())
    heads = [(sha, name.removeprefix("refs/heads/")) for sha, _, name in
             (line.partition("\t") for line in r.stdout.splitlines()) if name.startswith("refs/heads/")]
    out = sorted(n for sha, n in heads if sha in held_by and n != default and n not in KEEP)
    open_heads, note = _open_pr_heads(repo)
    notes = [note] if note else []
    for what, keep in (("checked out in a worktree that stays", set(staying or {})),
                       ("the head of an open PR", open_heads)):
        kept = [n for n in out if n in keep]
        out = [n for n in out if n not in keep]
        if kept:
            notes.append(f"{len(kept)} kept, {what}: {', '.join(kept)}")
    return out, "; ".join([f"against origin/{default} as last fetched", *notes])


def _open_pr_heads(repo: Path) -> tuple[set[str], str]:
    try:
        # no breaker here (brain.net): the open PRs' heads protect branches from --apply, so gh is always asked
        r = subprocess.run(["gh", "pr", "list", "--state", "open", "--json", "headRefName", "--limit", "500"],
                           cwd=str(repo), capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=60, stdin=subprocess.DEVNULL)
        if r.returncode == 0:
            return {p["headRefName"] for p in json.loads(r.stdout or "[]")}, ""
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        pass
    return set(), "gh did not list the open PRs: their heads are not told apart"


def plan(scope: list[projects.Project], *, remote: bool = False) -> list[RepoPlan]:
    state: list = []
    roots = guards.production_roots()
    out = []
    for p in scope:
        if not p.root.is_dir():
            out.append(RepoPlan(p.name, p.name, str(p.root), False, error="its root is not on this machine"))
            continue
        for name, path, prod in _repos(p):
            out.append(plan_repo(p.name, name, path, prod, remote=remote, state=state, prod_roots=roots))
    return out


# --- doing it ----------------------------------------------------------------------------------------------------

def _run(repo, *args: str) -> tuple[bool, str]:
    try:
        r = _git(repo, *args, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    text = (r.stderr or r.stdout).strip().splitlines()
    return r.returncode == 0, text[-1] if text else ""


def apply_repo(rp: RepoPlan, *, remote: bool = False, env: dict | None = None) -> list[str]:
    """Remove what the plan marks, in order: stale worktrees (their folder links first), the pruned ones, the merged
    branches, then (--remote, outside a Claude Code session's shell) origin's merged branches. One line each."""
    lines: list[str] = []
    gone: set[str] = set()
    for s in rp.of("worktree", True):
        ok, why = clean(s.target)   # the plan may be minutes old
        if not ok:
            lines.append(f"kept {s.target}: {why}")
            continue
        for lk in s.links:
            try:
                _unlink(lk)
                lines.append(f"unlinked {lk}" + (" (into production)" if lk in s.into_production else ""))
            except OSError as exc:
                lines.append(f"failed to unlink {lk}: {exc}")
        ok, msg = _run(rp.path, "worktree", "remove", s.target)
        lines.append(f"removed worktree {s.target}" if ok else f"failed: git worktree remove {s.target}: {msg}")
        if ok:
            gone.add(s.target)
    if rp.of("prune", True) and not rp.production:
        ok, msg = _run(rp.path, "worktree", "prune")
        lines.append("pruned the worktrees whose folder is gone" if ok else f"failed: git worktree prune: {msg}")
    for s in rp.of("branch", True):
        if s.after and s.after not in gone:
            lines.append(f"kept {s.target}: its worktree stays")
            continue
        ok, msg = _run(rp.path, "branch", "-d", s.target)
        lines.append(f"deleted branch {s.target}" if ok else f"failed: git branch -d {s.target}: {msg}")
    if remote and rp.remote:
        lines += apply_remote(rp, env)
    return lines


def queue_command(rp: RepoPlan) -> list[str]:
    """The brain queue add that puts the deletion of ``rp``'s merged remote branches to the owner, as words."""
    run = ["brain", "tidy", "--project", rp.project, "--remote", "--apply"]
    return ["brain", "queue", "add", "--kind", "action", "--title",
            f"Delete the {len(rp.remote or [])} merged remote branches of {rp.name}",
            "--what", f"{' '.join(run)}: git push origin --delete, the branches origin/{rp.default} holds "
                      f"(brain tidy --project {rp.project} --remote lists them)",
            "--command", " ".join(run), "--item", "wi-brain-tidy"]


def apply_remote(rp: RepoPlan, env: dict | None = None) -> list[str]:
    why = detail.refused(env)
    if why:
        return [f"remote: {len(rp.remote or [])} merged branch(es) left: {why}; put it to "
                f"{config.owner_of()}: {shlex.join(queue_command(rp))}"]
    lines = []
    names = list(rp.remote or [])
    for i in range(0, len(names), PUSH_CHUNK):
        chunk = names[i:i + PUSH_CHUNK]
        ok, msg = _run(rp.path, "push", "origin", "--delete", *chunk)
        lines.append(f"deleted {len(chunk)} remote branch(es) of origin" if ok else
                     f"failed: git push origin --delete ({len(chunk)} branches): {msg}")
    return lines


# --- views -------------------------------------------------------------------------------------------------------

def _wrap(prefix: str, names: list[str]) -> list[str]:
    return textwrap.wrap(", ".join(names), width=118, initial_indent=prefix, subsequent_indent=" " * len(prefix),
                         break_on_hyphens=False, break_long_words=False)


def render(rp: RepoPlan, *, remote: bool = False) -> list[str]:
    head = f"== {rp.project}: {rp.name} ({Path(rp.path).as_posix()})" + (", production" if rp.production else "")
    if rp.error:
        return [f"{head}: {rp.error}"]
    out = [f"{head}, default {rp.default}"]
    wts = rp.of("worktree")
    gone = rp.of("prune")
    out.append(f"worktrees: {len(wts) + len(gone)} linked, {len(rp.of('worktree', True))} stale"
               + (f", {len(gone)} whose folder is gone" if gone else ""))
    for s in wts + gone:
        verb = "remove" if s.remove else "keep  "
        out.append(f"  {verb} {Path(s.target).as_posix()}: {s.why}")
        for lk in s.links:
            out.append(f"         then unlink {Path(lk).as_posix()}" +
                       (" (a junction into production)" if lk in s.into_production else ""))
    gone_b = [s.target for s in rp.of("branch", True)]
    kept_b = rp.of("branch", False)
    out.append(f"branches: {len(gone_b) + len(kept_b)} merged into {rp.default}, {len(gone_b)} to delete")
    if gone_b:
        out += _wrap("  delete ", gone_b)
    out += [f"  keep   {s.target}: {s.why}" for s in kept_b]
    if remote:
        names = rp.remote or []
        out.append(f"remote: {len(names)} merged branch(es) of origin" + (f" ({rp.remote_note})" if rp.remote_note
                                                                          else ""))
        if names:
            out += _wrap("  delete ", names)
    return out


def counts(plans: list[RepoPlan]) -> dict:
    return {"worktrees": sum(len(rp.of("worktree", True)) for rp in plans),
            "pruned": sum(len(rp.of("prune", True)) for rp in plans),
            "branches": sum(len(rp.of("branch", True)) for rp in plans),
            "remote": sum(len(rp.remote or []) for rp in plans)}


def main(scope: list[projects.Project], *, remote: bool = False, apply: bool = False, as_json: bool = False,
         env: dict | None = None) -> int:
    plans = plan(scope, remote=remote)
    if as_json and not apply:
        print(json.dumps([asdict(rp) for rp in plans], ensure_ascii=False, indent=1))
        return 0
    failed = False
    for rp in plans:
        print("\n".join(render(rp, remote=remote)))
        if apply and not rp.error:
            lines = apply_repo(rp, remote=remote, env=env)
            failed = failed or any(ln.startswith("failed") for ln in lines)
            print("\n".join(f"  {ln}" for ln in lines) or "  nothing to remove")
    n = counts(plans)
    total = (f"{n['worktrees']} stale worktree(s), {n['branches']} merged branch(es)"
             + (f", {n['pruned']} worktree(s) to prune" if n["pruned"] else "")
             + (f", {n['remote']} merged remote branch(es)" if remote else ""))
    if apply:
        print(f"tidy: applied ({total})" + ("; some steps failed" if failed else ""))
    else:
        more = " --remote" if remote else ""
        print(f"tidy: dry run, nothing removed: {total}; brain tidy{more} --apply removes them"
              + (f" (the remote ones: {config.owner_of()}'s, from their terminal or the queue)" if remote else ""))
    return 1 if failed else 0


def hygiene(p: projects.Project) -> str | None:
    """The hygiene pass's line (brain check, brain refresh): what brain tidy would remove locally in ``p``'s repos,
    None when nothing (or no git repo)."""
    try:
        plans = plan([p]) if p.root.is_dir() else []
    except Exception as exc:  # a hygiene line never fails a check
        return f"warning: brain tidy could not plan: {exc}"
    n = counts(plans)
    if not (n["worktrees"] or n["branches"] or n["pruned"]):
        return None
    parts = [f"{n['worktrees']} stale worktree(s)" if n["worktrees"] else "",
             f"{n['branches']} merged branch(es)" if n["branches"] else "",
             f"{n['pruned']} worktree(s) to prune" if n["pruned"] else ""]
    return f"warning: tidy: {', '.join(x for x in parts if x)} to remove: brain tidy (the list), then --apply"
