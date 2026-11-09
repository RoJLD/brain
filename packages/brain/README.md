# brain — the command

One command for a personal brain, at zero token: a person's or a team's rules, decisions, backlog, journal and
records, kept in a private git repo of their own and readable by people and by agents. This package is the engine
only: it holds no one's data. Each owner's brain is their own repo; the engine reads it through a small contract
(`config.json`, `projects.yaml`, the graph stores) and through paths it is given.

What it does, every command reading files and git, never a model:

- **records**: decisions put to the owner (DDR, `brain decision ask|answer|ack`), session and action records (SR, AR),
  captured by the hooks at zero token (`brain record`, `brain capture`);
- **backlog**: work items, milestones and specs in a `research-graph` store (`brain item add|set|close|link`,
  `brain milestone`, `brain spec`), with the views regenerated and checked (`brain sync`, `brain check`,
  `brain refresh`; in a brain's own root, check and refresh also run `brain check --all`'s registry check: the
  registry, `config.json`, the classes, the permissions, the stacks and the bundles they declare, the ids of every
  registered project);
- **history**: the journal (`brain journal add`) and the decision log (`brain adr new`), append-only;
- **views**: the owner's queue (`brain queue`), the status of every project (`brain status`), a cockpit (`brain tui`,
  its title bar the installed version and a newer one when out), a resume pack for agents (`brain resume`), digests,
  usage and cost ledgers, forecasts;
- **updates**: `brain update` shows the plan to the latest engine tag and installs it on the owner's yes;
- **the machine**: its profile (`brain profile`, alias `brain doctor`: Lite, Default, Recommended, Custom), stacks
  started on demand (`brain up|down|health`), permissions rendered for Claude Code (`brain permissions`);
- **Claude Code**: the hooks and guards under `src/brain/adapters/claude/hooks/` (rules injection, capture, the
  PreToolUse guards: production checkouts, the owner's own actions, a session's Remote Control and permission mode,
  power, third-party kits, attribution, secrets, conflict markers, public pushes, branch names; the usage governor before a new session, a subagent or a
  workflow; a command a session types into the owner's Terminal panel, `run_in_terminal`, meets the same shell
  guards), which `brain render --target claude` copies into the owner's own plugin;
- **publishing**: `brain check --public` refuses anything private (the owner's denied terms, secrets, personal data
  shapes, data files) before a push to a public repo, and its guard holds the push until the check is green under the same engine version,
  deny rules and gitleaks as now.

## Install

Python 3.10 or later. The command depends on PyYAML and on `research-graph` at the same tag.

```bash
pip install "brain @ git+https://github.com/RoJLD/brain.git@v0.2.7#subdirectory=packages/brain"
```

On Windows, `installer/install.ps1` does it in a venv of its own (`~/.brain/venv`, `BRAIN_HOME`), puts the `brain`
launcher on the user PATH, and, for a personal brain, sets up its Claude configuration (marketplace, plugin,
permissions, memory), the machine's pointer `<BRAIN_HOME>/personal.json`, the merge driver and the schedules (below).
On Linux it runs under `pwsh` and links the command into `~/.local/bin` ([`docs/install.md`](../../docs/install.md),
Linux). It prints a plan; `-Apply` does it. The launcher is replaced even while a brain runs (a session's hooks call it): a new one is swapped in beside it, the old one renamed aside and removed on the next run.

```powershell
.\packages\brain\installer\install.ps1                       # the plan
.\packages\brain\installer\install.ps1 -Apply                # the command
.\packages\brain\installer\install.ps1 -Apply -Personal D:\me\brain   # and this personal brain's setup
```

### Updates

`brain update` (since 0.2.4) reads the latest release tag of the engine's public repo (`config.json` `engine.repo`,
else RoJLD/brain) with `git ls-remote`, no token, and prints the plan: the version and its CHANGELOG sections, the
tag installed into the brain's venv (pip, the `tui` extra kept), the launcher swapped in on Windows (as the installer
does, even while a brain runs), and, for a brain that pins its engine (`config.json` `engine.pin`), the pin to move.
How it moves depends on the brain (COMPAT-5):

- **A brain without an installer of its own** (no `engine.installer`, such as one from `brain init`) has no review
  step, so the plan moves the pin itself: it writes the new tag into `engine.pin` (the file's other keys, their order
  and its indent kept), commits `config.json` alone in the brain's repo (« brain update: engine.pin vX -> vY »), then
  runs `brain sync` with the new engine. When the brain's venv already holds the latest tag and the pin lags it (an
  update made before this), the plan moves the pin alone. It never moves the pin backwards, nor to or from a pin that
  is not a release tag, nor for an editable install; a `config.json` with changes not committed or not tracked, a
  brain that is not a git repo or is on a detached HEAD, is left as it is and the plan says what to do by hand. The
  commit lands on the brain's current branch, never pushed. The plan's `--json` says so in
  `pin.move`: `"write"`.
- **A brain that declares its installer** keeps the reviewed PR: the pin to move is shown, never done
  (`pin.move`: `"pr"`).

It runs only on the owner's yes: `y` at its prompt, or `--yes`; never from a Claude Code session's shell, which is
told to run it in the owner's own terminal. `brain update --check` prints the plan and changes nothing; `--json`
gives its data. A checkout installed editable is not updated by pip (`git pull` there).

