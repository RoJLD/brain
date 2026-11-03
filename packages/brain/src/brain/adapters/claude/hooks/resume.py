"""Hook entry point, run by resume.sh as ``python -X utf8 -I resume.py <event>``.

``-X utf8``: its stdout is UTF-8 whatever the console's codepage (its stdin is read as bytes).
``-I`` keeps the user's site-packages and PYTHONPATH out; the plugin root goes first on the
path, for a plugin folder that still holds the brain package; else the interpreter's own brain (the installed engine).
The registry needs PyYAML (the brain command's venv has it); without it the hook logs the error and prints nothing.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brain.resume import hook_main  # noqa: E402

sys.exit(hook_main(sys.argv[1:]))
