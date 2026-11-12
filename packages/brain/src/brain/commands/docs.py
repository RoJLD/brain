"""``brain docs``: generated READMEs (brain.readme, wi-brain-readme-sync): ``render`` writes a repo's README.md (and its
FEATURES.md) from the engine's template, the repo's readme.yaml and the facts of their sources; ``check`` refuses a
README that is not that render. Only a checkout that holds readme.yaml is concerned.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .. import config, features, graph, readme, skew
from ._common import _repos, _root_repo, _store

ORDER = 45   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 32   # its usage lines' place in brain --help's epilog
RUNS_VIA = {   # brain perf --usage: how a subcommand that may never run from the CLI is reached (brain.adoption)
    "docs check": "wired: brain check runs its checks for each repo with a readme.yaml (stale: default branch)",
    "docs render": "on demand: the remedy brain check names when a generated README is stale",
}
USAGE = """\
  brain docs render [--write [--force]] [--repo R] [--dir PATH] | check [--repo R] [--dir PATH]   generated READMEs:
                 README.md from the engine's template and the repo's readme.yaml (what it is, why, how to start, its
                 notes, the commands it quotes), the facts from their sources (the features recap and FEATURES.md,
                 each quoted command's usage from its --help, a private repo's active specs, recent ADRs and
                 milestones); a public repo's render is neutral. render prints it (--write writes README.md and
                 FEATURES.md; --force replaces a hand-written README once, and writes under views.strict with another
                 engine than the pin). check exits 1 when readme.yaml misses a field, a quoted command is gone, or
                 README.md is not the render. Only a checkout with readme.yaml is concerned (--repo: one of the
                 project's repos, every one with readme.yaml by default; --dir: the checkout to use instead of the
                 registered one, a worktree of --repo, else of the root's repo); brain check runs the same check
"""


def targets(args, root: Path) -> list[tuple[str, Path]]:
    """(repo, checkout) of what to render or check: --repo (its registered path, or --dir: a worktree of it), else
    the root's repo with --dir (a worktree of the root's repo: another repo needs --repo), else every repo of the
    project whose checkout holds readme.yaml. A named target is returned even when it holds no readme.yaml: the
    caller says it is not concerned."""
    repos = {c.name.lower(): c.path for c in _repos(args, root)}
    name = (getattr(args, "repo", "") or "").lower()
    where = Path(args.dir).resolve() if getattr(args, "dir", "") else None
    if name:
        path = where or repos.get(name)
        if path is None:
            raise SystemExit(f"brain docs: {name} is not a repo of the project (projects.yaml repos:): give --dir")
        return [(name, path)]
    if where:
        return [(_root_repo(args, root), where)]
    found = [(n, p) for n, p in repos.items() if p.is_dir() and readme.applies(p)]
    if not found and readme.applies(root):
        found = [(_root_repo(args, root), root)]
    return found


def facts_for(args, root: Path, repo: str, checkout: Path, cfg=None) -> readme.Facts:
    store = _store(args, root)
    public = features.public_checkout(checkout, cfg)
    return readme.store_facts(store, repo, public, _root_repo(args, root))


def _render_one(args, root: Path, repo: str, checkout: Path, cfg) -> int:
    if not readme.applies(checkout):
        print(f"brain docs: {checkout} holds no {readme.FILE}: not concerned (write one to opt in)", file=sys.stderr)
        return 1
    try:
        spec = readme.load(checkout)
    except readme.ReadmeError as exc:
        print(f"error: {repo}: {exc}")
        return 1
    errors = readme.spec_errors(spec)
    for e in errors:
        print(f"error: {repo}: {e}")
    if errors:
        return 1
    facts = facts_for(args, root, repo, checkout, cfg)
    text = readme.render(spec, facts, checkout)
    if not args.write:
        print(text, end="")
        return 0
    said = readme.write(checkout, text, force=args.force)
    print(f"{repo}: {readme.VIEW} {said}" + (" (public render)" if facts.public else ""))
    if said.startswith("refused"):
        return 1
    if facts.model is not None:   # its FEATURES.md, as brain features render writes it there
        from .features import _features_view
        return _features_view(args, root, _store(args, root), write=True, repo=repo,
                              out=str(checkout / features.VIEW))
    return 0


def problems(args, root: Path, cfg=None) -> tuple[list[str], list[str]]:
    """(errors, stale READMEs) of every opted-in checkout of the project (brain docs check, brain check)."""
    errors, stale = [], []
    for repo, checkout in targets(args, root):
        if not readme.applies(checkout):
            continue
        rep = readme.check(checkout, facts_for(args, root, repo, checkout, cfg), cfg)
        errors += [f"{repo}: {e}" for e in rep.errors]
        if rep.stale:
            stale.append(f"{repo}: {rep.stale}: brain docs render --write")
    return errors, stale


def cmd_docs(args, root: Path) -> int:
    cfg = config.load(root)
    return (_cmd_render if args.docs_cmd == "render" else _cmd_check)(args, root, cfg)


def _cmd_render(args, root: Path, cfg) -> int:
    found = targets(args, root)
    if not found:
        print(f"brain docs: no repo of the project holds {readme.FILE}: not concerned")
        return 0
    if args.write and skew.refuse_view(root, "docs render --write", args.force, f"the committed {readme.VIEW}"):
        return 1
    rc = 0
    for repo, checkout in found:
        rc = _render_one(args, root, repo, checkout, cfg) or rc
    return rc


def _cmd_check(args, root: Path, cfg) -> int:
    found = targets(args, root)
    for repo, checkout in found:
        if not readme.applies(checkout):   # named by --repo or --dir: said, never counted as checked
            print(f"docs check: {repo} ({checkout}) holds no {readme.FILE}: not concerned")
    found = [(r, c) for r, c in found if readme.applies(c)]
    if not found:
        print(f"docs check: no repo of the project holds {readme.FILE}: not concerned")
        return 0
    try:
        errors, stale = problems(args, root, cfg)
    except graph.GraphError as exc:
        print(f"brain docs: {exc}", file=sys.stderr)
        return 1
    for line in errors + stale:
        print(f"error: {line}")
    if not errors and not stale:
        print(f"docs check: {len(found)} README(s) up to date")
    return 1 if errors or stale else 0


def register(sub, ctx) -> None:
    do = sub.add_parser("docs", help="generated READMEs: README.md from the engine's template and the repo's "
                                     "readme.yaml (brain.readme)")
    ds = do.add_subparsers(dest="docs_cmd", required=True)
    dr = ds.add_parser("render", help="print README.md's render, or write it (and FEATURES.md) with --write")
    dr.add_argument("--write", action="store_true", help="write README.md and the repo's FEATURES.md")
    dr.add_argument("--force", action="store_true", help="replace a hand-written README.md (the first render); write "
                                                         "under views.strict with another engine than the pin")
    dc = ds.add_parser("check", help="exit 1 when readme.yaml misses a field, a quoted command is gone, or README.md "
                                     "is not the render")
    for p in (dr, dc):
        p.add_argument("--repo", default="", help="one of the project's repos (default: every one with readme.yaml)")
        p.add_argument("--dir", default="", help="the checkout to read and write instead of the registered one (a "
                                                 "worktree of --repo, else of the root's repo)")


run = cmd_docs
