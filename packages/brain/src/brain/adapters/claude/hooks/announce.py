"""Hook entry point, run by announce.sh as ``python -I announce.py <event>`` (standard library only).

``-I`` keeps the user's site-packages and PYTHONPATH out; the plugin root is put on the path for the brain package.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brain.decisions import hook_main  # noqa: E402

sys.exit(hook_main(sys.argv[1:]))
