"""The locked floor's guard (wi-brain-unadopted-floor, brain.floor; docs/guards.md, the locked floor): the checks
brain.guards runs while config.json floor.refuse or floor.only is on. Every check reads each command a call runs,
past a wrapper, a launcher or a nested shell (brain.guards.actions); a wrapper whose payload it cannot read is refused.

- :func:`check_floor`: a git push to main or master (check ``main``) or a forced push (``force``), read as git reads
  it (aliases followed, the remote's mirror flag, push.default, symbolic branches); git configuration given by the
  command line (``-c``, ``--config-env``), a global option the floor does not know, a subcommand git does not know,
  or ``git config`` of the keys that change a push (``config``); send-pack, ``symbolic-ref`` of a branch and the code
  host's API writes of main's ref (``main``).
- :func:`check_files` (check ``config``): what would lift or stop the floor: a write, a copy, an extraction, a removal
  or a move of the config.json the guard reads, of its pointer, of git's configuration files, of the guard's
  interpreter (<BRAIN_HOME>/venv) or of the plugin that runs the guard (~/.claude/plugins, $CLAUDE_PLUGIN_ROOT); a
  git command other than a read in the checkout that holds config.json; a variable of brain.floor.WATCHED_VARS
  assigned in any form, or one of FLOOR_ENV set for later sessions, or a name the guard cannot read; any write to the
  registry's Environment key; ``claude plugin disable`` or ``uninstall`` of the core plugin; Claude Code's settings
  or a profile left (the edit applied to the file) setting what stops the guards.

A guard of the command line cannot be complete: what it does not read is listed under « Limits » in docs/guards.md,
and the code host's branch protection on main is the backstop.
"""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

from . import config, floor, paths
from . import guards as g

TAIL = ("; that breaks the locked floor (no push to main or master, no force-push: merge by a pull request; the "
        "owner's own terminal for the rest)")
REMOVERS = {"rm", "rmdir", "unlink", "shred", "remove-item", "ri", "rd", "del", "erase"}
MOVERS = {"mv", "move", "mi", "move-item", "rename-item", "ren", "rni", "rename"}
COPIERS = {"cp", "copy", "copy-item", "cpi", "xcopy", "rsync", "robocopy", "install"}
EXTRACTORS = {"tar", "bsdtar", "unzip", "expand-archive", "7z", "7za"}
OPAQUE_XARGS = {"git", "claude", "reg", "setx", *REMOVERS, *MOVERS, *COPIERS, *EXTRACTORS}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "pwsh", "powershell", "cmd"}
PLAIN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
ROBOCOPY_OPT = re.compile(r"/[A-Za-z]+(?::\S*)?")
DEST_OPTS = ("-t", "--target-directory", "-destination", "-dest", "-des")   # a mover's or a copier's target
REGISTRY_ENV = re.compile(
    r"(?i)(?:\b(?:set-itemproperty|new-itemproperty|remove-itemproperty|rename-itemproperty|clear-itemproperty|sp|rp|"
    r"set-item|new-item)\b[^;|\n]*(?:HKCU|HKEY_CURRENT_USER|HKLM|HKEY_LOCAL_MACHINE)[:\\/]+(?:[^;|\n]*[\\/])?"
    r"Environment\b|\breg(?:\.exe)?\s+(?:add|delete|copy)\b[^;|\n]*Environment\b|"
    r"\breg(?:\.exe)?\s+(?:import|restore|load)\b|(?:Registry|RegistryKey)\]?::"
    r"[^;\n]*Environment|\bCurrentUser\b[^;\n]*OpenSubKey\s*\([^)]*Environment|SetValue\s*\([^)]*Environment|"
    r"Win32_Environment|\bwmic\b[^;|\n]*\benvironment\b)")   # the environment through WMI or CIM too
ACLS = {"icacls", "cacls", "takeown", "attrib", "set-acl", "chattr", "chmod", "chown", "chgrp", "setfacl"}
_LIST_CMDS: dict[str, set[str]] = {}


def on(fl: dict) -> bool:
    return bool(fl["refuse"] or fl["only"])


def _under(path: str, folder: str) -> bool:
    """Whether ``path`` is ``folder`` or inside it (both as _real gives them)."""
    return bool(path) and bool(folder) and (path == folder or path.startswith(folder.rstrip("\\/") + os.sep))


# Claude Code's settings files: the floor refuses any change of them but a Write or an Edit (judged on what it leaves).
SETTINGS = re.compile(r"(?i)(?:^|[\\/])(?:\.claude[\\/]settings(?:\.local)?\.json|managed-settings\.json)$")
# The files Python runs at its start from any folder on its path: kept wherever they are written.
STARTUP = re.compile(r"(?i)(?:^|[\\/])(?:sitecustomize|usercustomize)\.py$|\.pth$")


def _interpreters(home: Path) -> list[str]:
    """The folders of the interpreter that runs the guard, as the file system resolves them: <BRAIN_HOME>/venv, the
    base installation it redirects to (pyvenv.cfg's home, this process's sys.base_prefix), and the user site."""
    import site
    import sys
    out = [home / "venv", sys.base_prefix, sys.prefix]
    try:
        cfg = (home / "venv" / "pyvenv.cfg").read_text(encoding="utf-8")
        m = re.search(r"(?m)^\s*home\s*=\s*(.+?)\s*$", cfg)
        if m:
            base = Path(m.group(1))
            out.append(base.parent if base.name.lower() in ("bin", "scripts") else base)
    except OSError:
        pass
    try:
        out.append(site.getusersitepackages())
    except (AttributeError, OSError):
        pass
    return sorted({g._real(p) for p in out if p})


class Kept:
    """What the floor keeps (as the file system resolves it): the files that set it (the config.json the guard reads,
    the pointer <BRAIN_HOME>/personal.json), the interpreter that runs the guard
    (<BRAIN_HOME>/venv, its base installation, the user site, any sitecustomize, usercustomize or .pth), the plugin
    that runs the guard (~/.claude/plugins, $CLAUDE_PLUGIN_ROOT), and the folders of the files (the checkout,
    BRAIN_HOME)."""

    def __init__(self, cfg_file):
        home = paths.brain_home()
        self.files = [g._real(f) for f in (cfg_file, home / paths.PERSONAL) if f]
        self.runtimes = _interpreters(home)
        self.venv = g._real(home / "venv")
        self.plugins = [g._real(p) for p in (Path.home() / ".claude" / "plugins", os.environ.get("CLAUDE_PLUGIN_ROOT"))
                        if p]
        self.folders = sorted({os.path.dirname(f) for f in self.files[:2]})
        self.paths = [*self.files, *self.runtimes, *self.plugins]

    def inside(self, real: str) -> bool:
        """Whether ``real`` is a kept file, a Python startup file, or in the interpreter's or the plugin's folder."""
        return bool(real) and (real in self.files or bool(STARTUP.search(real))
                               or any(_under(real, k) for k in (*self.runtimes, *self.plugins)))

    @staticmethod
    def settings(real: str) -> bool:
        """Whether ``real`` is one of Claude Code's settings files (a change other than Write or Edit is refused)."""
        return bool(real) and bool(SETTINGS.search(real))

    def holds(self, real: str) -> bool:
        """Whether ``real`` is a kept path or a folder above one (its removal or its replacement takes it)."""
        return any(_under(k, real) for k in self.paths)


