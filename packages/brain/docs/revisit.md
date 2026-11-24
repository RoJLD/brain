# The Revisit-if report

Every ADR ends with a **Revisit if**: when its decision should be looked at again. Nothing watched it, so a trigger
could be met for weeks before anyone noticed. `brain adr revisit` reads the triggers from the ADRs' prose, at zero
token, and lists those already **met** or **lapsed**, each with its evidence. It writes nothing: the decision log is
never edited, and no field is added to it. `brain.revisit`, `wi-brain-adr-revisit-report`.

```bash
brain adr revisit                 # the ADRs in force with a trigger met or lapsed, the newest triggers first
brain adr revisit --all           # also those a later ADR already reviewed
brain adr revisit --today 2026-03-01 --json
```

It exits 0: it is a report, never a refusal.

## What it reads

The « Revisit if » field of each ADR still in force, written as a label (`**Revisit if.**`) or a sentence
(`Revisit if: ...`), in every decision log of the project. An ADR a `supersedes` edge reaches, or whose node is
superseded, is skipped; so is a field left `TODO`.

| Kind     | Read in the prose                                                    | State                                    |
|----------|----------------------------------------------------------------------|------------------------------------------|
| `node`   | an id of the graph (item, milestone, feature, rule, DDR)             | `met` when done, reached, have, retired, answered, integrated or archived; `lapsed` when dropped |
| `wave`   | a wave milestone by its id, `wave s9`, `vague s9`, a bare `s9`, or the release it shipped as (`0.6.0`) | `met` when reached (closed) |
| `date`   | a day `YYYY-MM-DD` after the ADR's own; a span counted from the ADR's day: « after a month », « in its first month », « après deux semaines », « dans 3 mois » | `lapsed` once past |
| `config` | a dotted key of the project's `config.json` (`floor.refuse`)         | `met` when a commit after the ADR's day changed its value |

A node, wave or key closed or changed **on or before** the ADR's own day is not a trigger: the ADR was written knowing
it. A node's closing day is its dated prop (`done: "<day> ..."`, `dropped`, `reached`, as `brain item close` writes
them), a DDR's the day of its answer in its record, else, for an item or a milestone, the commit that closed it. A
node whose day is unknown (a feature, a rule) is kept, and its evidence says so. A day or a span still in the future
is not shown. A key is read from `config.json` as git holds it, at the last commit on or before the ADR's day and at
each commit after; a word that no version of the file has as a key (`transcript.py`) is not one.

Prose and a parser cover only part of the triggers: a judgement (« the guard refuses a launch the owner wanted ») is
not read, and stays the session's to watch. The premises as graph data (`wi-brain-decision-premises`) are the next
step.

## Closing a revisit

A flagged ADR is **reviewed** once a later ADR names it by its id, dated on or after its newest trigger: it leaves the
report (still counted; `--all` shows it, with the ADRs that reviewed it). So a revisit is closed by writing what was
looked at: a reversal (`brain adr new --reverses ID`, which supersedes it) or a plain ADR whose text cites its id.

## Where it shows

- `brain resume`: a section after the decisions, the first few flagged ADRs with their first trigger.
- `brain digest`: the ADRs whose triggers were met or lapsed in the window (a day known), with those triggers; its
  `--json` carries them under `revisit`.
- `brain.revisit.related(report, refs, words)`: the flagged ADRs a subject touches (a trigger's ref, or words of
  their title and Revisit if), the source a token-free `brain spec context` reads (`wi-brain-spec-build-path`).

## The JSON (a public contract)

`v` 1; keys are only added. `v, today, logs, adrs` (in force), `with_revisit`, `flagged`, `reviewed` (a count),
`counts` (triggers by kind). Each flagged ADR: `id, day, title, file, line, revisit` (the field's text), `triggers`,
`reviewed_by` (ids; empty unless `--all`). Each trigger: `kind, ref, state, day` (`''` unknown), `evidence`. A kind a
later engine adds is shown as it is by a reader that does not know it.
