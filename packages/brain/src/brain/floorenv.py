"""The locked floor's environment and the checkout that holds config.json (wi-brain-floor-watched-vars; brain.floor,
brain.floorguard calls them; docs/guards.md, « The environment » and « The checkout that holds config.json »):

- :func:`env`: a variable of brain.floor.watched assigned in any form, or an assignment whose name the guard cannot
  read; an assignment of brain.floor.WORKTREE_VARS passes as one literal absolute path inside a worktree of the
  repository that holds the config.json the guard reads (:func:`read_paths`).
- :func:`checkout`: a git command in the checkout that holds config.json other than a read or a pull of its upstream
  (:func:`pull`), and a git remote that writes in any worktree of its repository (they share its remotes).

Standard library only, with the guards' git and paths: the guard hook reads it.
"""

from __future__ import annotations

import os
import re

from . import floor
from . import guards as g

# The options a pull in the checkout that holds config.json may take: what merges or rebases its upstream, quietly or
# not; any other (a strategy, an interactive rebase, submodules, unrelated histories, a prefix git would take) is
# refused.
PULL_OPTS = {"--ff-only", "--ff", "--no-ff", "--rebase", "--rebase=true", "--rebase=false", "--rebase=merges",
             "--no-rebase", "-r", "-q", "--quiet", "-v", "--verbose", "--stat", "-n", "--no-stat", "--autostash",
             "--no-autostash", "--progress", "--no-progress", "--no-edit", "--prune", "-p", "--tags", "--no-tags",
             "--verify-signatures", "--no-verify-signatures"}
LOCAL_URL = re.compile(r"(?i)^(?:file:|[./~\\]|[A-Za-z]:(?:[\\/]|$))")   # a URL that is a folder a session writes
CONFIG_READS = {"--get", "--get-all", "--get-regexp", "--list", "-l"}
CONFIG_WRITES = {"--add", "--replace-all", "--unset", "--unset-all"}


def under(path: str, folder: str) -> bool:
    """Whether ``path`` is ``folder`` or inside it (both as _real gives them)."""
    return bool(path) and bool(folder) and (path == folder or path.startswith(folder.rstrip("\\/") + os.sep))


def repo_of(folder: str) -> str:
    """The git checkout that holds ``folder`` (the first parent with a .git), as _real gives it; '' for none."""
    p = g._real(folder)
    while True:
        if os.path.exists(os.path.join(p, ".git")):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            return ""
        p = parent


# --- the environment -------------------------------------------------------------------------------------------------

def env(code: str, sub: str, configs: list[str]) -> str | None:
    """A variable of brain.floor.watched assigned in any form, or an assignment whose name the guard cannot read, in
    ``code`` (a call's text, its prose out: brain.floorguard._code; unspelled here), once the assignments of
    brain.floor.WORKTREE_VARS that pass are taken out (:func:`read_paths`; ``configs``: the config.json files the guard
    reads, brain.floorguard.Kept.configs)."""
    kept = read_paths(code, sub, configs)
    watched = floor.assignments()
    for plain in (floor.unspelled(kept), floor.unspelled(unescaped(kept))):
        m = watched.search(plain) or floor.ENV_DYNAMIC.search(plain)
        if m:
            return f"{m.group(0).strip()[:60]!r} refused: a variable the floor watches (or one it cannot read) set"
    return None


def unescaped(text: str) -> str:
    """``text`` as bash reads a name it spells with escapes (``env BRAIN_\\HOME=x``, ``$'\\x42RAIN_HOME'=x``,
    ``$"BRAIN_HOME"=x``): an ANSI-C string's escapes decoded, the ``$`` before a quote dropped, every backslash dropped
    (a value's backslashes too: this text is only searched for names)."""
    def ansi(m: re.Match) -> str:
        body = re.sub(r"\\x([0-9A-Fa-f]{1,2})", lambda x: chr(int(x.group(1), 16)), m.group(1))
        body = re.sub(r"\\u([0-9A-Fa-f]{1,4})", lambda x: chr(int(x.group(1), 16)), body)
        body = re.sub(r"\\([0-7]{1,3})", lambda x: chr(int(x.group(1), 8) % 256), body)
        return "'" + body + "'"
    text = re.sub(r"\$'((?:[^'\\]|\\.)*)'", ansi, text)
    return re.sub(r"\$(?=\")", "", text).replace("\\", "")


