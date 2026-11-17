section: Upgrade

1. **Install the engine**, in your own terminal, not from a Claude Code session: `brain update`, then `y`. It installs
   the tag, writes `engine.pin`, commits `config.json` and runs `brain sync`. A brain whose `config.json` declares
   `engine.installer`: merge the PR that moves `engine.pin`, then run the installer's `-Apply` instead.
2. **Restart the Claude Code sessions**, so that they run the hooks `brain sync` rendered.
3. **Refresh the public stamp**: run `brain check --public --history` in each public repo's checkout before its next
   push. A stamp is valid only under the engine that made it, so the push guard refuses the old one until then.
