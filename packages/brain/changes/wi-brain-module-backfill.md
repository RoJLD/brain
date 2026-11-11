section: Added

- The module map reads the features and the done items too (`wi-brain-module-backfill`): in a store with
  `modules.yaml`, `brain modules` counts how many features and done items carry a `props.module` (the view's new line,
  `--json`'s `features`, `features_unplaced`, `done_items`, `done_unplaced`, `warnings`), and `brain check` warns,
  never fails, about one with no module, `none` without its reason, or a module the registry does not know;
  `brain modules --check` lists them as warnings, its exit code still the open items' only. The public render of
  `FEATURES.md` never shows the Module column (the module ids are the owner's platform's). The technical reference
  reads these modules.
