"""Memory shared across machines by a reviewed PR (wi-brain-memory-pr; spec-brain-plugin section 2.4, option 2).

Claude Code keeps its automatic memory per machine, ``<projects>/<key>/memory/*.md`` (``<key>``: the project's folder,
encoded). The Brain repo holds the shared copy, ``memory/<key>/*.md`` on ``main``. A sync, token-free:

1. fetches ``main`` and this machine's branch of the day into a private bare repo, ``<BRAIN_HOME>/memory-sync/repo.git``
   (never a working checkout: no branch switch, no index, no stash; git plumbing only);
2. compares each note three ways: the local copy, ``main``'s, and the base (the version this machine last saw equal on
   both sides, in ``state.json``; without one, a local copy found in ``main``'s history at that path is an old one,
   and any other is a conflict: a same-name note never replaces ``main``'s);
3. imports what only ``main`` changed (reviewed notes from another machine), the replaced copy backed up under
   ``memory-sync/backup/<date>/<key>/<stem>.<hash>.md`` (named by its content's hash, never overwritten) and the import
   recorded, so ``brain memory undo`` restores it only while the note still holds what was imported; a note is
   imported only into a project folder that exists on this machine;
4. exports what only this machine changed, from a recognized key only (one on ``main``, one of ``BRAIN_MEMORY_MAP`` or
   the folder of a project the personal brain registers: :func:`recognized_keys`; another stays here, listed): the
   secret scan first (a note with a hit stays on this machine alone, the others go on), then a commit built on
   ``main`` and pushed to ``memory/<machine>/<date>`` with ``--force-with-lease`` on this machine's last push there,
   one PR per machine and day. A branch someone else pushed to is never overwritten: the notes go to
   ``<branch>-2`` (then ``-3``...), and the alert says so. A PR body someone else edited, or a PR with a review, is
   never edited: the update is a comment. An older open PR of the machine is closed as superseded (its branch
   deleted) only when its head is still this machine's last push. Never a push to ``main``: the owner, or the
   close-item flow, merges the PR;
5. keeps both sides of a conflict (both changed since the base): the local copy goes to the PR as
   ``<stem>.conflict-<machine>.md`` beside ``main``'s, ``MEMORY.md`` (an index) included: it is never unioned nor
   regenerated, an index the agent wrote keeps its titles, order and sentences. Flagged in the PR title and body and in
   the alert. Once the PR that carried it is closed and ``main`` moved past the flagged version (the reviewer merged
   both), ``main``'s note is imported.

The SessionEnd hook (``hook_main(["session-end"])``) only decides and spawns: when a note of a key the last run
recognized changed since then (mtime and size; a key it left out, a read-only project's included, starts no run) or
the last pull is older than ``BRAIN_MEMORY_PULL_HOURS``, it starts ``run`` detached and returns, in
a few milliseconds. What needs the owner (a refused export, a conflict, a failure, a job that died) goes to
``alert.txt``, which the SessionStart hook prints in bash builtins; a clean run removes it.

Environment: ``BRAIN_MEMORY_SYNC`` (1: both ways, the default; export: no import; 0: off), ``BRAIN_MEMORY_REMOTE``
(default: the origin of the clone the brain command is installed from), ``BRAIN_MEMORY_REPO`` (the GitHub
``owner/name`` for gh, when the remote's URL does not show it), ``BRAIN_MACHINE`` (default: the host name),
``BRAIN_MEMORY_MAP`` (``local-key=repo-key;...`` for a machine with another layout; ``local-key=`` leaves a folder out),
``BRAIN_MEMORY_PULL_HOURS`` (default 12; 0: pull only when a note changed), ``BRAIN_MEMORY_TIMEOUT`` (seconds, default
300), ``BRAIN_GH`` (the gh program, or a JSON list of argv).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import zlib
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from . import config, paths, secretscan, stateio
from .memorykeys import CONFLICT_RX, local_dir, local_notes, recognized_keys, snapshot, watched

DEFAULT_TIMEOUT = 300.0
DEFAULT_PULL_HOURS = 12.0
INDEX = "MEMORY.md"
GITHUB_RX = re.compile(r"github\.com[:/]+([^/\s]+/[^/\s]+?)(?:\.git)?/?$")


class SyncError(Exception):
    """A step failed; its message goes to the alert."""


def sync_dir() -> Path:
    return paths.brain_home() / "memory-sync"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def mode() -> str:
    """BRAIN_MEMORY_SYNC: 'both' (the default), 'export' (no import) or 'off'."""
    v = os.environ.get("BRAIN_MEMORY_SYNC", "1").strip().lower()
    return {"0": "off", "off": "off", "false": "off", "export": "export"}.get(v, "both")


def machine() -> str:
    """This machine's name: brain.machine.name, the one identity ($BRAIN_MACHINE, else the host name)."""
    from .machine import name
    return name()


STATE_V = 1  # memory-sync/state.json's v (brain.stateio)


def _state(write: bool = False) -> stateio.State:
    return stateio.load(sync_dir() / "state.json", known=STATE_V, aside=write)


def load_state(write: bool = False) -> dict:
    """The sync's record (the 3-way base, the last snapshot, the pushes and PRs), through brain.stateio. ``write``:
    the caller will save it, so a state this engine must not write (a newer brain's) is refused here, before any
    work (SyncError), and an unreadable one is set aside; without it nothing is moved."""
    st = _state(write)
    if write and not st.writable:
        raise SyncError(st.refusal())
    return st.data if st.status in ("ok", "newer", "aside") else {}


