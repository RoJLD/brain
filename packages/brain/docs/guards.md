# Runbook: the session-settings, third-party and conflict-marker guards, and the usage governor

Two PreToolUse hooks of the engine's Claude Code plugin keep the owner's say over how sessions run. Both are scripts,
not rules: they decide before the call, at zero token, and never break a session (an error lets the call through and
goes to `<BRAIN_HOME>/ledger/errors.log`, but for a session's Remote Control or permission mode, where it refuses,
for the desktop app's `archive_session`, where it asks the owner's card, and for a commit or push the public and secrets checks cannot judge: see « The public and secrets checks fail
closed »).

| Hook | Tools | Decides |
|---|---|---|
| `guard.sh tool` (`brain.guards`) | `mcp__*__set_remote_control`, `mcp__*__set_session_permission_mode`, the app's `set_setting` for a Remote Control or permission key | refuses, but Remote Control's three exceptions |
| `guard.sh tool` (`brain.guards`) | `mcp__ccd_session_mgmt__archive_session` | the archive case (a finished child, a hand-over's predecessor) at its automation level: allowed at auto, asked (the guard's card) at ask, refused at manual; else asks the owner's card (docs/automation.md « Enforcement ») |
| `governor.sh` (`brain.governor`) | `mcp__*__start_session`, `Agent`, `Task`, `Workflow` | asks at WARN, refuses at CRITICAL, past a cap, or on a stale reading |

