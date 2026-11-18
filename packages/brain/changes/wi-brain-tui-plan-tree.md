section: Added

- The cockpit's Milestones tab gains its Tree view, the backlog's WBS (`v`; `brain.planviews`, `brain.tui_plan`):
  era › milestone › item, or with `g` era › wave › item (a carried item in the wave it is in now), each milestone's
  items done out of its live items through its sub-milestones, its bar and its p10–p90, each item's state, priority,
  gates and band, the done items folded; the dates read from the last `brain forecast`'s `latest.json` (re-read when it
  changes), never recomputed. The tree's axes are data (`cockpit.MODES`), the axis kept in `tui.json` with the tab's
  view; `brain tui --once --tab milestones --view tree [--axis waves]` prints it, and `--view` prints one view of a
  tab (`wi-brain-tui-plan-tree`).