def _write(path: Path, data: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".brain-tmp")
    if isinstance(data, str):
        data = data.encode("utf-8")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def save_state(state: dict) -> None:
    """The record back to state.json: a backup, then an atomic write (brain.stateio); SyncError when a newer brain
    wrote it meanwhile."""
    try:
        stateio.save(_state(write=True), state)
    except stateio.StateError as exc:
        raise SyncError(str(exc)) from None


def needs_run(state: dict, now: float | None = None) -> bool:
    """A watched note changed since the last run (mtime or size), or the last pull is older than the pull interval."""
    if snapshot(watched(local_notes(), state)) != state.get("snapshot"):
        return True
    hours = _float_env("BRAIN_MEMORY_PULL_HOURS", DEFAULT_PULL_HOURS)
    if hours <= 0 or mode() == "export":
        return False
    return (now or time.time()) - float(state.get("fetched_epoch") or 0) > hours * 3600


def normalize(data: bytes) -> bytes:
    """Notes are text: LF line ends, so a CRLF copy and the repo's blob agree."""
    return data.replace(b"\r\n", b"\n")


def blob_id(data: bytes) -> str:
    """git's object id of a blob holding ``data``."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _answered(flagged: dict, local: str, main: str, conflict_open, conflict_merged) -> bool:
    """A flagged conflict the owner answered: its PR is no longer open and main moved past the flagged version, or
    the PR was merged keeping main's note."""
    branch = flagged.get("branch")
    return (flagged.get("local") == local and not conflict_open(branch)
            and (flagged.get("main") != main or conflict_merged(branch)))


def decide(local: str | None, main: str | None, entry: dict, history: set[str],
           conflict_open=lambda branch: True, conflict_merged=lambda branch: False) -> tuple[str, str | None]:
    """(action, base) for one note from blob ids: the local copy, main's, the state entry (base, sent, conflict,
    declined) and the blobs main ever had at that path. ``conflict_open(branch)``: whether the PR that carried a
    flagged conflict is still open; ``conflict_merged(branch)``: whether it was merged. Actions: same, import, export,
    conflict, resolved (a flagged conflict main moved past, or whose PR was merged keeping main's: import), kept
    (deleted on main and kept here, or main's version declined by ``brain memory undo``: not exported, not imported)."""
    base = entry.get("base")
    if local == main:
        return "same", main
    if main is not None and main == entry.get("declined"):   # the owner put this import back: it stays undone
        return "kept", base
    if local is None:
        return "import", base
    if main is None:
        return ("kept", base) if base is not None and local == base else ("export", base)
    if main == entry.get("sent"):   # what this machine exported was merged: main's is the base
        base = main
    if _answered(entry.get("conflict") or {}, local, main, conflict_open, conflict_merged):
        return "resolved", base
    if base is None:  # first sync of this note here: a local copy main once had is an old one; another is a conflict
        if local not in history:   # a same-name note written apart: never a replacement of main's
            return "conflict", None
        base = local
    if local == base:
        return "import", base
    if main == base:
        return "export", base
    return "conflict", base


# --- processes ---

def _no_window() -> int:
    """No console window for git and gh started from the detached job (Windows)."""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


class Runner:
    """Runs git and gh with one deadline for the whole sync, never a prompt."""

    def __init__(self, deadline: float):
        self.deadline = deadline
        self.env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
        self.env.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never", GH_PROMPT_DISABLED="1")

    def __call__(self, argv: list[str], data: bytes | None = None, env: dict | None = None,
                 check: bool = True) -> subprocess.CompletedProcess:
        left = self.deadline - time.monotonic()
        what = " ".join(argv[:4])
        if left <= 0:
            raise SyncError(f"timed out before {what}")
        try:
            p = subprocess.run(argv, input=data, stdin=None if data is not None else subprocess.DEVNULL,
                               capture_output=True, timeout=min(left, 120), env={**self.env, **(env or {})},
                               creationflags=_no_window())
        except subprocess.TimeoutExpired:
            raise SyncError(f"timed out: {what}") from None
        except OSError as exc:
            raise SyncError(f"{argv[0]}: {exc.strerror or exc}") from None
        if check and p.returncode:
            err = p.stderr.decode("utf-8", "replace").strip().splitlines()
            msg = secretscan.strip_url_credentials(err[-1] if err else f"exit code {p.returncode}")
            raise SyncError(f"{what}: {secretscan.clean_text(msg)[0]}")
        return p


def gh_argv() -> list[str]:
    raw = os.environ.get("BRAIN_GH", "gh").strip()
    return json.loads(raw) if raw.startswith("[") else [raw]


def remote_url() -> str | None:
    """BRAIN_MEMORY_REMOTE, else the origin of the personal brain (``$BRAIN_PERSONAL``, <BRAIN_HOME>/personal.json),
    else of the clone the brain command is installed from editable, or that holds this package."""
    env = os.environ.get("BRAIN_MEMORY_REMOTE")
    if env:
        return env
    for repo in (paths.personal_root(), paths.installed_checkout(), paths.package_repo()):
        if not repo:
            continue
        try:
            url = subprocess.run(["git", "-C", str(repo), "config", "--get", "remote.origin.url"], capture_output=True,
                                 text=True, timeout=10, stdin=subprocess.DEVNULL,
                                 creationflags=_no_window()).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            continue
        if url:
            return url
    return None


# --- the sync ---

