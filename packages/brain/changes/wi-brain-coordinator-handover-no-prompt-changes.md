section: Changes

- `guard.sh` without a Python that imports brain, the floor off, refuses `set_remote_control` and
  `set_session_permission_mode` and asks the card for `archive_session` (it let them through to the card before): the
  owner's allow rules never pass them unguarded. The guard's tool matcher gets a 30 s timeout (10 before), its git
  calls 3 s each: a hook Claude Code kills lets the call through. A machine with a locked floor runs
  `brain floor lock --apply` again for the new matcher.
