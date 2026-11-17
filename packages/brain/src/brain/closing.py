"""``brain close ITEM --pr "repo #N"``: an item's definition of done in one command, at zero token (the shipping
process's third step: what a session ran by hand after each merge, item close, journal, features set, the fragment's
check, the milestones, tidy).

From the merged PR (``gh pr view``: its title, body, merge date, head branch and files) and the graph:

- the item closed done with the PR (after the refs its ``props.pr`` holds already) and the merge's date, its outcome
  the PR's title unless ``--outcome``; an item already closed is left as it is;
- a journal line, :func:`brain.graph.close_line`'s, at the end of today's entry (a new entry when today has none);
- the features the PR's title or body names with a status (``feat-x: have``, brain.features.named; a feature's
  ``public_id`` names it too), set as ``brain features sync-prs`` sets them: its status, ``status_pr`` and
  ``status_merged``, a PR already applied (its merge not after ``status_merged``) left out;
- its changelog fragment checked: a fragment the PR carries (brain.closemerged.is_fragment) named after the item
  (``<item>.md``, ``<item>-<section>.md``); none is said, never refused;
- the milestones it moves checked: each milestone the item is ``part_of`` with no open member left is listed with its
  trigger, for a judgement (a trigger is prose: reaching it stays a ``brain item set``);
- its worktree and branch removed by brain tidy's own plan, narrowed to the PR's head branch (never an unmerged branch,
  a dirty worktree or one an open session holds).

The plan first; ``--write`` applies it, refused while the PR is not merged or the item is unknown.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import closemerged, features, graph, milestones, notes, tidy

REF = re.compile(r"^\s*(?:(?P<repo>[\w.-]+)\s+)?#?(?P<n>\d+)\s*$")
OPEN = ("todo", "doing", "blocked", "pending")   # an open member keeps its milestone from being reached
FIELDS = "number,title,body,state,mergedAt,headRefName,files"


class CloseError(RuntimeError):
    """The PR could not be read, or its reference is not one."""


@dataclass
class PR:
    repo: str
    number: int
    title: str = ""
    body: str = ""
    state: str = ""          # OPEN, CLOSED, MERGED (gh's)
    merged_at: str = ""      # ISO timestamp, '' when not merged
    head: str = ""           # its head branch
    files: list[str] = field(default_factory=list)

    @property
    def ref(self) -> str:
        return f"{self.repo} #{self.number}"

    @property
    def day(self) -> str:
        return self.merged_at[:10]


@dataclass
class Milestone:
    id: str
    title: str
    trigger: str
    open: list[str]          # its members still open once the item is closed


@dataclass
class Plan:
    item: str
    status: str              # the item's status before the close ('' when unknown)
    pr: PR
    refs: str = ""           # props.pr once closed
    outcome: str = ""
    line: str = ""           # the journal's line
    features: list[tuple[str, str, str]] = field(default_factory=list)   # (feature, its status, the new one)
    features_done: list[str] = field(default_factory=list)   # named, already applied
    features_unknown: list[str] = field(default_factory=list)   # named, not a feature
    fragments: list[str] = field(default_factory=list)       # the PR's fragments named after the item
    other_fragments: list[str] = field(default_factory=list)
    milestones: list[Milestone] = field(default_factory=list)
    tidy: tidy.RepoPlan | None = None
    tidy_note: str = ""
    problems: list[str] = field(default_factory=list)        # what refuses --write

    @property
    def closes(self) -> bool:
        return self.status in OPEN

    def as_dict(self) -> dict:
        steps = [{"kind": s.kind, "target": s.target, "remove": s.remove, "why": s.why}
                 for s in (self.tidy.steps if self.tidy else [])]
        return {"item": self.item, "status": self.status, "close": self.closes,
                "pr": {"ref": self.pr.ref, "title": self.pr.title, "state": self.pr.state,
                       "merged": self.pr.merged_at, "head": self.pr.head},
                "refs": self.refs, "outcome": self.outcome, "journal": self.line,
                "features": [{"id": f, "from": old, "to": new} for f, old, new in self.features],
                "features_applied": self.features_done, "features_unknown": self.features_unknown,
                "fragments": self.fragments, "other_fragments": self.other_fragments,
                "milestones": [{"id": m.id, "title": m.title, "trigger": m.trigger, "open": m.open}
                               for m in self.milestones],
                "tidy": steps, "tidy_note": self.tidy_note, "problems": self.problems}


def parse_ref(text: str, repo: str = "") -> tuple[str, int]:
    """(repo, number) from ``"repo #N"``, ``"#N"`` or ``"N"``; the repo given apart when the text names none."""
    m = REF.match(text or "")
    if not m:
        raise CloseError(f"--pr {text!r}: \"repo #N\" or N")
    return (m.group("repo") or repo), int(m.group("n"))


def fetch_pr(repo_dir: Path, number: int) -> dict:
    """The PR as ``gh pr view N --json`` gives it, run in the repo's checkout (gh finds its remote)."""
    cmd = ["gh", "pr", "view", str(number), "--json", FIELDS]
    try:
        r = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=60, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CloseError(f"gh pr view {number}: {exc}") from exc
    if r.returncode:
        raise CloseError(f"gh pr view {number} in {repo_dir}: {r.stderr.strip() or r.returncode}")
    try:
        data = json.loads(r.stdout or "{}")
    except ValueError as exc:
        raise CloseError(f"gh pr view {number}: not JSON") from exc
    if not isinstance(data, dict):
        raise CloseError(f"gh pr view {number}: not a PR")
    return data


