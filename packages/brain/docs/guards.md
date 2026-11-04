# Runbook: the session-settings, third-party and conflict-marker guards, and the usage governor

Two PreToolUse hooks of the engine's Claude Code plugin keep the owner's say over how sessions run. Both are scripts,
not rules: they decide before the call, at zero token, and never break a session (an error lets the call through and
goes to `<BRAIN_HOME>/ledger/errors.log`).

| Hook | Tools | Decides |
|---|---|---|
| `guard.sh tool` (`brain.guards`) | `mcp__*__set_remote_control`, `mcp__*__set_session_permission_mode`, the app's `set_setting` for a Remote Control or permission key | refuses, always |
| `governor.sh` (`brain.governor`) | `mcp__*__start_session`, `Agent`, `Task`, `Workflow` | asks at WARN, refuses at CRITICAL, past a cap, or on a stale reading |

Both are declared in `src/brain/adapters/claude/hooks/hooks.json`. A personal brain gets them with
`brain render --target claude --write` (or `brain sync`) into its own plugin, then its installer applies the plugin
(on Windows `install.ps1 -Apply`, the owner's).

## The Terminal panel

A command a session types into the owner's Terminal panel (`mcp__*terminal__run_in_terminal`) runs in the owner's own
shell, outside any sandbox. `guard.sh shell` judges it like a Bash or PowerShell call, with every shell guard
(production, owner, power, third-party, attribution, secrets, markers, public, branches, the usage override): as PowerShell on Windows, as
bash elsewhere (an SSH host's login shell), in the new tab's `cwd`, else the session's folder. A reused tab's folder
is wherever its earlier commands left it: the guard reads it as the session's.

## The session-settings guard

A session that turns Remote Control on or off, or changes a session's permission mode (higher or lower, its own or
another's), is refused. The reason names the command that puts the exact action in the owner's queue:

```bash
brain queue add --kind action --guard guard-0123456789 [--item ID]
```

The owner then switches it in the app (the toolbar's Remote Control switch, the session's permission mode, or
Settings for the default). The category is `security-settings`, never grantable: `brain permissions check` refuses an
allow rule that names those tools, Remote Control or a permission mode, at every level. `BRAIN_GUARD_ALLOW` does not
lift it, not even `all`. Refusals are in `<BRAIN_HOME>/ledger/guards-<month>.jsonl` (`"check": "security-settings"`).

## The third-party guard

A session never installs or runs a third-party kit (the owner reads it first: wi-brain-guard-third-party). `guard.sh
shell` refuses, in a Bash, PowerShell or Terminal panel call, through wrappers, launchers, nested shells and ssh:

| Check | Shapes |
|---|---|
| `download` | a download piped, through any filter, to a shell or an interpreter reading stdin (`curl ... \| sh`, `wget -qO- ... \| bash`, `curl ... \| python3 -`, `curl ... \| ssh host`, `iwr ... \| iex`, `irm ... \| iex`); a download in a process substitution a shell or `source` runs (`bash <(curl ...)`, `. <(wget -qO- ...)`); a PowerShell statement where `iex` meets a download (`iex (iwr ...)`, a WebClient's `DownloadString`); `sh -c`, `eval` or a here-string whose text is a download's output (`sh -c "$(curl ...)"`) |
| `plugin` | `claude plugin install NAME@MARKETPLACE` whose marketplace is not in the owner's list, or with no marketplace named; `claude plugin marketplace add SOURCE` whose source is not |
| `skills` | `skills add`, through `npx`, `bunx`, `pnpm dlx` or `yarn dlx` |

The owner's list is config.json `adapters.claude.sources`: a marketplace name (no slash) for `plugin install`, a
source (`owner/repo`, a git URL, a folder from the brain's root) for `marketplace add`. The brain's own marketplace,
source repo and folder always pass:

```json
{"adapters": {"claude": {"marketplace": "my-brain", "plugin": "my-core", "source": "me/my-brain",
                         "sources": ["team-kit", "acme/team-kit"]}}}
```

What passes: a download to a file (`curl -o f`, `iwr -OutFile`), a download read as data (`curl ... | jq`, `| python
-m json.tool`), a download then a script that reads its own stdin (`curl -o f ...; python - <<EOF`), `pip install -e
.`, the commands' `--help`, and text that names the shapes (a commit message, a grep). A refusal is an action for the
owner with the call's exact command (`brain queue add --kind action --guard <ref>`, the title « Third-party script »,
« Third-party plugin » or « Third-party skill »); the owner reads the kit, then runs it in their own terminal, which
no hook sees. Override, the owner's: `BRAIN_GUARD_ALLOW=third-party` or `third-party:<check>`.

## Conflict markers

A merge that leaves `<<<<<<< `, `||||||| `, `>>>>>>> ` or a bare `=======` in a file breaks every brain command that
loads it, and a stale merge's generated views still pass the graph check. Two places refuse them (brain.markers):

- the commit guard (check `markers`): a `git commit`, or `git merge|rebase|cherry-pick|revert|am --continue`, whose
  added lines hold one, in the staged diff, in commit `-a`'s changes or in the files an earlier `git add` of the same
  command stages. The reason names the file and line.
- `brain check` (and `brain refresh`): it fails first, before reading anything else, on a store file (its nodes,
  edges and generated views), a journal, a decision log or a record holding one.

A Markdown or reStructuredText setext heading (`=======` under a line of text, in a file with no other marker) and a
file under a `fixtures`, `fixture` or `testdata` folder pass. Override, the owner's: `BRAIN_GUARD_ALLOW=markers`.

## A public repo's commits, a chained push, heredocs

Three guards the lessons registry asked for (`brain lessons --follow`):

- **The public check at the commit** (`public:commit`): in a checkout whose branch pushes to a repo of config.json's
  `public.repos` (its pushRemote, else its remote, else origin: a private fork's public upstream is not checked), a `git commit` whose added lines hold a denied term outside `public.allow` (the owner's name, a
  private repo's), an e-mail address, a home folder or a `public.patterns` match is refused with the file and the
  line, at the commit rather than at the push (les-brain-owner-name-in-fixtures). It reads what the commit records:
  the staged diff, commit `-a`'s changes, the files an earlier `git add` of the same call stages (untracked ones too,
  but not after `git add -u`), each by its path in the repo, so `public.allow` matches from a subfolder. Override, the
  owner's: `BRAIN_GUARD_ALLOW=public:commit`.
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

## The usage governor

### What it reads

- the quota readings the sessions note: `brain usage quota --observe PCT --resets RESETS_AT [--window 5h]`
  (get_usage's percent used and reset time), in `<BRAIN_HOME>/usage/quota.jsonl`, and the last forecast,
  `usage/quota.json` (its percent now, the last 24 h's pace, the $ per % of the week);
- the sessions: the desktop app's session files (`%LOCALAPPDATA%/Claude-Data/*/claude-code-sessions`, read only),
  else the session records `<BRAIN_HOME>/sessions/*.json`;
- the machine's committed memory (Windows; elsewhere the memory in use);
- config.json `usage.guard` and the registry's `usage:` entries, cached in `<BRAIN_HOME>/cache/governor.json`.

### What it decides, in order

| Check | Tools | Decision |
|---|---|---|
| `critical`: a window in force at `critical` % or more | all | deny |
| `stale`: the newest reading older than `fresh_minutes`, on a machine with a reading in the last 7 days | session, workflow | deny, with the commands that note both windows |
| `memory`: committed memory at `memory` % or more | session, workflow | deny |
| `sessions`: the sessions running reach the cap | session | deny |
| `brainstorms`: the open brainstorms reach the cap, for a brainstorm | session | deny |
| `warn`: a window at `warn` % or more | all | ask the owner |

The parallel sessions cap is the smaller of `sessions` and what the week's room pays for:
`(100 - week %) x $ per % / (wave_hours x session_hour_usd)`, minus one for the master. A session runs when the app
shows it not archived and active in the last `live_minutes`.

A brainstorm is a session whose brief says `Task class: brainstorm` or carries `#brainstorm` (the session record's
`task_class`), or whose title matches `brainstorm_title` (default: it starts with "Brainstorm"). It is open while not
archived and active in the last `brainstorm_hours`, in any project. A brainstorm start the governor lets through is
noted in `<BRAIN_HOME>/usage/starts.jsonl` and counted for 10 minutes, until the app shows its session.

### A master's start_session (the master's watch)

When none of the checks above holds, a `start_session` call goes through, and two things happen (ST-3, ST-4): the
budget watch's mark of the calling session is expired, so its next tool call checks it at once (it may have just
become a master); and if the watch last saw it past 80 % of its budget (`<BRAIN_HOME>/budget/<session>.json`, its
`master`), the call carries a reminder as hook context: past 80 % a master starts no new child, it hands over to a
fresh master and drains its own. It is never a refusal: no guard blocks start_session.

### Configuration (config.json `usage.guard`)

```json
{"usage": {"guard": {"warn": 80, "critical": 95, "sessions": 8, "brainstorms": 3, "memory": 90,
                     "wave_hours": 4, "session_hour_usd": 14, "fresh_minutes": 60, "live_minutes": 30,
                     "brainstorm_hours": 12}}}
```

Every key is optional (the defaults above, except `brainstorms`: 2). `"enabled": false` turns the governor off. A
project lowers its own caps in `projects.yaml`, never raises them:

```yaml
lab: {root: ../lab, usage: {brainstorms: 1, sessions: 4}}
```

`brain config --check` and `brain check --all` report a value of the wrong shape (it is left at its default).

### Reading it

```bash
brain usage guard          # the windows, the sessions and brainstorms, the memory, the caps, each tool's decision
brain usage guard --json
```

Every refusal, ask and override is a line of the guards ledger with `"guard": "usage"` and its check.

### Overriding it (the owner only)

```bash
brain usage allow --hours 2 --reason "finish the demo"   # in your own terminal
brain usage allow --hours 0                              # end it now
```

The guards refuse `brain usage allow` to a session, and any write of its file (`<BRAIN_HOME>/usage/allow.json`).
`BRAIN_GUARD_ALLOW=usage` in Claude Code's environment lifts it too, for every session started with it.

### Not applied here

`CLAUDE_CODE_WORKFLOW_MAX_CONCURRENT_AGENTS` (how many workflow agents run at once; about 8 on a machine like the
scale study's) is Claude Code's own setting: the owner sets it through their installer's plan, never a session.

## Troubleshooting

- **Every start is refused as stale**: a session reads get_usage, then notes each window it shows
  (`brain usage quota --observe 41 --resets 2026-11-09T12:00Z`). A machine that never notes a reading is not checked.
- **The hook seems silent**: `brain perf --engine --task "hook governor"` shows each run's time and the errors it
  caught (`ledger/errors.log` has their text); a missing Python lets every call through.
- **A cap looks wrong**: `brain usage guard` shows the count and where it comes from (`app` or `records`).