# --- check config: what would lift or stop the floor ---------------------------------------------------------------

def check_files(tool: str, inp: dict, cmds, cwd: str, fl: dict, cfg_file, command: str = "") -> str | None:
    """While the floor is on, what would lift it or stop the guard for this session or the next (module docstring),
    else None. A worktree's own config.json is another file: a pull request still changes it."""
    if not on(fl) or not (tool in g.EDIT_TOOLS or cmds or command):   # export X=1 alone parses to no command
        return None
    kept = Kept(cfg_file)
    what = _edit(tool, inp, cwd, kept) if tool in g.EDIT_TOOLS else \
        _shell(cmds, "ps" if tool == "PowerShell" else "bash", command, kept)
    return (f"{what}; the locked floor (config.json floor) is {config.owner_of()}'s to change, in their own terminal "
            "(BRAIN_GUARD_ALLOW=floor lifts it)") if what else None


def _edit(tool: str, inp: dict, cwd: str, kept: Kept) -> str | None:
    """What a tool edit would lift or stop the floor by: a kept file or folder (the path resolved: a stream's name, a
    junction), git's configuration files, or Claude Code's settings or a profile that the edit leaves setting a
    variable of FLOOR_ENV or the core plugin off (the edit applied to the file's text, JSON decoded)."""
    target = g._edit_target(inp, tool, cwd)
    if not target:
        return None
    real = g._resolved(target)
    if kept.inside(real):
        return f"{tool} refused: {target} sets the floor or runs the guard"
    if floor.GIT_CONFIG_FILES.search(real) or floor.GIT_CONFIG_FILES.search(target):
        return f"{tool} refused: {target} is git's configuration (an alias or a mirror there changes what a push does)"
    if not g._override_file(target):
        return None
    before, after = g._edit_result(inp, tool, target)
    added = g._introduced(floor.FLOOR_ENV, before, after)
    if added:
        return f"{tool} refused: it leaves {added} in {target}, which moves or stops the floor"
    if _plugin_off(floor.unspelled(after)) and not _plugin_off(floor.unspelled(before)):
        return f"{tool} refused: it turns the core plugin off in {target}"
    return None


def _plugin_off(text: str) -> bool:
    """Whether settings text turns the core plugin (the one that carries guard.sh) off in enabledPlugins."""
    plugin = config.claude(config.load())["plugin"]
    return bool(re.search(rf"{re.escape(plugin)}(?:@[^\s:,]*)?\s*:\s*false", text))


def _shell(cmds, sub: str, command: str, kept: Kept) -> str | None:
    """What a shell call would lift or stop the floor by (check_files), else None."""
    acts = [(words, d) for words, d, _, _ in g.actions(cmds, sub, command=command)]
    plain = floor.unspelled(_code(command))
    checks = (lambda: _opaque(cmds, acts, command), lambda: _env(plain), lambda: _registry(plain),
              lambda: _removals(acts, kept), lambda: _acl(acts, kept), lambda: _writes(cmds, sub, kept),
              lambda: _copies(acts, kept), lambda: _extractions(acts, kept), lambda: _archived_settings(acts),
              lambda: _links(acts, kept), lambda: _git_settings(acts), lambda: _checkout(acts, kept),
              lambda: _named(acts, command), lambda: _plugin_cmd(acts), lambda: _piped(command, acts, kept),
              lambda: _methods(command, acts, kept))
    what = next((w for check in checks if (w := check())), None)
    if what:
        return what
    what = g._override(command, cmds, sub, env=floor.FLOOR_ENV + "|enabledPlugins")
    return f"{what} refused: it moves or stops the floor" if what else None


# The commands whose quoted arguments are prose (an echo's words, a commit message, a PR body), and the options that
# take prose: only there is a quoted string holding a space taken out before the environment is read (_code).
PROSE_CMDS = {"echo", "printf", "write-output", "write-host", "write", "say"}
# Per program, its options whose value is prose (round 6: -t and -b were prose for any command, declare -x -t too).
PROSE_OPTS = {"git": re.compile(r"(?:^|\s)(?:-m|--message)\s*=?\s*$"),
              "gh": re.compile(r"(?:^|\s)(?:-m|--message|-b|--body|-t|--title|-n|--notes)\s*=?\s*$")}


def _code(command: str) -> str:
    """``command`` without the prose it quotes: a quoted string holding a space is taken out when it is an argument of
    echo or printf (not printf -v) or the value of git's -m or --message, or gh's -m, --body, --title or --notes (-b,
    -t, -n); any other stays (declare -x -t "NAME=..." is read), so an assignment
    quoted whole (export "GIT_CONFIG_PARAMETERS=..."), a shell's payload and a quoted word are read."""
    def keep(m: re.Match) -> str:
        s, before = m.group(0), command[:m.start()]
        seg = re.split(r"[;&|\n(]", before)[-1].split()
        first = g._prog(seg[0]) if seg else ""
        opts = PROSE_OPTS.get(first)
        prose = re.search(r"\s", s) and ((opts is not None and opts.search(before)) or
                                         (first in PROSE_CMDS and "-v" not in seg[1:2]))
        return " Q " if prose else s
    return re.sub(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"", keep, command)   # quotes paired left to right


# eval of these programs' own output (eval "$(ssh-agent -s)") prints only assignments the floor reads the shape of.
EVAL_OK = re.compile(r"^\$\((?:ssh-agent|dircolors|brew\s+shellenv|pyenv\s+init|direnv\s+hook|starship\s+init)\b")
# What Start-Process may run while the floor is on with arguments it cannot read: not git, a shell nor what writes the
# environment or the registry.
START_RISKY = {"git", "claude", "reg", "setx", "wmic", "robocopy", *SHELLS}
# A shell function the call defines, whatever its body (round 6: a subshell body, ( ... ), was not read): function
# NAME, or NAME ( ) before a compound command ({, (, ((, [[, if, for, while, until, case, select).
FUNCTION = re.compile(r"(?:^|[;&|\s])(?:function\s+[\w.-]+|[\w.-]+\s*\(\s*\)\s*(?:\{|\(|\[\[|"
                      r"(?:if|for|while|until|case|select)\b))|"
                      # round 7: PowerShell's ${function:f} = {...}, and the function: drive (Set-Item, New-Item)
                      r"(?i:\$\{function:|\b(?:set-item|si|new-item|ni)\s+(?:-path\s+)?['\"]?function:)")
# An alias the call defines or turns on (round 6: alias c=cp, then c, was read as a program c): bash's alias and
# shopt -s expand_aliases, PowerShell's Set-Alias and New-Alias; round 7: BASH_ALIASES[...]=, set -o posix (POSIX mode
# expands aliases), the alias: drive (Set-Item, New-Item).
ALIAS = re.compile(r"(?:^|[;&|\s(])(?:alias\s+[^\s=;&|]+=|shopt\s+(?:-\w+\s+)*expand_aliases\b|"
                   r"(?i:(?:set-alias|new-alias|sal|nal)\s))|\bBASH_ALIASES\s*\[|\bset\s+(?:-\w+\s+)*-o\s+posix\b|"
                   r"(?i:\b(?:set-item|si|new-item|ni)\s+(?:-path\s+)?['\"]?alias:)")


