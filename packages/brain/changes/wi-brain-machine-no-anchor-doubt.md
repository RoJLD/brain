section: Fixes

- A machine whose OS install id cannot be read (no machine-id file) no longer keeps its `no-anchor` identity doubt
  forever, holding the memory export: the owner confirms that home with `"<name>": {"local_id": "..."}` under
  config.json `hosts` (the `local_id` of its `machine.json`, which the doubt prints; new optional key `local_id` in the
  config schema), bound to that one home, so a config.json shared by every machine vouches for no other machine that
  takes the name. An unreadable id is never a false `moved` any more (nothing to compare), and a home first seen with
  an anchor, or a name declared with one, stays a doubt. An MSYS or Cygwin Python reads `MachineGuid` through
  `/proc/registry` and gives the native Python's anchor. `brain doctor` says when a machine runs confirmed without an
  anchor (`wi-brain-machine-no-anchor-doubt`).
