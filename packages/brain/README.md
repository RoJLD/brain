# brain — the command

One command for a personal brain, at zero token: a person's or a team's rules, decisions, backlog, journal and
records, kept in a private git repo of their own and readable by people and by agents. This package is the engine
only: it holds no one's data. Each owner's brain is their own repo; the engine reads it through a small contract
(`config.json`, `projects.yaml`, the graph stores) and through paths it is given.

What it does, every command reading files and git, never a model:

- **records**: decisions put to the owner (DDR, `brain decision ask|answer|ack`), session and action records (SR, AR),
  captured by the hooks at zero token (`brain record`, `brain capture`);
- **backlog**: work items, milestones and specs in a `research-graph` store (`brain item add|set|close|link`,
  `brain milestone`, `brain spec`), read back without opening its files (`brain item show`, `brain items`, `brain spec
  show`: « Reading a brain » below), the plan as eras, milestones and waves (`brain wave`, `brain next`), with the
  views regenerated and checked (`brain sync`, `brain check`,
  `brain refresh`; in a brain's own root, check and refresh also run `brain check --all`'s registry check: the
  registry, `config.json`, the classes, the permissions, the stacks and the bundles they declare, the ids of every
  registered project), and written once on the default branch after each merge by one writer (`brain views --write`;
  a branch need not commit them, the default branch's check warns of a stale one, fails under `config.json`
  `views.strict`: [`docs/views.md`](docs/views.md));
- **history**: the journal (`brain journal add`, `brain journal last`) and the decision log (`brain adr new`, `brain
  adr show`), append-only;
- **identity**: the brain's people and their public keys (`members.yaml`), and the owner's signatures of the answers
  only they may give, verified with public keys (`brain identity`: [`docs/identity.md`](docs/identity.md));
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
pip install "brain @ git+https://github.com/RoJLD/brain.git@v0.3.1#subdirectory=packages/brain"
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

Before the install, the plan verifies the tag's signature (since 0.3.2, STD-3): `git verify-tag` against the
`releaser` keys of the brain's `members.yaml` (else `allowed_signers`, the file generated from them); after the
install, the commits pip recorded are checked against the one the signed tag names. The plan says
`verify   vX.Y.Z: signed by <person>`, or why not, and installs anyway unless `config.json` `engine.verify_tags` is
`true`, the owner's opt-in, which refuses an unsigned tag (`brain update --yes` then exits 1). The installer does the same
([docs/identity.md](docs/identity.md), « Signed releases »).

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
The chosen columns are kept in `<BRAIN_HOME>/tui.json`, a file of its own (`v` 1, a backup `tui.json.bak` at each save,
an atomic write): what a newer brain added to it is kept through a save, and one a newer brain wrote is shown but not
written (`brain tui` says the views are not remembered; brain update). See [docs/formats.md](docs/formats.md).

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
an editable checkout or a folder that is not at the tag, or is dirty). `brain sync`, `brain refresh`,
`brain render --write` and `brain views --write` then refuse to write, since they would render the plugin's hooks,
generate the links or write the views with another engine; under `config.json` `views.strict`, so does every command
that writes one committed view (`brain audit --write`, `brain coverage --write`, `brain features render --write`,
`brain decision view --write`, `brain modules --write`). `brain update` moves the pin of a brain without an installer of its own; in a brain that declares
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

The scout also reads four cheap norms in the AST of each Python file a change touches (`brain.norms`):
`norm.timeout` (a `subprocess.run`, `call`, `check_call`, `check_output` or `urlopen` without `timeout=`, a
`Popen`'s `communicate()` or `wait()` without one), `norm.encoding` (an `open()` in text mode, a `read_text()` or a
`write_text()` without `encoding=`), `norm.naive-time` (a `datetime.now()` or `today()` without a tz, or a
`utcnow()`, stored: made text by `isoformat()`, `str()` or an f-string, put in a dict or given to `json.dump`; not
once `astimezone()` or `replace(tzinfo=...)` made it aware) and `norm.secret-argv` (a token, password, secret or API
key variable, or a constant subscript such as `os.environ["GH_TOKEN"]`, in a subprocess call's command or its `env`,
or assigned to `os.environ[...]`: a secret travels by stdin or the keystore). A call that unpacks `**kwargs`, or
whose mode is not a literal, is not judged; `timeout=None` or `encoding=None` counts as none. What the change adds is
an `info` line by default (shown, never blocking), a NEW line under `config.json` `audit.norm_lints_strict: true`
(the owner's opt-in), which a `Justified: <path>: ...` line clears; the occurrences already in a touched file, or
moved into it from a file that no longer defines their function, make one DEFER line per file and norm to the repo's
debt item, fixed by batches (never blocking).

### Feature coverage

A shipped capability cannot miss the feature matrix (`FEATURES.md`): in a package whose `commands/` lists its own
modules (a command registry, as `brain.commands` is), each command module (not the `_` helpers) and each module
beside its `cli.py` must be named by a feature of the project's stores (check `feature.coverage`,
`brain.feature_coverage`). A feature names one when an active `implemented_by` CodeRef of it points at its file (a
symbol's CodeRef names its file), or when its title says it: `brain quiet` for a command module (each command its
`register` adds, after each console script that runs the package), `brain.stateio` for a module. `brain audit` lists
them per repo as info, never counted, in a section of their own (`feature coverage: N of M commands and modules named
by a feature; no feature names: ...`, the JSON key `feature_coverage`, a section of `notes/audit.md`). The scout makes
one the change adds a NEW line (link it, `brain features link <feature> --code <path>`: `feature.links` already
makes such a unit NEW, so nothing that passed is newly refused), and one already there that the change touches a
DEFER line to the repo's debt item; `config.json` `audit.feature_coverage_strict: true` (the owner's opt-in, default
false) makes that one a LEFT line to fix in the PR.
`--store DIR` gives the scout a worktree of the store where the change's features are linked.