def _opaque(cmds, acts, command: str = "") -> str | None:
    """A wrapper whose payload the floor cannot read: eval or a shell's -c given a variable or a substitution,
    Start-Process of git or a shell with -ArgumentList, xargs running git or what writes files (read before it is
    unwrapped), a shell function the call defines (its body runs with arguments the floor does not follow), an alias
    it defines or turns on."""
    if FUNCTION.search(command):
        return "a shell function refused: the floor does not follow what it runs with its arguments"
    if ALIAS.search(command):
        return "an alias refused: the floor reads a command by its program's name, not by what an alias makes it"
    for words, _ in cmds:
        if g._prog(words[0]) == "xargs" and _xargs_writes(words):
            return "xargs refused: the floor cannot read the arguments it gives"
    return next((what for words, _ in acts if (what := _unread(g._prog(words[0]), words[1:]))), None)


def _xargs_writes(words: list[str]) -> bool:
    """Whether xargs runs git (but a read or git add) or a program that writes files, the registry or the
    environment."""
    rest = [a for a in words[1:] if not a.startswith("-")]
    if not rest or g._prog(rest[0]) not in OPAQUE_XARGS:
        return False
    return g._prog(rest[0]) != "git" or (rest[1] if len(rest) > 1 else "") not in XARGS_GIT_OK


XARGS_GIT_OK = {"add", "log", "show", "diff", "status", "grep", "blame", "ls-files", "cat-file", "rev-parse"}


def _unread(prog: str, args: list[str]) -> str:
    """Why one command's payload is out of the floor's reading, else ''."""
    text = " ".join(args)
    if prog == "eval" and any(c in text for c in "$`") and not EVAL_OK.match(text.strip()):
        return "eval of a variable refused: the floor cannot read what it runs"
    k = next((i for i, a in enumerate(args) if a.lower() in ("-c", "/c", "-command")), -1)
    if prog in SHELLS and 0 <= k < len(args) - 1 and re.match(r"\s*[$`]", args[k + 1]):
        return f"{prog} -c of a variable refused: the floor cannot read what it runs"
    return _start_unread(prog, args) if prog in ("start-process", "saps", "start") else ""


def _start_unread(prog: str, args: list[str]) -> str:
    """Start-Process of git, a shell or what writes the environment (or a program named by a variable) with
    -ArgumentList, which the floor cannot read; '' else."""
    if not any(re.match(r"(?i)^-(?:a(?:r(?:g\w*)?)?)$", a) for a in args):
        return ""
    program = next((a for a in args if not a.startswith("-")), "")
    if program.startswith("$") or g._prog(program) in START_RISKY:
        return f"{prog} {program} -ArgumentList refused: the floor cannot read what it runs"
    return ""


def _env(plain: str) -> str | None:
    """A variable of brain.floor.WATCHED_VARS assigned in any form, or an assignment whose name the guard cannot read
    (on the call's unspelled text)."""
    m = floor.ENV_ASSIGN.search(plain) or floor.ENV_DYNAMIC.search(plain)
    return f"{m.group(0).strip()[:60]!r} refused: a variable the floor watches (or one it cannot read) set" if m else None


def _registry(plain: str) -> str | None:
    """Any write to the registry's Environment key (Set-ItemProperty, New-ItemProperty, .NET's Registry, reg add or
    import), whatever the value's name."""
    m = REGISTRY_ENV.search(plain) or REGISTRY_NET.search(plain)
    return f"{m.group(0)[:60]!r} refused: a write of the registry's Environment key" if m else None


# Round 7: the environment through COM (WScript.Shell's Environment(...)), a .NET RegistryKey's writers, and the
# Environment key piped into a property cmdlet, whatever the statement.
REGISTRY_NET = re.compile(
    r"(?is)WScript\.Shell.*\.Environment\s*\(|\.Environment\s*\(.*WScript\.Shell|"
    r"(?:\bRegistry(?:Key)?\b|OpenSubKey|HKEY_|\bHKCU\b|\bHKLM\b).*\.(?:SetValue|CreateSubKey|DeleteValue|"
    r"DeleteSubKey\w*)\s*\(|OpenSubKey\s*\([^)]*\$true|"
    r"(?:HKCU|HKEY_CURRENT_USER|HKLM|HKEY_LOCAL_MACHINE)[:\\/]+(?:[^;|\n]*[\\/])?Environment\b[^;\n]*\|\s*"
    r"(?:set-itemproperty|new-itemproperty|remove-itemproperty|rename-itemproperty|clear-itemproperty|sp|rp|"
    r"set-item|new-item)\b")
# Round 7: what a PowerShell pipeline hands a cmdlet that writes, moves or removes (Get-Item X | Rename-Item, 'X' |
# Remove-Item): X is its -Path.
PIPE_WRITERS = {"rename-item", "ren", "rni", "move-item", "mi", "move", "remove-item", "ri", "rd", "del", "erase",
                "rm", "rmdir", "set-content", "sc", "add-content", "ac", "clear-content", "clc", "set-itemproperty",
                "sp", "new-itemproperty", "copy-item", "cpi", "copy", "set-acl", "out-file", "clear-item", "cli",
                "set-item", "si"}
PIPE_SOURCES = {"get-item", "gi", "get-childitem", "gci", "ls", "dir", "resolve-path", "rvpa", "get-itemproperty",
                "gp"}
WORD = re.compile(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"|[^\s|;]+")
# Round 7: .NET's file and folder methods that write, move, remove or re-ACL the object they are called on.
NET_WRITERS = re.compile(r"(?i)\.(?:MoveTo|CopyTo|Replace|Delete|SetAccessControl|Encrypt|Decrypt)\s*\(")
HOME_VARS = re.compile(r"(?i)^(?:\$env:(?:USERPROFILE|HOME)|\$\{env:(?:USERPROFILE|HOME)\}|\$HOME|~)(?=$|[\\/])")


def _unq(word: str) -> str:
    return word[1:-1] if len(word) > 1 and word[0] == word[-1] and word[0] in "'\"" else word


def _touches(word: str, d: str, kept: Kept) -> bool:
    """Whether ``word``, read as a path (the home's variables expanded), is kept, above a kept path, one of Claude
    Code's settings files or git's configuration."""
    real = g._real(g._path(HOME_VARS.sub(lambda m: str(Path.home()).replace("\\", "/"), word), d))
    return bool(real) and (kept.inside(real) or kept.holds(real) or real in kept.folders or kept.settings(real)
                           or bool(floor.GIT_CONFIG_FILES.search(real)))


def _piped(command: str, acts, kept: Kept) -> str | None:
    """A path piped into a cmdlet that writes, moves or removes (PIPE_WRITERS) that _touches."""
    d = acts[0][1] if acts else os.getcwd()
    for stmt in re.split(r"[;\n]", command):
        parts = stmt.split("|")
        for left, right in zip(parts, parts[1:]):
            rw, lw = WORD.findall(right), WORD.findall(left)
            if not rw or not lw or g._prog(_unq(rw[0])) not in PIPE_WRITERS:
                continue
            literal = len(lw) == 1 and lw[0][0] in "'\""
            sources = [_unq(lw[0])] if literal else \
                [_unq(w) for w in lw[1:] if not w.startswith("-")] if g._prog(_unq(lw[0])) in PIPE_SOURCES else []
            hit = next((s for s in sources if _touches(s, d, kept)), None)
            if hit:
                return (f"{_unq(rw[0])} of {hit} through a pipeline refused: it changes what sets the floor or runs "
                        "the guard")
    return None


