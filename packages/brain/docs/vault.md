# Runbook: data classes and the vault

What a brain may send where, and how what leaves a machine is protected. Two commands:

- `brain classes`: every store of the brain declares a **data class** in `config.json` (`classes.stores`), and the
  class says where the store may go and how. `brain check --all` refuses a tracked file without a class and a
  destination its class forbids; an engine store the brain leaves undeclared takes its suggested class, and is noted.
- `brain vault`: what leaves a machine is **sealed client-side to public keys** (age, gpg as the fallback): a device
  key per machine and an offline recovery key, two recipients at least for every sealed store. Sealing needs no
  secret, so it runs unattended; opening is a human act in the owner's own terminal. A daily canary per recipient
  proves the keys still open what is sealed, and `brain health vault` turns red when it stops.

Three rules hold everywhere:

- no private key in the repo, a hook, a scheduled task's command line or a log: only public recipients enter
  `config.json`; `brain vault recipient add` and `brain check --all` refuse anything private;
- `brain vault open`, `drill` and `device init` refuse to run in an agent session (`CLAUDECODE`,
  `CLAUDE_CODE_ENTRYPOINT` or `BRAIN_AGENT_SESSION` set): a session may seal, run the canary and read the health,
  never decrypt or create a key;
- sealing is not scanning: whoever builds an archive scans it for secrets and leaves out the `resident` class first.

## Data classes

| Class | Where it may go |
|---|---|
| `public` | anywhere, once `brain check --public` passes |
| `private` | the private repo in clear; off the machine otherwise only sealed |
| `confidential` | never in clear in git or with a third party; sealed off the machine |
| `sealed` | never in git; off the machine only sealed client-side |
| `resident` | never leaves the machine, even sealed (a residency clause) |
| `secret` | never in the brain: key values live in a keystore or a password manager |
| `tenant:<id>` | a hosted team's store: its own private repo, sealed to its own recipients only |

`brain classes --matrix` prints how each class may take each exit (`git-public`, `git-private`, `offsite`, `backup`,
`devices`, `third-party`, `cloud-model`, `local-model`): `clear`, `sealed`, `opt-in` (only when the store names the
exit in its `to`) or `never`.

```
brain classes                 every store: its class, tracked files, machine paths, exits; the engine stores at their
                              default class; the sources read through a closed list of keys; notes, waivers, errors
brain classes --check         exit 1 on a store without a class or a destination its class forbids (brain check --all too)
brain classes PATH...         the store and class of each path (a repo path, $BRAIN_HOME/..., ~/...)
brain classes --suggest       a starting classes block for config.json, to edit; a brain that declares classes gets
                              only the engine stores it misses
```

The check reads reality:

- every tracked file has a class: the first store whose glob matches it, in the file's order (specific stores first,
  a catch-all `**` last);
- every store the engine writes outside the repo has a class (below): one the brain does not declare takes its
  suggested class, and the check notes it without failing until it is declared; a name at the top of `$BRAIN_HOME`
  that no store covers (a newer engine's store, one made by hand) is noted the same way, `sealed` by default;
- tracked files whose class does not allow the repo's remote in clear are refused (`git-private`, or `git-public` when
  the remote is one of `public.repos`); a tracked `*.age` or `*.gpg` file is sealed, and an empty `.gitkeep` holds no
  data;
- an exit in `to` that the class says `never` for is refused;
- a class is at least the strictest `classes: {floor: ...}` along its project's scope chain (`scopes.yaml`, read when
  it exists).

A known gap is written as a waiver, `waive: {exit: reason}` on a store (a reason of 15 characters or more): it is
printed by every check instead of failing. `brain init` writes a starting block; `brain classes --suggest` prints one.

### The engine's own stores