@dataclass
class Report:
    machine: str
    day: str
    branch: str
    actions: dict[str, str] = field(default_factory=dict)  # note -> action
    imported: list[str] = field(default_factory=list)
    exported: list[str] = field(default_factory=list)  # repo paths written to the branch
    conflicts: list[str] = field(default_factory=list)
    hits: list[str] = field(default_factory=list)  # 'key/name.md:line pattern' (never the line itself)
    left: list[str] = field(default_factory=list)  # branches someone else pushed to: left as they are
    kept_open: list[str] = field(default_factory=list)  # older PRs not closed: their head is not this machine's push
    commented: str = ""  # the PR whose body was not edited: the update went to a comment
    pushed: bool = False
    pr: str = ""
    error: str = ""
    dry_run: bool = False

    def lines(self) -> list[str]:
        """One line per note that is not in sync, then the outcome."""
        by: dict[str, list[str]] = {}
        for note, action in sorted(self.actions.items()):
            by.setdefault(action, []).append(note)
        out = [f"{action:<9} {note}" for action in ("export", "conflict", "import", "resolved", "kept", "secret")
               for note in by.get(action, [])]
        stray = sorted({n.split("/", 1)[0] for n in by.get("unmapped", [])})
        said = [   # (a line, when it is said)
            (f"unmapped  {len(by.get('unmapped', []))} note(s) of keys no project claims, kept here: "
             f"{', '.join(stray)} (register the project, or map the key in BRAIN_MEMORY_MAP)", stray),
            (f"same      {len(by.get('same', []))} note(s)", by.get("same")),
            ("held      on this machine, secret patterns in " + ", ".join(self.hits), self.hits),
            *[(f"left      {b}: someone else pushed to it; this machine's notes go to {self.branch}", True)
              for b in self.left],
            *[(f"open      {b}: its head is not this machine's last push, so it is not closed as superseded", True)
              for b in self.kept_open],
            (f"comment   {self.commented}: its body was edited or reviewed, the update is a comment", self.commented),
            (f"failed    {self.error}", self.error),
        ]
        out += [line for line, when in said if when]
        if self.dry_run:
            out.append("(status only: nothing written)")
        elif self.pushed or self.pr:
            out.append(f"branch    {self.branch}" + (f": {self.pr}" if self.pr else ""))
        return out


