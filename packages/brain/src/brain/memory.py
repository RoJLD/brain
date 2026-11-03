"""Memory shared across machines by a reviewed PR (wi-brain-memory-pr; spec-brain-plugin section 2.4, option 2).

Claude Code keeps its automatic memory per machine, ``<projects>/<key>/memory/*.md`` (``<key>``: the project's folder,
encoded). The Brain repo holds the shared copy, ``memory/<key>/*.md`` on ``main``. A sync, token-free:

1. fetches ``main`` and this machine's branch of the day into a private bare repo, ``<BRAIN_HOME>/memory-sync/repo.git``
   (never a working checkout: no branch switch, no index, no stash; git plumbing only);
2. compares each note three ways: the local copy, ``main``'s, and the base (the version this machine last saw equal on
   both sides, in ``state.json``; without one, a local copy found in ``main``'s history at that path is an old one);
3. imports what only ``main`` changed (reviewed notes from another machine), the replaced copy backed up under
   ``memory-sync/backup/<date>``; a note is imported only into a project folder that exists on this machine;
4. exports what only this machine changed: the secret scan first (a hit refuses the whole export), then a commit built
   on ``main`` and force-pushed to ``memory/<machine>/<date>``, one PR per machine and day (an older open PR of the
   machine is closed as superseded: the new branch holds its changes). Never a push to ``main``: the owner, or the
   close-item flow, merges the PR;
5. keeps both sides of a conflict (both changed since the base): the local copy goes to the PR as
   ``<stem>.conflict-<machine>.md`` beside ``main``'s, and ``MEMORY.md`` (an index) as the union of both sides' lines,
   flagged in the PR title and body and in the alert. Once the PR that carried it is closed and ``main`` moved past the
   flagged version (the reviewer merged both), ``main``'s note is imported.

The SessionEnd hook (``hook_main(["session-end"])``) only decides and spawns: when a note changed since the last run
(mtime and size) or the last pull is older than ``BRAIN_MEMORY_PULL_HOURS``, it starts ``run`` detached and returns, in
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
import socket
import subprocess
import sys
import time
import zlib
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from . import config, paths, secretscan

DEFAULT_TIMEOUT = 300.0
DEFAULT_PULL_HOURS = 12.0
INDEX = "MEMORY.md"
CONFLICT_RX = re.compile(r"\.conflict-[A-Za-z0-9_-]+\.md$")
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
    raw = os.environ.get("BRAIN_MACHINE") or socket.gethostname() or "machine"
    return re.sub(r"[^a-z0-9-]+", "-", raw.lower()).strip("-")[:40] or "machine"


def key_map() -> dict[str, str]:
    """BRAIN_MEMORY_MAP, 'local-key=repo-key;...': local project folder -> repo key ('' leaves the folder out)."""
    out = {}
    for part in re.split(r"[;\n]", os.environ.get("BRAIN_MEMORY_MAP", "")):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def local_notes() -> dict[str, Path]:
    """'key/name.md' -> local file, for every note of every project's memory folder (MEMORY.md included, conflict
    copies left out)."""
    root = paths.projects_dir()
    if not root.is_dir():
        return {}
    aliases = key_map()
    out = {}
    for mem in sorted(root.glob("*/memory")):
        key = aliases.get(mem.parent.name, mem.parent.name)
        if not key:
            continue
        for f in sorted(mem.glob("*.md")):
            if f.is_file() and not CONFLICT_RX.search(f.name):
                out[f"{key}/{f.name}"] = f
    return out


def local_dir(key: str) -> Path | None:
    """This machine's memory folder for the repo key ``key``, when its project folder exists (import never creates
    a project folder: on a machine with another layout it would be noise)."""
    aliases = key_map()
    local_key = next((k for k, v in aliases.items() if v == key), key)
    if aliases.get(local_key, local_key) != key:
        return None
    proj = paths.projects_dir() / local_key
    return proj / "memory" if proj.is_dir() else None


def snapshot(notes: dict[str, Path]) -> dict[str, list[int]]:
    out = {}
    for k, f in notes.items():
        try:
            st = f.stat()
        except OSError:
            continue
        out[k] = [st.st_mtime_ns, st.st_size]
    return out


def load_state() -> dict:
    try:
        data = json.loads((sync_dir() / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(path: Path, data: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".brain-tmp")
    if isinstance(data, str):
        data = data.encode("utf-8")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def save_state(state: dict) -> None:
    _write(sync_dir() / "state.json", json.dumps(state, indent=1, sort_keys=True, ensure_ascii=False))


def needs_run(state: dict, now: float | None = None) -> bool:
    """A note changed since the last run (mtime or size), or the last pull is older than the pull interval."""
    if snapshot(local_notes()) != state.get("snapshot"):
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


def union_lines(main: bytes, local: bytes) -> bytes:
    """``main``'s lines, then the lines only ``local`` has, in order (an index merged by keeping both sides)."""
    lines = main.decode("utf-8", "replace").splitlines()
    seen = set(lines)
    for line in local.decode("utf-8", "replace").splitlines():
        if line.strip() and line not in seen:
            lines.append(line)
            seen.add(line)
    return ("\n".join(lines).rstrip("\n") + "\n").encode("utf-8")


