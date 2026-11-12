"""The technical reference as of a wave, a milestone, an era, a date or a git ref (wi-brain-reference-asof;
spec-brain-architecture-docs 5.3; docs/views.md, « The reference as of a point »).

- **The point** (:func:`resolve`): a wave (its id or its release), a milestone or an era is read at the commit of the
  day it was reached (``props.reached``, its first date: the last first-parent commit of that day,
  ``research_graph.history.commit_on``); a date at that day's last commit; anything else is a git ref. A milestone,
  wave or era still pending is read as of now, with its target view.
- **The render**: the store, the DDR records, ``modules.yaml``, ``docs/reference.yaml`` and ``projects.yaml`` as they
  were at that commit, read from git into a temporary folder (``git archive``: nothing checked out, nothing written to
  the repository), then rendered by ``brain.reference`` as today's reference is. It is written under
  ``<BRAIN_HOME>/views/reference/<project>/<point>/``, never into the repo: no frozen copy.
- **« Changes since »** the wave reached before the point: decisions taken and reversed, features whose status
  changed, items done, modules added, from the two stores.
- **The target view** of a pending milestone, wave or era: the features and items planned in it (``part_of``), so the
  as-is and the to-be read side by side.
"""

from __future__ import annotations

import io
import re
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import modules, paths, reference, waves

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
DONE = "done"
GIT_TIMEOUT = 120
# What the render reads beyond the store, relative to the root (a path the commit lacks is left out).
EXTRA = ("records", reference.YAML, "projects.yaml", "config.json")


class AsofError(ValueError):
    """A point the repository cannot be read at."""


@dataclass
class Point:
    """Where the reference is read: its label, the commit, the milestone it names (if any) and whether it is still
    pending (a target view then)."""
    label: str
    sha: str
    day: str = ""
    milestone: str = ""
    pending: bool = False
    nodes: dict = field(default_factory=dict, repr=False)