class Sync:
    def __init__(self, remote: str, deadline: float, day: str | None = None, gh=None):
        self.remote = remote
        self.run = Runner(deadline)
        self.machine = machine()
        self.day = day or date.today().isoformat()
        self.day_branch = f"memory/{self.machine}/{self.day}"
        self.branch = self.day_branch   # the branch this run pushes to (pick_branch: -2, -3... past one someone touched)
        self.heads: dict[str, str] = {}   # this machine's branches on the remote: ref -> commit
        self.repo = sync_dir() / "repo.git"
        m = GITHUB_RX.search(remote)
        self.slug = os.environ.get("BRAIN_MEMORY_REPO") or (m.group(1) if m else "")
        self._gh = gh
        self._prs: dict | None = None

    # git and gh

    def git(self, *args: str, data: bytes | None = None, env: dict | None = None, check: bool = True) -> str:
        p = self.run(["git", "--git-dir", str(self.repo), *args], data=data, env=env, check=check)
        return p.stdout.decode("utf-8", "replace").strip() if p.returncode == 0 else ""

    def gh(self, *args: str, data: str | None = None) -> str:
        if self._gh:
            return self._gh(list(args), data)
        if not self.slug:
            raise SyncError(f"no PR: the remote is not on GitHub ({secretscan.strip_url_credentials(self.remote)}); "
                            "set BRAIN_MEMORY_REPO=owner/name")
        p = self.run([*gh_argv(), *args, "--repo", self.slug], data=data.encode("utf-8") if data is not None else None)
        return p.stdout.decode("utf-8", "replace").strip()

    def open_prs(self) -> dict[str, dict]:
        """This machine's open memory PRs, by branch (with their head, body and reviews)."""
        if self._prs is None:
            out = self.gh("pr", "list", "--state", "open", "--json", "number,url,headRefName,headRefOid,body,reviews",
                          "--limit", "100")
            prefix = f"memory/{self.machine}/"
            self._prs = {p["headRefName"]: p for p in json.loads(out or "[]")
                         if str(p.get("headRefName", "")).startswith(prefix)}
        return self._prs

    def conflict_open(self, branch: str | None) -> bool:
        try:
            return bool(branch) and branch in self.open_prs()
        except (SyncError, ValueError):
            return True  # unknown: keep the conflict flagged

    def conflict_merged(self, branch: str | None) -> bool:
        """Whether the PR of ``branch`` was merged (a conflict the owner answered by keeping main's note); unknown:
        no, the conflict stays flagged."""
        if not branch:
            return False
        try:
            return bool(json.loads(self.gh("pr", "list", "--state", "merged", "--head", branch, "--json", "number",
                                           "--limit", "1") or "[]"))
        except (SyncError, ValueError):
            return False

    # steps

    def refs(self) -> dict[str, tuple[str, str]]:
        """The private repo's branches: ref -> (commit, tree)."""
        out = {}
        for line in self.git("for-each-ref", "--format=%(refname) %(objectname) %(tree)", "refs/heads/").splitlines():
            ref, commit, tree = line.split()
            out[ref] = (commit, tree)
        return out

    def touched(self, branch: str, state: dict) -> bool:
        """Whether someone else pushed to ``branch``: it is on the remote and its head is not this machine's last push
        there (state['pushed'])."""
        head = self.heads.get(f"refs/heads/{branch}")
        return head is not None and head != ((state.get("pushed") or {}).get(branch) or {}).get("commit")

    def pick_branch(self, state: dict, skip: tuple[str, ...] = ()) -> list[str]:
        """Set ``self.branch`` to the day's branch, or ``-2``, ``-3``... past each one someone else pushed to (or in
        ``skip``: a lease that failed); the branches passed over."""
        left = []
        for n in range(1, 10):
            branch = self.day_branch if n == 1 else f"{self.day_branch}-{n}"
            if branch in skip or self.touched(branch, state):
                left.append(branch)
                continue
            self.branch = branch
            return left
        raise SyncError(f"no branch left for the day: {self.day_branch} to -9 were pushed to by someone else")

    def fetch(self, offline: bool = False) -> tuple[str, str | None]:
        """(main's commit, the branch's commit or None), fetched into the private bare repo (``offline``: as last
        fetched); their trees in ``self.trees``, this machine's branches' heads in ``self.heads``."""
        main_ref, day_ref = "refs/heads/main", f"refs/heads/{self.day_branch}"

        def ours(ref: str) -> bool:   # the day's branch and its -2, -3...
            return ref == day_ref or re.fullmatch(re.escape(day_ref) + r"-[2-9]", ref) is not None

        if not (self.repo / "HEAD").is_file():
            if offline:
                raise SyncError("nothing fetched yet: run without --offline")
            self.run(["git", "init", "--bare", "-q", "--initial-branch=main", str(self.repo)])
        mark = self.repo / "brain-remote"  # the URL last set, read without starting git
        if not offline and (not mark.is_file() or mark.read_text(encoding="utf-8") != self.remote):
            self.git("config", "remote.origin.url", self.remote)
            mark.write_text(self.remote, encoding="utf-8")
        refs = self.refs()
        if offline:
            heads = {r: refs[r][0] for r in refs if r == main_ref or ours(r)}
        else:
            heads = {}
            for line in self.git("ls-remote", "origin", main_ref, day_ref, f"{day_ref}-*").splitlines():
                sha, _, ref = line.partition("\t")
                if ref == main_ref or ours(ref):
                    heads[ref] = sha
            want = [f"+{r}:{r}" for r, sha in heads.items() if refs.get(r, ("",))[0] != sha]
            if want:
                self.git("fetch", "-q", "--no-tags", "origin", *want)
            for r in refs:
                if ours(r) and r not in heads:   # deleted on the remote (merged, closed)
                    self.git("update-ref", "-d", r)
            if want:
                refs = self.refs()
        if main_ref not in heads:
            raise SyncError("nothing fetched yet: run without --offline" if offline else "the remote has no main")
        self.trees = {r: refs[r][1] for r in heads}
        self.heads = {r: sha for r, sha in heads.items() if r != main_ref}
        return heads[main_ref], heads.get(day_ref)

    def main_notes(self, main: str) -> dict[str, str]:
        """'key/name.md' -> blob id, for main's memory/<key>/<name>.md (conflict copies left out)."""
        out = {}
        raw = self.git("-c", "core.quotePath=false", "ls-tree", "-r", main, "--", "memory/")
        for line in raw.splitlines():
            meta, _, path = line.partition("\t")
            parts = path.split("/")
            if len(parts) == 3 and parts[2].endswith(".md") and not CONFLICT_RX.search(parts[2]):
                out[f"{parts[1]}/{parts[2]}"] = meta.split()[2]
        return out

    def history(self, main: str) -> dict[str, set[str]]:
        """Every blob main ever had at each memory/<key>/<name>.md."""
        out: dict[str, set[str]] = {}
        raw = self.git("-c", "core.quotePath=false", "log", "--format=", "--raw", "--no-abbrev", "--no-renames",
                       main, "--", "memory/")
        for line in raw.splitlines():
            if not line.startswith(":"):
                continue
            meta, _, path = line.partition("\t")
            f = meta.split()
            if path.startswith("memory/") and len(f) >= 4:
                out.setdefault(path[len("memory/"):], set()).update(b for b in f[2:4] if set(b) != {"0"})
        return out

    def blob(self, sha: str) -> bytes:
        return self.run(["git", "--git-dir", str(self.repo), "cat-file", "blob", sha]).stdout

    def write_blob(self, data: bytes) -> str:
        """Store ``data`` as a loose object (git's own format, written without starting git); its id."""
        sha = blob_id(data)
        obj = self.repo / "objects" / sha[:2] / sha[2:]
        if not obj.exists():
            _write(obj, zlib.compress(b"blob %d\0" % len(data) + data))
        return sha

    def build(self, main: str, files: dict[str, bytes]) -> str:
        """The tree of ``main`` with ``files`` (repo path -> content) written, through a private index file."""
        index = sync_dir() / "index.tmp"
        env = {"GIT_INDEX_FILE": str(index)}
        try:
            self.git("read-tree", main, env=env)
            info = "".join(f"100644 {self.write_blob(data)}\t{path}\n" for path, data in sorted(files.items()))
            self.git("update-index", "--index-info", data=info.encode("utf-8"), env=env)
            return self.git("write-tree", env=env)
        finally:
            index.unlink(missing_ok=True)

    def commit(self, tree: str, main: str, message: str) -> str:
        """A commit of ``tree`` on ``main``, by the machine's git identity (a placeholder one when it has none)."""
        argv = ["git", "--git-dir", str(self.repo), "commit-tree", tree, "-p", main]
        p = self.run(argv, data=message.encode("utf-8"), check=False)
        if p.returncode:
            who = {"NAME": "brain memory sync", "EMAIL": f"memory-sync@{self.machine}.invalid"}
            p = self.run(argv, data=message.encode("utf-8"),
                         env={f"GIT_{role}_{k}": v for role in ("AUTHOR", "COMMITTER") for k, v in who.items()})
        return p.stdout.decode("utf-8").strip()

    def push(self, commit: str, state: dict) -> bool:
        """Push ``commit`` to ``self.branch`` with a lease on this machine's last push there (none: the branch must
        not exist). False when the lease fails: someone pushed meanwhile, nothing was overwritten."""
        expect = ((state.get("pushed") or {}).get(self.branch) or {}).get("commit", "") \
            if f"refs/heads/{self.branch}" in self.heads else ""
        ref = f"refs/heads/{self.branch}"
        p = self.run(["git", "--git-dir", str(self.repo), "push", "-q", f"--force-with-lease={ref}:{expect}", "origin",
                      f"{commit}:{ref}"], check=False)
        if p.returncode == 0:
            return True
        err = p.stderr.decode("utf-8", "replace")
        if "stale info" in err:   # the lease lost; a hook's or a protected branch's refusal is a failure, said
            return False
        last = (err.strip().splitlines() or [f"exit code {p.returncode}"])[-1]
        raise SyncError(f"git push: {secretscan.clean_text(secretscan.strip_url_credentials(last))[0]}")

    def own_head(self, branch: str, pr: dict, state: dict) -> bool:
        """The PR's head is this machine's last push to ``branch`` and nobody reviewed it."""
        last = ((state.get("pushed") or {}).get(branch) or {}).get("commit")
        return bool(last) and pr.get("headRefOid") == last and not pr.get("reviews")

    def open_pr(self, title: str, body: str, state: dict, report: Report | None = None) -> str:
        """Open or update the PR of ``self.branch``, close this machine's older ones (the branch holds their changes)
        whose head is still its last push; its URL. A body someone else edited (not the one this machine wrote last)
        or a PR with a review is never edited: the update goes to a comment."""
        prs = self.open_prs()
        bodies = state.setdefault("bodies", {})
        digest = _body_digest(body)
        if self.branch in prs:
            pr = prs[self.branch]
            url = pr["url"]
            current = _body_digest(str(pr.get("body") or ""))
            if current == digest:
                pass
            elif bodies.get(self.branch) == current and not pr.get("reviews"):
                self.gh("pr", "edit", str(pr["number"]), "--title", title, "--body-file", "-", data=body)
                bodies[self.branch] = digest
            else:
                self.gh("pr", "comment", str(pr["number"]), "--body-file", "-",
                        data=f"The memory sync of `{self.machine}` pushed again; the body was left as it is.\n\n"
                             + body)
                if report is not None:
                    report.commented = url
        else:
            out = self.gh("pr", "create", "--base", "main", "--head", self.branch, "--title", title,
                          "--body-file", "-", data=body)
            url = (out.splitlines() or [""])[-1].strip()
            bodies[self.branch] = digest
        state.setdefault("prs", {})[self.branch] = url
        for branch, pr in sorted(prs.items()):
            if branch == self.branch:
                continue
            if self.own_head(branch, pr, state):
                self.gh("pr", "close", str(pr["number"]), "--delete-branch",
                        "--comment", f"Superseded by {url}: the branch {self.branch} holds these notes.")
            elif report is not None:
                report.kept_open.append(branch)
        return url


