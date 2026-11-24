section: Fixes

- `brain forecast` dates a wave by the items in it now, as the cockpit's Tree counts them: an item carried into a wave
  counts in its range, one carried out of it no longer does (`brain.waves`' `items_of`;
  `wi-brain-forecast-starts-critical`).
