section: Added

- **`BRAIN_TEST_WORKERS`** (`wi-brain-test-speed-2`): the number of workers `pytest -n auto` (or `-n logical`) starts
  for the brain suite (`tests/conftest.py`, xdist's `pytest_xdist_auto_num_workers`), the strict form of xdist's
  `PYTEST_XDIST_AUTO_NUM_WORKERS`, which it wins over; unset, xdist decides as before, and an explicit `-n N` wins.
  Measured on a 16-thread Windows machine without psutil (`-n auto` = 16), three runs each with the machine shared: 16
  workers 229/308/281 s; 24 workers a crash at start on one run (a worker's platform query timed out with 24 starting
  together), then 262/237 s; 32 workers 259/257/246 s. No clear gain, so nothing changes by default.
