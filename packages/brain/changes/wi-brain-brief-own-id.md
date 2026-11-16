section: Added

- `brain sessions self [--json]` prints this session's own app id (`local_...`), the one a report to its coordinator
  is signed with; `brain brief` says to read it there (or with the app's get_session `self`), never to sign with the
  coordinator's id or the shared notes folder's (`wi-brain-brief-own-id`).
