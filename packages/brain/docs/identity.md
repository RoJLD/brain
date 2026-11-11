# Runbook: identity, members and signed answers

Who belongs to a brain, and proof that the owner gave an answer that only the owner may give. A brain in files and
git has no server to log in to: what it needs is **signatures**, not sessions. This is the standalone identity:
signing keys first. Passkeys (WebAuthn), short tokens for agents and an OIDC issuer come once a brain server exists.

Three rules hold everywhere:

- **public keys only** in the brain: `members.yaml` holds public halves, and `brain check` refuses a line that matches
  a private key;
- **the engine never signs**: it never generates, reads, stores or prints a private key, and never names one to a
  tool. It only verifies, with `ssh-keygen -Y verify` and the public keys of `members.yaml` (`brain.sshsig`);
- **nothing is refused by default**: without `members.yaml` nothing is checked; with it, the findings are warnings
  until the owner sets `identity.require_signed: true` in `config.json`.

## members.yaml

At the brain's root, beside `config.json`; its schema is `src/brain/schemas/members.schema.json` (version `v: 1`,
read tolerantly like every format: [formats.md](formats.md)). The vocabulary is the one of an identity provider:
Person, Account, Organization, Membership.

```yaml
v: 1
class: confidential
people:
  - person_id: ada                 # stable: never reused, never renamed (a signature names it)
    name: Ada
    keys:
      signing:                     # SSH ed25519 public keys, one per machine or hardware key
        - {key: "ssh-ed25519 AAAAC3Nz... ada@laptop", machine: laptop, since: 2026-11-10}
      encryption:                  # age recipients (brain vault)
        - {key: age1..., machine: laptop}
accounts:                          # linked by proof on both sides, never by an e-mail address alone
  - {person_id: ada, provider: github, subject: ada-example}
organizations:
  - {id: acme, name: Acme, kind: tenant}
memberships:
  - {person_id: ada, roles: [owner, decider]}          # the whole brain
  - {person_id: ada, project: demo, roles: [decider]}  # one project of the registry
  - {person_id: ada, tenant: acme, roles: [member]}    # a hosted tenant
```

- `decider` is the role whose keys verify an owner-decides answer: on the whole brain, or on the project the DDR
  belongs to. `releaser`, on the whole brain, is the role whose keys verify a release tag of the engine (« Signed
  releases » below). `owner`, `member` and `viewer` are read by later checks.
- `since` on a signing key: answers recorded before the earliest `since` of the deciders' keys need no signature (the
  past is not re-signed). A key without `since` asks a signature of every owner-decides answer.
- `revoked: <date>` on a key: it no longer verifies anything, not even a signature it made before that day. The date
  is a record of when, not a cut-off: an answer's `at` is written by whoever records it, so a stolen key could sign
  an answer dated before its revocation. After a rotation, `brain identity check` names each signature that no
  longer verifies; delete those `records/ddr/<id>.sig` files (void), and `brain identity unsigned --write DIR` gives
  their answers to sign again with the new key, as below.
- Its data class is confidential (names, accounts): declare it in `config.json` `classes.stores`, e.g.
  `"members": {"class": "confidential", "paths": ["members.yaml"], "waive": {"git-private": "public keys and names,
  read in clear by brain check"}}` ([vault.md](vault.md)).
- Its side in `boundary.yaml` is personal: add `- {glob: "members.yaml", side: personal, why: "who belongs to the
  brain"}` to the brain's `boundary.yaml` with the file, or `brain check` reports it as classified by no rule (the
  template gains the rule with the next minor version: a template change moves what `brain init` wrote once).

`brain check` and `brain identity check` validate it: the schema, unique `person_id`s, every person, organization and
tenant named exists, no private key.

## The owner-decides class

