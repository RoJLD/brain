"""The locked floor's guard (wi-brain-unadopted-floor, brain.floor; docs/guards.md, the locked floor): the checks
brain.guards runs while config.json floor.refuse or floor.only is on.

- :func:`check_floor`: a git push to main or master (check ``main``) or a forced push (``force``), read as git reads
  it (aliases followed, the remote's mirror flag, push.default, symbolic branches); git configuration given by the
  command line (``-c``, ``--config-env``), by the environment (GIT_CONFIG*, GIT_DIR...) or written by ``git config``
  for the keys that change a push (``config``); send-pack, ``symbolic-ref`` of a branch and the code host's API
  writes of main's ref (``main``).
- :func:`check_files` (check ``config``): what would lift or stop the floor: a write of the config.json the guard
  reads, of its pointer or of git's configuration files; a removal or a move of a folder that holds one, or of the
  guard's interpreter (<BRAIN_HOME>/venv), or a write into it; a git command other than CHECKOUT_SAFE in the checkout
  that holds config.json; a variable that chooses that file or stops the guards (brain.floor.FLOOR_ENV) set for
  later sessions, including by a name the guard cannot read (a concatenation, a variable); Claude Code's settings
  that turn the core plugin off, read on their decoded JSON.

A guard of the command line cannot be complete: what it does not read is listed under « Limits » in docs/guards.md,
and the code host's branch protection on main is the backstop.
"""

from __future__ import annotations

import os
import re
import shlex

from . import config, floor, paths
from . import guards as g

TAIL = ("; that breaks the locked floor (no push to main or master, no force-push: merge by a pull request; the "
        "owner's own terminal for the rest)")
REMOVERS = {"rm", "rmdir", "unlink", "shred", "remove-item", "ri", "rd", "del", "erase"}
MOVERS = {"mv", "move", "mi", "move-item", "rename-item", "ren", "rni", "rename"}
PLAIN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
ROBOCOPY_OPT = re.compile(r"/[A-Za-z]+(?::\S*)?")


def on(fl: dict) -> bool:
    return bool(fl["refuse"] or fl["only"])


def _under(path: str, folder: str) -> bool:
    """Whether ``path`` is ``folder`` or inside it (both as _real gives them)."""
    return bool(path) and bool(folder) and (path == folder or path.startswith(folder.rstrip("\\/") + os.sep))


def protected(cfg_file) -> tuple[list[str], str]:
    """The files that set the floor (the config.json the guard reads, the pointer <BRAIN_HOME>/personal.json) and the
    folder of the guard's interpreter (<BRAIN_HOME>/venv), as the file system resolves them."""
    home = paths.brain_home()
    return [g._real(f) for f in (cfg_file, home / paths.PERSONAL) if f], g._real(home / "venv")


# --- check config: what would lift or stop the floor ---------------------------------------------------------------

def check_files(tool: str, inp: dict, cmds, cwd: str, fl: dict, cfg_file, command: str = "") -> str | None:
    """While the floor is on, what would lift it or stop the guard for this session or the next (module docstring),
    else None. A worktree's own config.json is another file: a pull request still changes it."""
    if not on(fl) or not (tool in g.EDIT_TOOLS or cmds):
        return None
    files, venv = protected(cfg_file)
    what = _edit(tool, inp, cwd, files, venv) if tool in g.EDIT_TOOLS else \
        _shell(cmds, "ps" if tool == "PowerShell" else "bash", command, files, venv)
    return (f"{what}; the locked floor (config.json floor) is {config.owner_of()}'s to change, in their own terminal "
            "(BRAIN_GUARD_ALLOW=floor lifts it)") if what else None


def _edit(tool: str, inp: dict, cwd: str, files: list[str], venv: str) -> str | None:
    """What a tool edit would lift or stop the floor by: a floor file or the interpreter's folder (the path resolved:
    a stream's name, a junction), git's configuration files, or Claude Code's settings or a profile that set a
    variable of FLOOR_ENV or turn the core plugin off, read on the decoded text."""
    target = g._edit_target(inp, tool, cwd)
    if not target:
        return None
    real = g._resolved(target)
    if real in files:
        return f"{tool} refused: {target} sets the floor"
    if _under(real, venv):
        return f"{tool} refused: {target} is in the guard's interpreter (<BRAIN_HOME>/venv)"
    if floor.GIT_CONFIG_FILES.search(real) or floor.GIT_CONFIG_FILES.search(target):
        return f"{tool} refused: {target} is git's configuration (an alias or a mirror there changes what a push does)"
    if not g._override_file(target):
        return None
    text = floor.unspelled(g._edit_text(inp))
    hit = re.search(floor.FLOOR_ENV, text, re.I)
    if hit:
        return f"{tool} refused: it writes {re.findall(r'[A-Za-z_]+', hit.group(0))[-1]} into {target}, which moves or " \
               "stops the floor"
    return f"{tool} refused: it turns the core plugin off in {target}" if _plugin_off(text) else None