def _methods(command: str, acts, kept: Kept) -> str | None:
    """A .NET method that writes (NET_WRITERS) in a call that names a path _touches finds."""
    m = NET_WRITERS.search(command)
    if not m:
        return None
    d = acts[0][1] if acts else os.getcwd()
    for word in re.findall(r"'([^']*)'|\"([^\"]*)\"|([^\s'\"(),;|=]+)", command):
        w = next(x for x in word if x) if any(word) else ""
        if w and re.search(r"[\\/~]", w) and _touches(w, d, kept):
            return (f"{m.group(0)[1:-1].strip()}( on {w} refused: a .NET method that writes, moves or removes what "
                    "sets the floor or runs the guard")
    return None


def _removals(acts, kept: Kept) -> str | None:
    """A removal or a move of a kept path or of a folder above one: rm, mv, Remove-Item, Move-Item, Rename-Item...,
    robocopy /MIR or /PURGE onto it, /MOVE from it. A write into such a folder is judged by _copies and _writes."""
    for words, d in acts:
        prog = g._prog(words[0])
        for t in _removed(prog, words):
            if kept.holds(g._real(g._path(t, d))):
                return f"{prog} of {t} refused: it removes or moves what sets the floor or runs the guard"
    return None


def _positional(words: list[str]) -> tuple[list[str], str]:
    """(the positional arguments, the target an option names: -t, --target-directory, -Destination) of a command."""
    pos, target, i = [], "", 1
    while i < len(words):
        w, low = words[i], words[i].lower()
        name, eq, val = low.partition("=")
        if name in DEST_OPTS or (name.startswith("-des") and "-destination".startswith(name)):
            target = words[i][len(name) + 1:] if eq else (words[i + 1] if i + 1 < len(words) else "")
            i += 1 if eq else 2
            continue
        if not w.startswith("-"):
            pos.append(w)
        i += 1
    return pos, target


def _removed(prog: str, words: list[str]) -> list[str]:
    """The paths a removal or a move takes away: every path of a remover, a mover's sources (not its target, named
    last or by -t, --target-directory, -Destination), robocopy's DST under /MIR or /PURGE and its SRC under /MOVE."""
    if prog == "robocopy":
        opts = {w.split(":")[0].upper() for w in words[1:] if ROBOCOPY_OPT.fullmatch(w)}
        pos = [w for w in words[1:] if not ROBOCOPY_OPT.fullmatch(w)]
        return (pos[1:2] if opts & {"/MIR", "/PURGE"} else []) + (pos[:1] if opts & {"/MOVE", "/MOV"} else [])
    if prog not in REMOVERS | MOVERS:
        return []
    pos, target = _positional(words)
    if prog in REMOVERS or target:
        return pos
    return pos[:-1] if len(pos) > 1 else pos


def _writes(cmds, sub: str, kept: Kept) -> str | None:
    """A shell write (a redirection, a program that writes) of a kept file, into a kept folder, or of git's
    configuration files."""
    for what, target in g.shell_writes(cmds, sub):
        real = g._resolved(target)
        if real and kept.inside(real):
            return f"{what} into {target} refused: it sets the floor or runs the guard"
        if real and floor.GIT_CONFIG_FILES.search(real):
            return f"{what} into {target} refused: it is git's configuration"
        if kept.settings(real) or isinstance(target, g.Unresolved) and kept.settings(target.what):
            return f"{what} into {target} refused: Claude Code's settings change by Write or Edit only"
    return None


def _acl(acts, kept: Kept) -> str | None:
    """An ACL, ownership, mode or attribute change of a kept path or of any folder above one (icacls, cacls,
    takeown, attrib, Set-Acl, chattr, chmod, chown, setfacl; round 6: a deny on ~/.claude is inherited by guard.sh,
    whose hook then exits 126, a non-blocking error): the guard's interpreter and plugin must stay readable."""
    for words, d in acts:
        prog = g._prog(words[0])
        if prog not in ACLS:
            continue
        for t in (w for w in words[1:] if not w.startswith(("-", "+")) and not ROBOCOPY_OPT.fullmatch(w)):
            real = g._real(g._path(t, d))
            if kept.inside(real) or real in kept.folders or kept.holds(real):
                return f"{prog} of {t} refused: it changes who reads what sets the floor or runs the guard"
    return None


def _recursive(prog: str, words: list[str]) -> bool:
    """Whether a copy takes folders whole (cp -r, -R, -a; rsync -r, -a; Copy-Item -Recurse; xcopy and robocopy /E,
    /S, /MIR)."""
    args = words[1:]
    if prog in ("xcopy", "robocopy"):
        return any(a.upper().split(":")[0] in ("/E", "/S", "/MIR") for a in args)
    if prog in ("copy-item", "cpi"):
        return any(re.match(r"(?i)^-rec", a) for a in args)
    return any(a in ("--recursive", "--archive") or re.match(r"^-[A-Za-z]*[rRa]", a) and not a.startswith("--")
               for a in args)


def _copies(acts, kept: Kept) -> str | None:
    """A copy whose written path is a kept file or in a kept folder (the destination, or the destination plus the
    source's name when the destination is a folder), or a recursive copy into a kept file's folder or onto a folder
    above a kept path; robocopy's FILE arguments are written into DST."""
    for words, d in acts:
        prog = g._prog(words[0])
        if prog not in COPIERS | MOVERS | {"patch"}:
            continue
        for real, whole in _copied(prog, words, d):
            if kept.inside(real) or (whole and (real in kept.folders or kept.holds(real))):
                return f"{prog} into {real} refused: it writes what sets the floor or runs the guard"
            if kept.settings(real) or whole and os.path.basename(real).lower() == ".claude":
                return f"{prog} into {real} refused: Claude Code's settings change by Write or Edit only"
    return None


def _copied(prog: str, words: list[str], d: str) -> list[tuple[str, bool]]:
    """(the path a copy, a move or a patch writes, whether a whole folder lands there) for each source: a move lands
    as a copy does (folder plus the source's name); patch writes its first file (or -o's)."""
    if prog == "robocopy":
        return _robocopied(words, d)
    if prog == "patch":
        return _patched(words, d)
    pos, target = _positional(words)
    dest, sources = (target, pos) if target else (pos[-1] if pos else "", pos[:-1])
    if not dest:
        return []
    dst = g._real(g._path(dest, d))
    into = bool(target) or len(sources) > 1 or os.path.isdir(dst) or dest.endswith(("/", "\\"))
    whole = prog in MOVERS or _recursive(prog, words)   # a move takes a folder whole
    return [_lands(src, dst, into, whole) for src in sources]


