section: Added

- **The secret scan hardened** (`wi-brain-secretscan-hardening`, brain.secretscan): a PEM private key's whole block
  matches (a ledger line drop takes its body too, not only its BEGIN line); the fleet's token formats are known (ntfy
  `tk_`, Tailscale `tskey-`, GitLab `glpat-`, PyPI `pypi-`, npm `npm_`); `clean_unit` refuses a unit (a note, a rule
  file) whole on a match; `gitleaks:allow` waives nothing under `machines/` and `memory/`, in the commit guard (even
  with gitleaks, which honours the mark) and in `brain check --public`.
- A blocking decision about the owner's rules or notes (`brain decision ask --rule ... --note ...`, `links.rules`,
  `links.notes`) is notified as a pointer only: never its question, options, rule text, id or host.
- `brain check --public --private-text` (brain.privatetext): the tracked files against the personal brain's rules and
  notes, by windows of 8 words, before each tag (docs/release.md, « 3. The tag »); it never stamps.
