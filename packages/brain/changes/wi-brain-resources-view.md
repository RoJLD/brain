section: Added

- `brain resources [--by machine|project|session|container|store] [--quick] [--json]`: what runs for the Brain costs
  this machine, at zero token (`brain.resources`, one sampler): the CPU, the committed memory, the free space of the
  Brain's drives and the temporary folder, the network's throughput up and down; each Claude Code CLI's memory and
  process tree tied to its session (its command line, else its folder in the desktop app's sessions), with its tokens
  today; the brain commands and the test suites running; the containers (`docker stats --no-stream`, bounded; Docker
  absent, down, slow or answering garbage is a state) and the stack that declares each; the stores' sizes under
  BRAIN_HOME, the transcripts and Temp; the tokens today, the quota's pace and the room left in session-hours; WARN at
  85 %, CRITICAL at 95 %. The cockpit's header carries the same sampler's band at its right (CPU, RAM, disk, network,
  tokens today, quota and pace), read by a worker every 3 s without starting a program; a click on it or `9` opens
  the detail until the resources tab comes. psutil joins the `tui` extra for the process rows; without it the
  machine's totals come from the standard library. The test suite's `-n auto` keeps one worker per CPU thread with
  psutil installed (xdist would count physical cores) unless `BRAIN_TEST_WORKERS` or
  `PYTEST_XDIST_AUTO_NUM_WORKERS` says otherwise (`wi-brain-resources-view`).
