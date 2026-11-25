section: Fixes

- `brain decision answer ID CHOICE --dry-run` and `--batch ... --dry-run` wrote the answer: the flag reached `ask`
  and `--captured` only. They now run every check, print the DDR as it would be written (`--batch`: each answer) and
  write nothing (`wi-brain-decision-answer-dry-run`).
- An answer recorded by hand (`brain decision answer ID CHOICE`, `--batch`) now settles the question tool's capture of
  that DDR in the recorded ledger: the same answer marked recorded, another one captured before it retired
  (superseded). `--captured --dry-run` listed such captures again, and `--captured` would have written them from the
  default branch while the answer by hand waited on an unmerged branch (`wi-brain-answer-marks-capture-recorded`).