### The feature matrix of each repo

Each repo of a project has its own `FEATURES.md` at its root: the features whose `repo` prop names it (`brain features
set <id> repo=<repo>` moves one), from the Feature nodes of the brain's store. `brain sync` renders the store's own
repo's; another repo's is rendered into a checkout of it, then committed there by its own PR (`brain features render
--repo <repo> --out <checkout>/FEATURES.md --write`), and `brain audit` (check `features.md`) compares each repo's
file with its own render, its fix naming the command for that repo. A checkout that is a clone of a public repo (one
of its git remotes is in `config.json` `public.repos`) gets the public render: a feature's `public_title` and
`public_id` props stand for a title or an id that names the owner or a private project (`brain features set <id>
public_title="..." public_id=feat-...`; the graph keeps both, `brain features show` prints them), and only the repo's
own code, tests and docs are shown, no spec, ADR or work item of the private brain. The render warns, line by line,
about what `brain check --public` would still refuse in it. In such a clone the check (`brain audit`'s `features.md`,
`brain features render` without `--write`) accepts the full render too, which is what the file held before the
public render existed; `config.json` `features.public_strict: true` (the owner's opt-in, default false) makes it
accept the public render only. The render has no date and sorts what it lists: the same
graph gives the same file.

### The technical reference

`brain reference --write` writes `docs/reference/`: one page per module of the store's registry (what it does, the
decisions in force on its nodes from the answered DDRs, earlier ones folded, its rules, specs, items and open
questions) and an index with the decisions no module holds; `brain sync` keeps it current once the folder exists.
`--public` renders a public repo's neutral reference by feature domain, from its features only (this repo's own is
[docs/reference/](../../docs/reference/README.md)). See [docs/views.md](docs/views.md).

### Generated READMEs

