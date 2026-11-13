"""``brain wave close-merged X.Y.Z``: the items a wave's merged PRs deliver, closed from the PRs themselves
(wi-brain-close-from-fragments; packages/brain/README.md and docs/release.md, « 1. Before the version PR »).

Zero token and git only: in each repo of the project, the pull requests merged on its default branch since the last
release tag before X.Y.Z (``git log --first-parent``: a merge commit ``Merge pull request #N from ...`` whose body's
first line is the PR's title, or a squash commit ``Title (#N)``), each mapped to the items it delivers:

- by its changelog fragment, a file the PR added under a ``changes/`` folder (``changes/<item>.md``, or a slug that
  starts with the item's id: ``<item>-upgrade.md``);
- by an item id its title names.

The plan: each open item a merged PR delivers, closed done with ``--pr "<repo> #N"`` and its outcome from the PR's
title, dated by its merge; the items already closed; then the wave's open items that no merged PR names (still to
merge, or to carry: ``brain wave close``). ``--write`` closes them (brain.graph.close_item). A rebase merge leaves no
trace of its PR on the default branch and is not read.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from . import graph, waves

MERGE = re.compile(r"^Merge pull request #(\d+) from \S+")
SQUASH = re.compile(r"^(?P<title>.*\S)\s+\(#(?P<n>\d+)\)$")
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9]")
TAG = re.compile(r"^v?(\d+\.\d+\.\d+)$")
SEP = "\x1f"   # between a commit's fields in git log's output
END = "\x1e"   # after each commit


class CloseError(RuntimeError):
    """git failed, or no release tag to start from."""


@dataclass
class MergedPR:
    repo: str          # the repo's name in the registry: the PR is "<repo> #<number>"
    number: int
    title: str
    sha: str
    day: str           # the merge's date, YYYY-MM-DD
    fragments: list[str] = field(default_factory=list)   # the changelog fragments it added

    @property
    def ref(self) -> str:
        return f"{self.repo} #{self.number}"


@dataclass
class Plan:
    version: str
    wave: str
    ranges: dict[str, str] = field(default_factory=dict)        # repo -> the range read (tag..end)
    prs: list[MergedPR] = field(default_factory=list)
    to_close: dict[str, list[MergedPR]] = field(default_factory=dict)   # open item -> its merged PRs
    closed: dict[str, list[MergedPR]] = field(default_factory=dict)     # already done or dropped
    outside: list[str] = field(default_factory=list)            # items to close that are not the wave's
    unmapped: list[MergedPR] = field(default_factory=list)      # merged PRs that name no item
    waiting: list[str] = field(default_factory=list)            # the wave's open items no merged PR names
    skipped: dict[str, str] = field(default_factory=dict)       # repo -> why it was not read

    def as_dict(self) -> dict:
        def prs(xs):
            return [{"pr": p.ref, "title": p.title, "merged": p.day, "fragments": p.fragments} for p in xs]
        return {"version": self.version, "wave": self.wave, "ranges": self.ranges,
                "close": {i: prs(v) for i, v in self.to_close.items()},
                "closed": {i: prs(v) for i, v in self.closed.items()}, "outside": self.outside,
                "unmapped": prs(self.unmapped), "waiting": self.waiting, "skipped": self.skipped}


def _git(repo: Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CloseError(f"git {' '.join(args[:2])}: {exc}") from exc
    if r.returncode:
        raise CloseError(f"git {' '.join(args[:2])} in {repo}: {r.stderr.strip() or r.returncode}")
    return r.stdout


def release_tags(repo: Path) -> dict[tuple[int, int, int], str]:
    """The repo's release tags (vX.Y.Z or X.Y.Z), by their release."""
    out = {}
    for name in _git(repo, "tag", "--list").split():
        m = TAG.match(name)
        key = waves.release_key(m.group(1)) if m else None
        if key is not None:
            out[key] = name
    return out


