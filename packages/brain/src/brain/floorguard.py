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
    r"Environment\b|\breg(?:\.exe)?\s+(?:add|delete|import|copy|restore|load)\b|(?:Registry|RegistryKey)\]?::"
    r"[^;\n]*Environment|\bCurrentUser\b[^;\n]*OpenSubKey\s*\([^)]*Environment|SetValue\s*\([^)]*Environment)")
_LIST_CMDS: dict[str, set[str]] = {}


def on(fl: dict) -> bool:
    return bool(fl["refuse"] or fl["only"])


def _under(path: str, folder: str) -> bool:
    """Whether ``path`` is ``folder`` or inside it (both as _real gives them)."""
    return bool(path) and bool(folder) and (path == folder or path.startswith(folder.rstrip("\\/") + os.sep))


class Kept:
    """What the floor keeps (as the file system resolves it): the files that set it (the config.json the guard reads,
    the pointer <BRAIN_HOME>/personal.json), the guard's interpreter (<BRAIN_HOME>/venv), the plugin that runs the
    guard (~/.claude/plugins, $CLAUDE_PLUGIN_ROOT), and the folders of the files (the checkout, BRAIN_HOME)."""

    def __init__(self, cfg_file):
        home = paths.brain_home()
        self.files = [g._real(f) for f in (cfg_file, home / paths.PERSONAL) if f]
        self.venv = g._real(home / "venv")
        self.plugins = [g._real(p) for p in (Path.home() / ".claude" / "plugins", os.environ.get("CLAUDE_PLUGIN_ROOT"))
                        if p]
        self.folders = sorted({os.path.dirname(f) for f in self.files})
        self.paths = [*self.files, self.venv, *self.plugins]

    def inside(self, real: str) -> bool:
        """Whether ``real`` is a kept file, or in the interpreter's or the plugin's folder."""
        return real in self.files or any(_under(real, k) for k in (self.venv, *self.plugins))

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
    what = (_opaque(cmds, acts) or _env(plain) or _registry(plain) or _removals(acts, kept) or _writes(cmds, sub, kept)
            or _copies(acts, kept) or _extractions(acts, kept) or _checkout(acts, kept) or _named(acts, command)
            or _plugin_cmd(acts))
    if what:
        return what
    what = g._override(command, cmds, sub, env=floor.FLOOR_ENV + "|enabledPlugins")
    return f"{what} refused: it moves or stops the floor" if what else None


PAYLOAD = re.compile(r"(?i)(?:(?:^|\s)(?:-c|/c|-command|-argumentlist|eval|iex|invoke-expression)\s+)$")


def _code(command: str) -> str:
    """``command`` without the prose it quotes: a quoted string holding a space is taken out (an echo's words, a
    commit message, a line written to a profile), but a shell's or eval's payload (-c, -Command, eval, iex), which
    runs; a quoted word stays (GIT_""CONFIG_COUNT, "NAME=value")."""
    def keep(m: re.Match) -> str:
        s, before = m.group(0), command[:m.start()]
        prose = re.search(r"\s", s) and not re.search(r"[\w=]$", before) and not PAYLOAD.search(before)
        return " Q " if prose else s
    return re.sub(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"", keep, command)   # quotes paired left to right


def _opaque(cmds, acts) -> str | None:
    """A wrapper whose payload the floor cannot read: eval or a shell's -c given a variable or a substitution,
    Start-Process with -ArgumentList, xargs running git or what writes files (read before it is unwrapped)."""
    for words, _ in cmds:
        if g._prog(words[0]) == "xargs" and any(g._prog(a) in OPAQUE_XARGS for a in words[1:] if not a.startswith("-")):
            return "xargs refused: the floor cannot read the arguments it gives"
    return next((what for words, _ in acts if (what := _unread(g._prog(words[0]), words[1:]))), None)


def _unread(prog: str, args: list[str]) -> str:
    """Why one command's payload is out of the floor's reading, else ''."""
    if prog == "eval" and any(c in " ".join(args) for c in "$`"):
        return "eval of a variable refused: the floor cannot read what it runs"
    k = next((i for i, a in enumerate(args) if a.lower() in ("-c", "/c", "-command")), -1)
    if prog in SHELLS and 0 <= k < len(args) - 1 and re.match(r"\s*[$`]", args[k + 1]):
        return f"{prog} -c of a variable refused: the floor cannot read what it runs"
    if prog in ("start-process", "saps", "start") and any(re.match(r"(?i)^-(?:a(?:r(?:g\w*)?)?)$", a) for a in args):
        return f"{prog} -ArgumentList refused: the floor cannot read what it runs"
    return ""


def _env(plain: str) -> str | None:
    """A variable of brain.floor.WATCHED_VARS assigned in any form, or an assignment whose name the guard cannot read
    (on the call's unspelled text)."""
    m = floor.ENV_ASSIGN.search(plain) or floor.ENV_DYNAMIC.search(plain)
    return f"{m.group(0).strip()[:60]!r} refused: a variable the floor watches (or one it cannot read) set" if m else None


def _registry(plain: str) -> str | None:
    """Any write to the registry's Environment key (Set-ItemProperty, New-ItemProperty, .NET's Registry, reg add or
    import), whatever the value's name."""
    m = REGISTRY_ENV.search(plain)
    return f"{m.group(0)[:60]!r} refused: a write of the registry's Environment key" if m else None


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
        if prog not in COPIERS:
            continue
        for real, whole in _copied(prog, words, d):
            if kept.inside(real) or (whole and (real in kept.folders or kept.holds(real))):
                return f"{prog} into {real} refused: it writes what sets the floor or runs the guard"
    return None


def _copied(prog: str, words: list[str], d: str) -> list[tuple[str, bool]]:
    """(the path a copy writes, whether a whole folder lands there) for each source of a copy."""
    if prog == "robocopy":
        return _robocopied(words, d)
    pos, target = _positional(words)
    dest, sources = (target, pos) if target else (pos[-1] if pos else "", pos[:-1])
    if not dest:
        return []
    dst = g._real(g._path(dest, d))
    into = bool(target) or len(sources) > 1 or os.path.isdir(dst) or dest.endswith(("/", "\\"))
    whole = _recursive(prog, words)
    return [_lands(src, dst, into, whole) for src in sources]


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
    hit = _config_refusal(words, sub, args)
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


def _push(d: str, args: list[str]) -> tuple[str, str] | None:
    """(check, what) for a git push that breaks the floor. A push that names no refspec is read as git sends it: the
    remote's mirror flag and push refspecs, else push.default. A branch that is a symbolic ref is read as the branch
    it points at. git is asked only what the push needs."""
    if "-h" in args or "--help" in args:
        return None
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
    those keys."""
    pos, i = [], 0
    while i < len(args):
        a = args[i]
        if a in ("--file", "-f", "--blob", "--type", "--default", "--comment"):
            i += 2
            continue
        if a == "--rename-section" and i + 2 < len(args):
            return args[i + 2] if floor.PUSH_KEYS.match(args[i + 2] + ".x") else ""
        if a.startswith("--unset") or a in ("--get", "--get-all", "--get-regexp", "--list", "-l", "--remove-section",
                                            "-e", "--edit"):
            return ""
        if not a.startswith("-"):
            pos.append(a)
        i += 1
    if pos[:1] == ["set"]:
        pos = pos[1:]
    elif pos[:1] in (["get"], ["list"], ["unset"]):
        return ""
    return pos[0] if len(pos) >= 2 and floor.PUSH_KEYS.match(pos[0]) else ""


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
