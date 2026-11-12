"""PreToolUse guards, run by the core plugin's hooks: ``guard.py`` with the hook's JSON on stdin (standard library,
and PyYAML for the registry). They refuse at zero token what a rule used to forbid in words.

Hook payload fields (Claude Code hooks reference, 2026-11-01): tool_name, tool_input.command (Bash, PowerShell),
tool_input.file_path (Edit, Write, MultiEdit) or notebook_path (NotebookEdit), cwd, session_id, tool_use_id. A refusal
is one JSON line on stdout, ``permissionDecision: deny`` with a one-line reason the model reads, signed with the core
plugin's name (config.json adapters.claude); a call that passes prints nothing. A command the desktop app's
``run_in_terminal`` types into the owner's Terminal panel (tool_input.command, cwd) is judged as a shell call, PowerShell
on Windows, else bash (TERMINAL_TOOL), in its cwd, else the session's. Nine guards, in this order:

- ``production``: no tool edit under a production checkout (``production:`` in the Brain's projects.yaml), and no git
  command that changes one: commit, checkout, switch, restore, reset, merge, rebase, stash (but list, show), push,
  pull without --ff-only, cherry-pick, revert, am, apply, rm, mv, clean, and gh pr checkout. Reads, fetch, pull
  --ff-only, worktree, branch, log, status, diff and show pass. No shell write into one either (wi-brain-guard-shell-
  writes): a redirection (>, >>, 2>, &>), a program that writes the files it names (rm, cp, mv, touch, tee, sed -i,
  dd of=, tar x...), a PowerShell cmdlet (Set-Content, Out-File, Remove-Item, Copy-Item...), inline code that
  writes (python -c, node -e, perl -e) and the commands of bash -c, pwsh -Command and cmd /c; /dev/null, NUL and
  $null pass, and so do scripts (what a program writes by itself is not seen). A worktree or repo nested under a
  production checkout (a .git between them) is not production. A call is judged in the folder it runs in: the last
  cd before it, or its -C, with the variables the command assigned before it expanded; a folder that cannot be
  resolved stays the session's, and so does a target that cannot.
- ``owner``: nothing only the owner does (config.json's identity.owner). The list is brain.permissions' never-grantable
  categories (the engine's NEVER, extended by permissions.yaml's never:, one source): a category's deny rules (Claude
  Code's syntax, matched on every simple command) and, for the categories it knows by name, the shapes of their
  commands: visibility (gh repo create --public, gh repo edit --visibility, gh gist create --public, the REST and
  GraphQL calls), keys (gh secret set|delete, gh auth token, ssh-keygen, age-keygen, gpg's secret keys, cmdkey,
  Set-Secret, kubectl create secret and Secret manifests), accounts (gh auth login|logout|refresh, docker, npm, az,
  gcloud and argocd logins, local users), scheduled (schtasks /create|/change|/delete, Register-ScheduledTask and
  its kin, brain schedule install --apply, services, crontab but -l, at, systemctl enable, Run keys, a file written
  where it starts on its own, the desktop app's scheduled-tasks tools), arming (--arm), installer (install.ps1 -Apply). A category the file does
  not declare is not guarded; money and legal have no command, only their deny rules. Also refused: setting
  BRAIN_GUARD_ALLOW for later sessions (setx, the registry, Claude Code's settings, a shell profile; check override).
  A session's Remote Control and permission mode (security-settings, never lifted) are refused but in Remote Control's
  three exceptions (wi-brain-guard-rc-archive, remote_control): off on a finished session the caller started; at a
  handover between Brain coordinators, on for the coordinator the caller started to succeed it and off on itself,
  once its hand-over note is in <BRAIN_HOME>/handover/ (a successor with no transcript yet counts as starting for
  HANDOVER_START_S after its app file's createdAt); each one passes logged as decision allowed with its case.
- ``power`` (wi-brain-power-guard, TOPO-2): no act on a machine or the cluster: machine (shutdown, reboot, sleep,
  Stop-Computer, systemctl and loginctl power verbs, boot arming by bcdedit, efibootmgr or ipmitool), node (the verbs
  but reads of the platform's node lifecycle CLIs, config.json's power.node_clis, a kubectl-<name> one as kubectl
  <name> too; Σ-NODE-POWER-CORE's scripts, k3s-killall, stopping k3s or a service of power.node_services), wake
  (Wake-on-LAN, a magic packet), bot (the /power bot), cluster (kubectl writes but in the brain namespace on manifests
  it reads, node actions, helm writes, argocd writes but the Brain's own application).
  A cluster write passes only in the brain namespace (the last -n or --namespace, or each manifest's own), naming
  no kind but the namespaced ones the guard knows, with every -f manifest read and not written by the same command.
  Both see through wrappers (sudo, env, timeout, gsudo, doas), launchers (wsl, chroot, nsenter, uv run, npx, eval,
  su -c, runas, ansible -a), nested shells (bash -c, pwsh -Command and -File, cmd /c, iex), Start-Process, start,
  ssh's remote command (its options after the host skipped), and what a command feeds a shell reading stdin (a
  heredoc, a here-string, echo's words, a string piped to iex). A refusal is an action for the owner, recorded with
  its exact command (the outermost simple command, quoted for the session's shell), its folder and a ref
  (guard-<sha1>): the reason names ``brain queue add --kind action --guard <ref>``, which writes it into their queue
  (the cockpit's Apply), and brain queue lists the ones not queued yet.
- ``third-party`` (wi-brain-guard-third-party, EXT-6): a session never installs or runs a third-party kit. Refused: a
  download fed to a shell or an interpreter (``download``: curl | sh, wget -qO- | bash, curl | python3 -, curl | bash
  /dev/stdin, curl | source /dev/stdin, bash <(curl ...), source <(curl ...), sh -c "$(curl ...)", eval "$(curl
  ...)" or unquoted, bash <<<"$(curl ...)", iwr | iex, irm | iex, iex (iwr ...), a WebClient's DownloadString to
  iex), ``claude plugin install NAME@MARKETPLACE`` (and its --marketplace SOURCE) and ``claude plugin marketplace add
  SOURCE`` outside the owner's list (``plugin``: config.json's adapters.claude.sources, marketplace names and sources,
  plus the brain's own marketplace, source repo and folder; claude's global options before plugin read too), and
  ``skills add`` (``skills``: npx, bunx, bun x, pnpm dlx; its --list passes). It sees what the power guard sees
  (wrappers, launchers, nested shells, ssh, what a command feeds a shell); a download to a file (curl -o), or read
  as data by a script named first (python3 analyze.py <(curl ...)), passes. A refusal is an action for the owner
  with the call's exact command, as the owner guard's. The owner's own terminal is never seen: a hook judges a
  session's tool calls only.
- ``attribution``: no ``Co-Authored-By: Claude`` or ``Generated with Claude Code`` line in a git commit message or a
  gh pr create|edit title or body (arguments, heredocs, here-strings, -F and --body-file files), whatever precedes it
  on its line but letters (an emoji, a bullet). The hook's JSON is read as UTF-8 bytes (midsession.read_payload), so a
  Windows console codepage turns no non-ASCII text into letters.
- ``secrets``: no key in what a git commit records: the staged diff, plus what commit -a, the paths the commit names
  or a git add earlier in the same command stages. gitleaks scans the index when it is on the PATH, else the
  patterns of brain.secretscan (an assignment counts when its value is quoted or ends the line). A line marked ``gitleaks:allow`` passes.
- ``markers`` (wi-brain-guard-conflict-markers): no conflict marker in what a git commit (or git merge, rebase,
  cherry-pick, revert or am --continue) records: an added line of the staged diff, of commit -a's, of the paths the
  commit names or of an earlier git add's files (git add -A or -u with no path: the whole worktree), starting with
  <<<<<<< , ||||||| or >>>>>>> , or a bare ======= (brain.markers); during a merge, only a line new against every
  parent. A Markdown or reST setext heading (======= under a line of text) and a file under a fixtures folder pass.
  What git cannot show is an error (errors.log), never a silent pass.
- ``public``: no ``git push`` to a repo of config.json's ``public.repos`` (the remote named or given as a URL, else
  the branch's upstream, else origin) until every commit it sends has the stamp of a green ``brain check --public
  --history`` (brain.public) made under the key it is checked with now: this engine's version, the hash of
  config.json's public rules, gitleaks on the PATH or not (a stamp of 0.2.5 or older has no key and is refused, with
  « rerun brain check --public --history »): the refspecs' sources, every branch with --all or --mirror, the tags with --tags or
  --follow-tags, else HEAD. A push to any other repo passes untouched. A call that runs ``brain check --public`` before
  the push is told to split them: the guard judges the whole call before its first part runs. Its ``commit`` check
  runs brain.public's line checks (the denied terms outside public.allow, e-mail addresses and home folders,
  public.patterns) on what a git commit records in a checkout whose remote is a public repo, so the owner's name in a
  test's data is refused at the commit, not at the push (the lesson les-brain-owner-name-in-fixtures). Its ``config``
  check makes the public and secrets checks fail closed (COMPAT-4, wi-brain-guards-fail-closed): every git commit and
  git push is refused while the configuration they read is unexpected (brain.config.unexpected: config.json
  unreadable, not an object, ``public`` not an object, a ``v`` above the known one, $BRAIN_CONFIG naming no file, or
  no config.json found although $BRAIN_PERSONAL or personal.json names a personal brain; never an unknown key), the
  reason naming the fix; guard.sh refuses them too when no Python that imports brain can run the guards.
- A warning, never a refusal: a Bash heredoc that holds a doubled backslash and writes a file or feeds an
  interpreter, on Windows, gets a note in the session's context (additionalContext): through the Bash tool the
  doubled backslash has arrived single; Write or Edit, or a byte check after (the lesson
  les-brain-heredoc-backslashes). The ledger records it as ``heredoc:backslash``, decision warned.
- ``branches`` (wi-brain-tidy): no branch named outside the allowed list, config.json's ``branches.allowed`` (else
  the engine's BRANCHES; a prefix ending in /, or a pattern with <slug>, <host>, <date>), main and master always
  passing, in a repo of the registry (its checkouts and their worktrees, or gh's --repo naming one's origin): the name
  git checkout -b|-B|--orphan, git switch -c|-C|--orphan, git worktree add -b|-B (or the folder's name it takes
  without -b), git branch NAME or -m|-c [OLD] NEW gives, and gh pr create's head branch (--head, else the folder's
  current branch). A name the command does not resolve ($b) passes. The refusal names the allowed list.

Override, the owner's only: ``BRAIN_GUARD_ALLOW=production,owner,power,third-party,attribution,secrets,markers,
public,branches``, a
guard:check pair (owner:installer, power:cluster) or ``all``, in Claude Code's own environment, which a command
cannot set; the call passes and the ledger records it. Refusals and overrides go to
``<BRAIN_HOME>/ledger/guards-<month>.jsonl`` when the ledger exists (a request for the owner creates it), with the
check that refused (edit, git, shell-write, an owner category, machine, node, wake, cluster, bot, download, plugin,
skills, attribution, secrets, markers, public, commit, config, name; backslash for the heredoc warning). An internal
error lets the call through and goes to ``ledger/errors.log``: a guard never breaks a session. Two exceptions fail
closed: a session-settings call, where an error is a refusal (Remote Control's exceptions), and a commit or push the
public and secrets checks cannot judge (the ``config`` check above, and guard.sh without a Python that imports brain).
"""

from __future__ import annotations

import base64
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

from . import config, markers, midsession, paths, projects, public, secretscan, timing

GUARDS = ("production", "attribution", "secrets", "markers", "owner", "power", "third-party", "public", "branches")
ALLOW_ENV = "BRAIN_GUARD_ALLOW"
EDIT_TOOLS = {"Edit": "file_path", "Write": "file_path", "MultiEdit": "file_path", "NotebookEdit": "notebook_path"}
SHELL_TOOLS = ("Bash", "PowerShell")
CHANGING = {"commit", "checkout", "switch", "restore", "reset", "merge", "rebase", "stash", "push", "pull",
            "cherry-pick", "revert", "am", "apply", "rm", "mv", "clean"}
# git subcommands that only read, which guard.sh's pre-filter lets through without starting Python (git [-C DIR |
# --no-pager | -P] SUB, without --output or a pager option; wi-brain-hook-latency): none is in CHANGING, gives a branch
# its name, records a commit or pushes (tests/test_guards.py checks it against those tables and guard.sh's list).
GIT_READS = frozenset(("status", "log", "diff", "show", "rev-parse", "ls-files", "ls-tree", "blame", "describe",
                       "shortlog", "rev-list", "merge-base", "cat-file", "name-rev", "grep", "check-ignore",
                       "count-objects", "var", "version", "whatchanged", "show-ref", "for-each-ref"))
GIT_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"}
CD = {"cd", "chdir", "pushd", "set-location", "sl", "push-location"}
POP = {"popd", "pop-location"}
DECLARE = {"export", "declare", "typeset", "local", "readonly"}
ASSIGN = re.compile(r"^([A-Za-z_]\w*)=(.*)$", re.S)
PS_ASSIGN = re.compile(r"^\$(?:env:)?([A-Za-z_]\w*)=(.*)$", re.I | re.S)
VAR = re.compile(r"\$(?:\{(\w+)\}|(?:env:)?(\w+))", re.I)
REDIRECT = "\0"  # starts the word segments() puts before a redirection's target: no command text can hold it
SUBSHELL = ("\x01(", "\x01)")  # the one-word segments that open and close a bash subshell, ( ... ) and $( ... )
BASH_REDIR = re.compile(r"(?P<op>&>>?|<>|>>?\|?|<)(?:(?P<dup>&(?:\d+-?|-))|(?P<proc>\()|&)?")
PS_REDIR = re.compile(r"(?P<op>>>?)(?P<dup>&\d)?")
# PowerShell reads \ as a path separator on every system: where os.path does not (Linux, macOS), _path reads a
# backslash left in a path as a slash (bash has dropped its own escapes by then), so that {lab}\x resolves as PowerShell
# resolves it; the words themselves are kept as typed (the owner's queue shows the exact command).
BACKSLASH_SEP = os.sep == "/"
# A cmd.exe option: slashes, then a name without a separator (/c, //J, /XD, /exclude:list.txt); /tmp/x is a path.
CMD_OPTION = re.compile(r"/+[^/\\]*")
PATH_SUBST = re.compile(r"\$\(\s*(mktemp|cygpath|realpath)((?:\s+-[-\w=]*)*)\s*([^()`;&|<>\n]*?)\s*\)")
ATTRIBUTION = [re.compile(r"(?im)^\s*co-authored-by:.*(?:\bclaude\b|anthropic)"),
               re.compile(r"(?im)^[^a-z\n]*generated (?:with|by) \[?claude\b")]   # any prefix but letters
ASSIGNMENT = secretscan.ASSIGNMENT
MAX_FILE = 1_000_000


# --- reading a command -------------------------------------------------------------------------------------------

def _subst_end(command: str, i: int) -> int:
    """The index of the ) that closes the bash $( at ``i``, past nested quotes, escapes and heredoc bodies, or -1."""
    depth, tags, j, n = 0, [], i + 1, len(command)
    while j < n:
        c = command[j]
        if c == "\\":
            j += 2
            continue
        if c == "'":
            j = command.find("'", j + 1)
            if j < 0:
                return -1
        elif c == '"':
            j += 1
            while j < n and command[j] != '"':
                k = _subst_end(command, j) if command.startswith("$(", j) else j + (command[j] == "\\")
                if k < 0:
                    return -1
                j = k + 1
        elif command.startswith("<<", j) and (m := re.match(r"<<-?\s*(['\"]?)([\w.\-]+)\1", command[j:])):
            tags.append(m[2])
            j += m.end() - 1
        elif c == "\n" and tags:
            for tag in tags:
                m = re.compile(r"^[ \t]*" + re.escape(tag) + r"[ \t]*\r?$", re.M).search(command, j + 1)
                j = m.end() if m else n
            tags = []
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if not depth:
                return j
        j += 1
    return -1


def _command_subst(command: str, i: int, word: list[str], segs: list[list[str]]) -> int:
    """Read the bash $( ... ) at ``i``, if one is there (not $(( )): its text joins ``word``, its commands join
    ``segs`` between SUBSHELL[0] and SUBSHELL[1]. Returns the index past its ), or -1."""
    if not command.startswith("$(", i) or command.startswith("$((", i):
        return -1
    j = _subst_end(command, i)
    if j < 0:
        return -1
    word.append(command[i:j + 1])
    segs.extend([[SUBSHELL[0]], *segments(command[i + 2:j]), [SUBSHELL[1]]])
    return j + 1


def segments(command: str, powershell: bool = False, links: dict[int, str] | None = None) -> list[list[str]]:
    """The simple commands in ``command``, each as its words: split on unquoted newlines, ;, &, |, (, ), { and },
    with the shell's quoting (bash: '...', "..." and backslash; PowerShell: '...', "...", backtick, here-strings).
    Comments are dropped, and so are bash heredoc bodies (message text, which the attribution guard reads whole).
    A redirection (>, >>, 2>, &>, >|, <>, *>, and bash's <) becomes a word ``REDIRECT + operator`` before its file; a
    descriptor copy (2>&1, >&-) is dropped, and so is ``>`` in bash's ((...)) and [[ ... ]], where it compares. A bash
    ( or ) is a segment of its own, SUBSHELL[0] or SUBSHELL[1]; the commands of a $( ... ), quoted or not, come
    before the command, between the two, and its word keeps the text; a here-string's <<< is a word of its own. A
    path substitution ($(mktemp), $(cygpath -w
    X), $(realpath X)) stays in its word, for _expand. Given ``links``, it maps a segment's index to what joins it to
    the one before: "|" for a pipe, ";" for ;, &, &&, || or a newline, "<(" for the ( of a bash process substitution;
    an index it lacks is joined otherwise (a bracket)."""
    esc = "`" if powershell else "\\"
    segs: list[list[str]] = []
    seg: list[str] = []
    word: list[str] = []
    started = False
    heredocs: list[str] = []
    arith = 0
    proc = ""   # the <( or >( just read: the ( that follows opens a process substitution
    i, n = 0, len(command)

    def end_word():
        nonlocal word, started
        if started:
            seg.append("".join(word))
        word, started = [], False

    def end_seg():
        nonlocal seg
        end_word()
        if seg:
            segs.append(seg)
        seg = []

    def redirect(i: int) -> int:
        """Read the redirection at ``i`` (its descriptor, if any, is the word before), return where it ends."""
        nonlocal word, started, proc
        fd = "".join(word) if started else ""
        if fd.isdigit() or (powershell and fd == "*"):
            word, started = [], False
        else:
            end_word()
            fd = ""
        m =(PS_REDIR if powershell else BASH_REDIR).match(command, i)
        if m["dup"]:
            return m.end()
        if m.groupdict().get("proc"):
            proc = m["op"] + "("
            return i + 1
        seg.append(REDIRECT + fd + m["op"])
        return m.end()

    while i < n:
        c = command[i]
        if powershell and command.startswith(("@'", '@"'), i) and command[i + 2:i + 3] in ("\n", "\r"):
            close = "\n" + command[i + 1] + "@"
            j = command.find(close, i + 2)
            j = n if j < 0 else j
            word.append(command[i + 2:j].lstrip("\r\n").rstrip("\r"))
            started, i = True, j + len(close)
        elif c == "'":
            j = i + 1
            while True:
                k = command.find("'", j)
                if k < 0:
                    word.append(command[j:])
                    i = n
                    break
                if powershell and command.startswith("''", k):
                    word.append(command[j:k] + "'")
                    j = k + 2
                    continue
                word.append(command[j:k])
                i = k + 1
                break
            started = True
        elif c == '"':
            i += 1
            while i < n and command[i] != '"':
                if not powershell and (j := _command_subst(command, i, word, segs)) > 0:
                    i = j
                    continue
                if command[i] == esc and i + 1 < n and (powershell or command[i + 1] in '$`"\\\n'):
                    word.append(command[i + 1])
                    i += 2
                    continue
                word.append(command[i])
                i += 1
            started, i = True, i + 1
        elif c == esc and i + 1 < n:
            if command[i + 1] not in "\r\n":
                word.append(command[i + 1])
                started = True
            i += 2
        elif c == "#" and not started:
            j = command.find("\n", i)
            i = n if j < 0 else j
        elif not powershell and command.startswith("<<<", i):   # a word of its own: bash <<<"$(curl ...)" too
            end_word()
            seg.append("<<<")
            i += 3
        elif not powershell and command.startswith("<<", i):
            m = re.match(r"<<-?\s*(['\"]?)([\w.\-]+)\1", command[i:])
            if m:
                end_word()
                heredocs.append(m.group(2))
                i += m.end()
            else:
                word.append(c)
                started, i = True, i + 1
        elif not powershell and command.startswith("((", i):
            end_seg()
            arith, i = arith + 1, i + 2
        elif not powershell and arith and command.startswith("))", i):
            end_seg()
            arith, i = arith - 1, i + 2
        elif (c == ">" or (not powershell and (command.startswith("&>", i) or c == "<"))) and not arith \
                and (powershell or seg[:1] != ["[["]):
            i = redirect(i)
        elif command.startswith("{}", i):
            word.append("{}")
            started, i = True, i + 2
        elif not powershell and (m := PATH_SUBST.match(command, i)):
            word.append(m[0])
            started, i = True, m.end()
        elif not powershell and (j := _command_subst(command, i, word, segs)) > 0:   # unquoted too: eval $(curl ...)
            started, i = True, j
        elif c == "\n":
            continued = not seg and not started   # nothing since the operator: `curl URL |` <newline> `sh` is one pipe
            end_seg()
            if links is not None and not (continued and len(segs) in links):
                links[len(segs)] = ";"
            i += 1
            for tag in heredocs:
                m = re.compile(r"^[ \t]*" + re.escape(tag) + r"[ \t]*\r?$", re.M).search(command, i)
                i = m.end() + 1 if m else n
            heredocs = []
        elif c in ";&|(){}":
            end_seg()
            if links is not None and c in ";&|" and command[i - 1:i + 1] != "|&":   # |& pipes stderr too
                links[len(segs)] = "|" if c == "|" and "|" not in (command[i + 1:i + 2], command[i - 1:i]) else ";"
            if not powershell and c in "()":
                if links is not None and c == "(" and proc:
                    links[len(segs)] = proc
                segs.append([SUBSHELL[c == ")"]])
            proc = ""
            i += 1
        elif c in " \t\r":
            end_word()
            i += 1
        else:
            word.append(c)
            started, i = True, i + 1
    end_seg()
    return segs


def _expand(text: str, env: dict[str, str | None]) -> str | None:
    """``text`` with $NAME, ${NAME} and $env:NAME replaced by the variables the command assigned before (``env``, None
    for a value it cannot know), else the environment's, and a path substitution by its path ($(mktemp) a temporary
    one, $(cygpath -w X) and $(realpath X) X); None when one is unknown or a command substitution is left."""
    def value(m):
        name = m.group(1) or m.group(2)
        v = env[name] if name in env else os.environ.get(name)
        if v is None:
            raise LookupError(name)
        return v

    def path(m):
        if m[1] == "cygpath" and re.search(r"-\w*[wm]", m[2]):
            return re.sub(r"^/([a-zA-Z])(?=/|$)", r"\1:", m[3].strip("'\"")) or m[0]
        if m[1] != "mktemp":
            return m[3].strip("'\"") or m[0]
        here = re.search(r"(?:^|\s)(?:-p|--tmpdir)", m[2]) or (m[3] and not re.search(r"(?:^|\s)-\w*t", m[2]))
        return m[0] if here else os.path.join(tempfile.gettempdir(), "tmp.mktemp")

    try:
        out = VAR.sub(value, PATH_SUBST.sub(path, text))
    except LookupError:
        return None
    return None if "$" in out or "`" in out else out


def _path(arg: str, cwd: str) -> str:
    """``arg`` as an absolute path from ``cwd``: ~ and variables expanded, Git Bash's /e/... read as E:/... on Windows,
    a backslash read as a separator elsewhere (BACKSLASH_SEP); ``cwd`` itself when a variable or a command substitution
    in ``arg`` cannot be resolved."""
    expanded = _expand(arg, {})
    if expanded is None:
        return os.path.abspath(cwd)
    arg = os.path.expandvars(os.path.expanduser(expanded.replace("\\", "/") if BACKSLASH_SEP else expanded))
    if os.name == "nt":
        m = re.match(r"^/([a-zA-Z])(?=/|$)", arg)
        if m:
            arg = m.group(1) + ":" + (arg[2:] or "/")
    return os.path.abspath(os.path.join(cwd, arg))