def _body_digest(body: str) -> str:
    """A PR body's digest, its line ends and trailing white space aside (the code host may trim them)."""
    return blob_id(body.replace("\r\n", "\n").rstrip().encode("utf-8"))


def _title(machine_: str, day: str, conflicts: int) -> str:
    return f"Memory from {machine_}, {day}" + (f" ({conflicts} conflict(s) kept on both sides)" if conflicts else "")


def _plugin() -> str:
    """The core plugin's name (config.json adapters.claude): the hook that syncs the notes."""
    return config.claude(config.load())["plugin"]


def pr_body(report: Report, changes: list[tuple[str, str]], conflicts: list[tuple[str, str]]) -> str:
    out = [f"Memory notes exported from `{report.machine}` by the {_plugin()} SessionEnd hook (`brain memory sync`), "
           "for review. Never pushed to `main`; the secret scan passed on every file of this PR.", ""]
    if changes:
        out += [f"**Changed ({len(changes)})**", ""] + [f"- `{p}` ({what})" for p, what in changes] + [""]
    if conflicts:
        out += [f"**Conflicts, both sides kept ({len(conflicts)})**: `main` and `{report.machine}` both changed these "
                "notes since they last agreed. Merge each pair into the note on this branch, delete the conflict "
                "copy, then merge the PR.", ""]
        out += [f"- `memory/{note}`: {how}" for note, how in conflicts] + [""]
    out.append("After the merge, the other machines import these notes at their next sync (a session end).")
    return "\n".join(out) + "\n"


def export_held() -> str:
    """Why the export (the machine's branch, a shared machine-level write) is held, '' when it is not: an engine below
    config.json engine.min, or this machine's identity in doubt (brain.machine). The import goes on."""
    from . import config, machine, skew

    return skew.below_min(None) or machine.in_doubt(config.load().data)


