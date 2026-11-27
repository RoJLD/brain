section: Fixes

- Hooks killed at their timeout under load (`wi-brain-hook-timeout-trace`; 308 kills in one machine's transcripts,
  `inject-rules` among them on 2026-11-27, which starts a session without the owner's rules):
  `inject-rules.sh` starts no process any more (each `tr`, `sed`, `awk`, `dirname` or `$(...)` cost 35 to 90 ms on
  Windows at rest, seconds under load: 1.05 s at rest before, 0.21 s after); the engine's exec events go to one file a
  day (`ledger/engine/exec-[bash-]<yyyy-mm-dd>.jsonl`; the months' files before are still read and pruned), since on
  Windows an append to a file of 5 MB or more cost every hook ~0.3 s; the timeouts are sized for a loaded machine
  (30 s for every guard and for the rules, 15 to 20 s for the hints and the start notices, 10 s for `midsession`);
  `brain alerts` raises a hook Claude Code killed at its timeout in the last 24 hours, read from the transcripts'
  `hook_cancelled` entries (`hook-timeout:<script>[-<argument>]`, error for a guard and `inject-rules`); and the
  budget watch tells a session at its first tool call when its start left no mark of the rules injection.
