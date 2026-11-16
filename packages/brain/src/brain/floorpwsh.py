"""PowerShell's pipelines and .NET's writers under the floor, and the later rounds' write classes (wi-brain-unadopted-
floor, review rounds 7-10; brain.floorguard calls them): a path piped into a cmdlet that writes is its -Path, a .NET
method that writes is refused on what the floor keeps, the environment written through COM or a RegistryKey is refused
whatever the statement; a stream of a settings or customization file, a frontmatter that adds hooks, and a patch read
from standard input are refused."""

from __future__ import annotations

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
# Round 12 #2: git's rebase and am state, whose queued patches git am --continue and --skip apply, and what a queued
# patch must not name; round 12 #1: a link made by inline code.
REBASE_STATE = re.compile(r"(?i)[\\/]\.git[\\/](?:worktrees[\\/][^\\/]+[\\/])?rebase-(?:apply|merge)(?:[\\/]|$)")
QUEUED = re.compile(r"(?i)\.claude[\\/](?:settings(?:\.local)?\.json|skills|commands|agents)\b|\.mcp\.json|"
                    r"\.claude\.json")
INLINE_LINK = re.compile(r"(?i)\bos\.(?:link|symlink)\s*\(|\.(?:hardlink_to|symlink_to|link_to)\s*\(|"
                         r"\bfs\.(?:link|symlink)(?:Sync)?\s*\(|CreateHardLink|CreateSymbolicLink")
# Round 11 #3: git apply's and git am's forms that write nothing.
READ_ONLY = {"apply": {"--check", "--stat", "--numstat", "--summary"},
             "am": {"--continue", "--abort", "--skip", "--quit", "--show-current-patch"}}
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
    .NET type (TYPE_VAR); a link made by inline code (INLINE_LINK: os.link, Path.hardlink_to, fs.linkSync...)."""
    m = INLINE_LINK.search(plain)
    if m:
        return f"{m.group(0).strip()} refused: a link made by code, whose target the floor cannot read"
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
    if REBASE_STATE.search(real) or REBASE_STATE.search(str(target)):   # round 12 #2: git am's queued patches
        return f"{tool} refused: {target} is git's rebase or am state, which git am --continue or --skip applies"
    if g.STREAM.search(str(target)) and (custom or g._override_file(target)):
        return f"{tool} refused: {target} names a stream of a settings or customization file"
    if custom:
        return floor.frontmatter_hooks(tool, target, *g._edit_result(inp, tool, target)) or ""
    return None


def _queued(d: str) -> str:
    """A patch git am's state queues (.git/rebase-apply) that names a settings or customization path, said; ''
    when none does (round 12 #2: --continue and --skip apply the next ones)."""
    state = g._git_out(d, "rev-parse", "--git-path", "rebase-apply").strip()
    folder = Path(g._path(state, d)) if state else None
    for f in sorted(folder.iterdir()) if folder and folder.is_dir() else []:
        try:
            if f.is_file() and QUEUED.search(f.read_text(encoding="utf-8", errors="replace")):
                return f"the queued patch {f.name}, which names a settings or customization file"
        except OSError:
            return f"a queued patch it cannot read ({f.name})"
    return ""


def patched_settings(sub: str, args: list[str], d: str = ".") -> str:
    """Why git apply or git am would write under the floor (round 11 #3: a patch names its files in more spellings
    than a reader follows: case, renames, a patch the same command makes), '' for their read-only forms (apply
    --check, --stat, --numstat, --summary without --apply) and am's session options (--continue, --abort, --skip,
    --quit, --show-current-patch)."""
    flags = {a.split("=", 1)[0] for a in args}
    if flags & READ_ONLY.get(sub, set()) and "--apply" not in flags:
        return _queued(d) if sub == "am" and flags & {"--continue", "--skip"} else ""
    return f"the work tree through a patch (under the floor only {', '.join(sorted(READ_ONLY.get(sub, set())))})"


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


def link_refusal(prog: str, words: list[str], d: str, kept) -> str:
    """A link command (LINKERS) any of whose paths is a settings or kept file, a folder above a kept path, a
    .claude folder or a folder holding one (round 11 #1, #2): what it names; '' otherwise."""
    args = words[1:]
    if not _links_files(prog, args):
        return ""
    return next((a for a in args if (not a.startswith(("-", "/")) or os.path.isabs(a))
                 and _settings_reach(g._real(g._path(a, d)), kept)), "")


def _links_files(prog: str, args: list[str]) -> bool:
    """Whether the command makes a link: mklink, ln, link, fsutil hardlink, cp -l/--link, New-Item -ItemType *Link (a
    colon form -ItemType:Junction or -Type: too)."""
    if prog in ("mklink", "ln", "link"):
        return True
    if prog == "fsutil":
        return "hardlink" in (a.lower() for a in args)
    if prog == "cp":
        return any(a == "--link" or re.match(r"^-[a-zA-Z]*l", a) for a in args)
    return prog in ("new-item", "ni") and any(
        re.match(r"(?i)^(?:-(?:itemtype|type|it):)?['\"]?(?:symboliclink|hardlink|junction)['\"]?$", a) for a in args)


def _settings_reach(real: str, kept) -> bool:
    """Whether a link onto ``real`` reaches a settings or kept file: it is one, a folder above a kept path, the home or
    its .claude folder (round 12 #4: a project folder holding .claude passes; a write through it is judged on the
    file it reaches)."""
    home = os.path.normcase(os.path.abspath(Path.home()))
    return kept.settings(real) or kept.inside(real) or kept.holds(real) or \
        os.path.normcase(real) in (home, os.path.join(home, ".claude"))
