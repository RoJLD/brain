"""Hook entry point, run by memory.sh as ``python -X utf8 -I memory.py session-end`` (standard library only).

``-X utf8``: its stdout is UTF-8 whatever the console's codepage (its stdin is read as bytes).
``-I`` keeps the user's site-packages and PYTHONPATH out; the plugin root goes first on the
path, for a plugin folder that still holds the brain package; else the interpreter's own brain (the installed engine).
The sync itself runs detached (``brain.memory.job_argv``), never in the hook.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brain.memory import hook_main  # noqa: E402

sys.exit(hook_main(sys.argv[1:]))
