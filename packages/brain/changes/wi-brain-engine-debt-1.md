section: Changes

- `brain audit`: a repo's `waive` globs in `projects.yaml` also take a test module of `test.links` and a doc of
  `doc.links` (a test that checks data no module stands for, a template a new brain copies), listed as waived with
  their reason; any other check of a test or a doc is never waived. A glob written before for modules and scripts
  (a template's `"plugins/**"`) now takes the tests and docs it matches too (`wi-brain-engine-debt`, batch 1).
- A frozen store's files (`tests/fixtures/stores/<tag>/`) are no test modules any more, as they were no docs: their
  hooks no longer count as tests of a feature (`FEATURES.md`'s Tests cell, once `brain sync` derives the links again).
- `brain mcp`'s server reads a refused request's body before it closes: on Windows the client got a reset instead of
  the 401, and `brain health ipc` said « not the MCP server » of a healthy one; the test of that probe made steady
  the same way. `brain quiet --off --dry-run` ends the quiet and only prints the sum-up (its help says so).
- The engine's own debt, batch 1: `FEATURES.md` rendered again, `brain quiet`'s command tested (42 % to 97 %).