The cockpit (`brain tui`) has one tab per question, each on its key: `0` the overview, `1` the queue, `2` the sessions,
`3` the frontier, `4` the milestones, `8` health (alerts on top; audit debt, stacks and index, and the exec times).
The overview shows one card per tab, what counts in it in a few lines: the band now, the sessions asking, the nearest
milestones, what can start, the open alerts. Enter or a click opens its tab, already filtered as the card says, whatever your
filters and search (a filter that is not saved and goes when you leave the tab); the arrows move between the cards.
Ideas (`5`), lessons (`6`), features (`7`), resources (`9`) and settings (the comma) arrive with their items, and until
then their key says so. The bar shows what waits in each tab, in digits and signs: « 1 Ada's queue 3 » the band now, « 2
Sessions 1! » the sessions asking, « 8 Health 2 » the open alerts. A click on it, `ctrl+pageup` and
`ctrl+pagedown` also change tab, and Escape goes back one step at a time: the search, a full view, then the overview. A tab with several views says so in its toolbar:
`v` or a click changes it, and the overview's other views are the grid of every panel, where open alerts take a whole
row, and the digest. `--tab NAME` starts on a tab, and with `--once` or `--plain` prints its panels alone (the overview:
its cards). Under 120 columns or 30 rows the bar is reduced to its numbers (`0 1 Ada's queue 3 2 3 4 8`), the cards take
one column, the grid is not offered and the health frames stack. The last tab and each tab's view are kept
in `<BRAIN_HOME>/tui.json`.

From 140 columns, on a tab that is one list, a row's detail sits right of the list and follows the cursor: it reads
once the cursor rests, and remembers each row until its panel changes. Enter gives it the focus, where it scrolls and `o`
opens a link, and Escape gives the focus back; `a`, `d` and `A` work from the list too, each after its confirmation.
Narrower, or on a tab of several panels, Enter opens it over them.

`C` chooses the columns of the focused table: shown or hidden (space), their order (Up, Down, or `shift+up`, `shift+down`),
and the longest its title may be, the rest in the detail; the sessions also offer Cost, App id, Id and Branch. The palette
(`ctrl+p`) reaches every tab, view, project, sort, filter and table's columns without learning a key, and resets the views.
The chosen columns are kept in `<BRAIN_HOME>/tui.json`.

The cockpit's title bar always shows the installed version. Once the screen is drawn, it checks the tags in the
background (kept 24 h in `<BRAIN_HOME>/update.json`, silent offline) and shows « brain 0.2.3 · 0.2.4 available »
when a newer one is out; `u` then opens `brain update`'s plan in a confirmation, run on `y`.

A brain that declares its own installer in `config.json` (`"engine": {"repo": ..., "pin": "v0.2.3", "installer":
"install.ps1"}`, a path from the brain's root: its plan without arguments, `-Apply` to install the pinned engine)
gets one more signal: when the installed engine lags the pin, after a pin PR and before `-Apply`, the title bar reads
« brain 0.2.1 · pin v0.2.3: -Apply » and `u` opens that installer's plan, then `-Apply` on `y`. A brain without one,
such as one from `brain init`, keeps `brain update`. Either install runs outside the cockpit, which holds files pip
must replace on Windows: on `y` the cockpit exits, a new window waits for it, runs the install with its output in
view (a failure says so and waits for Enter), then relaunches `brain tui` with the same arguments. A queue
action's `install.ps1 -Apply`, applied with `A` in its detail, goes the same way.

A cockpit panel never stays blank without saying why. An empty table shows one line: « 7 hidden by kind action: f
changes the filters », « Nothing waits on Ada in every project », « far is not on this machine (../nowhere) ». A panel
not probed yet shows the probe's countdown (« probe in 1 min 40 (r for now) »), then its progress (« probing: quant
2/3 »). A read that fails keeps the panel's last content, with the error and the time of the data in its frame; it is
notified once and read again at the next tick (a probed panel: at the next probe). `--once` and `--json` print a
failed read on stderr and exit 1; `--detail` names it when it finds no row. A stack or a code index repo that is not
OK names its last OK measure this cockpit saw (« gitnexus DOWN (last OK 2 h ago) »). The project selector greys a
registered project this machine lacks, and `brain tui --all` without a project registry shows the folder's project
and says so.

A pinned brain runs its pinned engine. `brain check` warns when the running brain or research-graph is not
`config.json` `engine.pin`: a newer or an older version, or the pin's version from other code (another git revision,
an editable checkout or a folder that is not at the tag, or is dirty). `brain sync`, `brain refresh` and
`brain render --write` then refuse to write, since they would render the plugin's hooks and generate the links with
another engine. `brain update` moves the pin of a brain without an installer of its own; in a brain that declares
one, set `engine.pin` to the new tag in `config.json` and commit it by a reviewed PR; the refusal names the file and
the tag. Otherwise run the pinned
engine, or pass `--force`. A brain with no pin, or a
pin that is not a release tag, is not compared.

The local data survives an upgrade and a rollback: the engine reads tolerantly and writes strictly
([`docs/formats.md`](docs/formats.md)). A field or a key it does not know, a newer brain's, is noted and kept, and a
rewrite keeps it; a format whose `v` is above the engine's is refused with « written by brain > X: brain update ». The
checks read strictly in CI (`CI` set) or with `BRAIN_STRICT=1`, tolerantly elsewhere or with `BRAIN_STRICT=0`.

### The scout

`brain audit --diff` (the scout, run by the close-item procedure) lists what the units a change touches miss: a
test, the docs, the graph links. It also measures the shape the change gives the code, at zero token: a code file
it takes past 1,000 lines and a Python function whose cyclomatic complexity it takes past 15 are NEW (fixed in the
PR, or justified); a file or a function already past its threshold that grows again is deferred to the repo's debt
item. A dependency added to a manifest (`pyproject.toml`, `requirements*.txt`, `package.json`) that no decision log
of the project names, a `shortcut:` comment without its `ceiling:`, its `trigger:` and its debt item (`wi-...`), and
a symptom fix (an added `type: ignore` or `noqa`, a skipped test, an `except` that swallows everything, a sleep, a
retry, a longer timeout) with no `Root cause:` line are NEW too. The lines `Root cause: ...` and
`Justified: <unit>: <reason>` are read from the PR body (`--pr-body FILE`, `-` for stdin) and the range's commit
messages; a justified finding is shown and never blocks. The thresholds are the project's, in `projects.yaml`:
`audit: {max_lines: 1000, complexity: 15}`.

