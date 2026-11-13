section: Fixes

- The memory sync no longer overwrites anyone's work (`wi-brain-memory-sync-safety`): a same-name note with no base is
  a conflict copy, never a replacement of `main`'s; `MEMORY.md` is never unioned nor regenerated (a divergence is a
  conflict copy, like any note); a note with a secret stays on its machine alone while the others export; a key no
  registered project, `main` or `BRAIN_MEMORY_MAP` claims is not exported, and its changes start no SessionEnd run. The
  push uses `--force-with-lease` on the machine's last push: a branch someone else pushed to is left as it is and the
  notes go to `<branch>-2`, with an alert. A PR body someone edited, or a reviewed PR, gets a comment instead of an
  edit; an older PR is closed as superseded only while its head is the machine's own push. Backups are named by their
  content's hash and never overwritten, and the new `brain memory undo KEY/NAME.md` puts back the copy an import
  replaced only while the note still holds what was imported (else it writes `<name>.undo-conflict` beside it).
