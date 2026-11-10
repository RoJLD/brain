"""brain: the owner's records (DDR, SR, AR), their zero-token capture, and token-free graph commands.

The capture path (``brain.capture``, run by the brain's hooks) uses the standard library only. The commands that
read or write YAML (``brain record``, ``brain item``) import PyYAML when they run.
"""

__version__ = "0.3.1"

import time as _time

_started = (_time.time(), _time.perf_counter())  # brain.selftime: a command is timed from the engine's import
