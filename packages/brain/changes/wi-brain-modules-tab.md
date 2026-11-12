section: Added

- The cockpit's Modules page (`wi-brain-modules-tab`, SIGMA-15), in the settings tab: each module of the brain's
  catalogue (catalogue/v1) with its state on this machine and its source (`brain mod list`), its cost, what it needs and
  its fallback, then the distributions read-only. Enter on a module asks on or off (`--cascade` too), shows
  `brain mod enable|disable`'s plan, then `y` writes this machine's `profile.json`, logged as the owner's; off keeps the
  module's data and configuration. `brain tui --once --tab settings` prints the page.
