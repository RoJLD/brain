section: Added

- The guards in the MCP server (`wi-brain-mcp-guards`, `brain.mcpguards`): every tool call of `brain mcp serve` is
  judged before it runs, since other clients run no Claude Code hook. A write tool must declare its effect (a
  `brain` command, a file written) or it is refused; the owner's own `brain` gestures (answering a decision, a
  schedule installed, the machine's token or vault keys made, the engine updated, stacks started, `--arm`) are refused
  whatever the tool; a write's arguments pass the secret scan; then the engine's guards judge the effect, strictly (a
  check that cannot judge refuses, and `BRAIN_GUARD_ALLOW` lifts nothing there). Refusals go to the guards ledger as
  `mcp:<tool>`. `brain.guards.refusals` takes `strict=True` for it; the hooks stay fail-open (docs/mcp.md, « The
  guards »).
