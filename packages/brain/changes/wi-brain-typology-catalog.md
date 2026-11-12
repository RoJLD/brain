section: Added

- The typology catalog (`wi-brain-typology-catalog`, spec-brain-typology-packs E1, TYPO-3): one vocabulary of the kinds
  of project for the graph layers' `lifecycle` ids, the project templates' profiles and the standards' profiles. Eight
  entries (`software`, `research`, `hardware-cad`, `creation`, `strategy`, `marketing`, `organisation`, `compliance`),
  each with its column to the Vision's modules (J1 to K4); every id 0.4.0 published is an entry or a sub-profile
  (`cli`, `service`, `ai-ml`... of `software`), and a sub-profile takes what its entry takes (a `cli` project meets the
  standards rows of `software`). The lifecycle's stages, and the standards' stages mapped to them (`mvp` → `build`).
  `brain typologies [show ID --stage S]` lists the catalog and the layers a kind is proposed at a stage; config.json
  `typologies` renames labels and adds a brain's own ids; a scope node's `lifecycle.typologies` is read against it.
  An id the catalog does not know is a note in read mode, an error in strict mode (CI). Contract:
  `docs/typologies.md`.
