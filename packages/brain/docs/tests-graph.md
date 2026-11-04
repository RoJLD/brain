# Tests in the graph and coverage

`brain sync` derives, at zero token, a Test node for each test module and folder of a repo whose store has the `Test`
type, and the `tested_by` edges from the store's nodes to them (`brain.links`, written into
`nodes/_generated_links.yaml` and `edges/_generated_links.yaml`). `brain coverage` measures a repo's line coverage
under its tests and keeps a summary in the store, which the links, `brain audit` and `FEATURES.md` read
(`brain.testcov`).

## Which tests a node is tested by

A node stands for code through a Hook's scripts and through the CodeRefs it is `implemented_by`
(`code:<repo>:<path>[::<symbol>]`). Its tests are, for each file of that code:

1. **brain audit's evidence**, the strongest kind found for the file: a test named after it (`test_<stem>.py`),
   one that imports it, one that imports a name its package re-exports, one that runs it (`-m`, a subprocess, a
   path in its text), a test reaching it through what it imports and naming it. A script's tests are those named
   after it or that run it. This is the evidence `test.module` and `test.script` measure, so the graph never calls a
   unit tested that the audit calls untested.
2. **The test's own imports**: every Python test that imports the module itself (`import p.mod`, `from p import mod`,
   `from p.mod import name`) or runs it (`-m p.mod`, `"-m", "p.mod"` in an argument list, `run_module("p.mod")`), even
   when a test named after the module exists. Only the test's own statements count, not what they import in turn (a
   test of the audit that runs the inventory through the audit is the audit's test, not the inventory's), and not a
   dotted name a string, a fixture or a comment holds.

A CodeRef of a symbol (`path::name`) narrows its file's tests to those about that symbol:

- with no coverage summary, the tests whose text names it, as a word in any case, or names each of its words, a
  `cmd_` prefix (a subcommand's handler) left out: `main(["record", "ddr"])` names `cmd_record_ddr`, a guard test
  that checks a `production` path names `check_production`;
- with a coverage summary of the repo in the store that measured the symbol: the tests its test contexts saw run a
  line of the symbol's body (a method of it, for a class), those that name the symbol outright, and those the
  summary never saw (a test added or renamed since), by the names rule above.

A summary narrows only what it knows. A symbol it did not measure (added or renamed since; the summary lists every
function of each file it measured), a summary with no test context and an older summary format all keep the names
rule: a stale summary never strips a test.

A whole file keeps every test found for it: execution alone never adds a test to a whole file, since a module that
every command runs (the parser, the config) would then be tested by every test.

The node and edge ids do not change: `test:<repo>:<path>` for a module or a folder, one `tested_by` edge per node and
test module. `brain impact` and the risk register read them.

## Coverage: `brain coverage`

```bash
brain coverage --repo brain --run -n 8 --write    # run the repo's suites under pytest-cov, keep the summary
brain coverage --repo brain --from .coverage --cwd packages/brain --write    # a data file made elsewhere (CI)
brain coverage --repo brain --run --json          # the summary on stdout, nothing written
```

`--run` groups the repo's Python test modules by the folder of their nearest pytest configuration (a `pyproject.toml`
with `[tool.pytest.ini_options]`, a `pytest.ini`, a `tox.ini` or `setup.cfg` with a pytest section; the repo's root
when none) and runs `python -m pytest <folders> --cov=<package roots> --cov-context=test` there, the package roots
first on `PYTHONPATH`, so the code that runs is the checkout's, whatever the Python has installed. That Python
(`--python`, default the brain's own) needs pytest-cov (and pytest-xdist for `-n`) and the repo's test dependencies.
A test that fails still counts for what it ran; brain coverage says so.
The repo's own `fail_under` is turned off for the run and the report: this measure never fails on the threshold.
`--from` reads a coverage data file (`.coverage`, made with `--cov-context=test`), `--cwd` being the folder pytest
ran in. A file from another machine (the CI) needs coverage's `relative_files = true` so that its paths are this
checkout's. It is read against this checkout, whose HEAD is the commit recorded, so read it in a checkout at the
commit it measured. A data file in which no context names a test is refused; branch data (`branch = true`) is read
from its arcs.

The statements of each file come from `coverage json`; which test ran which line comes from the data file's own
SQLite tables, read by the brain without the coverage package (the JSON report with its contexts is gigabytes for
this engine's suite). The summary, `<store>/coverage/<repo>.json` (version 2), holds the commit measured (and whether
the tree was dirty), the day, the totals, every test module a context named (`test_modules`), and per file its
statements, covered lines and percent, every function it had (`functions`), and, for each test module that ran a
line of one of its functions' bodies, those functions (`f`, `Class.method`). A nested function counts for the one that
holds it, and a function under a module-level `if`, `try` or `with` counts. The def and decorator lines, and a module
or class body, run at import and count for no test, so the summary does not depend on which test imported a module
first, nor on `-n`. Its keys are sorted: a run that changes nothing writes the same file. Commit it with the store,
like any record: brain sync, FEATURES.md and brain audit read it from there (the checkout's tracked and untracked,
not ignored, files), the same on every machine.

## What the audit measures

- `test.links` (P2, never in the scout): a test module no graph node is `tested_by`.
- `feature.tests` (P2, never in the scout): a `have` or `partial` feature with code in the repo (a module or a
  script its CodeRefs name, whichever repo owns the feature; a data file is no code a test imports) that no test
  module of the repo is `tested_by`, by the links derived now.
- `test.coverage` (P2, never in the scout): a Python module of the repo its tests run under 50 % of
  (`audit.COVERAGE_FLOOR`), by the store's summary; a module the summary does not know (added since) is not counted,
  and without a summary the check is listed as not measured. The trend reads today's summary for every past week,
  as it reads today's code layers: the week a summary is first committed is no rise of the debt.
- `FEATURES.md`: each feature's Tests cell gives the percent of its files' statements the tests run (its whole-file
  CodeRefs, by the summary of each one's repo; a symbol's file figure would say nothing of the symbol), then its
  `tested_by` tests.