def read_paths(code: str, sub: str, configs: list[str]) -> str:
    """``code`` with each assignment of brain.floor.WORKTREE_ASSIGN whose value is one literal absolute path inside a
    worktree of the repository that holds one of ``configs`` (:func:`worktrees`) made a space: a read-path use
    (``BRAIN_PROJECTS=<worktree>/projects.yaml brain audit``). PowerShell's form counts in its own tool (``sub`` ps)
    only; a bash value reads no backslash outside double quotes (bash drops it)."""
    trees: list[str] | None = None

    def keep(m: re.Match) -> str:
        nonlocal trees
        if m.group("psname") and sub != "ps":
            return m.group(0)
        value = m.group("value") or m.group("psvalue") or ""
        if value[:1] in ("'", '"'):
            value = value[1:-1]
        if trees is None:
            trees = worktrees(configs)
        return " " if inside(value, trees) else m.group(0)
    return floor.WORKTREE_ASSIGN.sub(keep, code)


def worktrees(configs: list[str]) -> list[str]:
    """The folders of every worktree (git worktree list: the main checkout first) of the repositories that hold
    ``configs``, as the file system resolves them; a worktree git says is prunable, a bare repository or a folder that
    is gone is none."""
    out: list[str] = []
    for root in sorted({r for r in (repo_of(os.path.dirname(f)) for f in configs) if r}):
        for block in g._git_out(root, "worktree", "list", "--porcelain").replace("\r", "").split("\n\n"):
            lines = block.splitlines()
            path = next((ln[len("worktree "):] for ln in lines if ln.startswith("worktree ")), "")
            if path and not any(ln == "bare" or ln.startswith("prunable") for ln in lines) and os.path.isdir(path):
                out.append(g._real(path))
    return out


def inside(value: str, trees: list[str]) -> bool:
    """Whether ``value`` names an absolute local path (a drive's on Windows, where Git Bash's /e/x is E:/x) inside one
    of ``trees``, links resolved; a network or device path never is."""
    if os.name == "nt":
        value = re.sub(r"^/([A-Za-z])(?=/|$)", lambda m: m.group(1) + ":", value)
        if not re.match(r"^[A-Za-z]:[\\/]", value):
            return False
    elif not value.startswith("/"):
        return False
    if floor.UNC.match(value):
        return False
    real = g._real(value)
    return any(under(real, t) for t in trees)


# --- the checkout that holds config.json ----------------------------------------------------------------------------

def checkout(gits, folders: list[str]) -> str | None:
    """A git command (``gits``: brain.floorguard._git's (words, folder, subcommand, arguments), aliases resolved) in
    (or pointed at, -C) the checkout that holds one of ``folders`` (brain.floorguard.Kept.folders) other than a read
    (:func:`reads`) or a pull of its upstream (:func:`pull`); and, in any worktree of its repository, which shares its
    remotes, a git remote that writes one (a pull there would then fetch elsewhere)."""
    roots = {r for r in (repo_of(f) for f in folders) if r}
    if not roots:
        return None
    shared: list[set[str]] = []   # the roots' git common folders, read once, when a git remote writes
    for _, folder, sub, args in gits:
        why = "" if sub == "!" else _remote_write(folder, sub, args, roots, shared) or \
            (_in_checkout(folder, sub, args) if repo_of(folder) in roots else "")
        if why:
            return why
    return None


