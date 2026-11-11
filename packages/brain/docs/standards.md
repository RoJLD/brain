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
  there, by convention under `standards/` at the brain's root (where the upgrade test looks for them; the brain's
  `boundary.yaml` keeps them on the personal side).

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

## The engine's catalogs

**software** (`catalogs/software.yaml`, `wi-brain-standards-catalog-software`): 90 standards for code products
(profiles library, cli, local-client, service, data-pipeline, embedded), in ten domains, curated from two
taxonomies of engineering standards (a client architecture's six pillars and five gaps; software engineering's ten
domains) and the pillars they leave out (supply chain, portability and encodings, time, configuration and feature
flags, error messages, performance budgets, data lifecycle, recovery, AI-agent safety, multi-tenant isolation,
accessibility and i18n). Every row is `proposed` until the owner validates its domain; a validated row turns
`validated` in the same file. A row's `source` is a provenance trail (the pillar, gap or domain of the taxonomies it
comes from, by number); `refs` links the rows that overlap, kept apart because they are enforced differently. The
last domain holds data governance and the developer experience together, as the taxonomy does.

| Domain | Rows | What it holds |
|---|---|---|
| architecture | 8 | separation of concerns, bounded contexts, simplicity, injected dependencies, state machines, decision records, fitness functions |
| code-quality | 6 | parse don't validate, strict typing, typed errors, contracts, functional core, lint and format |
| concurrency | 7 | timeouts, locked writers, backpressure, cancellation, deterministic memory, mechanical sympathy, lock-free by measure |
| persistence | 9 | atomic writes, versioned formats, tolerant reader, migrations, checksums, backups, transactions, caches, recovery |
| distributed | 8 | idempotency, retries with backoff, circuit breakers, outbox, graceful degradation, bulkheads, replication, protocol versions |
| security | 14 | zero-trust input, secrets, encryption at rest and in transit, local IPC, least privilege, constant time, lockfiles, SBOM, reproducible builds, signing, image pinning, tenant isolation, AI-agent safety |
| testing | 12 | a test per change, the pyramid, hermetic tests, coverage, property-based, fuzzing, mutation, fault injection, simulation, formal specs, performance budgets, load tests |
| release | 9 | CI gates, SemVer, blue/green updates, canaries, feature flags, configuration as data, single instance, graceful shutdown, host footprint |
| observability | 6 | structured logs, metrics, correlation ids, crash reports, self-diagnosis, profiling |
| data-governance | 11 | privacy by design, erasure, retention, UTF-8, UTC, portability, i18n, accessibility, error messages, docs as code, a reproducible dev environment |

A prototype gets few rows (simplicity, lint and format, secrets, a test per change, UTF-8, UTC); a row's stage says
from when it is required, and the heavy ones (consensus, lock-free structures, canaries, mutation scores) wait for
`scale`. `brain standards list --catalog software --profile cli --stage mvp` shows what a command-line tool at MVP
follows.

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
- The language adapters (`wi-brain-lang-adapters`) carry a row's check per language through `adapter`; `languages`
  says which languages it covers today.
- The project templates (`wi-brain-project-templates`) write a `standards:` selection for a profile and stage.
- Left open: packs (a named set of ids), which a later key can add to the selection (an older engine notes an
  unknown key and keeps the file), and a row's per-stage severity (a later `v`).

A new key in a row or in the selection is a new format version or a note in read mode, never a silent change: the
catalogs and the selection are read tolerantly, written strictly ([formats.md](formats.md)).
