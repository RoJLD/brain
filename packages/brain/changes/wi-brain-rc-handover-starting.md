section: Fixes

- **A coordinator's successor just started gets its Remote Control at the handover** (`wi-brain-rc-handover-starting`).
  The guard's `handover-on` case (and `handover-off`'s successor test) refused a successor the outgoing coordinator
  switched on seconds after `start_session`: it had no transcript yet, so its state read `unknown`. A successor in the
  desktop app's session files, not archived, started by the caller, with a coordinator name and no transcript yet
  now counts as starting when its own app file's `createdAt` is at most 10 minutes old (`HANDOVER_START_S`); an older
  one, or one whose `createdAt` cannot be read, stays refused. Nothing else is widened (docs/guards.md, « Remote
  Control's three exceptions »).