A repo opts in by holding `readme.yaml` at its root (`schemas/readme.schema.json`): the text only a person writes, what
the repo is, why, how to start, its own notes and the commands its README quotes. `brain docs render --write` then
writes its `README.md` from the engine's template (`templates/readme/README.md.tmpl`) and the facts of their sources:
the features recap (counts by status and domain, the top ones, a link to the repo's `FEATURES.md`, written too), each
quoted command's usage from its `--help`, and, for a private repo, the active specs, recent ADRs and pending milestones
that touch it; a public repo's render is neutral (the features' public titles, no record of the private brain).
`brain docs check` exits 1 when `readme.yaml` misses a field, a quoted command is gone, or `README.md` is not the
render (a hand edit, or a stale render: a feature, a command's help or the graph changed); `brain check` runs it
(a stale README is a stale view, [docs/views.md](docs/views.md)). A repo without `readme.yaml` is never read.

### Standards

The standards registry holds engineering standards as data ([docs/standards.md](docs/standards.md)): one row per
standard, its domain, statement, the profiles it applies to, the stage it is required from, how it is enforced and by
what check, the languages that check covers and how the Brain itself meets it, in catalogs (the engine's own, and a
brain's local ones). A project opts in with `projects.yaml` `standards: {profiles, stage, include, exclude,
catalogs}`; `brain standards list|show|check` reads them, `brain check --all` checks each project's opt-in, and
`brain brief` lists the project's standards as its invariants. A project without the key follows none.

### Language adapters

A repo plugs its own tools in through `projects.yaml` `repos[].tools` (`brain.langs`): for each slot (lint,
typecheck, test, coverage, format), the report file its tool writes and that report's format (SARIF, JUnit XML,
Cobertura, lcov, coverage.py's JSON, istanbul's summary), so a TypeScript or Swift product is read through its own
tools. The engine reads the reports and runs nothing: the project's CI or its developer writes them. `brain audit`
measures `lang.report` for a repo that declares `tools:` (a report missing or unreadable, failed tests, findings,
coverage under 50 %), and `brain standards check` counts a standard whose `adapter` slot a repo declares as covered on that repo's
language. A repo without `tools:` is read as before. See [docs/standards.md](docs/standards.md), « Language adapters ».

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

A brain built module by module keeps the registry of its modules in the store (`notes/graph/modules.yaml`), and each open item names its module (`props.module`, `props.modules_secondary`). `brain sync` writes `notes/modules_graph.md`: per module its phase, its items done and open, and the gaps. `brain check` warns about an open item the map does not place, and about a feature or a done item with no module (the technical reference reads them by module). A programme's registry can live in another store (`config.json` `modules.store`) and be a read copy of the platform's documents, written by an agent session: `brain modules --check` validates the imported entries, the view generates the counts and lists the divergences between the documents, `brain modules --diff` says what an import changed; the map of realisations says who realises each module and where. See [docs/modules.md](docs/modules.md).

### Waves and eras

A wave is a release's batch of work: a milestone of kind wave named by its release (`props.kind: wave`,
`props.release: X.Y.Z`, `props.week` optional), whose members are work items (`part_of`), itself part of a milestone
or an era. An era is a milestone of milestones (`props.kind: era`), whose exit is a Go/NoGo question put to the owner
once its milestones are reached (`props.exit`; `props.stage_to` and `props.serves` optional). `brain check` refuses a
wave whose release is not `X.Y.Z`, two waves of one release, an item in two waves, a wave holding a milestone, an era
holding an item, a `carried_to` that names no later wave, and a dropped wave that still holds an open item; it warns
about a reached wave that still holds one, a wave in no milestone or era, an era without its exit and an era whose
exit is due. Those rules run
in a store that holds a wave or an era; any other `props.kind` on a milestone is refused there. The kinds are in
[docs/formats.md](docs/formats.md) (« Milestone kinds »).

`brain sync` writes `notes/plan_graph.md` (beside the store's other views; only for a store with a wave or an era,
and `brain sync` is its one writer): the tree era > milestone > wave > items, each item with its status and what waits
on the owner (its `props.open`, its `external_blocker`, the pending DDRs on it), each wave's carried items first,
then the startable ones. `brain next [--json]` prints its first part at zero token: the current wave (the lowest
release not closed), its items carried from an earlier wave, its startable items, what waits on the owner, the other
open ones, then the next wave.

The version PR closes its wave (`docs/release.md`, « 1. Before the version PR »): `brain wave close X.Y.Z --carry-to
X.Y.Z+1 [--drop ID]... [--write]` carries each open item by name to the later wave (`props.carried_to`; a pending
wave, created beside the closed one when that release has none yet) or drops it, then reaches the wave; it refuses
while an item is neither. An item carried again keeps the
waves it went through (`props.carried_via`). `brain wave check X.Y.Z` is the rule alone, and `release_check.py --store
DIR` applies it to a version PR, which also wants the wave reached. `brain wave add X.Y.Z --parent MS [--week W]`
adds a wave at once (no DDR, unlike `brain milestone add`: a wave is named by its release, which the version PR
closes), and `brain wave import [--from X.Y.Z] [--write]` turns the items' free-text `props.wave` into waves: one per
release a value names (`0.2.9 (decided ...)` is 0.2.9) from `--from` on, the earlier releases (already tagged) listed
and left out, the other values (letters, free text) listed for the owner to place.

`brain wave plan [X.Y.Z] [--at-once N] [--hot NAME]... [--json]` composes a wave's lots at zero token (default: the
current wave; `brain.lots`): each open item's predicted surface (`brain collisions`': its features' CodeRefs, its
modules, the files it names), the items that share a file in one lot, run in the order of their `depends_on`; the hot
files every PR adds to (the READMEs, CHANGELOGs, `formats.md`, `FEATURES.md`, `config.schema.json`, the `changes/`
fragments; `--hot` adds one) counted apart and listed, to merge origin/main before the push. A lot that holds another's
prerequisite comes a round earlier, the lots that unblock the most first, at most the sessions cap in force less the
master's and `N` PRs verified at once (3) a round. It prints the rounds, the predicted conflicts, the hot files shared
and the items with no known surface (each a lot of its own, unchecked), with what the memory guard and the last quota
forecast say now; it refuses nothing. `brain next` shows the current wave's first round.

### Reading a brain

Sessions read a brain through its commands, not its files: the graph's YAML, the decision log, the journal and the
generated views are long, and a hand read returns far more than the question needs. Each read command takes `--json`
and needs no `research_graph` on the PATH (the graph is loaded in brain's own process, with the other stores its edges
name):

```
brain item show ID [--history] [--json]        # props in full, edges both ways, the ids its props name, its blockers,
                                               # the ADRs behind it (direct, inherited, superseded) and its specs, the
                                               # DDRs that name it; --history: its changes from git (slow on a large store)
brain items [--status S]... [--all] [--priority P]... [--wave X.Y.Z|ID] [--milestone M]... [--prop K[=TEXT]]...
            [--text WORDS] [--type T]... [--repo R] [--limit N] [--json]
brain adr show REF [--titles] [--json]         # the ADR REF names (id, title, or the start of its id), else the ADRs
                                               # that decide the node REF (a rule, an item, a spec), with their text
brain spec show REF [--section N | --toc] [--json]   # a Spec node, a Doc id (doc:<repo>:<path>::<key>) or a path
brain journal last [N] [--titles] [--json]     # the last N dated entries (default 1; 0: all)
```

`brain items --wave` takes a wave's release or id: the items whose wave it is now (carried in included), and those in
no wave whose free-text `props.wave` names that release. `brain spec show --section` takes a heading's number (`2.1`),
its key (the last part of a Doc id) or the start of its title, and prints it down to the next heading of its level.
When a session reads one of those files by hand anyway, a PreToolUse hint names the command that answers (below,
« The Claude Code hooks »).

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
first, each started by `research_graph init`, every later one with its board and roadmap beside its store and no
decision log, also when the first exists already; `schema: default` only for now) and its `files` (`{the brain's path:
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

Zero-token commands for many sessions on one brain ([`docs/merge-driver.md`](docs/merge-driver.md)):

- **`brain merge-driver`**: a local git merge driver for the paths `.gitattributes` gives `merge=brain` (`brain init`
  writes them): a generated view keeps one side and is marked for `brain refresh`, the journal and the decision log
  are unioned in date order, the graph's edges and a CHANGELOG's Unreleased section are unioned, the other graph YAML
  is merged by id, anything else as git would. The installer defines it in the personal brain's git config
  (`brain merge-driver install --apply`); `brain merge-driver replay` merges a repo's past merges again with and
  without it. A driver that cannot run falls back to git's own `merge-file`, so ours is never left without its
  conflict markers, and `brain sync` brings an earlier engine's driver line to this one (`brain.mergedriver`).
- **`brain views`**: one writer of the generated views ([`docs/views.md`](docs/views.md)): a branch need not commit
  them (`brain views --unstage` after `git add`, `--reset` before merging the default branch), `brain check` warns of
  a stale one on the default branch (fails under `config.json` `views.strict`, the owner's opt-in; a `views:` line
  elsewhere), and `brain views --write --commit`, in a
  worktree at the default branch's tip after each merge, regenerates them, checks them by the default branch's rules
  and commits them, never from a HEAD that lacks that tip (`brain.views`).
- **`brain merge-check`**: after `git merge origin/main`, the base fetched again and nothing main brought since the
  merge base lost: the lines main added to the journals, decision logs, edge files and CHANGELOGs (as content, in any
  order), the fields main changed on the graph's nodes, the nodes main has (a removal by the branch passes); exit 1
  when the branch is behind or lost something.
- **`brain collisions [--all] [--frontier] [--json]`**: the files each open branch and worktree changes, crossed with
  each startable item's predicted surface (its features' CodeRefs, its module, the files it names): the items that
  can start now, and those that wait on a branch and its session.
- **`brain brief ITEM [--class C] [--budget B] [--coordinator ID]`**: a sub-session's brief from the graph: the item
  and its subgraph, its collisions, the class's model and effort (config.json `brief.classes`), the budget, the cost
  estimate, the coordinator's id, what to do after the merge (the close-item procedure's step 5: the session that
  merges its own PR archives itself once the main checkout is pulled, the note written and its report sent; a
  coordinator archives a child whose report says merged and verified without asking again; never another running session
  or one with uncommitted or unmerged work; the owner's app setting `auto_archive_inactive_days = 7` as the
  token-free net; config.json `brief.after_merge` replaces these lines), and the definition of done and the
  never-list read from the owner's rules.
