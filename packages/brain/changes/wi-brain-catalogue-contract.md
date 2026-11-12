section: Added

- `catalogue/v1`, the module catalogue's neutral contract (`wi-brain-catalogue-contract`,
  [docs/catalogue.md](docs/catalogue.md)): a public, versioned JSON format any program may emit for a catalogue of
  modules (its bricks; its modules with their hard and soft dependencies, the machine facts they require, the clauses
  that recommend them, their estimated cost in RAM, disk, VRAM and download, their fallback and licence; the
  distributions that ship them, with a digest and a signature to install offline; and the presets an installer
  offers, base ones and the personas a private catalogue declares), so one installer and one Modules tab read every
  catalogue. Its schema is `schemas/catalogue.schema.json`, registered with the other formats, with an invented
  catalogue of each side of the version in `tests/fixtures/formats/catalogue/v1/`; it evolves by the status
  contract's rule (an unknown key tolerated at every level, a new class, status or preset kind is v2, a typology id no
  catalogue holds yet kept, never refused; `release-check` counts an optional key added to its schema as a patch, as for
  docgraph/v1). `brain catalogue validate FILE...` checks a document against it (exit 1 when invalid or written for a
  later version; no brain needed) and `brain catalogue emit [--out FILE]` prints the brain's own: `brain mod`'s
  modules, the engine and its extras as distributions, and the presets Lite, Default and Recommended.
