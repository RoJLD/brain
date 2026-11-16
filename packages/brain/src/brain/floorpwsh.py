"""PowerShell's pipelines and .NET's writers under the floor, and the later rounds' write classes (wi-brain-unadopted-
floor, review rounds 7-14; brain.floorguard calls them): a path piped into a cmdlet that writes is its -Path, a .NET
method that writes is refused on what the floor keeps, the environment written through COM or a RegistryKey is refused
whatever the statement; a stream of a settings or customization file, a frontmatter that adds hooks, and a patch read
from standard input are refused. Round 14 refuses classes, not spellings: a link however it is made (links), any
write into a .git folder (GIT_DIR), a queue resumed (resumes), git apply unless read-only as git parses it
(apply_reads_only), a path the floor cannot resolve where it may reach what it keeps (expand, unresolved_reach)."""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from . import floor
from . import guards as g

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
# Round 8 #6: a .NET type held in a variable ($t = [type]'IO.File', $t = [IO.File], $t = 'IO.File' -as [type],
# $t = [Type]::GetType(...)), then a static member called through it ($t::WriteAllText(...)), which the parser cannot
# tie to a type: refused under the floor whatever the member.
TYPE_VAR = re.compile(r"(?i)\$(?:\{)?(\w+)\}?\s*=\s*(?:\[type\]|\[[\w.]+\]\s*(?=$|[;|\n)}])|\S+\s+-as\s+\[type\]|"
                      r"\[(?:system\.)?type\]::gettype\s*\()")
# Round 9 #3, as a class: a static member whose receiver is not a literal [Type] (a parenthesised expression, a
# variable, $_, ${...}), and reflection on a type (GetMethod, InvokeMember, UnderlyingSystemType...). Best-effort.
TYPE_CALL = re.compile(r"(?i)(?:\)|\}|\$[\w:]+)\s*::\s*\w|\]\s*\.\s*(?:GetMethods?|GetMembers?|InvokeMember|GetField|"
                       r"GetProperty|UnderlyingSystemType|GetType)\b|\.Invoke\s*\(\s*\$null\b|"
                       # round 10 #6: a member named by an expression (::("Write"+"AllText")), a method group invoked
                       r"::\s*[(\"'$]|::\s*\w+\s*\.\s*Invoke\s*\(|"
                       r"\)\s*\.\s*Invoke\s*\(")   # round 11 #7: a method group reached through parentheses
# Round 14 (refused as classes, not spellings): any .git folder, written by anything but git itself (its rebase and
# am state, its hooks, its gitdir pointer); a path the floor cannot resolve (a glob, a brace, a substitution, a
# variable, a splat); the names a glob or a brace may reach that the floor keeps.
GIT_DIR = re.compile(r"(?i)(?:^|[\\/])\.git(?:[\\/]|$)")
UNREAD = re.compile(r"[*?\[\]{}$`]|^@|^~[^\\/]")
GUARDED_NAMES = (".git", ".claude", "settings.json", "settings.local.json", ".mcp.json", ".claude.json")
CLAUDE_DIR = re.compile(r"(?i)(?:^|[\\/])\.claude(?:[\\/]|$)")
HOME_VARS = re.compile(r"(?i)^(?:\$env:(?:USERPROFILE|HOME)|\$\{env:(?:USERPROFILE|HOME)\}|\$HOME|~)(?=$|[\\/])")


def _unq(word: str) -> str:
    return word[1:-1] if len(word) > 1 and word[0] == word[-1] and word[0] in "'\"" else word


def _touches(word: str, d: str, kept) -> bool:
    """Whether ``word``, read as a path (the home's variables expanded), is kept, above a kept path, one of Claude
    Code's settings files or git's configuration."""
    real = g._real(g._path(HOME_VARS.sub(lambda m: str(Path.home()).replace("\\", "/"), word), d))
    return bool(real) and (kept.inside(real) or kept.holds(real) or real in kept.folders or kept.settings(real)
                           or bool(floor.GIT_CONFIG_FILES.search(real)))


def piped(command: str, acts, kept) -> str | None:
    """A path piped into a cmdlet that writes, moves or removes (PIPE_WRITERS) that _touches."""
    d = acts[0][1] if acts else os.getcwd()
    for stmt in re.split(r"[;\n]", command):
        parts = stmt.split("|")
        for left, right in zip(parts, parts[1:], strict=False):
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


