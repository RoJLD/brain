section: Fixes

- A machine whose OS install id cannot be read (no machine-id file, an MSYS Python) no longer keeps its `no-anchor`
  identity doubt forever, holding the memory export: the owner's confirmation, the name declared in `config.json`
  `hosts` without an anchor (`"hosts": {"<name>": {}}`), clears it, and the doubt's text says that line; a declared
  anchor that cannot be read here stays a doubt (`wi-brain-machine-no-anchor-doubt`).
