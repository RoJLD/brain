# The automation catalogue

Every recurring gesture of the owner, the ones a session runs as well as the commands only the owner runs, declared
once in the engine: `brain.gestures.CATALOGUE` (`wi-brain-automation-catalogue`, slice S1 of
`spec-brain-automation-levels`). `brain automation list` prints it (`--json`: the same data), read only, at zero token.

Each gesture has:

- **an id**, the stable key `config.json`'s `automation` section sets a level by (below).
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
publishes. The automation section (below) ignores an id this engine does not know, with a note, so that an older
engine reads a newer config; an unknown level reads `manual`.

The guards read a level (S3, below: « Enforcement »); the Settings page (S4) and the ask answered from the queue (S5)
are their own items, which read these ids and `brain.automation`.

## The levels: config.json's automation section

A gesture's level (`brain.automation`, `wi-brain-automation-config`, slice S2) is resolved in three layers, in order:

1. **the engine's default**, the gesture's `default` (its level today). A gesture no layer names keeps it: a new
   engine never raises a level by itself;
2. **config.json's `automation` section**, version 1:

   ```json
   "automation": {
     "v": 1,
     "levels": {
       "session-archive": "auto",
       "release-apply": "ask",
       "usage-allow": "ask"
     }
   }
   ```

   Raising a level is the owner's (the floor gesture `automation-raise`): config.json changes by a pull request, and
   the owner's merge is the raise (AUTO-5). When `$BRAIN_CONFIG` names another file than the config.json found
   without it (a worktree's, say: `brain.config.anchored`), a gesture's level is the lower of the two, so a
   config.json a session wrote never raises one; when no config.json is found without it (no pointer, or a personal
   brain without its config.json), the cap is the engine's default, so the file it names may only lower; lowering
   through it is anyone's;
3. **the machine file** `<BRAIN_HOME>/automation.json`, of the same shape (`{"v": 1, "levels": {...}}`, `v` 1 when
   absent): this machine's own levels, which **may only lower** (a second machine, or a session after an incident,
   which says so). A level it gives above the one it would lower is ignored; one that is not a level lowers to
   `manual`. The engine reads it and never writes it.

Every level then passes `brain.gestures.effective` (the floor, above). Fail closed: a config.json that exists but
cannot be read, one whose `v` this engine does not reach, a `$BRAIN_CONFIG` that names no file, an `automation`
section that is not an object or whose `v` is not 1, and a machine file that cannot be read or whose `v` is not 1,
make **every** gesture read `manual`. An id the catalogue does not hold (a newer engine's, or a retired one) is
ignored, and a key of the section this engine does not know too: both are notes.

`brain automation explain [GESTURE] [--json]` prints the layers it read (each file, or none, its error and notes) and,
for each gesture (or GESTURE alone; exit 1 for an id the catalogue does not hold), its level, the layer that set it
(`default`, `config` or `machine`) and one step per layer. `brain automation list` shows each level with that source.

`brain config --check` and `brain check` (with the rest of config.json) refuse a floor gesture set above `manual`, in
both modes: no config lifts the floor. An id the catalogue does not hold, a level that is not one of the three and a
level above a gesture's ceiling are notes on a machine (they are ignored, or read `manual`: an older engine reading a
newer config) and errors in strict mode (CI, where the engine is the pin). The schema
(`schemas/config.schema.json`, `brain config --keys`) requires `v` and refuses a level that is not a string.

The section is version 1 (`brain.automation.SECTION_V`): within it a gesture id may be added and a ceiling raised by a
later engine (an older one then reads the higher level `manual`); a change of what a level or a key means is a `v` 2,
which an older engine reads as `manual` for every gesture. An engine before 0.7.0 reads the section as an unknown key
of config.json (a note, refused in strict mode) and keeps every default.

## Enforcement: what the guards make of a level

A level changes who confirms a gesture, never its conditions (wi-brain-automation-guard, spec § 3.4;
`brain.automation.enforce`). `brain automation explain` prints, per gesture, the line `enforced:` that says which of
these holds.

**A session's gesture through the app's tools** (`session-archive`: `archive_session`, and the `set_remote_control`
off before an archive; `handover-remote-control`: Remote Control on and off at a coordinators' hand-over). The guard
hook reads the level on every call, with its conditions (docs/guards.md « The archive case », « Remote Control's three
exceptions ») and the session's permission mode (the payload's `permission_mode`):

