# Decision pins

(`wi-brain-decision-pins`; the code is `brain/pins.py`. The idea comes from a public MIT project's « learnings with
touches », rewritten; no code copied.)

A decision is easy to undo by accident: the code it governs changes, the review looks at the code, and nobody re-reads
the ADR. A pin ties a decision to the code it governs, so that a change to that code says, in its PR, whether it keeps
the decision or overrides it.

## The pin

A pin is one row of `pins.yaml`, beside the project's decision log (`notes/pins.yaml` by default):

```yaml
- decision: adr-2026-11-01-retries-stay-at-four   # an ADR or SDR of the project's logs, or an answered DDR
  holds: retries stay at 4                        # one line: the invariant the decision keeps
  touches:                                        # what it governs
    - src/net.py                                  # a file
    - docs/retries/                               # a folder (ends with /)
    - tests/test_retry_*.py                       # a glob
    - code:demo:src/retry.py::backoff             # a CodeRef (a symbol: precise once GitNexus says which changed)
  since: 2026-11-12
```

Why a file and not the ADR's own fields: the decision log is append-only and its ADR nodes are generated from it, so
an old ADR can be neither edited nor given props that last; a DDR's record is the owner's answer, not a place for the
code's map. The pins file is the one place both kinds of decision are pinned, by one command.

```bash
brain adr pin adr-2026-11-01-retries-stay-at-four --touches src/net.py --holds "retries stay at 4"
brain adr pin adr-2026-11-01-retries-stay-at-four --touches code:demo:src/retry.py::backoff   # touches added
```

- The decision is an ADR or an SDR that no REVERSAL supersedes, or a DDR answered (answered, acked, archived): a
  pending DDR is not a decision yet, a superseded ADR is pinned through its REVERSAL.
- `holds` is never edited: `brain adr pin` refuses a different line. Changing the invariant is an override: a new ADR
  (`brain adr new --reverses ID`), pinned in its turn. `touches` may grow as the code moves.

## What reads the pins

- **`brain impact --diff`**: its checklist lists each pinned decision the change touches, with its date, its line
  and what it hits (`pins` in `--json`).
- **`brain review check HEAD --pr N`** (or `--body FILE`, `--base REF`): exit 1 while a pinned decision the change
  touches has no line in the PR body saying either
  - `Keeps <id>` (a reason after a colon is welcome), or
  - `Overrides <id>: <why>`, the reason required, and the REVERSAL ADR that supersedes `<id>` already in the log.
  Without a body, the pins touched are listed and the stamp alone decides.
- **`brain merge-ready N`**: its `pins` check asks the same of the PR's body (after `body`).
- **`brain check`** warns on a pin of an unknown, pending or superseded decision, a malformed row (no `holds`, a
  `holds` on several lines, no `touches`, a touch that is neither a relative path nor a CodeRef) and a decision pinned
  twice.

The review and the merge gate read the files at the file level: a pinned CodeRef with a symbol counts as soon as its
file changes. Only `brain impact`, with GitNexus's index, narrows it to the symbols the change touches.
