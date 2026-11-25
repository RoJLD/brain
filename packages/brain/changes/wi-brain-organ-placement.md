section: Added

- Every node's organ (`wi-brain-organ-placement`, `brain.placement`): the module of the registry a node serves, its
  own `props.module`, else derived from the modules of its neighbours placed by hand, one hop along `documented_in`,
  `implemented_by`, `tested_by`, `specified_by`, `decided_by`, `enforced_by`, `delivers`, `learned_from`, `led_to`
  and `part_of` (a clear majority: the first module has twice the votes of the second), with its votes per module and
  edge type and a weight per module. The module view (`notes/modules_graph.md`) gains a placement section: per node
  type, the nodes placed by hand, derived, split and unplaced, and the hand placements the links contradict (another
  module's clear majority of two votes or more);
  `brain modules --json` gains `placement`; `brain item show` and `brain features show` print the node's organ line
  (`--json`: `organ`). Computed when read: no file or format changes. A brain's module view changes on its first
  `brain sync` under this engine.
