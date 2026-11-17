section: Fixes

- The test suite no longer waits forever on a real gpg call: `test_vault` runs each key generation in a child
  Python process, bounded (120 s for the test's key generations together); on the deadline it kills that
  process as a tree (gpg and its agent: `taskkill /T` on Windows, its process group on POSIX), stops the agents of
  the gpg homes that appeared during the call and removes them, and skips the test with its reason;
  an error other than gpg's own surfaces as
  itself (`wi-brain-test-vault-gpg-hang`). `test_handover` no longer fails when pytest's temporary folder holds the
  pid it searches for, such as `pytest-4242`, its paths quoted for sh included (`wi-brain-test-handover-basetemp`).
