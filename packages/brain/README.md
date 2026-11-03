# brain — the command

One command for a personal brain, at zero token: a person's or a team's rules, decisions, backlog, journal and
records, kept in a private git repo of their own and readable by people and by agents. This package is the engine
only: it holds no one's data. Each owner's brain is their own repo; the engine reads it through a small contract
(`config.json`, `projects.yaml`, the graph stores) and through paths it is given.

What it does, every command reading files and git, never a model:

- **records**: decisions put to the owner (DDR, `brain decision ask|answer|ack`), session and action records (SR, AR),
  captured by the hooks at zero token (`brain record`, `brain capture`);
- **backlog**: work items, milestones and specs in a `research-graph` store (`brain item add|set|close|link`,
  `brain milestone`, `brain spec`), with the views regenerated and checked (`brain sync`, `brain check`,
  `brain refresh`);
- **history**: the journal (`brain journal add`) and the decision log (`brain adr new`), append-only;
- **views**: the owner's queue (`brain queue`), the status of every project (`brain status`), a cockpit (`brain tui`,
  its title bar the installed version and a newer one when out), a resume pack for agents (`brain resume`), digests,
  usage and cost ledgers, forecasts;
- **updates**: `brain update` shows the plan to the latest engine tag and installs it on the owner's yes;
- **the machine**: its profile (`brain profile`, alias `brain doctor`: Lite, Default, Recommended, Custom), stacks
  started on demand (`brain up|down|health`), permissions rendered for Claude Code (`brain permissions`);
- **Claude Code**: the hooks and guards under `src/brain/adapters/claude/hooks/` (rules injection, capture, the
  PreToolUse guards: production checkouts, the owner's own actions, a session's Remote Control and permission mode,
  power, third-party kits, attribution, secrets, conflict markers, public pushes, branch names; the usage governor before a new session, a subagent or a
  workflow; a command a session types into the owner's Terminal panel, `run_in_terminal`, meets the same shell
  guards), which `brain render --target claude` copies into the owner's own plugin;
- **publishing**: `brain check --public` refuses anything private (the owner's denied terms, secrets, personal data
  shapes, data files) before a push to a public repo, and its guard holds the push until the check is green.

## Install

Python 3.10 or later. The command depends on PyYAML and on `research-graph` at the same tag.

```bash
pip install "brain @ git+https://github.com/RoJLD/brain.git@v0.2.4#subdirectory=packages/brain"
```

On Windows, `installer/install.ps1` does it in a venv of its own (`~/.brain/venv`, `BRAIN_HOME`), puts the `brain`
launcher on the user PATH, and, for a personal brain, sets up its Claude configuration (marketplace, plugin,
permissions, memory) and the machine's pointer `<BRAIN_HOME>/personal.json`. It prints a plan; `-Apply` does it. The launcher is replaced even while a brain runs (a session's hooks call it): a new one is swapped in beside it, the old one renamed aside and removed on the next run.

```powershell
.\packages\brain\installer\install.ps1                       # the plan
.\packages\brain\installer\install.ps1 -Apply                # the command
.\packages\brain\installer\install.ps1 -Apply -Personal D:\me\brain   # and this personal brain's setup
```

### Updates

`brain update` (since 0.2.4) reads the latest release tag of the engine's public repo (`config.json` `engine.repo`,
else RoJLD/brain) with `git ls-remote`, no token, and prints the plan: the version and its CHANGELOG sections, the
tag installed into the brain's venv (pip, the `tui` extra kept), the launcher swapped in on Windows (as the installer
does, even while a brain runs), and, for a brain that pins its engine (`config.json` `engine.pin`), the pin to move by
a reviewed PR, shown and never done. It installs only on the owner's yes: `y` at its prompt, or `--yes`; never from a
Claude Code session's shell. `brain update --check` prints the plan and installs nothing; `--json` gives its data. A
checkout installed editable is not updated by pip (`git pull` there).