Every name the engine writes under `$BRAIN_HOME` is one of its stores (`brain.classes.ENGINE_STORES`), with a
suggested data class and a format class, which says how it is read and written (`truth-local`: what nothing else
keeps, backed up before a write-back; `log`: append-only; `derived`: rebuilt, never migrated; `install`: rebuilt by
the installer; `external`: another tool's, read only; see [formats.md](formats.md)). A test of the engine fails on a
name its code writes there that the list does not hold, so a new store comes with its class in the same change.

| Store | Path | Class | Format | Holds |
|---|---|---|---|---|
| `ledger` | `$BRAIN_HOME/ledger` | sealed | log | the token ledger's events, the session records' lines, the engine's timings and errors |
| `sessions` | `$BRAIN_HOME/sessions` | sealed | truth-local | the session records, the children's reports |
| `resume` | `$BRAIN_HOME/resume` | sealed | derived | the resume packs |
| `digest` | `$BRAIN_HOME/digest` | sealed | derived | the digests |
| `vault` | `$BRAIN_HOME/vault` | sealed | truth-local | the sealed copies, the canaries, the device's public facts |
| `transcripts` | `~/.claude/projects` | sealed | external | the agent's transcripts |
| `usage` | `$BRAIN_HOME/usage` | sealed | log | the token ledger's views, `quota.json`, the session starts, the audits |
| `budget` | `$BRAIN_HOME/budget` | sealed | truth-local | the context budget watch's marks |
| `forecast` | `$BRAIN_HOME/forecast` | sealed | derived | the forecasts |
| `announce` | `$BRAIN_HOME/announce` | sealed | truth-local | the decisions already announced to a session |
| `handover` | `$BRAIN_HOME/handover` | sealed | truth-local | the hand-over notes and their mirror |
| `inbox` | `$BRAIN_HOME/inbox` | sealed | log | the owner's messages to sessions |
| `features` | `$BRAIN_HOME/features` | sealed | derived | the feature stores' indexes |
| `cache` | `$BRAIN_HOME/cache` | sealed | derived | the app metadata's picked keys, the governor's and the guards' caches |
| `memory-sync` | `$BRAIN_HOME/memory-sync` | sealed | truth-local | the memory export's state, alerts and backups |
| `schedules` | `$BRAIN_HOME/schedules` | sealed | truth-local | the scheduled tasks this machine installed |
| `alerts` | `$BRAIN_HOME/alerts` | sealed | truth-local | the alerts already raised |
| `machine.json` | `$BRAIN_HOME/machine.json` | sealed | truth-local | this machine's first sight: name, OS install anchor (a sha256), local id |
| `facts.json` | `$BRAIN_HOME/facts.json` | sealed | derived | the machine's last facts with their source |
| `locks` | `$BRAIN_HOME/locks` | sealed | derived | the single-instance locks (the cockpit, the alerts pass) and their holder's pid |
| `probes` | `$BRAIN_HOME/probes` | sealed | derived | the dependency probes' last run |
| `notify` | `$BRAIN_HOME/notify` | sealed | truth-local | the notifications' state, the quiet hours |
| `secrets` | `$BRAIN_HOME/secrets` | **secret** | truth-local | the stack bundles' secret files |
| `ipc` | `$BRAIN_HOME/ipc` | **secret** | truth-local | the machine's token for the Brain's local services (`brain ipc token`) |
| `collector` | `$BRAIN_HOME/stacks/sovereign/data/otel-collector` | sealed | log | the telemetry collector's data |
| `stacks` | `$BRAIN_HOME/stacks` | sealed | truth-local | the rendered stack bundles and their data |
| `telemetry` | `$BRAIN_HOME/telemetry` | sealed | truth-local | the telemetry consent record and the report outbox |
| `code-index` | `$BRAIN_HOME/code-index` | sealed | derived | the code index's bundles |
| `code-index-record` | `$BRAIN_HOME/code-index.json` | sealed | truth-local | the repos indexed |
| `code-map` | `$BRAIN_HOME/code-map` | sealed | derived | the code maps |
| `public-check` | `$BRAIN_HOME/public-check` | sealed | derived | the public check's stamps |
| `reviews` | `$BRAIN_HOME/reviews` | sealed | truth-local | the reviews' findings and stamps |
| `merge-ready` | `$BRAIN_HOME/merge-ready` | sealed | derived | the merge gate's stamps, per repo and head (`brain merge-ready`) |
| `backup` | `$BRAIN_HOME/backup` | sealed | truth-local | copies taken before a write-back: a work tree's settings files (`<project>-<key>/<folder>`, the last 10 each) |
| `spool` | `$BRAIN_HOME/spool` | sealed | truth-local | the sealed copies waiting to leave the machine and their index (`brain spool push`) |
| `session-archive` | `$BRAIN_HOME/session-archive` | sealed | truth-local | the session archive's index by session record, and its staged copies while a run seals them (`brain session-archive`) |
| `cockpit` | `$BRAIN_HOME/tui.json` | sealed | truth-local | the cockpit's settings |
| `update-check` | `$BRAIN_HOME/update.json` | sealed | derived | the last engine tags read |
| `net` | `$BRAIN_HOME/net` | sealed | truth-local | the external services' circuit breakers (`brain.net`) |
| `outbox` | `$BRAIN_HOME/outbox` | sealed | truth-local | the outbound calls that failed, waiting to be sent again (`brain.outbox`) |
| `personal` | `$BRAIN_HOME/personal.json` | sealed | truth-local | the pointer to the personal brain |
| `profile` | `$BRAIN_HOME/profile.json` | sealed | truth-local | the machine's frozen tier profile |
| `venv`, `venvs`, `bin`, `engine-clones` | `$BRAIN_HOME/venv`, `venvs`, `bin`, `engine` | sealed | install | the command's environment (once `brain update` ran blue-green: a link to the active slot of `venvs`, one venv per engine version), its launcher, the tags' clones |

An undeclared store's default is never looser than `sealed` (`secret` for the secrets): no store is ever without a
class. A store meant to be looser (the telemetry outbox, meant to be shared) is declared so by the owner. To declare
the missing ones, paste what `brain classes --suggest` prints into `classes.stores` (a name the brain already uses
for another store gets `home-`).

### What the engine reads and never writes

Some data the engine reads belongs to another tool (`brain.classes.SOURCES`). It is never written, and a file of it
is read through a closed list of keys:

- **the desktop app's session metadata** (`$LOCALAPPDATA/Claude-Data/*/claude-code-sessions`, read by the session
  tree, the governor, `brain tidy` and the SessionStart capture): `sessionId`, `cliSessionId`, `title`, `createdAt`,
  `lastActivityAt`, `isArchived`, `completedTurns`, `model`, `effort`, `branch`, `lineageDetached`, `prs` (counted),
  `cwd`, and in `spawnedFrom` its `sessionId`, `taskId`, `name` and `sideSession`. The keys that hold texts
  (`lastTurnReport`, `pendingSystemReminder`, `promptAppendSnapshot`, `remoteMcpServersConfig`, `spawnSeed`, and an
  e-mail address in most files) are never read and never reach a store: a test of the engine holds every reader to
  the list and scans what they write;