def sync(*, dry_run: bool = False, offline: bool = False, do_import: bool = True, do_export: bool = True,
         day: str | None = None, gh=None, timeout: float | None = None, state: dict | None = None,
         checkpoint=None) -> Report:
    """One sync, both ways (see the module's docstring). ``state`` is updated in place (saved by the caller;
    ``checkpoint(state)`` saves it as soon as a push landed)."""
    held = "" if dry_run or not do_export else export_held()
    do_export = do_export and not held
    state = load_state() if state is None else state
    deadline = time.monotonic() + (timeout or _float_env("BRAIN_MEMORY_TIMEOUT", DEFAULT_TIMEOUT))
    remote = remote_url()
    if not remote:
        raise SyncError("no remote: set BRAIN_MEMORY_REMOTE, or install the brain command from a clone "
                        "(install.ps1 -Apply)")
    s = Sync(remote, deadline, day, gh)
    main, _ = s.fetch(offline)
    left = s.pick_branch(state)
    report = Report(s.machine, s.day, s.branch, dry_run=dry_run, left=left)
    if held:
        report.actions["(export)"] = f"held: {held}"
    if not dry_run:
        state["fetched_epoch"], state["fetched_at"] = time.time(), _now()
        state["remote"] = secretscan.strip_url_credentials(remote)
    on_main = s.main_notes(main)
    history = s.history(main)
    notes = local_notes()
    main_keys = {k.split("/", 1)[0] for k in on_main}
    known = recognized_keys({k.split("/", 1)[0] for k in notes} | main_keys, main_keys)
    snap = snapshot({k: f for k, f in notes.items() if k.split("/", 1)[0] in known})
    local = {k: normalize(f.read_bytes()) for k, f in notes.items()}
    entries = state.setdefault("notes", {}) if not dry_run else dict(state.get("notes") or {})
    keys = sorted(set(local) | {k for k in on_main if local_dir(k.split("/")[0]) is not None})

    def elsewhere(branch: str | None) -> bool:
        """A flagged conflict's PR this run does not supersede: a branch someone else pushed to, or reviewed."""
        if not branch or branch == s.branch:
            return False
        try:
            pr = s.open_prs().get(branch)
        except (SyncError, ValueError):
            return False
        return pr is not None and (branch in left or not s.own_head(branch, pr, state))

    exporting = do_export and not dry_run
    files: dict[str, bytes] = {}
    changes: list[tuple[str, str]] = []
    conflicts: list[tuple[str, str]] = []
    for k in keys:
        if k.split("/", 1)[0] not in known:   # a key no project claims: kept here, never exported
            report.actions[k] = "unmapped"
            continue
        lb = blob_id(local[k]) if k in local else None
        mb = on_main.get(k)
        entry = dict(entries.get(k) or {})
        action, base = decide(lb, mb, entry, history.get(k, set()), s.conflict_open, s.conflict_merged)
        report.actions[k] = action
        if action in ("export", "conflict"):   # the secret scan, note by note: a hit keeps that note here alone
            hits = secretscan.scan_lines(local[k].decode("utf-8", "replace"))
            if hits:
                report.actions[k] = "secret"
                report.hits += [f"{k}:{line} {pattern}" for line, pattern in hits]
                continue
        if action in ("same", "import", "resolved"):
            if action != "same":
                if not do_import:
                    continue
                if not dry_run:
                    _import(s, k, mb, notes, state, snap)
                report.imported.append(k)
            entries[k] = {"base": mb}
        elif action == "export":
            files[f"memory/{k}"] = local[k]
            changes.append((f"memory/{k}", "new" if mb is None else "edited"))
            if exporting:   # what was sent: once main holds it, it is the base (decide)
                entries[k] = {"base": base, "sent": lb} if base else {"sent": lb}
        elif action == "conflict":
            flagged = entry.get("conflict") or {}
            if flagged.get("local") == lb and flagged.get("main") == mb and elsewhere(flagged.get("branch")):
                report.conflicts.append(k)   # already on a PR someone else is working on: not carried again
                continue
            key, name = k.split("/", 1)
            side = f"memory/{key}/{name[:-3]}.conflict-{s.machine}.md"
            files[side] = local[k]
            conflicts.append((k, f"`{s.machine}`'s version is `{side}`"))
            report.conflicts.append(k)
            if exporting:   # flagged only once a branch carries it: a held export flags nothing
                entries[k] = {"base": base, "conflict": {"local": lb, "main": mb, "branch": s.branch}}
    report.exported = sorted(files)

    if files and exporting:
        # the branch already holds these files on this main (the last push, from the state): no git at all
        digest = blob_id(json.dumps(sorted((p, blob_id(d)) for p, d in files.items())).encode("utf-8"))
        tree = ""
        lease_lost: tuple[str, ...] = ()
        while True:
            branch_head = s.heads.get(f"refs/heads/{s.branch}")
            pushed = (state.get("pushed") or {}).get(s.branch) or {}
            same = branch_head is not None and pushed == {"commit": branch_head, "main": main, "files": digest}
            if same:
                break
            tree = tree or s.build(main, files)
            same = branch_head is not None and s.trees.get(f"refs/heads/{s.branch}") == tree
            if same:
                break
            message = (_title(s.machine, s.day, len(conflicts)) + "\n\n"
                       + "\n".join(f"{p} ({what})" for p, what in changes + [(f"memory/{n}", "conflict")
                                                                          for n, _ in conflicts]) + "\n")
            commit = s.commit(tree, main, message)
            if s.push(commit, state):
                s.git("update-ref", f"refs/heads/{s.branch}", commit)
                state.setdefault("pushed", {})[s.branch] = {"commit": commit, "main": main, "files": digest}
                report.pushed = True
                if checkpoint:   # the push is recorded even if the PR step fails: never taken for someone else's
                    checkpoint(state)
                break
            lease_lost += (s.branch,)   # someone pushed between the fetch and the push: nothing overwritten
            left = report.left = s.pick_branch(state, skip=lease_lost)
        report.branch = s.branch
        for k in report.conflicts:   # the branch that carries them, once the lease settled it
            if (entries.get(k) or {}).get("conflict", {}).get("branch") in lease_lost:
                entries[k]["conflict"]["branch"] = s.branch
        if not same or s.branch not in (state.get("prs") or {}):  # or a PR the last run failed to open
            report.pr = s.open_pr(_title(s.machine, s.day, len(conflicts)), pr_body(report, changes, conflicts),
                                  state, report)
        else:
            report.pr = state["prs"][s.branch]
    if not dry_run:
        state["unmapped"] = sorted({k.split("/", 1)[0] for k in notes} - known)
        state["snapshot"] = snap
        cutoff = _days_ago(14)
        for k in ("prs", "pushed", "bodies"):  # two weeks of branches
            state[k] = {b: v for b, v in (state.get(k) or {}).items() if _branch_day(b) >= cutoff}
        state["imports"] = {n: v for n, v in (state.get("imports") or {}).items()
                            if str(v.get("at", ""))[:10] >= cutoff}
    return report