def _prog(word: str) -> str:
    """The program a command word names: its last path part, lowercased, without .exe; npm's Windows shims of a
    launcher, claude or skills (npx.cmd, pnpm.ps1, claude.cmd, skills.bat) are the program they start. Another
    script keeps its extension (install.ps1 is no coreutils install)."""
    name = re.split(r"[\\/]", word)[-1].lower()
    if name.endswith(".exe"):
        return name[:-4]
    stem, ext = os.path.splitext(name)
    return stem if ext in (".cmd", ".ps1", ".bat") and (stem in LAUNCHERS or stem in SHIMMED) else name


def calls(command: str, cwd: str, powershell: bool = False) -> list[tuple[list[str], str]]:
    """Each simple command of ``command`` with the folder it runs in, following cd, Set-Location, pushd and popd (the
    last one before it wins), its words expanded with the variables the command assigned before it (NAME=value,
    export NAME=value, PowerShell's $NAME = value). A redirection that writes a file comes before its command as a
    call of its own, ``[REDIRECT + operator, target]``; an input redirection (<) is dropped. A cd in a bash subshell
    ends with it."""
    out: list[tuple[list[str], str]] = []
    stack: list[str] = []
    subshells: list[str] = []
    env: dict[str, str | None] = {}
    for words in segments(command, powershell):
        if words[0] in SUBSHELL:
            if words[0] == SUBSHELL[0]:
                subshells.append(cwd)
            elif subshells:
                cwd = subshells.pop()
            continue
        marks = {k for k, w in enumerate(words) if w.startswith(REDIRECT)}
        for k in sorted(marks):
            target = words[k + 1] if k + 1 < len(words) and k + 1 not in marks else None
            if target is not None and not words[k].endswith("<"):
                out.append(([words[k], target if (x := _expand(target, env)) is None else x], cwd))
        words = [w for k, w in enumerate(words) if k not in marks and k - 1 not in marks]
        if not words:
            continue
        if powershell and words[0].startswith("$") and len(words) <= 3:
            m = PS_ASSIGN.match("".join(words))
            pairs = [m.groups()] if m else None
        elif all(ASSIGN.match(w) for w in words) or _prog(words[0]) in DECLARE:
            pairs = [m.groups() for m in map(ASSIGN.match, words) if m]
        else:
            pairs = None
        if pairs is not None:
            for name, value in pairs:
                env[name] = _expand(value, env)
            continue
        words = [w if (x := _expand(w, env)) is None else x for w in words]
        while words and re.match(r"^[A-Za-z_]\w*=", words[0]):
            words = words[1:]
        if not words:
            continue
        prog = _prog(words[0])
        if prog in CD:
            args = [w for w in words[1:] if not w.startswith("-")]
            if prog in ("pushd", "push-location"):
                stack.append(cwd)
            if args:
                cwd = _path(args[0], cwd)
            elif len(words) == 1 and prog == "cd":
                cwd = os.path.expanduser("~")
        elif prog in POP:
            cwd = stack.pop() if stack else cwd
        else:
            out.append((words, cwd))
    return out


def git_parts(words: list[str], cwd: str) -> tuple[str, str, list[str]] | None:
    """(folder, subcommand, its arguments) of a git command, after its global options (-C, --git-dir, --work-tree)."""
    i, d = 1, cwd
    while i < len(words) and words[i].startswith("-"):
        name, eq, val = words[i].partition("=")
        if name in GIT_VALUE_OPTS and not eq:
            i += 1
            val = words[i] if i < len(words) else ""
        if name in ("-C", "--work-tree"):
            d = _path(val, d)
        elif name == "--git-dir":
            d = os.path.dirname(_path(val, d))
        i += 1
    return (d, words[i], words[i + 1:]) if i < len(words) else None


def _option_values(args: list[str], names: tuple[str, ...]) -> list[str]:
    """The values of the options ``names`` in ``args`` (``-F x``, ``--file x``, ``--file=x``)."""
    out = []
    for i, a in enumerate(args):
        name, eq, val = a.partition("=")
        if name in names:
            out.append(val if eq else (args[i + 1] if i + 1 < len(args) else ""))
    return out


# --- production checkouts ----------------------------------------------------------------------------------------

def production_roots() -> list[str]:
    """Every project's production checkouts in the registry, as absolute paths."""
    return [os.path.abspath(str(p)) for proj in projects.guarded() for p in proj.production]


def in_production(path: str, roots: list[str]) -> str | None:
    """The production checkout that holds ``path``, unless a worktree or repo nested in it (a .git between) does."""
    p = os.path.normcase(os.path.abspath(path))
    for root in roots:
        r = os.path.normcase(root)
        if p != r and not p.startswith(r.rstrip("\\/") + os.sep):
            continue
        d = p
        while len(d) > len(r):
            if os.path.exists(os.path.join(d, ".git")):
                break
            d = os.path.dirname(d)
        else:
            return root
    return None


def _changes(sub: str, args: list[str]) -> bool:
    if sub not in CHANGING or "-h" in args or "--help" in args:
        return False
    if sub == "pull":
        return "--ff-only" not in args
    if sub == "stash":
        return args[:1] not in (["list"], ["show"])
    return True


def check_production(tool: str, inp: dict, cmds: list[tuple[list[str], str]], cwd: str) -> str | None:
    fix = "work in a worktree, merge by PR, then git pull --ff-only there"
    if tool in EDIT_TOOLS:
        target = inp.get(EDIT_TOOLS[tool]) or ""
        root = target and in_production(_path(target, cwd), production_roots())
        return f"{tool} refused: {target} is in the production checkout {root}; {fix}" if root else None
    roots = None
    for words, d in cmds:
        prog = _prog(words[0])
        if prog == "git":
            parts = git_parts(words, d)
            if not parts or not _changes(parts[1], parts[2]):
                continue
            d, what = parts[0], f"git {parts[1]}"
        elif prog == "gh" and words[1:3] == ["pr", "checkout"]:
            what = "gh pr checkout"
        else:
            continue
        roots = production_roots() if roots is None else roots
        root = in_production(d, roots)
        if root:
            return f"{what} refused in the production checkout {root}: {fix}"
    return None


# --- shell writes into production checkouts ----------------------------------------------------------------------

