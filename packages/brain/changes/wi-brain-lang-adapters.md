section: Added

- Language adapters (`wi-brain-lang-adapters`, [docs/standards.md](docs/standards.md), « Language adapters »): a repo
  declares the reports its own tools write in a new optional `projects.yaml` key, `repos[].tools` (`{lint|typecheck|
  test|coverage|format: {report, format, tool}}`; formats SARIF, JUnit XML, Cobertura, lcov, coverage.py's JSON,
  istanbul's summary); `repos[].lang` does not change. The engine reads the reports and runs no tool. `brain audit`
  measures a new check, `lang.report` (P2, ruleset 8), for a repo that declares `tools:` only: a report missing or
  unreadable, failed tests, lint, type or format findings, coverage under the floor. `brain standards check` counts a
  standard whose `adapter` slot a repo declares as covered on that repo's language. A repo without `tools:` is read
  as before: nothing is newly refused. An older engine notes `tools` as an unknown repo key (refused in CI's strict
  mode), so the key lands in a registry once its CI runs this engine.
