section: Fixes

- A first `install.ps1 -Apply` installs the profile's extras: `brain profile` (and `render`, `set`, `list`, `show`)
  runs with no personal brain and no graph store above the folder, on the machine's profile and the built-in base,
  where it stopped on the missing root; the installer, which reads `brain profile render` right after its pip install,
  so never added the default profile's `tui` before a `brain init`. A render that still fails says how to add it
  (`-Apply -Extras tui`) (`wi-brain-install-profile-extras`).
