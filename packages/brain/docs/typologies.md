# The typology catalog

One vocabulary of the kinds of project (`brain.typologies`, `wi-brain-typology-catalog`). The graph layers'
`lifecycle` ids (`research_graph layers`), the project templates' profiles (`brain init --template`), the standards'
profiles and stages (`brain standards`, [standards.md](standards.md)) and a scope node's `lifecycle.typologies` all name
its ids. Before it, three lists named kinds of project and two named stages; each of their ids is now an entry or a
sub-profile of this catalog, and each of their stages one of its stages.

```bash
brain typologies [--lang en|fr] [--json]                # the entries, their sub-profiles, the stages
brain typologies show cli --stage mvp [--json]          # one id: its entry and the layers proposed at a stage
```

## Entries and sub-profiles

An **entry** is a kind of project, with its column to the Vision's modules (`vision`): J1 the engineering studio,
J2 research, J3 creation, K3 venture, K4 enterprise. A **sub-profile** is a narrower kind of one entry.

| Entry | Vision | Sub-profiles |
|---|---|---|
| `software` | J1 | `library`, `cli`, `local-client`, `service`, `data-pipeline`, `api-cli`, `ai-ml`, `infra`, `embedded` |
| `research` | J2 | `trading` |
| `hardware-cad` | J1 | `hardware`, `engineering-product` |
| `creation` | J3 | |
| `strategy` | K3, K4 | |
| `marketing` | K4 | |
| `organisation` | K4 | |
| `compliance` | K4 | |

A sub-profile takes what its entry takes, plus what names it: a project of kind `cli` is proposed the layers open to
`software` (`code`, `docs_tests`, `features`) and those open to `cli`, and meets the standards rows of profile
`software` as well as those of profile `cli`; a sibling's (`service`) it does not meet. `*` (a layer) and `any` (a
standards row) are every kind.

## Stages

The lifecycle's stages (spec-brain-product-lifecycle LC-2): `explore`, `build`, `launch`, `grow`, `mature`, `sunset`,
`retired` for a living product; `explore`, `build`, `deliver`, `closed` for a finite project. The standards' stages
(`brain init --stage`, a standards selection) map to them: `prototype` → `explore`, `mvp` → `build`, `v1` → `launch`,
`scale` → `grow`. A layer may inject a stage of its own (research's `preregistration-backtest`): the layer's, not the
catalog's.

## A brain's labels and its own ids

The engine's catalog is `src/brain/typologies.yaml` (`v: 1`). A brain renames its labels and adds its own ids in
`config.json` `typologies`, as `scope_types` does for the scope tree's types (SCOPE-4):

```json
"typologies": {
  "software": {"fr": "Produit logiciel"},
  "podcast": {"en": "Podcast", "fr": "Podcast", "parent": "creation"},
  "venture": {"en": "Venture", "vision": ["K3"]}
}
```

`en`, `fr`, `description` and `vision` (an entry's) rename; `parent` makes a new id a sub-profile of that entry,
without it the new id is an entry. An engine id keeps its id and its place: it cannot be given a parent. `brain
config --check` (and `brain check`) refuses an id that is not lowercase letters, digits and `-`, an empty label, a
parent that is no entry, a vision that is not a list of module ids; an unknown key is a note in read mode.

The standards' vocabulary is the engine's catalog: a brain's own id names no standards row until a later engine
knows it (a note in read mode).

## An id the catalog does not know

Wherever a brain names a typology id (a scope node's `lifecycle.typologies`, a standards row or selection), an id the
catalog does not know is a note in read mode and an error only in strict mode (CI), so a brain written by a later
catalog is read by this engine. A layer that names one is read, and is proposed to that id only.

## Compatibility

Ids are stable and English, never renamed nor reused: an id is persisted in layer files, standards rows, a brain's
registry and scope tree, and later in a pack's `typologies` and an item's `props.typology`
(spec-brain-typology-packs §4, door 1). A later catalog adds entries and sub-profiles; it never moves a sub-profile to
another entry. The labels are free to change. The catalog's own `v` is the engine's: a brain never writes
`typologies.yaml`.