def decide(local: str | None, main: str | None, entry: dict, history: set[str],
           conflict_open=lambda branch: True) -> tuple[str, str | None]:
    """(action, base) for one note from blob ids: the local copy, main's, the state entry (base, conflict) and the
    blobs main ever had at that path. ``conflict_open(branch)``: whether the PR that carried a flagged conflict is
    still open. Actions: same, import, export, conflict, resolved (a flagged conflict main moved past: import), kept
    (deleted on main, kept here, not exported again)."""
    base = entry.get("base")
    if local == main:
        return "same", main
    if local is None:
        return "import", base
    if main is None:
        return ("kept", base) if base is not None and local == base else ("export", base)
    flagged = entry.get("conflict") or {}
    if flagged.get("local") == local and flagged.get("main") != main and not conflict_open(flagged.get("branch")):
        return "resolved", base
    if base is None:  # first sync of this note here: a local copy main once had is an old one
        base = local if local in history else main
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
    pushed: bool = False
    pr: str = ""
    error: str = ""
    dry_run: bool = False

    def lines(self) -> list[str]:
        """One line per note that is not in sync, then the outcome."""
        by: dict[str, list[str]] = {}
        for note, action in sorted(self.actions.items()):
            by.setdefault(action, []).append(note)
        out = [f"{action:<9} {note}" for action in ("export", "conflict", "import", "resolved", "kept")
               for note in by.get(action, [])]
        if by.get("same"):
            out.append(f"same      {len(by['same'])} note(s)")
        if self.hits:
            out.append("refused   the export: secret patterns in " + ", ".join(self.hits))
        if self.error:
            out.append(f"failed    {self.error}")
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
        self.branch = f"memory/{self.machine}/{self.day}"
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
        """This machine's open memory PRs, by branch."""
        if self._prs is None:
            out = self.gh("pr", "list", "--state", "open", "--json", "number,url,headRefName", "--limit", "100")
            prefix = f"memory/{self.machine}/"
            self._prs = {p["headRefName"]: p for p in json.loads(out or "[]")
                         if str(p.get("headRefName", "")).startswith(prefix)}
        return self._prs

    def conflict_open(self, branch: str | None) -> bool:
        try:
            return bool(branch) and branch in self.open_prs()
        except (SyncError, ValueError):
            return True  # unknown: keep the conflict flagged

    # steps

    def refs(self) -> dict[str, tuple[str, str]]:
        """The private repo's branches: ref -> (commit, tree)."""
        out = {}
        for line in self.git("for-each-ref", "--format=%(refname) %(objectname) %(tree)", "refs/heads/").splitlines():
            ref, commit, tree = line.split()
            out[ref] = (commit, tree)
        return out

    def fetch(self, offline: bool = False) -> tuple[str, str | None]:
        """(main's commit, the branch's commit or None), fetched into the private bare repo (``offline``: as last
        fetched); their trees in ``self.trees``."""
        main_ref, branch_ref = "refs/heads/main", f"refs/heads/{self.branch}"
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
            heads = {r: refs[r][0] for r in (main_ref, branch_ref) if r in refs}
        else:
            heads = {}
            for line in self.git("ls-remote", "origin", main_ref, branch_ref).splitlines():
                sha, _, ref = line.partition("\t")
                heads[ref] = sha
            want = [f"+{r}:{r}" for r, sha in heads.items() if refs.get(r, ("",))[0] != sha]
            if want:
                self.git("fetch", "-q", "--no-tags", "origin", *want)
            if branch_ref in refs and branch_ref not in heads:
                self.git("update-ref", "-d", branch_ref)
            if want:
                refs = self.refs()
        if main_ref not in heads:
            raise SyncError("nothing fetched yet: run without --offline" if offline else "the remote has no main")
        self.trees = {r: refs[r][1] for r in heads}
        return heads[main_ref], heads.get(branch_ref)

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

    def open_pr(self, title: str, body: str, state: dict) -> str:
        """Open or update the PR of the day, close this machine's older ones (the branch of the day holds their
        changes); its URL."""
        prs = self.open_prs()
        if self.branch in prs:
            pr = prs[self.branch]
            self.gh("pr", "edit", str(pr["number"]), "--title", title, "--body-file", "-", data=body)
            url = pr["url"]
        else:
            out = self.gh("pr", "create", "--base", "main", "--head", self.branch, "--title", title,
                          "--body-file", "-", data=body)
            url = (out.splitlines() or [""])[-1].strip()
        state.setdefault("prs", {})[self.branch] = url
        for branch, pr in sorted(prs.items()):
            if branch != self.branch:
                self.gh("pr", "close", str(pr["number"]), "--delete-branch",
                        "--comment", f"Superseded by {url}: the branch of {self.day} holds these notes.")
        return url


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


