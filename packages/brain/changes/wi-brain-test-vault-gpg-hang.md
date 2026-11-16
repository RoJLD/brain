section: Fixes

- The test suite no longer waits forever on a real gpg key generation: `test_vault` bounds it (120 s, in a thread)
  and skips the test with its reason when gpg's agent or entropy never answers (`wi-brain-test-vault-gpg-hang`);
  `test_handover` no longer fails when pytest's temporary folder holds the pid it searches for, such as
  `pytest-4242` (`wi-brain-test-handover-basetemp`).
