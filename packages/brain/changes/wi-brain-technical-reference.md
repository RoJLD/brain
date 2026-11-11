section: Added

- The technical reference, generated (`wi-brain-technical-reference`): `brain reference [--write]` writes
  `docs/reference/`, an index of the modules of the store's `modules.yaml` and one page per module (what it does from
  its features; the decisions in force on its nodes, from the answered DDRs with the earlier ones folded, an ADR no DDR
  went to by its title, a superseded one marked; the rules its items deliver, its specs, items done and open, open
  questions), and counts the decisions no module holds; without `--write` it exits 1 when the folder is not the
  render. Once the owner opted in (`brain reference --write`: the project's own render in `docs/reference/`), `brain
  sync` writes it again and `brain check` warns when it is stale on the default branch; a brain without it is not
  concerned, and a page there that is not generated is never overwritten. `brain reference --public --repo R --out DIR` renders a
  public repo's neutral reference by feature domain from its features only, written only when
  `brain check --public` would refuse none of it; the engine's own is in `docs/reference/`.
