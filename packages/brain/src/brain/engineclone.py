"""The owner's engine clone kept current without their gesture (wi-brain-clone-autopull; the owner's answer of
2026-11-18: a fast-forward only).

After an engine PR merges, the owner's clone of the engine (where they cut the tags, and where the audit's code
references are read) is behind its remote's main until someone pulls it. ``brain refresh`` (the merge path's
refresh) and ``brain release apply`` fast-forward it, under one rule:

- **which clone**: config.json ``engine.clone`` (absolute, ``~``, or relative to the config's folder), else the
  registry's checkout whose remote is ``engine.repo`` (brain.projects.repos_of, brain.public.remote_of); none found:
  nothing is said, nothing done;
- **only when** it is on its remote's default branch (``origin/HEAD``, else ``main``), no tracked file has a change
  and no merge, rebase, cherry-pick or revert is in progress: then ``git pull --ff-only origin <main>``, which moves
  nothing when main has commits of its own (it says so);
- **never** a switch, a commit, a reset, a stash or a checkout of a file: any other state is said in one line, and
  the clone is left as it was.

Every git call is bounded (:data:`TIMEOUT_S`) and runs with no terminal prompt. Standard library and the engine's own
modules only; it never raises: a failure is a line.
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
        return f"engine clone {self.clone}: {self.line}" if self.clone else ""


def _git(repo: Path, args: list[str], runner: Runner) -> tuple[int, str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
    try:
        r = runner(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                   errors="replace", timeout=TIMEOUT_S, stdin=subprocess.DEVNULL, env=env)
    except subprocess.TimeoutExpired:
        return 124, f"git {args[0]} timed out after {TIMEOUT_S}s"
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, f"git could not run ({exc.__class__.__name__})"
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


def _last(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return " / ".join(lines[-2:]) or "no output"


def find(root: Path | None = None, cfg=None) -> Path | None:
    """The owner's engine clone: config.json ``engine.clone``, else the registry's checkout whose remote is
    ``engine.repo``; None when neither names one that exists here. ``cfg``: a config already read (the planning
    brain's own, brain release apply), else the one ``root`` loads."""
    from . import config
    cfg = cfg if cfg is not None else config.load(root)
    eng = cfg.data.get("engine") if isinstance(cfg.data, dict) else None
    if not isinstance(eng, dict):
        return None
    named = eng.get("clone")
    if isinstance(named, str) and named.strip():
        p = Path(named).expanduser()
        p = p if p.is_absolute() else (cfg.file.parent if cfg.file else cfg.root) / p
        return p.resolve() if p.is_dir() else None
    repo = eng.get("repo")
    return _registered(cfg, repo, root) if isinstance(repo, str) and repo else None


def _registered(cfg, repo: str, root: Path | None) -> Path | None:
    """The first checkout of the registry's projects whose remote is ``repo`` (owner/name, any case)."""
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


def default_branch(clone: Path, runner: Runner = subprocess.run) -> str:
    """origin/HEAD as the clone set it, else main (no network)."""
    code, out = _git(clone, ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], runner)
    return out.split("/", 1)[-1] if code == 0 and out.startswith("origin/") else "main"


def pull(clone: Path, runner: Runner = subprocess.run) -> Result:
    """Fast-forward ``clone`` to origin's default branch when it is on it, clean and in no operation; else say why
    and touch nothing."""
    res = Result(clone)
    code, top = _git(clone, ["rev-parse", "--show-toplevel", "--absolute-git-dir"], runner)
    if code != 0:
        res.line = f"not a git checkout ({_last(top)}): left as it is"
        return res
    gitdir = Path(top.splitlines()[-1])
    main = default_branch(clone, runner)
    code, here = _git(clone, ["branch", "--show-current"], runner)
    if code != 0 or here != main:
        res.line = f"on {here or 'a detached HEAD'}, not {main}: left as it is (never switched)"
        return res
    busy = [n for n in IN_PROGRESS if (gitdir / n).exists()]
    if busy:
        res.line = f"a {IN_PROGRESS[busy[0]]} is in progress: left as it is"
        return res
    code, dirty = _git(clone, ["status", "--porcelain", "--untracked-files=no"], runner)
    if code != 0:
        res.state, res.line = FAILED, f"git status failed: {_last(dirty)}"
        return res
    if dirty:
        n = len(dirty.splitlines())
        res.line = f"{n} tracked file(s) changed: left as it is (never stashed, reset or committed)"
        return res
    _, before = _git(clone, ["rev-parse", "HEAD"], runner)
    code, out = _git(clone, ["pull", "--ff-only", "--quiet", "origin", main], runner)
    if code != 0:
        res.state = FAILED
        res.line = (f"git pull --ff-only origin {main} did not move it ({_last(out)}): {main} has commits of its "
                    "own, or the remote cannot be read; left as it is")
        return res
    _, after = _git(clone, ["rev-parse", "HEAD"], runner)
    if after == before:
        res.state, res.line = SAME, f"{main} up to date at {after[:12]}"
    else:
        res.state, res.line = PULLED, f"{main} fast-forwarded {before[:12]} -> {after[:12]}"
    return res


def refresh(root: Path | None = None, runner: Runner = subprocess.run, cfg=None) -> Result:
    """:func:`pull` on the clone :func:`find` names; Result(None) when there is none."""
    clone = find(root, cfg)
    return pull(clone, runner) if clone else Result(None)
