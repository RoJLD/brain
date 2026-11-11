section: Changes

- Before `brain permissions render --write` writes a settings file of a git work tree (a project's
  `.claude/settings.json`, its untracked `settings.local.json`), it backs the file up under
  `$BRAIN_HOME/backup/<project>-<key>/<its folder>` (the sealed backup store, keyed by the repo's path; the last 10
  copies per file, none when nothing changed), never as a `.bak` beside it, so git status stays clean; an untracked
  `.bak` an older engine left beside it moves there too. `~/.claude/settings.json` is backed up beside itself as
  before (`wi-brain-settings-backup-home`).
