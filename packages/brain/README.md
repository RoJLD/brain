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
  PreToolUse guards: production checkouts, the owner's own actions, power, attribution, secrets, public pushes,
  branch names), which `brain render --target claude` copies into the owner's own plugin;
- **publishing**: `brain check --public` refuses anything private (the owner's denied terms, secrets, personal data
  shapes, data files) before a push to a public repo, and its guard holds the push until the check is green.

## Install

Python 3.10 or later. The command depends on PyYAML and on `research-graph` at the same tag.

```bash
pip install "brain @ git+https://github.com/RoJLD/brain.git@v0.2.1#subdirectory=packages/brain"
```

On Windows, `installer/install.ps1` does it in a venv of its own (`~/.brain/venv`, `BRAIN_HOME`), puts the `brain`
launcher on the user PATH, and, for a personal brain, sets up its Claude configuration (marketplace, plugin,
permissions, memory) and the machine's pointer `<BRAIN_HOME>/personal.json`. It prints a plan; `-Apply` does it.

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
brain check                                          # graph-check OK
brain profile                                        # this machine's profile: Lite unless you choose another
brain item add wi-first --title "My first item"
# Claude Code, once: the brain's own folder is a local marketplace
claude plugin marketplace add ~/my-brain
claude plugin install brain-core@brain
```

`brain init` writes, from `src/brain/templates/` and `research_graph init`, never over an existing file:

| File | What it holds |
|---|---|
| `config.json` | the contract, v1: `identity` (the owner, a person or a team, a tenant), `registry`, `rules`, `memory`, `records`, `engine` (this repo and the tag installed), `tier` (Lite by default), `adapters.claude` (the marketplace `brain` and its core plugin `brain-core`); `brain config --keys` lists every key |
| `projects.yaml` | the registry: one project, the brain itself (`brain projects --keys`) |
| `source/packs.yaml` | the neutral source the agent files are rendered from: the marketplace's owner and one core pack with the engine's hooks |
| `notes/graph/` | the backlog's graph store, its `owner` the same as config.json's |
| `.claude-plugin/marketplace.json`, `plugins/brain-core/` | the Claude Code marketplace and its core plugin (its manifest and the engine's hooks: the rules injection, the guards, the capture), rendered after the store by `brain render --target claude --write`'s code, so `brain check` passes at once |
| `notes/decisions.md`, `notes/journal.md` | the decision log and the journal, append-only |
| `rules/global.md` | neutral starter rules for every project (definition of done, decisions, scripts before rules): edit them |
| `CLAUDE.md`, `.gitignore`, `memory/`, `records/` | the repo's own rules, the memory notes and the records |

It also writes `<BRAIN_HOME>/personal.json` when the machine has none, so that the hooks and commands run from any
folder find this brain. The brain is the owner's private repo: push it to their own account, never to a public one.
A team uses `--kind team` (and `--tenant ID` for a hosted brain).

Claude Code gets the hooks, the guards and the injected rules from the brain's own folder: `claude plugin marketplace
add <the brain's folder>` once, then `claude plugin install brain-core@brain`. The rendered files are never edited by
hand (`brain check` refuses them); after an engine upgrade, `brain sync` renders the plugin again. A rendered file
that already exists and differs is kept by `brain init` and named (`brain render --target claude --write` replaces
it). config.json names no `adapters.claude.source`, so the installer's marketplace steps (a GitHub marketplace) stay
off.

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
