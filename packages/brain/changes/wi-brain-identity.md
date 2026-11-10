section: Added

- Identity, standalone (`wi-brain-identity`): `members.yaml` beside `config.json` declares a brain's people (their
  `person_id`, public SSH ed25519 signing keys and age recipients), accounts, organizations and tenants, and their
  roles per project or tenant (`schemas/members.schema.json`). An answer of the owner-decides class (money, keys,
  accounts, visibility, heirs, scheduled tasks) may carry a detached signature, `records/ddr/<id>.sig`, made in the
  owner's own terminal with `ssh-keygen -Y sign` (namespace `brain-decision`) and verified by `brain check` with a
  decider's public key; the engine never signs nor reads a private key. New command `brain identity check | unsigned
  [--write DIR] | payload ID | attach SIG|DIR`. The board marks an owner-decides answer `(signed)` or `(unsigned,
  relayed by session S)`, and `asked.by` names the asking session, else the owner: never `unknown`. Nothing is
  refused by default: without `members.yaml` nothing is checked, and with it the findings are warnings until the
  optional `config.json` `identity.require_signed: true` makes them errors (docs/identity.md).
