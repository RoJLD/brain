section: Fixes

- The capture ledgers (`ar`, `ddr`, `events`), the guards, queue, answers and cockpit ledgers, the quota readings,
  the session starts, the notify audit and its held messages are appended under their folder's lock, in one write, as
  the exec ledger is: sessions' hooks writing at once on Windows no longer lose or mix lines; a hook still on an
  older engine writes without the lock until its plugin is updated (`wi-brain-ledger-append-lock`).
