# Changelog — brain

The command shares the repo's tag series with `research-graph`: `vX.Y.Z` is both at X.Y.Z.

## Unreleased

- **The cockpit knows its version and offers updates** (wi-brain-tui-update-check, ADR UPD-1 to UPD-3). The title
  bar of `brain tui` always shows the installed version (the text view's header too). Once the screen is drawn, a
  worker reads the release tags of the engine's public repo (`config.json` `engine.repo`, else RoJLD/brain) with
  `git ls-remote`, no token, no credential helper, no prompt; the answer is kept 24 h in `<BRAIN_HOME>/update.json`,
  and offline it says nothing. When a newer tag is out the title reads « brain 0.2.3 · 0.2.4 available » and `u`
  opens `brain update`'s plan in the cockpit's confirmation, run on `y` only.
- **`brain update`**: the plan to the latest tag (the version, its CHANGELOG sections read from the tag, the tag
  installed into `<BRAIN_HOME>/venv` with pip and the `tui` extra kept, the launcher swapped into `<BRAIN_HOME>/bin`
  even while a brain runs, install.ps1's Set-Launcher in Python, and for a pinned brain the `engine.pin` to move by a
  reviewed PR, shown, never done), installed on the owner's yes only (`y` at the prompt, or `--yes`), refused in a
  Claude Code session's shell. `--check` prints the plan and installs nothing; `--json` its data. An editable install
  is left to `git pull`. The tests never read the network (conftest fakes the tags offline).
- **The pilot's settings in the docs**: `docs/install.md` says, before the first session, `BRAIN_MEMORY_SYNC=0`, the
  venv at `%USERPROFILE%\.brain\venv` or `BRAIN_PYTHON`, Git Bash's `HOME` (else `BRAIN_HOME`), telemetry off by
  default, and how to upgrade by hand from a version without `brain update`; `docs/pilot.md` how updates come during the pilot.
- **The owner's answers, one writer per batch** (wi-brain-answers-lane). Two batches of answers went wrong in two days:
  a shortened label stored as free text, and a BOM that made `--batch` write nothing. Now `brain decision batch`
  writes the questions it prints to the ledger (`asked-<month>.jsonl`), the capture hook ties each answer of the
  question tool to the DDR its question came from (by the id it carries, else its text and header, else its header
  and labels) and writes it to `answer-<month>.jsonl` with the labels as the tool returned them and the owner's notes,
  and `brain decision answer --captured` records the session's captured answers in a worktree on `claude/answers-…`,
  refreshes, opens one PR and merges it, merging main and retrying when it moved (`--retries`, `--no-merge`). `--batch`
  is strict: an inexact label is refused, naming the label it shortens, unless it is marked free text
  (`{"other": ...}`); a BOM is read, UTF-8 or UTF-16. In an agent's session, `answer` and `--batch` record only what
  that session's question tool captured: an answer relayed by a message is never recorded, it is applied and acked.
  The capture also drops the French `(Recommandé)` mark from an ad-hoc question's labels.
- **Decisions by default, then reviewed** (wi-brain-decision-default). `brain decision ask --low-stakes` gives the DDR
  a `default` (its recommendation, final 24 h later): the asking session applies it at once, provisionally; without
  an answer, `brain refresh` or `brain decision defaulted --apply` records it `by: default`, `via: default` at the
  deadline and the hooks announce it « by default ». The mark is refused, at the ask and by `brain check`, on money,
  keys, visibility, publication, accounts, arming, rules and scheduled tasks. `brain decision defaulted` is the
  owner's review list (`--seen` from their terminal), with a line in the morning batch and the cockpit's queue panel; `answer ID <option> --again`
  reverses a default. The DDR schema gains `default` and the answer's `via: default`.

## 0.2.3 — 2026-11-03

- **`brain check` passes on a store that holds another repo's links.** Since 0.2.2, `brain sync` derives the Doc, Test
  and Workflow nodes of a project's other repos (those its CodeRefs name) into the store; their anchors are paths of
  that repo (`docs/install.md#...`), which research_graph 0.2.2 read under the store's repo, so `brain check` and
  `brain refresh` failed on every one. Such a node now says `repo: <name>` (written before its anchor), and `brain
  check` gives research_graph check each other repo's checkout (`--repo-path`, research-graph 0.2.3), found as `brain
  audit` finds it: from the project's root, else from its main checkout when the root is a worktree. A repo whose
  checkout is not on the machine is not checked (an advisory). Tested from a main checkout and from a worktree
  (`tests/test_links.py`); research-graph pinned at v0.2.3.

## 0.2.2 — 2026-11-03

- **The hooks read their JSON as UTF-8, whatever the console's codepage** (wi-brain-hook-stdin-utf8). On Windows,
  `python -I` decodes a pipe with the ANSI codepage (cp1252), so a hook got non-ASCII text as mojibake: an emoji
  before « Generated with » came out as letters, and the attribution guard let that line through; every guard read
  accents and « » wrong. The guards, the capture, the governor and the resume hook now read `sys.stdin.buffer` as
  UTF-8 with the BOM a PowerShell pipe adds dropped (`midsession.read_payload`, as the budget and midsession hooks
  already did; wi-brain-hook-stdin-bom), the memory and health hooks drain bytes, every launcher runs
  `python -X utf8 -I` (stdout in UTF-8), and the attribution pattern takes any prefix but letters. Tested from a
  cp1252 stdin and through `guard.sh` with raw UTF-8 (`tests/test_hook_stdin.py`).

- **The suite is green on Linux.** Three places misread Windows shapes off Windows: a PowerShell word's backslash is
  now a path separator wherever `os.path` reads only slashes (`guards.BACKSLASH_SEP`), as PowerShell reads it, so
  `Set-Content {lab}\x` is seen in the production checkout; a `cmd /c` option is slashes and a name without a
  separator (`guards.CMD_OPTION`: `/c`, `//J`, `/XD`), so a Unix absolute path is a target, not an option; and
  `detail.preview` finds `.\install.ps1` by its last part on either separator. The 26 advisory `brain-linux` failures
  of main go away.
- **The Terminal panel meets the shell guards** (wi-brain-guard-terminal-tool). A command that the desktop app's
  `run_in_terminal` types into the owner's Terminal panel ran outside every guard: production checkouts, the owner's
  own actions (`brain usage allow` included), power, attribution, secrets, public pushes and branch names. A
  PreToolUse matcher on `mcp__*terminal__run_in_terminal` now judges it as a shell call (`guard.sh shell`):
  PowerShell on Windows, the panel's shell there, else bash, in the tab's `cwd`, else the session's folder.
- **A brain fresh from `brain init` passes `brain check --all`.** It failed at once with « config.json declares no
  data classes ». A template's `template.yaml` gains `classes`, its own stores, checked when the template loads. The
  generic template classes `memory/` and `records/ddr/` confidential, opted in to `cloud-model`, with a waiver on
  `git-private` until encrypted git is adopted. `init` writes config.json's `classes` block: the template's stores,
  then the engine's machine stores (sealed), then a private catch-all. Its next steps name `brain classes`,
  `brain vault status` and the vault's runbook.
- **The vault's runbook ships with the engine** (`docs/vault.md`): the classes, the owner's steps once per machine,
  the daily canary as a scheduled task for Windows, macOS and Linux, the drill, a lost key. `brain vault status` links
  it. An empty `.gitkeep` holds no data for the classes check.
- **The Business Source License 1.1 from this version** (wi-brain-engine-license). The brain package leaves the MIT
  License: `LICENSE` (BSL 1.1 and its parameters) and `NOTICE` (the credit to keep) sit in `packages/brain`, and
  `pyproject.toml` declares `license = "BUSL-1.1"` and `license-files` (PEP 639: building the package needs setuptools
  77 or later). The Additional Use Grant allows any use, modification and running for your own work and reuse in your
  own products, with a visible credit to Brain and its author and the NOTICE kept; offering it to third parties as a
  hosted or managed service needs a commercial licence. Each version changes to the Apache License 2.0 four years after
  its release. 0.2.0 and 0.2.1 stay under the MIT License, and so does research-graph. The READMEs and
  `docs/pilot.md` say it. Tested (`tests/test_license.py`).
- **The links of a project's other repos** (`brain.links`). A store's CodeRefs may name another registered repo of
  its project (an engine whose code a personal brain describes, say). `brain sync` now also derives that repo's Doc,
  Test and Workflow nodes into the store's `_generated_links.yaml`, from its committed state (the commit `brain audit`
  reads), with the `tested_by` and `documented_in` edges from the nodes that stand for its code: the files of their
  CodeRefs, and a Hook's scripts found there by their `hooks/<name>` (the store's repo renders them from that repo). A
  Skill, a Plugin and the Spec anchors stay the store's repo's. A repo whose checkout is not on the machine is left out,
  and `brain sync` says so. `brain audit` measures `doc.links` and `test.links` of such a repo against that store
  (until now: "no store of its own to hold the links"). A repo no CodeRef names is not derived, so a project's
  production checkouts add nothing.
