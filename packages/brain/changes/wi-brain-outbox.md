section: Added

- **A failed notification waits in the outbox instead of being lost** (`wi-brain-outbox`). When no channel delivers
  because none was reached (refused, a DNS miss, HTTP 429/503, its breaker open), `brain notify send`, a blocking
  decision's notification and an alert's `resolved` message are kept in the sealed local outbox
  (`<BRAIN_HOME>/outbox/queue.json`, store `outbox`, sealed, truth-local) under an idempotency key made of their
  content: queued once, dropped when the same message is delivered later, replaced by a newer message of the same
  key. A timeout or a reset is not queued (the message may have arrived). Every alerts pass sends what is due again,
  after 5 minutes, then twice as long each time (at most 6 h, full jitter), and gives an entry up after 12 tries or
  7 days. A refusal (HTTP 401) is not queued; nor is an open alert (the pass already sends it again) or the quiet
  mode's summary (it stays held). `brain notify status` says how many wait.