The cockpit's title bar always shows the installed version. Once the screen is drawn, it checks the tags in the
background (kept 24 h in `<BRAIN_HOME>/update.json`, silent offline) and shows « brain 0.2.3 · 0.2.4 available »
when a newer one is out; `u` then opens `brain update`'s plan in a confirmation, run on `y`.

A brain that declares its own installer in `config.json` (`"engine": {"repo": ..., "pin": "v0.2.3", "installer":
"install.ps1"}`, a path from the brain's root: its plan without arguments, `-Apply` to install the pinned engine)
gets one more signal: when the installed engine lags the pin, after a pin PR and before `-Apply`, the title bar reads
« brain 0.2.1 · pin v0.2.3: -Apply » and `u` opens that installer's plan, then `-Apply` on `y`. A brain without one,
such as one from `brain init`, keeps `brain update`. Either install runs outside the cockpit, which holds files pip
must replace on Windows: on `y` the cockpit exits, a new window waits for it, runs the install with its output in
view (a failure says so and waits for Enter), then relaunches `brain tui` with the same arguments. A queue
action's `install.ps1 -Apply`, applied with `A` in its detail, goes the same way.

A pinned brain runs its pinned engine. `brain check` warns when the running brain or research-graph is not
`config.json` `engine.pin`: a newer or an older version, or the pin's version from other code (another git revision,
an editable checkout or a folder that is not at the tag, or is dirty). `brain sync`, `brain refresh` and
`brain render --write` then refuse to write, since they would render the plugin's hooks and generate the links with
another engine. After `brain update`, set `engine.pin` to the new tag in `config.json` and commit it (by a
reviewed PR where the brain's main is protected); the refusal names the file and the tag. Otherwise run the pinned
engine, or pass `--force`. A brain with no pin, or a
pin that is not a release tag, is not compared.

### The scout

`brain audit --diff` (the scout, run by the close-item procedure) lists what the units a change touches miss: a
test, the docs, the graph links. It also measures the shape the change gives the code, at zero token: a code file
it takes past 1,000 lines and a Python function whose cyclomatic complexity it takes past 15 are NEW (fixed in the
PR, or justified); a file or a function already past its threshold that grows again is deferred to the repo's debt
item. A dependency added to a manifest (`pyproject.toml`, `requirements*.txt`, `package.json`) that no decision log
of the project names, a `shortcut:` comment without its `ceiling:`, its `trigger:` and its debt item (`wi-...`), and
a symptom fix (an added `type: ignore` or `noqa`, a skipped test, an `except` that swallows everything, a sleep, a
retry, a longer timeout) with no `Root cause:` line are NEW too. The lines `Root cause: ...` and
`Justified: <unit>: <reason>` are read from the PR body (`--pr-body FILE`, `-` for stdin) and the range's commit
messages; a justified finding is shown and never blocks. The thresholds are the project's, in `projects.yaml`:
`audit: {max_lines: 1000, complexity: 15}`.

## Start your own brain

```bash
brain init ~/my-brain --owner "Your name"            # the plan
brain init ~/my-brain --owner "Your name" --apply    # writes it; a second apply changes nothing
cd ~/my-brain && git init && git add -A && git commit -m "my brain"
brain check                                          # graph-check OK, and the boundary's public scan green
brain profile                                        # this machine's profile: Lite unless you choose another
brain item add wi-first --title "My first item"
# Claude Code, once: the brain's own folder is a local marketplace
claude plugin marketplace add ~/my-brain
claude plugin install brain-core@brain
```

`brain init` writes, from a template (`--template`, default `generic`: `src/brain/templates/generic/`) and
`research_graph init`, never over an existing file. `--owner` may be left out in a folder that already has a
`config.json` (its `identity.owner`). The generic template:

| File | What it holds |
|---|---|
| `config.json` | the contract, v1: `identity` (the owner's id, the name the views show, `display_name`, a person or a team, a tenant), `registry`, `rules`, `memory`, `records`, `template` (its name and version), `engine` (this repo and the tag installed), `tier` (Lite by default), `adapters.claude` (the marketplace `brain` and its core plugin `brain-core`), `public` (no public repo yet; `deny`: the owner's name, this machine's user and host names); `brain config --keys` lists every key |
| `projects.yaml` | the registry: one project, the brain itself (`brain projects --keys`), its repo audited with the rendered plugin waived |
| `boundary.yaml`, `fixtures/README.md` | every file's side (`brain boundary`) at `readiness_max: 0`: `src/`, `tests/` and `fixtures/` may be published one day, so from the first commit `brain check` refuses a denied term, a secret, an e-mail address or a home folder in them, and a file no rule classifies |
| `source/packs.yaml` | the neutral source the agent files are rendered from: the marketplace's owner and one core pack with the engine's hooks |
| `notes/graph/` | the brain's graph store, its `owner` the same as config.json's, in three layers: the work (items, milestones, specs), the decisions (ADRs) and the records (DDR, Session, Action), which `brain sync` generates from `records/` |
| `.claude-plugin/marketplace.json`, `plugins/brain-core/` | the Claude Code marketplace and its core plugin (its manifest and the engine's hooks: the rules injection, the guards, the capture), rendered after the store by `brain render --target claude --write`'s code, so `brain check` passes at once |
| `notes/decisions.md`, `notes/journal.md` | the decision log and the journal, append-only |
| `rules/global.md` | neutral starter rules for every project (definition of done, decisions, scripts before rules): edit them |
| `CLAUDE.md`, `README.md`, `.gitignore`, `.gitattributes`, `memory/`, `records/` | the repo's own rules and what it is, LF endings (the hooks' shell scripts), the memory notes and the records |

A template is data and a manifest, never code: `template.yaml` gives its `name`, `version`, the `engine` versions that
can render it (`">=0.2.2"`), a `title`, its `graphs` (a list of `{name, store, schema}`, the brain's main store
first, each started by `research_graph init`; `schema: default` only for now) and its `files` (`{the brain's path:
the template's file}`, `""` for an empty one), rendered with `{owner}`, `{owner_q}` (quoted for YAML or JSON),
`{name}` and `{title_q}`. It must write what config.json names (`projects.yaml`, `rules/global.md`,
`source/packs.yaml`, `memory/`, `records/`); the engine writes config.json, the graph stores and the Claude
marketplace itself. `--template DIR` takes a folder of your own holding one. A template is public data; the owner's
records live in their own brain.

It also writes `<BRAIN_HOME>/personal.json` when the machine has none, so that the hooks and commands run from any
folder find this brain. The brain is the owner's private repo: push it to their own account, never to a public one.
A team uses `--kind team` (and `--tenant ID` for a hosted brain). The step-by-step guide from an empty machine is
[`docs/install.md`](../../docs/install.md); the pilot's is [`docs/pilot.md`](../../docs/pilot.md).

Claude Code gets the hooks, the guards and the injected rules from the brain's own folder: `claude plugin marketplace
add <the brain's folder>` once, then `claude plugin install brain-core@brain`. The rendered files are never edited by
hand (`brain check` refuses them); after an engine upgrade, `brain sync` renders the plugin again. A rendered file
that already exists and differs is kept by `brain init` and named (`brain render --target claude --write` replaces
it). config.json names no `adapters.claude.source`, so the installer's marketplace steps (a GitHub marketplace) stay
off.

## The owner's queue

`brain queue` lists what waits on the owner: decisions, actions only they may do, permissions an agent lacked. It is
ranked at zero token by what each entry holds up, in three bands: **now** (blocking, the critical path, a P0 or a
deadline within 2 days), **this week** (a P1, a slip on a milestone, a deadline within the week, a milestone within 14
days) and **when you can**. Within a band, the owner's own order first (`brain queue order ID N [--band B]`,
`--clear`), then a score whose terms `brain queue --explain` shows:

| Term | From |
|---|---|
| priority | the highest priority among the open items and milestones it holds up (P0 8, P1 4, P2 2, P3 1) |
| count | how many it holds up, 0.25 each, at most 3: many P3s never outweigh a P1 by number |
| slip | the critical path's slip per day of waiting, from the last `brain forecast` (its saved `latest.json`) |
| milestone | how near the nearest held-up milestone's p50 is |
| deadline | a stated deadline (the DDR's `due`, `brain queue add --due`; or a `due`/`deadline` prop of what it holds up): 12 overdue, 10 within 2 days, 6 within the week, above any count |
| effort | the owner's minutes (`--minutes`; a decision's reading time), a quick one a little higher |
| age, blocking | the days it has waited (at most 2), and 4 for a blocking one |

The same bands show in `brain status`, the cockpit's queue panel (a Band and a Score column, sorted and filtered by
band) and the morning batches (`brain decision batch --zen`: the band now always in the session). A denied tool call
expires once every session it was refused in is archived or gone in the Claude desktop app.

