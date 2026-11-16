"""The machine's IPC token kept from a session's tool calls (wi-brain-ipc-token-read-guard): the owner guard refuses
``brain ipc otel-headers`` (brain.gestures), the one command that prints the token, and this module refuses the other
way to it, the file itself (brain.ipcauth.token_file: ``<BRAIN_HOME>/ipc/token``, or ``$BRAIN_IPC_TOKEN_FILE``).

Under config.json ``guards.refuse_token_read: true`` (off by default: a refusal this release adds), the owner guard
refuses, as its check ``token``:

- a ``Read`` of the token file, a ``Grep`` whose path is the token file, its folder or a folder of ``<BRAIN_HOME>``
  that holds it (unless its glob or type cannot match the file), and a tool edit (``Edit``, ``Write``,
  ``MultiEdit``, ``NotebookEdit``) of the token file (a session never chooses the machine's token either). Read and
  Grep reach the guard through their own hook, ``tokenguard.sh``, which brain render registers only when the key is
  on (brain.render.OPTIONAL_HOOKS);
- a shell call (Bash, PowerShell, the Terminal panel) whose words name the token file, its folder or
  ``<BRAIN_HOME>`` itself, through every path the other guards see (wrappers, launchers, nested shells, cmd /c, pwsh
  -Command): any program but the few that read only a file's name or metadata (``ls``, ``stat``, ``test``,
  ``Test-Path``, ``Get-Item``...), and those too when the call pipes or substitutes their output (``echo T | xargs
  cat``); a word given as an option's value (``-Path:x``, ``--file=x``, ``if=x``, ``@x``, ``f=@x``), in a PowerShell
  list (``'x','T'``) or joined (``Join-Path $h ipc token``, ``[IO.Path]::Combine``), an input or output redirection
  (``< T``, ``> T``), a glob that matches it, ``${NAME}`` and ``${env:NAME}``, a loopback admin share
  (``\\\\localhost\\C$\\...``) or a WSL path (``/mnt/c/...``), any spelling the file system resolves to it (``..``,
  ``~``, a link, an 8.3 name, an NTFS stream suffix);
- inline code, or a heredoc fed to an interpreter, that names the token's file as text and reads, copies or opens
  something (``python -c "open('.../ipc/token')"``, ``Path(h) / 'ipc' / 'token'``), or uses brain.ipcauth; over ssh
  any command that names it as text (the remote file cannot be resolved here).

``brain ipc ...`` is the gestures' (brain.gestures): ``brain ipc token`` reports the file and never prints it.
``BRAIN_GUARD_ALLOW=owner`` (or ``owner:token``) lifts the check for the owner. The MCP server (brain.mcpguards)
judges its effects strictly: the check is on there whatever the key; its real protection is that every answer has the
token's value redacted (brain.mcpserver).

What it does not see (docs/guards.md, « The machine's token »): a script file that reads the token, a path built at
run time from pieces the guard cannot read (base64, character codes, ``os.sep`` joins, a variable set by an earlier
call), a recursive read of a folder above ``<BRAIN_HOME>`` (``grep -r x ~``), a link made earlier by a script. The
token is readable by the owner's account, which a session shares: the guard is the lock here, and it is advisory.
"""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from . import gestures, guards, ipcauth, paths

CONFIG_KEY = "refuse_token_read"   # config.json guards.refuse_token_read: the check is on (off by default)
CHECK = "token"
READ_TOOLS = {"Read": "file_path", "Grep": "path"}
# programs that read a file's name or metadata only, never its content: they may name the token (not in a pipe)
METADATA = frozenset(("ls", "dir", "stat", "test", "[", "[[", "file", "du", "test-path", "get-item", "gi",
                      "get-childitem", "gci", "get-acl", "icacls", "cacls", "attrib", "realpath", "readlink",
                      "basename", "dirname", "cygpath", "resolve-path", "rvpa", "split-path", "echo", "printf",
                      "write-host", "write-output"))
# of those, the ones whose output is the path they name: in a pipe or a substitution it may reach a reader
PRINTERS = frozenset(("ls", "dir", "realpath", "readlink", "cygpath", "resolve-path", "rvpa", "split-path", "echo",
                      "printf", "write-output", "get-item", "gi", "get-childitem", "gci"))
