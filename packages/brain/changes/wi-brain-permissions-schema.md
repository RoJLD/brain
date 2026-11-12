section: Added

- A JSON Schema for `permissions.yaml` (`wi-brain-permissions-schema`): `schemas/permissions.schema.json` describes
  what `brain.permissions` reads (its sections, a rule's keys), a test keeps it in step with the module's constants and
  the fixtures, and it is registered so that `brain schema diff` and `release-check` compare it like any format's
  schema. It refuses nothing at run time: `brain.permissions` still reads the file itself. A first schema given to a
  format the last tag registered with none is a patch's (`release_check.new_formats`).
