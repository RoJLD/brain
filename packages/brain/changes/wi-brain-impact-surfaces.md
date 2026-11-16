section: Added

- `brain impact` where the work happens (`wi-brain-impact-surfaces`): `--markdown` prints the checklist as a PR
  body's section (`### Impact (brain impact --diff)`, each entry a task, every text escaped for GitHub's Markdown);
  the cockpit's Health tab gains an Impact view, `brain impact --diff` of the branch of the checkout it runs from,
  read at each probe; a project's new optional `overlays:` key (another repo's graph store read with its first one,
  read-only, research_graph's `--overlay` format) is walked by `brain impact`, and the code map places the overlay's
  CodeRefs. An overlay that cannot be read is left out whole and named.