def typed(plain: str) -> str | None:
    """A static member reached through anything but a literal [Type] (TYPE_CALL), or through a variable that holds a
    .NET type (TYPE_VAR). A link made by code is judged per command (links), not on the call's whole text (round 13:
    a search that names a link function passes)."""
    m = TYPE_CALL.search(plain)
    if m:
        return (f"{m.group(0).strip()} refused: a .NET member reached through a type the floor cannot read (name the "
                "type: [IO.File]::...)")
    for name in {m.group(1) for m in TYPE_VAR.finditer(plain)}:
        if re.search(r"(?i)\$(?:\{" + re.escape(name) + r"\}|" + re.escape(name) + r"\b)\s*::", plain):
            return (f"${name}:: refused: a .NET type held in a variable, whose static members the floor cannot read "
                    "(name the type: [IO.File]::...)")
    return None


def methods(command: str, acts, kept) -> str | None:
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


def customized(tool: str, inp: dict, target: str, real: str) -> str | None:
    """A tool write to a stream of a settings or customization file (round 10 #1), or one that adds frontmatter hooks
    to a skill, command or agent (round 9 #2): the refusal; '' for a customization file it lets through; None when
    the target is neither (the settings checks go on)."""
    custom = floor.CUSTOMIZATION.search(real) or floor.CUSTOMIZATION.search(target)
    if GIT_DIR.search(real) or GIT_DIR.search(str(target)):   # round 14: any .git folder, by anything but git
        return f"{tool} refused: {target} is in a .git folder (its state, hooks and pointer change by git alone)"
    if g.STREAM.search(str(target)) and (custom or g._override_file(target)):
        return f"{tool} refused: {target} names a stream of a settings or customization file"
    if custom:
        return floor.frontmatter_hooks(tool, target, *g._edit_result(inp, tool, target)) or ""
    return None


# --- round 14: git's patch readers and resumers, their options read as git reads them --------------------------------

# git apply's long options (git 2.46, apply -h): name -> (takes a value, harmless while the patch is only read).
APPLY_LONG = {"exclude": (True, True), "include": (True, True), "no-add": (False, True), "add": (False, True),
              "stat": (False, True), "numstat": (False, True), "summary": (False, True), "check": (False, True),
              "index": (False, True), "intent-to-add": (False, True), "cached": (False, True),
              "unsafe-paths": (False, False), "apply": (False, True), "3way": (False, True),
              "build-fake-ancestor": (True, False), "whitespace": (True, True), "ignore-space-change": (False, True),
              "ignore-whitespace": (False, True), "reverse": (False, True), "unidiff-zero": (False, True),
              "reject": (False, False), "allow-overlap": (False, True), "verbose": (False, True),
              "quiet": (False, True), "inaccurate-eof": (False, True), "recount": (False, True),
              "directory": (True, True), "allow-empty": (False, True)}
APPLY_NONEG = {"exclude", "include", "no-add", "add"}   # no --no- form (--no-add is its own option, --add its opposite)
APPLY_SHORT = {"p": True, "C": True, "z": False, "R": False, "3": False, "N": False, "v": False, "q": False}
APPLY_READERS = ("stat", "numstat", "summary", "check")
# git am's forms that apply nothing, spelled whole (an abbreviation is refused: git am has --quiet, --quit and
# --quoted-cr); what resumes a queue the floor does not read (its patches, its todo's exec lines).
AM_READ = re.compile(r"^(?:--abort|--quit|--show-current-patch(?:=\w+)?|-h)$")
RESUMERS = {"am", "rebase", "cherry-pick", "revert"}
RESUME = ("--continue", "--skip", "--resolved")


def _long(arg: str, names) -> tuple[str, bool] | None:
    """(the option a long argument names, whether it is negated) as git's parse-options reads it: an exact name, else
    the one name it is a unique prefix of, a --no- form included; None for no name or more than one (git refuses)."""
    body = arg[2:].partition("=")[0]
    cands = {n: (n, False) for n in names}
    cands.update({f"no-{n}": (n, True) for n in names if n not in APPLY_NONEG})
    if body in cands:
        return cands[body]
    hits = {v for k, v in cands.items() if body and k.startswith(body)}
    return hits.pop() if len(hits) == 1 else None


def apply_reads_only(args: list[str]) -> bool:
    """Whether ``git apply ARGS`` only reads its patch (round 14: its options parsed as git parses them: unique
    prefixes, --no- forms, short clusters and values, the last one winning): --stat, --numstat, --summary or --check
    left on, --apply left off, and no option that writes beside the work tree (--build-fake-ancestor, --reject,
    --unsafe-paths) nor one the floor does not know."""
    state, i = {}, 0
    while i < len(args) and args[i] != "--":
        a = args[i]
        skip = _apply_long(a, state) if a.startswith("--") else _apply_short(a) if a.startswith("-") else 0
        if skip is None:
            return False
        i += 1 + skip
    return any(state.get(r) for r in APPLY_READERS) and not state.get("apply")


