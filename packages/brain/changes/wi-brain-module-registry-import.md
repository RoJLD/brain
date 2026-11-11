section: Added

- The module registry can be kept in another store and imported from the platform's documents
  (`wi-brain-module-registry-import`). `config.json` `modules.store` (optional, default none) names the store of the
  projects registry whose `modules.yaml` a store without its own reads (`<project>:<store>` or a project's name;
  only the stores under `config.json`'s folder): its items keep their module checks, and its view names that
  registry. An imported entry (`source` a list of documents, or `imported` a day) is validated by `brain modules --check` and warned
  of by `brain check`: its document fields, the documents read with their dates, the day of the import, the
  dependencies it declares; a hand entry is checked as before. The view of a registry with imported entries gains
  the generated counts (in the tree, proposed, by brick), the documents read and the divergences the import
  reported; `brain modules --diff [REF]` says what changed since the registry at a git ref (modules added and
  removed, document fields and hand fields changed). The engine never reads the documents: an agent session writes
  the import. A registry with no imported entry, and its view, are unchanged. Turning `modules.store` on is the
  owner's opt-in to the module checks on the stores that then read it: their view is written by the next
  `brain sync` (stale until then, an error of `brain check` under `views.strict`).
