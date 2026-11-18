section: Added

- `brain handover check` gains a `children` line: each session the checked one started, archived, detached or
  blocking (any other: the app archives a parent's side sessions with it and refuses while one works), with what a
  blocking one needs; its `predecessor` line says to archive the predecessor only once none of its children blocks,
  and lists those that do (only the session that started a child may detach it). The successor's brief says so.
  `--json` adds `children`, `blocking`, `parent_children`, `parent_blocking` and `parent_archived`; the exit code is
  unchanged (`wi-brain-handover-detach-children`).