def sync(*, dry_run: bool = False, offline: bool = False, do_import: bool = True, do_export: bool = True,
         day: str | None = None, gh=None, timeout: float | None = None, state: dict | None = None) -> Report:
    """One sync, both ways (see the module's docstring). ``state`` is updated in place (saved by the caller)."""
    state = load_state() if state is None else state
    deadline = time.monotonic() + (timeout or _float_env("BRAIN_MEMORY_TIMEOUT", DEFAULT_TIMEOUT))
    remote = remote_url()
    if not remote:
        raise SyncError("no remote: set BRAIN_MEMORY_REMOTE, or install the brain command from a clone "
                        "(install.ps1 -Apply)")
    s = Sync(remote, deadline, day, gh)
    report = Report(s.machine, s.day, s.branch, dry_run=dry_run)
    main, branch_head = s.fetch(offline)
    if not dry_run:
        state["fetched_epoch"], state["fetched_at"] = time.time(), _now()
        state["remote"] = secretscan.strip_url_credentials(remote)
    on_main = s.main_notes(main)
    history = s.history(main)
    notes = local_notes()
    snap = snapshot(notes)
    local = {k: normalize(f.read_bytes()) for k, f in notes.items()}
    entries = state.setdefault("notes", {}) if not dry_run else dict(state.get("notes") or {})
    keys = sorted(set(local) | {k for k in on_main if local_dir(k.split("/")[0]) is not None})

    files: dict[str, bytes] = {}
    changes: list[tuple[str, str]] = []
    conflicts: list[tuple[str, str]] = []
    for k in keys:
        lb = blob_id(local[k]) if k in local else None
        mb = on_main.get(k)
        entry = dict(entries.get(k) or {})
        action, base = decide(lb, mb, entry, history.get(k, set()), s.conflict_open)
        report.actions[k] = action
        if action in ("same", "import", "resolved"):
            if action != "same":
                if not do_import:
                    continue
                if not dry_run:
                    _import(s, k, mb, notes, snap)
                report.imported.append(k)
            entries[k] = {"base": mb}
        elif action == "export":
            files[f"memory/{k}"] = local[k]
            changes.append((f"memory/{k}", "new" if mb is None else "edited"))
            entries[k] = {"base": base} if base else {}
        elif action == "conflict":
            key, name = k.split("/", 1)
            if name == INDEX:
                merged = union_lines(s.blob(mb), local[k])
                if blob_id(merged) == mb:  # main's index already has every local line
                    report.actions[k] = "import"
                    if do_import and not dry_run:
                        _import(s, k, mb, notes, snap)
                        report.imported.append(k)
                        entries[k] = {"base": mb}
                    continue
                files[f"memory/{k}"] = merged
                how = "the union of both indexes' lines (check the order and duplicates)"
            else:
                side = f"memory/{key}/{name[:-3]}.conflict-{s.machine}.md"
                files[side] = local[k]
                how = f"`{s.machine}`'s version is `{side}`"
            conflicts.append((k, how))
            report.conflicts.append(k)
            entries[k] = {"base": base, "conflict": {"local": lb, "main": mb, "branch": s.branch}}
    for path, data in files.items():  # the secret scan: one hit refuses the whole export
        for line, pattern in secretscan.scan_lines(data.decode("utf-8", "replace")):
            report.hits.append(f"{path[len('memory/'):]}:{line} {pattern}")
    report.exported = sorted(files)

    if files and do_export and not dry_run and not report.hits:
        # the branch already holds these files on this main (the last push, from the state): no git at all
        digest = blob_id(json.dumps(sorted((p, blob_id(d)) for p, d in files.items())).encode("utf-8"))
        pushed = (state.get("pushed") or {}).get(s.branch) or {}
        same = branch_head is not None and pushed == {"commit": branch_head, "main": main, "files": digest}
        if not same:
            tree = s.build(main, files)
            same = branch_head is not None and s.trees.get(f"refs/heads/{s.branch}") == tree
            if not same:
                message = (_title(s.machine, s.day, len(conflicts)) + "\n\n"
                           + "\n".join(f"{p} ({what})" for p, what in changes + [(f"memory/{n}", "conflict")
                                                                              for n, _ in conflicts]) + "\n")
                commit = s.commit(tree, main, message)
                s.git("push", "-q", "origin", f"+{commit}:refs/heads/{s.branch}")
                s.git("update-ref", f"refs/heads/{s.branch}", commit)
                state.setdefault("pushed", {})[s.branch] = {"commit": commit, "main": main, "files": digest}
                report.pushed = True
        if not same or s.branch not in (state.get("prs") or {}):  # or a PR the last run failed to open
            report.pr = s.open_pr(_title(s.machine, s.day, len(conflicts)), pr_body(report, changes, conflicts),
                                  state)
        else:
            report.pr = state["prs"][s.branch]
    if not dry_run:
        state["snapshot"] = snap
        for k in ("prs", "pushed"):  # two weeks of branches
            state[k] = {b: v for b, v in (state.get(k) or {}).items() if b[-10:] >= _days_ago(14)}
    return report