def _apply_long(a: str, state: dict) -> int | None:
    """One long option of git apply recorded in ``state`` (its name: on or off): the words its value takes after it,
    None for one that writes or that the floor does not know."""
    hit = _long(a, APPLY_LONG)
    if hit is None:
        return None
    name, neg = hit
    value, harmless = APPLY_LONG[name]
    if not (harmless or neg):
        return None
    state[name] = not neg
    return 1 if value and not neg and "=" not in a else 0


def _apply_short(a: str) -> int | None:
    """A cluster of git apply's short options (-Rv, -p1, -C 3): the words its value takes after it, None for a letter
    the floor does not know ('-' alone, standard input, takes none)."""
    for k, c in enumerate(a[1:], 1):
        if c not in APPLY_SHORT:
            return None
        if APPLY_SHORT[c]:
            return 0 if a[k + 1:] else 1
    return 0


def resumes(sub: str, args: list[str]) -> str:
    """git am, rebase, cherry-pick or revert resuming a queue (round 14: --continue, --skip, am's --resolved and -r,
    in any prefix git takes): the refusal; '' else."""
    for a in args:
        if a == "--":
            break
        name = a.partition("=")[0]
        if (sub == "am" and a == "-r") or (len(name) > 2 and name.startswith("--") and
                                          any(full.startswith(name) for full in RESUME)):
            return (f"git {sub} {a} refused: it resumes a queue (its patches, its todo's exec lines) the floor does "
                    "not read; finish or abort it in the owner's terminal")
    return ""


def patched_settings(sub: str, args: list[str]) -> str:
    """Why git apply or git am would write under the floor (round 11 #3: a patch names its files in more spellings
    than a reader follows), '' for apply's read-only forms (apply_reads_only) and am's --abort, --quit and
    --show-current-patch spelled whole (--continue and --skip resume a queue: resumes)."""
    if sub == "apply" and apply_reads_only(args):
        return ""
    if sub == "am" and args and all(AM_READ.match(a) for a in args):
        return ""
    return ("the work tree through a patch (under the floor only apply --check, --stat, --numstat or --summary, and "
            "am --abort, --quit or --show-current-patch)")


def made_by_git(sub: str, args: list[str]) -> str:
    """git clone or init given a template folder or configuration (round 14: its hooks run at the clone's checkout,
    out of the floor's reading, and core.hooksPath points them anywhere), in any prefix git takes: the option; ''
    else."""
    if sub not in ("clone", "init"):
        return ""
    for a in args:
        name = a.partition("=")[0]
        if (sub == "clone" and (a == "-c" or a.startswith("-c") and not a.startswith("--"))) or (
                len(name) > 3 and any(full.startswith(name) for full in ("--template", "--config"))):
            return name
    return ""


def alias(real: str, kept, cwd: str) -> str:
    """``real`` as the settings or kept file it IS when it has more than one name (round 11 #1: a hard link): its
    identity (st_dev, st_ino: the volume serial and file index on Windows) against the home's and the working
    directory's settings files and the kept files; ``real`` itself otherwise."""
    try:
        st = os.stat(real)
    except (OSError, ValueError):
        return real
    if st.st_nlink < 2:
        return real
    for c in [*(f / n for f in _settings_folders(cwd) for n in ("settings.json", "settings.local.json")), *kept.files]:
        try:
            other = os.stat(c)
        except (OSError, ValueError):
            continue
        if (other.st_dev, other.st_ino) == (st.st_dev, st.st_ino):
            return os.path.normcase(os.path.abspath(str(c)))
    return real


def _settings_folders(cwd: str) -> list[Path]:
    """The .claude folders whose settings a hard link may be (round 12 #1): the home's, the launch folder's
    (CLAUDE_PROJECT_DIR), every folder of the working directory's parent chain (no depth cap: the git top-level is one
    of them), and every permissions.additionalDirectories entry of the home's and those folders' settings."""
    import json
    here = Path(cwd or os.getcwd())
    roots = [Path.home(), *([Path(os.environ["CLAUDE_PROJECT_DIR"])] if os.environ.get("CLAUDE_PROJECT_DIR") else []),
             here, *here.parents]
    folders = [r / ".claude" for r in roots]
    for f in list(folders):
        for name in ("settings.json", "settings.local.json"):
            try:
                extra = json.loads((f / name).read_text(encoding="utf-8")).get("permissions", {}).get(
                    "additionalDirectories") or []
            except (OSError, ValueError, AttributeError):
                continue
            folders += [Path(str(x)).expanduser() / ".claude" for x in extra if isinstance(x, str)]
    return folders


# --- round 14: a link, in any spelling, judged by every path it names ------------------------------------------------

