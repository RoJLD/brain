# catalogue/v1: the module catalogue's contract

`catalogue/v1` is a public, versioned format for a catalogue of modules: what a product or a brain is made of, which
parts depend on which, what each one costs a machine and needs from it, what replaces it when it is off, its licence,
what ships it, and the starting points an installer offers. Any program may emit it: the Brain emits its own
(`brain catalogue emit`), a product's module manager may emit its own; an installer (`brain init`'s screens) or a
settings tab reads one and plans from it, so one Modules screen serves every catalogue.

**Target compatibility.** Nothing in the contract is the Brain's alone: a `module` is any part a user turns on or
off (a capability of the engine, a plug-in, a model, a service), a `brick` any group of modules, a `distribution`
anything that ships them (the install itself, a package, an archive, a container image). The facts a module requires
are those of the machine status document (`brain.status/v1`, [formats.md](formats.md#external-formats)); the
typology ids a module or a preset names are the typology catalogue's (still to come), and an id a reader does not
know is kept, never refused.

The schema is [`schemas/catalogue.schema.json`](../src/brain/schemas/catalogue.schema.json); the rules a schema cannot
say are `brain.catalogue.validate`'s. Two invented documents, one of each side of the version, are in
[`tests/fixtures/formats/catalogue/v1/`](../tests/fixtures/formats/catalogue/v1/): a producer and a reader test
against the same files.

```bash
brain catalogue validate catalogue.json     # exit 1 when it does not hold to the contract
brain catalogue emit --out catalogue.json   # the brain's own catalogue
```

`validate` needs no brain: it runs wherever the engine is installed.

## A document

```json
{
  "schema": "catalogue/v1",
  "generated": {"at": "2026-01-01T00:00:00Z", "by": "example-tool 0.1.0", "from": ["modules.yaml"]},
  "name": "kettle",
  "bricks": [{"id": "K", "name": "the kettle"}],
  "modules": [
    {"id": "kettle-core", "name": "Kettle core", "brick": "K", "class": "core", "status": "built",
     "cost": {"disk_mb": 20}, "licence": "MIT", "distributions": ["base"]},
    {"id": "kettle-vision", "name": "Kettle vision", "brick": "K", "class": "service", "status": "built", "ai": true,
     "depends_on": ["kettle-core"], "requires": ["gpu"], "recommend_when": ["gpu_vram_gb >= 8"],
     "cost": {"ram_mb": 900, "vram_gb": 6, "download_mb": 2100}, "fallback": "the core alone",
     "distributions": ["vision-image"]}
  ],
  "distributions": [
    {"id": "base", "name": "the kettle install", "kind": "base", "bundled": true},
    {"id": "vision-image", "name": "the vision image", "kind": "image", "bundled": false,
     "source": {"url": "https://example.org/kettle/vision.tar", "size_mb": 2100, "sha256": "…", "signature": "…"}}
  ],
  "presets": [
    {"id": "lite", "name": "Lite", "kind": "base", "modules": ["kettle-core"]},
    {"id": "recommended", "name": "Recommended", "kind": "base", "modules": ["kettle-core"],
     "when_fits": ["kettle-vision"]}
  ]
}
```

- `schema` (required): `catalogue/v1`, the contract's id; the version is the id's, never a top-level `v`.
- `generated` (required): `at` (a date-time), `by` (the producer and its version) and `from` (what it read).
- `name`: the product or the brain whose modules it lists.
- `bricks`, `modules`, `distributions`, `presets`: lists of objects, each with an `id` unique in its list. An id is
  stable (letters, digits, `_ . : -`); a `name` is a label and may be renamed.

## Modules

| Key | Meaning |
|---|---|
| `id`, `name` (required) | its stable id and its label |
| `description` | what it does, in a sentence |
| `brick` | the brick it belongs to: an id of `bricks` |
| `class` | `core` (always on, nothing beyond the base install), `extra` (an optional package or tool, no resident process) or `service` (a resident process, local or remote) |
| `status` | `built`, or `planned`: listed so a reader sees what comes, never installable nor in a preset |
| `auto` | used whenever it is found: no switch turns it on or off |
| `ai` | it runs a model: what a preset that forbids AI leaves out |
| `components` | what turning it on turns on, in the producer's own terms (the Brain: its capabilities) |
| `depends_on` | the modules it needs (hard): turned on with it |
| `uses` | the modules it reads when they are on (soft): its fallback otherwise, never pulled |
| `requires` | facts of the machine that must hold for it to run, beyond what its distributions bring: a tool found (`docker`, `git`), `gpu`, `container_runtime`, `env:NAME` |
| `recommend_when` | clauses that must all hold for a recommended preset to add it: a fact (`docker`), its negation (`not wsl`), or a comparison (`memory_gb >= 7`) |
| `cost` | estimated: `ram_mb` (resident memory, MiB), `disk_mb` (installed, data excluded, MiB), `vram_gb` (GPU memory, GiB), `download_mb` (what adding it downloads, MiB) |
| `fallback` | what replaces it when it is off or missing |
| `licence` | an SPDX expression, or a name |
| `distributions` | the distributions it needs installed |
| `typologies` | the project typologies it serves (the typology catalogue's ids) |

The facts `requires` and `recommend_when` name are the flat facts of the machine status document: `os`, `arch`,
`cpu_cores`, `memory_gb`, `gpu`, `gpu_vram_gb`, `disk_free_gb`, each tool found (`git`, `docker`, `gh`...),
`container_runtime`, `docker_server`, `kube_context`, `ecc`, `battery`, `encrypted`. Memory and VRAM are in GiB as
the system reports them (an 8 GB machine reports about 7.8). A fact a reader does not know is unknown on its machine:
the module does not fit there, and the reader says why.

## Distributions

| Key | Meaning |
|---|---|
| `id`, `name` (required) | its stable id and its label |
| `kind` | what it is, in the producer's words: `base` (the install itself), `package`, `extra`, `archive`, `image`... |
| `version`, `licence` | its version and licence |
| `bundled` | `true`: it comes with the base install, adding a module it ships downloads nothing |
| `source` | where it is fetched from and how it is checked: `url`, `size_mb`, `sha256` (64 hexadecimal digits), `signature` (where it is, or the signature itself) |

A reader with no network installs a distribution from a copy with the same `sha256`: nothing in the contract needs
a network to read or to plan.

## Presets

| Key | Meaning |
|---|---|
| `id`, `name`, `modules` (required) | its stable id, its label, the modules it turns on whatever the machine (for a persona, those beyond its base's) |
| `description` | who it is for |
| `kind` | `base` (one of the catalogue's starting points) or `persona` (a profile of user a catalogue declares) |
| `base` | for a persona, the base preset it starts from: the persona turns on the base's modules, then its own |
| `when_fits` | the modules it adds on a machine that holds their `requires` and `recommend_when` |
| `typologies` | the project typologies it suits |

A preset lists what it turns on; the hard dependencies of its modules are pulled by the reader (a note of
`validate`), never by a hidden rule. The public engine's catalogue holds three base presets, `lite`, `default` and
`recommended`, and no persona: a persona is a private brain's, declared in its own catalogue.

## The Brain's own catalogue

`brain catalogue emit` prints the brain's catalogue: the modules `brain mod` turns on and off (its registry's
entries that list the engine's capabilities, else one module per capability, [modules.md](modules.md)), with:

- `components`: the module's capabilities ([the profiles](../README.md#a-projects-brain-by-profile)); `class` the
  most costly of theirs (core, then extra, then service), `status` planned when one of them is, `auto` when all are;
- `depends_on`: the registry's, and those its capabilities' own dependencies deduce; `uses`: the registry's (those
  that are modules of the catalogue) and its capabilities' soft dependencies;
- `requires`, `recommend_when`, `fallback` and `cost`: its capabilities', the costs summed (a capability's `disk_gb`
  counted in MiB);
- `brick`, `ai` and `description` (its `definition`): the registry entry's;
- `licence`: the engine's; `distributions`: `base` (the engine) and `extra-<name>` for each pip extra a capability
  installs;
- the presets `lite`, `default` and `recommended` (`brain profile`'s bases): each lists the modules whose switched
  capabilities its base brings; `recommended` adds, in `when_fits`, the built modules of profile recommended.

The document is validated as it is emitted (exit 1 on an error): what the contract refuses there comes from the
registry it is read from (two modules whose capabilities depend on each other's, which makes a cycle; an id or a brick
with a space), and the registry is fixed. A requirement a module's pip extra installs (`textual` for the cockpit) is
not one the machine must hold: it is left out of `requires`. `when_fits` follows `brain profile`'s Recommended: a
module whose switched capabilities are all in Default or recommendable (built, not auto, their dependencies in), one
of them recommendable.

## Evolution

The status contract's rule (`brain.status/v1`, [formats.md](formats.md#external-formats)):

- an optional key may be added in v1 at any level, and a reader ignores the keys it does not know (the schema allows
  them everywhere);
- a key the schema names keeps its type and its values: a new class, status or preset kind, a key made required,
  removed or retyped, or a change of meaning makes `catalogue/v2`;
- a reader refuses a later version with « a later contract than this engine's catalogue/v1: brain update », and
  judges none of its keys (their meaning may have changed).

`release-check` counts an optional key added to the schema as a patch, as for `docgraph/v1`
([release.md](../../../docs/release.md)).

## Neutral

A document holds no hostname, address, personal data or private name. A private brain's catalogue (its own bricks,
modules and personas) stays in that brain; a public product's catalogue holds only what it ships. The data go from the
public to the private, never back.

## What `brain catalogue validate` checks

The file is UTF-8 JSON (a byte order mark is accepted); a document nested too deep is refused as not JSON, never a
crash. Errors (exit 1): the schema's (a required key, a type, a value outside a list, a pattern); a later version; an
id used twice in its list; a `depends_on`, `brick`, `distributions` or preset module that the document does not hold;
a module both a hard and a soft dependency of another, or of itself; a cycle of hard dependencies; a planned module
in a preset, or a module both in a preset's `modules` and its `when_fits`; a persona whose `base` is not a base
preset. Notes (kept, never refused): a `uses` that names a module the document does not hold (another catalogue's),
a persona with no base, and the hard dependencies a preset's modules pull. `--json` gives, per file, `file`, `ok`,
`errors`, `notes` and `summary` (`schema`, `by`, `modules`, `classes`, `statuses`, `bricks`, `distributions`,
`presets`).