### The impact of a change

`brain impact [--diff BASE|A..B]` says, before merge, what a change's code carries in the graph
([`docs/impact.md`](docs/impact.md)): the symbols it touches in the GitNexus code index (`brain index`) and their
callers, the CodeRefs that name them, the nodes relying on those, then a checklist: the features whose status may
change, the docs to update, the ADRs and specs to re-read, the tests to run (one `pytest` line) and the CI jobs that
run them, the open items that deliver those features and the decisions pending on them. Without GitNexus it works at
the file level, a Python symbol looked up by the AST, and says so on its second line. `brain code-map` resolves
each active CodeRef to its GitNexus node and reports the coverage: symbols and files with a CodeRef.

### Tests linked and coverage

`brain sync` links each feature, item or hook to the test modules of its code (`tested_by`): the tests brain audit's
evidence names, the tests that import the module themselves, and for a CodeRef of a symbol the tests that name it, or
that ran it by the store's coverage summary. `brain coverage --repo R --run --write` runs a repo's suites under
pytest-cov with test contexts and keeps that summary in the store (`coverage/<repo>.json`); `brain audit` then
measures `test.coverage`, `feature.tests` reports a feature no test covers, and `FEATURES.md` shows each feature's
coverage. The rules: [docs/tests-graph.md](docs/tests-graph.md).

### The module map

A brain built module by module keeps the registry of its modules in the store (`notes/graph/modules.yaml`), and each open item names its module (`props.module`, `props.modules_secondary`). `brain sync` writes `notes/modules_graph.md`: per module its phase, its items done and open, and the gaps. `brain check` warns about an open item the map does not place. See [docs/modules.md](docs/modules.md).

## Start your own brain

```bash
brain init ~/my-brain --owner "Your name"            # the plan
brain init ~/my-brain --owner "Your name" --apply    # writes it; a second apply changes nothing
cd ~/my-brain && git init && git add -A && git commit -m "my brain"
brain check                                          # graph-check OK, and the boundary's public scan green
brain profile                                        # this machine's profile: Lite unless you choose another
brain item add wi-first --title "My first item"
# Claude Code, once: the brain's own folder is a local marketplace
claude plugin marketplace add ~/my-brain
claude plugin install brain-core@brain
```

`brain init` writes, from a template (`--template`, default `generic`: `src/brain/templates/generic/`) and
`research_graph init`, never over an existing file. `--owner` may be left out in a folder that already has a
`config.json` (its `identity.owner`). The generic template:

| File | What it holds |
|---|---|
| `config.json` | the contract, v1: `identity` (the owner's id, the name the views show, `display_name`, a person or a team, a tenant), `registry`, `rules`, `memory`, `records`, `template` (its name and version), `engine` (this repo and the tag installed), `tier` (Lite by default), `adapters.claude` (the marketplace `brain` and its core plugin `brain-core`), `public` (no public repo yet; `deny`: the owner's name, this machine's user and host names); `brain config --keys` lists every key |
| `projects.yaml` | the registry: one project, the brain itself (`brain projects --keys`), its repo audited with the rendered plugin waived |
| `boundary.yaml`, `fixtures/README.md` | every file's side (`brain boundary`) at `readiness_max: 0`: `src/`, `tests/` and `fixtures/` may be published one day, so from the first commit `brain check` refuses a denied term, a secret, an e-mail address or a home folder in them, and a file no rule classifies |
| `source/packs.yaml` | the neutral source the agent files are rendered from: the marketplace's owner and one core pack with the engine's hooks |
| `notes/graph/` | the brain's graph store, its `owner` the same as config.json's, in three layers: the work (items, milestones, specs), the decisions (ADRs) and the records (DDR, Session, Action), which `brain sync` generates from `records/` |
| `.claude-plugin/marketplace.json`, `plugins/brain-core/` | the Claude Code marketplace and its core plugin (its manifest and the engine's hooks: the rules injection, the guards, the capture), rendered after the store by `brain render --target claude --write`'s code, so `brain check` passes at once |
| `notes/decisions.md`, `notes/journal.md` | the decision log and the journal, append-only |
| `rules/global.md` | neutral starter rules for every project (definition of done, decisions, scripts before rules): edit them |
| `CLAUDE.md`, `README.md`, `.gitignore`, `.gitattributes`, `memory/`, `records/` | the repo's own rules and what it is, LF endings (the hooks' shell scripts), the memory notes and the records |

A template is data and a manifest, never code: `template.yaml` gives its `name`, `version`, the `engine` versions that
can render it (`">=0.2.2"`), a `title`, its `graphs` (a list of `{name, store, schema}`, the brain's main store
first, each started by `research_graph init`; `schema: default` only for now) and its `files` (`{the brain's path:
the template's file}`, `""` for an empty one), rendered with `{owner}`, `{owner_q}` (quoted for YAML or JSON),
`{name}` and `{title_q}`. It must write what config.json names (`projects.yaml`, `rules/global.md`,
`source/packs.yaml`, `memory/`, `records/`); the engine writes config.json, the graph stores and the Claude
marketplace itself. `--template DIR` takes a folder of your own holding one. A template is public data; the owner's
records live in their own brain.

It also writes `<BRAIN_HOME>/personal.json` when the machine has none, so that the hooks and commands run from any
folder find this brain. The brain is the owner's private repo: push it to their own account, never to a public one.
A team uses `--kind team` (and `--tenant ID` for a hosted brain). The step-by-step guide from an empty machine is
[`docs/install.md`](../../docs/install.md); the pilot's is [`docs/pilot.md`](../../docs/pilot.md).

Claude Code gets the hooks, the guards and the injected rules from the brain's own folder: `claude plugin marketplace
add <the brain's folder>` once, then `claude plugin install brain-core@brain`. The rendered files are never edited by
hand (`brain check` refuses them); after an engine upgrade, `brain sync` renders the plugin again. A rendered file
that already exists and differs is kept by `brain init` and named (`brain render --target claude --write` replaces
it). config.json names no `adapters.claude.source`, so the installer's marketplace steps (a GitHub marketplace) stay
off.

## The owner's queue

`brain queue` lists what waits on the owner: decisions, actions only they may do, permissions an agent lacked. It is
ranked at zero token by what each entry holds up, in three bands: **now** (blocking, the critical path, a P0 or a
deadline within 2 days), **this week** (a P1, a slip on a milestone, a deadline within the week, a milestone within 14
days) and **when you can**. Within a band, the owner's own order first (`brain queue order ID N [--band B]`,
`--clear`), then a score whose terms `brain queue --explain` shows:

