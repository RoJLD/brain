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
    - src/net.py                                  # a file (in any repo of the project)
    - docs/retries/                               # a folder: it ends with /
    - tests/test_retry_*.py                       # a glob: * and ? within a folder, ** across folders
    - code:demo:src/retry.py::backoff             # a CodeRef (a symbol: precise once GitNexus says which changed)
  since: 2026-11-12
```

Why a file and not the ADR's own fields: the decision log is append-only and its ADR nodes are generated from it, so
an old ADR can be neither edited nor given props that last; a DDR's record is the owner's answer, not the code's map.
The pins file is the one place both kinds of decision are pinned, by one command, which rewrites the file (a hand
comment does not survive; a file holding entries that are not pins is refused until fixed by hand).

```bash
brain adr pin adr-2026-11-01-retries-stay-at-four --touches src/net.py --holds "retries stay at 4"
brain adr pin adr-2026-11-01-retries-stay-at-four --touches code:demo:src/retry.py::backoff   # touches added
```

- The decision is an ADR or an SDR in force, or a DDR answered (status answered, integrated or archived): a pending
  DDR is not a decision yet, a superseded decision is pinned through the one that supersedes it.
- `holds` is never edited: `brain adr pin` refuses a different line. Changing the invariant is an override: a new ADR,
  `brain adr new --reverses ID` (an ADR's id, or an answered DDR's: its title is then yours to give), pinned in its
  turn. `touches` may grow as the code moves; a path is relative to its repo, with `/`, never `./`.

## What reads the pins

- **`brain impact --diff`**: its checklist lists each pinned decision the change touches, with its date, its line
  and what it hits (`pins` in `--json`).
- **`brain review check HEAD --pr N`** (or `--body FILE`, `--base REF`): exit 1 while a pinned decision the change
  touches is not answered by a line of the PR body:
  - `Keeps <id>` for a decision in force (a reason after a colon or a dash is welcome);
  - `Overrides <id>: <why>` for a decision a later ADR supersedes (in the decision log at the head): write the new
    ADR first, in the same PR or before it; its reason is required.
  A line may start with a list mark (`-`, `*`, `1.`), name several ids (`Keeps a, b`), quote them in backquotes or
  bold; lines inside fenced code or an HTML comment do not count, and one id both kept and overridden blocks.
  Without a body, the pins touched are listed and the stamp alone decides; a pin that cannot be read is a note then.
- **`brain merge-ready N`**: its `pins` check (the last one) asks the same of the PR's body.
- **`brain check`** warns, once a project, on a pin of an unknown, pending or superseded decision, a malformed row
  (no `holds`, a `holds` on several lines, no `touches`, a touch that is neither a relative path nor a CodeRef), an
  entry that is not a pin, and a decision pinned twice.

When the pins file lives in the changed repo (a brain's own PR), the gate reads the pins at the merge base, with the
head's new ones, and the decision logs at the head: a PR cannot drop its own pin (a row it edits or removes counts as
touched) nor hide the REVERSAL it adds. The review and the merge gate work at the file level: a pinned CodeRef with a
symbol counts as soon as its file changes; only `brain impact`, with GitNexus's index, narrows it to the symbols the
change touches.