LINK_PROGS = {"ln", "link", "mklink", "junction", "junction64", "subst"}
LINK_TYPES = ("symboliclink", "hardlink", "junction")
# What runs another program the floor does not unwrap (docs/guards.md, Limits): a link program given to one is
# refused, its paths unread.
UNWRAPPED = {"find", "parallel", "watch", "flock", "chrt", "script", "entr", "fd"}
# .NET's link makers in PowerShell code; a P/Invoke Add-Type (kernel32's CreateHardLinkW).
NET_LINK = re.compile(r"(?i)::\s*Create(?:Symbolic|Hard)Link\w*|\.\s*CreateAsSymbolicLink\s*\(|\bCreateJunction\b")
PS_PARAM = re.compile(r"^[-–—](\w+)(?::(.*))?$", re.S)
TEXT_READERS = g.TEXT_TOOLS | {"get-content", "gc", "type", "more", "wc", "sort", "uniq", "cut", "diff", "jq"}
# Inline code: the languages, how their programs are named, a reference to a link maker (a call, an attribute, an
# import), what reaches a member by a name the floor cannot read, and what runs a program.
LANGS = (("python", re.compile(r"^(?:python[\d.]*w?|pythonw|py|pypy[\d.]*)$")),
         ("node", re.compile(r"^(?:node|nodejs|deno|bun)$")), ("perl", re.compile(r"^perl[\d.]*$")),
         ("ruby", re.compile(r"^ruby[\d.]*$")), ("php", re.compile(r"^php[\d.]*$")))
_NAMES = (r"(?:link|symlink|hardlink_to|symlink_to|link_to|linkSync|symlinkSync|ln|ln_s|ln_sf|make_link|"
          r"CreateHardLink\w*|CreateSymbolicLink\w*|CreateJunction|CreateAsSymbolicLink|copy_function|mklink)")
CODE_LINK = re.compile(r"(?:\.\s*|\bimport\b[^\n;]*?\b|\buse\b[^\n;]*?\b)" + _NAMES + r"\b|\b" + _NAMES + r"\s*\(")
PERL_LINK = re.compile(r"(?<![$@%&\w])(?:link|symlink)\b\s*(?:\(|[$\w])")   # a call: link OLD, NEW (not /link/)
DYNAMIC = {"python": re.compile(r"(?<![.\w])(?:getattr|__import__|eval|exec|compile|vars|globals|locals)\s*\(|"
                                r"\b(?:import_module|ctypes|_winapi|__dict__|__builtins__|attrgetter|methodcaller)\b"),
           "node": re.compile(r"\b(?:eval|Function|Reflect|binding|import)\s*[.(]|\[[^\]\n]*\+[^\]\n]*\]"),
           "perl": re.compile(r"\beval\b|&\s*[{$]|->\s*can\b|\bCORE::"),
           "ruby": re.compile(r"\b(?:send|public_send|__send__|method|instance_eval|eval|const_get)\b"),
           "php": re.compile(r"\b(?:eval|call_user_func\w*|create_function)\b|\$\w+\s*\(")}
SPAWN = re.compile(r"(?i)\b(?:subprocess|system|popen|spawn\w*|exec\w*|child_process|Open3|shell_exec|passthru|"
                   r"proc_open|qx)\b|`")
LINK_COMMAND = re.compile(r"(?i)(?:^|[\s'\"\[,(])(?:ln|link|mklink|fsutil|new-item|ni|junction|subst|cpio)"
                          r"(?:\.exe)?(?=$|[\s'\",\])])|\bcp\s+-\w*[ls]|--link|--sym")
COMMENT = {"python": r"#[^\n]*", "ruby": r"#[^\n]*", "perl": r"#[^\n]*", "node": r"//[^\n]*|/\*.*?\*/",
           "php": r"//[^\n]*|#[^\n]*|/\*.*?\*/"}


def _lang(prog: str) -> str:
    return next((name for name, rx in LANGS if rx.match(prog)), "")


def _fed(cmds, command: str) -> str:
    """What a call may feed a program's input: its heredocs, its here-strings, the words echo and printf print."""
    fed = g._heredocs(command)
    for words, _ in cmds:
        if "<<<" in words[:-1]:
            fed.append(words[words.index("<<<") + 1])
        if g._prog(words[0]) in g.STDIN_FEEDERS:
            fed.append(" ".join(a for a in words[1:] if not a.startswith("-")))
    return "\n".join(fed)


def _code_of(lang: str, args: list[str], fed: str) -> str:
    """The code an interpreter runs from its arguments (python -c, node -e, perl -e, ruby -e, php -r, deno eval) or
    from its input (no script named: what the call feeds, _fed); '' when it runs a script or a module."""
    if lang in g.INLINE:
        code = g._inline(args, *g.INLINE[lang][:2])
        if code:
            return code[0]
    if lang == "php" and "-r" in args[:-1]:
        return args[args.index("-r") + 1]
    if args[:1] == ["eval"] and len(args) > 1:   # deno eval CODE
        return args[1]
    values = g.INLINE.get(lang, ("", "", []))[1]
    i = 0
    while i < len(args):
        a = args[i]
        if a == "-":
            break
        if not a.startswith("-") or a in ("-m", "-r") or a.startswith("--require"):
            return ""   # a script, a module, a file it requires
        i += 2 if len(a) == 2 and a[1] in values else 1
    return fed


