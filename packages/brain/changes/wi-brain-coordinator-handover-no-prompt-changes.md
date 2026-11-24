section: Changes

- `guard.sh` without a Python that imports brain refuses `set_remote_control` and `set_session_permission_mode` and
  asks the card for `archive_session` (it let them through to the card before): the owner's allow rules never pass
  them unguarded. A machine with a locked floor runs `brain floor lock --apply` again for the new matcher.
