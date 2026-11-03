"""``brain collisions``: which startable items can start now without touching a file another live branch edits, and
which wait on whom, at zero token (wi-brain-collisions; the scale study's gap 20). The coordinator reads it before a
wave, and ``brain brief`` embeds an item's line.

**What the branches touch.** For each repo of the project (its ``repos:``, each git repository once, as brain tidy
reads them): every linked worktree and every local branch the default branch does not hold, with the files it changes
against the default branch (``git diff --name-only <default>...<branch>``: since their merge base), and for a
worktree its uncommitted changes too (``git status --porcelain``, untracked files included). A main checkout counts
when it is on another branch or has uncommitted changes. The session of a worktree is the desktop app's
(brain.tidy's reading of its leases and session files): live, archived, gone or unknown. A file the merge driver
resolves (``git check-attr merge`` says ``brain``: the views, the logs, the graph's YAML) is listed apart and never
counts as a collision: two branches meet there at no cost (wi-brain-generated-merge).

**What an item will touch** (its predicted surface), from the graph:

- the CodeRefs of the features it ``delivers`` (``implemented_by``), as ``code:<repo>:<path>``;
- its module (``props.module``, ``props.modules_secondary``): the CodeRefs of the features of that module
  (``props.module`` on a Feature);
- the file names its title and props name (``cli.py``, ``install.ps1``, ``adapters/claude/hooks/guard.sh``): a
  branch's file whose path ends with one of them;
- each function of :data:`SURFACE_HOOKS` (``(node, store) -> [(repo or '', path)]``): where wi-brain-touched-surface
  will plug the files that similar finished items touched.

An item whose id (without its ``wi-`` and project prefix) is in a branch's name is on that branch already. An item
with no surface at all is listed apart: it can start, unchecked.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import projects, resume, tidy

FILE_NAME = re.compile(r"(?<![\w/.-])((?:\w[\w.-]*/)*\w[\w-]*\.(?:py|md|ps1|psm1|sh|ya?ml|json|jsonl|toml|txt|ts|js|cfg|ini))"
                       r"(?![\w-])")
GIT_TEMP = ".merge_file_"   # git's temporary files while a merge driver runs
SURFACE_HOOKS: list[Callable[[dict, "resume.Store"], list[tuple[str, str]]]] = []


@dataclass
class Branch:
    project: str
    repo: str                  # the repo's name (its CodeRef token is ``folder``)
    folder: str
    branch: str                # '' for a detached worktree
    worktree: str = ""         # '' when not checked out
    session: str = ""
    state: str = ""            # the app's: live, archived, gone, unknown; '' without a worktree
    files: list[str] = field(default_factory=list)       # changed, repo-relative, the driver's excluded
    shared: list[str] = field(default_factory=list)      # changed, resolved by the merge driver
    uncommitted: int = 0

    @property
    def label(self) -> str:
        return self.branch or f"(detached) {Path(self.worktree).name}"


@dataclass
class Item:
    id: str
    title: str
    priority: str
    paths: list[tuple[str, str]] = field(default_factory=list)   # (repo token, path) from CodeRefs
    names: list[str] = field(default_factory=list)               # file names the item names
    on: list[str] = field(default_factory=list)                  # branches named after it
    waits: list[dict] = field(default_factory=list)              # {branch, repo, worktree, session, state, files}

    @property
    def known(self) -> bool:
        return bool(self.paths or self.names)


@dataclass
class Report:
    projects: list[str]
    generated: str
    branches: list[Branch] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def overlaps(self) -> dict[tuple[str, str], list[Branch]]:
        """(repo, file) -> the branches that change it, two or more."""
        by: dict[tuple[str, str], list[Branch]] = {}
        for b in self.branches:
            for f in b.files:
                by.setdefault((b.repo, f), []).append(b)
        return {k: v for k, v in sorted(by.items()) if len(v) > 1}

    def as_dict(self) -> dict:
        return {"projects": self.projects, "generated": self.generated, "errors": self.errors,
                "branches": [asdict(b) | {"label": b.label} for b in self.branches],
                "overlaps": [{"repo": r, "file": f, "branches": [b.label for b in bs]}
                             for (r, f), bs in self.overlaps().items()],
                "items": [asdict(i) | {"known": i.known} for i in self.items]}


# --- git --------------------------------------------------------------------------------------------------------

def _lines(repo, *args: str) -> list[str]:
    return [x for x in tidy._out(repo, *args).splitlines() if x.strip()]


def _status_paths(worktree: str) -> list[str]:
    out = []
    for line in tidy._out(worktree, "status", "--porcelain", "--untracked-files=all").splitlines():
        if len(line) > 3:
            path = line[3:].split(" -> ")[-1].strip().strip('"')
            out.append(path)
    return out


def _driver_paths(repo, paths: list[str]) -> set[str]:
    """The paths whose merge attribute is the brain driver's."""
    if not paths:
        return set()
    try:
        r = subprocess.run(["git", "-C", str(repo), "check-attr", "--stdin", "merge"],  # bytes: LF on Windows too
                           input="".join(f"{x}\n" for x in paths).encode("utf-8"), capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return set()
    out = set()
    for line in r.stdout.decode("utf-8", "replace").splitlines():
        path, _, rest = line.rpartition(": merge: ")
        if rest.strip() == "brain":
            out.add(path)
    return out


def branches_of(p: projects.Project, state: list | None = None) -> tuple[list[Branch], list[str]]:
    """The open branches and worktrees of ``p``'s repos, with the files each changes."""
    folders = {}
    try:
        folders = {r.name: r.folder for r in projects.repos_of(p)}
    except projects.RepoError:
        pass
    out: list[Branch] = []
    errors: list[str] = []
    state = [] if state is None else state
    for name, path, _prod in tidy._repos(p):
        default, refs = tidy.default_branch(path)
        if not refs:
            errors.append(f"{p.name}/{name}: no default branch (origin/HEAD, main or master)")
            continue
        base = refs[0]
        seen: set[str] = set()
        for wt in tidy.worktrees(path):
            if wt.prunable or not Path(wt.path).is_dir():
                continue
            dirty = _status_paths(wt.path)
            if wt.main and wt.branch == default and not dirty:
                continue
            committed = _lines(path, "diff", "--name-only", f"{base}...{wt.head}") if wt.head else []
            if not state:
                state.append(tidy.app_state())
            known, sid = tidy.session_state(wt.path, state[0])
            out.append(_branch(p.name, name, folders.get(name, Path(path).name), wt.branch, path, committed, dirty,
                               worktree=wt.path, session=sid, state=known))
            if wt.branch:
                seen.add(wt.branch)
        for b in _lines(path, "for-each-ref", f"--no-merged={base}", "--format=%(refname:short)", "refs/heads"):
            if b in seen or b == default:
                continue
            out.append(_branch(p.name, name, folders.get(name, Path(path).name), b, path,
                               _lines(path, "diff", "--name-only", f"{base}...{b}"), []))
    return out, errors


def _branch(project: str, repo: str, folder: str, branch: str, path, committed: list[str], dirty: list[str],
            **kw) -> Branch:
    files = sorted(f for f in set(committed) | set(dirty) if not Path(f).name.startswith(GIT_TEMP))
    shared = _driver_paths(path, files)
    return Branch(project, repo, folder, branch, files=[f for f in files if f not in shared], shared=sorted(shared),
                  uncommitted=len(dirty), **kw)


# --- the items' surface ------------------------------------------------------------------------------------------

def _code(cid: str) -> tuple[str, str] | None:
    parts = cid.split(":", 2)
    if len(parts) != 3 or parts[0] != "code":
        return None
    return parts[1], parts[2].split("::", 1)[0]


def _texts(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [t for v in value.values() for t in _texts(v)]
    if isinstance(value, list):
        return [t for v in value for t in _texts(v)]
    return []


def surface(node: dict, st: resume.Store) -> tuple[list[tuple[str, str]], list[str]]:
    """(the (repo token, path) of its CodeRefs, the file names it names) of an item."""
    props = node.get("props") or {}
    feats = {e["to"] for e in st.edges if e["from"] == node["id"] and e.get("type") == "delivers"
             and (st.nodes.get(e["to"]) or {}).get("type") == "Feature"}
    modules = {str(m) for m in [props.get("module"), *(_texts(props.get("modules_secondary")))]
               if m and str(m).strip() and str(m).strip().lower() != "none"}
    if modules:
        feats |= {n["id"] for n in st.of_type("Feature") if str((n.get("props") or {}).get("module") or "") in modules}
    paths = {c for e in st.edges if e["from"] in feats and e.get("type") == "implemented_by"
             for c in [_code(e["to"])] if c}
    for hook in SURFACE_HOOKS:
        try:
            paths |= set(hook(node, st))
        except Exception:  # noqa: BLE001 - a predictor never breaks the report
            continue
    names = {m.group(1) for t in [node.get("title") or "", *_texts(props)] for m in FILE_NAME.finditer(t)}
    return sorted(paths), sorted(names)


def _named_after(nid: str, project: str, branch: str) -> bool:
    """Whether the branch's last part is the item's id, without ``wi-`` (and its project), or starts with it then a
    dash (claude/tui-update-check-b89f23 for wi-brain-tui-update-check)."""
    tail = branch.rsplit("/", 1)[-1]
    short = nid.removeprefix("wi-")
    return any(c and (tail == c or tail.startswith(c + "-")) for c in {short, short.removeprefix(f"{project}-")})


def _touches(item: Item, b: Branch) -> list[str]:
    hit = []
    for f in b.files:
        if any(repo in ("", b.folder, b.repo) and f == path for repo, path in item.paths):
            hit.append(f)
        elif any(f == n or f.endswith("/" + n) for n in item.names):
            hit.append(f)
    return hit


def items_of(p: projects.Project, branches: list[Branch], frontier: bool = False) -> list[Item]:
    """The startable items of ``p`` (todo, nothing they depend on open; P0/P1 unless ``frontier``), each with its
    surface and the branches it would meet."""
    out: list[Item] = []
    for store in p.stores or [p.root / "notes" / "graph"]:
        if not (store / "schema.yaml").is_file():
            continue
        st = resume.Store.load(store)
        todo = [n for n in st.of_type("WorkItem") if n.get("status") == "todo" and not st.blockers(n["id"])
                and (frontier or resume._priority(n) in resume.PRIORITIES)]
        for n in sorted(todo, key=resume._sort_key):
            paths, names = surface(n, st)
            it = Item(n["id"], str(n.get("title") or ""), resume._priority(n), paths, names)
            for b in branches:
                if b.project != p.name:
                    continue
                if b.branch and _named_after(n["id"], p.name, b.branch):
                    it.on.append(b.label)
                hit = _touches(it, b)
                if hit:
                    it.waits.append({"branch": b.label, "repo": b.repo, "worktree": b.worktree, "session": b.session,
                                     "state": b.state, "files": hit})
            out.append(it)
    return out


def report(projs: list[projects.Project], frontier: bool = False) -> Report:
    rep = Report([p.name for p in projs], datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
    state: list = []
    for p in projs:
        if not p.root.is_dir():
            rep.errors.append(f"{p.name}: {p.root} not found")
            continue
        bs, errs = branches_of(p, state)
        rep.branches += bs
        rep.errors += errs
        rep.items += items_of(p, bs, frontier)
    return rep


def item_line(rep: Report, nid: str) -> list[str]:
    """What brain brief embeds for one item: its surface and whom it waits on."""
    it = next((i for i in rep.items if i.id == nid), None)
    if it is None:
        return [f"{nid} is not a startable item (not todo, or something it depends on is open): no collision read"]
    lines = [f"Predicted surface: {_surface_text(it)}"]
    if it.on:
        lines.append(f"Already on branch(es): {', '.join(it.on)}")
    for w in it.waits:
        lines.append(f"Waits on {w['branch']} ({_who(w)}): {', '.join(w['files'])}")
    if it.known and not it.waits and not it.on:
        lines.append("No live branch touches it: it can start now.")
    return lines


def _surface_text(it: Item) -> str:
    parts = [f"{r}:{p}" if r else p for r, p in it.paths] + it.names
    return ", ".join(parts) if parts else "unknown (no feature CodeRef, module or file named; wi-brain-touched-surface)"


def _who(w: dict) -> str:
    if w.get("session"):
        return f"session {w['session']}, {w['state']}"
    if w.get("worktree"):
        return f"worktree {w['worktree']}, no session known"
    return "a branch without a worktree"


def render(rep: Report) -> list[str]:
    lines = [f"# Collisions — {', '.join(rep.projects)} (zero token, {rep.generated})", ""]
    lines.append(f"## Open branches and worktrees ({len(rep.branches)}), against each repo's default branch")
    lines.append("The files the merge driver resolves (merge=brain: views, logs, graph YAML) are counted apart.")
    quiet = [b for b in rep.branches if not b.files and not b.shared and b.state != "live"]
    for b in rep.branches:
        if b in quiet:
            continue
        where = f"{b.repo} {b.label}"
        who = (f"worktree {b.worktree}, " if b.worktree else "no worktree, ") + (
            f"session {b.session} {b.state}" if b.session else (b.state or "no session") if b.worktree else "")
        extra = f", {b.uncommitted} uncommitted" if b.uncommitted else ""
        shared = f" (+{len(b.shared)} the driver merges)" if b.shared else ""
        files = ", ".join(b.files[:8]) + (f", ... {len(b.files) - 8} more" if len(b.files) > 8 else "")
        lines.append(f"- {where} [{who.rstrip(', ')}]: {len(b.files)} file(s){extra}{shared}"
                     + (f": {files}" if files else ""))
    if quiet:
        lines.append(f"- and {len(quiet)} that change nothing, no live session (brain tidy lists the stale ones): "
                     + ", ".join(b.label for b in quiet))
    ov = rep.overlaps()
    lines += ["", f"## Files two branches change ({len(ov)})"]
    lines += [f"- {r} {f}: {', '.join(b.label for b in bs)}" for (r, f), bs in ov.items()] or ["- none"]
    now = [i for i in rep.items if i.known and not i.waits and not i.on]
    wait = [i for i in rep.items if i.waits or i.on]
    unknown = [i for i in rep.items if not i.known and not i.on]
    lines += ["", f"## Startable items ({len(rep.items)}): {len(now)} can start now, {len(wait)} wait, "
                  f"{len(unknown)} with no known surface"]
    lines.append(f"Can start now ({len(now)}):")
    lines += [f"- {i.id} [{i.priority or '-'}]: {_surface_text(i)}" for i in now] or ["- none"]
    lines.append(f"Wait ({len(wait)}):")
    for i in wait:
        why = [f"on {', '.join(i.on)}"] if i.on else []
        why += [f"{', '.join(w['files'])} with {w['branch']} ({_who(w)})" for w in i.waits]
        lines.append(f"- {i.id} [{i.priority or '-'}]: " + "; ".join(why))
    lines.append(f"No known surface ({len(unknown)}): they can start, unchecked")
    lines += [f"- {', '.join(i.id for i in unknown)}"] if unknown else ["- none"]
    if rep.errors:
        lines += ["", "## Not read"] + [f"- {e}" for e in rep.errors]
    return lines