| Term | From |
|---|---|
| priority | the highest priority among the open items and milestones it holds up (P0 8, P1 4, P2 2, P3 1) |
| count | how many it holds up, 0.25 each, at most 3: many P3s never outweigh a P1 by number |
| slip | the critical path's slip per day of waiting, from the last `brain forecast` (its saved `latest.json`) |
| milestone | how near the nearest held-up milestone's p50 is |
| deadline | a stated deadline (the DDR's `due`, `brain queue add --due`; or a `due`/`deadline` prop of what it holds up): 12 overdue, 10 within 2 days, 6 within the week, above any count |
| effort | the owner's minutes (`--minutes`; a decision's reading time), a quick one a little higher |
| age, blocking | the days it has waited (at most 2), and 4 for a blocking one |

The same bands show in `brain status`, the cockpit's queue panel (a Band and a Score column, filtered by band, sorted
by band, then the owner's order and the score; or by the score alone across the bands: s, a click on Score, or
`brain tui --sort queue:score`) and the morning batches (`brain decision batch --zen`: the band now always in the session). A denied tool call
expires once every session it was refused in is archived or gone in the Claude desktop app.

The views name the owner by `identity.display_name` (else `identity.owner`): the queue's title is « Ada's queue », or
« File d'Ada » with `"lang": "fr"` in `<BRAIN_HOME>/tui.json`'s settings (or `$BRAIN_LANG`), and « My queue » when no
one is named; `settings.titles` there gives any panel a free title. `identity.owner` stays the id `--by` writes and the
stores declare.

### The owner's answers: one writer per batch

The session that asks the owner records the answers, in one PR per batch (wi-brain-answers-lane):

1. `brain decision batch --json` prints the questions for Claude Code's question tool, and writes each one (its text,
   header and labels, the DDR's id, the session) to `<BRAIN_HOME>/ledger/asked-<month>.jsonl`.
