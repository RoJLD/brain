section: Added

- Item sizes: `brain item add --size S|M|L|XL --size-reason "..."` gives a work item `props.size` and
  `props.size_reason`, the writing session's judgement (S under about 0.3 h of active time, M about 0.8 h, L about
  2 h, XL beyond: to split); `brain item set ID size=...` checks the scale; `brain item add` stamps a work item
  `props.created` and, without a size, prints the line that gives one; `brain check` warns on an open item written
  since then without a size, and on a size without its reason (`brain.sizing`, `wi-brain-item-size`).