def _remote_write(folder: str, sub: str, args: list[str], roots: set[str], shared: list[set[str]]) -> str:
    """Why a git remote that writes in ``folder`` is refused (its repository is a root's: it shares its remotes)."""
    if sub != "remote" or reads(sub, args):
        return ""
    if not shared:
        shared.append({common_dir(r) for r in roots} - {""})
    if common_dir(folder) not in shared[0]:
        return ""
    pos = [a for a in args if not a.startswith("-")]
    return (f"git remote {(pos or ['?'])[0]} in {folder} refused: its repository holds config.json, whose checkout "
            "pulls from these remotes")


def _in_checkout(folder: str, sub: str, args: list[str]) -> str:
    """Why one git command in the checkout that holds config.json is refused there, '' when it passes."""
    if sub == "pull":
        why = pull(folder, args)
        return f"git pull in {folder} refused: {why}" if why else ""
    if reads(sub, args):
        return ""
    return f"git {sub} in {folder} refused: only reads change nothing in the checkout that holds config.json"


def common_dir(folder: str) -> str:
    """The git common folder of the repository ``folder`` is in (shared by all its worktrees), as _real gives it;
    '' for none."""
    out = g._git_out(folder, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    return g._real(out) if out else ""


def pull(folder: str, args: list[str]) -> str:
    """Why a git pull in the checkout that holds config.json may bring what the owner did not merge, '' when it
    cannot: it brings only its branch's upstream, read from git's configuration when it is judged (whoever set it):
    a branch checked out, whose upstream is main or master of a remote that is no local path (:func:`upstream`),
    named by the command or not; its options those of PULL_OPTS."""
    odd = next((a for a in args if a.startswith("-") and a not in PULL_OPTS), "")
    if odd:
        return f"its option {odd} (a pull there takes only {', '.join(sorted(PULL_OPTS))})"
    found = upstream(folder)
    if isinstance(found, str):
        return found
    current, remote, branch = found
    pos = [a for a in args if not a.startswith("-")]
    if pos and (pos[0] != remote or any(p != f"refs/heads/{branch}" for p in pos[1:])):
        return (f"it names {' '.join(pos)}, not {current}'s upstream {remote} refs/heads/{branch} (a bare {branch} is "
                f"read as a tag first: git pull alone brings the upstream)")
    return ""


def upstream(folder: str) -> tuple[str, str, str] | str:
    """(the branch checked out, its upstream's remote, the upstream branch) when the upstream is main or master of a
    remote whose URL is no local path, else why not."""
    conf = floor.git_config(g._git_out(folder, "config", "-z", "--list"))
    current = g._git_out(folder, "symbolic-ref", "-q", "--short", "HEAD").strip()
    if not current:
        return "no branch is checked out, so no upstream says what it brings"
    remote, merge = floor.last(conf, f"branch.{current}.remote"), floor.last(conf, f"branch.{current}.merge")
    branch = floor.HEADS.sub("", merge)
    if not remote or remote == "." or branch not in floor.BRANCHES:
        return (f"{current}'s upstream is {remote or 'none'}/{branch or 'none'}, not main or master of a remote: a "
                "pull there brings only what was merged by a pull request")
    url = floor.last(conf, f"remote.{remote}.url")
    if not url or LOCAL_URL.match(url):
        return f"the remote {remote} is {url or 'without a URL'}, a local path a session can write"
    return current, remote, branch


def reads(sub: str, args: list[str]) -> bool:
    """Whether a git command leaves the checkout's files and settings alone (:func:`checkout`; a pull is judged by
    :func:`pull`): brain.floor.CHECKOUT_SAFE, git config and git remote that only read."""
    pos = [a for a in args if not a.startswith("-")]
    if sub == "config":
        return bool(CONFIG_READS & set(args)) or pos[:1] in (["get"], ["list"]) \
            or (len(pos) == 1 and not set(args) & CONFIG_WRITES)
    if sub == "remote":
        return not pos or pos[0] in ("show", "get-url")
    return sub in floor.CHECKOUT_SAFE
