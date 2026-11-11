# The standards registry

Standards as data (`brain.standards`, `wi-brain-standards-registry`): one row per engineering standard, each with
the check that enforces it, reusable by every project, every agent and every language. A row binds no project: a
project opts in through `projects.yaml` `standards:`, by profile, stage and id. A project without that key follows
none, so nothing that passed before is refused.

## Catalogs

A catalog is a YAML file of rows, in the format `schemas/standards.schema.json` (kind `standards`, `v: 1`):

- the engine's own catalogs, under `src/brain/catalogs/*.yaml`: generic rows, in English, with nothing private (the
  engine is public, and `brain check --public` reads them like any file; the first, `software`, comes with
  `wi-brain-standards-catalog-software`, and until then `brain standards list` is empty);
- a brain's local catalogs, that a project names in `standards.catalogs`: paths relative to the registry's folder
  (where `projects.yaml` is), as `root` is, and inside it (an absolute path, or one that climbs out of it, is an
  error); the same file named twice is read once. A discipline's rows that stay in the owner's private brain live
  there.

```yaml
v: 1
catalog: software                 # its name: brain standards list --catalog
title: Software engineering       # one line
source: where the rows were curated from, in neutral words
rows:
  - id: sw-atomic-writes          # unique across every catalog a brain loads; never reused
    domain: persistence           # its domain within the catalog
    title: Atomic writes          # optional: a short name
    statement: Every file the program owns is written to a temporary file, then renamed over the old one.
    why: A crash mid-write leaves half a file.             # optional
    profiles: [cli, local-client, service]                 # or [any]
    stage: mvp                    # required from this stage on
    enforcement: check            # how it is enforced
    check: a lint refuses an open for writing outside the helper
    adapter: lint                 # optional: the language adapter's slot that carries its results
    languages: [py]               # the languages its check covers, or [any]
    coverage: {status: partial, by: the state helper}      # optional: how the Brain itself meets it
    status: proposed              # proposed until the owner validates it
    source: pillar 1              # optional: where in the catalog's source
    refs: [sw-utc]                # optional: related standards, items, specs
```

The vocabularies (`brain.standards`):

| Key | Values |
|---|---|
| `profiles` | `any`, `library`, `cli`, `local-client`, `service`, `data-pipeline`, `embedded`, `research`, `strategy`, `marketing`, `engineering-product` |
| `stage` | `prototype`, `mvp`, `v1`, `scale`, in that order: a row is required from its stage on |
| `enforcement` | from the cheapest: `check` (a machine check that blocks), `measure` (a number that trends), `test-template` (a test the brief asks for), `review-lens` (a question of the review), `rule` (judgement only) |
| `adapter` | `lint`, `typecheck`, `test`, `coverage`, `format` |
| `coverage.status` | `have`, `partial`, `none`, `n/a` |
| `status` | `proposed` (curated, not validated yet), `validated` (the owner validated it, batch by batch) |

A value outside them is a newer engine's: a note in read mode, an error in strict mode (CI), as an unknown key is
([formats.md](formats.md)). An id found twice, in one catalog or across them, is an error. A catalog of a higher
`v` (a newer engine's) is refused and its rows are not read: `brain standards check` and `brain check --all` are red
until the engine is updated.

## The opt-in

```yaml
# projects.yaml (the ids are illustrative: brain standards list gives the real ones)
app:
  root: ../app
  standards:
    profiles: [cli, local-client]  # the kinds of project it is
    stage: mvp                     # its stage
    include: [sw-sbom]             # rows taken whatever their profile and stage
    exclude: {sw-utc: "it stores no time at all, only counters"}   # rows waived, a reason of 15 characters or more
    catalogs: [standards/research.yaml]   # the brain's local catalogs, relative to the registry's folder
```

The rows that apply are those whose profiles meet the project's (or `any`) and whose stage is at or before its own,
plus `include`, minus `exclude`. `profiles` and `stage` go together; a project may hold `include` alone. An empty
`standards:` declares none, as without the key.

## The commands

- `brain standards list [--catalog C] [--domain D] [--profile P] [--stage S] [--enforcement E] [--status S]
  [--applicable] [--json]`: the rows by catalog and domain; `--stage S`, those required at stage S (theirs at or
  before it); `--applicable`, those the project follows, with why.
- `brain standards show ID [--json]`: one row, every field.
- `brain standards check [--json]`: exits 1 when a catalog breaks its format, an id is found twice, a local catalog
  cannot be read, or the project's `standards:` is malformed (a wrong shape, an exclude without its reason, profiles
  without a stage) or names an unknown profile, stage or id; it lists the applicable standards whose check does not
  cover one of the project's repos' languages (`repos[].lang`), as gaps, never errors. Every `brain standards`
  command exits 2 when one of the engine's own catalogs cannot be read.
