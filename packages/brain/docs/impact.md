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
3. **The CodeRefs.** The code map joins each touched symbol and each caller to the CodeRefs that name it; a file's
   CodeRef is touched by any change to the file, and a symbol the index does not place (an assignment it keeps no
   node for, a file it does not index) is looked up by the AST of both sides.
4. **The graph.** The nodes relying on those CodeRefs, by research_graph's reliance (`implemented_by`, `part_of`,
   `depends_on`, ...): features, their parent features, the quant layers. Around them: the Doc sections that document
   them or name a changed file, the Test modules that test them or cover the touched code and the CI jobs that run
   those, the ADRs and SDRs linked to them (the current one when a decision was superseded), their specs, the open
   items that deliver them and the DDRs pending on those items.

## The checklist

```
== impact brain/brain: main@933b331..worktree, 4 file(s) changed
symbols (GitNexus, index at 933b331): 5 touched in 2 file(s), 5 caller(s)
CodeRefs touched (1):
  code:brain:src/research_graph/code_layer.py  file
checklist:
[ ] features whose status may change (1):
    feat-brain-research-graph (have): implemented by code:brain:src/research_graph/code_layer.py; check it still holds
[ ] docs to update (0 section(s) in 0 file(s)):
[ ] ADRs and specs to re-read (1):
    adr-2026-11-02-le-moteur-des-graphes-...: Le moteur des graphes devient le paquet public research-graph ...
[ ] tests to run (52):
    pytest packages/brain/tests/test_alerts.py ... tests/test_research_graph_code_layer.py
    CI: .github/workflows/ci.yml::brain, .github/workflows/ci.yml::brain-linux, .github/workflows/ci.yml::test
    and 14 wider test module(s) of these features, covering none of the touched code (--json: wider_tests)
[ ] open items that deliver these features (0):
touched symbols no CodeRef names (4; the graph does not see them): packages/brain/src/brain/cli.py::cmd_brief, ...
```

- **Features**: a planned or partial feature may move (`brain features set`); a feature that has it should still
  hold.
- **Docs**: the sections that document a node relying on the code, or that name a changed file (a section of a doc
  the change already edits says `changed here`).
- **Tests**: the modules whose covered files meet the touched code (the changed files and the touched CodeRefs',
  a caller's included), the modules the relying nodes are `tested_by` that say nothing of what they cover, and the
  test files the change adds or edits. A `tested_by` module covering none of the touched code is one of the
  features' wider tests, counted apart. The `tested_by` edges are those `brain sync` derives (the links of the docs
  and tests, and, once it is built, `wi-brain-test-links-auto`'s from imports and coverage).
- **Touched symbols no CodeRef names**: code the graph does not see; a CodeRef on them (`brain features link --code`)
  brings them into the next impact.

## Without GitNexus

When the GitNexus stack does not answer, the repo is not indexed, or its indexed commit is not in this checkout, the
impact is at the file level and its second line says so and what to run:

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