def _branch_day(branch: str) -> str:
    """The date of a memory branch, ``memory/<machine>/<date>`` or ``...-<n>``; '' when it has none."""
    m = re.search(r"(\d{4}-\d{2}-\d{2})(?:-\d)?$", branch)
    return m.group(1) if m else ""


def backup(key: str, name: str, data: bytes) -> Path:
    """Keep ``data`` (a note about to be replaced) under memory-sync/backup/<date>/<key>/<stem>.<hash>.md, named by its
    content's hash: never overwritten (the same content is the same file)."""
    stem, dot, ext = name.rpartition(".")
    stem, ext = (stem, f".{ext}") if dot else (name, "")
    f = sync_dir() / "backup" / date.today().isoformat() / key / f"{stem}.{blob_id(data)[:12]}{ext}"
    if not f.exists():
        _write(f, data)
    return f


def _import(s: Sync, k: str, mb: str, notes: dict[str, Path], state: dict, snap: dict) -> None:
    """Write main's version of the note ``k`` here, the replaced copy backed up (:func:`backup`) and the import
    recorded in ``state['imports']`` for ``brain memory undo``."""
    key, name = k.split("/", 1)
    target = notes.get(k) or local_dir(key) / name
    rec = {"at": _now(), "after": mb, "before": None, "backup": None}
    if target.exists():
        old = target.read_bytes()
        rec.update(before=blob_id(normalize(old)), backup=backup(key, name, old).relative_to(sync_dir()).as_posix())
    _write(target, s.blob(mb))
    snap.update(snapshot({k: target}))
    state.setdefault("imports", {})[k] = rec


def _days_ago(n: int) -> str:
    return date.fromordinal(date.today().toordinal() - n).isoformat()


# --- alert, job, hook ---

def alert_lines(report: Report | None, error: str = "") -> list[str]:
    """What the owner has to act on, one line each; none when the run was clean."""
    head = f"Memory sync ({_plugin()}, {machine()}, {_now()[:16].replace('T', ' ')} UTC):"
    out = []
    if error:
        out.append(f"{head} failed: {error}. `brain memory sync` runs it again in the foreground.")
    if report and report.hits:
        out.append(f"{head} note(s) kept on this machine, secret patterns in {', '.join(report.hits[:5])}. Remove the "
                   "secret from the local note (~/.claude/projects/<key>/memory/), then `brain memory sync`; the other "
                   "notes went on.")
    if report and report.left and report.pushed:
        out.append(f"{head} {', '.join(report.left)}: someone else pushed to it, so it was left as it is; this "
                   f"machine's notes went to {report.branch}. Merge or close the first one's PR.")
    if report and report.conflicts:
        out.append(f"{head} {len(report.conflicts)} conflicting note(s) kept on both sides in "
                   f"{report.pr or report.branch}: {', '.join(report.conflicts[:5])}. Merge each pair on the PR "
                   "branch, then merge the PR.")
    return out


def write_alert(lines: list[str]) -> None:
    f = sync_dir() / "alert.txt"
    if lines:
        _write(f, "\n".join(lines) + "\n")
    else:
        f.unlink(missing_ok=True)


def _log_error(event: str, exc: BaseException) -> None:
    from .capture import _log_error as log  # here: capture's imports are not needed on the fast path

    log(event, exc)


def _lock_path() -> Path:
    return sync_dir() / "run.json"


def _acquire(wait: float, stale: float, died: list[str] | None = None) -> bool:
    """Take the run lock (run.json, created exclusively), waiting up to ``wait`` seconds; a lock older than ``stale``
    belongs to a job that died: alerted at once (and its line added to ``died``), then broken."""
    lock = _lock_path()
    lock.parent.mkdir(parents=True, exist_ok=True)
    end = time.monotonic() + wait
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                age = time.time() - lock.stat().st_mtime
                started = json.loads(lock.read_text(encoding="utf-8")).get("at", "?")
            except (OSError, ValueError):
                age, started = 0.0, "?"
            if age > stale:
                line = (f"Memory sync ({_plugin()}, {machine()}): the job started at {started} never finished "
                        "(killed?); a new one runs. `brain memory sync` runs it in the foreground.")
                write_alert([line])
                if died is not None:
                    died.append(line)
                lock.unlink(missing_ok=True)
                continue
            if time.monotonic() >= end:
                return False
            time.sleep(1.0)
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"pid": os.getpid(), "at": _now()}, fh)
        return True


