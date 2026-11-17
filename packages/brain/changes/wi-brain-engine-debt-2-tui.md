section: Fixes

- The cockpit's tests run in the CI again: its jobs install the `tui` extra (Textual 8, psutil), without which every
  `tests/test_tui*.py` was skipped, so `brain audit` measured the cockpit's modules at 0 % and three tests broke
  unseen when the frontier gained the score sort and the Size, Value and Score columns; they now expect both.
  `tests/test_ci_workflows.py` fails if a job that runs the suite stops installing Textual.
