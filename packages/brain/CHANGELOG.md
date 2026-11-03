# Changelog — brain

The command shares the repo's tag series with `research-graph`: `vX.Y.Z` is both at X.Y.Z.

## Unreleased

- **The Business Source License 1.1 from this version** (wi-brain-engine-license). The brain package leaves the MIT
  License: `LICENSE` (BSL 1.1 and its parameters) and `NOTICE` (the credit to keep) sit in `packages/brain`, and
  `pyproject.toml` declares `license = "BUSL-1.1"` and `license-files` (PEP 639: building the package needs setuptools
  77 or later). The Additional Use Grant allows any use, modification and running for your own work and reuse in your
  own products, with a visible credit to Brain and its author and the NOTICE kept; offering it to third parties as a
  hosted or managed service needs a commercial licence. Each version changes to the Apache License 2.0 four years after
  its release. 0.2.0 and 0.2.1 stay under the MIT License, and so does research-graph. Tested
  (`tests/test_license.py`).
- **`install.ps1 -Apply` replaces a running launcher.** Sessions' hooks run `brain.exe` many times a minute, and
  Windows refuses to overwrite a running image, so the last step of `-Apply` (the copy to `<BRAIN_HOME>\bin`) failed
  twice. `Set-Launcher` leaves an identical launcher alone, copies a new one beside it and swaps it in with a short
  retry, and renames a still-locked one aside (`brain.exe.old-<time>`, removed on the next run); it prints `same`,
  `copied` or `swapped`. Tested on a running image (`tests/test_installer_launcher.py`).
- **The queue in three bands, ranked by what each entry holds up** (wi-brain-queue-priority). `brain queue` scores
  each entry at zero token: the highest priority and the count of the open items and milestones it holds up, the
  critical path's slip per day of waiting and the nearest milestone (the last `brain forecast`, through
  `forecast.waiting`), a stated deadline above the count, the owner's minutes, its age and the blocking flag. Bands:
  now, this week, when you can. `--explain` shows each term; `brain queue order ID N [--band B] [--clear]` sets the
  owner's own order, which wins; `brain queue add --minutes`, and DDRs gain an optional `minutes`. `brain status`, the
  cockpit's queue panel (Band and Score columns, the band sort first and a band filter) and the zen batches show the
  bands. A denial (perm-, guard-) expires once its session is archived or gone in the desktop app.
- **The owner's display name** (wi-brain-owner-label, UX-16). `config.json` `identity.display_name`
  (`config.name_of`) names the owner in the cockpit's titles, help, confirmations and the text views; `identity.owner`
  stays the id `--by` writes. The queue's title is « {name}'s queue » or « File de {name} » (`tui.json` settings
  `lang`, or `$BRAIN_LANG`), « My queue » when no one is named, and `settings.titles` gives any panel a free title.
- Fixed: a date-typed prop (`due: 2026-11-08`) no longer breaks `brain queue`.
- Fixed: the cockpit reads `tui.json`'s settings again after two writes that share one modification time (Windows'
  coarse clock): its cache keys on the time and the size, and `save_state` clears it.
- **A session's Remote Control and permission mode are the owner's** (wi-brain-guard-session-settings). The guards
  refuse `set_remote_control` and `set_session_permission_mode` under any MCP prefix, and the app's `set_setting` for
  a Remote Control or permission key, whatever the value; the refusal names the `brain queue add --guard` command
  that queues the exact action for the owner, and goes to the guards ledger. `brain.permissions` gains the
  never-grantable category `security-settings` (an allow rule naming those tools, Remote Control or a permission
  mode is refused at every level), and `BRAIN_GUARD_ALLOW` cannot lift it, not even with `all`.
