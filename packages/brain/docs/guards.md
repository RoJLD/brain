# Runbook: the session-settings, third-party and conflict-marker guards, and the usage governor

Two PreToolUse hooks of the engine's Claude Code plugin keep the owner's say over how sessions run. Both are scripts,
not rules: they decide before the call, at zero token, and never break a session (an error lets the call through and
goes to `<BRAIN_HOME>/ledger/errors.log`, but for a session's Remote Control or permission mode, where it refuses,
and for a commit or push the public and secrets checks cannot judge: see « The public and secrets checks fail
closed »).

| Hook | Tools | Decides |
|---|---|---|
| `guard.sh tool` (`brain.guards`) | `mcp__*__set_remote_control`, `mcp__*__set_session_permission_mode`, the app's `set_setting` for a Remote Control or permission key | refuses, but Remote Control's three exceptions |
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
another's), is refused, but in Remote Control's three exceptions (below). The reason names the command that puts the exact action in the owner's queue:

```bash
brain queue add --kind action --guard guard-0123456789 [--item ID]
```

The owner then switches it in the app (the toolbar's Remote Control switch, the session's permission mode, or
Settings for the default). The category is `security-settings`, never grantable: `brain permissions check` refuses an
allow rule that names those tools, Remote Control or a permission mode, at every level. `BRAIN_GUARD_ALLOW` does not
lift it, not even `all`. Refusals are in `<BRAIN_HOME>/ledger/guards-<month>.jsonl` (`"check": "security-settings"`).

### Remote Control's three exceptions

The owner decided three cases where a session switches Remote Control itself (wi-brain-guard-rc-archive, the ADRs of
2026-11-04 on archiving and on the coordinators' handover). `mcp__ccd_session_mgmt__set_remote_control` (the desktop
app's own server; any other prefix gets the plain refusal) passes in exactly these, checked by the guard
(`brain.guards.remote_control`), and is refused otherwise, the reason saying which condition failed:

| Case | Call | The guard checks |
|---|---|---|
| `archive` | `enabled: false` on another session, just before archiving it | the caller started it; it is `idle` or `ended` (its transcript's tail); it is no live coordinator (by name or title) |
| `handover-on` | `enabled: true` on another session | the caller is a coordinator started by a coordinator; it started the target; the target is a coordinator, live on this machine; the caller's hand-over note exists |
| `handover-off` | `enabled: false` on `self` (or its own id) | the caller is a coordinator started by a coordinator; its hand-over note exists; it started a coordinator that is detached and live on this machine |

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
- **Live on this machine**: `running`, `idle`, `asking` or `stale`; not archived, and not `unknown` (no transcript).
- **Detached**: the app's `lineageDetached` (`brain.sessions` reads it as `detached`).
- **The hand-over note**: a regular `*.md` file (no link) in `<BRAIN_HOME>/handover/`, at most 512 kB, written in the
  last 6 hours (not in the future), whose first `local_…` id in its first 2,000 characters is the caller's: a note
  opens with whose it is, so the successor's note, which names its predecessor after itself, is not the
  predecessor's.

Each allowed call is logged in the guards ledger with `"decision": "allowed"`, its `case` and its input; a pass the
ledger does not take (no ledger, `BRAIN_CAPTURE=0`) is a refusal. Anything the guard cannot read (no app files on the
machine, a caller it cannot identify, an input of another shape) is a refusal, and so is an error once the hook's
JSON is read: for a session's security settings the guard fails closed, where every other guard lets the call
through (a payload that is not JSON, which Claude Code never sends, names no tool and passes as before). Not checked, because a hook
cannot see it: that an `archive_session` follows the `archive` case, and whether the target's PRs are merged and its
worktree clean (the first ADR's wording); the turn being idle stands for « finished ». `set_session_permission_mode`
and the app's settings stay refused in every case.

What it does not hold against: its inputs are files a session can write. A session that writes into the app's
session files, or a note naming itself, is tampering, not drifting; the guard holds against a mistake, and the app
still asks the owner to approve each switch unless its permission mode decides. The note is the handover's
procedural mark (the ADR's « une fois sa note écrite »), not a credential. The names are chosen by the session that
starts a child, so a session that starts a `coordinator-x` which starts a `coordinator-y` has built the mark; the
guard checks one hop of lineage, not the whole chain back to the owner. While its note is under 6 hours old, a
coordinator may turn Remote Control on for any coordinator it started, not only one. After a new root coordinator
(started by the owner, so unnamed), the first two handovers stay the owner's gesture: the root has no name, and its
first successor's parent is no coordinator by name.

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

Three guards the lessons registry asked for (`brain lessons --follow`):

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
  `patterns`, `refuse`) of another type (`brain config --keys`), a `v` that is not a whole number, or above the one the engine reads (`brain update`), `$BRAIN_CONFIG` naming no file, or no
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
| `memory`: committed memory at `memory` % or more, or available RAM under `memory_available_gb` GB (default 0: no floor) | session, workflow | deny, naming both measures and the one that refused |
| `sessions`: the sessions running reach the cap | session | deny |
| `brainstorms`: the open brainstorms reach the cap, for a brainstorm | session | deny |
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
noted in `<BRAIN_HOME>/usage/starts.jsonl` and counted for 10 minutes, until the app shows its session (a log rotated
monthly, two months kept; the governor reads the live file and the newest monthly one, so a start just before the
month turned still counts).

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
  caught (`ledger/errors.log` has their text); a missing Python lets every call through, but a git commit or git
  push, which guard.sh refuses (« the guards cannot run »: `brain update`, or `install.ps1 -Apply`).
- **Every commit and push is refused with « cannot trust the configuration »**: `brain config --check` shows what is
  wrong in `config.json`; `brain config` shows which file was found and the personal brain `personal.json` names.
- **A cap looks wrong**: `brain usage guard` shows the count and where it comes from (`app` or `records`).
