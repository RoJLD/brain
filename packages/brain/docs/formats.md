# Formats and versions: tolerant readers, strict writers

A brain's local data must survive an upgrade of the engine and a rollback to the previous one: a newer engine reads
what an older one wrote, and an older engine reads what a newer one wrote, or refuses it cleanly, never losing it.
This page says how each format the engine reads carries its version, what the engine does with a field or a key it
does not know, and what it does with a version above its own.

## The rule

- **A version per format.** `v` is an integer, one per format. An additive change (a new optional field or key)
  keeps `v`; a rename, a removal or a change of meaning bumps it and ships a migration.
- **Read mode, tolerant.** A field or a key the engine does not know is a newer brain's additive one: it is reported
  (a warning, or a `brain: note:` line on stderr) and **kept**, never dropped. A rewrite keeps it too, even one built
  afresh (an SR from its transcript, `brain record ... --replace`, `brain record backfill --update`): the fields of the
  file it replaces are put back at their exact place (`brain.records.keep_unknown`), so a round trip through an older
  engine loses nothing.
- **A new value of an enum is not additive.** A DDR `status` or an SR `role` this engine does not know fails the
  record's check in both modes: such a change bumps `v`. The one exception is an AR line's `kind`, whose line is
  skipped and counted.
- **Strict mode.** What the engine writes is valid under its schema, an unknown field included as an error; the
  checks in CI are strict too, since the engine there is the pin.
- **A higher `v` is refused, in both modes**, with the same message:
  `<file>: v2 is written by brain > 0.2.5, which reads v1: brain update`. Its other fields are not judged (their
  meaning may have changed), and a record a newer brain wrote is never overwritten.

## Which mode a check reads in

`brain check`, `brain record check`, `brain config --check`, `brain permissions check` and the checks of
`projects.yaml` and `packs.yaml` pick their mode from the environment (`brain.schema.mode`):

