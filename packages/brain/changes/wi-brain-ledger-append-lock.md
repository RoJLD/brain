section: Fixes

- The capture ledgers (`ar`, `ddr`, `events`), the guards, queue, answers and cockpit ledgers, the quota readings and
  the notify audit are appended under their folder's lock, in one write, as the exec ledger is: sessions' hooks writing
  at once on Windows no longer lose or mix lines (`wi-brain-ledger-append-lock`).
