section: Changes

- An edge of a store listed after its project's first may name an ADR or SDR stub that first store derives (an item
  of a second store `decided_by` an ADR of `notes/decisions.md`): `brain sync` and `brain check` accept it and
  research_graph resolves it in the first store, as any edge between stores (`--foreign-store`). The 0.3.0 rule that
  refused it (« that ADR stub is notes/graph's only ... move the edge ») is dropped, with its error: it only stops
  refusing (`wi-brain-shared-root-stub-rule-drop`). An engine before 0.3.2 still refuses such an edge: write one only
  once every machine of the brain runs 0.3.2 (`brain update`).