- **the app's worktrees** (`git-worktrees.json`): each worktree's `path` and `leasedBy`;
- **the notes a family of sessions shares** (`side-session-notes`): read whole by `brain resume` and the briefs.

## The vault: the owner's steps, once per machine

Disk encryption comes first (BitLocker, FileVault, LUKS; `brain doctor` reports it): a sealed remote next to a disk
in clear is a false sense of safety.

1. **The tool.** age: `winget install FiloSottile.age` (Windows; open a new terminal afterwards), `brew install age`
   (macOS), `apt install age` (Debian, Ubuntu). Without it the vault falls back to gpg (Git for Windows ships one).
   `brain vault status` says which adapters it finds.
2. **This machine's device key**, in your own terminal, not in an agent session:
   ```
   brain vault device init
   ```
   The key goes straight into the OS keystore (Windows: Credential Manager, entry `brain-vault/device`, kept on this
   machine only; macOS: the login keychain; Linux: the Secret Service; a container: a file the owner mounts,
   `BRAIN_VAULT_IDENTITY_FILE`). The command prints only the public `age1...` recipient and the line that declares
   it; `$BRAIN_HOME/vault/device.json` keeps the public facts.
3. **The recovery key**, created by you alone, offline if you can (no network, no sync, no terminal transcript):
   ```
   age-keygen
   ```
   It prints a date, `# public key: age1...` and `AGE-SECRET-KEY-1...`. Copy the `AGE-SECRET-KEY-1...` line on paper,
   twice, kept in two places; note the `age1...` public key; then clear the screen and close the terminal. Never paste
   that line anywhere else, and never into an agent's chat.
4. **Declare both** (public keys only), then commit `config.json` to your private repo:
   ```
   brain vault recipient add <machine> --kind device --age age1... --host <machine> --write
   brain vault recipient add recovery --kind recovery --age age1... --write
   ```
   Without `--write` it prints the entry it would add. A gpg key is declared with `--gpg FILE` (an armored public key,
   copied into `vault/keys/`). Declare the two together: with one recipient, `brain health vault` fails.
