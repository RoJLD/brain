section: Changes

- The typology doors kept open before the release (`wi-brain-typology-pretag`, spec-brain-typology-packs E1, E1 bis,
  E1 ter). The project base `_project` writes nothing of a code host: the GitHub issue template and the boundary's
  `.github/**` rule move to `_software`. `research` extends `_project` and takes the parts of `_software` it uses by a
  new template key, `takes: {an engine template: [the brain's paths]}`, instead of extending all of it. Every
  template's output is unchanged (a test hashes each one). A pack key of `source/packs.yaml` this engine does not
  know is kept and noted in read mode, refused only in strict mode (CI), as a top-level key already was, so a later
  brain may add pack keys (`typologies`, `layers`...). The README says that the templates' profiles and stages and
  the graph layers' `lifecycle` ids follow one typology catalog still to come, and that an unknown id is tolerated.
