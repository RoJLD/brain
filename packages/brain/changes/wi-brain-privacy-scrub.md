section: Added

- **One privacy scrub for what leaves the machine** (`wi-brain-privacy-scrub`, brain.scrub): `ledger/errors.log`'s
  lines, a notification's title, text and link, and the free text of the outbox's kept copies have their secrets,
  e-mail addresses, home folders with a user name, this machine's and the fleet's names and the login replaced
  (`<secret>`, `<email>`, `~`, `<host>`, `<user>`); short names and common words (`root`, `runner`, `dev`...) are
  kept; a test corpus (`tests/fixtures/scrub/corpus.json`) holds the cases. The sending host's own field of a
  notification, and what routes an outbox entry (project, key, channel), are kept.