Both are declared in `src/brain/adapters/claude/hooks/hooks.json`. A personal brain gets them with
`brain render --target claude --write` (or `brain sync`) into its own plugin, then its installer applies the plugin
(on Windows `install.ps1 -Apply`, the owner's).

## The owner's gestures, declared once

What only the owner runs, in their own terminal, is one list in the engine, `brain.gestures.GESTURES`: a subcommand
path of `brain`, the flags that make it the owner's, the owner guard's category, and where it is refused. The owner
guard (`brain.guards.check_owner`) reads it for every shell call and every command of a nested shell, wrapper or
launcher it sees through; `guard.sh`'s pre-filter starts Python for each; the command line (`brain.cli`) refuses the
ones it gates when an agent's session (`CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT` or `BRAIN_AGENT_SESSION` set) runs them
past the hook, through a script for instance. `tests/test_gestures.py` checks each gesture against the guard, the
pre-filter, the command line and this table, so a new gesture added to the list is refused everywhere at once. Each
one is also an entry of the automation catalogue ([automation.md](automation.md)), with its ceiling and floor.

| Gesture | Category | The guard | The command line in a session |
|---|---|---|---|
| `brain usage allow` | override | refuses | refuses (strict) |
| `brain handover root` | override | refuses, whatever runs it | refuses (its own check) |
| `brain schedule install --apply` | scheduled | refuses, queued for the owner | refuses (strict) |
| `brain ipc otel-headers` | keys | refuses, whatever runs it, queued | runs: Claude Code's `otelHeadersHelper` calls it |
| `brain vault open` | keys | refuses (strict), queued | refuses (its own check) |
| `brain vault drill` | keys | refuses (strict), queued | refuses (its own check) |
| `brain vault device init` | keys | refuses (strict), queued | refuses (its own check) |
| `brain vault device forget-previous` | keys | refuses (strict), queued | refuses (its own check) |
| `brain vault reseal --apply` (or `--identity`) | keys | refuses (strict), queued | refuses (strict; `--identity`: its own check) |
| `brain update` (but `--check`) | installer | refuses (strict) | refuses (its own check) |
| `brain uninstall --apply` | installer | refuses (strict) | refuses (its own check) |
| `brain queue apply` | actions | refuses (strict) | refuses (its own check) |
| `brain release apply` | release | refuses (never queued: the installer needs the owner's terminal) | refuses (its own check, after the installer's plan) |
| `brain release tag` | release | refuses (never queued: it needs the owner's terminal) | refuses (its own check, after its plan; `--json` too) |
| `install.ps1 -Apply` | installer | refuses when permissions.yaml declares `installer` | not the engine's |

A gesture's words follow `brain`'s own options (`--root`, `--project`, `--store`, or argparse's prefixes of them:
`brain --proj x usage allow`), with options and their values allowed between them (`brain usage --hours 2 allow`),
whatever runs it as the program: `brain`, its `.exe` or `.cmd`, `python -m brain` (`-mbrain`, `-Imbrain`, `-m
brain.cli`), `uv run brain`; a word that only names brain (`echo brain update`, `cp -r brain x`) runs nothing. A flag
counts by argparse's prefixes too (`--a`, `--app=x`). A loose gesture (`handover root`, `ipc otel-headers`) is found
anywhere in the command, its last word unresolved too (`brain ipc $x`), `--help` or not; any other is a read with
`--help` or `-h` before a `--`. A category
of the never-grantable list (keys, scheduled; installer when permissions.yaml declares it) makes the refusal an action
the owner can queue (`brain queue add --guard`); the others name the gesture and the owner's terminal.

Quoted or escaped words are read as the shell reads them (`'brain' "schedule" install --apply`, `b\rain sched\ule
install --ap\ply`, `ins''tall`, PowerShell's backtick, cmd's caret), and so are the variables the call itself sets to
one word (`x=install; brain schedule $x --apply`, `$a = '--apply'; brain schedule install $a`), through the launchers
the guards read (brain's `.exe` or `.cmd`, a venv's, `python -m brain`, `-mbrain`, `py -3.12 -X utf8 -m brain.cli`,
`uv run`, `uvx`, `pipx run`, `env`, `sudo`, `nohup`, `timeout`, `Start-Process`, `bash -c`, `cmd /c`, `iex`).
**Wide** (config.json `guards.gestures_wide: true`, off by default: refusals 0.6.0 adds): a word the guard cannot
resolve where a gesture's word or flag would stand may hold them (`brain schedule install $FLAG`, `brain schedule
$x`, `brain schedule $(echo install) --apply`, `brain $opts schedule install --apply`, `& $brain schedule install
--apply`, PowerShell's `@a` and `@('--apply')`; a word that may hold any gesture, `brain $x` or `brain "$@"`, is
refused as the first one), but an option's value (`brain usage --hours $h guard` passes); Python's inline code that
names brain and, as words, each of a gesture's words and one of its flags, in its code or its own arguments, drives it
(`python -X utf8 -c "from brain.cli import main; main(['schedule', 'install', '--apply'])"`, `$PY -c "...main(sys.argv[1:])"
schedule install --apply`, `schedule.install(reg, apply=True)`); and a call that clears an agent session's markers
(`brain.gestures.MARKER_NAMES`) is refused (check `override`), read from the call's own commands: an empty
assignment (`CLAUDECODE= ...`, `$env:CLAUDECODE = ''`), `unset`, `export -n`, `declare +x` or `env -u` of a marker,
of `${!CLAUDE*}` or of a word the guard cannot resolve in a call that names CLAUDE (`unset $v`, `unset $(compgen -e
| grep ^CLAUDE)`), `env -i`, PowerShell's removal of `Env:` items (`Remove-Item Env:CLAUDE*`, `Get-ChildItem
Env:CLAUDE* | Remove-Item`), .NET's `SetEnvironmentVariable` of a marker or a variable, `-UseNewEnvironment`,
`.Environment.Clear()`, inline code's `environ.pop`. Reading them passes (`$env:CLAUDECODE`, `CLAUDECODE=1 pytest`),
and so does a message or a search that only names the forms (`git commit -m "unset ..."`). The MCP server follows
the key too (off: it matches as 0.5.1 did).

**The lock under the guard.** The gestures that act check the session themselves: `brain schedule install --apply`,
`brain update`, `brain uninstall --apply`, `brain queue apply`, `brain release tag` and `apply`, `brain handover root` (and
`brain tidy --remote --apply`, the cockpit's actions) refuse to run while `CLAUDECODE` is set (`brain.detail.refused`,
`brain.gestures.lock_marker`), as 0.5.1 did, and so do `brain usage allow` and `brain vault reseal --apply` under
`guards.owner_strict` or `guards.gestures_wide` (the command line's gate, `brain.gestures.agent_session`: while
`CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT` or `BRAIN_AGENT_SESSION` is set), whatever launched them (a script, `python -m
runpy`, `xargs`, `find -exec`, inline code calling `schedule.install`); the guard's reading of the command line is the
earlier, advisory layer that queues the action for the owner. **Session markers** (config.json
`guards.gestures_session_markers: true`, optional, off by default: refusals 0.6.0 adds): both refuse while any agent
marker is set (`brain.gestures.MARKER_NAMES`: `CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT`, `BRAIN_AGENT_SESSION`, and the
variables Claude Code sets for each session, `CLAUDE_CODE_SESSION_ID`, `CLAUDE_CODE_HOST_SESSION_ID`,
`CLAUDE_CODE_CHILD_SESSION`, `CLAUDE_CODE_EXECPATH`, `CLAUDE_CODE_MESSAGING_SOCKET`, `CLAUDE_PID`; never a
configuration variable an owner may export, `CLAUDE_CODE_USE_BEDROCK` or the IDE's `CLAUDE_CODE_SSE_PORT`), so that
clearing one is not enough. `brain ipc otel-headers` has no such lock (Claude Code runs it as its
`otelHeadersHelper`, from a session's environment): the guard alone keeps it from a session, and
`guards.refuse_token_read` the token's file. What neither sees: a session that clears every marker by a means the
guard does not read (a script that rewrites its own environment; `sudo`, whose `env_reset` drops them, asks for
the owner's password), a variable the call sets to several words (`x="install
--apply"; brain schedule $x`, PowerShell's `$a = 'install', '--apply'`), `${x}` (the guards' reader splits a brace),
PowerShell's parenthesised arguments (`brain schedule install ('--apply')`), an option the guard takes for one with a
value (`brain usage --json $x`), the arguments `xargs`, `find -exec` or `parallel` add from their input, and code fed
by a heredoc or stdin (`python - <<EOF`). Inline code is matched by its words, a heuristic: a flag's prefix (`--ap`) or a positional `True` in a call is not read, and a code that names a gesture's words only to read it (`help(usage.allow)`) is refused under the key; the command's own check holds against the first two.

**Strict** (config.json `guards.owner_strict: true`, off by default): the refusals 0.5.1 adds to what the guard let
through before. At the guard: `brain vault reseal --apply`, and the gestures whose commands refuse themselves in an
agent's session already (`vault open`, `drill`, `device init` and `forget-previous`, `update`, `uninstall --apply`,
`queue apply`: refused before they run, `brain update`'s plan included); at the command line, its own refusal of
`brain usage allow`, `brain schedule install --apply` and `brain vault reseal --apply` in an agent's session (exit 2).
Without it, the guard refuses what 0.5.0 refused (`usage allow`, `handover root`, `schedule install --apply`, `ipc
otel-headers`), now however brain is run, and the release commands from the release that adds them (`release
tag` and `apply`); each command keeps its own check.

## The locked floor

The few rules no level overrides (`brain.floor`, the owner's R21): a line of the owner's rules (config.json `rules`)
that carries `<!-- lock -->` or `<!-- lock: ID -->` (the decision that locked it) is locked; Markdown shows nothing of
the marker (the lock's ID is ASCII letters, digits, `_`, `.` and `-`). The guard holds them with three refusals,
guard `floor`:

- `main`: a `git push` that writes `main` or `master`, read as git reads it: a refspec's destination (`HEAD:main`,
  `x:refs/heads/master`, `x:heads/main`), `HEAD` or `@` as the branch checked out, a deletion (`:main`, `--delete
  main`), every branch (`--all`, `--branches`, or a prefix git accepts: `--al`), a matching push (`:`), a refspec with
  `*` whose pattern takes main (`*`, `refs/heads/*:refs/heads/*`; not `refs/tags/*`); with no refspec, what git sends
  then: the remote's `remote.<name>.push`, else `push.default` (`matching` every branch, `upstream` the current branch
  to its `branch.<name>.merge`, `nothing` nothing, else the current branch), read from git's configuration and the
  command's own `git -c`; `--tags` alone and a negative refspec (`^x`) send no branch;
- `force`: a forced push: `--force`, `--force-with-lease`, `--force-if-includes`, `--mirror` or any prefix git takes
  of them (`--force-w`, `--mirr`), `f` in a group of short options (`-uf`, `-4f`; not after `o`, whose value is
  attached: `-oforce` is a push option), a refspec starting with `+`;
- `config`: what would lift the floor: an edit or a shell write of the config.json the guard reads, or of the pointer
  that finds it (`<BRAIN_HOME>/personal.json`), and a variable that chooses that file (`BRAIN_CONFIG`,
  `CLAUDE_BRAIN_DIR`, `BRAIN_PERSONAL`, `BRAIN_HOME`) set for later sessions (`setx`, the registry, Claude Code's
  settings, a shell profile). A worktree's own config.json is another file: a pull request still changes it; a
  `BRAIN_CONFIG` naming it never lowers the floor (« The environment » below).

The third line of the floor, no secret in a commit, is the secrets guard's already. They run under config.json
`floor.refuse: true` (off by default: refusals 0.5.1 adds) or `floor.only: true`; `BRAIN_GUARD_ALLOW=floor` (or
`floor:main`, `floor:force`, `floor:config`) lifts them, the owner's. git is asked only what a push needs: the branch
checked out for `HEAD`, `@` or no refspec, the configuration for no refspec; config.json is read once per call.

**Where the floor is read** (`brain.floor.effective`, review rounds 6 and 7): with no lock, from config.json (a file
that exists but cannot be read or parsed says on). On a locked machine, from the lock file's copy of the floor, the
authority: config.json is only compared to it, and a config.json whose floor differs (or another config.json than
the one the lock holds) refuses every call until the owner locks again. Round 5's committed reading (`HEAD`,
`origin/main`, a cache) is gone: a guard that parses the shell cannot stop a session that runs as the same user, and
round 7 showed any folder of the user's profile can be renamed through its parent, so the lock holds nothing there.

### The lock: `brain floor lock` (the owner's, elevated)

`brain floor lock` prints the plan: the floor it locks and the one locked now, what it writes, and the command line the
owner runs. `brain floor lock --apply` refuses to run without elevation (a session never elevates), with config.json's
floor off (a lock of no floor holds nothing), or lowering a locked floor without `--lower`. It writes three things,
each in a folder whose parents only an administrator writes:

- **the guard as a system component**, a new copy per lock under `<Program Files>/Brain/guard` (the folder HKLM names;
  `/opt/brain/guard`), named by its time (`g20261116-120000`): a copy of the interpreter (Windows; on POSIX the
  system's own Python, which root must own), of the guard's code and its dependencies with their metadata, the
  plugin's hook scripts, two launchers (`hook.py` for the hooks, `floor.py` for the owner's next elevated step), the
  bytecode of all of it (compiled by the copy's own interpreter during the apply: the hooks run as the user and cannot
  write `__pycache__` there; a guarded call takes about 0.5 s with it, about 2 s without) and `manifest.json`, the hash
  of every file, bytecode included;
- **Claude Code's managed settings**, `C:\Program Files\ClaudeCode\managed-settings.d\brain-floor.json`
  (`/etc/claude-code`, `/Library/Application Support/ClaudeCode`): `allowManagedHooksOnly: true`, so that no user,
  project, local or plugin hook runs ("Your user, project, local, and plugin hooks are blocked", hooks reference): a
  hook running beside the guard could otherwise return an `updatedInput` that replaces the call the guard judged. The
  plugin's own hooks are declared again from the copy, in exec form (`command` an absolute program, `args` its
  arguments: no shell, no PATH lookup). The PreToolUse ones (the guard, the governor, the read and wait hints) run the
  copy's interpreter on `hook.py` with `-X utf8 -I`; the judging ones, the guard and the governor, carry `"onFailure":
  "block"` (a hook that fails or times out then blocks the call; Claude Code v2.1.295 or later) and a deadline at 60 %
  of their timeout past which they refuse the call themselves. A hint never judges: a failing one lets the call
  through. The other events' hooks (the rules, the announcements, health, resume, memory, capture, budget) run the
  copy's scripts with the administrators' bash (Git for Windows under Program Files, `/bin/bash`). On Windows those
  scripts run the copy's interpreter and engine (`plugin/hooks/locked-python`, read first by `common.sh`, and a `.pth`
  that puts the copy's `site` on its path), never `BRAIN_PYTHON` or the user's venv; on POSIX they still run the
  user's engine. The copy carries the rendered plugin's `rules/` and `hooks/contract.txt`, so its `inject-rules.sh`
  injects the same rules as the plugin. With no such bash they are left out, and the apply says so.
  `"strictPluginOnlyCustomization": ["hooks", "mcp"]`: `hooks` stops the hooks in skills', custom commands' and agents'
  frontmatter, which `allowManagedHooksOnly` does not name ("Frontmatter hooks in skills, custom commands, and agents",
  settings reference); `mcp` stops loading MCP servers from `~/.claude.json` and `.mcp.json` (a stdio server's command
  starts with no tool call), and keeps managed and plugin servers. The brain's own MCP server comes from the rendered
  plugin's `.mcp.json` (`brain sync`), a plugin server, so it keeps working; servers the owner adds at user or project
  scope stop on a locked machine (declare them in the plugin's pack, or in the managed settings).
  `strictKnownMarketplaces` names the brain's own marketplace only (config.json `adapters.claude.source`, or the
  brain's folder holding `.claude-plugin/marketplace.json`; an empty list when neither): Claude Code enforces it "on
  marketplace add and on plugin install, update, refresh, and auto-update" (settings reference). "`disableAllHooks` set in user, project, or local settings can't disable those managed hooks"
  (hooks reference, "Disable or remove hooks");
- last, **the lock file**, `<ProgramData>/Brain/floor-lock.json` (the folder Windows names, not the environment's
  `ProgramData`; `/etc/brain`): the floor's copy, the config.json and `<BRAIN_HOME>` the guard reads, the copy in use,
  the paths it checks on each call, the manifest's hash, and the administrators' git (and bash) the guard runs.

**The ACL step** (config.json `floor.acl: true` under `floor.only`, off by default; Windows; `brain.flooracl`,
wi-brain-floor-acl-lock). A shell guard cannot read code it is not shown: a script, a program, inline code can still
write the account's own Claude Code files, whose `statusLine`, `apiKeyHelper` or `env` run outside any tool call. So the
apply, once the guard's copy holds and before the managed hooks and the lock file, denies the account the sessions run
as every change of them, whatever writes them:

- `~/.claude/settings.json` and `settings.local.json` (made empty, `{}`, when missing), the scripts directly in
  `~/.claude` (`statusline-command.sh`...), and the settings files and scripts of the `.claude` folder of the brain's
  own folder, of its registry's projects that exist on this machine, of the repos they span and of every worktree git
  lists for them: no write, append, attribute, delete, ACL or owner change (icacls' `WD,AD,WEA,WA,DC,D,WDAC,WO`, every
  right the per-call check reads);
- `~/.claude/hooks`, `skills`, `commands`, `agents` (made when missing) and `plugins` (their MCP servers and `bin/` run
  with no tool call), and a project's `hooks`, `skills`, `commands` and `agents` that exist, with everything in them:
  the same, inherited by every entry (`(OI)(CI)`) and given to each entry as an entry of its own (it comes before
  any allow, an explicit one made before the lock included);
- each project's `.claude` folder (made when missing, with its `worktrees`, where Claude Code makes a session's):
  nothing added to it and nothing removed through it;
- `~/.claude` itself: none of the locked paths removed through it (`DC`, and its ACL and owner); Claude Code still adds
  and removes its own files there (sessions, todos).

The rights are named one by one, and the deny entries are written with that exact mask through the Win32 API
(`brain.flooracl.deny_exact`), never by icacls' `/deny`, which adds `SYNCHRONIZE` to the entry (CI's elevated runner:
the locked settings.json no longer read): a read asks `SYNCHRONIZE` and `READ_CONTROL`, and Claude Code must still read
the files; the apply's check refuses a deny holding a right reading needs. Each path is opened once, by itself
(`FILE_FLAG_OPEN_REPARSE_POINT`: a link or a junction is refused on its handle, never followed), its owner made
Administrators (the account, as owner, would keep `WRITE_DAC`; its normal token holds Administrators as deny-only) and
its deny put first in its DACL, on that handle (`SetKernelObjectSecurity`), with nothing computed for or propagated to
what it holds. The elevated step often runs as the account it denies, whose deny then holds the step too, and an
`OWNER RIGHTS` entry (which Python's `mkdir(mode=0o700)` writes) takes the owner's implicit `WRITE_DAC` away: when
`SetNamedSecurityInfo` wrote a tree root's inheritable deny into every entry, the walk could no longer write an entry's
own ACL (CI's elevated runner, error 5). So each entry is written before any deny of the account lands on it, and the
step asks its token's backup and restore privileges (an elevated administrator's, off until asked) to open a path
already denied (a relock over a lock, the unlock); a deny already there is not written again. `~/.claude` comes first,
so that nothing under it is renamed meanwhile. No command takes a wildcard nor recurses (icacls followed a link in a
path's middle components); the apply refuses, before anything runs, a path that is a link or a junction, sits under one
or holds one; and a tree is walked top down once its root is denied (nothing is added to it or removed through it from
then on), each entry owned by the administrators and given a deny of its own before its own entries are listed, a
link met there refusing the step. The unlock removes the account's deny entries the same way (`brain.flooracl.undeny`,
a tree entry's inherited copies too), never by icacls' `/remove:d`, which an entry's own deny refused while `/C`
reported it done. A path still goes through its parents by name: a
session that renames `~/.claude` or a project's `.claude` through a parent it owns while the elevated step runs could
turn a folder on its way into a junction once checked. So each handle's final path (`GetFinalPathNameByHandleW`) must
be the path as written, or nothing is written (with the privileges asked, a write sent elsewhere could reach a system
file); and the commands only make the administrators an owner and add a deny for the account (never a reset, never an
owner given away), so no folder is ever opened to the account. A reparse point that is no name surrogate (a
compressed, deduplicated or cloud file) is the file itself and is held.
Every path the plan names must already belong to the account (or to the administrators, a previous lock's): a
registry entry or a worktree pointing at another account's folder refuses the plan. The account is a SID the plan reads in a normal
terminal of the account (`brain floor lock` prints the elevated command line with `--account <SID>`: the elevated step
may run as another administrator); it must look up as a user's (a group, a well-known SID, a malformed one is
refused), and its profile is read from HKLM's `ProfileList` (none there: refused, never guessed). A registry that does
not load stops the plan (a project's worktrees are read from its `.git/worktrees`, no git run), and the plan names
any command a held setting runs from a path the step does not hold, its `env`'s `BASH_ENV`, `CLAUDE_ENV_FILE`,
`CLAUDE_CODE_SHELL_PREFIX` and `NODE_OPTIONS` included (move it under a held folder; a script named without a folder
runs from wherever a session is). The apply then checks every path (present, no link, owned by Administrators, SYSTEM or
TrustedInstaller, its deny entries for the account holding every right its kind needs; every entry of a tree, none of
whose own entries lets anyone else write ahead of the deny it inherits) and records them in the lock file's `acl`.

On each call the guard (`brain.floor.unlocked`) then refuses every call while one of them is missing, a link, within
the session's reach or owned by another than the administrators (a folder renamed away with its parent's rights and
made again, its DACL read-only for itself: a rename of `~/.claude` or of a project's `.claude` is detected this way,
not prevented, and what such a folder's settings run with no tool call runs until then), while the session's account
cannot be read or is not the one the lock denies, while `CLAUDE_CONFIG_DIR` or `USERPROFILE` (node's home on Windows)
points Claude Code elsewhere than the profile the lock holds, and while config.json's `floor.acl` is not the locked one. A step that fails
gives back what it added (the previous lock, restored, keeps its entries); a relock without `floor.acl`, for another
account (whose shared paths keep the administrators as owner) or with fewer paths gives the previous lock's back once
the new one holds. `brain floor status` says whether each is held; `brain floor unlock --apply` lifts the account's deny entries
first, trees first (each entry) and `~/.claude` last (a path gone, a link or one no longer owned by Administrators left
alone and said); when one fails, the lock file and the managed hooks stay, the failures are named and an unlock
again ends it. The ownership stays the administrators': an
elevated step never gives a path's owner away (a folder swapped in for one of them would be handed to the account);
the account keeps the rights it inherits and takes the ownership back from its own terminal if it wants (`takeown /f
<path> /r`); with a lock file that
cannot be read it needs `--account <SID>` and rebuilds the paths from config.json.

Before the apply, sign out and in again (or restart): a process that opened one of these files before the lock keeps
the rights it opened it with. While locked, Claude Code's own writes there fail (an "always allow" saved to
`settings.local.json`, a plugin or a skill installed or updated, a project's new `.claude` file brought by a pull): the
owner changes them after unlocking. Not held: a worktree made after the lock, a project added to the registry after it (lock again), a
command a setting names outside the held folders (the plan says which), a repo's `.git/hooks`. `floor.acl` counts on
Windows only: a POSIX machine that shares the config.json locks without it.

Each folder is given to Administrators (root): its own ACL reset, its inheritance cut with Administrators and SYSTEM
full and the users read and run (from here no child gains the user's rights), the owner set on the whole tree, then
every child's ACL reset to what it inherits (an entry a session added before the cut goes); POSIX `chown -R 0:0`,
`chmod -R u=rwX,go=rX`. A session may create a folder in ProgramData: the apply empties `Brain` after the cut. It then
checks every file it wrote (owner Administrators, SYSTEM or TrustedInstaller, no allow entry that grants a write right
to anyone else, no link or junction) and keeps the lock file only when all hold. A step that fails puts the managed
file and the lock file back as they were, together (the previous lock and its untouched copy; or no lock, and a
floor-only machine then refuses every call until an apply completes), and removes the new copy. Once the new copy
holds, the older ones are removed, except the one the apply's own interpreter runs from (the next lock removes it).

The locked guard takes nothing from the environment a session sets: `hook.py` puts the copy's own folders first
(`python -I`), takes `BRAIN_CONFIG` and `BRAIN_HOME` from the lock file, drops `BRAIN_PYTHON`, `CLAUDE_PLUGIN_ROOT`,
`CLAUDE_BRAIN_DIR` and `BRAIN_PERSONAL`, sets `NoDefaultCurrentDirectoryInExePath` and runs the git the lock names (a
`git.exe` in the hook's working directory never runs; `brain.floorhook`, `brain.floor.git`). A network or device path
(`\\host\share`, `//host/share`, and every `\\?\`, `\\.\`, `//?/` path but a drive letter's: `GLOBALROOT`, a volume)
is judged as written, without resolving it (an unreachable host took 21 s); a form the pattern misses still meets the
deadline, then `onFailure: block`. Wherever a lock
file exists, `BRAIN_GUARD_ALLOW` lifts none of the floor's checks (`floor`, `floor:*`, `all`), and the refusal says so:
`brain floor lock --lower` and `brain floor unlock`, elevated, alone change a locked floor.

