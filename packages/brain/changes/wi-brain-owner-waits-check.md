section: Added

- `brain check` warns of an open item whose text says it waits on the owner (« waits on Ada's install », « pending
  Ada's answer », « en attente de … du propriétaire ») while no `props.open`, `props.external_blocker` or pending DDR
  carries it, with the `brain item set` command that records the wait; a warning, never an error. The owner's names
  come from `identity.owner` and `identity.display_name`; history props, quoted text and general phrasings (« with
  Ada's go ») are left alone, and `props.owner_wait_checked` marks a sentence that is no wait
  (`brain.ownerwaits`, `wi-brain-owner-waits-check`).
