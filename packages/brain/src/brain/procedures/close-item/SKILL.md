---
name: close-item
description: Close a finished work item by the owner's definition of done - documented, tested and linked in the graph, merged and applied, ticked in the backlog, historised in the journal, session archived and worktree removed, memory updated. Use when an item, a PR or a fix asked in chat is finished, or when the user asks to close, finish, wrap up or tick an item.
argument-hint: "[item id, PR link or short description]"
---

# Close an item (definition of done)

The owner's rule (their rules for every project): an item is done only when it is documented, tested, linked in the project's graph, merged and applied,
ticked in the project's backlog, historised in its journal, its session archived and its worktree removed, and memory
updated when a durable fact changed. Walk the steps below in order for the item in `$ARGUMENTS` (or the item this
session worked on), check each one yourself, and do what is missing. Stop at the first step you cannot complete and say why.

## 0. Read the project's own procedure first

The `CLAUDE.md` of the repository the item belongs to wins over this skill. Read it and look for a closing
procedure, the backlog (graph, kanban, issue tracker, `TODO.md`), the journal and the production checkouts. Where it
says more or says otherwise, follow it. Then the project's addendum, when this skill's folder has one: a
`<project>.md` beside this file, the owner's own (it says which repositories it covers), read in full.

When the project has no backlog or no journal, say so in the report rather than inventing one.

## 1. Documented, tested and linked

In the item's PR, every change of behaviour, command, option, configuration, setup or data updates the docs that
describe it: README, `docs/`, runbook, CHANGELOG of a released package, the script's own help. Read the PR diff
(`gh pr diff <n>`) and list what changed against what was documented. Missing documentation goes into the same PR
before merge, or a follow-up PR if it is already merged.

The same PR carries a test for the changed behaviour whenever one can be written, and the links of what it touches
in the project's graph (its item, spec and ADR, and code references for new modules). Missing ones are added the
same way.

Then the scout (rule R8): run `brain [--project P] audit --diff` in the PR's worktree (`--diff A..B` once merged).
Exit 1: fix each NEW and LEFT line in this PR, a catch-up test checking the behaviour the spec or ADR expects. DEFER
lines go to the debt item named (the line prints its `brain item add` when the item is missing). PENDING is not
asked. Exit 2: report why. Run it again until it exits 0. Its structure lines (`size.*`, `complexity.*`, `dep.adr`,
`shortcut.marker`, `symptom.cause`) are fixed the same way, or answered in the PR body, passed with `--pr-body FILE`:
a `Root cause:` line for a symptom fix, a `Justified: <unit>: <reason>` line for the others.

## 2. Merged and applied

- The PR is merged with `gh` after local verification (tests, linters), in dependency order for stacked branches,
  with no AI attribution in its commits or body. After merging the base into the branch, `brain merge-check` (where
  the `brain` command serves the project) says whether the resolution lost a line or a node of a fresh base. Check: `gh pr view <n> --json state,mergedAt,mergeCommit`.
- Applied: where the change runs somewhere (a production checkout, a scheduled task, an installed copy), that place
  is updated the project's way (for example `git pull --ff-only` in the production checkout, then the project's setup
  command) and checked on its next real run when there is one.
- The owner decides repository visibility, new scheduled tasks or services, and anything touching money, keys or
  accounts: ask instead of applying those.

## 3. Ticked in the backlog

Mark the item done where the project tracks its work, with the PR (repository and number) and the date and a
one-line outcome. New follow-ups become new items, not notes in the old one. Run the backlog's own regeneration and
check commands when it has them. In the same PR as the work when possible.
Where the `brain` command serves the project (a research_graph store registered in the brain's `projects.yaml`),
use it rather than editing the YAML: `brain [--project P] item close <id> --pr "<repo> #<n>" --outcome "..."`, then
`brain refresh`.

## 4. Historised

Add one dated entry to the project's journal (append-only: never edit a past entry): item ids, PR links, outcome,
what comes next. One entry per working day may group several items.
With the `brain` command: `brain [--project P] journal add --title "..." "line"...` for the day's first entry,
`brain journal add "line"` for more lines in it.

## 5. Session archived, worktree removed

- Archive the session that did the work once its PR is merged and verified: the owner's standing authorization covers
  it. A side session is archived by the session that started it, after that one has verified and merged the branch.
  Never archive a session with unmerged or unverified work. In the Claude desktop app, use its session-management
  archive tool; elsewhere, tell the owner which session to archive.
- Remove the item's git worktree and local branch: `git worktree list`, then `git worktree remove <path>` without
  `--force` (first remove links such as junctions that point into a production checkout), then
  `git branch -d <branch>` once it is merged. If git refuses, report why instead of forcing.

## 6. Memory

Update Claude's memory only when a durable fact changed (a host, a version, a path, what waits on the owner), not for
what the repository or its history already records.

## Report

End with one line per step - done, already done, not applicable (why) or blocked (what is missing) - a line
`Scout: audit --diff exit N, M fixed, K deferred`, and the links: PR, journal entry, backlog item.
