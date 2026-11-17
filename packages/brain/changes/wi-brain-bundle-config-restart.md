section: Fixes

- `brain bundle apply` recreates a running component whose mounted configuration changed (`wi-brain-bundle-config-restart`):
  each service of the rendered compose file is labelled with the hash of the bundle files it mounts
  (`brain.config-hash`), so `docker compose up -d` recreates the collector on a new `otelcol.yaml` (its
  private-attribute processors took effect only after a down and up); the plan says « recreated: its mounted
  configuration changed ». The first apply after this upgrade recreates each service that mounts a file, once.
  docs/mcp.md gives the owner's purge of what was written before (or the 31 days' wait).
