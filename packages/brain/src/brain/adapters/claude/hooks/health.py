"""Hook entry point, run by health.sh as ``python -I health.py <event>``.

``-I`` keeps the user's site-packages and PYTHONPATH out; the plugin root is put on the path for the brain package.
The registry needs PyYAML (the brain command's venv has it); without it the hook logs the error and prints nothing.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brain.stacks import hook_main  # noqa: E402

sys.exit(hook_main(sys.argv[1:]))