def _import(s: Sync, k: str, mb: str, notes: dict[str, Path], snap: dict) -> None:
    """Write main's version of the note ``k`` here, the replaced copy backed up under memory-sync/backup/<date>."""
    key, name = k.split("/", 1)
    target = notes.get(k) or local_dir(key) / name
    if target.exists():
        _write(sync_dir() / "backup" / date.today().isoformat() / key / name, target.read_bytes())
    _write(target, s.blob(mb))
    snap.update(snapshot({k: target}))


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
        out.append(f"{head} export refused, secret patterns in {', '.join(report.hits[:5])}. Remove the secret from "
                   "the local note (~/.claude/projects/<key>/memory/), then `brain memory sync`; nothing was pushed.")
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
        state = load_state()
        if not force and not needs_run(state):
            return 0
        report, error = None, ""
        try:
            report = sync(do_import=mode() == "both" if do_import is None else do_import, state=state,
                          timeout=timeout, **kw)
        except SyncError as exc:
            error = str(exc)
        except Exception as exc:  # noqa: BLE001 - the job reports, it never raises
            error = f"{type(exc).__name__}: {exc}"
            _log_error("memory-sync", exc)
        if report or error:
            if not error:
                save_state(state)
            last = {"at": _now(), "took": round(time.monotonic() - started, 2), "machine": machine(),
                    "result": "failed" if error else "refused" if report.hits else "ok", "error": error}
            if report:
                last.update(branch=report.branch, pr=report.pr, pushed=report.pushed, imported=report.imported,
                            exported=report.exported, conflicts=report.conflicts, hits=report.hits)
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
            (stdin or sys.stdin).read()  # the hook's JSON: nothing in it is needed
            session_end()
    except BaseException as exc:  # noqa: BLE001 - a hook never breaks a session's end, SystemExit included
        _log_error(f"memory-{event}", exc)
    return 0


def main_cli(cmd: str, offline: bool = False, export_only: bool = False, out=None) -> int:
    """``brain memory status`` (what a sync would do, nothing written) or ``brain memory sync`` (now, in the
    foreground)."""
    out = out or sys.stdout
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