def job_main(force: bool = False, out=None, do_import: bool | None = None, **kw) -> int:
    """The sync under the run lock, its outcome in last.json and the alert. ``force``: even when nothing changed.
    Exit code 1 when the export was refused or the sync failed."""
    timeout = _float_env("BRAIN_MEMORY_TIMEOUT", DEFAULT_TIMEOUT)
    died: list[str] = []  # a dead job's line stays in this run's alert
    if not _acquire(wait=timeout, stale=2 * timeout, died=died):
        if out:
            print("brain: a memory sync is already running", file=out)
        return 1
    started = time.monotonic()
    try:
        (sync_dir() / "queued.json").unlink(missing_ok=True)
        try:   # a newer brain's record is refused before any fetch: a sync it cannot record would run again
            state, error = load_state(write=True), ""
        except SyncError as exc:
            state, error = load_state(), str(exc)
        if not force and not error and not needs_run(state):
            return 0
        report = None
        try:
            if not error:
                report = sync(do_import=mode() == "both" if do_import is None else do_import, state=state,
                              timeout=timeout, checkpoint=save_state, **kw)
        except SyncError as exc:
            error = str(exc)
        except Exception as exc:  # noqa: BLE001 - the job reports, it never raises
            error = f"{type(exc).__name__}: {exc}"
            _log_error("memory-sync", exc)
        if report or error:
            if not error:
                try:
                    save_state(state)
                except SyncError as exc:
                    error = str(exc)
            last = {"at": _now(), "took": round(time.monotonic() - started, 2), "machine": machine(),
                    "result": "failed" if error else "held" if report.hits else "ok", "error": error}
            if report:
                last.update(branch=report.branch, pr=report.pr, pushed=report.pushed, imported=report.imported,
                            exported=report.exported, conflicts=report.conflicts, hits=report.hits, left=report.left)
            _write(sync_dir() / "last.json", json.dumps(last, indent=1, ensure_ascii=False))
            write_alert(died + alert_lines(report, error))
        if out:
            for line in (report.lines() if report else []) + ([f"failed    {error}"] if error else []):
                print(line, file=out)
        return 1 if error or (report and report.hits) else 0
    finally:
        _lock_path().unlink(missing_ok=True)


def _spawn(argv: list[str]) -> None:
    """Start ``argv`` detached: it outlives the hook and Claude Code's process tree (breaking away from the job object
    on Windows when it allows it)."""
    kw: dict = {"start_new_session": True}
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        kw = {"creationflags": flags | subprocess.CREATE_BREAKAWAY_FROM_JOB}
    try:
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         close_fds=True, **kw)
    except OSError:
        if os.name != "nt":
            raise
        kw["creationflags"] &= ~subprocess.CREATE_BREAKAWAY_FROM_JOB  # a job object that forbids breaking away
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         close_fds=True, **kw)


def job_argv() -> list[str]:
    package_parent = str(Path(__file__).resolve().parents[1])
    code = (f"import sys; sys.path.insert(0, {package_parent!r}); from brain.memory import hook_main; "
            "sys.exit(hook_main(['run']))")
    return [sys.executable, "-I", "-c", code]


def session_end() -> bool:
    """The SessionEnd decision: spawn the job when a note changed or the pull is due, unless one is already queued
    (it rescans when it starts). True when a job was started."""
    if mode() == "off" or not needs_run(load_state()):
        return False
    queued = sync_dir() / "queued.json"
    timeout = _float_env("BRAIN_MEMORY_TIMEOUT", DEFAULT_TIMEOUT)
    try:
        if time.time() - queued.stat().st_mtime < 2 * timeout:
            return False
    except OSError:
        pass
    _write(queued, json.dumps({"at": _now()}))
    _spawn(job_argv())
    return True


def hook_main(argv: list[str], stdin=None) -> int:
    """``session-end`` (the SessionEnd hook: decide and spawn) or ``run`` (the detached job). Never fails, prints
    nothing: an error goes to <BRAIN_HOME>/ledger/errors.log."""
    event = argv[0] if argv else "session-end"
    try:
        if event == "run":
            job_main()
        else:
            # the hook's JSON, as bytes (a codepage decode can fail): nothing in it is needed
            stdin.read() if stdin is not None else getattr(sys.stdin, "buffer", sys.stdin).read()
            session_end()
    except BaseException as exc:  # noqa: BLE001 - a hook never breaks a session's end, SystemExit included
        _log_error(f"memory-{event}", exc)
    return 0


def main_cli(cmd: str, offline: bool = False, export_only: bool = False, out=None, note: str = "") -> int:
    """``brain memory status`` (what a sync would do, nothing written), ``brain memory sync`` (now, in the
    foreground) or ``brain memory undo NOTE`` (an import put back)."""
    out = out or sys.stdout
    if cmd == "undo":
        from .memoryundo import undo

        return undo(note, out)
    if cmd == "sync":
        if mode() == "off":
            print("brain: memory sync is off (BRAIN_MEMORY_SYNC=0)", file=out)
            return 1
        return job_main(force=True, out=out, do_import=False if export_only else None)
    try:
        report = sync(dry_run=True, offline=offline)
    except SyncError as exc:
        print(f"brain: {exc}", file=out)
        return 1
    for line in report.lines():
        print(line, file=out)
    return 0


if __name__ == "__main__":
    sys.exit(hook_main(sys.argv[1:]))
