"""``brain merge-check``: after a merge of main into a branch, check against a fresh main that the resolution lost
nothing, at zero token (wi-brain-merge-stale-main; the lesson les-brain-merge-stale-main: a resolution made against
a stale local main dropped a just-merged PR's item and journal line, #185 against #194).

It fetches a remote base again (``origin/main``; ``--no-fetch``: as last fetched; a local branch is used as it is),
then compares three sides: the base (main), the branch before the merge (ours: the newest merge's first parent, or
HEAD while a merge is not committed yet) and their merge base, against the result (HEAD, or the working tree with
``--worktree``). What main brought since the merge base must be in the result:

- **behind**: the base is not in the result's history (not in HEAD, nor in MERGE_HEAD while a merge is uncommitted):
  merge it again first;
- **lost**: in the files that only grow (the journals, the decision logs, the graph's curated edge files, the
  CHANGELOGs), each line main added that the result lacks, compared as content (a multiset of lines), so a line the
  merge driver moved (a reordered edge, a CHANGELOG section) is not lost; in a curated node file, each field or prop
  main changed on a node whose value the result does not keep (the branch's own change to the same field shows here
  too: check it by eye);
- **lost ids**: a node main has that the result lacks, unless the branch removed it on purpose (it was in the merge
  base and is not in ours).

The files are the registered project's stores (``nodes/*.yaml`` and ``edges/*.yaml``, the generated ones left out),
its journals and decision logs and every ``CHANGELOG*.md``, in the base or in the result (a whole file the resolution
dropped counts); ``--path`` adds others. Exit 1 when the branch is behind or lost something, 2 on a git error.
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


def _files(repo: Path, rev: str) -> set[str]:
    return set(git(repo, "ls-tree", "-r", "-z", "--name-only", rev).split("\0")) - {""} if rev else set()


def watched(repo: Path, project: projects.Project | None, extra: list[str] | None = None,
            revs: tuple[str, ...] = ()) -> dict[str, str]:
    """Path (repo-relative, posix) -> kind: append (journals, decision logs, edge files, CHANGELOGs) or nodes (a
    store's curated node files), among the index's files and those of ``revs`` (the base: a file the resolution
    dropped)."""
    tracked = set(git(repo, "ls-files", "-z").split("\0")) - {""}
    for rev in revs:
        tracked |= _files(repo, rev)
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


def _show(repo: Path, rev: str, path: str) -> str:
    try:
        return git(repo, "show", f"{rev}:{path}") if rev else ""
    except AuditError:
        return ""


def _rev(repo: Path, ref: str) -> str:
    return git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", allow=(0, 1)).strip()


def _contains(repo: Path, ancestor: str, rev: str) -> bool:
    return bool(rev) and git(repo, "merge-base", ancestor, rev, allow=(0, 1)).strip() == ancestor


def sides(repo: Path, base_sha: str, worktree: bool, head: str = "HEAD") -> dict[str, str]:
    """{"ours": the branch before the merge, "mb": its merge base with the base, "merge": MERGE_HEAD or ''}: while a
    merge is uncommitted, ours is HEAD; else the newest merge commit since the base's history (its first parent), else
    ``head`` (no merge: nothing of main to lose)."""
    merge = _rev(repo, "MERGE_HEAD") if worktree else ""
    ours = head
    if not merge:
        merges = git(repo, "rev-list", "--first-parent", "--merges", "-n", "50", head, f"^{base_sha}").split()
        brought = [m for m in merges if not _contains(repo, base_sha, _rev(repo, f"{m}^1"))]
        ours = f"{brought[0]}^1" if brought else head   # the merge that brought the base in
    ours_sha = _rev(repo, ours)
    mb = git(repo, "merge-base", ours_sha, base_sha, allow=(0, 1)).strip()
    return {"ours": ours_sha, "mb": mb, "merge": merge}


def _mine(repo: Path, path: str, worktree: bool, head: str = "HEAD") -> str:
    if worktree:
        return (repo / path).read_text(encoding="utf-8") if (repo / path).is_file() else ""
    return _show(repo, head, path)


def _nodes(text: str) -> dict[str, dict]:
    """id -> the node's fields flattened (status, title, props.<k>...), from a node file's text."""
    try:
        data = graph.load_yaml(text) if text else []
    except yaml.YAMLError:
        return {m.group(1): {} for m in (_ID.match(ln) for ln in text.splitlines()) if m}
    out = {}
    for n in data if isinstance(data, list) else []:
        if isinstance(n, dict) and n.get("id"):
            flat = {k: v for k, v in n.items() if k not in ("id", "props")}
            flat.update({f"props.{k}": v for k, v in (n.get("props") or {}).items()})
            out[str(n["id"])] = flat
    return out


def lost_lines(base: str, mb: str, result: str) -> list[tuple[int, str]]:
    """(base line number, text) of each line main added since the merge base (base's lines less the merge base's,
    as a multiset) that the result lacks."""
    want = Counter(base.splitlines()) - Counter(mb.splitlines())
    missing = want - Counter(result.splitlines())
    out = []
    for n, line in enumerate(base.splitlines(), 1):
        if missing[line] > 0:
            missing[line] -= 1
            out.append((n, line))
    return out


def lost_nodes(base: str, mb: str, ours: str, result: str) -> tuple[list[tuple[str, str, object]], list[str]]:
    """(id, field, main's value) of each field main changed on a node that the result does not keep, and the ids of
    the nodes main has that the result lacks, unless the branch removed them (in the merge base, not in ours)."""
    b, m, o, r = _nodes(base), _nodes(mb), _nodes(ours), _nodes(result)
    changed, gone = [], []
    for nid, fields in b.items():
        if nid not in r:
            if nid not in m or nid in o:
                gone.append(nid)
            continue
        old = m.get(nid, {})
        changed += [(nid, k, v) for k, v in fields.items() if old.get(k) != v and r[nid].get(k) != v]
    return changed, sorted(gone)


def check(repo: Path, project: projects.Project | None = None, base: str = "", fetch: bool = True,
          worktree: bool = False, extra: list[str] | None = None, head: str = "HEAD") -> dict:
    """The check of ``head`` (a commit of the repo, HEAD by default: brain merge-ready passes a PR's head) against a
    fresh ``base``."""
    base = base or default_base(repo)
    remotes = set(git(repo, "remote").split())
    if fetch and base.split("/", 1)[0] in remotes and "/" in base:
        git(repo, "fetch", "--quiet", base.split("/", 1)[0])
    base_sha = git(repo, "rev-parse", "--verify", f"{base}^{{commit}}").strip()
    s = sides(repo, base_sha, worktree, head)
    behind = not (_contains(repo, base_sha, _rev(repo, head)) or _contains(repo, base_sha, s["merge"]))
    files = watched(repo, project, extra, revs=(base_sha, head))
    out = {"base": base, "base_sha": base_sha, "behind": behind, "files": len(files), "lost": [], "lost_ids": [],
           "merge_base": s["mb"]}
    if behind or not files or not s["mb"]:
        return out
    for path, kind in sorted(files.items()):
        texts = [_show(repo, base_sha, path), _show(repo, s["mb"], path)]
        if texts[0] == texts[1]:
            continue  # main did not change it since the merge base
        result = _mine(repo, path, worktree, head)
        if kind == "append":
            out["lost"] += [{"path": path, "line": n, "text": t} for n, t in lost_lines(*texts, result)]
            continue
        changed, gone = lost_nodes(*texts, _show(repo, s["ours"], path), result)
        out["lost"] += [{"path": path, "line": 0, "text": f"{nid} {k}: {v}"} for nid, k, v in changed]
        out["lost_ids"] += [{"path": path, "id": nid} for nid in gone]
    return out


def failed(r: dict) -> bool:
    return r["behind"] or bool(r["lost"]) or bool(r["lost_ids"])


def render(r: dict) -> list[str]:
    head = f"merge-check against {r['base']} ({r['base_sha'][:8]}), {r['files']} file(s) watched"
    if r["behind"]:
        return [head, f"behind: {r['base']} is not merged into this branch; git merge {r['base']}, resolve, then run "
                      "brain merge-check again"]
    lines = [head + f": {len(r['lost'])} of main's line(s) or node change(s) lost, {len(r['lost_ids'])} node id(s) "
                    "lost"]
    lines += [f"  lost id  {x['path']}: {x['id']}" for x in r["lost_ids"]]
    lines += [f"  lost     {x['path']}" + (f":{x['line']}" if x["line"] else "") + f": {str(x['text'])[:100]}"
              for x in r["lost"][:40]]
    if len(r["lost"]) > 40:
        lines.append(f"  ... {len(r['lost']) - 40} more")
    if failed(r):
        lines.append(f"put each lost line or value back from {r['base']} (git show {r['base']}:<path>), unless the "
                     "branch changes it on purpose; then run it again")
    else:
        lines.append("ok: nothing main brought since the merge base is lost")
    return lines
