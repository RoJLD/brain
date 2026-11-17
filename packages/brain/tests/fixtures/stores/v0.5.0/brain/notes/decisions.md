# Decisions (ADR log)

Append-only: one dated entry per decision, never rewritten; a reversal is a new entry titled
`REVERSAL: <original title>`. `research_graph sync --write` gives each `## YYYY-MM-DD — Title` heading an ADR node
(`adr-<date>-<slug>`), and `research_graph check` fails while a heading has no node or an empty body.
