# Changelog — brain

The command shares the repo's tag series with `research-graph`: `vX.Y.Z` is both at X.Y.Z.

## Unreleased

### Fixes

- `brain status` reads the quota's clock from `usage.now_utc`, like the rest of the quota: a test that froze that clock
  saw the real time in the status row, and failed on every commit once its fixed reset (2026-11-09 12:00 UTC) had passed.

### Changes

- `brain usage quota` converts dollars to percent with the readings of the plan in force only
  (wi-brain-quota-per-plan; config.json `usage.plans`, a reading's own `plan` first): a median across an Ultra and a
  Pro week was neither plan's quota. Until the plan has 3 converted readings (`quota.CAL_MIN`) the conversion is
  reported `uncalibrated` (in the text, the JSON's `uncalibrated` and the `brain status` line), the weekly window is
  not converted, and the 5-hour window is estimated from its latest reading plus the ledger's cost since
  (`window_5h`). The weekly reset is still read from every reading: it is the account's.
- `brain --project P` run from a linked git worktree of P's repo acts on that worktree, not on the registry's root
  (wi-brain-root-from-cwd). An explicit `--root` still wins; a cwd in another repo or a plain folder keeps the
  registry's root.

### Added

- `schedules:` entries take `days` (mon to sun), the days `at` runs on, so that a weekly command can be declared and
  installed like any other (`days: [mon]`): a `ScheduleByWeek` trigger on Windows, `OnCalendar=Mon ...` under systemd,
  the day-of-week field in a crontab. A task whose days changed is planned as an update (wi-brain-schedule-hidden-all).
- **Quiet mode** (wi-brain-quiet-mode): `brain quiet --for 2h` or a project's `notify: quiet_hours: "22:00-07:00"`
  (local time) holds every notification below `critical`; a critical one still goes through. The held ones are summed
  up in one message per project when the quiet ends (`brain quiet --off`, or the next alerts pass). No task is
  paused and no scheduled task is touched: collection and the alerts pass run on. The state is in `brain quiet`,
  `brain status` and the cockpit's health card. A send during a quiet reports `held` (`brain notify send` exit 0).
  Takes effect once this release is installed.

### Fixed

- `brain <cmd> --help` no longer crashes without a stdout (pythonw.exe, Python 3.10: argparse wrote to None); it
  survives a cp1252 pipe too, the CLI already writing UTF-8 with `errors=replace` (`wi-brain-help-encoding`). Takes
  effect with the next tagged release.

## 0.2.6 — 2026-11-09

### Upgrade

From 0.2.5, in this order. No hand edit of a brain's data is needed: the upgrade test (`compat-prev`,
`docs/release.md`) installs this engine over a brain 0.2.5 wrote, moves the pin and runs `brain sync`, `brain check`
and `brain record check`.

1. **Check the configuration first**, with 0.2.5 still installed: `brain config --check` and `brain config` (its `file`
   and `personal`). The public and secrets checks now fail closed (wi-brain-guards-fail-closed, COMPAT-4): from
   the install on, every `git commit` and `git push` is refused on a machine whose `config.json` is unreadable or not
   an object, has a `public` (or one of its keys) of another type or a `v` above 1, whose `$BRAIN_CONFIG` names no
   file, or whose `personal.json` names a folder without `config.json` (a renamed personal brain); so too when the
   hooks find no Python that imports brain. An unknown key never refuses. The override is
   `BRAIN_GUARD_ALLOW=public:config`.
2. **Install the engine**, in your own terminal, not from a Claude Code session: `brain update`, then `y`. 0.2.5 runs
   this update and only reminds you of the pin. A brain whose `config.json` declares `engine.installer`: merge the PR
   that moves `engine.pin`, then run the installer's `-Apply` instead.
3. **Move the pin and render the hooks.** Run `brain update` again and answer `y`: 0.2.6 now does what 0.2.5 left to
   you (wi-brain-update-moves-pin, COMPAT-5): it writes `engine.pin`, commits `config.json` alone (never pushed) and
   runs `brain sync`, which rewrites `guard.sh` and `health.sh`. With changes in `config.json` not committed, it leaves
   the pin and says so. A brain that declares its installer: run `brain sync` after `-Apply`; its pin never moves
   except by the reviewed PR.
4. **Restart the Claude Code sessions**, so that no older bash hook from the plugin cache keeps running.
5. **Refresh the public stamp**: run `brain check --public --history` in each public repo's checkout before its next
   push (wi-brain-public-stamp-binding). A stamp written by brain 0.2.5 or older has no key, and the push guard
   refuses it, as it refuses any stamp made under another engine, other public rules or with gitleaks gained or lost.
   So this step comes back after every engine upgrade.

Nothing to run for these:

- **The cockpit's number keys now go to tabs** (wi-brain-tui-layout). Nothing to run: 1 is the queue, 2 the sessions, 3
  the frontier, 4 the milestones, 8 health and 0 the overview, where 1 to 8 used to focus a panel of the grid. `m` is
  offered only where a tab shows several panels, and Escape goes back one step at a time: the search, a full view, then
  the overview. `tui.json` gains `tab` and `tabs`;
  an older engine ignores them and forgets them at its next save.

- Nothing to run for the machine-local state (wi-brain-state-safe-io). `vault/state.json` gains `"v": 1` at its
  next write, which brain 0.2.5 reads unchanged; `schedules/installed.json` and `alerts/state.json` keep their v 1
  unwritten. Each of the four files may now have a `<name>.bak` beside it, and a file that was unreadable a
  `<name>.unreadable-<stamp>`: both are safe to delete once you have looked.

- Nothing to run. Outside CI, a check that used to fail on an unknown key in `config.json`, `permissions.yaml`,
  `packs.yaml`, `projects.yaml` or a record now prints a note instead; CI (`CI` set) still fails on it. A `v` above 1
  in `config.json`, `permissions.yaml` or a record was refused before and is still refused, now with « brain
  update »; `packs.yaml`'s `v`, written but never read until now, is refused the same way.

### Changes

- **The release checklist** (wi-brain-release-checklist; spec-brain-data-compat, gate item 6). `docs/release.md` says
  every step of a release, from the version PR to the pin. CI's new `release-check` job (`installer/release_check.py`,
  standard library only) reads the last tag on every pull request. On a version PR, it fails when a registered schema
  changed since that tag and this version's CHANGELOG section has no `### Upgrade` with something in it, and when
  the two `__version__`, the research-graph pin, the hooks' `brain_version` and both CHANGELOGs' dated sections do not
  agree: what `release-tag` used to find out only after the tag. Any other pull request passes it at once. An Unreleased
  section now keeps its `### Upgrade` apart from its `### Changes`.

- **The cockpit's tabs** (wi-brain-tui-layout, UX-2, UX-18; spec 2026-11-03 cockpit-ux-round2 §4.0). One tab per
  question, in data (`cockpit.TABS`: key, label in English and French, question, views and their panels, count): 0
  overview, 1 queue, 2 sessions, 3 frontier, 4 milestones, 8 health (alerts on top;
  audit debt, stacks and index, and a new frame of exec times with the slowest steps). Ideas (5), lessons (6), features
  (7), resources (9) and settings (the comma) arrive with their items, and until then their key says so. The bar shows
  each tab's state in digits and signs (the queue's band now, the sessions asking `!`, the open alerts), a click on it,
  ctrl+pageup and ctrl+pagedown change tab, and its tooltips name each tab with its key and question. Under 120 columns or 30 rows the bar is reduced to its
  numbers, the active tab named, the grid is not offered and the health frames stack. A tab keeps its panels' cursor and
  scroll: they are the same widgets, laid out again. `v` or a click in the toolbar changes the view; the toolbar says
  the tab's question and holds an `[i]`; the global bar says the last change and the next probe. The last tab and each
  tab's view are kept in `tui.json`. `brain tui --tab NAME` starts there, and with `--once` or `--plain` prints that
  tab's panels alone.