| Environment | Mode |
|---|---|
| `BRAIN_STRICT=0`, `false`, `no`, `off`, `n` or `f` | read (an older engine reading a newer one's data, in CI too: the rollback job) |
| `BRAIN_STRICT` set to anything else (`1`, `on`...) | strict |
| `CI` set to anything but `0`, `false`, `no`, `off` (GitHub Actions sets `CI=true`) | strict |
| otherwise (a machine) | read |

Writing is always strict. The engine's test suite runs strict (`tests/conftest.py` sets `BRAIN_STRICT=1`); the
tolerant tests set `BRAIN_STRICT=0`.

## The formats

Each store the engine writes under `$BRAIN_HOME` carries its format class (`truth-local`, `log`, `derived`,
`install`, `external`) beside its data class in `brain.classes.ENGINE_STORES`: the list is in
[vault.md](vault.md#the-engines-own-stores), and `brain classes --json` prints it for the stores a brain leaves at
their default.

| Format | Where | Version | Unknown field or key (read mode) | Higher `v` |
|---|---|---|---|---|
| DDR | `records/ddr/<id>.yaml` | `v` (`ddr.schema.json`) | a warning; `brain` rewrites keep it | refused; never overwritten |
| SR | `records/sr/<yyyy-mm>/<id>.yaml` | `v` (`sr.schema.json`) | a warning; rewrites keep it | refused; never overwritten (`brain record backfill` counts it `sr-refused`) |
| AR | `records/ar/<yyyy-mm>.jsonl`, one line each | `v` per line (`ar.schema.json`) | a warning; the line is never rewritten | the line is skipped and counted (a warning; an error in strict mode) |
| event | the ledger's `events` and ops error lines | `v` per line (`event.schema.json`) | reported by `brain.schema.validate` | refused |
| config.json | the brain's root | `v` (`config.schema.json`) | a note on stderr; the file is kept as written | refused |
| members.yaml | the brain's root, beside config.json ([identity.md](identity.md)) | `v` (`members.schema.json`) | ignored, the file kept as written (in strict mode, CI: reported by `brain check` with the other identity findings) | refused |
| readme.yaml | a repo's root, opt-in ([views.md](views.md), « Generated READMEs ») | `v` (`readme.schema.json`) | ignored, the file kept as written (in strict mode, CI: `brain docs check` and `brain check` report it) | refused |
| modules.yaml | a store (or the one `config.json` `modules.store` names, [modules.md](modules.md)) | none: a YAML list; each entry that carries the map (`realized_by` or `map_review`) is checked against `modules.schema.json` | an entry's other field is free; a realisation's unknown key is a note (in strict mode, CI: `brain modules --check` refuses it, `brain check` warns) | - (no `v`: a change of the schema moves the format) |
| standards catalog | the engine's `src/brain/catalogs/*.yaml`; a brain's local ones that `projects.yaml` `standards.catalogs` names ([standards.md](standards.md)) | `v` (`standards.schema.json`) | a note, the row kept; a vocabulary value this engine does not know (a profile, stage, enforcement...) too (in strict mode, CI: `brain standards check` and `brain check --all` report it) | refused: its rows are not read |
| DDR signature | `records/ddr/<id>.sig`, beside its record | none: an SSH signature (namespace `brain-decision`) over the answer's payload | - | - (an older engine ignores the file and reads the record as before) |
| permissions.yaml | the brain's root | `v` (`permissions.schema.json`, described: read by `brain.permissions`) | a note; an **allow** rule that carries an unknown key is left out (the key may narrow it), a deny or ask rule is kept | refused |
| packs.yaml | `source/packs.yaml` | `v` | a note, a top-level key and a pack's key alike (a pack's since 0.4.0: an older engine refuses a pack key it does not know, so a brain writes a new pack key, `typologies` or `layers` for instance, only once its machines run 0.4.0 or later); the key is kept and the pack rendered as without it (in strict mode, CI: refused) | refused |
| template.yaml | a template's folder | `engine:` range | a note (in CI: refused), `extends` and `append` (wi-brain-project-templates) and `takes` (spec-brain-typology-packs E1 bis) included: a template that uses them names the engine that knows them in `engine:`; a graph's keys are strict: a graph's `layers` (wi-brain-graph-templates) is refused by an older engine, so a template that uses it names the engine that knows it in `engine:` | `engine:` is checked **first**: a template for a newer engine says "it needs brain >=X", not "unknown key(s)" |
| graph layer | research_graph's `templates/layers/<name>.yaml` (the catalogue); a template's own `layers/<name>.yaml` | `version`, per layer, recorded in a store's `templates:` | refused (`research_graph layers` names the known keys) | - (a layer's version is compared by `brain template upgrade`, a later item) |
| schema.yaml `templates:`, `endpoints:` | a store's `schema.yaml`, when composed from layers (`research_graph layers`) | none: the store's schema | both optional; an older engine ignores them (its `check` then verifies no endpoints) | - |
| projects.yaml | the brain's root | none yet | a project key (`KEYS`; `standards` since 0.3.2, `parent` and `classes` since 0.3.3, its own keys a note too), a `repos:` key (`REPO_KEYS`; `tools` since 0.3.2, its slots, keys and formats a note too): a note, kept. `access` is a key that **narrows**: a brain that does not know it (0.2.8 and before) keeps the note (in CI: refused, so a brain repo whose CI runs 0.2.8 goes red) and reads an `access: read` entry as a full project, at the registry's root with the default store, journal and decision log, so such an entry lands in a registry only once every machine runs brain 0.3.0 or later | - |
| scopes.yaml | beside config.json (config.json `scopes`, `$BRAIN_SCOPES`; [the README](../README.md#the-scope-tree)) | `v` | a container's unknown key: a note, kept (in strict mode, CI: `brain check --all` reports it); the keys the inheritance resolver will read (`rules`, `notify`, `quiet`, `capabilities`, `never`, `budgets`, `members`, `language`) are accepted as declared | refused |

AR lines are parsed one by one (`brain.records.parse_ar`): a line that is not a JSON object (a conflict marker, a
truncated write, a byte that is not UTF-8) or that its schema refuses is an error of `brain record check`; a line a newer brain wrote (a higher
`v`, a kind this engine does not know) is skipped and counted. Neither stops `brain sync`: the graph is built from the
other lines, and a note says how many were left out. Their ids still count as recorded, so no AR is appended twice.

### Milestone kinds (the store)

A graph store's `schema.yaml` is a registered format (`store` in `SCHEMAS`, with what `brain init` writes once:
`gitattributes`, `boundary.yaml`). The kinds of milestone add no node type, edge type or status: they are props of a
`Milestone` (brain.waves), so the store's `schema.yaml` does not change. What `brain init` writes once gains two lines
for the new generated view `notes/plan_graph.md` (its `merge=brain` line and its `generated` side), which makes the
release that brings them a minor one (`docs/release.md`, « The version policy »); 0.3.0 is one already. A brain made
before keeps its own files, and its owner adds the two lines by hand (CHANGELOG, 0.3.0 « Upgrade », step 4): until
then the view merges as plain text and `boundary.yaml` reads it as `notes/**`; `brain check` passes either way.

| `props.kind` | Its members (`part_of` it) | Its props | brain check refuses |
|---|---|---|---|
| none | items and milestones, as before | `trigger`, `reached` | - |
| `wave` | work items; it is itself `part_of` a milestone or an era (a warning without one) | `release: X.Y.Z` (its name), `week` (optional) | a `release` that is not `X.Y.Z`, two waves of one release, a member that is not a work item, an item `part_of` two waves, a `carried_to` that names no later wave, a `carried_via` that names no wave, a reached or dropped wave that still holds an open item |
| `era` | milestones | `exit` (the Go/NoGo question, a DDR once its milestones are reached), `stage_to` and `serves` (optional, free labels) | a member that is not a milestone (a warning without `exit`, and once its exit is due) |

An item's wave is the one it is `part_of`, or, once that wave closed without it, the later one its `props.carried_to`
names (a wave's id or its release; `brain wave close` writes the id): the edge to its first wave stays, as where it was
planned. `brain wave close` carries only to a pending wave, which it creates when the release has none yet. An item carried again keeps the waves it went through
after its first, in order, in `props.carried_via` (wave ids, comma-separated): the view says it came from the last of
them, and lists it under each one's « Carried out ». In a store that holds a wave or an era, any other `props.kind`
on a milestone is refused; a store with neither is not read for kinds at all, so a store that never used them is
refused nothing new. An engine that does not know the kinds (0.2.8 and before) reads a wave or an era as a plain
milestone, and `props.carried_to` and `props.carried_via` as unknown props it keeps; no fixture guards that yet (a
manual run of 0.2.8 on such a store passed).

## Machine-local state: `brain.stateio`

A **truth-local** file lives under `$BRAIN_HOME` on one machine, with no git behind it: losing it loses a record
nothing else keeps. Such a file is read and written through `brain.stateio` (`load`, `save`), which:

- reads a missing file as an empty record;
- **sets aside** a file that is not JSON, not an object, or not the shape its owner expects: it is moved beside
  itself as `<name>.unreadable-<UTC stamp>` (a line on stderr names it) and the record starts afresh. It is never
  replaced by `{}` and saved over. Only a command that writes the file sets it aside: a read-only one (`brain
  status`, the cockpit, a plan, a dry run) reads it as empty and moves nothing. A byte that is not UTF-8 counts as
  not JSON, and a file a writer replaced between the read and the move is read again;
- reads a file whose `v` is above the engine's (or is not an integer) as it is, but treats it as **read-only**: the
  command that would write it refuses up front, « written by a newer brain (v N, this engine knows v M): brain
  update »; an OSError other than a missing file (a lock, a permission) is read-only too, and nothing is moved;
- **writes** a backup first, `<name>.bak` beside the file (the same folder, so the same store and data class; a file
  under `$BRAIN_HOME/secrets` is never copied), then a temporary file, synced and moved over the file
  (`os.replace`). The `v` on disk is checked again just before: a newer brain that wrote since the load wins;
- keeps the keys it does not know (a newer brain's additive ones) through the round trip.
- with **integrity** on (config.json `integrity.sidecars: true`, or `BRAIN_STATE_INTEGRITY=1`; off by default),
  writes a sidecar beside each file it saves, `<name>.sha256` (`{"v": 1, "sha256", "size", "mtime_ns"}`), and
  checks it at each load. A file whose size and mtime are its sidecar's but whose sha256 is not (bit rot, or a write
  outside the engine that kept both) is set aside as above, its sidecar beside the copy, with a line on stderr: the
  copy is kept, never saved over, and the record starts afresh. A file whose size or mtime differ was written since by
  another writer (an older engine after a rollback, which does not know the sidecar): it loads, and the next save
  writes a fresh sidecar. A missing sidecar (every file written before) loads as it always did. With integrity off, a save removes a sidecar left from before, so none goes stale. A
  sidecar is a leftover of its store (`classes.HOME_TRANSIENT`), never a name of its own; an older engine's `brain
  check` notes a top-level one (`tui.json.sha256`) as a name no store covers, a note that never fails. The old
  sidecar goes just before each write, and the new one is made from the file's bytes and stat read through one
  handle, so a writer cut short or racing another never leaves a sidecar that does not describe its file.

`v` is the top-level integer `v`; a file without one is read as version 1. A record keyed by names (schedules,
projects) keeps its `v` 1 unwritten, so that brain 0.2.5, which reads every key as a name, still reads it.

| File | Version | What the engine does when it cannot write it |
|---|---|---|
| `schedules/installed.json` | `v` 1, unwritten | `brain schedule install --apply` prints the plan and refuses (exit 2) |
| `alerts/state.json` | `v` 1, unwritten | the notify pass sends nothing (« nothing sent: ... »), since sending without a record would send again each pass |
| `vault/state.json` | `v` 1, written from 0.2.6 | `brain vault seal`, `canary` and `drill` refuse before any work; `status` and the health still read it |
| `usage/sessions.json` | `v` 2 (`LEDGER_V`, apart from the scanner's `SCAN_V`, which only rescans rows) | `brain usage` brings the rows up to date in memory and says on stderr that it saved nothing |
| `tui.json` | `v` 1 (beside the older `cockpit: 1`, kept) | the cockpit shows the saved views but does not remember new ones (« brain tui: ... written by a newer brain ... the views are not remembered ») |
| `memory-sync/state.json` | `v` 1 | the memory sync refuses before any fetch: `last.json` says « failed » and the alert names brain update |
| `vault/device.json` | `v` 1 | `brain vault device init` (`--rotate` too) and `device forget-previous` refuse before the keystore is touched |
| `sessions/<id>.json`, `<id>.state.json` | `v` 1 (the SR's schema, `capture.SR_V`; `STATS_V`) | the Stop hook writes neither (a newer brain's session) and logs nothing |
| `sessions/<id>.report.json`, `<id>.plan.json` | `v` 1 | `sessions.write_report` returns None, the plan hook keeps the file |
| `budget/<session>.json` | `v` 1 | the budget watch gives no notice and sets its mark `IDLE_S` ahead, so bash starts no Python meanwhile |
| `spool/spool.json` | `v` 1 (`spool.INDEX_V`) | `brain spool push` refuses before sealing anything (exit 2; `--dry-run` only reads it); `status` and `brain health spool` still read it |
| `session-archive/index.json` | `v` 1 (`sessionarchive.INDEX_V`) | `brain session-archive run` refuses before reading a transcript (exit 2; `--dry-run` only reads it); `status` and `brain health session-archive` still read it |

`tui.json` keeps the keys this engine does not know at each level it names (the top level, `panels`, `tabs`,
`columns`, `settings`, `settings.titles`): a newer brain's panel view, tab or setting survives a save of this one. A
key it knows is its own: a title the owner removed is removed. `budget/<session>.json` is written by the hook's Python
only (bash reads its `.mark`), once per check, never per tool call: the backup and the synced write cost about 10 ms
there; the prune of states older than `KEEP_DAYS` takes their `.bak` and set-aside copies too.

### Foreign files: Claude Code's settings

A file another tool owns is edited in its own keys only (spec-brain-data-compat §1, class foreign).
`brain.stateio.read_foreign` refuses one that cannot be read (a lock, a permission), is not JSON or not an object
(« fix it by hand first »): it is never set aside nor replaced. `write_foreign` refuses a file that changed since it
was read (its owner wrote it meanwhile: « run the command again »), backs it up (beside itself, or into a folder of
`$BRAIN_HOME/backup` the caller names: `backup_home`, the last 10 copies per file, none when the bytes did not change),
then writes atomically.
A symbolic link (a settings file kept in a dotfiles repo) is written through: the file it points to changes, the link
stays. `permissions.ClaudeCode.write` (`brain permissions render --write`, `--level session --out`) goes through
them; a file of a git work tree (a project's committed `.claude/settings.json`, its `.claude/settings.local.json`, which
Claude Code gitignores) is backed up under `$BRAIN_HOME/backup/<project>-<key>/<its folder>` (the project named by its
main checkout's folder and keyed by eight hex digits of its git common dir's path, so two repos of one name never share
a folder; a linked worktree's copies under `worktrees/<folder>-<key>`; `permissions.home_backup_dir`), never beside
itself, so git status stays clean; an untracked `<name>.bak` an older engine left beside it moves there first, its time
as its stamp (a tracked one stays). Any other file is backed up beside itself. The user file, `~/.claude/settings.json`,
is the owner's act: `install.ps1 -Apply` writes it, with the same policy in PowerShell (`Read-ForeignJson`,
`Write-ForeignJson`: a file that is not a JSON object stops it, an empty one is read as missing, a backup
`settings.json.bak`, a temporary file that replaces it).

### The machine's files

`<BRAIN_HOME>/machine.json` (`v: 1`, truth-local, `brain.machine`): `name`, `anchor` (a sha256 of the OS install's
id and family, never the id), `local_id`, `since`, and `asked` (the date each doubt was first shown). Written once at
first sight; a doubt never rewrites it. `<BRAIN_HOME>/facts.json` (`v: 1`, derived): `machine`, `at` and `facts`,
`{fact: {value, source}}` with `value` true, false, a text or null (unknown) and `source` agent, probed,
`nodes-file@<ref>:<sha256[:12]>`, declared or unknown; rewritten by each `brain doctor`. The status document's `brain`
block gains `hardware` (`ecc`, `battery`, each true, false or null, and their sources), an optional key.

### The log class: rotation and retention

A log is appended to, never rewritten. A JSON-lines ledger (the exec, capture, guards, queue, answers and cockpit
ledgers, the quota readings, the session starts, the notify audit and its held messages) is appended by `brain.timing.append_text`: one write, under an
exclusive lock on `exec.lock` in its folder, a last line left without its newline closed first (on Windows the C
runtime's append is a seek then a write, so two writers without the lock lose and mix lines); a signal that
arrives during the write waits for its end (`brain.shutdown.critical`), as it does during `stateio.write_atomic`. The single-instance
locks (the interactive cockpit, the alerts pass) are `<BRAIN_HOME>/locks/<name>.lock`, with the holder's pid and start in
`<name>.json` beside it (machine-local, never synced). `brain.stateio.rotate_log` runs before a line is appended: a log last written
in an earlier month (UTC) moves aside as `<stem>-<YYYY-MM><suffix>`, one past 1 MB the same way under this month
(`-<n>` when that name is taken), then the monthly files past the class's retention go (`prune_months`). Hooks rotate
at the same time without a lock: the move never replaces an existing file (a rename that refuses one on Windows, a
hard link elsewhere), and a name taken meanwhile makes it look at the log again, so a rotated month is never written
over. Each class keeps (`stateio.LOG_RETENTION`, this month counted):

| Class | Files | Kept |
|---|---|---|
| errors | `ledger/errors.log`, `ledger/errors-YYYY-MM[-n].log` | 6 months |
| timing | `ledger/engine/*-YYYY-MM.jsonl` (brain.selftime, the hooks' `exec-bash-`) | 3 months |
| ledger | `ledger/<name>-YYYY-MM.jsonl` (actions, decisions, events, guard decisions, the queue) | kept: records nothing else holds |
| starts | `usage/starts.jsonl`, `usage/starts-YYYY-MM[-n].jsonl` (the governor's brainstorm starts, read for 10 minutes) | 2 months |
| quota | `usage/quota.jsonl`, `usage/quota-YYYY-MM[-n].jsonl` (`brain usage quota --observe`'s readings) | 12 months |
| notify | `notify/YYYY-MM.jsonl` (the notifications' audit: one file per month already; the older months go at a month's first line) | 6 months |

An `errors.log.1` left by an older engine (which cut errors.log at 1 MB into that one file) stays as it is. A reader
of a rotated log's history reads its files in order (`stateio.log_files`: the monthly files by month, then the live
one): `quota.load_readings` reads them all, the governor the live file and the newest month. An older engine reads
only the live file after a rotation: it sees less history; its `brain usage quota --observe` may then ask for
`--resets` when the month's file holds no weekly reading yet.

### The `return {}` sites, classified

Before this helper, 17 readers caught `(OSError, ValueError)` and returned `{}`. Each has a class
(spec-brain-data-compat §1); only a truth-local file needs the helper, since a derived file is rebuilt and a
foreign one is never written here.

| Site | File | Class | Status |
|---|---|---|---|
| `alerts.state_load` | `alerts/state.json` | truth-local | through `brain.stateio` |
| `schedule.installed` | `schedules/installed.json` | truth-local | through `brain.stateio` |
| `schedule.last_pass` | `alerts/state.json` (`_pass`) | truth-local | through `alerts.state_load` |
| `usage.load` | `usage/sessions.json` | truth-local | through `brain.stateio` |
| `vault.device` | `vault/device.json` | truth-local | through `brain.stateio` (`device init`, the rotation's `forget-previous`) |
| `cockpit.load_state` | `tui.json` | truth-local | through `brain.stateio`; the save keeps the keys it does not know |
| `memory.load_state` | `memory-sync/state.json` | truth-local | through `brain.stateio` (the 3-way base) |
| `cockpit.snapshot_of`, `sessions.snapshot` | `sessions/<id>.json` | truth-local | read-only here, `{}` is right; its writer, the Stop hook (`capture.stop`), through `brain.stateio` |
| `sessions.read_report` | `sessions/<id>.report.json` | truth-local | read-only here; `sessions.write_report` through `brain.stateio` |
| `sessions.watch_state` | `budget/<session>.json` | truth-local, one session's life | read-only here; its writer, the budget hook's Python (`budget.check`), through `brain.stateio` |
| `sessions.app_meta` | the desktop app's session file | foreign, read only | `{}` is right: never written |
| `codemap.read` | `code-map/<project>.json` | derived (local) | `{}` is right: rebuilt |
| `codeindex.read_record` | `code-index.json` | derived (local) | `{}` is right: rebuilt |
| `forecast.load_latest` | `forecast/<project>/latest.json` | derived (local) | `{}` is right: rebuilt |
| `quota.load_status` | the quota forecast | derived (local) | `{}` is right: rebuilt |
| `update._read_cache` | `update.json` | derived (local) | `{}` is right: the tags are asked again |
| `net.blocked`, `net.failed` | `net/breakers.json` | truth-local | through `brain.stateio`; losing it costs one timeout per service |
| `outbox.put`, `outbox.replay` | `outbox/queue.json` | truth-local | through `brain.stateio`; a newer brain's is read-only (nothing queued, said) |

## The hook contract

The bash hooks (`src/brain/adapters/claude/hooks/*.sh`) read four files that Python writes, with bash builtins only
(no fork: wi-brain-hook-latency). A session keeps the plugin copy it started with (one cached copy per commit), so old
bash reads what a newer engine writes until the session restarts: each file keeps its first line(s) as bash before
0.3.2 reads them and names its format on a line of its own, after them (wi-brain-hook-contracts). Today's bash trusts
a file without a format line (an older engine's) or with its own; another format makes it start Python, which decides.

| File | Writer | Lines | Format line |
|---|---|---|---|
| `<BRAIN_HOME>/budget/<session>.mark` | `brain.budget` | the transcript `budget.sh` compares its mtime with | last, `#brain.budget-mark/v1` |
| `<BRAIN_HOME>/announce/<session>.mark` | `brain.midsession` | the session's folder, the queue, the pending DDRs | last, `#brain.announce-mark/v1` (bash before 0.3.2 reads it as a DDR that does not exist) |
| `<BRAIN_HOME>/cache/node-clis.txt` | `brain.guards.node_tools` | the node CLIs as one alternation, which `guard.sh`'s pre-filter matches | last, `#brain.node-clis/v1` |
| `plugins/<plugin>/hooks/contract.txt` | `brain render` (`brain sync`) | `version <the engine that rendered it>`, then one `rule <path>` per file of config.json `rules`, relative to its folder | first, `#brain.hook-contract/v1` (a new file: no older reader) |

`inject-rules.sh` reads the contract's `rule` lines instead of the first `"rules"` array in config.json's text (which
may be another section's), for the config the plugin was rendered from as it was then: no `BRAIN_CONFIG` or
`CLAUDE_BRAIN_DIR` naming another, and a contract newer than config.json (a rules edit since the render is read from
config.json at once). Otherwise, without a contract (the engine's own hooks folder, a plugin rendered before 0.3.2),
or with another format, it reads config.json as before. `tests/fixtures/hooks/` holds each file as the engine writes it, and
`tests/test_hook_contracts.py` checks the writers against them and today's bash against each format line.

The version: `common.sh` exports its `brain_version` as `BRAIN_HOOK_VERSION`, so every Python a hook starts knows the
plugin copy's version. The SessionStart health (`brain.stacks.hook_contract_notes`) says when it differs from the
engine's: restart the session, then `brain sync` or `brain update`. A hook before 0.3.2 passes none, and nothing is
said.

`<BRAIN_HOME>`: every hook spells it `${BRAIN_HOME:-${USERPROFILE:-$HOME}/.brain}`, the folder Python's
`Path.home()` names on Windows (before 0.3.2, some hooks started the venv of `$HOME/.brain`). With `$BRAIN_HOME`
unset, the health says when more than one of `Path.home()`, `%USERPROFILE%` and `$HOME` holds a `.brain` folder
(`brain.paths.home_folders`): bash and Python may each have used their own.

## Public-check stamps: a derived file with its whole key

A green `brain check --public --history` on a public repo writes `$BRAIN_HOME/public-check/<owner>/<repo>/<sha>`
(atomically), which the `public` guard reads before a `git push` (wi-brain-public-stamp-binding, spec-brain-data-compat
N2). It is a cache, so it carries every input it depends on:

| Field | What |
|---|---|
| `v` | 2 (0.2.5 and older wrote none) |
| `key.engine` | the engine version that checked |
| `key.rules` | sha256 of config.json's `public.deny` (as brain.config reads it, the terms `public.deny_from_tree` generates from the scope tree included), `allow`, `patterns` and `refuse`, in a canonical form: key order and spacing do not count |
| `key.gitleaks` | whether gitleaks read the history (with no commit to read: whether it was on the PATH) |
| `at`, `repo`, `remote`, `files`, `commits`, `gitleaks` | what the check read, for the owner |

The guard computes the key now and refuses the push when the stamp's differs: another engine version, other rules,
gitleaks then and not now or the other way round. A stamp without `v` 2 and a `key` (0.2.5's), an unreadable one,
and one a newer brain wrote are refused the same way, never a crash; each refusal ends with the fix, « rerun brain
check --public --history ». A stamp is never upgraded in place: the check writes a new one. A gitleaks that is on
the PATH but fails stamps nothing (the check exits 1 and says so): its stamp would be refused at every push.

## External formats

What the engine reads from another program, and what it writes for one (wi-brain-external-contracts).

**In: Claude Code's hook payloads and transcripts.** Neither is a public API, so both are read tolerantly: every
field with a default, an unknown record skipped. That tolerance is made loud: the capture hook compares each payload
with its event's keys (`brain.capture.PAYLOAD_KEYS`: those every event may carry, those capture reads, the rest of the
hooks reference's) and the Stop hook's transcript reader (`brain.transcript.SessionStats.contract`) counts a record
type outside `transcript.RECORD_TYPES` and a user or assistant record without a key it reads (`timestamp`,
`message.id`, `message.model`, `message.usage`). Each is counted in `<BRAIN_HOME>/ledger/contracts.json` (`v` 1:
`{"keys": {"<source>: unknown|missing <key>": {count, first, last, shown}}}`, left as it is when a newer brain wrote
it; a key already counted is counted again at most once an hour, so a new key costs no write per tool call, and a
write that fails is a count lost, never a capture); its first sighting adds a line to `ledger/errors.log`, and the
next SessionStart health names it once. Nothing is refused. `tests/fixtures/claude/` holds a payload per captured event and a transcript, invented with the keys real ones
carry: `tests/test_capture.py` reads them clean.

**Out: the status document.** `brain doctor --json` (`brain profile`) prints the inventory contract a machines agent
emits too, published as `schemas/status.schema.json` (registered in `SCHEMAS`, `status`): `schema` is the contract's
id, `brain.status/v1` unless config.json `inventory.schema` names another of the same pattern (`<name>/v<N>`), so a
brain whose consumers know the contract under another name keeps it without the engine naming it. The schema is
versioned by that id, not by a top-level `v`; it allows a key it does not name at every level (an emitter may add
one) and holds the type of each key it names; removing or retyping one is a new id. Its fixtures,
`tests/fixtures/formats/status/v1/`, are the engine's document (`older`) and another emitter's, with keys of its own
and no `brain` block (`newer`); `tests/test_probe.py` checks the probe's report against the schema and the fixture,
and a consumer tests against the same two files.

**Out and in: the documentation graph.** `docgraph/v1` ([docgraph.md](docgraph.md), wi-brain-docgraph-contract) is a
documentation graph any program may emit and the Brain reads read only, published as `schemas/docgraph.schema.json`
(registered in `SCHEMAS`, `docgraph`). Like the status document, it is versioned by its id (`schema: docgraph/v1`), not
by a top-level `v`; it allows a key it does not name at every level, and a key it names keeps its type and its values:
a new node type, edge type or status is `docgraph/v2`, which `brain docgraph validate` refuses as a later contract.
Its fixtures, `tests/fixtures/formats/docgraph/v1/`, are a first producer's document (`older`) and another's with keys
of its own, a need and a producer's own check (`newer`); `tests/test_docgraph.py` reads both clean. A brain holds no
file of it (the upgrade test's `NOT_STORED`).

## The validator's keywords

`brain.schema` validates with the standard library only, so the capture hooks can validate what they write. It
implements the subset of JSON Schema 2020-12 the schemas use: `type`, `const`, `enum`, `required`, `properties`,
`additionalProperties`, `items`, `minItems`, `maxItems`, `minLength`, `maxLength`, `minimum`, `maximum`, `pattern`,
`format` (date, date-time), `$ref` to `#/$defs`, `allOf`, `if`/`then` (as an `allOf` entry of their own). A schema
that uses any other keyword, `if`/`then` elsewhere or `items` as a list is refused when it is loaded, and a test fails on it (`tests/test_formats_compat.py`): a validator in another language (ajv,
jsonschema) enforces the same contract, never a stricter one.

## Fixtures

`tests/fixtures/formats/<format>/v<N>/` holds, per format, an `older` file (as brain 0.2.4 wrote it) and a `newer`
one (a newer brain's additive keys under the same `v`). `tests/test_formats_compat.py` reads both, writes the records
back through the engine and compares them, field for field (AR lines byte for byte), then checks the strict mode and
the refusal of a higher `v`. A new format, or a new version of one, adds its pair; an additive change extends
the `newer` file only (the `projects` one holds an `access: read` entry and a second project at a shared root since
0.3.0).

Beside that pair, **each released engine's own file** (wi-brain-format-fixture-freeze): `<format>/v<N>/<tag>.<ext>`
(`ar/v1/v0.3.1.jsonl`), written by that tag through its own commands and frozen by `installer/freeze_store.py` (« The
old stores » below), never edited. `tests/test_formats_frozen.py` reads each one strict, as CI does: what N-1 wrote,
N reads with no note and no error. ar, config, ddr, event (the first lines of an exec ledger file), packs, projects,
sr and template are frozen from v0.2.4 and v0.3.1, then the last tag's at each version PR; the formats no command
writes (permissions, members, readme, modules, standards, docgraph) keep their hand-written pair only, and the status
document too: `brain doctor --json` prints the machine's own inventory, which a public fixture never holds.

### The old stores

A reader tested on its format alone can still refuse a whole brain an older engine made: brain #33's `brain lesson
add` refused every store made before it, and its tests used only stores its own code wrote. So
`tests/fixtures/stores/<tag>/brain/` holds a brain as a released engine wrote it, through that engine's own commands,
as an invented owner (wi-brain-old-store-fixture): brain init, the first commit, a milestone, three items (one
depending on another, one closed), a decision, a journal line, a lesson where the engine had the type, an AR, an SR
and the generated views. `freeze.json` beside it names the tag, the engine and each step with its exit code (a command
the engine lacked is recorded, not run again). They are frozen, never edited: v0.2.4 (before the Lesson type) and
v0.3.1 to start, then the last tag's at each version PR.

```bash
python packages/brain/installer/freeze_store.py v0.3.2     # installs the tag in a fresh venv and an isolated home
```

`tests/test_old_stores.py` copies each, commits it, moves the pin and runs `brain sync` as `brain update` does, then
runs this checkout strict on it: `brain check` (before the sync, its one failure may be the plugin to render again;
after it, none), `brain record check`, `brain item` (show, add, set, close), `brain items`, `brain lesson` (list, and
add: taken where the store has the Lesson type, refused with the way to add it where it has not), `brain retro`, and
the reads write nothing. The engine is public: the machine's user and host names that brain init writes into
`public.deny` are replaced by invented ones (`host-a`, `ada-l`), and a store that still names one, or the work folder
(an absolute path of the machine that froze it), is refused by the script.

## At a release

[`docs/release.md`](../../../docs/release.md) says when these are frozen. Its `release-check` job holds the list of each
format's schema files (`SCHEMAS` in `installer/release_check.py`): a version PR that changed one since the last tag and
has no `### Upgrade` in its CHANGELOG section fails, and so does a patch version that changed one at all (a format that
moves is a minor version, « The version policy »). A new folder here adds its entry there, or a test fails.

## The schema diff

`release-check` sees that a schema file changed; `brain schema diff` says what the change narrows, so that a breaking
format change is seen on the PR that makes it, not at the version PR (wi-brain-schema-diff; spec-brain-data-compat
N6). It compares, between a tag and the working tree, every schema the change touches: the JSON Schemas
(`*.schema.json`) and the graph stores' `schema.yaml` (a store's, or a template's), in any repo. A **narrowing** is
what a file valid before would no longer satisfy:

- a JSON Schema: a property removed, a field newly `required`, an `enum` that lost a value (or appeared), a `type`
  that lost one (or appeared), a `const` added or changed, `additionalProperties` closed or constrained, a bound
  tightened or added, a `pattern` or `format` added or changed (a wider pattern cannot be told: it counts), an
  `allOf` entry added, a `$ref` changed, the format's `v` moved, and any keyword it does not weigh (`anyOf`, `oneOf`,
  `not`, `if`, `uniqueItems`...) added or changed. It walks the subschemas: `properties`, `$defs`, `items`,
  `additionalProperties`, `allOf`, `then`, `else` (the engine's records keep their conditional fields there);
- a `schema.yaml`: a node type, an edge type or a status removed, a status of a type removed, a prop newly required;
- either: the file removed or renamed (a reader looks it up by its path), or one it cannot read or compare (said,
  never a crash).

What only widens is no narrowing (an optional property, a type, `integer` to `number`, a status, a value, `false` to
a schema), and prose (`description`, `title`, `$comment`, `examples`) is not compared. A narrowing is resolved by the
PR's **Compat: line**, in its body or a commit message of the range, read as the scout reads `Root cause:`:

```text
Compat: migration mig-ddr-v2          v bumped (properties.v.const) and fixtures/formats/ddr/v2/ in the change's tree
Compat: breaking adr-2026-11-12-x     an adr- id: the decision that drops the reader, for every narrowing of the PR
Compat: additive                      what the PR claims: a narrowing found stays unresolved
```

A `migration` id with no hyphen (`TBD`) or a `breaking` line with no `adr-` id resolves nothing.

```bash
brain schema diff --against v0.3.2 [--pr-body FILE|-] [--strict] [--json]
```

The scout (`brain audit --diff`) shows each unresolved narrowing as a `schema.narrowed` info line, never blocking,
and a resolved one as justified. With config.json `audit.schema_diff_strict: true` (the owner's opt-in) it is a NEW
line, to fix or resolve in the PR, and `brain schema diff` exits 1 on it (or with `--strict`): a release never newly
refuses what passed. CI's advisory `schema-diff` job runs it on every pull request against its target's tip (this
PR's change alone, and its own commits' Compat: lines), with the PR's body as it was at the push (an edited body is
read at the next push, or by re-running the job), into the job's summary. `permissions.yaml`'s keys are constants of
`brain.permissions`; `schemas/permissions.schema.json` describes them (wi-brain-permissions-schema), a test keeps the
two in step, and the diff compares it like any schema. `brain.permissions` still reads the file itself: the schema
refuses nothing at run time.

## The upgrade test (`compat-prev`)

The fixtures prove each reader on its own; the upgrade test proves an engine on a real brain, in both directions
(wi-brain-upgrade-test; spec-brain-data-compat N8, COMPAT-2 and COMPAT-3). CI's `compat-prev` job runs it on every
pull request, from the last tag before the commit (`git describe --tags --abbrev=0 --match 'v*' HEAD`; no tag
fails the job), before any tag is cut:

```bash
python packages/brain/installer/stranger_test.py --source . --upgrade-from v0.2.5     # or --upgrade-from <a checkout>
```

1. **The previous engine writes** every registered format into a new brain: brain init, a decision, an AR, an SR,
   the older `permissions.yaml` and `members.yaml` (no command writes them), its own exec events. A format
   registered here (a `<format>/v<N>/` folder) that the test does not place fails it, so the test grows with the
   registry.
2. **This checkout is installed over it**, the pin moved if the version changed, and runs strict (`BRAIN_STRICT=1`):
   the store plan (`brain init` on the existing brain), `brain sync` (the documented step after an upgrade: the
   plugin rendered again), `brain check`, `brain record check` and the stranger test's Lite scenario.
3. **The rollback.** Each `newer` fixture's additive keys are laid over the brain's files (a format they reach no
   file of fails the step), a canary and a drill are put on record (their entries as `vault.canary` and `vault.drill`
   write them; no real seal), and the previous engine is installed back over this one, as the installer does until
   the pin moves. In read mode it runs `brain check`, `brain record check`, `brain permissions check`,
   `brain vault status` (which must show the drill), `brain perf` (the ledger's events) and a newer template's plan.
   An engine with the read mode must pass them, its `brain check` exiting 0, or 1 when its one failure is the plugin
   this checkout's `brain sync` rendered (files under `plugins/`: the hooks carry the engine's `brain_version`, so
   every version is not current under the one before; the rollback renders nothing again, as it writes nothing). One
   before the read mode (0.2.5) may only refuse the newer keys (every `error:`
   line an unknown key or field, no traceback). No file of the brain or of `$BRAIN_HOME/vault` is changed or removed,
   and the ledger's files only grow.
4. **And back.** This checkout is installed again and makes the same reads, all passing, the drill shown; nothing is
   lost over the round trip.

After each install the harness checks that brain's `direct_url.json` names the engine meant: the tag and HEAD can
share a version. The job uploads its report (`compat-prev-report`, every step's command, exit code and output).

### Negative controls

A harness that cannot fail proves nothing (wi-brain-harness-negative-controls: the review of brain #52 found seven
false greens in this one). `tests/test_harness_negative_controls.py` reruns the upgrade test with one fault injected
each (`stranger_test.py --fault NAME`), and requires a no-go failing at the step that guards against it and at no
other, then once without a fault, which must be a go:

| Fault | What it does | The step that must fail |
|---|---|---|
| `rewrite` | `config.json` saved again after the older engine's reads, the same data in other bytes | `no loss` |
| `truncated-ledger` | an exec ledger's first line dropped there (the older engine appended its own after) | `no loss` |
| `unreached` | the `members` format's newer fixture replaced by its older one: its additive keys reach no file | `newer data` |
| `wrong-engine` | the previous engine reinstalled in place of this checkout for the way back | `engine` |

The missing tag needs no seam: `--upgrade-from ""` is refused before any install (a fast test). The plain stranger
test's control installs the last tag and denies the invented owner's name (`--deny "people:Ada Example"`): its leaks
must be found, every step ok. An upgrade rerun installs the engine four times (each on a copy of the checkout: pip
builds one in place, so two runs on the same one break each other): about 10 minutes on Windows. The reruns are
skipped unless selected,

```bash
pytest packages/brain/tests/test_harness_negative_controls.py -m harness -n 3
```

and CI's `harness-controls` job runs them on a pull request that touches `stranger_test.py`, the test fixtures, the
package's `pyproject.toml`, the controls or the workflows. The seams themselves are tested fast in the default suite. A new guard of the harness gets
its fault in `stranger_test.FAULTS` and its rerun here.

`tests/test_ci_workflows.py` checks the engine's own workflows: a step that writes a command substitution to
`GITHUB_OUTPUT` (`>>` or `tee -a`, in bash or pwsh; directly, or through a variable assigned one) must test first that it is not empty (`test -n`, or
`${var:?}`): an empty output is no error to the shell, and compat-prev once went on green with no tag. It reads only
this repository's `.github/workflows`, so no user repository is newly refused.
