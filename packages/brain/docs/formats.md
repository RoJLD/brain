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
| projects.yaml | the brain's root | none yet | a project key (`KEYS`) or a `repos:` key (`REPO_KEYS`): a note, kept | - |

AR lines are parsed one by one (`brain.records.parse_ar`): a line that is not a JSON object (a conflict marker, a
truncated write, a byte that is not UTF-8) or that its schema refuses is an error of `brain record check`; a line a newer brain wrote (a higher
`v`, a kind this engine does not know) is skipped and counted. Neither stops `brain sync`: the graph is built from the
other lines, and a note says how many were left out. Their ids still count as recorded, so no AR is appended twice.

## Machine-local state: `brain.stateio`

A **truth-local** file lives under `$BRAIN_HOME` on one machine, with no git behind it: losing it loses a record
nothing else keeps. Such a file is read and written through `brain.stateio` (`load`, `save`), which:

- reads a missing file as an empty record;
- **sets aside** a file that is not JSON, not an object, or not the shape its owner expects: it is moved beside
  itself as `<name>.unreadable-<UTC stamp>` (a line on stderr names it) and the record starts afresh. It is never
  replaced by `{}` and saved over;
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
| `usage/sessions.json` | `v` = the scanner's `SCAN_V` (2) | `brain usage` brings the rows up to date in memory and says on stderr that it saved nothing |

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
the refusal of a higher `v`. A new format, or a new version of one, adds its pair.
