"""``brain test --changed``: the test modules a change touches, by the coverage map, run first; fail-safe, in shadow
mode (brain.targeted).
"""

from __future__ import annotations

import sys
from pathlib import Path

from ..inventory import AuditError
from ._common import _print_json, root_of

ORDER = 535   # its place in brain --help's list of commands (brain.commands), after coverage
USAGE_ORDER = 191
USAGE = """\
  brain test --changed [BASE] [--repo-dir D] [--map FILE] [--inert GLOB]... [--list] [--json] [--strict]
             [--python PY] [-n N] [-- PYTEST ARGS]
                        the targeted tests: the test modules the change from merge-base(HEAD, BASE or the default
                        branch) to the working tree touches, by the coverage map (<store>/coverage/<repo>.json, brain
                        coverage --write), run first; missing, stale or incomplete evidence (no map, a file coverage
                        cannot see, a module it never measured) widens the answer to the whole suite, and a static
                        import or mention only adds a test. Shadow mode (the default): the selection runs, a widened
                        answer is left to the CI's whole suite, each run is a line of the targeted-tests ledger;
                        --strict runs the whole suite when the answer widens; --list prints the selection only
"""


def early(args) -> int:
    """Its repo may be any checkout of a registered one (a worktree): resolved like the scout's (brain.scout)."""
    from .. import projects, scout, targeted
    if args.changed is None:
        raise SystemExit("brain test: --changed (the only selection there is)")
    root = root_of(args)
    try:
        p, _, c, top, registered = scout.resolve(args, root)
        base, base_rev = scout.base_of(top, args.changed or "")
    except AuditError as exc:
        raise SystemExit(f"brain test: {exc}") from None
    if args.map:
        summary = targeted.load_map(Path(args.map))
    elif registered and (args.store or projects.stores_of(p)):
        store = Path(args.store).resolve() if args.store else projects.stores_of(p)[0]
        summary = targeted.load_map(targeted.map_path(store, c.name))
    else:
        summary = None
    sel = targeted.select(top, c.name, base, base_rev, summary, c.roots, args.inert)
    if args.json and args.list:
        _print_json(sel.to_json())
        return 0
    print("\n".join(targeted.lines(sel)))
    if args.list:
        return 0
    strict = args.strict and not sel.complete
    tests = sel.suite if strict else sorted(sel.tests)
    extra = [a for a in (args.pytest_args or []) if a != "--"]
    rc = targeted.run(top, tests, args.python, args.workers, extra) if tests else 0
    if not tests:
        print("brain test: no test module to run")
    led = targeted.record(sel, "strict" if args.strict else "shadow", len(tests), rc)
    if not sel.complete and not args.strict:
        print(f"brain test: shadow mode: the whole suite is the answer; the CI runs it before the merge "
              f"(--strict runs it here); recorded in {led}", file=sys.stderr)
    if args.json:
        _print_json({**sel.to_json(), "ran": len(tests), "rc": rc})
    return rc


def register(sub, ctx) -> None:
    t = sub.add_parser("test", help="the targeted tests: the test modules a change touches, by the coverage map, run "
                                    "first; missing or stale evidence widens to the whole suite (shadow mode)")
    t.add_argument("--changed", nargs="?", const="", default=None, metavar="BASE",
                   help="the change from merge-base(HEAD, BASE or the default branch) to the working tree")
    t.add_argument("--repo-dir", metavar="D", help="the repo changed (default: the current folder)")
    t.add_argument("--map", metavar="FILE", help="a coverage summary (brain coverage --json) instead of the store's")
    t.add_argument("--inert", action="append", default=[], metavar="GLOB",
                   help="changed paths no test reads (repeatable): left out of the selection")
    t.add_argument("--list", action="store_true", help="print the selection, run nothing")
    t.add_argument("--json", action="store_true", help="the selection (and the run) as JSON")
    t.add_argument("--strict", action="store_true", help="run the whole suite when the answer widens")
    t.add_argument("--python", default="", help="the Python that runs the tests (default: this one)")
    t.add_argument("-n", dest="workers", default="", help="pytest-xdist workers (auto, 8...)")
    t.add_argument("pytest_args", nargs="*", metavar="-- PYTEST ARGS", help="passed to pytest")

