
## 2026-01-01 — Keep the work state in this graph

**Context.** The work state was spread over notes and chats; nothing said what can start now or what waits on whom.

**Decision.** Specs, milestones and work items live in `notes/graph`; the board and the roadmap are generated from
it (`research_graph kanban --write`) and never edited by hand.

**Why.** One source that a person and a script can both read; generated views that cannot drift.

**Revisit if.** The graph is no longer read before work starts.
