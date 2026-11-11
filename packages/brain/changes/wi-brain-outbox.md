section: Added

- **A failed notification waits in the outbox instead of being lost** (`wi-brain-outbox`). When no channel delivers
  because one was down (refused, timed out, HTTP 429/5xx, its breaker open), `brain notify send`, a blocking
  decision's notification and an alert's `resolved` message are kept in the sealed local outbox
  (`<BRAIN_HOME>/outbox/queue.json`, store `outbox`, sealed, truth-local) under an idempotency key made of their
  content: queued once, dropped when the same message is delivered later. Every alerts pass sends what is due again,
  after 5 minutes, then twice as long each time (at most 6 h, full jitter), and gives an entry up after 12 tries or
  7 days. A refusal (HTTP 401) is not queued; nor is an open alert (the pass already sends it again) or the quiet
  mode's summary (it stays held). `brain notify status` says how many wait.