- **The cockpit's column chooser and palette** (wi-brain-tui-layout; spec cockpit-ux §4.4). `C` chooses a table's columns
  (`cockpit.columns`, `brain.tui_palette`): shown or hidden, their order, and the longest its title may be, the rest in
  the detail; the sessions also offer Cost, App id, Id and Branch (`EXTRA_COLUMNS`), the Cost column sorting by cost. They
  are kept in `tui.json`'s `columns`, which an older engine ignores and forgets at its next save. A state's colour follows its word wherever it is
  placed. The palette (`ctrl+p`, `cockpit.palette`) gains an entry for each tab and view, project, sort, filter and table's
  columns, and « Reset the views », which keeps the project, the theme and the timezone.

- **The cockpit's detail beside the list** (wi-brain-tui-layout, UX-20; spec cockpit-ux-round2 §4.0.2). From 140 columns,
  on a tab that is one list (`cockpit.detail_beside`), a row's detail sits right of the list and follows the cursor
  (`brain.tui_side`): it is read once the cursor rests, in a worker thread, and remembered per row until its panel changes,
  so an arrow held down reads nothing. Enter gives it the focus, Escape gives it back, `o` opens a link from it, and `a`, `d`
  and `A` work from the list too, after the same confirmation. Narrower, or on a tab of several panels, Enter opens it
  over them as before.