The views name the owner by `identity.display_name` (else `identity.owner`): the queue's title is « Ada's queue », or
« File d'Ada » with `"lang": "fr"` in `<BRAIN_HOME>/tui.json`'s settings (or `$BRAIN_LANG`), and « My queue » when no
one is named; `settings.titles` there gives any panel a free title. `identity.owner` stays the id `--by` writes and the
stores declare.

### The owner's answers: one writer per batch

The session that asks the owner records the answers, in one PR per batch (wi-brain-answers-lane):

1. `brain decision batch --json` prints the questions for Claude Code's question tool, and writes each one (its text,
   header and labels, the DDR's id) to `<BRAIN_HOME>/ledger/asked-<month>.jsonl`.
2. When the tool returns, the capture hook ties each answer to the DDR its question came from (the id a repeated
   question carries, else its text and header, else its header and labels) and writes it to
   `ledger/answer-<month>.jsonl`: the answer exactly as the tool returned it, the labels it names (the DDR's own,
   `(Recommandé)` dropped; a multiple choice is the labels joined by `, `, the rest of it the owner's text) and the
   owner's notes. A question the session wrote by hand stays an ad-hoc DDR of the capture.
3. `brain decision answer --captured` records this session's captured answers: a worktree of the project's main
   checkout on `claude/answers-<stamp>` from origin's default branch, the answers written, `brain refresh --offline`,
   one commit, one PR (`gh`), then merged; when the merge is refused because main moved, it merges main, takes main's
   side of the generated files, refreshes again, pushes and retries (`--retries`, default 3; `--no-merge` stops at
   the PR). A record that conflicts stops it. A decision answered meanwhile is left (`--again` replaces it).

`--batch` is strict: a value is an option's exact label (any case, `(Recommandé)` ignored) or its number; a shortened
label is refused with the label it shortens, and the owner's own text is marked as such, `{"other": "..."}`. Its file
may start with a BOM (UTF-8, or UTF-16 from Windows PowerShell's `>`). In an agent's session (`CLAUDECODE`),
`brain decision answer` and `--batch` record only an answer this session's own question tool captured: an answer
relayed by a message is never recorded; the session that gets it applies it and acknowledges it (`brain decision
ack`) once the asking session has recorded it and the mid-session announce names it. The owner's own terminal records
anything.

### Decisions by default, then reviewed

`brain decision ask --low-stakes` marks a decision whose recommendation the asking session may apply at once,
provisionally (wi-brain-decision-default): the DDR gets `default: {option, after}`, `after` 24 h from the ask. The
owner may answer it as any other; without an answer, `brain refresh` (or `brain decision defaulted --apply`) records
the recommendation as its answer, `by: default`, `via: default`, at the deadline, and the hooks announce it with « by
default ». The mark is refused, at the ask and by `brain check`, on a decision whose text names money, keys,
visibility, publication, accounts, arming, rules or scheduled tasks (`brain.defaults.REFUSED`, by words: a false alarm
only keeps the decision with the owner). `brain decision defaulted` is the owner's review list (the defaults to
review, the provisional ones, the reversed ones; `--seen` marks them read, from the owner's terminal only), with a
line in the morning batch (`brain decision batch --zen`) and in the cockpit's queue panel (`brain tui`); any default is reversed with `brain decision answer ID
<option> --again`.

## Parallel sessions

Three zero-token commands for many sessions on one brain ([`docs/merge-driver.md`](docs/merge-driver.md)):

- **`brain merge-driver`**: a local git merge driver for the paths `.gitattributes` gives `merge=brain` (`brain init`
  writes them): a generated view keeps one side and is marked for `brain refresh`, the journal and the decision log
  are unioned in date order, the graph's edges and a CHANGELOG's Unreleased section are unioned, the other graph YAML
  is merged by id, anything else as git would. The installer defines it in the personal brain's git config
  (`brain merge-driver install --apply`); `brain merge-driver replay` merges a repo's past merges again with and
  without it.
- **`brain collisions [--all] [--frontier] [--json]`**: the files each open branch and worktree changes, crossed with
  each startable item's predicted surface (its features' CodeRefs, its module, the files it names): the items that
  can start now, and those that wait on a branch and its session.
- **`brain brief ITEM [--class C] [--budget B] [--coordinator ID]`**: a sub-session's brief from the graph: the item
  and its subgraph, its collisions, the class's model and effort (config.json `brief.classes`), the budget, the cost
  estimate, the coordinator's id, and the definition of done and the never-list read from the owner's rules.

## Lessons

What each finished item teaches is a node of the graph, so it can be found, counted and fixed, at zero token
([`docs/lessons.md`](docs/lessons.md)):

- **`brain retro ITEM`**, a step of the close-item procedure: the friction signals of the sessions that served the
  item (merges and conflicts, guard refusals, failed tests, waits, tokens against the estimate, the owner's minutes,
  pushes to its PRs after they were opened), the known lessons of the signals that fired and five questions; the
  session answers in a few lines (`--record --note ...` writes them on the item). `brain retro --wave W`: a wave's
  deep retro.
- **`brain lesson add|seen`**: a Lesson node (`nodes/lessons.yaml`) with its trigger, anti-pattern and check, learned
  from an item or a PR; a lesson close to a known one is refused, to be marked `seen` instead. A lesson seen twice
  (once if severe) with nothing fixing it, or recurring after its fix, files an item proposal, its fix a script
  first, a rule last.
- **`brain lessons --follow`**: each lesson and what it led to (the item, its PR, whether it recurred since), and the
  friction per item by week. **`brain lesson rules`**: the iron rules (`Σ-NAME`) cited in each registered repo's
  Markdown, read only. **`brain lint lessons`**: the lessons a script could check (guard candidates) and those that
  should say why not.

## Where the brain is found

`config.json` and `projects.yaml` are found at `$BRAIN_CONFIG` / `$BRAIN_PROJECTS`, else in the first of:
`$CLAUDE_BRAIN_DIR`, `$BRAIN_PERSONAL`, the repo acted on (a worktree of the brain reads its own files), then the
machine's pointer `<BRAIN_HOME>/personal.json` (`{"root": ...}`, written by the installer and by `brain init`). The
repo acted on is `--root`, else `$BRAIN_ROOT`, else the nearest folder above with `notes/graph/schema.yaml`, else the
personal brain. Machine-local state (ledgers, sessions, the resume pack, the vault) lives in `BRAIN_HOME`
(`~/.brain`), never in a repo.

## The Claude Code hooks

`src/brain/adapters/claude/hooks/` is package data: `hooks.json` and a `.sh` launcher per hook, each running its `.py`
entry with `$BRAIN_PYTHON`, else the brain command's venv (`<BRAIN_HOME>/venv`), else `python3`/`python`. A personal
brain whose `source/packs.yaml` gives its core pack `hooks:` gets them copied into its own plugin by
`brain render --target claude --write`, at the version it pins; `inject-rules.sh` injects the files of config.json
`rules`. The guards never block a session on an error: without Python, the call goes through.

A hook costs every tool call its time, so the launchers start nothing they do not need: they read their JSON and find
Python with bash builtins (`hooks/common.sh`, no `$(...)`), and `guard.sh` starts Python only for a shell command that
may write, names `gh`, a program of the owner and power guards, `claude plugin` or `skills add`, or git other than to
read (`git [-C DIR] status`, `log`, `diff`, `show`, `rev-parse`... without `--output`: `brain.guards.GIT_READS`,
checked against the guards' tables). In Python a guard reads the registry through libyaml and does not import `urllib.request`.

Two guards keep what a session brings in and what it records clean (the runbook: [`docs/guards.md`](docs/guards.md)):

- **Third-party kits** (`guard.sh shell`, check `third-party`): a session never installs or runs a third-party kit. A
  download fed to a shell or an interpreter (`curl ... | sh`, `bash <(curl ...)`, `sh -c "$(curl ...)"`, `iwr ... |
  iex`, `iex (irm ...)`), `claude plugin install` and `claude plugin marketplace add` from a source outside the owner's
  list (config.json `adapters.claude.sources`; the brain's own marketplace always passes) and `npx skills add` are
  refused, each an action for the owner's queue with its exact command (`brain queue add --kind action --guard
  <ref>`). A download to a file (`curl -o`) passes; what the owner types in their own terminal is never seen.
- **Conflict markers** (check `markers`): a git commit, or a merge, rebase or cherry-pick `--continue`, whose staged
  lines add `<<<<<<< `, `||||||| `, `>>>>>>> ` or a bare `=======` is refused with the file and line; `brain check`
  fails on a store, journal, decision log or record file that holds one. A Markdown setext heading (`=======` under a
  line of text) and a file under a `fixtures` folder pass.

Two of the PreToolUse hooks keep the owner's say over how sessions run (the runbook: [`docs/guards.md`](docs/guards.md)):

- **Session settings** (`guard.sh tool`, `brain.guards`): a session that changes Remote Control or a permission mode
  (`set_remote_control`, `set_session_permission_mode` under any MCP prefix, the app's `set_setting` for a Remote
  Control key) is refused, whatever the value, and the exact action goes to the owner's queue (`brain queue add
  --kind action --guard <ref>`). Its category, `security-settings`, is never grantable (`brain permissions`), and
  `BRAIN_GUARD_ALLOW` does not lift it, not even `all`: the owner switches it in the app.
- **The usage governor** (`governor.sh`, `brain.governor`), before `start_session`, `Agent` and `Workflow`: it reads
  the cached quota readings (`brain usage quota --observe`), the sessions running and the brainstorms open on the
  machine (the desktop app's session files, else the session records), and the committed memory. It asks the owner
  from `warn` % of a quota window, refuses from `critical` %, refuses a new session past the parallel sessions cap
  (the smaller of `sessions` and what the week's room pays for), a new brainstorm past `brainstorms` (every project
  counted; a project's `usage: {brainstorms: N}` in `projects.yaml` lowers it for itself, never raises it), a new
  session or workflow from `memory` % of committed memory or while the newest quota reading is older than
  `fresh_minutes`. The thresholds are config.json `usage.guard`; `brain usage guard` shows what each tool would get
  now. A refusal names its reason and the owner's override: `brain usage allow [--hours H]` in their own terminal
  (the guards refuse it to a session), or `BRAIN_GUARD_ALLOW=usage`. Its decision takes under 50 ms.

The session record (`brain capture`, the Stop hook) holds the brief's `task_class` (trivial, standard, strategic,
brainstorm) and `ultracode` (whether it was on at any time), so the ledgers tell ultracode spend apart. The capture
hooks run `brain.capture` (`capture.sh <event>` runs `hooks/capture.py`, which calls it with the brain command's
venv): it reads the hook's JSON on stdin and appends the session events, the session-record snapshots and the action
records to `<BRAIN_HOME>/ledger` at zero token; it prints nothing and never fails the session (its errors go to
`ledger/errors.log`; `BRAIN_CAPTURE=0` turns it off).

**The engine times itself** (`brain.selftime`, local only, zero token). Every `brain` command and every hook writes
one exec event (task `brain <command> [<subcommand>]` or `hook <name>`, a bash-only run marked `[bash]`, the engine's
version, its duration from the engine's import or the hook's first line, its exit) to
`<BRAIN_HOME>/ledger/engine/exec-<yyyy-mm>.jsonl` (`exec-bash-...` for the bash fast paths); every error a hook or a
command catches becomes an error event there (its exception class and the engine's `module:function`, never its
message, whose text stays in `ledger/errors.log`). The last three months are kept. `brain perf --engine` lists the
slowest commands and hooks, the regressions from one engine version to the next, the hooks' blocking time per week
and the errors caught; `brain alerts` raises a hook or a command that caught the same exception 3 times in 24 hours,
on the brain's own project. `BRAIN_SELFTIME=0` turns it off.

```
brain perf --engine [--since 7d] [--task guard] [--json]
```

## Data classes and the vault

Every store of a brain declares a data class in `config.json` (`classes.stores`: public, private, confidential,
sealed, resident, secret, `tenant:<id>`), and the class says where it may go and how; `brain check --all` refuses a
store without a class and a destination its class forbids, and `brain init` writes a starting block. What leaves a
machine is sealed client-side to public keys (`brain vault`: age, gpg as the fallback), to a device key per machine,
kept in the OS keystore, and an offline recovery key: two recipients at least, proven daily by a canary per recipient
(`brain health vault`). Opening, drilling and creating a key are the owner's acts, refused in an agent session. The
owner's steps, the canary's scheduled task per system and what to do with a lost key: the runbook
[`docs/vault.md`](docs/vault.md).

```
brain classes [--check] [--suggest] [--matrix] [PATH...]
brain vault status | seal STORE | canary | recipient add NAME | device init | open FILE | drill RECIPIENT
brain health vault
```

## Tests

From a checkout of this repo, with research-graph from the same checkout:

```bash
pip install -e . && pip install --no-deps -e packages/brain && pip install pyyaml pytest
pytest packages/brain
```

The tests run as an invented owner, Ada (`tests/fixtures/brain/config.json`, set for every test by `conftest.py`
through `BRAIN_CONFIG`), with a temporary `BRAIN_HOME`; they need git, and bash for the hooks (Git Bash on Windows).

## Releasing

With research-graph, under the repo's single tag series: see the root README. `CHANGELOG.md` here is the command's.
A release moves `brain_version` in `src/brain/adapters/claude/hooks/common.sh` with `__version__` (the hooks' bash
fast paths stamp it on their events; `tests/test_selftime.py` checks the two agree).

## License

The Business Source License 1.1, from version 0.2.2: `LICENSE` (its parameters at the top) and `NOTICE` (the credit to
keep). Its Additional Use Grant allows you to use, modify and run the brain command for your own work, as a person or
an organisation, and to reuse it in your own products, provided each product gives a visible credit to Brain and its
author in its documentation or its about screen (`NOTICE` gives a credit line) and the `NOTICE` file is kept with every
copy you distribute. Offering it to third parties as a hosted or managed service needs a commercial licence from the
licensor. Each version changes to the Apache License 2.0 four years after its release.

Versions 0.2.0 and 0.2.1 were released under the MIT License and stay under it. `research-graph`, the graph engine
this package depends on, stays under the MIT License (the repo's root `LICENSE`).
