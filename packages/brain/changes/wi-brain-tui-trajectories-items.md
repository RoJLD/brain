section: Added

- The cockpit's Trajectories have an item level (`brain tui`, Milestones, Trajectories: `z` or Enter on a milestone's,
  an era's or a wave's row): its items as Gantt lanes, a wave's by lot and the others in the scheduler's order, each
  with its past bar from its first session to its done day, its start-to-finish band, its est. h (a done item: its
  actual hours) and its `crit.`, the share of futures in which it lies on the chain that sets the row's finish; `c`
  marks that chain with `◆` and says it in the heading, Enter opens an item's detail (on the heading, the
  milestone's), `Z` or Escape goes back. A forecast written before model 3 shows its finish bands alone and no
  `crit.`. The text twin: `brain tui --once --tab milestones --view trajectories --zoom <milestone>`
  (`wi-brain-tui-trajectories-items`).
