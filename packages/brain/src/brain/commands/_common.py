"""What several command modules share: the text options, the project, its store and scope, the root of an early
command (brain.commands)."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from .. import actions, decisions, paths, projects, resume, transcript, usage


def _now() -> str:
    return transcript.iso(datetime.now(timezone.utc))


def _text(value: str | None) -> str:
    """A text option: @FILE reads the file, '-' reads stdin, else the value itself."""
    if not value:
        return value or ""
    if value == "-":
        return sys.stdin.read()
    if value.startswith("@") and Path(value[1:]).is_file():
        return Path(value[1:]).read_text(encoding="utf-8")
    return value


def _kv(pairs: list[str]) -> dict:
    out = {}
    for p in pairs or []:
        if "=" not in p:
            raise SystemExit(f"brain: {p!r}: expected key=value")
        k, v = p.split("=", 1)
        out[k.strip()] = v
    return out


def _project(args, root: Path) -> projects.Project:
    """--project's; else, with --store, the project registered at ``root`` that lists that store (one that shares the
    root runs its store with its own layout, never the owner's); else the registered project at ``root`` (a worktree
    of its checkout keeps its name)."""
    obj = getattr(args, "project_obj", None)
    if obj:
        return obj
    store = getattr(args, "store", None)
    return (store and projects.lister(Path(store).resolve(), root)) or resume.project_for(root)


def _store(args, root: Path) -> Path:
    if getattr(args, "store", None):
        return Path(args.store).resolve()
    return projects.stores_of(_project(args, root))[0]


def _read_stores(args, root: Path) -> list[Path]:
    """The stores a read command searches (brain.reads): --store, else the project's stores that hold a schema."""
    if getattr(args, "store", None):
        return [Path(args.store).resolve()]
    return [s for s in projects.stores_of(_project(args, root)) if (s / "schema.yaml").is_file()]


def _print_json(data) -> None:
    import json
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def _repos(args, root: Path) -> list[projects.Repo]:
    try:
        return projects.repos_of(_project(args, root))
    except projects.RepoError as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return []


def _root_repo(args, root: Path) -> str:
    """The name of the repo at the project's root (the one that holds the store): a feature's default repo."""
    for c in _repos(args, root):
        if c.path.resolve() == root.resolve():
            return c.name
    return projects._repo_folder(root).lower()


def _store_label(root: Path, store: Path) -> str:
    return store.relative_to(root).as_posix() if store.is_relative_to(root) else store.as_posix()


def _queue_changed(root: Path, args) -> None:
    """The decision queue of the root's records written again: it is the root's owner's, whichever of the projects
    that share the root acted."""
    p = _project(args, root)
    out = decisions.write_view(root, p.shares_root_with or p.name)
    print(f"view: {out.relative_to(root).as_posix()}")


def _scope(args, root: Path, *, root_shared: bool = False) -> list[projects.Project]:
    """--all: every registered project; else the one --project names or the one at ``root``. ``root_shared`` (sync,
    check, refresh): every project registered at ``root`` when several share it and neither --project nor --store
    names one, so the views of the next ones are kept as current as the owner's. ``--scope REF`` (a view that takes
    it): the projects of that node's subtree in the scope tree (brain.scopes; global is every one, as --all); the node
    is left in ``args.scope_node``."""
    if getattr(args, "scope", None):
        return _scope_projects(args, root)
    if getattr(args, "all", False):
        if getattr(args, "project", None):
            raise SystemExit("brain: --project or --all, not both")
        reg = projects.load(root)
        if not reg:
            raise SystemExit(f"brain: --all needs the project registry ({projects.REGISTRY}; $BRAIN_PROJECTS or "
                             "$CLAUDE_BRAIN_DIR)")
        return list(reg.values())
    if root_shared and not getattr(args, "project_obj", None) and not getattr(args, "store", None):
        here = projects.at_root(root)
        if len(here) > 1:
            return here
    return [_project(args, root)]


def _scope_projects(args, root: Path) -> list[projects.Project]:
    """--scope REF resolved to the loaded projects under that node, depth first; one of --scope, --project, --all."""
    from .. import scopes
    from .scopes import here
    if getattr(args, "all", False) or getattr(args, "project", None):
        raise SystemExit("brain: --scope, --project or --all: one of them")
    try:
        args.scope_node, names = scopes.select(args.scope, root, here(root))
    except scopes.ScopeError as exc:
        raise SystemExit(f"brain: {exc}") from None
    if args.scope_node == "global":   # global is --all, whatever the view does with it
        args.all = True
    if not names:
        raise SystemExit(f"brain: --scope {args.scope}: no registered project the brain loads under "
                         f"{args.scope_node} (brain scopes shows the tree)")
    reg = projects.load(root)
    return [reg[n] for n in names]


def scope_every(args, scope: list[projects.Project]) -> bool:
    """A view's --all behaviour (the totals, the ids shared across stores): --all, or --scope on Global or on a node
    that holds several projects."""
    if getattr(args, "all", False):
        return True
    node = getattr(args, "scope_node", "")
    return bool(node) and (node == "global" or len(scope) > 1)


def _notify_project(args, root: Path) -> projects.Project:
    """--project, else the registered project at root; a worktree of a registered checkout gets that project's routes
    (a blocking question asked from a worktree of that project is still sent)."""
    return getattr(args, "project_obj", None) or resume.project_for(root)


def _on_main(root: Path) -> str:
    """The branch when ``root`` is a main checkout on main or master (the checkout services run from), else ''."""
    branch = actions.git(root, "rev-parse", "--abbrev-ref", "HEAD")
    main = paths.main_checkout(root)
    return branch if branch in ("main", "master") and main and main.resolve() == root.resolve() else ""


def _when(text: str | None, default: str = "") -> str:
    try:
        return usage.parse_when(text or default, usage.now_utc())
    except ValueError as exc:
        raise SystemExit(f"brain: {exc}") from None


def _whole(text: str) -> int:
    """argparse type: a whole number (0 or more)."""
    try:
        n = int(text)
    except ValueError:
        n = -1
    if n < 0:
        raise argparse.ArgumentTypeError(f"a whole number, 0 or more ({text!r})")
    return n


def root_of(args) -> Path | None:
    """--root resolved, else None: what a command that runs before the project's root is resolved (early) gets."""
    return Path(args.root).resolve() if args.root else None