A decision whose text (title, question, context, options, the recommendation's why, its links) speaks of **money,
keys, accounts, visibility, heirs or scheduled tasks**: the words of `brain.defaults` (the same that refuse a
low-stakes default), plus heirs and succession. A false alarm only asks one more signature.

## The signature

A **detached file beside the record**, `records/ddr/<id>.sig`: an SSH signature (namespace `brain-decision`, so it
verifies nowhere else and nothing else verifies here) over the answer's **payload**, a stable JSON text of the DDR's
id, title, question, option labels and its answer (`at`, `by`, `choices`, `other`, `notes`) that
`brain identity payload ID` prints. Any later change of the answer (`brain decision answer --again`) voids it.

Why a file and not a field of the DDR: a new field moves the record's format (a minor version), and an older engine
elsewhere would refuse the record; the file is ignored by an older engine, which reads the record as before.

An answer without its signature is **unsigned**. The board (`notes/decision_queue.md`) marks each owner-decides
answer once `members.yaml` exists: `(signed)` only when its signature verifies with a decider's key, `(signature not
verified: brain identity check)` when the file is there but does not verify (the answer changed after it, another or
a revoked key, no `ssh-keygen` on this machine), else `(unsigned, relayed by session S (ask-tool))`; `brain check` and
`brain identity check` report each unsigned answer and each signature that does not verify. `asked.by` names the
asking session, else the owner who asked from their own terminal: never `unknown`.

## The owner's commands

Once, in the owner's own terminal (never in a session): make a signing key protected by a passphrase, outside the
SSH agent, then declare its public half.

```
ssh-keygen -t ed25519 -f ~/.ssh/brain_decision -C "<you>@<machine>"     # asks a passphrase: give one
cat ~/.ssh/brain_decision.pub                                            # the line to copy into members.yaml
```

Copy the `.pub` line into `members.yaml` (`people[].keys.signing[].key`, with `since:` today), give yourself the
`decider` role, then `brain check`. A hardware key (`ssh-keygen -t ed25519-sk`) is declared the same way: its
`.pub` line as written.

To sign, by batch, after reading what you sign:

```
brain identity unsigned --write ~/brain-sign               # the answers waiting, each payload as <id>.txt
ssh-keygen -Y sign -f ~/.ssh/brain_decision -n brain-decision ~/brain-sign/*.txt   # one passphrase for the batch
brain identity attach ~/brain-sign                         # verified, then kept as records/ddr/<id>.sig
```

In PowerShell the second line is
`ssh-keygen -Y sign -f $HOME\.ssh\brain_decision -n brain-decision (Get-ChildItem $HOME\brain-sign\*.txt).FullName`.
`attach` verifies each signature against the answer as recorded and the deciders' keys, and keeps none when one
fails or names a decision not answered yet. A session may run `unsigned` and `attach` (the public side); only the owner's key makes a signature. Then
commit the `.sig` files with the records (a PR as any record change).

## The merge lock (opt-in)

```json
"identity": {"owner": "ada", "require_signed": true}
```

With it, `brain check` exits 1 on an unsigned owner-decides answer recorded from the deciders' `since`, on a
signature that does not verify (or that cannot be verified: no `ssh-keygen` on the PATH), and on an invalid
`members.yaml`: the PR that applies an unsigned answer does not merge before its signature. Without it, the same
lines are warnings.

`ssh-keygen` with `-Y` is OpenSSH 8.1 or later: Windows 10 and later and Git for Windows ship it.

## Signed releases

A release tag of the engine is signed by its releaser, so that a tag pushed from a compromised account does not
install (wi-brain-release-signing). The engine verifies; it never signs.

- **The `releaser` role**: in `members.yaml`, a membership on the whole brain (no project, organization nor tenant)
  with `releaser` in its roles. Its people's signing keys not revoked are the release keys.
- **`allowed_signers`**, beside `config.json`: the file `git verify-tag` reads (`gpg.ssh.allowedSignersFile`), one line
  per release key, valid for the namespace `git` only (a `brain-decision` signature verifies no tag, and a tag's
  signature no answer). It is **generated**, never edited by hand: `brain identity allowed-signers` prints it,
  `--write` writes it (or `--write FILE`). Commit it with `members.yaml`; `brain check` warns when it is no longer what
  `members.yaml` gives (a key added, rotated or revoked since), and when `engine.verify_tags` is on with no file
  written. Publishing it elsewhere later (in the public engine, for a pilot) is an export of this file, a decision of
  its own, not a code change.
- **`brain update`** verifies the tag before installing it: the tag alone is fetched into a temporary repo
  (`git fetch --depth 1`), checked with `git verify-tag` against `allowed_signers` (or, when the file is not written,
  the same text generated from `members.yaml`), and a verified tag is installed **by the commit it names**, so that it
  cannot move between the check and the install. Its plan says `verify   vX.Y.Z: signed by <person>`, or why not.
  research-graph comes by the tag the engine's `pyproject.toml` pins: after the install, a research-graph from another
  commit than the verified one is said (the tag moved meanwhile).
- **The engine's installer** (`installer/install.ps1`) does the same before `pip install`, with the personal brain's
  `allowed_signers` (it runs before the brain command exists, so it reads the file only: write it). `-Engine` installs
  what it names, unchecked.
- **Nothing is refused by default**: both say the verification and install anyway, until the owner sets
  `"engine": {..., "verify_tags": true}` in `config.json`. Then a tag that is unsigned, signed by a key not in
  `allowed_signers`, or that cannot be verified (offline, no `ssh-keygen`) is refused, before anything is installed.

**Scope and target compatibility** (the one-way doors of this feature):

- `engine.verify_tags`: an optional boolean of `config.json`'s `engine`, off when absent. An engine before 0.3.2 reads
  it as an unknown key (a warning in `brain config --check`, never an error outside CI) and verifies nothing: turn it on
  once every machine runs 0.3.2 or later. Every engine from 0.3.2 reads it the same way; it is never renamed.
- `allowed_signers`: OpenSSH's own format (ssh-keygen(1), « ALLOWED SIGNERS »), at the brain's root beside
  `config.json`, generated from `members.yaml`. Its lines are `<person_id> namespaces="git" <public key>`, after one
  `#` comment line. Its place and format stay; a later engine may read more files of the same format (a published
  one), never another format at this path.
- **A rollback** to an unsigned tag (every tag up to v0.3.1) is refused while `verify_tags` is on: turn it off first,
  the owner's decision, then roll back.

The owner's steps, once, in their own terminal (never in a session):

```
ssh-keygen -t ed25519 -f ~/.ssh/brain_release -C "<you>@<machine>"     # asks a passphrase: give one
cat ~/.ssh/brain_release.pub                                           # the line for members.yaml
```

Add the `.pub` line to your `people[].keys.signing` in `members.yaml`, `releaser` to your roles on the whole brain,
then `brain identity allowed-signers --write` and commit both (with `boundary.yaml`'s lines for `members.yaml` and
`allowed_signers`, side personal, if the brain has none yet). Then tell git to sign tags with that key:

```
git config --global gpg.format ssh
git config --global user.signingkey "$HOME/.ssh/brain_release"     # the key file: ssh-keygen asks its passphrase
```

(In PowerShell, `"$HOME\.ssh\brain_release"`. The `.pub` path works instead only while an ssh-agent holds the key;
the key stays outside the agent here, as for the answers.)

Each release tag is then `git tag -s vX.Y.Z -m "..."` (your passphrase), checked with
`git -c gpg.ssh.allowedSignersFile=<brain>/allowed_signers verify-tag vX.Y.Z` before `git push origin vX.Y.Z`
(docs/release.md, « 3. The tag »). The same key may also be added to the GitHub account as a signing key, so that the
web shows the tag as verified; that is the account's setting, not the engine's.

## Commands

```
brain identity check                         members.yaml and the signatures (what brain check runs)
brain identity unsigned [--write DIR] [--json]   the owner-decides answers without a signature
brain identity payload ID                    what a signature of that answer covers
brain identity attach SIG|DIR...             verify the owner's signatures, keep them beside their records
brain identity allowed-signers [--write [FILE]]   the release signers (role releaser, namespace git), generated
```