DISCARD = {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty", "nul", "nul:", "$null", "-"}
# Programs that write the files they name: name -> (which positionals are targets, short options that take a value,
# long options that take a value, options whose value is a target). all: every positional; last: the destination;
# after1: all but the first (chmod's mode); none: only the target options.
_T = ("-t", "--target-directory")
WRITERS = {
    "rm": ("all", "", (), ()), "rmdir": ("all", "", (), ()), "unlink": ("all", "", (), ()),
    "shred": ("all", "nsu", ("iterations", "size", "random-source"), ()), "tee": ("all", "", ("output-error",), ()),
    "touch": ("all", "dtr", ("date", "reference"), ()), "mkdir": ("all", "m", ("mode", "context"), ()),
    "truncate": ("all", "sr", ("size", "reference"), ()), "mv": ("all", "St", ("suffix", "target-directory"), _T),
    "cp": ("last", "St", ("suffix", "target-directory"), _T), "ln": ("last", "St", ("suffix", "target-directory"), _T),
    "install": ("last", "gmoSt", ("group", "mode", "owner", "suffix", "target-directory", "strip-program"), _T),
    "rsync": ("last", "efT", ("rsh", "filter", "exclude", "include", "exclude-from", "include-from", "files-from",
                              "temp-dir", "rsync-path", "chmod", "chown", "log-file"), ()),
    "scp": ("last", "cFiJlPSoD", (), ()), "chmod": ("after1", "", ("reference",), ()),
    "chown": ("after1", "", ("reference", "from"), ()), "chgrp": ("after1", "", ("reference",), ()),
    "sort": ("none", "kStTo", ("key", "buffer-size", "field-separator", "temporary-directory", "output",
                               "files0-from"), ("-o", "--output")),
    "curl": ("none", "oDcK", ("output", "dump-header", "cookie-jar", "output-dir", "config"),
             ("-o", "--output", "-D", "--dump-header", "-c", "--cookie-jar", "--output-dir")),
}
# In place (sed -i, perl -i, awk -i inplace) or writing into a folder (tar x, unzip, patch, wget): read in writes().
SPECIAL = {"sed", "perl", "ruby", "awk", "gawk", "dd", "tar", "bsdtar", "unzip", "patch", "wget", "find"}
# PowerShell cmdlets that write: name -> (positions that are targets, target parameters, whether a call with no target
# writes in the current folder: pipeline input, New-Item -Name). A position counts positionals, a comma list as one.
_PATH = ("path", "literalpath", "pspath", "lp")
PS_WRITERS = {
    "set-content": ((0,), _PATH, True), "add-content": ((0,), _PATH, True), "clear-content": ((0,), _PATH, True),
    "out-file": ((0,), ("filepath", "literalpath", "path", "lp", "pspath"), False),
    "tee-object": ((0,), ("filepath", "literalpath", "lp", "pspath"), False),
    "export-csv": ((0,), _PATH, False), "export-clixml": ((0,), _PATH, False), "new-item": ((0,), _PATH, True),
    "remove-item": ((0,), _PATH, True), "rename-item": ((0,), _PATH, True), "copy-item": ((1,), ("destination",), True),
    "move-item": ((0, 1), _PATH + ("destination",), True),
    "start-transcript": ((0,), _PATH + ("outputdirectory",), False),
    "expand-archive": ((1,), ("destinationpath",), True), "compress-archive": ((1,), ("destinationpath",), False),
    "invoke-webrequest": ((), ("outfile",), False), "invoke-restmethod": ((), ("outfile",), False),
}
PS_ALIASES = {"sc": "set-content", "ac": "add-content", "clc": "clear-content", "tee": "tee-object",
              "epcsv": "export-csv", "ni": "new-item", "mkdir": "new-item", "md": "new-item", "ri": "remove-item",
              "rm": "remove-item", "rmdir": "remove-item", "rd": "remove-item", "del": "remove-item",
              "erase": "remove-item", "rni": "rename-item", "ren": "rename-item", "cpi": "copy-item",
              "cp": "copy-item", "copy": "copy-item", "mi": "move-item", "mv": "move-item", "move": "move-item",
              "iwr": "invoke-webrequest", "curl": "invoke-webrequest", "wget": "invoke-webrequest",
              "irm": "invoke-restmethod"}
# Parameters that take a value, so that the value is not read as a position (the common ones and their aliases).
PS_VALUES = _PATH + ("filepath", "destination", "destinationpath", "outfile", "outputdirectory", "value", "encoding",
                     "itemtype", "type", "filter", "include", "exclude", "credential", "stream", "delimiter", "width",
                     "inputobject", "name", "newname", "target", "uri", "method", "headers", "body", "contenttype",
                     "useragent", "compressionlevel", "variable", "erroraction", "ea", "warningaction", "wa",
                     "informationaction", "infa", "errorvariable", "ev", "warningvariable", "wv", "outvariable", "ov",
                     "outbuffer", "ob", "pipelinevariable", "pv")
DOTNET = re.compile(r"^\[(?:system\.)?io\.(?:file|directory)\]::(?:write|append|create|delete|move|copy|replace|open)",
                    re.I)
# cmd.exe's commands (cmd /c), options /x: name -> which positionals are targets.
CMD_WRITERS = {"del": "all", "erase": "all", "rd": "all", "rmdir": "all", "md": "all", "mkdir": "all", "move": "all",
               "ren": "first", "rename": "first", "mklink": "first", "copy": "last", "xcopy": "last",
               "robocopy": "second"}
SHELLS = {"bash": "bash", "sh": "bash", "zsh": "bash", "dash": "bash", "ksh": "bash", "pwsh": "ps",
          "powershell": "ps", "cmd": "cmd"}
# Wrappers before the program they run, with their short options that take a value.
WRAPPERS = {"env": "uCS", "nohup": "", "nice": "n", "time": "", "command": "", "exec": "a", "builtin": "",
            "sudo": "ugCDhpr", "timeout": "sk", "stdbuf": "ioe", "xargs": "IiadEeLlnPs", "gsudo": "udn", "doas": "uC",
            "pkexec": ""}
WRAPPER_LONGS = {"sudo": ("user", "group", "host", "prompt", "close-from", "chdir", "role", "type", "other-user",
                          "command-timeout"),
                 "env": ("unset", "chdir"), "nice": ("adjustment",), "timeout": ("signal", "kill-after"),
                 "stdbuf": ("input", "output", "error"), "gsudo": ("user", "integrity", "directory"),
                 "pkexec": ("user",), "xargs": ("arg-file", "delimiter", "eof", "replace", "max-lines", "max-args",
                                                "max-procs", "max-chars", "process-slot-var")}
# Inline code: interpreter -> (its code options, its options that take a value, the calls that write a file: (call,
# where the target is, which argument is the mode that must write)). The target is an argument's index, all of them,
# the receiver (self: Path(...).write_text) or any path in the code (code: perl, ruby).
_P = r"(?:Sync)?\s*\("
INLINE = {
    "python": ("c", "XWm", [
        (r"(?<![\w.])open\s*\(|\b(?:io|codecs|gzip|bz2|lzma)\.open\s*\(", 0, 1), (r"\.open\s*\(", "self", 0),
        (r"\.(?:write_text|write_bytes|touch|unlink|rmdir|mkdir|symlink_to|hardlink_to)\s*\(", "self", None),
        (r"\.to_(?:csv|parquet|feather|excel|pickle|hdf|stata|orc|json)\s*\(|\.save\w*\s*\(", 0, None),
        (r"\bos\.(?:remove|unlink|rmdir|removedirs|mkdir|makedirs|truncate)\s*\(|\bshutil\.(?:rmtree|make_archive)"
         r"\s*\(", 0, None),
        (r"\bos\.(?:rename|replace|renames)\s*\(|\bshutil\.move\s*\(", "all", None),
        (r"\bos\.(?:symlink|link)\s*\(|\bshutil\.(?:copy\w*|unpack_archive)\s*\(", 1, None)]),
    "node": ("ep", "r", [
        (r"\b(?:writeFile|appendFile|createWriteStream|truncate|unlink|rm|rmdir|mkdir)" + _P, 0, None),
        (r"\brename" + _P, "all", None), (r"\b(?:copyFile|cp|symlink|link)" + _P, 1, None),
        (r"\bopen" + _P, 0, 1)]),
    "perl": ("eE", "IMm", [
        (r"\bopen\b[^;\n]*?['\"]\s*\+?[>|]|\b(?:unlink|rename|mkdir|rmdir|truncate|utime|chmod|symlink)\b", "code",
         None)]),
    "ruby": ("e", "IrC", [
        (r"\b(?:File|IO)\.(?:write|delete|unlink|rename|symlink|truncate|chmod)\b|\bFileUtils\.|\bDir\.(?:mkdir|rmdir"
         r"|delete|unlink)\b|\bopen\s*\([^;\n]*?['\"][wa]\+?['\"]", "code", None)]),
}
WRITE_MODE = re.compile(r"^[rbtUwaxs+]*[wax+][rbtUwaxs+]*$")
LITERAL = re.compile(r"(?:\b[rRbBuUfF]{1,2})?(['\"])((?:\\.|(?!\1)[^\\])*)\1")
PATH_LIKE = re.compile(r"[\\/]|^\.\.?$|\.\w{1,10}$")


class Unresolved(str):
    """The folder a write is judged in when its target cannot be read from the command (``what``: $(...), an unset
    variable, a cmdlet's pipeline input, a path inline code computes)."""

    def __new__(cls, folder: str, what: str):
        self = super().__new__(cls, os.path.abspath(folder))
        self.what = what
        return self


def _targets(names, cwd: str) -> list[str]:
    """``names`` as absolute paths from ``cwd``, without the discarded outputs (/dev/null, NUL, $null, -); one that
    cannot be resolved is the folder of its static part (/tmp for /tmp/$D), else ``cwd``, as Unresolved."""
    out = []
    for n in names:
        if n and n.lower() not in DISCARD:
            static = os.path.dirname(re.split(r"[$`]", n, maxsplit=1)[0])
            out.append(_path(n, cwd) if _expand(n, {}) is not None else
                       Unresolved(_path(static, cwd) if static else cwd, "$(...)" if n == "$" else n))
    return out


def _getopt(args: list[str], values: str = "", longs=(), optional: str = ""):
    """(positionals, [(option, value)]) of ``args`` read like getopt: a short option of ``values`` takes the rest of
    its cluster or the next word, one of ``optional`` only the rest of its cluster (sed -i.bak), a long option of
    ``longs`` its =value or the next word; -- ends the options."""
    pos, opts, i = [], [], 0
    while i < len(args):
        a = args[i]
        if a == "--":
            pos += args[i + 1:]
            break
        if a.startswith("--"):
            name, eq, val = a.partition("=")
            if not eq and name[2:] in longs and i + 1 < len(args):
                i, val = i + 1, args[i + 1]
            opts.append((name, val))
        elif a.startswith("-") and len(a) > 1:
            for k in range(1, len(a)):
                if a[k] in values + optional:
                    val = a[k + 1:]
                    if not val and a[k] in values and i + 1 < len(args):
                        i, val = i + 1, args[i + 1]
                    opts.append(("-" + a[k], val))
                    break
                opts.append(("-" + a[k], ""))
        else:
            pos.append(a)
        i += 1
    return pos, opts


def _unwrap(words: list[str]) -> list[str]:
    """``words`` from the program a wrapper runs (env X=1, nohup, nice -n 5, timeout 10, xargs), with a "." for the
    arguments xargs adds from its input, which are relative to the folder."""
    stdin = False
    while words and (w := _prog(words[0])) in WRAPPERS:
        i = 1
        while i < len(words) and (words[i].startswith("-") or (w == "env" and ASSIGN.match(words[i]))):
            a = words[i]
            if a.startswith("--"):   # --user root (sudo), --signal KILL (timeout); --opt=value is one word
                i += 2 if "=" not in a and a[2:] in WRAPPER_LONGS.get(w, ()) else 1
            elif a.startswith("-") and len(a) > 1:   # -u root, -uroot, -iu root: a value option ends its cluster
                k = next((j for j in range(1, len(a)) if a[j] in WRAPPERS[w]), None)
                i += 2 if k == len(a) - 1 else 1
            else:
                i += 1
        stdin = stdin or (w == "xargs" and not any(a.startswith(("-I", "-i", "--replace")) for a in words[1:i]))
        words = words[i + (w == "timeout"):]
    return words + ["."] if words and stdin else words


def _ps_targets(name: str, args: list[str], cwd: str) -> list[str]:
    """The paths a PowerShell cmdlet of PS_WRITERS writes: its target parameters and positions (abbreviated parameter
    names and -Name:value read as PowerShell does); none under -WhatIf."""
    slots, params, here = PS_WRITERS[name]
    groups, named, i = [], [], 0
    while i < len(args):
        a = args[i]
        if a.startswith("-") and len(a) > 1 and not a[1].isdigit():
            p, colon, val = a[1:].lower().partition(":")
            if p == "whatif":
                return []
            target = any(t.startswith(p) for t in params)
            if (target or any(t.startswith(p) for t in PS_VALUES)) and not colon and i + 1 < len(args):
                i, val = i + 1, args[i + 1]
            if target:
                named.append(val)
        elif groups and (groups[-1][-1].endswith(",") or a.startswith(",")):
            groups[-1].append(a)
        else:
            groups.append([a])
        i += 1
    names = named + [x for k in slots if k < len(groups) for w in groups[k] for x in w.split(",")]
    return _targets([x.strip() for x in names], cwd) or ([Unresolved(cwd, "its input")] if here else [])


def _inline(args: list[str], code: str, values: str) -> list[str]:
    """The words from an interpreter's inline code on (python -c CODE ARGS, node -e), or [] when it runs a script."""
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--eval", "--print") or a.startswith(("--eval=", "--print=")):
            return ([a.partition("=")[2]] if "=" in a else []) + args[i + 1:]
        if not a.startswith("-") or a == "-":
            return []
        for k in range(1, len(a) if not a.startswith("--") else 0):
            if a[k] in code:
                return ([a[k + 1:]] if a[k + 1:] else []) + args[i + 1:]
            if a[k] in values:
                i += k + 1 == len(a)
                break
        i += 1
    return []


def _args(code: str, i: int) -> list[str]:
    """The arguments of the call whose ( is at ``i`` in ``code``, split on its top-level commas."""
    out, depth, start, quote, j = [], 0, i + 1, "", i
    while j < len(code):
        ch = code[j]
        if quote:
            j += ch == "\\"
            quote = "" if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if not depth:
                out.append(code[start:j])
                break
        elif ch == "," and depth == 1:
            out.append(code[start:j])
            start = j + 1
        j += 1
    return [a.strip() for a in out if a.strip()]


def _receiver(code: str, i: int) -> str:
    """The expression before the method call whose . is at ``i``: names, dots and bracketed parts."""
    j, depth = i, 0
    while j > 0:
        ch = code[j - 1]
        if ch in ")]":
            depth += 1
        elif ch in "([" and depth:
            depth -= 1
        elif not depth and not (ch.isalnum() or ch in "_."):
            break
        j -= 1
    return code[j:i]


def _paths_of(expr: str, code: str, argv: list[str], depth: int = 2) -> list[str]:
    """The path-like string literals and arguments (sys.argv[1], process.argv[1]) of ``expr``, and those of what the
    names in it are assigned in ``code`` (two levels)."""
    names = [m[2].replace("\\\\", "\\") for m in LITERAL.finditer(expr)]
    names += [argv[int(k) - 1] for k in re.findall(r"\b(?:sys|process)\.argv\[(\d+)\]", expr)
              if 0 < int(k) <= len(argv)]
    for ident in set(re.findall(r"\b[A-Za-z_]\w*", LITERAL.sub("", expr))) if depth else ():
        m = re.search(rf"(?:^|[;\n(])\s*{ident}\s*:?=(?!=)\s*([^;\n]*)", code)
        names += _paths_of(m[1], code, argv, depth - 1) if m else []
    return [n for n in names if PATH_LIKE.search(n) and "://" not in n]


def _code_targets(prog: str, words: list[str], cwd: str) -> list[str]:
    """The paths inline code writes (``words``: the code, then its arguments): each writing call's target, read from
    its literals and the assignments of its names; a target it computes otherwise is the folder, as Unresolved."""
    code, found, unknown = words[0], [], False
    for call, where, mode in INLINE[prog][2]:
        for m in re.finditer(call, code):
            if where == "code":
                found += [n for n in [x[2] for x in LITERAL.finditer(code)] + words[1:] if PATH_LIKE.search(n)]
                unknown = unknown or not found
                continue
            args = _args(code, m.end() - 1)
            if mode is not None and not any(WRITE_MODE.match(lit[2]) for k, a in enumerate(args)
                                            if k == mode or a.startswith("mode=") for lit in LITERAL.finditer(a)):
                continue
            if where == "self":
                recv = _receiver(code, m.start())
                exprs = [] if recv in ("os", "shutil", "os.path") else [recv]
            else:
                exprs = args if where == "all" else args[where:where + 1]
            for e in exprs:
                paths = _paths_of(e, code, words[1:])
                found += paths
                unknown = unknown or not paths
    return _targets(found, cwd) + ([Unresolved(cwd, "a path the code computes")] if unknown else [])


def _pwsh_command(args: list[str], cwd: str) -> tuple[str | None, str]:
    """(the command, its folder) that pwsh or powershell runs from its arguments: -Command, -EncodedCommand or the
    first positional; None for -File or a .ps1 script, "" when an encoded command cannot be read."""
    i = 0
    while i < len(args):
        a, low = args[i], args[i].lower()
        p = low[1:].partition(":")[0]
        if not low.startswith(("-", "/")):
            return (None if low.endswith(".ps1") else " ".join(args[i:])), cwd
        if p and "command".startswith(p) and p[0] == "c":
            return " ".join(args[i + 1:]) or None, cwd
        if p in ("e", "ec", "en", "enc") or (len(p) > 2 and "encodedcommand".startswith(p)):
            try:
                return base64.b64decode(args[i + 1]).decode("utf-16-le"), cwd
            except (IndexError, ValueError):
                return "", cwd
        if p and "file".startswith(p):
            return None, cwd
        if p in ("wd", "workingdirectory") and i + 1 < len(args):
            cwd = _path(args[i + 1], cwd)
        if p in _PWSH_VALUES:
            i += 1
        i += 1
    return None, cwd


_PWSH_VALUES = ("ex", "ep", "executionpolicy", "w", "windowstyle", "o", "of", "outputformat", "if", "inputformat", "wd",
                "workingdirectory", "config", "configurationname", "settingsfile")


def _pwsh_file(args: list[str]) -> list[str] | None:
    """The script and its arguments that pwsh or powershell runs (-File X ..., or a first positional .ps1)."""
    i = 0
    while i < len(args):
        low = args[i].lower()
        p = low[1:].partition(":")[0]
        if not low.startswith(("-", "/")):
            return args[i:] if low.endswith(".ps1") else None
        if p and "file".startswith(p):
            return args[i + 1:] or None
        if p and (("command".startswith(p) and p[0] == "c") or "encodedcommand".startswith(p)):
            return None
        i += 1 + (p in _PWSH_VALUES)
    return None


def writes(words: list[str], cwd: str, shell: str = "bash"):
    """(what, path) for each file or folder the simple command ``words`` writes as far as its text tells: a
    redirection, the programs and cmdlets of WRITERS, SPECIAL, PS_WRITERS and CMD_WRITERS, inline code that writes
    (python -c, node -e, perl -e) and, read again, the commands of bash -c, pwsh -Command and cmd /c. ``shell`` is
    bash, ps or cmd, the shell that reads ``words``. What a script or a program writes by itself is not seen."""
    if words[0].startswith(REDIRECT):
        yield from ((f"redirection {words[0][1:]}", p) for p in _targets(words[1:2], cwd))
        return
    words = _unwrap(words)
    if not words:
        return
    name, args = re.split(r"[\\/]", words[0])[-1], words[1:]
    prog = _prog(name)
    prog = "python" if re.fullmatch(r"python[\d.]*w?|py", prog) else prog
    if shell == "ps" and PS_ALIASES.get(prog, prog) in PS_WRITERS:
        yield from ((name, p) for p in _ps_targets(PS_ALIASES.get(prog, prog), args, cwd))
    elif shell == "cmd" and prog in CMD_WRITERS:
        pos, kind = [a for a in args if not CMD_OPTION.fullmatch(a)], CMD_WRITERS[prog]
        names = {"all": pos, "first": pos[:1], "second": pos[1:2], "last": pos[-1:] if len(pos) > 1 else ["."]}[kind]
        yield from ((name, p) for p in _targets(names, cwd))
    elif prog in WRITERS:
        kind, values, longs, target_opts = WRITERS[prog]
        pos, opts = _getopt(args, values, longs)
        named = [v for o, v in opts if o in target_opts]
        last = pos[-1:] if len(pos) > 1 else ["."] if pos else []
        names = {"all": pos, "last": last, "after1": pos[1:], "none": []}[kind]
        names = named + (names if kind == "all" or not named else [])
        if prog == "curl" and any(o in ("-O", "--remote-name", "--remote-name-all") for o, _ in opts):
            names += [v for o, v in opts if o == "--output-dir"] or ["."]
        yield from ((name, p) for p in _targets(names, cwd))
    elif prog in ("sed", "perl", "ruby"):
        values, longs = ("efl", ("expression", "file", "line-length")) if prog == "sed" else ("eEIMmrC", ())
        pos, opts = _getopt(args, values, longs, optional="i" if prog == "sed" else "i0lx")
        given = ("-e", "-f", "--expression", "--file") if prog == "sed" else ("-e", "-E")
        scripts = [o for o, _ in opts if o in given]
        if any(o in ("-i", "--in-place") for o, _ in opts):
            yield from ((f"{name} -i", p) for p in _targets(pos if scripts else pos[1:], cwd))
        if prog != "sed":
            code = [v for o, v in opts if o in ("-e", "-E")]
            if code:
                yield from ((f"{name} -e", p) for p in _code_targets(prog, ["\n".join(code)] + pos, cwd))
    elif prog in ("awk", "gawk"):
        pos, opts = _getopt(args, "fvFiE", ("file", "assign", "field-separator", "include"))
        if any(o in ("-i", "--include") and v == "inplace" for o, v in opts):
            program = any(o in ("-f", "--file") for o, _ in opts)
            yield from ((f"{name} -i inplace", p) for p in _targets(pos if program else pos[1:], cwd))
    elif prog == "dd":
        yield from ((name, p) for p in _targets([a[3:] for a in args if a.startswith("of=")], cwd))
    elif prog in ("tar", "bsdtar"):
        first = ["-" + args[0]] if args and not args[0].startswith("-") else args[:1]
        pos, opts = _getopt(first + args[1:], "fCbHKLNTVXg", ("file", "directory", "files-from", "exclude-from"))
        given = {o for o, _ in opts}
        if given & {"-x", "--extract", "--get"}:
            yield from ((name, p) for p in _targets([v for o, v in opts if o in ("-C", "--directory")] or ["."], cwd))
        elif given & {"-c", "-r", "-u", "-A", "--create", "--append", "--update", "--delete", "--concatenate"}:
            yield from ((name, p) for p in _targets([v for o, v in opts if o in ("-f", "--file")], cwd))
    elif prog == "unzip":
        pos, opts = _getopt(args, "dP")
        if not {o for o, _ in opts} & {"-l", "-t", "-v", "-p", "-Z", "-z"}:
            yield from ((name, p) for p in _targets([v for o, v in opts if o == "-d"] or ["."], cwd))
    elif prog == "patch":
        pos, opts = _getopt(args, "dorBpiDFzVYg", ("directory", "output", "reject-file", "input", "strip", "prefix",
                                                   "ifdef", "fuzz", "suffix", "version-control"))
        if "--dry-run" not in {o for o, _ in opts}:
            names = [v for o, v in opts if o in ("-o", "--output", "-r", "--reject-file")]
            yield from ((name, p) for p in _targets(names + ([v for o, v in opts if o in ("-d", "--directory")]
                                                              or ["."]), cwd))
    elif prog == "wget":
        pos, opts = _getopt(args, "OPoaeiBtTwQUlADRIX", ("output-document", "directory-prefix", "output-file",
                                                           "append-output", "execute", "input-file"))
        if "--spider" not in {o for o, _ in opts}:
            out = [v for o, v in opts if o in ("-O", "--output-document")]
            dirs = [v for o, v in opts if o in ("-P", "--directory-prefix")]
            logs = [v for o, v in opts if o in ("-o", "--output-file", "-a", "--append-output")]
            yield from ((name, p) for p in _targets(out + logs + ([] if out else dirs or ["."]), cwd))
    elif prog == "find":
        k = next((i for i, a in enumerate(args) if a[:1] in "-(!"), len(args))
        starts, expr = args[:k] or ["."], args[k:]
        if "-delete" in expr:
            yield from (("find -delete", p) for p in _targets(starts, cwd))
        for i, a in enumerate(expr):
            if a in ("-exec", "-execdir", "-ok", "-okdir"):
                end = next((j for j in range(i + 1, len(expr)) if expr[j] in (";", "+")), len(expr))
                for s in starts:
                    sub = [s if w == "{}" else w for w in expr[i + 1:end]]
                    yield from ((f"find {a} {what}", p) for what, p in (writes(sub, cwd, shell) if sub else ()))
    elif prog in INLINE:
        code = _inline(args, *INLINE[prog][:2])
        if code:
            yield from ((f"{name} {'-c' if prog == 'python' else '-e'}", p) for p in _code_targets(prog, code, cwd))
    elif (nested := _nested(prog, args, cwd, shell)) is not None:
        inner, sub, cwd = nested
        if not inner:
            yield f"{name} -EncodedCommand", Unresolved(cwd, "its encoded command")
        else:
            yield from ((f"{name}: {what}", p) for what, p in shell_writes(calls(inner, cwd, sub != "bash"), sub))


def _nested(prog: str, args: list[str], cwd: str, shell: str):
    """(the command a shell runs from its arguments, the shell that reads it: bash, ps or cmd, its folder) for bash -c,
    pwsh -Command and -EncodedCommand ("" when it cannot be read), cmd /c and iex; None for another program, a script
    (-File) or no command. bash -c's command is its first operand, read past the options' values by _bash_words (bash
    -euo pipefail -c CMD, bash -co pipefail CMD, bash --rcfile FILE -c CMD)."""
    if not (prog in SHELLS or (shell == "ps" and prog in ("iex", "invoke-expression"))):
        return None
    inner, sub = None, SHELLS.get(prog, "ps")
    if sub == "bash":
        opts, pos = _bash_words(args)   # the option values skipped as bash reads them: -euo pipefail, --rcfile FILE
        pos = pos[1:] if pos[:1] == ["-"] else pos   # bash -c - CMD: a lone - ends the options, like --
        inner = (pos[0] or None) if pos and _bash_short(opts, "c") else None
    elif sub == "cmd":
        k = next((i for i, a in enumerate(args) if a.lower().lstrip("/") in ("c", "k")), None)
        inner = None if k is None else " ".join(args[k + 1:]) or None
    elif prog in ("iex", "invoke-expression"):
        inner = " ".join(a for a in args if not a.lower().startswith("-c")) or None
    else:
        inner, cwd = _pwsh_command(args, cwd)
    return None if inner is None else (inner, sub, cwd)


def shell_writes(cmds: list[tuple[list[str], str]], shell: str = "bash"):
    """(what, path) for each write of the calls ``cmds`` (see writes()), PowerShell's [IO.File]::Write...(path, ...)
    included: its path is in the call after it, the arguments between its parentheses."""
    for k, (words, d) in enumerate(cmds):
        if shell != "bash" and DOTNET.match(words[0]):
            args = cmds[k + 1][0] if k + 1 < len(cmds) else []
            names = [x.strip() for a in args for x in a.split(",") if PATH_LIKE.search(x.strip())]
            yield from ((words[0], p) for p in _targets(names, d) or [os.path.abspath(d)])
        else:
            yield from writes(words, d, shell)


def check_shell_writes(cmds: list[tuple[list[str], str]], powershell: bool = False) -> str | None:
    roots = None
    for what, target in shell_writes(cmds, "ps" if powershell else "bash"):
        roots = production_roots() if roots is None else roots
        root = in_production(target, roots)
        if root:
            if isinstance(target, Unresolved):
                target = f"{target.what} (read as its folder {target})"
            return (f"{what} refused: it writes {target} in the production checkout {root}; write in a worktree or "
                    "outside the checkout (merge by PR, then git pull --ff-only there)")
    return None


# --- what a call runs, nested commands included --------------------------------------------------------------------

SSH_VALUES = "BbcDEeFIiJLlmOoPpQRSWw"   # ssh's options that take a value; its first other word is the host
_START_VALUES = ("filepath", "argumentlist", "workingdirectory", "verb", "windowstyle", "credential", "environment",
                 "redirectstandardoutput", "redirectstandarderror", "redirectstandardinput")


def _start_process(args: list[str]) -> list[str] | None:
    """The program and arguments Start-Process launches (-FilePath, -ArgumentList as one string or a comma list)."""
    file, given, pos, i = None, [], [], 0
    while i < len(args):
        a = args[i]
        if a.startswith("-") and len(a) > 1:
            p, colon, val = a[1:].lower().partition(":")
            if any(n.startswith(p) for n in _START_VALUES) and not colon and i + 1 < len(args):
                i, val = i + 1, args[i + 1]
                while val.endswith(",") and i + 1 < len(args):
                    i, val = i + 1, val + args[i + 1]
            if "filepath".startswith(p):
                file = val
            elif "argumentlist".startswith(p):
                given.append(val)
        else:
            pos.append(a)
        i += 1
    if file is None and pos:
        file, pos = pos[0], pos[1:]
    words = [x for v in given + pos for part in v.split(",") for x in part.split()]
    return [file, *words] if file else None


def _launched(prog: str, args: list[str], shell: str) -> list[str] | None:
    """The words of the program another one launches: pwsh -File, Start-Process (saps, PowerShell's start), and the
    start of cmd and Git Bash (a "" title and its /options skipped)."""
    if prog in ("pwsh", "powershell"):
        return _pwsh_file(args)
    if prog in ("start-process", "saps") or (prog == "start" and shell == "ps"):
        return _start_process(args)
    if prog == "start":
        rest = [a for a in args if not a.startswith("/")]
        return rest[1:] if rest[:1] == [""] else rest or None
    return None


def _ssh_remote(args: list[str]) -> list[str] | None:
    """The remote command of ssh or plink: the words after the host, with the options OpenSSH also reads after the
    host (ssh build-host -t 'sudo reboot', ssh host -p 2222 cmd, ssh host -- cmd) skipped."""
    i, host = 0, None
    while i < len(args):
        a = args[i]
        if a == "--":
            i += 1
            if host is not None:
                break
        elif a.startswith("-") and len(a) > 1:
            k = next((j for j in range(1, len(a)) if a[j] in SSH_VALUES), None)
            i += 2 if k == len(a) - 1 else 1
        elif host is None:
            host, i = a, i + 1
        else:
            break
    return (args[i:] or None) if host is not None else None


# Programs that run another one: name -> (short options that take a value, long ones, positionals before it). uv run,
# poetry run and npm exec name their runner first.
LAUNCHERS = {"chroot": ("", ("userspec", "groups"), 1), "nsenter": ("tmuinpUCSGrwT", ("target",), 0),
             "wsl": ("du", ("distribution", "user", "cd"), 0), "npx": ("pc", ("package", "call"), 0),
             "uvx": ("p", ("from", "with", "python"), 0), "bunx": ("", (), 0), "pnpx": ("", (), 0),
             "uv": ("p", ("with", "python", "project", "directory", "env-file", "extra", "group", "package", "index",
                          "from"), 1),
             "poetry": ("C", ("directory",), 1), "pipx": ("", ("spec", "python"), 1), "pdm": ("p", ("project",), 1),
             "hatch": ("e", ("env",), 1), "rye": ("", (), 1),
             "npm": ("w", ("package", "call", "prefix", "workspace"), 1),
             "pnpm": ("CF", ("dir", "filter"), 1), "yarn": ("", ("cwd",), 1), "bun": ("", ("cwd",), 1),
             "corepack": ("", (), 0)}
COREPACK_RUNS = {"npm": "npm", "npx": "npx", "pnpm": "pnpm", "pnpx": "pnpx", "yarn": "yarn", "yarnpkg": "yarn"}
LAUNCH_VERBS = {"uv": {"run", "tool"}, "poetry": {"run"}, "pipx": {"run"}, "pdm": {"run"}, "hatch": {"run"},
                "rye": {"run"}, "npm": {"exec", "x"}, "pnpm": {"exec", "dlx"}, "yarn": {"dlx", "exec"},
                "bun": {"x"}}   # its global options may come before the verb: pnpm --silent dlx, npm --yes exec
SHIMMED = {"claude", "skills"}   # with LAUNCHERS, the programs whose npm Windows shims (.cmd, .ps1, .bat) _prog unwraps
STDIN_FEEDERS = {"echo", "printf", "write-output", "write-host", "echo.exe"}


def _past_options(prog: str, args: list[str], i: int) -> int:
    """The index of the first operand of ``args`` from ``i``, past the launcher's options and their values (and a --,
    or wsl's -e)."""
    shorts, longs, _ = LAUNCHERS[prog]
    while i < len(args):
        a = args[i]
        if a == "--" or (prog == "wsl" and a in ("-e", "--exec")):
            return i + 1
        if a.startswith("--"):
            i += 2 if "=" not in a and a[2:] in longs else 1
        elif a.startswith("-") and len(a) > 1:
            k = next((j for j in range(1, len(a)) if a[j] in shorts), None)
            i += 2 if k == len(a) - 1 else 1
        else:
            break
    return i


def _launcher(prog: str, args: list[str]) -> list[str] | None:
    """The words of the program a launcher of LAUNCHERS runs (wsl -e cmd, uv run cmd, npx tool, bun x tool, chroot DIR
    cmd, corepack pnpm@9 args), a verb's launcher's global options read before its verb. A global option LAUNCHERS does not list may take a
    value (npm --loglevel silent exec): a word that follows an option and is not the verb is read as its value."""
    if prog not in LAUNCHERS:
        return None
    i = 0
    if prog in LAUNCH_VERBS:
        i = _past_options(prog, args, 0)
        while 0 < i < len(args) and args[i] not in LAUNCH_VERBS[prog] and args[i - 1].startswith("-") \
                and "=" not in args[i - 1] and args[i - 1] != "--":
            i = _past_options(prog, args, i + 1)
        if i >= len(args) or args[i] not in LAUNCH_VERBS[prog]:
            return None
        i += 2 if prog == "uv" and args[i:i + 2] == ["tool", "run"] else 1
    i = _past_options(prog, args, i) + (LAUNCHERS[prog][2] if prog == "chroot" else 0)
    if prog == "corepack":   # corepack pnpm@9 dlx ...: the package manager it names, never its own verbs (enable, up)
        run = COREPACK_RUNS.get(args[i].split("@", 1)[0].lower()) if i < len(args) else None
        return [run, *args[i + 1:]] if run else None
    return args[i:] or None


def _launched_text(prog: str, args: list[str]) -> tuple[str, str] | None:
    """(the command text a program runs, the shell that reads it) for eval, su -c, runas and ansible's -a."""
    if prog == "eval" and args:
        return " ".join(args), "bash"
    if prog == "su" and "-c" in args[:-1]:
        return args[args.index("-c") + 1], "bash"
    if prog == "runas":
        pos = [a for a in args if not a.startswith("/")]
        return (pos[-1], "ps") if pos else None
    if prog == "ansible":
        mod = next((args[i + 1] for i, a in enumerate(args[:-1]) if a in ("-m", "--module-name")), "")
        cmd = next((args[i + 1] for i, a in enumerate(args[:-1]) if a in ("-a", "--args")), "")
        if cmd and mod.rsplit(".", 1)[-1] in ("shell", "command", "raw", "win_shell", "win_command"):
            return cmd, "ssh"
    return None


STDIN_PATHS = ("-", "/dev/stdin", "/dev/fd/0", "/proc/self/fd/0")   # a script "named" that is stdin
BASH_VALUES = ("--rcfile", "--init-file")   # bash's long options that take the next word (its short ones: o, O)


def _bash_words(args: list[str]) -> tuple[list[str], list[str]]:
    """(options, operands) of a bash-family shell's ``args``: its options up to the first operand (the script, or -),
    the values of -o, +o, -O, +O, --rcfile and --init-file skipped; a short cluster takes one value word for each o
    or O it holds, wherever the letter sits (-eo pipefail, -oe pipefail, -oO pipefail extglob), as bash reads it; what
    follows the script is the script's."""
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            return args[:i], args[i + 1:]
        if a == "-" or not a.startswith(("-", "+")):
            break
        values = int(a in BASH_VALUES) if a.startswith("--") else a.count("o") + a.count("O")
        i += 1 + values
    return args[:i], args[i:]


def _bash_short(opts: list[str], letter: str) -> bool:
    """Whether bash's short option ``letter`` (c, s) is among ``opts``, alone or in a cluster (-ec, -xs)."""
    return any(o.startswith("-") and not o.startswith("--") and letter in o[1:] for o in opts)


def _bash_reads_stdin(prog: str, args: list[str]) -> bool:
    """Whether a bash-family shell, or source and . (bash 3.2's way to run a here-string: source /dev/stdin), reads
    its commands from stdin: no script named, -, /dev/stdin or /dev/fd/0 named, or -s; never with -c. An option's
    value (bash -o pipefail, --rcfile FILE) is no script."""
    if prog in ("source", "."):
        return bool(args[:1]) and args[0] in STDIN_PATHS
    opts, pos = _bash_words(args)
    return (not pos or pos[0] in STDIN_PATHS or _bash_short(opts, "s")) and not _bash_short(opts, "c")


def _reads_stdin(prog: str, args: list[str], shell: str) -> str | None:
    """The shell that reads commands from stdin when ``prog`` is one with no command of its own (bash, bash -s, bash
    /dev/stdin, source /dev/stdin, ssh host, pwsh -Command -, cmd, iex with pipeline input), else None."""
    if prog in ("ssh", "plink"):
        remote = _ssh_remote(args)
        if remote is None:
            return "ssh" if any(not a.startswith("-") for a in args) else None
        inner = calls(" ".join(remote), ".")
        words = _unwrap(inner[0][0]) if inner else []
        return "ssh" if words and _reads_stdin(_prog(words[0]), words[1:], "ssh") else None
    if prog in ("iex", "invoke-expression") and shell == "ps":
        return "ps" if not [a for a in args if not a.lower().startswith("-c")] else None
    sub = SHELLS.get(prog)
    if sub == "bash" or (prog in ("source", ".") and shell != "ps"):
        return "bash" if _bash_reads_stdin(prog, args) else None
    if sub == "ps":
        low = [a.lower() for a in args]
        if any(a in ("-command", "-c", "-file", "-f") and low[i + 1:i + 2] == ["-"] for i, a in enumerate(low)):
            return "ps"
        if _pwsh_file(args) or _pwsh_command(args, ".")[0] is not None:
            return None
        return "ps"
    if sub == "cmd":
        return None if any(a.lower().lstrip("/") in ("c", "k") for a in args) else "ps"
    return None


def _heredocs(command: str) -> list[str]:
    """The bodies of the bash heredocs of ``command`` (segments drops them)."""
    out = []
    for m in re.finditer(r"<<-?\s*(['\"]?)([\w.\-]+)\1[^\n]*\n", command):
        end = re.compile(r"^[ \t]*" + re.escape(m[2]) + r"[ \t]*\r?$", re.M).search(command, m.end())
        out.append(command[m.end():end.start() if end else len(command)])
    return out


def actions(cmds: list[tuple[list[str], str]], shell: str = "bash", top=None, depth: int = 0, command: str = ""):
    """(words, folder, shell, top) for each simple command of ``cmds`` and each one it runs in turn: past a wrapper
    (sudo, env, nohup, timeout, xargs, gsudo, doas) and a launcher (wsl, chroot, nsenter, uv run, npx, eval, su -c,
    runas, ansible -a), PowerShell's . and &, inside bash -c, pwsh -Command, -EncodedCommand and -File, cmd /c, iex,
    Start-Process, start, ssh's remote command (shell "ssh", read as bash), and, given the call's whole ``command``,
    what it feeds a shell that reads stdin (a heredoc, a here-string, echo's words, a lone PowerShell string piped to
    iex). ``top`` is the (words, folder) of the outermost command that holds it: what the owner would run."""
    readers = []
    for words, d in cmds:
        if words[0].startswith(REDIRECT):
            continue
        t = top or (words, d)
        words = _unwrap(words)
        while words and words[0] in (".", "&"):
            words = words[1:]
        if not words:
            continue
        yield words, d, shell, t
        prog, args = _prog(words[0]), words[1:]
        if depth > 4:
            continue
        nested = _nested(prog, args, d, "bash" if shell == "ssh" else shell)
        if nested and nested[0]:
            inner, sub, folder = nested
            yield from actions(calls(inner, folder, sub != "bash"), sub, t, depth + 1)
        elif run := _launched(prog, args, shell) or _launcher(prog, args):
            yield from actions([(run, d)], shell, t, depth + 1)
        elif text := _launched_text(prog, args):
            yield from actions(calls(text[0], d, text[1] == "ps"), text[1], t, depth + 1)
        elif prog in ("ssh", "plink") and (remote := _ssh_remote(args)):
            yield from actions(calls(" ".join(remote), d), "ssh", t, depth + 1)
        if "<<<" in args:   # bash <<< 'cmd': the here-string is stdin, not an argument
            k = args.index("<<<")
            args = args[:k] + args[k + 2:]
        reader = _reads_stdin(prog, args, "ssh" if shell == "ssh" else shell)
        if reader:
            readers.append(("ssh" if shell == "ssh" else reader, d, t))
    if not (command and readers and depth == 0):
        return
    fed = _heredocs(command)
    for words, _ in cmds:
        if "<<<" in words[:-1]:
            fed.append(words[words.index("<<<") + 1])
        if _prog(words[0]) in STDIN_FEEDERS:
            fed.append(" ".join(a for a in words[1:] if not a.startswith("-")))
        elif len(words) == 1 and re.search(r"\s", words[0]):   # "Restart-Computer -Force" | iex
            fed.append(words[0])
    for sub, d, t in readers:
        for text in fed:
            yield from actions(calls(text, d, sub == "ps"), sub, t, depth + 1)


def _has(args: list[str], *flags: str) -> bool:
    return any(a == f or a.startswith(f + "=") for a in args for f in flags)


def _first(args: list[str], values=()) -> list[str]:
    """The positionals of ``args``, the value of an option of ``values`` skipped."""
    out, i = [], 0
    while i < len(args):
        if args[i] in values:
            i += 1
        elif not args[i].startswith("-"):
            out.append(args[i])
        i += 1
    return out


def _text(words: list[str]) -> str:
    return " ".join(words)


# --- the actions only the owner takes (the never-grantable categories of permissions.yaml) --------------------------

# How the commands of each category look, by category name; a category permissions.yaml declares and no classifier
# knows (money, legal) is guarded by its deny rules alone. The list itself is brain.permissions' (NEVER, never:).
VISIBILITY = re.compile(r"(?i)\bprivate[\"']?\s*[:=]\s*[\"']?\$?(?:false|0)\b|"
                        r"\bvisibility[\"']?\s*[:=]\s*[\"']?(?:public|internal)\b")
SECRETS_API = re.compile(r"(?i)(?:^|/)(?:actions|dependabot|codespaces|agents)/secrets/|/environments/[^/]+/secrets/")
HTTP = {"curl", "wget", "http", "https", "xh", "iwr", "irm", "invoke-webrequest", "invoke-restmethod"}
# Programs whose arguments are text to search or print, not flags of a command that runs (grep -- --arm).
TEXT_TOOLS = {"grep", "egrep", "fgrep", "rg", "ag", "ack", "git", "findstr", "select-string", "sls", "echo", "printf",
              "write-output", "write-host", "sed", "awk", "cat", "less", "head", "tail", "brain"}
GH_API_VALUES = {"-X", "--method", "-f", "--raw-field", "-F", "--field", "-H", "--header", "--input", "-q", "--jq",
                 "-t", "--template", "--cache", "-p", "--preview", "--hostname"}
PS_OWNER = {**dict.fromkeys(("register-scheduledtask", "set-scheduledtask", "unregister-scheduledtask",
                             "enable-scheduledtask", "disable-scheduledtask", "register-scheduledjob",
                             "set-scheduledjob", "unregister-scheduledjob", "new-service", "set-service",
                             "remove-service"), "scheduled"),
            **dict.fromkeys(("set-secret", "remove-secret", "register-secretvault", "unregister-secretvault",
                             "set-secretstorepassword", "reset-secretstore", "new-storedcredential",
                             "remove-storedcredential"), "keys"),
            **dict.fromkeys(("new-localuser", "set-localuser", "remove-localuser", "rename-localuser",
                             "enable-localuser", "disable-localuser", "add-localgroupmember",
                             "remove-localgroupmember"), "accounts")}
ACCOUNT_PROGRAMS = {"useradd", "usermod", "userdel", "passwd", "chpasswd", "chage", "groupadd", "groupmod", "groupdel",
                    "gpasswd"}
# program -> (category, the first positionals that make a call one: a word, or a tuple of words)
SUBCOMMANDS = {
    "docker": [("accounts", {"login", "logout"}), ("keys", {("secret", "create"), ("secret", "rm")})],
    "npm": [("accounts", {"login", "logout", "adduser"}), ("keys", {("token", "create")})],
    "pnpm": [("accounts", {"login", "logout", "adduser"})], "yarn": [("accounts", {"login", "logout"})],
    "az": [("accounts", {"login", "logout"})],
    "gcloud": [("accounts", {("auth", "login"), ("auth", "revoke"), ("auth", "activate-service-account"),
                             ("auth", "application-default", "login"), ("auth", "application-default", "revoke")})],
    "aws": [("accounts", {"configure", ("sso", "login")})],
    "argocd": [("accounts", {"login", "relogin", "logout"}),
               ("keys", {("account", "generate-token"), ("account", "update-password"), ("account", "delete-token")})],
    "nssm": [("scheduled", {"install", "set", "remove", "reset", "edit"})],
    "launchctl": [("scheduled", {"load", "bootstrap", "enable", "submit", "unload", "bootout", "disable"})],
    "security": [("keys", {"add-generic-password", "add-internet-password", "delete-generic-password",
                           "delete-internet-password", "import", "create-keychain", "delete-keychain",
                           "set-keychain-password"})],
    "secret-tool": [("keys", {"store", "clear"})],
    "k3s": [("keys", {("token", "create"), ("token", "rotate")})],
}
# Their global options that take a value (docker -H ssh://build-host login): skipped before the subcommand.
SUB_VALUES = {"docker": ("-H", "--host", "-c", "--context", "--config", "-l", "--log-level", "--tlscacert",
                         "--tlscert", "--tlskey"),
              "gcloud": ("--project", "--account", "--configuration", "--verbosity", "--impersonate-service-account"),
              "aws": ("--profile", "--region", "--output", "--endpoint-url", "--query"),
              "az": ("--subscription", "-o", "--output", "--query"),
              "npm": ("--prefix", "--registry", "--userconfig", "-w", "--workspace"), "pnpm": ("-C", "--dir"),
              "argocd": ("--server", "--auth-token", "--config", "--context", "--grpc-web-root-path", "-H",
                         "--header")}
KEYS_API = re.compile(r"(?i)(?:^|/)(?:user/(?:keys|gpg_keys|ssh_signing_keys)|repos/[^/]+/[^/]+/keys)(?:/|$)")
ACCOUNTS_API = re.compile(r"(?i)/collaborators/|(?:^|/)orgs/[^/]+/(?:members|memberships|outside_collaborators)/|"
                          r"(?:^|/)user/emails")
GPG_SECRET = re.compile(r"^--(?:export-secret|delete-secret|gen-key|generate-key|full-gen|full-generate|quick-gen|"
                        r"quick-generate|quick-add-key|add-key|change-passphrase|passwd)")
SYSTEMCTL_SCHEDULED = {"enable", "disable", "reenable", "link", "edit", "preset", "preset-all", "mask", "unmask",
                       "set-property", "revert", "add-wants", "add-requires"}
SC_SCHEDULED = {"create", "config", "delete", "failure", "failureflag", "sidtype", "privs", "managedaccount",
                "triggerinfo"}
RUN_KEY = re.compile(r"(?i)[\\/](?:Microsoft[\\/]Windows[\\/]CurrentVersion[\\/]Run(?:Once|Services(?:Once)?)?|"
                     r"Winlogon)(?:[\\/]|$|['\"])")
# Where a written file starts something on its own, from the root of a drive (cron, systemd and init folders, launchd,
# the all-users Startup folder) or of the user's home (systemd --user, XDG autostart, LaunchAgents, Startup); a repo's
# deploy/etc/systemd/system is not one.
AUTOSTART_ROOT = re.compile(r"(?i)^(?:[a-z]:)?/(?:etc/(?:cron[\w.]*|anacrontab|systemd/system|init\.d|rc\.local)|"
                            r"var/spool/cron|(?:usr/)?lib/systemd/system|library/launch(?:agents|daemons)|"
                            r"programdata/microsoft/windows/start menu/programs/startup)(?:/|$)")
AUTOSTART_HOME = re.compile(r"(?i)^/(?:\.config/(?:systemd/user|autostart)|library/launchagents|"
                            r"appdata/roaming/microsoft/windows/start menu/programs/startup)(?:/|$)")
# The files that would set the guards' override for the next sessions: Claude Code's settings, shell profiles.
OVERRIDE_FILES = re.compile(r"(?i)(?:^|[\\/])(?:\.claude[\\/]settings(?:\.local)?\.json|managed-settings\.json|"
                            r"\.(?:bashrc|bash_profile|bash_login|profile|zshrc|zprofile|zshenv)|"
                            r"(?:microsoft\.[\w.]+_)?profile\.ps1)$")
PERSIST_ENV = re.compile(r"(?i)SetEnvironmentVariable|\\Environment\b")   # .NET's call, the registry's key
OVERRIDE_HINT = re.compile(r"(?i)settings(?:\.local)?\.json|\.(?:bashrc|bash_profile|profile|zshrc|zprofile)\b|"
                           r"profile\.ps1")   # what inline code names when it writes one of OVERRIDE_FILES
INSTALL_APPLY = re.compile(r"(?i)^[-–—]a(?:p(?:p(?:l(?:y)?)?)?)?(?::\$?(?:true|1))?$")   # PowerShell takes – and —
SCHEDULED_TOOL = re.compile(r"^mcp__.*scheduled[-_]?tasks?__(?:create|update)_scheduled_task$")
# The desktop app's tools that change a session's Remote Control or permission mode, under any MCP prefix, and its
# settings tool for a key of either (connect_new_sessions_to_remote_control): security-settings, the owner's alone,
# but Remote Control's three exceptions (remote_control).
SESSION_SETTINGS_TOOL = re.compile(r"^mcp__.+__(?:set_remote_control|set_session_permission_mode)$")
SETTINGS_TOOL = re.compile(r"^mcp__.+__set_setting$")
SECURITY_KEY = re.compile(r"remote[_-]?control|permission", re.I)
# The desktop app's tool that types a command into the owner's Terminal panel: judged as a shell call, PowerShell on
# Windows (the panel's shell there), else bash (an SSH host's login shell), in its cwd or the session's.
TERMINAL_TOOL = re.compile(r"^mcp__.*terminal__run_in_terminal$")
UNLIFTED = {"security-settings"}   # the owner guard's checks BRAIN_GUARD_ALLOW cannot lift, not even with all


def _autostart(path) -> bool:
    """Whether a written ``path`` starts a program on its own (AUTOSTART_ROOT, or AUTOSTART_HOME under the home)."""
    p = str(path).replace("\\", "/")
    home = os.path.expanduser("~").replace("\\", "/").rstrip("/")
    if AUTOSTART_ROOT.match(p):
        return True
    return bool(home) and os.path.normcase(p).startswith(os.path.normcase(home + "/")) and \
        bool(AUTOSTART_HOME.match(p[len(home):]))


def owner_categories() -> dict[str, dict]:
    """The never-grantable categories, name -> {why, deny}: brain.permissions' (the engine's NEVER extended by
    permissions.yaml's never:), kept as JSON in <BRAIN_HOME>/cache/never.json while permissions.yaml and
    brain/permissions.py keep their mtime and size (PyYAML costs a hook ~25 ms, JSON ~1)."""
    from . import permissions
    f = permissions.permissions_file()
    key = [str(f)]
    for p in (f, permissions.__file__):
        try:
            st = os.stat(p) if p else None
            key += [st.st_mtime_ns, st.st_size] if st else [None, None]
        except OSError:
            key += [None, None]
    cache = paths.brain_home() / "cache" / "never.json"
    try:
        kept = json.loads(cache.read_text(encoding="utf-8"))
        if kept.get("key") == key and isinstance(kept.get("categories"), dict):
            return kept["categories"]
    except (OSError, ValueError, AttributeError):
        pass
    cats = {c.name: {"why": c.why, "deny": list(c.deny)} for c in permissions.default_categories()}
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"key": key, "categories": cats}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return cats


