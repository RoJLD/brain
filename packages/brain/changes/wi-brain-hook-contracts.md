section: Added

- The hook contract between the bash hooks and Python (`wi-brain-hook-contracts`, docs/formats.md « The hook
  contract »): `brain sync` renders `hooks/contract.txt` beside the plugin's hooks (config.json's rules and the
  engine's version as flat lines), which `inject-rules.sh` reads instead of the first `"rules"` array in config.json's
  text; the budget and announce `.mark` files and `cache/node-clis.txt` end with a format line that today's bash
  checks (another format starts Python), after the lines an older plugin copy reads, so its bash keeps working; each
  hook passes its `brain_version` to Python, and the SessionStart health says when the session's hooks and the engine
  differ. Every hook now spells `<BRAIN_HOME>` as Python does on Windows (`%USERPROFILE%\.brain` before `$HOME`), and
  the health says when two `.brain` folders exist.
