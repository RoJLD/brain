section: Added

- The ranked frontier: `brain next` lists each wave's groups by the owner's priority (a confirmed one before the same
  one proposed), then the owner's order (`props.order`), then value over effort (WSJF: the value derived from the
  features delivered, a milestone moved and the items unblocked, or the owner's `props.value`; the effort from
  `props.size`); the wave's quick wins (size S, high value) come first; `brain next --explain` shows each score's parts
  and the values the owner set; the cockpit's frontier takes the same order, sorts by score and offers Size, Value and
  Score columns (`brain.ranking`, `wi-brain-prioritization`).
