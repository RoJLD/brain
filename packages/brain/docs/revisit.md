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

It exits 0: it is a report, never a refusal (1 only on a malformed `--today`). `--today D` moves the day the dates
and spans are checked against; the graph and `config.json` are read as they are now.

## What it reads

The « Revisit if » field of each ADR still in force, written as a label (`**Revisit if.**`) or a sentence
(`Revisit if: ...`), in every decision log of the project. An ADR a `supersedes` edge reaches, or whose node is
superseded, is skipped; so is a field left `TODO`.

| Kind     | Read in the prose                                                    | State                                    |
|----------|----------------------------------------------------------------------|------------------------------------------|
| `node`   | an id of the graph (item, milestone, feature, rule, DDR)             | `met` when done, reached, have, retired, answered, integrated or archived; `lapsed` when dropped |
| `wave`   | a wave milestone by its id, `wave s9`, `vague s9`, `(s9)`, or the release it shipped as (`0.6.0`); a bare `s9` is not read (« an s3 bucket ») | `met` when reached (closed) |
| `date`   | a day `YYYY-MM-DD` after the ADR's own; a span counted from the ADR's day: « after a month », « in its first month », « après deux semaines », « au bout d'un mois », « dans 3 mois » | `lapsed` once reached (today included) |
| `config` | a dotted key of the project's `config.json` (`floor.refuse`)         | `met` when its value now differs from its value on the ADR's day |

A node, wave or key closed or changed **on or before** the ADR's own day is not a trigger: the ADR was written knowing
it. A node's closing day is its dated prop (`done: "<day> ..."`, `dropped`, `reached`, as `brain item close` writes
them), a DDR's the day of its answer in its record, else, for an item or a milestone, the commit that closed it. A
node whose day is unknown (a feature, a rule) is kept, and its evidence says so. A day or a span still in the future
is not shown. A key is read from `config.json` as git holds it, at the last commit on or before the ADR's day and at
each commit after, along git's first-parent history (a change merged from a branch is dated by its merge); a version
that is not a JSON object is skipped, and a key that holds a mapping changes with any of its sub-keys. The evidence
gives the value on the ADR's day, the value now and the commit that first changed it. A word that no version of the
file has as a key (`transcript.py`) is not one.

`met` says what the trigger names is closed, never that the condition the prose states holds: an id read in a
consequence clause (« then wi-x ») or a release a trigger had to come before is read the same. The report says which
ADRs to read again; the reader judges.

Prose and a parser cover only part of the triggers: a judgement (« the guard refuses a launch the owner wanted ») is
not read, and stays the session's to watch. The premises as graph data (`wi-brain-decision-premises`) are the next
step.

## Closing a revisit

A flagged ADR is **reviewed** once a later ADR names it by its id, dated on or after its newest trigger: it leaves the
report (still counted; `--all` shows it, with the ADRs that reviewed it). So a revisit is closed by writing what was
looked at: a reversal (`brain adr new --reverses ID`, which supersedes it) or a plain ADR whose text cites its id.

## Where it shows

- `brain resume`: a section after the decisions, the first few flagged ADRs, each with its newest trigger.
- `brain digest`: the ADRs whose triggers were met or lapsed in the window (a day known), with those triggers, those a
  later ADR reviewed included (a past window reads the same later); its `--json` carries them under `revisit`.
- `brain.revisit.related(report, refs, words)`: the flagged ADRs a subject touches (a trigger's ref, or words of
  their title and Revisit if), the source a token-free `brain spec context` reads (`wi-brain-spec-build-path`).

## The JSON (a public contract)

`v` 1; keys are only added. `v, today, logs, adrs` (in force), `with_revisit`, `flagged`, `reviewed` (a count),
`counts` (triggers by kind). Each flagged ADR: `id, day, title, file, line, revisit` (the field's text), `triggers`,
`reviewed_by` (ids; empty unless `--all`). Each trigger: `kind, ref, state, day` (`''` unknown), `evidence`. A kind a
later engine adds is shown as it is by a reader that does not know it.
