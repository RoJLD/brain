# Runbook: data classes and the vault

What a brain may send where, and how what leaves a machine is protected. Two commands:

- `brain classes`: every store of the brain declares a **data class** in `config.json` (`classes.stores`), and the
  class says where the store may go and how. `brain check --all` refuses a store without a class and a destination
  its class forbids.
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
brain classes                 every store: its class, tracked files, machine paths, exits; waivers; errors
brain classes --check         exit 1 on a store without a class or a destination its class forbids (brain check --all too)
brain classes PATH...         the store and class of each path (a repo path, $BRAIN_HOME/..., ~/...)
brain classes --suggest       a starting classes block for config.json, to edit
```

The check reads reality:

- every tracked file has a class: the first store whose glob matches it, in the file's order (specific stores first,
  a catch-all `**` last);
- every store the engine writes outside the repo is declared: `$BRAIN_HOME/ledger`, `sessions`, `resume`, `digest`,
  `vault` and the transcripts (`~/.claude/projects`);
- tracked files whose class does not allow the repo's remote in clear are refused (`git-private`, or `git-public` when
  the remote is one of `public.repos`); a tracked `*.age` or `*.gpg` file is sealed, and an empty `.gitkeep` holds no
  data;
- an exit in `to` that the class says `never` for is refused;
- a class is at least the strictest `classes: {floor: ...}` along its project's scope chain (`scopes.yaml`, read when
  it exists).

A known gap is written as a waiver, `waive: {exit: reason}` on a store (a reason of 15 characters or more): it is
printed by every check instead of failing. `brain init` writes a starting block; `brain classes --suggest` prints one.

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

## Once a year: the drill

```
brain vault drill recovery
```

Type or paste the secret `AGE-SECRET-KEY-1...` line from paper at the prompt (not the public `age1...` key), then
Enter. Nothing shows as you paste: the key is hidden, like a password, so it stays out of the screen and the
terminal's scrollback.
The recovery canary must open and match its digest; `state.json` records the date and the health warning goes away.

## A lost or exposed key

- **A lost machine**: open its sealed copies elsewhere with the recovery key (`brain vault open FILE --identity -`) and
  remove its recipient from `config.json`. What was sealed to it stays readable by that key: the disk encryption is
  what protects it.
- **An exposed device key**: remove its recipient, delete the keystore entry (Windows: `cmdkey
  /delete:brain-vault/device`), run `brain vault device init` again and declare the new key.
- **The recovery key exposed or lost**: create a new one (step 3), declare it, remove the old one, and seal again what
  matters.
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
| `$BRAIN_HOME/vault/device.json` | this machine's device key: name, adapter, public key, keystore, date |
| `$BRAIN_HOME/vault/state.json` | the canaries (sealed, opened, digest, error), the drills, the last seal of each store |
| `$BRAIN_HOME/vault/canary/` | one sealed nonce per recipient |
| `$BRAIN_HOME/vault/sealed/<store>/` | the sealed copies and their manifests |
| the OS keystore, `brain-vault/device` | the device key itself: never on disk in clear, never printed |
