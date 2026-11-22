"""The owner's engine clone kept current without their gesture (wi-brain-clone-autopull; the owner's answer of
2026-11-18: a fast-forward only).

After an engine PR merges, the owner's clone of the engine (where they cut the tags, and where the audit's code
references are read) is behind its remote's default branch until someone pulls it. ``brain refresh`` (the merge
path's refresh) fast-forwards it, under one rule:

- **which clone**: config.json ``engine.clone`` (absolute, ``~``, or relative to the config's folder), else the
  registry's checkout whose remote is ``engine.repo`` (brain.projects.repos_of, brain.public.remote_of); an
  ``engine.clone`` missing on this machine is said, and the registry's is used (config.json is every machine's);
  none found: nothing is said, nothing done;
- **only when** it is on its remote's default branch (``origin/HEAD``, else ``main``), no tracked file has a change
  and no merge, rebase, cherry-pick or revert is in progress: then ``git fetch origin <branch>`` and ``git merge
  --ff-only`` of what was fetched, which moves nothing when the branch has commits of its own; refused before the
  merge when it would write over a file git ignores here (a local file the remote starts tracking);
- **never** a switch, a commit, a reset, a stash or a checkout of a file: any other state is said in one line, and
  the clone is left as it was.

Every git call is bounded (:data:`TIMEOUT_S`; its whole process tree stopped at the deadline, git's helpers included)
and runs with no terminal prompt. Standard library and the engine's own modules only; it never raises: a failure is a
line.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

TIMEOUT_S = 60
PULLED, SAME, SKIPPED, FAILED = "pulled", "same", "skipped", "failed"
IN_PROGRESS = {"MERGE_HEAD": "merge", "CHERRY_PICK_HEAD": "cherry-pick", "REVERT_HEAD": "revert",
               "rebase-merge": "rebase", "rebase-apply": "rebase"}   # the files git keeps while one is in progress
Runner = Callable[..., subprocess.CompletedProcess]


@dataclass
class Result:
    clone: Path | None
    state: str = SKIPPED      # pulled, same, skipped or failed
    line: str = ""

    def said(self) -> str:
        if self.clone is None:
            return f"engine clone: {self.line}" if self.line else ""
        return f"engine clone {self.clone}: {self.line}"


def bounded(argv: list[str], *, timeout: float = TIMEOUT_S, **kw) -> subprocess.CompletedProcess:
    """subprocess.run's contract, its whole process tree stopped at the deadline (git's https or ssh helper holds the
    pipes after git itself is killed, on Windows): TimeoutExpired then."""
    from .formats import _kill_tree
    kw.pop("capture_output", None)
    group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **group, **kw)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        try:
            proc.communicate(timeout=5)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            pass
        raise
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


def _git(repo: Path, args: list[str], runner: Runner) -> tuple[int, str]:
    """(exit code, stdout) when git succeeds, (exit code, stdout and stderr) when it fails; 124 on the deadline, 127
    when it could not run."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
    try:
        r = runner(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                   errors="replace", timeout=TIMEOUT_S, stdin=subprocess.DEVNULL, env=env)
    except subprocess.TimeoutExpired:
        return 124, f"git {args[0]} timed out after {TIMEOUT_S}s"
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, f"git could not run ({exc.__class__.__name__})"
    if r.returncode == 0:
        return 0, (r.stdout or "").strip()
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


def _last(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return " / ".join(lines[-2:]) or "no output"


def find(root: Path | None = None, cfg=None) -> tuple[Path | None, str]:
    """(the owner's engine clone, a note): config.json ``engine.clone``, else the registry's checkout whose remote is
    ``engine.repo``; (None, '') when neither names one here. The note says an ``engine.clone`` missing on this
    machine. ``cfg``: a config already read (the planning brain's own), else the one ``root`` loads."""
    from . import config
    cfg = cfg if cfg is not None else config.load(root)
    eng = cfg.data.get("engine") if isinstance(cfg.data, dict) else None
    if not isinstance(eng, dict):
        return None, ""
    note = ""
    named = eng.get("clone")
    if isinstance(named, str) and named.strip():
        p = Path(named).expanduser()
        p = p if p.is_absolute() else (cfg.file.parent if cfg.file else cfg.root) / p
        if p.is_dir():
            return p.resolve(), ""
        note = f"config.json engine.clone names {p}, missing on this machine"
    repo = eng.get("repo")
    found = _registered(cfg, repo, root) if isinstance(repo, str) and repo else None
    return found, (f"{note}: the registry's checkout of {repo} instead" if note and found else note)


def _registered(cfg, repo: str, root: Path | None) -> Path | None:
    """The first checkout of the registry's projects whose origin is ``repo`` (owner/name, any case)."""
    from . import projects, public
    for p in projects.load(root or cfg.root).values():
        try:
            repos = projects.repos_of(p)
        except projects.RepoError:
            continue
        for r in repos:
            path = Path(r.path)
            if not path.is_dir():
                continue
            try:
                _, slug = public.remote_of(path, cfg, "origin")
            except (OSError, subprocess.SubprocessError):
                continue
            if slug and slug.lower() == repo.lower():
                return path.resolve()
    return None


def default_branch(clone: Path, runner: Runner = bounded) -> str:
    """origin/HEAD as the clone set it, else main (no network)."""
    code, out = _git(clone, ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], runner)
    return out.split("/", 1)[-1] if code == 0 and out.startswith("origin/") else "main"


