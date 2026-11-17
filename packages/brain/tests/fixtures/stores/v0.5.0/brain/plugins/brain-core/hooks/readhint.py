"""Hook entry point, run by readhint.sh as ``python -X utf8 -I readhint.py PreToolUse`` (brain.readhint).

``-X utf8``: its stdout is UTF-8 whatever the console's codepage (its stdin is read as bytes).
``-I`` keeps the user's site-packages and PYTHONPATH out; the plugin root goes first on the
path, for a plugin folder that still holds the brain package; else the interpreter's own brain (the installed engine).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from brain.readhint import hook_main
except ImportError:  # an engine older than its hooks: no hint, the call goes through
    sys.exit(0)
try:
    from brain.selftime import hook  # its exec event, and an error event for what it catches
except ImportError:  # an engine older than its hooks: untimed
    sys.exit(hook_main(sys.argv[1:]))
sys.exit(hook("hook readhint", hook_main, sys.argv[1:]))
