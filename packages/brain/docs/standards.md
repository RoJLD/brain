# The standards registry

Standards as data (`brain.standards`, `wi-brain-standards-registry`): one row per engineering standard, each with
the check that enforces it, reusable by every project, every agent and every language. A row binds no project: a
project opts in through `projects.yaml` `standards:`, by profile, stage and id. A project without that key follows
none, so nothing that passed before is refused.

## Catalogs

A catalog is a YAML file of rows, in the format `schemas/standards.schema.json` (kind `standards`, `v: 1`):

- the engine's own catalogs, under `src/brain/catalogs/*.yaml`: generic rows, in English, with nothing private (the
  engine is public, and `brain check --public` reads them like any file);
- a brain's local catalogs, that a project names in `standards.catalogs`: paths relative to the registry's folder
  (where `projects.yaml` is), as `root` is. A discipline's rows that stay in the owner's private brain live there.

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
([formats.md](formats.md)). An id found twice, in one catalog or across them, is an error.

## The opt-in

```yaml
# projects.yaml
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
plus `include`, minus `exclude`. `profiles` and `stage` go together; a project may hold `include` alone.

## The commands

- `brain standards list [--catalog C] [--domain D] [--profile P] [--stage S] [--enforcement E] [--status S]
  [--applicable] [--json]`: the rows by catalog and domain; `--applicable`, those the project follows, with why.
- `brain standards show ID [--json]`: one row, every field.
- `brain standards check [--json]`: exits 1 when a catalog breaks its format, an id is found twice, or the project's
  `standards:` names an unknown profile, stage or id; it lists the applicable standards whose check does not cover
  one of the project's repos' languages (`repos[].lang`), as gaps, never errors.
- `brain check --all` (and a brain's own `brain check`) checks every project's `standards:` the same way.
- `brain brief` lists the project's applicable standards as the invariants of the item's session.

The other consumers (the review lenses, the audit's standards check, the rules text, CI templates) come with
`wi-brain-standards-registry-consumers`; the languages' adapters with `wi-brain-lang-adapters`.

## Scope and target compatibility

**Scope.** Wave 0.3.2: the row format (`standards.schema.json`, `v: 1`), the engine's catalog folder, the
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
