section: Upgrade

1. **Bring the default branch's views up to date, and run the one writer after each merge.** `brain check` (and
   `brain refresh`, which checks) now fails on the default branch (HEAD on origin/HEAD's target, else main, else
   master) when a generated view is stale: the decision queue, the links graph, the plan and module maps, the
   records' graph, `FEATURES.md`, the kanban and the roadmap; it only warned before. On any other branch a stale view
   is one `views:` line, no longer a warning, and outside git the warnings stay. Before installing, check the main
   checkout (`brain check`); where it names a stale view, regenerate from a worktree at its tip:
   `git worktree add -b chore/views-<date> <path> origin/main`, `brain --root <path> views --write --commit`, then
   push and merge that commit. Afterwards a branch may leave its views uncommitted (`brain views --unstage`,
   `--reset`) and the same command runs after each merge (`docs/views.md`). A brain worked on its default branch
   itself regenerates there with `brain sync`, as before. `brain audit --write`, `brain coverage --write`,
   `brain features render --write`, `brain decision view --write` and `brain modules --write` now refuse another
   engine than `config.json` `engine.pin`, as `brain sync` does (`--force` writes anyway) (`wi-brain-views-one-writer`).
2. **Install the engine**, in your own terminal, not from a Claude Code session: `brain update`, then `y`. It installs
   the tag, writes `engine.pin`, commits `config.json` and runs `brain sync`. A brain whose `config.json` declares
   `engine.installer`: merge the PR that moves `engine.pin`, then run the installer's `-Apply` instead.
3. **Restart the Claude Code sessions**, so that they run the hooks `brain sync` rendered.
4. **Refresh the public stamp**: run `brain check --public --history` in each public repo's checkout before its next
   push. A stamp is valid only under the engine that made it, so the push guard refuses the old one until then.