def read_pr(repo: str, repo_dir: Path, number: int, fetch=None) -> PR:
    data = (fetch or fetch_pr)(repo_dir, number)
    files = [str(f.get("path") if isinstance(f, dict) else f) for f in data.get("files") or []]
    return PR(repo, int(data.get("number") or number), str(data.get("title") or ""), str(data.get("body") or ""),
              str(data.get("state") or "").upper(), str(data.get("mergedAt") or ""), str(data.get("headRefName") or ""),
              [f for f in files if f])


def plan(store: Path, item: str, pr: PR, repo_dir: Path | None, *, outcome: str = "",
         do_tidy: bool = True) -> Plan:
    """What ``brain close`` does for ``item`` closed by ``pr`` (merged), the graph at ``store``."""
    index = graph.node_index(store, generated=False)
    node = index.get(item, (None, {}))[1] or {}
    p = Plan(item, str(node.get("status") or ""), pr)
    p.problems = _problems(item, node, pr)
    props = node.get("props") or {}
    have = [x.strip() for x in str(props.get("pr") or "").split(",") if x.strip()]
    p.refs = ", ".join(dict.fromkeys([*have, pr.ref]))
    p.outcome = " ".join((outcome or pr.title).split())
    closed = {**node, "status": "done", "props": {**props, "pr": p.refs, "done": f"{pr.day} {p.outcome}".strip()}}
    p.line = graph.close_line(closed if p.closes else node)
    _features(p, index)
    _fragments(p)
    _milestones(p, store)
    if do_tidy and repo_dir is not None:
        _tidy(p, repo_dir)
    elif do_tidy:
        p.tidy_note = f"no checkout of {pr.repo} here: nothing to tidy"
    return p


def _problems(item: str, node: dict, pr: PR) -> list[str]:
    """What refuses --write: an unknown item, a node that is no WorkItem, a PR not merged."""
    out = []
    if not node:
        out.append(f"{item}: unknown node")
    elif node.get("type") not in (None, "WorkItem"):
        out.append(f"{item}: a {node.get('type')}, not a WorkItem")
    if pr.state != "MERGED" or not pr.merged_at:
        out.append(f"{pr.ref} is not merged ({pr.state.lower() or 'state unknown'}): close it after the merge")
    return out


def _features(p: Plan, index: dict) -> None:
    feats = {nid: n for nid, (_, n) in index.items() if n.get("type") == features.TYPE}
    alias = {str((n.get("props") or {}).get(features.PUBLIC_ID) or ""): nid for nid, n in feats.items()}
    alias.pop("", None)
    seen = set()
    for named, status in features.named(f"{p.pr.title}\n{p.pr.body}"):
        fid = named if named in feats else alias.get(named, "")
        if not fid:
            p.features_unknown.append(named)
            continue
        if fid in seen:
            continue
        seen.add(fid)
        props = feats[fid].get("props") or {}
        if p.pr.merged_at and p.pr.merged_at <= str(props.get("status_merged") or ""):
            p.features_done.append(fid)
        else:
            p.features.append((fid, str(feats[fid].get("status") or ""), status))


def _fragments(p: Plan) -> None:
    for f in (x for x in p.pr.files if closemerged.is_fragment(x)):
        (p.fragments if closemerged.fragment_item(f, {p.item}) else p.other_fragments).append(f)


def _milestones(p: Plan, store: Path) -> None:
    """Each milestone the item is part_of, with its members still open once the item is closed."""
    nodes, edges = milestones.load(store)
    members: dict[str, list[str]] = {}
    for e in edges:
        if e.get("type") == "part_of" and (nodes.get(str(e.get("to"))) or {}).get("type") == "Milestone":
            members.setdefault(str(e.get("to")), []).append(str(e.get("from")))
    for mid, ids in members.items():
        node = nodes[mid]
        if p.item not in ids or node.get("status") in ("reached", "dropped"):
            continue
        left = sorted(i for i in dict.fromkeys(ids) if i != p.item and (nodes.get(i) or {}).get("status") in OPEN)
        trigger = " ".join(str((node.get("props") or {}).get("trigger") or "").split())
        p.milestones.append(Milestone(mid, str(node.get("title") or ""), trigger, left))


