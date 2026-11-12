section: Added

- **`BRAIN_TEST_WORKERS`** (`wi-brain-test-speed-2`): the number of workers `pytest -n auto` starts for the brain
  suite (`tests/conftest.py`, xdist's `pytest_xdist_auto_num_workers`); unset, one per core as before, and an
  explicit `-n N` wins. Measured on a 16-thread Windows machine, three runs each with the machine shared: 16 workers
  229/308/281 s, 24 workers a crash at start (a worker's platform query timed out with 24 starting at once) then
  262/237 s, 32 workers 259/257/246 s: no clear gain, so the default stays.
