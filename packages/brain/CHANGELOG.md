# Changelog — brain

The command shares the repo's tag series with `research-graph`: `vX.Y.Z` is both at X.Y.Z.

## 0.2.1 — 2026-11-03

- **`brain init` for a stranger, from a template.** `--template NAME|DIR` (default `generic`, the only one the engine
  ships): a template is data and a manifest (`template.yaml`: name, version, the engine versions it fits, title, the
  files it renders with `{owner}`, `{owner_q}`, `{name}`, `{title_q}`), never code; a bad manifest, an engine outside
  its range or a template missing what config.json names plans nothing. config.json records it (`template`, a new key
  of the schema). `--owner` defaults to the owner of the folder's config.json. The generic template's files moved to
  `templates/generic/`.
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
