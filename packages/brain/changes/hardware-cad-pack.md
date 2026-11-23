section: Added

- The engine ships a third typology pack, `hardware-cad` (a physical or cyber-physical product): the software catalog
  under the `hardware-cad` profile, three clauses of done (`physical-evidence`: a hardware or simulated run recorded
  with its run id, date and data hash; `failsafe-tested`: an emergency stop and a lost link put the device in its safe
  state; `design-checked`: schematics, bill of materials and netlist in step, the electrical and design rule checks
  passed), two one-way doors (`hardware-spec`, `safety-interlock`) and two roles. An item of typology `hardware-cad`
  (or its sub-profiles `hardware` and `engineering-product`) takes its clauses from this release on; a brain takes the
  pack's other parts with `from: engine` in its `packs.yaml` (`brain typologies propose`).
