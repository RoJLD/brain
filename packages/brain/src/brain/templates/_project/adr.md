# The ADR template

This project's decisions go to its decision log, `notes/decisions.md`, one dated heading each, appended by `brain adr
new` (never rewritten: a decision that changes is a new ADR that reverses the old one, `--reverses`). `brain adr new`
writes the context, the decision, the why and the « Revisit if »; give the scope and the target compatibility inside
the decision, as below. A decision that waits on the owner is asked first (`brain decision ask`, 2 to 4 options, the
recommendation first).

```markdown
## YYYY-MM-DD — <the decision, in a few words>

**Context.** <what makes a decision needed now: the item, the measure, the question>

**Decision.** <what is decided.>
**Scope.** <up to which phase or stage it holds: a prototype's choice is not a V1's>
**Target compatibility.** <each need of a later phase it touches, and for each: compatible, an extension point, or to
review; what stays open. Never a design of the later phases.>

**Why.** <the reasons, and the options set aside with theirs>

**Revisit if.** <the precise trigger that reopens it: a measure that crosses a value, a stage reached, a dependency
released; never « if needed »>
```
