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
pip install "brain @ git+https://github.com/RoJLD/brain.git@v0.3.2#subdirectory=packages/brain"
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

The cockpit (`brain tui`) runs once per machine (`<BRAIN_HOME>/locks/cockpit.lock`: a second interactive cockpit is
refused, `--once`, `--json` and `--detail` read beside it). It has one tab per question, each on its key: `0` the overview, `1` the queue, `2` the sessions,
`3` the frontier, `4` the milestones, `8` health (alerts on top; audit debt, stacks and index, and the exec times), the
comma the settings.
The overview shows one card per tab, what counts in it in a few lines: the band now, the sessions asking, the nearest
milestones, what can start, the open alerts. Enter or a click opens its tab, already filtered as the card says, whatever your
filters and search (a filter that is not saved and goes when you leave the tab); the arrows move between the cards.
Ideas (`5`), lessons (`6`), features (`7`) and resources (`9`) arrive with their items, and until then their key says
so. The bar shows what waits in each tab, in digits and signs: « 1 Ada's queue 3 » the band now, « 2
Sessions 1! » the sessions asking, « 8 Health 2 » the open alerts. A click on it, `ctrl+pageup` and
`ctrl+pagedown` also change tab, and Escape goes back one step at a time: the search, a full view, then the overview. A tab with several views says so in its toolbar:
`v` or a click changes it, and the overview's other views are the grid of every panel, where open alerts take a whole
row, and the digest. `--tab NAME` starts on a tab, and with `--once` or `--plain` prints its panels alone (the overview:
its cards). Under 120 columns or 30 rows the bar is reduced to its numbers (`0 1 Ada's queue 3 2 3 4 8`), the cards take
one column, the grid is not offered and the health frames stack. The last tab and each tab's view are kept
in `<BRAIN_HOME>/tui.json`.

The settings tab (the comma) shows every setting with its value, the file or variable it comes from and how it changes,
page by page on its left: Cockpit, Identity, Brain, Permissions and Setup. The cockpit's own settings live in
`<BRAIN_HOME>/tui.json` and are edited there with Enter: the theme, the timezone, the language, how often the files are
checked (`refresh`) and the probes run (`probe`; `--refresh` and `--probe` win for one launch), and each panel's free
title; a wrong value is refused, an empty one sets the default back, and each change applies at once. The brain's
settings (`identity.display_name` and the owner, `$BRAIN_HOME`, the personal pointer, `config.json`, the registry, the
engine pin, the profile, the stacks, the notification routes, the code index, the scope types, `permissions.yaml`,
Claude Code's settings) are only shown with the command that changes each: Enter says it, nothing is written from
there, and a secret is named, never shown. `brain tui --once --tab settings` prints the same pages (`brain.settings`).

The Modules page (SIGMA-15) lists each module of the brain's catalogue (`brain catalogue emit`, catalogue/v1) with its
state on this machine and where it comes from (`brain mod list`: the preset, `config.json`, `profile.json`, pulled),
its cost (RAM, disk, VRAM, download), what it needs and its fallback, then the distributions. Enter on a module that
can be switched asks on or off (and off with what needs it, `--cascade`), shows `brain mod`'s plan (the dependencies
pulled, what turns on and off, its cost), then `y` writes this machine's `profile.json` (`--apply`), logged as the
owner's. Off keeps the module's data and configuration: only the profile changes. A core module is always on. Adding
or removing a distribution, uninstalling a module with a sealed archive of its data, and refusing a module the machine
cannot hold arrive later.

The Setup page holds the setup wizards (`brain.wizards`), one per row, in the order a new brain walks them: the first
run (the profile Lite, Default or Recommended), the stacks to enable, the modules, a project to add, the notification
channels (ntfy, Telegram and its chats, the routes), the permissions, the machines and their facts, the code index, a
new brain from a domain template, Claude Code's settings and the checks. Each wizard is the brain's own commands,
never a hidden edit: Enter asks its choice when it has one (and the folder of a new brain, an absolute path), then
shows its exact command. A wizard that writes shows its plan already run (`brain profile set default`), and `y` runs
the apply (`... --apply`), never after a plan that failed; a wizard that reads runs its one command on `y`. Each runs
as the owner's, logged in `<BRAIN_HOME>/ledger/cockpit-<month>.jsonl`, refused in a Claude Code session's shell; the
notification and code index wizards run for the project the cockpit shows. What stays
the owner's stays a plan with its command: Claude Code's settings (`install.ps1 -Apply`, in your own terminal), a
project added to `projects.yaml` and a permission granted (a branch and a PR). A secret is never typed in the cockpit:
you set it as an environment variable (or in the system keyring), and the wizards name it, never show it.

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
`audit: {max_lines: 1000, complexity: 15}`. A frozen store (a brain an older engine wrote, under `tests/fixtures/stores/`
in any test folder) is data a test reads, not code or docs: the shape signals and the docs set leave it out; any
other fixture, a fake binary a test runs included, is reviewed.

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

And it reads what a change of a schema narrows (`brain.schemadiff`, wi-brain-schema-diff): a JSON Schema
(`*.schema.json`) or a graph store's `schema.yaml` whose new version refuses what the old one accepted (a property
removed, a field newly required, an enum or a type narrowed, a bound tightened, a type or a status removed). A
`schema.narrowed` line is an `info` line by default, a NEW line under `config.json` `audit.schema_diff_strict: true`,
and justified when the PR's `Compat:` line resolves it (`Compat: migration <id>` with the format's `v` bumped and its
fixture, or `Compat: breaking <adr-id>`). `brain schema diff --against <tag>` prints the same over a tag's range
([`docs/formats.md`](docs/formats.md), « The schema diff »).

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

