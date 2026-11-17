"""``brain test --changed``: the test modules a change touches, by the coverage map, run first; fail-safe, in shadow
mode (brain.targeted).
"""

from __future__ import annotations

import sys
from pathlib import Path

from ..inventory import AuditError
from ._common import _print_json, root_of

ORDER = 532   # its place in brain --help's list of commands (brain.commands), after coverage
USAGE_ORDER = 191
USAGE = """\
  brain test --changed [BASE] [--repo-dir D] [--map FILE] [--inert GLOB]... [--list] [--json] [--strict]
             [--python PY] [-n N] [--verdict [--deadline S] [--log FILE]] [-- PYTEST ARGS]
                        the targeted tests: the test modules the change from merge-base(HEAD, BASE or the default
                        branch) to the working tree touches, by the coverage map (<store>/coverage/<repo>.json, brain
                        coverage --write), run first; missing, stale or incomplete evidence (no map, a file coverage
                        cannot see, a module it never measured) widens the answer to the whole suite, and a static
                        import or mention only adds a test. Shadow mode (the default): the selection runs, a widened
                        answer is left to the CI's whole suite, each run is a line of the targeted-tests ledger;
                        --strict runs the whole suite when the answer widens; --list prints the selection only.
                        --verdict: the selection and pytest's whole output go to a log (<temp>/brain-test/<run>/
                        pytest.log, or --log), the run blocks until it ends or its deadline (--deadline seconds, 540
                        by default: under a shell tool's ten minutes; its process tree stopped then, exit 124), and
                        three lines come out: PASSED, FAILED or TIMEOUT with pytest's counts and the log, the failed
                        tests' ids, the next command
"""
DEADLINE = 540.0   # --verdict's default deadline, in seconds: under the ten minutes a session's shell tool waits


def _map(args, p, c, registered) -> dict | None:
    """--map's coverage summary, else the project's store's (--store's) for the repo, else None."""
    from .. import projects, targeted
    if args.map:
        return targeted.load_map(Path(args.map))
    stores = [Path(args.store).resolve()] if args.store else projects.stores_of(p) if registered else []
    return targeted.load_map(targeted.map_path(stores[0], c.name)) if stores else None


def _selection(args):
    """(the selection, the checkout): the repo resolved like the scout's (a worktree of a registered one too)."""
    from .. import scout, targeted
    try:
        p, _, c, top, registered = scout.resolve(args, root_of(args))
        base, base_rev = scout.base_of(top, args.changed or "")
    except AuditError as exc:
        raise SystemExit(f"brain test: {exc}") from None
    return targeted.select(top, c.name, base, base_rev, _map(args, p, c, registered), c.roots, args.inert), top


def early(args) -> int:
    """brain test --changed (brain.targeted): the selection printed, then run (shadow mode, or --strict)."""
    from .. import targeted
    if args.changed is None:
        raise SystemExit("brain test: --changed (the only selection there is)")
    if args.deadline is not None and not args.verdict:
        raise SystemExit("brain test: --deadline goes with --verdict")
    if args.log and not args.verdict:
        raise SystemExit("brain test: --log goes with --verdict")
    if args.verdict and args.list:
        raise SystemExit("brain test: --verdict runs the tests; --list runs nothing")
    sel, top = _selection(args)
    if args.verdict:
        return _verdict(args, sel, top)
    if not args.json:
        print("\n".join(targeted.lines(sel)))
    if args.list:
        if args.json:
            _print_json(sel.to_json())
        return 0
    tests = sel.suite if args.strict and not sel.complete else sorted(sel.tests)
    extra = [a for a in (args.pytest_args or []) if a != "--"]
    rc = targeted.run(top, tests, args.python, args.workers, extra, quiet_stdout=args.json) if tests else 0
    _report(args, sel, tests, rc)
    return rc


def _verdict(args, sel, top: Path) -> int:
    """--verdict: the selection and pytest's whole output in a log file, the run blocking until the deadline, three
    lines out (brain.verdict.test_lines)."""
    import posixpath

    from .. import targeted, verdict
    tests = sel.suite if args.strict and not sel.complete else sorted(sel.tests)
    extra = [a for a in (args.pytest_args or []) if a != "--"]
    deadline = DEADLINE if args.deadline is None else args.deadline
    log = Path(args.log).resolve() if args.log else \
        verdict.run_folder("test", f"{top.name}-{sel.head[:8]}") / "pytest.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("\n".join(targeted.lines(sel, limit=10 ** 6)) + "\n", encoding="utf-8", newline="\n")
    rc, stopped = targeted.run_logged(top, tests, log, deadline, args.python, args.workers, extra) if tests \
        else (0, False)
    led = targeted.record(sel, "strict" if args.strict else "shadow", len(tests), rc)
    widened = not sel.complete and not args.strict
    with log.open("a", encoding="utf-8", newline="\n") as f:
        f.write(f"\nrecorded in {led}" + ("; shadow mode: the selection widened, the CI runs the whole suite"
                                          if widened else "") + "\n")
    summary = verdict.pytest_summary(log.read_text(encoding="utf-8", errors="replace"))
    runs = targeted.commands(top, tests, args.python, args.workers) if tests else []
    where = f" (in {posixpath.relpath(runs[0][0].as_posix(), top.as_posix())})" if len(runs) == 1 else ""
    again = f"brain test --changed {args.changed} --verdict".replace("--changed  ", "--changed ")
    rerun = (f"python -m pytest {' '.join(summary.failed[:3])}{where}, fix, then {again}" if summary.failed
             else f"read the log, fix, then {again}")
    lines = verdict.test_lines(rc, stopped, deadline, summary, log, len(tests),
                               again if stopped else rerun, "brain gate (or git push)",
                               "widened: the CI runs the whole suite" if widened else "")
    if args.json:
        _print_json({**sel.to_json(), "ran": len(tests), "rc": rc, "stopped": stopped, "log": log.as_posix(),
                     "counts": summary.counts, "failed": summary.failed, "verdict": lines})
    else:
        print("\n".join(lines))
    return rc


def _report(args, sel, tests: list[str], rc: int) -> None:
    """The run's line in the shadow ledger, and what it means."""
    from .. import targeted
    led = targeted.record(sel, "strict" if args.strict else "shadow", len(tests), rc)
    if not tests:
        print("brain test: no test module to run", file=sys.stderr)
    if not sel.complete and not args.strict:
        print(f"brain test: shadow mode: the whole suite is the answer; the CI runs it before the merge "
              f"(--strict runs it here); recorded in {led}", file=sys.stderr)
    if args.json:
        _print_json({**sel.to_json(), "ran": len(tests), "rc": rc})


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
    t.add_argument("--verdict", action="store_true",
                   help="pytest's whole output to a log file, the run blocking until its deadline, three lines out "
                        "(passed, the failed test ids, the next command)")
    t.add_argument("--deadline", type=_seconds, metavar="S",
                   help=f"--verdict: stop the run after S seconds (default {int(DEADLINE)}), exit 124")
    t.add_argument("--log", metavar="FILE", help="--verdict: the log file (default: <temp>/brain-test/<run>/pytest.log)")
    t.add_argument("pytest_args", nargs="*", metavar="-- PYTEST ARGS", help="passed to pytest")


def _seconds(text: str) -> float:
    import argparse
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r}: a number of seconds") from None
    if not value > 0 or value != value or value == float("inf"):
        raise argparse.ArgumentTypeError(f"{text!r}: a positive number of seconds")
    return value

