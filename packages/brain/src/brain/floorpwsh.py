"""PowerShell's pipelines and .NET's writers under the floor (wi-brain-unadopted-floor, review round 7; brain.floorguard
calls them): a path piped into a cmdlet that writes is its -Path, a .NET method that writes is refused on what the
floor keeps, and the environment written through COM or a RegistryKey is refused whatever the statement."""

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
                       r"GetProperty|UnderlyingSystemType|GetType)\b|\.Invoke\s*\(\s*\$null\b")
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
    .NET type (TYPE_VAR)."""
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