`brain reference --write` writes `docs/reference/`: an arc42 skeleton, its twelve sections from the graph (goals and
milestones, constraints, context, strategy, building blocks, runtime, deployment, concepts, decisions by module,
quality from the milestones' triggers and tests, risks and debt, glossary) with the prose of the repo's reference YAML,
and one page per module of the store's registry (what it does, the decisions in force on its nodes from the answered
DDRs, earlier ones folded, its rules, specs, items and open questions); `brain sync` keeps it current once the folder exists.
`--public` renders a public repo's neutral reference by feature domain, from its features only (this repo's own is
[docs/reference/](../../docs/reference/README.md)). `brain reference --asof POINT` renders it as of a wave, a milestone,
an era, a date or a git ref, read from git, with what changed since the wave before and a pending milestone's
target view, under `BRAIN_HOME/views`, never into the repo. See [docs/views.md](docs/views.md).

### The documentation graph

`brain sync` also writes `notes/docs_graph.md` for a store with the `Doc` type ([docs/docs-graph.md](docs/docs-graph.md)):
every doc file with its kind (Diataxis, generated and dated specs apart), last commit, declared owner, the nodes it
cites and the docs that cite it; the links declared between docs (`depends_on` with `props.reason`); and the docs to
re-read (`doc.stale`): a hand-written doc whose cited node or declared parent changed after its last commit, by
section. `brain check` warns on them, the scout (`brain audit --diff`) names the docs a change should have re-read,
and `brain docgraph emit` writes the graph as a [docgraph/v1](docs/docgraph.md) document.

### The documentation graph's contract