5. **The first canary**, then the health:
   ```
   brain vault canary
   brain health vault
   ```
6. **The daily canary**: a scheduled task, your decision. Without it `brain health vault` fails after 26 hours
   (`canary_hours`). It runs as you, in your session (the keystore opens the device key there), with no key on its
   command line.

   Windows (PowerShell, not as administrator):
   ```powershell
   Register-ScheduledTask -TaskPath '\Brain\' -TaskName 'vault-canary-daily' -Description 'brain vault canary' -Action (New-ScheduledTaskAction -Execute (Get-Command brain).Source -Argument 'vault canary') -Trigger (New-ScheduledTaskTrigger -Daily -At 07:30) -Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10))
   ```
   Check it with `Get-ScheduledTaskInfo -TaskPath '\Brain\' -TaskName 'vault-canary-daily'`.

   macOS: a LaunchAgent, `~/Library/LaunchAgents/brain.vault-canary.plist`, with the absolute path `which brain`
   prints:
   ```xml
   <?xml version="1.0" encoding="UTF-8"?>
   <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
   <plist version="1.0"><dict>
     <key>Label</key><string>brain.vault-canary</string>
     <key>ProgramArguments</key><array><string>/path/to/brain</string><string>vault</string><string>canary</string></array>
     <key>StartCalendarInterval</key><dict><key>Hour</key><integer>7</integer><key>Minute</key><integer>30</integer></dict>
   </dict></plist>
   ```
   then `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/brain.vault-canary.plist`.

   Linux: a user timer, `~/.config/systemd/user/brain-vault-canary.service`:
   ```ini
   [Service]
   Type=oneshot
   ExecStart=%h/.brain/bin/brain vault canary
   ```
   and `~/.config/systemd/user/brain-vault-canary.timer`:
   ```ini
   [Timer]
   OnCalendar=*-*-* 07:30
   Persistent=true

   [Install]
   WantedBy=timers.target
   ```
   then `systemctl --user enable --now brain-vault-canary.timer`.

   Each other machine that runs the brain gets its own task once it has its device key.

## Every day: the canary and the health

`brain vault canary` seals a fresh random nonce to each recipient alone (`$BRAIN_HOME/vault/canary/<name>.age`), keeps
its digest in `state.json`, then opens the one this machine's device key can open and compares the digests.

| `brain health vault` says | Meaning | Exit |
|---|---|---|
| `vault OFF (config.json declares no vault ...)` | nothing is sealed yet | 0 |
| `vault OFF on this machine (neither age nor gpg found ...)` | a Lite machine: available, off | 0 |
| `vault OK (N recipient(s), device X (age, wincred), last sealed: ...)` | every canary sealed within 26 h, this machine's opened | 0 |
| `vault FAIL (...): canary X: never sealed / sealed N h ago / error` | the proof stopped: run the canary, read its error | 1 |
| `vault FAIL (...): the device key X is missing from the keystore` | the keystore lost it: see "A lost or exposed key" | 1 |
| `vault FAIL (...): 1 recipient(s): a sealed store needs 2 at least` | declare the recovery key | 1 |
| `vault warning: no device key on this machine` | step 2 not done here | 0 |
| `vault warning: recovery: never drilled` | the yearly drill is due | 0 |

`brain vault status` shows the adapters, the keystore, this machine's device, every recipient with its fingerprint and
its last proof, the last seal of each store, and **next (yours)**: the steps above still to do, with their commands.

## Sealing and opening

```text
brain vault seal STORE [PATH...] [--out FILE] [--adapter age|gpg]
brain vault open FILE [--out DIR] [--identity FILE|-]
```

- `seal` packs the store's content (its machine folders and tracked files, or the paths given) into a tar.gz with no
  user name in it, seals it to the store's recipients and writes `$BRAIN_HOME/vault/sealed/<store>/` with a manifest
  beside it (class, recipients and their fingerprints, counts, sha256). It refuses a `resident` or `secret` store, an
  unknown store and fewer than two recipients.
- A store is sealed to the root's recipients (those no scope node and no tenant names, filtered by their optional
  `classes`) plus those the nodes of its scope chain add (`vault: {recipients: [...]}` in `scopes.yaml`); a
  `tenant:<id>` store to its tenant's only (`vault.tenants`).
