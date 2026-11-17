section: Added

- Project ids, the doctrine (`brain.projectids`): a project's key in `projects.yaml` is its id, frozen at birth; new
  keys `aliases` (the names it had: `--project` and a scope reference resolve one to the id, with a notice on stderr),
  `label` (a short display name) and `status` (`active`, or `merged`, `split`, `became-process`, `archived`: a
  tombstone, the entry of a project that ended, which no command loads and whose id and aliases are never reused),
  documented by `brain projects --keys`; `brain projects` shows them and lists the tombstones. `brain check --all`
  refuses an alias that is another node's id or alias (projects and the containers of `scopes.yaml`, which take
  `aliases` too, are one namespace), and a tombstone that still holds a live key; it warns, never fails, on an id
  that is not kebab-case (frozen as it is), and when a project's repo has no `name:` while its graph's ids name a repo
  no registered one answers to (a clone in another folder). `brain project add` never mints a name in use and takes 2
  to 40 characters. A private project's aliases and label, and a tombstone's names, join the derived deny terms and
  those of `public.deny_from_tree`. A test holds that no engine code reads a project from a node id. A tombstone needs
  0.6.0 on every machine (`docs/formats.md`).