def _patched(words: list[str], d: str) -> list[tuple[str, bool]]:
    """The file patch writes: -o's, else its first file argument."""
    out = next((words[i + 1] for i, w in enumerate(words[:-1]) if w in ("-o", "--output")), "")
    first = next((w for w in words[1:] if not w.startswith("-")), "")
    return [(g._real(g._path(out or first, d)), False)] if (out or first) else []


def _lands(src: str, dst: str, into: bool, whole: bool) -> tuple[str, bool]:
    """(the path one source of a copy writes, whether a whole folder lands there): the folder's contents or names
    the guard cannot know (., *, $x) land as a whole in ``dst``."""
    name = os.path.basename(src.rstrip("/\\"))
    if name in (".", "..", "") or any(c in name for c in "*?[$"):
        return dst, True
    return (os.path.join(dst, name) if into else dst), whole


def _robocopied(words: list[str], d: str) -> list[tuple[str, bool]]:
    """robocopy SRC DST [FILE...]: each FILE written into DST, else SRC's files land in DST as a whole."""
    pos = [w for w in words[1:] if not ROBOCOPY_OPT.fullmatch(w)]
    if len(pos) < 2:
        return []
    dst = g._real(g._path(pos[1], d))
    return [(os.path.join(dst, f), False) for f in pos[2:]] or [(dst, True)]


def _extractions(acts, kept: Kept) -> str | None:
    """An archive extracted into a kept file's folder or a kept folder (tar -x -C, unzip -d, Expand-Archive
    -DestinationPath, 7z x -o; the current folder when none is named): its members are not read."""
    for words, d in acts:
        prog = g._prog(words[0])
        target = _extract_target(prog, words) if prog in EXTRACTORS else None
        if target is None:
            continue
        real = g._real(g._path(target, d)) if target else g._real(d)
        if real in kept.folders or kept.inside(real):
            return f"{prog} into {real} refused: an archive there can hold what sets the floor or runs the guard"
    return None


TAR_X = re.compile(r"-?[A-Za-z]*x[A-Za-z]*")   # x, xzf, -xf: a group of tar's short options holding x


def _tar_target(args: list[str]) -> str | None:
    """Where tar extracts (-C, --directory; '' for the current folder), None when it does not extract."""
    short = [a for a in args if a.startswith("-") and not a.startswith("--")]
    if not ((args and TAR_X.fullmatch(args[0])) or any(TAR_X.fullmatch(a) for a in short)
            or "--extract" in args or "--get" in args):
        return None
    return _value(args, ("-C", "--directory"))


def _unzip_target(args: list[str]) -> str | None:
    """Where unzip extracts (-d), None for a listing or a test."""
    return None if any(a in ("-l", "-v", "-t", "-Z") for a in args) else _value(args, ("-d",))


def _7z_target(args: list[str]) -> str | None:
    """Where 7z x or e extracts (-o<dir>), None for another command."""
    if not args or args[0] not in ("x", "e"):
        return None
    return next((a[2:] for a in args if a.startswith("-o")), "")


def _expand_target(args: list[str]) -> str:
    """Where Expand-Archive extracts: -DestinationPath or a prefix of it PowerShell takes, else its second
    positional argument."""
    v = next((args[i + 1] for i, a in enumerate(args[:-1])
              if len(a) > 1 and "-destinationpath".startswith(a.lower())), "")
    pos = [a for a in args if not a.startswith("-")]
    return v or (pos[1] if len(pos) > 1 else "")


EXTRACT = {"tar": _tar_target, "bsdtar": _tar_target, "unzip": _unzip_target, "7z": _7z_target, "7za": _7z_target,
           "expand-archive": _expand_target}


def _extract_target(prog: str, words: list[str]) -> str | None:
    """Where an extraction writes ('' for the current folder), or None when the command extracts nothing."""
    return EXTRACT[prog](words[1:]) if prog in EXTRACT else None


def _value(args: list[str], names: tuple[str, ...]) -> str:
    """The value of the first of ``names`` in ``args`` (``-C x``, ``--directory=x``), '' when none."""
    for i, a in enumerate(args):
        name, eq, val = a.partition("=")
        if name in names:
            return val if eq else (args[i + 1] if i + 1 < len(args) else "")
    return ""


# --- Claude Code's settings written by git or an archive (round 6, #5): they change by Write or Edit only ---------

# git commands that write the work tree, and where what they bring comes from.
GIT_TREE_WRITERS = {"checkout", "restore", "checkout-index", "update-index", "reset", "stash", "apply", "read-tree",
                    "am", "merge", "pull", "switch", "cherry-pick", "revert", "rebase", "worktree", "sparse-checkout",
                    "mv"}
SETTINGS_SPEC = (":(glob)**/.claude/settings.json", ":(glob)**/.claude/settings.local.json")
REV_OPTS = ("--source", "-s", "--onto")   # restore --source=X, rebase --onto X: a commit the command reads from


def _git_settings(acts) -> str | None:
    """A git command that would write one of Claude Code's settings files: one named in its arguments (a pathspec,
    update-index's --cacheinfo), update-index from its input, or a commit, the index, a stash or a patch it brings
    whose settings differ from the work tree's (git diff --name-only on the settings' pathspec)."""
    for _, folder, sub, args in _git(acts):
        if sub not in GIT_TREE_WRITERS:
            continue
        named = next((a for a in args if any(SETTINGS.search(part) for part in re.split(r"[,=]", a))), "")
        if named:
            return f"git {sub} of {named} refused: Claude Code's settings change by Write or Edit only"
        if sub == "update-index" and set(args) & {"--index-info", "--stdin"}:
            return "git update-index from its input refused: the floor cannot read what it stages"
        brought = _brings_settings(folder, sub, args)
        if brought:
            return (f"git {sub} refused: it would write {brought}, and Claude Code's settings change by Write or Edit "
                    "only")
    return None


def _brings_settings(d: str, sub: str, args: list[str]) -> str:
    """The settings file a work-tree writer would change, '' when none: for what restores the index or HEAD over the
    work tree (restore, checkout-index, reset, stash, read-tree, checkout with a pathspec), the work tree against them;
    each commit it names or reads by default (the last stash, the upstream for pull) against HEAD, so a local edit
    the command carries over is no change; each patch file of apply or am read as text."""
    if sub in ("apply", "am"):
        return _patched_settings(d, args)
    if sub in INDEX_RESTORERS or (sub == "checkout" and ("--" in args or "." in args)):
        changed = g._git_out(d, "diff", "--name-only", "HEAD", "--", *SETTINGS_SPEC).split() or \
            g._git_out(d, "diff", "--name-only", "--", *SETTINGS_SPEC).split()
        if changed:
            return changed[0]
    for rev in _revs(sub, args):
        if not g._git_out(d, "rev-parse", "--verify", "-q", f"{rev}^{{commit}}").strip():
            continue
        changed = g._git_out(d, "diff", "--name-only", "--diff-filter=d", *_span(sub, rev), "--",
                             *SETTINGS_SPEC).split()
        if changed:
            return f"{changed[0]} (from {rev})"
    return ""


INDEX_RESTORERS = {"restore", "checkout-index", "reset", "stash", "read-tree"}
MERGERS = {"merge", "cherry-pick", "rebase", "pull"}   # they bring what a commit changed since the fork point


