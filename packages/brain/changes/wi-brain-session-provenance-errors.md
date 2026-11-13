section: Changes

- A value that breaks a schema's `pattern` is no longer printed back in the error (`brain.schema`, every schema:
  `brain record check`, `brain config --check`, `brain check`...): the error names the field's path and the value's
  length, so an e-mail address, an account id or a secret never reaches a terminal or a log
  (`wi-brain-session-provenance`).
