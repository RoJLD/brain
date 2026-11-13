section: Added

- The wave quota gate (`wi-brain-wave-quota-gate`), off by default: with config.json
  `usage.guard.wave_quota: {"ask_over_pct": 90, "max_streams": 3}`, the usage governor refuses a `start_session` that
  starts a session now when its master already has `max_streams` live streams (its running or starting children in the
  desktop app, and the starts the app does not show yet), and asks the owner when the week's forecast at its reset
  (`brain usage quota`'s pace) plus the stream's estimate (its brief's `usd=`, else the median session's) goes over
  `ask_over_pct`. A forecast or a session tree it cannot read, or a count past 2 s, lets the start through with a note.
  `brain brief`, `brain wave plan`, `brain next` and `brain usage guard` say how many streams fit now, and a wave
  plan's round holds at most `max_streams` lots.