def _span(sub: str, rev: str) -> list[str]:
    """What git diff compares for a commit a command brings (a removed settings file is no lift): since the fork
    point for a merge, a pick, a rebase or a pull; the commit's own change undone for a revert; HEAD to it else (the
    work tree becomes its tree)."""
    if sub in MERGERS:
        return [f"HEAD...{rev}"]
    if sub == "revert":
        return [rev, f"{rev}^"]
    return ["HEAD", rev]


def _revs(sub: str, args: list[str]) -> list[str]:
    """What a work-tree writer may read commits from: its positional arguments, the value of --source, -s or --onto,
    and its default (HEAD for reset, the last stash, the upstream for pull); git says which are commits."""
    revs = [a for a in args if not a.startswith("-") and a not in ("--", ".")]
    revs += [a.partition("=")[2] for a in args if a.partition("=")[0] in REV_OPTS and "=" in a]
    revs += [args[i + 1] for i, a in enumerate(args[:-1]) if a in REV_OPTS]
    revs += {"reset": ["HEAD"], "stash": ["stash@{0}"], "pull": ["@{u}"]}.get(sub, [])
    return list(dict.fromkeys(revs))


def _patched_settings(d: str, args: list[str]) -> str:
    """The settings file a patch of git apply or am writes, '' when none."""
    for a in (a for a in args if not a.startswith("-")):
        try:
            text = Path(g._path(a, d)).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = re.search(r"(?m)^(?:\+\+\+|---|diff --git)\s.*?(\S*\.claude/settings(?:\.local)?\.json)", text)
        if m:
            return m.group(1)
    return ""


LINK_TYPE = re.compile(r"(?i)^(?:symboliclink|hardlink|junction)$")


def _links(acts, kept: Kept) -> str | None:
    """A link made onto one of Claude Code's settings files or a kept path, in any shell's payload (cmd's mklink LINK
    TARGET, ln's last argument or -t; New-Item -ItemType SymbolicLink, HardLink or Junction -Path)."""
    for words, d in acts:
        prog = g._prog(words[0])
        link = _link_of(prog, words)
        real = g._real(g._path(link, d)) if link else ""
        if real and (kept.settings(real) or kept.inside(real)):
            return f"{prog} onto {link} refused: Claude Code's settings and what sets the floor change by Write or Edit only"
    return None


def _link_of(prog: str, words: list[str]) -> str:
    """The path a link command makes, '' for another command."""
    args = words[1:]
    if prog == "mklink":
        return next((a for a in args if not a.startswith("/")), "")
    if prog == "ln":
        pos, target = _positional(words)
        return target or (pos[-1] if len(pos) > 1 else "")
    if prog in ("new-item", "ni") and any(LINK_TYPE.match(a) for a in args):
        named = next((args[i + 1] for i, a in enumerate(args[:-1]) if re.match(r"(?i)^-(?:path|p)$", a)), "")
        return named or next((a for a in args if not a.startswith("-")), "")
    return ""


def _archived_settings(acts) -> str | None:
    """An extraction whose archive holds one of Claude Code's settings files (its members listed: tar, zip), or one
    whose members the floor cannot list (from its input, 7z, a compression it does not read)."""
    for words, d in acts:
        prog = g._prog(words[0])
        if prog not in EXTRACTORS or _extract_target(prog, words) is None:
            continue
        archive = _archive_of(prog, words[1:])
        members = _members(g._path(archive, d)) if archive and archive != "-" else None
        if members is None:
            return f"{prog} refused: the floor cannot list what the archive holds ({archive or 'its input'})"
        hit = next((m for m in members if SETTINGS.search(m.replace("\\", "/"))), "")
        if hit:
            return f"{prog} refused: the archive holds {hit}, and Claude Code's settings change by Write or Edit only"
    return None


def _archive_of(prog: str, args: list[str]) -> str:
    """The archive an extraction reads: tar's -f (in a group of short options too, or old style: xzf FILE), unzip's
    first argument, Expand-Archive's -Path or first argument, 7z's after x; '-' for tar's input."""
    if prog in ("tar", "bsdtar"):
        return _tar_archive(args)
    if prog == "expand-archive":
        return _expand_archive(args)
    pos = [a for a in args if not a.startswith("-")]
    return pos[1] if prog in ("7z", "7za") and len(pos) > 1 else (pos[0] if pos else "")


def _tar_archive(args: list[str]) -> str:
    """tar's archive: --file=X, --file X, a group of short options holding f (its value attached or next), the old
    style's first word (xzf X); '-' (its input) when none."""
    for i, a in enumerate(args):
        if a.startswith("--file="):
            return a[7:]
        short = a.startswith("-") and not a.startswith("--") and "f" in a
        old_style = i == 0 and re.fullmatch(r"[A-Za-z]+", a) is not None and "f" in a
        if a == "--file" or short or old_style:
            rest = "" if a == "--file" else a[a.index("f") + 1:]
            return rest or (args[i + 1] if i + 1 < len(args) else "")
    return "-"


def _expand_archive(args: list[str]) -> str:
    """Expand-Archive's archive: -Path or -LiteralPath (a prefix PowerShell takes), else its first argument."""
    for i, a in enumerate(args[:-1]):
        low = a.lower()
        if (len(a) > 2 and "-literalpath".startswith(low)) or (len(a) > 1 and "-path".startswith(low)):
            return args[i + 1]
    return next((a for a in args if not a.startswith("-")), "")


def _members(path: str) -> list[str] | None:
    """The member names of a tar or zip archive, None when it cannot be read as one ([] when there is no such file:
    the extraction fails)."""
    import tarfile
    import zipfile
    if not os.path.lexists(path):
        return []
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                return z.namelist()
        with tarfile.open(path) as tf:
            return tf.getnames()
    except (OSError, tarfile.TarError, zipfile.BadZipFile, ValueError, EOFError):
        return None


def _repo_of(folder: str) -> str:
    """The git checkout that holds ``folder`` (the first parent with a .git), as _real gives it; '' for none."""
    p = g._real(folder)
    while True:
        if os.path.exists(os.path.join(p, ".git")):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            return ""
        p = parent


def _checkout(acts, kept: Kept) -> str | None:
    """A git command in (or pointed at, -C) the checkout that holds config.json other than a read: CHECKOUT_SAFE,
    git config and git remote that only read, git pull --ff-only with no remote nor refspec."""
    roots = {r for r in (_repo_of(f) for f in kept.folders) if r}
    if not roots:
        return None
    for _, folder, sub, args in _git(acts):
        if _reads(sub, args) or sub == "!":
            continue
        if _repo_of(folder) in roots:
            return f"git {sub} in {folder} refused: only reads change nothing in the checkout that holds config.json"
    return None


def _reads(sub: str, args: list[str]) -> bool:
    """Whether a git command leaves the checkout's files and settings alone (_checkout)."""
    pos = [a for a in args if not a.startswith("-")]
    if sub == "pull":
        return "--ff-only" in args and not pos
    if sub == "config":
        return bool({"--get", "--get-all", "--get-regexp", "--list", "-l"} & set(args)) or pos[:1] in (["get"], ["list"]) \
            or (len(pos) == 1 and not set(args) & {"--add", "--replace-all", "--unset", "--unset-all"})
    if sub == "remote":
        return not pos or pos[0] in ("show", "get-url")
    return sub in floor.CHECKOUT_SAFE