def _gh(args: list[str], words: list[str], command: str, cwd: str) -> tuple[str, str] | None:
    group, verb = (_first(args, ("-R", "--repo", "--hostname")) + ["", ""])[:2]
    if group == "repo" and verb == "create" and _has(args, "--public"):
        return "visibility", "gh repo create --public"
    if group == "repo" and verb == "edit" and _has(args, "--visibility"):
        return "visibility", "gh repo edit --visibility"
    if group == "gist" and verb == "create" and (_has(args, "--public") or "-p" in args):
        return "visibility", "gh gist create --public"
    if group == "secret" and verb in ("set", "delete", "remove"):
        return "keys", f"gh secret {verb}"
    if group in ("ssh-key", "gpg-key") and verb in ("add", "delete"):
        return "keys", f"gh {group} {verb}"
    if group == "repo" and verb == "deploy-key" and set(args) & {"add", "delete"}:
        return "keys", "gh repo deploy-key"
    if group == "auth" and verb == "token":
        return "keys", "gh auth token (it prints the token)"
    if group == "auth" and verb in ("login", "logout", "refresh", "switch"):
        return "accounts", f"gh auth {verb}"
    if group != "api":
        return None
    method, bodies, endpoint, i = "", [], "", 0
    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            name, eq, val = a.partition("=")
        elif len(a) > 2 and a[:2] in GH_API_VALUES:
            name, eq, val = a[:2], "=", a[2:]
        else:
            name, eq, val = a, "", ""
        if name in GH_API_VALUES:
            if not eq:
                i, val = i + 1, (args[i + 1] if i + 1 < len(args) else "")
            if name in ("-X", "--method"):
                method = val.upper()
            elif name in ("-f", "--raw-field", "-F", "--field"):
                bodies.append(val)
            elif name == "--input":
                bodies.append(command if val == "-" else _read_file(val, cwd))
        elif a != "api" and not a.startswith("-") and not endpoint:
            endpoint = a
        i += 1
    method = method or ("POST" if bodies else "GET")
    if method == "GET":
        return None
    return _github_write(f"gh api {method}", method, endpoint, bodies)


def _github_write(what: str, method: str, endpoint: str, bodies: list[str]) -> tuple[str, str] | None:
    """(category, what) of a write to GitHub's REST or GraphQL API that only the owner makes: a secret, a key, a
    collaborator or a member, a repository made public."""
    if SECRETS_API.search(endpoint) or KEYS_API.search(endpoint):
        return "keys", f"{what} {endpoint}"
    if ACCOUNTS_API.search(endpoint):
        return "accounts", f"{what} {endpoint}"
    if any(VISIBILITY.search(b) for b in bodies):
        return "visibility", f"{what} {endpoint} (a repository's visibility)"
    return None


def _http(prog: str, args: list[str], words: list[str], command: str, shell: str) -> tuple[str, str] | None:
    """A REST call to GitHub's API (curl, Invoke-RestMethod...) that _github_write refuses."""
    urls = [a for a in args if "api.github.com" in a or "/api/v3/" in a]
    if not urls:
        return None
    text = _text(args)
    m = re.search(r"(?:^|\s)(?:-[A-Za-z]*X\s*|--request[\s=]+)([A-Za-z]+)", text) or \
        re.search(r"(?i)(?:^|\s)-method[\s:=]+([A-Za-z]+)", text)
    method = m[1].upper() if m else "GET"
    stdin = any(a in ("@-", "-") or a.endswith("@-") for a in args)
    body = command if stdin or shell == "ps" else _text(words)   # PowerShell's -Body @{...} is segments of its own
    sends = method != "GET" or re.search(r"(?i)(?:^|\s)(?:-d|--data[\w-]*|--json|-body|-F|--form)(?:\s|=|$)", text)
    if not sends:
        return None
    return _github_write(f"{prog} {method}", method, re.sub(r"^\w+://[^/]+/(?:api/v3/)?", "", urls[0]), [body])


def _subcommand(prog: str, args: list[str]) -> tuple[str, str] | None:
    pos = _first(args, SUB_VALUES.get(prog, ()))
    for category, subs in SUBCOMMANDS.get(prog, ()):
        for sub in subs:
            sub = (sub,) if isinstance(sub, str) else sub
            if tuple(pos[:len(sub)]) == sub:
                return category, f"{prog} {' '.join(sub)}"
    return None


def _owner_command(words: list[str], cwd: str, shell: str, command: str) -> tuple[str, str] | None:
    """(category, what) when the simple command ``words`` is one of the never-grantable categories' commands."""
    name = re.split(r"[\\/]", words[0])[-1].lower()
    prog, args = _prog(words[0]), words[1:]
    low = [a.lower() for a in args]
    if name == "install.ps1" and any(INSTALL_APPLY.match(a) for a in args):
        return "installer", "install.ps1 -Apply"
    if prog not in TEXT_TOOLS and any(a == "--arm" or a.startswith("--arm=") for a in args):
        return "arming", f"{prog} --arm"
    if prog in PS_OWNER:
        return PS_OWNER[prog], words[0]
    if prog in ACCOUNT_PROGRAMS:
        return "accounts", prog
    if prog == "gh":
        return _gh(args, words, command, cwd)
    if prog in HTTP:
        return _http(prog, args, words, command, shell)
    if prog == "schtasks" and set(low) & {"/create", "/change", "/delete", "-create", "-change", "-delete"}:
        return "scheduled", f"schtasks {next(a for a in low if a.lstrip('/-') in ('create', 'change', 'delete'))}"
    if prog == "sc" and (shell != "ps" or name == "sc.exe"):
        pos = [a for a in low if not a.startswith("\\\\")]
        return ("scheduled", f"sc {pos[0]}") if pos[:1] and pos[0] in SC_SCHEDULED else None
    if prog == "crontab" and not ("-l" in args and not set(args) & {"-e", "-r", "-i", "-"}):
        return "scheduled", "crontab (it installs or edits a crontab)"
    if prog in ("at", "batch", "atrm") and not set(args) & {"-l", "-V", "--help"}:
        return "scheduled", prog
    if prog == "systemctl":
        verb = (_first(args, ("-H", "--host", "-M", "--machine", "-t", "--type", "-p", "--property", "-o",
                              "--output", "-n", "--lines", "--root", "--signal", "-s", "--state")) or [""])[0]
        return ("scheduled", f"systemctl {verb}") if verb in SYSTEMCTL_SCHEDULED else None
    if prog == "systemd-run" and any(a.startswith(("--on-", "--timer-property")) for a in args):
        return "scheduled", "systemd-run with a timer"
    if prog == "reg" and low[:1] == ["add"] and any(RUN_KEY.search(a) for a in args):
        return "scheduled", "reg add of a Run key"
    if prog == "reg" and low[:1] == ["import"]:   # a .reg file sets what it holds: a Run key, or what is not read
        text = _read_file(args[1], cwd) if len(args) > 1 and shell != "ssh" else ""
        if not text or RUN_KEY.search(text) or PERSIST_ENV.search(text):
            return "scheduled", "reg import (a Run key, or a file the guard cannot read)"
    if prog == "aws" and _first(args, SUB_VALUES["aws"])[:2] in (["configure", "list"], ["configure", "get"],
                                                                 ["configure", "list-profiles"]):
        return None
    if prog in ("npm", "pnpm", "yarn") and _first(args)[:2] == ["config", "set"] and \
            re.search(r"(?i)_auth|authtoken|_password", _text(args)):
        return "keys", f"{prog} config set (a registry token)"
    if prog in ("new-itemproperty", "set-itemproperty", "sp", "new-item", "ni") and any(RUN_KEY.search(a)
                                                                                       for a in args):
        return "scheduled", f"{words[0]} of a Run key"
    if prog == "cmdkey" and any(a.startswith(("/add", "/generic", "/delete", "-add", "-generic", "-delete"))
                                for a in low):
        return "keys", "cmdkey (a stored credential)"
    if prog == "ssh-keygen":
        flags = {c for a in args if a.startswith("-") and not a.startswith("--") for c in a[1:]}
        reads = flags & set("lFBQyRH") or ("Y" in flags and set(args) & {"verify", "check-novalidate",
                                                                         "find-principals", "match-principals"})
        return None if reads else ("keys", "ssh-keygen (it creates or changes a key)")
    if prog == "age-keygen" and not set(args) & {"-y", "--version", "-h", "--help"}:
        return "keys", "age-keygen"
    if prog in ("gpg", "gpg2") and any(GPG_SECRET.match(a) for a in args):
        home = next((args[i + 1] for i, a in enumerate(args[:-1]) if a == "--homedir"),
                    next((a.partition("=")[2] for a in args if a.startswith("--homedir=")), ""))
        mine = {os.path.normcase(os.path.expanduser("~/.gnupg")),
                os.path.normcase(os.path.join(os.environ.get("APPDATA", "~"), "gnupg"))}
        if home and shell != "ssh" and os.path.normcase(_path(home, cwd)) not in mine:
            return None   # a throwaway keyring (--homedir elsewhere): not the owner's keys
        return "keys", f"gpg {next(a for a in args if GPG_SECRET.match(a))}"
    if prog == "net" and low[:1] in (["user"], ["localgroup"]):
        changes = any(a.startswith("/") and not a.startswith("/domain") for a in low[1:]) or \
            (low[0] == "user" and len(_first(args[1:])) >= 2)
        return ("accounts", f"net {low[0]}") if changes else None
    if prog in KUBECTL or (prog in ("k3s", "microk8s") and args[:1] == ["kubectl"]):
        args = args[1:] if prog in ("k3s", "microk8s") else args
        verb, pos, opts = _kube(args)
        if verb == "create" and pos[:1] in (["secret"], ["token"]):
            return "keys", f"kubectl create {pos[0]}"
        files = opts.get("-f", []) + opts.get("--filename", [])
        if verb in K_WRITES and files:
            objs, _ = _manifests(files, cwd, shell, "-R" in opts or "--recursive" in opts)
            if any(str(o.get("kind")) == "Secret" for o in objs):
                return "keys", f"kubectl {verb} of a Secret"
        return None
    if (prog == "brain" or "brain" in low[1:3]) and "--apply" in low and             any(x == "schedule" and y == "install" for x, y in zip(low, low[1:])):
        return "scheduled", "brain schedule install --apply (it creates, changes or removes scheduled tasks)"
    return _subcommand(prog, args)


def _deny_rules(words: list[str], cats: dict[str, dict]) -> tuple[str, str] | None:
    """(category, what) when a category's deny rule (Claude Code's syntax) matches the simple command ``words``, its
    program read as written and by name (gh.exe as gh); brain.permissions matches it, imported only for a rule whose
    program is this one."""
    names = {words[0].lower(), _prog(words[0])}
    texts = {_text(words), _text([_prog(words[0]), *words[1:]])}
    for name, c in cats.items():
        for rule in c.get("deny") or []:
            m = re.match(r"^\w+\(\s*(\S+)", rule)
            if m and "*" not in m[1] and m[1].lower() not in names and _prog(m[1]) not in names:
                continue
            from . import permissions
            for atom in permissions.atoms(rule):
                p = permissions.parse(atom)
                if p and p[0] in permissions.SHELLS and any(permissions.matches(atom, p[0], t) for t in texts):
                    return name, f"{_text(words)[:80]} (deny rule {rule})"
    return None


def _override(command: str, cmds, shell: str) -> str | None:
    """What sets the guards' override for later sessions: setx or a registry Environment key, a write into Claude
    Code's settings or a shell profile, or a write whose target the guard cannot resolve ($PROFILE, a path the code
    computes), with BRAIN_GUARD_ALLOW in the command."""
    if not re.search(ALLOW_ENV, command, re.I):
        return None
    for words, d, _, _ in actions(cmds, shell, command=command):
        prog, text = _prog(words[0]), _text(words)
        if (prog == "setx" and re.search(ALLOW_ENV, text, re.I)) or PERSIST_ENV.search(words[0]) or \
                (prog in ("set-itemproperty", "new-itemproperty", "sp", "reg") and PERSIST_ENV.search(text)
                 and re.search(ALLOW_ENV, text, re.I)):
            return f"setting {ALLOW_ENV} in the user's environment"
        lang = "python" if re.fullmatch(r"python[\d.]*w?|py", prog) else prog
        code = _inline(words[1:], *INLINE[lang][:2]) if lang in INLINE else []
        if code and re.search(ALLOW_ENV, code[0], re.I) and OVERRIDE_HINT.search(code[0]) and \
                _code_targets(lang, code, d):   # it writes, and names a settings file or a profile
            return f"inline code writing {ALLOW_ENV} into Claude Code's settings or a shell profile"
    for _, target in shell_writes(cmds, shell):
        if OVERRIDE_FILES.search(str(target)) or isinstance(target, Unresolved):
            where = f"{target.what} (read as its folder {target})" if isinstance(target, Unresolved) else target
            return f"writing {ALLOW_ENV} into {where}"
    return None


def session_setting(tool: str, inp: dict) -> bool:
    """Whether a tool call changes a session's Remote Control or permission mode (SESSION_SETTINGS_TOOL), or sets one
    of the app's settings that does (SETTINGS_TOOL with a SECURITY_KEY key)."""
    return bool(SESSION_SETTINGS_TOOL.match(tool) or (SETTINGS_TOOL.match(tool) and isinstance(inp, dict)
                                                     and SECURITY_KEY.search(str(inp.get("key") or ""))))


def check_session_settings(tool: str, inp: dict, cwd: str):
    """(category, reason, request) for a call that changes a session's security settings (wi-brain-guard-session-
    settings): refused to every session, whatever the value (on or off, a higher or a lower mode), and put to the owner
    as an action; the category is security-settings, which the override does not lift (UNLIFTED)."""
    args = {k: v for k, v in (inp or {}).items() if not str(k).startswith("_")}   # _consent is the app's
    what = f"{tool.rsplit('__', 1)[-1]} " + " ".join(f"{k}={json.dumps(v, ensure_ascii=False)}"
                                                       for k, v in sorted(args.items()))
    req = {"ref": _ref(f"{tool}\0{json.dumps(args, sort_keys=True)}"), "category": "security-settings",
           "what": what.strip()[:300], "command": None, "cwd": cwd, "shell": None}
    why = (owner_categories().get("security-settings") or {}).get("why") or         "a session's Remote Control and permission mode are switched in the app, by its owner"
    return "security-settings", (f"{tool} refused: security-settings is {config.owner_of()}'s alone "
                                 f"({why.rstrip('.')}); they switch it in the app"), req


