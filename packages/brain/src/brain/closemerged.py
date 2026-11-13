"""``brain wave close-merged X.Y.Z``: the items a wave's merged PRs deliver, closed from the PRs themselves
(wi-brain-close-from-fragments; packages/brain/README.md and docs/release.md, « 1. Before the version PR »).

Zero token and git only: in each repo of the project, the pull requests merged on its default branch (as last
fetched) since the repo's last release tag before X.Y.Z (``git log --first-parent``: a merge commit ``Merge pull
request #N from ...`` whose body's first line is the PR's title, or a squash commit ``Title (#N)``), each mapped to
the items it delivers:

- by its changelog fragment, a file the PR added in a fragment folder (``changes/`` or ``packages/<name>/changes/``,
  the folders the changelog compiler reads): ``<item>.md``, or ``<item>-<section>.md`` (upgrade, added, fixes,
  changes) and ``<item>-<n>.md``; a fragment that names no item is listed;
- by an item id its title names (any case).

A revert PR (its title ``Revert "<title>"``) maps no item, and takes the PR it reverts out of its items' lists.

The plan: each open item a merged PR delivers, closed done with ``--pr "<repo> #N"`` (after the refs its props.pr
holds already) and its outcome from the PR's title, dated by its merge; the items already closed; then the wave's open
items that no merged PR names (still to merge, or to carry: ``brain wave close``). ``--write`` closes them
(brain.graph.close_item), refused while a repo could not be read. A rebase merge leaves no trace of its PR on the
default branch and is not read; a title that only mentions an item (« part 1 of ... ») closes it too: the fragment is
the mapping to trust.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from . import graph, waves

MERGE = re.compile(r"^Merge pull request #(\d+) from \S+")
SQUASH = re.compile(r"^(?P<title>.*\S)\s+\(#(?P<n>\d+)\)$")
REVERT = re.compile(r'^Revert "(?P<title>.+)"$')
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9]")
TAG = re.compile(r"^v?(\d+\.\d+\.\d+)$")
SUFFIX = re.compile(r"^(?:upgrade|added|fixes|changes|\d+)$")   # <item>-<suffix>.md: one PR's second fragment
CLOSED = ("done", "dropped")
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

    @property
    def reverts(self) -> str:
        """The title of the PR this one reverts, else ''."""
        m = REVERT.match(self.title)
        return _bare(m.group("title")) if m else ""


@dataclass
class Plan:
    version: str
    wave: str
    ranges: dict[str, str] = field(default_factory=dict)        # repo -> the range read (tag, its date..end)
    prs: list[MergedPR] = field(default_factory=list)
    to_close: dict[str, list[MergedPR]] = field(default_factory=dict)   # open item -> its merged PRs
    closed: dict[str, list[MergedPR]] = field(default_factory=dict)     # already done or dropped
    other: dict[str, str] = field(default_factory=dict)         # an item of another status: its status
    outside: list[str] = field(default_factory=list)            # items to close that are not the wave's
    unmapped: list[MergedPR] = field(default_factory=list)      # merged PRs that name no item
    reverted: dict[str, str] = field(default_factory=dict)      # a PR reverted -> the PR that reverted it
    stray: list[str] = field(default_factory=list)              # fragments that name no item ("<repo>: <path>")
    waiting: list[str] = field(default_factory=list)            # the wave's open items no merged PR names
    skipped: dict[str, str] = field(default_factory=dict)       # repo -> why it was not read
    earlier: dict[str, str] = field(default_factory=dict)       # item -> the props.pr it holds already

    def as_dict(self) -> dict:
        def prs(xs):
            return [{"pr": p.ref, "title": p.title, "merged": p.day, "fragments": p.fragments} for p in xs]
        return {"version": self.version, "wave": self.wave, "ranges": self.ranges,
                "close": {i: prs(v) for i, v in self.to_close.items()},
                "closed": {i: prs(v) for i, v in self.closed.items()}, "other": self.other,
                "outside": self.outside, "unmapped": prs(self.unmapped), "reverted": self.reverted,
                "stray": self.stray, "waiting": self.waiting, "skipped": self.skipped}


def _bare(title: str) -> str:
    """A title without the ``(#N)`` a squash merge appends."""
    m = SQUASH.match(title)
    return m.group("title") if m else title


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
    """The default branch as last fetched: origin/HEAD's target, else origin/main or origin/master, else HEAD."""
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
    """A changelog fragment: a Markdown file but the README, right under ``changes/`` or ``packages/<name>/changes/``."""
    parts = PurePosixPath(path).parts
    folder_ok = parts[:-1] == ("changes",) or (len(parts) == 4 and parts[0] == "packages"
                                               and parts[2] == "changes")
    return folder_ok and parts[-1].endswith(".md") and parts[-1].lower() != "readme.md"


def fragment_item(path: str, ids: set[str]) -> str:
    """The item a fragment names: its name, or ``<item>-<suffix>`` (:data:`SUFFIX`); '' for none."""
    stem = PurePosixPath(path).stem
    if stem in ids:
        return stem
    head, _, tail = stem.rpartition("-")
    return head if head in ids and SUFFIX.match(tail) else ""


def items_of(pr: MergedPR, ids: set[str]) -> tuple[list[str], list[str]]:
    """(the items a PR delivers, its fragments that name none): each fragment's item, then the ids its title names
    (any case); in that order, once each. A revert delivers nothing."""
    if pr.reverts:
        return [], []
    found, stray = [], []
    for f in pr.fragments:
        hit = fragment_item(f, ids)
        (found if hit else stray).append(hit or f)
    lower = {i.lower(): i for i in ids}
    found += [lower[t.lower()] for t in TOKEN.findall(pr.title) if t.lower() in lower]
    return list(dict.fromkeys(found)), stray


def _reverted(prs: list[MergedPR]) -> dict[int, MergedPR]:
    """id(a reverted PR) -> the revert: the latest earlier PR of the same repo whose title the revert names."""
    out = {}
    for i, pr in enumerate(prs):
        if not pr.reverts:
            continue
        hit = next((p for p in reversed(prs[:i]) if p.repo == pr.repo and _bare(p.title) == pr.reverts
                    and id(p) not in out), None)
        if hit is not None:
            out[id(hit)] = pr
    return out


def plan(store: Path, repos: list[tuple[str, Path]], version: str, since: str = "", until: str = "",
         root: Path | None = None) -> Plan:
    """What close-merged does for the wave ``version`` (its release or its id) over ``repos`` ((name, checkout))."""
    wp = waves.load(store, root)
    wid = wp.resolve(version)
    if wid is None:
        raise CloseError(f"{version}: no wave of that release (brain wave add {version})")
    out = Plan(wp.label(wid), wid)
    _read(out, repos, since, until)
    nodes = {k: n for k, n in wp.nodes.items() if n.get("type") == "WorkItem"}
    _map(out, wp, set(nodes))
    members = set(wp.items_of(wid))
    out.outside = sorted(i for i in out.to_close if i not in members)
    out.waiting = [i for i in wp.items_of(wid) if wp.status(i) in waves.OPEN and i not in out.to_close]
    out.earlier = {i: str((nodes[i].get("props") or {}).get("pr") or "") for i in out.to_close
                   if (nodes[i].get("props") or {}).get("pr")}
    return out


def _read(out: Plan, repos: list[tuple[str, Path]], since: str, until: str) -> None:
    """Each repo's merged PRs into ``out.prs``, its range into ``out.ranges``, or why it was not read."""
    for name, path in repos:
        try:
            start, end = span(path, out.version, since, until)
            out.prs += merged_prs(path, name, start, end)
            day = _git(path, "log", "-1", "--format=%cs", start).strip()
        except CloseError as exc:
            out.skipped[name] = str(exc)
            continue
        out.ranges[name] = f"{start} ({day})..{end}"


def _map(out: Plan, wp: waves.Plan, ids: set[str]) -> None:
    """Each PR's items sorted by their status, a reverted PR left out, what names nothing listed."""
    gone = _reverted(out.prs)
    reverts = {id(r) for r in gone.values()}
    for pr in out.prs:
        if id(pr) in gone:
            out.reverted[pr.ref] = gone[id(pr)].ref
            continue
        hits, stray = items_of(pr, ids)
        out.stray += [f"{pr.ref}: {f}" for f in stray]
        if not hits and id(pr) not in reverts:   # a revert of a PR not in the range is said
            out.unmapped.append(pr)
        for i in hits:
            _place(out, i, wp.status(i), pr)


def _place(out: Plan, item: str, status: str, pr: MergedPR) -> None:
    if status in waves.OPEN:
        out.to_close.setdefault(item, []).append(pr)
    elif status in CLOSED:
        out.closed.setdefault(item, []).append(pr)
    else:
        out.other[item] = status or "no status"


def outcome(prs: list[MergedPR]) -> str:
    return "; ".join(dict.fromkeys(p.title for p in prs if p.title))


def refs(p: Plan, item: str) -> str:
    """props.pr for ``item``: the refs it holds already (an earlier PR of it), then its merged PRs', once each."""
    have = [x.strip() for x in p.earlier.get(item, "").split(",") if x.strip()]
    return ", ".join(dict.fromkeys([*have, *(x.ref for x in p.to_close[item])]))


def write(store: Path, p: Plan, done: list[str]) -> None:
    """Each item of ``p.to_close`` closed done with its PRs, the outcome from their titles, dated by the last merge;
    ``done`` gets each id as it is written (what a failure part way left written)."""
    for item, prs in p.to_close.items():
        graph.close_item(store, item, refs(p, item), outcome(prs), today=max(x.day for x in prs))
        done.append(item)


def render(p: Plan, written: bool) -> list[str]:
    lines = [f"wave {p.version} ({p.wave}): {len(p.prs)} merged PR(s) read"]
    lines += [f"  {repo}: {rng}" for repo, rng in p.ranges.items()]
    lines += [f"  {repo}: not read: {why}" for repo, why in p.skipped.items()]
    verb = "closed" if written else "to close"
    for item in p.to_close:
        where = " (not in this wave)" if item in p.outside else ""
        lines.append(f"{verb}: {item}{where} --pr \"{refs(p, item)}\" --outcome \"{outcome(p.to_close[item])}\"")
    for item, prs in p.closed.items():
        lines.append(f"already closed: {item} ({', '.join(x.ref for x in prs)})")
    for item, status in p.other.items():
        lines.append(f"left as it is: {item} ({status})")
    for pr, by in p.reverted.items():
        lines.append(f"reverted: {pr} by {by}: its items left out")
    for pr in p.unmapped:
        lines.append(f"names no item: {pr.ref} {pr.title}")
    for f in p.stray:
        lines.append(f"fragment names no item: {f}")
    for item in p.waiting:
        lines.append(f"no merged PR: {item} (still to merge, or brain wave close {p.version} --carry-to)")
    tail = "written; then brain sync and brain check" if written else "not written: --write"
    lines.append(f"close-merged {p.version}: {len(p.to_close)} item(s) {verb}, {len(p.closed)} already closed, "
                 f"{len(p.waiting)} with no merged PR; {tail}")
    return lines
