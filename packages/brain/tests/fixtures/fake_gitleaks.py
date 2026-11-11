"""A stand-in for gitleaks in the session archive's tests (gitleaks is not installed everywhere): the same command
line (``dir FOLDER`` or ``detect --no-git --source FOLDER``, ``--exit-code N``, ``--report-format json
--report-path FILE``). It reports each line holding the marker FAKELEAK, with gitleaks' File and StartLine.

$FAKE_GITLEAKS changes it: ``fail`` exits 126 (a broken gitleaks), ``old`` refuses ``dir`` as an older gitleaks does,
``sticky`` reports line 1 of every file whatever it holds (a finding that does not go away), and ``log=FILE``
appends each call's subcommand to FILE."""

import json
import os
import sys
from pathlib import Path

MARK = "FAKELEAK"


def main(args: list[str]) -> int:
    mode = os.environ.get("FAKE_GITLEAKS", "")
    if mode.startswith("log="):
        with open(mode[4:], "a", encoding="utf-8") as fh:
            fh.write(args[0] + "\n")
    if mode == "fail":
        print("error: something broke", file=sys.stderr)
        return 126
    if args[0] == "dir":
        if mode == "old":
            print('Error: unknown command "dir" for "gitleaks"', file=sys.stderr)
            return 1
        folder = args[1]
    elif args[0] == "detect" and "--no-git" in args:
        folder = args[args.index("--source") + 1]
    else:
        return 2
    code = int(args[args.index("--exit-code") + 1])
    report = args[args.index("--report-path") + 1]
    found = []
    for f in sorted(Path(folder).iterdir()):
        for i, line in enumerate(f.read_text(encoding="utf-8").split("\n"), 1):
            if (mode == "sticky" and i == 1) or MARK in line:
                found.append({"File": str(f), "StartLine": i, "RuleID": "fake", "Secret": "REDACTED"})
    Path(report).write_text(json.dumps(found), encoding="utf-8")
    return code if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