def _standing(clone: Path, runner: Runner) -> tuple[str, str, str]:
    """(the default branch, '', '') when the clone may move: on that branch, in no operation, no tracked change;
    else ('', state, why)."""
    code, top = _git(clone, ["rev-parse", "--absolute-git-dir"], runner)
    if code != 0 or not top:
        return "", SKIPPED, f"not a git checkout ({_last(top)}): left as it is"
    main = default_branch(clone, runner)
    code, here = _git(clone, ["branch", "--show-current"], runner)
    if code != 0:
        return "", FAILED, f"git branch failed ({_last(here)}): left as it is"
    if here != main:
        return "", SKIPPED, f"on {here or 'a detached HEAD'}, not {main}: left as it is (never switched)"
    busy = [n for n in IN_PROGRESS if (Path(top.splitlines()[-1]) / n).exists()]
    if busy:
        return "", SKIPPED, f"a {IN_PROGRESS[busy[0]]} is in progress: left as it is"
    code, dirty = _git(clone, ["status", "--porcelain", "--untracked-files=no"], runner)
    if code != 0:
        return "", FAILED, f"git status failed ({_last(dirty)}): left as it is"
    if dirty:
        return "", SKIPPED, (f"{len(dirty.splitlines())} tracked file(s) changed: left as it is (never stashed, reset "
                             "or committed)")
    return main, "", ""


def pull(clone: Path, runner: Runner = bounded) -> Result:
    """Fast-forward ``clone`` to origin's default branch when it is on it, clean and in no operation; else say why
    and touch nothing."""
    res = Result(clone)
    main, res.state, res.line = _standing(clone, runner)
    if not main:
        return res
    res.state = SKIPPED
    code, before = _git(clone, ["rev-parse", "--verify", "HEAD"], runner)
    if code != 0:
        res.state, res.line = FAILED, f"git rev-parse HEAD failed ({_last(before)}): left as it is"
        return res
    code, out = _git(clone, ["fetch", "--quiet", "--no-tags", "origin", main], runner)
    if code != 0:
        res.state, res.line = FAILED, f"git fetch origin {main} failed ({_last(out)}): left as it is"
        return res
    code, theirs = _git(clone, ["rev-parse", "--verify", "FETCH_HEAD"], runner)
    if code != 0:
        res.state, res.line = FAILED, f"git could not read what it fetched ({_last(theirs)}): left as it is"
        return res
    if theirs == before:
        res.state, res.line = SAME, f"{main} up to date at {before[:12]}"
        return res
    over = _ignored_overwritten(clone, before, theirs, runner)
    if over:
        res.line = (f"the fast-forward would write over {len(over)} file(s) git ignores here ({', '.join(over[:3])}): "
                    "left as it is; move them aside yourself")
        return res
    code, out = _git(clone, ["merge", "--ff-only", "--quiet", theirs], runner)
    if code != 0:
        res.state, res.line = FAILED, f"git merge --ff-only did not move it ({_last(out)}): left as it is"
        return res
    res.state, res.line = PULLED, f"{main} fast-forwarded {before[:12]} -> {theirs[:12]}"
    return res


def _ignored_overwritten(clone: Path, before: str, theirs: str, runner: Runner) -> list[str]:
    """The files the fast-forward would bring that are here as files git ignores (git writes over them silently)."""
    code, changed = _git(clone, ["diff", "--name-only", "--no-renames", before, theirs], runner)
    if code != 0 or not changed:
        return []
    code, ignored = _git(clone, ["ls-files", "--others", "--ignored", "--exclude-standard"], runner)
    if code != 0 or not ignored:
        return []
    return sorted(set(changed.splitlines()) & set(ignored.splitlines()))


def refresh(root: Path | None = None, runner: Runner = bounded, cfg=None) -> Result:
    """:func:`pull` on the clone :func:`find` names, its note first; Result(None) when there is none."""
    clone, note = find(root, cfg)
    if clone is None:
        return Result(None, SKIPPED, note)
    res = pull(clone, runner)
    if note:
        res.line = f"{note}; {res.line}"
    return res
