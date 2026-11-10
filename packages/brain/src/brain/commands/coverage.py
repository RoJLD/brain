"""``brain coverage``: a repo's line coverage under its tests, with test contexts: printed, kept in the store with
--write (the tested_by links, test.coverage).
"""

from __future__ import annotations

import sys
from pathlib import Path

from .. import skew
from ..inventory import AuditError
from ._common import _repos, _root_repo, _store

ORDER = 530   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 190   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain coverage [--repo R] [--run [-n N] | --from DATA [--cwd DIR]] [--python PY] [--write [--force]] [--json]
                        a repo's line coverage: --run runs its pytest suites (from each suite's pytest configuration)
                        under pytest-cov with test contexts, --from reads a coverage data file made elsewhere (the
                        CI's .coverage, run with --cov-context=test); the summary (totals; per file its statements,
                        covered lines and the test modules that ran each function) printed, and with --write kept in
                        the store as coverage/<repo>.json: brain sync links a CodeRef's symbol to the tests that ran
                        it, brain audit measures test.coverage, FEATURES.md shows each feature's coverage; another
                        engine than config.json engine.pin writes nothing (--force)
"""


def _refused(args, root: Path) -> bool:
    return bool(args.write and skew.refuse(root, "coverage --write", args.force, "the committed coverage summary"))


def cmd_coverage(args, root: Path) -> int:
    """brain coverage (brain.testcov): a repo of the project measured; the summary printed, kept with --write."""
    from .. import testcov
    if _refused(args, root):   # before the measure: another engine than config.json engine.pin writes nothing
        return 1
    cfgs = _repos(args, root)
    want = (args.repo or _root_repo(args, root) or "").lower()
    c = next((c for c in cfgs if c.name.lower() == want), None)
    if c is None:
        raise SystemExit(f"brain coverage: no repo {want or '?'} in the project (repos: "
                         f"{', '.join(x.name for x in cfgs) or 'none'})")
    try:
        summary, rc = testcov.measure(c, args.run, args.from_data, args.cwd, args.python, args.workers)
    except (testcov.CoverageError, AuditError) as exc:
        raise SystemExit(f"brain coverage: {exc}") from None
    print(testcov.render(summary) if args.json else "\n".join(testcov.lines(summary)), end="" if args.json else "\n")
    if args.write:
        f = _store(args, root) / testcov.FOLDER / f"{c.name.lower()}.json"
        f.parent.mkdir(exist_ok=True)
        f.write_text(testcov.render(summary), encoding="utf-8", newline="\n")
        print(f"brain coverage: wrote {f} (brain sync links the symbols, brain audit reads test.coverage)")
    if rc:
        print("brain coverage: some tests failed; their coverage is counted as run", file=sys.stderr)
    return 0


def register(sub, ctx) -> None:
    cv = sub.add_parser("coverage", help="a repo's line coverage under its tests, with test contexts: printed, kept "
                                         "in the store with --write (the tested_by links, test.coverage)")
    cv.add_argument("--repo", default="", help="a repo of the project (default: the one that holds the store)")
    cv.add_argument("--run", action="store_true", help="run the repo's pytest suites under pytest-cov")
    cv.add_argument("-n", dest="workers", default="", help="pytest-xdist workers for --run (auto, 8...)")
    cv.add_argument("--python", default="", help="the Python that runs the tests (default: this one)")
    cv.add_argument("--from", dest="from_data", default="", help="a coverage data file (.coverage, run with "
                                                                  "--cov-context=test) instead of a run")
    cv.add_argument("--cwd", default="", help="with --from: the folder pytest ran in (default: the repo's root)")
    cv.add_argument("--write", action="store_true", help="keep the summary in the store: coverage/<repo>.json")
    cv.add_argument("--force", action="store_true", help="--write even when the running engine is not config.json "
                                                         "engine.pin")
    cv.add_argument("--json", action="store_true")


run = cmd_coverage