| Level | Inside its conditions | Outside them |
|---|---|---|
| `manual` | refused (`deny`), logged `denied`: the session records it on its item (`props.external_blocker`) and the owner does it | refused |
| `ask` | the guard asks (`ask`, the card), logged `asked` with its case, whatever the tool's native rule | `archive_session`: the guard asks (`ask`, the card); `set_remote_control`: refused, as before |
| `auto` | allowed (`allow`): no card, in any mode | as at `ask` |

`ask` reads `manual` where the permission mode shows no card for an ask: the guard counts one only in `default`,
`acceptEdits`, `plan` and `auto` (`brain.automation.CARD_MODES`); in `bypassPermissions`, `dontAsk`, a mode this
engine does not know or a payload that gives none, the call is refused (the safe direction).

Inside the conditions at `ask` the guard asks itself rather than leave the call to the native rule, since that rule
need not be the gesture's level: `set_remote_control` is rendered at the higher level of its two gestures (an allow
rule when the archive is at `auto` and the hand-over at `ask`, or the reverse), and a level lowered since the render
(config.json, or the machine file after an incident) leaves the old allow rule in `~/.claude/settings.json` until
`install.ps1 -Apply`. A hook's `ask` shows the card over an allow rule, so each gesture's level holds on each call as
the guard reads it: a lowering to `ask` or `manual` takes effect at once. At the engine's defaults (`ask` for both) a
call inside the conditions gets the card in the modes with one, as the default render's ask rule gives it; an owner's
allow rule of before this item (`wi-brain-coordinator-handover-no-prompt`) no longer lifts it: the owner raises the
level to `auto` instead (config.json, AUTO-5).

The probe behind `CARD_MODES` (2026-11-25, Claude Code 2.1.330, recorded in the personal brain's trials): the
documentation says an `ask` rule prompts in every mode but `dontAsk` (where it is denied), `bypassPermissions`
included; a hook's `ask` prompts in `auto` mode (the classifier does not decide it), and nothing is said of it in
`bypassPermissions`; deny and ask rules are evaluated whatever a hook returns, so an `ask` or `deny` rule wins over the
guard's `allow`. The hook input carries `permission_mode` (a field of every tool hook's common input). A headless run
that would settle the `bypassPermissions` cell needs a logged-in `claude` CLI: until it shows a card there, `ask` stays
`manual` in that mode.

**The native rules** (`brain permissions render --level user`, which `install.ps1 -Apply` writes into
`~/.claude/settings.json`; `brain.automation.native_rules`, `brain.permissions.automation_rules`). Each tool gets the
highest level of the gestures that use it (`set_remote_control`: the hand-over's and the archive's), since an ask or
deny rule wins over the guard's allow, and the guard judges each call apart and always decides (a deny, its own ask or
an allow), so a rule above a gesture's level never lifts its card: `auto` an allow rule, `ask` an ask rule, `manual` a
deny rule; the tool's two other verdicts
are rendered as expired, so that the install takes the old level's rule out (an old allow would lift a new ask; an old
ask or deny would win over a new auto). An allow rule is withheld where no guard sees the tool (`GUARD_REQUIRED`,
docs/guards.md « The archive case »): the tool then gets no rule. `--json` adds `automation`, each tool's level and
verdict. The guard stays the authority: a native rule depends on the mode, the guard does not.

**The engine clone's pull** (`engine-clone-pull`): `brain refresh` and `brain release apply` fast-forward the clone
through one door, `brain.engineclone.refresh`. In an agent's session (`brain.gestures.agent_session`) it pulls at
`auto` only; at `ask` or `manual` it says `not pulled`, with the level and the command, and leaves it to the owner.
The owner's own terminal pulls at every level: the level says what a session does.

**A gesture of the owner's terminal** (`release-tag`, `release-apply`, `engine-update`, `queue-apply`...): refused to a
session at every level, as before (the owner guard, brain.gestures); its level is what the owner's own terminal does
(spec § 3.1). **The harness's** (`merge-go`, `workflow-launch`) are its own confirmations. **The floor** stays refused
at every level.

## The gestures

The Commands column is each gesture's `commands`, the engine's commands that run it; a gesture the app runs (an
archive, Remote Control, a merge, a workflow) or the owner does outside the engine has none. Its conditions are in
`brain automation list`. The guard holds `session-archive`'s and `handover-remote-control`'s conditions
(`brain.guards.archive` and `remote_control`, docs/guards.md « The archive case »), and reads their level inside
them (« Enforcement » above); the engine's default stays `ask`.

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
