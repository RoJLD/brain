"""The machine's IPC token kept from a session's tool calls (wi-brain-ipc-token-read-guard): the owner guard refuses
``brain ipc otel-headers`` (brain.gestures), the one command that prints the token, and this module refuses the other
way to it, the file itself (brain.ipcauth.token_file: ``<BRAIN_HOME>/ipc/token``, or ``$BRAIN_IPC_TOKEN_FILE``).

Under config.json ``guards.refuse_token_read: true`` (off by default: a refusal this release adds), the owner guard
refuses, as its check ``token``:

- a ``Read`` of the token file, a ``Grep`` whose path is the token file, its folder or a folder of ``<BRAIN_HOME>``
  that holds it, and a tool edit (``Edit``, ``Write``, ``MultiEdit``, ``NotebookEdit``) of the token file (a session
  never chooses the machine's token either);
- a shell call (Bash, PowerShell, the Terminal panel) whose words name the token file or its folder, through every
  path the other guards see (wrappers, launchers, nested shells, cmd /c, pwsh -Command): any program but the few that
  read only a file's name or metadata (``ls``, ``stat``, ``test``, ``Test-Path``, ``Get-Item``, ``icacls``...), a
  word given as an option's value (``-Path:x``, ``--file=x``, ``if=x``, ``@x``), an input redirection (``< x``), a
  glob that matches it (``ipc/tok*``), any spelling the file system resolves to it (``..``, ``~``, variables the
  guard knows, a link, an 8.3 name, an NTFS stream suffix);
- inline code or a command substitution that names it as text (``python -c "open('.../ipc/token')"``, ``Path(h) /
  'ipc' / 'token'``, ``cat $(echo .../ipc/token)``, a .NET call), or brain.ipcauth in inline code, and over ssh any
  command that names it as text (the remote file cannot be resolved here).

A ``brain`` command is the gestures' (brain.gestures): ``brain ipc token`` reports the file and never prints it.
``BRAIN_GUARD_ALLOW=owner`` (or ``owner:token``) lifts the check for the owner. The MCP server (brain.mcpguards)
judges its effects strictly: the check is on there whatever the key, and every answer has the token's value
redacted (brain.mcpserver).

What it does not see (docs/guards.md, « The machine's token »): a script file that reads the token, a path built at
run time from pieces the guard cannot read (base64, character codes, ``os.sep`` joins), a recursive read of a folder
above the token's own beyond ``<BRAIN_HOME>`` (``grep -r x ~``), a link made earlier by a script. The token is
readable by the owner's account, which a session shares: the guard is the lock here, and it is advisory.
"""

from __future__ import annotations

import glob
import os
import re
from pathlib import Path

from . import gestures, guards, ipcauth, paths

CONFIG_KEY = "refuse_token_read"   # config.json guards.refuse_token_read: the check is on (off by default)
CHECK = "token"
READ_TOOLS = {"Read": "file_path", "Grep": "path"}
# programs that read a file's name or metadata only, never its content: they may name the token
METADATA = frozenset(("ls", "dir", "stat", "test", "[", "[[", "file", "du", "test-path", "get-item", "gi",
                      "get-childitem", "gci", "get-acl", "icacls", "cacls", "attrib", "realpath", "readlink",
                      "basename", "dirname", "cygpath", "resolve-path", "rvpa", "split-path", "echo", "printf",
                      "write-host", "write-output"))
# interpreters whose words are code: their text is read for the token's path, not only resolved as paths
INTERPRETER = re.compile(r"^(?:python[0-9.]*w?|pythonw|py|pypy[0-9.]*|ipython[0-9.]*|node(?:js)?|deno|bun|perl|"
                         r"ruby|php|rscript|lua|osascript|jshell|groovy)$")
CODE_WORD = re.compile(r"\$\(|`|::|\(|\[(?:system\.)?io\.", re.I)   # a word that computes: read as text too
SEP = r"[\s'\"`,+/\\]+"   # what joins the folder's name and the file's in text: a separator, quotes, a join's comma
GLOB = re.compile(r"[*?\[]")


def enabled(data: dict | None = None) -> bool:
    """config.json's ``guards.refuse_token_read`` (off by default)."""
    if data is None:
        from . import config
        data = config.load().data
    section = data.get("guards") if isinstance(data, dict) else None
    return isinstance(section, dict) and section.get(CONFIG_KEY) is True


def token_files() -> list[Path]:
    """The token's file as brain.ipcauth reads it, and the default one when $BRAIN_IPC_TOKEN_FILE names another."""
    out = [ipcauth.token_file()]
    default = paths.brain_home() / "ipc" / "token"
    if guards._real(default) != guards._real(out[0]):
        out.append(default)
    return out


def _protected() -> tuple[set[str], set[str]]:
    """({the token files' real paths}, {their folders' real paths})."""
    files = token_files()
    return {guards._real(f) for f in files}, {guards._real(f.parent) for f in files}


def _text_pattern() -> re.Pattern:
    """The token's folder and file names joined in text (``ipc/token``, ``'ipc', 'token'``, ``ipc\\token``)."""
    pairs = {(f.parent.name, f.name) for f in token_files()}
    alts = "|".join(rf"{re.escape(d)}{SEP}{re.escape(n)}" for d, n in pairs if d and n)
    return re.compile(rf"(?i)(?<![\w.-])(?:{alts})(?![\w.-])")


