section: Added

- `brain lot check [SESSION] [--branch B]... [--keep B]... [--repo-dir D]... [--scratch GLOB]... [--lot NAME]
  [--offline] [--json]` (`wi-brain-lot-close-check`, `brain.lotcheck`): whether a finished lot's session can be
  archived, read only: from the desktop app's file of the session, each worktree on its branches clean, each branch
  merged (its PR, or the default branch holds it) or kept on purpose, and pushed; « ready to archive » with what to
  remove (worktrees, branches, scratch folders), else what is left. The archive itself stays the app's tool.