# programs whose first positional word is a pattern, not a path (unless -e, -f or -Pattern gives it)
SEARCHERS = frozenset(("grep", "egrep", "fgrep", "rg", "ag", "ack", "findstr"))
# interpreters whose code words (and heredocs) are read as text for the token's path
INTERPRETER = re.compile(r"^(?:python[0-9.]*w?|pythonw|py|pypy[0-9.]*|ipython[0-9.]*|node(?:js)?|deno|bun|perl|"
                         r"ruby|php|rscript|lua|osascript|jshell|groovy)$")
CODE = re.compile(r"[\s();'\"]")   # an interpreter's word that is code, not a path or a name
DOTNET = re.compile(r"::|\[(?:system\.)?io\.", re.I)   # a PowerShell .NET call's word: read as text too
# what code does with a path it names: a read, a copy, an open, a send (print('ipc/token') only names it)
USES = re.compile(r"(?i)\b(?:open|read\w*|copy\w*|path|shutil|io|fs|file\w*|load\w*|cat|spawn\w*|exec\w*|system|"
                  r"popen|subprocess|require|get-content|send\w*|post|request\w*|urlopen|ipcauth)\b")
SEP = r"[\s'\"`,+/\\]+"   # what joins the folder's name and the file's in text: a separator, quotes, a join's comma
GLOB = re.compile(r"[*?\[]")
PIPED = {"bash": re.compile(r"\||\$\(|`|<\("), "ps": re.compile(r"\||\$\(")}
SHARE = re.compile(r"^(?:[\\/]{2}[?.][\\/]UNC|[\\/])?[\\/]([^\\/]+)[\\/]([a-z])\$(?=[\\/]|$)", re.I)
LOOPBACK = re.compile(r"^(?:localhost|127(?:\.\d{1,3}){3}|\[?::1\]?|0--1\.ipv6-literal\.net|\.)$", re.I)
WSL_DRIVE = re.compile(r"^/mnt/([a-z])(?=/|$)", re.I)


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


class Protected:
    """The token files, their folders and <BRAIN_HOME>, as real paths and as written (a glob is matched on both)."""

    def __init__(self):
        files = token_files()
        home = paths.brain_home()
        self.files = {guards._real(f) for f in files} | {_norm(f) for f in files}
        self.folders = {guards._real(f.parent) for f in files} | {_norm(f.parent) for f in files}
        self.home = {guards._real(home), _norm(home)}
        self.names = {(f.parent.name, f.name) for f in files}

    def kind(self, real: str) -> str:
        return "file" if real in self.files else "folder" if real in self.folders else \
            "home" if real in self.home else ""


def _norm(p) -> str:
    return os.path.normcase(os.path.abspath(str(p)))


def _text_pattern(prot: Protected) -> re.Pattern:
    """The token's folder and file names joined in text (``ipc/token``, ``'ipc', 'token'``, ``ipc\\token``)."""
    alts = "|".join(rf"{re.escape(d)}{SEP}{re.escape(n)}" for d, n in prot.names if d and n)
    return re.compile(rf"(?i)(?<![\w.-])(?:{alts})(?![\w.-])")


def _this_host(name: str) -> bool:
    """Whether a share's host is this machine: a loopback name or address, or its own name (COMPUTERNAME, the host
    name, its first label)."""
    if LOOPBACK.match(name):
        return True
    import socket
    mine = {os.environ.get("COMPUTERNAME", ""), socket.gethostname()}
    mine |= {m.split(".")[0] for m in mine}
    return name.lower() in {m.lower() for m in mine if m}


def _local(path: str) -> str:
    """An admin share of this machine (``\\\\localhost\\C$\\x``, ``\\\\<its name>\\C$\\x``) or a WSL drive
    (``/mnt/c/x``) as the local path it is."""
    m = SHARE.match(path)
    if m and _this_host(m.group(1)):
        return m.group(2) + ":" + (path[m.end():] or "/")
    m = WSL_DRIVE.match(path) if os.name == "nt" else None
    return m.group(1) + ":" + (path[m.end():] or "/") if m else path


def _glob_kind(pattern: str, prot: Protected) -> str:
    """'file', 'folder' or 'home' when the glob ``pattern`` (an absolute path) matches one, part by part (a * never
    crosses a separator), without reading the file system: a deep glob costs nothing."""
    parts = re.split(r"[\\/]+", os.path.normcase(pattern).rstrip("\\/"))
    for kind, group in (("file", prot.files), ("folder", prot.folders), ("home", prot.home)):
        for target in group:
            tparts = re.split(r"[\\/]+", target.rstrip("\\/"))
            if len(tparts) == len(parts) and all(fnmatch.fnmatchcase(t, p) for t, p in zip(tparts, parts)):
                return kind
    return ""