def _tidy(p: Plan, repo_dir: Path) -> None:
    """brain tidy's plan of the PR's repo, narrowed to its head branch and the worktrees that hold it."""
    if not p.pr.head:
        p.tidy_note = "the PR names no head branch: nothing to tidy"
        return
    try:
        rp = tidy.plan_repo("", p.pr.repo, repo_dir, False, state=[])
        holders = {tidy._norm(w.path) for w in tidy.worktrees(repo_dir) if w.branch == p.pr.head and not w.main}
    except (OSError, subprocess.SubprocessError) as exc:
        p.tidy_note = f"tidy: {exc}"
        return
    if rp.error:
        p.tidy_note = f"tidy: {rp.error}"
        return
    rp.steps = [s for s in rp.steps if (s.kind == "branch" and s.target == p.pr.head)
                or (s.kind == "worktree" and tidy._norm(s.target) in holders)]
    p.tidy = rp
    if not rp.steps:
        here = tidy._git_ok(repo_dir, "rev-parse", "--verify", "--quiet", f"refs/heads/{p.pr.head}")
        p.tidy_note = (f"{p.pr.head} is not merged into {rp.default} as git sees it here (a squash or rebase merge, or "
                       f"the default branch not fetched): kept, brain tidy decides later" if here and not holders
                       else f"no local branch {p.pr.head} nor worktree on it: nothing to tidy" if not here
                       else f"the worktrees on {p.pr.head} stay (see brain tidy): nothing removed")


def write(store: Path, journal: Path, p: Plan, today: str | None = None, title: str = "") -> list[str]:
    """Apply the plan: the item closed, the features set, the journal's line, then tidy. One line each. The journal is
    checked first: a close it could not historise would leave a re-run nothing to finish."""
    out: list[str] = []
    day = today or date.today().isoformat()
    if p.closes and not journal.is_file():
        raise notes.NotesError(f"{journal}: no journal here: nothing written")
    if p.closes:
        graph.close_item(store, p.item, p.refs, p.outcome, today=p.pr.day)
        out.append(f"closed: {p.item} --pr \"{p.refs}\" ({p.pr.day})")
    for fid, _, status in p.features:
        features.set_feature(store, fid, [f"status={status}", f"status_pr={p.pr.ref}",
                                          f"status_merged={p.pr.merged_at}"])
        out.append(f"feature: {fid} {status} ({p.pr.ref})")
    if p.closes:
        new = notes.last_day(notes.read(journal)[0]) != day
        notes.journal_add(journal, [p.line], title=(title or f"{p.item} closed") if new else "", day=day)
        out.append(f"journal: {p.line}")
    if p.tidy is not None and p.tidy.steps:
        out += [f"tidy: {x}" for x in tidy.apply_repo(p.tidy)]
    return out


def _plan_lines(p: Plan) -> list[str]:
    """What --write would do: the close and its journal line, the features, tidy's steps."""
    lines = []
    if p.closes:
        lines.append(f"to close: {p.item} --pr \"{p.refs}\" --outcome \"{p.outcome}\" ({p.pr.day or 'not merged'})")
        lines.append(f"journal: {p.line}")
    elif p.status:
        lines.append(f"already {p.status}: {p.item} (left as it is; no journal line)")
    lines += [f"feature: {f} {old} -> {new}" for f, old, new in p.features]
    if p.tidy is not None:
        lines += [f"tidy: {'remove' if s.remove else 'keep'} {s.kind} {s.target} ({s.why})" for s in p.tidy.steps]
    return lines


def _fragment_line(p: Plan) -> str:
    if p.fragments:
        return f"fragment: {', '.join(p.fragments)}"
    carries = f" (it carries {', '.join(p.other_fragments)})" if p.other_fragments else ""
    return f"fragment: none of the PR's names {p.item}{carries}"


def _milestone_line(p: Plan, m: Milestone) -> str:
    if m.open:
        more = ", ..." if len(m.open) > 5 else ""
        return f"milestone {m.id}: {len(m.open)} open left ({', '.join(m.open[:5])}{more})"
    return (f"milestone {m.id}: no open item left; its trigger: « {m.trigger or 'none written'} »; when met: brain "
            f"item set {m.id} status=reached reached=\"{p.pr.day or date.today()} <evidence>\"")


def render(p: Plan, written: list[str] | None = None) -> list[str]:
    lines = [f"close {p.item} by {p.pr.ref}: {p.pr.title}" + (f" (merged {p.pr.day})" if p.pr.day else "")]
    lines += [f"refused: {x}" for x in p.problems]
    lines += written if written is not None else _plan_lines(p)
    lines += [f"feature already applied: {f}" for f in p.features_done]
    lines += [f"feature named, unknown: {f}" for f in p.features_unknown]
    lines.append(_fragment_line(p))
    lines += [_milestone_line(p, m) for m in p.milestones]
    lines += [p.tidy_note] if p.tidy_note else []
    tail = ("written; then brain sync and brain check" if written is not None
            else "not written: --write" if not p.problems else "nothing written")
    lines.append(f"close {p.item}: {tail}")
    return lines