`docgraph/v1` ([docs/docgraph.md](docs/docgraph.md)) is the neutral, public format of a documentation graph: its
decisions, documents and sections, milestones, criteria, items, changes, tests, threats and modules, typed edges named
as the Brain names them, a source on every node and derived edge, declared links with their reason, and the findings
of named checks every producer and reader mean the same way. Any program may emit it (a repository's own docs
command, the Brain's doc graph); `brain docgraph validate FILE...` checks a document against the schema
(`schemas/docgraph.schema.json`) and `brain docgraph checks` lists the named checks. Neither needs a brain.

A brain reads the documents of the projects it only reads (`access: read`) without writing to them:
`brain docgraph pin PROJECT --from CLONE --ref REF --file PATH` copies the project's document from a local clone at a
commit (`git show`, never a checkout), validated, to `docgraph/PROJECT.json`, committed by PR; `brain docgraph join`
reads the brain's own graph, those pinned copies and the documents the brain keeps for itself as one graph, ids
namespaced by project (`item:example/25`), and runs the named checks again across it, where an edge of one document
reaches a node of another. The technical reference gives each pinned project a page (`docs/reference/read/`).

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
The other consumers read the same applicable rows, by enforcement level: `brain review prep` adds a **standards**
lens of the `review-lens` rows to its packet (`brain standards lenses`); `brain audit` measures `standards.gap` (P2,
never in the scout), a row whose check covers neither a repo's language nor a slot its `tools:` declares;
`brain standards rules [--write FILE]` prints the `rule` rows as a section of rules text (only what needs
judgement); `brain standards ci [--write FILE]` prints a GitHub Actions skeleton from the `check` and `measure`
rows with an adapter, one step per slot and repo in its folder, each failing until it is filled with the project's
own tool.

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
coverage. `brain test --changed` runs the test modules a change touches by that summary first (shadow mode: missing
or stale evidence widens the answer to the whole suite, which the CI runs before the merge). The rules:
[docs/tests-graph.md](docs/tests-graph.md).

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
then the startable ones. `brain next [--explain] [--json]` prints its first part at zero token: the current wave (the
lowest release not closed), its quick wins, its items carried from an earlier wave, its startable items, what waits on
the owner, the other open ones, then the next wave.

Each group, here and in the view, is ranked (`brain.ranking`): the owner's priority first (a confirmed one before the
same one proposed), then the owner's explicit order (`props.order`, a number, lower first), then WSJF, value over
effort. The value is derived from the graph by default: a base of 1, plus the value of the features the item delivers
(`delivers` edges; a feature's `props.value` high 3, medium 2, low 1), plus 1 when it moves a milestone of the roadmap
(`part_of` a milestone that is not a wave or an era), plus 0.5 per open item that depends on it. The owner overrides
it with `props.value` (high 5, medium 3, low 1 on that scale) and `props.value_reason`; `--explain` lists the items
whose value the owner set, so that frequent overrides show the weights are wrong. The effort is the hours of the
item's size (« Item sizes »), an unsized item counting as M. A quick win is a carried or startable item of size S
whose value is high (the owner's, or a derived value of 4 or more); the wave's quick wins are named on a line of their
own at its top, the rows keeping the rank's order. `brain forecast` derives an item's value the same way. `--explain` puts
each score's parts under its item: `score 12.5 = value 3.75 (base 1 + features 2 + unblocks 0.75) / 0.3 h (S)`. The
cockpit's frontier takes the same order by default, sorts by score on demand, and its column chooser adds the size,
the value and the score. Every number is a written setting of `brain.ranking` (`SCORE`, `VALUE`, `HIGH`), which
`brain forecast` shares for its tie-breaks.

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

### Item sizes

Every work item carries a size, the judgement of the session that writes it: `props.size` (`S`, `M`, `L`, `XL`) and
`props.size_reason` (one line). The scale, until the recalibration against the actuals moves it: S under about 0.3 h
of active time, M up to about 0.8 h, L up to about 2 h, XL beyond (to be split when possible); `brain.sizing.HOURS`
holds it as the hours the ranking reads. `brain item add ID --title T --size M --size-reason "..."` gives both (a size
without its reason is refused), `brain item set ID size=L size_reason=...` changes them (any case; a size off the
scale is refused). `brain item add` stamps a work item `props.created` (today) and, without `--size`, prints the
`brain item set` line that sizes it (`--prop size=m` follows the same rules as `--size`). `brain check` warns, never
fails, on an open item stamped `created` that carries no size, on an open item whose size is off the scale (a hand
edit; an edit that leaves the size alone is not refused), and on an open item with a size but no `size_reason`. The
proposals the engine writes itself (a lesson's prevention item, an audit's debt item) carry no stamp: the session that
adopts one sizes it. Items written before the rule carry no stamp: a
session sizes them once, in batches, reading each one (a script cannot guess a size: the free signals predict an
item's cost poorly).

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
brain adr target [--needs] [--json]            # the one-way-door ADRs against the register of future needs
                                               # (docs/adr-target.md: Scope, Target compatibility; advisory)
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

**Choose your modules at the start** (the three screens, offline and with no telemetry; `brain.firstrun`):
`brain init ~/my-brain --owner "Your name" --interactive` asks who you are (a preset of the catalogue: Lite, Default,
Recommended, or a persona of a private catalogue, `--catalogue FILE`), shows your machine (what runs here and what is
recommended, from the probe), then lets you adjust (each module's box, its cost, its dependencies, what it pulls;
what the machine does not hold is refused). It ends on the same choice as one command (`--preset ID --with MODULE
--without MODULE`), which plans it without the screens. The choice is brain commands (`brain profile set BASE`, then
`brain mod disable|enable ID`, each `--apply`): the plan shows them, `--apply` runs them in order and logs each one
in `<BRAIN_HOME>/ledger/setup-<month>.jsonl`. What must be downloaded (a pip extra) is named, never fetched. The
catalogue is `brain catalogue emit`'s ([docs/catalogue.md](docs/catalogue.md)).

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
decision log, also when the first exists already; `schema: default`, the brain's base, or `layers: [records,
research, ...]`, its schema composed from research_graph's catalogue of layers with what they require and the
template's own layers, `layers/<name>.yaml` in its folder: `research_graph layers`) and its `files` (`{the brain's
path: the template's file}`, `""` for an empty one), rendered with `{owner}`, `{owner_q}` (quoted for YAML or JSON),
`{name}`, `{title_q}` and `{stage}` (`--stage`). It must write what config.json names (`projects.yaml`,
`rules/global.md`, `source/packs.yaml`, `memory/`, `records/`); the engine writes config.json, the graph stores and the Claude
marketplace itself. `--template DIR` takes a folder of your own holding one. A template is public data; the owner's
records live in their own brain. A template may `extends` one of the engine's (its files, appends, graphs and classes,
to which it adds or replaces its own: a file of the same path, its `graphs` when it gives some) and `append` a
fragment of its own to a file the base writes (`{the brain's path: the fragment}`; a YAML file must still read as
YAML). It may also `takes` parts of another engine template instead of extending all of it (`{the template: [the
brain's paths]}`: each path's file, or the fragment it appends there, from that template's own manifest, never its
chain, graphs or classes), so what that template adds later reaches it only when it names it.

### A project's brain, by profile

When the brain is a product's own repo, a profile's template starts it with what the profile needs
(`wi-brain-project-templates`; the standards registry, [docs/standards.md](docs/standards.md)):

```bash
brain init ~/my-tool --owner "Your name" --template cli --stage mvp --apply
```

| Template | The profile | The graph's layers (`research_graph layers`) |
|---|---|---|
| `cli` | a command-line tool | work, decisions, records, lessons, code, docs_tests, features |
| `local-client` | a local client (a desktop or mobile application with its own data) | the same |
| `service` | a service (a server, an API, a worker) | the same, operations and fleet |
| `data-pipeline` | a data pipeline | the same, data and operations |
| `research` | a research project | work, decisions, records, lessons, ideas, research, data, code, docs_tests |

Each one is the generic brain (its files unchanged), plus:

- the standards selection in `projects.yaml`: `standards: {profiles: [<profile>], stage: <--stage, default
  prototype>}`, so `brain standards list --applicable`, `brain standards check` and `brain brief` read what applies;
- the CI jobs, `.github/workflows/ci.yml`: the tests with their coverage (JUnit and Cobertura reports, a floor of
  50 % the owner raises as the stage moves) and compat-prev, the last tag's tests on the PR's code;
- the test harness, `tests/conftest.py`: a virtual clock (`clock`), fault injection (`faults.fail(module, "name",
  after=N)`) and the old formats' fixtures (`old_formats("fmt")`, `fixtures/formats/<format>/v<N>/older.*`), with its
  own tests, so the CI is green from the first commit;
- the format registry's skeleton, `docs/formats.md` (tolerant readers, strict writers; a format that moves is a minor
  version);
- the issue template, a task form in the brain's GitHub issue templates (reference, context, acceptance,
  dependencies, an estimate marked (e) with its author and date, the exit criterion served, a proposed owner), and
  the ADR template among its docs' templates (scope, target compatibility, a precise « Revisit if »): `_software`'s
  `issue-task.md` and `_project`'s `adr.md`;
- the boundary's rule for `.github/**` (the engine side: nothing private in it).

The bases `_project` (the ADR template: nothing of a code host, so a project that is not code, or not on GitHub, extends
it alone) and `_software` (the CI, the issue template and the `.github/**` rule, the harness, the format registry,
the code layers) are what the profiles build on: `cli`, `local-client`, `service` and `data-pipeline` extend
`_software`; `research` extends `_project` and `takes` the parts of `_software` it uses (all its files today, not its
graph, whose layers are its own). `--template` does not take a base. The CI and the harness are Python's first:
another language replaces their steps and keeps the jobs.

