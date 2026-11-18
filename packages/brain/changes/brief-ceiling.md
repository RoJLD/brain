section: Changes

- `brain brief` starts every task class at 400k: the strategic class's default budget was 800k. A budget above
  config.json `brief.ceiling` (new, default `400k`), from `--budget` or a class of `brief.classes`, is warned about in
  the brief's warnings: it is the expansion step of an unfinished task, not a start (a message costs two to three
  times more above 400k of context).
