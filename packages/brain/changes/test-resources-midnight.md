section: Fixes

- `tests/test_resources.py` no longer fails when a run crosses midnight UTC: the module took its ledger day from the
  clock at import while `Sampler.tokens_today()` read the clock again, so the fixtures' tokens fell on yesterday.
  The sampler's clock is now frozen for the module, and a new test moves it across midnight with the ledger
  unchanged (`wi-brain-engine-debt`).
