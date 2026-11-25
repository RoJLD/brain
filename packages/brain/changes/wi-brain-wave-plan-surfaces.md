section: Changes

- `brain wave plan` cuts lots by weighted surfaces: an item's strong entries (what its title, `props.where`,
  `props.size_reason` or `props.files` name, a `brain.x` module read as `brain/x.py`, a narrow feature's CodeRefs) join
  a lot; weak ones (a spec document, a context prop, a broad feature's or its module's CodeRefs) meeting each other are
  listed as « Possible conflicts » and join nothing, so a spec document every item cites no longer folds a wave into
  one lot. The files the repos' last 100 first-parent commits mostly add to count hot (« Hot by history »); a lot over
  8 items or with a `depends_on` chain over 3 is split at its most shared file (« Lots split », a merge-order note); a
  broad item (more than 30 strong entries, or a standing debt item: `props.audit_repo` or `props.standing`) is a lot of
  its own, last when nothing waits on it. The JSON gains `possible`, `cuts` and `history`; a lot, `broad`.
  `brain next`'s lots leave the history aside (one `git log --numstat` a repo on every call).
