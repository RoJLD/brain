# The impact of a change: `brain impact` and `brain code-map`

Before a branch merges, `brain impact` says what its code carries in the graph: which features, items, decisions,
specs, docs and tests rely on the code it touches. Zero token and read-only. It runs from the changed repo (a
worktree of it too), like `brain audit --diff`.

```
brain impact                      # from the merge base with the default branch to the working tree
brain impact --diff main          # from merge-base(main, HEAD)
brain impact --diff A..B          # the commits A..B only (a replay)
brain impact --json               # the whole chain and the checklist
brain code-map [--project P]      # the CodeRefs resolved in the code index, and the coverage
```

## The chain

1. **The change.** The files from the base to the working tree, untracked files included, and their hunks
   (`git diff -U0`), read as the scout reads them.
2. **The symbols touched.** GitNexus's code index holds the repo at its indexed commit (`brain index`). The hunks of
   the diff from that commit, on the files the change touches, are matched to the indexed symbols whose lines they
   overlap: the query GitNexus's `detect_changes` runs, sent through its MCP `cypher` tool. `detect_changes` itself
   cannot serve: it diffs GitNexus's own clone, inside its container at the default branch, never this checkout or
   its branch. Then the callers of those symbols, `--depth` levels up (2 by default), along the CALLS edges GitNexus
   resolved; the calls it guessed from a name alone (confidence about 0.5) are left out.
   GitNexus counts lines from 0 (tree-sitter's rows): they are shifted to git's count, from 1.
3. **The CodeRefs.** The code map joins each touched symbol and each caller to the CodeRefs that name it; a file's
   CodeRef is touched by any change to the file, and a symbol the index does not place (an assignment it keeps no
   node for, a file it does not index) is looked up by the AST of both sides. A CodeRef whose file the change deletes
   or moves away is touched whatever the index holds (`removed with its file`, `its file moved to ...`): it now names
   a path that is gone.
4. **The graph.** The nodes relying on those CodeRefs, by research_graph's reliance (`implemented_by`, `part_of`,
   `depends_on`, ...): features, their parent features, the domain layers. Around them: the Doc sections that document
   them or name a changed file, the Test modules that test them or cover the touched code and the CI jobs that run
   those, the ADRs and SDRs linked to them (the current one when a decision was superseded), their specs, the open
   items that deliver them and the DDRs pending on those items.

## The checklist

The demo project of the tests (`tests/test_impact.py`): a change edits `go` in `src/lab/core.py` and adds a test.

```
== impact demo/lab: main@419fa01..worktree, 2 file(s) changed
symbols (GitNexus, index at 419fa01): 3 touched in 1 file(s), 2 caller(s)
CodeRefs touched (3):
  code:lab:lab/cli.py::main  caller: Function:src/lab/core.py:go (depth 1)
  code:lab:lab/core.py::Engine.run  caller: Function:src/lab/core.py:go (depth 1)
  code:lab:lab/core.py::go  symbol
checklist:
[ ] features whose status may change (3):
    feat-all (partial): part of a touched feature; this change may complete it (have) (through its part)
    feat-cli (have): implemented by code:lab:lab/cli.py::main; check it still holds
    feat-go (planned): implemented by code:lab:lab/core.py::go; this change may make it partial or have
[ ] docs to update (2 section(s) in 2 file(s)):
    README.md: CLI (documents feat-cli)
    docs/guide.md: Core (names src/lab/core.py)
[ ] ADRs and specs to re-read (2):
    adr-new (active): New decision (via feat-go)
    spec-go (active): Go spec (via feat-go)
[ ] tests to run (4):
    pytest tests/test_cli.py tests/test_core.py tests/test_new.py
    tests/Lab.Tests.ps1 (pester)
    CI: .github/workflows/ci.yml::test
    and 1 wider test module(s) of these features, covering none of the touched code (--json: wider_tests)
[ ] open items that deliver these features (1):
    wi-go (todo): Ship go
[ ] decisions pending on them (1):
    ddr-go (pending): Which go?
touched symbols no CodeRef names (2; the graph does not see them): src/lab/core.py::helper, src/lab/core.py::go
```

- **Features**: a planned or partial feature may move (`brain features set`); a feature that has it should still
  hold.
- **Docs**: the sections that document a node relying on the code, or that name a changed file (a section of a doc
  the change already edits says `changed here`, one it deletes or moves away `removed by this change`).
- **Tests**: the modules whose covered files meet the touched code (the changed files and the touched CodeRefs',
  a caller's included), the modules the relying nodes are `tested_by` that say nothing of what they cover, and the
  test files the change adds or edits; never a module the change deletes or moves away, so the `pytest` line runs.
  A `tested_by` module covering none of the touched code is one of the features' wider tests, counted apart. The
  `tested_by` edges are those `brain sync` derives (the links of the docs and tests, and, once it is built,
  `wi-brain-test-links-auto`'s from imports and coverage).
- **Malformed CodeRefs**: an active CodeRef whose id the grammar refuses is left out and named on the last lines.
- **Touched symbols no CodeRef names**: code the graph does not see; a CodeRef on them (`brain features link --code`)
  brings them into the next impact.

## Without GitNexus

When the GitNexus stack does not answer, the repo is not indexed, its indexed commit is not in this checkout, or the
code map of the repo fails (a query that times out), the impact is at the file level and its second line says so
and what to run:

```
FILE LEVEL (no symbol, no caller): gitnexus does not answer at http://127.0.0.1:4747: brain up gitnexus, then brain index brain
```

Every CodeRef of a changed file is touched, a Python symbol's CodeRef narrowed by the AST of the base and of the
change (research_graph's code-check lookup, decorators and body included); no caller is followed. A CodeRef whose
file the change deletes or moves is touched (`removed with its file`, `its file moved to ...`).

When the index is older or newer than the base, the diff from the indexed commit also holds what the default branch
changed in those files since: those symbols count as touched too, and a note says so (`brain index` the repo).

## The code map

`brain code-map` resolves each active CodeRef of the project's stores to its node in the code index, as the code
layer's design (2026-10-17, §3.7) drew it:

| CodeRef | GitNexus |
|---|---|
| `<repo>` | the indexed repo, named after its folder |
| the path, `src/<path>` else `<path>` | a `File` node's `filePath` |
| a top-level name | a `Class` or `Function` no other definition encloses, else a `Variable` (an assignment) |
| `A.b` | a member of class `A` (its `HAS_METHOD` and `HAS_PROPERTY` edges) |
| a symbol the index does not hold | unresolved; its `File` stands in |

It writes `<BRAIN_HOME>/code-map/<project>.json` (derived and machine-local, never written into a store) and prints,
per repo, the indexed commit, the CodeRefs resolved and the coverage: symbols with a CodeRef over all symbols
(`Class`, `Function`, `Method`), files with a CodeRef over the indexed files; then each CodeRef that does not resolve
and why. Exit 1 when GitNexus does not answer (nothing written), 2 when no stack declares `index:`. `brain impact`
builds the same map in memory for the changed repo.

The map lives with the code index in the brain package, not in research_graph: research_graph never calls a service
(the core runs without one), and the stack, its MCP client and the indexed commits are the code index's.