def _named(acts, command: str) -> str | None:
    """A variable set for later sessions under a name the guard cannot read: setx or SetEnvironmentVariable whose
    name is a concatenation, a variable or a call, not a plain name."""
    for words, _ in acts:
        if g._prog(words[0]) == "setx":
            name = next((w for w in words[1:] if not w.startswith("/")), "")
            if name and not PLAIN.fullmatch(floor.unspelled(name)):
                return f"setx of {name!r} refused: a variable whose name the guard cannot read"
    m = re.search(r"(?i)SetEnvironmentVariable\s*\(\s*([^,)]*)", command)
    if m and not re.fullmatch(r"\s*(['\"])[A-Za-z_]\w*\1\s*", m.group(1)):
        return f"SetEnvironmentVariable({m.group(1).strip()}) refused: a variable whose name the guard cannot read"
    return None


def _plugin_cmd(acts) -> str | None:
    """claude plugin disable, uninstall or marketplace remove of the core plugin or its marketplace, or of a name the
    guard cannot read."""
    cfg = config.claude(config.load())
    for words, _ in acts:
        if g._prog(words[0]) != "claude":
            continue
        low = [w.lower() for w in words[1:]]
        if not ({"plugin", "plugins"} & set(low) and {"disable", "uninstall", "remove", "rm"} & set(low)):
            continue
        names = " ".join(low)
        if cfg["plugin"].lower() in names or cfg["marketplace"].lower() in names or "$" in names:
            return f"claude {' '.join(words[1:4])} refused: it turns off the plugin that runs the guard"
    return None


# --- check main, force and config: what git and the code host push ------------------------------------------------

def git_c(words: list[str]) -> list[str]:
    """The configuration a git command's global options give: ``-c key=value`` and ``--config-env key=VAR`` (as
    ``key=``), in order."""
    out, i = [], 1
    while i < len(words) and words[i].startswith("-"):
        name, eq, val = words[i].partition("=")
        if name in g.GIT_VALUE_OPTS and not eq:
            i += 1
            val = words[i] if i < len(words) else ""
        if name == "-c":
            out.append(val)
        elif name == "--config-env":
            out.append(val.partition("=")[0] + "=")
        i += 1
    return out


def _globals(words: list[str]) -> list[str]:
    """The names of a git command's global options, before its subcommand."""
    out, i = [], 1
    while i < len(words) and words[i].startswith("-"):
        name, eq, _ = words[i].partition("=")
        out.append(name)
        i += 2 if name in g.GIT_VALUE_OPTS and not eq else 1
    return out


def check_floor(cmds, fl: dict, command: str = "", shell: str = "bash") -> tuple[str, str, None] | None:
    """(check, reason, None) for what breaks the floor through git or the code host (module docstring), under
    config.json floor.refuse or floor.only (``fl``: floor.settings); None otherwise. ``shell``: bash or ps."""
    if not on(fl):
        return None
    acts = [(words, d) for words, d, _, _ in g.actions(cmds, shell, command=command)]
    for words, _ in acts:
        what = _gh_write(words)
        if what:
            return "main", f"gh api {what} refused: a write of main's ref through the code host's API{TAIL}", None
    for words, d, sub, args in _git(acts):
        hit = _git_refusal(words, d, sub, args)
        if hit:
            return hit[0], hit[1] + TAIL, None
    return None


def _git_refusal(words: list[str], d: str, sub: str, args: list[str]) -> tuple[str, str] | None:
    """(check, what) for one git command (an alias resolved) that breaks the floor, else None."""
    hit = _config_refusal(words, sub, args) or _runs(sub, args)
    if hit:
        return "config", hit
    if sub == "!":
        return "main", f"the git command {args[0][:60]!r} refused: what it runs is out of the floor's reading"
    if sub == "send-pack":
        return "main", "git send-pack refused: it writes the remote's refs directly"
    pos = [a for a in args if not a.startswith("-")]
    if sub == "symbolic-ref" and len(pos) >= 2 and pos[0].startswith("refs/heads/"):
        return "main", "git symbolic-ref of a branch refused: a push of it writes the branch it points at"
    return _push(d, args) if sub == "push" else None


def _config_refusal(words: list[str], sub: str, args: list[str]) -> str:
    """What a git command sets of git's configuration while the floor is on: anything by -c or --config-env, a global
    option the floor does not know (floor.GIT_GLOBAL_OK), a key of floor.PUSH_KEYS by git config, a mirror remote by
    git remote add; '' else."""
    given = git_c(words)
    if given:
        return f"git -c {given[0].partition('=')[0]} refused: configuration from the command line"
    odd = next((o for o in _globals(words) if o not in floor.GIT_GLOBAL_OK), "")
    if odd:
        return f"git {odd} refused: a global option the floor does not read"
    key = _config_write(args) if sub == "config" else ""
    if key or (sub == "remote" and any(a.startswith("--mirror") for a in args)):
        return f"git setting {key or 'a mirror remote'} refused: it changes what a push sends"
    return ""


# The transports whose URL runs a program (ext::, fd::; protocol.<name>.allow is a key of floor.PUSH_KEYS).
TRANSPORTS = re.compile(r"(?i)^(?:[\w.+-]*=)?(?:ext|fd)::")
# floor.GIT_RUNNING_OPTS and the prefixes git takes of them (--out, --upl, --rece; --text alone is git's own option).
RUNNING_LONG = re.compile(r"^--(?:out\w*(?:-\w+)*|open-f[\w-]*|upl[\w-]*|rece[\w-]*|exec|ext-[\w-]*|textc\w*|extc\w*|"
                          r"unsafe-p\w*)$")


def _runs(sub: str, args: list[str]) -> str:
    """A git option or subcommand that writes a file or runs a program (floor.GIT_RUNNING_OPTS anywhere, the short
    ones of floor.GIT_RUNNING_SHORT for their subcommand, bisect run, submodule foreach, filter-branch...); ''
    else."""
    for a in args:
        name = a.partition("=")[0]
        if TRANSPORTS.match(a):
            return f"git {sub} {a[:20]} refused: a transport that runs a program"
        if sub == "format-patch" and name in ("-o", "--output-directory"):
            continue   # NNNN-*.patch files in a folder (round 6, #12)
        if RUNNING_LONG.match(name):
            return f"git {sub} {name} refused: it writes a file or runs a program"
        short = floor.GIT_RUNNING_SHORT.get(sub, ())
        if any(a == s or (a.startswith(s) and len(a) > len(s)) for s in short):
            return f"git {sub} {a[:2]} refused: it writes a file or runs a program"
    if sub in floor.GIT_RUNNERS and (not floor.GIT_RUNNERS[sub] or floor.GIT_RUNNERS[sub] in args):
        return f"git {sub} {floor.GIT_RUNNERS[sub]} refused: it runs what it is given or writes refs".replace("  ", " ")
    return ""