def code_link(lang: str, code: str) -> str:
    """Why inline code may make a link (round 14, whatever the interpreter): a link maker it names as a call, an
    attribute or an import; a member or a module reached by a name the floor cannot read, a link name spelled in
    pieces; a program it runs whose command line names a link maker. '' for code that only names one in a string or
    a comment (round 13: ordinary code passes)."""
    stripped = re.sub(COMMENT.get(lang, r"#[^\n]*"), " ", g.LITERAL.sub("S", code), flags=re.S)
    if lang == "perl" and PERL_LINK.search(stripped):
        return "link"
    m = CODE_LINK.search(stripped)
    if m:
        return m.group(0).strip()
    collapsed = re.sub(r"['\"\s+,.]", "", code).lower()
    dyn = DYNAMIC.get(lang)
    if dyn and dyn.search(stripped) and ("link" in collapsed or lang == "python" and re.search(
            r"(?<![.\w])(?:eval|exec|compile|__import__)\s*\(|\bimport_module\b|"
            r"(?<![.\w])getattr\s*\([^,()]*,\s*(?!S\s*[,)])", stripped)):
        return dyn.search(stripped).group(0).strip()
    strings = " ".join(m.group(2) for m in g.LITERAL.finditer(code))
    if SPAWN.search(stripped) and LINK_COMMAND.search(strings):
        return LINK_COMMAND.search(strings).group(0).strip(" '\"[,(")
    return ""


def link_words(prog: str, args: list[str]) -> list[str] | None:
    """The path words of a command that makes a link, in any spelling it is given (round 14: GNU's unique prefixes,
    PowerShell's parameter prefixes, colon forms and -ItemType read as a wildcard prefix, a splat, a type the floor
    cannot read), or None when it makes none (LINKERS). A word the floor cannot read stays as written (UNREAD)."""
    if prog in ("busybox", "toybox") and args:
        return link_words(g._prog(args[0]), args[1:])
    reader = LINKERS.get(prog)
    return reader(args) if reader else None


def _ln_words(args: list[str]) -> list[str]:
    """ln's and link's path words: its operands and -t's folder (not -S's suffix)."""
    pos, opts = g._getopt(args, "St", ("suffix", "target-directory"))
    return pos + [v for o, v in opts if v and not (o == "-S" or len(o) > 3 and "--suffix".startswith(o))]


def _operands(args: list[str]) -> list[str]:
    """The words that are not options (mklink's /D /H /J, junction's -s, subst's /D)."""
    return [a for a in args if not a.startswith(("-", "/"))]


def _fsutil_words(args: list[str]) -> list[str] | None:
    """fsutil hardlink create NEW EXISTING: its two paths; None for another fsutil command."""
    low = [a.lower() for a in args]
    return args[low.index("create") + 1:] if "hardlink" in low and "create" in low else None


def _pass_through_words(args: list[str]) -> list[str] | None:
    """cpio -pl and pax -rwl: the names they link come from their input, which the floor does not read."""
    letters = "".join(a[1:] for a in args if re.match(r"^-[A-Za-z]+$", a))
    link = "l" in letters or any(len(x) > 3 and "--link".startswith(x.partition("=")[0]) for x in args)
    return ["$(the names it reads from its input)", *(a for a in args if not a.startswith("-"))] if link else None


def _rsync_words(args: list[str]) -> list[str] | None:
    """rsync --link-dest DIR (hard links to DIR's files): DIR and its operands; None without it."""
    hits = [i for i, a in enumerate(args) if a.startswith("--link-d")]
    if not hits:
        return None
    return [args[i].partition("=")[2] or (args[i + 1] if i + 1 < len(args) else "$") for i in hits] + \
        [a for a in args if not a.startswith("-")]


def _cp_link(args: list[str]) -> list[str] | None:
    """cp's path words when it makes links (-l, -s, --link, --symbolic-link, any unique prefix GNU takes), else None."""
    words, link, i = [], False, 0
    while i < len(args):
        a = args[i]
        if a == "--":
            words += args[i + 1:]
            break
        if a.startswith("-") and len(a) > 1:
            hit, named, i = (_cp_long if a.startswith("--") else _cp_short)(args, i)
            link, words = link or hit, words + named
        else:
            words.append(a)
        i += 1
    return words if link else None


