"""``brain merge-check``: after a merge of main into a branch, check against a fresh main that the resolution lost
nothing, at zero token (wi-brain-merge-stale-main; the lesson les-brain-merge-stale-main: a resolution made against
a stale local main dropped a just-merged PR's item and journal line, #185 against #194).

It fetches the base's remote (``--no-fetch``: as last fetched), then:

- **behind**: the base is not in the branch's history (main moved since the merge): merge it again first;
- **lost**: each line the base has and the branch does not, in the files that are written by hand and only grow (the
  journals, the decision logs, the graph's curated edge files, a CHANGELOG), and each line removed from a curated
  node file in a hunk that adds nothing back (a node's block taken out whole);
- **lost ids**: each node id of the base's curated node files missing from the branch's.

A line the branch changes in place (a closed item's last line, a prop added) is removed in a hunk that also adds
lines: counted as changed, never lost. A line one of the branch's own commits removes (base..HEAD, merges left out:
brain item unlink, an edit) is removed on purpose; only what the merge's resolution dropped is lost. The files are the registered project's stores (``nodes/*.yaml`` and
``edges/*.yaml``, the generated ones left out), journals and decision logs, and every tracked ``CHANGELOG*.md``;
``--path`` adds others. The branch is HEAD, or the working tree with ``--worktree`` (a resolution not committed yet).
Exit 1 when the branch is behind or lost something, 2 on a git error.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import yaml

from . import graph, projects
from .inventory import AuditError, git

GENERATED = "_generated_"
_ID = re.compile(r"^-\s*\{\s*id:\s*\"?([^\",}\s]+)")


def default_base(repo: Path) -> str:
    """origin's default branch (refs/remotes/origin/HEAD), else origin/main."""
    try:
        ref = git(repo, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD").strip()
    except AuditError:
        ref = ""
    return ref.removeprefix("refs/remotes/") or "origin/main"


def watched(repo: Path, project: projects.Project | None, extra: list[str] | None = None) -> dict[str, str]:
    """Tracked path (repo-relative, posix) -> kind: append (journals, decision logs, edge files, CHANGELOGs) or nodes
    (a store's curated node files)."""
    tracked = set(git(repo, "ls-files", "-z").split("\0")) - {""}
    out: dict[str, str] = {}
    for store in (project.stores if project else []):
        s = _rel(repo, store)
        if s is not None:
            out.update(_store_files(tracked, s))
    logs = [_rel(repo, p) for p in [*(project.journals if project else []), *(project.decision_logs if project else [])]]
    out.update({r: "append" for r in logs if r in tracked})
    out.update({t: "append" for t in tracked if re.fullmatch(r"(?:.*/)?CHANGELOG[^/]*\.md", t)})
    out.update({p.replace("\\", "/"): "append" for p in extra or []})
    return out


def _rel(repo: Path, p: Path) -> str | None:
    try:
        return p.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return None


def _store_files(tracked: set[str], s: str) -> dict[str, str]:
    """A store's curated files: its nodes (kind nodes) and edges (append), the generated ones left out."""
    out = {}
    for t in tracked:
        if not t.endswith(".yaml") or t.rsplit("/", 1)[-1].startswith(GENERATED):
            continue
        if t.startswith(f"{s}/nodes/"):
            out[t] = "nodes"
        elif t.startswith(f"{s}/edges/") or t == f"{s}/edges.yaml":
            out[t] = "append"
    return out


def hunks(diff: str) -> list[dict]:
    """The hunks of a unified diff (-U0): path, the old start line, removed and added lines."""
    out, path = [], ""
    for raw in diff.splitlines():
        if raw.startswith("--- "):
            continue
        if raw.startswith("+++ "):
            path = raw[4:].strip('"')
            path = path[2:] if path.startswith("b/") else path
        elif raw.startswith("@@"):
            m = re.search(r"-(\d+)", raw)
            out.append({"path": path, "line": int(m.group(1)) if m else 0, "removed": [], "added": []})
        elif out and raw[:1] == "-":
            out[-1]["removed"].append(raw[1:])
        elif out and raw[:1] == "+":
            out[-1]["added"].append(raw[1:])
    return out


def _ids(text: str) -> list[str]:
    try:
        data = graph.load_yaml(text)
    except yaml.YAMLError:
        return [m.group(1) for m in (_ID.match(ln) for ln in text.splitlines()) if m]
    return [str(n["id"]) for n in data if isinstance(n, dict) and n.get("id")] if isinstance(data, list) else []


def _own_removals(repo: Path, base: str, files: list[str]) -> Counter:
    """(path, line) -> how many times the branch's own commits (base..HEAD, merges left out) remove it: a removal on
    purpose (brain item unlink, an edit), not one the merge's resolution made."""
    log = git(repo, "log", "--no-merges", "--format=", "-p", "-U0", "--no-color", "--no-ext-diff", "--no-renames",
              f"{base}..HEAD", "--", *files)
    return Counter((h["path"], t) for h in hunks(log) for t in h["removed"])


def _show(repo: Path, rev: str, path: str) -> str:
    try:
        return git(repo, "show", f"{rev}:{path}")
    except AuditError:
        return ""


def check(repo: Path, project: projects.Project | None = None, base: str = "", fetch: bool = True,
          worktree: bool = False, extra: list[str] | None = None) -> dict:
    base = base or default_base(repo)
    if fetch and "/" in base:
        git(repo, "fetch", "--quiet", base.split("/", 1)[0])
    base_sha = git(repo, "rev-parse", "--verify", f"{base}^{{commit}}").strip()
    behind = git(repo, "merge-base", base_sha, "HEAD", allow=(0, 1)).strip() != base_sha
    files = watched(repo, project, extra)
    out = {"base": base, "base_sha": base_sha, "behind": behind, "files": len(files), "changed": 0, "lost": [],
           "lost_ids": []}
    if not files:
        return out
    diff = git(repo, "diff", "-U0", "--no-color", "--no-ext-diff", "--no-renames", base_sha,
               *([] if worktree else ["HEAD"]), "--", *sorted(files))
    out["removed"] = 0
    _classify(hunks(diff), files, _own_removals(repo, base_sha, sorted(files)), out)
    for path in sorted(p for p, kind in files.items() if kind == "nodes"):
        gone = set(_ids(_show(repo, base_sha, path))) - set(_ids(_mine(repo, path, worktree)))
        out["lost_ids"] += [{"path": path, "id": i} for i in sorted(gone)]
    return out


def _classify(hs: list[dict], files: dict[str, str], own: Counter, out: dict) -> None:
    """Each removed line of ``hs``: changed in place (a node file's hunk that adds lines back), removed by the
    branch's own commits, else lost."""
    for h in hs:
        if files.get(h["path"], "append") == "nodes" and h["added"]:
            out["changed"] += len(h["removed"])
            continue
        for i, t in enumerate(h["removed"]):
            if own[(h["path"], t)] > 0:
                own[(h["path"], t)] -= 1
                out["removed"] += 1
            else:
                out["lost"].append({"path": h["path"], "line": h["line"] + i, "text": t})


def _mine(repo: Path, path: str, worktree: bool) -> str:
    if worktree:
        return (repo / path).read_text(encoding="utf-8") if (repo / path).is_file() else ""
    return _show(repo, "HEAD", path)


def failed(r: dict) -> bool:
    return r["behind"] or bool(r["lost"]) or bool(r["lost_ids"])


def render(r: dict) -> list[str]:
    head = f"merge-check against {r['base']} ({r['base_sha'][:8]}), {r['files']} file(s) watched"
    if r["behind"]:
        return [head, f"behind: {r['base']} is not merged into this branch; git merge {r['base']}, resolve, then run "
                      "brain merge-check again"]
    lines = [head + f": {r['changed']} line(s) changed in place, {r.get('removed', 0)} removed by the branch's own "
                    f"commits, {len(r['lost'])} lost, {len(r['lost_ids'])} node id(s) lost"]
    lines += [f"  lost id  {x['path']}: {x['id']}" for x in r["lost_ids"]]
    lines += [f"  lost     {x['path']}:{x['line']}: {x['text'][:100]}" for x in r["lost"][:40]]
    if len(r["lost"]) > 40:
        lines.append(f"  ... {len(r['lost']) - 40} more")
    if failed(r):
        lines.append(f"put each lost line back from {r['base']} (git show {r['base']}:<path>), unless the branch "
                     "removes it on purpose; then run it again")
    else:
        lines.append("ok: nothing of the base is lost")
    return lines
