section: Added

- `brain audit --diff` reads four cheap norms in the AST of each Python file a change touches (`brain.norms`, ruleset
  7): `norm.timeout` (a subprocess call or `urlopen` without `timeout=`, a `Popen`'s `communicate()` or `wait()`
  without one), `norm.encoding` (a text `open()`, `read_text()` or `write_text()` without `encoding=`),
  `norm.naive-time` (a naive `datetime.now()`, `today()` or `utcnow()` stored as text, in a dict or a JSON dump) and
  `norm.secret-argv` (a token, password, secret or API key variable in a child's command or env). What a change adds
  is an info line, never blocking, and a NEW line under the optional `config.json` key `audit.norm_lints_strict:
  true`; the occurrences already in a touched file are DEFER lines to the repo's debt item, one per file and norm
  (`wi-brain-norm-lints`).
