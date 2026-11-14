section: Added

- One view of every scheduled task of every project: `brain schedule list` adds the tasks found under each project's
  `alerts: scheduler:` folders to the declared schedules, each with its cadence, window (hidden or visible), enabled,
  its project's quiet hours, a collector's floor, its last run, the file its value lives in and how it changes; the
  cockpit's Settings tab gains a Schedules page. `brain schedule set NAME` changes a declared schedule in the file that
  declares it, as a plan then `--apply`, comments kept; nothing is installed until `brain schedule install --apply`.
  A schedule entry gains `visible` (a console window; hidden stays the default) and `floor` (a collector's slowest
  cadence: a slower `every` and a `--disable` are refused); an engine before 0.5.1 refuses these two keys, so a
  registry declares them once every machine runs 0.5.1 (`wi-brain-schedule-settings`).
