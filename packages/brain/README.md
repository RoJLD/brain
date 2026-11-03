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
- **views**: the owner's queue (`brain queue`), the status of every project (`brain status`), a cockpit (`brain tui`),
  a resume pack for agents (`brain resume`), digests, usage and cost ledgers, forecasts;
- **the machine**: its profile (`brain profile`, alias `brain doctor`: Lite, Default, Recommended, Custom), stacks
  started on demand (`brain up|down|health`), permissions rendered for Claude Code (`brain permissions`);
- **Claude Code**: the hooks and guards under `src/brain/adapters/claude/hooks/` (rules injection, capture, the
  PreToolUse guards: production checkouts, the owner's own actions, a session's Remote Control and permission mode,
  power, attribution, secrets, public pushes, branch names; the usage governor before a new session, a subagent or a
  workflow), which `brain render --target claude` copies into the owner's own plugin;
- **publishing**: `brain check --public` refuses anything private (the owner's denied terms, secrets, personal data
  shapes, data files) before a push to a public repo, and its guard holds the push until the check is green.

## Install

Python 3.10 or later. The command depends on PyYAML and on `research-graph` at the same tag.

```bash
pip install "brain @ git+https://github.com/RoJLD/brain.git@v0.2.2#subdirectory=packages/brain"
```

On Windows, `installer/install.ps1` does it in a venv of its own (`~/.brain/venv`, `BRAIN_HOME`), puts the `brain`
launcher on the user PATH, and, for a personal brain, sets up its Claude configuration (marketplace, plugin,
permissions, memory) and the machine's pointer `<BRAIN_HOME>/personal.json`. It prints a plan; `-Apply` does it. The launcher is replaced even while a brain runs (a session's hooks call it): a new one is swapped in beside it, the old one renamed aside and removed on the next run.

```powershell
.\packages\brain\installer\install.ps1                       # the plan
.\packages\brain\installer\install.ps1 -Apply                # the command
.\packages\brain\installer\install.ps1 -Apply -Personal D:\me\brain   # and this personal brain's setup
```

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
brainstorm) and `ultracode` (whether it was on at any time), so the ledgers tell ultracode spend apart.

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

## License

MIT