# Remote Control's three exceptions (wi-brain-guard-rc-archive; the owner's ADRs of 2026-11-04 on archiving and on
# the coordinators' handover). A coordinator is marked by the name the session that started it gave it (the app's
# spawnedFrom.name, fixed at the start), never by its title, which a session can change.
RC_TOOL = re.compile(r"^mcp__ccd_session_mgmt__set_remote_control$")   # the desktop app's own server only
COORDINATOR_NAME = re.compile(r"(?i)^(?:coordinat(?:or|eur)-[a-z0-9]{1,3}|coordination-du-brain(?:-[a-z0-9-]*)?)$")
COORDINATOR_TITLE = re.compile(r"(?i)^\s*(?:coordination du brain|brain coordinat(?:ion|or))\b")   # refusals only
HANDOVER_DIR = "handover"    # <BRAIN_HOME>/handover/: the coordinators' hand-over notes (*.md)
HANDOVER_NOTE_S = 6 * 3600   # a hand-over note counts this long after it was last written
HANDOVER_HEAD = 2000         # the note's opening, whose first app id says whose note it is
HANDOVER_MAX = 512_000       # a bigger file is not read
LOCAL_ID = re.compile(r"(?<![\w-])local_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![\w-])")
RC_FINISHED = ("idle", "ended")   # the states of a finished session (brain.sessions.state_of)
RC_LIVE = ("running", "idle", "asking", "stale")   # a successor's: not archived, ended or unknown on this machine
# A successor with no transcript yet (unknown) counts as starting this long after its app file's createdAt: the
# outgoing coordinator turns its Remote Control on seconds after start_session, before its first turn is written.
HANDOVER_START_S = 10 * 60


def _created_age(node: dict, now: float | None = None) -> float | None:
    """Seconds since a session was created by its app file's ``createdAt`` (milliseconds, sessions.APP_KEYS'
    ``created``), never the ledger's; None when it is missing or not a finite positive number."""
    import math
    import time
    created = node.get("created")
    if not isinstance(created, (int, float)) or isinstance(created, bool) or not math.isfinite(created) or \
            created <= 0:
        return None
    return (time.time() if now is None else now) - created / 1000


def _coordinator(node: dict, titles: bool = False) -> bool:
    """Whether a session is a Brain coordinator by its name (given by the session that started it); ``titles`` also
    takes its title, for a refusal only (a live coordinator keeps its Remote Control)."""
    return bool(COORDINATOR_NAME.fullmatch(str(node.get("name") or "")) or
                titles and COORDINATOR_TITLE.match(str(node.get("title") or "")))


def handover_note(host_id: str, now: float | None = None) -> Path | None:
    """The session's hand-over note: a ``*.md`` (a regular file, no link) in <BRAIN_HOME>/handover/ written in the
    last HANDOVER_NOTE_S whose first app id, in its opening (HANDOVER_HEAD characters), is the session's; None
    without one. A note that names it after another id (its successor's, which names its predecessor) is not its own."""
    import stat
    import time

    from . import sessions
    if not sessions.HOST_RE.match(host_id or ""):
        return None
    now = time.time() if now is None else now
    d = paths.brain_home() / HANDOVER_DIR
    try:
        files = [(f, f.lstat()) for f in d.glob("*.md")]
    except OSError:
        return None
    for f, st in sorted(files, key=lambda x: -x[1].st_mtime):
        if not stat.S_ISREG(st.st_mode) or not (0 <= now - st.st_mtime <= HANDOVER_NOTE_S) or \
                st.st_size > HANDOVER_MAX:
            continue
        try:
            first = LOCAL_ID.search(f.read_text(encoding="utf-8", errors="replace")[:HANDOVER_HEAD])
        except OSError:
            continue
        if first and first.group(0) == host_id:
            return f
    return None


def remote_control(payload: dict, now: float | None = None) -> tuple[str | None, str]:
    """(case, why) for a set_remote_control call: ``archive`` (off on a finished session the caller started),
    ``handover-on`` (on for the coordinator the caller started to succeed it) or ``handover-off`` (off on the caller
    itself at that handover, its successor detached), else None and why it is none of them. Read at zero token from
    the desktop app's own session files (brain.sessions.app_index and app_meta: who started whom, the names,
    archived and detached flags, the creation time) and the hand-over notes, never from the ledger's SessionStart
    events or the brief hash, which any session can append to; what cannot be read is a refusal, never a guess.
    A successor counts when it is live (RC_LIVE) or starting: no transcript yet (unknown) but created by its own app
    file's createdAt in the last HANDOVER_START_S; an unknown one created earlier, or whose creation time cannot be
    read, does not."""
    from . import sessions
    inp = payload.get("tool_input") or {}
    enabled, target = inp.get("enabled"), inp.get("session_id")
    if not isinstance(enabled, bool) or not isinstance(target, str) or not target.strip():
        return None, "its session_id or enabled cannot be read"
    target = target.strip()
    index = sessions.app_index()
    if index is None:
        return None, "the desktop app's session files are not on this machine"
    sid = str(payload.get("session_id") or "")
    callers = [h for h, m in index.items() if sid and m.get("session") == sid]
    if len(callers) != 1:
        return None, "this session is not in the desktop app's session files"
    caller = callers[0]
    own = sessions.here()["host_id"]
    if own and own != caller:
        return None, "this session's app id and its transcript's disagree"
    dirs = sessions.app_dirs()

    def meta(host: str) -> dict:   # one session's own file, read again now (the index may be cached); one file only
        if host not in index or sum((d / f"{host}.json").is_file() for d in dirs) != 1:
            return {}
        m = sessions.app_meta(host)
        return {**m, "source": "app"} if m.get("host_id") == host else {}

    def mine(m: dict) -> bool:
        return bool(m) and m.get("parent") == caller

    def state(m: dict) -> str:
        return "archived" if m.get("archived") else sessions.state_of(m, {}, now)

    def successor_state(m: dict) -> tuple[str, str]:
        """(its state, or ``starting`` for an unknown one created in the last HANDOVER_START_S; what is known of an
        unknown one's start, '' otherwise)."""
        st = state(m)
        if st != "unknown":
            return st, ""
        age = _created_age(m, now)
        if age is None:
            return st, "no transcript yet and its creation time cannot be read"
        if not 0 <= age <= HANDOVER_START_S:
            return st, (f"no transcript yet and was created {int(age)} s ago, beyond the {HANDOVER_START_S // 60} min "
                        "a starting successor gets")
        return "starting", f"has no transcript yet and was created {int(age)} s ago"

    def live(m: dict) -> bool:
        return successor_state(m)[0] in RC_LIVE + ("starting",)

    me = meta(caller)
    if not me or me.get("session") != sid:
        return None, "this session's own app file cannot be read, or names another transcript"

    def handover() -> str:   # '' when the caller is a coordinator at its handover, else why not
        if not _coordinator(me):
            return "this session is not a Brain coordinator (the name its starter gave it)"
        if not me.get("parent") or not _coordinator(meta(str(me["parent"]))):
            return "this session was not started by a Brain coordinator (the name its starter gave it)"
        if handover_note(caller, now) is None:
            return (f"no hand-over note of {caller} (its first app id) in {HANDOVER_DIR}/ written in the last "
                    f"{HANDOVER_NOTE_S // 3600} h")
        return ""

    if target in ("self", caller):
        if enabled:
            return None, "a session never turns its own Remote Control on"
        why = handover()
        if why:
            return None, why

        def successor(m: dict) -> bool:
            return mine(m) and _coordinator(m) and m.get("detached") is True and live(m)
        succ = [h for h, m in sorted(index.items()) if m.get("parent") == caller and successor(meta(h))]
        if not succ:
            return None, "it has started no live coordinator to succeed it, detached"
        named = [f"{h} (starting: {why})" if st == "starting" else h
                 for h in succ for st, why in [successor_state(meta(h))]]
        return "handover-off", f"off on itself at its handover to {', '.join(named)}"
    node = meta(target) if sessions.HOST_RE.match(target) else {}
    if not node:
        return None, f"{json.dumps(target[:80], ensure_ascii=False)} is not in the desktop app's session files"
    if not mine(node):
        return None, f"{target} was not started by this session"
    st = state(node)
    if enabled:
        if not _coordinator(node):
            return None, f"{target} is not a Brain coordinator (the name this session gave it), so not a successor"
        why = handover()
        if why:
            return None, why
        sst, how = successor_state(node)
        if sst == "starting":
            return "handover-on", f"on for {target}, the coordinator it started to succeed it, which {how}"
        if sst not in RC_LIVE:
            return None, f"{target} is {sst}: {how}" if how else f"{target} is {sst}"
        return "handover-on", f"on for {target}, the coordinator it started to succeed it"
    if _coordinator(node, titles=True) and st not in ("archived", "ended"):
        return None, f"{target} is a live coordinator, which stays in Remote Control"
    if st not in RC_FINISHED:
        return None, f"{target} is {st}, not finished"
    return "archive", f"off on {target}, a finished session it started, before archiving it"


def _is_usage_allow(target) -> bool:
    """Whether ``target`` is the usage governor's override file (brain.governor.allow_file)."""
    from . import governor
    return os.path.normcase(os.path.abspath(str(target))) ==         os.path.normcase(os.path.abspath(str(governor.allow_file())))


def _usage_override(cmds, shell: str) -> str | None:
    """What lifts the usage governor for a session: brain usage allow (python -m brain too), or a shell write into its
    file."""
    for words, _, _, _ in actions(cmds, shell):
        low = [w.lower() for w in words]
        if (_prog(words[0]) == "brain" or "brain" in low[1:3]) and any(
                a == "usage" and b == "allow" for a, b in zip(low, low[1:])):
            return "brain usage allow"
    for what, target in shell_writes(cmds, shell):
        if not isinstance(target, Unresolved) and _is_usage_allow(target):
            return f"{what} into {target}"
    return None


def _request(category: str, what: str, top, shell: str, cwd: str = "") -> dict:
    """The action put to the owner: its category, what it is, and the exact command with its folder: the outermost
    command that holds it (``top``: words and folder), quoted for the session's shell, or the call's whole text."""
    if isinstance(top, str):
        command, cwd = top, cwd or os.getcwd()
    else:
        words, cwd = top
        command = _quote(words, shell)
    return {"ref": _ref(f"{shell}\0{cwd}\0{command}"), "category": category, "what": what, "command": command,
            "cwd": os.path.abspath(cwd), "shell": shell}


def _ref(key: str) -> str:
    """guard- and 10 hex digits of the action's SHA-1: the same action refused again keeps its ref."""
    import hashlib  # here, not at the top: it loads OpenSSL, ~10 ms of a hook that refuses nothing
    return "guard-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def _quote(words: list[str], shell: str) -> str:
    if shell == "powershell":
        return " ".join(w if re.fullmatch(r"[\w./:\\=+,@%-]+", w) else "'" + w.replace("'", "''") + "'"
                        for w in words)
    return shlex.join(words)


def check_owner(tool: str, inp: dict, cmds, cwd: str, powershell: bool = False, command: str = ""):
    """(category, reason, request) for a call that does what only the owner does, else None: a command of a
    never-grantable category, a file that starts something on its own (scheduled), the scheduled-tasks tools, or the
    guards' override set for later sessions (check override). The reasons name the owner (config.owner_of)."""
    shell = "powershell" if powershell else "bash"
    if tool in EDIT_TOOLS:
        target = _path(inp.get(EDIT_TOOLS[tool]) or "", cwd) if inp.get(EDIT_TOOLS[tool]) else ""
        text = "\n".join(str(t) for t in [inp.get("content"), inp.get("new_string"), inp.get("new_source"),
                                          *[e.get("new_string") for e in inp.get("edits") or []]] if t)
        if target and OVERRIDE_FILES.search(target) and re.search(ALLOW_ENV, text, re.I):
            return ("override", f"{tool} refused: it writes {ALLOW_ENV} into {target}; the override is "
                                f"{config.owner_of()}'s", None)
        if target and _is_usage_allow(target):
            return ("override", f"{tool} refused: {target} lifts the usage guard; brain usage allow is "
                                f"{config.owner_of()}'s, in their own terminal", None)
        if target and _autostart(target) and "scheduled" in owner_categories():
            req = {"ref": _ref(f"{tool}\0{target}"), "category": "scheduled", "what": f"{tool} {target}",
                   "command": None, "cwd": cwd, "shell": None}
            return "scheduled", (f"{tool} refused: {target} starts a program on its own (a new scheduled task or "
                                 f"service is {config.owner_of()}'s alone); write it elsewhere and ask them to "
                                 "install it"), req
        return None
    if SCHEDULED_TOOL.match(tool):
        what = f"{tool} {json.dumps(inp, ensure_ascii=False)[:300]}"
        req = {"ref": _ref(what), "category": "scheduled", "what": what, "command": None, "cwd": cwd, "shell": None}
        return "scheduled", f"{tool} refused: a new scheduled task is {config.owner_of()}'s alone", req
    if session_setting(tool, inp):
        return check_session_settings(tool, inp, cwd)
    if not cmds:
        return None
    sub = "ps" if powershell else "bash"
    what = _override(command, cmds, sub)
    if what:
        return ("override", f"{what} refused: the guards' override is {config.owner_of()}'s, set in Claude Code's "
                            "environment", None)
    what = _usage_override(cmds, sub)
    if what:
        return ("override", f"{what} refused: it lifts the usage guard (brain.governor), which is "
                            f"{config.owner_of()}'s to do in their own terminal", None)
    cats = owner_categories()

    def refusal(cat, what, top, remote=""):
        why = cats[cat].get("why") or f"{cat} is in the never-grantable list"
        return (cat, f"{what}{remote} refused: {cat} is {config.owner_of()}'s alone ({why.rstrip('.')})",
                _request(cat, what + remote, top, shell, cwd))
    for words, d, sh, top in actions(cmds, sub, command=command):
        if "--help" in words[1:] or "/?" in words[1:]:
            continue
        hit = _owner_command(words, d, sh, command)
        hit = hit if hit and hit[0] in cats else _deny_rules(words, cats)
        if hit:
            return refusal(*hit, top, " over ssh" if sh == "ssh" else "")
    if "scheduled" in cats:
        for what, target in shell_writes(cmds, sub):
            if _autostart(target):
                return refusal("scheduled", f"{what} into {target} (it starts a program on its own)", command)
    return None


# --- power and cluster ---------------------------------------------------------------------------------------------

BRAIN_NAMESPACE = "brain"   # the Brain's own namespace at the cluster (spec-brain-deployment-topology 3.4)
BRAIN_APP = re.compile(r"^(?:[\w.-]+/)?brain(?:-[\w.-]+)?$")   # the Brain's own ArgoCD applications
KUBECTL = {"kubectl", "kubecolor", "oc"}
K_VALUES = {"-n", "--namespace", "--context", "--kubeconfig", "--cluster", "--user", "-s", "--server", "--token",
            "--as", "--as-group", "--as-uid", "--request-timeout", "--certificate-authority", "--client-certificate",
            "--client-key", "--tls-server-name", "--cache-dir", "-v", "--v", "--profile", "--profile-output", "-o",
            "--output", "-l", "--selector", "-c", "--container", "-f", "--filename", "-k", "--kustomize", "-p",
            "--patch", "--patch-file", "--type", "--replicas", "--field-selector", "--for", "--timeout", "--image",
            "--port", "--overrides", "--field-manager", "--subresource", "--template", "--sort-by", "--grace-period",
            "--target-port", "--name", "--resource-version", "--current-replicas", "--from-literal", "--from-file",
            "--from-env-file", "--env", "-e", "--labels", "-L", "--restart", "--serviceaccount", "--to-revision",
            "--min", "--max", "--cpu-percent", "--protocol", "--selector-labels", "--cascade", "--pod-running-timeout"}
K_READS = {"get", "describe", "logs", "log", "top", "explain", "api-resources", "api-versions", "version",
           "cluster-info", "config", "diff", "wait", "events", "kustomize", "completion", "help", "options", "proxy",
           "port-forward", "plugin"}
K_WRITES = {"apply", "create", "delete", "edit", "patch", "replace", "scale", "autoscale", "rollout", "set", "label",
            "annotate", "expose", "run", "exec", "attach", "cp", "debug"}
K_NODE = {"cordon", "uncordon", "drain", "taint"}
CLUSTER_KINDS = {"node", "namespace", "clusterrole", "clusterrolebinding", "customresourcedefinition",
                 "persistentvolume", "storageclass", "priorityclass", "ingressclass", "runtimeclass",
                 "validatingwebhookconfiguration", "mutatingwebhookconfiguration", "validatingadmissionpolicy",
                 "validatingadmissionpolicybinding", "apiservice", "csidriver", "csinode", "volumeattachment",
                 "certificatesigningrequest", "clusterissuer", "podsecuritypolicy", "flowschema",
                 "prioritylevelconfiguration", "volumesnapshotclass"}
# The kinds a write in the brain namespace may name: the namespaced ones the guard knows (an unknown kind, a CRD's
# GatewayClass say, may be cluster-scoped and is refused).
NAMESPACED = {"pod", "deployment", "replicaset", "statefulset", "daemonset", "job", "cronjob", "service", "configmap",
              "secret", "serviceaccount", "role", "rolebinding", "persistentvolumeclaim", "ingress", "networkpolicy",
              "resourcequota", "limitrange", "horizontalpodautoscaler", "poddisruptionbudget", "lease", "endpoints",
              "endpointslice", "event", "controllerrevision", "podtemplate", "replicationcontroller", "certificate",
              "issuer", "servicemonitor", "podmonitor", "prometheusrule"}
K_SHORT = {"no": "node", "ns": "namespace", "crd": "customresourcedefinition", "crds": "customresourcedefinition",
           "pv": "persistentvolume", "sc": "storageclass", "pc": "priorityclass", "csr": "certificatesigningrequest",
           "po": "pod", "deploy": "deployment", "rs": "replicaset", "sts": "statefulset", "ds": "daemonset",
           "cj": "cronjob", "svc": "service", "cm": "configmap", "sa": "serviceaccount",
           "pvc": "persistentvolumeclaim", "ing": "ingress", "netpol": "networkpolicy", "quota": "resourcequota",
           "limits": "limitrange", "hpa": "horizontalpodautoscaler", "pdb": "poddisruptionbudget", "ep": "endpoints",
           "ev": "event", "rc": "replicationcontroller", "cert": "certificate", "certs": "certificate"}
K_TYPED = {"delete", "edit", "patch", "label", "annotate", "scale", "autoscale", "expose", "create", "set", "rollout"}
K_READ_PLUGINS = {"krew", "tree", "neat", "images", "resource-capacity", "who-can", "access-matrix"}
H_WRITES = {"install", "upgrade", "uninstall", "delete", "del", "un", "rollback", "test"}
H_VERBS = H_WRITES | {"list", "ls", "get", "history", "hist", "status", "template", "show", "search", "repo", "pull",
                      "push", "package", "lint", "dependency", "dep", "plugin", "registry", "env", "version",
                      "verify", "completion", "create"}
ARGO_VALUES = {"--server", "--auth-token", "-l", "--selector", "-p", "--parameter", "--revision", "--app-namespace",
               "-N", "-o", "--output", "--config", "--context", "--project", "--dest-namespace", "--dest-server",
               "--repo", "--path", "--sync-policy", "--timeout", "--resource", "--label", "--port-forward-namespace",
               "--grpc-web-root-path", "--header", "-H", "--kube-context"}
NODE_CLI_READS = {"status", "events", "history", "help", "version", "completion"}   # a node CLI's verbs that only read
NODE_CLI_CACHE = "node-clis.txt"   # <BRAIN_HOME>/cache/: config.json's power.node_clis, for guard.sh's pre-filter
NODE_CLI_FORMAT = "#brain.node-clis/v1"   # its line 2 (line 1 the alternation, which guard.sh before 0.3.2 reads)
PROGRAM = re.compile(r"^[a-z0-9][a-z0-9._-]*$")   # a program's name as power.node_clis and node_services give it
NODE_POWER = re.compile(r"(?i)(?:^|[\\/.])(?:sigma_node_power|forge_boot|pxe_router)(?:\.py)?$|(?:^|\.)node_power\b")
NODE_SCRIPTS = {"k3s-killall.sh", "k3s-uninstall.sh", "k3s-agent-uninstall.sh"}
NODE_SERVICES = {"k3s", "k3s-agent", "kubelet"}   # and config.json's power.node_services
WAKE = {"wakeonlan", "wol", "etherwake", "ether-wake", "wakemeonlan", "mc-wol", "wolcmd", "send-wol",
        "invoke-wakeonlan", "send-wakeonlan"}
MAGIC = re.compile(r"(?i)send_magic_packet\s*\(|\b(?:from|import)\s+wakeonlan\b|(?:0x)?ff['\"]?\s*\)?\s*\*\s*6\b|"
                   r"\b255\s*\]?\s*\)?\s*\*\s*6\b")   # b'\xff'*6, [byte[]](,0xFF * 6), bytes([255]*6)
POWER_VERBS = {"poweroff", "reboot", "halt", "suspend", "hibernate", "hybrid-sleep", "suspend-then-hibernate",
               "kexec", "soft-reboot", "sleep", "emergency", "rescue"}
POWER_TARGETS = re.compile(r"(?i)^(?:poweroff|reboot|halt|suspend|hibernate|hybrid-sleep|sleep|kexec|rescue|"
                           r"emergency|suspend-then-hibernate|soft-reboot)\.target$")
WIN_POWER = re.compile(r"(?i)\bWin32Shutdown(?:Tracker)?\b|\bSetSuspendState\b|\bExitWindowsEx\b|"
                       r"\bInitiateSystemShutdown")
BOT = re.compile(r"(?:^|[\s=:\"'{,])/power(?:@\w+)?(?!\s+(?:\w+\s+)?status\b)(?:$|[\s\"',}])")   # /power status reads
BOT_SENDERS = HTTP | {"telegram-send", "tg", "telegram"}


def node_tools() -> dict[str, frozenset[str]]:
    """The owner's platform as the power guard knows it by name, config.json's ``power`` (none by default), read at
    each call: ``node_clis``, the node lifecycle CLIs whose every verb but NODE_CLI_READS acts on a node (one named
    kubectl-<name> is a kubectl plugin, kubectl <name> too), and ``node_services``, the node agents' services that
    stopping acts on a node; lower-cased, names of PROGRAM only. The CLIs are kept in <BRAIN_HOME>/cache/node-clis.txt,
    which guard.sh's pre-filter reads (it cannot find config.json: the plugin runs from a cached copy)."""
    data = config.load().data
    power = data.get("power") if isinstance(data.get("power"), dict) else {}
    out = {k: frozenset(n.lower() for n in (power.get(k) if isinstance(power.get(k), list) else [])
                        if isinstance(n, str) and PROGRAM.match(n.lower()))
           for k in ("node_clis", "node_services")}
    line = "|".join(sorted(n.replace(".", "\\.") for n in out["node_clis"]))   # a bash regular expression
    cache = paths.brain_home() / "cache" / NODE_CLI_CACHE
    try:
        text = line + "\n" + NODE_CLI_FORMAT + "\n"
        if not cache.is_file() or cache.read_text(encoding="utf-8") != text:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(text, encoding="utf-8", newline="\n")
    except OSError:
        pass
    return out


def _kube(args: list[str]):
    """(verb, its positionals, {option: [values]}) of a kubectl command; the words after -- are dropped."""
    verb, pos, opts, i = None, [], {}, 0
    while i < len(args):
        a = args[i]
        if a == "--":
            break
        if a.startswith("--"):
            name, eq, val = a.partition("=")
        elif a.startswith("-") and len(a) > 1:
            name, eq, val = a[:2], "", a[2:].removeprefix("=")
        else:
            name = None
        if name is None and verb is None:
            verb = a
        elif name is None:
            pos.append(a)
        else:
            if not eq and not val and name in K_VALUES and i + 1 < len(args):
                i, val = i + 1, args[i + 1]
            opts.setdefault(name, []).append(val)
        i += 1
    return verb, pos, opts


def _kind(t: str) -> str:
    """A kind as a write names it (nodes, no, deploy, ClusterIssuer, gatewayclasses.gateway.networking.k8s.io): its
    singular lower-case name."""
    t = t.lower().split(".")[0]
    t = K_SHORT.get(t, t)
    known = CLUSTER_KINDS | NAMESPACED
    for cand in (t, t[:-3] + "y" if t.endswith("ies") else "", t[:-1] if t.endswith("s") else "",
                 t[:-2] if t.endswith("es") else ""):
        if cand in known:
            return cand
    return t


def _cluster_kind(t: str) -> bool:
    return _kind(t) in CLUSTER_KINDS


def _kind_refusal(t: str) -> str | None:
    """Why a write that names kind ``t`` leaves the brain namespace: a cluster-scoped kind, or one the guard does not
    know as namespaced; None for a namespaced one."""
    k = _kind(t)
    if k in CLUSTER_KINDS:
        return f"{t} is cluster-scoped"
    return None if k in NAMESPACED else f"{t} is a kind the guard does not know as namespaced"