def _cp_long(args: list[str], i: int) -> tuple[bool, list[str], int]:
    """(it makes links, the path it names, the index of its last word) for cp's long option at ``i``."""
    a = args[i]
    name = a.partition("=")[0]
    if len(name) > 2 and ("--link".startswith(name) or "--symbolic-link".startswith(name)):
        return True, [], i
    if len(name) > 2 and ("--target-directory".startswith(name) or "--suffix".startswith(name)):
        val, i = (a.partition("=")[2], i) if "=" in a else ((args[i + 1] if i + 1 < len(args) else ""), i + 1)
        return False, [val] if name.startswith("--t") else [], i
    return False, [], i


def _cp_short(args: list[str], i: int) -> tuple[bool, list[str], int]:
    """(it makes links, the path it names, the index of its last word) for cp's short cluster at ``i`` (l, s; -t's
    folder, -S's suffix skipped)."""
    a, link = args[i], False
    for k, c in enumerate(a[1:], 1):
        link = link or c in "ls"
        if c in "St":
            val = a[k + 1:] or (args[i + 1] if i + 1 < len(args) else "")
            return link, [val] if c == "t" else [], i + (0 if a[k + 1:] else 1)
    return link, [], i


def _new_item_link(args: list[str]) -> list[str] | None:
    """New-Item's path words when it may make a link: -ItemType (or -Type, any prefix PowerShell takes, a colon form)
    whose value matches SymbolicLink, HardLink or Junction as PowerShell's wildcard prefix does (h, Hard*, j, Sym), or
    a type or a splat the floor cannot read; None for another item."""
    words, link, i = [], False, 0
    while i < len(args):
        name, val, i = _ps_param(args, i)
        if name is None:
            link, words = link or val.startswith("@"), words + [_unq(val)]   # a splat: its -ItemType is not read
        elif "itemtype".startswith(name) or "type".startswith(name):
            kind = _item_type(val)
            link, words = link or bool(kind), words + ([kind] if kind.startswith("$") else [])
        elif val is not None:
            words.append(_unq(val))
        i += 1
    return words if link else None


def _ps_param(args: list[str], i: int) -> tuple[str | None, str | None, int]:
    """(a PowerShell parameter's name, lowercased, its value: after a colon or the next word that is not a parameter,
    the index of its last word) for ``args[i]``; (None, the word, i) for a positional word."""
    m = PS_PARAM.match(args[i])
    if not m:
        return None, args[i], i
    if m.group(2) is None and i + 1 < len(args) and not PS_PARAM.match(args[i + 1]):
        return m.group(1).lower(), args[i + 1], i + 1
    return m.group(1).lower(), m.group(2), i


def _item_type(val: str | None) -> str:
    """New-Item's -ItemType value read as PowerShell reads it: 'link' when it matches a link type as a wildcard prefix
    (h, Hard*, j, Sym), a $(...) word when the floor cannot read it, '' for another item type."""
    v = _unq((val or "").strip()).lower()
    if not v or UNREAD.search(re.sub(r"[*?\[\]]", "", v)):
        return "$(an -ItemType the floor cannot read)"
    return "link" if any(fnmatch.fnmatchcase(t, v + "*") for t in LINK_TYPES) else ""


LINKERS = {"ln": _ln_words, "link": _ln_words, "mklink": _operands, "junction": _operands, "junction64": _operands,
           "subst": _operands, "fsutil": _fsutil_words, "cp": _cp_link, "cpio": _pass_through_words,
           "pax": _pass_through_words, "rsync": _rsync_words, "new-item": _new_item_link, "ni": _new_item_link}


def _link_reach(word: str, real: str, kept) -> bool:
    """Whether a link that names ``word`` (``real`` as resolved) reaches what the floor keeps: a settings or kept file,
    a folder above a kept path, the home, any .claude or .git folder or what is in one (round 14: a symbolic link's
    target is read from the link's folder, so the name as written counts too), .mcp.json or .claude.json."""
    home = os.path.normcase(os.path.abspath(Path.home()))
    return bool(kept.settings(real) or kept.inside(real) or kept.holds(real) or os.path.normcase(real) == home
                or os.path.basename(real).lower() in (".mcp.json", ".claude.json")
                or any(GIT_DIR.search(x) or CLAUDE_DIR.search(x) for x in (word, real)))


def _program(what: str) -> str:
    """The program a shell write names (``bash: ln`` -> ln, ``redirection >`` -> redirection)."""
    tail = what.rsplit(": ", 1)[-1].split()
    return g._prog(tail[0]) if tail else ""