- Fixed: `code_index:` entries resolve like `repos:` (`projects._resolve_root`): from a project rooted in a worktree, a
  sibling of the main checkout (`../brain`) is found there, not looked for beside the worktree.
- `brain.capture` is documented in the README (the capture hooks' module); `hooks/health.sh` has its end-to-end test;
  `brain lint rules` lost its fallback to a plugin's own `rules/global.md` (the package left the plugin folder).
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
- **`brain init` for a stranger, from a template.** `--template NAME|DIR` (default `generic`, the only one the engine
  ships): a template is data and a manifest (`template.yaml`: name, version, the engine versions it fits, title, the
  graph stores it starts, a list of `{name, store, schema}` with the main store first and only research_graph's
  default schema for now, and the files it renders with `{owner}`, `{owner_q}`, `{name}`, `{title_q}`), never code;
  the plan stays local, a list of steps a later one (the owner's repos and data store) can join; a bad manifest, an
  engine outside its range or a template missing what config.json names plans nothing. config.json records it (`template`, a new key
  of the schema). `--owner` defaults to the owner of the folder's config.json. The generic template's files moved to
  `templates/generic/`.
- **The generic store holds the records** (GT-2, wi-brain-init-records-layer). A template's `schema: default` is
  the brain's base (`templates/schemas/default.yaml`): the work, decisions and records layers, so that `brain sync`
  turns a new brain's DDRs, sessions and actions into nodes from the first sync; `research_graph init` builds the
  store, then `brain init` writes this schema in its place (a new store only).
- **Publishable by construction.** The generic template writes `boundary.yaml` (every file's side, `readiness_max: 0`,
  `src/`, `tests/` and `fixtures/` on the engine side), `fixtures/README.md`, a `README.md` and `.gitattributes` (LF:
  the hooks' shell scripts), and config.json `public` (no repo; `deny`: the owner, this machine's user and host,
  leaving out names too common to deny). `brain check` runs the boundary's check and the engine side's public scan
  wherever a boundary.yaml is (`brain.public.gate`): a file no rule classifies, or a denied term, a secret, an e-mail
  address or a home folder in what may be published, fails it from the first commit. `projects.yaml` waives the
  rendered plugin in `brain audit`, so a fresh brain carries no debt of the engine's.
- **The stranger test.** `installer/stranger_test.py` installs a tag (or, `--pre-tag`, a branch with research-graph
  from the same ref) into a fresh venv, isolated from its caller (its own home, BRAIN_HOME, Claude and git config, a
  PATH with no docker, Git's bash for the hooks on Windows), runs the Lite scenario as an invented owner and scans
  every output and file for the terms given with `--deny`; its verdict is a pilot's go. `docs/install.md` (Windows
  from zero, Linux and macOS) and `docs/pilot.md` (what to try, how to report an issue) are the tester's.

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
