section: Added

- `brain project new` asks the languages and tools and the data (`wi-brain-project-wizard-tools`, its second slice):
  `--lang py|ts` and `--tool SLOT=TOOL` (each check's slot takes the language's usual tool unless named, `none` for
  none; `brain.langs.TOOLS`) write the brain's own repo's `lang` and `tools:` (each tool's report and format), `--floor
  CLASS` or `--residency` its `classes: {floor}` (a floor the brain's own stores are under, which `brain check`
  refuses, is refused by the plan with the stores it names), `--personal-data` the privacy rows into its standards
  selection's `include` (merged into the template's own); the plan shows the tools with their commands, the reports
  the template's CI does not write, the standards rows required at its stage, those its tools run and those its
  language leaves uncovered, and a re-run shows what the answers change in an existing entry (each slot's tool,
  report and format). The Python defaults for the tests and the coverage are the reports the code templates' CI
  writes (`reports/junit.xml`, `reports/coverage.xml`, cobertura).