def links(acts, cmds, shell: str, command: str, kept) -> str | None:
    """Round 14, links as a class whatever the tool, the spelling or the interpreter: inline code or .NET that makes
    one (its paths unread: _unread_link); a link program run by a launcher the floor does not unwrap; a link program
    whose path words the floor cannot resolve (a glob, a brace, a substitution, a variable, a splat, its input) or
    that reaches what it keeps (_link_paths); and a call that makes a link and writes anything else (a write through
    the new link is not known until the link exists)."""
    makers, fed = set(), _fed(cmds, command)
    for words, d, *_ in acts:
        prog, args = g._prog(words[0]), words[1:]
        found = link_words(prog, args)
        why = _unread_link(prog, words, fed) or (_link_paths(prog, found, d, kept) if found is not None else "")
        if why:
            return why
        makers |= {prog} if found is not None else set()
    if makers and shell != "ps" and BRACE_WORD.search(_unquoted(command)):
        return "a link in a call with a brace expansion refused: the floor does not read the paths a brace makes"
    for what, target in g.shell_writes(cmds, shell) if makers else ():
        if _program(what) not in makers | NO_CONTENT:   # a folder made or a file removed writes nothing through one
            return (f"a link and a write ({what} into {target}) in one call refused: the file a write reaches through "
                    "a new link is not known until the link exists")
    return None


def _unread_link(prog: str, words: list[str], fed: str) -> str:
    """A link made where the floor cannot read its paths: inline code (code_link), .NET (NET_LINK, a P/Invoke
    Add-Type), a link program given to a launcher the floor does not unwrap; '' else."""
    args, lang = words[1:], _lang(prog)
    what = code_link(lang, _code_of(lang, args, fed)) if lang else ""
    if what:
        return f"{prog} refused: inline code that makes a link ({what}), whose paths the floor cannot read"
    if prog not in TEXT_READERS and (any(NET_LINK.search(w) for w in words) or prog == "add-type" and any(
            re.search(r"(?i)dllimport|link", w) for w in args)):
        return f"{prog} refused: .NET code that makes a link, whose paths the floor cannot read"
    if prog in UNWRAPPED and any(g._prog(w) in LINK_PROGS for w in args):
        return f"{prog} refused: it runs a link program the floor does not read the paths of"
    return ""


def _link_paths(prog: str, found: list[str], d: str, kept) -> str:
    """A link program's path word the floor cannot resolve (none at all: its input), or one that reaches what it keeps
    (_link_reach): the refusal; '' else."""
    for w in found or ["$(its input)"]:
        if UNREAD.search(w):
            return f"{prog} refused: a link whose path ({w}) the floor cannot resolve"
        if _link_reach(w, g._real(g._path(w, d)), kept):
            return (f"{prog} onto {w} refused: a link onto Claude Code's settings or customization, a .git folder or "
                    "what sets the floor (they change by Write or Edit only)")
    return ""


NO_CONTENT = {"mkdir", "md", "rm", "rmdir", "unlink", "remove-item", "ri", "rd", "del", "erase"}
# A bash word with a brace expansion (a.{txt,bak}), which the parser reads as separate words: quotes taken out first.
BRACE_WORD = re.compile(r"[^\s;&|()<>]*\{[^{}\s]*,[^{}\s]*\}[^\s;&|()<>]*")


def _unquoted(command: str) -> str:
    return re.sub(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"", " Q ", command)


def braced(command: str, shell: str) -> str | None:
    """A bash brace expansion one of whose words names a .git or .claude folder or a settings file (round 14: the
    parser reads a.{b,c} as separate words): the refusal; None else."""
    if shell == "ps":
        return None
    for m in BRACE_WORD.finditer(_unquoted(command)):
        hit = next((w for w in _braces(m.group(0)) if GUARDED_TEXT.search(w)), "")
        if hit:
            return f"{m.group(0)} refused: a brace that makes {hit}, which the floor does not read as a path"
    return None


# --- round 14: a path word as its shell expands it ------------------------------------------------------------------

GLOB = re.compile(r"[*?\[]")
GUARDED_TEXT = re.compile(r"(?i)\.git\b|\.claude\b|settings(?:\.local)?\.json|rebase-(?:apply|merge)|\.mcp\.json")


def _braces(word: str) -> list[str]:
    """bash's brace expansion of ``word`` (a{b,c}d: abd, acd), 64 words at most (the rest left as written)."""
    out, todo = [], [word]
    while todo and len(out) + len(todo) < 64:
        w = todo.pop()
        m = re.search(r"\{([^{}]*,[^{}]*)\}", w)
        if not m:
            out.append(w)
            continue
        todo += [w[:m.start()] + part + w[m.end():] for part in m.group(1).split(",")]
    return out + todo