def _plugin_off(text: str) -> bool:
    """Whether settings text turns the core plugin (the one that carries guard.sh) off in enabledPlugins."""
    plugin = config.claude(config.load())["plugin"]
    return bool(re.search(rf"{re.escape(plugin)}(?:@[^\s:,]*)?\s*:\s*false", text))


def _shell(cmds, sub: str, command: str, files: list[str], venv: str) -> str | None:
    """What a shell call would lift or stop the floor by (check_files), else None."""
    what = (_removals(cmds, [*files, venv]) or _writes(cmds, sub, files, venv) or _checkout(cmds, files)
            or _named(cmds, command, sub))
    if what:
        return what
    what = g._override(command, cmds, sub, env=floor.FLOOR_ENV + "|enabledPlugins")
    return f"{what} refused: it moves or stops the floor" if what else None


def _writes(cmds, sub: str, files: list[str], venv: str) -> str | None:
    """A shell write of a floor file, into the interpreter's folder, or of git's configuration files."""
    for what, target in g.shell_writes(cmds, sub):
        real = g._resolved(target)
        if real in files:
            return f"{what} into {target} refused: it sets the floor"
        if _under(real, venv):
            return f"{what} into {target} refused: it is in the guard's interpreter (<BRAIN_HOME>/venv)"
        if real and floor.GIT_CONFIG_FILES.search(real):
            return f"{what} into {target} refused: it is git's configuration"
    return None


def _removals(cmds, kept: list[str]) -> str | None:
    """A removal or a move of a folder that holds a floor file or the interpreter's folder, or of that file or folder
    itself: rm, mv, Remove-Item, Move-Item, Rename-Item..., robocopy /MIR or /PURGE onto it, /MOVE from it. A write
    into such a folder (cp, tar -C, Expand-Archive) is no removal."""
    for words, d in cmds:
        prog = g._prog(words[0])
        if prog not in REMOVERS | MOVERS | {"robocopy"}:
            continue
        opts = {w.split(":")[0].upper() for w in words[1:] if ROBOCOPY_OPT.fullmatch(w)} if prog == "robocopy" else set()
        pos = [w for w in words[1:] if not w.startswith("-") and not (prog == "robocopy" and ROBOCOPY_OPT.fullmatch(w))]
        if prog in REMOVERS:
            targets = pos
        elif prog in MOVERS:
            targets = pos[:-1] if len(pos) > 1 else pos   # the sources; the last is where they go
        else:   # robocopy SRC DST: /MIR and /PURGE remove from DST, /MOVE and /MOV from SRC
            targets = (pos[1:2] if opts & {"/MIR", "/PURGE"} else []) + (pos[:1] if opts & {"/MOVE", "/MOV"} else [])
        for t in targets:
            real = g._real(g._path(t, d))
            if any(_under(k, real) for k in kept):
                return f"{prog} of {t} refused: it removes or moves what sets the floor or runs the guard"
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


def _checkout(cmds, files: list[str]) -> str | None:
    """A git command in (or pointed at, -C, --git-dir, --work-tree) the checkout that holds config.json that is not
    one of CHECKOUT_SAFE (git pull only with --ff-only), an alias read as what it runs."""
    roots = {r for r in (_repo_of(os.path.dirname(f)) for f in files) if r}
    if not roots:
        return None
    for _, folder, sub, args in _git(cmds):
        if sub in floor.CHECKOUT_SAFE or (sub == "pull" and "--ff-only" in args) or sub == "!":
            continue
        if _repo_of(folder) in roots:
            return f"git {sub} in {folder} refused: only reads change nothing in the checkout that holds config.json"
    return None


