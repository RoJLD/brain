"""The guards in the MCP server (wi-brain-mcp-guards; spec-brain-multi-agent-connector §4, MA-3): every tool call
passes the engine's guard checks before it runs, because Cursor, Grok and other clients run none of Claude Code's
hooks. Nothing ships on the assumption that the client behaves.

Each tool (brain.mcpserver.Tool) states what its call does as the payload a PreToolUse hook would get (its
``effect``): a ``brain`` command is a Bash call of that command in the brain's root, a note written is a Write of its
path. :func:`judge` runs, in order:

1. **the tool's own declaration**: a write tool with no effect is refused (a guard that exists only as a Claude hook
   is ported, or its tool is refused);
2. **the owner's gestures** (:data:`OWNER_GESTURES`, and brain.gestures' list, every one strict here): the ``brain`` commands only the owner runs (answering a
   decision, closing their queue's actions, a schedule installed, the machine's token or vault keys made, the engine
   updated or installed, stacks started, a bundle applied, an arming flag) are refused whatever the tool;
3. **the secret scan of a write's arguments**: a string argument of a write tool that matches a secret pattern is
   refused (nothing is written);
4. **the engine's guards** (brain.guards.refusals, strict): production checkouts, the owner's never-grantable
   categories, power and cluster, third-party kits, attribution, the public and secrets checks, conflict markers,
   branch names, on the effect's payload. Strict: a check that fails to judge the call refuses it, where a hook lets
   it through (a hook never breaks a session; a server never trusts its client).

``BRAIN_GUARD_ALLOW`` lifts nothing here: a client's configuration can set the server's environment (a stdio
server's ``env``), so the owner's override stays Claude Code's; the rest of that environment is the owner's
configuration (docs/mcp.md, « The guards »). An effect the guards do not read (an agent, a session) is refused, and a
command hidden behind an abbreviated global option is refused too. A refusal reaches the client as a tool error naming
the guard, and goes to the guards ledger (``<BRAIN_HOME>/ledger/guards-<month>.jsonl``) with the tool as
``mcp:<name>`` and the client as its session. Every answer then passes the secret scan (brain.mcpserver.clean): no
tool result carries a key's shape.

The Claude Code hooks, and where each one stands for an MCP client (docs/mcp.md, « The guards »): guard.sh is ported
(4); governor.sh (sessions and agents) has no tool here, so none can start one; readhint.sh, inject-rules.sh and the
SessionStart hooks give context, served as resources and the initialize instructions; capture.sh and budget.sh
measure Claude's own sessions.
"""

from __future__ import annotations

import shlex
from typing import NamedTuple

from . import gestures, guards, paths, secretscan

# brain's own commands only the owner runs, as their leading words (after the global options); "--arm" anywhere; and
# every gesture of brain.gestures.GESTURES, the engine's one list (this one is wider: a client is trusted less)
OWNER_GESTURES: tuple[tuple[str, ...], ...] = (
    ("decision", "answer"), ("queue", "done"), ("schedule", "install"), ("ipc",), ("vault",),
    ("identity",), ("update",), ("init",), ("up",), ("down",), ("bundle", "apply"), ("permissions", "grant"),
    ("session-archive",),
)
GLOBAL_VALUES = ("--root", "--project", "--store")
JUDGED = {"Bash", "PowerShell", *guards.EDIT_TOOLS}   # the effects brain.guards.refusals reads


class Refusal(NamedTuple):
    guard: str
    check: str
    reason: str


def words(argv: list[str]) -> list[str]:
    """A brain command's words past its global options (``--root X``, ``--project=P``)."""
    out, i = [], 0
    while i < len(argv):
        w = argv[i]
        if w in GLOBAL_VALUES:
            i += 2
            continue
        if w.split("=", 1)[0] in GLOBAL_VALUES and "=" in w:
            i += 1
            continue
        out.append(w)
        i += 1
    return out


def _arm(word: str) -> bool:
    """``--arm`` or a prefix argparse would expand to it (``--ar``, ``--a``), with or without ``=value``."""
    opt = word.split("=", 1)[0]
    return len(opt) >= 3 and opt.startswith("--") and "--arm".startswith(opt)


def owner_gesture(argv: list[str]) -> str:
    """The owner's gesture a brain command is, as text, else ''. An option before the command that is not a global
    option spelled out (``--proj=P``, which argparse expands) is refused too: the command could not be read."""
    ws = words(argv)
    if ws and ws[0].startswith("-"):
        return f"a command behind the option {ws[0].split('=', 1)[0]} (spell --root, --project, --store in full)"
    if any(_arm(w) for w in ws):
        return "an arming flag"
    for gesture in OWNER_GESTURES:
        if tuple(ws[:len(gesture)]) == gesture:
            return "brain " + " ".join(gesture)
    g = gestures.match(["brain", *ws])   # the engine's one list (wi-brain-owner-only-registry), strict or not
    return g.name if g else ""


def bash_payload(root, argv: list[str]) -> dict:
    """The payload a PreToolUse hook would get for ``brain --root=ROOT ARGV`` run in the brain's root."""
    command = shlex.join(["brain", f"--root={root}", *argv])
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(root)}


def write_payload(root, path) -> dict:
    return {"tool_name": "Write", "tool_input": {"file_path": str(path)}, "cwd": str(root)}


def judge(tool, args: dict, effect: dict | None, argv: list[str] | None) -> Refusal | None:
    """The first refusal of a tool call, else None. ``effect``: the call as a hook payload (None: it has none);
    ``argv``: the brain command it runs, if any. Any error while judging refuses (fail closed)."""
    try:
        if tool.kind != "read" and effect is None:
            return Refusal("mcp", "undeclared", f"the write tool {tool.name} declares no effect the guards can judge")
        if effect is not None and effect.get("tool_name") not in JUDGED:
            return Refusal("mcp", "undeclared", f"the guards judge shell calls and file writes only, not "
                                                f"{effect.get('tool_name')!r} (an agent or a session starts none here)")
        gesture = owner_gesture(argv) if argv is not None else ""
        if gesture.startswith("a command behind"):
            return Refusal("mcp", "options", f"{gesture}: it could not be read")
        if gesture:
            return Refusal("owner", "gesture", f"{gesture} is the owner's alone")
        if tool.kind != "read":
            for key, value in sorted(args.items()):
                hits = secretscan.scan_lines(value) if isinstance(value, str) else []
                if hits:
                    return Refusal("secrets", "argument", f"{key}, line {hits[0][0]}, matches a secret pattern "
                                                          f"({hits[0][1]})")
        if effect is not None:
            for guard, check, reason, _request in guards.refusals(effect, strict=True):
                return Refusal(guard, check or guard, reason)
    except Exception as exc:   # a guard that cannot judge refuses
        return Refusal("mcp", "error", f"the guards could not judge the call ({type(exc).__name__})")
    return None


def record(tool, refusal: Refusal, effect: dict | None, client: dict) -> None:
    """The refusal in the guards ledger, when it exists (as a hook's); never raises."""
    try:
        if not paths.ledger_dir().is_dir():
            return
        payload = dict(effect or {}, tool_name=f"mcp:{tool.name}",
                       session_id=f"mcp:{client.get('name') or 'unknown client'}")
        guards._record(payload, refusal.guard, refusal.check, "denied", refusal.reason)
    except Exception:
        pass
