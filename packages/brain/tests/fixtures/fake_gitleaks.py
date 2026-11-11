"""A stand-in for gitleaks in the session archive's tests (gitleaks is not installed everywhere): the same command
line (``dir FOLDER`` or ``detect --no-git --source FOLDER``, ``--exit-code N``, ``--report-format json
--report-path FILE``). It reports each line holding the marker FAKELEAK, with gitleaks' File and StartLine.

$FAKE_GITLEAKS changes it: ``fail`` exits 126 (a broken gitleaks), ``old`` refuses ``dir`` as an older gitleaks does,
``sticky`` reports line 1 of every file whatever it holds (a finding that does not go away), and ``log=FILE``
appends each call's subcommand to FILE. Like gitleaks, it skips a line marked gitleaks:allow unless it is given
--ignore-gitleaks-allow, and finds nothing when GITLEAKS_CONFIG is set (an owner's narrowed rules)."""

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
    if os.environ.get("GITLEAKS_CONFIG"):   # an owner's narrowed config would hide everything
        Path(report).write_text("[]", encoding="utf-8")
        return 0
    honour_allow = "--ignore-gitleaks-allow" not in args
    for f in sorted(Path(folder).iterdir()):
        with open(f, encoding="utf-8", newline="") as fh:   # lines by \n alone, as gitleaks counts them
            lines = fh.read().split("\n")
        for i, line in enumerate(lines, 1):
            if honour_allow and "gitleaks:allow" in line:  # gitleaks:allow
                continue
            if (mode == "sticky" and i == 1) or MARK in line:
                found.append({"File": str(f), "StartLine": i, "RuleID": "fake", "Secret": "REDACTED"})
    Path(report).write_text(json.dumps(found), encoding="utf-8")
    return code if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
