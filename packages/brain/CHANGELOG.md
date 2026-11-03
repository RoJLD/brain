# Changelog — brain

The command shares the repo's tag series with `research-graph`: `vX.Y.Z` is both at X.Y.Z.

## Unreleased

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
  `props.retro_notes`. `brain retro --wave W`: a wave's deep retro. The close-item procedure gains the step (3b,
  Retro) and a `Retro:` line in its report.

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