def _names(word: str, cwd: str, prot: Protected, literal: bool = False) -> str:
    """'file', 'folder' or 'home' when ``word`` (a path, an option's value, a list, a glob) resolves to the token,
    its folder or <BRAIN_HOME>; ``literal``: a tool's path, which holds no variable (``token::$DATA`` is the file's
    stream) and no glob."""
    for cand in [_local(word)] if literal else _candidates(word):
        target = os.path.abspath(os.path.join(cwd, os.path.expanduser(cand))) if literal else guards._path(cand, cwd)
        kind = prot.kind(guards._real(target)) or (_glob_kind(target, prot) if GLOB.search(cand) and not literal
                                                   else "")
        if kind:
            return kind
    return ""


def _candidates(word: str) -> list[str]:
    """``word`` and what in it may be a path: an option's value (``-Path:x``, ``--file=x``, ``if=x``), a curl-style
    ``@x`` (``f=@x`` too), PowerShell's ``${x}``, a list's items (``'x','T'``) and their join (``$h,ipc,token``: a
    Combine's arguments), a backquote's text."""
    out = [word]
    m = re.match(r"^-{1,2}[\w-]+[:=](.+)$", word) or re.match(r"^\w+=(.+)$", word)
    if m:
        out.append(m.group(1))
    for w in list(out):
        if w.startswith(("@", "<")) and len(w) > 1:
            out.append(w[1:])
    m = re.match(r"^\$\{(.+)\}$", word)
    if m:
        out.append(m.group(1))
    if "," in word:
        items = [x.strip("'\" ") for x in word.split(",") if x.strip("'\" ")]
        out += items + ["/".join(items)]
    out = [w.strip("'\"`()") for w in out]
    return [_local(w) for w in out if w]


def _read_tool(tool: str, inp: dict, cwd: str, prot: Protected) -> str:
    """What a Read or Grep call reaches of the token, else ''."""
    raw = inp.get(READ_TOOLS[tool])
    if tool == "Read" and isinstance(raw, str) and raw:
        return f"Read of {raw}" if _names(raw, cwd, prot, literal=True) == "file" else ""
    if tool == "Grep":
        where = guards._real(os.path.join(cwd, os.path.expanduser(_local(raw))) if isinstance(raw, str) and raw
                             else cwd)
        if where in prot.files:
            return f"Grep in {raw}"
        inside = any(f.startswith(where.rstrip("\\/") + os.sep) for f in prot.files)
        in_home = any(where == h or where.startswith(h.rstrip("\\/") + os.sep) for h in prot.home)
        if not (where in prot.folders or (inside and in_home)):
            return ""
        globs, kind = inp.get("glob"), inp.get("type")
        if isinstance(kind, str) and kind:
            return ""   # a type is a set of extensions: the token's file has none
        if isinstance(globs, str) and globs and not globs.lstrip().startswith("!") and not any(
                _glob_hits(g, f) for f in token_files() for g in _brace(globs)):
            return ""   # a glob that cannot match the file's name (a negated one, !*.md, reads all the rest)
        return f"Grep in {raw or cwd}"
    return ""


def _brace(pattern: str) -> list[str]:
    """A glob's {a,b} alternatives spread (one level, as ripgrep's globs take them)."""
    m = re.search(r"\{([^{}]*)\}", pattern)
    return [pattern[:m.start()] + alt + pattern[m.end():] for alt in m.group(1).split(",")] if m else [pattern]


def _glob_hits(glob: str, f: Path) -> bool:
    """Whether a Grep glob may match the token file (a glob with a / matches the path's tail, else the name)."""
    if "/" in glob or "\\" in glob:
        return fnmatch.fnmatch(f.as_posix(), "*" + glob.replace("\\", "/").lstrip("*"))
    return fnmatch.fnmatch(f.name, glob)


def _edit_tool(tool: str, inp: dict, cwd: str, prot: Protected) -> str:
    raw = inp.get(guards.EDIT_TOOLS[tool])
    if isinstance(raw, str) and raw and _names(raw, cwd, prot, literal=True) == "file":
        return f"{tool} of {raw}"
    return ""


def _normalized(command: str, powershell: bool) -> str:
    """``command`` with ``${NAME}`` (bash) and ``${env:NAME}`` (PowerShell) written as ``$NAME`` and ``$env:NAME``:
    the guards' reader splits a brace, so the path would not be seen whole."""
    if powershell:
        return re.sub(r"\$\{env:(\w+)\}", r"$env:\1", command, flags=re.I)
    return re.sub(r"\$\{(\w+)\}", r"$\1", command)


