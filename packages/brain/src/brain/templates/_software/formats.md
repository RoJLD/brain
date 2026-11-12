# Formats and versions

Every file this project writes and reads back (a configuration, a state file, a cache, an export, a message) is a
format, listed below with its version. The rule is tolerant readers, strict writers:

- a reader keeps what it does not know (a note, the file kept as written) and reads an older version as it was
  written;
- a writer writes only what it knows, and a version field (`v`) says which;
- a file of a higher version than the reader knows is refused, never overwritten;
- a format that moves (a field removed, a type narrowed, a new required field) is a minor version, with its migration
  and the fixtures of its older version, `fixtures/formats/<format>/v<N>/older.*`, which the tests read
  (`tests/conftest.py`, `old_formats`); an optional field added is a patch.

| Format | Where | Version | Unknown field or key (read mode) | Higher `v` |
|---|---|---|---|---|
| <!-- name --> | <!-- its path --> | <!-- `v` (its schema) --> | <!-- a note; the file kept --> | <!-- refused --> |
