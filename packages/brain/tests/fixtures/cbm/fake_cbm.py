"""A stand-in for codebase-memory-mcp v0.12.1 in the tests: its CLI's ``config list`` and ``config set``, and its
stdio MCP server answering each tool with the real answer recorded in answers.json (scrubbed paths), the fixture's
project name replaced by the one the call names.

FAKE_CBM_STATE: a JSON file holding {"settings": {...}, "calls": [...], "mode": ""} (settings missing: CBM's
defaults, UI and watcher on). Its mode: "" answers; "slow" never answers a tool call; "garbage" answers a tool call
with a line that is not JSON; "crash" ends on a tool call; "error:<tool>" answers that tool as an error.
FAKE_CBM_ANSWERS: another answers file (the tests' own detect_changes over their repo).
"""

import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
STATE = Path(os.environ["FAKE_CBM_STATE"])
DEFAULTS = {"auto_index": "false", "auto_watch": "true", "watcher_enabled": "true", "ui_enabled": "true",
            "ui_port": "9749"}
FIXTURE_PROJECT = "brain-wt-0f3c9a21"


def state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(s: dict) -> None:
    STATE.write_text(json.dumps(s), encoding="utf-8")


def config(args: list[str]) -> int:
    s = state()
    settings = {**DEFAULTS, **s.get("settings", {})}
    if args[:1] == ["list"]:
        print("Configuration:")
        for k, v in settings.items():
            print(f"  {k:<25} = {v:<10}")
        return 0
    if args[:1] == ["set"] and len(args) == 3:
        s.setdefault("settings", {})[args[1]] = args[2]
        s.setdefault("sets", []).append(args[1:])
        save(s)
        return 0
    print("usage: config <list|get|set|reset>", file=sys.stderr)
    return 2


def answer(name: str, arguments: dict) -> dict:
    answers = json.loads(Path(os.environ.get("FAKE_CBM_ANSWERS") or HERE / "answers.json").read_text(encoding="utf-8"))
    if name == "index_status" and arguments.get("project") == "nope":
        name = "index_status_missing"
    if name not in answers:
        return {"content": [{"type": "text", "text": f"unknown tool {name}"}], "isError": True}
    text = json.dumps(answers[name]["result"])
    project = arguments.get("project") or arguments.get("name")
    if project:
        text = text.replace(FIXTURE_PROJECT, project)
    return json.loads(text)


def serve() -> int:
    for line in sys.stdin:
        msg = json.loads(line)
        if "id" not in msg:
            continue
        s = state()
        mode = s.get("mode", "")
        if msg["method"] == "initialize":
            res = json.loads((HERE / "answers.json").read_text(encoding="utf-8"))["initialize"]
        elif msg["method"] == "tools/call":
            name, arguments = msg["params"]["name"], msg["params"].get("arguments") or {}
            s.setdefault("calls", []).append([name, arguments])
            save(s)
            if mode == "slow":
                time.sleep(60)
            if mode == "garbage":
                print("Segmentation fault (not JSON)", flush=True)
                continue
            if mode == "crash":
                return 3
            res = answer(name, arguments)
            if mode == f"error:{name}":
                res = {"content": [{"type": "text", "text": json.dumps({"error": "project not found or not indexed"})}],
                       "structuredContent": {"error": "project not found or not indexed"}, "isError": True}
        else:
            res = {}
        print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": res}), flush=True)
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    sys.exit(config(args[1:]) if args[:1] == ["config"] else serve())
