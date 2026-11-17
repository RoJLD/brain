section: Fixes

- Two tests no longer flake on a slow Windows runner: `test_filelock`'s heartbeat test reads a virtual clock (a
  lock's `expires` is cut to the second, so two renewals within one second were equal) and treats a read during a
  replace as no renewal; `test_vault`'s hang test starts its deadline once the fake gpg is up, so the tree kill never
  falls while the tree's last process is being created.
