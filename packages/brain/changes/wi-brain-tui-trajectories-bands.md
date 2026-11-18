section: Added

- The cockpit's Milestones tab gains its Trajectories view, the Gantt as bands (`v`; `brain.planbands`,
  `brain.tui_plan`): one row per milestone, era and wave the last `brain forecast` dates, sorted by its median, `▒`
  p10 to p80, `░` p80 to p90, `█` the median, the band stopped at the 6-week horizon with `▸` where it goes on; the
  gates (`◆` go/no-go, `⧗` calendar, `⚙` hardware, `⇢` another project), why a milestone is not dated, « (no
  milestone) » and the backlog's flow, the notes wrapped rather than cut; UNCALIBRATED until judged, read from
  `latest.json`, never recomputed. `[` `]` change the scale, `←`/`→` pan a week up to the horizon, Enter opens a milestone's detail, and Enter on a Tree milestone opens its row
  there; `brain tui --once --tab milestones --view trajectories` prints it (`wi-brain-tui-trajectories-bands`).
