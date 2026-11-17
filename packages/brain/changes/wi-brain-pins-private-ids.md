section: Added

- Each decision pin has a public alias, which a public repo's PR body says in place of the private decision's id
  (`Keeps <alias>`, `Overrides <alias>: why`): its `alias` (`brain adr pin ID --alias NAME`, refused when the public
  check would refuse it: the shape of a graph id, a decision's id, the words of an ADR's title), else `pin-` and 8 hex
  digits of the id's sha-256. `brain review check` (its pinned lines and every block), `brain merge-ready` and `brain
  impact --diff` give it; `brain check` warns on an alias the public check would refuse (the computed one answers in
  its place: the pin stays in the gate) and on one alias given to two decisions; `brain adr pin` takes `--touches`
  only for a new pin, and says which alias a new `--alias` replaces. An engine older than this one reads the same
  `pins.yaml` (it keeps the `alias` key) but its gate does not take `Keeps <alias>` (`wi-brain-pins-private-ids`).
