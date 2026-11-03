"""Hook entry point, run by capture.sh as ``python -I capture.py <event> [git|gh]`` (standard library only).

``-I`` keeps the user's site-packages and PYTHONPATH out; the plugin root is put on the path for the brain package.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brain.capture import main  # noqa: E402

sys.exit(main(sys.argv[1:]))
