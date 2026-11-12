section: Fixes

- One unified-diff reader for the engine (`brain.diffs`): `brain impact`, the commit guards (secrets, conflict
  markers, the public check), `brain check --public --history`, the digest, the forecast and the changed-items reader
  read a hunk's lines by its counts, so a content line starting `-- ` or `++ ` is never a header, a name with a space
  loses git's TAB, a C-quoted name is unquoted, and the user's `diff.noprefix`, `diff.mnemonicPrefix`,
  `diff.relative`, `diff.suppressBlankEmpty`, `diff.interHunkContext`, colour, external diff and textconv no longer
  reshape what they read; a merge's combined diff counts as added only the lines new against every parent
  (`wi-brain-diff-parser`).
