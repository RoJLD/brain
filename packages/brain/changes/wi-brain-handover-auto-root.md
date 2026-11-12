section: Added

- A coordinators' chain root marked by its first prompt (`wi-brain-handover-auto-root`, HANDOVER-1): the
  UserPromptSubmit hook (`midsession`) marks a session in `<BRAIN_HOME>/handover/roots.json` when the desktop app shows
  it owner-started (no parent, no completed turn), its own transcript (found from its id) holds no turn yet and its
  prompt asks for a coordinator (`brain.succession.ROOT_WORDS`); the row's reason names the hook and the owner is told
  (a system message). The guard refuses a session that runs the hook's entry by hand (an interpreter given
  `midsession.py`, `-m brain.midsession`, or `python -c` code that imports or calls it); `brain handover root` stays
  the fallback.