- `open` (yours only) opens with this machine's device key by default; `--identity -` asks for the recovery key,
  hidden as you paste it (age: checked for its shape, handed to age on its stdin, never written; gpg reads its key
  block itself); `--identity FILE` a key file. An archive is extracted into `--out`, refusing any path that would land
  outside.

## The spool: what leaves the machine, sealed, waiting for its remote

```text
brain spool push [STORE...] [--dry-run] [--json]
brain spool status [--json]
brain spool verify
brain health spool
```

The stores that leave the machine (the ledger, the usage, the session records; the transcripts later, with the
session archive) leave only sealed. Until a data remote exists (a NAS, object storage, a private dataset host), they
wait in a local spool, `$BRAIN_HOME/spool`, sealed and checked by hash. **It runs by hand**: no scheduled task runs it
until you add one.

- `push` takes the spool's set (`spool.stores` in config.json, else `ledger`, `usage` and `sessions`; each declared in
  `classes.stores`). A store whose content (its files' names, sizes and times) and recipients have not changed since
  its last push is skipped. Each other one is scanned for a secret's shape (a key's prefix, a token's form:
  `brain.secretscan.SHAPED`; the password heuristics are left out, since the engine's own JSON keys would trip them).
  A hit stops that store and names the file and line, never the value; so does a file that cannot be read. A binary
  file (a NUL byte in its first 8 KB: sqlite, an archive) is sealed unscanned. Then the store is sealed through
  `brain vault seal` to its recipients into `$BRAIN_HOME/spool/<store>/`, its manifest beside it, its sha256 and its
  recipients' fingerprints recorded in `spool.json`. A store whose class never leaves the machine (`resident`,
  `secret`: `brain.classes.decide(cfg, store, "offsite")`), an undeclared one and a file locked while it is packed
  fail that store; the other stores go on.
