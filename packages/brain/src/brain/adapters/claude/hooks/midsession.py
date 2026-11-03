"""Hook entry point, run by midsession.sh as ``python -I midsession.py UserPromptSubmit`` (standard library only).

``-I`` keeps the user's site-packages and PYTHONPATH out; the plugin root is put on the path for the brain package.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brain.midsession import hook_main  # noqa: E402

sys.exit(hook_main(sys.argv[1:]))
