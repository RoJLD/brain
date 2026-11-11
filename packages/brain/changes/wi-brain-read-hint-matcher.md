section: Changes

- The read hint starts only on a likely hit (`wi-brain-read-hint-matcher`): its hooks in the core plugin's
  `hooks.json` are split per tool, each Read, Bash and PowerShell hook gated by an `if` condition naming the brain
  files it hints about (`Read(//**/journal.md)`, `Bash(*decisions.md*)`...), so a call that names none starts no
  bash at all; Grep's path is a folder or a glob, which a permission rule cannot match, so a Grep call still starts
  it. Before, every such call started bash (on one machine, 4,854 of 4,981 runs in a week stopped at its fast path,
  about 85 ms each on Windows). The conditions only narrow: the bash fast path and the Python hint decide as before,
  and the hint stays opt-in (`config.json` `hints.read`); `brain sync` renders the new `hooks.json`.