- Then it prunes (below), and with `spool.remote` set (a folder: a mounted share, a synced drive; a relative path from
  the brain's root) it copies each file that waits to `<remote>/<store>/`, with brain.vault's manifest beside it (in
  clear, as in `vault/sealed/`: the recipients' names and fingerprints, the counts, the sha256). The file's sha256 is
  checked against the index before the copy and on the copy; only then is it marked sent. A remote that is not
  reachable leaves them waiting. Without a remote, they stay in the spool.
- When the recipients change (a removed or rotated key), the next push seals each store again, since its recipients
  differ; a file that waits sealed to the old set is never sent, and a superseded snapshot of it is pruned.
  `brain vault reseal` does not rewrite the spool.
- Pruning keeps, per store, the newest 3 snapshots (`spool.keep`), sent or not, since a newer one holds the store. A
  file put with its own paths (the session archive's) is pruned only once sent, past the newest 3 of them.
- `push` exits 1 when a store or a copy failed (an unreachable remote counts), 2 when the index cannot be written (a
  newer brain's: nothing sealed; `--dry-run` only reads it and prints the plan). `verify` exits 1 on a missing or
  changed file.
- `brain health spool` gives the age of the last push without an error (`brain spool status` shows the last push,
  failed or not) and what waits. It warns when no push succeeded for 7 days (`spool.max_age_days`), or none ever did,
  or the last one had an error, and fails only when a waiting file is missing or no longer matches its sha256. Named,
  it says OFF while nothing was ever pushed and config.json has no `spool` block; with `--all` it is silent then.

For a caller (the session archive), `brain.spool.put(cfg, store, items)` seals the given paths into the spool as one
entry of kind `items`, after the same scan and refusals. It refuses an empty list, two items of the same file name (one
would overwrite the other when opened) and an item inside a store whose class never leaves the machine.

## The session archive: transcripts, scanned and filtered, then sealed

```text
brain session-archive run [--dry-run] [--max N] [--json]
brain session-archive status [--json]
brain health session-archive
```

The agents' transcripts (Claude Code's first: each session's `.jsonl` and its subagents'; other agents later, through
their adapters) are the episodic memory of every machine. They hold prompts, tool inputs and outputs, and sometimes a
secret, so they leave the machine only scanned, filtered and sealed, and never go to a git repo.

**Opt-in.** Nothing runs until `config.json` says so; no scheduled task is created (add one yourself when you want the
archive kept up without you):

```json
"session_archive": {"enabled": true, "resident": {"vendor-rows": "\\bvendor-feed\\b"}},
"classes": {"stores": {"session-archive": {"class": "sealed", "paths": ["$BRAIN_HOME/session-archive"],
                                           "to": ["offsite", "backup"]}, "...": "..."}}
```

A run:

1. takes each transcript quiet for 2 hours (`session_archive.quiet_minutes`; a live session waits for a later run)
   whose size or time changed since it was archived, 200 at most per run (`max_files`, `--max`; the rest wait);
2. **the residency filter**: a line a pattern of `session_archive.resident` (`{name: regex}`, matched against the line
   as it is written, JSON escapes included) matches is a row a data source forbids from leaving the machine: it is
   replaced by a stub (`{"type": "brain-archive-dropped", "why": "residency"}`) and counted under the filter's name.
   The engine names no source: the patterns are yours. A pattern that does not compile refuses the run;
3. **the secret scan**, fail-closed: the engine's patterns (`brain.secretscan`) drop the matching lines of each string
   value, and a line still holding a key's shape becomes a stub (`"why": "secret"`); then **gitleaks** reads the
   staged copies (`gitleaks dir`, else `detect --no-git` for an older one) with its default rules, `gitleaks:allow`
   marks ignored and no `GITLEAKS_CONFIG` or `.gitleaksignore` read: each line it reports becomes a stub, and a
   second pass must find nothing. **gitleaks absent** (one line says so), failing, or still finding something:
   **nothing is archived** (exit 2). A transcript is never archived unscanned;
4. **sealed**: the staged copies go into the spool as one entry (`brain.spool.put`, store `session-archive`), which
   scans them once more and seals them with `brain vault` to the store's recipients (two at least); `brain spool push`
   sends them to `spool.remote`. The staged copies in clear (`$BRAIN_HOME/session-archive/staging-*`) are
   deleted when the run ends, whatever its outcome; a run killed mid-way, or a file locked by an indexer or an
   antivirus, can leave them: the next run removes them first, and `status` and `brain health session-archive` warn
   while they are there. The store must be declared in
   `classes.stores` (sealed), or the spool refuses it;
5. **the index**, `$BRAIN_HOME/session-archive/index.json`: by session record (`sr-<start date>-<first 8 characters of
   the session id>`, the SR's id), each session's id, project folder, machine of origin, its place in the tree when
   `brain sessions` knows it (`host_id`, `parent`, `role`), and per file its source, fingerprint, lines, what the
   filter and the scans dropped, and the sealed file in the spool. A transcript that grows again (a resumed session) is
   archived again whole at the next run.

`--dry-run` lists what would be archived and what the filter and the scans would drop (gitleaks still runs, over copies
in a temporary folder deleted after); it seals nothing and writes no index. The desktop app's session metadata (its
turn reports, reminders, prompt snapshots, connectors) is never read here. `brain health session-archive` warns when
gitleaks is missing or no run sealed anything for 7 days (`session_archive.max_age_days`); it says OFF while the
archive is not enabled, and with `--all` it is silent then.

## Once a year: the drill

```
brain vault drill recovery
```

Type or paste the secret `AGE-SECRET-KEY-1...` line from paper at the prompt (not the public `age1...` key), then
Enter. Nothing shows as you paste: the key is hidden, like a password, so it stays out of the screen and the
terminal's scrollback.
The recovery canary must open and match its digest; `state.json` records the date and the health warning goes away.

## Changing the recipients: rotation and re-sealing

A sealed file opens with the keys it was sealed to, and with no other. When the recipients change, the sealed files
this machine keeps (`$BRAIN_HOME/vault/sealed/`) are sealed again to the new set:

```
brain vault reseal            # the plan: each file whose recipients are not its store's current ones
brain vault reseal --apply    # open each with this machine's device key, seal it again, replace the old copy
```

`brain vault status` lists those files ("to re-seal"), and `brain health vault` fails while a removed or replaced key
still opens one. It only warns when a new recipient cannot open one yet. A copy already sent elsewhere (a remote, a
NAS, a backup) stays readable by the keys it was sealed to: seal it again where it lives, or delete it there.

Each store keeps its floors on its own: two distinct keys at least, and a recovery key for the owner's stores (a
tenant's or a scope's key does not count for them). `recipient remove` refuses what would break them, and `reseal`
leaves a file as it is rather than seal it under them. A key keeps its proofs, not its name: once a recipient gets a
new key (`--replace`), its canary and drill start again, and `reseal` keeps the old recovery key on a file until a
recovery key of its store has been drilled.

**Rotating this machine's key** (a suspect key, a yearly habit), in your own terminal:

1. `brain vault device init --rotate`: a new key goes into the keystore. The previous one is kept beside it
   (`brain-vault/device-previous`) and still opens what was sealed to it. The command prints the new public key and
   its line: `brain vault recipient add <name> --kind device --age age1... --host <name> --replace --write`.
2. Declare it in a PR: `--replace` gives the name its new key (its kind, classes and why stay). Pull it on this
   machine. The name stays through a rotation: a new name would leave the old one declared, a key nobody holds.
3. `brain vault reseal --apply` (the previous key opens, the new set seals), then `brain vault canary`.
4. `brain vault device forget-previous`: it deletes the previous key. It refuses while config.json still declares the
   old key (under any name) or a sealed file waits on a re-seal. A rotation that fails midway puts the keystore back
   as it was.

## A lost or exposed key

- **A lost machine**: take its recipient out (`brain vault recipient remove <name>`, the plan, then `--write` in a PR),
  then `brain vault reseal --apply` on each machine that keeps sealed files. Open its sealed copies elsewhere with the
  recovery key (`brain vault open FILE --identity -`). What was already sealed to the lost machine stays readable by
  its key: the lost machine's disk encryption is what protects it.
- **An exposed device key**: rotate it (above). On a machine that is gone, remove its recipient and delete its keystore
  entry (Windows: `cmdkey /delete:brain-vault/device`).
- **The recovery key exposed or lost**: create a new one (step 3) and declare it (`recipient add recovery --kind
  recovery --age age1... --replace --write`, a PR), then `brain vault canary` and drill it (`brain vault drill
  recovery`, with the new paper). Only then does `brain vault reseal --apply` move the copies off the old key: it
  refuses while the new one is not drilled, so a mistyped paper key never becomes the only way back.
- **A revoked heir, a member leaving a tenant**: `brain vault recipient remove <name>` (it refuses while
  `vault.tenants` or a scope still names them: take them out there first), then `brain vault reseal --apply`.
- **A private key pasted into `config.json`** by mistake: `brain check --all` refuses it; remove it and treat the key
  as exposed.

## gpg, the fallback

The same commands with gpg: the device key is generated in a fresh temporary home, exported into the keystore
(base64), and imported into another temporary home for each opening, the home and its agent removed after. Recipients
are armored public key files (`--recipient-file`), so no keyring is touched. Git for Windows' gpg (MSYS) takes its home
as `/c/...` and needs a short path for its agent's sockets: the vault handles both.

## Where things are

| Path | What |
|---|---|
| `config.json` `classes` | the stores, their class, paths, exits and waivers |
| `config.json` `vault` | the recipients (public keys), `min_recipients` (2), `canary_hours` (26), `adapter`, `tenants` |
| `$BRAIN_HOME/vault/device.json` | this machine's device key: name, adapter, public key, keystore, date; `v` 1 through `brain.stateio` (a backup in `device.json.bak`; a newer brain's file stops `device init` and `forget-previous` before the keystore is touched) |
| `$BRAIN_HOME/vault/state.json` | the canaries (sealed, opened, digest, error), the drills, the last seal of each store; `v` 1, read and written through `brain.stateio` (a backup in `state.json.bak` before each write; an unreadable file set aside, never reset; a newer brain's state read-only: [formats.md](formats.md)) |
| `$BRAIN_HOME/vault/canary/` | one sealed nonce per recipient |
| `$BRAIN_HOME/vault/sealed/<store>/` | the sealed copies and their manifests (`resealed` once sealed again) |
| `config.json` `spool` | optional: `stores` (the spool's set), `remote` (a folder), `keep` (3), `max_age_days` (7) |
| `$BRAIN_HOME/spool/spool.json` | the spool's index: each sealed file's store, kind, sha256, bytes, when put and sent; the last push; `v` 1 through `brain.stateio` |
| `$BRAIN_HOME/spool/<store>/` | the sealed copies waiting to leave, each with brain.vault's manifest |
| the OS keystore, `brain-vault/device` | the device key itself: never on disk in clear, never printed |
| the OS keystore, `brain-vault/device-previous` | during a rotation only: the replaced key, until `forget-previous` |
