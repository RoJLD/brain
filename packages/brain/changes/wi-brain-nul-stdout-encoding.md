section: Fixes

- `brain` no longer raises `UnicodeEncodeError` when its output goes to `NUL` on Windows (`brain items --text x >
  NUL`): `NUL` reports `isatty()` true in the ANSI code page, so the CLI now switches stdout and stderr to UTF-8 with
  `errors=replace` whenever a stream's encoding is not UTF-8, not only when it is not a terminal; a UTF-8 console is
  left alone (`wi-brain-nul-stdout-encoding`).