- **The cockpit's overview: one card per tab** (wi-brain-tui-layout, UX-19; spec cockpit-ux-round2 §4.0.3). The overview
  opens on its cards (`cockpit.cards`, each tab declaring its own): the queue's band now, the sessions asking, the nearest
  milestones, what can start, the open alerts, worst first across the projects, and the audit. Enter or a click opens
  the tab, already filtered as the card says, its search cleared, by a filter that is never saved and goes when the tab
  is left (the filters dialog makes it the owner's); the arrows move between them, and they take one column on a narrow terminal. The grid and the digest are its other views
  (`v`). `brain tui --once --tab overview` prints the cards. In the digest view the frame no longer repeats its title on
  each project and above the digest (L9); in the grid, open alerts take a whole row (L11). A key now moves the focus at
  once, so `1` then Enter opens the queue's row, not the previous tab's. A table's cell is text, never markup: a title
  like « Move [/docs] out » crashed the cockpit, and « [blocking] » vanished from the queue's Id column.

- **A public-check stamp is valid only under the key it was made with** (wi-brain-public-stamp-binding,
  spec-brain-data-compat N2 and finding 11; `docs/formats.md`, « Public-check stamps »). The stamp of a green `brain
  check --public --history` now carries `v` 2 and a `key`: the engine version, the sha256 of config.json's public
  deny, allow, patterns and refuse, and whether gitleaks read the history. The push guard refuses a stamp whose key
  differs from now's (another engine, rules changed since, gitleaks gained or lost), an old-format or unreadable one,
  naming why and the fix, « rerun brain check --public --history ». A check with no commit to read keys gitleaks by
  its presence on the PATH; a gitleaks on the PATH that fails stamps nothing (exit 1, « fix gitleaks or take it off
  the PATH »), since the guard would refuse that stamp; a stamp is written atomically; a newer brain's stamp, a
  nested or unreadable one, or any surprise while reading it refuses the push instead of letting it through.

- **`brain update` moves the pin where no review step exists** (wi-brain-update-moves-pin, spec-brain-data-compat
  COMPAT-5). For a brain whose `config.json` declares no `engine.installer` (one from `brain init`), the plan's last
  steps write the new tag into `engine.pin` (the file's other keys, their order and its indent kept; written
  atomically), commit `config.json` alone (« brain update: engine.pin vX -> vY »), then run `brain sync` with the new
  engine, on the owner's `y` or `--yes`. With the latest engine already in the brain's venv and the pin behind it, the
  plan moves the pin alone. The pin never moves backwards, nor to or from a pin that is not a release tag, nor for an
  editable install; a `config.json` with changes not committed or not tracked, or a brain that is not a git repo or
  is on a detached HEAD, is left as it is (exit 1, with what to do by hand); the commit lands on the current branch,
  never pushed. From a Claude Code session the command refuses, as before, and says to run it in
  the owner's terminal. A brain that declares its installer keeps the reviewed pin PR, shown and never done. The plan's
  `--json` gains `pin.move` (`"write"` or `"pr"`).

- **The cockpit's empty, error and offline states** (wi-brain-tui-states; spec 2026-11-02 cockpit-ux §4.10). An
  empty table shows one line that says why (`cockpit.why_empty`): a filter or the search hides N rows, and the key
  that changes it; nothing in the scope, the owner named; a project not on this machine. A panel not probed yet shows
  the probe's countdown, then its progress project by project (`probe_wait`). `Cockpit.refresh` no longer raises: a
  failed read keeps its panels' content, its error and the data's time go to the snapshot (`errors`, `panel_at`) and
  the panel's frame, the TUI notifies it once, and it is read again at the next tick, a probed panel at the next
  probe (before, a failed graph read waited for the next file change). `--once` and `--json` print a failed read on
  stderr and exit 1 (they used to raise); `--detail` names it when it finds no row. A stack or code index repo not OK
  names its last OK measure. The project selector greys a registered project this machine lacks; `brain tui --all` without a
  registry shows the folder's project instead of exiting. `brain tui --json` gains `errors`, `panel_at`, `probing`
  and `registry`.

- **The cockpit's queue sorts by score** (wi-brain-tui-queue-sort-score). The queue panel's `score` sort ranks by
  the score alone, across the bands: the highest first (an entry without a score last), then what it unblocks, then
  the oldest. It is the second sort of `s`, a click on the Score column, `brain tui --sort queue:score`, and a view
  `tui.json` remembers (a saved sort a panel does not know still falls back to its default). The default stays by
  band, the owner's order, then the score. `brain tui --help` now lists every panel's sorts from the code.

- **Machine-local state is never reset and saved over** (wi-brain-state-safe-io, spec-brain-data-compat N4;
  `docs/formats.md`, « Machine-local state »). `brain.stateio` loads and saves a truth-local file: a file that is not
  JSON, not an object or not its expected shape is set aside as `<name>.unreadable-<stamp>`, never replaced by `{}`
  and saved; a `v` above the engine's makes it read-only (« written by a newer brain: brain update »); every write
  backs up to `<name>.bak` beside the file (a secret is never copied), then writes atomically, synced. It now carries
  `schedules/installed.json` (`brain schedule install --apply` refuses a newer record), `alerts/state.json` (the
  notify pass sends nothing rather than send again each pass), `vault/state.json` (gains a `v`; a non-object no
  longer crashes `brain vault`; `seal`, `canary` and `drill` refuse a newer state before any work; the one-way drill
  migration backs up first) and `usage/sessions.json` (a newer ledger is updated in memory, never saved). The 17
  `return {}` readers are classified in the same page; the rest of the truth-local ones follow. Only a command that
  writes a file sets it aside (`brain status` and the cockpit move nothing); `brain vault reseal --apply` refuses a
  newer state before resealing; a backup that fails (a locked `.bak`) is said and the write goes on.

- **The upgrade test, on every pull request** (wi-brain-upgrade-test; spec-brain-data-compat N8, COMPAT-2 and
  COMPAT-3). `installer/stranger_test.py --upgrade-from TAG|DIR`: the tag writes every registered format into a new
  brain (a decision, an AR, an SR, `permissions.yaml`, its exec events; a format with fixtures and no place in the
  test fails it), then this engine is installed over it and runs strict: the store plan, `brain sync`, `brain check`,
  `brain record check` and the Lite scenario. Then the rollback: the `newer` fixtures' additive keys laid over the
  brain, a canary and a drill on record, the tag installed back, and its check, record check, permissions check,
  vault status (the drill shown), `brain perf` and a newer template's plan run in read mode; a tag with the read mode
  must pass them, 0.2.5 may only refuse the newer keys. Then this engine again makes the same reads, all passing. No
  file of the brain or of the vault may change and the ledgers may only grow, over the whole round trip; after each
  install, `direct_url.json` must name the engine meant. CI's new `compat-prev` job (Windows, pull requests) runs it
  from the last tag (none found fails it) and uploads its report. The stranger test's exit code is 1, not 2, when a
  step fails after a good first install. `docs/formats.md`.
- **The public and secrets checks fail closed** (wi-brain-guards-fail-closed, COMPAT-4; the 2026-11-04 REVERSAL of
  the guards' internal-error policy, for these checks only). A new check, `public:config`, refuses every `git commit`
  and `git push` while `brain.config.unexpected` finds the configuration unexpected: `config.json` unreadable or not
  an object, `public` or one of its keys (`repos`, `deny`, `allow`, `patterns`, `refuse`) of another type, a `v` that
  is not a whole number or is above the engine's, `$BRAIN_CONFIG` naming no file, or no `config.json` found although `$BRAIN_PERSONAL` or `personal.json` names a personal brain. An unknown key never refuses. Each
  reason names its fix (`brain config --check`, `brain update`, `install.ps1 -Apply`). `guard.sh` refuses a shell
  command naming git and commit or push when it finds no Python, or the one it finds cannot import brain (« the
  guards cannot run »); before, it let every call through in silence. The SessionStart health says both (`health.py`
  through `brain.stacks.hook_main`, `health.sh` when no Python can run it). `BRAIN_GUARD_ALLOW=public:config` lifts
  the Python check. `config.json` is now read with or without a UTF-8 BOM (Windows PowerShell 5.1 writes one), as
  the installer reads it. `health.sh` now tries guard.sh's interpreters in guard.sh's order (`$BRAIN_PYTHON` first),
  so what it says of the guards is what they run on. `docs/guards.md`.
- **Remote Control's three exceptions** (wi-brain-guard-rc-archive; the owner's ADRs of 2026-11-04). The
  session-settings guard lets the desktop app's `set_remote_control` through in exactly three cases, each checked
  from the app's own session files and the hand-over notes: off on a finished (idle) session the caller started,
  before archiving it; at a handover between Brain coordinators, on for the coordinator the caller started to succeed
  it, and off on the caller itself once that successor is detached, both once the caller's hand-over note (a `*.md`
  in `<BRAIN_HOME>/handover/` whose first app id is the caller's, under 6 h old) exists. A coordinator is marked by
  the name its starter gave it (`coordinator-g`), never by its title, and must itself have been started by one. Each
  pass is logged in the guards ledger (`"decision": "allowed"`, its `case`), and a pass the ledger cannot take is
  refused; anything the guard cannot read is a refusal, and an error in the guard now refuses a session-settings call
  instead of letting it through. `set_session_permission_mode` and the app's settings stay refused, and
  `BRAIN_GUARD_ALLOW` still lifts nothing. `brain.sessions` reads the app's `lineageDetached` (`detached`). Acts once
  the engine is installed (`install.ps1 -Apply`). `docs/guards.md`.
- **Tolerant readers, strict writers** (wi-brain-tolerant-reader, COMPAT-1's gate; `docs/formats.md`). The schema
  validator gains two modes. Read mode keeps a field it does not know (a newer brain's additive one) and reports it;
  strict mode, for every write and for the checks in CI (`CI` set, or `BRAIN_STRICT=1`), refuses it. A `v` above the
  engine's is refused in both: « `<file>`: v2 is written by brain > 0.2.5, which reads v1: brain update ». It covers
  the five schemas (DDR, SR, AR, event, config.json), `permissions.yaml` (an allow rule with an unknown key is left
  out in read mode, since the key may narrow it), `packs.yaml`, the template manifest (its `engine:` range is checked
  before its keys, so a newer template says « it needs brain >=X ») and `projects.yaml` (`KEYS`, `REPO_KEYS`). A DDR
  or SR rewrite, even one rebuilt afresh (`--replace`, `brain record backfill --update`), puts back the unknown fields
  of the file it replaces and never replaces one a newer brain wrote (backfill counts it `sr-refused`). AR lines
  are parsed one by one: a broken line is an error of `brain record check`, a newer brain's line (a higher `v`, an
  unknown kind) is skipped and counted, and neither stops `brain sync`. Fixtures under `tests/fixtures/formats/`: an
  older and a newer file per format, round-tripped without loss.
- **The validator enforces `maximum`** (wi-brain-schema-keywords). `config.json` `usage.guard` `critical: 950` no
  longer passes and silently turns the governor's refusal off. `brain.schema` refuses a schema that uses a keyword it
  does not implement (or `if`/`then` outside an `allOf` entry of their own, `items` as a list), and a test fails on
  one.
- **The answers' lane on the question tool's real shapes** (wi-brain-capture-multiselect,
  wi-brain-capture-unanswered). The tool returns a multiple choice as a list of labels: the capture of an ad-hoc
  question raised a TypeError and the whole tool call was lost (`ledger/errors.log`). `capture.ddr_from_question` and
  `answers.capture` take the list (or the labels joined by `, `). When the owner sends a message instead of answering,
  the tool returns a placeholder for each question (« [User did not answer this question — they sent a message
  instead. …] »): it was captured as the owner's free text. It is now no answer: nothing is captured for a printed
  question, an ad-hoc DDR stays pending, and `brain decision answer --captured` refuses, lists and retires the rows an
  older engine wrote, `--again` included. A test fixture holds both tool results, copied from real transcripts and
  redacted.
- **The answers' lane, review of #19** (wi-brain-answers-fixes). `--captured` retires what it does not write (a new
  `retired` reason in `answer-recorded`, with each capture's `captured_at`): an older capture of a DDR whose later one
  was recorded never comes back; a capture older than the answer the DDR holds is stale, never written, `--again`
  included. An answer captured before a low-stakes deadline wins: `brain refresh` leaves such a DDR pending, and
  `--captured` replaces a default another branch took meanwhile. A label the session shortened in the tool is kept
  `unmapped` and refused, never recorded as free text. The header-and-labels match looks only at the questions this
  session's batch printed (the asked ledger now records the session). The recorded ledger is read from the month of
  the oldest capture on. The never-by-default check reads amounts with a currency sign (`40€`, `$50`), `-`/`_`
  compounds (`ssh-key`, `API_KEY`, `cron-job`), more synonyms and forms (cost, spend, sign-in, Task Scheduler,
  PyPI, settings.json, a GitHub PAT, `.env`, rotating keys), the recommendation's why and the linked ids; `brain
  check` applies it to pending DDRs only, so a word learned later never fails a decision already answered. A typed
  single-choice answer that starts with a label (« No, because… ») stays the owner's text in an ad-hoc DDR, and a
  joined multiple choice takes the longest label. The review list shows a low-stakes DDR answered in time through
  the question tool as such, not « due now ». A stamp without a zone is UTC instead of a TypeError
  in refresh, the batch and the cockpit. `reversed` is a non-default answer after the deadline (compared as times),
  never one that took the default's option, and `--seen` clears it; `--seen` checks every id before it writes.
  Left for after the command registry (they need `cli.py`): `brain record ddr --answer` without the one-writer
  check, `defaulted --apply` writing main checkouts, `--all --seen ID`, the refresh that writes the records graph
  before taking a default, and printing the refused captures apart from the skipped ones.

- **Git's identity before the first commit** (wi-brain-install-git-identity). A fresh Git for Windows has no
  `user.name` nor `user.email`, and the first commit of `docs/install.md` stopped at « Author identity unknown ».
  `brain init --apply` now asks git, as a commit would (`git var GIT_AUTHOR_IDENT` and `GIT_COMMITTER_IDENT`, from
  the new brain's folder), whether it has an identity; when it has none, its next steps add the `git config --global`
  commands for the keys git's config lacks (the owner's name for a person, a placeholder for a team or a name a shell
  would expand: `$`, a backtick, a backslash, a quote). Nothing is printed when the commit would pass (the config, the
  `GIT_AUTHOR_*` variables, git's own guess) or git is not found. `docs/install.md` (step 3,
  Windows and Linux) and `docs/pilot.md` set the identity before the first commit.
- **The onboarding at the installed tag** (wi-brain-onboarding-tag-links). The vault runbook that `brain init` and
  `brain vault status` print points to `blob/v<the running version>`, not `blob/main`, which may be ahead of the
  engine installed. `docs/install.md` and `docs/pilot.md` say to read them at the tag installed, and now explain the
  vault that `brain init` names: data classes (`brain classes`), optional in the pilot (`vault OFF` until it is set
  up), the runbook for when it is wanted.
- **A command registry** (wi-brain-cli-registry). Each top-level command is now a module of `brain.commands`
  (`src/brain/commands/<name>.py`): its parser (`register(sub, ctx)`), its handlers (`run(args, root)`, and
  `early(args)` for what runs before a root is resolved), its place in `brain --help` (`ORDER`) and its usage lines
  (`USAGE`, `USAGE_ORDER`). `brain.cli` keeps `main` and `build_parser` as a facade: it lists the package, adds each
  module's parser and dispatches to the module, and it no longer holds an `add_parser` call. A new command is a new
  file; the README's « Adding a command » shows one. Nothing a command does or prints changed: `tests/help_dump.py`
  prints the help and the arguments of every command and subcommand (149 parsers), byte for byte the same before and
  after the move.
  - `brain audit`'s new check `cmd.registry` (ruleset 5; P1 on a production path, NEW and LEFT in the scout) flags a
    parser the `cli.py` beside a `commands/` package that lists its modules adds itself, and a module of that package
    with no `register`.
  - The inventory reads `pkgutil.iter_modules(__path__)` in a package's `__init__.py` as an import of each of its
    modules, so the audit's production closure and the tests' reach go through the registry as through an import.
  - The distribution's packages are `brain` and `brain.commands` (`pyproject.toml`): a wheel carries the registry.

## 0.2.5 — 2026-11-04

### Upgrade

From 0.2.4, in a brain that 0.2.4 (or older) initialised, in this order:

1. Move `config.json` `engine.pin` to `v0.2.5` and commit it: until then `brain sync` refuses another engine than the
   pin (the engine-skew refusal since 0.2.4).
2. Run `brain sync`: it rewrites the plugin's `guard.sh`, `health.sh` and `hooks.json`; until then `brain check`
   exits 1.
3. Add the `Lesson` node type to `notes/graph/schema.yaml` by hand, as `docs/lessons.md` shows: `brain lesson add`
   refuses until then, and the close-item retro is skipped with one line meanwhile.
4. Add `notes/modules_graph.md merge=brain` to `.gitattributes`, and the generated `notes/modules_graph.md` to
   `boundary.yaml`, by hand: `brain init` keeps the files it made earlier.
5. Restart the Claude Code sessions, so that no older bash hook from the plugin cache keeps running.

- **The four high findings of the review of the PRs merged without one** (wi-brain-fix-merged-highs).
  - `brain sessions`, the Stop snapshot, the master's watch, the cockpit and `brain check` no longer raise
    `TypeError` on a family that mixes an app child (its `createdAt`, milliseconds) with a ledger-only one (its
    SessionStart, ISO: its app file deleted, or half-written while the app rewrites it): the children sort on one
    start time in seconds (#34).
  - The third-party guard refuses a pipe continued on the next line (`curl URL |` then `sh`, `irm URL |` then
    `iex`): a newline right after `|`, `&&`, `||` or `;` keeps the operator's link (#26).
  - It refuses `iex "& { $(irm URL) }"`, `iex "$(irm URL)"` and `Invoke-Expression "..."` alike, directly or through
    `powershell -c`: PowerShell expands the string's `$( )` before `iex` runs it (#26).
  - `brain decision answer --captured` finds each DDR by its exact id on the default branch: one asked on a branch
    not merged yet is left captured and said (« not on the default branch yet »), the batch's other answers are
    recorded, and a DDR whose id merely contains the captured one is no longer answered in its place
    (`decisions.find(..., exact=True)`; #19).
- **Coverage in the CI** (wi-brain-test-coverage). The `brain` job on Windows, Python 3.12, runs the suite from
  `packages/brain` with `--cov=src --cov-context=test` and keeps the data file as the artifact `coverage-data`, which
  `brain coverage --from coverage.data --cwd packages/brain` reads (`relative_files = true` in packages/brain's
  pyproject.toml; `pytest-cov` joins the test extras). It never fails on a threshold. Docs: `docs/tests-graph.md`.

- **The schedules** (wi-brain-alerts-pass). The registry's new `schedules:` key, `{name: {command, every, at,
  at_logon, machines, timeout, enabled}}`, declares the brain commands a machine's scheduler runs, the alerts pass
  every 15 minutes and at logon first. New `brain schedule install [--apply] [--json]` (`brain.schedule`): the plan,
  then the Task Scheduler (`\Brain\<name>`, the user's interactive token, the venv's `pythonw.exe`, IgnoreNew,
  StartWhenAvailable), a systemd user timer or the user's crontab, through `bash -lc`; what this machine installed
  and no longer declares is removed (`<BRAIN_HOME>/schedules/installed.json`), a task registered by hand never.
  `brain schedule list`. The installer's new schedule step runs it (a plan line, applied by `-Apply`); `brain check
  --all` checks the entries, refusing a control character or an unbalanced quote in a command. `--apply` is refused
  from a Claude Code session, and the guards refuse `brain schedule install --apply` (owner, scheduled). A task
  already deleted by hand is removed without an error; a schedule recorded under another scheduler than this run's
  is left alone with a note; the Task Scheduler's XML is read in the OEM code page and compared with its entities
  decoded.
- **The alerts pass's dead-man** (wi-brain-alerts-pass). Each `brain alerts --notify` pass records itself (`_pass`
  in the state: when, where, the unset variables); once the pass is installed here, `brain schedule list`, `brain
  status`'s alerts row and the SessionStart health hook say SILENT when its last run (or its install, the later)
  is older than two cadences of the machine's awake time, so a boot or a wake raises no false SILENT.
  Without its channel's variable (an unset `BRAIN_NTFY_TOPIC`) a pass sends nothing, writes no notify audit line and
  says so in one line; those alerts go at the first pass that finds it. Off Windows the alerts' Task Scheduler
  folders are skipped instead of raising a `scheduler` warning.
- **Linux** (wi-brain-install-linux). The installer ran under `pwsh` 7.6 on Ubuntu 24.04 (a container): the venv, the
  `~/.local/bin` link, `brain init`, the personal brain's setup (pointer, merge driver, Lite profile, permissions), the
  Claude Code plugin, the hooks under bash and the guards on Linux paths; `docs/install.md` gains its Linux section
  from that run.
- **Tests linked by their imports, and coverage measured** (wi-brain-test-links-auto, wi-brain-test-coverage;
  TEST-1). `brain sync`'s `tested_by` edges now also go to every Python test that imports a node's module itself,
  besides brain audit's strongest evidence; a CodeRef of a symbol (`path::name`) keeps only its file's tests that
  name it (or each of its words, a `cmd_` prefix left out), or, once the store keeps a coverage summary, those whose
  test contexts ran it. Measured on this engine's brain (main d28f77c): 1,522 edges become 584 by the static rules
  (−1,026, most of which gave each `cli.py` subcommand's feature every CLI test; +88 from imports), 472 with the
  coverage summary (+143, of which 138 ran the code by the contexts); 101 test modules linked instead of 99. New
  `brain coverage [--repo R] --run [-n N] | --from DATA [--write] [--json]` (brain.testcov): the repo's pytest
  suites run under pytest-cov with `--cov-context=test`, the checkout's code first on PYTHONPATH, reduced to
  `<store>/coverage/<repo>.json` (statements, covered lines, and which test modules ran each function, read from the
  data file's SQLite tables; this engine: 90.2 % of 32,296 statements, a 346 KB summary). `brain audit`
  measures `test.coverage` (a module its tests run under 50 %, P2) and the new `feature.tests` (a have or partial
  feature whose module or script no test covers, P2), both outside the scout (ruleset 4); FEATURES.md's Tests cell
  gives each feature's coverage. A summary narrows only what it measured (version 2: every function of each file
  and every test module a context named): a symbol or a test added since, an older or context-less summary, keep
  the names rule; a data file without test contexts is refused, branch data is read from its arcs, the def and
  decorator lines count for no test, the repo's `fail_under` is off for the measure, and the trend reads today's
  summary. Docs: `docs/tests-graph.md`.
- **The module map** (wi-brain-module-map; BRIQUE-4). New `brain modules [--write] [--check] [--json]` (brain.modules):
  each open item's `props.module` and `props.modules_secondary` against the store's registry `modules.yaml`; the
  view `notes/modules_graph.md` (per brick and module: phase, status, items done and open, the secondary ones,
  the gaps, the items outside the tree), written by `brain sync`; `brain check` warns about an open item with no
  module, `none` without a reason, or a module the registry does not know. A store without a registry is not
  concerned. The view goes to the merge driver (`notes/modules_graph.md merge=brain`, in `brain init`'s
  `.gitattributes`). Docs: `docs/modules.md`.

- **The session tree** (wi-brain-session-tree; ST-1, ST-2, scale study gap 19). The SessionStart event records both
  ids, the transcript's (`CLAUDE_CODE_SESSION_ID`) and the desktop app's `local_` id (`CLAUDE_CODE_HOST_SESSION_ID`),
  and the parent, task and short name of the session's own app metadata file (`spawnedFrom`, a closed list of keys;
  nothing else is read and the app's files are never written); the token ledger's brief hash fills the parent in
  without the app. The session record gains `host_id`, `name`, `parent`, `children` and `role` (schema). New `brain
  sessions [tree [ID] | show ID [--report]] [--json]`: both ids, role (master, sub, relay, solo), parent, children
  live/started, state and context against the budget, resolving either id (a prefix of 8 or more) or the short name;
  `show` says what a message would meet (live, idle, archived). The resume pack prints both ids. The cockpit's
  sessions panel shows the short name in Session and gains the Role, Parent, Kids and Ctx (% of the budget) columns,
  the ids in the detail. `brain decision ask`, `answer`, `ack`, `archive` and the question-tool capture stamp
  `host_id` and `machine` (DDR schema); `brain check` refuses a DDR stamped on this machine with a `local_` id that
  matches no session, and warns for one stamped elsewhere or before the stamps (the 9 DDRs with a false `asked.by`).
- **The child's report** (wi-brain-child-report). The Stop hook writes `<BRAIN_HOME>/sessions/<id>.report.json`: the
  session's PRs and its branch's head, the items and DDRs it names, what it waits on, what comes next and its recap,
  read from the last wrap-up, the session record, the plan and the pending DDRs at zero token. `brain sessions tree`
  prints it under each child; `brain sessions show ID --report` prints the child's last final message in full from
  its transcript (the app cuts its end-of-turn note at 400 characters).
- **The master's watch** (wi-brain-master-watch; ST-3, ST-4, ST-10, scale study gap 17). The budget watch treats a
  session that called `start_session` as a master: its budget is its brief's, else config.json `usage.master_budget`
  (new), else the model's window (1M); its steps are 70, 80, 90 and 100 %: the room left in children (measured on the
  family, else 22k a child), then « start no new child, hand over and drain » with a draft hand-over note of the live
  children (both ids, items, state), then « drain only, compact only with no child alive », each with the cost of one
  wake. The governor expires the watch's mark at each `start_session` call and reminds a master past 80 % without
  refusing the call (ST-4); `brain alerts` raises a master past 80 % with live children (source `session`); the
  cockpit colours the master's row at each step.
- **`brain impact [--diff BASE|A..B] [--repo-dir D] [--depth N] [--json]`** (wi-brain-impact-diff): before merge,
  what a change's code carries in the graph. The symbols it touches, from the GitNexus code index (the hunks of the
  diff from the indexed commit matched to the indexed symbols' lines, the query of GitNexus's `detect_changes` sent
  through its MCP `cypher` tool, since `detect_changes` diffs GitNexus's own clone, never this checkout), and their
  callers along the CALLS edges GitNexus resolved (confidence 0.8 and up: the guesses by name left out), `--depth`
  levels (2); the CodeRefs that name them; the nodes relying on those (research_graph's reliance); then a checklist:
  features whose status may change, docs to update (`documented_in`, sections naming a changed file), ADRs (the
  current one of a superseded chain) and specs to re-read, tests to run (the modules covering the touched code, the
  `tested_by` of the relying nodes, the changed test files; one `pytest` line and the CI jobs that run them; the
  features' wider tests counted apart), open items that deliver those features, DDRs pending on them, and the
  touched symbols no CodeRef names. GitNexus's lines, counted from 0, are shifted to git's; a CodeRef whose file the
  change deletes or moves away is touched; a deleted or moved test module never reaches the `pytest` line; a
  malformed CodeRef is left out and named. Without GitNexus (down, the repo not indexed, its indexed commit not here,
  its code map failing) it works at the file level and says so: a Python symbol's CodeRef looked up by the AST of
  both sides, no caller. Docs: `docs/impact.md`.
- **`brain code-map [--json]`** (wi-brain-code-map, the code layer's design §3.7): each active CodeRef of the
  project's stores resolved to its GitNexus node (filePath, name, label: Class, Function, Method, File, or Variable
  for an assignment; a method through its class's HAS_METHOD edge) into `<BRAIN_HOME>/code-map/<project>.json`, with
  the coverage per repo (symbols with a CodeRef over all symbols, files with a CodeRef over the indexed files) and
  each CodeRef that does not resolve, with why. Exit 1 when GitNexus does not answer.
- **The vault's recipients change safely** (wi-brain-vault-rotation, its first part).
  - `brain vault recipient remove NAME`: a plan, then `--write`. It refuses to leave a store with fewer than two
    distinct keys or with no recovery key, each store on its own (a tenant's or a scope's key does not stand for the
    owner's stores), to remove the only recovery key, and to remove a recipient that `vault.tenants` or a scope still
    names. The plan lists the sealed files the removed key still opens.
  - `brain vault recipient add` refuses a declared name unless `--replace` is given (a rotation), and a key another
    name already holds. `--replace` keeps the recipient's kind (a change of kind is refused), its `classes`, `why`
    and host, and copies a new gpg key file even where the old one lies.
  - The canary and the drill prove a key, not a name: a key replaced under the same name is « never sealed » and
    « never drilled » until they run again (state.json keeps each proof's fingerprint; an older drill is tied once to
    the key its canary held).
  - `brain vault reseal [STORE...]`: the plan, then `--apply`. It seals again, to their store's current recipients,
    the sealed files whose recipients changed: it opens each with this machine's device key (its previous one during a
    rotation) or with the key the owner gives, seals it again with the same adapter, replaces the old copy, and records
    `resealed` in the manifest (written atomically). It leaves a file as it is when its store would fall under its
    floors, or would leave a recovery key for one never drilled; an unreadable manifest is that file's error.
  - `brain vault device init --rotate` replaces this machine's key and keeps the previous one in the keystore
    (`device-previous`), which still opens what was sealed to it; the name stays, and a failure puts the keystore back
    as it was. `brain vault device forget-previous` deletes the previous key once config.json declares the new key, no
    longer declares the old one, and nothing waits on a re-seal.
  - `brain vault status` lists the files to re-seal and an unfinished rotation. `brain health vault` fails while a
    removed or replaced key still opens a sealed file or a store has fewer than two distinct keys, and warns when a
    new recipient cannot open one yet or a store is sealed to no recovery key.
  - The runbook gains « Changing the recipients ».
  - YubiKey recipients, each machine's canary seen from the others and post-quantum recipients stay for later.
- **A test never reaches the real keystore or ~/.brain.** Under pytest, `keystore.backend()` refuses this machine's
  keystore unless `BRAIN_TEST_KEYSTORE` asks for it, and `paths.brain_home()` refuses the default ~/.brain: on
  2026-11-03 a test's `monkeypatch.undo()` dropped the conftest's settings and the rest of it rotated the owner's real
  device key (restored the same day; nothing was lost).

- **Lessons in the graph** (wi-brain-lessons-registry). A `Lesson` node type in `brain init`'s default schema (layer
  `lessons`, statuses open, enforced, resolved, regressed, archived; edges `learned_from`, `enforced_by`, `led_to`;
  its `trigger`, `anti_pattern` and `check` required). `brain lesson add|seen|list|rules` (also `brain lessons`):
  `add` writes the node in `nodes/lessons.yaml` and refuses one close to a known lesson (mark it `seen`, or
  `--new`); a lesson seen twice (once if severe) with no open fix, or recurring after its fix (regressed), files an
  item proposal (`priority_proposed`) linked `led_to`, or links the open item whose title is close to it;
  `brain lessons --follow` prints each lesson's lineage (learned from, led to, its PR, enforced by, recurred since
  its fix) and the friction per item by week;
  `brain lesson rules` indexes the iron rules (`Σ-NAME`, `Sigma-NAME`) of each registered repo's tracked Markdown,
  read only. `brain lint lessons [--propose]`: the open lessons a script could check (guard candidates) and those
  that say no `why_not_script`. `docs/lessons.md`.
- **The retro at each close** (wi-brain-lessons-loop). `brain retro ITEM [--record --note ...]`: the friction
  signals of the item's sessions (merges and conflicts, guard refusals from the guards ledger, failed test runs,
  waits, tokens against the estimate, the owner's minutes, pushes to its PRs after opening from the action
  records), the known lessons of the signals that fired and five questions; `--record` writes `props.retro` and
  `props.retro_notes`. `brain retro --wave W`: a wave's deep retro. The close-item procedure gains the step (2b,
  Retro), before the item is ticked and never stopping the close (`Retro: skipped (<why>)` when the store has no
  Lesson type yet or the ledger does not know the item), and a `Retro:` line in its report.
- **A brain's own data is checked by the brain, not by its tests** (wi-brain-test-split). `brain refresh` and
  `brain check` in a brain's own root (its neutral source, `source/packs.yaml`) end with the registry check `brain
  check --all` runs: the registry's keys, `config.json`'s contract, the data classes, the permission hierarchy, the
  stacks, and the ids across every registered project (a `shared_ids` waiver names an id another project holds).
  That check now also renders each bundle the engine ships with the components the registry declares and refuses
  what `brain bundle apply` would (a service without a component, a component without a service), a component whose
  tier class is not `service`, and a stack whose `bundle:` the engine does not ship. A project whose stacks file sits
  in a root this machine does not hold is left out of the stacks with a warning (`stacks.uncloned`), so the verdict
  no longer depends on which repos are cloned here. A brain's repository no longer needs a pytest suite over its own
  graph, records and rendered files: the engine's tests run on fixtures only.

- **What the lessons asked for** (wi-brain-merge-stale-main, wi-brain-guard-public-commit,
  wi-brain-guard-public-chain, wi-brain-guard-heredoc-backslash). `brain merge-check [--base REF] [--no-fetch]
  [--worktree] [--path P] [--json]`: after a merge of main into a branch, a remote base fetched again and, against
  the merge base of main and the branch before the merge, nothing main brought lost (its lines in the journals,
  decision logs, edge files and CHANGELOGs, compared as content; the fields it changed on the graph's nodes; its
  nodes, unless the branch removed them); exit 1 when behind or lost. The public guard gains its `commit` check: in
  a checkout whose branch pushes to a public repo, a commit whose added lines hold a denied
  term, an e-mail address, a home folder or a public.patterns match is refused at the commit, not at the push. Its
  push refusal says to split a `brain check --public ... && git push` call. On Windows, a Bash heredoc holding a
  doubled backslash that writes a file or feeds an interpreter gets a warning in the session's context (never a
  refusal), recorded in the guards ledger as `heredoc:backslash`. `docs/guards.md`, `docs/merge-driver.md`; the
  close-item procedure names `brain merge-check` after a merge of the base.
- **The tests run in parallel** (wi-brain-test-speed, TEST-1). `pytest packages/brain -n auto` (pytest-xdist, now in
  the `test` extra) runs one worker per core; the CI's Windows and Linux jobs do. A test's git repository is a copy of
  a template made once per worker (`conftest.git_init`, behind the `git_repo` and `make_repo` fixtures and every test
  that ran `git init`): 24 ms instead of 329 ms on Windows (47 ms instead of 580 ms for `git_repo`, which copies its
  committed template); the branches guard's tests copy their two repositories, made once per module (84 s to 14 s).
  The test that calls the real docker client is marked `docker` and runs apart, on one process (`-m docker`).
  Measured: on a 16-core Windows machine, 885 s on one process to 165-183 s with `-n auto`; on the CI's Windows
  runners (4 workers), 386-391 s to 173-191 s; on its Linux runner, 42 s to 34 s.
- `brain bundle`'s `docker compose config` no longer crashes when docker compose, killed at its timeout, leaves a
  child holding its scratch folder on Windows (Python 3.10's `TemporaryDirectory` recursed until `RecursionError`):
  docker compose runs from outside the folder (the file given with `-f`), the folder goes by `shutil.rmtree` with its
  errors ignored, and the problem is said (« no answer »).

## 0.2.4 — 2026-11-03

- **A session never installs or runs a third-party kit** (wi-brain-guard-third-party, EXT-6). The new `third-party`
  guard refuses a download fed to a shell or an interpreter (`curl ... | sh`, `wget -qO- ... | bash`, `curl ... |
  python3 -`, `bash <(curl ...)`, `source <(curl ...)`, `sh -c "$(curl ...)"`, `eval "$(curl ...)"`, `iwr ... | iex`,
  `iex (irm ...)`, a WebClient's `DownloadString` to `iex`), `claude plugin install` and `claude plugin marketplace
  add` from outside the owner's list (config.json `adapters.claude.sources`, new; the brain's own marketplace, source
  and folder always pass) and `npx skills add` (also `bunx`, `pnpm dlx`), through wrappers, launchers, nested shells,
  ssh and the Terminal panel. Each refusal is an action for the owner's queue with the call's exact command (`brain
  queue add --kind action --guard <ref>`). `segments()` records what joins its segments (a pipe, a statement, a
  process substitution), so a download to a file then a script with its own stdin passes: replayed on 20,717 past
  commands, no refusal. guard.sh's pre-filter starts Python for `claude plugin` and `skills add`.
- **No conflict marker reaches a commit or a store** (wi-brain-guard-conflict-markers). The new `markers` guard
  refuses a `git commit` (or `merge|rebase|cherry-pick|revert|am --continue`) whose staged lines, commit `-a`'s or an
  earlier `git add`'s, add `<<<<<<< `, `||||||| `, `>>>>>>> ` or a bare `=======`, with the file and line; `brain
  check` fails first on a store, journal, decision log or record file that holds one (brain.markers). A setext
  heading in Markdown and a file under a `fixtures` folder pass.
- **The shared files merge by themselves** (wi-brain-generated-merge). `brain merge-driver run %O %A %B %P %L` is a
  local git merge driver for the paths `.gitattributes` gives `merge=brain`, which `brain init` now writes: a
  generated view (``GENERATED by` `` in its first lines, or `_generated_*`) keeps one side, the default branch's when
  one side is its version, and is marked for `brain refresh`, which clears the mark once it passes (`brain check`
  and `brain merge-driver status` name the marked views); `journal.md` and `decisions.md` are unioned, the new dated
  entries in date order, a new entry dated before an old one left as a conflict; `edges/*.yaml` and a CHANGELOG's
  Unreleased section are unioned (a subsection both sides opened becomes one); the other graph YAML is merged entry
  by entry by id (an entry both sides changed, key by key, as `brain item set` writes it); a dated CHANGELOG
  without an Unreleased section is a log, newest first when written so; anything else, and any failure, falls back to `git merge-file`, so a file never loses its markers.
  `brain merge-driver install [--apply]` defines it in a repo's git config, and the installer's new `merge` step runs
  it for the personal brain with the launcher on PATH. `brain merge-driver replay` merges a repo's past merges again
  with `git merge-tree`, as text then with the driver. Docs: `docs/merge-driver.md`.
- **`brain collisions [--all] [--frontier] [--json]`** (wi-brain-collisions): the files each open branch and worktree
  of the project's repos changes (against the default branch, uncommitted changes included, the merge driver's files
  apart), crossed with each startable item's predicted surface (its features' CodeRefs, its module's, the files it
  names; `brain.collisions.SURFACE_HOOKS` for a predictor): the items that can start now, those that wait on a
  branch and its session, those with no known surface.
