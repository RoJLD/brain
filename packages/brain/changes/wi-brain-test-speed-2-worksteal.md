section: Changes

- **The parallel tests steal work** (`wi-brain-test-speed-2`). `pytest -n auto` with no `--dist` now schedules with
  pytest-xdist's `worksteal` (`tests/conftest.py`; pytest-xdist 3.5 or later, pinned in the CI): an idle worker takes
  tests still queued on a busy one. Measured on a 16-thread Windows machine, alternating runs: the idle
  worker-seconds at the end of the run fell from about 400 to about 125 and the workers' utilisation rose from 88 %
  to 96 %, with the wall time unchanged (233-236 s against 236-247 s). On that machine the suite is bound by process
  creation (some 10,400 git calls, about 55 git starts per second at most), so busier workers wait longer per git call.
  `--dist load` gives the old scheduling back.
