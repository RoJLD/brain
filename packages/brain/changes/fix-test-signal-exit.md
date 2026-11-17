section: Fixes

- `brain test --changed`: a pytest run killed by a signal (a negative exit code on POSIX) counted as a pass, the
  worst code being taken with `max()` against 0; it is now 128 + the signal (`brain.targeted.exit_code`), so neither
  the targeted tests nor the merge queue's step can pass on a killed run.
