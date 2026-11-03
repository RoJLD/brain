# Lessons: the registry and the loop

The brain keeps what finished work taught as nodes of the project's graph, and asks for them at every item's close.
Everything here runs at zero token: the commands read the graph, the token ledger (`brain usage`), the guards ledger
and the action records under `$BRAIN_HOME/ledger`.

## The Lesson node

A Lesson lives in `nodes/lessons.yaml` of the project's graph store, its edges in `edges/lessons.yaml`. The schema
(`brain init`'s default, or a store's own `schema.yaml`) declares the type, its statuses and the props it requires:

```yaml
node_types: [..., Lesson]
edge_types: [..., learned_from, enforced_by, led_to]
statuses: [..., open, enforced, resolved, regressed, archived]
layers:
  lessons: [Lesson]
status_by_type:
  Lesson: [open, enforced, resolved, regressed, archived]
required_props:
  Lesson: [trigger, anti_pattern, check]
```

`required_props` is research-graph's: `research_graph check` refuses a node of that type without each prop, or with
it empty.

| prop | what it says |
|---|---|
| `trigger` | the situation the lesson applies to |
| `anti_pattern` | what went wrong |
| `check` | how one tells it happened again: a command in backticks when one can, a test, a guard's refusal |
| `severity` | high, medium (default) or low; a high one turns into a proposal at its first occurrence |
| `signal` | the friction signal it shows in: merges, guards, tests, waits, tokens, owner, rework, other |
| `prs` | the PRs it was seen in (`my-brain #185, #194`) |
| `rule` | an iron rule of a repo it restates (`Σ-NAME`) |
| `seen`, `learned`, `last_seen` | how many times, the first and the last day |
| `why_not_script` | for a lesson no script can check: why |

Its edges: `learned_from` the item, ADR, DDR or session it came from; `enforced_by` the hook, test or workflow that
checks it; `led_to` the item that fixes it. Its status: `open` (nothing checks it), `enforced` (something does),
`resolved` (the fix made it impossible), `regressed` (it recurred after a fix), `archived`.

## Commands

```bash
brain lesson add les-brain-stale-main --title "Merge resolution against a stale main" \
  --trigger "merging main into a branch while other PRs land" \
  --anti-pattern "the resolution used the local main and dropped a merged item" \
  --check '`git diff origin/main -- notes/journal.md` removes no line of another PR' \
  --signal merges --from wi-brain-generated-merge --pr "my-brain #185, #194"
brain lesson seen les-brain-stale-main --from wi-brain-other --pr "my-brain #230"
brain lessons --follow
brain lesson rules --all
brain lint lessons [--propose]
brain retro wi-brain-other [--record --note "..."]
brain retro --wave F
```

- **Dedup.** `add` compares the new lesson's words (title, trigger, anti-pattern) with every known lesson's (the
  rules linter's measure: the Jaccard index of their content words, or the share of the shorter found in the other).
  Past 0.5 it refuses and names the close one: mark it `seen`, or pass `--new` for a lesson that only sounds alike.
- **Recurrence.** `seen` adds one occurrence, the PR, and a `learned_from` edge to a new node. A lesson seen twice
  (once if severe) with no open item fixing it, or one that recurs after its fix (it was enforced or resolved, or an
  item it led to is done; it turns regressed), files an item proposal: `wi-<slug>` for `les-<slug>`,
  `priority_proposed` P1 if severe else P2, `led_to` from the lesson, the fix to choose in the order a script, a hook,
  a template, a rule last. An open item whose title is close to the lesson's (the same measure) is linked `led_to`
  instead of a new one. The ideation board (an Idea node instead of an item) will take this over once it exists.
- **The lineage.** `brain lessons --follow` prints each lesson, where it was learned, what it led to (the item, its
  status and PR), what enforces it and whether it recurred since its fix; then the friction per item by ISO week,
  from the retros recorded on the items. It should fall.
- **The iron rules.** `brain lesson rules` lists the rule ids (`Σ-NAME`, `Sigma-NAME`) cited in the tracked Markdown
  of each registered repo (`git ls-files`, nothing written), with the files and lines that cite them and the lessons
  whose `rule` names them. A repo without a checkout on this machine is listed as missing.
- **The linter.** `brain lint lessons`: an open or regressed lesson nothing enforces is a guard candidate when its
  check names a command (scripts before rules: a test, a hook or `brain check` can run it; `--propose` files its item
  when none is open), else a prose lesson that should say `why_not_script`.

## The retro

`brain retro ITEM` is the close-item procedure's retro step. The item's sessions are those `brain usage` credits to
it (the sessions that closed it, named its PRs, its id in their title or brief). It prints:

| line | from |
|---|---|
| merges | merge, rebase and pull commands, merge conflicts (the token ledger) |
| guards | the guards ledger's refusals in those sessions, by guard and check |
| tests | failed test runs (pytest, Pester, a `test` command that failed), failing-command streaks |
| waits | time waiting for a message, compactions |
| tokens | the cost against the recorded estimate (else the backtest's), the context peak against the brief's budget |
| the owner | questions to the owner and the time until the answers |
| PRs | the item's PRs and the pushes to their branch after they were opened and before they merged (rework) |

Its friction points are the conflicts, guard refusals, failed test runs, failing streaks, rework pushes and
compactions, plus one when the cost is over its estimate by more than x1.5. The known lessons of the signals that
fired come next, then five questions: what cost the most, what a script, a hook or a template would have
prevented, what to keep, a lesson for the registry or a known one seen again, what to change in the next brief.
`--record` writes `props.retro` on the item (`2026-11-03 friction=9 merges=11 conflicts=4 ...`) and the `--note`
lines in `props.retro_notes`.

`brain retro --wave W` is the coordinator's deep retro at a wave's end or hand-over: every item whose `props.wave`
names the wave, with its friction and signals, the totals, the items with no session yet and the lessons learned
from the wave's items.
