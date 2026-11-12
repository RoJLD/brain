section: Added

- One machine identity and facts in three states (`wi-brain-machine-facts`): `brain.machine.name` (`$BRAIN_MACHINE`,
  else the host name) read by the memory sync, the profile and the schedules; an anchor on the OS
  install (a sha256, never the raw id) kept in `<BRAIN_HOME>/machine.json` and checked against `config.json` `hosts`
  (a reused name, a cloned image, a renamed machine or a copied home is a doubt `brain doctor` names, which holds the
  memory export); facts true,
  false or unknown (an unknown fact holds neither way in `recommend_when`); ECC and battery probes; `ecc`, `battery`
  and `encrypted` flattened; each fact's source in `brain doctor` (an infra agent's report behind the new `infra-node`
  capability, off by default; the local probe; a nodes file read at a git ref; `hosts`) and `<BRAIN_HOME>/facts.json`;
  `profile.json` merged key by key over `tier.components`; `config.json` `engine.min`, under which the memory export and
  the DDRs write nothing. New optional config keys: `hosts`, `engine.min`, `inventory.nodes_file`,
  `inventory.agent_json`.