def _default_end(repo: Path) -> str:
    """The default branch as fetched: origin/HEAD's target, else origin/main or origin/master, else HEAD."""
    try:
        head = _git(repo, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD").strip()
    except CloseError:
        head = ""
    for spec in ([head] if head else []) + ["refs/remotes/origin/main", "refs/remotes/origin/master"]:
        try:
            _git(repo, "rev-parse", "--verify", "--quiet", spec)
        except CloseError:
            continue
        return spec
    return "HEAD"


def span(repo: Path, version: str, since: str = "", until: str = "") -> tuple[str, str]:
    """(from, to): the last release tag before ``version`` (``since`` instead) to its own tag when it is cut, else
    the default branch (``until`` instead)."""
    key = waves.release_key(version)
    if key is None:
        raise CloseError(f"{version}: not a release X.Y.Z")
    tags = release_tags(repo)
    start = since or next((tags[k] for k in sorted(tags, reverse=True) if k < key), "")
    if not start:
        raise CloseError(f"{repo.name}: no release tag before {version} (--since REF)")
    return start, until or tags.get(key) or _default_end(repo)


def merged_prs(repo: Path, name: str, start: str, end: str) -> list[MergedPR]:
    """The PRs merged on the first-parent line of ``end`` since ``start``, oldest first, with the changelog fragments
    each added."""
    log = _git(repo, "log", "--first-parent", "--reverse", f"--format=%H{SEP}%cs{SEP}%B{END}", f"{start}..{end}")
    out = []
    for record in log.split(END):
        if SEP not in record:
            continue
        sha, day, body = record.strip("\n").split(SEP, 2)
        pr = _pr_of(body)
        if pr is None:
            continue
        number, title = pr
        added = _git(repo, "diff", "--name-only", "--diff-filter=A", "--no-renames", f"{sha}^1", sha).splitlines()
        out.append(MergedPR(name, number, title, sha, day, [f for f in added if is_fragment(f)]))
    return out


def _pr_of(body: str) -> tuple[int, str] | None:
    """(its number, its title) from a merge commit's message, or None for a commit that merged no PR."""
    lines = [x.strip() for x in body.splitlines()]
    head = lines[0] if lines else ""
    m = MERGE.match(head)
    if m:
        title = next((x for x in lines[1:] if x), "")
        return int(m.group(1)), title
    m = SQUASH.match(head)
    return (int(m.group("n")), m.group("title")) if m else None


def is_fragment(path: str) -> bool:
    p = PurePosixPath(path)
    return p.parent.name == "changes" and p.suffix == ".md" and p.name.lower() != "readme.md"


def items_of(pr: MergedPR, ids: set[str]) -> list[str]:
    """The items a PR delivers: each fragment's (its name, or the longest id its name starts with then a dash), and
    the ids its title names; in that order, once each."""
    found = []
    for f in pr.fragments:
        stem = PurePosixPath(f).stem
        hit = stem if stem in ids else max((i for i in ids if stem.startswith(i + "-")), key=len, default="")
        if hit:
            found.append(hit)
    found += [t for t in TOKEN.findall(pr.title) if t in ids]
    return list(dict.fromkeys(found))


def plan(store: Path, repos: list[tuple[str, Path]], version: str, since: str = "", until: str = "",
         root: Path | None = None) -> Plan:
    """What close-merged does for the wave ``version`` over ``repos`` ((name, checkout) pairs)."""
    wp = waves.load(store, root)
    wid = wp.resolve(version)
    if wid is None:
        raise CloseError(f"{version}: no wave of that release (brain wave add {version})")
    out = Plan(version, wid)
    for name, path in repos:
        try:
            start, end = span(path, version, since, until)
            out.prs += merged_prs(path, name, start, end)
        except CloseError as exc:
            out.skipped[name] = str(exc)
            continue
        out.ranges[name] = f"{start}..{end}"
    items = {k for k, n in wp.nodes.items() if n.get("type") == "WorkItem"}
    for pr in out.prs:
        hits = items_of(pr, items)
        if not hits:
            out.unmapped.append(pr)
        for i in hits:
            bucket = out.to_close if wp.status(i) in waves.OPEN else out.closed
            bucket.setdefault(i, []).append(pr)
    members = set(wp.items_of(wid))
    out.outside = sorted(i for i in out.to_close if i not in members)
    out.waiting = [i for i in wp.items_of(wid) if wp.status(i) in waves.OPEN and i not in out.to_close]
    return out


def outcome(prs: list[MergedPR]) -> str:
    return "; ".join(dict.fromkeys(p.title for p in prs if p.title))


def write(store: Path, p: Plan) -> list[str]:
    """Each item of ``p.to_close`` closed done with its PRs, the outcome from their titles, dated by the last merge."""
    done = []
    for item, prs in p.to_close.items():
        graph.close_item(store, item, ", ".join(dict.fromkeys(x.ref for x in prs)), outcome(prs),
                         today=max(x.day for x in prs))
        done.append(item)
    return done


def render(p: Plan, written: bool) -> list[str]:
    lines = [f"wave {p.version} ({p.wave}): {len(p.prs)} merged PR(s) read"]
    lines += [f"  {repo}: {rng}" for repo, rng in p.ranges.items()]
    lines += [f"  {repo}: not read: {why}" for repo, why in p.skipped.items()]
    verb = "closed" if written else "to close"
    for item, prs in p.to_close.items():
        where = " (not in this wave)" if item in p.outside else ""
        lines.append(f"{verb}: {item}{where} --pr \"{', '.join(dict.fromkeys(x.ref for x in prs))}\" "
                     f"--outcome \"{outcome(prs)}\"")
    for item, prs in p.closed.items():
        lines.append(f"already closed: {item} ({', '.join(x.ref for x in prs)})")
    for pr in p.unmapped:
        lines.append(f"names no item: {pr.ref} {pr.title}")
    for item in p.waiting:
        lines.append(f"no merged PR: {item} (still to merge, or brain wave close {p.version} --carry-to)")
    tail = "written; then brain sync and brain check" if written else "not written: --write"
    lines.append(f"close-merged {p.version}: {len(p.to_close)} item(s) {verb}, {len(p.closed)} already closed, "
                 f"{len(p.waiting)} with no merged PR; {tail}")
    return lines
