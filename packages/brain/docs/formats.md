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

## The upgrade test (`compat-prev`)

The fixtures prove each reader on its own; the upgrade test proves an engine on a real brain, in both directions
(wi-brain-upgrade-test; spec-brain-data-compat N8, COMPAT-2 and COMPAT-3). CI's `compat-prev` job runs it on every
pull request, from the last tag before the commit (`git describe --tags --abbrev=0`), before any tag is cut:

```bash
python packages/brain/installer/stranger_test.py --source . --upgrade-from v0.2.5     # or --upgrade-from <a checkout>
```

1. **The previous engine writes** every registered format into a new brain: brain init, a decision, an AR, an SR,
   the older `permissions.yaml`, its own exec events. A format registered here (a `<format>/v<N>/` folder) that the
   test does not place fails it, so the test grows with the registry.
2. **This checkout is installed over it**, the pin moved if the version changed, and runs strict (`BRAIN_STRICT=1`):
   the store plan (`brain init` on the existing brain), `brain sync` (the documented step after an upgrade: the
   plugin rendered again), `brain check`, `brain record check` and the stranger test's
   Lite scenario.
3. **The rollback.** Each `newer` fixture's additive keys are laid over the brain's files, a vault drill is put on
   record, and the previous engine is installed back over this one, as the installer does until the pin moves. It
   runs `brain check`, `brain record check`, `brain permissions check`, `brain vault status` (which must show the
   drill) and a newer template's plan, in read mode. An engine with the read mode must pass them; one before it
   (0.2.5) may refuse, cleanly. Either way no file of the brain, and not the vault state, is changed or removed.

The job uploads its report (`compat-prev-report`, every step's command, exit code and output).
