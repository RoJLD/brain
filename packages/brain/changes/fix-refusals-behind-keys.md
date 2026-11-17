section: Changes

- Five refusals this release adds are behind optional config.json keys, each off by default, so that without them the
  engine refuses what 0.5.1 refused (docs/guards.md, README):
  - `guards.gestures_session_markers`: the acting gestures (`brain schedule install --apply`, `update`, `uninstall
    --apply`, `queue apply`, `handover root`, `tidy --remote --apply`, the cockpit's actions) refuse themselves while
    any agent marker is set (`brain.gestures.MARKER_NAMES`: `CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT`,
    `BRAIN_AGENT_SESSION` and the variables Claude Code sets for each session), and the command line's gate reads
    them too; off, the acting gestures read `CLAUDECODE` alone, the gate `CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT` and
    `BRAIN_AGENT_SESSION`.
  - `projects.lifecycle_strict`: `brain check` makes an unknown `lifecycle.stage`, `shape` or `profile` an error in
    strict mode (CI); off, a note only.
  - `projects.ids_strict`: `brain project add` takes a name of 2 to 40 characters only, never an alias another project
    or container holds; off, a kebab-case name from a letter of any length (a registered name, a container's id and
    the tree's root still refused, and so is a name another node holds as an alias: the entry would add an error to
    `brain check --all`, which refuses the write).
  - `guards.gestures_wide` now reaches the MCP server: it matches the owner's gestures wide under the key only; off,
    as 0.5.1.
  - `guards.refuse_token_read` now reaches the MCP server: it runs the token check under the key only; off, no check
    (its answers are still redacted).
