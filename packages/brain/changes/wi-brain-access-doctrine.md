section: Added

- Access, the doctrine (`brain.access`, read only: nothing is refused by it yet): `members.yaml` grows `groups`
  (people and groups, nested, never a cycle) and grants on nodes of the scope tree (`group` or `person_id`, `scope`,
  `grade`, `since`, `until`); the grades `viewer` < `contributor` < `maintainer` < `owner` (read, propose, write,
  administer) and the capability roles `decider`, `releaser`, `auditor`, their labels renamed by `config.json`
  `grades`; a grant holds down the tree by union, the highest grade winning. `brain check` and `brain identity check`
  add the references (an unknown group, member, node or grade, a cycle, a grant that grants nothing) to the identity
  findings: warnings, errors under `identity.require_signed`. `brain access explain PERSON [--scope REF] [--client C]`
  prints a person's grade on a node with the grant behind each verb, and an agent's reach (read and propose at most).
  A solo brain sees no change. The fields need 0.6.0 on every machine (`docs/formats.md`).
