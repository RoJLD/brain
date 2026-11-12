section: Added

- Gates as data (`wi-brain-forecast-gates`, `docs/gates.md`): `props.gate` on a WorkItem or a Milestone, one gate or a
  list, of five kinds: `calendar` (days from a date or an item's end, a reset rule and its daily chance), `count` (a
  counter to reach: `ddr.answered` and `items.done` measured, any other with its own pace), `external`
  (`<project>:<id>`, passed once done), `hardware` (a machine and its ready range) and `go_nogo` (an answer delay once
  the node's dependencies are done). `brain forecast` (model v2) draws each one, waits a milestone on its own gate,
  reads a pending DDR of kind action as a gate of the items it names (timed by the actions done), lists the declared
  gates with what they hold and raises an alert when an item's p80 passes its `due` date; an `after_external` that
  resolves to a done item no longer holds its item. `brain check` warns on a malformed gate, a trigger that names a
  duration with no gate, an `after_external` or external gate that does not resolve, and a `due` without its
  `due_source`. `brain queue` ends with what each gate holds.
