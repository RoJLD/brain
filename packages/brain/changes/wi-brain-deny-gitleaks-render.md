section: Added

- `brain public deny render --format gitleaks` (`wi-brain-deny-gitleaks-render`, brain.denyrender): the deny list
  (config.json `public.deny`, the scope tree's and the derived terms) as a gitleaks configuration for a pass of
  its own (or extending `--extend PATH`), one rule per category matching each term as `brain check
  --public` does; a plan that never prints a term, then `--apply`: an atomic, idempotent write, mode 600, refused
  inside a git repository (default `$XDG_CONFIG_HOME/brain/gitleaks-private-patterns.toml`).