- **The usage governor** (wi-brain-usage-enforce, `brain.governor`, `hooks/governor.sh`): a PreToolUse hook on
  `start_session`, `Agent` and `Workflow` that asks the owner at the quota's WARN and refuses at CRITICAL (both quota
  windows read, the 5-hour one when a reading of it is noted), refuses a new session past the parallel sessions cap
  (config, lowered to what the week's room pays for: room / (wave hours x $ per session-hour) minus the master), a
  new brainstorm past the machine's brainstorms cap (2 by default; a project may lower it for itself, never raise
  it; a brainstorm is known by its brief's `Task class: brainstorm` or `#brainstorm`, or its title), a new session
  or workflow from 90 % of committed memory or while the newest reading is stale (on a machine that notes readings).
  config.json `usage.guard` holds the thresholds and caps; projects.yaml entries gain `usage:`. It reads cached
  state only: its decision takes under 50 ms. `brain usage guard [--json]` shows what each tool would get now;
  `brain usage allow [--hours H] [--reason TEXT]` is the owner's override, which the guards refuse to a session
  (the command and any write of its file). `CLAUDE_CODE_WORKFLOW_MAX_CONCURRENT_AGENTS` stays the owner's to set
  through their installer.
- **The session record knows ultracode and the task class.** The SR gains `ultracode` (on at any time: the app's
  `ultra_effort_enter` attachment) and `task_class` (the brief's, brainstorm included).

## 0.2.1 — 2026-11-03

- **A new brain gets its own Claude Code plugin.** `brain init` renders a local marketplace in the new brain: it
  writes `source/packs.yaml` (the marketplace's owner, one core pack with the engine's hooks) and config.json
  `adapters.claude` (the marketplace `brain`, the plugin `brain-core`, no `source`), then, after the store,
  `.claude-plugin/marketplace.json` and `plugins/brain-core/` by the code of `brain render --target claude --write`,
  so `brain check` passes at once; a rendered file that exists and differs is kept. The owner adds the marketplace
  once (`claude plugin marketplace add <the brain's folder>`, then `claude plugin install brain-core@brain`): a local
  marketplace's plugin is loaded in place, so its hooks are those of the installed engine, and `brain sync` renders
  them again after an upgrade. Nothing of the owner's leaves the machine, nothing is published.
## 0.2.0 — 2026-11-03

The brain command, published as this repo's second distribution, from the personal brain it was written in (a fresh
history: its code, Claude hooks, tests and installer at their targets, then the changes below).

- **The digest dates closures at any hour.** `digest.git_closures` bounds `git log` by full days at midnight and keeps
  the commits whose own day falls in the window: a bare `--since=<day>` was read at the current time of day, so a
  closure from the first day of margin showed up or not depending on the hour (failing before noon UTC).
- **Python 3.10 reads pyproject.toml.** The `tomli` backport is a dependency below 3.11, and `brain.inventory` falls
  back to it: the audit, the scout and the links measured nothing on 3.10 without `tomllib`.
- **A package of its own.** `packages/brain`: `pip install "brain @ git+https://github.com/RoJLD/brain.git@v0.2.0#subdirectory=packages/brain"`;
  it depends on `research-graph` at the same tag. The Claude hooks are package data
  (`src/brain/adapters/claude/hooks/`), copied into the owner's own plugin by `brain render --target claude`; the
  engine's narrow allow rules too (`src/brain/adapters/claude/allow-rules.txt`, read by `brain permissions`).
- **The personal brain, found from anywhere.** `$BRAIN_PERSONAL`, then the machine's pointer
  `<BRAIN_HOME>/personal.json` (`{"root": ...}`), join the places `config.json`, `projects.yaml` and `permissions.yaml`
  are looked for (after `$CLAUDE_BRAIN_DIR`; the pointer after the repo acted on, so a worktree reads its own files),
  and the repo acted on falls back to the personal brain (`brain.paths.bases`, `personal_root`). `inject-rules.sh`
  reads the pointer too; `brain config` shows it.
- **The hooks find the installed engine.** Every hook's launcher tries `$BRAIN_PYTHON`, then the brain command's venv
  (`<BRAIN_HOME>/venv`), then `python3` and `python`: a plugin folder without the package runs the installed one.
- **`brain init`**: a new personal brain from `src/brain/templates/` (config.json v1 with the engine pinned at this
  tag and the Lite tier, projects.yaml, the graph store by `research_graph init --owner`, journal, ADR log, neutral
  starter rules, CLAUDE.md, memory and records) and the machine's pointer; a plan, `--apply` writes it, nothing is
  overwritten.
- **The installer** (`installer/install.ps1`) installs the command at the tag config.json `engine.pin` names (or its
  own version without a personal brain; `-Engine` for another pip spec), takes the personal brain from `-Personal`
  (its main checkout, never a worktree), writes the pointer, and runs the Claude steps only when config.json names a
  marketplace and rules.
- **`brain check --public --history`** also reads the commits' messages (every check of a line) and their author's
  and committer's e-mail addresses (a no-reply one passes).
- Tests: the ones that read the personal brain's own files stay there; the permission tests read a neutral fixture
  (`tests/fixtures/permissions.yaml`).