- **`brain brief ITEM`** (wi-brain-brief-generate): a sub-session's brief from the graph: the item and its props, its
  subgraph, its collisions, the task class's model and effort and the budget (config.json `brief.classes`, a new
  key), the cost estimate, the coordinator's app session id (`--coordinator`, else `$CLAUDE_CODE_HOST_SESSION_ID`),
  the shared notes folder, how to start from the default branch, and the definition of done and the never-list read
  from the owner's rules (`brief.done`, `brief.never`), never written in the engine. The generic template's rules gain
  a « Never » section.

- **The recovery key is typed hidden, and Enter is enough.** `brain vault drill` and `brain vault open --identity -`
  asked age to read the key from the terminal: after Enter, age kept waiting for the end of input (Ctrl+Z alone on a
  line on Windows, Ctrl+D elsewhere), which a terminal may swallow, and timed out after 300 s; the key showed on the
  screen and stayed in the scrollback. The brain now asks for it like a password (`vault.ask_key`: no echo, Enter
  ends it), checks that it is an age identity line and hands it to age on its stdin; it is never written, and a wrong
  line, nothing or Ctrl+C opens nothing. A stdin that is not a terminal gives its first line. gpg still reads its key
  block itself, and its prompt now says how the console ends the input. age missing from a terminal opened before
  its install says to open a new one, and a failure of age names its error, not the « report unexpected or unhelpful
  errors » line it prints last.
