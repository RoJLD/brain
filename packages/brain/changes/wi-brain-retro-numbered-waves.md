section: Fixes

- `brain retro --wave` reads the numbered waves: `--wave 0.3.2` (or `wave-0.3.2`) takes the items `part_of` that
  wave and those carried to it by `props.carried_to` (not those carried out of it), with the items whose free-text
  `props.wave` names it, a comma after the release included (`0.3.2, week of ...`); the deep retro of 0.3.1 found no
  item. It also lists the retro notes recorded on the wave's items (`props.retro_notes`, a `notes` key in `--json`)
  (`wi-brain-retro-numbered-waves`).