def _git(top: Path, *args: str, text: bool = True):
    try:
        done = subprocess.run(["git", "-C", str(top), *args], capture_output=True, timeout=GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        raise AsofError(f"git could not run ({exc})") from exc
    if done.returncode:
        raise AsofError(done.stderr.decode("utf-8", "replace").strip() or f"git {args[0]} failed")
    return done.stdout.decode("utf-8", "replace").strip() if text else done.stdout


def _top(store: Path) -> tuple[Path, str]:
    from research_graph import history
    try:
        return history.repo_location(store)
    except history.GitError as exc:
        raise AsofError(str(exc)) from exc


def _commit_on(store: Path, day: str) -> str:
    from research_graph import history
    c = history.commit_on(store, date.fromisoformat(day))
    if c is None:
        raise AsofError(f"no commit on or before {day}")
    return c.sha


def _reached_day(node: dict) -> str:
    m = DATE_RE.search(str((node.get("props") or {}).get("reached") or ""))
    return m.group(1) if m else ""


def resolve(store: Path, ref: str) -> Point:
    """The point ``ref`` names (see the module's docstring); :class:`AsofError` when it names nothing."""
    plan = waves.load(store)
    mid = ref if ref in plan.nodes and plan.nodes[ref].get("type") == "Milestone" else (plan.resolve(ref) or "")
    top, _ = _top(store)
    if mid:
        node = plan.nodes[mid]
        if node.get("status") != "reached":
            return Point(mid, _git(top, "rev-parse", "HEAD"), milestone=mid, pending=True, nodes=plan.nodes)
        day = _reached_day(node)
        if not day:
            raise AsofError(f"{mid} is reached but says not when (props.reached: a date first)")
        return Point(mid, _commit_on(store, day), day, mid, nodes=plan.nodes)
    if DATE_RE.fullmatch(ref):
        return Point(ref, _commit_on(store, ref), ref, nodes=plan.nodes)
    if ref.startswith("-"):
        raise AsofError(f"{ref!r}: a wave, a milestone, an era, a date or a git ref")
    sha = _git(top, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    return Point(ref, sha, _git(top, "show", "-s", "--format=%cs", sha), nodes=plan.nodes)


def previous_wave(point: Point) -> tuple[str, str]:
    """(the wave reached last before ``point``, its day): the « Changes since » base; ("", "") when none."""
    if not point.nodes:
        return "", ""
    plan = waves.Plan(point.nodes)
    cut = point.day or "9999-12-31"
    done = [(d, w) for w in plan.waves if plan.nodes[w].get("status") == "reached" and w != point.milestone
            for d in [_reached_day(plan.nodes[w])] if d and (d < cut or (d == cut and not point.milestone))]
    return (max(done)[1], max(done)[0]) if done else ("", "")


# --- reading the repo at a commit -------------------------------------------------------------------------------------

def materialize(store: Path, sha: str, dest: Path) -> tuple[Path, Path]:
    """The store and what the render reads beside it, as of ``sha``, extracted under ``dest``: (its root, its store).
    The root is the repo's top when the store lives inside it."""
    top, prefix = _top(store)
    want = [p for p in [prefix or ".", *EXTRA] if p]
    present = [p for p in want if _git(top, "ls-tree", "--name-only", sha, "--", p)]
    if not present or (prefix and prefix not in present):
        raise AsofError(f"{prefix or 'the store'} does not exist at {sha[:12]}")
    blob = _git(top, "archive", "--format=tar", sha, "--", *present, text=False)
    with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
        tar.extractall(dest, filter="data")   # no link, device or path outside dest
    store_at = dest / prefix if prefix else dest
    _modules_at(store, top, sha, store_at)
    return dest, store_at


def _modules_at(store: Path, top: Path, sha: str, store_at: Path) -> None:
    """The modules registry as of ``sha`` when the store reads one kept in another store of the repo (config.json
    ``modules.store``): copied beside the extracted store, so the render reads that commit's, not today's."""
    if (store_at / modules.REGISTRY).is_file():
        return
    live = modules.registry_file(store, top)
    if live is None:
        return
    try:
        rel = live.resolve().relative_to(top.resolve()).as_posix()
    except ValueError:   # kept in another repo: its history is not this one's
        return
    try:
        text = _git(top, "show", f"{sha}:{rel}", text=False)
    except AsofError:   # not there yet at that commit: no registry then
        return
    (store_at / modules.REGISTRY).write_bytes(text)


# --- the sections it adds ---------------------------------------------------------------------------------------------

def changes(now: reference.Model, before: reference.Model, since: str) -> list[str]:
    """« Changes since <since> »: decisions taken and reversed, features whose status changed, items done, modules
    added."""
    old_units = {u.id: u for u in before.units}
    taken = sorted((u for u in now.units if u.id not in old_units), key=lambda u: (u.date, u.id), reverse=True)
    reversed_ = sorted(u.id for u in now.units if u.superseded and u.id in old_units and not old_units[u.id].superseded)
    feats = sorted((f, before.nodes.get(f, {}).get("status") or "new", n.get("status")) for f, n in now.nodes.items()
                   if n.get("type") == "Feature" and before.nodes.get(f, {}).get("status") != n.get("status"))
    done = sorted(i for i, n in now.nodes.items() if n.get("type") == "WorkItem" and n.get("status") == DONE
                  and before.nodes.get(i, {}).get("status") != DONE)
    mods = sorted({str(x["id"]) for x in now.registry} - {str(x["id"]) for x in before.registry})
    out = ["", f"## Changes since {since}", ""]
    out += _sub(f"Decisions taken: {len(taken)}", [f"- {reference._unit_line(u)}" for u in taken])
    out += _sub(f"Decisions reversed: {len(reversed_)}", [f"- `{x}`" for x in reversed_])
    out += _sub(f"Features whose status changed: {len(feats)}",
                [f"- `{f}`: {a} → {b} {reference._title(now, f)}".rstrip() for f, a, b in feats])
    out += _sub(f"Items done: {len(done)}", [f"- `{i}` {reference._title(now, i)}".rstrip() for i in done])
    return out + _sub(f"Modules added: {len(mods)}", [f"- `{m}`" for m in mods])


def _sub(title: str, lines: list[str]) -> list[str]:
    return [f"### {title}", ""] + (lines or ["None."]) + [""]


def target(m: reference.Model, mid: str) -> list[str]:
    """The target view of a pending milestone: the items and features planned in it (``part_of``, nested
    milestones followed), the features its items deliver too."""
    members, todo = set(), [mid]
    while todo:
        cur = todo.pop()
        for e in m.edges:
            if e.get("type") == "part_of" and str(e["to"]) == cur and str(e["from"]) not in members:
                members.add(str(e["from"]))
                if m.nodes.get(str(e["from"]), {}).get("type") == "Milestone":
                    todo.append(str(e["from"]))
    items = sorted(x for x in members if m.nodes.get(x, {}).get("type") == "WorkItem")
    feats = {x for x in members if m.nodes.get(x, {}).get("type") == "Feature"}
    feats |= {str(e["to"]) for e in m.edges if e.get("type") == "delivers" and str(e["from"]) in items
              and m.nodes.get(str(e["to"]), {}).get("type") == "Feature"}
    trig = (m.nodes.get(mid, {}).get("props") or {}).get("trigger")
    out = ["", f"## Target: at the end of {mid}", ""]
    out += [f"Reached when: {reference._short(trig, 200)}", ""] if trig else []
    out += _sub(f"Features: {len(feats)}", [f"- `{f}` ({m.nodes[f].get('status')}) {reference._title(m, f)}"
                                           for f in sorted(feats)])
    left = [i for i in items if m.nodes[i].get("status") != DONE]
    return out + _sub(f"Items: {len(items) - len(left)} done, {len(left)} left",
                      [f"- [{'x' if m.nodes[i].get('status') == DONE else ' '}] `{i}` {reference._title(m, i)}"
                       for i in items])


# --- the whole render -------------------------------------------------------------------------------------------------

def render(store: Path, ref: str) -> tuple[Point, dict[str, str]]:
    """(the point, {path: text}) of the reference as of ``ref``: today's render read from git at that commit, its
    README with « Changes since » the wave before and, for a pending milestone, its target view."""
    point = resolve(store, ref)
    with tempfile.TemporaryDirectory(prefix="brain-asof-") as tmp:
        root_at, store_at = materialize(store, point.sha, Path(tmp) / "now")
        files = reference.render(root_at, store_at)
        head = (f"As of `{point.label}`: commit `{point.sha[:12]}`" + (f", {point.day}" if point.day else "")
                + " (brain reference --asof; not the repo's copy).")
        lines = files["README.md"].rstrip("\n").split("\n")
        lines[4:4] = [head, ""]   # under the GENERATED line: the page stays a generated one
        model = reference.load(root_at, store_at)
        since, day = previous_wave(point)
        if since:
            sha = _commit_on(store, day)
            prev_root, prev_store = materialize(store, sha, Path(tmp) / "before")
            lines += changes(model, reference.load(prev_root, prev_store), since)
        if point.pending and point.milestone:
            lines += target(model, point.milestone)
        files["README.md"] = "\n".join(lines).rstrip("\n") + "\n"
    return point, files


def out_dir(project: str, point: Point) -> Path:
    """Where an as-of render is written: ``<BRAIN_HOME>/views/reference/<project>/<point>/``, never the repo."""
    return paths.brain_home() / "views" / "reference" / _safe(project) / _safe(point.label)


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(text)).strip("-.") or "x"