Claude Code reads its managed sources first-wins: server-managed settings, then (Windows) an HKLM policy, then the
managed files; when one of the first two holds a policy the files are skipped, and the lock's hooks with them. `brain
floor status` says whether the managed hooks are in force (an HKLM `SOFTWARE\Policies\ClaudeCode` key on this machine:
not in force). Where they are not, the plugin's own `guard.sh` still judges each call with the user's engine (it no
longer steps aside for the managed file; where they are, `allowManagedHooksOnly` keeps it from running).

What the guard checks on each call (`brain.floor.unlocked`), under `floor.only` and wherever a lock file exists: the
lock file exists and reads; its folder and file, the guard's folder, manifest, launchers and interpreter, and the
managed file exist and are out of the session's reach; the manifest is the one the lock hashed; config.json is the
one the lock holds, with the floor it holds. "Out of reach" is the session token's effective access read from the
path's security descriptor (AccessCheck: no write, append, delete, delete-child, ACL or owner right); POSIX: owned by
root and not writable. Anything else, and a floor-only machine with no lock, refuses every call the guard judges:
"the floor is not locked: ...; every call is refused until the owner runs brain floor lock". `brain floor status`
also walks every file of the lock and compares the guard's files to the manifest; run it in a normal terminal (an
elevated one reaches everything).

- **The owner's elevated step** starts no shell: the plan prints one command line to paste in Win+R (Start > Run) and
  run with Ctrl+Shift+Enter (as administrator): the interpreter by absolute path with `-I`, then, once the guard is
  installed, the copy's `floor.py lock --apply --wait` (`--wait` keeps the window on its result until Enter). Not from
  an elevated PowerShell window: the window loads the user's profile and modules (`PSReadLine` from
  `Documents\WindowsPowerShell\Modules`), which a session can write, before any `-NoProfile` command runs. The first
  lock runs the engine in `<BRAIN_HOME>/venv` (`python.exe -I -m brain floor lock --apply --wait`), which a session
  can write: update it from your own terminal first, and close every Claude Code session before any apply (a process
  keeps what it opened before the lock). POSIX: `/usr/bin/sudo` and the interpreter's absolute path.
- **Changing a locked machine**: a change of config.json's floor refuses every call until the owner locks again from
  the copy (`brain floor lock` prints its command line). That line is printed by the user's engine, which a session
  can change: check that it starts with the `interpreter` the lock file names (`<ProgramData>/Brain/floor-lock.json`)
  and runs that copy's `floor.py`. An engine update changes nothing the locked guard runs until
  the owner locks again with the new engine, from its venv (the first lock's command line, the venv updated from the
  owner's own terminal, sessions closed). The personal brain's checkout and its worktrees stay the user's: nothing
  there is locked.
- `brain floor unlock` prints its own command line (the copy's `floor.py unlock --apply --wait`). `--apply` (elevated)
  removes the lock file and the managed file together (both put back if either fails), then the guard's copies, except
  the one its own interpreter runs from (removed by hand once the window is closed, or by the next lock); the plugin's
  guard then judges again.

What else the floor holds (`brain.floorguard`; reviews 2 to 5 closed classes, not spellings). Every check reads each
command a call runs, past a wrapper, a launcher, a nested shell or the shell's reserved words (`timeout`, `env`,
`nohup`, `bash -c`, `cmd /c`, `pwsh -Command`, `eval`, `if ...; then`, `do`, `!`: `brain.guards.actions`); a payload
the floor cannot read is refused (`eval` or `-c` of a variable, `Start-Process` of git or a shell with
`-ArgumentList`, `xargs` running git but a read or what writes files, a shell function the call defines, a push
whose remote or refspec holds `$(`, a backtick or a variable). git options and subcommands that write a file or run a
program are refused (`--output`, `-O`, `--upload-pack`, `--receive-pack`, `--exec`, `--ext-diff`, `--textconv`,
`rebase -x`, `bisect run`, `submodule foreach`, `difftool -x`, `filter-branch`, `apply --unsafe-paths`), and so is
`git config` of `core.*`, `filter.*`, `diff.*`, `credential.*`, `gpg.*`, editors and pagers, or into another file
than a repo's own (`-f`). A settings file of Claude Code changes by Write or Edit only (any copy, move, redirect or
patch onto it is refused, and round 6: git that would write one, an archive that holds one, a link onto one); the
interpreter that runs the guard is kept with its base installation (pyvenv.cfg's `home`, `sys.base_prefix`), the
user site and any `sitecustomize.py`, `usercustomize.py` or `.pth`; an environment write through WMI or CIM
(`Win32_Environment`, `wmic environment`) and an ACL, ownership or mode change of a kept path or of any folder above
one (`icacls`, `cacls`, `takeown`, `attrib`, `Set-Acl`, `chmod`, `chown`, `setfacl`: a deny on `~/.claude` is
inherited by `guard.sh`, whose hook then exits 126, a non-blocking error) are refused.

Round 6 (the classes the lock does not cover, guard-lifts):

- **Reserved words**: `time -p` and `time --` are read through (round 5 left `-p` as the program, which hid any
  command from every guard, the power guard's too), and so are `coproc CMD` and `coproc NAME { ...; }`.
- **Claude Code's settings written by git**: a git command that writes the work tree (`checkout`, `restore`,
  `reset`, `merge`, `pull`, `switch`, `stash`, `cherry-pick`, `revert`, `rebase`, `am`, `apply`, `read-tree`,
  `checkout-index`, `worktree add`, `update-index`...) is refused when it names a `.claude/settings*.json` (a
  pathspec, `--cacheinfo`), when `update-index` reads its input, or when the index, a commit it names or reads by
  default (`HEAD` for reset, the last stash, the upstream for pull), or a patch it applies holds a settings file that
  differs from the work tree's (`git diff --name-only` on that pathspec). An extraction (`tar -x`, `unzip`,
  `Expand-Archive`, `7z x`) is refused when its archive holds one, or when the floor cannot list its members (its
  input, 7z, a compression it does not read). A link onto one (`mklink`, `ln`, `New-Item -ItemType SymbolicLink`) is
  refused, in any shell's payload.
- **Functions and aliases**: a function of any body form (`f() ( ... )`, `f() [[ ... ]]`, `f() if ...`) and an alias
  the call defines or turns on (`alias`, `shopt -s expand_aliases`, `Set-Alias`, `New-Alias`) are refused.
- **Assignments**: only git's `-m`/`--message` and gh's `-m`, `--body`, `--title`, `--notes` (`-b`, `-t`, `-n`) take
  prose (`declare -x -t "NAME=..."` is read); `allexport` anywhere in a `set` or `shopt -o` list, `for NAME in`,
  `select NAME in`, `getopts ... NAME`, `mapfile`/`readarray NAME`, and PowerShell's `Get-Item Env:X | Rename-Item
  -NewName NAME`, `New-Item -Name NAME`, `$psi.EnvironmentVariables['NAME']` are assignments.
- **git running a program**: `protocol.*`, `submodule.*`, `interactive.*`, `browser.*`, `web.*`, `man.*`,
  `instaweb.*`, `sendemail.*`, `init.*`, `ssh.*`, `trailer.*` and `hook.*` join the refused keys, and so do an
  `ext::` or `fd::` URL and `GIT_ALLOW_PROTOCOL`. An ordinary repo's keys pass (`core.autocrlf`, `core.longpaths`,
  `core.filemode`, `core.ignorecase`, `core.eol`, `core.quotepath`, `core.safecrlf`, `diff.tool`, `merge.tool`,
  `branch.<b>.description`, `credential.helper` set to `manager`, `store`, `cache` or another usual helper), so do
  `git format-patch -o` and, the committed reading gone, `git fetch origin main:main` and `git branch -f`.

Round 7 (the same classes, new spellings; on any machine with the floor on):

- **Pipelines and .NET**: a path piped into a cmdlet that writes, moves or removes (`Get-Item X | Rename-Item`,
  `Get-ChildItem X | ...`, `'X' | Remove-Item`, `Set-Content`, `Add-Content`, `Set-ItemProperty`...) is that cmdlet's
  `-Path`; a call to `.MoveTo(`, `.CopyTo(`, `.Replace(`, `.Delete(` or `.SetAccessControl(` is refused when the call
  names a kept path, a folder above one, a settings file or git's configuration (`$env:USERPROFILE`, `$HOME` and `~`
  read as the home). `guard.sh`'s pre-filter starts Python for those methods.
- **The environment through COM and .NET**: `WScript.Shell`'s `Environment(...)`, a `RegistryKey`'s `SetValue`,
  `CreateSubKey`, `DeleteValue`, `OpenSubKey(..., $true)`, and the `Environment` key piped into a property cmdlet,
  whatever the statement.
- **Spellings**: the `Env:/` provider, PowerShell's `${function:f} =`, `Set-Item`/`New-Item` on the `function:` and
  `alias:` drives, bash's `BASH_ALIASES[...]=` and `set -o posix` (POSIX mode expands aliases); `imap.*` joins the
  refused git keys, and `credential.helper` passes only as a usual helper and its `--options` (git runs the value
  through the shell).

- **git configuration**: any git command given configuration by its command line (`-c`, `--config-env`) is refused
  (check `config`), so is a global option outside `brain.floor.GIT_GLOBAL_OK` (`--git-dir`, `--work-tree`,
  `--attr-source`...) and a subcommand that is neither git's, a `git-<name>` on PATH nor an alias; `git config`
  setting `alias.*`, `include.path`, `includeIf.*.path`, `remote.*`, `push.*` or `url.*`, `git remote add --mirror`,
  and a write of git's configuration files. An alias is read as what it runs, an alias of an alias too (ten levels);
  a shell alias (`!`), or one that starts with an option, is refused.
- **The environment**: a variable of `brain.floor.watched` (git's that change its configuration, repository or
  programs, `HOME`, `XDG_CONFIG_HOME`, `BASH_ENV`, `SHELLOPTS`, `BASHOPTS`, `PATH`, the Brain's own `BRAIN_*`, and
  Claude Code's that choose its settings or plugin) assigned in any form (`NAME=`, `NAME[0]=`, `export`, `declare`,
  `printf -v`, `read`, `env`, `${NAME:=}`, `(( NAME = ))`, `set -a`, `$env:`, `${env:}`, the `env:` provider and the
  `env:` drive as the location (`Set-Location Env:`), `SetEnvironmentVariable`, `Start-Process -Environment @{...}`,
  and inline code's `os.environ[NAME] =`, `os.putenv`, `process.env.NAME =`, `$ENV{NAME} =`), its name read as bash
  reads it too (`BRAIN_\HOME`, `$'\x42RAIN_HOME'`, `$"BRAIN_HOME"`: `brain.floorenv.unescaped`), and any assignment
  whose name the guard cannot read, are refused; only an `echo`'s or
  `printf`'s quoted words and the value of `-m`, `--message`, `--body` or `--title` are prose, never an `export` or
  `env` argument. On Windows, where a native program reads a variable's name in any case, the names are read in any
  case (`brain_home=` is `BRAIN_HOME`), `HOME` and `PATH` included (see Limits).
  `GIT_EDITOR=true`, `GIT_TRACE`, `ENV=` and `CLAUDE_CODE_*` pass. A command's assignment reaches that command and its children only, but a child may be a
  nested Claude Code whose hooks inherit it, so the `BRAIN_*` names are watched as a class and a name passes only
  where `brain.floor` says why it lifts and redirects nothing (wi-brain-floor-watched-vars):
  - `brain.floor.READ_PATH_VARS`, in any form: `BRAIN_STRICT` (how strictly a check reads its files), and the read
    hint's, the wait hint's and the budget reminder's switches;
  - `brain.floor.SCRATCH_VARS`, `BRAIN_NOW` and `BRAIN_FAULT`, while the guard's own home is the default one: the
    engine honours them on a scratch home alone (`brain.faults.scratch`), and `BRAIN_HOME` stays watched;
  - `brain.floor.WORKTREE_VARS`, `BRAIN_CONFIG` and `BRAIN_PROJECTS`, as one literal absolute path inside a worktree
    of the repository that holds the config.json the guard reads (the folders `git worktree list` gives, the main
    checkout first; a prunable one is none; links resolved): `BRAIN_PROJECTS=<worktree>/projects.yaml brain audit
    --diff`, `export BRAIN_CONFIG='<worktree>/config.json'`, `env NAME=...`, PowerShell's `$env:BRAIN_CONFIG =
    '<worktree>\config.json'`. The value is single-quoted, double-quoted with nothing a shell expands in it, or bare
    path characters (no backslash: bash drops it; Git Bash's `/e/x` is `E:/x`); a relative path, a variable, a
    substitution, `~`, a network path, another form (`declare -n`, `read`, `printf -v`, `${env:...}`, `Set-Item`)
    stays watched. And the guard never lowers its floor for `BRAIN_CONFIG` (`brain.config.anchored`): when it names
    another file than the config.json found without it, the guard holds both floors (either on is on, an unreadable
    one is on), keeps both files and both core plugins, and `guard.sh` reads both when it cannot run Python; so a
    nested session started with `BRAIN_CONFIG` pointing at a worktree's config.json, which the session may write,
    still holds the owner's floor.
  Every other `BRAIN_*` name stays watched: `BRAIN_GUARD_ALLOW`, `BRAIN_PYTHON`, `BRAIN_HOME`, `BRAIN_PERSONAL`,
  `BRAIN_AGENT_SESSION`, `BRAIN_IPC_TOKEN_FILE`, `BRAIN_ROOT`, a name the engine does not know yet. `guard.sh`'s
  pre-filter starts Python for every shape of a watched assignment (a watched name given a value, a builtin that sets
  a variable, `allexport`, `set -a`, `env:`, `Environment`), its quotes, escapes and carets dropped. Any
  write of the registry's `Environment` key is refused, whatever the value's name (`Set-ItemProperty`,
  `New-ItemProperty`, .NET's `Registry`, `reg add` or `import`). `hooks.json` runs `guard.sh` under `bash -p`, which
  reads no `BASH_ENV` nor `SHELLOPTS`.
- **Copies and archives**: a copy is judged on the path it writes (the destination, or the destination plus the
  source's name: `cp`, `rsync`, `robocopy` with files, `Copy-Item`, `xcopy`); a recursive copy into a kept file's
  folder (the checkout, BRAIN_HOME) or onto a folder above a kept path, and an archive extracted into a kept file's
  folder (`tar -x -C`, `unzip -d`, `Expand-Archive`, `7z x`), are refused.
- **The plugin that runs the guard**: a write, a removal or a move under `~/.claude/plugins` or
  `$CLAUDE_PLUGIN_ROOT`, and `claude plugin disable`, `uninstall` or `marketplace remove` of the core plugin, are
  refused.
- **What git pushes**: `remote.<name>.mirror` is a forced push, a symbolic branch is the branch it points at;
  `git symbolic-ref` making a branch symbolic (`refs/heads/...`; pointing `HEAD` passes), `git send-pack`, and the
  code host's API writes of main's ref (`gh api` on `git/refs` or `merges`, short options glued or not; a GraphQL
  `updateRef`, `createRef`, `deleteRef`, `createCommitOnBranch` or `mergeBranch`) are refused.
- **The checkout that holds config.json**: only reads run there (`brain.floor.CHECKOUT_SAFE`: reads, `fetch`,
  `push` judged on its own, `worktree`, `branch`, `tag`; `git config` and `git remote` that only read), and a pull of
  its upstream (`brain.floorenv.pull`): `git pull`, `git pull --ff-only`, `git pull origin refs/heads/main`, with
  the options of `brain.floorenv.PULL_OPTS` only (`--ff-only`, `--ff`, `--no-ff`, `--rebase`, `--no-rebase`,
  `--autostash`, `-q`, `-v`, `--stat`...; no strategy, interactive rebase, submodules or unrelated histories). The
  pull is judged by what it brings, read from git's configuration when it is judged, whoever set it (`git branch
  -u`, `git push -u` from a worktree that shares the configuration): a branch checked out whose upstream is `main` or
  `master` of a remote whose URL is no local path (`file:`, a folder, a drive), and a remote and branch named by the
  command, if any, that are that upstream, the branch by its full name (`refs/heads/main`: git reads a bare `main`
  as the remote's tag `main` first, which a session may push). So a pull there brings only what was merged into main
  by a pull request.
  In any worktree of that repository (the same git common folder), a `git remote` that writes (`add`, `set-url`,
  `rename`, `remove`...) is refused: the worktrees share the remotes the checkout pulls from. A commit there stays
  refused. A removal or a move of it, or of a folder that holds it or the guard's
  interpreter (`rm`, `mv`, `Remove-Item`, `Move-Item`, `Rename-Item`, `robocopy /MIR` or `/PURGE` onto it), is
  refused; a mover's target (`-t`, `-Destination`) is no source, and a write into such a folder (`cp x ~/`,
  `tar -C ~`) is no removal and passes.
- **What stops the guards**: `BRAIN_PYTHON`, `PYTEST_CURRENT_TEST`, `CLAUDE_CONFIG_DIR`, `BRAIN_CONFIG`,
  `CLAUDE_BRAIN_DIR`, `BRAIN_PERSONAL`, `BRAIN_HOME`, and `HOME`, `USERPROFILE` and `PATH` where they are set (never
  where they are read: `$HOME`, `${HOME}`), set for later sessions; Claude Code's `disableAllHooks` and an
  `enabledPlugins` entry that turns the core plugin off; a write into `<BRAIN_HOME>/venv`. Names are read as the shell
  and JSON read them (`brain.floor.unspelled`: quotes, carets, a concatenation and JSON's unicode escapes taken out),
  and `setx`, a registry `Environment` value or `SetEnvironmentVariable` whose name is not a plain word is refused.
  Paths are resolved first (an NTFS stream's name, a junction, a link).
- **Failing closed**: while the floor is on, or config.json cannot be read, a guard that fails refuses the call.
  `guard.sh` finds config.json as `inject-rules.sh` does (`common.sh`'s `brain_config` and `floor_setting`), and
  reads the floor as on wherever a lock file exists (`<ProgramData>/Brain`, `C:/ProgramData/Brain`, `/etc/brain`;
  round 6: the working file alone could be the session's); when Python cannot judge the call (no
  `<BRAIN_HOME>/venv`, an import error, an exit other than 0) it refuses every call it would have sent to Python,
  and it never runs PATH's Python while the floor is on, nor a `BRAIN_PYTHON` whose file name holds no python.
- Under `guards.owner_strict` the owner guard refuses `BRAIN_PYTHON`, `PYTEST_CURRENT_TEST`, `CLAUDE_CONFIG_DIR` and
  `disableAllHooks` on every machine; the override's own name is read the same way (quotes, carets, escapes) always.

**Limits** (a guard of the command line cannot be complete). Three classes, three answers:

- **Floor-lift** (a session changes the floor's own settings, or what the guard reads them from or runs): closed by
  the lock on a locked machine, whatever runs the change, a launcher included: the floor's copy, the guard and its
  hooks are in folders whose parents only an administrator writes, and config.json is only compared to the copy. On
  a machine that is not locked (`floor.refuse` without `brain floor lock`), the floor is the parser's alone: a write
  it does not read (a launcher below, code it does not read) lifts it, and so does `BRAIN_GUARD_ALLOW` set for later
  sessions by such a write. A floor-only machine is never in that state: with no lock, every call is refused.
- **PowerShell's .NET writers on an unlocked `floor.refuse` machine**: a literal `[IO.File]::...` onto a kept path is
  read; a member reached through anything else (a parenthesised type, a variable, `$_`, `-as`, `GetMethod`,
  `InvokeMember`, `UnderlyingSystemType`, a member named by an expression `::(...)`, a method group's `.Invoke(`) is
  refused as a class whatever its path. It stays best-effort: PowerShell has
  more ways to name a type than a parser reads, so a config.json rewritten floor-off is caught only by the lock (it
  differs from the lock's floor and every call is refused) or by the backstop below.
- **Push to main and force-push**: the code host's branch protection on main is the backstop (since 2026-11-14 on
  the engine repo: no force-push, no deletion, a pull request and the required checks, for admins too) for what the
  guard does not read: the code host's other writers (the contents API, other GraphQL mutations, `gh repo sync`, a
  raw HTTP call), git's transports beyond `git push` and `git send-pack`, a symbolic branch made before the floor was
  on and pushed by a refspec with a colon.
- **Guard-lift** (a session stops the guard for itself or later sessions, without touching the floor's files): on a
  locked machine the managed hooks hold while Claude Code reads the managed files (no server-managed settings or HKLM
  policy first): `allowManagedHooksOnly` blocks every other hook, no `disableAllHooks` of the user's or a project's
  turns them off, a hook that fails or times out blocks the call (Claude Code v2.1.295 or later; an older one lets it
  through), and the plugin folder is not what runs them. A SessionStart hook can change every later Bash call of its
  session (`CLAUDE_ENV_FILE`: "Each Bash command runs the file's contents as shell code before the command itself",
  hooks reference): on Windows the managed ones run the copy's engine; on POSIX they run the user's, code a session may
  have written. Settings `env` reaches every command after the guard judged it (`BASH_FUNC_git%%` redefines git in the
  Bash tool's bash): while the floor is on, a settings write adds only the names of `brain.floor.ENV_ALLOWED`, and adds
  or changes only the top-level keys of `brain.floor.SETTINGS_ALLOWED`, each with its reason (`apiKeyHelper`,
  `otelHeadersHelper`, `awsAuthRefresh`, `awsCredentialExport`, `gcpAuthRefresh`, `statusLine`, `fileSuggestion`,
  which Claude Code runs as shell command lines with no tool call, are refused, and so are the marketplaces and any
  `enabledPlugins` change but turning a plugin off);
  a write is judged by the file it reaches, not by its path: its NTFS stream dropped, links and junctions resolved,
  and a file with more than one name (a hard link) compared by identity (`st_dev`, `st_ino`: the volume serial and
  file index on Windows) with the kept files and the settings files of the home, the launch folder
  (`CLAUDE_PROJECT_DIR`), every folder of the working directory's parent chain and every
  `permissions.additionalDirectories` entry; a write to a stream of a settings or customization file is refused.
  Since review round 14 four classes are refused as classes, not spellings, under `floor.refuse` and `floor.only`:
  1. **A link**, whatever makes it: `ln`, `link`, `mklink`, `junction`, `subst`, `fsutil hardlink`, `cp` with `-l`,
     `-s` or any prefix GNU takes of `--link` and `--symbolic-link`, `cpio -pl`, `rsync --link-dest`, a multicall
     binary (`busybox`, `toybox`, `coreutils`, `uutils`, cmd's `call`) and GNU's `g` prefix (`gln`), `New-Item` whose
     `-ItemType` (any parameter prefix, a colon form) matches a link type as PowerShell's wildcard prefix does (`h`,
     `Hard*`, `j`, `Sym`), an archive member that is a link; in a `cmd /c` payload its carets are removed first
     (`mk^link` is `mklink`) and a `%VAR%` is a word the floor cannot resolve. A link program run by `xargs`, `find
     -exec` or another launcher the floor does not unwrap is refused, and so is one whose path words it cannot resolve
     (a glob, a brace, a substitution, a variable, a splat, its input), one that names a settings or kept file, a
     folder above a kept path, the home, any `.claude` or `.git` folder or what is in one (a symbolic link's target is
     read from the link's folder, so the name as written counts too), and a call that makes a link and writes anything
     else (a folder made or a file removed aside). Inline code (Python, Node, Perl, Ruby, PHP, from `-c` or from its
     input) is read by a positive rule, after Unicode normalisation (NFKC, as Python reads identifiers): it is refused
     when a link name is a token of its code (`link`, `symlink`, `linkSync`, `hardlink_to`, `ln_s`...; `islink`,
     `readlink` and `unlink` are not), when one is spelled across strings (`'li'+'nk'`), when one is in a string while
     the code reaches members by a name held in text (`getattr`, `__getattribute__`, an index in Node, `send` and
     `public_method` in Ruby, any string in PHP), when it evaluates text (`eval`, `exec`, `compile`, `__import__`),
     when it runs a program whose command line names a link maker, and when the floor cannot read it (code given by a
     substitution or a variable, a file or a pipe on the interpreter's input). A link name in a print, a comment or a
     regular expression passes; a search or a text outside an interpreter is not read as code. awk that runs a command
     (`system()`, a pipe) and sed that runs one (its `e` command, `s///e`) are refused, and so are they when they write
     into a `.git` or `.claude` folder; PowerShell's script blocks run from text (`InvokeScript`, `NewScriptBlock`,
     `[scriptblock]::Create`) are refused; .NET's `CreateSymbolicLink`, `CreateHardLink`, `CreateAsSymbolicLink` and
     a P/Invoke `Add-Type` are refused. A link between ordinary files, by a program whose paths the floor reads, passes.
  2. **A write into any `.git` folder** by anything but git: a redirection, a program that writes, Write or Edit, a copy
     or a move whose destination is in one, an extraction into one (tar, unzip, Expand-Archive, 7z, `python -m
     zipfile -e` and `tarfile -e`; `cpio -i` and `pax -r` read their members from their input and are refused; tar's
     member renames, `--transform` and `-s`, are refused), an archive that holds a `.git` or `.claude` member, a merge
     of a folder's contents (`.`, `*`, a glob under `shopt -s dotglob`, robocopy, xcopy, `cp -T`, an rsync source
     ending in `/`) that brings a `.claude` folder or a `.git` folder over an existing one, `patch` that names no file
     (the files its diff names are not read), a `cd` or `Set-Location` into a glob that may be `.git` or `.claude` or
     into git's own folder by a substitution (`$(git rev-parse --git-dir)`); a removal passes (`rm .git/index.lock`).
     git's own commands write there as they do, but not when aimed into one: `checkout-index --prefix`,
     `format-patch -o`, `archive -o`, `bundle create`, `worktree add`, clone's and init's folder.
  3. **Resuming a queue**: `git am`, `rebase`, `cherry-pick` and `revert` with `--continue`, `--skip` (am's
     `--resolved` and `-r`) in any prefix git takes; the owner finishes it in their terminal, and `--abort`, `--quit`
     and `--show-current-patch` pass. `git apply` passes only when its options, parsed as git parses them (unique
     prefixes, `--no-` forms, short clusters, the last one winning), leave `--stat`, `--numstat`, `--summary` or
     `--check` on, `--apply` off and nothing else that writes (`--reject`, `--build-fake-ancestor`,
     `--unsafe-paths`, an option the floor does not know); `git am` applies nothing; `git clone` and `git init` with
     a template folder or configuration (`--template`, `-c`, `--config`) are refused: its hooks run at the checkout.
  4. **A path the floor cannot resolve** where it may reach what it keeps: a glob or a brace is read as the shell
     expands it against the file system (bash's leading dot unless `dotglob`; PowerShell's wildcards match any name);
     a write, a copy, a move or an extraction whose target holds a substitution or a variable is refused when its text
     names a `.git` or `.claude` folder, a settings file, a `hooks` folder or git's own folder (`--git-dir`,
     `--git-path`, `GIT_DIR`), or when the folder it is read in is one; otherwise it passes, as a variable alone does.
  Not read, and left to the operating system's lock (the ACL step above, under `floor.only` with `floor.acl`): a
  script file an interpreter runs (`python p.py`), a write or a copy whose target is a variable alone (`> "$OUT"`, `cp
  x "$OUT"`), a program an interpreter runs from a name it computes, and code that hides a link name from the rules
  above in a way they do not read. The ACL step holds the account's own Claude Code files and its projects' settings
  whatever writes them; it does not hold what « The ACL step » lists as not held, nor anything on a machine without
  it.
  A write that adds a `hooks` key, at any depth, to a skill's, command's or agent's frontmatter (read as YAML) is
  refused, and `claude plugin install`, `enable`, `update` and `marketplace add`/`update` are refused, under
  `floor.only` too. A hard link made before the floor was on, to the settings file of a project outside those folders,
  is not found until a session works there. On an unlocked machine the
  MCP servers of `~/.claude.json` and `.mcp.json` are not judged (`claude mcp add` passes), and a shell write into a
  skill, a command or an agent file is not read; such a write through code the guard does not read is not either. Elsewhere it is the parser's alone, with no backstop (an edit that adds
  a settings file's PreToolUse or PermissionRequest hook is refused too), open through code the
  guard does not read (a script, a program, a compiled tool, a Python wrapper named like a Python) and through a
  launcher it does not unwrap: `flock`, `chrt`, `script -c`, `watch`, `parallel`, `find -exec`, `busybox`, a program
  named by a variable, PowerShell's `[scriptblock]::Create`, bash's `. <(...)`, `Invoke-CimMethod` or
  `Invoke-WmiMethod` of `Win32_Process` `Create`, `powershell -EncodedCommand` (review rounds 5 and 6). Through them a
  session can write a project's or the user's `.claude/settings*.json` (`disableAllHooks`) or rename the plugin folder
  from its parent (the hook then fails, a non-blocking error). A repo's `.git/hooks` are code the guard does not read
  either: a write into them is refused (class 2 above), but one made through code the guard does not read runs at the
  next `git commit`; the ACL step holds the account's Claude Code files and its projects' settings, not a repo's
  `.git/hooks` (git writes them as it works).
- **The environment's limits**: on Windows `HOME` and `PATH` are read in any case like every watched name, so a shell
  variable of those letters is refused even where it would stay in the shell (`path=$(pwd)`, `read -r home`, `for
  path in`): name it otherwise (the shell exports one in more ways than a reading of its forms kept up with: a value
  holding `;`, `ex\port`, a nameref, `eval`). A `BRAIN_CONFIG` or `BRAIN_PROJECTS` that passes may name any file inside a worktree of
  the repository, one the session wrote included: the guard holds the floor of the config.json found without
  `BRAIN_CONFIG` (above), and the registry is no part of the floor; the other guards a nested session runs read
  that worktree's settings, as a session opened in that worktree would. The upstream a pull of the checkout reads
  is the owner's to keep: a remote URL or an upstream set before the floor was on, or by code the guard does not
  read, is not undone.
- Also: a guard the hook never reaches (the core plugin removed from outside a session, on a machine that is not
  locked); a clone, which brings the cloned repo's own project settings, as any repo the owner opens does.

**Floor only** (config.json `floor.only: true`): the machine gets the floor and nothing else, until it is adopted:
`inject-rules.sh` injects the locked lines alone, after one line that says why (`brain.floor.ONLY_LINE`, the same
words in both); the guard runs the floor's refusals, the secrets and configuration checks, the override protection
(`check_override`: the owner guard's override category, so that no session lifts its own floor: the guards' override
set for later sessions, `brain usage allow`, `brain handover root`, a write of the usage allow file, the chain
roots or the desktop app's session files and their index) and the session-settings and scheduled-task tool checks; no production, power or third-party guard, nor the
owner guard's other categories (a project whose own work they would refuse). The memory notes are not synced, either
way, whatever `BRAIN_MEMORY_SYNC` says. `floor` is read at config.json's top level alone, by the guard and by
`inject-rules.sh` alike (a `floor` key inside another object is not the setting). The owner sets it; how a machine
with no anchor in the owner's brain, or a project until its merge phase, enters it on its own is a decision still
open.

## The Terminal panel

A command a session types into the owner's Terminal panel (`mcp__*terminal__run_in_terminal`) runs in the owner's own
shell, outside any sandbox. `guard.sh shell` judges it like a Bash or PowerShell call, with every shell guard
(production, owner, power, third-party, attribution, secrets, markers, public, branches, the usage override): as PowerShell on Windows, as
bash elsewhere (an SSH host's login shell), in the new tab's `cwd`, else the session's folder. A reused tab's folder
is wherever its earlier commands left it: the guard reads it as the session's.

## The session-settings guard

A session that turns Remote Control on or off, or changes a session's permission mode (higher or lower, its own or
another's), is refused, but in Remote Control's three exceptions (below). The reason names the command that puts the exact action in the owner's queue:

```bash
brain queue add --kind action --guard guard-0123456789 [--item ID]
```

The owner then switches it in the app (the toolbar's Remote Control switch, the session's permission mode, or
Settings for the default). The category is `security-settings`, never grantable: `brain permissions check` refuses an
allow rule that names those tools, Remote Control or a permission mode, at every level, but the one rule
`mcp__ccd_session_mgmt__set_remote_control`, exactly (`brain.permissions.GUARD_BOUNDED`): this guard refuses every
call of that tool outside its three exceptions, and inside them the gesture's level decides (« Its level » below:
at `ask` the guard's own card, whatever the allow rule; at `auto` no card) (wi-brain-coordinator-handover-no-prompt,
wi-brain-automation-guard). `BRAIN_GUARD_ALLOW` does not
lift it, not even `all`. Refusals are in `<BRAIN_HOME>/ledger/guards-<month>.jsonl` (`"check": "security-settings"`).

### Remote Control's three exceptions

The owner decided three cases where a session switches Remote Control itself (wi-brain-guard-rc-archive, the ADRs of
2026-11-04 on archiving and on the coordinators' handover). `mcp__ccd_session_mgmt__set_remote_control` (the desktop
app's own server; any other prefix gets the plain refusal) passes in exactly these, checked by the guard
(`brain.guards.remote_control`), and is refused otherwise, the reason saying which condition failed:

| Case | Call | The guard checks |
|---|---|---|
| `archive` | `enabled: false` on another session, just before archiving it | the caller started it; it is `idle` or `ended` (its transcript's tail); it is no live coordinator (by name or title) |
| `handover-on` | `enabled: true` on another session | the caller is a coordinator started by a coordinator or by a chain root, or a chain root; it started the target; the target is a coordinator, live (or starting) on this machine; the caller's hand-over note exists |
| `handover-off` | `enabled: false` on `self` (or its own id) | the caller is a coordinator started by a coordinator or by a chain root, or a chain root; its hand-over note exists; it started a coordinator that is detached and live (or starting) on this machine |

What it reads, at zero token:

- **Who is calling**: the one desktop app session file whose `cliSessionId` is the hook's `session_id`, read again at
  the call and naming that same transcript; when Claude Code's environment gives the app id
  (`CLAUDE_CODE_HOST_SESSION_ID`), the two must agree. A session whose file is in two account folders is refused.
- **Who started whom**: the app's own files only (`spawnedFrom.sessionId`), read again at the call. The ledger's
  SessionStart events and the brief hash (what `brain sessions` adds) are not trusted here: any session can append to
  the ledger, and the brief hash is a guess. A file without a parent's id is no proof the owner started it: a root
  coordinator's Remote Control stays the owner's gesture.
- **A coordinator**: its name, `spawnedFrom.name`, fixed by the session that started it: `coordinator-<x>` or
  `coordinateur-<x>` (one to three letters or digits) or `coordination-du-brain[-…]`. Never its title, which a session
  can change (`set_session_title`); a title starting « Coordination du Brain » only protects a live session from the
  `archive` case. `coordinator-report` is no coordinator.
- **A chain root**: a session the owner started (its app file names no parent) whose id the owner marked with
  `brain handover root <id>` in their own terminal (`<BRAIN_HOME>/handover/roots.json`; the guard refuses to a
  session any command with `handover root` in its words and any write into that file or its folder, whatever the
  spelling, like `brain usage allow`; a roots.json reached through a link marks nothing). A root hands over without a coordinator's
  name, and the coordinators it starts pass the parent condition through it until the owner clears the mark
  (wi-brain-handover-command). A marked id whose
  app file names a parent is no root. The first prompt of an owner-started session that asks for a coordinator marks
  it with no gesture (wi-brain-handover-auto-root: the UserPromptSubmit hook, `brain.succession.auto_root`); the
  guard refuses a session that runs that hook's entry by hand: an interpreter (python, bash, cmd, a wrapper) given a
  file named `midsession.py` or `.sh`, `-m brain.midsession`, or a `python -c` code that imports or calls it
  (`brain.midsession`, `hook_main`, `auto_root`); reading or testing it is not refused. It holds against a mistake:
  a renamed copy or code built at run time is out of its reach, and the mark itself judges the session's own
  transcript (found from its id) and the app's count of completed turns, never what the payload says.
- **Live on this machine**: `running`, `idle`, `asking` or `stale`; not archived, and not `unknown` (no transcript).
  A successor `unknown` because it has no transcript yet still counts, as starting, for `handover-on` and
  `handover-off` when its own app file's `createdAt` is at most 10 minutes old (`HANDOVER_START_S`): the outgoing
  coordinator switches it on seconds after `start_session`, before its first turn is written; an older one, or
  one whose `createdAt` cannot be read, stays refused (`wi-brain-rc-handover-starting`).
- **Detached**: the app's `lineageDetached` (`brain.sessions` reads it as `detached`).
- **The hand-over note**: a regular `*.md` file (no link) in `<BRAIN_HOME>/handover/`, at most 512 kB, written in the
  last 6 hours (not in the future), whose first `local_…` id in its first 2,000 characters is the caller's: a note
  opens with whose it is, so the successor's note, which names its predecessor after itself, is not the
  predecessor's.

Each allowed call is logged in the guards ledger with `"decision": "allowed"`, its `case` and its input; a pass the
ledger does not take (no ledger, `BRAIN_CAPTURE=0`) is a refusal. Anything the guard cannot read (no app files on the
machine, a caller it cannot identify, an input of another shape) is a refusal, and so is an error once the hook's
JSON is read: for a session's security settings the guard fails closed, where every other guard lets the call
through (a payload that is not JSON, which Claude Code never sends, names no tool and passes as before). The `archive` case itself checks
the turn only (idle stands for « finished »); the `archive_session` that follows has its own case (below), which
checks the PRs and the folder. `set_session_permission_mode`
and the app's settings stay refused in every case.

### The archive case

The owner allows `mcp__ccd_session_mgmt__archive_session` and `mcp__ccd_session_mgmt__set_remote_control` in their
permissions (their personal brain's `permissions.yaml`): the guard bounds both, and since wi-brain-automation-guard
the allow rule alone no longer lifts the card, the gesture's level does (« Its level » below: at `ask`, the engine's
default, the guard asks, logged `asked`; at `auto` it allows, logged `allowed`; at `manual` it refuses).
`set_remote_control` keeps its three exceptions above, everything else refused. `archive_session`
(`brain.guards.archive`) passes its conditions, logged with its case, only in:

| Case | Target | The guard checks |
|---|---|---|
| `child` | a session the caller started | not a coordinator (by name or title): its own successor archives it |
| `predecessor` | the session that started the caller | a coordinator by name or a chain root; the caller is its successor (a coordinator by name it started, live and detached); the predecessor's hand-over note is written (as for `handover-off`) |

and in both: the target is `idle` or `ended`, not archived; none of its children blocks (each archived or detached:
the app archives a finished child with its parent and refuses a parent whose child works; `brain handover check`'s
children line); every PR of its app file (`prs[].state`) is `MERGED` or `CLOSED`; each of its folders (`cwd`, and
`worktreePath` when the file has one: the folder the app removes) is gone, or the top of a checkout (`git rev-parse
--show-toplevel`: else git would read a parent repo that ignores it) where `git status --porcelain` shows nothing and
git ignores nothing but caches (what `brain tidy` names before a removal: a `.env`, local data). git runs by its path,
file-system monitor, untracked cache, hooks and submodule recursion off, no optional lock, none of the hook's `GIT_`
variables, no system config and an empty global one (`GIT_CONFIG_NOSYSTEM`, `GIT_CONFIG_GLOBAL`; the `core.autocrlf` and
`core.eol` git reads otherwise are carried over, so that a clean CRLF checkout stays clean), 3 s per call (five per
folder) and 15 s for all of them (`GIT_TOTAL_S`, both folders together; past it the card asks), inside the hook's
30 s: a hook Claude Code kills lets the call through to the allow rule. No program of the
target repo runs: git cannot switch off a filter driver its config declares, so the guard reads that config first (a
read runs nothing) and asks when the repo's own config declares a filter (`filter.*`), an `include` or an
`includeIf`, or when the checkout has submodules or nested repos (`.gitmodules`, or a gitlink in its index, mode
160000: `git status` would run git in them, under their own config). Not checked: commits on a branch
with no PR (the branch survives the worktree's removal). Any other call (`self`, another session, an
unreadable input), a pass the ledger does not take and an error get `permissionDecision: ask`, logged `asked` with
the reason: the card, which no allow rule lifts. While the guards cannot run at all (`guard.sh` without a Python that
imports brain) and the floor is off, it asks too, and refuses `set_remote_control` and `set_session_permission_mode`
(with the floor on, it refuses all three).

The allow rules wait for the guard (`brain.permissions.GUARD_REQUIRED`, fail closed): an allow rule that lets
`set_remote_control` or `archive_session` through (the tool, its server, a wildcard, with any specifier) is withheld on
a machine whose PreToolUse hooks do not send that tool to the guard. With a floor lock, its managed settings alone
count (their `allowManagedHooksOnly` keeps the plugin's hooks from running): the copy `brain floor lock --apply` wrote
before this engine has no `archive_session` in its matcher, so run it again; else the core plugin as Claude Code
installed it (`<claude home>/plugins/installed_plugins.json`: at user scope, enabled, the user settings without
`disableAllHooks`). What cannot be read counts as unseen. `brain permissions render` leaves a withheld rule out and
lists it as expired, so `install.ps1 -Apply` takes it out of the settings that hold it (its line `withheld`);
`brain permissions check` fails on it, `brain check` and `brain doctor` warn of it (a repo's check reads the same on
every machine). Such a rule is held only at the user levels
(engine, global, profile, machine), which each machine's installer renders for itself: a project's or tenant's
settings are committed and read by every machine, a session's by any. The guard the plugin starts runs the engine of
the brain's venv, which `install.ps1 -Apply` installs with the plugin and which renders these rules itself (an older
engine refuses the Remote Control rule): going back to an older engine is the owner's, with its plugin. A project's
own settings that turn the hooks off are not read here: under `guards.owner_strict` the guard refuses a session's
`disableAllHooks` (`GUARD_OFF`) and its disabling the core plugin (`enabledPlugins` set false by an edit or a shell
write into Claude Code's settings, `claude plugin disable` or `uninstall` of it: `brain.guards._plugin_off`).

Its level (wi-brain-automation-guard; docs/automation.md « Enforcement »): inside a case, the gesture's automation
level decides. `archive_session` and the `set_remote_control` off before it read `session-archive`'s, the hand-over's
on and off `handover-remote-control`'s: at `manual` the call is refused (logged `denied` with its case and level), at
`ask` (the engine's default) the guard prints `permissionDecision: ask` (the card, logged `asked` with its case),
whatever the tool's native rule (an owner's allow rule no longer lifts it: their level `auto` does), at `auto` it
prints `permissionDecision: allow`. A refusal at `manual` the ledger cannot take still refuses. Outside a case
nothing changes, but at `manual` an `archive_session` is refused instead of asked. `ask` reads `manual` in a permission mode with no card for an ask (`bypassPermissions`, `dontAsk`, none given):
refused. Every row of these decisions carries the `level` it read.

What it does not hold against: its inputs are files a session can write. The guard reads the app's session files
themselves, each parsed at the call, never the index's cache (`<BRAIN_HOME>/cache/sessions-app.json`, a session
could hide a child there), and it refuses a session's write into them, into the folders that hold them
(`Claude-Data/<account>/claude-code-sessions`, any account folder, an existing one or a new one, and `Claude-Data`
itself), into that cache, or into a transcript (a `.jsonl` of `<claude home>/projects/<project>/`, whose tail says
whether a turn is finished) or a folder that would bring one (the projects' folder, a project's, what a project's
folder holds and a session's `subagents/`: a folder copied or moved there; the memory beside the transcripts and a
session's tool results and workflow scripts stay writable), by an edit tool or a shell write, also through a hard link (`override`, as the chain roots' file; the app
and Claude Code write them themselves, with no tool call). That holds against a mistake: a script that writes them, a
path built at run time (`"$(...)"`), or a note naming itself, is tampering, out of a hook's reach, and the app asked the owner to approve each
switch until the owner's allow rules (the archive case): inside the cases at level `auto` the guard is now the only
check (at `ask` the card still asks), and a session that forges the app's files through a script passes it. The note is the handover's
procedural mark (the ADR's « une fois sa note écrite »), not a credential. The names are chosen by the session that
starts a child, so a session that starts a `coordinator-x` which starts a `coordinator-y` has built the mark; the
guard checks one hop of lineage, not the whole chain back to the owner. While its note is under 6 hours old, a
coordinator may turn Remote Control on for any coordinator it started, not only one. After a new root coordinator
(started by the owner, so unnamed), the first two handovers stay the owner's gesture unless the root is marked: by its
first prompt when it asks for a coordinator (the hook), else by `brain handover root <id>`, once per chain: the root has no name, and its first successor's parent is no
coordinator by name. `brain handover check` reads the same conditions before the calls and names the one that fails,
then the session's children and its predecessor's (archived, detached or blocking: the guard reads neither, and only
the session that started a child may detach it, so the predecessor is archived once none of its children blocks);
`brain handover wait --successor <id>` waits, bounded, for the successor's first turn before `on` (a successor with
no transcript yet passes only as starting, from 0.4.0, within ten minutes of its creation).

## The third-party guard

A session never installs or runs a third-party kit (the owner reads it first: wi-brain-guard-third-party). `guard.sh
shell` refuses, in a Bash, PowerShell or Terminal panel call, through wrappers, launchers, nested shells and ssh:

| Check | Shapes |
|---|---|
| `download` | a download piped, through any filter, to a shell or an interpreter reading stdin (`curl ... \| sh`, `wget -qO- ... \| bash`, `curl ... \| python3 -`, `curl ... \| bash /dev/stdin`, `curl ... \| bash -o pipefail` (an option's value, `-o`, `-O`, `--rcfile`, is no script; a short cluster takes one value per `o` or `O` it holds, wherever it sits: `bash -oe pipefail`, `bash -Ox extglob`), `curl ... \| source /dev/stdin`, `curl ... \| ssh host`, `iwr ... \| iex`, `irm ... \| iex`, the pipe continued on the next line too); a download in a process substitution a shell or `source` runs as its script (`bash <(curl ...)`, `. <(wget -qO- ...)`); a PowerShell statement where `iex` meets a download (`iex (iwr ...)`, a WebClient's `DownloadString`, a `$( )` in
its string, which PowerShell expands first: `iex "& { $(irm ...) }"`); `sh -c`, `eval` or a here-string whose text is a download's output, quoted or not (`sh -c "$(curl ...)"`, `eval $(curl ...)`, `bash <<<"$(curl ...)"`, `source /dev/stdin <<< "$(curl ...)"`). Every check reads the command of `bash -c` (and `sh -c`, `zsh -c`) as its first word past the options and their values, as bash does: `bash -euo pipefail -c '...'`, `bash -co pipefail '...'`, `bash --rcfile FILE -c '...'`, `bash -c -- '...'` |
| `plugin` | `claude plugin install NAME@MARKETPLACE` (`claude.exe`, and npm's Windows shims `claude.cmd`, `claude.ps1`, too) whose marketplace is not in the owner's list, or with no marketplace named, and its `--marketplace SOURCE` whose source is not; `claude plugin marketplace add SOURCE` whose source is not; claude's global options before `plugin` (`claude --model opus plugin ...`) and the options' values (`--config`, `--scope`, `--sparse a b`) never shift what is checked |
| `skills` | `skills add`, through `npx`, `bunx`, `bun x`, `pnpm dlx`, `yarn dlx` or `npm exec`, and through `corepack` before any of them (`corepack pnpm dlx`, `corepack pnpm@9.12.0 dlx`, `corepack npx`; corepack's own verbs, `enable`, `install`, `up`, run nothing), a launcher's global options before its verb too (`pnpm --silent dlx`, `npm -w pkg exec`; a word after an option the guard does not know, before the verb, is read as its value: `npm --loglevel silent exec`); npm's Windows shims too, of skills and of the launchers (`skills.cmd add`, `npx.cmd skills add`, `pnpm.cmd dlx skills add`, their `.ps1` and `.bat`; another script keeps its name: `install.ps1` is no `install`) |

The owner's list is config.json `adapters.claude.sources`: a marketplace name (no slash) for `plugin install`, a
source (`owner/repo`, a git URL, a folder from the brain's root) for `marketplace add`. The brain's own marketplace,
source repo and folder always pass:

```json
{"adapters": {"claude": {"marketplace": "my-brain", "plugin": "my-core", "source": "me/my-brain",
                         "sources": ["team-kit", "acme/team-kit"]}}}
```

What passes: a download to a file (`curl -o f`, `iwr -OutFile`), a download read as data (`curl ... | jq`, `| python
-m json.tool`, `| python -I parse.py`, a script named before a process substitution: `python3 analyze.py <(curl
...)`, `diff <(curl ...) <(curl ...)`), a download then a script that reads its own stdin (`curl -o f ...; python -
<<EOF`), `pip install -e .`, the commands' `--help` and `-h`, `skills add REPO --list` (it lists, installs nothing),
and text that names the shapes (a commit message, a grep). `guard.sh` starts Python for any command naming `claude`
or `skills` with a later `plugin` or `add` word, whatever comes between (a quoted `claude.exe`, global options, a
line continuation). A refusal is an action for the
owner with the call's exact command (`brain queue add --kind action --guard <ref>`, the title « Third-party script »,
« Third-party plugin » or « Third-party skill »); the owner reads the kit, then runs it in their own terminal, which
no hook sees. Override, the owner's: `BRAIN_GUARD_ALLOW=third-party` or `third-party:<check>`.

## Conflict markers

A merge that leaves `<<<<<<< `, `||||||| `, `>>>>>>> ` or a bare `=======` in a file breaks every brain command that
loads it, and a stale merge's generated views still pass the graph check. Two places refuse them (brain.markers):

- the commit guard (check `markers`): a `git commit`, or `git merge|rebase|cherry-pick|revert|am --continue`, whose
  added lines hold one, in the staged diff, in commit `-a`'s changes, in the working tree of the paths the commit
  names (`git commit -m x PATH`, `--only`, `-i`) or in the files an earlier `git add` of the same command stages.
  `git add -A`, `-u` or `-p` with no path stage the whole worktree, from any folder (git 2.0), and `:/` too; an
  exclusion (`':!x'`) is dropped, so more is read, never less; `-u` and `-p` stage no untracked file, so none is
  read. During a merge (`MERGE_HEAD`), a line counts only when it is new against every parent: content the merged
  branch already holds (a documented conflict in its CONTRIBUTING.md) is not the session's. A moved file adds no line
  (renames are found whatever `diff.renames` says), only the files whose changes hold a marker-like line are read
  (`git diff -G`), so a big data file never cuts the diff, and an untracked file is read whole, whatever its size.
  What git cannot show (it fails, times out, or prints over 20 MB) is an error in ledger/errors.log, never a silent
  pass; a folder that is no git worktree when the guard runs (missing, or its `git init` later in the same call:
  `mkdir p && cd p && git init && git add . && git commit`), git saying "not a git repository", has nothing to read
  and passes, as for git; any other failure of that worktree check (git missing from the hook's PATH, a timeout,
  dubious ownership) is an error in errors.log too. The reason names the file and line.
- `brain check` (and `brain refresh`): it fails first, before reading anything else, on a store file (its nodes,
  edges and generated views), a journal, a decision log or a record holding one.

A setext heading (`=======` under a line of text, in a file with no other marker) in Markdown (`.md`, `.markdown`,
`.mdx`, Quarto's `.qmd`, R Markdown's `.Rmd`) or reStructuredText (`.rst`, `.txt`), its path holding a space or not,
and a file under a `fixtures`, `fixture` or `testdata` folder pass. A `.txt` file is often data (`requirements.txt`,
`constraints.txt`), so there only reStructuredText's shape passes: a title no longer than its underline (seven
characters at most); a bare `=======` left under `numpy==1.26` is still a marker, one under `six` is not. Elsewhere (a Python docstring), underline a title
with eight `=` or more. A conflict quoted in a fenced code block is a marker too, unless the fence is tagged as an
example: in a Markdown file, a fence whose info string holds `conflict-example` (three backticks, then `text
conflict-example`) lets its markers pass, for the commit guard and for `brain check` alike; the tag ends with its
fence. In a commit's diff, a hunk that starts inside a fence whose opening line it does not show is read as unfenced,
so the guard fails closed. Override, the owner's: `BRAIN_GUARD_ALLOW=markers`.

## A public repo's commits, a chained push, heredocs

Three guards the lessons registry asked for (`brain lessons --follow`), and an advice:

- **The private text a push sends** (`public:private-text`, advice, never a refusal; wi-brain-private-text-prepush):
  a `git push` to a repo of `public.repos` that the guards let through is compared, by its added lines that the
  remote has not, with the owner's rules and notes on this machine (`brain.privatetext`, windows of 8 words, as
  `brain check --public --private-text` before a tag). Each passage is named in the session's context by its file,
  line and source, never its text, and the ledger records the advice (`warned`); a file under `public.allow` is not
  read, and a scan that fails lets the push go (`errors.log`). The PR rewords them; the tag's check still refuses.
  A push that adds no line costs one `git log`; the windows are hashed and cached in
  `<BRAIN_HOME>/cache/private-text.json` (hashes and source paths, never the words) while the rules and notes keep
  their mtime and size; one push reads 500 commits at most (a first push of a long history), each hunk on its own,
  and a remote given as a URL excludes what the remotes naming the same repo have. Tag messages and git notes are not
  read. `BRAIN_GUARD_ALLOW=public` lifts the push's refusal, not the advice; `BRAIN_GUARD_ALLOW=public:private-text`
  turns the advice off.

- **The public check at the commit** (`public:commit`): in a checkout whose branch pushes to a repo of config.json's
  `public.repos` (its pushRemote, else its remote, else origin: a private fork's public upstream is not checked), a `git commit` whose added lines hold a denied term outside `public.allow` (the owner's name, a
  private repo's), an e-mail address, a home folder or a `public.patterns` match is refused with the file and the
  line, at the commit rather than at the push (les-brain-owner-name-in-fixtures). It reads what the commit records:
  the staged diff, commit `-a`'s changes, the paths the commit names, the files an earlier `git add` of the same call
  stages (untracked ones too, but not after `git add -u` or `-p`), each by its path in the repo, so `public.allow`
  matches from a subfolder. Override, the
  owner's: `BRAIN_GUARD_ALLOW=public:commit`.
- **The public and secrets checks fail closed** (`public:config`; COMPAT-4, wi-brain-guards-fail-closed; the
  2026-11-04 REVERSAL of the internal-error policy, for these checks only). They refuse every `git commit` and
  `git push`, whatever the repo, while the configuration they read is unexpected, the reason naming the fix:
  `config.json` unreadable or not an object (fix it: `brain config --check`), `public` or one of its keys (`repos`, `deny`, `allow`,
  `patterns`, `refuse`, `deny_from_tree`, `derive`, `public_names`) of another type (`brain config --keys`), with `public.deny_from_tree` on a
  `scopes.yaml` or a `projects.yaml` that cannot be read (the generated deny list would miss terms), a registry
  `public.derive` reads that raises (brain.denylist: the derived terms would be missing), a `v` that is not a whole number, or above the one the engine reads (`brain update`), `$BRAIN_CONFIG` naming no file, or no
  `config.json` found although `$BRAIN_PERSONAL` or `<BRAIN_HOME>/personal.json` names a personal brain (a renamed or
  moved folder: point the pointer at the main checkout, `install.ps1 -Apply`). An unknown key never refuses (a newer
  brain's, kept). `guard.sh` refuses them as well when it finds no Python, or the one it finds cannot import brain (a
  missing or broken venv): « the guards cannot run ... brain update ». The SessionStart health says both: « The
  public and secrets guards refuse every git commit and git push: ... » and « The brain guards cannot run ».
  Override, the owner's: `BRAIN_GUARD_ALLOW=public:config` (not for guard.sh's refusal, which runs without Python).
  Every other guard keeps letting the call through on an internal error.
- **A chained check and push**: the push guard judges the whole call before any part of it runs, so `brain check
  --public ... && git push` is refused although the check would pass; the refusal now says to run them in two calls
  (les-brain-guard-judges-chain-early). A `git add ... && git commit` in one call is fine: the commit guards read
  what the add stages.
- **A heredoc with a doubled backslash** (a warning, never a refusal): on Windows, a Bash call whose heredoc body
  holds a doubled backslash and whose first line writes a file or feeds an interpreter (`python -`, `python3 <<EOF`,
  `cat > f`, `tee`)
  gets a note in the session's context: through the Bash tool the doubled backslash has arrived single; write the
  file with Write or Edit, or check its bytes after (les-brain-heredoc-backslashes). The guards ledger records it as
  `heredoc:backslash`, decision `warned`.

- **A merge resolution against a stale main** (`merges:stale`; wi-brain-merge-stale-main-2): a `git push` of a
  branch whose merge of the base is not on the remote yet runs `brain merge-check` against the base as merged and
  a fresh one, and refuses a lost line or node, or a file the merge resolved that the base has moved on since
  (docs/merge-driver.md). Override,
  the owner's: `BRAIN_GUARD_ALLOW=merges:stale`.

### How the guards read a diff

The commit guards (secrets, conflict markers, the public check), `brain impact`, `brain check --public --history`,
the digest's and the forecast's history and the changed-items reader all read git's patches through one function,
`brain.diffs.parse` (wi-brain-diff-parser; the lesson les-brain-unescaped-format: three parsers had the same defect).

- A hunk's lines are read by the counts of its `@@` line: a deleted `-- x` (which reads `--- x`) or an added `++ y`
  is content, never a header. Headers are read only between a file's `diff --git` line and its first hunk.
- A name is read as git writes it: a C-quoted one (a quote, a control character, a non-ASCII byte) is unquoted, an
  unquoted one ends at git's TAB after a name with a space.
- The git call is built by `brain.diffs.argv`: the a/ and b/ prefixes forced (`diff.noprefix`,
  `diff.mnemonicPrefix`), whole-repo paths (`diff.relative`), no colour, no external diff, no textconv, no hunks
  joined over unchanged lines (`diff.interHunkContext`), a blank
  context line kept as a space (`diff.suppressBlankEmpty`; an empty line in a hunk is read as context anyway).
- A merge's combined diff (`diff --cc`) is read too: a line is in the result unless a parent's column says `-`,
  and added only when every parent's column says `+` (a line one parent already held is not the merge's).

## The usage governor

### What it reads

- the quota readings the sessions note: `brain usage quota --observe PCT --resets RESETS_AT [--window 5h]`
  (get_usage's percent used and reset time), in `<BRAIN_HOME>/usage/quota.jsonl` (rotated monthly into
  `quota-YYYY-MM.jsonl`, 12 months kept; the governor reads the live file and the newest month), and the last forecast,
  `usage/quota.json` (its percent now, the last 24 h's pace, the $ per % of the week);
- the sessions: the desktop app's session files (`%LOCALAPPDATA%/Claude-Data/*/claude-code-sessions`, read only),
  else the session records `<BRAIN_HOME>/sessions/*.json`;
- the machine's two memory measures: its committed memory (Windows: what it promised, RAM plus page file, in % of its
  commit limit; elsewhere the memory in use) and its available RAM (what is free now, in GB);
- config.json `usage.guard` and the registry's `usage:` entries, cached in `<BRAIN_HOME>/cache/governor.json`.

### What it decides, in order

| Check | Tools | Decision |
|---|---|---|
| `critical`: a window in force at `critical` % or more | all | deny |
| `stale`: the newest reading older than `fresh_minutes`, on a machine with a reading in the last 7 days | session, workflow | deny, with the commands that note both windows |
| `memory`: committed memory at `memory` % or more (with `memory_free_gb` set: under that many GB of commit left, the percent not read), or available RAM under `memory_available_gb` GB (default 0: no floor) | session, workflow | deny, naming the measures and the one that refused |
| `sessions`: the sessions running reach the cap | session | deny |
| `brainstorms`: the open brainstorms reach the cap, for a brainstorm | session | deny |
| `streams`: the calling session already has `max_streams` live streams (`usage.guard.wave_quota`, off by default) | a session started now | deny |
| `wave_quota`: the week's forecast at its reset plus this stream's estimate over `ask_over_pct` (`usage.guard.wave_quota`, off by default) | a session started now | ask the owner |
| `warn`: a window at `warn` % or more | all | ask the owner |

The parallel sessions cap is the smaller of `sessions` and what the week's room pays for:
`(100 - week %) x $ per % / (wave_hours x session_hour_usd)`, minus one for the master. A session runs when the app
shows it not archived and active in the last `live_minutes`. `session_hour_usd` is the configured one. With
`session_hour_measured` true (an opt-in, default false), it is instead the one `brain usage quota` measured when that
is higher (its `session-h` line, kept in `quota.json`): the last 7 days' cost per session-hour, the subagents' and
workflow agents' cost included, so that a wave whose sessions run workflows leaves room for fewer of them. By default
the measured value is information only: `brain usage guard` shows it on its `session-h` line with whether it is
applied, and a `sessions` refusal names the session-hour it used (`measured` when it is the measured one).

A brainstorm is a session whose brief says `Task class: brainstorm` or carries `#brainstorm` (the session record's
`task_class`), or whose title matches `brainstorm_title` (default: it starts with "Brainstorm"). It is open while not
archived and active in the last `brainstorm_hours`, in any project. A brainstorm start the governor lets through is
noted in `<BRAIN_HOME>/usage/starts.jsonl` (`"brainstorm": true`) and counted for 10 minutes, until the app shows its session (a log rotated
monthly, two months kept; the governor reads the live file and the newest monthly one, so a start just before the
month turned still counts).

### The wave quota gate (`usage.guard.wave_quota`, off by default)

The owner's rule for waves (the waves retro, RETRO-5): a stream starts only while the quota's forecast, its own
estimate included, keeps the week under 90 % at its reset, and one master runs three streams at most, their reviews
included. Without `usage.guard.wave_quota` in config.json nothing of this runs; with it, two checks apply to a
`start_session` call that starts a session now (`initiation` `user_asked` or none, or a `proposal_id`; a proposal card,
`offer` or `own_initiative`, starts nothing and is not checked):

- **`streams`** refuses a new stream when the calling session (the master) already has `max_streams` live ones: its
  children in the desktop app's session files (their `spawnedFrom`), neither archived nor detached, that are
  *running* (the transcript written in the last `live_minutes` and its last turn not ended: a child that reported and
  waits, or asks the owner, does not count) or *starting* (created in the last 10 minutes, no transcript yet), plus the
  stream starts no child matches yet. Each start the governor lets through, or asks the owner about (so that parallel
  starts in one message see each other), is noted in `usage/starts.jsonl` (`"stream": true`). A noted start is matched
  against every child of the master, archived and detached ones included, on its creation time (the title or the
  app's short name only breaks a tie: the app may cut or rename a title); one no child matches counts for one minute
  only, so a start the app refused, or the owner declined, holds no slot for long, and a review that ran and was
  archived within minutes holds none.
- **`wave_quota`** asks the owner when the week's forecast at its reset goes over `ask_over_pct`: the week's percent
  as read (the newest reading, or the last forecast's percent when it is newer) plus the last forecast's pace
  (`usage/quota.json`, `pace.pct_h`, only while that forecast is of the week in force) times the hours from that
  reading to the reset, plus this stream's cost in percent of the week. The
  cost is the brief's estimate (the `usd=` of its « Cost estimate » line: `brain brief`, `brain cost estimate`), else
  the median session's cost of the last forecast (`live.median_session_usd`), converted by its `pct_per_usd`. The
  question gives the arithmetic: `232 % (78 % at 12:24 UTC + 2.16 %/h x 71.6 h) plus this stream's 0.7 % ($11.00,
  the brief's estimate): 233 %, over 90 %`.

Both fail open: a forecast that cannot be read (no week reading in force, no pace of this week, no conversion), a
session the app does not know or no app on the machine, a count that takes more than 2 s (timed from before the app's
sessions are read), a transcript with no whole record in its last 1 MB (that child is not counted), or an error inside
the gate let the call through, and the hook says why in its context (« Wave quota gate (usage.guard.wave_quota): ...; the start
goes through unchecked by it. »). The owner's override (below) lifts either check when it is named
(`brain usage allow --check streams`, `--check wave_quota`); an allow without `--check` leaves the gate on. The
counts of the streams that fit (below) plan a wave and ignore an allow: `brain usage guard`'s line says when one lifts a
check of the gate.

The gate is `brain.wavegate`. How many streams fit now, from the same reading (`brain.wavegate.room`): the smaller of the streams left to the
master (`max_streams` less its live ones) and the streams that keep the forecast at the reset under `ask_over_pct`.
`brain brief` says it on its « Streams that fit now » line (for its coordinator, each stream at the item's estimate),
`brain wave plan` and `brain next` on theirs (a round holds at most `max_streams` lots, the first round's lots at the sum
of their items' recorded estimates), `brain usage guard` on its `waves` line.

```json
{"usage": {"guard": {"wave_quota": {"ask_over_pct": 90, "max_streams": 3}}}}
```

Both fields are optional (90 and 3); `0` turns that check off.

### A master's start_session (the master's watch)

When none of the checks above holds, a `start_session` call goes through, and two things happen (ST-3, ST-4): the
budget watch's mark of the calling session is expired, so its next tool call checks it at once (it may have just
become a master); and if the watch last saw it past 80 % of its budget (`<BRAIN_HOME>/budget/<session>.json`, its
`master`), the call carries a reminder as hook context: past 80 % a master starts no new child, it hands over to a
fresh master and drains its own. It is never a refusal: no guard blocks start_session.

### Configuration (config.json `usage.guard`)

```json
{"usage": {"guard": {"warn": 80, "critical": 95, "sessions": 8, "brainstorms": 3, "memory": 97,
                     "memory_available_gb": 4, "wave_hours": 4, "session_hour_usd": 14, "session_hour_measured": false,
                     "fresh_minutes": 60, "live_minutes": 30, "brainstorm_hours": 12}}}
```

`memory_free_gb` (default 0: the percent) reads the committed memory in GB of commit left instead (Windows: the commit
limit minus the commit charge; elsewhere MemAvailable plus SwapFree): a page file of a fixed size keeps the percent at
91-94 % with 25 GB of RAM free, where 6 GB of commit left is a session's worth and a margin (`"memory_free_gb": 6`);
with it set, `brain usage guard`, `brain status` and `brain lots` show it beside the percent (read to the hundredth:
5.95 GB left is under 6).

Every key is optional (the defaults above, except `brainstorms`: 2, and `memory_available_gb`: 0, no floor; 4 is the
opt-in shown). `"enabled": false` turns the governor off. A
project lowers its own caps in `projects.yaml`, never raises them:

```yaml
lab: {root: ../lab, usage: {brainstorms: 1, sessions: 4}}
```

`brain config --check` and `brain check --all` report a value of the wrong shape (it is left at its default).

### Reading it

```bash
brain usage guard          # the windows, the sessions and brainstorms, both memory measures, the caps, each tool's decision
brain usage guard --json
```

Every refusal, ask and override is a line of the guards ledger with `"guard": "usage"` and its check.

### Overriding it (the owner only)

```bash
brain usage allow --hours 2 --reason "finish the demo"   # in your own terminal: the memory and session caps
brain usage allow --check critical --hours 1             # the critical quota (and warn with it)
brain usage allow --hours 0                              # end it now
```

An allow lifts checks, not the governor (RETRO-8): by default the memory and session caps (`memory`, `sessions`,
`brainstorms`); `--check NAME`, repeatable, aims one or more of `critical` (which
lifts `warn` too), `warn`, `memory`, `sessions`, `brainstorms`, `streams`, `wave_quota`. A stale quota reading is never lifted: reading it again is one `get_usage` call. A lifted
check lets the next one decide (memory lifted, the sessions cap still refuses), and each refusal names the allow that
lifts it (`brain usage allow --check critical --hours 2`), or says that none does. An allow adds to the one in
force (its checks and the later end kept), so following one refusal's hint never undoes another allow; `--hours 0`
ends the whole override. Each allow, and its end (`ended` by `--hours 0`, `expired` when its time has passed: the
first to see it, a hook, `brain usage guard` or the next allow, claims the file and ends it, once; an allow the
owner wrote meanwhile is kept), is a line of the guards ledger (`"guard": "usage"`, `"check": "allow"`, its checks, since, until and reason),
and each call it lets through one more (`"decision": "overridden"`, `"by": "allow"`). An `allow.json` written by
0.5.0 (no `checks`) lifts every check but `stale` until it ends.

The guards refuse `brain usage allow` to a session, and any write of its file (`<BRAIN_HOME>/usage/allow.json`).
`BRAIN_GUARD_ALLOW=usage` in Claude Code's environment lifts every check, for every session started with it;
`BRAIN_GUARD_ALLOW=usage:CHECK` that one only.

### Not applied here

`CLAUDE_CODE_WORKFLOW_MAX_CONCURRENT_AGENTS` (how many workflow agents run at once; about 8 on a machine like the
scale study's) is Claude Code's own setting: the owner sets it through their installer's plan, never a session.

## The machine's token

`<BRAIN_HOME>/ipc/token` (or the file `$BRAIN_IPC_TOKEN_FILE` names, docs/mcp.md « The machine's token ») is the key of
the Brain's local services. Claude Code's `otelHeadersHelper` runs `brain ipc otel-headers`, the one command that
prints it, which the owner guard refuses to a session (the gestures above); the file itself is the other door.

Under config.json `"guards": {"refuse_token_read": true}` (off by default: a refusal 0.6.0 adds), the owner guard's
check `token` (`brain.tokenguard`) refuses a session's call that reaches the file:

| Door | Refused | Passes |
|---|---|---|
| `Read` (`tokenguard.sh`) | the token file, by any spelling the file system resolves to it (`..`, a link, an 8.3 name, `token::$DATA`, an admin share of this machine: `\\localhost\C$\...`, `\\<its name>\C$\...`, `\\127.0.0.1\C$`, `\\0--1.ipv6-literal.net\C$`) | any other file |
| `Grep` (`tokenguard.sh`) | a path that is the token file, its folder, or a folder of `<BRAIN_HOME>` that holds it (no path: the cwd) | any other folder; a `type`, or a `glob` that cannot match the file's name (`*.md`; a negated one, `!*.md`, reads all the rest: refused) |
| `Edit`, `Write`, `MultiEdit`, `NotebookEdit` | the token file (a session never chooses the machine's token either) | |
| a shell call (Bash, PowerShell, the Terminal panel; wrappers, launchers, nested shells, `cmd /c`, `pwsh -Command`) | any program whose words name the file, its folder or `<BRAIN_HOME>` itself (`cat`, `Get-Content`, `type`, `cp -r ~/.brain`, `tar`, `grep -r . ~/.brain`, `Compress-Archive`, `rm`); an option's value (`-Path:x`, `--file=x`, `if=x`, `@x`, `f=@x`), a PowerShell list (`'x','T'`) or join (`Join-Path $h ipc token`, `[IO.Path]::Combine(...)`), an input or output redirection (`< T`, `> T`), a glob that matches it (part by part, without reading the disk), `${NAME}`, `${env:NAME}`, `${T}`, a WSL path (`/mnt/c/...`); a program that prints the path it names (`ls`, `echo`, `realpath`, `Get-Item`, `Get-ChildItem`) on the file or its folder (or on the home listed recursively, `gci -Recurse ~/.brain \| Get-Content`) in a call with a pipe or a substitution (`echo T \| xargs cat`, `ls -d ~/.brain/ipc/* \| xargs cat`, `Get-Item T \| Get-Content`); inline code, or a heredoc fed to an interpreter that reads its code from stdin (`python - <<X`, `cat <<X \| python`), that names `ipc/token` and does something with a path (`open('.../ipc/token')`, `Path(h) / 'ipc' / 'token'`), or uses brain.ipcauth; over ssh, any command that names `ipc/token` | `ls`, `dir`, `stat`, `test`, `file`, `du`, `Test-Path`, `Get-Item`, `Get-ChildItem`, `Get-Acl`, `icacls`, `attrib`, `realpath`, `echo` of the path (in a pipe, not on the file or its folder: `ls ~/.brain \| head`, `test -f T && echo yes \| cat`); `Join-Path $env:BRAIN_HOME handover`; a search's pattern (`grep -rn 'ipc/token' handover` from the home); a heredoc into anything but an interpreter (`git commit -F - <<X`); `brain ipc token` (it never prints the token); a mention in a search, a message or an argument (`grep -rn 'ipc/token' docs`, `git commit -m '... ipc/token'`, `pytest -k ipc/token`, `print('ipc/token')`) |

The refusal names the owner and the key; `BRAIN_GUARD_ALLOW=owner` (or `owner:token`) lifts it for the owner. Nothing
is queued: the owner reads their own token in their own terminal.

**Its cost.** Read and Grep reach it through their own hook, `tokenguard.sh`, which `brain render --target claude`
(`brain sync`) registers only when the key is on (`brain.render.OPTIONAL_HOOKS`): off, no Read or Grep pays anything.
On, it starts Python only when the call names `ipc`, `token`, `.brain` or `$BRAIN_HOME`'s folder or the file
`$BRAIN_IPC_TOKEN_FILE` names, or its path (a relative one read from the call's cwd, a trailing separator dropped) is
a link. Shell calls and edits are `guard.sh`'s: its pre-filter starts Python on the words `ipc` and `token`, and, only
when the key is on (`common.sh`'s `floor_setting` reads it with awk, no Python), on `.brain`, `$BRAIN_HOME`, its
folder's name, `$BRAIN_IPC_TOKEN_FILE` and the token file's name, in any case. A locked floor's managed hooks (`brain floor lock`) leave
`tokenguard.sh` out, so a locked machine judges a Read or Grep for nothing; its shell calls and edits keep the check.
The locked floor never turns the check on (the key does) nor off (a floor-only machine keeps it).

The MCP server (below) runs the check under the same key (optional, off by default: as 0.5.1, no check), on its
tools' effects: every effect is a `brain` command, so it refuses a reference that resolves to the file (a link named
as a spec); its real protection is that every answer has the token's value redacted, whatever the key.

**What it does not see** (the token is readable by the owner's account, which a session shares: this guard is the
lock, and it is advisory): a script file that reads the token (`python leak.py`), a path built at run time from
pieces the guard cannot read (base64, character codes, `os.sep` joins, a variable set by an earlier call), a
recursive read of a folder above `<BRAIN_HOME>` (`grep -r x ~`), a link made earlier by a script, a working folder
that is itself a link, a glob through a junction made earlier, and a glob that spells neither `ipc`, `token` nor the
brain's home (`~/.br?in/ip?/*`), which the pre-filter lets through without starting Python. A pipe that carries `ls`
of the token's folder is refused even when it only counts (`ls ~/.brain/ipc | wc -l`).

## The guards for other agents (the MCP server)

`brain mcp serve` (docs/mcp.md) runs these same checks on each tool call of a client that runs no Claude Code hook
(`brain.mcpguards`): the call's effect as a hook payload, through `brain.guards.refusals(payload, strict=True)`. Two
differences from a hook: a check that raises refuses the call (a hook lets it through), and `BRAIN_GUARD_ALLOW` lifts
nothing (a client's configuration can set the server's environment). The owner's own `brain` gestures (answering a
decision, a schedule installed, the machine's token made...) are refused there whatever the tool, and the refusals go
to the same guards ledger, the tool named `mcp:<name>`.

## Troubleshooting

- **Every start is refused as stale**: a session reads get_usage, then notes each window it shows
  (`brain usage quota --observe 41 --resets 2026-11-09T12:00Z`). A machine that never notes a reading is not checked.
- **The hook seems silent**: `brain perf --engine --task "hook governor"` shows each run's time and the errors it
  caught (`ledger/errors.log` has their text); a missing Python lets every call through, but a git commit or git
  push, which guard.sh refuses (« the guards cannot run »: `brain update`, or `install.ps1 -Apply`).
- **Every commit and push is refused with « cannot trust the configuration »**: `brain config --check` shows what is
  wrong in `config.json`; `brain config` shows which file was found and the personal brain `personal.json` names.
- **A cap looks wrong**: `brain usage guard` shows the count and where it comes from (`app` or `records`).