def _objects(doc) -> list[dict]:
    if not isinstance(doc, dict):
        return []
    if str(doc.get("kind", "")).endswith("List") and isinstance(doc.get("items"), list):
        return [o for item in doc["items"] for o in _objects(item)]
    return [doc]


def _manifests(names: list[str], cwd: str, shell: str, recursive: bool,
               written=frozenset()) -> tuple[list[dict], str | None]:
    """The objects of the local manifests -f names (files, folders, comma lists), or ([], what cannot be read: stdin,
    a URL, a missing file, a remote one, one the same command writes first (``written``: normcased paths), more than
    200 files, YAML that does not parse, a folder that cannot be listed)."""
    out = []
    for name in (p for n in names for p in n.split(",")):
        if name == "-" or "://" in name or shell == "ssh":
            return [], name
        try:
            path = _path(name, cwd)
            key = os.path.normcase(path)
            if any(w == key or w.startswith(key + os.sep) or key.startswith(w + os.sep) for w in written):
                return [], f"{name} (this command writes it first)"
            if os.path.isdir(path):
                walk = os.walk(path) if recursive else [(path, [], os.listdir(path))]
                files = sorted(os.path.join(d, f) for d, _, fs in walk for f in fs
                               if f.lower().endswith((".yaml", ".yml", ".json")))
            else:
                files = [path] if os.path.isfile(path) else []
            if not files or len(files) > 200:
                return [], name
            for f in files:
                if os.path.getsize(f) > MAX_FILE:
                    return [], name
                with open(f, encoding="utf-8", errors="replace") as fh:
                    docs = projects.graph.load_yaml_all(fh.read())
                out += [o for d in docs for o in _objects(d)]
        except Exception:
            return [], name
    return out, None


def _kube_namespace(args: list[str]) -> str | None:
    """The namespace kubectl uses: the last -n or --namespace given (it reads them in order)."""
    ns, i = None, 0
    while i < len(args) and args[i] != "--":
        a = args[i]
        if a in ("-n", "--namespace") and i + 1 < len(args):
            ns, i = args[i + 1], i + 1
        elif a.startswith("--namespace="):
            ns = a.partition("=")[2]
        elif a.startswith("-n") and not a.startswith("--") and len(a) > 2:
            ns = a[2:].removeprefix("=")
        i += 1
    return ns


def _kubectl(args: list[str], cwd: str, shell: str, written=frozenset(),
             clis=frozenset()) -> tuple[str, str, str] | None:
    """(check, what, why) for a kubectl call that acts outside the brain namespace or on a node, else None. A write
    passes only in the brain namespace, naming no kind but the namespaced ones the guard knows, with each -f manifest
    read; a dry run and help pass. ``clis``: the node lifecycle CLIs (node_tools), a plugin among them read as one."""
    verb, pos, opts = _kube(args)
    if verb is None or verb in K_READS or (verb == "auth" and pos[:1] in (["can-i"], ["whoami"])) or \
            (verb == "rollout" and pos[:1] in (["status"], ["history"])) or verb in K_READ_PLUGINS or \
            any(o in opts for o in ("-h", "--help")) or \
            any(v != "none" for v in opts.get("--dry-run", [])):
        return None
    if f"kubectl-{verb.lower()}" in clis:
        return _node_cli(pos, f"kubectl {verb}")
    what = f"kubectl {verb}"
    if verb in K_NODE:
        return "cluster", what, "a node action"
    if verb not in K_WRITES:
        return "cluster", what, "a verb or plugin the guard does not read"
    if "--raw" in opts:
        return "cluster", what, "a raw API path"
    named = (pos[:1] if verb not in ("rollout", "set") else pos[1:2]) if verb in K_TYPED else []
    kinds = [t.split("/")[0] for x in named + [p for p in pos if "/" in p] for t in x.split(",") if t]
    why = next((r for k in kinds if (r := _kind_refusal(k))), None)
    if why:
        return "cluster", what, why
    if "-A" in opts or "--all-namespaces" in opts:
        return "cluster", what, "every namespace (-A)"
    if opts.get("-k") or opts.get("--kustomize"):
        return "cluster", what, ("a kustomization the guard does not read (build it to a file first: kubectl "
                                 "kustomize DIR > x.yaml)")
    ns = _kube_namespace(args)
    files = opts.get("-f", []) + opts.get("--filename", [])
    if files:
        objs, unread = _manifests(files, cwd, shell, "-R" in opts or "--recursive" in opts, written)
        if unread is not None:
            return "cluster", what, f"{unread} cannot be read (a local manifest can)"
        for o in objs:
            kind = str(o.get("kind") or "?")
            why = _kind_refusal(kind)
            if why:
                return "cluster", what, f"its {why}"
            md = o.get("metadata") if isinstance(o.get("metadata"), dict) else {}
            where = md.get("namespace") or ns
            if where != BRAIN_NAMESPACE:
                return "cluster", what, f"its {kind} goes to " + (f"namespace {where}" if where else
                                                                  "the context's namespace (no -n brain)")
        return None
    if ns != BRAIN_NAMESPACE:
        return "cluster", what, f"namespace {ns}" if ns else "the context's namespace (no -n brain)"
    return None


def _node_cli(args: list[str], prog: str) -> tuple[str, str, str] | None:
    """(check, what, why) for a verb of a node lifecycle CLI (power.node_clis) that does more than read, else None."""
    pos = _first(args, ("-o", "--output", "--context", "--kubeconfig", "-n", "--namespace", "--server", "--token"))
    verb = pos[0] if pos else ""
    if not verb or verb in NODE_CLI_READS or "--help" in args or "-h" in args:
        return None
    return "node", f"{prog} {verb}", "a node lifecycle verb of the platform's operator"


def _argocd(args: list[str]) -> tuple[str, str, str] | None:
    pos = _first(args, ARGO_VALUES)
    group, verb = (pos + ["", ""])[:2]
    if group in ("", "version", "context", "completion", "help", "login", "relogin", "logout", "account"):
        return None   # account, login and logout: the owner guard's (keys, accounts)
    if group == "app":
        if verb in ("", "get", "list", "diff", "history", "manifests", "resources", "logs", "wait", "man") or \
                (verb == "actions" and pos[2:3] == ["list"]):
            return None
        names = pos[2:]
        wide = _has(args, "-l", "--selector", "--all") or not names
        dest = next((args[i + 1] for i, a in enumerate(args[:-1]) if a == "--dest-namespace"),
                    next((a.partition("=")[2] for a in args if a.startswith("--dest-namespace=")), None))
        if verb == "create" and dest != BRAIN_NAMESPACE or (verb == "set" and dest not in (None, BRAIN_NAMESPACE)):
            return "cluster", f"argocd app {verb}", f"its destination namespace is {dest or 'not brain'}"
        if not wide and all(BRAIN_APP.match(n) for n in names):
            return None
        return "cluster", f"argocd app {verb}", "an application that is not the Brain's"
    if verb in ("", "list", "get"):
        return None
    return "cluster", f"argocd {group} {verb}", "ArgoCD's configuration"


def _py_target(args: list[str]) -> tuple[str, str]:
    """(the script, the module) python runs from its arguments (-X utf8 and -W ignore take a value)."""
    i = 0
    while i < len(args):
        a = args[i]
        if a == "-m":
            return "", args[i + 1] if i + 1 < len(args) else ""
        if a in ("-X", "-W", "-Q"):
            i += 2
            continue
        if a == "-c" or not a.startswith("-"):
            return ("" if a == "-c" else a), ""
        i += 1
    return "", ""


ANSIBLE_POWER = {"reboot": "machine", "win_reboot": "machine", "shutdown": "machine", "wakeonlan": "wake",
                 "win_wakeonlan": "wake"}


def _power_command(words: list[str], cwd: str, shell: str, command: str, written=frozenset(),
                   tools=None) -> tuple[str, str, str] | None:
    """(check, what, why) when ``words`` acts on a machine's power or boot, wakes one, or writes to the cluster outside
    the brain namespace. ``tools``: the platform's node CLIs and services (node_tools), read from config.json when
    None."""
    tools = node_tools() if tools is None else tools
    clis = tools.get("node_clis", frozenset())
    name = re.split(r"[\\/]", words[0])[-1].lower()
    prog, args = _prog(words[0]), words[1:]
    low = [a.lower() for a in args]
    power = "a machine's power"
    if prog == "shutdown" and not set(low) & {"/a", "-a", "-c", "/?", "--help"}:
        return "machine", "shutdown", power
    if prog in ("poweroff", "reboot", "halt", "psshutdown", "rtcwake", "logoff", "pm-suspend", "pm-hibernate",
                "pm-suspend-hybrid", "stop-computer", "restart-computer") and "--help" not in low:
        return "machine", words[0], power
    if prog in ("init", "telinit") and set(args) & {"0", "6"}:
        return "machine", f"{prog} {'0' if '0' in args else '6'}", power
    if prog in ("systemctl", "loginctl"):
        verbs = [a for a in low if not a.startswith("-")]
        if verbs[:1] and verbs[0] in POWER_VERBS:
            return "machine", f"{prog} {verbs[0]}", power
        if verbs[:1] and verbs[0] in ("start", "isolate") and any(POWER_TARGETS.match(v) for v in verbs[1:]):
            return "machine", f"{prog} {verbs[0]} {verbs[1]}", power
        if prog == "systemctl" and verbs[:1] and verbs[0] in ("stop", "restart", "kill", "disable", "mask") and \
                {v.removesuffix(".service") for v in verbs[1:]} & (NODE_SERVICES | tools.get("node_services", set())):
            return "node", f"systemctl {verbs[0]} {verbs[1]}", "a cluster node's service"
    if prog == "pmset" and set(low) & {"sleepnow", "schedule", "repeat", "restart", "shutdown"}:
        return "machine", "pmset", power
    if prog == "osascript" and re.search(r"(?i)\b(?:shut down|restart|sleep)\b", _text(args)):
        return "machine", "osascript", power
    if prog in ("dbus-send", "busctl", "gdbus") and "login1" in _text(args) and \
            re.search(r"\b(?:PowerOff|Reboot|Suspend|Hibernate|HybridSleep|Halt)\b", _text(args)):
        return "machine", f"{prog} (logind)", power
    if prog == "rundll32" and re.search(r"(?i)powrprof|SetSuspendState|ExitWindowsEx|LockWorkStation", _text(args)):
        return "machine", "rundll32 (power)", power
    if prog == "nircmd" and low[:1] and low[0] in ("standby", "hibernate", "exitwin", "initshutdown"):
        return "machine", f"nircmd {low[0]}", power
    if prog == "wmic" and "call" in low and set(low) & {"shutdown", "reboot", "win32shutdown"}:
        return "machine", "wmic os call", power
    if WIN_POWER.search(words[0]) or (prog in ("invoke-cimmethod", "invoke-wmimethod") and
                                      re.search(r"(?i)\b(?:Shutdown|Reboot|Win32Shutdown)\b", _text(args))):
        return "machine", words[0], power
    if shell == "ps" and re.match(r"(?i)^\.(?:reboot|shutdown)$", words[0]) and \
            re.search(r"(?i)win32_operatingsystem", command):   # (gwmi Win32_OperatingSystem).Reboot()
        return "machine", f"Win32_OperatingSystem{words[0]}()", power
    if prog == "ansible":
        mod = next((args[i + 1] for i, a in enumerate(args[:-1]) if a in ("-m", "--module-name")), "")
        check = ANSIBLE_POWER.get(mod.rsplit(".", 1)[-1])
        if check:
            return check, f"ansible -m {mod}", power if check == "machine" else "Wake-on-LAN"
    if prog == "bcdedit" and low and "/enum" not in low and not set(low) <= {"/v", "/?"}:
        return "machine", "bcdedit (the next boot)", "a machine's boot configuration (arming PXE)"
    if prog == "efibootmgr" and not set(low) <= {"-v", "--verbose"}:
        return "machine", "efibootmgr (the next boot)", "a machine's boot configuration (arming PXE)"
    if prog == "ipmitool":
        if ("power" in low and set(low) & {"on", "off", "cycle", "reset", "soft", "diag", "up", "down"}) or \
                "bootdev" in low or "bootparam" in low or ("mc" in low and "reset" in low):
            return "machine", "ipmitool (power or boot)", power
    if prog == "racadm" and "serveraction" in low:
        return "machine", "racadm serveraction", power
    if name in NODE_SCRIPTS:
        return "node", name, "a cluster node"
    if prog in WAKE:
        return "wake", prog, "Wake-on-LAN"
    if prog in clis:
        return _node_cli(args, prog)
    interpreter = re.fullmatch(r"python[\d.]*w?|py", prog)
    if interpreter or NODE_POWER.search(name):
        target, module = (name, "") if not interpreter else _py_target(args)
        if module == "wakeonlan":
            return "wake", "python -m wakeonlan", "Wake-on-LAN"
        if (NODE_POWER.search(target) or NODE_POWER.search(module)) and \
                not set(low) & {"status", "--dry-run", "--help", "-h"}:
            return "node", f"{target or module} (Σ-NODE-POWER-CORE)", "a cluster node's power"
    lang = "python" if interpreter else prog
    if lang in INLINE:
        code = _inline(args, *INLINE[lang][:2])
        if code and MAGIC.search(code[0]):
            return "wake", f"{prog} (a magic packet)", "Wake-on-LAN"
        if code and BOT.search(code[0]) and re.search(r"(?i)https?://|requests|urllib|telegram", code[0]):
            return "bot", f"{prog} /power", "the /power bot"
    if shell == "ps" and MAGIC.search(_text(words)):
        return "wake", "a magic packet", "Wake-on-LAN"
    if prog in KUBECTL or (prog in ("k3s", "microk8s") and args[:1] == ["kubectl"]) or name == "microk8s.kubectl":
        return _kubectl(args[1:] if prog in ("k3s", "microk8s") else args, cwd, shell, written, clis)
    if prog == "helm":
        verb = next((a for a in args if a in H_VERBS), "")
        if verb in H_WRITES and not set(args) & {"--help", "-h", "--dry-run"}:
            return "cluster", f"helm {verb}", "what a chart writes is not read (render it: helm template ... > " \
                                              "x.yaml, then kubectl apply -f x.yaml -n brain)"
    if prog == "argocd":
        return _argocd(args)
    if prog in BOT_SENDERS and BOT.search(command if shell == "ps" else _text(args)):
        return "bot", f"{prog} /power", "the /power bot"
    return None


def check_power(cmds, powershell: bool = False, command: str = ""):
    """(check, reason, request) for a call that acts on a machine's power or boot, wakes one, uses the /power bot or
    writes to the cluster outside the brain namespace, locally or over ssh; else None."""
    shell = "powershell" if powershell else "bash"
    written, tools = None, node_tools()
    for words, d, sh, top in actions(cmds, "ps" if powershell else "bash", command=command):
        if "--help" in words[1:] or "/?" in words[1:]:
            continue
        if written is None and _prog(words[0]) in KUBECTL | {"k3s", "microk8s"}:
            written = frozenset(os.path.normcase(os.path.abspath(str(t)))
                                for _, t in shell_writes(cmds, "ps" if powershell else "bash"))
        hit = _power_command(words, d, sh, command, written or frozenset(), tools)
        if not hit:
            continue
        check, what, why = hit
        remote, owner = " over ssh" if sh == "ssh" else "", config.owner_of()
        if check == "cluster":
            reason = (f"{what}{remote} refused: {why}; the Brain writes to the cluster only in the {BRAIN_NAMESPACE} "
                      f"namespace (kubectl -n {BRAIN_NAMESPACE} on local manifests), else through the GitOps PR (its "
                      f"manifests in its repo, applied by ArgoCD) or {owner}'s queue")
        else:
            reason = (f"{what}{remote} refused: {why} is {owner}'s to act on (TOPO-2: the Brain observes and asks, "
                      f"never acts); the gated path is {owner}'s queue, later an energy intent for the platform's "
                      "operator after their go")
        return check, reason, _request(check, what + remote, top, shell)
    return None


# --- third-party kits (wi-brain-guard-third-party, EXT-6) ----------------------------------------------------------

DOWNLOADERS = {"curl", "wget", "iwr", "irm", "invoke-webrequest", "invoke-restmethod", "http", "https", "xh"}
WEBCLIENT = re.compile(r"(?i)^\.?Download(?:String|Data)$|^\(?(?:system\.)?net\.webclient\)?$")
SCRIPT_READERS = re.compile(r"^(?:python[\d.]*|py|node|perl|ruby)$")   # run the script stdin holds when none is named
# A text a shell runs (sh -c, eval, a here-string) that is a download's output: "$(curl ...)", `wget -qO- ...`.
EVALUATED = re.compile(r"(?i)^\s*(?:\$\(|`)\s*(?:[\w.~:-]*[\\/])?(?:curl|wget|https?|xh)(?:\.exe)?(?=[\s)`]|$)")
EVALUATORS = re.compile(r"(?i)^(?:iex|invoke-expression|\[scriptblock\]::create)$")   # PowerShell runs its text
# SCRIPT_READERS' short options: (those that give code of its own, those that take a value).
SCRIPT_OPTS = {"python": ("cm", "WX"), "node": ("ep", "r"), "perl": ("eE", "IMm"), "ruby": ("e", "IrC")}
# claude plugin install's options that take a value (the CLI 2.1.x), and marketplace add's list (--sparse a b).
PLUGIN_VALUES = ("-s", "--scope", "--config", "--marketplace", "--accept-command", "--registry")
PLUGIN_LISTS = ("--sparse",)
KIT_HELP = ("--help", "-h")
SKILLS_READS = ("--list", "-l")   # skills add REPO --list lists a repo's skills, installs none


def _downloads(prog: str, words: list[str]) -> bool:
    """Whether the simple command ``words`` fetches from the network what it prints (curl, wget, iwr, a WebClient)."""
    return prog in DOWNLOADERS or any(WEBCLIENT.match(w) for w in words)


def _reads_script(prog: str, args: list[str], shell: str) -> bool:
    """Whether ``prog`` runs as a script what stdin holds: a shell reading stdin (_reads_stdin), iex with no command
    of its own, or python, node, perl and ruby with no script named (or -, /dev/stdin) and no -c, -m or -e."""
    if _reads_stdin(prog, args, shell):
        return True
    return bool(SCRIPT_READERS.match(prog)) and _script_kind(prog, args) == "stdin"


def _script_kind(prog: str, args: list[str]) -> str:
    """What python, node, perl or ruby (``prog``) runs from ``args``: "stdin" (no script named, or -, /dev/stdin),
    "file" (a script named) or "code" (its own: -c, -m, -e, --eval). Each one's own options that take a value
    (SCRIPT_OPTS) skip it: python -I takes none, ruby -I does."""
    code, values = SCRIPT_OPTS["python" if prog.startswith("py") else prog]
    i = 0
    while i < len(args):
        a = args[i]
        if a in STDIN_PATHS:
            return "stdin"
        if a in ("--eval", "--print"):
            return "code"
        if a in ("--require", "--import"):
            i += 2
            continue
        if not a.startswith("-"):
            return "file"
        for k, ch in enumerate(a[1:] if not a.startswith("--") else "", 1):
            if ch in code:
                return "code"
            if ch in values:   # a value option ends its cluster; at its end, the value is the next word
                i += k == len(a) - 1
                break
        i += 1
    return "stdin"


def _runs_substitution(prog: str, args: list[str]) -> bool:
    """Whether a <( ) after ``args`` is what ``prog`` runs: source's or .'s first operand, a shell's or an
    interpreter's when it names no script before it (code of its own, sh -c, may read it: counted); a script named
    first reads the download as data (python3 analyze.py <(curl ...))."""
    if prog in ("source", "."):
        return not [a for a in args if not a.startswith("-")]
    if SHELLS.get(prog) == "bash":
        opts, pos = _bash_words(args)   # the same reading as _bash_reads_stdin's
        return not pos or _bash_short(opts, "c")
    return bool(SCRIPT_READERS.match(prog)) and _script_kind(prog, args) != "file"


def plugin_sources() -> tuple[set[str], set[str]]:
    """(the marketplace names, the sources) the owner allows a session to install or add from: config.json's
    ``adapters.claude.sources`` (an entry with a / or \\ is a source: owner/repo, a git URL, a folder; else a
    marketplace name), plus the brain's own marketplace, its source repo and its folder."""
    cfg = config.load()
    own = config.claude(cfg)
    adapters = cfg.data.get("adapters") if isinstance(cfg.data.get("adapters"), dict) else {}
    given = (adapters.get("claude") or {}).get("sources") if isinstance(adapters.get("claude"), dict) else None
    entries = [e for e in given if isinstance(e, str) and e] if isinstance(given, list) else []
    names = {own["marketplace"].lower()} | {e.lower() for e in entries if not re.search(r"[\\/]", e)}
    sources = {_source(e, str(cfg.root)) for e in entries if re.search(r"[\\/]", e)}
    sources |= {_source(own["source"], str(cfg.root))} if own["source"] else set()
    sources.add(_source(str(cfg.root), str(cfg.root)))
    return names, sources


def _source(text: str, cwd: str) -> str:
    """A plugin source as one comparable string: owner/repo for GitHub (its URL, git@github.com:, or owner/repo; a
    #ref or @ref dropped), the URL for another git host, else the folder it names, from ``cwd``."""
    t = text.strip().rstrip("/")
    m = re.match(r"(?i)^(?:https?://(?:www\.)?github\.com/|git@github\.com:|ssh://git@github\.com/)?"
                 r"([\w-][\w.-]*)/([\w.-]+?)(?:\.git)?(?:[#@][\w./-]*)?$", t)
    if m and (re.match(r"(?i)^(?:https?|git@|ssh:)", t) or not os.path.isdir(_path(t, cwd))):
        return f"{m[1]}/{m[2]}".lower()
    if re.match(r"(?i)^(?:https?|ssh|git)://|^[\w.-]+@[\w.-]+:", t):
        return t.lower()
    return os.path.normcase(os.path.normpath(_path(t, cwd)))


def _kit_command(prog: str, args: list[str], d: str) -> tuple[str, str] | None:
    """(check, what) when the simple command adds a plugin, a marketplace or a skill from outside the owner's list:
    claude plugin install NAME@MARKETPLACE (and its --marketplace SOURCE), claude plugin marketplace add SOURCE, skills
    add (npx, bunx, bun x, pnpm dlx); its --list only lists. claude's global options may come before plugin. npm's
    Windows shims (claude.cmd, claude.ps1, skills.cmd, npx.cmd) are the programs they start (_prog)."""
    if re.sub(r"(?<=.)@[^/]*$", "", prog) == "skills" and _first(args)[:1] == ["add"]:
        if any(a in SKILLS_READS for a in args):
            return None
        return "skills", f"skills add {' '.join(_first(args)[1:2])}".rstrip()
    if prog != "claude":
        return None
    at = next((k for k, a in enumerate(args) if a in ("plugin", "plugins")), None)
    return None if at is None else _plugin_command(args[at + 1:], d)


def _drop_lists(args: list[str]) -> list[str]:
    """``args`` without PLUGIN_LISTS' options and their values (the words up to the next option, or past a --)."""
    out, listing = [], False
    for a in args:
        if a in PLUGIN_LISTS:
            listing = True
        elif listing and not a.startswith("-"):
            continue
        else:
            listing = False
            out.append(a)
    return out


def _plugin_command(args: list[str], d: str) -> tuple[str, str] | None:
    """(check, what) for claude plugin's ``args`` (after the plugin word): every operand of install is a plugin it
    checks, and every operand of marketplace add a source, so an option's value never shifts what is checked."""
    pos = _first(_drop_lists(args), PLUGIN_VALUES)
    names, sources = plugin_sources() if pos[:1] in (["install"], ["i"]) or pos[:2] == ["marketplace", "add"] \
        else (set(), set())
    if pos[:1] in (["install"], ["i"]):
        for spec in pos[1:]:
            market = spec.rpartition("@")[2].lower() if "@" in spec else ""
            if market not in names:
                return "plugin", f"claude plugin install {spec} (" + (f"marketplace {market}" if market else
                                                                       "no marketplace named") + ")"
        for source in _option_values(args, ("--marketplace",)):
            if _source(source, d) not in sources:
                return "plugin", f"claude plugin install --marketplace {source}"
    elif pos[:2] == ["marketplace", "add"]:
        for source in pos[2:]:
            if _source(source, d) not in sources:
                return "plugin", f"claude plugin marketplace add {source}"
    return None


