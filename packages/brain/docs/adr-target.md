# Checking a decision against the target

A decision that is hard to undo (a **one-way door**) is checked against what the project already plans before it is
accepted, so that it keeps the door open for a known future need instead of being reversed and migrated later. A
decision that is cheap to change (a **two-way door**: a process, a preference, a screen, a wave's composition) is
decided fast and never checked. `brain.targets`, `wi-brain-adr-target-check`.

One-way doors: a persisted format or schema, a public contract or a CLI key, a licence, a security invariant, an
identity or a key, the graph's schema.

## The two fields

A one-way-door ADR states, beside its Context, Decision, Why and Revisit if:

- **Scope**: what it covers, and up to which wave, milestone or era;
- **Target compatibility**: each future need it touches, marked `compatible`, `extension-point` (a named place where
  the need will plug in) or `to-review` (to look at again when the need comes), and what it leaves open.

```bash
brain adr new "A format for the cups" --context ... --decision ... --why ... --revisit ... \
  --scope "this lab, up to wave 0.2.0" \
  --target feat-lab-mugs=extension-point:"a key added later" --target wi-later=compatible \
  --leaves-open "the mug's size"
```

`--target ID=COMPAT[:note]` is repeatable; `ID` is a need of the register (below). Given one of `--scope` and
`--target` alone, the other is written `TODO` and said. An ADR written by hand states them as labels (`**Scope.**`,
`**Target compatibility.**`) or as sentences (`Scope: ...`, `Target compatibility: wi-x (to review at 0.2.0); ...`):
both are read. A sentence field opens a line or follows a sentence's end (« Out of Scope: » inside a sentence is not
one), its label may wrap over two lines, and a label alone on its line takes the paragraph or list after it. A need
named without a compatibility in its clause (up to a `;`, a line's end or the next need named) counts as
`to-review`. An ADR with either field is a one-way door; any other is a two-way door. A superseded ADR is not
checked.

The compatibility section says what stays open. It never designs a later phase, and no check asks it to.

## The register of future needs

Computed from the graph at each call, never written by hand (`brain adr target --needs`):

- the features still `planned`;
- the pending milestones with a trigger (`props.trigger`);
- the open items of the waves after the current one (the lowest release not closed), and of the pending eras: their
  own items and those of their pending milestones and waves, the current wave aside.

Each need keeps its source's status and its module (`props.module`). The register records; it never decides.

## The checks

`brain adr target` reads the project's decision logs and runs three advisory checks on the one-way doors (warnings,
exit 0); they are the docgraph/v1 named checks of the same ids ([docgraph.md](docgraph.md)):

- `decision.target-compat-missing`: a scope without a target compatibility (or one left `TODO`);
- `decision.review-trigger-missing`: no « Revisit if », or one left `TODO`;
- `decision.target-unreferenced`: an open need of a module the decision touches (the modules of the nodes it
  decides, `decided_by`) that its target compatibility does not cite.

The two presence checks are run on the one-way doors only: a two-way door has neither field by design. `brain
docgraph emit` adds the register (need nodes), the one-way decisions (with `door: one-way` and their
`module`), a `constrains` edge per cited need and the findings of the three checks to the brain's documentation graph;
`brain docgraph join` runs `decision.target-unreferenced` again across the joined graph, where a read project's
decisions and needs meet the brain's.
