section: Added

- `brain render --target cursor --home` plans the user-level `~/.cursor/mcp.json` for the machine-wide MCP servers
  (those of the packs without `projects`, such as the Brain's own server) with each entry it adds or changes, and
  `--home --write` merges it: its `mcpServers` entries only, every other server and key kept with the file's format,
  written atomically, a file it cannot read refused and never overwritten, a second run a no-op; `--home --check`
  exits 1 while it is not current. `--write` alone still never writes the home folder, and the plan of `brain render
  --target cursor` names the home file; the `--json` rows gain `entries` and the answer `home`. The setup wizard's
  Cursor step shows this command (`wi-brain-render-user-mcp`).