def _code_says(text: str, pattern: re.Pattern) -> bool:
    """Whether code names the token's file and does something with a path, or uses brain.ipcauth."""
    return bool(re.search(r"\bipcauth\b", text) or (pattern.search(text) and USES.search(text)))


def _shell(cmds, command: str, powershell: bool, cwd: str, prot: Protected) -> str:
    """What a shell call does to the token, else ''."""
    text = _text_pattern(prot)
    sub = "ps" if powershell else "bash"
    norm = _normalized(command, powershell)
    if norm != command:
        cmds = [*cmds, *guards.calls(norm, cwd, powershell)]
    piped = bool(PIPED[sub].search(command))   # a metadata program's output may reach a reader
    for words, d in cmds:   # an output redirection into the file (echo x > T, : > T)
        if words[0].startswith(guards.REDIRECT) and len(words) > 1 and _names(words[1], d, prot) == "file":
            return f"a redirection into {words[1]}"
    fed = False   # an interpreter that reads its code from stdin (python -, node, cat <<X | python)
    for words, d, sh, _ in guards.actions(cmds, sub, command=command):
        low = [w.lower() for w in words]
        prog = guards._prog(words[0])
        if sh == "ssh":
            if any(text.search(w) for w in words):
                return f"{' '.join(words)[:120]} over ssh (it names the token's file)"
            continue
        if INTERPRETER.match(prog):
            fed = fed or all(w.startswith("-") for w in words[1:])
            if any(CODE.search(w) and _code_says(w, text) for w in words[1:]):
                return f"{prog} (its code names the token's file)"
        if any(DOTNET.search(w) and text.search(w) for w in words):
            return f"{words[0]} (a .NET call names the token's file)"
        at = gestures.runs_brain(low)
        if at >= 0 and gestures._command(low, at + 1)[:1] == ["ipc"]:
            continue   # brain ipc: the gestures' (otel-headers); brain ipc token never prints it
        if prog in METADATA:
            if not (piped and prog in PRINTERS):
                continue
            # its output may reach a reader: refused when it names the file or its folder (not the home: ls ~/.brain)
            for w in words:
                kind = _names(w, d, prot)
                if kind in ("file", "folder"):
                    return f"{prog} on {w} in a pipe or a substitution (the token's {kind})"
            continue
        if prog == "join-path":   # Join-Path $h ipc token: the path it makes, not its base alone
            parts = [w for w in words[1:] if not w.startswith("-")]
            kind = _names("/".join(parts), d, prot) if parts else ""
            if kind in ("file", "folder"):
                return f"Join-Path {' '.join(parts)} (the token's {kind})"
            continue
        if prog in SEARCHERS and not any(w in ("-e", "-f", "--regexp", "--file") or w.startswith(("-e", "--regexp="))
                                         for w in words[1:]):
            pos = next((i for i, w in enumerate(words[1:], 1) if not w.startswith("-")), None)
            words = [w for i, w in enumerate(words) if i != pos]   # the pattern is no path
        for w in words:
            kind = _names(w, d, prot)
            if kind:
                return f"{prog} on {w} (the token's {kind})"
    if fed:
        for body in guards._heredocs(command):   # code fed to an interpreter by a heredoc
            if _code_says(body, text):
                return "an interpreter's heredoc (it names the token's file)"
    folders_seen = {d for _, d in cmds} or {cwd}
    for seg in guards.segments(command, powershell):
        for k, w in enumerate(seg[:-1]):
            if w.startswith(guards.REDIRECT) and "<" in w and not w.endswith("<<"):
                if any(_names(seg[k + 1], d, prot) for d in folders_seen):
                    return f"an input redirection from {seg[k + 1]}"
    return ""


def check(tool: str, inp: dict, cwd: str, cmds=None, command: str = "", powershell: bool = False,
          strict: bool = False) -> str | None:
    """The owner guard's refusal of a call that reads, copies or replaces the machine's token, else None; on only
    under config.json guards.refuse_token_read, or ``strict`` (the MCP server)."""
    if not (strict or enabled()):
        return None
    prot = Protected()
    if tool in READ_TOOLS:
        what = _read_tool(tool, inp, cwd, prot)
    elif tool in guards.EDIT_TOOLS:
        what = _edit_tool(tool, inp, cwd, prot)
    elif cmds:
        what = _shell(cmds, command, powershell, cwd, prot)
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
