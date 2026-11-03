"""Hook entry point, run by guard.sh as ``python -X utf8 -I guard.py`` (the PreToolUse guards of brain.guards).

``-X utf8``: its stdout is UTF-8 whatever the console's codepage (its stdin is read as bytes).
``-I`` keeps the user's site-packages and PYTHONPATH out; the plugin root goes first on the
path, for a plugin folder that still holds the brain package; else the interpreter's own brain (the installed engine).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brain.guards import main  # noqa: E402

sys.exit(main())
