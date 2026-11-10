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
| permissions.yaml | the brain's root | `v` | a note; an **allow** rule that carries an unknown key is left out (the key may narrow it), a deny or ask rule is kept | refused |
| packs.yaml | `source/packs.yaml` | `v` | a note | refused |
| template.yaml | a template's folder | `engine:` range | a note (in CI: refused) | `engine:` is checked **first**: a template for a newer engine says "it needs brain >=X", not "unknown key(s)" |
| projects.yaml | the brain's root | none yet | a project key (`KEYS`) or a `repos:` key (`REPO_KEYS`): a note, kept. `access` is a key that **narrows**: a brain that does not know it (0.2.8 and before) keeps the note (in CI: refused, so a brain repo whose CI runs 0.2.8 goes red) and reads an `access: read` entry as a full project, at the registry's root with the default store, journal and decision log, so such an entry lands in a registry only once every machine runs brain 0.3.0 or later | - |

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

`v` is the top-level integer `v`; a file without one is read as version 1. A record keyed by names (schedules,
projects) keeps its `v` 1 unwritten, so that brain 0.2.5, which reads every key as a name, still reads it.

| File | Version | What the engine does when it cannot write it |
|---|---|---|
| `schedules/installed.json` | `v` 1, unwritten | `brain schedule install --apply` prints the plan and refuses (exit 2) |
| `alerts/state.json` | `v` 1, unwritten | the notify pass sends nothing (« nothing sent: ... »), since sending without a record would send again each pass |
| `vault/state.json` | `v` 1, written from 0.2.6 | `brain vault seal`, `canary` and `drill` refuse before any work; `status` and the health still read it |
| `usage/sessions.json` | `v` 2 (`LEDGER_V`, apart from the scanner's `SCAN_V`, which only rescans rows) | `brain usage` brings the rows up to date in memory and says on stderr that it saved nothing |

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
| `vault.device` | `vault/device.json` | truth-local | next (read-only here; `device init` and the rotation write it atomically) |
| `cockpit.load_state` | `tui.json` | truth-local | next: it also drops the keys it does not know |
| `memory.load_state` | `memory-sync/state.json` | truth-local | next (the 3-way base; off on the pilot, `BRAIN_MEMORY_SYNC=0`) |
| `cockpit.snapshot_of`, `sessions.snapshot` | `sessions/<id>.json` | truth-local | next (the Stop hook's snapshot; read-only at these sites) |
| `sessions.read_report` | `sessions/<id>.report.json` | truth-local | next (read-only here) |
| `sessions.watch_state` | `budget/<session>.json` | truth-local, one session's life | next (written by the bash budget hooks) |
| `sessions.app_meta` | the desktop app's session file | foreign, read only | `{}` is right: never written |
| `codemap.read` | `code-map/<project>.json` | derived (local) | `{}` is right: rebuilt |
| `codeindex.read_record` | `code-index.json` | derived (local) | `{}` is right: rebuilt |
| `forecast.load_latest` | `forecast/<project>/latest.json` | derived (local) | `{}` is right: rebuilt |
| `quota.load_status` | the quota forecast | derived (local) | `{}` is right: rebuilt |
| `update._read_cache` | `update.json` | derived (local) | `{}` is right: the tags are asked again |

## Public-check stamps: a derived file with its whole key

A green `brain check --public --history` on a public repo writes `$BRAIN_HOME/public-check/<owner>/<repo>/<sha>`
(atomically), which the `public` guard reads before a `git push` (wi-brain-public-stamp-binding, spec-brain-data-compat
N2). It is a cache, so it carries every input it depends on:

| Field | What |
|---|---|
| `v` | 2 (0.2.5 and older wrote none) |
| `key.engine` | the engine version that checked |
| `key.rules` | sha256 of config.json's `public.deny` (as brain.config reads it), `allow`, `patterns` and `refuse`, in a canonical form: key order and spacing do not count |
| `key.gitleaks` | whether gitleaks read the history (with no commit to read: whether it was on the PATH) |
| `at`, `repo`, `remote`, `files`, `commits`, `gitleaks` | what the check read, for the owner |

The guard computes the key now and refuses the push when the stamp's differs: another engine version, other rules,
gitleaks then and not now or the other way round. A stamp without `v` 2 and a `key` (0.2.5's), an unreadable one,
and one a newer brain wrote are refused the same way, never a crash; each refusal ends with the fix, « rerun brain
check --public --history ». A stamp is never upgraded in place: the check writes a new one. A gitleaks that is on
the PATH but fails stamps nothing (the check exits 1 and says so): its stamp would be refused at every push.

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

## At a release

[`docs/release.md`](../../../docs/release.md) says when these are frozen. Its `release-check` job holds the list of each
format's schema files (`SCHEMAS` in `installer/release_check.py`): a version PR that changed one since the last tag and
has no `### Upgrade` in its CHANGELOG section fails, and so does a patch version that changed one at all (a format that
moves is a minor version, « The version policy »). A new folder here adds its entry there, or a test fails.

## The upgrade test (`compat-prev`)

The fixtures prove each reader on its own; the upgrade test proves an engine on a real brain, in both directions
(wi-brain-upgrade-test; spec-brain-data-compat N8, COMPAT-2 and COMPAT-3). CI's `compat-prev` job runs it on every
pull request, from the last tag before the commit (`git describe --tags --abbrev=0 --match 'v*' HEAD`; no tag
fails the job), before any tag is cut:

```bash
python packages/brain/installer/stranger_test.py --source . --upgrade-from v0.2.5     # or --upgrade-from <a checkout>
```

1. **The previous engine writes** every registered format into a new brain: brain init, a decision, an AR, an SR,
   the older `permissions.yaml`, its own exec events. A format registered here (a `<format>/v<N>/` folder) that the
   test does not place fails it, so the test grows with the registry.
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
