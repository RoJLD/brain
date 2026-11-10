section: Changes

- Finished sessions archive themselves (`wi-brain-archive-after-merge`). The close-item procedure's step 5 says the
  session that merges its own PR archives itself once its after-merge steps are done (the main checkout pulled, the
  backlog ticked, the journal note written, its report given: the archive is its last act), the owner's standing
  authorization standing for their yes; a coordinator archives its children as soon as a report says merged and
  verified, without asking again; never another running session (the self-archive is the one mid-turn archive
  allowed, the final tool call of the merging session's turn) or one with uncommitted, unmerged or unverified work;
  and the owner's app setting `auto_archive_inactive_days = 7` is the token-free net, which the owner sets and no session
  changes. `brain brief` gains an « After the merge » section with the same clauses (`brain.brief.AFTER_MERGE`;
  config.json `brief.after_merge` replaces them, `[]` drops the section), and the generic rules template counts the
  archived session in its definition of done. Tests check that the procedure, the brief and the template keep saying
  it.
