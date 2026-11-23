# The automation catalogue

Every recurring gesture of the owner, the ones a session runs as well as the commands only the owner runs, declared
once in the engine: `brain.gestures.CATALOGUE` (`wi-brain-automation-catalogue`, slice S1 of
`spec-brain-automation-levels`). `brain automation list` prints it (`--json`: the same data), read only, at zero token.

Each gesture has:

- **an id**, the stable key `config.json`'s `automation` section will set a level by (`wi-brain-automation-config`).
  An id is never renamed or reused: one that leaves the catalogue moves to `brain.gestures.RETIRED`. The label beside
  it may change;
- **a ceiling**: the highest level the engine allows it, whatever the config says. The levels, in order: `manual`
  (the owner types the commands), `ask` (the gesture is prepared and one confirmation runs it) and `auto` (it runs when
  its conditions hold, and is reported after);
- **a default**: its level today. A new engine never raises a level by itself: the defaults are what the engine
  already did when the catalogue was written;
- **its conditions**: what must hold at any level. A level changes who confirms, never the conditions: an archive at
  `auto` still needs the PRs merged and the worktree clean, a clone pull stays fast-forward only;
- **where it runs**: `session` (an agent's session, under the conditions above), `terminal` (the owner's terminal),
  `elevated` (their elevated terminal), `harness` (Claude Code's own confirmation: the Brain cannot raise it);
- **its floor category**, for a gesture of the floor (AUTO-1, below), else none;
- **its commands**: the owner's gestures of `brain.gestures.GESTURES` it covers (each one is in exactly one entry), or
  the commands that run it.

## The floor (AUTO-1)

A floor gesture has the ceiling `manual` and is shown locked: no config lifts it. The floor is the owner's
never-grantable categories (`brain.permissions.NEVER`: keys, money, arming, visibility, accounts, scheduled, legal,
security-settings, which holds Remote Control outside a hand-over and the permission mode), what needs their elevated
terminal (`elevated`), the rules' text (`rules`: a session proposes, the owner merges) and raising a level itself
(`raise`: the owner's merge of `config.json` is the raise; lowering a level is anyone's).

A level reads `manual` (`brain.gestures.effective`, fail closed) when the gesture is unknown, when the level is not one
of the three (unknown, or unreadable), when it is above the gesture's ceiling, and for any gesture of the floor.

## The contract

The catalogue is version 1 (`brain.gestures.CATALOGUE_V`, the `v` of `--json`). Within it a gesture may be added; an
id is never renamed, never reused, and leaves only to `RETIRED`. `tests/test_gestures.py` pins the ids 0.7.0
publishes. The automation config (S2, `wi-brain-automation-config`) is to ignore an id this engine does not know,
with a warning, so that an older engine reads a newer config; an unknown level reads `manual` (`effective`, now).

No guard reads the catalogue yet: the `automation` section of `config.json` (S2), the guards that enforce a level (S3),
the Settings page (S4) and the ask answered from the queue (S5) are their own items, which read these ids.

## The gestures

The Commands column is each gesture's `commands`, the engine's commands that run it; a gesture the app runs (an
archive, Remote Control, a merge, a workflow) or the owner does outside the engine has none. Its conditions are in
`brain automation list`. No guard sees an archive call itself, only the Remote Control off before it (the guard's
archive case, `wi-brain-guard-rc-archive`).

| Id | Runs | Ceiling | Default | Floor | Commands |
|---|---|---|---|---|---|
| `engine-clone-pull` | session | auto | auto | | `brain refresh` (and `brain release apply`, after an install) |
| `session-archive` | session | auto | ask | | |
| `handover-remote-control` | session | auto | ask | | |
| `merge-go` | harness | ask | ask | | |
| `workflow-launch` | harness | ask | ask | | |
| `release-tag` | terminal | ask | ask | | `brain release tag` |
| `release-apply` | terminal | ask | ask | | `brain release apply` |
| `installer-apply` | terminal | ask | manual | | `install.ps1 -Apply` |
| `engine-update` | terminal | ask | ask | | `brain update` |
| `usage-allow` | terminal | ask | manual | | `brain usage allow` |
| `queue-apply` | terminal | ask | ask | | `brain queue apply` |
| `uninstall` | terminal | manual | manual | | `brain uninstall --apply` |
| `handover-root` | terminal | manual | manual | security-settings | `brain handover root` |
| `remote-control` | harness | manual | manual | security-settings | |
| `permission-mode` | harness | manual | manual | security-settings | |
| `schedule-install` | terminal | manual | manual | scheduled | `brain schedule install --apply` |
| `otel-headers` | harness | manual | manual | keys | `brain ipc otel-headers` |
| `vault-open` | terminal | manual | manual | keys | `brain vault open` |
| `vault-drill` | terminal | manual | manual | keys | `brain vault drill` |
| `vault-device-init` | terminal | manual | manual | keys | `brain vault device init` |
| `vault-device-forget-previous` | terminal | manual | manual | keys | `brain vault device forget-previous` |
| `vault-reseal` | terminal | manual | manual | keys | `brain vault reseal --apply` |
| `elevated` | elevated | manual | manual | elevated | `brain floor lock --apply`, `brain floor unlock --apply` |
| `rules-text` | terminal | manual | manual | rules | |
| `automation-raise` | terminal | manual | manual | raise | |
| `money` | terminal | manual | manual | money | |
| `arming` | terminal | manual | manual | arming | |
| `visibility` | terminal | manual | manual | visibility | |
| `accounts` | terminal | manual | manual | accounts | |
| `legal` | terminal | manual | manual | legal | |
