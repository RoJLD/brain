"""Hook entry point, run by governor.sh as ``python -I governor.py`` (brain.governor: the usage-enforce hook).

``-I`` keeps the user's site-packages and PYTHONPATH out; the plugin root goes first on the
path, for a plugin folder that still holds the brain package; else the interpreter's own brain (the installed engine).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brain.governor import main  # noqa: E402

sys.exit(main())