The profiles' names and the stages `--stage` selects are typology and stage ids, as are the graph layers'
`lifecycle` ids (`research_graph layers`): they follow one typology catalog still to come
(`wi-brain-typology-catalog`), which maps the profiles to the layers' typologies and the standards' stages to the
layers' (`explore`, `build`, ...). An id this engine does not know in a brain's `standards:` selection, written by a
template of a later catalog, is tolerated: a note in read mode, an error only in strict mode (CI) (`--stage` itself
takes this engine's stages).

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
one is named; `settings.titles` there gives any panel a free title (the settings tab edits both). `identity.owner` stays the id `--by` writes and the
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
- **`brain merge-ready PR`**: the merge gate, before `gh pr merge`: the PR open and not a draft, main not moved under
  a file it touches since their merge base, `brain merge-check` on a head that merged main, every CI check green on
  the head, the review's stamp for the head with no finding open, the public check's stamp for a public repo, nothing
  private in the PR's title and body; exit 0, a stamp and the head to merge (`gh pr merge --match-head-commit`),
  else the list of what blocks
  ([`docs/merge-driver.md`](docs/merge-driver.md)).
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

### The coordinators' hand-over

A coordinator hands over to the coordinator it starts: a hand-over note, then Remote Control on for the successor and
off on itself, two calls the guard lets through only when its conditions hold ([`docs/guards.md`](docs/guards.md),
Remote Control's three exceptions). `brain handover` (`brain.succession`, machine-wide) scripts the note and checks
those conditions before the calls, at zero token, from the files the guard reads:

- **`brain handover write [--from FILE|-] [--successor NAME] [--id ID]`**: the note,
  `<BRAIN_HOME>/handover/coordinator-<date>-<name>.md`, whose first line is `From <app id> (<name>), <date> UTC` (the
  guard reads the first app id of its opening as whose note it is), then the successor's name and the body.
- **`brain handover check [--id ID] [--successor ID] [--json]`**: each condition (a coordinator by name or a chain
  root, started by one, its note under 6 hours old, its successors live and detached), whether `on` and `off` would
  pass, and the predecessor, which an incoming coordinator archives first (a session's own archive is refused); exit
  1 when the hand-over would be refused, 2 when the app's files cannot be read.
- **`brain handover root [ID] [--reason TEXT] [--clear]`**: the owner's, in their own terminal (refused in a Claude
  Code session's shell, and by the guard to every session, like `brain usage allow`): a session the owner started
  (no parent in the app's files) marked a chain root, `<BRAIN_HOME>/handover/roots.json`. A root hands over without a
  coordinator's name, and the coordinators it starts pass the parent condition through it, until `--clear`; a
  marked id that a session started, or that the app's files do not know, is no root. No ID lists the marks.

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
at the first pass that finds it. Off Windows, the alerts' Task Scheduler folders are skipped. One pass runs at a time
per machine (`<BRAIN_HOME>/locks/alerts-pass.lock`, `brain.shutdown`): a pass that starts while another runs (a
logon pass beside the 15-minute one) is skipped, exit 0.

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

### External calls: retries and breakers

The engine's calls to services it does not run (GitNexus's API and MCP endpoint, docker in `brain index`, the ntfy
and Telegram channels, `git ls-remote` for the update check and `brain tidy --remote`) go through one helper,
`brain.net`. Each keeps its own timeout. A read that fails quickly (a refused or reset connection, a DNS miss, an
HTTP 429, 502, 503 or 504) is tried again twice, after a wait that doubles from 0.5 s with full jitter; a POST (a
notification, GitNexus's analyze) only when it was surely not handled (a refused connection, a DNS miss, an HTTP 429
or 503), so that nothing is sent twice; a timeout is never tried again. A call that finds the service down (a
timeout, a connection that still fails) opens that service's breaker for 5 minutes
(`<BRAIN_HOME>/net/breakers.json`): until then its calls are skipped at once and the command says so in one line
(« gitnexus unavailable since 20:14 (timed out); skipped until 20:19 »), so a service that is down costs one timeout
per window, not one per call. The first call after the window tries again and closes the breaker when it answers.
Any answer from the service (any HTTP status, a non-zero exit, a refused certificate) is passed on as before and
closes the breaker: a busy or rate-limited service never shuts its other calls. A docker job that runs past a long
timeout (a snapshot) and a poll of GitNexus's analyze job never open a breaker; `brain update` reads the tags even
when the cockpit's background check opened it. `BRAIN_NET_BREAKER=off` tries every call for one run (a service just
restarted by hand).

### The outbox

A notification that no channel delivered because one was surely not reached (a refused connection, a DNS miss, an
HTTP 429 or 503, its breaker open) is no longer lost: `brain notify send`, a blocking decision's notification and an
alert's `resolved` message keep it in the sealed local outbox (`<BRAIN_HOME>/outbox/queue.json`, store `outbox`,
sealed) under an idempotency key made of its content, so the same message queued twice is kept once, a later
delivery of it drops the queued copy, and a newer message of the same project and key (its alert reopened) replaces
it. A timeout or a reset is not queued: the message may have arrived, and nothing is sent twice. Every alerts pass
(`brain alerts --notify`, after its own sends) sends what is due again through the project's routes as they are
then, waiting 5 minutes, then twice as long each time (at most 6 h, with full jitter); an entry is given up after 12
tries or 7 days, said in the pass's lines. A pass leaves as they are the entries of projects outside its scope and
every entry while `$BRAIN_NOTIFY` is `off` or `dry-run`; an outbox a newer brain wrote is not replayed. A refusal (a
wrong token, an HTTP 401) is not queued: sending it again would not help. An open alert is not queued either, since
the pass already sends a failed one again, nor the quiet mode's summary, which stays held. `brain notify status` says
how many wait. The outbox's API (`brain.outbox.put`, `drop`, `supersede`, `replay`) takes other kinds of calls as
their callers come (the shareboard, the telemetry reports).

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

### This machine: its identity and its facts

One name for the machine everywhere (`brain.machine`): `$BRAIN_MACHINE`, else the host name, lowercase and
`[a-z0-9-]` (the memory sync, the profile and the schedules read it; the permissions' `machines:` stay host names). It is tied to the OS install
by an anchor, `sha256(install id || OS family)` of `MachineGuid`, `/etc/machine-id` or `IOPlatformUUID` (never the raw
id), kept at first sight in `<BRAIN_HOME>/machine.json`. `brain doctor` prints the identity's state and, while the
owner's `config.json` lacks it, the `hosts` line to add (`"hosts": {"<name>": {"anchor": "..."}}`): a name on another
install (reused), two names on one install (a cloned image), a renamed machine, a copied `BRAIN_HOME` or an unreadable
id is a doubt, said with its question; while it lasts the memory sync exports nothing (the machine's branch), and
imports as before.

Each fact is true, false or unknown: an unknown fact satisfies neither `FACT` nor `not FACT` in a `recommend_when`,
and a requirement unknown counts as missing. `brain doctor` probes ECC memory (WMI on Windows, EDAC on Linux) and a
battery, flattens `ecc`, `battery` and `encrypted` (BRAIN_HOME's volume), and prints each fact's source, the first that
knows it: an infra agent's recent report (`inventory.agent_json`, only when the `infra-node` capability is on: off by
default, `brain profile set --with infra-node`), the local probe, a nodes file another tool keeps (`inventory.nodes_file`:
read at a git ref of a local checkout, never its working copy, through a table of field paths; a version it does not
know is refused loudly), the facts declared in `config.json` `hosts.<name>`, else unknown. `<BRAIN_HOME>/facts.json`
keeps the last ones with their source. A machine's `profile.json` overrides `config.json` `tier.components` key by
key (a switch it does not name keeps the brain's default).

**Modules** (`brain mod`, `brain.mod`): the module face of `brain profile`, on the same files. A module of the
store's registry (`modules.yaml`, or the one `config.json` `modules.store` names) that lists the engine's
`capabilities` turns them on and off together; without such a registry each capability is its own module. The layers,
in order: the base preset, `config.json` `tier.components` (every machine's default, by a PR), `profile.json` (this
machine), both accepting module ids, expanded to their capabilities (a capability named directly wins), then the hard
dependencies pulled. A capability declares `depends_on` (hard: pulled when it is on) and `uses` (soft: a provider it
reads, its `fallback` otherwise) in `tiers.yaml`; a module depends on another by its registry entry's `depends_on` or
through its capabilities'. `brain mod list | show ID | explain ID` read; `brain mod enable ID [--apply]` pulls the hard
dependencies and shows the cost, `brain mod disable ID [--cascade] [--apply]` is refused while a module that is on
needs it (`--cascade` turns those off too); `--apply` writes this machine's `profile.json`, a second apply changes
nothing. `explain` shows the scopes' `capabilities` (require, forbid) as declared: the scope tree reserves the key, its
enforcement comes later. `brain init` writes an empty `modules` key. An auto capability is never switched (its
module shows auto); a capability two modules list follows the first of them a layer names (keys in order).

**The module catalogue** (`brain catalogue`, `brain.catalogue`): `catalogue/v1` ([docs/catalogue.md](docs/catalogue.md))
is the neutral, public format of a catalogue of modules: its bricks, its modules with their hard and soft
dependencies, requirements, estimated cost (RAM, disk, VRAM), fallback and licence, the distributions that ship them
and the presets an installer offers (Lite, Default, Recommended; the personas a private catalogue declares). Any
program may emit it; `brain catalogue emit [--out FILE]` prints the brain's own (`brain mod`'s modules, the engine and
its extras, the three bases) and `brain catalogue validate FILE...` checks any document against the schema
(`schemas/catalogue.schema.json`), with no brain needed.

`config.json` `engine.min` (optional, beside `engine.pin`) is the oldest engine that may write the shared formats:
below it the memory sync exports nothing (it still imports), the DDRs are not written and `brain check` says so; the
machine still reads.

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

### The scope tree

Projects can sit in a tree (`brain.scopes`): Global at the root, the brain itself; containers (a sphere, an
organisation, a unit, a folder) and projects under it, projects inside projects, one parent each. A project's place is
the `parent:` key of its entry in `projects.yaml` (a read-only project and a tenant mount take it too); the containers
are declared once in `scopes.yaml`, beside `config.json` (config.json `scopes` names another file, `$BRAIN_SCOPES`
another path):

```yaml
v: 1
scopes:
  pro:     {type: sphere, title: Professional}
  acme:    {type: company, title: ACME SA, parent: pro, classes: {floor: confidential}}
  finance: {type: unit, title: Finance, parent: acme, also_under: [ops]}   # also_under: a shortcut, display only
```

A container has a `type`, and `title`, `parent` (default global) and `status` (`active` or `archived`); `classes:
{floor}` is read by `brain classes` and `brain vault`. Types are ids with labels (sphere, company, institution,
government, association, unit, office, team, folder, project, tenant); `config.json` `scope_types` renames one
(`{"unit": {"en": "Department"}}`, the id kept), adds one, and may say which `children` a type accepts. `brain check
--all` (and a brain's own root) refuses an unknown parent, a cycle, an id used by a project and a container, an unknown
type or one its parent does not accept, and a class floor under an ancestor's (a guard only tightens); it warns past six
levels. `brain scopes [--scope REF] [--depth N] [--archived] [--lang fr] [--types] [--json]` prints the tree with the
projects under each node, and `brain sync` writes `notes/scopes_graph.md` (generated, never edited). `brain status
--scope REF` shows the projects of a node's subtree, with the totals when it holds several, and so do `brain resume`,
`digest`, `queue`, `tui`, `usage`, `cost`, `audit` and `permissions` (with `--requests`, `permissions --scope` keeps its
older meaning, a level's start): REF is an id, a path of ids (`pro/acme`), `global` (as `--all`), `.` (the project of the folder) or `..` (its parent); `--project` and `--all`
stay. Without `scopes.yaml` and `parent:`, every project sits under Global and nothing changes. An older engine
reads `parent:` and `scope_types` as unknown keys (a note; refused in strict mode, CI) and refuses `parent:` on a
read-only entry or a mount: add them once every machine and the brain repo's CI run the release that knows them.

**The deny list from the tree.** With `config.json` `public.deny_from_tree: true`, `public.deny.repos` gains, after the
hand list, the name of every project whose class floor along its chain is `private` or stricter (a container's
`classes: {floor: private}` covers its whole subtree, sub-projects, read-only projects and mounts included; a
project marked on its own entry, `classes: {floor: private}` in `projects.yaml`, read-only entries and mounts too,
counts as well, and its floor also binds its stores in `brain classes`) and the
names of its repos (`brain audit`'s, and their folders), a repo of `public.repos` left out: a private project placed in
the tree is denied by `brain check --public` and the public guard without a hand edit, and the hand list keeps the
people, users, hosts and paths. `brain scopes --deny` prints the generated terms. With it on, a `scopes.yaml` or a
registry that cannot be read, a tree file named but missing, no tree at all, or an error of the tree's check (an
unknown parent, a floor that is no class) makes the public and secrets guards refuse: the list would miss terms. A
term is a whole word matched without case: a private project or repo named after a common word (`data`) would block
the engine's own text, so rename it, or keep it out of a private subtree. Off by default. An older engine reads the key
as unknown and generates nothing: keep the repos in the hand list until every machine and the brain repo's CI run the
release that knows it.

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

## The Brain as an MCP server

`brain mcp serve` serves the Brain to any MCP client ([`docs/mcp.md`](docs/mcp.md), `brain.mcpserver`): its rules,
procedures and decision log as resources, the procedures as prompts, and tools over the graph (`brain items`, `item
show`, `adr show`, `spec show`, `next`, `check`) and the memory (a note read, a note proposed, which the memory sync
carries by a reviewed PR). Every tool call passes the engine's guards before it runs, strictly, since other clients
run no Claude Code hook (`brain.mcpguards`), and every answer passes the secret scan. It speaks stdio (the client
launches it) or, with `--http`, Streamable HTTP on a loopback address only, each request carrying the machine's token
(`brain ipc token --init` makes it once; it is never printed). `packages/brain/container/` defines its image (a user
that is not root, the port published on 127.0.0.1 only). Nothing runs it on its own: a service or a remote endpoint is
the owner's decision. `brain health ipc` checks every local service the Brain starts: loopback only, the token where
the service can check one (the collector's is opt-in, config.json `ipc.require_token`), no container as root
([`docs/mcp.md`](docs/mcp.md), « The Brain's other local services »).

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
the worktree's `.git` file, no git started). Claude Code starts it only on a likely hit: each of its hooks carries an
`if` condition (a permission rule: `Read(//**/journal.md)`, `Bash(*decisions.md*)`...) naming the files it hints
about, so a Read, Bash or PowerShell call that names none starts no process at all; Grep's path is a folder or a glob,
which a rule cannot match, so a Grep call still starts it. The rules do not overlap, so a call that names one brain file starts it once (one that names two kinds may start it twice: Claude Code runs every matching hook). What gets through still stops in bash builtins when its
JSON names none of those files (the conditions only narrow), the Python path, about 0.4 s, taken only on a hand read
of a brain file. Measured on the owner's machine over a week before the conditions: 4,854 of 4,981 runs stopped at
the bash fast path, each a bash start of about 85 ms on Windows; on a shell call it runs beside `guard.sh`.
Read and Grep had no hook before it, so it is **opt-in**: `brain render --target claude` (`brain sync`) registers it
in the core plugin's `hooks.json` only when the brain's `config.json` says `"hints": {"read": true}`; by default it is
not registered and no call pays its cost (the script ships either way, `brain.render.OPTIONAL_HOOKS`). To turn it on,
set the key, run `brain sync` and restart the sessions; while it is on, `BRAIN_READ_HINT=0` turns it off in a
session.

**The background waiter's hint** (`waithint.sh`, `brain.waithint`, PreToolUse on Bash and PowerShell;
wi-brain-stuck-waiters) never refuses either: a call run in the background whose `until` or `while` loop has no
bound gets one line of hook context: bound it (`timeout 1800 bash -c 'until ...'`), make it exit when its file or
process is gone (`[ -e run.log ] || exit 1`, `kill -0 $pid || exit 1`), and stop the session's background tasks
before deleting their logs or venvs. A bound is a `timeout N` wrapper or a `-Timeout` parameter, a counter (`seq`, a
variable compared), a clock (`$SECONDS`, `date +%s`, a Stopwatch, `Get-Date`), a process check (`kill -0`, `ps -p`,
`pgrep`, `Get-Process`, `Wait-Process`) or a check that the file is still there which leaves the loop (`|| exit`,
`then break`, `{ break }`); a loop whose own condition waits for a file to appear or compares a count read from a log
is no bound, and a `while read` loop is no wait. The word `until` or `while` in a quoted text or a comment can still
draw the line (a hint: it costs one line). In wave 0.3.2 two such loops spun on logs their sessions had deleted, and
the sessions could not be archived (lesson les-brain-unbounded-background-waiter). Claude Code matches a hook's `if` condition against each simple
command of the call, never the loop's keyword, so it starts this hook only when one of them names `sleep`
(`Bash(*sleep*)`, `PowerShell(*leep*)`: what a wait loop's body runs; a busy loop with no sleep is not seen); its bash
then stops at once for a call not run in the background or with no `until` or `while`; a foreground call is bounded
by the tool's own timeout, a Monitor by its own. Always registered;
`BRAIN_WAIT_HINT=0` turns it off. The brief's after-merge lines and close-item's step 5 say the same: no background
task left at the cleanup or the archive.

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
`BRAIN_CAPTURE=0` turns it off). Every append-only ledger (the exec ledger, the capture ledgers `ar`, `ddr` and
`events`, the guards, queue, answers and cockpit ledgers, the quota readings, the session starts in `usage/`, the
notify audit and its held messages) is appended in one write
under its folder's lock (`exec.lock`, `brain.timing.append_text`), so that sessions writing at once neither lose nor mix
a line. The session snapshots, states, reports and plans under `<BRAIN_HOME>/sessions` and the
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
shell (a command at the start of a part of the line; a quoted text or a heredoc runs none) and the others (a hook, a
scheduled task, a script: the ledger's runs less the sessions', never below zero, so when the transcripts go further
back than the ledger a command may show runs by a session only); the commands that never ran; the Read, Grep and
shell reads of a registered brain's graph YAML, decision logs, journals and generated views that a read command
answers; the hand edits of the files a command writes or regenerates; a feature marked have whose command modules
never ran; the sub-sessions started against the runs of `brain brief`, `brain collisions` and `brain wave plan`. Each
gap comes with what to propose, of three kinds: hint (the read hint), procedure (a procedure line), wire (a hook, a
schedule or a procedure, documented, or retired); nothing is refused. A command whose module declares how it is
reached without the CLI (`RUNS_VIA`, « Adding a command »: wired by a hook, another command or a schedule, or run on
demand) is listed apart with that line, not as a gap, and does not make its feature unused; close-item's step 2b
runs `brain cost review --record`, so that command shows as a gap again if the procedure stops running it. Run it
after each wave. It
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
each copy checked by sha256, and `brain health spool` gives the last push's age. The session archive (opt-in,
`session_archive.enabled`) puts the agents' quiet transcripts into the spool: each row a residency filter of the
owner's matches dropped, scanned by the engine's patterns then gitleaks (absent or failing: nothing archived), sealed
and indexed by session record (`brain session-archive run [--dry-run]`).

```
brain classes [--check] [--suggest] [--matrix] [PATH...]
brain vault status | seal STORE | canary | recipient add NAME [--replace] | recipient remove NAME | reseal [--apply]
brain vault device init [--rotate] | device forget-previous | open FILE | drill RECIPIENT
brain health vault
brain spool push [STORE...] [--dry-run] | status | verify
brain health spool
brain session-archive run [--dry-run] [--max N] | status
brain health session-archive
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
- Every command runs under `brain.shutdown.graceful()`: SIGINT (Ctrl+C), SIGTERM, SIGHUP and SIGBREAK (Ctrl+Break
  on Windows) stop it with `Stopped` (a `KeyboardInterrupt`), so its `finally` and `with` blocks run and its locks
  are released; one that arrives inside `brain.shutdown.critical()` (each ledger line, each atomic state write)
  waits for the write to end, and one that arrives while the write fails still stops it. stderr names the signal;
  then, on POSIX, the command dies by the signal itself, so a shell sees 128 + its number (130 for Ctrl+C, 143 for
  SIGTERM) and stops a loop on it; on Windows it exits 128 + the number (149 for Ctrl+Break). `main([...])` called
  from Python returns that code instead. `brain timed` passes a signal sent to brain alone to its command (POSIX),
  and the text cockpit quits with 0 on Ctrl+C. A long command's own write that must not be cut goes in `critical()`, or through
  `stateio.write_atomic`; `taskkill /F` and SIGKILL cannot be trapped.
- `NO_PROJECT = {"hello"}`: no `--project` is added after its subcommand (the hooks', machine-wide commands).
- `RUNS_VIA = {"hello wave": "wired: the session-start hook runs brain.hello"}`: a subcommand that may never run
  from the CLI and is no gap, with how it is reached: `wired: ...` (a hook, another command or a schedule runs its
  code) or `on demand: ...` (run by hand when its occasion comes, an owner's gesture); `brain perf --usage` lists it
  apart. A test checks each entry names a real subcommand and says one of the two.
- What several commands share is in `_common.py` (the text options, the project, its store and scope) and
  `_stores.py` (the passes of sync, check and refresh); a module whose name starts with `_` is not a command.
- `brain audit` flags a parser added in `cli.py` and a module of `commands/` without `register` (the check
  `cmd.registry`). `tests/test_cli_registry.py` checks every module's contract; `python tests/help_dump.py` prints
  every command's and subcommand's help and arguments: run it before and after a change of the parsers, and diff.

### A project's command plugin

A project brings its own subcommands through a plugin, named under its `plugin` key in `projects.yaml`, and `brain
<project> <subcommand> ...` runs them (`brain.plugins`): one command for every project. The value is an entry point
of the group `brain.plugins`, which the project's installed package declares, or `module:attr` directly (`module:`
names the module itself):

```toml
[project.entry-points."brain.plugins"]
demo = "demo_cli.brain:plugin"
```

```yaml
demo: {root: ../demo, title: The demo platform, plugin: demo}
```

The object is either a command module, with the contract above (`register(sub, ctx)` and `run(args, root)`, given
`args.project` and the project's root, its worktree when run from one), or a callable `main(argv)` given the words
after the project's name: a project's own CLI plugs in unchanged, so its console script stays a shortcut
(`demo cron list` is `brain demo cron list`). `brain --help` lists the plugged projects without importing them,
`brain demo --help` a command module's subcommands (a main gets `--help` itself); brain's own options (`--root`,
`--store`) go before the project's name. Each run is timed in the exec ledger as `brain demo <subcommand>`; a main
that returns a string fails with it as its message (`sys.exit(main())`'s convention). A registry without the key, or
with `plugin: null`, behaves as before, and a plugin that cannot load fails its own run only (exit 2). `brain check
--all` reports a value that is not a string and a project named like one of brain's commands, whose plugin never runs
(the command wins).
`brain status --project demo` and `brain status --all` show the project as any other.

The plugin also brings its cockpit panels and tabs, as data (`brain.plugin_panels`): a `COCKPIT` mapping beside the
object it names (or in its module; a callable that returns it works too). Each panel names where its rows come from
(`rows`: a JSON file under the project's root, a list of objects or `{"rows": [...]}`; or `read`: a `module:attr`
callable given the project's root), its columns, its sorts (the first the default), its filters, the field that
names a row and its help:

```python
COCKPIT = {"v": 1, "panels": {"runs": {
    "title": {"en": "Runs", "fr": "Exécutions"}, "rows": "out/runs.json",
    "columns": [{"key": "id", "title": "Id"}, {"key": "state", "title": "State"}, {"key": "score", "title": "Score"}],
    "sorts": ["score", "state"], "filters": {"state": ["all", "ok", "failed"]}, "help": "The last runs."}}}
```

`brain tui` reads the registry's plugins at its start and draws each panel (`demo-runs`) as one of its own tables: the
project selector, the search, the sorts and filters (`s`, `o`, `f`, `--sort demo-runs:state`), the saved views, the
column chooser, the palette, a row's detail and `--once` work on it. Its tab, `demo` (or one per entry of `tabs`), comes
after Resources with no number: a click, the palette or `ctrl+pagedown` reaches it, and `--tab demo` starts there. Its
rows are read at the cockpit's first read (until one passes) and at each probe (`r` reads them again); a file or a
read that fails keeps its last rows and shows the error, and is read again at the next probe. A name another project's
plugin has already, or one of the cockpit's own tabs, is noted and left out. Nothing of it is Textual code. A key this engine does not know is kept and noted, a
plugin that cannot be loaded is noted (a notification, or stderr with `--once`), and the other panels go on.

## Tests

From a checkout of this repo, with research-graph from the same checkout:

```bash
pip install -e . && pip install --no-deps -e packages/brain && pip install pyyaml pytest "pytest-xdist>=3.5"
pytest packages/brain -n auto
```

The tests run as an invented owner, Ada (`tests/fixtures/brain/config.json`, set for every test by `conftest.py`
through `BRAIN_CONFIG`), with a temporary `BRAIN_HOME`; they need git, and bash for the hooks (Git Bash on Windows).
They read only fixtures, never a real brain's graph, records or rendered files: what checks a brain's own data is
`brain check` and `brain audit`.

`-n auto` runs them in parallel, one pytest-xdist worker per CPU thread: each test has its own temporary folder,
`BRAIN_HOME` and environment, so no test shares state with another. With `-n` and no `--dist`, `conftest.py` picks
xdist's `worksteal` scheduling (pytest-xdist 3.5 or later): a worker that runs out of tests takes some still queued on a
busy one, so the run no longer ends on one or two workers while the others idle; `--dist load` gives the old scheduling
back. A git repository in a test is a copy of a template made once per worker (`conftest.git_init`, the `git_repo` and
`make_repo` fixtures), not a `git init`. The test that calls the real docker client is marked `docker`: the CI runs it
apart, on one process (`pytest packages/brain -m docker`).

`BRAIN_TEST_WORKERS=N` sets how many workers `-n auto` (or `-n logical`) starts. Unset, xdist decides: its own
`PYTEST_XDIST_AUTO_NUM_WORKERS` if set, else one worker per CPU thread (per physical core when psutil is installed).
`BRAIN_TEST_WORKERS` wins over `PYTEST_XDIST_AUTO_NUM_WORKERS` and, unlike it, refuses anything but a whole number
with `-n auto`; an explicit `-n N` wins over both. More workers than CPU threads rarely help: on Windows the suite is
bound by process creation (it starts some ten thousand git processes, and an on-access antivirus scans each one),
not by the CPU. On a 16-thread machine, 24 and 32 workers ran no faster than 16, and on one run 24 workers starting
together timed out a worker's start.

`BRAIN_TEST_ROOT=<folder>` (made absolute; outside the checkout) moves the bulk of the suite's temporary files under
one folder: pytest's temporary folders, where the tests write their repos, brains and homes, under `<folder>/tmp`
(pytest keeps its numbering and its last three runs there; an explicit `--basetemp` wins), and the venvs the harness
tests build under `<folder>/venvs`. Unset, they go to the system's temp folder as before. The few scratch files the
engine itself, git and pip make still go to the system's temp folder. A short folder outside the user profile
(`C:\brain-tests` on Windows, say) keeps pip's paths in those venvs under Windows' length limit, and is one place to
exclude from an on-access antivirus scan: the tests write and delete tens of thousands of small files, and a scan of
each one slows the suite (about 10 % measured with pytest's temporary folders excluded). The engine never changes the
antivirus: the owner adds that exclusion by hand, if wanted, and the processes the tests start (git, bash, python) are
still scanned.

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
