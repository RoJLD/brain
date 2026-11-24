section: Changes

- `brain audit`'s measure is split into one step each (the feature model, the closure's classes, the test evidence,
  the CodeRefs), and `cmd.documented` into a script's, a module's and a shim's test, every one at complexity 15 or
  under; the inventory is split by concern into `brain.inventory_python` (the text patterns and a Python file's
  facts), `brain.inventory_closure`, `brain.inventory_evidence` and `brain.inventory_stores`, `brain.inventory`
  keeping every public name; `brain audit --json` is byte-identical before and after (`wi-brain-engine-debt`,
  batch 4).