def _push(d: str, args: list[str]) -> tuple[str, str] | None:
    """(check, what) for a git push that breaks the floor. A push that names no refspec is read as git sends it: the
    remote's mirror flag and push refspecs, else push.default. A branch that is a symbolic ref is read as the branch
    it points at. git is asked only what the push needs."""
    if "-h" in args or "--help" in args:
        return None
    unread = next((a for a in args if re.search(r"\$\(|`|\$\{|\$\w", a)), "")
    if unread:
        return "main", f"git push {unread[:40]} refused: a remote or refspec the floor cannot read"
    remote, refspecs, flags = g._push_target(args)
    current = g._git_out(d, "rev-parse", "--abbrev-ref", "HEAD").strip() if floor.needs_current(refspecs, flags) \
        else ""
    if not refspecs and floor.needs_current(refspecs, flags):
        refspecs = _defaults(d, remote, current)
        if isinstance(refspecs, tuple) or not refspecs:
            return refspecs or None   # a mirror push; or nothing sent (push.default nothing, no branch checked out)
    hit = floor.push_refusal(_unsymref(d, refspecs), flags, current)
    return (hit[0], f"git push refused: {hit[1]}") if hit else None


def _defaults(d: str, remote: str, current: str):
    """What a push that names no refspec sends (floor.default_refspecs), or (check, what) for a mirror push."""
    conf = floor.git_config(g._git_out(d, "config", "-z", "--list"))
    remote = remote or floor.default_remote(conf, current)
    if floor.truthy(floor.last(conf, f"remote.{remote}.mirror")):
        return "force", f"git push refused: a mirror push (remote.{remote}.mirror)"
    return floor.default_refspecs(conf, remote, current)


def _unsymref(d: str, refspecs: list[str]) -> list[str]:
    """``refspecs`` with each bare branch that is a symbolic ref written to the branch it points at (git asked only
    when a bare branch is pushed)."""
    if not any(":" not in r and r.lstrip("+") not in floor.HEAD and "*" not in r for r in refspecs):
        return refspecs
    syms = {}
    for line in g._git_out(d, "for-each-ref", "--format=%(refname:short)%00%(symref)", "refs/heads").splitlines():
        name, _, target = line.partition("\0")
        if target:
            syms[name] = floor.HEADS.sub("", target)
    return [f"{r}:{syms[r.lstrip('+')]}" if ":" not in r and r.lstrip("+") in syms else r for r in refspecs]


def _config_write(args: list[str]) -> str:
    """The key ``git config ARGS`` sets when it is one of floor.PUSH_KEYS ('' for a read, an unset or another key):
    ``KEY VALUE``, ``set KEY VALUE``, ``--add``/``--replace-all KEY VALUE``, and ``--rename-section`` to a section of
    those keys; a write into another file than a repo's own configuration (-f)."""
    pos, file, verdict = _config_args(args)
    if verdict is not None:
        return verdict
    if pos[:1] == ["set"]:
        pos = pos[1:]
    elif pos[:1] in (["get"], ["list"], ["unset"]):
        return ""
    if len(pos) >= 2 and file and not re.search(r"(?:^|[\\/])\.git[\\/]config$", file):
        return f"{pos[0]} into {file}"   # a write of another file than a repo's own configuration
    if len(pos) < 2 or not floor.PUSH_KEYS.match(pos[0]):
        return ""
    if floor.SAFE_KEYS.match(pos[0]) or (pos[0].lower() == "credential.helper" and
                                         floor.CREDENTIAL_VALUE.match(pos[1])):
        return ""   # an ordinary repo's key: it runs nothing and redirects no write (round 6, #12)
    return pos[0]


CONFIG_READS = ("--get", "--get-all", "--get-regexp", "--list", "-l", "--remove-section", "-e", "--edit")


def _config_args(args: list[str]) -> tuple[list[str], str, str | None]:
    """(git config's positional arguments, its -f file, a verdict already reached: '' for a read or an unset, the new
    section of a --rename-section into floor.PUSH_KEYS; None to go on)."""
    pos, i, file = [], 0, ""
    while i < len(args):
        a = args[i]
        if a in ("--file", "-f") or a.startswith("--file="):
            file = a.partition("=")[2] or (args[i + 1] if i + 1 < len(args) else "")
            i += 1 if "=" in a else 2
            continue
        if a in ("--blob", "--type", "--default", "--comment"):
            i += 2
            continue
        if a == "--rename-section" and i + 2 < len(args):
            return pos, file, (args[i + 2] if floor.PUSH_KEYS.match(args[i + 2] + ".x") else "")
        if a.startswith("--unset") or a in CONFIG_READS:
            return pos, file, ""
        if not a.startswith("-"):
            pos.append(a)
        i += 1
    return pos, file, None


def _known(folder: str) -> set[str]:
    """git's own subcommands and the git-<name> programs on PATH (git --list-cmds), once per process."""
    if folder not in _LIST_CMDS:
        _LIST_CMDS[folder] = set(g._git_out(folder, "--list-cmds=main,others,nohelpers").split())
    return _LIST_CMDS[folder]


def _git(acts):
    """(words, folder, subcommand, arguments) of each git command of ``acts``, an alias resolved to what it runs, an
    alias of an alias too (alias.<name> of git's configuration; ten levels at most). A shell alias (``!``), an alias
    that starts with an option, one deeper than ten levels, or a subcommand that is neither git's nor an alias is
    subcommand '!' (the floor cannot read it)."""
    for words, d in acts:
        parts = g.git_parts(words, d) if g._prog(words[0]) == "git" else None
        if not parts:
            continue
        folder, sub, args = parts
        conf = None
        for _ in range(11):
            if sub in floor.GIT_BUILTIN:
                break
            conf = conf if conf is not None else floor.git_config(g._git_out(folder, "config", "-z", "--list"))
            alias = floor.last(conf, f"alias.{sub.lower()}")
            if not alias:
                if sub not in _known(folder):
                    sub, args = "!", [sub]
                break
            try:
                run = shlex.split(alias)
            except ValueError:
                run = []
            if alias.startswith("!") or not run or run[0].startswith("-"):
                sub, args = "!", [alias]
                break
            sub, args = run[0], run[1:] + args
        else:
            sub, args = "!", [sub]
        yield words, folder, sub, args


GRAPHQL_REF = re.compile(r"(?i)\b(?:updateRefs?|createRef|deleteRef|createCommitOnBranch|mergeBranch)\b")


def _gh_write(words: list[str]) -> str:
    """The endpoint a ``gh api`` call writes main's or master's ref through (git/refs, merges, with -X, --method or
    a field, short options glued or not), or a GraphQL mutation of refs; else ''."""
    if g._prog(words[0]) != "gh" or words[1:2] != ["api"]:
        return ""
    text = " ".join(words[2:])
    if "graphql" in text and GRAPHQL_REF.search(text):
        return "graphql " + GRAPHQL_REF.search(text).group(0)
    write = re.search(r"(?i)(?:^|\s)(?:-X\s*|--method[\s=]+)(?:POST|PATCH|PUT|DELETE)\b|"
                      r"(?:^|\s)(?:-[fF]|--field|--raw-field|--input)", text)
    if write and re.search(r"git/refs|/merges\b", text) and re.search(r"\b(?:main|master)\b", text):
        return next((w for w in words[2:] if "/" in w and not w.startswith("-")), text)[:120]
    return ""
