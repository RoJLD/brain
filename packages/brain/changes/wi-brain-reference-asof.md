section: Added

- The technical reference as of a point (`wi-brain-reference-asof`, [docs/views.md](docs/views.md), « The reference
  as of a point »): `brain reference --asof POINT [--out DIR]` renders it as of a wave (its id or release), a
  milestone or an era (the commit of the day it was reached; a pending one as of now, with its target view: its
  trigger, the features and items planned in it), a date or a git ref. The store, the DDR records, the modules
  registry (another store's included), `docs/reference.yaml` and `projects.yaml` are read from git at that commit
  (nothing checked out), and the README gains « Changes since » the wave reached before: decisions taken and
  reversed, features whose status changed, items done, modules added. It is written under
  `BRAIN_HOME/views/reference/<project>/<point>/`, never into the repo. The reference's section 3 now reads the
  repo's `projects.yaml` from the file itself, so a rendering as of a commit reads that commit's.
