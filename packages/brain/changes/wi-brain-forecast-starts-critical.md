section: Added

- `brain forecast` keeps what its scheduler knows (model 3, additive keys of format 1): each item's `start`
  (p10-p90), its drawn `hours` and its `critical` index per group it belongs to (the share of futures in which it
  lies on the chain that sets the group's finish, Van Slyke 1963), each milestone's and the backlog's most frequent
  `chain` (what each link waited on: a gate, a dependency or a lane another item freed), and `past`, the ledger's first
  session and done day of the done and doing members of the open milestones. `brain forecast --critical
  [<milestone>]` prints the chains, capacity- or dependency-bound, and one milestone's items with their index, start
  and end (`wi-brain-forecast-starts-critical`).