def check_third_party(cmds, cwd: str, powershell: bool = False, command: str = ""):
    """(check, reason, request) when the call installs or runs a third-party kit: a downloaded script fed to a shell
    or an interpreter (curl | sh, sh -c "$(curl ...)", bash <(curl ...), iwr | iex, iex (iwr ...)), a plugin or a
    marketplace from outside the owner's list (plugin_sources), or skills add; seen through what actions() sees
    (wrappers, launchers, nested shells, ssh, what a command feeds a shell). The request of a download is the call's
    whole text, of the others the outermost command that holds it."""
    sub = "ps" if powershell else "bash"
    shell = "powershell" if powershell else "bash"
    owner = config.owner_of()

    def refusal(check, what, top):
        why = {"download": "a downloaded script would run unread",
               "plugin": f"its source is not in {owner}'s list, config.json adapters.claude.sources",
               "skills": "a third-party skill would install unread"}[check]
        return (check, f"{what} refused: a session never installs or runs a third-party kit ({why}); {owner} reads "
                       "it first and runs it themself", _request(check, what, top, shell, cwd))
    for words, d, _, top in actions(cmds, sub, command=command):
        hit = None if any(a in KIT_HELP for a in words[1:]) else _kit_command(_prog(words[0]), words[1:], d)
        if hit:
            return refusal(*hit, top)
    what = _fed_download(command, sub)
    return refusal("download", what, command) if what else None


def _plain(raw: list[str], shell: str) -> tuple[list[str], bool]:
    """(the words of the program a segment runs, whether it reads stdin from a file): its redirections and leading
    assignments dropped, past wrappers (sudo, env) and launchers (uv run, npx, Start-Process)."""
    marks = {i for i, w in enumerate(raw) if w.startswith(REDIRECT)}
    own = any(raw[i].endswith("<") for i in marks)
    words = [w for i, w in enumerate(raw) if i not in marks and i - 1 not in marks]
    while words and ASSIGN.match(words[0]):
        words = words[1:]
    words = _unwrap(words)
    for _ in range(3):
        run = words and (_launched(_prog(words[0]), words[1:], shell) or _launcher(_prog(words[0]), words[1:]))
        if not run:
            break
        words = _unwrap(run)
    return words, own


def _ps_subexpression_download(args: list[str]) -> str:
    """The download in a $( ) of iex's string, which PowerShell expands before iex runs it: iex "& { $(irm URL) }"
    (Microsoft's own installer line) and iex "$(irm URL)"; '' when none."""
    for arg in args:
        i = arg.find("$(")
        while i >= 0:
            j = _subst_end(arg, i)
            for seg in segments(arg[i + 2:j if j > 0 else len(arg)], True):
                words = _plain(seg, "ps")[0]
                if words and _downloads(_prog(words[0]), words):
                    return _prog(words[0]) if _prog(words[0]) in DOWNLOADERS else "a WebClient download"
            i = arg.find("$(", i + 2)
    return ""


def _substituted_download(segs: list[list[str]], k: int, shell: str) -> str | None:
    """The download a process substitution opened at segment ``k`` (the <( of segs[k - 1]) feeds the program that
    runs it as a script (_runs_substitution: bash <(curl ...), source <(curl ...)), else None."""
    runner = _plain(segs[k - 1], shell)[0]
    prog = _prog(runner[0]) if runner else ""
    if not (SHELLS.get(prog) == "bash" or prog in ("source", ".") or SCRIPT_READERS.match(prog)) or \
            not _runs_substitution(prog, runner[1:]):
        return None
    depth_in, j = 1, k + 1
    while j < len(segs) and depth_in:
        depth_in += {SUBSHELL[0]: 1, SUBSHELL[1]: -1}.get(segs[j][0], 0)
        inner = _plain(segs[j], shell)[0]
        if depth_in and inner and _downloads(_prog(inner[0]), inner):
            return f"{_prog(inner[0])} run by {prog} through <( )"
        j += 1
    return None


def _fed_download(text: str, shell: str = "bash", depth: int = 0) -> str | None:
    """What runs a download as a script in the command ``text`` read by ``shell`` (bash, ps, or ssh: a remote bash),
    else None: a download piped, through any filter, to a shell or an interpreter reading stdin (curl | sh, wget -qO- |
    python3 -, iwr | iex); a download in a process substitution a shell or source runs (bash <(curl ...)); a
    PowerShell statement where iex meets a download (iex (iwr ...)); the text of sh -c, eval or a here-string that is a
    download's output (sh -c "$(curl ...)"); and the same in what the call runs in turn (nested shells, launchers,
    ssh's remote command, a heredoc fed to a shell). A download to a file, then a script run (curl -o f; python - <<EOF)
    is no pipe: it passes."""
    if depth > 4 or not text:
        return None
    links: dict[int, str] = {}
    segs = segments(text, shell == "ps", links)
    piped = stated = ""   # the download whose output flows down this pipe, the one of this PowerShell statement
    evaluator = readers = False
    for k, raw in enumerate(segs):
        if links.get(k) == ";":
            piped = stated = ""
            evaluator = False
        if raw[0] in SUBSHELL:
            if links.get(k) == "<(" and k and segs[k - 1][0] not in SUBSHELL and \
                    (found := _substituted_download(segs, k, shell)):
                return found
            continue
        words, own = _plain(raw, shell)
        if not words:
            continue
        prog, args = _prog(words[0]), words[1:]
        if _downloads(prog, words):
            piped = piped or (prog if prog in DOWNLOADERS else "a WebClient download")
            stated = stated or piped
        if shell == "ps" and EVALUATORS.match(words[0]):
            evaluator = True
            if inner := _ps_subexpression_download(args):
                return f"{inner} fed to iex"
        if evaluator and stated:
            return f"{stated} fed to iex"
        if "<<<" in args[:-1]:   # bash <<< "$(curl ...)": the here-string is stdin
            here = args[args.index("<<<") + 1]
            args = [a for i, a in enumerate(args) if a != "<<<" and args[i - 1:i] != ["<<<"]]
            if EVALUATED.search(here) and _reads_script(prog, args, shell):
                return f"{prog} running a download's output"
            own = True
        if piped and not own and _reads_script(prog, args, shell):
            return f"{piped} piped to {prog}"
        nested = _nested(prog, args, ".", "bash" if shell == "ssh" else shell)
        if nested and nested[0]:
            if nested[1] == "bash" and EVALUATED.search(nested[0]):
                return f"{prog} running a download's output"
            found = _fed_download(nested[0], "bash" if nested[1] == "bash" else "ps", depth + 1)
        elif text_run := _launched_text(prog, args):
            if text_run[1] != "ps" and EVALUATED.search(text_run[0]):
                return f"{prog} running a download's output"
            found = _fed_download(text_run[0], text_run[1], depth + 1)
        elif prog in ("ssh", "plink") and (remote := _ssh_remote(args)):
            found = _fed_download(" ".join(remote), "ssh", depth + 1)
        else:
            found = None
        if found:
            return found
        readers = readers or bool(_reads_stdin(prog, args, shell))
    if readers:
        for body in _heredocs(text):
            found = _fed_download(body, shell, depth + 1)
            if found:
                return found
    return None


# --- AI attribution ----------------------------------------------------------------------------------------------

def _read_file(name: str, cwd: str) -> str:
    if not name or name == "-":
        return ""
    p = _path(name, cwd)
    try:
        if os.path.getsize(p) <= MAX_FILE:
            with open(p, encoding="utf-8", errors="replace") as fh:
                return fh.read()
    except OSError:
        pass
    return ""


def check_attribution(command: str, cmds: list[tuple[list[str], str]]) -> str | None:
    texts, what = [], ""
    for words, d in cmds:
        prog = _prog(words[0])
        if prog == "git":
            parts = git_parts(words, d)
            if not parts or parts[1] != "commit":
                continue
            what, args, files = "git commit message", parts[2], ("-F", "--file")
            d = parts[0]
        elif prog == "gh" and len(words) > 2 and words[1] == "pr" and words[2] in ("create", "edit"):
            what, args, files = f"gh pr {words[2]} text", words[3:], ("-F", "--body-file")
        else:
            continue
        texts += [a.partition("=")[2] if a.startswith("--") else a for a in args]
        texts += [_read_file(f, d) for f in _option_values(args, files)]
    if not what:
        return None
    for text in (command, *texts):
        if any(rx.search(text) for rx in ATTRIBUTION):
            return (f"{what} refused: it holds an AI attribution line (Co-Authored-By: Claude, Generated with Claude "
                    f"Code); {config.owner_of()}'s repos take none, remove the line")
    return None


# --- secrets in what a commit records ----------------------------------------------------------------------------

def _run(args: list[str], cwd: str, timeout: float = 10, env: dict[str, str] | None = None) \
        -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL, env=env)


def _secret_names(line: str) -> list[str]:
    return secretscan.find_in_line(line)


def scan_diff(diff: str) -> list[str]:
    """``file:line (pattern)`` for every added line of a unified diff that looks like a secret."""
    hits, path, line = [], "", 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            path = markers.diff_path(raw)
        elif raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            line = int(m.group(1)) if m else 0
        elif raw.startswith("+"):
            names = _secret_names(raw[1:])
            if names:
                hits.append(f"{path}:{line} ({names[0]})")
            line += 1
    return hits


def scan_text(path: str, text: str) -> list[str]:
    return [f"{path}:{i} ({names[0]})" for i, line in enumerate(text.splitlines(), 1)
            if (names := _secret_names(line))]


def gitleaks(repo: str) -> list[str] | None:
    """gitleaks on the index of ``repo`` (``git --staged``, then the older ``protect --staged``): its hits, or None
    when it is not installed or fails."""
    exe = shutil.which("gitleaks")
    if not exe:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        report = os.path.join(tmp, "report.json")
        for sub in (["git", "--staged"], ["protect", "--staged"]):
            try:
                r = _run([exe, *sub, "--redact", "--no-banner", "--exit-code", "1", "--report-format", "json",
                          "--report-path", report], repo, timeout=20)
            except (OSError, subprocess.SubprocessError):
                return None
            if r.returncode == 0:
                return []
            if r.returncode == 1 and os.path.exists(report):
                with open(report, encoding="utf-8") as fh:
                    found = json.load(fh) or []
                return [f"{f.get('File')}:{f.get('StartLine')} ({f.get('RuleID')})" for f in found]
    return None


class GuardError(RuntimeError):
    """A check could not read what it judges (git failed, timed out, or printed more than it reads): the call goes
    on and the error goes to ledger/errors.log, never a silent pass."""


GIT_CAP = 20 * MAX_FILE   # the most of a git command's output a check reads


def _git_out(repo: str, *args: str, strict: bool = False) -> str:
    """git's output in ``repo``; '' when it fails, or, ``strict``, a GuardError then and when the output is cut."""
    try:
        r = _run(["git", *args], repo)
    except (OSError, subprocess.SubprocessError) as exc:
        if strict:
            raise GuardError(f"git {args[0]} in {repo}: {exc}") from exc
        return ""
    if strict and (r.returncode or len(r.stdout) > GIT_CAP):
        why = f"exit {r.returncode}" if r.returncode else f"over {GIT_CAP} bytes, not read whole"
        raise GuardError(f"git {' '.join(args[:3])} in {repo}: {why}")
    return r.stdout[:GIT_CAP].decode("utf-8", "replace") if r.returncode == 0 else ""


def _is_worktree(repo: str) -> bool:
    """Whether ``repo`` is inside a git worktree. False, quietly, for a missing folder, git's 'not a git repository'
    (a folder whose git init comes later in the call) and a .git folder (rev-parse says false); any other failure
    (git missing from PATH, a timeout, dubious ownership) is a GuardError, never a silent pass. git's messages are
    read in English (LC_ALL=C)."""
    if not os.path.isdir(repo):
        return False
    try:
        r = _run(["git", "rev-parse", "--is-inside-work-tree"], repo,
                 env={**os.environ, "LC_ALL": "C", "LANGUAGE": "C"})
    except (OSError, subprocess.SubprocessError) as exc:
        raise GuardError(f"git rev-parse in {repo}: {exc}") from exc
    if r.returncode == 0:
        return r.stdout.strip() == b"true"
    if b"not a git repository" in r.stderr.lower():
        return False
    why = r.stderr.decode("utf-8", "replace").strip().splitlines()[:1]
    raise GuardError(f"git rev-parse in {repo}: exit {r.returncode}{': ' + why[0] if why else ''}")


def commit_secrets(repo: str, specs: list[str], every_tracked: bool, untracked: list[str] | None = None) -> list[str]:
    """The secrets a commit in ``repo`` would record: the index, plus ``specs`` (paths a git add before it stages,
    or the commit names) or every tracked change (commit -a), and the untracked files a git add stages
    (``untracked``: its paths; default ``specs``)."""
    untracked = specs if untracked is None else untracked
    staged = gitleaks(repo)
    if staged is None:
        staged = scan_diff(_git_out(repo, "diff", "--cached", "-U0", "--no-color", "--no-ext-diff"))
    hits = list(staged)
    if specs or every_tracked:
        hits += scan_diff(_git_out(repo, "diff", "HEAD", "-U0", "--no-color", "--no-ext-diff", "--", *specs))
    if untracked:
        for name in _git_out(repo, "ls-files", "--others", "--exclude-standard", "-z", "--", *untracked).split("\0"):
            if name:
                hits += scan_text(name, _read_file(name, repo))
    return list(dict.fromkeys(hits))


CONTINUES = {"merge", "rebase", "cherry-pick", "revert", "am"}   # git SUB --continue commits what the index holds
COMMIT_VALUES = "mFCct"   # git commit's short options that take a value; its long ones:
COMMIT_LONGS = {"--message", "--file", "--reuse-message", "--reedit-message", "--fixup", "--squash", "--author",
                "--date", "--template", "--cleanup", "--trailer"}
WHOLE_TREE = ":/"   # the pathspec of the whole worktree, from any of its folders


class Commit(NamedTuple):
    """A git commit (or SUB --continue) of a call: its folder, what it is, the pathspecs it records from the working
    tree (a git add's before it, its own), commit -a, the pathspecs whose untracked files a git add stages."""
    repo: str
    what: str
    specs: list[str]
    every: bool
    untracked: list[str]


def _pathspec(spec: str, d: str) -> str | None:
    """A pathspec as the guard's git commands read it from any folder: a path, from ``d``; :/x as is; an exclusion
    (:!x, :^x, :(exclude)x) None (dropped: more is read, never less); any other magic the whole worktree."""
    if not spec.startswith(":"):
        return _path(spec, d)
    if re.match(r"^:(?:[!^]|\([^)]*\bexclude\b)", spec):
        return None
    return spec if spec.startswith(":/") else WHOLE_TREE


def _operands(args: list[str], shorts: str = "", longs=()) -> tuple[list[str], list[str]]:
    """(operands, options) of git SUB's ``args``: a short option of ``shorts`` takes the rest of its cluster or the
    next word, a long one of ``longs`` its =value or the next word; -- ends the options."""
    pos, opts, i = [], [], 0
    while i < len(args):
        a = args[i]
        if a == "--":
            return pos + args[i + 1:], opts
        if a.startswith("-") and len(a) > 1:
            opts.append(a)
            k = next((j for j in range(1, len(a)) if a[j] in shorts), None) if not a.startswith("--") else None
            i += 2 if (k is not None and k == len(a) - 1) or ("=" not in a and a in longs) else 1
        else:
            pos.append(a)
            i += 1
    return pos, opts


def _named_specs(pos: list[str], opts: list[str], d: str) -> list[str]:
    """The pathspecs of ``pos``, read by _pathspec; the whole worktree when only exclusions remain or the list comes
    from a file (--pathspec-from-file)."""
    specs = [s for s in (_pathspec(p, d) for p in pos) if s]
    from_file = any(o.startswith("--pathspec-from-file") for o in opts)
    return [WHOLE_TREE] if from_file or (pos and not specs) else specs


def _add_specs(args: list[str], d: str) -> tuple[list[str], list[str]]:
    """(the pathspecs a git add stages, those whose untracked files it stages too). With no pathspec, git add -A, -u
    and -p take the whole worktree from any folder (git 2.0); -u and -p stage no untracked file."""
    pos, opts = _operands(args)
    specs = _named_specs(pos, opts, d) or [WHOLE_TREE]
    tracked = any(o in ("--update", "--patch") or re.match(r"^-[A-Za-z]*[up]", o) for o in opts)
    return specs, [] if tracked else specs


def _commits(cmds: list[tuple[list[str], str]], continues: bool = False):
    """A Commit for each git commit of ``cmds``, and, with ``continues``, each git merge|rebase|cherry-pick|revert|am
    --continue: what a git add earlier in the call stages, the commit's own pathspecs (git commit -m x path records
    that path's working tree), commit -a."""
    added: list[str] = []
    untracked: list[str] = []
    for words, d in cmds:
        if _prog(words[0]) != "git":
            continue
        parts = git_parts(words, d)
        if not parts:
            continue
        d, sub, args = parts
        if sub == "add":
            specs, new = _add_specs(args, d)
            added, untracked = added + specs, untracked + new
        elif sub == "commit" and "--help" not in args:
            pos, opts = _operands(args, COMMIT_VALUES, COMMIT_LONGS)
            every = any(re.match(r"^-[A-Za-z]*a[A-Za-z]*$", a) or a == "--all" for a in opts)
            yield Commit(d, "git commit", added + _named_specs(pos, opts, d), every, list(untracked))
        elif continues and sub in CONTINUES and "--continue" in args:
            yield Commit(d, f"git {sub} --continue", list(added), False, list(untracked))


def _pushes(cmds: list[tuple[list[str], str]]):
    """(words, folder, git push's arguments) for each git push of ``cmds`` (not its -h or --help)."""
    for words, d in cmds:
        if _prog(words[0]) != "git":
            continue
        parts = git_parts(words, d)
        if parts and parts[1] == "push" and "-h" not in parts[2] and "--help" not in parts[2]:
            yield words, parts[0], parts[2]


def check_config(cmds: list[tuple[list[str], str]]) -> str | None:
    """The public and secrets checks fail closed (COMPAT-4, wi-brain-guards-fail-closed): a git commit or git push is
    refused while the configuration they read is unexpected (config.unexpected), the reason naming the fix. Only
    then is config.json read: every other call never pays for it."""
    what = next(("git commit" for _ in _commits(cmds)), None) or next(("git push" for _ in _pushes(cmds)), None)
    if not what:
        return None
    why = config.unexpected()
    if not why:
        return None
    return (f"{what} refused: the public and secrets checks cannot trust the configuration, so they fail closed: "
            f"{why}")


def check_secrets(cmds: list[tuple[list[str], str]]) -> str | None:
    for c in _commits(cmds):
        hits = commit_secrets(c.repo, c.specs, c.every, c.untracked)
        if hits:
            more = f" and {len(hits) - 1} more" if len(hits) > 1 else ""
            return (f"git commit refused: {hits[0]}{more} looks like a secret; take it out of the commit "
                    f"({config.owner_of()} adds keys themself), or end a false positive's line with a "
                    "gitleaks:allow comment")
    return None


# --- conflict markers in what a commit records (wi-brain-guard-conflict-markers) ------------------------------------

# The diff the markers check reads: one line of context (a heading's line above), renames found whatever diff.renames
# says (a moved file adds no line), and only the files whose changes hold a line that starts like a marker (-G, the
# same in basic and extended regex), so a big data file never fills the output.
MARKER_DIFF = ("-U1", "--no-color", "--no-ext-diff", "-M", "-G^[<=>|][<=>|][<=>|][<=>|][<=>|][<=>|][<=>|]")


def _head(repo: str) -> str:
    """HEAD, or before the first commit the empty tree."""
    if _git_out(repo, "rev-parse", "--verify", "--quiet", "HEAD").strip():
        return "HEAD"
    return _git_out(repo, "hash-object", "-t", "tree", "--stdin", strict=True).strip()


def _merge_heads(repo: str) -> list[str]:
    """The commits a merge in progress in ``repo`` merges (.git/MERGE_HEAD), else []."""
    name = _git_out(repo, "rev-parse", "--git-path", "MERGE_HEAD").strip()
    try:
        with open(_path(name, repo), encoding="utf-8") as fh:
            return [line.strip() for line in fh if line.strip()]
    except OSError:   # no merge in progress (or no repo: name is '', the folder itself)
        return []


def _added_markers(repo: str, cached: bool, specs: list[str]) -> list[str]:
    """The markers the added lines of the index (``cached``) or of ``specs``' working tree bring against HEAD, and,
    during a merge, against every commit it merges too: a line the merged branch already holds is not the session's
    (a combined diff's rule)."""
    hits: list[str] | None = None
    for base in (_head(repo), *_merge_heads(repo)):
        diff = _git_out(repo, "diff", *(["--cached"] if cached else []), *MARKER_DIFF, base, "--", *specs,
                        strict=True)
        found = markers.scan_diff(diff)
        hits = found if hits is None else [h for h in hits if h in set(found)]
    return hits or []


def _file_markers(name: str, repo: str) -> list[str]:
    """The markers of the untracked file ``name`` (from ``repo``), read as it goes whatever its size; a binary file
    (a NUL in its first 8000 bytes) has none, as in a diff."""
    p = _path(name, repo)
    try:
        with open(p, "rb") as fh:
            if b"\0" in fh.read(8000):
                return []
        with open(p, encoding="utf-8", errors="replace") as fh:
            return markers.scan_lines(name, fh)
    except OSError:
        return []


def commit_markers(repo: str, specs: list[str], every_tracked: bool, untracked: list[str] | None = None) -> list[str]:
    """The conflict markers (brain.markers) a commit in ``repo`` would record: the added lines of the index, plus
    ``specs`` (paths a git add before it stages, or the commit names) or every tracked change (commit -a), and the
    untracked files a git add stages (``untracked``: its paths; default ``specs``). During a merge, a line counts only
    when it is new against every parent. What git cannot show is a GuardError (logged), never a silent pass; a folder
    that is not yet a repo when the guard runs (missing, or its git init later in the call) has nothing to read, as
    for git itself (_is_worktree)."""
    untracked = specs if untracked is None else untracked
    if not _is_worktree(repo):
        return []
    hits = _added_markers(repo, True, [])
    if specs or every_tracked:
        hits += _added_markers(repo, False, specs)
    if untracked:
        for name in _git_out(repo, "ls-files", "--others", "--exclude-standard", "-z", "--", *untracked,
                             strict=True).split("\0"):
            if name:
                hits += _file_markers(name, repo)
    return list(dict.fromkeys(hits))


def check_markers(cmds: list[tuple[list[str], str]]) -> str | None:
    for c in _commits(cmds, continues=True):
        d, what = c.repo, c.what
        hits = commit_markers(d, c.specs, c.every, c.untracked)
        if hits:
            more = f" and {len(hits) - 1} more" if len(hits) > 1 else ""
            return (f"{what} refused: {hits[0]}{more} adds a conflict marker (<<<<<<<, ======= or >>>>>>>); finish "
                    "the merge in that file, git add it, then commit (a test's data goes under a fixtures folder)")
    return None


# --- pushes to a public repo -------------------------------------------------------------------------------------

PUSH_VALUE_OPTS = {"--repo", "-o", "--push-option", "--receive-pack", "--exec"}


def _push_target(args: list[str]) -> tuple[str, list[str], set[str]]:
    """(remote or URL, refspecs, flags) of git push's arguments; '' when no remote is named."""
    pos, flags, repo, i = [], set(), "", 0
    while i < len(args):
        a = args[i]
        name, eq, val = a.partition("=")
        if a == "--":
            pos += args[i + 1:]
            break
        if a.startswith("-"):
            flags.add(name)
            if name == "--repo":
                repo = val if eq else (args[i + 1] if i + 1 < len(args) else "")
            if name in PUSH_VALUE_OPTS and not eq:
                i += 1
        else:
            pos.append(a)
        i += 1
    remote = repo or (pos[0] if pos else "")
    return remote, pos[1:] if pos and not repo else pos, flags


