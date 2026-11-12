"""The background waiter's hint (wi-brain-stuck-waiters, lesson les-brain-unbounded-background-waiter):
``hooks/waithint.sh`` at ``PreToolUse`` on Bash and PowerShell.

A session that waits for a long run with a background loop on its log (``until grep -q passed run.log; do sleep 5;
done``) keeps a live task as long as the loop runs. When the run is abandoned and its log deleted at cleanup, the loop
never ends: the session cannot be archived (the app refuses one with live work) and the loop spins until the owner
stops it by hand (wave 0.3.2, two lots). A background ``until`` or ``while`` loop with no bound gets one line of hook
context: give it a deadline (``timeout``, a counter, ``$SECONDS``), make it exit when its file or process is gone, and
stop the session's background tasks before deleting their logs or venvs.

A bound is any of: a ``timeout`` wrapper, a counter (``seq``, ``{1..N}``, ``for ((``, a numeric comparison), a clock
(``$SECONDS``, ``date +%s``, a PowerShell ``Stopwatch``, ``Get-Date``, ``AddMinutes``/``AddSeconds``, ``-Timeout``),
a process check (``kill -0``, ``ps -p``, ``pgrep``, ``/proc/``, ``Get-Process``, ``Wait-Process``, ``HasExited``) or a
file that must still be there (``[ -e FILE ] || exit``, ``[ ! -e FILE ]``, ``test -f FILE || break``, ``-not (Test-Path
FILE)``): a loop that waits for a file to appear is no bound. A ``while read`` loop ends with its input and is no wait.
A foreground loop is bounded by the tool's own timeout. Never a refusal: it prints no permission decision, only
additionalContext, and nothing at all on an error. The standard library only.
"""

from __future__ import annotations

import json
import re
import sys

LESSON = "les-brain-unbounded-background-waiter"
SHELL_TOOLS = ("Bash", "PowerShell")
LOOP = re.compile(r"(?i)(?<![\w-])(until|while)(?![\w-])")
READ_LOOP = re.compile(r"(?i)(?<![\w-])while\s+(?:IFS=\S*\s+)?read(?![\w-])")
BOUNDS = re.compile(
    r"(?ix)"
    r"(?<![\w-])g?timeout(?![\w-])|-timeout(?![\w-])"                      # a timeout wrapper or parameter
    r"|(?<![\w-])seq(?![\w-])|\{\d+\.\.\d+\}|for\s*\(\("                # a counter
    r"|-(?:lt|le|gt|ge)(?![\w-])|\(\(\s*[\w$]+\s*(?:<|>|<=|>=)"           # a numeric comparison
    r"|\$SECONDS|date\s+\+%s|stopwatch|get-date|add(?:minutes|seconds|hours)\b"   # a clock
    r"|kill\s+-0|ps\s+-p|(?<![\w-])pgrep(?![\w-])|/proc/|get-process|wait-process|hasexited"   # a process check
    r"|\[\[?\s*!\s*-[efsd]\s|(?<![\w-])test\s+!\s*-[efsd]\s"              # a file check: gone, then out
    r"|(?:\]\]?|(?<![\w-])test\s+-[efsd]\s+\S+)\s*\|\||(?:-not|!)\s*\(?\s*test-path"
)


def unbounded(command: str) -> bool:
    """Whether ``command`` holds a wait loop (until or while, not a while read) and no bound at all."""
    text = READ_LOOP.sub(" ", command or "")
    return bool(LOOP.search(text)) and not BOUNDS.search(text)


def hint(data: dict) -> str:
    """The line for a background shell call whose loop has no bound, else ''."""
    if data.get("tool_name") not in SHELL_TOOLS:
        return ""
    inp = data.get("tool_input") or {}
    if not isinstance(inp, dict) or inp.get("run_in_background") is not True:
        return ""
    if not unbounded(str(inp.get("command") or "")):
        return ""
    return ("brain waithint: this background wait loop has no deadline. If what it waits for is abandoned (its log "
            "deleted, its process gone), it never ends, and the session keeps live work and cannot be archived. "
            "Bound it: `timeout 1800 bash -c 'until ...; do sleep 5; done'`, or exit when its file or process is "
            "gone (`[ -e run.log ] || exit 1`, `kill -0 $pid || exit 1`); stop your background tasks (TaskStop) "
            f"before deleting their logs or venvs ({LESSON}).")


def hook_main(argv: list[str], stdin=None) -> int:
    """PreToolUse hook: the hook JSON on stdin, the hint as additionalContext on stdout. Never fails."""
    try:
        raw = (stdin or sys.stdin.buffer).read()
        data = json.loads(raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw)
        out = hint(data) if isinstance(data, dict) else ""
        if out:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": out}},
                             ensure_ascii=False))
    except Exception:   # noqa: BLE001 (a hint never breaks a call)
        return 0
    return 0
