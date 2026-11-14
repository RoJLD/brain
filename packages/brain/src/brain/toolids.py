"""Stable tool ids for the usage counters (wi-brain-rule-usage; spec 2026-11-01 context engine §12, spec 2026-11-06
tooling scopes §4.4): one id per tool whatever the form a source names it in, so that a transcript's Skill call and
its Read of the same SKILL.md, or a transcript's ``mcp__docs__search`` and the OpenTelemetry export's ``mcp_tool``
with its server and tool names, count as one tool. Standard library only: the token ledger's scan imports it.

  skill    ``plugin:name`` for a plugin's skill, ``name`` for a user's or a project's: a Skill call's ``skill``, a
           slash command (``<command-name>``, Claude Code's own commands left out), the path of a SKILL.md
           (``.../plugins/<plugin>/skills/<name>/SKILL.md``, the plugin cache's ``.../plugins/cache/<marketplace>/
           <plugin>/<version>/skills/<name>/SKILL.md``, ``~/.claude/skills/<name>/SKILL.md``) a Read or an Agent's
           prompt names (spec 2026-11-03 external kits §2.1);
  rule     a Rule node's id (``rule-<slug>``) a session cites, or an instruction file it loads or reads (CLAUDE.md,
           AGENTS.md, a ``rules/*.md``, the memory index): its path relative to the session's folder, ``memory/<file>``
           for the auto-memory, ``~/.claude/<path>`` for the user's;
  command  a brain command, ``brain <command> [<subcommand>]``, never its arguments (brain's options before the command
           skipped, ``python -m brain`` too);
  hook     ``<event>:<matcher>`` as Claude Code names a hook's run (``PreToolUse:Bash``), an MCP tool's matcher as
           ``mcp_tool`` (the export's name);
  mcp      ``mcp__<server>__<tool>``;
  guard    the guard that refused (brain.guards.GUARDS, ``usage`` for the usage governor), read from the refusal's
           text when the guards ledger does not say it.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

KINDS = ("skill", "rule", "command", "script", "mcp", "tool", "hook", "guard", "plugin", "scheduled")

_SKILL_MD = re.compile(r"([^\s\"'`<>|*?]*?)[\\/]skills[\\/]([A-Za-z0-9_.:-]+)[\\/]SKILL\.md\b")
# Claude Code's own slash commands: not skills
BUILTIN_COMMANDS = frozenset({
    "add-dir", "agents", "bashes", "branch", "bug", "clear", "compact", "config", "context", "copy", "cost", "doctor",
    "effort", "exit", "export", "fast", "feedback", "help", "hooks", "ide", "init", "install-github-app",
    "keybindings", "login", "logout", "mcp", "memory", "migrate-installer", "model", "output-style", "permissions",
    "plugin", "plugins", "pr-comments", "privacy-settings", "quit", "release-notes", "rename", "resume", "rewind",
    "sandbox", "skills", "statusline", "stats", "status", "tasks", "terminal-setup", "theme", "todos", "upgrade",
    "usage", "vim"})
RULE_ID = re.compile(r"(?<![\w-])rule-[a-z0-9]+(?:-[a-z0-9]+)*(?![\w-])")
RULE_FILES = frozenset({"claude.md", "agents.md", "claude.local.md"})

# --- brain commands (brain.adoption reads the registry's units from them) ---
SEGMENT = re.compile(r"[;&|\n]+|\$\(|`")
BRAIN = re.compile(r"(^|[\\/])brain(\.exe)?$", re.I)
OPTIONS = ("--root", "--project", "--store")   # brain's options that take a value, before the command
QUOTED = re.compile(r"\"[^\"\n]*\"|'[^'\n]*'")
PREFIXES = {"&", "sudo", "time", "exec", "nohup", "call", "do", "then", "else", "{", "("}
_WORD = re.compile(r"^[a-z][a-z0-9-]*$")


def _command(words: list[str]) -> tuple[str, list[str]] | None:
    """(brain's command word, the words after it): brain's options before it skipped, those that take a value
    (--root, --project, --store, or an abbreviation argparse accepts) with their value."""
    i = 0
    while i < len(words):
        w = words[i]
        if w.startswith("--") and "=" not in w and len(w) > 2 and any(o.startswith(w) for o in OPTIONS):
            i += 2
        elif w.startswith("-"):
            i += 1
        else:
            return w, words[i + 1:]
    return None


def brain_words(command: str) -> list[tuple[str, str]]:
    """(command, subcommand or '') of each brain command a shell line runs (``brain [options] <command> [<sub>]``,
    the program ``brain`` or ``brain.exe`` by any path, or ``python -m brain``) at the start of a part of the line,
    after an assignment or a prefix (``&``, ``sudo``); a quoted text is one word (a commit message that names a command
    runs none), and from the first heredoc on the line is left out. The subcommand is a word, never an argument's
    value: the registry (brain.adoption.typed) says whether it is one."""
    if not isinstance(command, str):
        return []
    text = QUOTED.sub(lambda m: re.sub(r"[;&|`\n]|\$\(", " ", m.group(0)), command.split("<<", 1)[0])
    return [hit for seg in SEGMENT.split(text) if (hit := _brain_segment(seg.split()))]


def _brain_segment(words: list[str]) -> tuple[str, str] | None:
    """(command, subcommand or '') of one part of a shell line when it runs brain, else None."""
    while words and (words[0].lower() in PREFIXES or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0])):
        words.pop(0)
    if len(words) > 2 and words[0].lower() in ("python", "python3", "py") and words[1:3] == ["-m", "brain"]:
        words = words[2:]
    if not words or not BRAIN.search(words[0].strip("'\"")):
        return None
    parts = _command([w.strip("'\"") for w in words[1:]])
    if parts is None or not _WORD.match(parts[0]):
        return None
    sub = next((w for w in parts[1][:1] if not w.startswith("-")), "")
    return parts[0], sub if _WORD.match(sub) else ""


def brain_command(command: str) -> list[str]:
    """``brain <command> <subcommand>`` per brain command of a shell line, as words (brain.adoption maps them to the
    registry's units: a word that is an argument falls back to its command)."""
    return [f"brain {c} {s}".rstrip() for c, s in brain_words(command)]


# --- skills ---

def _plugin_of(parts: list[str]) -> str:
    """The plugin a skills folder belongs to, from the folders above it: ``plugins/<plugin>/skills`` (a repo, a
    marketplace) or ``plugins/cache/<marketplace>/<plugin>/<version>/skills`` (Claude Code's plugin cache)."""
    low = [p.lower() for p in parts]
    if len(low) >= 2 and low[-2] == "plugins":
        return parts[-1]
    for i in range(len(low) - 1, 0, -1):
        if low[i] == "cache" and low[i - 1] == "plugins" and len(parts) >= i + 4:
            return parts[i + 2]
    return ""


def skill_of_path(path: str) -> str:
    """The skill id of a SKILL.md path ('' when the path is not one)."""
    m = _SKILL_MD.search(str(path or ""))
    return _skill_id(m) if m else ""


def _skill_id(m: re.Match) -> str:
    parts = [p for p in re.split(r"[\\/]+", m.group(1)) if p]
    plugin = _plugin_of(parts)
    name = m.group(2)
    return f"{plugin}:{name}" if plugin and ":" not in name else name


def skills_in(text: str) -> list[str]:
    """The skill ids of every SKILL.md path a text names (an Agent's prompt), each once."""
    return list(dict.fromkeys(_skill_id(m) for m in _SKILL_MD.finditer(str(text or ""))))


def slash_skill(name: str) -> str:
    """The skill id of a slash command (``/kit:close-item``), '' for Claude Code's own commands."""
    n = str(name or "").lstrip("/")
    return "" if not n or n.lower() in BUILTIN_COMMANDS else n


# --- rules ---

def rule_ids(text: str) -> list[str]:
    """The Rule node ids a text cites (``rule-git-prs``), never a fragment of a longer id (``wi-x-rule-usage``)."""
    return RULE_ID.findall(str(text or ""))


def claude_dir() -> str:
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return os.path.expanduser(env) if env else os.path.join(os.path.expanduser("~"), ".claude")


def _norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(p)) if p else ""


def is_rule_file(path: str) -> bool:
    """An instruction file: CLAUDE.md, AGENTS.md, CLAUDE.local.md, a ``rules/*.md``, the auto-memory's files."""
    p = str(path or "").replace("\\", "/")
    name = p.rsplit("/", 1)[-1].lower()
    return name in RULE_FILES or (name.endswith(".md") and ("/rules/" in p.lower() or _memory_file(p) != ""))


_MEMORY = re.compile(r"(?:^|[\\/])projects[\\/][^\\/]+[\\/]memory[\\/](.+)$")


def _under_home(raw: str) -> str:
    """The path relative to Claude Code's user folder ('' when it is not under it)."""
    full, home = _norm(raw), _norm(claude_dir())
    if not home or not (full == home or full.startswith(home + os.sep)):
        return ""
    return os.path.relpath(os.path.normpath(raw), os.path.normpath(claude_dir())).replace("\\", "/")


def _memory_file(p: str) -> str:
    """The auto-memory file a path names (``~/.claude/projects/<folder>/memory/<file>``), '' when none."""
    rel = _under_home(p)
    m = _MEMORY.search(rel) if rel else re.search(r"[\\/]\.claude[\\/]projects[\\/][^\\/]+[\\/]memory[\\/](.+)$", p)
    return m.group(1).replace("\\", "/") if m else ""


@lru_cache(maxsize=256)
def project_root(cwd: str) -> str:
    """The root an instruction file's id is relative to: the nearest folder at or above ``cwd`` that holds ``.git``
    (a file in a worktree), else ``cwd``; '' for none."""
    if not cwd:
        return ""
    here = Path(cwd)
    for d in (here, *here.parents):
        if (d / ".git").exists():
            return str(d)
    return cwd


def rule_file(path: str, cwd: str = "") -> str:
    """An instruction file's id: relative to ``cwd``, the project's root (``CLAUDE.md``, ``.claude/rules/x.md``),
    ``memory/<file>`` for the auto-memory, ``~/.claude/<path>`` for the user's, ``~/<path>`` for another file under
    the home folder, else its full path: never its bare name, so another project's CLAUDE.md is never this one's."""
    raw = str(path or "")
    mem = _memory_file(raw)
    if mem:
        return f"memory/{mem}"
    home = _under_home(raw)
    if home:
        return f"~/.claude/{home}"
    if cwd and os.path.isabs(raw):
        try:
            rel = os.path.relpath(raw, cwd)
        except ValueError:   # another drive
            rel = ""
        if rel and not rel.startswith(".."):
            return rel.replace("\\", "/")
    if os.path.isabs(raw):
        try:
            under = os.path.relpath(raw, os.path.expanduser("~"))
        except ValueError:   # another drive
            under = ""
        if under and not under.startswith(".."):
            return "~/" + under.replace("\\", "/")
        return raw.replace("\\", "/")
    return raw.replace("\\", "/")


# --- hooks, MCP tools, guards ---

def hook_id(name: str) -> str:
    """``<event>:<matcher>`` as Claude Code names a hook's run; an MCP tool's matcher is ``mcp_tool``."""
    ev, sep, matcher = str(name or "").partition(":")
    if matcher.startswith("mcp__"):
        matcher = "mcp_tool"
    return f"{ev}:{matcher}" if sep else ev


def mcp_id(server: str, tool: str) -> str:
    return f"mcp__{server}__{tool}" if server and tool else ""


def plugin_of_tool(kind: str, tid: str) -> str:
    """The plugin a skill (``plugin:name``) or an MCP tool of a plugin's server (``mcp__plugin_<plugin>_<server>__x``)
    belongs to; '' when none."""
    if kind == "skill" and ":" in tid:
        return tid.split(":", 1)[0]
    if kind == "mcp" and tid.startswith("mcp__plugin_"):
        rest = tid[len("mcp__plugin_"):].split("__", 1)[0]
        return rest.split("_", 1)[0]
    return ""


_REFUSAL = re.compile(r"\bhook error: (?:\[[^\]\n]*\]: )?[\w.-]+ (usage )?guard: ", re.I)
# The words each guard's refusal says (brain.guards, brain.governor), the first match wins; a refusal they miss is
# counted as ``guard`` (unknown) and the replay (brain usage --kind guard --json, ``misses``) counts it.
GUARD_WORDS = (
    ("attribution", re.compile(r"AI attribution", re.I)),
    ("public", re.compile(r"is a public repo|cannot trust the configuration", re.I)),
    ("secrets", re.compile(r"looks like a secret", re.I)),
    ("markers", re.compile(r"conflict marker", re.I)),
    ("branches", re.compile(r"the branch name .* fits none", re.I)),
    ("production", re.compile(r"production checkout", re.I)),
    ("third-party", re.compile(r"third-party kit", re.I)),
    ("power", re.compile(r"TOPO-2|the Brain writes to the cluster", re.I)),
    ("merges", re.compile(r"\bstale\b|behind (?:its|the) base|not merged", re.I)),
    ("owner", re.compile(r"'s alone|security-settings|override is|lifts the usage guard|chain root", re.I)),
)


def refusal_guard(text: str) -> str:
    """The guard a refused tool call's result names ('' when the result is no guard's refusal): ``usage`` for the
    usage governor, else the guard its words say, else ``guard``."""
    head = str(text or "")[:600]
    m = _REFUSAL.search(head)
    if not m:
        return ""
    if m.group(1):
        return "usage"
    reason = head[m.end():]
    return next((g for g, rx in GUARD_WORDS if rx.search(reason)), "guard")