- `brain check --all` (and a brain's own `brain check`) checks every project's `standards:` the same way.
- `brain brief` lists the project's applicable standards as the invariants of the item's session.

The other consumers (the review lenses, the audit's standards check, the rules text, CI templates) come with
`wi-brain-standards-registry-consumers`; the languages' adapters with `wi-brain-lang-adapters`.

## Language adapters

A row's `adapter` names the slot whose results carry its check. A repo declares the reports its own tools write in
`projects.yaml` `repos[].tools` (`brain.langs`, `wi-brain-lang-adapters`), a new optional key beside `lang`, which
does not change:

```yaml
repos:
  - path: ../web
    lang: ts
    tools:
      lint: {report: reports/eslint.sarif, format: sarif, tool: eslint}
      typecheck: {report: reports/tsc.sarif, format: sarif}
      test: {report: reports/junit.xml, format: junit, tool: vitest}
      coverage: {report: coverage/coverage-summary.json, format: istanbul-summary}
```

| Slot | Formats it reads | What counts |
|---|---|---|
| `lint`, `typecheck`, `format` | `sarif`, `junit` | every SARIF result (a `note` or `none` level aside), every failed or errored case |
| `test` | `junit` | failed and errored cases, over the cases run |
| `coverage` | `cobertura`, `lcov`, `coverage-json` (coverage.py), `istanbul-summary` (istanbul, c8) | the line coverage, in percent |

A report path is relative to the repo's registered checkout and stays inside it. The engine **reads** the reports and
runs no tool: the project's CI or its developer writes them (running the declared commands, under the guards, is
`wi-brain-lang-adapters-exec`, after a test phase). `brain.langs.DEFAULTS` names the usual tools of Python and
TypeScript and how each writes its report; the messages quote them, nothing is assumed from them.

- `brain audit` measures `lang.report` (P2, never in the scout, listed only for a repo that declares `tools:`): a
  report missing or unreadable, failed tests, lint, type or format findings, coverage under the floor.
- `brain standards check` counts a standard whose `adapter` slot a repo declares as covered on that repo's language,
  so a TypeScript repo with a `lint` report is no gap for a lint standard written for Python.
- A slot, key or format this engine does not know is a note in read mode (a newer engine's), an error in strict mode
  (CI); an older engine notes `tools` as an unknown repo key, and refuses it in CI's strict mode.

## Scope and target compatibility

**Scope.** Wave 0.3.2: the row format (`standards.schema.json`, `v: 1`), the engine's catalog folder (its first
catalog, software, in the same wave), the
`projects.yaml` `standards:` key, `brain standards list|show|check` and the brief's invariants. Nothing is enforced on
a project's code yet: the registry says what applies, and `brain standards check` says what is declared wrong.

**Target compatibility.**

- The catalogs (`wi-brain-standards-catalog-software`, `-research`, `-disciplines`) are data in this format: a new
  catalog or row moves no format.
- The consumers (`wi-brain-standards-registry-consumers`) read the same rows: `enforcement` says which consumer takes
  a row, `check` and `adapter` what it runs or reads. An extension point, nothing to change in the format.
- The language adapters (`wi-brain-lang-adapters`, « Language adapters » above) carry a row's check per language
  through `adapter`; `languages` says which languages it covers without one. Running the declared commands
  (`wi-brain-lang-adapters-exec`) adds a key to a slot's entry (an older engine notes it), never a change of
  `report` or `format`.
- The project templates (`wi-brain-project-templates`) write a `standards:` selection for a profile and stage.
- Left open: packs (a named set of ids), which a later key can add to the selection (an older engine notes an
  unknown key and keeps the file), and a row's per-stage severity (a later `v`).

A new key in a row or in the selection is a new format version or a note in read mode, never a silent change: the
catalogs and the selection are read tolerantly, written strictly ([formats.md](formats.md)).