- **`brain review prep [PR | BASE..HEAD]`**, **`brain review stamp HEAD`**, **`brain review check HEAD`**: the review
  a session runs on its own PR before it reports ([`docs/review.md`](docs/review.md), `brain.review`). The packet
  (the diff, the touched files at the head, `brain audit --diff`'s output, the lenses its surfaces call for) is
  gathered at zero token; the lens agents and two skeptics per distinct finding read it; the stamp, keyed by the
  head's full sha, keeps the counts and answers the merge gate.

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
cockpit turns yellow, orange and red at each step; `brain alerts` (`brain.alerts`) raises a master past 80 % with live
children, both read from the session tree at each pass (an archived master, or all of its children archived, close the
alert at once; a session the app does not know, master or child, also ends with its recorded `SessionEnd`, while one
the app knows lives until archived, since the app resumes it on a message; the state of a transcript the app's master
has left, after a `/clear`, raises nothing, its current transcript's own state decides, assuming the app moves its
file's `cliSessionId` to the new transcript after a `/clear`, as `brain.sessions.host_for` assumes too: not yet checked
against a real `/clear` in the desktop app, and were the app to keep the old id, both would go wrong: the current
transcript's state, which then has no app id, would count no live child, so the master past 80 % now would raise no
alert of its own, while the earlier transcript's state, still matched to the app's master, would keep its stale alert
at the pct it had before the `/clear` until the master or all of its children are archived or that state is pruned
(14 days); a master the tree does not know counts while its watch state is under 6 h old). An unarchived master left
past 80 % with unarchived children keeps its alert until the master or all of its children are archived (or, for one
the app does not know, ended; archiving one child of several keeps it, with one live child fewer) or its watch state
is pruned (14 days), by design: those children still spend; the governor reminds a master past 80 % that calls
`start_session`, and lets the call through: nothing blocks a new session.

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

### Dependency probes: loud fallbacks

A capability that relies on something outside the brain (a CLI's login, a tool's last output, an index's freshness,
a channel's last delivery, a collector's last data, the last backup) should not fail silently. Each such dependency
declares a token-free probe in the personal brain's `config.json`, under `probes`, with the machines it runs on; the
engine holds the probe kinds, never a probe per dependency (`brain.depprobes`):

```json
"probes": {
  "cli-login": {"kind": "command", "argv": ["tool", "auth", "status"], "expect": "logged in", "timeout": "20s",
                "level": "error", "about": "the session archive's summaries", "machines": ["host-a"]},
  "notify-delivery": {"kind": "json-age", "path": "$BRAIN_HOME/notify/*.jsonl", "field": "at",
                      "where": {"outcome": "sent"}, "max_age": "7d"},
  "backup": {"kind": "file-age", "path": "D:/backups/*.zip", "max_age": "26h"},
  "index-ui": {"kind": "http", "url": "http://127.0.0.1:4747/", "timeout": "5s"}
}
```

- `file-age`: the newest file matching `path` (a glob) was modified within `max_age`.
- `json-age`: a timestamp `field` (dotted) of a JSON file, or of the last line of a JSON Lines file that matches
  `where`, is within `max_age` (an ISO time, or seconds since the epoch).
- `command`: `argv` exits with one of `ok_exit` (default 0) within `timeout`, its output matching `expect`. Never
  through a shell, and a shell or an interpreter as the program is refused. The output is read for `expect` only: it is
  never shown, stored or sent. Declare read-only status commands only: the alerts pass runs them unattended.
- `http`: a GET of `url` answers one of `ok_status` (default 2xx or 3xx) within `timeout`. No header is sent, a URL
  with a user or a password is refused, and the URL is never shown.

Each probe may also give `about` (what relies on it), `level` (its alert's, default warn), `timeout` (default 10s, at
most 120s) and `machines` (none: every machine). Durations read `90s`, `15m`, `26h`, `7d`; paths expand `~`, the
environment's variables and `$BRAIN_HOME`. `brain config --check` (and `brain check --all`) checks every declaration.

The probes run in parallel, each with its own timeout, and are OK, STALE, FAIL or TIMEOUT. A command that runs past
its timeout is killed with every process it started (a `.cmd` shim's program too), and a probe still running then
never holds the command at its exit. The alerts pass runs them (`brain alerts` without `--quick`, when the brain's own
project is in scope) and raises `probe:<name>` at the probe's level on the brain's own project for each one that is
not OK, so the pass's notify path sends it once, again if its level rises, and `resolved` once it is OK again; one
that goes from a state not OK to another (STALE to FAIL) keeps its alert, whose message follows, and sends nothing
new. Each run is recorded in `<BRAIN_HOME>/probes/state.json`: the
state, why, when it ran, the last OK and since when. `brain status` shows a probes row once one runs on this machine
(`--quick`: the last run), and the cockpit's health panel a line. `brain probes` runs them now (exit 1 when one is not
OK, 2 for a bad declaration); `--last` shows the last run, `--list` every declared probe and its machines, `--kinds`
the kinds and their keys.

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

### Projects the brain only reads, projects that share a root

An entry `access: read` in `projects.yaml` is a project the brain reads and never writes (its own sessions do): it
holds `title` and `access` only, no command loads or names it (`--project` refuses it), no guard reaches into it, and
`brain projects`, `brain status --all` and `brain check --all` count it. Only `read` is read only: any other value
than `read` or `write` is invalid, named as such by `brain check --all`, `--project` and the rules' scopes and packs,
and the entry is never loaded (it needs brain 0.3.0 or later on every machine: an older brain loads it as a full
project). Several projects may share a root: the first
registered owns it (its records, its decision queue, its rendered files, its repo for `brain audit`), and each next
one declares its own store, journal and decision log (the defaults are the owner's: until it does, it is not loaded,
and `brain check --all` says what to declare). A first entry the brain skips for its `access` value (a typo, or
`access: read` with a `root:` still there) keeps owning its root, so the next one never takes it over. Its board and roadmap sit beside its store (`prog/graph` writes
`prog/kanban_graph.md`), as do those of a project's second store. At such a root, `brain sync`, `check` and `refresh`
cover every project registered there, and `--store prog/graph` runs as the project that lists that store.
`examples/projects.yaml` has both.

### Edges between stores

An edge of a store may name a node another store of the registry holds (every store of every registered project on
this machine; ids are unique across them): a programme's items kept in a parent project's store keep their edges to a
child's milestones, specs and decisions, and the parent's milestones group the children's. `brain item link` and
`brain item add` (`--milestone`, `--after`, `--spec`, `--adr`) accept such an id as one end, the other being the
store's own. Every brain command that runs research_graph on the store gives it the stores holding those ids
(`--foreign-store <project>:<store>=<path>`, `brain.crossstore`; nothing for a store whose edges name only its own
ids), so the store loads and its board and roadmap name the other store's node with its label
(`wi-x (parent:notes/graph)`). That holds for a project's own stores too: a store listed after its first covers no
decision log, and an edge of it to an ADR or SDR stub its first store derives (an item `decided_by` an ADR of
`notes/decisions.md`) resolves there, accepted by `brain sync` and `brain check` since 0.3.2 (0.3.0 and 0.3.1
refused it). `brain check --all` reads every edge of every store and refuses one whose end is in no
store of the registry on this machine (the store's own check refuses it too, as before), and counts the edges between
stores; a brain's own root, checking its registry without `--all`, warns of it.

## The Claude Code hooks

`src/brain/adapters/claude/hooks/` is package data: `hooks.json` and a `.sh` launcher per hook, each running its `.py`
entry with `$BRAIN_PYTHON`, else the brain command's venv (`<BRAIN_HOME>/venv`), else `python3`/`python`. A personal
brain whose `source/packs.yaml` gives its core pack `hooks:` gets them copied into its own plugin by
`brain render --target claude --write`, at the version it pins; `inject-rules.sh` injects the files of config.json
`rules`, read from the flat `hooks/contract.txt` the render writes beside the hooks (the hook contract,
[docs/formats.md](docs/formats.md#the-hook-contract)). The guards never block a session on an error: without Python,
the call goes through. Each hook passes its `brain_version` to the Python it starts, and the SessionStart health says
when a session's plugin copy and the engine differ, or when two `.brain` folders exist.

A hook costs every tool call its time, so the launchers start nothing they do not need: they read their JSON and find
Python with bash builtins (`hooks/common.sh`, no `$(...)`), and `guard.sh` starts Python only for a shell command that
may write, names `gh`, a program of the owner and power guards, `claude` then `plugin` or `skills` then `add` (whatever
comes between: a quoted `claude.exe`, global options, a line continuation), or git other than to
read (`git [-C DIR] status`, `log`, `diff`, `show`, `rev-parse`... without `--output`: `brain.guards.GIT_READS`,
checked against the guards' tables). In Python a guard reads the registry through libyaml and does not import `urllib.request`.

**The read hint** (`readhint.sh`, `brain.readhint`, PreToolUse on Read, Grep, Bash and PowerShell) never refuses: when
a call reads a registered brain's graph YAML (a store's `nodes/` or `edges/`, or the store), its decision log, its
journal or a generated view (`*_graph.md`, `decision_queue.md`, `FEATURES.md`) by hand, it adds one line of hook
context naming the command that answers, with the id the call looked for when it names one (`brain --project P item
show wi-x`, `brain adr show`, `brain journal last`, `brain items`, `brain next`, `brain decision pending`, `brain
features`). A shell command counts only when it reads (`grep`, `rg`, `cat`, `head`, `tail`, `sed`, `awk`,
`Select-String`, `Get-Content`...); "registered" is a project of the registry or a worktree of its checkout (read from
the worktree's `.git` file, no git started). A call whose JSON names none of those files stops in bash builtins:
measured on Windows, the launcher then costs what starting bash costs (about 0.2 s, as `budget.sh` on every call), the
Python path about 0.6 s, taken only on a hand read of a brain file; on a shell call it runs beside `guard.sh`.
Read and Grep had no hook before it, so it is **opt-in**: `brain render --target claude` (`brain sync`) registers it
in the core plugin's `hooks.json` only when the brain's `config.json` says `"hints": {"read": true}`; by default it is
not registered and no call pays its cost (the script ships either way, `brain.render.OPTIONAL_HOOKS`). To turn it on,
set the key, run `brain sync` and restart the sessions; while it is on, `BRAIN_READ_HINT=0` turns it off in a
session.

Two guards keep what a session brings in and what it records clean (the runbook: [`docs/guards.md`](docs/guards.md)):

- **Third-party kits** (`guard.sh shell`, check `third-party`): a session never installs or runs a third-party kit. A
  download fed to a shell or an interpreter (`curl ... | sh`, `curl ... | bash /dev/stdin`, `bash <(curl ...)`, `sh
  -c "$(curl ...)"`, `eval $(curl ...)`, `bash <<<"$(curl ...)"`, `iwr ... | iex`, `iex (irm ...)`), `claude plugin
  install` (and its `--marketplace`) and `claude plugin marketplace add` from a source outside the owner's list
  (config.json `adapters.claude.sources`; the brain's own marketplace always passes) and `skills add` (`npx`, `bunx`,
  `bun x`, `pnpm dlx`, `npm -w pkg exec`, `corepack pnpm dlx`; npm's Windows shims too: `claude.cmd`, `skills.cmd`,
  `npx.cmd`, `pnpm.cmd`, their `.ps1` and `.bat`) are refused, each an action for the owner's queue with its exact command
  (`brain queue add --kind action --guard <ref>`). A download to a file (`curl -o`) or read as data (`python3 analyze.py <(curl ...)`)
  passes; what the owner types in their own terminal is never seen. (`brain.guards`)
- **Conflict markers** (check `markers`): a git commit, or a merge, rebase or cherry-pick `--continue`, that adds
  `<<<<<<< `, `||||||| `, `>>>>>>> ` or a bare `=======` is refused with the file and line: the staged lines, commit
  `-a`'s, the paths the commit names, an earlier `git add`'s (`-A` or `-u` with no path: the whole worktree), and,
  during a merge, only the lines new against every parent; `brain check` fails on a store, journal, decision log or
  record file that holds one. A Markdown or reST setext heading (`=======` under a line of text; `.md`, `.qmd`, `.Rmd`,
  `.rst`, and `.txt` under a title no longer than the underline, so a half-resolved `requirements.txt` is still
  refused) and a file under a `fixtures` folder pass; a commit in a folder that is not yet a repo passes, as for git
  (any other git failure is logged in errors.log).
  (`brain.markers`)

Two of the PreToolUse hooks keep the owner's say over how sessions run (the runbook: [`docs/guards.md`](docs/guards.md)):

- **Session settings** (`guard.sh tool`, `brain.guards`): a session that changes Remote Control or a permission mode
  (`set_remote_control`, `set_session_permission_mode` under any MCP prefix, the app's `set_setting` for a Remote
  Control key) is refused, whatever the value, and the exact action goes to the owner's queue (`brain queue add
  --kind action --guard <ref>`). Its category, `security-settings`, is never grantable (`brain permissions`), and
  `BRAIN_GUARD_ALLOW` does not lift it, not even `all`: the owner switches it in the app.
- **The usage governor** (`governor.sh`, `brain.governor`), before `start_session`, `Agent` and `Workflow`: it reads
  the cached quota readings (`brain usage quota --observe`), the sessions running and the brainstorms open on the
  machine (the desktop app's session files, else the session records), and the machine's committed memory and available
  RAM. It asks the owner
  from `warn` % of a quota window, refuses from `critical` %, refuses a new session past the parallel sessions cap
  (the smaller of `sessions` and what the week's room pays for), a new brainstorm past `brainstorms` (every project
  counted; a project's `usage: {brainstorms: N}` in `projects.yaml` lowers it for itself, never raises it), a new
  session or workflow from `memory` % of committed memory or under `memory_available_gb` GB of available RAM (an opt-in floor, 0 by default; both
  shown by `brain usage guard` and `brain status`, the refusal naming the one), or while the newest quota reading is older than
  `fresh_minutes`. The thresholds are config.json `usage.guard`; `brain usage guard` shows what each tool would get
  now. A refusal names its reason and the owner's override: `brain usage allow [--hours H]` in their own terminal
  (the guards refuse it to a session), or `BRAIN_GUARD_ALLOW=usage`. Its decision takes under 50 ms.

The quota conversion (`brain usage quota`) is per plan: only the readings of the plan in force (config.json
`usage.plans`) count, and until the plan has 3 converted readings it says "uncalibrated", does not convert the week and
estimates the 5-hour window from its latest reading and the ledger's cost since.

The token ledger (`brain usage`) reads each session's subagents and workflow agents with it
(`<session>/subagents/agent-<id>.jsonl` and `<session>/subagents/workflows/<run>/agent-<id>.jsonl`): their cost is in
the session's cost and hours, so the quota forecast and the governor count it, and a message is counted once, as the
subagent's, should the parent's transcript copy it. `brain usage` says whose the cost is (main threads, subagents,
workflows), `--by workflow` lists each run (its agents, phases and the session that launched it) and `--by agent` each
agent's label (the `description` of its `.meta.json`, else the run's `journal.jsonl`). `brain usage quota` measures
the cost of a session-hour, the agents' included, as information: the governor's parallel-sessions cap uses it only
with `usage.guard.session_hour_measured` true (default false), and then when it is above `usage.guard.session_hour_usd`;
`brain usage guard` shows the measured value and whether it is applied.

The session record (`brain capture`, the Stop hook) holds the brief's `task_class` (trivial, standard, strategic,
brainstorm) and `ultracode` (whether it was on at any time), so the ledgers tell ultracode spend apart. The capture
hooks run `brain.capture` (`capture.sh <event>` runs `hooks/capture.py`, which calls it with the brain command's
venv): it reads the hook's JSON on stdin and appends the session events, the session-record snapshots and the action
records to `<BRAIN_HOME>/ledger` at zero token; it prints nothing and never fails the session (its errors go to
`ledger/errors.log`, moved aside each month, or past 1 MB, as `errors-YYYY-MM.log` and kept six months;
`BRAIN_CAPTURE=0` turns it off). The session snapshots, states, reports and plans under `<BRAIN_HOME>/sessions` and the
budget watch's states are written through `brain.stateio` (a backup beside each, an atomic write; a newer brain's left
to it): [docs/formats.md](docs/formats.md) gives each file's policy and each log's retention. With `config.json`
`integrity.sidecars: true` (or `BRAIN_STATE_INTEGRITY=1`; off by default) each of these files gets a sha256 sidecar
(`<name>.sha256`), checked at each load: a file that rotted is set aside with a note.

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

**Command adoption** (`brain perf --usage`, `brain.adoption`, zero token) crosses the CLI registry (every command,
and each subcommand of a family, as the exec ledger names them) with those events and with this machine's session
transcripts of the period (28 days by default): each command's runs, split into those a session typed itself in a
shell and the others (a hook, a scheduled task, a script); the commands that never ran; the Read, Grep and shell reads
of a registered brain's graph YAML, decision logs, journals and generated views that a read command answers; the hand
edits of the files a command writes or regenerates; a feature marked have whose command modules never ran; the
sub-sessions started against the runs of `brain brief` and `brain wave plan`. Each gap comes with what to propose (the
read hint, a hook wiring, a procedure line, wire, document or retire); nothing is refused. Run it after each wave. It
is a flag of `brain perf` rather than an audit lens because it reads what ran on a machine, as perf does, not a repo's
code.

```
brain perf --usage [--since 28d] [--top N] [--json]
```

## Data classes and the vault

Every store of a brain declares a data class in `config.json` (`classes.stores`: public, private, confidential,
sealed, resident, secret, `tenant:<id>`), and the class says where it may go and how; `brain check --all` refuses a
store without a class and a destination its class forbids, and `brain init` writes a starting block. Each store the
engine writes under `$BRAIN_HOME` has a suggested class and a format class: one a brain does not declare takes its
suggested class (never looser than sealed) and is noted, never failed (`brain classes --suggest` prints the lines to
declare), and the desktop app's session metadata is read through a closed list of keys, never its texts. What leaves a
machine is sealed client-side to public keys (`brain vault`: age, gpg as the fallback), to a device key per machine,
kept in the OS keystore, and an offline recovery key: two recipients at least, proven daily by a canary per recipient
(`brain health vault`). When the recipients change (a lost machine, a revoked heir, a rotated key), `brain vault
reseal` seals the kept copies again to the current set. Opening, drilling, and creating or rotating a key are the
owner's acts, refused in an agent session. The owner's steps, the canary's scheduled task per system, the rotation
and what to do with a lost key are in the runbook, [`docs/vault.md`](docs/vault.md). Until a data remote exists,
what leaves waits in a sealed local spool: `brain spool push`, run by hand, seals the changed stores of its set (the
ledger, the usage, the session records by default) after a secret scan, sends them to `spool.remote` when one is set,
each copy checked by sha256, and `brain health spool` gives the last push's age.

```
brain classes [--check] [--suggest] [--matrix] [PATH...]
brain vault status | seal STORE | canary | recipient add NAME [--replace] | recipient remove NAME | reseal [--apply]
brain vault device init [--rotate] | device forget-previous | open FILE | drill RECIPIENT
brain health vault
brain spool push [STORE...] [--dry-run] | status | verify
brain health spool
```

## Identity: members and signed answers

A brain may declare its people in `members.yaml`, beside `config.json` (`schemas/members.schema.json`, class
confidential): each person's `person_id`, public SSH ed25519 signing keys and age recipients, their accounts, the
organizations and tenants, and their roles per project or tenant. An answer to a decision of the owner-decides class
(money, keys, accounts, visibility, heirs, scheduled tasks) may then carry a detached signature,
`records/ddr/<id>.sig`, made by a decider's key in the owner's own terminal (`ssh-keygen -Y sign`, namespace
`brain-decision`); the engine only verifies it with the public keys, and never generates, reads or prints a private
key. An answer relayed by a session is marked unsigned on the board (`brain decision view`), and `asked.by` names
the asking session, else the owner: never `unknown`. `brain check` reports the unsigned answers and the signatures
that do not verify as warnings, as errors under `config.json` `identity.require_signed: true`; without
`members.yaml` nothing is checked. The owner's commands (making the key, declaring it, signing a batch):
[`docs/identity.md`](docs/identity.md).

The `releaser` role's keys verify the engine's release tags: `brain identity allowed-signers --write` generates
`allowed_signers` beside `config.json` (namespace `git`), which `brain update` and the installer read before an
install ([docs/identity.md](docs/identity.md), « Signed releases »).

```
brain identity check | unsigned [--write DIR] [--json] | payload ID | attach SIG|DIR... | allowed-signers [--write [FILE]]
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
fast paths stamp it on their events; `tests/test_selftime.py` checks the two agree). Which number moves is
[`docs/release.md`](../../docs/release.md)'s version policy: before 1.0 the middle one for a change an owner must act
on or a format that moves, the last for what needs nothing; `installer/release_check.py` (CI's `release-check`)
refuses a patch with a schema change or an `### Upgrade` step beyond the standard ones, an `### Upgrade` that leaves
out a standard step, a section with no theme, and a section of either CHANGELOG that repeats an entry an earlier one
released. A PR never edits a CHANGELOG: it writes its entry as a fragment, `changes/<item>.md` here (`changes/` at
the root for research-graph; the folders' READMEs), and the version PR compiles them with `installer/changelog.py
compile X.Y.Z --theme T --write`; `release-check` refuses a malformed fragment, a `## Unreleased` section and a standard
step two Upgrade fragments ask on every PR, and a fragment left uncompiled on a version PR; `release_check.py
--preview` (CI's advisory `release-preview`) says on every PR whether the next release would be a minor one. The CHANGELOGs are `merge=brain` in `.gitattributes`, a net for a
merge back from `release/X.Y`.

## License

The Business Source License 1.1, from version 0.2.2: `LICENSE` (its parameters at the top) and `NOTICE` (the credit to
keep). Its Additional Use Grant allows you to use, modify and run the brain command for your own work, as a person or
an organisation, and to reuse it in your own products, provided each product gives a visible credit to Brain and its
author in its documentation or its about screen (`NOTICE` gives a credit line) and the `NOTICE` file is kept with every
copy you distribute. Offering it to third parties as a hosted or managed service needs a commercial licence from the
licensor. Each version changes to the Apache License 2.0 four years after its release.

Versions 0.2.0 and 0.2.1 were released under the MIT License and stay under it. `research-graph`, the graph engine
this package depends on, stays under the MIT License (the repo's root `LICENSE`).