def _push_commits(repo: str, refspecs: list[str], flags: set[str]) -> list[tuple[str, str]]:
    """(ref, commit sha) of what a push sends: the refspecs' sources, every branch (--all, --mirror), the tags
    (--tags, --follow-tags), else HEAD. A deletion (``:ref``, --delete) sends nothing."""
    if "--delete" in flags or "-d" in flags:
        return []
    refs = [s.lstrip("+").split(":", 1)[0] for s in refspecs]
    refs = [r for r in refs if r] if refspecs else ["HEAD"]
    if flags & {"--all", "--mirror", "--branches"}:
        refs += _git_out(repo, "for-each-ref", "--format=%(refname)", "refs/heads").split()
    if flags & {"--tags", "--follow-tags", "--mirror"}:
        refs += _git_out(repo, "for-each-ref", "--format=%(refname)", "refs/tags").split()
    out = []
    for ref in dict.fromkeys(refs):
        sha = _git_out(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").strip()
        if sha:
            out.append((ref, sha))
    return out


def check_public(cmds: list[tuple[list[str], str]]) -> str | None:
    cfg = None
    for words, d, args in _pushes(cmds):
        cfg = cfg or config.load()
        if not public.public_repos(cfg):
            return None
        remote, refspecs, flags = _push_target(args)
        if not remote:
            branch = _git_out(d, "rev-parse", "--abbrev-ref", "HEAD").strip()
            remote = _git_out(d, "config", f"branch.{branch}.pushRemote").strip() or \
                _git_out(d, "config", f"branch.{branch}.remote").strip() or "origin"
        url = remote if re.search(r"[:/]", remote) else _git_out(d, "remote", "get-url", "--push", remote).strip()
        slug = public.repo_slug(url)
        if not public.is_public(slug, cfg):
            continue
        # a stamp counts only under the key it was made with: this engine, these rules, gitleaks as now
        # (wi-brain-public-stamp-binding)
        missing = [(ref, sha, why) for ref, sha in _push_commits(d, refspecs, flags)
                   if (why := public.stamp_refusal(slug, sha, cfg))]
        if missing:
            ref, sha, why = missing[0]
            more = f" and {len(missing) - 1} more" if len(missing) > 1 else ""
            fix = ("run brain check --public --history" if why == public.NO_STAMP else
                   "rerun brain check --public --history (the stamp is not valid under this ruleset)")
            return (f"git push refused: {slug} is a public repo (config.json public.repos) and {ref} ({sha[:8]}){more} "
                    f"{why}; {fix} in {d}, take out what it finds, then push again"
                    + (CHAIN_HINT if _checks_first(cmds, words) else ""))
    return None


CHAIN_HINT = (" (this call runs brain check --public before the push, but the guard judges the whole call before "
              "anything in it runs: run the check in one call and git push in the next)")


def _checks_first(cmds: list[tuple[list[str], str]], push: list[str]) -> bool:
    """A ``brain ... check ... --public`` among the calls before the push ``push``."""
    for words, _ in cmds:
        if words is push:
            return False
        prog = _prog(words[0])
        brain = prog == "brain" or (prog in ("python", "python3", "py") and "brain" in words[1:3])
        if brain and "check" in words and "--public" in words:
            return True
    return False


# --- what a commit to a public repo records (the lesson les-brain-owner-name-in-fixtures) ------------------------

def added_lines(diff: str) -> dict[str, list[tuple[int, str]]]:
    """path -> (line number, text) of each added line of a unified diff."""
    out: dict[str, list[tuple[int, str]]] = {}
    path, line = "", 0
    for raw in diff.splitlines():
        if raw.startswith("+++ ") and line == -1:
            path = raw[4:].rstrip("\t").strip('"')   # git ends a name holding a space with a tab
            path = path[2:] if path.startswith("b/") else path
        elif raw.startswith("diff --git "):
            line = -1   # the file's header until its first hunk: a content line '+++ x' is not a header
        elif raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            line = int(m.group(1)) if m else 0
        elif line == -1:
            continue
        elif raw.startswith("+") and path != "/dev/null":
            out.setdefault(path, []).append((line, raw[1:]))
            line += 1
        elif raw.startswith(" "):
            line += 1
    return out


def push_slug(repo: str) -> str:
    """owner/name of the remote a checkout's branch pushes to: its pushRemote, else its remote, else origin (not any
    remote: a private fork's public upstream is not where it pushes)."""
    branch = _git_out(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    remote = _git_out(repo, "config", f"branch.{branch}.pushRemote").strip() or \
        _git_out(repo, "config", f"branch.{branch}.remote").strip() or "origin"
    return public.repo_slug(_git_out(repo, "remote", "get-url", "--push", remote).strip())


def commit_public(repo: str, specs: list[str], every_tracked: bool,
                  untracked: list[str] | None = None) -> tuple[str, list[str]]:
    """(the public repo, the findings) of what a commit in ``repo`` would record when the remote its branch pushes to
    is a public repo: brain.public's line checks (denied terms, e-mail addresses, home folders, public.patterns) and
    file checks on the added lines of the index, plus ``specs`` or commit -a's changes, and the untracked files a git
    add stages (``untracked``: its paths; default ``specs``)."""
    cfg = config.load()
    if not public.public_repos(cfg):
        return "", []
    slug = push_slug(repo)
    if not public.is_public(slug, cfg):
        return "", []
    untracked = specs if untracked is None else untracked
    r = public.rules(cfg)
    diff = ["diff", "-U0", "--no-color", "--no-ext-diff", "--no-renames"]
    texts = [_git_out(repo, diff[0], "--cached", *diff[1:])]
    if specs or every_tracked:
        texts.append(_git_out(repo, *diff, "HEAD", "--", *specs))
    found: list[public.Finding] = []
    for text in texts:
        for path, lines in added_lines(text).items():
            found += [f for f in [public.file_finding(path, r)] if f] + public.scan_lines(path, lines, r)
    found += _untracked_findings(repo, untracked, r) if untracked else []
    return slug, list(dict.fromkeys(f.text() for f in found if f.check != "secret"))   # secrets: check_secrets


def _untracked_findings(repo: str, specs: list[str], r) -> list:
    """brain.public's file and line checks on the untracked files of ``specs``, each by its path in the repo (so
    public.allow matches from a subfolder too)."""
    top = _git_out(repo, "rev-parse", "--show-toplevel").strip() or repo
    found = []
    for name in _git_out(repo, "ls-files", "--others", "--exclude-standard", "--full-name", "-z", "--",
                         *specs).split("\0"):
        if name:
            found += [f for f in [public.file_finding(name, r)] if f]
            found += public.scan_lines(name, enumerate(_read_file(name, top).splitlines(), 1), r)
    return found


def check_public_commit(cmds: list[tuple[list[str], str]]) -> str | None:
    for c in _commits(cmds):
        d, what = c.repo, c.what
        slug, hits = commit_public(d, c.specs, c.every, c.untracked)
        if hits:
            more = f" and {len(hits) - 1} more" if len(hits) > 1 else ""
            return (f"{what} refused: {hits[0]}{more}; {slug} is a public repo (config.json public.repos): take it "
                    "out (a test names invented people and repos), or except the file in config.json public.allow")
    return None


# --- heredocs with a doubled backslash (a warning; the lesson les-brain-heredoc-backslashes) ----------------------

_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
_FEEDS = re.compile(r"(?:^|[|;&\s])(?:python[0-9.]*|py|node|perl|ruby|bash|sh|pwsh)(?:\s+-\S*)*\s*(?:-|<<)|"
                    r"(?:^|\s)(?:cat|tee)\b|\s>>?\s*\S")
HEREDOC_NOTE = ("brain guard, a warning (nothing refused): this heredoc holds a doubled backslash, and through the "
                "Bash tool on Windows a doubled backslash has arrived single (a regex that never matched, a \\n that "
                "became a newline, a replace that matched nothing). Write the file with Write or Edit instead, or "
                "check its bytes after (od -c, or run what it wrote).")


def heredoc_note(payload: dict, windows: bool | None = None) -> str | None:
    """The warning for a Bash call whose heredoc body holds a doubled backslash and whose first line writes a file or
    feeds an interpreter (python -, node -, cat > f, tee f), on Windows (``windows``: os.name == 'nt')."""
    if not (os.name == "nt" if windows is None else windows) or payload.get("tool_name") != "Bash":
        return None
    command = str((payload.get("tool_input") or {}).get("command") or "")
    first, _, body = command.partition("\n")
    m = _HEREDOC.search(first)
    if not m or "\\\\" not in body.split(f"\n{m.group(2)}", 1)[0]:
        return None
    return HEREDOC_NOTE if _FEEDS.search(first) else None   # python3 <<'EOF' and python - <<'EOF' alike


# --- branch names ------------------------------------------------------------------------------------------------

# The engine's default list of allowed branch names, config.json's branches.allowed replacing it: an entry is a prefix
# ending in / (feat/: feat/<slug>) or a pattern whose <slug>, <host> and <date> stand for BRANCH_SHAPES.
BRANCHES = ("claude/<slug>", "memory/<host>/<date>", "feat/", "fix/", "docs/", "chore/", "test/", "perf/", "ops/",
            "notes/", "research/", "release/")
BRANCH_SHAPES = {"slug": r"[a-z0-9][a-z0-9._-]*", "host": r"[a-z0-9][a-z0-9-]*", "date": r"\d{4}-\d{2}-\d{2}"}
BRANCH_FREE = ("main", "master")   # a default branch's name passes whatever the list
_PLACEHOLDER = re.compile(r"<([a-z]+)>")
CHECKOUT_NEW = ("-b", "-B", "--orphan")
SWITCH_NEW = ("-c", "-C", "--create", "--force-create", "--orphan")
WORKTREE_NEW = ("-b", "-B")
WORKTREE_VALUES = {"--reason"}
BRANCH_MOVE = ("-m", "-M", "--move", "-c", "-C", "--copy")
BRANCH_CREATE_OPTS = {"-f", "--force", "-t", "--track", "--no-track", "-q", "--quiet", "--recurse-submodules",
                      "--no-recurse-submodules", "--create-reflog"}   # the options a creation may carry; another one lists


def branch_rules() -> tuple[list[str], re.Pattern]:
    """(entries, their pattern): config.json's ``branches.allowed`` when it lists names, else :data:`BRANCHES`."""
    data = config.load().data
    given = (data.get("branches") or {}).get("allowed") if isinstance(data.get("branches"), dict) else None
    entries = [e for e in given if isinstance(e, str) and e] if isinstance(given, list) else []
    entries = entries or list(BRANCHES)
    alts = []
    for e in entries:
        e = e + "<slug>" if e.endswith("/") else e
        parts = _PLACEHOLDER.split(e)   # literal, name, literal, name, ..., literal
        alts.append("".join(re.escape(p) if i % 2 == 0 else BRANCH_SHAPES.get(p, BRANCH_SHAPES["slug"])
                            for i, p in enumerate(parts)))
    return entries, re.compile(f"(?:{'|'.join(alts)})")


def _new_value(args: list[str], names: tuple[str, ...]) -> str | None:
    """The value of the first option of ``names`` in ``args`` (-b NAME, -bNAME, --create NAME, --create=NAME), None
    when none is given; '' when it ends the arguments."""
    for i, a in enumerate(args):
        if a == "--":
            return None
        name, eq, val = a.partition("=")
        if a.startswith("--") and name in names:
            return val if eq else (args[i + 1] if i + 1 < len(args) else "")
        if a in names:
            return args[i + 1] if i + 1 < len(args) else ""
        if not a.startswith("--") and len(a) > 2 and a[:2] in names:
            return a[2:]
    return None


def _positional(args: list[str], values=()) -> list[str]:
    """The arguments that are not options (nor an option's value of ``values``), all of them after --."""
    out, i = [], 0
    while i < len(args):
        a = args[i]
        if a == "--":
            return out + args[i + 1:]
        if a.startswith("-") and len(a) > 1:
            i += 2 if a in values else 1
            continue
        out.append(a)
        i += 1
    return out


def _git_branch_new(args: list[str]) -> str | None:
    """The new name of a git branch command: NAME [START] or -m|-c [OLD] NEW; None for a listing, a deletion or an
    upstream change."""
    move = any(a in BRANCH_MOVE for a in args)
    if any(a.startswith("-") and a.partition("=")[0] not in BRANCH_CREATE_OPTS | set(BRANCH_MOVE) for a in args
           if a != "--"):
        return None
    pos = _positional(args)
    if not pos:
        return None
    return pos[-1] if move else pos[0]


def branch_creations(cmds: list[tuple[list[str], str]]):
    """(what, name, folder, gh's --repo or '') for each command that gives a branch its name: git checkout
    -b|-B|--orphan, git switch -c|-C|--create|--force-create|--orphan, git worktree add -b|-B (and its branch named
    after the folder when no -b or --detach is given and no branch has that name), git branch NAME and -m|-c [OLD]
    NEW, and gh pr create's head branch (--head, else the folder's current branch). --help and -h pass."""
    for words, d in cmds:
        prog = _prog(words[0])
        if prog == "git":
            parts = git_parts(words, d)
            if not parts or "-h" in parts[2] or "--help" in parts[2]:
                continue
            d, sub, args = parts
            name = None
            if sub == "checkout":
                name = _new_value(args, CHECKOUT_NEW)
            elif sub == "switch":
                name = _new_value(args, SWITCH_NEW)
            elif sub == "branch":
                name = _git_branch_new(args)
            elif sub == "worktree" and args[:1] == ["add"]:
                name = _new_value(args[1:], WORKTREE_NEW)
                pos = _positional(args[1:], WORKTREE_VALUES | set(WORKTREE_NEW))
                if name is None and len(pos) == 1 and not {"-d", "--detach"} & set(args):
                    implicit = os.path.basename(pos[0].rstrip("\\/"))
                    if implicit and not _git_out(d, "rev-parse", "--verify", "--quiet", f"refs/heads/{implicit}"):
                        name = implicit
                sub = "worktree add"
            if name:
                yield f"git {sub}", name, d, ""
        elif prog == "gh" and words[1:3] == ["pr", "create"]:
            args = words[3:]
            if "-h" in args or "--help" in args:
                continue
            head = _new_value(args, ("-H", "--head"))
            if head is None:
                head = _git_out(d, "rev-parse", "--abbrev-ref", "HEAD").strip()
            head = head.rpartition(":")[2]   # owner:branch
            if head and head != "HEAD":
                yield "gh pr create", head, d, _new_value(args, ("-R", "--repo")) or ""


def registered_repos() -> tuple[set[str], set[str]]:
    """(folders, owner/name slugs) of the registry's repos: each project's repos:, root and production checkouts, as
    their main checkouts' normalised folders (a registry read from a worktree resolves its root there), and the slugs
    of their origin remotes."""
    folders: set[str] = set()
    for p in projects.guarded():   # a project not loaded yet keeps its guards
        try:
            dirs = [r.path for r in projects.repos_of(p)] or [p.root]
        except projects.RepoError:
            dirs = [p.root, *p.production]
        folders |= {os.path.normcase(os.path.abspath(str(paths.main_checkout(x) or x))) for x in dirs
                    if os.path.isdir(x)}
    slugs = {public.repo_slug(_git_out(f, "remote", "get-url", "origin").strip()).lower() for f in folders
             if os.path.isdir(f)}
    return folders, slugs - {""}


def _in_registry(d: str, repo: str, known: tuple[set[str], set[str]]) -> bool:
    """Whether folder ``d`` is in a checkout of a registered repo (or one of its worktrees), or gh's --repo slug
    ``repo`` is one's."""
    if repo:
        return "/".join(repo.lower().split("/")[-2:]) in known[1]   # OWNER/REPO or HOST/OWNER/REPO
    main = paths.main_checkout(d)
    return main is not None and os.path.normcase(os.path.abspath(str(main))) in known[0]


def check_branches(cmds: list[tuple[list[str], str]]) -> str | None:
    """A branch named outside the allowed list (config.json branches.allowed, else BRANCHES) in a repo of the
    registry; None when every new name fits. A name the command does not resolve ($b in a loop) passes."""
    rules = known = None
    for what, name, d, repo in branch_creations(cmds):
        if name in BRANCH_FREE or re.search(r"[$`%(){}]", name):
            continue
        rules = rules or branch_rules()
        if rules[1].fullmatch(name):
            continue
        known = known or registered_repos()
        if not _in_registry(d, repo, known):
            continue
        slug = re.sub(r"[^a-z0-9._-]+", "-", name.lower()).strip("-._") or "x"
        first = next((e for e in rules[0] if e.endswith(("/", "/<slug>")) and e.count("<") <= 1), "")
        hint = f" (such as {first.rpartition('/')[0]}/{slug})" if first else ""
        fix = "rename the branch first (git branch -m NEW), then push it" if what == "gh pr create" else "name it so"
        return (f"{what} refused: the branch name {name} fits none of the allowed names (config.json "
                f"branches.allowed): {', '.join(rules[0])}; a <slug> is lowercase letters, digits, '.', '_' and '-'; "
                f"{fix}{hint}")
    return None


# --- the hook ----------------------------------------------------------------------------------------------------

def refusals(payload: dict, strict: bool = False):
    """(guard, check, reason, request) for each check that refuses the call, in order, lazily; ``check`` tells a
    guard's refusals apart in the ledger (the production guard's edit, git and shell-write; the owner guard's category;
    the power guard's machine, node, wake, cluster and bot); ``request`` is the action put to the owner (owner and
    power), else None. ``strict`` (the MCP server, brain.mcpguards): a check that raises refuses the call instead of
    letting the others judge it alone; a hook stays fail-open."""
    tool = payload.get("tool_name") or ""
    inp = payload.get("tool_input") or {}
    cwd = payload.get("cwd") or os.getcwd()
    if TERMINAL_TOOL.match(tool):
        tool = terminal_shell()
        cwd = _path(inp["cwd"], cwd) if isinstance(inp.get("cwd"), str) and inp["cwd"] else cwd
    if tool in EDIT_TOOLS:
        reason = check_production(tool, inp, [], cwd)
        if reason:
            yield "production", "edit", reason, None
        hit = check_owner(tool, inp, [], cwd)
        if hit:
            yield "owner", *hit
        return
    if SCHEDULED_TOOL.match(tool) or session_setting(tool, inp):
        hit = check_owner(tool, inp, [], cwd)
        if hit:
            yield "owner", *hit
        return
    command = (inp.get("command") or "") if tool in SHELL_TOOLS else ""
    if not command:
        return
    powershell = tool == "PowerShell"
    cmds = calls(command, cwd, powershell)
    for guard, check, run in (("production", "git", lambda: check_production(tool, inp, cmds, cwd)),
                              ("production", "shell-write", lambda: check_shell_writes(cmds, powershell)),
                              ("owner", None, lambda: check_owner(tool, inp, cmds, cwd, powershell, command)),
                              ("power", None, lambda: check_power(cmds, powershell, command)),
                              ("third-party", None, lambda: check_third_party(cmds, cwd, powershell, command)),
                              ("attribution", "attribution", lambda: check_attribution(command, cmds)),
                              ("public", "config", lambda: check_config(cmds)),
                              ("secrets", "secrets", lambda: check_secrets(cmds)),
                              ("markers", "markers", lambda: check_markers(cmds)),
                              ("public", "public", lambda: check_public(cmds)),
                              ("public", "commit", lambda: check_public_commit(cmds)),
                              ("branches", "name", lambda: check_branches(cmds))):
        try:
            out = run()
        except Exception as exc:  # one check's error lets the others run (and goes to ledger/errors.log)
            _log(guard, exc)
            if strict:   # the MCP server (brain.mcpguards): a check that cannot judge the call refuses it
                yield guard, check or "error", f"the {guard} guard could not judge the call ({type(exc).__name__})", None
            continue
        if isinstance(out, str):
            yield guard, check, out, None
        elif out:
            yield guard, *out


def terminal_shell() -> str:
    """The shell tool a Terminal panel command is judged as: PowerShell on Windows, else Bash."""
    return "PowerShell" if os.name == "nt" else "Bash"


def _log(guard: str, exc: Exception) -> None:
    try:
        from .capture import _log_error
        _log_error(f"guard {guard}", exc)
    except Exception:
        pass


def allowed() -> set[str]:
    """The guards the override lifts: names (production, owner...), guard:check pairs (owner:installer, power:cluster),
    or all."""
    raw = os.environ.get(ALLOW_ENV, "")
    names = {w.strip().lower() for w in raw.split(",") if w.strip()}
    return set(GUARDS) | names if "all" in names else names


def _record(payload: dict, guard: str, check: str, decision: str, reason: str, request: dict | None = None,
            case: str | None = None) -> bool:
    """Append the refusal, override or exception (``case``) to the guards ledger; True when written. A request for
    the owner, or an exception, creates the ledger folder: brain queue add --guard reads it there."""
    d = paths.ledger_dir()
    if os.environ.get("BRAIN_CAPTURE", "1") == "0":
        return False
    if request is not None or case is not None:
        d.mkdir(parents=True, exist_ok=True)
    if not d.is_dir():
        return False
    at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rec = {"at": at, "event": "guard", "guard": guard, "check": check, "decision": decision, "reason": reason,
           "tool": payload.get("tool_name"), "session_id": payload.get("session_id"),
           "tool_use_id": payload.get("tool_use_id"), "cwd": payload.get("cwd")}
    if request is not None:
        rec["request"] = request
    if case is not None:
        rec["case"] = case
        rec["what"] = {k: v for k, v in (payload.get("tool_input") or {}).items() if not str(k).startswith("_")}
    timing.append(d / f"guards-{at[:7]}.jsonl", rec)  # under the ledger's lock: every session's hook writes here
    return True


def queue_hint(request: dict, recorded: bool, tool: str) -> str:
    """How the agent puts the refused action in the owner's queue (config.owner_of): by its ledger ref, else with the
    exact command."""
    owner = config.owner_of()
    if recorded:
        return (f"; put it in {owner}'s queue with the exact command: brain queue add --kind action --guard "
                f"{request['ref']} [--item ID]")
    words = ["brain", "queue", "add", "--kind", "action", "--title", request_title(request), "--what",
             request["command"] or request["what"]]
    hint = _quote(words, "powershell" if tool == "PowerShell" else "bash")
    return f"; put it in {owner}'s queue: " + " ".join(hint.split("\n"))


def request_title(request: dict) -> str:
    """The title of the action a refusal puts in the queue: the power guard's check, else the owner's category."""
    label = {"machine": "Power", "node": "Cluster node", "wake": "Wake-on-LAN", "cluster": "Cluster",
             "bot": "The /power bot", "download": "Third-party script",
             "plugin": "Third-party plugin", "skills": "Third-party skill"}.get(request["category"]) or \
        f"{config.owner_of()}'s alone ({request['category']})"
    title = f"{label}: {request['what']}"
    return title if len(title) <= 100 else title[:99] + "…"


def main(stdin=None, stdout=None) -> int:
    payload = None
    try:
        payload = midsession.read_payload(stdin)   # UTF-8 bytes, whatever the console's codepage
        ok = allowed()
        rc_why, case = "", None
        if RC_TOOL.match(str(payload.get("tool_name") or "")):
            try:
                case, rc_why = remote_control(payload)
                # every decision is logged: a pass the ledger did not take is no pass
                if case and not _record(payload, "owner", "security-settings", "allowed", rc_why, case=case):
                    case, rc_why = None, "the pass could not be logged in the guards ledger"
            except Exception as exc:   # an error is no exception: the call goes on to its refusal
                _log("owner", exc)
                case, rc_why = None, "the session tree or the ledger could not be read"
        for guard, check, reason, request in refusals(payload):
            if case and check == "security-settings":   # one of the three exceptions, logged above
                continue
            if (guard in ok or f"{guard}:{check}" in ok) and check not in UNLIFTED:
                _record(payload, guard, check, "overridden", reason, request)
                continue
            if rc_why and check == "security-settings":
                reason += f" (none of the three exceptions: {rc_why})"
            recorded = _record(payload, guard, check, "denied", reason, request)
            if request is not None:
                tool = payload.get("tool_name") or ""
                reason += queue_hint(request, recorded, terminal_shell() if TERMINAL_TOOL.match(tool) else tool)
            cfg = config.load()
            reason = f"{config.claude(cfg)['plugin']} guard: {reason}. " + (
                f"No override: {check} is {config.owner(cfg)}'s alone, in the app." if check in UNLIFTED else
                f"Override ({config.owner(cfg)} only): {ALLOW_ENV}={guard} (or {guard}:{check}) in Claude Code's "
                "environment.")
            (stdout or sys.stdout).write(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}) + "\n")
            return 0
        note = heredoc_note(payload)
        if note:
            _record(payload, "heredoc", "backslash", "warned", note)
            (stdout or sys.stdout).write(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "additionalContext": note}}) + "\n")
    except Exception as exc:  # never break the session
        try:
            from .capture import _log_error
            _log_error("guard", exc)
        except Exception:
            pass
        try:   # but a session's security settings fail closed: an error there is a refusal
            p = payload if isinstance(payload, dict) else {}
            if session_setting(str(p.get("tool_name") or ""), p.get("tool_input") or {}):
                (stdout or sys.stdout).write(json.dumps({"hookSpecificOutput": {
                    "hookEventName": "PreToolUse", "permissionDecision": "deny",
                    "permissionDecisionReason": "brain guard: a session's Remote Control or permission mode is the "
                                                "owner's; the guard failed, so it refuses (ledger/errors.log)"}}) + "\n")
        except Exception:
            pass
    return 0
