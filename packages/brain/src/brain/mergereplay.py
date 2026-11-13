"""``brain merge-driver replay``: a repo's past merges merged again with ``git merge-tree`` (nothing checked out, the
working tree untouched), once as text and once with the driver (brain.mergedriver), and the conflicted files of each
counted (docs/merge-driver.md, « Checking it on a repo's history »)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from .mergedriver import ATTRIBUTES, NAME, NO_MARK, DriverError, _decode, _git

def _merge_tree(repo: Path, ours: str, theirs: str, driver: str, attrs: Path, env: dict) -> tuple[str, list[str]]:
    """(the merged tree, the conflicted paths) of ``git merge-tree`` with that driver for merge=brain. Git runs from
    the scratch folder ``attrs`` sits in, the repo named by GIT_DIR: the driver's temporary files land there, never in
    a checkout (a production one included), and only ``attrs`` gives the attributes."""
    r = subprocess.run(["git", "-c", f"core.attributesFile={attrs.as_posix()}", "-c", f"merge.{NAME}.driver={driver}",
                        "merge-tree", "--write-tree", "--name-only", "--no-messages", ours, theirs],
                       cwd=attrs.parent, capture_output=True, timeout=600, env={**env, "GIT_DIR": _git_dir(repo)},
                       stdin=subprocess.DEVNULL)
    if r.returncode not in (0, 1):
        raise DriverError(f"git merge-tree {ours} {theirs}: {_decode(r.stderr).strip() or r.returncode}")
    lines = [x for x in _decode(r.stdout).splitlines() if x]
    return (lines[0] if lines else ""), lines[1:]


def _git_dir(repo: Path) -> str:
    r = _git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=repo)
    if r.returncode:
        raise DriverError(f"{repo}: not a git repository")
    return _decode(r.stdout).strip()


def _rev(repo: Path, spec: str) -> str:
    r = _git("rev-parse", "--verify", "--quiet", spec, cwd=repo)
    return _decode(r.stdout).strip() if r.returncode == 0 else ""


def merges(repo: Path, since: str = "", rev: str = "HEAD") -> list[tuple[str, str, str]]:
    """(merge, first parent, second parent) of the two-parent merges reachable from ``rev`` (since a date)."""
    args = ["log", "--merges", "--format=%H %P", rev] + ([f"--since={since}"] if since else [])
    out = []
    for line in _decode(_git(*args, cwd=repo).stdout).splitlines():
        parts = line.split()
        if len(parts) == 3:
            out.append((parts[0], parts[1], parts[2]))
    return out


def replay(repo: Path, pairs: list[tuple[str, str, str]], attributes: str = ATTRIBUTES,
           driver: str | None = None) -> list[dict]:
    """Each (merge, ours, theirs) merged again by ``git merge-tree``, as text then with the driver: the conflicted
    paths of each, and for each path the driver resolved, whether its result is the merge's own (``same``) or not
    (``differs``: a view the merge regenerated, an order, a resolution by hand)."""
    driver = driver or f'"{Path(sys.executable).as_posix()}" -m brain.mergedriver %O %A %B %P %L'
    env = dict(os.environ, **{NO_MARK: "1"})
    out = []
    with tempfile.TemporaryDirectory(prefix="brain-replay-") as d:
        attrs = Path(d) / "attributes"
        attrs.write_text(attributes, encoding="utf-8")
        for merge, ours, theirs in pairs:
            _, before = _merge_tree(repo, ours, theirs, "git merge-file --marker-size=%L %A %O %B", attrs, env)
            tree, after = _merge_tree(repo, ours, theirs, driver, attrs, env)
            resolved = {}
            for path in before:
                if path in after:
                    continue
                mine = _rev(repo, f"{tree}:{path}")
                theirs_ = _rev(repo, f"{merge}:{path}") if merge else ""
                resolved[path] = "same" if mine and mine == theirs_ else "differs"
            out.append({"merge": merge, "ours": ours, "theirs": theirs, "before": before, "after": after,
                        "resolved": resolved})
    return out


def summary(results: list[dict]) -> list[str]:
    """The replay in a few lines: merges conflicted before and after, per path."""
    before = sum(1 for r in results if r["before"])
    after = sum(1 for r in results if r["after"])
    files_b = Counter(p for r in results for p in r["before"])
    files_a = Counter(p for r in results for p in r["after"])
    same = Counter(p for r in results for p, v in r["resolved"].items() if v == "same")
    lines = [f"{len(results)} merge(s) replayed: {before} conflicted as text, {after} with the driver",
             f"{sum(files_b.values())} conflicted file(s) as text, {sum(files_a.values())} with the driver"]
    for path, n in files_b.most_common():
        lines.append(f"  {path}: {n} -> {files_a.get(path, 0)}"
                     + (f" ({same[path]} identical to the merge's own result)" if same.get(path) else ""))
    for path, n in files_a.most_common():
        if path not in files_b:
            lines.append(f"  {path}: 0 -> {n} (the driver conflicted where text merged)")
    return lines


def main_replay(repo: Path, since: str, specs: list[str], as_json: bool, rev: str = "HEAD") -> int:
    pairs: list[tuple[str, str, str]] = []
    for spec in specs:
        if ".." in spec:   # OURS..THEIRS: two heads merged as they are today (two PRs against each other)
            a, _, b = spec.partition("..")
            pairs.append(("", _rev(repo, a), _rev(repo, b)))
        else:
            sha = _rev(repo, spec)
            parents = _decode(_git("rev-list", "--parents", "-n", "1", sha, cwd=repo).stdout).split()
            if len(parents) != 3:
                print(f"brain merge-driver replay: {spec} is not a two-parent merge", file=sys.stderr)
                return 1
            pairs.append((parents[0], parents[1], parents[2]))
    if since or not specs:
        pairs += merges(repo, since, rev)
    if any(not x for p in pairs for x in p[1:]):
        print("brain merge-driver replay: a revision does not resolve", file=sys.stderr)
        return 1
    results = replay(repo, pairs)
    if as_json:
        print(json.dumps(results, indent=2))
    else:
        print("\n".join(summary(results)))
    return 0