2. When the tool returns, the capture hook ties each answer to the DDR its question came from (the id a repeated
   question carries, else its text and header, else its header and labels among the questions this session's batch
   printed) and writes it to `ledger/answer-<month>.jsonl`: the answer exactly as the tool returned it, the labels it
   names (the DDR's own, `(Recommandé)` dropped; a multiple choice is the tool's list of labels, or the labels joined
   by `, `, the rest of it the owner's text) and the owner's notes. A label the session shortened in the tool, which
   names no option, is kept `unmapped`, never the owner's text. A question the owner did not answer (they sent a
   message instead: the tool's « [User did not answer this question… » placeholder) is no answer: nothing is
   captured. A question the session wrote by hand stays an ad-hoc DDR of the capture (pending when unanswered).
3. `brain decision answer --captured` records this session's captured answers: a worktree of the project's main
   checkout on `claude/answers-<stamp>` from origin's default branch, the answers written, `brain refresh --offline`,
   one commit, one PR (`gh`), then merged; when the merge is refused because main moved, it merges main, takes main's
   side of the generated files, refreshes again, pushes and retries (`--retries`, default 3; `--no-merge` stops at
   the PR). A record that conflicts stops it. A decision answered meanwhile is left (`--again` replaces it). A
   capture names its DDR by its full id: one the default branch does not hold yet (asked on a branch not merged)
   is left captured and said, the others recorded; a DDR whose id merely contains it is never answered instead.
   A capture with no answer (an older engine's placeholder rows) or an `unmapped` label is refused, listed and
   retired (`ledger/answer-recorded-<month>.jsonl`, `retired`); so is a stale one, older than the answer the DDR
   already holds (answered by hand or by `--batch` meanwhile), `--again` included. An older capture of a DDR whose
   later capture was recorded never comes back. An answer captured before a low-stakes deadline replaces the
   default another branch's refresh took meanwhile. The command prints the retired captures (« retired, never
   recorded », each with its reason; `--dry-run` marks the refused ones) apart from the decisions left because they
   are no longer pending (« not pending, left », which `--again` replaces).

`--batch` is strict: a value is an option's exact label (any case, `(Recommandé)` ignored) or its number; a shortened
label is refused with the label it shortens, and the owner's own text is marked as such, `{"other": "..."}`. Its file
may start with a BOM (UTF-8, or UTF-16 from Windows PowerShell's `>`). In an agent's session (`CLAUDECODE`),
`brain decision answer`, `--batch` and `brain record ddr` (an answer by `--id ID --answer/--other`, or one a `--file`
adds or changes) record only an answer this session's own question tool captured: an answer relayed by a message is
never recorded; the session that gets it applies it and acknowledges it (`brain decision ack`) once the asking session
has recorded it and the mid-session announce names it. The owner's own terminal records anything.

### Decisions by default, then reviewed

`brain decision ask --low-stakes` marks a decision whose recommendation the asking session may apply at once,
provisionally (wi-brain-decision-default): the DDR gets `default: {option, after}`, `after` 24 h from the ask. The
owner may answer it as any other; without an answer, `brain refresh` (before it writes any view, so that the records'
graph and the kanban show it answered) or `brain decision defaulted --apply` records the recommendation as its
answer, `by: default`, `via: default`, at the deadline, and the hooks announce it with « by
default »; a DDR whose answer the question tool captured on this machine before the deadline stays pending for
`brain decision answer --captured`. The mark is refused, at the ask and by `brain check`, on a decision whose text
(the recommendation's why and the linked ids included) names money, keys, visibility, publication, accounts, arming,
rules or scheduled tasks (`brain.defaults.REFUSED`, by words, inside `-`/`_` compounds too, and amounts such as `40€`
or `$50`: a false alarm only keeps the decision with the owner; `brain check` applies it to pending DDRs, never to one already answered). A stamp without a zone is read as UTC. `brain
decision defaulted` is the owner's review list (the defaults to review, the provisional ones, the reversed ones:
answered otherwise than the default after the deadline; `--seen` marks them read, from the owner's terminal only,
and checks every id it names before it marks any (with `--apply`, the defaults due are taken first and stay taken
when an id is refused); with `--all` it takes full ids, each marked in the one project that holds it;
`--apply` and `--seen` never write a main checkout on main or master unless `--on-main`, as `brain refresh`), with a
line in the morning batch (`brain decision batch --zen`) and in the cockpit's queue panel (`brain tui`); any default is reversed with `brain decision answer ID
<option> --again`.

## Parallel sessions

Three zero-token commands for many sessions on one brain ([`docs/merge-driver.md`](docs/merge-driver.md)):

- **`brain merge-driver`**: a local git merge driver for the paths `.gitattributes` gives `merge=brain` (`brain init`
  writes them): a generated view keeps one side and is marked for `brain refresh`, the journal and the decision log
  are unioned in date order, the graph's edges and a CHANGELOG's Unreleased section are unioned, the other graph YAML
  is merged by id, anything else as git would. The installer defines it in the personal brain's git config
  (`brain merge-driver install --apply`); `brain merge-driver replay` merges a repo's past merges again with and
  without it. A driver that cannot run falls back to git's own `merge-file`, so ours is never left without its
  conflict markers (`brain.mergedriver`).
- **`brain merge-check`**: after `git merge origin/main`, the base fetched again and nothing main brought since the
  merge base lost: the lines main added to the journals, decision logs, edge files and CHANGELOGs (as content, in any
  order), the fields main changed on the graph's nodes, the nodes main has (a removal by the branch passes); exit 1
  when the branch is behind or lost something.
- **`brain collisions [--all] [--frontier] [--json]`**: the files each open branch and worktree changes, crossed with
  each startable item's predicted surface (its features' CodeRefs, its module, the files it names): the items that
  can start now, and those that wait on a branch and its session.
- **`brain brief ITEM [--class C] [--budget B] [--coordinator ID]`**: a sub-session's brief from the graph: the item
  and its subgraph, its collisions, the class's model and effort (config.json `brief.classes`), the budget, the cost
  estimate, the coordinator's id, and the definition of done and the never-list read from the owner's rules.

### The session tree

A session has two ids: its transcript's (`CLAUDE_CODE_SESSION_ID`: the ledger, the session records, the budget watch,
the cockpit) and the desktop app's `local_` id (`CLAUDE_CODE_HOST_SESSION_ID`: `SendMessage` and the app's session
tools). The SessionStart hook records both, and the parent, task and short name the session's own app metadata file
holds (`spawnedFrom`, read through a closed list of keys: never the files' reports, reminders, prompts or MCP
configuration); the briefs' hash in the token ledger gives the parent of a session the app never knew. The Stop hook
adds `host_id`, `name`, `parent`, `children` and `role` to the session record, and writes the child's end-of-turn
report, `<BRAIN_HOME>/sessions/<id>.report.json`: its PRs and its branch's head, the items and DDRs it names, what it
waits on (a wrap-up marked blocked, a question), what comes next (the wrap-up's question, else the plan's next step)
and its recap.

- **`brain sessions [--hours H] [--all] [--json]`**: the sessions active in the last 24 h with both ids, role
  (`master`, `sub`, `relay`, `solo`), parent, children live/started, state and context against its budget (the
  brief's; a master's without one: config.json `usage.master_budget`, else the model's window, 1M). The options may
  come before or after `tree` and `show`.
- **`brain sessions tree [ID]`**: the families with a member active in the last `--hours` (the app's last activity,
  else its SessionStart), or ID's, each child with its report: a master learns what its children did without paging
  their transcripts (archived branches counted, `--all` draws them). A session detached to the top level
  (`lineageDetached`, a hand-over's session living on) heads its own family; a parent the app's file no longer names
  does not come back from the ledger or the brief hash (the briefs give a parent only to a session the app does not
  know). A report's wait and recap come from the wrap-up of its last turn only.
- **`brain sessions show ID [--report]`**: one session by either id (a prefix of 8 or more) or its short name, its
  family, and what a message would meet: live and working (it waits in the queue), idle (it starts a turn), archived
  (lost). `--report` prints its last final message in full, read from its transcript, never stored.

`brain decision ask`, `answer`, `ack` and `archive` (and the question-tool capture) stamp the session's transcript id
and its app id with the machine (`host_id`, `machine`), the app id only when the app's own file of it names this
session's transcript (a `claude` started from a desktop session's shell inherits that session's id); `brain check`
(`brain.sessions`) refuses a DDR stamped on this machine in the last 7 days whose `local_` id matches no session the
app or the ledger knows, and warns for an older one (its session may have left the app and the ledger's two months
since), one stamped elsewhere or before the stamps.
The resume pack prints both ids, the app id under the same rule. The cockpit's sessions panel shows the short name (else the app id) in Session, then
Role, Parent, Kids (live/started) and Ctx (% of the budget), and the ids in a session's detail.

**The master's watch** (the budget watch, `budget.sh`, `brain.budget`): a session that started a session is a master
(a `start_session` call the owner asked for, or one that starts a proposal by its `proposal_id`, whose result is not
an error, or a child the app's files name; a proposal card, `offer` or `own_initiative`, starts nothing until the
owner starts it), its children read from the app's files
and the SessionStart events. A child is live until the app archives it (its recorded end counts only for a session
the app does not know: the app resumes its own on a message). At 70 % of its budget it says how many more children
fit before 80 % (the context a child costs, measured on the family, else 22k); at 80 %: start no new child, hand over
to a fresh master and drain yours (ask the owner nothing new, touch no other master's children), with a draft
hand-over note listing the live children with both ids, items and their state now (read from their transcripts); at
90 %: drain only, compact only once no child is alive. Each step gives the cost of one wake after the prompt cache
expired; a subagent's tool call never uses a step up, the main thread's next call gives it. The master's row in the
cockpit turns yellow, orange and red at each step; `brain alerts` (`brain.alerts`) raises a master past 80 % with
live children, both read from the session tree at each pass (an archived master or its archived children close the
alert at once; the state of a transcript the app's master has left, after a `/clear`, raises nothing, its current
transcript's own state decides; a master the tree does not know counts while its watch state is under 6 h old). An
unarchived master left past 80 % with unarchived children keeps its alert until one of them is archived or its watch
state is pruned (14 days), by design: those children still spend; the governor reminds
a master past 80 % that calls `start_session`, and lets the call through: nothing blocks a new session.

## Lessons

What each finished item teaches is a node of the graph, so it can be found, counted and fixed, at zero token
([`docs/lessons.md`](docs/lessons.md)):

- **`brain retro ITEM`**, a step of the close-item procedure: the friction signals of the sessions that served the
  item (merges and conflicts, guard refusals, failed tests, waits, tokens against the estimate, the owner's minutes,
  pushes to its PRs after they were opened), the known lessons of the signals that fired and five questions; the
  session answers in a few lines (`--record --note ...` writes them on the item). `brain retro --wave W`: a wave's
  deep retro.
- **`brain lesson add|seen`**: a Lesson node (`nodes/lessons.yaml`) with its trigger, anti-pattern and check, learned
  from an item or a PR; a lesson close to a known one is refused, to be marked `seen` instead. A lesson seen twice
  (once if severe) with nothing fixing it, or recurring after its fix, files an item proposal, its fix a script
  first, a rule last.
- **`brain lessons --follow`**: each lesson and what it led to (the item, its PR, whether it recurred since), and the
  friction per item by week. **`brain lesson rules`**: the iron rules (`Σ-NAME`) cited in each registered repo's
  Markdown, read only. **`brain lint lessons`**: the lessons a script could check (guard candidates) and those that
  should say why not.

## Schedules and the alerts pass

A project's `schedules:` entry in the registry declares the brain commands a machine's scheduler runs, `{name:
{command, every, at, days, at_logon, machines, timeout, enabled}}`, with `days` the days `at` runs on (`days: [mon]`
is weekly, none is every day); the alerts pass, say:

```yaml
brain:
  schedules:
    alerts-pass: {command: alerts --all --notify, every: 15m, at_logon: true}
```

`brain schedule install` prints the plan for this machine and `--apply` installs it (`brain.schedule`): on Windows a
Task Scheduler task `\Brain\<name>`, as the user, in their session, through the venv's `pythonw.exe` (no console
window, for it or for the programs it starts: `brain.nowindow`), never two runs at once; on Linux a systemd user timer
`brain-<name>.timer` (else the user's crontab), through `bash -lc` so that the login profile's variables reach the
command. What this machine installed
(`<BRAIN_HOME>/schedules/installed.json`) and no longer declares is removed; a task registered by hand is never
touched. The installer's schedule step runs it, so a schedule is a plan line that `-Apply` applies; creating a
scheduled task stays the owner's decision: from a Claude Code session `--apply` is refused after the plan, and the
guards refuse it as `owner:scheduled`. A command holds the brain command's arguments only: a newline or an
unbalanced quote is refused by `brain check --all`. `brain schedule list` shows every declared schedule and the alerts pass's
**dead-man**: once installed here, the pass is SILENT when its last run (`_pass` in `<BRAIN_HOME>/alerts/state.json`)
or its install, the later, is older than two cadences of the machine's awake time (a machine asleep or off misses
no pass); the SessionStart health hook says so in one line and `brain status`'s alerts row shows
it. Without its channel's variable (`BRAIN_NTFY_TOPIC`) a pass sends nothing and says so in one line; the alerts go
at the first pass that finds it. Off Windows, the alerts' Task Scheduler folders are skipped.

## Quiet mode

`brain quiet --for 2h` silences the notifications below `critical` for that long (90m, 2h, 1d; at most 7d); a
`critical` one still goes through. What was held (`<BRAIN_HOME>/notify/held.jsonl`) is summed up in one message per
project, through that project's routes, when the quiet ends: `brain quiet --off`, or the first alerts pass after the
end. A project may also declare hours, in local time and across midnight if need be:

```yaml
brain:
  notify:
    quiet_hours: "22:00-07:00"
```

Quiet silences notifications and nothing else: no task is paused, no scheduled task is disabled, no window opens or
closes, so a collector, whose data cannot be recovered, runs on and the alerts pass keeps recording what it finds.
`brain quiet` alone, `brain status` and the cockpit's health card show the state: until when, the declared hours, how
many are held. A summary that fails to send stays held for the next pass.

## Where the brain is found

`config.json` and `projects.yaml` are found at `$BRAIN_CONFIG` / `$BRAIN_PROJECTS`, else in the first of:
`$CLAUDE_BRAIN_DIR`, `$BRAIN_PERSONAL`, the repo acted on (a worktree of the brain reads its own files), then the
machine's pointer `<BRAIN_HOME>/personal.json` (`{"root": ...}`, written by the installer and by `brain init`). The
repo acted on is `--root`, else `$BRAIN_ROOT`, else the nearest folder above with `notes/graph/schema.yaml`, else the
personal brain. `--project P` alone resolves to the git worktree the cwd is in when that is a linked worktree of the
repo P's root is in (so a sub-session in a worktree never writes to the main checkout); an explicit `--root` wins, and
a cwd in another repo (a code repo of P, say) or a plain folder keeps the registry's root. Machine-local state (ledgers, sessions, the resume pack, the vault) lives in `BRAIN_HOME`
(`~/.brain`), never in a repo.

## The Claude Code hooks

`src/brain/adapters/claude/hooks/` is package data: `hooks.json` and a `.sh` launcher per hook, each running its `.py`
entry with `$BRAIN_PYTHON`, else the brain command's venv (`<BRAIN_HOME>/venv`), else `python3`/`python`. A personal
brain whose `source/packs.yaml` gives its core pack `hooks:` gets them copied into its own plugin by
`brain render --target claude --write`, at the version it pins; `inject-rules.sh` injects the files of config.json
`rules`. The guards never block a session on an error: without Python, the call goes through.

A hook costs every tool call its time, so the launchers start nothing they do not need: they read their JSON and find
Python with bash builtins (`hooks/common.sh`, no `$(...)`), and `guard.sh` starts Python only for a shell command that
may write, names `gh`, a program of the owner and power guards, `claude plugin` or `skills add`, or git other than to
read (`git [-C DIR] status`, `log`, `diff`, `show`, `rev-parse`... without `--output`: `brain.guards.GIT_READS`,
checked against the guards' tables). In Python a guard reads the registry through libyaml and does not import `urllib.request`.

Two guards keep what a session brings in and what it records clean (the runbook: [`docs/guards.md`](docs/guards.md)):

- **Third-party kits** (`guard.sh shell`, check `third-party`): a session never installs or runs a third-party kit. A
  download fed to a shell or an interpreter (`curl ... | sh`, `bash <(curl ...)`, `sh -c "$(curl ...)"`, `iwr ... |
  iex`, `iex (irm ...)`), `claude plugin install` and `claude plugin marketplace add` from a source outside the owner's
  list (config.json `adapters.claude.sources`; the brain's own marketplace always passes) and `npx skills add` are
  refused, each an action for the owner's queue with its exact command (`brain queue add --kind action --guard
  <ref>`). A download to a file (`curl -o`) passes; what the owner types in their own terminal is never seen.
- **Conflict markers** (check `markers`): a git commit, or a merge, rebase or cherry-pick `--continue`, whose staged
  lines add `<<<<<<< `, `||||||| `, `>>>>>>> ` or a bare `=======` is refused with the file and line; `brain check`
  fails on a store, journal, decision log or record file that holds one. A Markdown setext heading (`=======` under a
  line of text) and a file under a `fixtures` folder pass.

Two of the PreToolUse hooks keep the owner's say over how sessions run (the runbook: [`docs/guards.md`](docs/guards.md)):

- **Session settings** (`guard.sh tool`, `brain.guards`): a session that changes Remote Control or a permission mode
  (`set_remote_control`, `set_session_permission_mode` under any MCP prefix, the app's `set_setting` for a Remote
  Control key) is refused, whatever the value, and the exact action goes to the owner's queue (`brain queue add
  --kind action --guard <ref>`). Its category, `security-settings`, is never grantable (`brain permissions`), and
  `BRAIN_GUARD_ALLOW` does not lift it, not even `all`: the owner switches it in the app.
- **The usage governor** (`governor.sh`, `brain.governor`), before `start_session`, `Agent` and `Workflow`: it reads
  the cached quota readings (`brain usage quota --observe`), the sessions running and the brainstorms open on the
  machine (the desktop app's session files, else the session records), and the committed memory. It asks the owner
  from `warn` % of a quota window, refuses from `critical` %, refuses a new session past the parallel sessions cap
  (the smaller of `sessions` and what the week's room pays for), a new brainstorm past `brainstorms` (every project
  counted; a project's `usage: {brainstorms: N}` in `projects.yaml` lowers it for itself, never raises it), a new
  session or workflow from `memory` % of committed memory or while the newest quota reading is older than
  `fresh_minutes`. The thresholds are config.json `usage.guard`; `brain usage guard` shows what each tool would get
  now. A refusal names its reason and the owner's override: `brain usage allow [--hours H]` in their own terminal
  (the guards refuse it to a session), or `BRAIN_GUARD_ALLOW=usage`. Its decision takes under 50 ms.

The quota conversion (`brain usage quota`) is per plan: only the readings of the plan in force (config.json
`usage.plans`) count, and until the plan has 3 converted readings it says "uncalibrated", does not convert the week and
estimates the 5-hour window from its latest reading and the ledger's cost since.

The session record (`brain capture`, the Stop hook) holds the brief's `task_class` (trivial, standard, strategic,
brainstorm) and `ultracode` (whether it was on at any time), so the ledgers tell ultracode spend apart. The capture
hooks run `brain.capture` (`capture.sh <event>` runs `hooks/capture.py`, which calls it with the brain command's
venv): it reads the hook's JSON on stdin and appends the session events, the session-record snapshots and the action
records to `<BRAIN_HOME>/ledger` at zero token; it prints nothing and never fails the session (its errors go to
`ledger/errors.log`; `BRAIN_CAPTURE=0` turns it off).

**The engine times itself** (`brain.selftime`, local only, zero token). Every `brain` command and every hook writes
one exec event (task `brain <command> [<subcommand>]` or `hook <name>`, a bash-only run marked `[bash]`, the engine's
version, its duration from the engine's import or the hook's first line, its exit) to
`<BRAIN_HOME>/ledger/engine/exec-<yyyy-mm>.jsonl` (`exec-bash-...` for the bash fast paths); every error a hook or a
command catches becomes an error event there (its exception class and the engine's `module:function`, never its
message, whose text stays in `ledger/errors.log`). The last three months are kept. `brain perf --engine` lists the
slowest commands and hooks, the regressions from one engine version to the next, the hooks' blocking time per week
and the errors caught; `brain alerts` raises a hook or a command that caught the same exception 3 times in 24 hours,
on the brain's own project. `BRAIN_SELFTIME=0` turns it off.

```
brain perf --engine [--since 7d] [--task guard] [--json]
```

## Data classes and the vault

Every store of a brain declares a data class in `config.json` (`classes.stores`: public, private, confidential,
sealed, resident, secret, `tenant:<id>`), and the class says where it may go and how; `brain check --all` refuses a
store without a class and a destination its class forbids, and `brain init` writes a starting block. What leaves a
machine is sealed client-side to public keys (`brain vault`: age, gpg as the fallback), to a device key per machine,
kept in the OS keystore, and an offline recovery key: two recipients at least, proven daily by a canary per recipient
(`brain health vault`). When the recipients change (a lost machine, a revoked heir, a rotated key), `brain vault
reseal` seals the kept copies again to the current set. Opening, drilling, and creating or rotating a key are the
owner's acts, refused in an agent session. The owner's steps, the canary's scheduled task per system, the rotation
and what to do with a lost key are in the runbook, [`docs/vault.md`](docs/vault.md).

```
brain classes [--check] [--suggest] [--matrix] [PATH...]
brain vault status | seal STORE | canary | recipient add NAME [--replace] | recipient remove NAME | reseal [--apply]
brain vault device init [--rotate] | device forget-previous | open FILE | drill RECIPIENT
brain health vault
```

## Adding a command

Each top-level command is a module of `src/brain/commands/`: its parser, its handlers and its lines of `brain --help`.
`brain.cli` lists that package, adds each module's parser in `ORDER` and hands the parsed command to its module, so a
new command is a new file and no shared file changes:

```python
"""``brain hello``: say hello (the module hello.py of the package)."""

from __future__ import annotations

from pathlib import Path

ORDER = 560          # its place in brain --help's list of commands
USAGE_ORDER = 550    # its usage lines' place in brain --help's epilog ({owner}: the owner's display name)
USAGE = """\
  brain hello [--name N]   say hello to {owner}, or to N
"""


def register(sub, ctx) -> None:
    hello = sub.add_parser("hello", help=f"say hello to {ctx.who}")
    hello.add_argument("--name")


def run(args, root: Path) -> int:
    print(f"hello {args.name or 'world'}, from {root}")
    return 0
```

- `register(sub, ctx)` adds the command's parser (its subcommands, an alias) to brain's subparsers; `ctx.who` is the
  owner's display name for the help, `ctx.by` their id, the default of a `--by`.
- `run(args, root)` gets the project's root: `--root`, else `--project`'s, else the nearest folder above with a graph
  store. A command that must run before any root is resolved (a hook, a machine-wide command, a repo that may hold
  no graph store) defines `early(args)`: its exit code, or `None` to go on to `run`.
- `NO_PROJECT = {"hello"}`: no `--project` is added after its subcommand (the hooks', machine-wide commands).
- What several commands share is in `_common.py` (the text options, the project, its store and scope) and
  `_stores.py` (the passes of sync, check and refresh); a module whose name starts with `_` is not a command.
- `brain audit` flags a parser added in `cli.py` and a module of `commands/` without `register` (the check
  `cmd.registry`). `tests/test_cli_registry.py` checks every module's contract; `python tests/help_dump.py` prints
  every command's and subcommand's help and arguments: run it before and after a change of the parsers, and diff.

## Tests

From a checkout of this repo, with research-graph from the same checkout:

```bash
pip install -e . && pip install --no-deps -e packages/brain && pip install pyyaml pytest pytest-xdist
pytest packages/brain -n auto
```

The tests run as an invented owner, Ada (`tests/fixtures/brain/config.json`, set for every test by `conftest.py`
through `BRAIN_CONFIG`), with a temporary `BRAIN_HOME`; they need git, and bash for the hooks (Git Bash on Windows).
They read only fixtures, never a real brain's graph, records or rendered files: what checks a brain's own data is
`brain check` and `brain audit`.

`-n auto` runs them in parallel, one pytest-xdist worker per core: each test has its own temporary folder, `BRAIN_HOME`
and environment, so no test shares state with another. A git repository in a test is a copy of a template made once
per worker (`conftest.git_init`, the `git_repo` and `make_repo` fixtures), not a `git init`. The test that calls the
real docker client is marked `docker`: the CI runs it apart, on one process (`pytest packages/brain -m docker`).

## Releasing

With research-graph, under the repo's single tag series: see the root README. `CHANGELOG.md` here is the command's.
A release moves `brain_version` in `src/brain/adapters/claude/hooks/common.sh` with `__version__` (the hooks' bash
fast paths stamp it on their events; `tests/test_selftime.py` checks the two agree).

## License

The Business Source License 1.1, from version 0.2.2: `LICENSE` (its parameters at the top) and `NOTICE` (the credit to
keep). Its Additional Use Grant allows you to use, modify and run the brain command for your own work, as a person or
an organisation, and to reuse it in your own products, provided each product gives a visible credit to Brain and its
author in its documentation or its about screen (`NOTICE` gives a credit line) and the `NOTICE` file is kept with every
copy you distribute. Offering it to third parties as a hosted or managed service needs a commercial licence from the
licensor. Each version changes to the Apache License 2.0 four years after its release.

Versions 0.2.0 and 0.2.1 were released under the MIT License and stay under it. `research-graph`, the graph engine
this package depends on, stays under the MIT License (the repo's root `LICENSE`).