def _named(cmds, command: str, sub: str) -> str | None:
    """A variable set for later sessions under a name the guard cannot read: setx, a registry Environment value or
    SetEnvironmentVariable whose name is a concatenation, a variable or a call, not a plain name."""
    for words, _, _, _ in g.actions(cmds, sub, command=command):
        prog = g._prog(words[0])
        if prog == "setx":
            name = next((w for w in words[1:] if not w.startswith("/")), "")
            if name and not PLAIN.fullmatch(floor.unspelled(name)):
                return f"setx of {name!r} refused: a variable whose name the guard cannot read"
    # the registry's Environment key: its value's name read on the command's text (a parenthesis splits the words)
    m = re.search(r"(?i)\b(?:set-itemproperty|new-itemproperty|sp|reg)\b[^;|&\n]*[\\/:]Environment\b[^;|&\n]*?"
                  r"(?:-name|/v)\s+(\S+)", command)
    if m and not PLAIN.fullmatch(m.group(1).strip("'\"")):
        return f"a registry value named {m.group(1)!r} refused: a variable whose name the guard cannot read"
    m = re.search(r"(?i)SetEnvironmentVariable\s*\(\s*([^,)]*)", command)
    if m and not re.fullmatch(r"\s*(['\"])[A-Za-z_]\w*\1\s*", m.group(1)):
        return f"SetEnvironmentVariable({m.group(1).strip()}) refused: a variable whose name the guard cannot read"
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


def check_floor(cmds, fl: dict, command: str = "") -> tuple[str, str, None] | None:
    """(check, reason, None) for what breaks the floor through git or the code host (module docstring), under
    config.json floor.refuse or floor.only (``fl``: floor.settings); None otherwise."""
    if not on(fl):
        return None
    m = floor.GIT_ENV.search(command)
    if m:
        return "config", f"{m.group(0).rstrip('= ')} refused: git configuration from the environment{TAIL}", None
    for words, _ in cmds:
        what = _gh_write(words)
        if what:
            return "main", f"gh api {what} refused: a write of main's ref through the code host's API{TAIL}", None
    for words, d, sub, args in _git(cmds):
        hit = _git_refusal(words, d, sub, args)
        if hit:
            return hit[0], hit[1] + TAIL, None
    return None


def _git_refusal(words: list[str], d: str, sub: str, args: list[str]) -> tuple[str, str] | None:
    """(check, what) for one git command (an alias resolved) that breaks the floor, else None."""
    given = git_c(words)
    if given:
        return "config", f"git -c {given[0].partition('=')[0]} refused: configuration from the command line"
    key = _config_write(args) if sub == "config" else ""
    if key or (sub == "remote" and any(a.startswith("--mirror") for a in args)):
        return "config", f"git setting {key or 'a mirror remote'} refused: it changes what a push sends"
    if sub == "!":
        return "main", f"the git alias {args[0][:60]!r} refused: an alias the floor cannot read"
    if sub == "send-pack":
        return "main", "git send-pack refused: it writes the remote's refs directly"
    pos = [a for a in args if not a.startswith("-")]
    if sub == "symbolic-ref" and len(pos) >= 2 and pos[0].startswith("refs/heads/"):
        return "main", "git symbolic-ref of a branch refused: a push of it writes the branch it points at"
    return _push(d, args) if sub == "push" else None


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
    ``KEY VALUE``, ``set KEY VALUE``, ``--add``/``--replace-all KEY VALUE``."""
    pos, i = [], 0
    while i < len(args):
        a = args[i]
        if a in ("--file", "-f", "--blob", "--type", "--default", "--comment"):
            i += 2
            continue
        if a.startswith("--unset") or a in ("--get", "--get-all", "--get-regexp", "--list", "-l", "--remove-section",
                                            "--rename-section", "-e", "--edit"):
            return ""
        if not a.startswith("-"):
            pos.append(a)
        i += 1
    if pos[:1] == ["set"]:
        pos = pos[1:]
    elif pos[:1] in (["get"], ["list"], ["unset"]):
        return ""
    return pos[0] if len(pos) >= 2 and floor.PUSH_KEYS.match(pos[0]) else ""


def _git(cmds):
    """(words, folder, subcommand, arguments) of each git command of ``cmds``, an alias resolved to what it runs, an
    alias of an alias too (alias.<name> of git's configuration; ten levels at most). A shell alias (``!``), an alias
    that starts with an option, or one deeper than ten levels is subcommand '!' (the floor cannot read it)."""
    for words, d in cmds:
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
