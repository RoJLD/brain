section: Added

- The model of each agent role: config.json `brief.agent_models` (`{role: model}`, default `{"verify": "sonnet"}`: the verifiers and skeptics on the smaller model, every other role on the session's), printed by `brain brief`. The token ledger records each agent's role (a workflow agent's label before its colon, else its phase; a subagent's type) and model (the scanner's `SCAN_V` 6), and `brain usage --by role` lists the agents by role with each model's count and how many ran off the map (`wi-brain-review-model-routing`).
