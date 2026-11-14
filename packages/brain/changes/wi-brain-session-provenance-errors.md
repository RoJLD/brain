section: Changes

- A value that breaks a schema's `pattern` is no longer printed back in the error (`brain.schema`, every schema:
  `brain record check`, `brain config --check`, `brain check`...): the error names the field's path and the value's
  length; an enum's or a format's error prints the value only when it is a short plain word (no `@`, no UUID, at most
  40 characters), else its length, so an e-mail address or an account id never reaches a terminal or a log
  (`wi-brain-session-provenance`).