- **Structure signals in the scout** (wi-brain-audit-structure; EXT-4, EXT-5). `brain audit --diff` measures the
  shape a change gives the code, from the two trees it already reads, at zero token (`brain.structure`):
  `size.cross` (a code file taken past `max_lines`, NEW), `size.grow` (one already past it grown again, DEFER to the
  debt item), `complexity.cross` and `complexity.grow` (the same for a Python function's cyclomatic complexity,
  computed with `ast`), `dep.adr` (a dependency added to `pyproject.toml`, `requirements*.txt` or `package.json` that
  no decision log of the project names), `shortcut.marker` (a `shortcut:` comment without its ceiling, trigger and
  debt item) and `symptom.cause` (an added `type: ignore` or `noqa` comment, a skipped test, an `except` that
  swallows everything, a sleep, a retry or a longer timeout, with no `Root cause:` line). `--pr-body FILE` gives the
  PR body; it and the range's commit messages are read for `Root cause:` and `Justified: <unit>: <reason>` lines,
  which turn a NEW structure line into `justified` (shown, never blocking). The thresholds are `projects.yaml`
  `audit: {max_lines, complexity}` (default 1000 and 15); the JSON gains `justified` and `structure`.
- **The engine against its pin** (wi-brain-engine-version-skew). `brain check` warns when the running brain or
  research-graph is not `config.json` `engine.pin` (ahead, behind, or the pin's version from another git revision or
  a folder not at the tag: a dev engine, read from the distribution's `direct_url.json`); `brain sync`, `brain
  refresh` and `brain render --write` refuse to write then, unless `--force` (new on sync and refresh; render's also
  replaces foreign files). The refusal ends with the way out in one line: after `brain update`, the tag to set as
  `engine.pin` in the brain's `config.json` and commit; for a dev engine, run the pinned one. A brain with no pin, or a
  pin that is not a release tag, is not compared (`brain.skew`). The upgrade steps of `docs/install.md` and
  `docs/pilot.md` now move the pin before `brain sync`.
- **The cockpit knows its version and offers updates** (wi-brain-tui-update-check, ADR UPD-1 to UPD-3). The title
  bar of `brain tui` always shows the installed version (the text view's header too). Once the screen is drawn, a
  worker reads the release tags of the engine's public repo (`config.json` `engine.repo`, else RoJLD/brain) with
  `git ls-remote`, no token, no credential helper, no prompt; the answer is kept 24 h in `<BRAIN_HOME>/update.json`,
  and offline it says nothing. When a newer tag is out the title reads « brain 0.2.3 · 0.2.4 available » and `u`
  opens `brain update`'s plan in the cockpit's confirmation, run on `y` only.
- **The cockpit applies the brain's installer and relaunches itself** (wi-brain-tui-apply-reload, ADR INST-1 to
  INST-3). A brain declares its own installer in `config.json` `engine.installer` (a path from its root, run without
  arguments for its plan and with `-Apply` to install the engine at the pin; `brain config --check` reports a missing
  file); the engine names none. When the installed engine lags `engine.pin` (a pin PR merged, `-Apply` not run yet)
  and the brain declares one, the title bar reads « brain 0.2.1 · pin v0.2.3: -Apply » (no network needed) and `u`
  opens that installer's plan in the confirmation, then `-Apply` on `y` only; a brain without one (from `brain init`)
  keeps `brain update`. The install never runs inside the cockpit, which on Windows holds files pip must replace
  (PyYAML's `_yaml.pyd`): on `y` it writes `<BRAIN_HOME>/handover/cockpit-<pid>.ps1`, logs it as the owner's action
  and exits; a new console window waits for it to exit, runs the step there (its output stays, a failure says so and
  waits for Enter), then relaunches `brain tui` with the same arguments (elsewhere, an sh script in the cockpit's
  place). `brain update` from the cockpit goes the same way, and so does a queue action's `install.ps1 -Apply`
  (`A`, its `brain queue done` after it in the window). Refused in a Claude Code session's shell.
- **`brain update`**: the plan to the latest tag (the version, its CHANGELOG sections read from the tag, the tag
  installed into `<BRAIN_HOME>/venv` with pip and the `tui` extra kept, the launcher swapped into `<BRAIN_HOME>/bin`
  even while a brain runs, install.ps1's Set-Launcher in Python, and for a pinned brain the `engine.pin` to move by a
  reviewed PR, shown, never done), installed on the owner's yes only (`y` at the prompt, or `--yes`), refused in a
  Claude Code session's shell. `--check` prints the plan and installs nothing; `--json` its data. An editable install
  is left to `git pull`. The tests never read the network (conftest fakes the tags offline).
- **The pilot's settings in the docs**: `docs/install.md` says, before the first session, `BRAIN_MEMORY_SYNC=0`, the
  venv at `%USERPROFILE%\.brain\venv` or `BRAIN_PYTHON`, Git Bash's `HOME` (else `BRAIN_HOME`), telemetry off by
  default, and how to upgrade by hand from a version without `brain update`; `docs/pilot.md` how updates come during the pilot.
- **The engine times itself** (wi-brain-self-timing, the first stage of the opt-in telemetry). Every `brain`
  command and every hook writes one exec event to `<BRAIN_HOME>/ledger/engine/` (project `brain`, task
  `brain <command> [<subcommand>]` or `hook <name>`, `[bash]` for a run that never started Python, the engine's
  version, the duration from the engine's import or from the hook's first bash line, so the interpreter's start
  counts); every error a hook or a command catches through the shared sink (`capture._log_error`) or lets escape
  becomes an error event: its exception class and the engine's `module:function`, never its message. The bash fast
  paths append their own line (`hooks/common.sh`, builtins only) to their own file, apart from the locked Python
  writers. `brain perf --engine` lists the slowest commands and hooks, regressions between engine versions, the
  hooks' blocking time per week against the 1 h trigger of the PERF ADR, and the errors caught; `brain alerts`
  raises a task that caught the same exception 3 times in 24 h (`engine` source; error for a hook, warn for a
  command) on the brain's own project. The engine's events stay out of the projects' ledger files, which `brain
  alerts` and `brain status` read, and the last three months are kept. `BRAIN_SELFTIME=0` turns it off;
  `BRAIN_CAPTURE_TIMING`, which wrote decision times into `errors.log` as errors, is gone. `brain.timing` imports
  `schema`, `secretscan` and `socket` only where they are used, so a hook does not pay for them.
- **The token ledger counts the engine's sessions** (wi-brain-ledger-engine-sessions). A session that ran in a repo
  a project declares under `repos:` (the engine's checkout for a personal brain, its `.claude/worktrees/*`, a
  checkout beside it named `<repo>-wt-<name>` even once removed) is credited to that project, and a sub-session to
  the project of the item its brief names, wherever it ran; before, they landed in « other folders », so `brain
  usage`, the quota pacing and the forecast missed them (`queue.Placer`, also used by the cockpit and `brain queue`).
  A project's own root wins over another project's repo at the same place.
- **Faster hooks** (wi-brain-hook-latency, PERF-1: Python first). The launchers read their JSON with `read` instead
  of `$(cat)`, find Python with `[ -x ]` and `hash` instead of `$(command -v)` (`brain_python`, `hooks/common.sh`),
  pass the JSON as a here-string instead of a pipe, and take the plugin root from their own path: no fork before
  Python. `guard.sh` leaves git that only reads to bash (`git [-C DIR | --no-pager | -P] SUB`, SUB in
  `guards.GIT_READS`: status, log, diff, show, rev-parse, ls-files, blame...; not with `--output` or a pager option;
  any other git, `-c` or `--git-dir` still starts Python), about 30 % of the shell commands that started it.
  `paths.installed_checkout` reads its `file:` URL with `urllib.parse` (`paths.file_url_path`) and once per process:
  a guard no longer imports `urllib.request` (~50 ms). The registry and `permissions.yaml` are read through libyaml
  (`graph.load_yaml`). The exec form of the hooks (`args`, no shell) waits until it is checked on Windows.
- **Fast YAML** (wi-brain-yaml-fast-load). Every YAML read of the engine goes through one helper,
  `research_graph.yamlio` (`graph.load_yaml`, `load_yaml_file`, `load_yaml_all`): libyaml (`CSafeLoader`) when PyYAML
  has it, and a per-process memo keyed by (path, size, mtime_ns) that keeps the data pickled and hands each caller a
  fresh copy; a file written within 2 s of its read is checked against its text's digest. `graph.load_yaml_list`,
  `records.load`, the registry and every module's `safe_load` used the pure-Python parser. `paths.main_checkout`
  keeps its answers for the process (not a None). Numbers from `brain perf --engine` in the PR.
- **Releasing:** `hooks/common.sh`'s `brain_version` moves with `__version__` (a test checks it).
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
