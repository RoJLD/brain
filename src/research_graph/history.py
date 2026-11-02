"""The graph's history, read from git: when each node was created and how its status, title and props changed, and
the whole store as it was on a given day.

The history follows the first-parent chain of a revision (``HEAD`` by default): on ``main`` each step is a merged
PR or a direct commit, dated when it landed, so a status change is dated by its merge and named by its PR number
(``Merge pull request #89 ...``). One ``git log --raw`` over ``<store>/nodes`` and one ``git cat-file --batch``
read every version of the node files; nothing is checked out and nothing is written to the repository.

    timeline(store)                 # every change to the work layer (WorkItem, Milestone, Spec), oldest first
    timeline(store, types=None)     # every node type
    load_store_at(store, commit)    # the store as of a commit, validated with that commit's own schema
    commit_on(store, day)           # the last first-parent commit on or before a day
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import networkx as nx
import yaml

from .loader import load_store

WORK_TYPES = frozenset({"WorkItem", "Milestone", "Spec"})
# libyaml when present: the history parses every version of every node file.
_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
_PR = re.compile(r"^Merge pull request #(\d+)")


class GitError(RuntimeError):
    pass


def _git(cwd: str | Path, *args: str, stdin: bytes | None = None) -> bytes:
    try:
        res = subprocess.run(["git", "-C", str(cwd), *args], input=stdin, capture_output=True)
    except FileNotFoundError as exc:
        raise GitError("git is not installed") from exc
    if res.returncode:
        raise GitError(f"git {' '.join(args[:2])} failed in {cwd}: "
                       + res.stderr.decode("utf-8", "replace").strip())
    return res.stdout


def repo_location(store: str | Path) -> tuple[Path, str]:
    """(top level of the git repository holding ``store``, the store's path inside it in posix form, '' at the top)."""
    store = Path(store)
    if not store.is_dir():
        raise GitError(f"no store directory {store}")
    top = _git(store, "rev-parse", "--show-toplevel").decode("utf-8").strip()
    prefix = _git(store, "rev-parse", "--show-prefix").decode("utf-8").strip().rstrip("/")
    return Path(top), prefix


@dataclass(frozen=True)
class Commit:
    sha: str
    when: datetime
    subject: str

    @property
    def day(self) -> str:
        return self.when.date().isoformat()

    @property
    def ref(self) -> str:
        """``#89`` for a merged PR, else the short sha."""
        m = _PR.match(self.subject)
        return f"#{m.group(1)}" if m else self.sha[:7]

    def to_json(self) -> dict:
        return {"sha": self.sha, "date": self.when.isoformat(), "ref": self.ref, "subject": self.subject}


@dataclass(frozen=True)
class Event:
    """One change to one node. ``kind``: created, status, title, props, anchor or removed. For ``props``, ``old``
    and ``new`` map each changed key to its value before and after (None when absent)."""

    id: str
    type: str
    kind: str
    commit: Commit
    old: Any = None
    new: Any = None

    @property
    def day(self) -> str:
        return self.commit.day

    def describe(self) -> str:
        if self.kind == "created":
            return f"created [{self.new}]"
        if self.kind == "removed":
            return f"removed (was {self.old})"
        if self.kind == "status":
            return f"status {self.old} -> {self.new}"
        if self.kind == "props":
            marks = []
            for k in self.new:
                if self.old.get(k) is None:
                    marks.append(f"+{k}")
                elif self.new.get(k) is None:
                    marks.append(f"-{k}")
                else:
                    marks.append(f"~{k}")
            return "props " + " ".join(marks)
        return f"{self.kind} changed"

    def to_json(self) -> dict:
        return {"id": self.id, "type": self.type, "kind": self.kind, "old": self.old, "new": self.new,
                "commit": self.commit.to_json()}


@dataclass
class _Replay:
    """Node files as of the current step: id -> node, and which file each id came from."""

    files: dict[str, set[str]] = field(default_factory=dict)
    index: dict[str, dict] = field(default_factory=dict)
    owner: dict[str, str] = field(default_factory=dict)

    def apply(self, path: str, nodes: dict[str, dict]) -> None:
        for nid in self.files.get(path, set()):
            if self.owner.get(nid) == path:
                del self.index[nid], self.owner[nid]
        self.files[path] = set(nodes)
        for nid, node in nodes.items():
            self.index[nid] = node
            self.owner[nid] = path


def _log(top: Path, path: str, rev: str) -> list[tuple[Commit, dict[str, str | None]]]:
    """First-parent commits of ``rev`` that changed ``path``, oldest first, with each changed file's new blob."""
    out = _git(top, "log", "--first-parent", "--diff-merges=first-parent", "--raw", "--no-abbrev", "--no-renames",
               "--format=@@%H%x09%cI%x09%s", rev, "--", path).decode("utf-8", "replace")
    commits: list[tuple[Commit, dict[str, str | None]]] = []
    for line in out.splitlines():
        if line.startswith("@@"):
            sha, when, subject = (line[2:].split("\t", 2) + ["", ""])[:3]
            commits.append((Commit(sha, datetime.fromisoformat(when), subject), {}))
        elif line.startswith(":") and "\t" in line and commits:
            meta, fpath = line.split("\t", 1)
            parts = meta.split()
            commits[-1][1][fpath] = None if parts[4].startswith("D") else parts[3]
    commits.reverse()
    return commits


def _blobs(top: Path, shas: Iterable[str]) -> dict[str, bytes]:
    wanted = sorted(set(shas))
    if not wanted:
        return {}
    out = _git(top, "cat-file", "--batch", stdin=("\n".join(wanted) + "\n").encode())
    blobs: dict[str, bytes] = {}
    pos = 0
    for sha in wanted:
        nl = out.index(b"\n", pos)
        header = out[pos:nl].split()
        if len(header) < 3:  # "<sha> missing"
            pos = nl + 1
            continue
        size = int(header[2])
        blobs[sha] = out[nl + 1:nl + 1 + size]
        pos = nl + 1 + size + 1
    return blobs


def _nodes(blob: bytes) -> dict[str, dict] | None:
    """id -> node of one version of a node file; None when that version does not parse."""
    try:
        data = yaml.load(blob.decode("utf-8", "replace"), Loader=_LOADER)
    except yaml.YAMLError:
        return None
    if data is None:
        return {}
    if not isinstance(data, list):
        return None
    return {n["id"]: n for n in data if isinstance(n, dict) and isinstance(n.get("id"), str)}


def _diff(nid: str, old: dict | None, new: dict | None, commit: Commit,
          types: frozenset[str] | None) -> list[Event]:
    ntype = (new or old or {}).get("type")
    if types is not None and ntype not in types:
        return []
    if old is None and new is not None:
        return [Event(nid, ntype, "created", commit, None, new.get("status"))]
    if new is None and old is not None:
        return [Event(nid, ntype, "removed", commit, old.get("status"), None)]
    if old == new or old is None:
        return []
    out = []
    for key in ("status", "title", "anchor"):
        if old.get(key) != new.get(key):
            out.append(Event(nid, ntype, key, commit, old.get(key), new.get(key)))
    op, np_ = old.get("props") or {}, new.get("props") or {}
    keys = [k for k in dict.fromkeys([*op, *np_]) if op.get(k) != np_.get(k)]
    if keys:
        out.append(Event(nid, ntype, "props", commit, {k: op.get(k) for k in keys}, {k: np_.get(k) for k in keys}))
    return out


def timeline(store: str | Path, *, rev: str = "HEAD", types: Iterable[str] | None = WORK_TYPES) -> list[Event]:
    """Every change to the store's nodes along the first-parent chain of ``rev``, oldest first; ``types`` limits it
    to some node types (default: the work layer; None: every type). A file version that does not parse is skipped:
    its nodes keep their previous state."""
    types = frozenset(types) if types is not None else None
    top, prefix = repo_location(store)
    nodes_dir = f"{prefix}/nodes" if prefix else "nodes"
    commits = _log(top, nodes_dir, rev)
    blobs = _blobs(top, (b for _, changes in commits for b in changes.values() if b))
    parsed: dict[str, dict[str, dict] | None] = {}
    replay = _Replay()
    events: list[Event] = []
    for commit, changes in commits:
        changes = {p: b for p, b in changes.items()
                   if p.endswith(".yaml") and p.rsplit("/", 1)[0] == nodes_dir}
        if not changes:
            continue
        affected: set[str] = set()
        versions: dict[str, dict[str, dict]] = {}
        for path, blob in changes.items():
            if blob is None:
                nodes: dict[str, dict] | None = {}
            else:
                if blob not in parsed:
                    parsed[blob] = _nodes(blobs[blob]) if blob in blobs else None
                nodes = parsed[blob]
            if nodes is None:
                continue
            versions[path] = nodes
            affected |= replay.files.get(path, set()) | set(nodes)
        before = {nid: replay.index.get(nid) for nid in affected}
        for path, nodes in versions.items():
            replay.apply(path, nodes)
        for nid in sorted(affected):
            events += _diff(nid, before[nid], replay.index.get(nid), commit, types)
    return events


def commit_on(store: str | Path, day: date, *, rev: str = "HEAD") -> Commit | None:
    """The last first-parent commit of ``rev`` made on or before ``day`` (local time), or None."""
    top, _ = repo_location(store)
    out = _git(top, "log", "--first-parent", "-1", f"--before={day.isoformat()}T23:59:59",
               "--format=%H%x09%cI%x09%s", rev, "--").decode("utf-8", "replace").strip()
    if not out:
        return None
    sha, when, subject = (out.split("\t", 2) + ["", ""])[:3]
    return Commit(sha, datetime.fromisoformat(when), subject)


def load_store_at(store: str | Path, commit: str) -> nx.DiGraph:
    """The store as of ``commit``, loaded (and validated) with that commit's own schema. Raises GitError when the
    store did not exist then, and ``loader.ValidationError`` when that version does not validate."""
    top, prefix = repo_location(store)
    listing = _git(top, "ls-tree", "-r", "-z", "--full-tree", commit, "--", prefix or ".")
    entries = []
    for rec in listing.split(b"\0"):
        if b"\t" not in rec:
            continue
        meta, path = rec.split(b"\t", 1)
        entries.append((path.decode("utf-8"), meta.split()[2].decode()))
    if not entries:
        raise GitError(f"{prefix or 'the store'} does not exist at {commit[:7]}")
    blobs = _blobs(top, (b for _, b in entries))
    with tempfile.TemporaryDirectory(prefix="graph-asof-") as tmp:
        for path, blob in entries:
            rel = path[len(prefix) + 1:] if prefix else path
            if not rel.endswith(".yaml") or blob not in blobs:
                continue
            dst = Path(tmp, rel)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(blobs[blob])
        return load_store(tmp)
