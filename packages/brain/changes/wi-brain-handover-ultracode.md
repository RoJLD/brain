section: Added

- `brain handover write --successor NAME` also writes the successor's brief beside the note, `<note>.brief.txt`, its
  first line carrying the word `ultracode` (ultracode on at every coordinator hand-over, the owner's decision of
  2026-11-12); `brain handover wait --successor ID` waits, bounded (default 120 s, at most 600), for the successor's
  first turn before Remote Control on for it, and says to wait again and retry once on a refusal that says it is
  unknown (`wi-brain-handover-command`, its follow-up).