def _glob(pattern: str, shell: str) -> list[str] | None:
    """The existing paths a glob matches, folder by folder (bash: a name with a leading dot only by a pattern that
    starts with one; PowerShell's wildcards: any name), case-insensitively; None past 256 matches."""
    parts = re.split(r"[\\/]", pattern)
    k = next(i for i, p in enumerate(parts) if GLOB.search(p))
    paths = ["/".join(parts[:k]) + "/"]
    for seg in parts[k:]:
        nxt = []
        for p in paths:
            if not GLOB.search(seg):
                nxt.append(os.path.join(p, seg))
                continue
            try:
                names = os.listdir(p)
            except OSError:
                continue
            nxt += [os.path.join(p, n) for n in names if fnmatch.fnmatchcase(n.lower(), seg.lower())
                    and (shell == "ps" or not n.startswith(".") or seg.startswith("."))]
        paths = nxt
        if len(paths) > 256:
            return None
    return [p for p in paths if os.path.lexists(p)]


def expand(word: str, d: str, shell: str) -> list[str] | None:
    """The paths ``word`` names as its shell expands it: its braces (bash), then its glob against the file system
    (_glob), the word as written when a glob matches nothing (bash keeps it); None when it holds what the floor cannot
    resolve (a substitution, a variable, a splat, a brace left, too many matches)."""
    out = []
    for w in (_braces(word) if shell != "ps" else [word]):
        if re.search(r"[{}$`]", w) or w.startswith("@"):
            return None
        if not GLOB.search(w):
            out.append(w)
            continue
        hits = _glob(g._path(w, d), shell)
        if hits is None:
            return None
        out += hits or [w]
    return out


def unresolved_reach(target) -> bool:
    """Whether a write whose target the floor cannot resolve (brain.guards.Unresolved) may reach a .git or .claude
    folder or a settings file: its text names one, or the folder it is read in is one or in one."""
    return bool(GUARDED_TEXT.search(target.what) or GIT_DIR.search(str(target)) or CLAUDE_DIR.search(str(target)))

# --- extractions and the archives they read (moved from brain.floorguard in round 14, unchanged but the .git and
# link members) ----------------------------------------------------------------------------------------------

EXTRACTORS = {"tar", "bsdtar", "unzip", "expand-archive", "7z", "7za"}


def extractions(acts, kept, shells=()) -> str | None:
    """An archive extracted into a kept file's folder or a kept folder (tar -x -C, unzip -d, Expand-Archive
    -DestinationPath, 7z x -o; the current folder when none is named): its members are not read. Round 14: into any
    .git folder, or into a folder the floor cannot resolve."""
    for (words, d), shell in zip(acts, list(shells) or ["bash"] * len(acts), strict=True):
        prog = g._prog(words[0])
        target = _extract_target(prog, words) if prog in EXTRACTORS else None
        if target is None:
            continue
        spelled = expand(target, d, shell) if target else [""]
        if not spelled or len(spelled) > 1:
            return f"{prog} refused: it extracts into a folder the floor cannot resolve ({target})"
        real = g._real(g._path(spelled[0], d)) if spelled[0] else g._real(d)
        if real in kept.folders or kept.inside(real):
            return f"{prog} into {real} refused: an archive there can hold what sets the floor or runs the guard"
        if GIT_DIR.search(real):
            return f"{prog} into {real} refused: a .git folder changes by git alone (its state, hooks and pointer)"
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


def archived_settings(acts, settings) -> str | None:
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
        why = _member_refusal(members, g._path(archive, d), settings)
        if why:
            return f"{prog} refused: {why}"
    return None


def _member_refusal(members: list[str], path: str, settings) -> str:
    """What an archive's members bring that the floor keeps: a settings file, anything in a .git or .claude folder
    (round 14: git's state and hooks, a skill's frontmatter, never read once extracted), a link; '' else."""
    hit = next((m for m in members if settings.search(m.replace("\\", "/"))), "")
    if hit:
        return f"the archive holds {hit}, and Claude Code's settings change by Write or Edit only"
    hit = next((m for m in members if GIT_DIR.search(m) or CLAUDE_DIR.search(m)), "")
    if hit:
        return f"the archive holds {hit}, in a .git or .claude folder"
    link = _linked_member(path)
    return f"the archive holds a link ({link}), which an extraction makes onto any path" if link else ""


def _linked_member(path: str) -> str:
    """The first member of a tar or zip archive that is a link (a tar hard or symbolic link, a zip entry whose mode
    is a symbolic link's), '' for none (round 14: links as a class)."""
    import tarfile
    import zipfile
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                return next((i.filename for i in z.infolist() if (i.external_attr >> 16) & 0o170000 == 0o120000), "")
        with tarfile.open(path) as tf:
            return next((m.name for m in tf.getmembers() if m.islnk() or m.issym()), "")
    except (OSError, tarfile.TarError, zipfile.BadZipFile, ValueError, EOFError):
        return ""


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
