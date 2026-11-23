"""A stand-in for the xerj binary (tests/test_xerj.py): it answers with xerj's recorded output (this folder), records
each call's arguments and the environment variables the engine must set, and can be down, slow or answer garbage.
Its state is the JSON file named by FAKE_XERJ_STATE: mode (ok, down, slow, garbage), exit, autoindex (a file here)."""

import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
WATCHED = ("XERJ_DISABLE_FEEDBACK", "XERJ_NO_AUTOSTART", "HF_HUB_OFFLINE")


def main() -> int:
    state_file = Path(os.environ["FAKE_XERJ_STATE"])
    state = json.loads(state_file.read_text(encoding="utf-8"))
    args = sys.argv[1:]
    state.setdefault("calls", []).append({"args": args, "env": {k: os.environ.get(k) for k in WATCHED}})
    state_file.write_text(json.dumps(state), encoding="utf-8")
    mode = state.get("mode", "ok")
    if mode == "slow":
        time.sleep(30)
        return 0
    if args[:1] == ["autoindex"]:
        sys.stderr.write((HERE / state.get("autoindex", "autoindex-completed.txt")).read_text(encoding="utf-8"))
        return int(state.get("exit", 3))
    if args[:1] == ["search"]:
        if mode == "down":
            sys.stderr.write("xerj search: query failed against http://127.0.0.1:9200/bxalpha-*: connection refused\n")
            return 1
        if mode == "garbage":
            sys.stdout.write("<html><body>502 Bad Gateway</body></html>\n")
            return 0
        sys.stdout.write((HERE / "search.json").read_text(encoding="utf-8"))
        return 0
    if "--detach" in args:
        if mode == "down":
            sys.stderr.write("error: Address already in use (os error 10048) binding 127.0.0.1:9200\n")
            return 1
        sys.stdout.write("xerj: node started in the background (pid 4242)\n  url       http://localhost:9200\n"
                         "  stop      taskkill /PID 4242\n  It keeps running after this terminal closes.\n")
        return 0
    sys.stderr.write(f"error: unknown arguments {args}\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
