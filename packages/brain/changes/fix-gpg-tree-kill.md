section: Fixes

- `test_vault`'s hang test no longer flakes on a loaded Windows runner: its gpg child runs in a job object of its own
  (created suspended, put in the job, then resumed; `tests/proc_tree.py`), killed with every process it started in
  one call, and anything it left (an agent the vault did not stop) ends when the job closes. `taskkill /T` killed the
  tree leaf first from one snapshot, so the child, between its fake gpg's death and its own, started the next gpg
  call, which survived. The test checks every fake it started, by a file each holds open on Windows, not by a pid
  Windows can reuse within seconds; `test_proc_tree.py` kills a parent that restarts its child at once.
