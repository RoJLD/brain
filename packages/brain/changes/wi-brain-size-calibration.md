section: Added

- Sizes checked against actuals (`wi-brain-size-calibration`): `brain cost review` says a finished item's judged size
  (`props.size`) against the size its active time falls in on the scale (a hit, under-sized or over-sized);
  `brain cost audit` adds « Sizes against actuals »: the window's misses per size and class, the thresholds the
  history proposes (each size's p75 of active hours), and whether the size is kept as `brain cost estimate`'s first
  similarity key: it is, as the `size+class` basis, only while it lowers the backtests' error.
