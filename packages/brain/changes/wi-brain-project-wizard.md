section: Added

- The new-project wizard, first slice (`wi-brain-project-wizard`, spec-brain-client-standards §8, STD-5): `brain
  project new DIR --kind K [--kind K]... [--stage S] [--template T] [--apply]` asks what the project produces (ids of
  the typology catalog; code products and research first) and its stage, plans (the layers its kinds are proposed, the
  template, `brain init`'s plan), and with `--apply` writes its brain through `brain init`, its registry entry
  recording `lifecycle: {typologies, stage}`. Run again on that brain, the plan shows what the answers change there and
  writes nothing (a PR of that brain). The cockpit's Setup page offers it as « A new project ».
