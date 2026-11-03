"""Hook entry point, run by guard.sh as ``python -I guard.py`` (the PreToolUse guards of brain.guards).

``-I`` keeps the user's site-packages and PYTHONPATH out; the plugin root is put on the path for the brain package.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brain.guards import main  # noqa: E402

sys.exit(main())
