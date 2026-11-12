"""``brain formats``: a project's own formats (projects.yaml ``formats:``, brain.formats, wi-brain-project-formats):
``list`` them, ``check`` them: their declarations, then each ``check:`` command, opt-in (PF-1), bounded and cached by
the hashes of the files it judges.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .. import formats, projects
from ._common import _print_json, _scope

ORDER = 126   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 126   # its usage lines' place in brain --help's epilog
RUNS_VIA = {   # brain perf --usage: how a subcommand that may never run from the CLI is reached (brain.adoption)
    "formats list": "on demand: a project's formats read by hand (brain projects --keys documents the key)",
}
USAGE = """\
  brain formats list [--all] [--json] | check [--all] [--format ID] [--fresh] [--timeout S] [--json]   a project's
                 own persisted formats (projects.yaml formats:, docs/formats.md « A project's own formats »): list
                 prints each one's files, repo, class, version locator, schema, fixtures and check; check judges
                 their declarations (as brain check does), then runs each check: command in its repo's checkout, with
                 no shell, bounded by its timeout (default 120 s; --timeout overrides it), a pass or a fail cached
                 under $BRAIN_HOME/formats by the hashes of the command and of the files it judges (--fresh runs it
                 anyway). Exit 1 on an invalid declaration, a fail, a timeout or an error (an exit code other than 0
                 or 1, a command not found); a format without check: is skipped. Never run by a plain brain check
                 (brain check --formats runs it after); a project the brain only reads declares none
"""


def _repos(p: projects.Project) -> tuple[dict[str, Path], str, list[str]]:
    """({repo name: its checkout}, the first repo's name, errors) of a project."""
    try:
        repos = projects.repos_of(p)
    except projects.RepoError as exc:
        return {}, "", [str(exc)]
    return {r.name: r.path for r in repos}, repos[0].name if repos else "", []


def declared(p: projects.Project) -> tuple[list[formats.Format], dict[str, Path], str, list[str]]:
    """(its well-formed formats, its repos, its first repo, what its declarations break)."""
    entry = {"formats": p.formats, "migrations": p.migrations}
    where = f"project {p.name}"
    repos, default, errors = _repos(p)
    errors = formats.errors(where, entry) + errors
    if not errors:
        errors += formats.check_project(where, entry, repos, default)
    return formats.formats_of(p.formats), repos, default, errors


def report(p: projects.Project, *, only: str = "", fresh: bool = False, timeout: int | None = None,
           run: bool = True) -> dict:
    """What brain formats check says of a project, with stable keys: its declarations' errors, then (``run``) each
    format's result. An invalid declaration runs nothing of the project."""
    fmts, repos, default, errors = declared(p)
    if only and not any(f.id == only for f in fmts):
        errors = errors + [f"project {p.name}: no format {only!r} (brain formats list)"]
    results = [] if errors or not run else formats.run(p.name, fmts, repos, default, only=only, fresh=fresh,
                                                        timeout=timeout)
    return {"project": p.name, "formats": len(fmts), "errors": errors,
            "results": [{"format": r.format, "status": r.status, "cached": r.cached, "seconds": round(r.seconds, 3),
                         "detail": r.detail, "tail": r.tail} for r in results]}


def failed(data: dict) -> bool:
    return bool(data["errors"]) or any(r["status"] in ("fail", "error", "timeout") for r in data["results"])


def print_report(data: dict) -> None:
    for e in data["errors"]:
        print(f"error: {e}")
    for r in data["results"]:
        how = " (cached)" if r["cached"] else (f" ({r['seconds']:.1f} s)" if r["status"] != "skipped" else "")
        print(f"  {r['status']:<8} {r['format']}{how}" + (f": {r['detail']}" if r["detail"] else ""))
        if r["status"] in ("fail", "error", "timeout"):
            for line in r["tail"][-5:]:
                print(f"           | {line}")


def run_scope(scope: list[projects.Project], *, only: str = "", fresh: bool = False,
              timeout: int | None = None, as_json: bool = False) -> int:
    """brain formats check over projects (brain check --formats too): exit 1 when one fails. With ``only``, the
    projects that declare that format (an error when none of them does)."""
    if only and len(scope) > 1:
        scope = [p for p in scope if any(f.id == only for f in formats.formats_of(p.formats))] or scope[:1]
    out = [report(p, only=only, fresh=fresh, timeout=timeout) for p in scope
           if p.formats is not None or only or len(scope) == 1]
    if as_json:
        _print_json({"formats": 1, "projects": out})
    else:
        for data in out:
            print(f"== formats {data['project']}: {data['formats']} declared")
            print_report(data)
        if not out:
            print("no project declares formats: (projects.yaml)")
    return 1 if any(failed(d) for d in out) else 0


def _cmd_list(args, root: Path) -> int:
    rows, rc = [], 0
    for p in _scope(args, root):
        fmts, repos, default, errors = declared(p)
        rc = 1 if errors else rc
        for e in errors:
            print(f"brain formats: {e}", file=sys.stderr)
        rows += [{"project": p.name, "id": f.id, "glob": f.globs, "repo": f.repo or default, "class": f.cls,
                  "version": f.version, "schema": f.schema, "fixtures": f.fixtures, "check": f.check,
                  "timeout": f.timeout} for f in fmts]
    if args.json:
        _print_json({"formats": rows})
        return rc
    for r in rows:
        print(f"{r['project']}/{r['id']}  {', '.join(r['glob'])} in {r['repo']}  class {r['class']}, version: "
              f"{r['version']}")
        for k in ("schema", "fixtures"):
            if r[k]:
                print(f"    {k}: {r[k]}")
        print(f"    check: {' '.join(r['check'])} (timeout {r['timeout']} s)" if r["check"] else "    check: none")
    if not rows:
        print("no format declared (projects.yaml formats:)")
    return rc


def _cmd_check(args, root: Path) -> int:
    return run_scope(_scope(args, root), only=args.format or "", fresh=args.fresh, timeout=args.timeout,
                     as_json=args.json)


def cmd_formats(args, root: Path) -> int:
    return {"list": _cmd_list, "check": _cmd_check}[args.formats_cmd](args, root)


def _timeout(value: str) -> int:
    import argparse
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("a whole number of seconds") from None
    if not 1 <= n <= formats.MAX_TIMEOUT:
        raise argparse.ArgumentTypeError(f"from 1 to {formats.MAX_TIMEOUT} seconds")
    return n


def register(sub, ctx) -> None:
    fm = sub.add_parser("formats", help="a project's own formats (projects.yaml formats:): list them, check their "
                                        "declarations and run their check: commands, on demand")
    fs = fm.add_subparsers(dest="formats_cmd", required=True)
    fl = fs.add_parser("list", help="each format: its files, repo, class, version locator, schema, fixtures, check")
    fc = fs.add_parser("check", help="the declarations, then each check: command (bounded, cached by its files' "
                                     "hashes); exit 1 on a fail, a timeout or an error")
    fc.add_argument("--format", default="", help="the format of this id only")
    fc.add_argument("--fresh", action="store_true", help="run every check, a cached result aside")
    fc.add_argument("--timeout", type=_timeout, default=None, help="every check's bound in seconds (default: each "
                                                                   "format's, else 120)")
    for p in (fl, fc):
        p.add_argument("--all", action="store_true", help="every project of the registry")
        p.add_argument("--json", action="store_true", help="stable keys")


run = cmd_formats