def _names(word: str, cwd: str, files: set[str], folders: set[str], literal: bool = False) -> str:
    """'file' or 'folder' when ``word`` (a path, an option's value, a glob) resolves to the token or its folder;
    ``literal``: a tool's path, which holds no variable (``token::$DATA`` is the file's stream)."""
    for cand in [word] if literal else _candidates(word):
        target = os.path.abspath(os.path.join(cwd, os.path.expanduser(cand))) if literal else guards._path(cand, cwd)
        found = glob.glob(target) if GLOB.search(cand) and not literal else [target]
        for t in found:
            real = guards._real(t)
            if real in files:
                return "file"
            if real in folders:
                return "folder"
    return ""


def _candidates(word: str) -> list[str]:
    """``word`` and what in it may be a path: an option's value (``-Path:x``, ``--file=x``, ``if=x``), a curl-style
    ``@x``, PowerShell's ``${x}``."""
    out = [word]
    m = re.match(r"^-{1,2}[\w-]+[:=](.+)$", word) or re.match(r"^\w+=(.+)$", word)
    if m:
        out.append(m.group(1))
    if word.startswith("@") and len(word) > 1:
        out.append(word[1:])
    m = re.match(r"^\$\{(.+)\}$", word)
    if m:
        out.append(m.group(1))
    return [w.strip("'\"") for w in out if w.strip("'\"")]


def _read_tool(tool: str, inp: dict, cwd: str, files: set[str], folders: set[str]) -> str:
    """What a Read or Grep call reaches of the token, else ''."""
    raw = inp.get(READ_TOOLS[tool])
    if tool == "Read" and isinstance(raw, str) and raw:
        return f"Read of {raw}" if _names(raw, cwd, files, folders, literal=True) == "file" else ""
    if tool == "Grep":
        where = guards._real(os.path.join(cwd, os.path.expanduser(raw)) if isinstance(raw, str) and raw else cwd)
        home = guards._real(paths.brain_home())
        in_home = where == home or where.startswith(home.rstrip("\\/") + os.sep)
        holds = any(f.startswith(where.rstrip("\\/") + os.sep) for f in files)
        if where in files or where in folders or (holds and in_home):
            return f"Grep in {raw or cwd}"
    return ""


def _edit_tool(tool: str, inp: dict, cwd: str, files: set[str], folders: set[str]) -> str:
    raw = inp.get(guards.EDIT_TOOLS[tool])
    if isinstance(raw, str) and raw and _names(raw, cwd, files, folders, literal=True) == "file":
        return f"{tool} of {raw}"
    return ""


def _shell(cmds, command: str, powershell: bool, cwd: str, files: set[str], folders: set[str]) -> str:
    """What a shell call does to the token, else ''."""
    text = _text_pattern()
    sub = "ps" if powershell else "bash"
    for words, d, sh, _ in guards.actions(cmds, sub, command=command):
        low = [w.lower() for w in words]
        if gestures.runs_brain(low) >= 0:
            continue   # brain's own commands: brain.gestures judges them (ipc otel-headers)
        prog = guards._prog(words[0])
        if sh == "ssh":
            if any(text.search(w) for w in words):
                return f"{' '.join(words)[:120]} over ssh (it names the token's file)"
            continue
        code = INTERPRETER.match(prog) is not None
        for w in words:
            if (code or CODE_WORD.search(w)) and (text.search(w) or (code and re.search(r"\bipcauth\b", w))):
                return f"{prog} (its code names the token's file)"
        if prog in METADATA:
            continue
        for w in words:
            kind = _names(w, d, files, folders)
            if kind:
                return f"{prog} on {w} (the token's {kind})"
    folders_seen = {d for _, d in cmds} or {cwd}
    for seg in guards.segments(command, powershell):
        for k, w in enumerate(seg[:-1]):
            if w.startswith(guards.REDIRECT) and "<" in w and not w.endswith("<<"):
                if any(_names(seg[k + 1], d, files, folders) for d in folders_seen):
                    return f"an input redirection from {seg[k + 1]}"
    return ""


def check(tool: str, inp: dict, cwd: str, cmds=None, command: str = "", powershell: bool = False,
          strict: bool = False) -> str | None:
    """The owner guard's refusal of a call that reads, copies or replaces the machine's token, else None; on only
    under config.json guards.refuse_token_read, or ``strict`` (the MCP server)."""
    if not (strict or enabled()):
        return None
    files, folders = _protected()
    if tool in READ_TOOLS:
        what = _read_tool(tool, inp, cwd, files, folders)
    elif tool in guards.EDIT_TOOLS:
        what = _edit_tool(tool, inp, cwd, files, folders)
    elif cmds:
        what = _shell(cmds, command, powershell, cwd, files, folders)
    else:
        what = ""
    if not what:
        return None
    from . import config
    return (f"{what} refused: it reaches the machine's IPC token ({ipcauth.token_file()}), which only Claude Code's "
            f"otelHeadersHelper and the Brain's services read; it is {config.owner_of()}'s (keys, config.json "
            f"guards.{CONFIG_KEY})")


def redact(obj, token: str | None = None):
    """A copy of ``obj`` (dicts, lists, strings) with the machine's token replaced wherever it appears (the MCP
    server's answers: brain.mcpserver)."""
    token = ipcauth.read() if token is None else token
    if not token:
        return obj
    if isinstance(obj, str):
        return obj.replace(token, "[the machine's IPC token, redacted]")
    if isinstance(obj, dict):
        return {k: redact(v, token) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v, token) for v in obj]
    return obj
